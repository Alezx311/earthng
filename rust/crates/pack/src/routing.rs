//! Routing graph of a pack region (earthng-routing-v1): earthng/routing_format.py's graph() and
//! encode() over the roads build_routing.region_roads reads from the region's blocks, byte for
//! byte the file the Python step writes.

use std::collections::{HashMap, HashSet};

use crate::format::{DecodedRoad, FormatError};

pub const MAGIC: &[u8; 4] = b"EGR1";
pub const VERSION: u64 = 1;
const SCALE: f64 = 10.0;
const SIMPLIFY: f64 = 5.0;
const CLASSES: [&str; 8] =
    ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"];
const NO_ONEWAY: [&str; 5] = ["no", "false", "0", "reversible", "alternating"];
const LINK: u64 = 8;
const ONEWAY: u64 = 16;
const RING: u64 = 32;

type Result<T> = std::result::Result<T, FormatError>;

fn tag<'a>(tags: &'a [(String, String)], key: &str) -> Option<&'a str> {
    tags.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
}

/// Python's float(text) for what OSM values hold (digits, sign, point, exponent, underscores
/// between digits, inf/nan words); None where float() raises.
fn py_float(text: &str) -> Option<f64> {
    let t = text.trim();
    if t.contains('_') {
        let b = t.as_bytes();
        for (k, &c) in b.iter().enumerate() {
            if c == b'_' && !(k > 0 && k + 1 < b.len() && b[k - 1].is_ascii_digit() && b[k + 1].is_ascii_digit()) {
                return None;
            }
        }
        return py_float(&t.replace('_', ""));
    }
    let lower = t.to_ascii_lowercase();
    let body = lower.trim_start_matches(['+', '-']);
    if lower.len() - body.len() > 1 {
        return None;
    }
    if matches!(body, "inf" | "infinity" | "nan") {
        return Some(f64::NAN);
    }
    if body.is_empty() || !body.bytes().all(|c| c.is_ascii_digit() || matches!(c, b'.' | b'e' | b'+' | b'-')) {
        return None;
    }
    lower.parse::<f64>().ok()
}

/// _number(value, default): the first number of "50;60" or "50 mph".
fn number(value: &str, default: f64) -> f64 {
    let first = value.split(';').next().unwrap_or("").trim();
    let first = first.split(' ').next().unwrap_or("");
    match py_float(first) {
        Some(v) if v.is_finite() => v,
        _ => default,
    }
}

/// (one-way, reversed) as generator.lua ROADS.oneway.
fn oneway(tags: &[(String, String)]) -> (bool, bool) {
    let value = tag(tags, "oneway").unwrap_or("").to_lowercase();
    if value == "-1" {
        return (true, true);
    }
    if matches!(value.as_str(), "yes" | "1" | "true") {
        return (true, false);
    }
    if NO_ONEWAY.contains(&value.as_str()) {
        return (false, false);
    }
    let ring = matches!(tag(tags, "junction"), Some("roundabout" | "circular"));
    (tag(tags, "highway") == Some("motorway") || ring, false)
}

/// Signed speed as navSegment reads maxspeed; 0 means the class default.
fn speed_kmh(tags: &[(String, String)]) -> u64 {
    let text = tag(tags, "maxspeed").unwrap_or("").to_lowercase();
    if text == "none" {
        return 130;
    }
    if text.contains("urban") {
        return 50;
    }
    if text.contains("rural") {
        return 90;
    }
    let mut value = number(&text, 0.0);
    if text.contains("mph") {
        value *= 1.609;
    }
    value.round_ties_even().clamp(0.0, 250.0) as u64
}

pub struct Edge {
    a: String,
    b: String,
    xy: Vec<(f64, f64)>,
    length: f64,
    flags: u64,
    speed: u64,
    names: [Option<String>; 4],
}

/// edge_of: the routing edge of a pack road, or None where navSegment makes no navgraph.
fn edge_of(road: &DecodedRoad) -> Option<Edge> {
    let tags = &road.tags;
    let highway = tag(tags, "highway").unwrap_or("residential");
    let base = highway.strip_suffix("_link").unwrap_or(highway);
    let class = CLASSES.iter().position(|c| *c == base)?;
    if matches!(tag(tags, "access"), Some("private" | "no")) || tag(tags, "area") == Some("yes") {
        return None;
    }
    if road.points.len() < 2 || road.nodes.len() < 2 {
        return None;
    }
    let (one, flip) = oneway(tags);
    let mut xy: Vec<(f64, f64)> = road.points.iter().map(|p| (p[0], p[1])).collect();
    let (mut a, mut b) = (road.nodes[0].clone(), road.nodes[road.nodes.len() - 1].clone());
    if flip {
        xy.reverse();
        std::mem::swap(&mut a, &mut b);
    }
    let mut length = 0.0;
    for k in 0..xy.len() - 1 {
        let (dx, dy) = (xy[k + 1].0 - xy[k].0, xy[k + 1].1 - xy[k].1);
        length += dx.hypot(dy);
    }
    if length <= 0.0 {
        return None;
    }
    let mut flags = class as u64 | if base != highway { LINK } else { 0 } | if one { ONEWAY } else { 0 };
    if matches!(tag(tags, "junction"), Some("roundabout" | "circular")) {
        flags |= RING;
    }
    let name = |key| tag(tags, key).filter(|v| !v.is_empty()).map(str::to_string);
    Some(Edge { a, b, xy, length, flags, speed: speed_kmh(tags), names: [name("name"), name("name:uk"), name("name:en"), name("ref")] })
}

/// Ramer-Douglas-Peucker keeping both ends, in routing_format.simplify's order.
fn simplify(xy: &[(f64, f64)], tolerance: f64) -> Vec<(f64, f64)> {
    if xy.len() <= 2 {
        return xy.to_vec();
    }
    let mut keep = vec![false; xy.len()];
    keep[0] = true;
    keep[xy.len() - 1] = true;
    let mut stack = vec![(0usize, xy.len() - 1)];
    while let Some((i, j)) = stack.pop() {
        let ((ax, ay), (bx, by)) = (xy[i], xy[j]);
        let (dx, dy) = (bx - ax, by - ay);
        let length2 = dx * dx + dy * dy;
        let (mut worst, mut at) = (tolerance * tolerance, None);
        for (k, &(px, py)) in xy.iter().enumerate().take(j).skip(i + 1) {
            let f = if length2 == 0.0 { 0.0 } else { (((px - ax) * dx + (py - ay) * dy) / length2).clamp(0.0, 1.0) };
            let (ex, ey) = (px - ax - f * dx, py - ay - f * dy);
            if ex * ex + ey * ey > worst {
                (worst, at) = (ex * ex + ey * ey, Some(k));
            }
        }
        if let Some(k) = at {
            keep[k] = true;
            stack.push((i, k));
            stack.push((k, j));
        }
    }
    xy.iter().zip(keep).filter(|(_, k)| *k).map(|(p, _)| *p).collect()
}

#[inline]
fn dm(value: f64) -> i64 {
    (value * SCALE).round_ties_even() as i64
}

pub struct Graph {
    pub nodes: Vec<(i64, f64, f64)>,
    pub edges: Vec<Edge>,
}

/// graph(): roads taken once per id, an edge between the same nodes with the same length (to the
/// decimetre) and one-way flag once.
pub fn graph<'a>(roads: impl IntoIterator<Item = &'a DecodedRoad>) -> Result<Graph> {
    let mut seen: HashSet<&str> = HashSet::new();
    let mut keys: HashSet<(String, String, i64, u64)> = HashSet::new();
    let mut ends: HashMap<String, (f64, f64)> = HashMap::new();
    let mut edges = Vec::new();
    for road in roads {
        if !seen.insert(road.id.as_str()) {
            continue;
        }
        let Some(edge) = edge_of(road) else { continue };
        let key = (edge.a.clone(), edge.b.clone(), (edge.length * SCALE).round_ties_even() as i64, edge.flags & ONEWAY);
        if !keys.insert(key) {
            continue;
        }
        ends.entry(edge.a.clone()).or_insert(edge.xy[0]);
        ends.entry(edge.b.clone()).or_insert(edge.xy[edge.xy.len() - 1]);
        edges.push(edge);
    }
    let mut nodes = Vec::with_capacity(ends.len());
    for (id, (x, y)) in ends {
        let n: i64 = id.trim().parse().map_err(|_| FormatError("routing node id is not an integer"))?;
        nodes.push((n, x, y));
    }
    nodes.sort_by_key(|n| n.0);
    Ok(Graph { nodes, edges })
}

fn put_u(out: &mut Vec<u8>, value: i64) -> Result<()> {
    if value < 0 {
        return Err(FormatError("negative unsigned varint"));
    }
    let mut v = value as u64;
    while v >= 0x80 {
        out.push((v as u8 & 0x7f) | 0x80);
        v >>= 7;
    }
    out.push(v as u8);
    Ok(())
}

fn put_s(out: &mut Vec<u8>, value: i64) {
    let mut v = ((value << 1) ^ (value >> 63)) as u64;
    while v >= 0x80 {
        out.push((v as u8 & 0x7f) | 0x80);
        v >>= 7;
    }
    out.push(v as u8);
}

/// encode(): the region's routing file.
pub fn encode(g: &Graph) -> Result<Vec<u8>> {
    let mut out = MAGIC.to_vec();
    put_u(&mut out, VERSION as i64)?;
    let mut strings: HashMap<&str, i64> = HashMap::new();
    let mut order: Vec<&str> = Vec::new();
    for e in &g.edges {
        for text in e.names.iter().flatten() {
            if !strings.contains_key(text.as_str()) {
                strings.insert(text, order.len() as i64);
                order.push(text);
            }
        }
    }
    put_u(&mut out, order.len() as i64)?;
    for text in &order {
        put_u(&mut out, text.len() as i64)?;
        out.extend_from_slice(text.as_bytes());
    }
    put_u(&mut out, g.nodes.len() as i64)?;
    let mut index: HashMap<String, usize> = HashMap::with_capacity(g.nodes.len());
    let (mut prev, mut px, mut py) = (0i64, 0i64, 0i64);
    for (k, &(nid, x, y)) in g.nodes.iter().enumerate() {
        if nid <= prev && k > 0 {
            return Err(FormatError("routing nodes must ascend by OSM id"));
        }
        index.insert(nid.to_string(), k);
        let (qx, qy) = (dm(x), dm(y));
        put_u(&mut out, nid - prev)?;
        put_s(&mut out, qx - px);
        put_s(&mut out, qy - py);
        (prev, px, py) = (nid, qx, qy);
    }
    // str(int(id)) is how Python keys the index; the edges carry the ids as the pack stores them
    let at = |id: &str| -> Result<usize> {
        let n: i64 = id.trim().parse().map_err(|_| FormatError("routing node id is not an integer"))?;
        index.get(&n.to_string()).copied().ok_or(FormatError("routing edge end without a node"))
    };
    let mut rows = Vec::with_capacity(g.edges.len());
    for e in &g.edges {
        rows.push((at(&e.a)?, at(&e.b)?, e));
    }
    rows.sort_by_key(|r| (r.0, r.1));
    put_u(&mut out, rows.len() as i64)?;
    let mut prev_a = 0i64;
    for (a, b, e) in rows {
        put_u(&mut out, a as i64 - prev_a)?;
        put_s(&mut out, b as i64 - a as i64);
        prev_a = a as i64;
        put_u(&mut out, dm(e.length).max(1))?;
        put_u(&mut out, e.flags as i64)?;
        put_u(&mut out, e.speed as i64)?;
        for name in &e.names {
            put_u(&mut out, name.as_ref().map_or(0, |t| strings[t.as_str()] + 1))?;
        }
        let simple = simplify(&e.xy, SIMPLIFY);
        let inner = &simple[1..simple.len() - 1];
        put_u(&mut out, inner.len() as i64)?;
        let (mut qx, mut qy) = (dm(g.nodes[a].1), dm(g.nodes[a].2));
        for &(x, y) in inner {
            let (rx, ry) = (dm(x), dm(y));
            put_s(&mut out, rx - qx);
            put_s(&mut out, ry - qy);
            (qx, qy) = (rx, ry);
        }
    }
    put_u(&mut out, 0)?;
    put_u(&mut out, 0)?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_float_and_speeds() {
        assert_eq!(py_float("5_0"), Some(50.0));
        assert_eq!(py_float("_5"), None);
        assert_eq!(py_float("1e2"), Some(100.0));
        assert_eq!(py_float("abc"), None);
        let tags = |v: &str| vec![("maxspeed".to_string(), v.to_string())];
        assert_eq!(speed_kmh(&tags("30 mph")), 48);
        assert_eq!(speed_kmh(&tags("RU:urban")), 50);
        assert_eq!(speed_kmh(&tags("none")), 130);
        assert_eq!(speed_kmh(&tags("60;80")), 60);
        assert_eq!(speed_kmh(&tags("")), 0);
    }

    #[test]
    fn rdp_keeps_the_bend() {
        let xy = [(0.0, 0.0), (10.0, 0.1), (20.0, 0.0), (20.0, 20.0)];
        assert_eq!(simplify(&xy, 5.0), vec![(0.0, 0.0), (20.0, 0.0), (20.0, 20.0)]);
    }
}
