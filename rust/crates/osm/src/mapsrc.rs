//! What earthng/build_map.py reads from a country PBF: settlement nodes and main roads.
//!
//! Same selection as its osmium TagFilter pass: nodes tagged place=city/town/village/hamlet/suburb/
//! neighbourhood with all their tags, and ways tagged highway=motorway/trunk/primary/secondary/tertiary
//! (or their _link) whose every node has a location, with coordinates in 1e-7 degrees divided as
//! osmium divides them. Both in file order. Ways are read first (one pass over the way blobs), then
//! every node blob once for place nodes and the nodes those ways need.

use std::io::Write;
use std::path::Path;
use std::time::Instant;

use anyhow::{Context, Result};
use osmpbf::{Mmap, MmapBlob};
use rayon::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};

use crate::cut::{decode, header_box, phases};

pub const PLACES: [&str; 6] = ["city", "town", "village", "hamlet", "suburb", "neighbourhood"];
const ROADS: [(&str, u8); 5] = [("motorway", 1), ("trunk", 1), ("primary", 1), ("secondary", 2), ("tertiary", 3)];

/// build_map.ROAD_RANK of a highway value, with or without _link.
pub fn rank(highway: &[u8]) -> Option<u8> {
    let base = highway.strip_suffix(b"_link").unwrap_or(highway);
    ROADS.iter().find(|(k, _)| k.as_bytes() == base).map(|&(_, r)| r)
}

fn passes_filter(key: &[u8], value: &[u8]) -> bool {
    (key == b"place" && PLACES.iter().any(|p| p.as_bytes() == value))
        || (key == b"highway" && rank(value).is_some() && value != b"_link")
}

pub struct Road {
    pub rank: u8,
    pub refs: Vec<i64>,
}

pub struct Place {
    pub x: i32,
    pub y: i32,
    pub tags: Vec<(String, String)>,
}

pub struct Extract {
    pub places: Vec<Place>,
    /// (rank, [(lon, lat)]) of every road with all its nodes found
    pub roads: Vec<(u8, Vec<(f64, f64)>)>,
    pub skipped: usize,
}

/// osmium's Location::lon()/lat(): the int coordinate over 1e7, as double.
pub fn degrees(v: i32) -> f64 {
    v as f64 / 1e7
}

fn text(table: &[Vec<u8>], i: usize) -> String {
    String::from_utf8_lossy(&table[i]).into_owned()
}

pub fn extract(pbf: &Path, emit: &(dyn Fn(String) + Sync)) -> Result<Extract> {
    let t0 = Instant::now();
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

    let roads: Vec<Road> = way_blobs
        .par_iter()
        .map(|&i| -> Result<Vec<Road>> {
            let mut found = Vec::new();
            let Some(block) = decode(&data[i])? else { return Ok(found) };
            let table = block.raw_stringtable();
            for g in block.groups() {
                for w in g.ways() {
                    // osmium's Tags::get: the first highway tag; the filter wants any matching pair
                    let mut first = None;
                    let mut matched = false;
                    for (k, v) in w.raw_tags() {
                        let (k, v) = (&table[k as usize][..], &table[v as usize][..]);
                        if k == b"highway" && first.is_none() {
                            first = Some(v);
                        }
                        matched |= passes_filter(k, v);
                    }
                    if !matched {
                        continue;
                    }
                    if let Some(r) = first.and_then(rank) {
                        found.push(Road { rank: r, refs: w.refs().collect() });
                    }
                }
            }
            Ok(found)
        })
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect();
    let needed: FxHashSet<i64> = roads.iter().flat_map(|r| r.refs.iter().copied()).collect();
    emit(format!("map: {} roads, {} road nodes ({:.1} s)", roads.len(), needed.len(), t0.elapsed().as_secs_f64()));

    let parts: Vec<(Vec<(i64, i32, i32)>, Vec<Place>)> = node_blobs
        .par_iter()
        .map(|&i| -> Result<_> {
            let (mut at, mut places) = (Vec::new(), Vec::new());
            let Some(block) = decode(&data[i])? else { return Ok((at, places)) };
            let table = block.raw_stringtable();
            let mut visit = |id: i64, x: i32, y: i32, tags: &mut dyn Iterator<Item = (usize, usize)>| {
                if needed.contains(&id) {
                    at.push((id, x, y));
                }
                let mut place = false;
                let mut pairs = Vec::new();
                for (k, v) in tags {
                    place |= &table[k][..] == b"place" && PLACES.iter().any(|p| p.as_bytes() == &table[v][..]);
                    pairs.push((k, v));
                }
                if place {
                    places.push(Place { x, y, tags: pairs.into_iter().map(|(k, v)| (text(table, k), text(table, v))).collect() });
                }
            };
            for g in block.groups() {
                for n in g.dense_nodes() {
                    let mut tags = n.raw_tags().map(|(k, v)| (k as usize, v as usize));
                    visit(n.id(), n.decimicro_lon(), n.decimicro_lat(), &mut tags);
                }
                for n in g.nodes() {
                    let mut tags = n.raw_tags().map(|(k, v)| (k as usize, v as usize));
                    visit(n.id(), n.decimicro_lon(), n.decimicro_lat(), &mut tags);
                }
            }
            Ok((at, places))
        })
        .collect::<Result<_>>()?;
    let mut location: FxHashMap<i64, (i32, i32)> = FxHashMap::default();
    location.reserve(needed.len());
    let mut places = Vec::new();
    for (at, found) in parts {
        // osmium's location index keeps the last location stored for an id
        location.extend(at.into_iter().map(|(id, x, y)| (id, (x, y))));
        places.extend(found);
    }
    drop(needed);

    let mut skipped = 0;
    let roads: Vec<(u8, Vec<(f64, f64)>)> = roads
        .into_iter()
        .filter_map(|r| {
            let coords: Option<Vec<(f64, f64)>> =
                r.refs.iter().map(|id| location.get(id).map(|&(x, y)| (degrees(x), degrees(y)))).collect();
            if coords.is_none() {
                skipped += 1;
            }
            coords.map(|c| (r.rank, c))
        })
        .collect();
    emit(format!("map: {} places, {} roads with every node, {} without ({:.1} s)", places.len(), roads.len(), skipped,
                 t0.elapsed().as_secs_f64()));
    Ok(Extract { places, roads, skipped })
}

/// places: one JSON line per place, [lat, lon, [[key, value], ...]] in file order.
/// roads: per road u8 rank, u32 point count, then (lon, lat) f64 pairs, little-endian.
pub fn write(extract: &Extract, places: &Path, roads: &Path) -> Result<()> {
    let mut out = std::io::BufWriter::new(std::fs::File::create(places)?);
    for p in &extract.places {
        let tags: Vec<[&str; 2]> = p.tags.iter().map(|(k, v)| [k.as_str(), v.as_str()]).collect();
        serde_json::to_writer(&mut out, &(degrees(p.y), degrees(p.x), tags))?;
        out.write_all(b"\n")?;
    }
    out.flush()?;
    let mut out = std::io::BufWriter::new(std::fs::File::create(roads)?);
    for (rank, coords) in &extract.roads {
        out.write_all(&[*rank])?;
        out.write_all(&(coords.len() as u32).to_le_bytes())?;
        for (lon, lat) in coords {
            out.write_all(&lon.to_le_bytes())?;
            out.write_all(&lat.to_le_bytes())?;
        }
    }
    out.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ranks_follow_build_map() {
        assert_eq!(rank(b"primary"), Some(1));
        assert_eq!(rank(b"secondary_link"), Some(2));
        assert_eq!(rank(b"tertiary"), Some(3));
        assert_eq!(rank(b"residential"), None);
        assert_eq!(rank(b"_link"), None);
        assert!(passes_filter(b"place", b"town"));
        assert!(!passes_filter(b"place", b"locality"));
    }
}
