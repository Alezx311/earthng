//! Experimental batch of the road-strip normal and distance calculation from
//! generator.lua. Input points must already be cleaned, trimmed and densified.
//! This is not road mesh generation or a live tile integration.
use std::sync::atomic::{AtomicUsize, Ordering};

const EPS: f64 = 1e-8;
const MAX_ROADS: usize = 20000;
const MAX_POINTS: usize = 300000;
type Joint = Option<[f64; 3]>;
#[derive(Clone)]
struct Road { points: Vec<[f64; 2]>, mitre: f64, joints: [Joint; 2] }
fn u32at(data:&[u8], p:usize)->u32 { u32::from_le_bytes(data[p..p+4].try_into().unwrap()) }
fn f64at(data:&[u8], p:usize)->f64 { f64::from_le_bytes(data[p..p+8].try_into().unwrap()) }

fn solve(road:&Road)->Vec<[f64;3]> {
    let mut result=Vec::with_capacity(road.points.len());
    let mut dist=0.;
    for (i,p) in road.points.iter().enumerate() {
        let (mut tx,mut ty)=(0.,0.);
        if i>0 {
            let prev=road.points[i-1]; let (dx,dy)=(p[0]-prev[0],p[1]-prev[1]);
            let l=(dx*dx+dy*dy).sqrt(); tx+=dx/l;ty+=dy/l;dist+=l;
        }
        if i+1<road.points.len() {
            let next=road.points[i+1];let (dx,dy)=(next[0]-p[0],next[1]-p[1]);
            let l=(dx*dx+dy*dy).sqrt();tx+=dx/l;ty+=dy/l;
        }
        let l=(tx*tx+ty*ty).sqrt().max(EPS);
        let ends=if i==0 || i+1==road.points.len() {1.} else {2.};
        let mitre=(ends/l).min(road.mitre);
        let (mut nx,mut ny)=(-ty/l*mitre,tx/l*mitre);
        if i==0 {if let Some(j)=road.joints[0] {(nx,ny)=(-j[1]*j[2],j[0]*j[2]);}}
        if i+1==road.points.len() {if let Some(j)=road.joints[1] {(nx,ny)=(-j[1]*j[2],j[0]*j[2]);}}
        result.push([nx,ny,dist]);
    }
    result
}

pub fn batch(data:&[u8])->Result<Vec<u8>, &'static str> {
    if data.len()<12 || &data[..4]!=b"ERD1" {return Err("road header");}
    let workers=u32at(data,4) as usize; let count=u32at(data,8) as usize;
    if workers==0 || workers>32 || count>MAX_ROADS {return Err("road limit");}
    let (mut pos,mut total)=(12usize,0usize); let mut roads=Vec::with_capacity(count);
    for _ in 0..count {
        if data.len()-pos<64 {return Err("road metadata");}
        let n=u32at(data,pos) as usize; let flags=u32at(data,pos+4); let mitre=f64at(data,pos+8);
        if flags>3 || !mitre.is_finite() || mitre<0. {return Err("road metadata");}
        let mut joints=[None,None];
        for k in 0..2 {if flags & (1<<k)!=0 {
            let p=pos+16+k*24; let j=[f64at(data,p),f64at(data,p+8),f64at(data,p+16)];
            if j.iter().any(|v|!v.is_finite()) {return Err("road joint");} joints[k]=Some(j);
        }}
        pos+=64; total=total.checked_add(n).ok_or("road size")?;
        if total>MAX_POINTS || n>(data.len()-pos)/16 || n<2 {return Err("road points");}
        let mut points=Vec::with_capacity(n);
        for _ in 0..n {
            let p=[f64at(data,pos),f64at(data,pos+8)]; pos+=16;
            if p.iter().any(|v|!v.is_finite()) {return Err("road coordinate");}
            if let Some(last)=points.last() {let q:&[f64;2]=last;
                let dx=p[0]-q[0];let dy=p[1]-q[1];let d2=dx*dx+dy*dy;
                if !d2.is_finite() || d2==0. {return Err("invalid segment");}
            }
            points.push(p);
        }
        roads.push(Road{points,mitre,joints});
    }
    if pos!=data.len(){return Err("road trailing data");}
    let next=AtomicUsize::new(0); let mut result=vec![Vec::new();count];
    if count>0 {std::thread::scope(|scope| {
        let mut handles=Vec::new();
        for _ in 0..workers.min(count) {let roads=&roads;let next=&next; handles.push(scope.spawn(move || {
            let mut out=Vec::new(); loop {let i=next.fetch_add(1,Ordering::Relaxed);
                if i>=roads.len(){break;} out.push((i,solve(&roads[i])));
            } out
        }));}
        for h in handles {for (i,values) in h.join().expect("road worker panicked") {result[i]=values;}}
    });}
    let mut out=b"ERR1".to_vec();out.extend_from_slice(&(count as u32).to_le_bytes());
    for values in result {out.extend_from_slice(&(values.len() as u32).to_le_bytes());
        for p in values {for v in p {out.extend_from_slice(&v.to_le_bytes());}}
    }
    Ok(out)
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn bend_and_joint() {
        let road=Road{points:vec![[0.,0.],[10.,0.],[10.,10.]],mitre:2.,joints:[Some([0.,1.,1.5]),None]};
        let got=solve(&road); assert_eq!(got[0],[-1.5,0.,0.]);
        assert!((got[1][0]+1.).abs()<1e-12 && (got[1][1]-1.).abs()<1e-12);
        assert_eq!(got[1][2],10.); assert_eq!(got[2],[-1.,0.,20.]);
    }
    #[test] fn malformed_input_is_rejected(){assert!(batch(b"ERD1").is_err());}
}
