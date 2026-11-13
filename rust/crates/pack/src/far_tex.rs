//! The far view's colour map (earthng-far-tex-v1): what the land looks like from a plane, drawn
//! offline from a region's cells and draped over the far ground, so the distance reads like an
//! aerial photo instead of a quilt of flat class colours.
//!
//! One texel is `tstep` metres (50 by default) and is the mean of SUB x SUB subsamples, each one
//! of: a roof (buildings filled by scanline, roof colours by height and a hash), or the ground of
//! the cover class at that point. Farmland and unmapped land are split into fields: blocks of a
//! jittered Voronoi lattice, each turned its own way, cut into strips and the strips into fields,
//! each field its own crop; the block borders and some strip borders carry tree belts (лісосмуги),
//! the field borders dirt tracks. Roads add their own width of asphalt or dust to the texels
//! they cross. Low-frequency noise breaks up even colours. Every pattern hashes absolute frame
//! coordinates (the region's projected origin plus local metres), so neighbouring regions and
//! rebuilds agree.
//!
//! The region's map is a DDS (BC1, 4:1, full mip chain, written here without dependencies):
//! row 0 is the north edge, texel (c, r) covers x from x0 + c * tstep, y from y1 - (r + 1) * tstep,
//! and the map spans the region raster exactly (`step / tstep` texels a raster pixel).

use crate::far::{FarCell, grid_height, ring_area, BARE, FARMLAND, FOREST, MEADOW, NONE, ORCHARD, PARK, PAVED,
                 RESIDENTIAL, ROCK, SCRUB, SEA, SNOW, WATER, WETLAND};

/// Subsamples a texel side.
pub const SUB: usize = 4;

/// One cell's texels, row by row along x, south row first, linear RGB.
pub struct CellTex {
    pub k: usize,
    pub rgb: Vec<[f32; 3]>,
    /// roughness 0..1 a texel: water is smooth (it mirrors the sky from afar), land is not
    pub rough: Vec<f32>,
}

fn lin(c: u8) -> f32 {
    let c = f32::from(c) / 255.0;
    if c <= 0.04045 { c / 12.92 } else { ((c + 0.055) / 1.055).powf(2.4) }
}

fn srgb(c: f32) -> u8 {
    let c = c.clamp(0.0, 1.0);
    let s = if c <= 0.0031308 { c * 12.92 } else { 1.055 * c.powf(1.0 / 2.4) - 0.055 };
    (s * 255.0).round() as u8
}

fn rgb(c: [u8; 3]) -> [f32; 3] {
    [lin(c[0]), lin(c[1]), lin(c[2])]
}

fn mix(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] {
    [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

fn scale(a: [f32; 3], k: f32) -> [f32; 3] {
    [a[0] * k, a[1] * k, a[2] * k]
}

// --- hashing and noise ---------------------------------------------------------------------------

fn mixer(mut z: u64) -> u64 {
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    z ^ (z >> 31)
}

fn hash3(a: i64, b: i64, salt: u64) -> u64 {
    mixer((a as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15) ^ mixer((b as u64) ^ salt.wrapping_mul(0xd6e8_feb8_6659_fd93)))
}

/// A hash as a number in [0, 1).
fn unit(h: u64) -> f64 {
    (h >> 11) as f64 / (1u64 << 53) as f64
}

/// Value noise in [-1, 1] on a lattice of `size` metres.
fn noise(x: f64, y: f64, size: f64, salt: u64) -> f64 {
    let (gx, gy) = (x / size, y / size);
    let (ix, iy) = (gx.floor(), gy.floor());
    let (tx, ty) = (gx - ix, gy - iy);
    let (sx, sy) = (tx * tx * (3.0 - 2.0 * tx), ty * ty * (3.0 - 2.0 * ty));
    let (ix, iy) = (ix as i64, iy as i64);
    let v = |a: i64, b: i64| unit(hash3(a, b, salt)) * 2.0 - 1.0;
    let top = v(ix, iy) + (v(ix + 1, iy) - v(ix, iy)) * sx;
    let bottom = v(ix, iy + 1) + (v(ix + 1, iy + 1) - v(ix, iy + 1)) * sx;
    top + (bottom - top) * sy
}

/// Three octaves of value noise, each turned against the last so no lattice lines show.
fn fbm(x: f64, y: f64, size: f64, salt: u64) -> f64 {
    let (mut sum, mut amp, mut norm) = (0.0, 1.0, 0.0);
    let (mut u, mut v, mut s) = (x, y, size);
    for k in 0..3 {
        sum += amp * noise(u, v, s, salt + k);
        norm += amp;
        amp *= 0.5;
        s *= 0.5;
        (u, v) = (u * 0.8 - v * 0.6 + 1234.5, u * 0.6 + v * 0.8 - 987.6);
    }
    sum / norm
}

/// Coverage of a line of width `w` at distance `d` for a sample `sub` metres wide (box filter).
fn cover(d: f64, w: f64, sub: f64) -> f32 {
    ((w / 2.0 + sub / 2.0 - d) / sub).clamp(0.0, 1.0) as f32
}

// --- fields ------------------------------------------------------------------------------------------

/// Districts: a jittered lattice of this pitch, each point's Voronoi cell one district whose
/// fields share one direction (the land plans of a collective farm).
const DISTRICT: f64 = 7000.0;

struct Field {
    /// palette pick for the crop
    crop: u64,
    /// coverage of the tree belt and of the dirt track at the point
    belt: f32,
    track: f32,
}

fn district_seed(a: i64, b: i64) -> (f64, f64) {
    let h = hash3(a, b, 11);
    ((a as f64 + 0.2 + 0.6 * unit(h)) * DISTRICT, (b as f64 + 0.2 + 0.6 * unit(mixer(h))) * DISTRICT)
}

/// Jittered boundaries of a 1-D row of cells: boundary n stands at (n + jitter) * size.
/// (cell, distance past its lower boundary, distance to its upper one)
fn strip(q: f64, size: f64, jitter: f64, salt: u64) -> (i64, f64, f64) {
    let at = |n: i64| (n as f64 + (unit(hash3(n, 0, salt)) - 0.5) * jitter) * size;
    let mut n = (q / size).floor() as i64;
    if q < at(n) {
        n -= 1;
    } else if q >= at(n + 1) {
        n += 1;
    }
    (n, q - at(n), at(n + 1) - q)
}

fn field(x: f64, y: f64, sub: f64) -> Field {
    let (a, b) = ((x / DISTRICT).floor() as i64, (y / DISTRICT).floor() as i64);
    let (mut d1, mut d2, mut best, mut p1, mut p2) = (f64::INFINITY, f64::INFINITY, (0, 0), (0.0, 0.0), (0.0, 0.0));
    for db in -1..=1 {
        for da in -1..=1 {
            let s = district_seed(a + da, b + db);
            let d = (s.0 - x).hypot(s.1 - y);
            if d < d1 {
                (d2, p2) = (d1, p1);
                (d1, p1, best) = (d, s, (a + da, b + db));
            } else if d < d2 {
                (d2, p2) = (d, s);
            }
        }
    }
    let sep = (p2.0 - p1.0).hypot(p2.1 - p1.1).max(1.0);
    let border = (d2 * d2 - d1 * d1) / (2.0 * sep);
    let h = hash3(best.0, best.1, 23);
    // a region's fields lean one way (the lie of the land, the old roads); a district turns a
    // little from it, a quarter of them square across
    let lean = noise(p1.0, p1.1, 40000.0, 91) * 0.5;
    let across = if unit(mixer(h ^ 7)) < 0.25 { std::f64::consts::FRAC_PI_2 } else { 0.0 };
    let angle = lean + across + (unit(mixer(h)) - 0.5) * 0.3;
    let (c, s) = (angle.cos(), angle.sin());
    let (dx, dy) = (x - p1.0, y - p1.1);
    let (p, q) = (dx * c + dy * s, -dx * s + dy * c);
    let salt = h ^ 0x51;
    // blocks between tree belts, 0.9-1.8 km across and 1.4-3 km long
    let block_w = 900.0 + 900.0 * unit(mixer(h ^ 3));
    let (bn, below_b, above_b) = strip(q, block_w, 0.3, salt);
    let block_l = 1400.0 + 1600.0 * unit(mixer(h ^ 5));
    let (bm, before_b, after_b) = strip(p + unit(hash3(bn, 1, salt)) * block_l, block_l, 0.3, salt ^ 0x1234);
    // fields inside a block: strips 250-600 m wide cut into 400-1500 m
    let bh = hash3(bn, bm, salt ^ 0x99);
    let width = 280.0 + 400.0 * unit(bh);
    let (n, below, above) = strip(below_b, width, 0.4, bh);
    let length = 500.0 + 1300.0 * unit(mixer(bh ^ 3));
    let whole = unit(mixer(bh ^ 4)) < 0.35; // some fields run the block's whole length
    let (m, before, after) = if whole { (0, f64::INFINITY, f64::INFINITY) } else { strip(before_b, length, 0.5, bh ^ hash3(n, 2, bh)) };
    let crop = hash3(n + bn * 64, m + bm * 64, salt ^ 0x77);
    let belt_w = 14.0 + 12.0 * unit(mixer(h ^ 9));
    let mut belt = cover(below_b.min(above_b), belt_w, sub);
    if unit(hash3(bm, 5, salt)) < 0.5 {
        belt = belt.max(cover(before_b.min(after_b), belt_w * 0.8, sub));
    }
    let _ = above;
    let mut track = cover(before.min(after), 5.0, sub).max(cover(below, 4.0, sub) * 0.7);
    // a district's edge is where the furrows turn; half of them follow a dirt road
    if unit(hash3(best.0 + 7, best.1 - 3, 31)) < 0.5 {
        track = track.max(cover(border, 6.0, sub));
    }
    Field { crop, belt, track }
}

// --- palettes ----------------------------------------------------------------------------------------

/// Crops of a Ukrainian summer seen from above, with their weights.
const CROPS: [([u8; 3], u32); 9] = [
    ([178, 154, 92], 18),  // ripe wheat
    ([196, 176, 116], 10), // stubble
    ([104, 128, 58], 16),  // maize, sunflower leaves
    ([84, 110, 50], 10),   // dark green crop
    ([136, 146, 72], 10),  // young crop
    ([98, 82, 62], 10),    // ploughed chernozem
    ([122, 104, 78], 8),   // harrowed soil
    ([150, 140, 88], 8),   // dry grass, fallow
    ([164, 158, 70], 6),   // rapeseed gone to seed
];

const MEADOWS: [([u8; 3], u32); 5] = [
    ([118, 138, 74], 30),
    ([104, 126, 64], 25),
    ([138, 146, 86], 20),
    ([150, 142, 92], 15),
    ([90, 112, 58], 10),
];

const HOUSE_ROOFS: [([u8; 3], u32); 8] = [
    ([148, 72, 54], 18),   // red tile
    ([118, 66, 52], 12),   // brown tile
    ([158, 160, 158], 18), // galvanised sheet
    ([96, 100, 104], 14),  // slate, asbestos sheet
    ([72, 108, 98], 10),   // green metal
    ([166, 96, 64], 8),    // orange tile
    ([108, 50, 44], 10),   // dark red metal
    ([126, 128, 124], 10), // weathered grey
];

const FLAT_ROOFS: [([u8; 3], u32); 5] = [
    ([96, 96, 94], 30),    // bitumen
    ([122, 120, 116], 25), // concrete
    ([82, 84, 86], 20),    // dark membrane
    ([146, 144, 138], 15), // gravel
    ([170, 170, 168], 10), // light membrane
];

fn pick(palette: &[([u8; 3], u32)], h: u64) -> [u8; 3] {
    let total: u32 = palette.iter().map(|p| p.1).sum();
    let mut at = (unit(h) * f64::from(total)) as u32;
    for (c, w) in palette {
        if at < *w {
            return *c;
        }
        at -= w;
    }
    palette[palette.len() - 1].0
}

fn belt_colour(x: f64, y: f64) -> [f32; 3] {
    mix(rgb([46, 66, 38]), rgb([62, 82, 44]), (0.5 + 0.5 * fbm(x, y, 180.0, 41)) as f32)
}

fn track_colour() -> [f32; 3] {
    rgb([168, 152, 118])
}

/// The ground of a cover class at a frame point.
fn ground(class: u8, x: f64, y: f64, sub: f64) -> [f32; 3] {
    match class {
        FARMLAND | NONE => {
            let f = field(x, y, sub);
            let base = if class == FARMLAND || unit(mixer(f.crop ^ 0x33)) < 0.5 {
                rgb(pick(&CROPS, f.crop))
            } else {
                rgb(pick(&MEADOWS, f.crop))
            };
            // a field is not one flat colour: soil and moisture in a few hundred metres
            let base = scale(base, (1.0 + 0.08 * fbm(x, y, 220.0, 43)) as f32);
            let c = mix(base, track_colour(), f.track * 0.7);
            mix(c, belt_colour(x, y), f.belt)
        }
        MEADOW => {
            let c = rgb(pick(&MEADOWS, hash3((x / 300.0).floor() as i64, (y / 300.0).floor() as i64, 47)));
            mix(c, rgb([112, 134, 70]), (0.5 + 0.5 * fbm(x, y, 440.0, 48)) as f32 * 0.6)
        }
        FOREST => {
            // pine and broadleaf stands at hundreds of metres, crowns and gaps below a texel
            let stand = (0.5 + 0.5 * fbm(x, y, 420.0, 51)) as f32;
            let base = mix(rgb([36, 54, 32]), rgb([60, 82, 44]), stand);
            scale(base, (1.0 + 0.1 * fbm(x, y, 120.0, 52)) as f32)
        }
        ORCHARD => scale(rgb([92, 116, 60]), (1.0 + 0.08 * fbm(x, y, 90.0, 55)) as f32),
        RESIDENTIAL => {
            // gardens and yard trees between the roofs
            let t = (0.5 + 0.5 * fbm(x, y, 140.0, 57)) as f32;
            mix(rgb([110, 122, 80]), rgb([66, 90, 50]), t * 0.8)
        }
        PAVED => mix(rgb([136, 134, 128]), rgb([112, 110, 106]), (0.5 + 0.5 * fbm(x, y, 160.0, 59)) as f32),
        PARK => mix(rgb([58, 88, 46]), rgb([86, 112, 58]), (0.5 + 0.5 * fbm(x, y, 140.0, 61)) as f32),
        WETLAND => mix(rgb([86, 102, 70]), rgb([70, 88, 72]), (0.5 + 0.5 * fbm(x, y, 180.0, 63)) as f32),
        BARE => mix(rgb([196, 182, 146]), rgb([170, 156, 124]), (0.5 + 0.5 * fbm(x, y, 240.0, 65)) as f32),
        SCRUB => mix(rgb([92, 108, 64]), rgb([124, 128, 82]), (0.5 + 0.5 * fbm(x, y, 140.0, 67)) as f32),
        SNOW => rgb([232, 236, 240]),
        WATER => rgb([44, 66, 74]),
        SEA => rgb([32, 58, 72]),
        ROCK => mix(rgb([138, 132, 122]), rgb([110, 106, 100]), (0.5 + 0.5 * fbm(x, y, 140.0, 69)) as f32),
        _ => rgb([118, 138, 74]),
    }
}

fn roof_colour(height: f64, h: u64) -> [f32; 3] {
    let c = if height >= 12.0 { pick(&FLAT_ROOFS, h) } else { pick(&HOUSE_ROOFS, h) };
    scale(rgb(c), (0.9 + 0.2 * unit(mixer(h ^ 0x99))) as f32)
}

// --- scanline fill -----------------------------------------------------------------------------------

/// Calls `put(c, r)` for every sample of the g x g grid (sample (c, r) at
/// (x0 + (c + .5) * sub, y0 + (r + .5) * sub)) inside the rings (even-odd).
fn fill(rings: &[Vec<[f64; 2]>], x0: f64, y0: f64, sub: f64, g: usize, mut put: impl FnMut(usize, usize)) {
    let (mut ylo, mut yhi) = (f64::INFINITY, f64::NEG_INFINITY);
    for ring in rings {
        for p in ring {
            ylo = ylo.min(p[1]);
            yhi = yhi.max(p[1]);
        }
    }
    if !ylo.is_finite() {
        return;
    }
    let r0 = (((ylo - y0) / sub - 0.5).ceil().max(0.0)) as usize;
    let r1 = (((yhi - y0) / sub - 0.5).floor()).min(g as f64 - 1.0);
    if r1 < 0.0 {
        return;
    }
    let mut xs: Vec<f64> = Vec::new();
    for r in r0..=r1 as usize {
        let y = y0 + (r as f64 + 0.5) * sub;
        xs.clear();
        for ring in rings {
            let n = ring.len();
            if n < 3 {
                continue;
            }
            let mut j = n - 1;
            for i in 0..n {
                let (a, b) = (ring[i], ring[j]);
                if (a[1] > y) != (b[1] > y) {
                    xs.push(a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]));
                }
                j = i;
            }
        }
        xs.sort_by(f64::total_cmp);
        for pair in xs.chunks_exact(2) {
            let c0 = ((pair[0] - x0) / sub - 0.5).ceil().max(0.0);
            let c1 = ((pair[1] - x0) / sub - 0.5).ceil().min(g as f64);
            let (c0, c1) = (c0 as usize, c1.max(0.0) as usize);
            for c in c0..c1.max(c0) {
                put(c, r);
            }
        }
    }
}

/// The texels of cell (i, j) (`size` metres, `tstep` a texel). `origin`: the region frame's
/// projected origin, for patterns that agree across regions; `sea`: the region's sea level.
pub fn albedo(cell: &FarCell, i: i64, j: i64, size: f64, tstep: f64, sea: Option<f64>, origin: [f64; 2]) -> CellTex {
    let k = (size / tstep).round() as usize;
    let g = k * SUB;
    let sub = tstep / SUB as f64;
    let (x0, y0) = (i as f64 * size, j as f64 * size);
    // cover class of every sample: areas are partitioned, the first that holds a point wins
    let mut class = vec![NONE; g * g];
    for area in cell.areas.iter().rev() {
        let c = area.class;
        fill(&area.rings, x0, y0, sub, g, |a, b| class[b * g + a] = c);
    }
    if let Some(level) = sea {
        for b in 0..g {
            for a in 0..g {
                if class[b * g + a] == NONE {
                    let h = grid_height(cell, size, (a as f64 + 0.5) * sub, (b as f64 + 0.5) * sub);
                    if h <= level + 0.3 {
                        class[b * g + a] = SEA;
                    }
                }
            }
        }
    }
    // roofs: the building index + 1 of every sample under one
    let mut roof = vec![0u32; g * g];
    let mut roofs: Vec<[f32; 3]> = Vec::with_capacity(cell.buildings.len());
    for (n, building) in cell.buildings.iter().enumerate() {
        let (_, cx, cy) = building.rings.first().map(ring_area).unwrap_or((0.0, 0.0, 0.0));
        let h = hash3(((cx + origin[0]) * 4.0) as i64, ((cy + origin[1]) * 4.0) as i64, 71);
        roofs.push(roof_colour(building.height, h));
        fill(&building.rings, x0, y0, sub, g, |a, b| roof[b * g + a] = n as u32 + 1);
    }
    let mut rgb_out = vec![[0.0f32; 3]; k * k];
    let mut rough = vec![0.0f32; k * k];
    let weight = 1.0 / (SUB * SUB) as f32;
    // the relief as an aerial photo shows it: steep banks and gullies read darker (their own
    // shade and the scrub on them), whatever the sun of the moment does to the coarse mesh
    let slope = |a: usize, b: usize| -> f32 {
        let (x, y) = ((a as f64 + 0.5) * sub, (b as f64 + 0.5) * sub);
        let d = sub;
        let gx = grid_height(cell, size, (x + d).min(size), y) - grid_height(cell, size, (x - d).max(0.0), y);
        let gy = grid_height(cell, size, x, (y + d).min(size)) - grid_height(cell, size, x, (y - d).max(0.0));
        ((gx * gx + gy * gy).sqrt() / (2.0 * d)) as f32
    };
    for b in 0..g {
        for a in 0..g {
            let at = b * g + a;
            let c = if roof[at] > 0 {
                roofs[roof[at] as usize - 1]
            } else {
                let (x, y) = (origin[0] + x0 + (a as f64 + 0.5) * sub, origin[1] + y0 + (b as f64 + 0.5) * sub);
                let mut c = ground(class[at], x, y, sub);
                if !matches!(class[at], WATER | SEA | SNOW) {
                    let s = slope(a, b);
                    c = scale(c, 1.0 - 0.22 * (s / 0.45).min(1.0));
                    // the land's slow swings of colour: soils, wetness, haze of a summer afternoon
                    let n1 = noise(x, y, 2400.0, 81) as f32;
                    let n2 = noise(x, y, 700.0, 82) as f32;
                    c = scale(c, 1.0 + 0.07 * n1 + 0.04 * n2);
                    let warm = 0.035 * noise(x, y, 3100.0, 83) as f32;
                    c = [c[0] * (1.0 + warm), c[1], c[2] * (1.0 - warm)];
                }
                c
            };
            let t = &mut rgb_out[(b / SUB) * k + a / SUB];
            t[0] += c[0] * weight;
            t[1] += c[1] * weight;
            t[2] += c[2] * weight;
            let r = if roof[at] > 0 { 0.8 } else if matches!(class[at], WATER | SEA) { 0.12 } else { 0.95 };
            rough[(b / SUB) * k + a / SUB] += r * weight;
        }
    }
    // roads: their width times the length inside each texel, as a share of the texel
    let mut paved = vec![0.0f32; k * k];
    let mut dirt = vec![0.0f32; k * k];
    let area = (tstep * tstep) as f32;
    for road in &cell.roads {
        for w in road.points.windows(2) {
            let (p, q) = (w[0], w[1]);
            let len = (q[0] - p[0]).hypot(q[1] - p[1]);
            let n = (len / (sub * 0.5)).ceil().max(1.0) as usize;
            let piece = (len / n as f64 * road.width) as f32 / area;
            for s in 0..n {
                let t = (s as f64 + 0.5) / n as f64;
                let (x, y) = (p[0] + (q[0] - p[0]) * t - x0, p[1] + (q[1] - p[1]) * t - y0);
                if x < 0.0 || y < 0.0 || x >= size || y >= size {
                    continue;
                }
                let at = ((y / tstep) as usize).min(k - 1) * k + ((x / tstep) as usize).min(k - 1);
                if road.paved { paved[at] += piece } else { dirt[at] += piece }
            }
        }
    }
    let asphalt = rgb([92, 92, 90]);
    let dust = track_colour();
    for at in 0..k * k {
        let c = mix(rgb_out[at], asphalt, paved[at].min(0.9));
        rgb_out[at] = mix(c, dust, dirt[at].min(0.8));
    }
    CellTex { k, rgb: rgb_out, rough }
}

// --- region map, mips and BC1 ------------------------------------------------------------------------

/// The region's texels from its cells ((i, j, texels) in any order): (width, height, linear RGB,
/// row 0 north). Texels of missing cells take their neighbours' colour so filtering at the region's
/// edge does not bleed black.
pub fn assemble(cells: &[(i64, i64, CellTex)]) -> (usize, usize, Vec<[f32; 3]>, Vec<f32>) {
    if cells.is_empty() {
        return (4, 4, vec![[0.1, 0.15, 0.06]; 16], vec![0.95; 16]);
    }
    let k = cells[0].2.k;
    let (mut i0, mut j0, mut i1, mut j1) = (i64::MAX, i64::MAX, i64::MIN, i64::MIN);
    for (i, j, _) in cells {
        i0 = i0.min(*i);
        j0 = j0.min(*j);
        i1 = i1.max(*i);
        j1 = j1.max(*j);
    }
    let (w, h) = (((i1 - i0 + 1) as usize) * k, ((j1 - j0 + 1) as usize) * k);
    let mut out = vec![[0.0f32; 3]; w * h];
    let mut rough = vec![0.95f32; w * h];
    let mut have = vec![false; w * h];
    for (i, j, t) in cells {
        let (ou, ov) = (((i - i0) as usize) * k, ((j - j0) as usize) * k);
        for b in 0..k {
            let row = h - 1 - (ov + b);
            for a in 0..k {
                out[row * w + ou + a] = t.rgb[b * k + a];
                rough[row * w + ou + a] = t.rough[b * k + a];
                have[row * w + ou + a] = true;
            }
        }
    }
    // grow the known texels a few rings into the gaps, then fill the rest with the mean
    for _ in 0..8 {
        let mut next = have.clone();
        let snapshot = out.clone();
        for r in 0..h {
            for c in 0..w {
                if have[r * w + c] {
                    continue;
                }
                let (mut sum, mut n) = ([0.0f32; 3], 0.0f32);
                for (dr, dc) in [(-1i64, 0i64), (1, 0), (0, -1), (0, 1)] {
                    let (rr, cc) = (r as i64 + dr, c as i64 + dc);
                    if rr >= 0 && cc >= 0 && (rr as usize) < h && (cc as usize) < w && have[rr as usize * w + cc as usize] {
                        let v = snapshot[rr as usize * w + cc as usize];
                        sum = [sum[0] + v[0], sum[1] + v[1], sum[2] + v[2]];
                        n += 1.0;
                    }
                }
                if n > 0.0 {
                    out[r * w + c] = scale(sum, 1.0 / n);
                    next[r * w + c] = true;
                }
            }
        }
        have = next;
    }
    let (mut sum, mut n) = ([0.0f32; 3], 0.0f32);
    for (v, &k) in out.iter().zip(&have) {
        if k {
            sum = [sum[0] + v[0], sum[1] + v[1], sum[2] + v[2]];
            n += 1.0;
        }
    }
    let mean = if n > 0.0 { scale(sum, 1.0 / n) } else { [0.1, 0.15, 0.06] };
    for (v, &k) in out.iter_mut().zip(&have) {
        if !k {
            *v = mean;
        }
    }
    (w, h, out, rough)
}

/// The size the game takes for a compressed texture along one axis: a power of two (it refuses
/// any other, "Unable to load compressed texture with non pow2 size", far-view-06), the nearer
/// one on a log scale, from 4 to `max`.
pub fn pow2(n: usize, max: usize) -> usize {
    let mut p = 4usize;
    while p * 2 <= n {
        p *= 2;
    }
    if (n as f64) > (p as f64) * std::f64::consts::SQRT_2 {
        p *= 2;
    }
    p.clamp(4, max.max(4))
}

/// Per output texel along an axis of n -> m texels, edge to edge: the source texels and weights.
/// Shrinking averages the area each output texel covers; growing is linear between centres.
fn axis_weights(n: usize, m: usize) -> Vec<Vec<(usize, f32)>> {
    let r = n as f64 / m as f64;
    (0..m)
        .map(|j| {
            if m <= n {
                let (a, b) = (j as f64 * r, (j + 1) as f64 * r);
                let mut out = Vec::new();
                let mut i = a.floor() as usize;
                while (i as f64) < b && i < n {
                    let w = (b.min((i + 1) as f64) - a.max(i as f64)) / r;
                    if w > 1e-9 {
                        out.push((i, w as f32));
                    }
                    i += 1;
                }
                out
            } else {
                let c = ((j as f64 + 0.5) * r - 0.5).clamp(0.0, (n - 1) as f64);
                let i0 = c.floor() as usize;
                let f = (c - i0 as f64) as f32;
                if i0 + 1 < n && f > 0.0 {
                    vec![(i0, 1.0 - f), (i0 + 1, f)]
                } else {
                    vec![(i0, 1.0)]
                }
            }
        })
        .collect()
}

/// `src` (w x h, row major) resampled to nw x nh, edge to edge: the region's edges stay put, so
/// its UVs do not change. Done on linear values.
pub fn resample<const C: usize>(w: usize, h: usize, src: &[[f32; C]], nw: usize, nh: usize) -> Vec<[f32; C]> {
    if (w, h) == (nw, nh) {
        return src.to_vec();
    }
    let (wx, wy) = (axis_weights(w, nw), axis_weights(h, nh));
    let mut rows = vec![[0.0f32; C]; nw * h];
    for r in 0..h {
        for (x, taps) in wx.iter().enumerate() {
            let mut v = [0.0f32; C];
            for &(i, wt) in taps {
                let s = src[r * w + i];
                for c in 0..C {
                    v[c] += s[c] * wt;
                }
            }
            rows[r * nw + x] = v;
        }
    }
    let mut out = vec![[0.0f32; C]; nw * nh];
    for (y, taps) in wy.iter().enumerate() {
        for x in 0..nw {
            let mut v = [0.0f32; C];
            for &(i, wt) in taps {
                let s = rows[i * nw + x];
                for c in 0..C {
                    v[c] += s[c] * wt;
                }
            }
            out[y * nw + x] = v;
        }
    }
    out
}

/// A grey DDS (DXT1, full mips) of values 0..1 stored as they are (a data map: roughness).
pub fn dds_data(w: usize, h: usize, values: &[f32]) -> Vec<u8> {
    // dds() encodes linear colours to sRGB; hand it the values pre-linearised so they come out as is
    let lin: Vec<[f32; 3]> = values
        .iter()
        .map(|&v| {
            let c = lin(((v.clamp(0.0, 1.0) * 255.0).round()) as u8);
            [c, c, c]
        })
        .collect();
    dds_as(w, h, &lin, false)
}

fn half(w: usize, h: usize, src: &[[f32; 3]]) -> (usize, usize, Vec<[f32; 3]>) {
    let (nw, nh) = ((w / 2).max(1), (h / 2).max(1));
    let mut out = vec![[0.0f32; 3]; nw * nh];
    for r in 0..nh {
        for c in 0..nw {
            let mut sum = [0.0f32; 3];
            let mut n = 0.0f32;
            for (dr, dc) in [(0, 0), (0, 1), (1, 0), (1, 1)] {
                let (rr, cc) = ((2 * r + dr).min(h - 1), (2 * c + dc).min(w - 1));
                let v = src[rr * w + cc];
                sum = [sum[0] + v[0], sum[1] + v[1], sum[2] + v[2]];
                n += 1.0;
            }
            out[r * nw + c] = scale(sum, 1.0 / n);
        }
    }
    (nw, nh, out)
}

fn to565(c: [f32; 3]) -> u16 {
    let r = (c[0].clamp(0.0, 255.0) * 31.0 / 255.0).round() as u16;
    let g = (c[1].clamp(0.0, 255.0) * 63.0 / 255.0).round() as u16;
    let b = (c[2].clamp(0.0, 255.0) * 31.0 / 255.0).round() as u16;
    (r << 11) | (g << 5) | b
}

fn from565(v: u16) -> [f32; 3] {
    let r = f32::from((v >> 11) & 31) * 255.0 / 31.0;
    let g = f32::from((v >> 5) & 63) * 255.0 / 63.0;
    let b = f32::from(v & 31) * 255.0 / 31.0;
    [r, g, b]
}

/// One BC1 block (4 colours, no alpha) of 16 sRGB texels in 0..255.
fn bc1_block(px: &[[f32; 3]; 16]) -> [u8; 8] {
    let mut mean = [0.0f32; 3];
    for p in px {
        for c in 0..3 {
            mean[c] += p[c] / 16.0;
        }
    }
    // principal axis of the block's colours (a few power iterations on the covariance)
    let mut cov = [[0.0f32; 3]; 3];
    for p in px {
        let d = [p[0] - mean[0], p[1] - mean[1], p[2] - mean[2]];
        for a in 0..3 {
            for b in 0..3 {
                cov[a][b] += d[a] * d[b];
            }
        }
    }
    let mut axis = [1.0f32, 1.0, 1.0];
    for _ in 0..6 {
        let v = [
            cov[0][0] * axis[0] + cov[0][1] * axis[1] + cov[0][2] * axis[2],
            cov[1][0] * axis[0] + cov[1][1] * axis[1] + cov[1][2] * axis[2],
            cov[2][0] * axis[0] + cov[2][1] * axis[1] + cov[2][2] * axis[2],
        ];
        let n = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
        if n < 1e-6 {
            break;
        }
        axis = [v[0] / n, v[1] / n, v[2] / n];
    }
    let (mut lo, mut hi) = (f32::INFINITY, f32::NEG_INFINITY);
    for p in px {
        let t = (p[0] - mean[0]) * axis[0] + (p[1] - mean[1]) * axis[1] + (p[2] - mean[2]) * axis[2];
        lo = lo.min(t);
        hi = hi.max(t);
    }
    // inset the ends a little: the extremes are often lone texels
    let inset = (hi - lo) / 32.0;
    let (lo, hi) = (lo + inset, hi - inset);
    let end = |t: f32| [mean[0] + axis[0] * t, mean[1] + axis[1] * t, mean[2] + axis[2] * t];
    let (mut c0, mut c1) = (to565(end(hi)), to565(end(lo)));
    if c0 < c1 {
        std::mem::swap(&mut c0, &mut c1);
    }
    let mut out = [0u8; 8];
    out[0..2].copy_from_slice(&c0.to_le_bytes());
    out[2..4].copy_from_slice(&c1.to_le_bytes());
    if c0 == c1 {
        return out; // all indices 0
    }
    let (a, b) = (from565(c0), from565(c1));
    let palette = [a, b, mix(a, b, 1.0 / 3.0), mix(a, b, 2.0 / 3.0)];
    let mut bits = 0u32;
    for (n, p) in px.iter().enumerate() {
        let mut best = (f32::INFINITY, 0u32);
        for (k, q) in palette.iter().enumerate() {
            let d = (p[0] - q[0]).powi(2) + (p[1] - q[1]).powi(2) + (p[2] - q[2]).powi(2);
            if d < best.0 {
                best = (d, k as u32);
            }
        }
        bits |= best.1 << (2 * n);
    }
    out[4..8].copy_from_slice(&bits.to_le_bytes());
    out
}

fn bc1_level(w: usize, h: usize, lin_rgb: &[[f32; 3]], out: &mut Vec<u8>) {
    let s: Vec<[f32; 3]> = lin_rgb
        .iter()
        .map(|c| [f32::from(srgb(c[0])), f32::from(srgb(c[1])), f32::from(srgb(c[2]))])
        .collect();
    for by in 0..h.div_ceil(4) {
        for bx in 0..w.div_ceil(4) {
            let mut px = [[0.0f32; 3]; 16];
            for y in 0..4 {
                for x in 0..4 {
                    let (r, c) = ((by * 4 + y).min(h - 1), (bx * 4 + x).min(w - 1));
                    px[y * 4 + x] = s[r * w + c];
                }
            }
            out.extend_from_slice(&bc1_block(&px));
        }
    }
}

/// DXGI formats in the DX10 header: BC1 read as it is, and BC1 read as sRGB
pub const BC1_UNORM: u32 = 71;
pub const BC1_UNORM_SRGB: u32 = 72;

/// A colour map: a DDS file (BC1 with the full mip chain) of a linear RGB image, row 0 at the top,
/// marked sRGB. A plain DXT1 header leaves the game reading the bytes as linear: the far land
/// came out pale and grey from the air (far-view-07), as a lawn once did (earthng/fast_dds.py).
pub fn dds(w: usize, h: usize, lin_rgb: &[[f32; 3]]) -> Vec<u8> {
    dds_as(w, h, lin_rgb, true)
}

/// The DDS of dds(), with a DX10 header naming the format: sRGB for colour, UNORM for data.
pub fn dds_as(w: usize, h: usize, lin_rgb: &[[f32; 3]], srgb: bool) -> Vec<u8> {
    let mut levels = 1u32;
    let (mut lw, mut lh) = (w, h);
    while lw > 1 || lh > 1 {
        lw = (lw / 2).max(1);
        lh = (lh / 2).max(1);
        levels += 1;
    }
    let top = (w.div_ceil(4) * h.div_ceil(4) * 8) as u32;
    let mut out = Vec::with_capacity(128 + top as usize * 4 / 3 + 64);
    out.extend_from_slice(b"DDS ");
    let mut head = [0u32; 31];
    head[0] = 124;
    head[1] = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000; // caps height width pixelformat mipmapcount linearsize
    head[2] = h as u32;
    head[3] = w as u32;
    head[4] = top;
    head[6] = levels;
    // pixel format at word 18: size, flags (FOURCC), fourcc
    head[18] = 32;
    head[19] = 0x4;
    head[20] = u32::from_le_bytes(*b"DX10");
    head[26] = 0x1000 | 0x400000 | 0x8; // texture, mipmap, complex
    for v in head {
        out.extend_from_slice(&v.to_le_bytes());
    }
    // DX10 extension: format, 2D texture, no flags, one array slice, no alpha mode
    for v in [if srgb { BC1_UNORM_SRGB } else { BC1_UNORM }, 3, 0, 1, 0] {
        out.extend_from_slice(&v.to_le_bytes());
    }
    let (mut lw, mut lh) = (w, h);
    let mut img = lin_rgb.to_vec();
    for level in 0..levels {
        bc1_level(lw, lh, &img, &mut out);
        if level + 1 < levels {
            let (nw, nh, next) = half(lw, lh, &img);
            (lw, lh, img) = (nw, nh, next);
        }
    }
    out
}

/// A plain PNG-free preview: the image as binary PPM (sRGB), for looking at a map offline.
pub fn ppm(w: usize, h: usize, lin_rgb: &[[f32; 3]]) -> Vec<u8> {
    let mut out = format!("P6\n{w} {h}\n255\n").into_bytes();
    for c in lin_rgb {
        out.extend_from_slice(&[srgb(c[0]), srgb(c[1]), srgb(c[2])]);
    }
    out
}

#[cfg(test)]
mod tests {
    #[test]
    fn pow2_sizes_the_game_takes() {
        assert_eq!(pow2(2380, 2048), 2048);
        assert_eq!(pow2(2460, 4096), 2048);
        assert_eq!(pow2(3000, 4096), 4096);
        assert_eq!(pow2(700, 2048), 512);
        assert_eq!(pow2(730, 2048), 1024);
        assert_eq!(pow2(3, 2048), 4);
        assert_eq!(pow2(2048, 1024), 1024);
    }

    #[test]
    fn resample_keeps_the_edges_and_the_mean() {
        // a 10 x 6 image, west 4 columns dark, the rest bright
        let (w, h) = (10, 6);
        let src: Vec<[f32; 1]> = (0..w * h).map(|k| [if k % w < 4 { 0.0 } else { 1.0 }]).collect();
        for (nw, nh) in [(4usize, 4usize), (16, 8), (8, 2)] {
            let out = resample(w, h, &src, nw, nh);
            let mean: f32 = out.iter().map(|v| v[0]).sum::<f32>() / out.len() as f32;
            if nw <= w {
                assert!((mean - 0.6).abs() < 1e-4, "area is kept when shrinking: {mean}");
            }
            for r in 0..nh {
                assert!(out[r * nw][0] < 0.05, "the west edge stays dark");
                assert!((out[r * nw + nw - 1][0] - 1.0).abs() < 1e-5, "the east edge stays bright");
            }
        }
        let flat = resample(3, 3, &[[0.3f32, 0.5, 0.7]; 9], 4, 4);
        assert!(flat.iter().all(|v| (v[0] - 0.3).abs() < 1e-6 && (v[2] - 0.7).abs() < 1e-6));
    }

    use super::*;
    use crate::far::{FarArea, FarBuilding, FarRoad};

    fn flat(h: f64) -> FarCell {
        FarCell { nx: 2, ny: 2, heights: vec![h; 4], buildings: vec![], areas: vec![], points: vec![], roads: vec![] }
    }

    #[test]
    fn forest_and_roofs_and_a_road() {
        let mut cell = flat(120.0);
        let ring = vec![[0.0, 0.0], [500.0, 0.0], [500.0, 1000.0], [0.0, 1000.0]];
        cell.areas.push(FarArea { class: FOREST, rings: vec![ring], bbox: [0.0, 0.0, 500.0, 1000.0] });
        // a block of flats filling texel (15, 15) exactly
        let block = vec![[750.0, 750.0], [800.0, 750.0], [800.0, 800.0], [750.0, 800.0]];
        cell.buildings.push(FarBuilding { height: 40.0, rings: vec![block] });
        cell.roads.push(FarRoad { width: 10.0, paved: true, points: vec![[525.0, 0.0], [525.0, 1000.0]] });
        let t = albedo(&cell, 0, 0, 1000.0, 50.0, None, [650_000.0, 5_600_000.0]);
        assert_eq!(t.k, 20);
        let at = |c: usize, r: usize| t.rgb[r * 20 + c];
        // forest is dark and green
        let f = at(3, 7);
        assert!(f[1] > f[0] && f[1] > f[2] && f[1] < 0.12, "{f:?}");
        // the roof texel is one of the flat roof greys
        let r = at(15, 15);
        assert!((r[0] - r[1]).abs() < 0.03 && (r[1] - r[2]).abs() < 0.03, "{r:?}");
        // the road column is greyer than its neighbour two texels on
        let (road, field) = (at(10, 4), at(12, 4));
        let grey = |c: [f32; 3]| (c[0] - c[2]).abs() + (c[1] - c[2]).abs();
        assert!(grey(road) < grey(field), "{road:?} {field:?}");
    }

    #[test]
    fn fields_agree_across_cells_and_have_belts() {
        let cell = flat(100.0);
        let o = [600_000.0, 5_500_000.0];
        let a = albedo(&cell, 3, 4, 1000.0, 50.0, None, o);
        let b = albedo(&cell, 2, 4, 1000.0, 50.0, None, [o[0] + 1000.0, o[1]]);
        // cell 3 of origin o is cell 2 of an origin one cell east: the same absolute place
        for (x, y) in a.rgb.iter().zip(&b.rgb) {
            for c in 0..3 {
                assert!((x[c] - y[c]).abs() < 1e-5);
            }
        }
        // over 20 km of open land some texels are tree belt dark
        let mut dark = 0;
        let mut total = 0;
        for i in 0..20 {
            let t = albedo(&cell, i, 0, 1000.0, 50.0, None, o);
            for c in &t.rgb {
                total += 1;
                if c[1] < 0.09 {
                    dark += 1;
                }
            }
        }
        assert!(dark * 100 > total, "{dark} of {total}");
        assert!(dark * 4 < total, "{dark} of {total}");
    }

    #[test]
    fn dds_layout_and_a_flat_block() {
        let img = vec![[0.2f32, 0.3, 0.1]; 8 * 4];
        let d = dds(8, 4, &img);
        assert_eq!(&d[..4], b"DDS ");
        let word = |n: usize| u32::from_le_bytes(d[4 + 4 * n..8 + 4 * n].try_into().unwrap());
        assert_eq!((word(0), word(2), word(3), word(6)), (124, 4, 8, 4));
        assert_eq!(&d[84..88], b"DX10");
        let dx10 = |n: usize| u32::from_le_bytes(d[128 + 4 * n..132 + 4 * n].try_into().unwrap());
        assert_eq!((dx10(0), dx10(1), dx10(3)), (BC1_UNORM_SRGB, 3, 1), "a colour map is read as sRGB");
        let r = dds_data(8, 4, &[0.5; 32]);
        assert_eq!(u32::from_le_bytes(r[128..132].try_into().unwrap()), BC1_UNORM, "a data map is not");
        // levels 8x4, 4x2, 2x1, 1x1: 2 + 1 + 1 + 1 blocks after the 148-byte header
        assert_eq!(d.len(), 148 + 5 * 8);
        // a flat block: both ends the same colour, all indices 0
        assert_eq!(&d[148..150], &d[150..152]);
        assert_eq!(&d[152..156], &[0, 0, 0, 0]);
    }

    #[test]
    fn bc1_keeps_a_two_colour_block() {
        let mut px = [[40.0f32, 70.0, 30.0]; 16];
        for p in px.iter_mut().skip(8) {
            *p = [200.0, 180.0, 120.0];
        }
        let b = bc1_block(&px);
        let c0 = from565(u16::from_le_bytes([b[0], b[1]]));
        let c1 = from565(u16::from_le_bytes([b[2], b[3]]));
        let bits = u32::from_le_bytes(b[4..8].try_into().unwrap());
        let palette = [c0, c1, mix(c0, c1, 1.0 / 3.0), mix(c0, c1, 2.0 / 3.0)];
        for (n, p) in px.iter().enumerate() {
            let q = palette[((bits >> (2 * n)) & 3) as usize];
            assert!((p[0] - q[0]).abs() < 24.0 && (p[1] - q[1]).abs() < 24.0, "{n} {p:?} {q:?}");
        }
    }
}
