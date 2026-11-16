//! Batched flat-roof footprint triangulation. Experimental benchmark, not game integration.
//! Implements generator.lua prepareRings/triangulate for 3D vertices and a clipping rectangle.
use std::{sync::atomic::{AtomicUsize,Ordering},time::Instant};
const EPS:f64=1e-8;
type Point=[f64;3];
#[derive(Clone,Copy)] struct Edge { a:Point,b:Point,lo:f64,hi:f64,index:usize }
fn f64at(b:&[u8],p:usize)->f64 { f64::from_le_bytes(b[p..p+8].try_into().unwrap()) }
fn u32at(b:&[u8],p:usize)->u32 { u32::from_le_bytes(b[p..p+4].try_into().unwrap()) }
fn at(e:&Edge,y:f64)->f64 { e.a[0]+(e.b[0]-e.a[0])*((y-e.a[1])/(e.b[1]-e.a[1])) }
fn on(e:&Edge,y:f64)->Point { let t=(y-e.a[1])/(e.b[1]-e.a[1]); let mut p=[0.;3]; for i in 0..3 {p[i]=e.a[i]+(e.b[i]-e.a[i])*t;} p }
pub(crate) fn triangulate(rings:&[Vec<Point>],rect:[f64;4])->Vec<[Point;3]> {
    let mut ys=vec![rect[1],rect[3]]; let mut edges=Vec::new();
    for raw in rings {
        let mut ring:Vec<Point>=Vec::new();
        for &p in raw { if ring.last().is_none_or(|q| (q[0]-p[0]).abs()+(q[1]-p[1]).abs()>EPS) {ring.push(p);} }
        if ring.len()>1 && (ring[0][0]-ring[ring.len()-1][0]).abs()+(ring[0][1]-ring[ring.len()-1][1]).abs()<EPS {ring.pop();}
        for k in 0..ring.len() {
            let a=ring[k]; let b=ring[(k+1)%ring.len()];
            if a[1]>rect[1] && a[1]<rect[3] && !ys.contains(&a[1]) {ys.push(a[1]);}
            if (a[1]-b[1]).abs()>EPS {edges.push(Edge{a,b,lo:a[1].min(b[1]),hi:a[1].max(b[1]),index:edges.len()});}
        }
    }
    ys.sort_by(|a,b|a.partial_cmp(b).unwrap());
    edges.sort_by(|a,b|a.lo.partial_cmp(&b.lo).unwrap().then(a.index.cmp(&b.index)));
    let order:Vec<Edge>=edges.into_iter().filter(|e|e.lo<rect[3]&&e.hi>rect[1]).collect();
    let mut next=0; let mut active:Vec<Edge>=Vec::new(); let mut result=Vec::new();
    for band in ys.windows(2) {
        let (low,high)=(band[0],band[1]); let mid=(low+high)*0.5;
        while next<order.len() && order[next].lo<=mid {active.push(order[next]);next+=1;}
        active.retain(|e|e.hi>mid);
        let mut cross:Vec<(f64,Edge)>=active.iter().map(|e|(at(e,mid),*e)).collect();
        cross.sort_by(|a,b|a.0.partial_cmp(&b.0).unwrap().then(a.1.index.cmp(&b.1.index)));
        for pair in cross.chunks_exact(2) {
            let (e,f)=(pair[0].1,pair[1].1);
            let (xa,xb,xc,xd)=(at(&e,low),at(&f,low),at(&f,high),at(&e,high));
            if xa.max(xb).max(xc).max(xd)<rect[0]-EPS || xa.min(xb).min(xc).min(xd)>rect[2]+EPS {continue;}
            let (a,b,c,d)=(on(&e,low),on(&f,low),on(&f,high),on(&e,high));
            if b[0]-a[0]>EPS {result.push([a,b,c]);}
            if c[0]-d[0]>EPS {result.push([a,c,d]);}
        }
    }
    result
}
pub fn batch(data:&[u8])->Result<Vec<u8>, &'static str> {
    if data.len()<44||&data[..4]!=b"ETG1" {return Err("roof header");}
    let workers=u32at(data,4) as usize; let n=u32at(data,8) as usize;
    if workers==0||workers>32||n>20000 {return Err("roof limit");}
    let rect=[f64at(data,12),f64at(data,20),f64at(data,28),f64at(data,36)];
    if rect.iter().any(|v|!v.is_finite()) || rect[0]>rect[2] || rect[1]>rect[3] {return Err("roof rect");}
    let mut p=44usize; let mut polygons=Vec::with_capacity(n); let mut total=0usize;
    for _ in 0..n {
        if p+4>data.len(){return Err("roof rings");} let nr=u32at(data,p) as usize;p+=4;
        if nr>10000{return Err("roof rings limit");} let mut rings=Vec::with_capacity(nr);
        for _ in 0..nr {
            if p+4>data.len(){return Err("roof points");} let count=u32at(data,p) as usize;p+=4;
            total=total.checked_add(count).ok_or("roof size")?;
            if total>500000 || count>(data.len()-p)/24{return Err("roof points limit");}
            let mut ring=Vec::with_capacity(count);
            for _ in 0..count {let pt=[f64at(data,p),f64at(data,p+8),f64at(data,p+16)];p+=24;if pt.iter().any(|v|!v.is_finite()){return Err("roof coordinate");}ring.push(pt);}
            rings.push(ring);
        }
        polygons.push(rings);
    }
    if p!=data.len(){return Err("roof trailing data");}
    let start=Instant::now(); let next=AtomicUsize::new(0); let mut results=vec![Vec::new();n];
    if n>0 {std::thread::scope(|s|{let mut hs=Vec::new();for _ in 0..workers.min(n){let polys=&polygons;let next=&next;hs.push(s.spawn(move||{let mut done=Vec::new();loop{let i=next.fetch_add(1,Ordering::Relaxed);if i>=polys.len(){break;}done.push((i,triangulate(&polys[i],rect)));}done}));}for h in hs {for (i,tris) in h.join().expect("roof worker panicked"){results[i]=tris;}}});}
    let mut out=b"ETR1".to_vec();out.extend_from_slice(&(n as u32).to_le_bytes());out.extend_from_slice(&(start.elapsed().as_micros() as u64).to_le_bytes());
    for tris in results {out.extend_from_slice(&(tris.len() as u32).to_le_bytes());for tri in tris {for pt in tri {for v in pt {out.extend_from_slice(&v.to_le_bytes());}}}}
    Ok(out)
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn rectangle_hole_and_duplicates() {
        let outer=vec![[0.,0.,0.],[10.,0.,0.],[10.,10.,0.],[0.,10.,0.],[0.,0.,0.]];
        let hole=vec![[3.,3.,0.],[7.,3.,0.],[7.,7.,0.],[3.,7.,0.],[3.,3.,0.]];
        let out=triangulate(&[outer,hole],[0.,0.,10.,10.]);
        let area:f64=out.iter().map(|t|((t[1][0]-t[0][0])*(t[2][1]-t[0][1])-(t[2][0]-t[0][0])*(t[1][1]-t[0][1])).abs()/2.).sum();
        assert!((area-84.).abs()<1e-9);
    }
    #[test] fn rejects_truncated_input(){assert!(batch(b"ETG1").is_err());}
}

