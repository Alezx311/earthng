//! Experimental batch of BLD.pieces. Hidden runs must already be computed by Lua;
//! facade materials, windows, roofs, clipping and engine meshes are not here.
use std::sync::atomic::{AtomicUsize, Ordering};
const MAX_WALLS:usize=50000;
const MAX_RUNS:usize=300000;
#[derive(Clone,Copy,Debug)] struct Point {x:f64,y:f64,z:f64,has_z:bool}
#[derive(Clone,Copy)] struct Run {start:f64,end:f64,hidden:f64}
struct Wall {a:Point,b:Point,length:f64,runs:Option<Vec<Run>>}
#[derive(Clone,Copy)] struct Piece {a:Point,b:Point,length:f64,start:f64,hidden:Option<f64>}
fn read_u32(b:&[u8],p:usize)->u32 {u32::from_le_bytes(b[p..p+4].try_into().unwrap())}
fn read_f64(b:&[u8],p:usize)->f64 {f64::from_le_bytes(b[p..p+8].try_into().unwrap())}
fn point(w:&Wall,s:f64)->Point {Point{x:w.a.x+(w.b.x-w.a.x)*s/w.length,
    y:w.a.y+(w.b.y-w.a.y)*s/w.length,z:0.,has_z:false}}
fn solve(w:&Wall)->Vec<Piece> {
    let Some(runs)=&w.runs else {return vec![Piece{a:w.a,b:w.b,length:w.length,start:0.,hidden:None}];};
    let mut out:Vec<Piece>=Vec::new();let mut at:f64=0.;
    let add=|out:&mut Vec<Piece>,s0:f64,s1:f64,z:Option<f64>| {
        if z.is_none() && s1-s0<0.4 {
            if let Some(last)=out.last_mut() {if last.hidden.is_some() {
                last.b=point(w,s1);last.length=s1-last.start;return;
            }}
        }
        if s1-s0>1e-3 {out.push(Piece{a:point(w,s0),b:point(w,s1),length:s1-s0,start:s0,hidden:z});}
    };
    for r in runs {if r.start>at {add(&mut out,at,r.start,None);}
        add(&mut out,at.max(r.start),r.end,Some(r.hidden));at=at.max(r.end);}
    if at<w.length {add(&mut out,at,w.length,None);}
    if let Some(first)=out.first_mut(){first.a=w.a;}
    if let Some(last)=out.last_mut(){last.b=w.b;}
    out
}
pub fn batch(data:&[u8])->Result<Vec<u8>, &'static str> {
    if data.len()<12 || &data[..4]!=b"EWP1" {return Err("wall header");}
    let workers=read_u32(data,4) as usize;let n=read_u32(data,8) as usize;
    if workers==0 || workers>32 || n>MAX_WALLS{return Err("wall limit");}
    let (mut pos,mut total)=(12usize,0usize);let mut walls=Vec::with_capacity(n);
    for _ in 0..n {
        if data.len()-pos<64{return Err("wall metadata");}
        let flags=read_u32(data,pos);let count=read_u32(data,pos+4) as usize;
        if flags>7{return Err("wall flags");}
        let mut v=[0.;7];for k in 0..7 {v[k]=read_f64(data,pos+8+k*8);}
        if v.iter().any(|x|!x.is_finite()) || v[6]<=1e-3 {return Err("wall coordinate");}
        pos+=64;total=total.checked_add(count).ok_or("wall size")?;
        if total>MAX_RUNS || count>(data.len()-pos)/24{return Err("wall runs");}
        if flags&4==0 && count!=0{return Err("wall runs flag");}
        let mut runs=Vec::with_capacity(count);let mut prev=0.;
        for _ in 0..count {let r=Run{start:read_f64(data,pos),end:read_f64(data,pos+8),hidden:read_f64(data,pos+16)};pos+=24;
            if !r.start.is_finite() || !r.end.is_finite() || !r.hidden.is_finite() || r.start<prev || r.end<=r.start || r.end>v[6]+1e-6 {return Err("wall run");}
            prev=r.end;runs.push(r);
        }
        walls.push(Wall{a:Point{x:v[0],y:v[1],z:v[2],has_z:flags&1!=0},
            b:Point{x:v[3],y:v[4],z:v[5],has_z:flags&2!=0},length:v[6],runs:if flags&4!=0 {Some(runs)}else{None}});
    }
    if pos!=data.len(){return Err("wall trailing data");}
    let next=AtomicUsize::new(0);let mut results=vec![Vec::new();n];
    if n>0 {std::thread::scope(|s|{let mut hs=Vec::new();for _ in 0..workers.min(n){let walls=&walls;let next=&next;
        hs.push(s.spawn(move||{let mut r=Vec::new();loop {let i=next.fetch_add(1,Ordering::Relaxed);if i>=walls.len(){break;}r.push((i,solve(&walls[i])));}r}));}
        for h in hs {for (i,r) in h.join().expect("wall worker panicked"){results[i]=r;}}
    });}
    let mut out=b"EWR1".to_vec();out.extend_from_slice(&(n as u32).to_le_bytes());
    for pieces in results {out.extend_from_slice(&(pieces.len() as u32).to_le_bytes());for p in pieces {
        let flags=(p.a.has_z as u32)|((p.b.has_z as u32)<<1)|((p.hidden.is_some() as u32)<<2);
        out.extend_from_slice(&flags.to_le_bytes());
        for v in [p.a.x,p.a.y,p.a.z,p.b.x,p.b.y,p.b.z,p.length,p.start,p.hidden.unwrap_or(0.)] {out.extend_from_slice(&v.to_le_bytes());}
    }}
    Ok(out)
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn short_gap_merges_into_hidden_run() {
        let p=|x|Point{x,y:0.,z:2.,has_z:true};
        let w=Wall{a:p(0.),b:p(10.),length:10.,runs:Some(vec![Run{start:1.,end:3.,hidden:5.},Run{start:3.2,end:7.,hidden:7.}])};
        let r=solve(&w);assert_eq!(r.len(),4);assert!((r[1].length-2.2).abs()<1e-12);
        assert_eq!(r[0].a.z,2.);assert!(r[0].a.has_z);assert!(!r[0].b.has_z);assert!(r.last().unwrap().b.has_z);
    }
    #[test] fn rejects_short_header(){assert!(batch(b"EWP1").is_err());}
}
