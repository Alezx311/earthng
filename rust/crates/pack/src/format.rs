//! Binary source cells of native country packages (earthng-features-v2), byte for byte what
//! earthng/country_format.py writes.
//!
//! ```text
//! block   := 'EGB2' varint(count) count * (varint(slot) varint(length)) payloads
//! slot    := (i - bi*BLOCK) + (j - bj*BLOCK) * BLOCK, ascending
//! payload := strings terrain roads junctions buildings areas lines points
//! ```
//!
//! Numbers are unsigned LEB128 varints, signed ones zigzagged. Lengths, heights and coordinates
//! are integer centimetres, terrain heights decimetres. Every polyline or ring starts at the cell
//! origin (and z 0) and continues as deltas. Rounding is Python's: half to even.

use std::collections::{BTreeMap, HashMap};
use std::fmt;

use serde::de::{Deserializer, MapAccess, Visitor};
use serde::Deserialize;

pub const MAGIC: &[u8; 4] = b"EGB2";
pub const BLOCK: i64 = 8;
pub const SCALE: f64 = 100.0;
pub const TERRAIN: f64 = 10.0;

/// A feature's OSM tags in their original order: the strings table lists them that way, the
/// payload sorts them by key.
pub type Tags = Vec<(String, String)>;
pub type P3 = [f64; 3];

#[derive(Debug, Clone, Deserialize)]
pub struct Terrain {
    pub nx: usize,
    pub ny: usize,
    pub heights: Vec<f64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Road {
    pub id: String,
    pub width: f64,
    #[serde(default, deserialize_with = "tags")]
    pub tags: Tags,
    #[serde(default)]
    pub nodes: Vec<String>,
    #[serde(deserialize_with = "points")]
    pub points: Vec<P3>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Junction {
    pub id: String,
    pub height: f64,
    #[serde(deserialize_with = "rings")]
    pub rings: Vec<Vec<P3>>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Building {
    pub id: String,
    pub kind: String,
    pub height: f64,
    #[serde(default, rename = "minHeight")]
    pub min_height: f64,
    #[serde(default, deserialize_with = "tags")]
    pub tags: Tags,
    #[serde(deserialize_with = "rings")]
    pub rings: Vec<Vec<P3>>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Area {
    pub id: String,
    pub kind: String,
    #[serde(default, deserialize_with = "tags")]
    pub tags: Tags,
    #[serde(deserialize_with = "rings")]
    pub rings: Vec<Vec<P3>>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Line {
    pub id: String,
    pub kind: String,
    #[serde(default, deserialize_with = "tags")]
    pub tags: Tags,
    #[serde(deserialize_with = "points")]
    pub points: Vec<P3>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Point {
    pub id: String,
    pub kind: String,
    #[serde(default, deserialize_with = "tags")]
    pub tags: Tags,
    #[serde(deserialize_with = "point")]
    pub pos: P3,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Cell {
    pub terrain: Terrain,
    #[serde(default)]
    pub roads: Vec<Road>,
    #[serde(default)]
    pub junctions: Vec<Junction>,
    #[serde(default)]
    pub buildings: Vec<Building>,
    #[serde(default)]
    pub areas: Vec<Area>,
    #[serde(default)]
    pub lines: Vec<Line>,
    #[serde(default)]
    pub points: Vec<Point>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FormatError(pub &'static str);

impl fmt::Display for FormatError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}

impl std::error::Error for FormatError {}

type Result<T> = std::result::Result<T, FormatError>;

/// Python's int(round(value * scale)): half to even, refusing what is not finite.
#[inline]
fn scaled(value: f64, scale: f64) -> Result<i64> {
    let v = (value * scale).round_ties_even();
    if !v.is_finite() {
        return Err(FormatError("non-finite source number"));
    }
    Ok(v as i64)
}

#[inline]
fn put_u(out: &mut Vec<u8>, mut value: u64) {
    while value >= 0x80 {
        out.push((value as u8 & 0x7f) | 0x80);
        value >>= 7;
    }
    out.push(value as u8);
}

#[inline]
fn put_s(out: &mut Vec<u8>, value: i64) {
    put_u(out, ((value << 1) ^ (value >> 63)) as u64);
}

fn put_unsigned(out: &mut Vec<u8>, value: i64) -> Result<()> {
    if value < 0 {
        return Err(FormatError("negative unsigned varint"));
    }
    put_u(out, value as u64);
    Ok(())
}

struct Strings<'a> {
    index: HashMap<&'a str, u64>,
    order: Vec<&'a str>,
}

impl<'a> Strings<'a> {
    fn add(&mut self, text: &'a str) {
        let next = self.order.len() as u64;
        self.index.entry(text).or_insert_with(|| {
            self.order.push(text);
            next
        });
    }

    fn tags(&mut self, tags: &'a Tags) {
        for (k, v) in tags {
            self.add(k);
            self.add(v);
        }
    }

    fn of(cell: &'a Cell) -> Self {
        let mut s = Strings { index: HashMap::new(), order: Vec::new() };
        for f in &cell.roads {
            s.add(&f.id);
            s.tags(&f.tags);
            for n in &f.nodes {
                s.add(n);
            }
        }
        for f in &cell.junctions {
            s.add(&f.id);
        }
        for f in &cell.buildings {
            s.add(&f.id);
            s.add(&f.kind);
            s.tags(&f.tags);
        }
        for f in &cell.areas {
            s.add(&f.id);
            s.add(&f.kind);
            s.tags(&f.tags);
        }
        for f in &cell.lines {
            s.add(&f.id);
            s.add(&f.kind);
            s.tags(&f.tags);
        }
        for f in &cell.points {
            s.add(&f.id);
            s.add(&f.kind);
            s.tags(&f.tags);
        }
        s
    }
}

struct Encoder<'a> {
    out: Vec<u8>,
    strings: Strings<'a>,
    ox: i64,
    oy: i64,
}

impl<'a> Encoder<'a> {
    fn r#ref(&mut self, text: &str) {
        put_u(&mut self.out, self.strings.index[text]);
    }

    fn tags(&mut self, tags: &Tags) {
        put_u(&mut self.out, tags.len() as u64);
        let mut order: Vec<&(String, String)> = tags.iter().collect();
        order.sort_unstable_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        for (k, v) in order {
            self.r#ref(k);
            self.r#ref(v);
        }
    }

    fn line(&mut self, points: &[P3], minimum: usize) -> Result<()> {
        if points.len() < minimum {
            return Err(FormatError("too few source coordinates"));
        }
        put_u(&mut self.out, points.len() as u64);
        let (mut px, mut py, mut pz) = (self.ox, self.oy, 0i64);
        for p in points {
            let (x, y, z) = (scaled(p[0], SCALE)?, scaled(p[1], SCALE)?, scaled(p[2], SCALE)?);
            put_s(&mut self.out, x - px);
            put_s(&mut self.out, y - py);
            put_s(&mut self.out, z - pz);
            (px, py, pz) = (x, y, z);
        }
        Ok(())
    }

    fn rings(&mut self, rings: &[Vec<P3>]) -> Result<()> {
        if rings.is_empty() {
            return Err(FormatError("source polygon without rings"));
        }
        put_u(&mut self.out, rings.len() as u64);
        for ring in rings {
            self.line(ring, 3)?;
        }
        Ok(())
    }
}

/// Bytes of one compiled cell; origin is the cell's south-west corner in region metres.
pub fn encode_cell(cell: &Cell, origin: [f64; 2]) -> Result<Vec<u8>> {
    let strings = Strings::of(cell);
    let mut out = Vec::with_capacity(1 << 16);
    put_u(&mut out, strings.order.len() as u64);
    for text in &strings.order {
        put_u(&mut out, text.len() as u64);
        out.extend_from_slice(text.as_bytes());
    }
    let mut e = Encoder { out, strings, ox: scaled(origin[0], SCALE)?, oy: scaled(origin[1], SCALE)? };

    let t = &cell.terrain;
    if t.heights.len() != t.nx * t.ny {
        return Err(FormatError("terrain size does not match its grid"));
    }
    put_u(&mut e.out, t.nx as u64);
    put_u(&mut e.out, t.ny as u64);
    let mut previous = 0i64;
    for &h in &t.heights {
        let h = scaled(h, TERRAIN)?;
        put_s(&mut e.out, h - previous);
        previous = h;
    }

    put_u(&mut e.out, cell.roads.len() as u64);
    for f in &cell.roads {
        e.r#ref(&f.id);
        put_unsigned(&mut e.out, scaled(f.width, SCALE)?)?;
        e.tags(&f.tags);
        put_u(&mut e.out, f.nodes.len() as u64);
        for n in &f.nodes {
            e.r#ref(n);
        }
        e.line(&f.points, 2)?;
    }
    put_u(&mut e.out, cell.junctions.len() as u64);
    for f in &cell.junctions {
        e.r#ref(&f.id);
        put_s(&mut e.out, scaled(f.height, SCALE)?);
        e.rings(&f.rings)?;
    }
    put_u(&mut e.out, cell.buildings.len() as u64);
    for f in &cell.buildings {
        e.r#ref(&f.id);
        e.r#ref(&f.kind);
        put_unsigned(&mut e.out, scaled(f.height, SCALE)?)?;
        put_unsigned(&mut e.out, scaled(f.min_height, SCALE)?)?;
        e.tags(&f.tags);
        e.rings(&f.rings)?;
    }
    put_u(&mut e.out, cell.areas.len() as u64);
    for f in &cell.areas {
        e.r#ref(&f.id);
        e.r#ref(&f.kind);
        e.tags(&f.tags);
        e.rings(&f.rings)?;
    }
    put_u(&mut e.out, cell.lines.len() as u64);
    for f in &cell.lines {
        e.r#ref(&f.id);
        e.r#ref(&f.kind);
        e.tags(&f.tags);
        e.line(&f.points, 2)?;
    }
    put_u(&mut e.out, cell.points.len() as u64);
    for f in &cell.points {
        e.r#ref(&f.id);
        e.r#ref(&f.kind);
        e.tags(&f.tags);
        e.line(std::slice::from_ref(&f.pos), 1)?;
    }
    Ok(e.out)
}

/// Slot of cell (i, j) in its block.
pub fn slot(i: i64, j: i64) -> u32 {
    (i.rem_euclid(BLOCK) + j.rem_euclid(BLOCK) * BLOCK) as u32
}

/// The block file of {slot: payload} and its 64-bit presence mask (16 hex digits).
pub fn encode_block(payloads: &BTreeMap<u32, Vec<u8>>) -> Result<(Vec<u8>, String)> {
    let mut out = Vec::with_capacity(payloads.values().map(Vec::len).sum::<usize>() + 4 + 8 * payloads.len());
    out.extend_from_slice(MAGIC);
    put_u(&mut out, payloads.len() as u64);
    for (&k, p) in payloads {
        if k >= (BLOCK * BLOCK) as u32 {
            return Err(FormatError("cell slot outside its block"));
        }
        put_u(&mut out, k as u64);
        put_u(&mut out, p.len() as u64);
    }
    for p in payloads.values() {
        out.extend_from_slice(p);
    }
    Ok((out, mask(payloads.keys().copied())))
}

/// 16 hex digits; digit d (first = 0) holds slots 4d..4d+3 as bits 1, 2, 4, 8.
pub fn mask(slots: impl IntoIterator<Item = u32>) -> String {
    let mut digits = [0u8; (BLOCK * BLOCK / 4) as usize];
    for k in slots {
        digits[(k / 4) as usize] |= 1 << (k % 4);
    }
    digits.iter().map(|&d| b"0123456789abcdef"[d as usize] as char).collect()
}

// JSON input (a Python cell dumped for tests and tools): points of two or three coordinates,
// tags in their key order.

fn p3(v: &[f64]) -> std::result::Result<P3, &'static str> {
    match v.len() {
        2 => Ok([v[0], v[1], 0.0]),
        3 => Ok([v[0], v[1], v[2]]),
        _ => Err("source points need two or three coordinates"),
    }
}

fn points<'de, D: Deserializer<'de>>(d: D) -> std::result::Result<Vec<P3>, D::Error> {
    let raw: Vec<Vec<f64>> = Vec::deserialize(d)?;
    raw.iter().map(|p| p3(p).map_err(serde::de::Error::custom)).collect()
}

fn point<'de, D: Deserializer<'de>>(d: D) -> std::result::Result<P3, D::Error> {
    let raw: Vec<f64> = Vec::deserialize(d)?;
    p3(&raw).map_err(serde::de::Error::custom)
}

fn rings<'de, D: Deserializer<'de>>(d: D) -> std::result::Result<Vec<Vec<P3>>, D::Error> {
    let raw: Vec<Vec<Vec<f64>>> = Vec::deserialize(d)?;
    raw.iter()
        .map(|r| r.iter().map(|p| p3(p).map_err(serde::de::Error::custom)).collect())
        .collect()
}

fn tags<'de, D: Deserializer<'de>>(d: D) -> std::result::Result<Tags, D::Error> {
    struct Ordered;
    impl<'de> Visitor<'de> for Ordered {
        type Value = Tags;
        fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
            f.write_str("a map of tags or null")
        }
        fn visit_unit<E>(self) -> std::result::Result<Tags, E> {
            Ok(Vec::new())
        }
        fn visit_none<E>(self) -> std::result::Result<Tags, E> {
            Ok(Vec::new())
        }
        fn visit_some<D: Deserializer<'de>>(self, d: D) -> std::result::Result<Tags, D::Error> {
            d.deserialize_map(Ordered)
        }
        fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> std::result::Result<Tags, A::Error> {
            let mut out = Vec::new();
            while let Some((k, v)) = map.next_entry::<String, String>()? {
                out.push((k, v));
            }
            Ok(out)
        }
    }
    d.deserialize_option(Ordered)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn varints_and_rounding() {
        let mut out = Vec::new();
        put_s(&mut out, -1);
        put_s(&mut out, 1);
        put_u(&mut out, 300);
        assert_eq!(out, [1, 2, 0xac, 0x02]);
        assert_eq!(scaled(0.125, SCALE).unwrap(), 12); // 12.5 -> 12, half to even
        assert_eq!(scaled(0.135, SCALE).unwrap(), 14); // 13.5 -> 14 (the product is 13.5)
        assert!(scaled(f64::NAN, SCALE).is_err());
        assert_eq!(mask([0, 1, 5, 63]), "3200000000000008");
        assert_eq!(slot(-1, -1), 63);
    }
}

/// A road as decode_roads reads it back from a cell.
#[derive(Debug, Clone, PartialEq)]
pub struct DecodedRoad {
    pub id: String,
    pub width: f64,
    pub tags: Tags,
    pub nodes: Vec<String>,
    pub points: Vec<P3>,
}

struct Reader<'a> {
    data: &'a [u8],
    at: usize,
    end: usize,
}

impl Reader<'_> {
    fn u(&mut self) -> Result<u64> {
        let (mut value, mut shift) = (0u64, 0u32);
        loop {
            if self.at >= self.end || shift > 56 {
                return Err(FormatError("truncated or invalid source varint"));
            }
            let b = self.data[self.at];
            self.at += 1;
            value |= u64::from(b & 0x7f) << shift;
            if b < 0x80 {
                return Ok(value);
            }
            shift += 7;
        }
    }

    fn s(&mut self) -> Result<i64> {
        let v = self.u()?;
        Ok(if v % 2 == 0 { (v >> 1) as i64 } else { -(((v + 1) >> 1) as i64) })
    }

    fn skip(&mut self, mut count: u64) -> Result<()> {
        while count > 0 {
            if self.at >= self.end {
                return Err(FormatError("truncated or invalid source varint"));
            }
            if self.data[self.at] < 0x80 {
                count -= 1;
            }
            self.at += 1;
        }
        Ok(())
    }
}

/// decode_block: {slot: (start, end)} of a block file (v2 or EGB3), in slot order.
pub fn decode_block(data: &[u8]) -> Result<Vec<(u32, usize, usize)>> {
    if data.len() < 4 || (&data[..4] != MAGIC && !crate::fixed::is_v3(data)) {
        return Err(FormatError("not an EarthNG source block"));
    }
    let mut r = Reader { data, at: 4, end: data.len() };
    let n = r.u()?;
    let mut entries = Vec::with_capacity(n as usize);
    for _ in 0..n {
        entries.push((r.u()? as u32, r.u()? as usize));
    }
    let mut at = r.at;
    let mut out = Vec::with_capacity(entries.len());
    for (k, len) in entries {
        out.push((k, at, at + len));
        at += len;
    }
    if at != data.len() {
        return Err(FormatError("source block size mismatch"));
    }
    Ok(out)
}

/// decode_roads without the `seen` filter: every road of the cell data[at..end], in order.
/// A cell of an EGB3 block (cells start after the magic, so at >= 5) is read as its v2 bytes.
pub fn decode_roads(data: &[u8], origin: [f64; 2], at: usize, end: usize) -> Result<Vec<DecodedRoad>> {
    if at >= 5 && crate::fixed::is_v3(data) {
        let cell = crate::fixed::cell_to_v2(data, at, end)?;
        return decode_roads(&cell, origin, 0, cell.len());
    }
    let mut r = Reader { data, at, end };
    let n = r.u()?;
    let mut strings = Vec::with_capacity(n as usize);
    for _ in 0..n {
        let len = r.u()? as usize;
        if r.at + len > r.end {
            return Err(FormatError("truncated source string"));
        }
        strings.push(std::str::from_utf8(&data[r.at..r.at + len]).map_err(|_| FormatError("source string not UTF-8"))?);
        r.at += len;
    }
    let text = |r: &mut Reader| -> Result<String> {
        let k = r.u()? as usize;
        strings.get(k).map(|s| s.to_string()).ok_or(FormatError("source string index out of range"))
    };
    let (nx, ny) = (r.u()?, r.u()?);
    r.skip(nx * ny)?;
    let (ox, oy) = (scaled(origin[0], SCALE)?, scaled(origin[1], SCALE)?);
    let count = r.u()?;
    let mut out = Vec::with_capacity(count as usize);
    for _ in 0..count {
        let id = text(&mut r)?;
        let width = r.u()? as f64 / SCALE;
        let ntags = r.u()?;
        let mut tags = Vec::with_capacity(ntags as usize);
        for _ in 0..ntags {
            let k = text(&mut r)?;
            tags.push((k, text(&mut r)?));
        }
        let nnodes = r.u()?;
        let mut nodes = Vec::with_capacity(nnodes as usize);
        for _ in 0..nnodes {
            nodes.push(text(&mut r)?);
        }
        let npoints = r.u()?;
        let mut points = Vec::with_capacity(npoints as usize);
        let (mut px, mut py, mut pz) = (ox, oy, 0i64);
        for _ in 0..npoints {
            px += r.s()?;
            py += r.s()?;
            pz += r.s()?;
            points.push([px as f64 / SCALE, py as f64 / SCALE, pz as f64 / SCALE]);
        }
        out.push(DecodedRoad { id, width, tags, nodes, points });
    }
    Ok(out)
}
