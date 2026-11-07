//! fast_sources.read_ways for raw OSM tiles: the drivable ways, the foot bridges and the closed
//! man_made=bridge outlines the height solve needs, as pyosmium's SimpleHandler with locations
//! reads them.
//!
//! Per tile, in file order: a way's tags are looked up as osmium's Tags.get (the first pair of a
//! key), the first copy of a way id wins, a node's location is the last one stored for its id
//! and valid only within +-180 / +-90 degrees, coordinates in 1e-7 degrees (lon = x / 1e7 in
//! Python, as osmium divides). The tags go out as the way's own pairs, so Python's dict() of them
//! is the same. A road or foot bridge with a node of no location is Python's error: the whole
//! read is left to Python, which raises it.

use std::path::Path;

use anyhow::{Context, Result, bail};
use osmpbf::{Mmap, MmapBlob};
use rayon::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};

use crate::cut::{decode, header_box, phases};

pub const ROAD: u8 = 0;
pub const FOOT: u8 = 1;
pub const DECK: u8 = 2;

pub struct Rules {
    pub drivable: Vec<String>,
    /// fast_sources.FOOT_WIDTH's keys
    pub foot: Vec<String>,
}

/// One way kept, of one kind; nodes (ref, x, y) in 1e-7 degrees (a deck's refs are not used).
pub struct Way {
    pub kind: u8,
    pub id: i64,
    pub tags: Vec<(String, String)>,
    pub nodes: Vec<(i64, i32, i32)>,
}

struct Candidate {
    id: i64,
    deck: bool,
    /// ROAD, FOOT or none
    road: Option<u8>,
    tags: Vec<(String, String)>,
    refs: Vec<i64>,
}

fn get<'a>(tags: &'a [(String, String)], key: &str) -> Option<&'a str> {
    tags.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
}

fn none_or_no(v: Option<&str>) -> bool {
    matches!(v, None | Some("no"))
}

fn road_kind(tags: &[(String, String)], rules: &Rules) -> Option<u8> {
    let h = get(tags, "highway").unwrap_or("");
    if rules.drivable.iter().any(|d| d == h) || h.ends_with("_link") {
        return Some(ROAD);
    }
    // fast_sources.foot_bridge
    let foot = rules.foot.iter().any(|f| f == h)
        && !none_or_no(get(tags, "bridge"))
        && get(tags, "area") != Some("yes")
        && none_or_no(get(tags, "tunnel"))
        && none_or_no(get(tags, "indoor"));
    foot.then_some(FOOT)
}

fn valid(x: i32, y: i32) -> bool {
    (-1_800_000_000..=1_800_000_000).contains(&x) && (-900_000_000..=900_000_000).contains(&y)
}

/// The kept ways of one tile in read_ways' dict order: roads, feet and decks, each in the order
/// they were first stored.
pub fn read(pbf: &Path, rules: &Rules) -> Result<Vec<Way>> {
    let mmap = unsafe { Mmap::from_path(pbf) }.with_context(|| format!("open {}", pbf.display()))?;
    let (_, sorted) = header_box(&mmap)?;
    let data: Vec<MmapBlob> = mmap
        .blob_iter()
        .filter_map(|b| match b {
            Ok(b) if matches!(b.get_type(), osmpbf::BlobType::OsmData) => Some(Ok(b)),
            Ok(_) => None,
            Err(e) => Some(Err(e)),
        })
        .collect::<std::result::Result<_, _>>()?;
    let [node_blobs, way_blobs, _] = phases(&data, sorted)?;
    if !sorted {
        // osmium reads in file order, a way seeing only the nodes before it: this reads every node
        // first, the same only when no node comes after a way (tiles osmium cut have no Sort flag)
        let mixed = way_blobs.first().is_some_and(|&w| node_blobs.last().is_some_and(|&n| n >= w));
        if mixed {
            bail!("{} has nodes after ways", pbf.display());
        }
    }
    let candidates: Vec<Candidate> = way_blobs
        .par_iter()
        .map(|&i| -> Result<Vec<Candidate>> {
            let mut found = Vec::new();
            let Some(block) = decode(&data[i])? else { return Ok(found) };
            let table = block.raw_stringtable();
            let text = |i: u32| String::from_utf8_lossy(&table[i as usize]).into_owned();
            for g in block.groups() {
                for w in g.ways() {
                    // cheap test on the raw pairs before any string is made
                    let mut wanted = false;
                    for (k, _) in w.raw_tags() {
                        let k = &table[k as usize][..];
                        wanted |= k == b"highway" || k == b"man_made";
                    }
                    if !wanted {
                        continue;
                    }
                    let tags: Vec<(String, String)> = w.raw_tags().map(|(k, v)| (text(k), text(v))).collect();
                    let deck = get(&tags, "man_made") == Some("bridge");
                    let road = road_kind(&tags, rules);
                    if deck || road.is_some() {
                        found.push(Candidate { id: w.id(), deck, road, tags, refs: w.refs().collect() });
                    }
                }
            }
            Ok(found)
        })
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect();
    let needed: FxHashSet<i64> = candidates.iter().flat_map(|c| c.refs.iter().copied()).collect();
    let parts: Vec<Vec<(i64, i32, i32)>> = node_blobs
        .par_iter()
        .map(|&i| -> Result<_> {
            let mut at = Vec::new();
            let Some(block) = decode(&data[i])? else { return Ok(at) };
            for g in block.groups() {
                for n in g.dense_nodes() {
                    if needed.contains(&n.id()) {
                        at.push((n.id(), n.decimicro_lon(), n.decimicro_lat()));
                    }
                }
                for n in g.nodes() {
                    if needed.contains(&n.id()) {
                        at.push((n.id(), n.decimicro_lon(), n.decimicro_lat()));
                    }
                }
            }
            Ok(at)
        })
        .collect::<Result<_>>()?;
    let mut location: FxHashMap<i64, (i32, i32)> = FxHashMap::default();
    location.reserve(needed.len());
    for at in parts {
        location.extend(at.into_iter().map(|(id, x, y)| (id, (x, y))));
    }
    let at = |id: &i64| location.get(id).copied().filter(|&(x, y)| valid(x, y));
    // read_ways' handler, way by way in file order
    let (mut roads, mut feet, mut decks) = (Vec::new(), Vec::new(), Vec::new());
    let (mut road_ids, mut foot_ids, mut deck_ids) = (FxHashSet::default(), FxHashSet::default(), FxHashSet::default());
    for c in candidates {
        if c.deck && !deck_ids.contains(&c.id) && !c.refs.is_empty() && c.refs[0] == c.refs[c.refs.len() - 1] {
            let ring: Vec<(i64, i32, i32)> = c.refs.iter().filter_map(|r| at(r).map(|(x, y)| (*r, x, y))).collect();
            if ring.len() == c.refs.len() && ring.len() >= 4 {
                deck_ids.insert(c.id);
                decks.push(Way { kind: DECK, id: c.id, tags: Vec::new(), nodes: ring });
            }
        }
        let Some(kind) = c.road else { continue };
        let (ids, list) = if kind == ROAD { (&mut road_ids, &mut roads) } else { (&mut foot_ids, &mut feet) };
        if ids.contains(&c.id) || get(&c.tags, "area") == Some("yes") || get(&c.tags, "access") == Some("no") {
            continue;
        }
        let nodes: Vec<(i64, i32, i32)> = c.refs.iter().filter_map(|r| at(r).map(|(x, y)| (*r, x, y))).collect();
        if nodes.len() != c.refs.len() {
            bail!("incomplete OSM way {}", c.id);
        }
        if nodes.len() >= 2 {
            ids.insert(c.id);
            list.push(Way { kind, id: c.id, tags: c.tags, nodes });
        }
    }
    roads.extend(feet);
    roads.extend(decks);
    Ok(roads)
}

/// Every tile's ways (tiles in order) into one file:
/// 'EWY1', u32 count, then count x u32 tile, count x u8 kind, count x i64 id, count x u32 nodes,
/// u64 total, total x i64 ref, total x i32 x, total x i32 y, then the JSON list of every way's
/// tags ([[key, value], ...], [] for a deck), all little-endian.
pub fn write(tiles: &[Vec<Way>], out: &Path) -> Result<usize> {
    let count: usize = tiles.iter().map(Vec::len).sum();
    let total: usize = tiles.iter().flatten().map(|w| w.nodes.len()).sum();
    let mut b = Vec::with_capacity(16 + count * 17 + total * 16);
    b.extend_from_slice(b"EWY1");
    b.extend_from_slice(&(count as u32).to_le_bytes());
    for (t, ways) in tiles.iter().enumerate() {
        for _ in ways {
            b.extend_from_slice(&(t as u32).to_le_bytes());
        }
    }
    b.extend(tiles.iter().flatten().map(|w| w.kind));
    for w in tiles.iter().flatten() {
        b.extend_from_slice(&w.id.to_le_bytes());
    }
    for w in tiles.iter().flatten() {
        b.extend_from_slice(&(w.nodes.len() as u32).to_le_bytes());
    }
    b.extend_from_slice(&(total as u64).to_le_bytes());
    for w in tiles.iter().flatten() {
        for n in &w.nodes {
            b.extend_from_slice(&n.0.to_le_bytes());
        }
    }
    for w in tiles.iter().flatten() {
        for n in &w.nodes {
            b.extend_from_slice(&n.1.to_le_bytes());
        }
    }
    for w in tiles.iter().flatten() {
        for n in &w.nodes {
            b.extend_from_slice(&n.2.to_le_bytes());
        }
    }
    let tags: Vec<&Vec<(String, String)>> = tiles.iter().flatten().map(|w| &w.tags).collect();
    serde_json::to_writer(&mut b, &tags)?;
    std::fs::write(out, b).with_context(|| format!("write {}", out.display()))?;
    Ok(count)
}
