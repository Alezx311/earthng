//! Experimental batch implementation of routing.lua's nearest-node scan.
//! Wire format is deliberately private to the benchmark; it is not a release API.
use std::{ffi::OsString, io::{Read, Write}, net::TcpListener, os::windows::ffi::OsStringExt, path::{Path, PathBuf}, time::{Duration, Instant}};
mod route;
mod roofs;
mod tile_batch;
mod road_geometry;
mod wall_geometry;

const MAX_NODES: usize = 4_000_000;
const MAX_QUERIES: usize = 4096;
fn u32at(b: &[u8], p: usize) -> Result<u32, &'static str> {
    Ok(u32::from_le_bytes(b.get(p..p + 4).ok_or("truncated")?.try_into().unwrap()))
}
fn f64at(b: &[u8], p: usize) -> f64 { f64::from_le_bytes(b[p..p + 8].try_into().unwrap()) }

fn batch(b: &[u8]) -> Result<Vec<u8>, &'static str> {
    if b.get(..4) != Some(b"ENB1") || b.len() < 16 { return Err("header"); }
    let n = u32at(b, 4)? as usize;
    let q = u32at(b, 8)? as usize;
    let workers = u32at(b, 12)? as usize;
    if n > MAX_NODES || q > MAX_QUERIES || workers == 0 || workers > 32 { return Err("limits"); }
    let expected = 16usize.checked_add(n.checked_mul(20).ok_or("size")?).and_then(|s| s.checked_add(q * 16)).ok_or("size")?;
    if expected != b.len() { return Err("length"); }
    solve(n, &b[16..16+n*20], &b[16+n*20..], workers)
}

fn solve(n: usize, graph: &[u8], queries: &[u8], workers: usize) -> Result<Vec<u8>, &'static str> {
    if n > MAX_NODES || graph.len() != n * 20 || queries.len() % 16 != 0 || queries.len()/16 > MAX_QUERIES || workers == 0 || workers > 32 { return Err("limits"); }
    let q = queries.len()/16;
    let ox = 0;
    let oy = 8 * n;
    let ou = 16 * n;
    let start = Instant::now();
    let mut results = vec![(u32::MAX, f64::INFINITY); q];
    if q != 0 {
        let chunk_size = q.div_ceil(workers.min(q));
        std::thread::scope(|scope| {
            for (chunk_index, chunk) in results.chunks_mut(chunk_size).enumerate() {
                scope.spawn(move || {
                    for (i, out) in chunk.iter_mut().enumerate() {
                        let pos = (chunk_index * chunk_size + i) * 16;
                        let x = f64at(queries, pos);
                        let y = f64at(queries, pos + 8);
                        let mut best = f64::INFINITY;
                        let mut at = u32::MAX;
                        for k in 0..n {
                            if u32at(graph, ou + 4 * k).unwrap() == 0 { continue; }
                            let dx = f64at(graph, ox + 8 * k) - x;
                            let dy = f64at(graph, oy + 8 * k) - y;
                            let d = dx * dx + dy * dy;
                            if d < best { best = d; at = k as u32; }
                        }
                        *out = (at, best.sqrt());
                    }
                });
            }
        });
    }
    let mut out = Vec::with_capacity(16 + q * 12);
    out.extend_from_slice(b"ENR1");
    out.extend_from_slice(&(q as u32).to_le_bytes());
    out.extend_from_slice(&(start.elapsed().as_micros() as u64).to_le_bytes());
    for (i, d) in results { out.extend_from_slice(&i.to_le_bytes()); out.extend_from_slice(&d.to_le_bytes()); }
    Ok(out)
}

// Both transports use the same cached graph representation and solver.
#[derive(Default)]
struct Cache { nearest: Option<(usize, Vec<u8>)>, route: Option<route::Graph> }
fn handle(data: &[u8], cache: &mut Cache) -> Result<Vec<u8>, &'static str> {
    match data.get(..4) {
        Some(b"ENG1") => {
            let n = u32at(data, 4)? as usize;
            if n > MAX_NODES || data.len() != 8 + n * 20 { return Err("graph length"); }
            cache.nearest = Some((n, data[8..].to_vec()));
            Ok(b"EOK1".to_vec())
        }
        Some(b"ENQ1") => {
            let workers = u32at(data, 4)? as usize;
            let (n, graph) = cache.nearest.as_ref().ok_or("graph missing")?;
            solve(*n, graph, data.get(8..).ok_or("query")?, workers)
        }
        Some(b"ERG1") => { cache.route=Some(route::Graph::decode(data)?); Ok(b"EOK1".to_vec()) }
        Some(b"ERQ1") => cache.route.as_ref().ok_or("route graph missing")?.batch(data),
        Some(b"ETG1") | Some(b"EFG1") => roofs::batch(data),
        Some(b"ETB1") => tile_batch::handle(data),
        Some(b"ERD1") => road_geometry::batch(data),
        Some(b"EWP1") => wall_geometry::batch(data),
        Some(b"ENB1") => batch(data),
        _ => Err("command"),
    }
}

fn worker(dir: &Path) {
    let mut cache = Cache::default();
    loop {
        if dir.join("bench-stop").exists() { break; }
        let ready = dir.join("bench-request.ready");
        if ready.exists() {
            let result = std::fs::read(dir.join("bench-request.bin"))
                .map_err(|_| "read").and_then(|b| handle(&b, &mut cache));
            let _ = std::fs::remove_file(&ready);
            let (file, data) = match result { Ok(b) => ("bench-response.bin", b), Err(e) => ("bench-error.txt", e.as_bytes().to_vec()) };
            if std::fs::write(dir.join(file), data).is_ok() { let _ = std::fs::write(dir.join("bench-response.ready"), b"1"); }
        }
        std::thread::sleep(Duration::from_millis(2));
    }
}

fn socket_worker(dir: &Path) -> std::io::Result<()> {
    // Test-only endpoint: one local connection, bounded frames and finite timeout.
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    listener.set_nonblocking(true)?;
    std::fs::write(dir.join("bench-port.txt"), listener.local_addr()?.port().to_string())?;
    loop {
        if dir.join("bench-stop").exists() { return Ok(()); }
        let mut stream = match listener.accept() {
            Ok((s, peer)) => { let _ = std::fs::write(dir.join("bench-socket-trace.txt"), format!("accepted {peer}\n")); s },
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => { std::thread::sleep(Duration::from_millis(2)); continue; },
            Err(e) => return Err(e),
        };
        stream.set_nonblocking(false)?;
        stream.set_read_timeout(Some(Duration::from_secs(5)))?;
        stream.set_write_timeout(Some(Duration::from_secs(5)))?;
        stream.set_nodelay(true)?;
        let mut cache = Cache::default();
        loop {
            let mut header = [0u8; 4];
            if stream.read_exact(&mut header).is_err() { break; }
            let n = u32::from_le_bytes(header) as usize;
            if n > 256 * 1024 * 1024 || n < 4 { break; }
            let mut data = vec![0; n];
            if stream.read_exact(&mut data).is_err() { break; }
            let one_shot_tile = data.get(..4) == Some(b"ETB1");
            let reply = handle(&data, &mut cache).unwrap_or_else(|e| format!("ERR:{e}").into_bytes());
            if stream.write_all(&(reply.len() as u32).to_le_bytes()).is_err()
                || stream.write_all(&reply).is_err() { break; }
            if one_shot_tile { break; }
        }
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "system" fn earthng_probe(argument: *const u16) -> u32 {
    if argument.is_null() { return 1; }
    let mut len = 0;
    while len < 32767 && unsafe { *argument.add(len) } != 0 { len += 1; }
    if len == 32767 { return 2; }
    let path = PathBuf::from(OsString::from_wide(unsafe { std::slice::from_raw_parts(argument, len) }));
    let Some(dir) = path.parent().map(Path::to_path_buf) else { return 3; };
    if std::fs::write(path, format!("nearest-bench-v1\npid={}\n", std::process::id())).is_err() { return 3; }
    let socket_dir = dir.clone();
    if std::thread::Builder::new().name("earthng-nearest-socket".into()).spawn(move || {
        if let Err(e) = socket_worker(&socket_dir) { let _ = std::fs::write(socket_dir.join("bench-socket-error.txt"), e.to_string()); }
    }).is_err() { return 4; }
    if std::thread::Builder::new().name("earthng-nearest-bench".into()).spawn(move || worker(&dir)).is_err() { return 4; }
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn compares_ties_excluded_nodes_and_parallel_results() {
        let mut b = b"ENB1".to_vec();
        for v in [3u32, 2, 2] { b.extend_from_slice(&v.to_le_bytes()); }
        for v in [0f64, 2., 1., 0., 0., 0.] { b.extend_from_slice(&v.to_le_bytes()); }
        for v in [1u32, 1, 0] { b.extend_from_slice(&v.to_le_bytes()); }
        for v in [1f64, 0., 2., 0.] { b.extend_from_slice(&v.to_le_bytes()); }
        let out = batch(&b).unwrap();
        assert_eq!(u32at(&out, 16).unwrap(), 0); // tie: first node wins
        assert_eq!(f64at(&out, 20), 1.);
        assert_eq!(u32at(&out, 28).unwrap(), 1);
        assert_eq!(f64at(&out, 32), 0.);
        assert!(batch(&b[..b.len()-1]).is_err());
    }
    #[test]
    fn empty_graph_reports_no_node() {
        let mut b = b"ENB1".to_vec();
        for v in [0u32, 1, 1] { b.extend_from_slice(&v.to_le_bytes()); }
        b.extend_from_slice(&[0; 16]);
        let out = batch(&b).unwrap();
        assert_eq!(u32at(&out, 16).unwrap(), u32::MAX);
        assert!(f64at(&out, 20).is_infinite());
    }
    #[test]
    fn cached_protocol_checks_lengths_and_matches_full_batch() {
        let mut cache = Cache::default();
        assert!(handle(b"ENQ1\x01\0\0\0", &mut cache).is_err());
        let mut graph = b"ENG1".to_vec();
        graph.extend_from_slice(&1u32.to_le_bytes());
        graph.extend_from_slice(&2f64.to_le_bytes());
        graph.extend_from_slice(&3f64.to_le_bytes());
        graph.extend_from_slice(&1u32.to_le_bytes());
        assert_eq!(handle(&graph, &mut cache).unwrap(), b"EOK1");
        let mut query = b"ENQ1".to_vec();
        query.extend_from_slice(&1u32.to_le_bytes());
        query.extend_from_slice(&5f64.to_le_bytes());
        query.extend_from_slice(&7f64.to_le_bytes());
        let out = handle(&query, &mut cache).unwrap();
        assert_eq!(u32at(&out,16).unwrap(), 0);
        assert_eq!(f64at(&out,20), 5.);
        assert!(handle(&query[..query.len()-1], &mut cache).is_err());
        assert!(handle(&graph[..graph.len()-1], &mut cache).is_err());
    }
}
