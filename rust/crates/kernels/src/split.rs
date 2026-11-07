//! fast_sources._prepare's road split: ways cut at nodes shared with another road (or used twice),
//! points closer than 1 cm to the previous raw point dropped, arc lengths summed as CPython's
//! math.hypot sums them, pieces shorter than 10 cm dropped, coordinates rounded as round(x, 3).

use std::collections::HashMap;

use rayon::prelude::*;

/// CPython 3.13's math.hypot(x, y): vector_norm with its lossless scaling, Dekker products and
/// differential correction (Modules/mathmodule.c), so lengths are Python's to the last bit.
pub fn hypot(x: f64, y: f64) -> f64 {
    let (x, y) = (x.abs(), y.abs());
    let found_nan = x.is_nan() || y.is_nan();
    let mut max = 0.0f64;
    for v in [x, y] {
        if v > max {
            max = v;
        }
    }
    vector_norm([x, y], max, found_nan)
}

/// frexp's exponent: v = m * 2^e with m in [0.5, 1)
fn frexp_exp(v: f64) -> i32 {
    let bits = v.to_bits();
    let e = ((bits >> 52) & 0x7ff) as i32;
    if e == 0 {
        frexp_exp(v * f64::powi(2.0, 64)) - 64
    } else {
        e - 1022
    }
}

/// ldexp(1.0, e) for the exponents vector_norm asks (-1074..=1023)
fn pow2(e: i32) -> f64 {
    if e >= -1022 {
        f64::from_bits(((e + 1023) as u64) << 52)
    } else {
        f64::from_bits(1u64 << (e + 1074))
    }
}

fn dl_mul(x: f64, y: f64) -> (f64, f64) {
    let z = x * y;
    (z, x.mul_add(y, -z))
}

fn dl_fast_sum(a: f64, b: f64) -> (f64, f64) {
    let x = a + b;
    let z = x - a;
    (x, b - z)
}

fn vector_norm(mut vec: [f64; 2], max: f64, found_nan: bool) -> f64 {
    if max.is_infinite() {
        return max;
    }
    if found_nan {
        return f64::NAN;
    }
    if max == 0.0 {
        return max;
    }
    let max_e = frexp_exp(max);
    if max_e < -1023 {
        for v in vec.iter_mut() {
            *v /= f64::MIN_POSITIVE;
        }
        return f64::MIN_POSITIVE * vector_norm(vec, max / f64::MIN_POSITIVE, found_nan);
    }
    let scale = pow2(-max_e);
    let (mut csum, mut frac1, mut frac2) = (1.0f64, 0.0f64, 0.0f64);
    for &v in &vec {
        let x = v * scale;
        let pr = dl_mul(x, x);
        let sm = dl_fast_sum(csum, pr.0);
        csum = sm.0;
        frac1 += pr.1;
        frac2 += sm.1;
    }
    let mut h = (csum - 1.0 + (frac1 + frac2)).sqrt();
    let pr = dl_mul(-h, h);
    let sm = dl_fast_sum(csum, pr.0);
    csum = sm.0;
    frac1 += pr.1;
    frac2 += sm.1;
    let x = csum - 1.0 + (frac1 + frac2);
    h += x / (2.0 * h);
    h / scale
}

/// Python's round(x, 3): the correctly rounded decimal (ties to even), read back
pub fn round3(x: f64) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.3}").parse().unwrap()
}

/// The pieces of the ways, in way order: ints [way, node a, node b, offsets (S + 1), point rows],
/// floats [x, y rounded (2 per point), arc length (1 per point), piece length (S)].
#[derive(Default)]
pub struct Pieces {
    pub way: Vec<i64>,
    pub a: Vec<i64>,
    pub b: Vec<i64>,
    pub off: Vec<i64>,
    pub rows: Vec<i64>,
    pub xy: Vec<f64>,
    pub cum: Vec<f64>,
    pub length: Vec<f64>,
}

/// lens: nodes per way; ids, x, y: every way's nodes in turn.
pub fn split(lens: &[i64], ids: &[i64], x: &[f64], y: &[f64]) -> Pieces {
    let mut refs: HashMap<i64, u32> = HashMap::with_capacity(ids.len());
    for &id in ids {
        *refs.entry(id).or_insert(0) += 1;
    }
    let mut start = Vec::with_capacity(lens.len() + 1);
    start.push(0usize);
    for &n in lens {
        start.push(start.last().unwrap() + n as usize);
    }
    let parts: Vec<Pieces> = (0..lens.len())
        .collect::<Vec<_>>()
        .par_chunks(1024)
        .map(|ways| {
            let mut out = Pieces::default();
            let mut pts: Vec<usize> = Vec::new();
            let mut cum: Vec<f64> = Vec::new();
            for &w in ways {
                let (s, n) = (start[w], lens[w] as usize);
                if n == 0 {
                    continue;
                }
                let mut cuts = vec![0usize];
                for k in 1..n.saturating_sub(1) {
                    if refs[&ids[s + k]] > 1 {
                        cuts.push(k);
                    }
                }
                cuts.push(n - 1);
                for c in cuts.windows(2) {
                    let (a, b) = (c[0], c[1]);
                    pts.clear();
                    pts.push(s + a);
                    for k in a + 1..=b {
                        let (p, q) = (s + k, s + k - 1);
                        if hypot(x[p] - x[q], y[p] - y[q]) > 0.01 {
                            pts.push(p);
                        }
                    }
                    if pts.len() < 2 {
                        continue;
                    }
                    cum.clear();
                    cum.push(0.0);
                    for k in 1..pts.len() {
                        let (p, q) = (pts[k], pts[k - 1]);
                        cum.push(cum[k - 1] + hypot(x[p] - x[q], y[p] - y[q]));
                    }
                    if *cum.last().unwrap() < 0.1 {
                        continue;
                    }
                    out.way.push(w as i64);
                    out.a.push(ids[s + a]);
                    out.b.push(ids[s + b]);
                    out.off.push(pts.len() as i64);
                    for &p in &pts {
                        out.rows.push(p as i64);
                        out.xy.push(round3(x[p]));
                        out.xy.push(round3(y[p]));
                    }
                    out.cum.extend_from_slice(&cum);
                    out.length.push(*cum.last().unwrap());
                }
            }
            out
        })
        .collect();
    let mut all = Pieces { off: vec![0], ..Default::default() };
    for p in parts {
        for count in p.off {
            all.off.push(all.off.last().unwrap() + count);
        }
        all.way.extend(p.way);
        all.a.extend(p.a);
        all.b.extend(p.b);
        all.rows.extend(p.rows);
        all.xy.extend(p.xy);
        all.cum.extend(p.cum);
        all.length.extend(p.length);
    }
    all
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hypot_is_exact_on_easy_values() {
        assert_eq!(hypot(3.0, 4.0), 5.0);
        assert_eq!(hypot(0.0, -0.0), 0.0);
        assert!(hypot(f64::NAN, 1.0).is_nan());
        assert_eq!(hypot(f64::INFINITY, f64::NAN), f64::INFINITY);
    }

    #[test]
    fn round3_ties_to_even() {
        assert_eq!(round3(0.0625), 0.062);
        assert_eq!(round3(0.1875), 0.188);
        assert_eq!(round3(-0.0001).to_bits(), (-0.0f64).to_bits());
        assert_eq!(round3(2.675), 2.675);
    }
}
