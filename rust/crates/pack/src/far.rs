//! The far view of a pack region (earthng-far-v1): the land to the horizon at a coarse step,
//! read from the region's own cells so the distant ground meets the near tiles.
//!
//! ```text
//! file      := 'EGF1' u8 version i32 u0 i32 v0 u32 nu u32 nv f32 step f32 sea
//!              (nu+1)*(nv+1) u16 elevation     (h + 500) * 4, 0 where no cell has the node
//!              nu*nv u8 class                   CLASS_*, NO_DATA where no cell has the pixel
//!              nu*nv u8 built                   share of the pixel under roofs, 0..255
//!              nu*nv u8 roof                    mean building height in the pixel, m
//!              u32 count, count * landmark
//! landmark  := f32 x, y, z, height, half length, half width, angle (rad), kind (32 bytes: a reader
//!              copies them into a float array as they are)
//! ```
//!
//! All little-endian. Node (u, v) stands at (u * step, v * step) of the region frame; pixel
//! (u, v) is the square from node (u, v) to node (u + 1, v + 1), so a cell holds
//! cellSize / step pixels a side and every pixel belongs to exactly one cell. Rows run along u.
//! A landmark is a building tall enough to read from kilometres away (an oriented box round its
//! footprint) or a mapped tower with a height.

use crate::format::{FormatError, SCALE, TERRAIN};

pub const MAGIC: &[u8; 4] = b"EGF1";
pub const VERSION: u8 = 1;

pub const NONE: u8 = 0; // land without a mapped cover (grass, an unmapped field)
pub const FARMLAND: u8 = 1;
pub const MEADOW: u8 = 2;
pub const FOREST: u8 = 3;
pub const ORCHARD: u8 = 4;
pub const RESIDENTIAL: u8 = 5;
pub const WATER: u8 = 6;
pub const PAVED: u8 = 7;
pub const PARK: u8 = 8;
pub const WETLAND: u8 = 9;
pub const BARE: u8 = 10;
pub const SCRUB: u8 = 11;
pub const SNOW: u8 = 12;
pub const SEA: u8 = 13;
pub const ROCK: u8 = 14;
pub const CLASSES: usize = 15;
pub const NO_DATA: u8 = 255;

/// Buildings at least this tall (m) are landmarks: a box each, drawn far past the far ring.
pub const LANDMARK_HEIGHT: f64 = 30.0;
/// Subsamples a pixel side for its cover class.
const SUB: usize = 4;

type Result<T> = std::result::Result<T, FormatError>;
type Ring = Vec<[f64; 2]>;

pub struct FarBuilding {
    pub height: f64,
    pub rings: Vec<Ring>,
}

pub struct FarArea {
    pub class: u8,
    pub rings: Vec<Ring>,
    pub bbox: [f64; 4],
}

/// A road as the far colour map draws it: a line of its width, paved or a dirt track.
pub struct FarRoad {
    pub width: f64,
    pub paved: bool,
    pub points: Vec<[f64; 2]>,
}

pub struct FarPoint {
    pub kind: String,
    pub tags: Vec<(String, String)>,
    pub pos: [f64; 3],
}

/// The parts of a cell the far view uses.
pub struct FarCell {
    pub nx: usize,
    pub ny: usize,
    pub heights: Vec<f64>,
    pub buildings: Vec<FarBuilding>,
    pub areas: Vec<FarArea>,
    pub points: Vec<FarPoint>,
    pub roads: Vec<FarRoad>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Landmark {
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub height: f32,
    pub half_a: f32,
    pub half_b: f32,
    pub angle: f32,
    pub kind: u8,
}

/// One cell's share of the raster: (k+1)^2 node heights, k^2 pixels, row by row along x.
pub struct CellRaster {
    pub k: usize,
    pub nodes: Vec<f64>,
    pub class: Vec<u8>,
    pub built: Vec<u8>,
    pub roof: Vec<u8>,
    pub landmarks: Vec<Landmark>,
}

/// The far class of a pack area kind (fast_style.ground_kind, nature.ground_kind), or None for a
/// small site the far view leaves to the land round it.
pub fn class_of(kind: &str) -> Option<u8> {
    Some(match kind {
        "forest" | "wood" => FOREST,
        "farmland" => FARMLAND,
        "orchard" | "vineyard" => ORCHARD,
        "meadow" | "grass" | "grassland" => MEADOW,
        "residential" => RESIDENTIAL,
        "water" => WATER,
        "paved" => PAVED,
        "park" => PARK,
        "wetland" => WETLAND,
        "bare_ground" | "beach" | "sand" => BARE,
        "scree" | "bare_rock" => ROCK,
        "scrub" | "heath" => SCRUB,
        "glacier" | "snow" => SNOW,
        _ => return None,
    })
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

/// The terrain, buildings, areas and points of the cell data[at..end] (v2 or EGB3), coordinates
/// in region metres from the cell's south-west corner `origin`.
pub fn decode_far(data: &[u8], origin: [f64; 2], at: usize, end: usize) -> Result<FarCell> {
    if at >= 5 && crate::fixed::is_v3(data) {
        let cell = crate::fixed::cell_to_v2(data, at, end)?;
        return decode_far(&cell, origin, 0, cell.len());
    }
    let mut r = Reader { data, at, end };
    let n = r.u()?;
    let mut strings: Vec<&str> = Vec::with_capacity(n as usize);
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
    let (ox, oy) = ((origin[0] * SCALE).round() as i64, (origin[1] * SCALE).round() as i64);
    let ring = |r: &mut Reader| -> Result<Ring> {
        let n = r.u()?;
        let mut out = Vec::with_capacity(n as usize);
        let (mut px, mut py) = (ox, oy);
        for _ in 0..n {
            px += r.s()?;
            py += r.s()?;
            r.s()?;
            out.push([px as f64 / SCALE, py as f64 / SCALE]);
        }
        Ok(out)
    };
    let (nx, ny) = (r.u()? as usize, r.u()? as usize);
    if nx < 2 || ny < 2 || nx > 257 || ny > 257 {
        return Err(FormatError("invalid source elevation grid"));
    }
    let mut heights = Vec::with_capacity(nx * ny);
    let mut h = 0i64;
    for _ in 0..nx * ny {
        h += r.s()?;
        heights.push(h as f64 / TERRAIN);
    }
    let mut roads = Vec::new();
    for _ in 0..r.u()? {
        r.u()?;
        let width = r.u()? as f64 / SCALE;
        let t = r.u()?;
        let (mut highway, mut surface) = (String::new(), String::new());
        for _ in 0..t {
            let k = text(&mut r)?;
            let v = text(&mut r)?;
            match k.as_str() {
                "highway" => highway = v,
                "surface" => surface = v,
                _ => {}
            }
        }
        let n = r.u()?;
        r.skip(n)?;
        let p = r.u()?;
        let mut points = Vec::with_capacity(p as usize);
        let (mut px, mut py) = (ox, oy);
        for _ in 0..p {
            px += r.s()?;
            py += r.s()?;
            r.s()?;
            points.push([px as f64 / SCALE, py as f64 / SCALE]);
        }
        // footways and the like do not read from the air
        let drawn = !matches!(highway.as_str(), "" | "footway" | "path" | "cycleway" | "steps" | "pedestrian"
            | "bridleway" | "corridor" | "elevator" | "proposed" | "construction" | "platform");
        if drawn && points.len() > 1 {
            let dirt = matches!(surface.as_str(), "unpaved" | "dirt" | "ground" | "grass" | "gravel" | "sand"
                | "earth" | "fine_gravel" | "compacted" | "mud");
            let paved = !(dirt || (highway == "track" && surface.is_empty()));
            roads.push(FarRoad { width: width.max(3.0), paved, points });
        }
    }
    // junctions
    for _ in 0..r.u()? {
        r.u()?;
        r.s()?;
        for _ in 0..r.u()? {
            let p = r.u()?;
            r.skip(3 * p)?;
        }
    }
    let mut buildings = Vec::new();
    for _ in 0..r.u()? {
        r.u()?;
        r.u()?;
        let height = r.u()? as f64 / SCALE;
        r.u()?;
        let t = r.u()?;
        r.skip(2 * t)?;
        let mut rings = Vec::new();
        for _ in 0..r.u()? {
            rings.push(ring(&mut r)?);
        }
        buildings.push(FarBuilding { height, rings });
    }
    let mut areas = Vec::new();
    for _ in 0..r.u()? {
        r.u()?;
        let kind = text(&mut r)?;
        let t = r.u()?;
        r.skip(2 * t)?;
        let mut rings = Vec::new();
        for _ in 0..r.u()? {
            rings.push(ring(&mut r)?);
        }
        if let Some(class) = class_of(&kind) {
            let mut bbox = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
            for p in rings.first().into_iter().flatten() {
                bbox = [bbox[0].min(p[0]), bbox[1].min(p[1]), bbox[2].max(p[0]), bbox[3].max(p[1])];
            }
            areas.push(FarArea { class, rings, bbox });
        }
    }
    // lines
    for _ in 0..r.u()? {
        r.u()?;
        r.u()?;
        let t = r.u()?;
        r.skip(2 * t)?;
        let p = r.u()?;
        r.skip(3 * p)?;
    }
    let mut points = Vec::new();
    for _ in 0..r.u()? {
        r.u()?;
        let kind = text(&mut r)?;
        let t = r.u()?;
        let mut tags = Vec::with_capacity(t as usize);
        for _ in 0..t {
            let k = text(&mut r)?;
            tags.push((k, text(&mut r)?));
        }
        let n = r.u()?;
        let (mut px, mut py, mut pz) = (ox, oy, 0i64);
        for _ in 0..n {
            px += r.s()?;
            py += r.s()?;
            pz += r.s()?;
        }
        points.push(FarPoint { kind, tags, pos: [px as f64 / SCALE, py as f64 / SCALE, pz as f64 / SCALE] });
    }
    if r.at != r.end {
        return Err(FormatError("trailing bytes after source cell"));
    }
    Ok(FarCell { nx, ny, heights, buildings, areas, points, roads })
}

pub(crate) fn inside(rings: &[Ring], x: f64, y: f64) -> bool {
    let mut odd = false;
    for ring in rings {
        let n = ring.len();
        if n < 3 {
            continue;
        }
        let mut j = n - 1;
        for i in 0..n {
            let (a, b) = (ring[i], ring[j]);
            if (a[1] > y) != (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0] {
                odd = !odd;
            }
            j = i;
        }
    }
    odd
}

/// Bilinear height of the cell's grid at a point of the cell (local metres from its corner).
pub(crate) fn grid_height(cell: &FarCell, size: f64, x: f64, y: f64) -> f64 {
    let gx = (x / size * (cell.nx - 1) as f64).clamp(0.0, (cell.nx - 1) as f64);
    let gy = (y / size * (cell.ny - 1) as f64).clamp(0.0, (cell.ny - 1) as f64);
    let ix = (gx.floor() as usize).min(cell.nx - 2);
    let iy = (gy.floor() as usize).min(cell.ny - 2);
    let (tx, ty) = (gx - ix as f64, gy - iy as f64);
    let h = &cell.heights;
    let row = iy * cell.nx + ix;
    (h[row] * (1.0 - tx) + h[row + 1] * tx) * (1.0 - ty) + (h[row + cell.nx] * (1.0 - tx) + h[row + cell.nx + 1] * tx) * ty
}

/// Signed area and centroid of a ring (shoelace).
pub(crate) fn ring_area(ring: &Ring) -> (f64, f64, f64) {
    let (mut a, mut cx, mut cy) = (0.0, 0.0, 0.0);
    let n = ring.len();
    if n < 3 {
        return (0.0, 0.0, 0.0);
    }
    let (x0, y0) = (ring[0][0], ring[0][1]);
    for i in 0..n {
        let p = ring[i];
        let q = ring[(i + 1) % n];
        let (px, py, qx, qy) = (p[0] - x0, p[1] - y0, q[0] - x0, q[1] - y0);
        let c = px * qy - qx * py;
        a += c;
        cx += (px + qx) * c;
        cy += (py + qy) * c;
    }
    if a.abs() < 1e-9 {
        return (0.0, x0, y0);
    }
    (a / 2.0, cx / (3.0 * a) + x0, cy / (3.0 * a) + y0)
}

/// An oriented box round a ring: along its longest edge. (centre x, y, half length, half width, angle)
fn oriented_box(ring: &Ring) -> (f64, f64, f64, f64, f64) {
    let n = ring.len();
    let (mut best, mut angle) = (-1.0, 0.0);
    for i in 0..n {
        let (p, q) = (ring[i], ring[(i + 1) % n]);
        let d = (q[0] - p[0]).hypot(q[1] - p[1]);
        if d > best {
            best = d;
            angle = (q[1] - p[1]).atan2(q[0] - p[0]);
        }
    }
    let (c, s) = (angle.cos(), angle.sin());
    let (mut a0, mut a1, mut b0, mut b1) = (f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY);
    for p in ring {
        let a = p[0] * c + p[1] * s;
        let b = -p[0] * s + p[1] * c;
        a0 = a0.min(a);
        a1 = a1.max(a);
        b0 = b0.min(b);
        b1 = b1.max(b);
    }
    let (am, bm) = ((a0 + a1) / 2.0, (b0 + b1) / 2.0);
    (am * c - bm * s, am * s + bm * c, (a1 - a0) / 2.0, (b1 - b0) / 2.0, angle)
}

fn tag<'a>(tags: &'a [(String, String)], key: &str) -> Option<&'a str> {
    tags.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
}

fn metres(text: &str) -> Option<f64> {
    let first = text.split(';').next()?.trim();
    let first = first.trim_end_matches('m').trim();
    first.parse::<f64>().ok().filter(|v| v.is_finite() && *v > 0.0)
}

/// The raster of cell (i, j): node heights, cover class, roofs and landmarks. `sea`: the region's
/// sea level (pixels at it with no mapped cover are sea).
pub fn rasterize(cell: &FarCell, i: i64, j: i64, size: f64, step: f64, sea: Option<f64>) -> CellRaster {
    let k = (size / step).round() as usize;
    let (x0, y0) = (i as f64 * size, j as f64 * size);
    let mut nodes = Vec::with_capacity((k + 1) * (k + 1));
    for b in 0..=k {
        for a in 0..=k {
            nodes.push(grid_height(cell, size, a as f64 * step, b as f64 * step));
        }
    }
    let mut class = vec![NONE; k * k];
    let sub = step / SUB as f64;
    for b in 0..k {
        for a in 0..k {
            let (px0, py0) = (x0 + a as f64 * step, y0 + b as f64 * step);
            let mut votes = [0u8; CLASSES];
            for sb in 0..SUB {
                for sa in 0..SUB {
                    let (x, y) = (px0 + (sa as f64 + 0.5) * sub, py0 + (sb as f64 + 0.5) * sub);
                    let mut found = NONE;
                    // areas are partitioned (nature.partition): the first that holds the point
                    for area in &cell.areas {
                        let bb = area.bbox;
                        if x >= bb[0] && x <= bb[2] && y >= bb[1] && y <= bb[3] && inside(&area.rings, x, y) {
                            found = area.class;
                            break;
                        }
                    }
                    votes[found as usize] += 1;
                }
            }
            let mut best = NONE;
            for c in 0..CLASSES {
                if votes[c] > votes[best as usize] {
                    best = c as u8;
                }
            }
            if best == NONE
                && let Some(level) = sea
            {
                let low = [nodes[b * (k + 1) + a], nodes[b * (k + 1) + a + 1], nodes[(b + 1) * (k + 1) + a], nodes[(b + 1) * (k + 1) + a + 1]];
                if low.iter().all(|&h| h <= level + 0.3) {
                    best = SEA;
                }
            }
            class[b * k + a] = best;
        }
    }
    let mut area_sum = vec![0.0f64; k * k];
    let mut height_sum = vec![0.0f64; k * k];
    let mut landmarks = Vec::new();
    for building in &cell.buildings {
        let Some(outer) = building.rings.first() else { continue };
        let (area, cx, cy) = ring_area(outer);
        let mut area = area.abs();
        for hole in building.rings.iter().skip(1) {
            area -= ring_area(hole).0.abs();
        }
        // a building is stored whole in every cell it reaches: it counts where its centre is
        if area <= 0.0 || cx < x0 || cy < y0 || cx >= x0 + size || cy >= y0 + size {
            continue;
        }
        let a = (((cx - x0) / step) as usize).min(k - 1);
        let b = (((cy - y0) / step) as usize).min(k - 1);
        area_sum[b * k + a] += area;
        height_sum[b * k + a] += area * building.height;
        if building.height >= LANDMARK_HEIGHT {
            let (bx, by, ha, hb, angle) = oriented_box(outer);
            let z = grid_height(cell, size, (bx - x0).clamp(0.0, size), (by - y0).clamp(0.0, size));
            landmarks.push(Landmark {
                x: bx as f32,
                y: by as f32,
                z: z as f32,
                height: building.height as f32,
                half_a: ha.max(2.0) as f32,
                half_b: hb.max(2.0) as f32,
                angle: angle as f32,
                kind: 1,
            });
        }
    }
    for point in &cell.points {
        let man_made = tag(&point.tags, "man_made").unwrap_or(point.kind.as_str());
        let tall = matches!(man_made, "tower" | "mast" | "chimney" | "communications_tower");
        let Some(height) = tag(&point.tags, "height").and_then(metres) else { continue };
        let (x, y) = (point.pos[0], point.pos[1]);
        if !tall || height < LANDMARK_HEIGHT || x < x0 || y < y0 || x >= x0 + size || y >= y0 + size {
            continue;
        }
        let z = grid_height(cell, size, x - x0, y - y0);
        let half = if man_made == "chimney" { 4.0 } else { 3.0 };
        landmarks.push(Landmark { x: x as f32, y: y as f32, z: z as f32, height: height as f32, half_a: half,
                                  half_b: half, angle: 0.0, kind: 2 });
    }
    let pixel = step * step;
    let built = area_sum.iter().map(|&a| ((a / pixel).min(1.0) * 255.0).round() as u8).collect();
    let roof = area_sum
        .iter()
        .zip(&height_sum)
        .map(|(&a, &h)| if a > 0.0 { (h / a).round().clamp(1.0, 255.0) as u8 } else { 0 })
        .collect();
    CellRaster { k, nodes, class, built, roof, landmarks }
}

/// The region file from its cells' rasters ((i, j, raster) in any order).
pub fn encode(cells: &[(i64, i64, CellRaster)], step: f64, sea: f64) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(MAGIC);
    out.push(VERSION);
    if cells.is_empty() {
        for _ in 0..4 {
            out.extend_from_slice(&0i32.to_le_bytes());
        }
        out.extend_from_slice(&(step as f32).to_le_bytes());
        out.extend_from_slice(&(sea as f32).to_le_bytes());
        out.extend_from_slice(&0u32.to_le_bytes());
        return out;
    }
    let k = cells[0].2.k as i64;
    let (mut i0, mut j0, mut i1, mut j1) = (i64::MAX, i64::MAX, i64::MIN, i64::MIN);
    for (i, j, _) in cells {
        i0 = i0.min(*i);
        j0 = j0.min(*j);
        i1 = i1.max(*i);
        j1 = j1.max(*j);
    }
    let (nu, nv) = (((i1 - i0 + 1) * k) as usize, ((j1 - j0 + 1) * k) as usize);
    let mut elevation = vec![0u16; (nu + 1) * (nv + 1)];
    let mut class = vec![NO_DATA; nu * nv];
    let mut built = vec![0u8; nu * nv];
    let mut roof = vec![0u8; nu * nv];
    let mut landmarks = Vec::new();
    let k = k as usize;
    for (i, j, r) in cells {
        let (ou, ov) = (((i - i0) as usize) * k, ((j - j0) as usize) * k);
        for b in 0..=k {
            for a in 0..=k {
                let h = r.nodes[b * (k + 1) + a];
                let v = ((h + 500.0) * 4.0).round().clamp(1.0, 65535.0) as u16;
                elevation[(ov + b) * (nu + 1) + ou + a] = v;
            }
        }
        for b in 0..k {
            for a in 0..k {
                let at = (ov + b) * nu + ou + a;
                class[at] = r.class[b * k + a];
                built[at] = r.built[b * k + a];
                roof[at] = r.roof[b * k + a];
            }
        }
        landmarks.extend_from_slice(&r.landmarks);
    }
    for v in [(i0 * k as i64) as i32, (j0 * k as i64) as i32] {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out.extend_from_slice(&(nu as u32).to_le_bytes());
    out.extend_from_slice(&(nv as u32).to_le_bytes());
    out.extend_from_slice(&(step as f32).to_le_bytes());
    out.extend_from_slice(&(sea as f32).to_le_bytes());
    for v in elevation {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out.extend_from_slice(&class);
    out.extend_from_slice(&built);
    out.extend_from_slice(&roof);
    // tall first: a reader that keeps only some keeps the skyline
    landmarks.sort_by(|a, b| b.height.total_cmp(&a.height));
    out.extend_from_slice(&(landmarks.len() as u32).to_le_bytes());
    for l in landmarks {
        for v in [l.x, l.y, l.z, l.height, l.half_a, l.half_b, l.angle, f32::from(l.kind)] {
            out.extend_from_slice(&v.to_le_bytes());
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn flat(h: f64) -> FarCell {
        FarCell { nx: 2, ny: 2, heights: vec![h; 4], buildings: vec![], areas: vec![], points: vec![], roads: vec![] }
    }

    #[test]
    fn forest_half_and_a_tower_block() {
        let mut cell = flat(120.0);
        let ring = vec![[0.0, 0.0], [500.0, 0.0], [500.0, 1000.0], [0.0, 1000.0]];
        cell.areas.push(FarArea { class: FOREST, rings: vec![ring], bbox: [0.0, 0.0, 500.0, 1000.0] });
        let block = vec![[610.0, 610.0], [650.0, 610.0], [650.0, 630.0], [610.0, 630.0]];
        cell.buildings.push(FarBuilding { height: 75.0, rings: vec![block] });
        let r = rasterize(&cell, 0, 0, 1000.0, 200.0, Some(20.0));
        assert_eq!(r.k, 5);
        assert!(r.nodes.iter().all(|&h| (h - 120.0).abs() < 1e-9));
        // pixels 0, 1 are inside x < 400; pixel 2 spans 400..600, half forest: 8 of 16 votes tie
        // with none, which comes first
        assert_eq!(r.class[0], FOREST);
        assert_eq!(r.class[1], FOREST);
        assert_eq!(r.class[4], NONE);
        let at = 3 * 5 + 3;
        assert_eq!(r.roof[at], 75);
        assert_eq!(r.built[at], (800.0f64 / 40000.0 * 255.0).round() as u8);
        assert_eq!(r.landmarks.len(), 1);
        let l = r.landmarks[0];
        assert!((l.x - 630.0).abs() < 1e-3 && (l.y - 620.0).abs() < 1e-3);
        assert!((l.half_a - 20.0).abs() < 1e-3 && (l.half_b - 10.0).abs() < 1e-3);
        assert!((l.z - 120.0).abs() < 1e-3);
    }

    #[test]
    fn sea_only_where_nothing_is_mapped() {
        let cell = flat(20.0);
        let r = rasterize(&cell, -1, 2, 1000.0, 250.0, Some(20.0));
        assert_eq!(r.k, 4);
        assert!(r.class.iter().all(|&c| c == SEA));
        let r = rasterize(&cell, 0, 0, 1000.0, 250.0, None);
        assert!(r.class.iter().all(|&c| c == NONE));
    }

    #[test]
    fn encoded_layout() {
        let cell = flat(100.0);
        let a = rasterize(&cell, 3, -2, 1000.0, 500.0, None);
        let b = rasterize(&cell, 4, -2, 1000.0, 500.0, None);
        let data = encode(&[(3, -2, a), (4, -2, b)], 500.0, 20.0);
        assert_eq!(&data[..4], MAGIC);
        let int = |at: usize| i32::from_le_bytes(data[at..at + 4].try_into().unwrap());
        assert_eq!((int(5), int(9), int(13), int(17)), (6, -4, 4, 2));
        let nodes = 5 * 3;
        let h = u16::from_le_bytes(data[29..31].try_into().unwrap());
        assert_eq!(h, 2400);
        assert_eq!(data.len(), 29 + 2 * nodes + 3 * 8 + 4);
    }
}
