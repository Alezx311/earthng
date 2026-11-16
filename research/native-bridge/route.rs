//! Experimental A* travel-time queries over a copied EarthNG CSR routing graph.
use std::{sync::atomic::{AtomicUsize, Ordering}, time::Instant};
const MAX_N: usize = 4_000_000;
const MAX_A: usize = 24_000_000;
#[repr(C)]
#[derive(Default)]
struct FileTime { low: u32, high: u32 }
#[link(name="kernel32")]
unsafe extern "system" {
    fn GetCurrentThread() -> *mut std::ffi::c_void;
    fn GetThreadTimes(thread: *mut std::ffi::c_void, create: *mut FileTime, exit: *mut FileTime, kernel: *mut FileTime, user: *mut FileTime) -> i32;
}
fn thread_cpu_us() -> Option<u64> {
    let (mut c,mut e,mut k,mut u)=(FileTime::default(),FileTime::default(),FileTime::default(),FileTime::default());
    let ok=unsafe { GetThreadTimes(GetCurrentThread(), &mut c, &mut e, &mut k, &mut u) };
    if ok==0 { return None; }
    let val=|t:FileTime| (u64::from(t.high)<<32)|u64::from(t.low);
    Some((val(k)+val(u))/10)
}
fn u32at(s: &[u8], at: usize) -> u32 { u32::from_le_bytes(s[at..at+4].try_into().unwrap()) }
fn f64at(s: &[u8], at: usize) -> f64 { f64::from_le_bytes(s[at..at+8].try_into().unwrap()) }

pub struct Graph { x: Vec<f64>, y: Vec<f64>, first: Vec<u32>, used: Vec<u32>, to: Vec<u32>, cost: Vec<f32> }
impl Graph {
    pub fn decode(data: &[u8]) -> Result<Self, &'static str> {
        if data.len()<12 || &data[..4]!=b"ERG1" { return Err("graph header"); }
        let n=u32at(data,4) as usize; let a=u32at(data,8) as usize;
        if n>MAX_N || a>MAX_A || data.len()!=12+n*24+4+a*8 { return Err("graph length"); }
        let mut p=12;
        let mut doubles=|| { let v=(0..n).map(|i| f64at(data,p+8*i)).collect::<Vec<_>>(); p+=8*n; v };
        let x=doubles(); let y=doubles();
        let mut ints=|len:usize| { let v=(0..len).map(|i| u32at(data,p+4*i)).collect::<Vec<_>>(); p+=4*len; v };
        let first=ints(n+1); let used=ints(n); let to=ints(a);
        let cost=(0..a).map(|i| f32::from_bits(u32at(data,p+4*i))).collect::<Vec<_>>();
        if first[0]!=0 || first[n] as usize!=a || (0..n).any(|i| first[i]>first[i+1] || used[i]>first[i+1]-first[i]) { return Err("csr bounds"); }
        for i in 0..n { for j in first[i]..first[i]+used[i] { let j=j as usize; if to[j] as usize>=n || !cost[j].is_finite() || cost[j]<0. { return Err("arc"); } } }
        if x.iter().chain(&y).any(|v| !v.is_finite()) { return Err("coordinate"); }
        Ok(Self{x,y,first,used,to,cost})
    }
    fn search(&self, from: usize, target: usize) -> (f64,u32) {
        let n=self.x.len(); let mut dist=vec![f64::INFINITY;n]; let mut done=vec![false;n];
        let mut heap:Vec<(f64,usize)>=Vec::new();
        let h=|v:usize| { let dx=self.x[v]-self.x[target]; let dy=self.y[v]-self.y[target]; (dx*dx+dy*dy).sqrt()/(130./3.6) };
        fn push(heap:&mut Vec<(f64,usize)>, item:(f64,usize)) { let mut k=heap.len(); heap.push(item); while k>0 { let p=(k-1)/2; if heap[p].0<=item.0 { break; } heap[k]=heap[p]; k=p; } heap[k]=item; }
        fn pop(heap:&mut Vec<(f64,usize)>)->usize { let node=heap[0].1; let last=heap.pop().unwrap(); if heap.is_empty(){return node;} let mut k=0; loop { let mut c=2*k+1; if c>=heap.len(){break;} if c+1<heap.len() && heap[c+1].0<heap[c].0 {c+=1;} if heap[c].0>=last.0 {break;} heap[k]=heap[c]; k=c; } heap[k]=last; node }
        dist[from]=0.; push(&mut heap,(h(from),from)); let mut expanded=0;
        while !heap.is_empty() {
            let node=pop(&mut heap); if done[node] { continue; }
            if node==target { return (dist[target],expanded); }
            done[node]=true; expanded+=1;
            for a in self.first[node]..self.first[node]+self.used[node] {
                let a=a as usize; let next=self.to[a] as usize; let nd=dist[node]+self.cost[a] as f64;
                if !done[next] && nd<dist[next] { dist[next]=nd; push(&mut heap,(nd+h(next),next)); }
            }
        }
        (f64::INFINITY,expanded)
    }
    pub fn batch(&self, data:&[u8]) -> Result<Vec<u8>, &'static str> {
        if data.len()<8 || &data[..4]!=b"ERQ1" || (data.len()-8)%8!=0 { return Err("query length"); }
        let workers=u32at(data,4) as usize; let q=(data.len()-8)/8;
        if workers==0 || workers>32 || q>256 { return Err("query limit"); }
        let queries=(0..q).map(|i|(u32at(data,8+i*8) as usize,u32at(data,12+i*8) as usize)).collect::<Vec<_>>();
        if queries.iter().any(|&(a,b)| a>=self.x.len() || b>=self.x.len()) { return Err("query node"); }
        let started=Instant::now(); let mut results=vec![(0.,0u32);q]; let mut cpu_us=Some(0u64);
        if q>0 {
            // Routes vary greatly in search size. Work stealing via an atomic job
            // index avoids leaving cores idle behind one unusually expensive route.
            let next=AtomicUsize::new(0);
            std::thread::scope(|s| {
                let mut handles=Vec::new();
                for _ in 0..workers.min(q) {
                    let queries=&queries; let next=&next;
                    handles.push(s.spawn(move || {
                        let cpu_start=thread_cpu_us();
                        let mut completed=Vec::new();
                        loop {
                            let i=next.fetch_add(1,Ordering::Relaxed);
                            if i>=queries.len() { break; }
                            let (a,b)=queries[i]; completed.push((i,self.search(a,b)));
                        }
                        let cpu_end=thread_cpu_us();
                        (completed,cpu_start.zip(cpu_end).map(|(a,b)|b.saturating_sub(a)))
                    }));
                }
                for handle in handles {
                    let (completed,used)=handle.join().expect("route worker panicked");
                    for (i,value) in completed { results[i]=value; }
                    cpu_us=cpu_us.zip(used).map(|(a,b)|a+b);
                }
            });
        }
        let mut out=b"ERR1".to_vec(); out.extend_from_slice(&(q as u32).to_le_bytes()); out.extend_from_slice(&(started.elapsed().as_micros() as u64).to_le_bytes());
        for (d,e) in results {out.extend_from_slice(&d.to_le_bytes());out.extend_from_slice(&e.to_le_bytes());}
        out.extend_from_slice(&cpu_us.unwrap_or(u64::MAX).to_le_bytes()); Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn graph() -> Vec<u8> {
        let mut b=b"ERG1".to_vec(); for n in [3u32,2] {b.extend(n.to_le_bytes());}
        for x in [0f64,1.,2.,0.,0.,0.] {b.extend(x.to_le_bytes());}
        for n in [0u32,1,2,2,1,1,0,1,2] {b.extend(n.to_le_bytes());}
        for x in [1f32,1.] {b.extend(x.to_le_bytes());} b
    }
    #[test] fn shortest_unreachable_and_invalid() {
        let g=Graph::decode(&graph()).unwrap();
        assert_eq!(g.search(0,2).0,2.); assert!(g.search(2,0).0.is_infinite()); assert_eq!(g.search(1,1).0,0.);
        assert!(Graph::decode(&graph()[..20]).is_err());
        let mut q=b"ERQ1".to_vec(); q.extend(2u32.to_le_bytes()); for n in [0u32,2,2,0] {q.extend(n.to_le_bytes());}
        let r=g.batch(&q).unwrap(); assert_eq!(f64at(&r,16),2.); assert!(f64at(&r,28).is_infinite());
        q.extend([0;4]); assert!(g.batch(&q).is_err());
    }
}
