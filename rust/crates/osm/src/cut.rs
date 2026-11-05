//! Cut an .osm.pbf into the static tile archive of earthng/osm_tiles.py.
//!
//! Same selection as osm_tiles.cut (one cut of the package box): tiles of CELL degrees grown by
//! BUFFER; every way with a node inside a tile's coverage goes to that tile complete; restriction,
//! multipolygon and landmark relations with a member there, their nested parents, and all their
//! members; every tagged node inside. A relation stays in a tile only when all its members are
//! written there. The difference is how: blobs are decoded on all cores, relations first (they sit
//! at the end of a sorted file), then nodes, then ways, then only the node blobs that hold nodes
//! outside the package that selected ways need.

use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{Context, Result, bail};
use osmpbf::{BlobDecode, Mmap, MmapBlob, PrimitiveBlock, RelMemberType};
use rayon::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use smallvec::SmallVec;

use crate::pbfwrite::{MemberOut, NodeOut, PbfWriter, RelationOut, Tags, WayOut};
use crate::select;

pub const CELL: f64 = 0.05;
pub const BUFFER: f64 = 0.01;

type TSet = SmallVec<[u32; 4]>;

/// Python's round(v, 6) (correctly rounded, half to even on the exact binary value).
pub fn round6(v: f64) -> f64 {
    format!("{v:.6}").parse().expect("formatted float")
}

pub fn cell_box(x: i64, y: i64) -> [f64; 4] {
    [round6(x as f64 * CELL), round6(y as f64 * CELL), round6((x + 1) as f64 * CELL), round6((y + 1) as f64 * CELL)]
}

pub fn coverage(x: i64, y: i64) -> [f64; 4] {
    let [w, s, e, n] = cell_box(x, y);
    [round6(w - BUFFER), round6(s - BUFFER), round6(e + BUFFER), round6(n + BUFFER)]
}

/// The tiles of a package box, in sorted (x, y) order, and a dense lookup over their range.
pub struct Grid {
    pub keys: Vec<(i64, i64)>,
    x0: i64,
    y0: i64,
    w: i64,
    h: i64,
    slot: Vec<u32>,
}

const NONE: u32 = u32::MAX;

impl Grid {
    pub fn new(package_box: [f64; 4]) -> Grid {
        let [pw, ps, pe, pn] = package_box;
        let (x0, x1) = ((pw / CELL).floor() as i64, (pe / CELL).floor() as i64);
        let (y0, y1) = ((ps / CELL).floor() as i64, (pn / CELL).floor() as i64);
        let mut keys = Vec::new();
        for x in x0..=x1 {
            for y in y0..=y1 {
                let c = coverage(x, y);
                if pw <= c[0] && c[2] <= pe && ps <= c[1] && c[3] <= pn {
                    keys.push((x, y));
                }
            }
        }
        let (w, h) = ((x1 - x0 + 1).max(0), (y1 - y0 + 1).max(0));
        let mut slot = vec![NONE; (w * h) as usize];
        for (i, &(x, y)) in keys.iter().enumerate() {
            slot[((x - x0) * h + (y - y0)) as usize] = i as u32;
        }
        Grid { keys, x0, y0, w, h, slot }
    }

    fn get(&self, x: i64, y: i64) -> u32 {
        let (dx, dy) = (x - self.x0, y - self.y0);
        if dx < 0 || dy < 0 || dx >= self.w || dy >= self.h {
            return NONE;
        }
        self.slot[(dx * self.h + dy) as usize]
    }

    /// osm_tiles.cells_of: the tiles whose buffered box holds the point (1e-7 degree units),
    /// for a valid location only.
    pub fn tiles_of(&self, x: i32, y: i32) -> TSet {
        let mut out = TSet::new();
        if !(-1_800_000_000..=1_800_000_000).contains(&x) || !(-900_000_000..=900_000_000).contains(&y) {
            return out;
        }
        let lon = f64::from(x) / 1e7;
        let lat = f64::from(y) / 1e7;
        let (xa, xb) = (((lon - BUFFER) / CELL).floor() as i64, ((lon + BUFFER) / CELL).floor() as i64);
        let (ya, yb) = (((lat - BUFFER) / CELL).floor() as i64, ((lat + BUFFER) / CELL).floor() as i64);
        for cx in xa..=xb {
            for cy in ya..=yb {
                let t = self.get(cx, cy);
                if t != NONE {
                    out.push(t);
                }
            }
        }
        out
    }
}

/// a |= b for sorted, unique sets; true when a grew.
fn union_into<A: smallvec::Array<Item = u32>>(a: &mut SmallVec<A>, b: &[u32]) -> bool {
    if b.iter().all(|t| a.binary_search(t).is_ok()) {
        return false;
    }
    let mut out: SmallVec<A> = SmallVec::with_capacity(a.len() + b.len());
    let (mut i, mut j) = (0, 0);
    while i < a.len() || j < b.len() {
        let next = if j >= b.len() || (i < a.len() && a[i] < b[j]) {
            i += 1;
            a[i - 1]
        } else if i >= a.len() || b[j] < a[i] {
            j += 1;
            b[j - 1]
        } else {
            i += 1;
            j += 1;
            a[i - 1]
        };
        out.push(next);
    }
    *a = out;
    true
}

fn intersect(a: &[u32], b: &[u32]) -> TSet {
    a.iter().copied().filter(|t| b.binary_search(t).is_ok()).collect()
}

struct Member {
    kind: u8,
    id: i64,
    role: Box<[u8]>,
}

struct Rel {
    id: i64,
    members: Box<[Member]>,
    tags: Tags,
}

struct Way {
    id: i64,
    refs: Box<[i64]>,
    tags: Tags,
    tiles: TSet,
}

/// Nodes inside the package: sorted ids, coordinates, tags of the tagged ones.
#[derive(Default)]
struct Inside {
    ids: Vec<i64>,
    xy: Vec<[i32; 2]>,
    tagged: Vec<(u32, Tags)>,
}

impl Inside {
    fn find(&self, id: i64) -> Option<usize> {
        self.ids.binary_search(&id).ok()
    }
    fn tags(&self, i: usize) -> &[(Box<[u8]>, Box<[u8]>)] {
        match self.tagged.binary_search_by_key(&(i as u32), |(k, _)| *k) {
            Ok(k) => &self.tagged[k].1,
            Err(_) => &[],
        }
    }
}

fn tags_of(table: &[Vec<u8>], pairs: impl Iterator<Item = (usize, usize)>) -> Tags {
    pairs.map(|(k, v)| (table[k].clone().into_boxed_slice(), table[v].clone().into_boxed_slice())).collect()
}

pub(crate) fn decode<'a>(blob: &'a MmapBlob<'a>) -> Result<Option<PrimitiveBlock>> {
    Ok(match blob.decode()? {
        BlobDecode::OsmData(block) => Some(block),
        _ => None,
    })
}

const HAS_NODES: u8 = 1;
const HAS_WAYS: u8 = 2;
const HAS_RELATIONS: u8 = 4;

fn kinds(block: &PrimitiveBlock) -> u8 {
    let mut k = 0;
    for g in block.groups() {
        if g.dense_nodes().next().is_some() || g.nodes().next().is_some() {
            k |= HAS_NODES;
        }
        if g.ways().next().is_some() {
            k |= HAS_WAYS;
        }
        if g.relations().next().is_some() {
            k |= HAS_RELATIONS;
        }
    }
    k
}

/// Visit every node of a block: (id, x, y, tags as string-table index pairs).
fn each_node(block: &PrimitiveBlock, mut f: impl FnMut(i64, i32, i32, &mut dyn Iterator<Item = (usize, usize)>)) {
    for g in block.groups() {
        for n in g.dense_nodes() {
            let mut tags = n.raw_tags().map(|(k, v)| (k as usize, v as usize));
            f(n.id(), n.decimicro_lon(), n.decimicro_lat(), &mut tags);
        }
        for n in g.nodes() {
            let mut tags = n.raw_tags().map(|(k, v)| (k as usize, v as usize));
            f(n.id(), n.decimicro_lon(), n.decimicro_lat(), &mut tags);
        }
    }
}

pub struct CutReport {
    pub index: Value,
    pub seconds: f64,
}

/// What the blob ranges of each phase are: all blobs of a kind, found by binary search in a file
/// sorted by type then id, else by decoding everything once.
pub(crate) fn phases(data: &[MmapBlob], sorted: bool) -> Result<[Vec<usize>; 3]> {
    let n = data.len();
    if sorted && n > 0 {
        let kind = |i: usize| -> Result<u8> { Ok(decode(&data[i])?.map(|b| kinds(&b)).unwrap_or(0)) };
        // first blob with ways or relations, first blob with relations (both monotone when sorted)
        let first = |mask: u8| -> Result<usize> {
            let (mut lo, mut hi) = (0usize, n);
            while lo < hi {
                let mid = (lo + hi) / 2;
                if kind(mid)? & mask != 0 { hi = mid } else { lo = mid + 1 }
            }
            Ok(lo)
        };
        let fw = first(HAS_WAYS | HAS_RELATIONS)?;
        let fr = first(HAS_RELATIONS)?;
        let nodes = (0..(fw + 1).min(n)).collect();
        let ways = (fw..(fr + 1).min(n)).collect();
        let rels = (fr..n).collect();
        return Ok([nodes, ways, rels]);
    }
    let k: Vec<u8> = data.par_iter().map(|b| Ok(decode(b)?.map(|b| kinds(&b)).unwrap_or(0))).collect::<Result<_>>()?;
    let pick = |m: u8| (0..n).filter(|&i| k[i] & m != 0).collect();
    Ok([pick(HAS_NODES), pick(HAS_WAYS), pick(HAS_RELATIONS)])
}

pub fn header_box(mmap: &Mmap) -> Result<(Option<[f64; 4]>, bool)> {
    for blob in mmap.blob_iter() {
        let blob = blob?;
        if let BlobDecode::OsmHeader(h) = blob.decode()? {
            let sorted = h.optional_features().iter().any(|f| f == "Sort.Type_then_ID");
            // osmium keeps the header box in 1e-7 degrees, like node locations
            let deg = |v: f64| ((v * 1e9).round() as i64 / 100) as f64 / 1e7;
            let b = h.bbox().map(|b| [deg(b.left), deg(b.bottom), deg(b.right), deg(b.top)]);
            return Ok((b, sorted));
        }
        break;
    }
    Ok((None, false))
}

pub fn cut(pbf: &Path, out: &Path, package_box: Option<[f64; 4]>, emit: &(dyn Fn(String) + Sync)) -> Result<CutReport> {
    let t0 = Instant::now();
    if out.exists() {
        bail!("{} exists", out.display());
    }
    let mmap = unsafe { Mmap::from_path(pbf) }.with_context(|| format!("open {}", pbf.display()))?;
    let (header, sorted) = header_box(&mmap)?;
    let package_box = match package_box.or(header) {
        Some(b) => b,
        None => bail!("{} has no bounding box: give --package-box", pbf.display()),
    };
    let grid = Grid::new(package_box);
    let data: Vec<MmapBlob> = mmap
        .blob_iter()
        .filter_map(|b| match b {
            Ok(b) if matches!(b.get_type(), osmpbf::BlobType::OsmData) => Some(Ok(b)),
            Ok(_) => None,
            Err(e) => Some(Err(e)),
        })
        .collect::<std::result::Result<_, _>>()?;
    let [node_blobs, way_blobs, rel_blobs] = phases(&data, sorted)?;
    emit(format!("{} tiles, {} blobs ({} node, {} way, {} relation){}", grid.keys.len(), data.len(), node_blobs.len(),
                 way_blobs.len(), rel_blobs.len(), if sorted { "" } else { ", unsorted file" }));

    // Relations: every one, with members (completion follows any relation) and tags.
    let rels: Vec<Rel> = rel_blobs
        .par_iter()
        .map(|&i| -> Result<Vec<Rel>> {
            let mut found = Vec::new();
            let Some(block) = decode(&data[i])? else { return Ok(found) };
            let table = block.raw_stringtable();
            for g in block.groups() {
                for r in g.relations() {
                    let members = r
                        .members()
                        .map(|m| Member {
                            kind: match m.member_type { RelMemberType::Node => 0, RelMemberType::Way => 1, RelMemberType::Relation => 2 },
                            id: m.member_id,
                            role: table[m.role_sid as usize].clone().into_boxed_slice(),
                        })
                        .collect();
                    let tags = tags_of(table, r.raw_tags().map(|(k, v)| (k as usize, v as usize)));
                    found.push(Rel { id: r.id(), members, tags });
                }
            }
            Ok(found)
        })
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect();
    let rel_at: FxHashMap<i64, u32> = rels.iter().enumerate().map(|(i, r)| (r.id, i as u32)).collect();
    let relevant: Vec<u32> = (0..rels.len() as u32).filter(|&i| select::relevant_relation(&rels[i as usize].tags)).collect();
    // ways that relation completion may add: the way members of everything below a followed relation
    let mut candidate_ways: FxHashSet<i64> = FxHashSet::default();
    {
        let mut seen: FxHashSet<u32> = relevant.iter().copied().collect();
        let mut stack: Vec<u32> = relevant.clone();
        while let Some(i) = stack.pop() {
            for m in &rels[i as usize].members {
                match m.kind {
                    1 => { candidate_ways.insert(m.id); }
                    2 => if let Some(&c) = rel_at.get(&m.id) && seen.insert(c) { stack.push(c) },
                    _ => {}
                }
            }
        }
    }
    emit(format!("relations: {} ({} followed) ({:.1} s)", rels.len(), relevant.len(), t0.elapsed().as_secs_f64()));

    // Nodes inside the package; and every node blob's id range, for the outside nodes later.
    struct NodeChunk {
        range: Option<(i64, i64)>,
        inside: Inside,
    }
    let chunks: Vec<NodeChunk> = node_blobs
        .par_iter()
        .map(|&i| -> Result<NodeChunk> {
            let mut chunk = NodeChunk { range: None, inside: Inside::default() };
            let Some(block) = decode(&data[i])? else { return Ok(chunk) };
            let table = block.raw_stringtable();
            each_node(&block, |id, x, y, tags| {
                chunk.range = Some(match chunk.range { None => (id, id), Some((a, b)) => (a.min(id), b.max(id)) });
                if grid.tiles_of(x, y).is_empty() {
                    return;
                }
                let at = chunk.inside.ids.len() as u32;
                chunk.inside.ids.push(id);
                chunk.inside.xy.push([x, y]);
                let t = tags_of(table, tags);
                if !t.is_empty() {
                    chunk.inside.tagged.push((at, t));
                }
            });
            Ok(chunk)
        })
        .collect::<Result<_>>()?;
    let mut inside = Inside::default();
    let mut ranges: Vec<(i64, i64, usize)> = Vec::new();
    for (chunk, &blob) in chunks.into_iter().zip(&node_blobs) {
        if let Some((a, b)) = chunk.range {
            ranges.push((a, b, blob));
        }
        let base = inside.ids.len() as u32;
        inside.ids.extend(chunk.inside.ids);
        inside.xy.extend(chunk.inside.xy);
        inside.tagged.extend(chunk.inside.tagged.into_iter().map(|(k, t)| (k + base, t)));
    }
    if !inside.ids.windows(2).all(|w| w[0] < w[1]) {
        // an unsorted file: order the inside nodes by id (first copy of a duplicate wins)
        let mut order: Vec<u32> = (0..inside.ids.len() as u32).collect();
        order.sort_by_key(|&i| (inside.ids[i as usize], i));
        order.dedup_by_key(|i| inside.ids[*i as usize]);
        let tags: FxHashMap<u32, Tags> = std::mem::take(&mut inside.tagged).into_iter().collect();
        let mut sorted_inside = Inside::default();
        let mut tags = tags;
        for (k, &i) in order.iter().enumerate() {
            sorted_inside.ids.push(inside.ids[i as usize]);
            sorted_inside.xy.push(inside.xy[i as usize]);
            if let Some(t) = tags.remove(&i) {
                sorted_inside.tagged.push((k as u32, t));
            }
        }
        inside = sorted_inside;
    }
    emit(format!("nodes: {} inside ({:.1} s)", inside.ids.len(), t0.elapsed().as_secs_f64()));
    let inside_tiles = |id: i64| -> TSet {
        match inside.find(id) {
            Some(i) => grid.tiles_of(inside.xy[i][0], inside.xy[i][1]),
            None => TSet::new(),
        }
    };

    // Ways touching a tile, plus the ones a followed relation may complete.
    let mut ways: Vec<Way> = way_blobs
        .par_iter()
        .map(|&i| -> Result<Vec<Way>> {
            let mut found = Vec::new();
            let Some(block) = decode(&data[i])? else { return Ok(found) };
            let table = block.raw_stringtable();
            for g in block.groups() {
                for w in g.ways() {
                    let mut tiles = TSet::new();
                    for r in w.refs() {
                        let t = inside_tiles(r);
                        if !t.is_empty() {
                            union_into(&mut tiles, &t);
                        }
                    }
                    if tiles.is_empty() && !candidate_ways.contains(&w.id()) {
                        continue;
                    }
                    let tags = tags_of(table, w.raw_tags().map(|(k, v)| (k as usize, v as usize)));
                    found.push(Way { id: w.id(), refs: w.refs().collect(), tags, tiles });
                }
            }
            Ok(found)
        })
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect();
    if !ways.windows(2).all(|w| w[0].id < w[1].id) {
        ways.sort_by_key(|w| w.id);
        ways.dedup_by_key(|w| w.id);
    }
    let way_at: FxHashMap<i64, u32> = ways.iter().enumerate().map(|(i, w)| (w.id, i as u32)).collect();
    emit(format!("ways: {} touching ({:.1} s)", ways.iter().filter(|w| !w.tiles.is_empty()).count(), t0.elapsed().as_secs_f64()));

    // Relations: spatial hits of the followed ones, nested parents, to a fixpoint.
    let mut rel_tiles: FxHashMap<i64, TSet> = FxHashMap::default();
    loop {
        let mut changed = false;
        for &i in &relevant {
            let r = &rels[i as usize];
            let mut m = rel_tiles.get(&r.id).cloned().unwrap_or_default();
            for mb in &r.members {
                match mb.kind {
                    1 => if let Some(&w) = way_at.get(&mb.id) { union_into(&mut m, &ways[w as usize].tiles); },
                    0 => { union_into(&mut m, &inside_tiles(mb.id)); }
                    _ => if let Some(t) = rel_tiles.get(&mb.id) { let t = t.clone(); union_into(&mut m, &t); },
                }
            }
            if m != rel_tiles.get(&r.id).cloned().unwrap_or_default() {
                rel_tiles.insert(r.id, m);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    // Completion: every member of a relation goes to its tiles, recursively.
    let mut extra_ways: FxHashMap<i64, TSet> = FxHashMap::default();
    let mut extra_nodes: FxHashMap<i64, TSet> = FxHashMap::default();
    let mut pending: Vec<(i64, TSet)> = rel_tiles.iter().map(|(&k, v)| (k, v.clone())).collect();
    while let Some((rid, m)) = pending.pop() {
        let Some(&ri) = rel_at.get(&rid) else { continue };
        for mb in &rels[ri as usize].members {
            match mb.kind {
                1 => { union_into(extra_ways.entry(mb.id).or_default(), &m); }
                0 => { union_into(extra_nodes.entry(mb.id).or_default(), &m); }
                _ => {
                    let t = rel_tiles.entry(mb.id).or_default();
                    if union_into(t, &m) {
                        pending.push((mb.id, t.clone()));
                    }
                }
            }
        }
    }
    // ways named by a relation but absent from the file still count as written (as in Python)
    let mut ghost_ways: FxHashMap<i64, TSet> = FxHashMap::default();
    for (wid, m) in &extra_ways {
        match way_at.get(wid) {
            Some(&w) => { union_into(&mut ways[w as usize].tiles, m); }
            None => { ghost_ways.insert(*wid, m.clone()); }
        }
    }
    let way_tiles = |id: i64| -> &[u32] {
        match way_at.get(&id) {
            Some(&w) => &ways[w as usize].tiles,
            None => ghost_ways.get(&id).map(|t| t.as_slice()).unwrap_or(&[]),
        }
    };
    let poi_tiles = |id: i64| -> TSet {
        match inside.find(id) {
            Some(i) if select::poi(inside.tags(i)) => grid.tiles_of(inside.xy[i][0], inside.xy[i][1]),
            _ => TSet::new(),
        }
    };

    // node_tiles of relation node members: their own (POI), as members, and of the ways through them
    let mut member_nodes: FxHashMap<i64, TSet> = FxHashMap::default();
    for rid in rel_tiles.keys() {
        if let Some(&ri) = rel_at.get(rid) {
            for mb in rels[ri as usize].members.iter().filter(|m| m.kind == 0) {
                member_nodes.entry(mb.id).or_insert_with(|| {
                    let mut t = poi_tiles(mb.id);
                    if let Some(e) = extra_nodes.get(&mb.id) { union_into(&mut t, e); }
                    t
                });
            }
        }
    }
    if !member_nodes.is_empty() {
        for w in ways.iter().filter(|w| !w.tiles.is_empty()) {
            for r in w.refs.iter() {
                if let Some(t) = member_nodes.get_mut(r) {
                    union_into(t, &w.tiles);
                }
            }
        }
    }
    // A relation stays in a tile only when all its members (recursively) are written there.
    loop {
        let mut changed = false;
        let ids: Vec<i64> = rel_tiles.keys().copied().collect();
        for rid in ids {
            let Some(&ri) = rel_at.get(&rid) else { continue };
            let m = rel_tiles[&rid].clone();
            let mut keep = m.clone();
            for mb in &rels[ri as usize].members {
                let other: &[u32] = match mb.kind {
                    0 => member_nodes.get(&mb.id).map(|t| t.as_slice()).unwrap_or(&[]),
                    1 => way_tiles(mb.id),
                    _ => rel_tiles.get(&mb.id).map(|t| t.as_slice()).unwrap_or(&[]),
                };
                keep = intersect(&keep, other);
                if keep.is_empty() {
                    break;
                }
            }
            if keep != m {
                rel_tiles.insert(rid, keep);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    emit(format!("relations kept in {} tiles ({:.1} s)", rel_tiles.values().filter(|t| !t.is_empty()).count(), t0.elapsed().as_secs_f64()));

    // Nodes outside the package that selected ways and relations need.
    let mut missing: Vec<i64> = Vec::new();
    for w in ways.iter().filter(|w| !w.tiles.is_empty()) {
        missing.extend(w.refs.iter().copied().filter(|&r| inside.find(r).is_none()));
    }
    missing.extend(extra_nodes.keys().copied().filter(|&r| inside.find(r).is_none()));
    missing.par_sort_unstable();
    missing.dedup();
    let wanted: Vec<usize> = ranges
        .iter()
        .filter(|(a, b, _)| { let k = missing.partition_point(|v| v < a); k < missing.len() && missing[k] <= *b })
        .map(|r| r.2)
        .collect();
    let outside: FxHashMap<i64, ([i32; 2], Tags)> = wanted
        .par_iter()
        .map(|&i| -> Result<Vec<(i64, ([i32; 2], Tags))>> {
            let mut found = Vec::new();
            let Some(block) = decode(&data[i])? else { return Ok(found) };
            let table = block.raw_stringtable();
            each_node(&block, |id, x, y, tags| {
                if missing.binary_search(&id).is_ok() {
                    found.push((id, ([x, y], tags_of(table, tags))));
                }
            });
            Ok(found)
        })
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect();
    emit(format!("outside nodes: {} of {} found in {} blobs ({:.1} s)", outside.len(), missing.len(), wanted.len(), t0.elapsed().as_secs_f64()));

    // Per tile: its ways, the nodes they use, its POI and member nodes, its relations.
    let nt = grid.keys.len();
    let mut tile_ways: Vec<Vec<u32>> = vec![Vec::new(); nt];
    for (i, w) in ways.iter().enumerate() {
        for &t in &w.tiles {
            tile_ways[t as usize].push(i as u32);
        }
    }
    let mut tile_nodes: Vec<Vec<i64>> = vec![Vec::new(); nt];
    for &(i, ref tags) in &inside.tagged {
        if select::poi(tags) {
            let [x, y] = inside.xy[i as usize];
            for t in grid.tiles_of(x, y) {
                tile_nodes[t as usize].push(inside.ids[i as usize]);
            }
        }
    }
    for (&id, m) in &extra_nodes {
        for &t in m {
            tile_nodes[t as usize].push(id);
        }
    }
    let mut tile_rels: Vec<Vec<u32>> = vec![Vec::new(); nt];
    for (rid, m) in &rel_tiles {
        if let Some(&ri) = rel_at.get(rid) {
            for &t in m {
                tile_rels[t as usize].push(ri);
            }
        }
    }
    let tmp = PathBuf::from(format!("{}.part", out.display()));
    if tmp.exists() {
        std::fs::remove_dir_all(&tmp)?;
    }
    std::fs::create_dir_all(&tmp)?;
    let written: Vec<Option<(usize, Value)>> = (0..nt)
        .into_par_iter()
        .map(|t| -> Result<Option<(usize, Value)>> {
            if tile_ways[t].is_empty() {
                return Ok(None);
            }
            let mut ids = tile_nodes[t].clone();
            for &w in &tile_ways[t] {
                ids.extend_from_slice(&ways[w as usize].refs);
            }
            ids.sort_unstable();
            ids.dedup();
            let nodes: Vec<NodeOut> = ids
                .iter()
                .filter_map(|&id| match inside.find(id) {
                    Some(i) => Some(NodeOut { id, x: inside.xy[i][0], y: inside.xy[i][1], tags: inside.tags(i) }),
                    None => outside.get(&id).map(|(xy, tags)| NodeOut { id, x: xy[0], y: xy[1], tags }),
                })
                .collect();
            let wout: Vec<WayOut> = tile_ways[t].iter().map(|&w| { let w = &ways[w as usize]; WayOut { id: w.id, refs: &w.refs, tags: &w.tags } }).collect();
            let mut rs = tile_rels[t].clone();
            rs.sort_unstable_by_key(|&r| rels[r as usize].id);
            let members: Vec<Vec<MemberOut>> = rs
                .iter()
                .map(|&r| rels[r as usize].members.iter().map(|m| MemberOut { kind: m.kind, id: m.id, role: &m.role }).collect())
                .collect();
            let rout: Vec<RelationOut> = rs.iter().zip(&members).map(|(&r, m)| RelationOut { id: rels[r as usize].id, members: m, tags: &rels[r as usize].tags }).collect();
            let mut w = PbfWriter::new("earthng-mapbuilder");
            w.nodes(&nodes);
            w.ways(&wout);
            w.relations(&rout);
            let bytes = w.finish();
            let (x, y) = grid.keys[t];
            let file = format!("{x}_{y}.osm.pbf");
            std::fs::write(tmp.join(&file), &bytes)?;
            let sha = hex::encode(Sha256::digest(&bytes));
            Ok(Some((t, json!({
                "file": file, "cell": cell_box(x, y), "coverage": coverage(x, y), "bytes": bytes.len(),
                "sha256": sha, "nodes": nodes.len(), "ways": wout.len(), "relations": rout.len(),
            }))))
        })
        .collect::<Result<_>>()?;
    let mut tiles = Map::new();
    for (t, entry) in written.into_iter().flatten() {
        let (x, y) = grid.keys[t];
        tiles.insert(format!("{x}_{y}"), entry);
    }
    let seconds = (t0.elapsed().as_secs_f64() * 10.0).round() / 10.0;
    let mut index = Map::new();
    index.insert("cell".into(), json!(CELL));
    index.insert("buffer".into(), json!(BUFFER));
    index.insert("source".into(), json!(pbf.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()));
    index.insert("package_box".into(), json!(package_box));
    index.insert("select".into(), json!(select::VERSION));
    index.insert("tiles".into(), Value::Object(tiles));
    index.insert("seconds".into(), json!(seconds));
    index.insert("cutter".into(), json!("earthng-mapbuilder"));
    let index = Value::Object(index);
    let mut text = Vec::new();
    let mut ser = serde_json::Serializer::with_formatter(&mut text, serde_json::ser::PrettyFormatter::with_indent(b" "));
    serde::Serialize::serialize(&index, &mut ser)?;
    std::fs::write(tmp.join("index.json"), &text)?;
    std::fs::rename(&tmp, out).with_context(|| format!("publish {}", out.display()))?;
    let sizes: Vec<u64> = index["tiles"].as_object().unwrap().values().map(|t| t["bytes"].as_u64().unwrap()).collect();
    emit(format!("written {} tiles, {:.1} MB total ({seconds} s)", sizes.len(), sizes.iter().sum::<u64>() as f64 / 1048576.0));
    Ok(CutReport { index, seconds })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_rounding() {
        assert_eq!(round6(608.0 * CELL), 30.4);
        assert_eq!(coverage(608, 1006), [30.39, 50.29, 30.46, 50.36]);
        assert_eq!(cell_box(-1, -1), [-0.05, -0.05, 0.0, 0.0]);
    }

    #[test]
    fn grid_keeps_whole_coverages() {
        // the Kyiv spot package: 30 tiles
        let g = Grid::new([30.39, 50.29, 30.71, 50.56]);
        assert_eq!(g.keys.len(), 30);
        assert_eq!(g.keys[0], (608, 1006));
        // a point in the buffer between two cells belongs to both
        let t = g.tiles_of(304_500_000 + 50_000, 503_200_000);
        assert_eq!(t.len(), 2);
    }

    #[test]
    fn union_and_intersection() {
        let mut a: TSet = SmallVec::from_slice(&[1, 4, 9]);
        assert!(union_into(&mut a, &[2, 4, 10]));
        assert_eq!(a.as_slice(), &[1, 2, 4, 9, 10]);
        assert!(!union_into(&mut a, &[4, 9]));
        assert_eq!(intersect(&a, &[0, 2, 9, 11]).as_slice(), &[2, 9]);
    }
}
