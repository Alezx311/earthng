//! fast_sources.Store.build_scene of one raw OSM tile, written as write_scene writes it.
//!
//! Python still runs osmium's area assembly (one pass, area callback only) and hands over every
//! area in callback order: a way area of one outer ring as its id alone (its ring is the way's,
//! started at the smallest location and turned counter-clockwise, as osmium builds it), anything
//! else as osmium's WKB and tags. The rest is here: nodes, ways, the tag rules, the retail
//! duplicates and link_parts through shapely's GEOS, metres through pyproj's PROJ.
//! What this does not cover goes back to Python (Outcome::Python), which builds the tile itself.

use std::collections::HashMap;
use std::io::Read;
use std::path::PathBuf;

use anyhow::{Context, Result, bail};
use osmpbf::{BlobDecode, Mmap};
use serde::Deserialize;

use crate::geos::{self, Geom, Shape, Tree};
use crate::numeric::{number, py_float, py_min};
use crate::proj;
use crate::pytext;
use crate::rules::{Get, Raw, Rules, Tags};

#[derive(Deserialize)]
pub struct SceneTask {
    pub geos: PathBuf,
    pub proj: PathBuf,
    pub proj_data: PathBuf,
    pub pbf: PathBuf,
    pub crs: String,
    pub origin: [f64; 2],
    pub rules: Rules,
    /// (fid, tags as write_scene's JSON, lon, lat) of venues.located()
    pub venues: Vec<(i64, String, f64, f64)>,
}

pub enum Outcome {
    Done(Vec<u8>, usize),
    Python(String),
}

/// One area of osmium's, as Python's pass hands it over.
pub struct Area {
    pub id: i64,
    pub how: AreaFrom,
}

pub enum AreaFrom {
    /// a way area with one outer ring and no inner: the way gives tags and ring
    Ring,
    /// tags as osmium's TagList pairs, and its multipolygon WKB
    Wkb(Vec<(String, String)>, Vec<u8>),
    /// create_multipolygon raised
    Broken,
}

/// Python's pass: 'EAR1', u32 count, then per area i64 id, u8 how (0 ring, 1 WKB, 2 broken) and
/// for 1: u32 length + tags JSON list of pairs, u32 length + WKB.
pub fn read_areas(data: &[u8]) -> Result<Vec<Area>> {
    if data.get(..4) != Some(b"EAR1") {
        bail!("not an area stream");
    }
    let mut at = 4;
    let mut take = |n: usize| -> Result<&[u8]> {
        let s = data.get(at..at + n).context("area stream cut short")?;
        at += n;
        Ok(s)
    };
    let count = u32::from_le_bytes(take(4)?.try_into()?) as usize;
    let mut out = Vec::with_capacity(count);
    for _ in 0..count {
        let id = i64::from_le_bytes(take(8)?.try_into()?);
        let how = match take(1)?[0] {
            0 => AreaFrom::Ring,
            1 => {
                let n = u32::from_le_bytes(take(4)?.try_into()?) as usize;
                let tags: Vec<(String, String)> = serde_json::from_slice(take(n)?)?;
                let n = u32::from_le_bytes(take(4)?.try_into()?) as usize;
                AreaFrom::Wkb(tags, take(n)?.to_vec())
            }
            2 => AreaFrom::Broken,
            k => bail!("area kind {k}"),
        };
        out.push(Area { id, how });
    }
    Ok(out)
}

/// A geometry in lon/lat, before the frame.
#[derive(Clone)]
enum Geo {
    Point([f64; 2]),
    Line(Vec<[f64; 2]>),
    /// polygons of rings, as osmium's create_multipolygon
    Multi(Vec<Vec<Vec<[f64; 2]>>>),
}

impl Geo {
    fn each(&self, f: &mut impl FnMut([f64; 2])) {
        match self {
            Geo::Point(p) => f(*p),
            Geo::Line(l) => l.iter().for_each(|p| f(*p)),
            Geo::Multi(m) => m.iter().flatten().flatten().for_each(|p| f(*p)),
        }
    }

    /// Little-endian 2D WKB, coordinates from next() in each() order.
    fn wkb(&self, next: &mut impl FnMut([f64; 2]) -> [f64; 2]) -> Vec<u8> {
        let mut out = Vec::new();
        let head = |out: &mut Vec<u8>, kind: u32| {
            out.push(1);
            out.extend_from_slice(&kind.to_le_bytes());
        };
        let pt = |out: &mut Vec<u8>, p: [f64; 2]| {
            out.extend_from_slice(&p[0].to_le_bytes());
            out.extend_from_slice(&p[1].to_le_bytes());
        };
        match self {
            Geo::Point(p) => {
                head(&mut out, 1);
                pt(&mut out, next(*p));
            }
            Geo::Line(l) => {
                head(&mut out, 2);
                out.extend_from_slice(&(l.len() as u32).to_le_bytes());
                l.iter().for_each(|p| pt(&mut out, next(*p)));
            }
            Geo::Multi(m) => {
                head(&mut out, 6);
                out.extend_from_slice(&(m.len() as u32).to_le_bytes());
                for poly in m {
                    head(&mut out, 3);
                    out.extend_from_slice(&(poly.len() as u32).to_le_bytes());
                    for ring in poly {
                        out.extend_from_slice(&(ring.len() as u32).to_le_bytes());
                        ring.iter().for_each(|p| pt(&mut out, next(*p)));
                    }
                }
            }
        }
        out
    }

    fn geos(&self) -> Result<Geom> {
        geos::from_wkb(&self.wkb(&mut |p| p))
    }
}

/// osmium's multipolygon WKB (either byte order) as Geo::Multi.
fn parse_multipolygon(w: &[u8]) -> Result<Geo> {
    let mut at = 0usize;
    let byte = |at: &mut usize| -> Result<u8> {
        let b = *w.get(*at).context("WKB cut short")?;
        *at += 1;
        Ok(b)
    };
    let u32_at = |at: &mut usize, le: bool| -> Result<u32> {
        let b: [u8; 4] = w.get(*at..*at + 4).context("WKB cut short")?.try_into()?;
        *at += 4;
        Ok(if le { u32::from_le_bytes(b) } else { u32::from_be_bytes(b) })
    };
    let f64_at = |at: &mut usize, le: bool| -> Result<f64> {
        let b: [u8; 8] = w.get(*at..*at + 8).context("WKB cut short")?.try_into()?;
        *at += 8;
        Ok(if le { f64::from_le_bytes(b) } else { f64::from_be_bytes(b) })
    };
    let le = byte(&mut at)? == 1;
    if u32_at(&mut at, le)? != 6 {
        bail!("not a 2D multipolygon");
    }
    let n = u32_at(&mut at, le)?;
    let mut polys = Vec::with_capacity(n as usize);
    for _ in 0..n {
        let ple = byte(&mut at)? == 1;
        if u32_at(&mut at, ple)? != 3 {
            bail!("not a 2D polygon");
        }
        let rings = u32_at(&mut at, ple)?;
        let mut poly = Vec::with_capacity(rings as usize);
        for _ in 0..rings {
            let k = u32_at(&mut at, ple)?;
            let mut ring = Vec::with_capacity(k as usize);
            for _ in 0..k {
                ring.push([f64_at(&mut at, ple)?, f64_at(&mut at, ple)?]);
            }
            poly.push(ring);
        }
        polys.push(poly);
    }
    Ok(Geo::Multi(polys))
}

/// osmium's Location::valid()
fn valid(x: i32, y: i32) -> bool {
    (-1_800_000_000..=1_800_000_000).contains(&x) && (-900_000_000..=900_000_000).contains(&y)
}

fn degrees(v: i32) -> f64 {
    v as f64 / 1e7
}

/// The ring osmium's assembler makes of a closed way it reads as one outer ring: consecutive
/// repeats dropped, started at the smallest location (x, then y), counter-clockwise. A way whose
/// ring comes back to a location (osmium may split or trim it) is not covered.
fn way_ring(refs: &[i64], at: &HashMap<i64, (i32, i32)>) -> Result<Vec<[f64; 2]>, String> {
    let mut pts: Vec<(i32, i32)> = Vec::with_capacity(refs.len());
    for r in refs {
        let &(x, y) = at.get(r).ok_or("a ring node has no location")?;
        if !valid(x, y) {
            return Err("a ring node has an invalid location".into());
        }
        if pts.last() != Some(&(x, y)) {
            pts.push((x, y));
        }
    }
    if pts.len() < 4 || pts.first() != pts.last() {
        return Err("a way area that is not a closed ring".into());
    }
    pts.pop();
    let mut seen = pts.clone();
    seen.sort_unstable();
    if seen.windows(2).any(|w| w[0] == w[1]) {
        return Err("a way ring that comes back to a location".into());
    }
    let k = (0..pts.len()).min_by_key(|&i| pts[i]).unwrap();
    pts.rotate_left(k);
    let n = pts.len();
    let twice: i128 = (0..n)
        .map(|i| {
            let (a, b) = (pts[i], pts[(i + 1) % n]);
            a.0 as i128 * b.1 as i128 - b.0 as i128 * a.1 as i128
        })
        .sum();
    if twice == 0 {
        return Err("a way ring without area".into());
    }
    if twice < 0 {
        pts[1..].reverse();
    }
    pts.push(pts[0]);
    Ok(pts.into_iter().map(|(x, y)| [degrees(x), degrees(y)]).collect())
}

enum TagsOf {
    /// shared: an area's dict is its building's, its site's and its retail point's
    Shared(usize),
    /// write_scene's JSON as Python made it (venues)
    Json(String),
}

struct Rec {
    fid: i64,
    kind: String,
    tags: TagsOf,
    geo: Geo,
}

struct Way {
    tags: Vec<(String, String)>,
    refs: Vec<i64>,
}

/// fast_sources.lifted: None where this cannot answer for Python's float()
fn lifted(t: &Tags) -> Option<f64> {
    match t.get("min_height").filter(|v| !v.is_empty()) {
        Some(v) => Some(py_float(v).ok()?.unwrap_or(0.0)),
        None => match t.get("building:min_level") {
            None => Some(0.0),
            Some(v) => Some(py_float(v).ok()?.map(|f| 3.0 * f).unwrap_or(0.0)),
        },
    }
}

fn tags_json(t: &Tags) -> String {
    let pairs: Vec<[&str; 2]> = t.0.iter().map(|(k, v)| [k.as_str(), v.as_str()]).collect();
    serde_json::to_string(&pairs).unwrap()
}

const RETAIL: [&str; 5] = ["fuel", "grocery", "fast_food", "post", "service"];

pub fn build(task: &SceneTask, areas: Vec<Area>) -> Result<Outcome> {
    geos::load(&task.geos)?;
    proj::load(&task.proj)?;
    let rules = &task.rules;
    let mut arena: Vec<Tags> = Vec::new();

    // ---- the tile: node locations, points, lines and the ways the area rings need ----
    let ring_ways: std::collections::HashSet<i64> =
        areas.iter().filter(|a| matches!(a.how, AreaFrom::Ring)).map(|a| a.id / 2).collect();
    let mmap = unsafe { Mmap::from_path(&task.pbf) }.with_context(|| format!("open {}", task.pbf.display()))?;
    let mut at: HashMap<i64, (i32, i32)> = HashMap::new();
    let mut marks: Vec<Rec> = Vec::new();
    let mut pending: Vec<(i64, &'static str, Tags, Vec<i64>)> = Vec::new();
    let mut ways: HashMap<i64, Way> = HashMap::new();
    let point_keys: std::collections::HashSet<&str> = rules.point_keys.iter().map(|s| s.as_str()).collect();
    for blob in mmap.blob_iter() {
        let BlobDecode::OsmData(block) = blob?.decode()? else { continue };
        let table: Vec<&str> = match block.raw_stringtable().iter().map(|s| std::str::from_utf8(s)).collect() {
            Ok(t) => t,
            Err(_) => return Ok(Outcome::Python("a tag that is not UTF-8".into())),
        };
        let mut node = |id: i64, x: i32, y: i32, raw: &mut dyn Iterator<Item = (u32, u32)>| {
            // osmium's location index keeps the last location stored for an id
            at.insert(id, (x, y));
            let pairs: Vec<(&str, &str)> = raw.map(|(k, v)| (table[k as usize], table[v as usize])).collect();
            // osmium.filter.KeyFilter(*fast_style.point_keys()) on nodes
            if !pairs.iter().any(|(k, _)| point_keys.contains(k)) {
                return;
            }
            let tags = Tags::dict(&pairs);
            if let Some(kind) = rules.point_kind(&tags) {
                if valid(x, y) {
                    arena.push(rules.enriched(&tags));
                    marks.push(Rec {
                        fid: -(1_000_000_000_000 + id),
                        kind: kind.into(),
                        tags: TagsOf::Shared(arena.len() - 1),
                        geo: Geo::Point([degrees(x), degrees(y)]),
                    });
                }
            }
        };
        for g in block.groups() {
            for n in g.dense_nodes() {
                let mut raw = n.raw_tags().map(|(k, v)| (k as u32, v as u32));
                node(n.id(), n.decimicro_lon(), n.decimicro_lat(), &mut raw);
            }
            for n in g.nodes() {
                let mut raw = n.raw_tags().map(|(k, v)| (k, v));
                node(n.id(), n.decimicro_lon(), n.decimicro_lat(), &mut raw);
            }
            for w in g.ways() {
                let pairs: Vec<(&str, &str)> = w.raw_tags().map(|(k, v)| (table[k as usize], table[v as usize])).collect();
                let raw = Raw(&pairs);
                if let Some(kind) = rules.line_kind(&raw) {
                    let tags = if kind == "rail" { rules.rail_tags(&raw) } else { Tags::dict(&pairs) };
                    pending.push((w.id(), kind, tags, w.refs().collect()));
                }
                if ring_ways.contains(&w.id()) {
                    let tags = pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
                    ways.insert(w.id(), Way { tags, refs: w.refs().collect() });
                }
            }
        }
    }
    let mut lines: Vec<Rec> = Vec::new();
    'line: for (id, kind, tags, refs) in pending {
        let mut coords = Vec::with_capacity(refs.len());
        for r in &refs {
            match at.get(r) {
                Some(&(x, y)) if valid(x, y) => coords.push([degrees(x), degrees(y)]),
                _ => continue 'line, // osmium.InvalidLocationError: the way is left out
            }
        }
        if coords.len() >= 2 {
            arena.push(tags);
            lines.push(Rec { fid: -id, kind: kind.into(), tags: TagsOf::Shared(arena.len() - 1), geo: Geo::Line(coords) });
        }
    }

    // ---- areas, in osmium's callback order ----
    let mut found: Vec<Rec> = Vec::new();
    let mut retail_areas: Vec<(i64, &'static str, usize, Geo)> = Vec::new();
    for area in &areas {
        let pairs: Vec<(&str, &str)> = match &area.how {
            AreaFrom::Broken => continue, // its create_multipolygon raised: Python skips it
            AreaFrom::Ring => match ways.get(&(area.id / 2)) {
                Some(w) => w.tags.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect(),
                None => return Ok(Outcome::Python(format!("area {} without its way", area.id))),
            },
            AreaFrom::Wkb(t, _) => t.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect(),
        };
        let mut tags = rules.enriched(&Tags::dict(&pairs));
        let point_kind = rules.retail_kind(&tags);
        let mut kind: Option<&str> = if !matches!(tags.get("building"), None | Some("no")) {
            Some("building")
        } else if tags.get("natural") == Some("water") || tags.get("waterway") == Some("riverbank") {
            Some("water")
        } else {
            None
        };
        if kind.is_none() && !matches!(tags.get("building:part"), None | Some("no")) {
            kind = Some("building");
            tags.set("e2r_part", "1");
        }
        if kind.is_none() {
            kind = rules.ground_kind(&tags);
        }
        if kind.is_none() && point_kind.is_none() {
            continue;
        }
        let geo = match &area.how {
            AreaFrom::Ring => match way_ring(&ways[&(area.id / 2)].refs, &at) {
                Ok(ring) => Geo::Multi(vec![vec![ring]]),
                Err(why) => return Ok(Outcome::Python(format!("way {}: {why}", area.id / 2))),
            },
            AreaFrom::Wkb(_, w) => parse_multipolygon(w)?,
            AreaFrom::Broken => unreachable!(),
        };
        arena.push(tags);
        let shared = arena.len() - 1;
        if let Some(kind) = kind {
            found.push(Rec { fid: area.id, kind: kind.into(), tags: TagsOf::Shared(shared), geo: geo.clone() });
        }
        if let Some(pk) = point_kind {
            // never empty: osmium made it
            retail_areas.push((-(2_000_000_000_000 + area.id), pk, shared, geo.clone()));
            found.push(Rec { fid: -(3_000_000_000_000 + area.id), kind: format!("{pk}_site"), tags: TagsOf::Shared(shared), geo });
        }
    }
    lines.extend(marks);

    // ---- a business mapped both as a node and as its site: keep the node ----
    let shared = |t: &TagsOf| match t {
        TagsOf::Shared(i) => *i,
        TagsOf::Json(_) => unreachable!(),
    };
    let nodes: Vec<(&str, String, Option<String>, Geom)> = lines
        .iter()
        .filter(|r| RETAIL.contains(&r.kind.as_str()))
        .filter_map(|r| {
            let t = &arena[shared(&r.tags)];
            let brand = t.get("e2r_brand").filter(|b| !b.is_empty())?;
            Some((r.kind.as_str(), brand.to_string(), t.get("e2r_post_type").map(String::from), r.geo.clone()))
        })
        .map(|(k, b, p, g)| Ok((k, b, p, g.geos()?)))
        .collect::<Result<_>>()?;
    let node_geoms: Vec<&Geom> = nodes.iter().map(|n| &n.3).collect();
    let tree = if nodes.is_empty() { None } else { Some(Tree::new(&node_geoms)?) };
    let mut kept = Vec::new();
    for (ident, kind, t, geo) in &retail_areas {
        let tags = &arena[*t];
        let g = geo.geos()?;
        let mut duplicate = false;
        if let (Some(brand), Some(tree)) = (tags.get("e2r_brand").filter(|b| !b.is_empty()), &tree) {
            for i in tree.query(&g)? {
                let n = &nodes[i];
                if n.0 == *kind && n.1 == brand && n.2.as_deref() == tags.get("e2r_post_type") && g.covers(&n.3)? {
                    duplicate = true;
                    break;
                }
            }
        }
        if !duplicate {
            let p = g.point_on_surface()?.coords()?[0];
            kept.push(Rec { fid: *ident, kind: kind.to_string(), tags: TagsOf::Shared(*t), geo: Geo::Point(p) });
        }
    }
    drop(tree);
    drop(nodes);
    lines.extend(kept);

    if let Err(why) = link_parts(&found, &mut arena, rules) {
        return Ok(Outcome::Python(why));
    }
    for (fid, tags, lon, lat) in &task.venues {
        lines.push(Rec { fid: *fid, kind: "venue".into(), tags: TagsOf::Json(tags.clone()), geo: Geo::Point([*lon, *lat]) });
    }
    found.extend(lines);
    found.sort_by_key(|r| r.fid);
    if found.windows(2).any(|w| w[0].fid == w[1].fid) {
        return Ok(Outcome::Python("two records with one id".into()));
    }

    // ---- shapely.make_valid(shapely.transform(geoms, frame.local)) ----
    let (mut xs, mut ys) = (Vec::new(), Vec::new());
    for r in &found {
        r.geo.each(&mut |p| {
            xs.push(p[0]);
            ys.push(p[1]);
        });
    }
    proj::Forward::new(&task.crs, &task.proj_data)?.transform(&mut xs, &mut ys)?;
    let [cx, cy] = task.origin;
    let mut out = Vec::with_capacity(64 << 20);
    out.extend_from_slice(b"ESC1");
    out.extend_from_slice(&(found.len() as u32).to_le_bytes());
    let mut k = 0usize;
    for r in &found {
        let local = r.geo.wkb(&mut |_| {
            let p = [xs[k] - cx, ys[k] - cy];
            k += 1;
            p
        });
        let wkb = geos::from_wkb(&local)?.make_valid()?.wkb()?;
        let tags = match &r.tags {
            TagsOf::Shared(i) => tags_json(&arena[*i]),
            TagsOf::Json(s) => s.clone(),
        };
        out.extend_from_slice(&r.fid.to_le_bytes());
        out.extend_from_slice(&(r.kind.len() as u16).to_le_bytes());
        out.extend_from_slice(r.kind.as_bytes());
        out.extend_from_slice(&(tags.len() as u32).to_le_bytes());
        out.extend_from_slice(tags.as_bytes());
        out.extend_from_slice(&(wkb.len() as u32).to_le_bytes());
        out.extend_from_slice(&wkb);
    }
    Ok(Outcome::Done(out, found.len()))
}

/// fast_sources.link_parts over the area records, in their order (part areas add up in it).
fn link_parts(found: &[Rec], arena: &mut [Tags], rules: &Rules) -> Result<(), String> {
    let id = |r: &Rec| match r.tags {
        TagsOf::Shared(i) => i,
        TagsOf::Json(_) => unreachable!(),
    };
    let parts: Vec<&Rec> = found.iter().filter(|r| r.kind == "building" && arena[id(r)].get("e2r_part").is_some_and(|v| !v.is_empty())).collect();
    if parts.is_empty() {
        return Ok(());
    }
    let fail = |e: anyhow::Error| e.to_string();
    let outlines: Vec<&Rec> = found.iter().filter(|r| r.kind == "building" && !arena[id(r)].get("e2r_part").is_some_and(|v| !v.is_empty())).collect();
    let outline_geoms: Vec<Geom> = outlines.iter().map(|r| r.geo.geos()).collect::<Result<_>>().map_err(fail)?;
    let outline_area: Vec<f64> = outline_geoms.iter().map(|g| g.area()).collect::<Result<_>>().map_err(fail)?;
    let refs: Vec<&Geom> = outline_geoms.iter().collect();
    let tree = if outlines.is_empty() { None } else { Some(Tree::new(&refs).map_err(fail)?) };
    let mut covered: HashMap<i64, f64> = HashMap::new();
    let mut under: HashMap<i64, f64> = HashMap::new();
    for part in parts {
        let geometry = part.geo.geos().map_err(fail)?;
        let inside = geometry.point_on_surface().map_err(fail)?;
        let mut holder: Option<usize> = None;
        if let Some(tree) = &tree {
            for n in tree.query(&inside).map_err(fail)? {
                if outline_geoms[n].covers(&inside).map_err(fail)? && holder.is_none_or(|h| outline_area[n] < outline_area[h]) {
                    holder = Some(n);
                }
            }
        }
        let pt = id(part);
        if let Some(h) = holder {
            let (hid, ht) = (outlines[h].fid, id(outlines[h]));
            let up = lifted(&arena[pt]).ok_or("a min_height Python reads differently")?;
            let height = number(arena[ht].get("height"), 0.0).map_err(|_| "a height Python reads differently")?;
            if (up >= height && height > 0.0) || (up > 0.0 && !arena[ht].has("height")) {
                let prev = *under.get(&hid).unwrap_or(&up);
                under.insert(hid, py_min(up, prev));
            } else {
                let area = geometry.area().map_err(fail)?;
                *covered.entry(hid).or_insert(0.0) += area;
            }
            let holder_tags = arena[ht].clone();
            let tags = &mut arena[pt];
            tags.set("e2r_of", &hid.to_string());
            for key in &rules.part_tags {
                if let Some(v) = holder_tags.get(key) {
                    if !tags.has(key) {
                        tags.set(key, v);
                    }
                }
            }
            if holder_tags.get("amenity") == Some("place_of_worship") {
                tags.set("amenity", "place_of_worship");
            }
        }
        arena[pt].setdefault("building", "yes");
    }
    for (n, r) in outlines.iter().enumerate() {
        let t = id(r);
        if *covered.get(&r.fid).unwrap_or(&0.0) >= 0.5 * outline_area[n] {
            arena[t].set("e2r_outline", "1");
        } else if let Some(&u) = under.get(&r.fid) {
            if !arena[t].has("height") && !arena[t].has("building:levels") {
                arena[t].set("height", &pytext::repr(u));
            }
        }
    }
    Ok(())
}

/// The mapbuilder `scene` command's input: u32 length + task JSON, then Python's area stream.
pub fn read_input(mut input: impl Read) -> Result<(SceneTask, Vec<Area>)> {
    let mut data = Vec::new();
    input.read_to_end(&mut data)?;
    let n = u32::from_le_bytes(data.get(..4).context("no task")?.try_into()?) as usize;
    let task: SceneTask = serde_json::from_slice(data.get(4..4 + n).context("task cut short")?)?;
    let areas = read_areas(&data[4 + n..])?;
    Ok((task, areas))
}
