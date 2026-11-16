//! Test-only envelope for a tile's asynchronous roof job.
//!
//! ETB1 | job:u64 | epoch:u64 | lod:u32 | bytes:u32 | task payload
//! ETC1 | job:u64 | epoch:u64 | lod:u32 | bytes:u32 | result payload
//! The identity is echoed so the caller can reject replies from an old tile
//! generation. The envelope does not itself implement a queue or cancellation.

const HEADER: usize = 28;
const MAX_PAYLOAD: usize = 8 * 1024 * 1024;
const MAX_REPLY: usize = 16 * 1024 * 1024;

pub fn handle(data: &[u8]) -> Result<Vec<u8>, &'static str> {
    if data.len() < HEADER || &data[..4] != b"ETB1" {return Err("tile header");}
    let lod=u32::from_le_bytes(data[20..24].try_into().unwrap());
    let size=u32::from_le_bytes(data[24..28].try_into().unwrap()) as usize;
    if size > MAX_PAYLOAD || data.len() != HEADER + size {return Err("tile length");}
    let body=&data[HEADER..];
    let result=match (lod, body.get(..4)) {
        (0, Some(b"ETG1")) | (1, Some(b"EFG1")) => super::roofs::batch(body)?,
        (0 | 1, Some(b"ERD1")) => super::road_geometry::batch(body)?,
        (0, Some(b"EWP1")) => super::wall_geometry::batch(body)?,
        _ => return Err("tile lod"),
    };
    if result.len() > MAX_REPLY {return Err("tile result length");}
    let mut out=Vec::with_capacity(HEADER+result.len());
    out.extend_from_slice(b"ETC1");
    out.extend_from_slice(&data[4..24]);
    out.extend_from_slice(&(result.len() as u32).to_le_bytes());
    out.extend_from_slice(&result);
    Ok(out)
}

#[cfg(test)] mod tests {
    use super::*;
    fn request(lod:u32, magic:&[u8;4])->Vec<u8> {
        let mut body=magic.to_vec();
        for v in [2u32,0] {body.extend_from_slice(&v.to_le_bytes());}
        for v in [0f64,0.,500.,500.] {body.extend_from_slice(&v.to_le_bytes());}
        let mut request=b"ETB1".to_vec();
        request.extend_from_slice(&57u64.to_le_bytes());
        request.extend_from_slice(&12u64.to_le_bytes());
        request.extend_from_slice(&lod.to_le_bytes());
        request.extend_from_slice(&(body.len() as u32).to_le_bytes());
        request.extend_from_slice(&body); request
    }
    #[test] fn preserves_identity_and_lod_for_empty_tile() {
        for (lod, magic) in [(0,b"ETG1"),(1,b"EFG1")] {
            let req=request(lod,magic); let response=handle(&req).unwrap();
            assert_eq!(&response[..4],b"ETC1");
            assert_eq!(&response[4..24],&req[4..24]);
            assert_eq!(&response[28..32],b"ETR1");
        }
    }
    #[test] fn rejects_inconsistent_or_truncated_requests() {
        let req=request(0,b"EFG1"); assert_eq!(handle(&req),Err("tile lod"));
        let req=request(1,b"EFG1"); assert_eq!(handle(&req[..req.len()-1]),Err("tile length"));
        let mut req=req; req[24..28].copy_from_slice(&u32::MAX.to_le_bytes());
        assert_eq!(handle(&req),Err("tile length"));
    }
    #[test] fn accepts_road_and_wall_tasks_with_tile_identity() {
        for (lod,magic,want) in [(0,b"ERD1",b"ERR1"),(1,b"ERD1",b"ERR1"),(0,b"EWP1",b"EWR1")] {
            let mut body=magic.to_vec();body.extend_from_slice(&1u32.to_le_bytes());body.extend_from_slice(&0u32.to_le_bytes());
            let mut req=request(lod,b"ETG1");req.truncate(28);
            req[24..28].copy_from_slice(&(body.len() as u32).to_le_bytes());req.extend_from_slice(&body);
            let result=handle(&req).unwrap();assert_eq!(&result[28..32],want);assert_eq!(&result[4..24],&req[4..24]);
        }
    }
}
