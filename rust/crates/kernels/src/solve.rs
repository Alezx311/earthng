//! fast_profile.solve's array steps in numpy's arithmetic: csr (COO -> CSR with the duplicates
//! summed as np.add.reduceat sums them) and close_pairs (the station / edge grid hash).

use rayon::prelude::*;

/// numpy's DOUBLE_pairwise_sum: under 8 values in order from -0.0, up to 128 in eight lanes, above
/// that the two halves (the first a multiple of 8) apart.
pub fn pairwise(a: &[f64]) -> f64 {
    let n = a.len();
    if n < 8 {
        let mut r = -0.0;
        for &x in a {
            r += x;
        }
        r
    } else if n <= 128 {
        let mut r = [a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]];
        let mut i = 8;
        while i < n - n % 8 {
            for j in 0..8 {
                r[j] += a[i + j];
            }
            i += 8;
        }
        let mut res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        while i < n {
            res += a[i];
            i += 1;
        }
        res
    } else {
        let mut n2 = n / 2;
        n2 -= n2 % 8;
        pairwise(&a[..n2]) + pairwise(&a[n2..])
    }
}

/// np.add.reduceat over one run: its first value plus the pairwise sum of the rest
fn reduce_run(a: &[f64]) -> f64 {
    a[0] + pairwise(&a[1..])
}

/// fast_profile.csr: (ptr, col, data) of n rows, entries sorted by (row, col) stably, duplicates
/// summed in that order.
pub fn csr(rows: &[i64], cols: &[i64], vals: &[f64], n: i64) -> (Vec<i64>, Vec<i64>, Vec<f64>) {
    let mut order: Vec<(i64, u32)> = rows.par_iter().zip(cols.par_iter()).enumerate().map(|(i, (r, c))| (r * n + c, i as u32)).collect();
    // (key, position): sorting the pairs is argsort(key, kind='stable')
    order.par_sort_unstable();
    let sorted: Vec<f64> = order.par_iter().map(|&(_, i)| vals[i as usize]).collect();
    let mut starts = Vec::new();
    for (i, &(k, _)) in order.iter().enumerate() {
        if i == 0 || order[i - 1].0 != k {
            starts.push(i);
        }
    }
    let m = starts.len();
    let data: Vec<f64> = (0..m)
        .into_par_iter()
        .map(|u| {
            let end = if u + 1 < m { starts[u + 1] } else { sorted.len() };
            reduce_run(&sorted[starts[u]..end])
        })
        .collect();
    let col: Vec<i64> = starts.iter().map(|&s| order[s].0 % n).collect();
    let mut ptr = vec![0i64; n as usize + 1];
    for &s in &starts {
        ptr[(order[s].0 / n) as usize + 1] += 1;
    }
    for i in 0..n as usize {
        ptr[i + 1] += ptr[i];
    }
    (ptr, col, data)
}

/// np.clip(x, 0, 1) as numpy's clip loop: _NPY_MIN(_NPY_MAX(x, 0), 1)
fn clip01(x: f64) -> f64 {
    let m = if x.is_nan() || x > 0.0 { x } else { 0.0 };
    if m.is_nan() || m < 1.0 { m } else { 1.0 }
}

const CELL: f64 = 24.0;
const M: i64 = 1 << 21;

fn key(x: f64, y: f64, dx: i64, dy: i64) -> i64 {
    ((x / CELL).floor() as i64 + dx + M) * (2 * M) + (y / CELL).floor() as i64 + dy + M
}

/// fast_profile.close_pairs: (station a, edge start e, t) in numpy's order — the nine neighbour
/// cells in turn, in each the stations in order and their edges by sorted key.
pub fn close_pairs(pos: &[[f64; 2]], seg_of: &[i64], width: &[f64], ground: &[bool], same: &[bool]) -> (Vec<i64>, Vec<i64>, Vec<f64>) {
    let e0: Vec<usize> = (0..same.len()).filter(|&e| same[e]).collect();
    let mut keyed: Vec<(i64, usize)> = e0
        .iter()
        .enumerate()
        .map(|(j, &e)| {
            let mid = [(pos[e][0] + pos[e + 1][0]) / 2.0, (pos[e][1] + pos[e + 1][1]) / 2.0];
            (key(mid[0], mid[1], 0, 0), j)
        })
        .collect();
    keyed.sort_unstable();                         // (key, position): a stable argsort
    let skey: Vec<i64> = keyed.iter().map(|k| k.0).collect();
    let (mut oa, mut oe, mut ot) = (Vec::new(), Vec::new(), Vec::new());
    for dx in -1..=1 {
        for dy in -1..=1 {
            let found: Vec<(Vec<i64>, Vec<i64>, Vec<f64>)> = pos
                .par_chunks(4096)
                .enumerate()
                .map(|(c, chunk)| {
                    let (mut a, mut e, mut t) = (Vec::new(), Vec::new(), Vec::new());
                    for (k, p) in chunk.iter().enumerate() {
                        let ia = c * 4096 + k;
                        let nk = key(p[0], p[1], dx, dy);
                        let lo = skey.partition_point(|&s| s < nk);
                        let hi = skey.partition_point(|&s| s <= nk);
                        for &(_, j) in &keyed[lo..hi] {
                            let ie = e0[j];
                            if seg_of[ia] == seg_of[ie] || !ground[ia] || !ground[ie] {
                                continue;
                            }
                            let (pa, pb) = (pos[ie], pos[ie + 1]);
                            let ab = [pb[0] - pa[0], pb[1] - pa[1]];
                            let l2 = ab[0] * ab[0] + ab[1] * ab[1];
                            let l2 = if l2 >= 1e-9 || l2.is_nan() { l2 } else { 1e-9 }; // np.maximum(L2, 1e-9)
                            let tt = clip01(((p[0] - pa[0]) * ab[0] + (p[1] - pa[1]) * ab[1]) / l2);
                            let q = [p[0] - (pa[0] + ab[0] * tt), p[1] - (pa[1] + ab[1] * tt)];
                            let d = (q[0] * q[0] + q[1] * q[1]).sqrt();
                            if d < (width[ia] + width[ie]) / 2.0 + 0.5 {
                                a.push(ia as i64);
                                e.push(ie as i64);
                                t.push(tt);
                            }
                        }
                    }
                    (a, e, t)
                })
                .collect();
            for (a, e, t) in found {
                oa.extend(a);
                oe.extend(e);
                ot.extend(t);
            }
        }
    }
    (oa, oe, ot)
}

/// The result of a kernel: arrays of i64 and f64, taken by index.
#[derive(Default)]
pub struct Out {
    pub ints: Vec<Vec<i64>>,
    pub floats: Vec<Vec<f64>>,
}
