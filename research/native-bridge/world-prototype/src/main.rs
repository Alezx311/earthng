use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::{collections::HashSet, error::Error, fs, path::Path};

#[derive(Deserialize)]
struct Input { tile: Tile, #[serde(default)] cell: Option<Cell>, #[serde(default)] cells: Vec<Cell>, #[serde(default)] options: Options }
#[derive(Deserialize)]
struct Options { #[serde(default = "default_tile_size", rename="tileSize")] tile_size: f64 }
fn default_tile_size() -> f64 { 500. }
impl Default for Options { fn default()->Self {Self {tile_size:default_tile_size()}} }
#[derive(Deserialize)]
struct Tile { i: i32, j: i32 }
#[derive(Deserialize)]
struct Cell { #[serde(default)] roads: Vec<Road>, #[serde(default)] buildings: Vec<Building>, #[serde(default)] points: Vec<MapPoint> }
#[derive(Deserialize)]
struct Road { #[serde(default)] id: Option<serde_json::Value>, points: Vec<[f64; 3]>, width: f64 }
#[derive(Deserialize)]
struct Building { #[serde(default)] id: Option<serde_json::Value>, rings: Vec<Vec<[f64; 3]>>, #[serde(default)] height: f64, #[serde(default, rename="minHeight")] min_height: f64 }
#[derive(Deserialize)]
struct MapPoint { #[serde(default)] id: Option<serde_json::Value>, kind: String, pos: Option<[f64; 3]> }
#[derive(Serialize)]
struct Output { tile: [i32; 2], roads: Vec<Triangle>, buildings: Vec<Triangle>, trees: Vec<[f64; 3]> }
type Triangle = [[f64; 3]; 3];

// Clip individual road segments to the tile before constructing the simple road strip.
fn clip(a: [f64;3], b: [f64;3], r: [f64;4]) -> Option<([f64;3],[f64;3])> {
    let (mut lo, mut hi): (f64,f64) = (0.,1.);
    let dx=b[0]-a[0]; let dy=b[1]-a[1];
    for (p,q) in [(-dx,a[0]-r[0]),(dx,r[2]-a[0]),(-dy,a[1]-r[1]),(dy,r[3]-a[1])] {
        if p.abs()<1e-12 { if q<0. {return None;} }
        else { let t=q/p; if p<0. {lo=lo.max(t);} else {hi=hi.min(t);} if lo>hi{return None;} }
    }
    let at=|t:f64| [a[0]+dx*t,a[1]+dy*t,a[2]+(b[2]-a[2])*t];
    Some((at(lo),at(hi)))
}
fn road_mesh(road:&Road, rect:[f64;4]) -> Vec<Triangle> {
    let mut out=Vec::new();
    if !road.width.is_finite() || road.width<=0. {return out;}
    for pair in road.points.windows(2) {
        let Some((a,b))=clip(pair[0],pair[1],rect) else {continue};
        let dx=b[0]-a[0]; let dy=b[1]-a[1]; let len=dx.hypot(dy);
        if len<1e-8 {continue;}
        let (x,y)=(-dy/len*road.width/2.,dx/len*road.width/2.);
        let (p,q,s,t)=([a[0]+x,a[1]+y,a[2]],[a[0]-x,a[1]-y,a[2]],[b[0]-x,b[1]-y,b[2]],[b[0]+x,b[1]+y,b[2]]);
        out.extend([[p,q,s],[p,s,t]]);
    }
    out
}
// Existing experimentally verified Lua-compatible band triangulator.
#[path = "../roofs.rs"] mod roofs;
fn building_mesh(building:&Building, rect:[f64;4])->Vec<Triangle> {
    let Some(outer)=building.rings.first() else {return vec![]};
    let Some(first)=outer.first() else {return vec![]};
    let base=first[2]+building.min_height; let top=first[2]+building.height.max(building.min_height);
    let mut result=Vec::new();
    for ring in &building.rings {
        for edge in ring.windows(2) {
            let Some((a,b))=clip(edge[0],edge[1],rect) else {continue};
            if (a[0]-b[0]).hypot(a[1]-b[1])<1e-8 {continue;}
            let (a,b,c,d)=([a[0],a[1],base],[b[0],b[1],base],[b[0],b[1],top],[a[0],a[1],top]);
            result.extend([[a,b,c],[a,c,d]]);
        }
    }
    for mut tri in roofs::triangulate(&building.rings,rect) { for p in &mut tri {*p=[p[0],p[1],top];} result.push(tri); }
    result
}
fn inside(rings:&[Vec<[f64;3]>],x:f64,y:f64)->bool {
    let mut inside=false;
    for ring in rings {
        if ring.len()<3 {continue;}
        let mut j=ring.len()-1;
        for i in 0..ring.len() {let a=ring[i]; let b=ring[j];
            if (a[1]>y)!=(b[1]>y) && x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0] {inside=!inside;} j=i;
        }
    }
    inside
}
fn near_road(p:[f64;3],road:&Road)->bool {
    road.points.windows(2).any(|e| {let a=e[0];let b=e[1];let dx=b[0]-a[0];let dy=b[1]-a[1];let d=dx*dx+dy*dy;
        let t=if d>0. {((p[0]-a[0])*dx+(p[1]-a[1])*dy)/d} else {0.}; let t=t.clamp(0.,1.);
        (p[0]-(a[0]+dx*t)).hypot(p[1]-(a[1]+dy*t)) <= road.width/2. + 1.
    })
}
fn feature_id(id:&Option<serde_json::Value>, index:usize)->String {
    match id {Some(serde_json::Value::String(s))=>s.clone(), Some(x)=>x.to_string(), None=>(index+1).to_string()}
}
// Match collect(): first occurrence of each id wins across all source cells,
// followed by the generator's lexicographic ordering.
fn unique<'a,T>(cells:&'a [&Cell], field:impl Fn(&'a Cell)->&'a [T], id:impl Fn(&T)->&Option<serde_json::Value>)->Vec<&'a T> {
    let mut seen=HashSet::new(); let mut items=Vec::new();
    for cell in cells {for (i,item) in field(cell).iter().enumerate() {
        let key=feature_id(id(item),i);
        if seen.insert(key.clone()) {items.push((key,item));}
    }}
    // Lua sorts by tostring(feature.id or ''), even when the dedup key used an index.
    items.sort_by(|a,b| {
        let key=|item:&T| match id(item) {Some(serde_json::Value::String(s))=>s.clone(),Some(x)=>x.to_string(),None=>String::new()};
        key(a.1).cmp(&key(b.1))
    });
    items.into_iter().map(|(_,item)|item).collect()
}
fn generate(input:&Input)->Output {
    let size=input.options.tile_size;
    let r=[input.tile.i as f64*size,input.tile.j as f64*size,(input.tile.i+1) as f64*size,(input.tile.j+1) as f64*size];
    let mut cells:Vec<&Cell>=input.cells.iter().collect();
    if let Some(cell)=input.cell.as_ref() {cells.push(cell);}
    let roads=unique(&cells,|c|&c.roads,|r|&r.id);
    let buildings=unique(&cells,|c|&c.buildings,|b|&b.id);
    let points=unique(&cells,|c|&c.points,|p|&p.id);
    let (road_meshes, building_meshes) = rayon::join(
        || roads.par_iter().flat_map_iter(|x|road_mesh(x,r)).collect(),
        || buildings.par_iter().flat_map_iter(|x|building_mesh(x,r)).collect());
    let trees=points.par_iter().filter_map(|item| {
        let p=item.pos?; if item.kind!="tree" || p[0]<r[0] || p[0]>=r[2] || p[1]<r[1] || p[1]>=r[3] {return None;}
        if roads.iter().any(|road|near_road(p,road)) || buildings.iter().any(|b|inside(&b.rings,p[0],p[1])) {return None;}
        Some(p)
    }).collect();
    Output{tile:[input.tile.i,input.tile.j],roads:road_meshes,buildings:building_meshes,trees}
}
fn main()->Result<(),Box<dyn Error>> {
    let args:Vec<_>=std::env::args_os().collect();
    if args.len()!=3 {return Err("usage: earthng-world-prototype input.json output.json".into());}
    let input:Input=serde_json::from_slice(&fs::read(&args[1])?)?;
    let result=generate(&input);
    let path=Path::new(&args[2]);
    let file=fs::OpenOptions::new().write(true).create_new(true).open(path)?;
    serde_json::to_writer(std::io::BufWriter::new(file),&result)?;
    println!("tile {:?}: {} road triangles, {} building triangles, {} mapped trees",result.tile,result.roads.len(),result.buildings.len(),result.trees.len());
    Ok(())
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn clips_and_handles_degenerate_segments() {
        let r=Road{id:None,width:4.,points:vec![[-5.,5.,0.],[15.,5.,10.],[15.,5.,10.]]};
        let m=road_mesh(&r,[0.,0.,10.,10.]); assert_eq!(m.len(),2); assert_eq!(m[0][0],[0.,7.,2.5]);
    }
    #[test] fn courtyard_and_roads_block_trees() {
        let ring=|lo:f64,hi:f64|vec![[lo,lo,0.],[hi,lo,0.],[hi,hi,0.],[lo,hi,0.],[lo,lo,0.]];
        let b=Building{id:None,rings:vec![ring(0.,10.),ring(3.,7.)],height:10.,min_height:0.};
        assert!(inside(&b.rings,1.,1.)); assert!(!inside(&b.rings,5.,5.));
        let r=Road{id:None,width:4.,points:vec![[0.,0.,0.],[10.,0.,0.]]};
        assert!(near_road([5.,2.5,0.],&r)); assert!(!near_road([5.,4.,0.],&r));
        assert!(!building_mesh(&b,[0.,0.,10.,10.]).is_empty());
    }
    #[test] fn multiple_cells_deduplicate_and_use_requested_tile_size() {
        let input:Input=serde_json::from_str(r#"{
          "tile":{"i":1,"j":0},"options":{"tileSize":100},
          "cells":[
            {"roads":[{"id":"r","width":4,"points":[[90,10,0],[210,10,0]]}],
             "points":[{"id":"a","kind":"tree","pos":[150,10,0]},
                       {"id":"b","kind":"tree","pos":[150,30,0]}]},
            {"roads":[{"id":"r","width":4,"points":[[90,10,0],[210,10,0]]}],
             "points":[{"id":"b","kind":"tree","pos":[150,30,0]},
                       {"id":"outside","kind":"tree","pos":[250,30,0]}]}
          ]}"#).unwrap();
        let out=generate(&input);
        assert_eq!(out.roads.len(),2);
        assert_eq!(out.trees,vec![[150.,30.,0.]]);
    }
}

