//! fast_profile.crossings: the vertices of the overlap between a deck's station ribbon and the
//! ribbons of the roads under it. The same arithmetic as the numpy code, in the same order (a dot
//! of two 2-vectors is numpy's a0*b0 + a1*b1, no FMA; np.clip as numpy's clip loop), and the
//! results in its order: decks by station, lower edges by hash cell, then by row.

use std::collections::HashMap;

use rayon::prelude::*;

const CELL: f64 = 32.0;
const STEP: f64 = 20.0;
const DECK_OVERHANG: f64 = 2.0;

#[derive(Default)]
pub struct Crossings {
    pub a: Vec<i64>,
    pub b: Vec<i64>,
    pub u: Vec<f64>,
    pub t: Vec<f64>,
}

/// Python's max(x, floor): x unless floor > x (a NaN stays)
fn py_max(x: f64, floor: f64) -> f64 {
    if floor > x { floor } else { x }
}

/// np.clip(x, 0, 1): _NPY_MIN(_NPY_MAX(x, 0), 1), a NaN passes
fn clip01(x: f64) -> f64 {
    let m = if x.is_nan() { x } else if x > 0.0 { x } else { 0.0 };
    if m.is_nan() { m } else if m < 1.0 { m } else { 1.0 }
}

fn dot(a: [f64; 2], b: [f64; 2]) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}

fn sub(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    [a[0] - b[0], a[1] - b[1]]
}

fn add(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    [a[0] + b[0], a[1] + b[1]]
}

/// np.maximum / np.minimum of finite or NaN values: a NaN in the first wins
fn np_max(a: f64, b: f64) -> f64 {
    if a >= b || a.is_nan() { a } else { b }
}

fn np_min(a: f64, b: f64) -> f64 {
    if a <= b || a.is_nan() { a } else { b }
}

fn ribbon(p: [f64; 2], r: [f64; 2], half: f64) -> Vec<[f64; 2]> {
    let scale = half / py_max(dot(r, r).sqrt(), 1e-9);
    let normal = [-r[1] * scale, r[0] * scale];
    let pr = add(p, r);
    vec![sub(p, normal), sub(pr, normal), add(pr, normal), add(p, normal)]
}

fn clip(mut poly: Vec<[f64; 2]>, q: [f64; 2], d: [f64; 2], half: f64) -> Vec<[f64; 2]> {
    let length = dot(d, d).sqrt();
    if length < 1e-9 {
        return Vec::new();
    }
    let axis = [d[0] / length, d[1] / length];
    let normal = [-axis[1], axis[0]];
    let planes = [(axis, 0.0), ([-axis[0], -axis[1]], -length), (normal, -half), ([-normal[0], -normal[1]], -half)];
    for (n, bound) in planes {
        if poly.is_empty() {
            break;
        }
        let mut result = Vec::with_capacity(poly.len() + 2);
        let mut a = poly[poly.len() - 1];
        let mut da = dot(sub(a, q), n) - bound;
        for &b in &poly {
            let db = dot(sub(b, q), n) - bound;
            if (da >= 0.0) != (db >= 0.0) {
                let f = da / (da - db);
                result.push([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]);
            }
            if db >= 0.0 {
                result.push(b);
            }
            a = b;
            da = db;
        }
        poly = result;
    }
    poly
}

/// pos: station positions; same[e]: stations e and e+1 are one segment's; upper / lower: the
/// stations that may be a deck / a road under one; widths and levels per station.
pub fn crossings(pos: &[[f64; 2]], seg_of: &[i64], same: &[bool], upper: &[bool], lower: &[bool], widths: &[f64], levels: &[f64]) -> Crossings {
    let e0: Vec<usize> = (0..same.len()).filter(|&e| same[e]).collect();
    let top: Vec<usize> = e0.iter().copied().filter(|&e| upper[e]).collect();
    let bottom: Vec<usize> = e0.iter().copied().filter(|&e| lower[e]).collect();
    if top.is_empty() || bottom.is_empty() {
        return Crossings::default();
    }
    let mut bins: HashMap<(i64, i64), Vec<u32>> = HashMap::new();
    for (k, &e) in bottom.iter().enumerate() {
        let mid = [(pos[e][0] + pos[e + 1][0]) / 2.0, (pos[e][1] + pos[e + 1][1]) / 2.0];
        bins.entry(((mid[0] / CELL).floor() as i64, (mid[1] / CELL).floor() as i64)).or_default().push(k as u32);
    }
    // np.max(widths[bottom]) / 2 + STEP / 2
    let widest = bottom.iter().map(|&e| widths[e]).fold(f64::NEG_INFINITY, |m, w| if w.is_nan() || m.is_nan() { f64::NAN } else { m.max(w) });
    let reach = widest / 2.0 + STEP / 2.0;
    let found: Vec<Crossings> = top
        .par_iter()
        .map(|&a| {
            let mut out = Crossings::default();
            let p = pos[a];
            let r = sub(pos[a + 1], p);
            let poly = ribbon(p, r, widths[a] / 2.0 + DECK_OVERHANG);
            let low = [poly.iter().map(|v| v[0]).reduce(np_min).unwrap(), poly.iter().map(|v| v[1]).reduce(np_min).unwrap()];
            let high = [poly.iter().map(|v| v[0]).reduce(np_max).unwrap(), poly.iter().map(|v| v[1]).reduce(np_max).unwrap()];
            let lo = [((low[0] - reach) / CELL).floor() as i64, ((low[1] - reach) / CELL).floor() as i64];
            let hi = [((high[0] + reach) / CELL).floor() as i64, ((high[1] + reach) / CELL).floor() as i64];
            let rr = py_max(dot(r, r), 1e-9);
            for x in lo[0]..=hi[0] {
                for y in lo[1]..=hi[1] {
                    let Some(near) = bins.get(&(x, y)) else { continue };
                    for &k in near {
                        let b = bottom[k as usize];
                        if seg_of[a] == seg_of[b] || !(levels[a] > levels[b]) {
                            continue;
                        }
                        let q = pos[b];
                        let d = sub(pos[b + 1], q);
                        let half = widths[b] / 2.0;
                        let qd = add(q, d);
                        let hit = (0..2).all(|c| np_max(q[c], qd[c]) + half >= low[c] && np_min(q[c], qd[c]) - half <= high[c]);
                        if !hit {
                            continue;
                        }
                        let dd = py_max(dot(d, d), 1e-9);
                        for point in clip(poly.clone(), q, d, half) {
                            out.a.push(a as i64);
                            out.b.push(b as i64);
                            out.u.push(clip01(dot(sub(point, p), r) / rr));
                            out.t.push(clip01(dot(sub(point, q), d) / dd));
                        }
                    }
                }
            }
            out
        })
        .collect();
    let mut all = Crossings::default();
    for c in found {
        all.a.extend(c.a);
        all.b.extend(c.b);
        all.u.extend(c.u);
        all.t.extend(c.t);
    }
    all
}
