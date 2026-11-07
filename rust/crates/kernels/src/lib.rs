//! earthng_native.dll: numeric kernels the Python Map Builder calls through ctypes
//! (earthng/native_tool.py) until each stage it serves is native as a whole.
//!
//! profile_cg / profile_matvec: fast_profile.solve's Jacobi-preconditioned conjugate gradients
//! and its matrix-vector product, including the clearance springs. A row's sum runs in column
//! order like numpy's add.reduceat, so the product matches numpy bit for bit; the dot products
//! sum fixed blocks in order, the same whatever the thread count (numpy's BLAS orders them its
//! own way, so solutions agree to rounding, not bit for bit).

use std::slice;

use rayon::prelude::*;

pub mod crossings;
pub mod terrain;

const BLOCK: usize = 4096;

fn dot(a: &[f64], b: &[f64]) -> f64 {
    let parts: Vec<f64> = a
        .par_chunks(BLOCK)
        .zip(b.par_chunks(BLOCK))
        .map(|(x, y)| {
            let mut s = 0.0;
            for i in 0..x.len() {
                s += x[i] * y[i];
            }
            s
        })
        .collect();
    parts.iter().sum()
}

pub struct Springs<'a> {
    /// crossing k's four variables and coefficients, xv[i][k], xc[i][k]
    pub xv: [&'a [i64]; 4],
    pub xc: [&'a [f64]; 4],
    pub active: &'a [f64],
    pub weight: f64,
}

impl Springs<'_> {
    fn any(&self) -> bool {
        self.active.iter().any(|&a| a != 0.0)
    }

    /// out += sum_i bincount(v_i, g * c_i), g = weight * active * gap(h), in numpy's order
    fn add(&self, h: &[f64], out: &mut [f64], scratch: &mut Vec<f64>) {
        let n = self.active.len();
        let g: Vec<f64> = (0..n)
            .map(|k| {
                let gap = 0.0 + self.xc[0][k] * h[self.xv[0][k] as usize] + self.xc[1][k] * h[self.xv[1][k] as usize]
                    + self.xc[2][k] * h[self.xv[2][k] as usize] + self.xc[3][k] * h[self.xv[3][k] as usize];
                self.weight * self.active[k] * gap
            })
            .collect();
        for i in 0..4 {
            bincount_add(self.xv[i], (0..n).map(|k| g[k] * self.xc[i][k]), out, scratch);
        }
    }

    /// diag0 + sum_i bincount(v_i, weight * active * c_i * c_i)
    fn diagonal(&self, diag0: &[f64]) -> Vec<f64> {
        let n = self.active.len();
        let mut total = vec![0.0; diag0.len()];
        let mut scratch = Vec::new();
        for i in 0..4 {
            bincount_add(self.xv[i], (0..n).map(|k| self.weight * self.active[k] * self.xc[i][k] * self.xc[i][k]), &mut total, &mut scratch);
        }
        diag0.iter().zip(&total).map(|(d, t)| d + t).collect()
    }
}

/// The springs' bincounts with their bins found once: bins[i] lists the bins of xv[i], each with
/// its entries k in increasing order, as bincount_add sums them. A CG iteration adds the springs
/// without the sort (5 of its 10 ms on Tokyo), the same sums in the same order.
struct Bins {
    /// per i: (bin, start) runs over order[i]; order[i] holds k sorted by (bin, k)
    runs: [Vec<(usize, usize)>; 4],
    order: [Vec<u32>; 4],
}

impl Bins {
    fn of(springs: &Springs) -> Bins {
        let one = |v: &[i64]| {
            let mut order: Vec<u32> = (0..v.len() as u32).collect();
            order.sort_by_key(|&k| (v[k as usize], k));
            let mut runs = Vec::new();
            for (at, &k) in order.iter().enumerate() {
                let j = v[k as usize] as usize;
                if runs.last().is_none_or(|&(b, _): &(usize, usize)| b != j) {
                    runs.push((j, at));
                }
            }
            (runs, order)
        };
        let (r0, o0) = one(springs.xv[0]);
        let (r1, o1) = one(springs.xv[1]);
        let (r2, o2) = one(springs.xv[2]);
        let (r3, o3) = one(springs.xv[3]);
        Bins { runs: [r0, r1, r2, r3], order: [o0, o1, o2, o3] }
    }

    /// Springs::add through the bins
    fn add(&self, springs: &Springs, h: &[f64], out: &mut [f64], g: &mut Vec<f64>) {
        let n = springs.active.len();
        g.clear();
        g.extend((0..n).map(|k| {
            let gap = 0.0 + springs.xc[0][k] * h[springs.xv[0][k] as usize] + springs.xc[1][k] * h[springs.xv[1][k] as usize]
                + springs.xc[2][k] * h[springs.xv[2][k] as usize] + springs.xc[3][k] * h[springs.xv[3][k] as usize];
            springs.weight * springs.active[k] * gap
        }));
        for i in 0..4 {
            let (runs, order, c) = (&self.runs[i], &self.order[i], springs.xc[i]);
            for (r, &(j, start)) in runs.iter().enumerate() {
                let end = runs.get(r + 1).map_or(order.len(), |&(_, e)| e);
                let mut sum = 0.0;
                for &k in &order[start..end] {
                    let k = k as usize;
                    sum += g[k] * c[k];
                }
                out[j] += sum;
            }
        }
    }
}

/// out += np.bincount(v, w, len(out)), the bins summed in order of k first
fn bincount_add(v: &[i64], w: impl Iterator<Item = f64>, out: &mut [f64], scratch: &mut Vec<f64>) {
    if scratch.len() != out.len() {
        *scratch = vec![0.0; out.len()];
    }
    let mut touched: Vec<usize> = Vec::with_capacity(v.len());
    for (&j, x) in v.iter().zip(w) {
        let j = j as usize;
        touched.push(j);
        scratch[j] += x;
    }
    touched.sort_unstable();
    touched.dedup();
    for j in touched {
        out[j] += scratch[j];
        scratch[j] = 0.0;
    }
}

pub struct Csr<'a> {
    pub ptr: &'a [i64],
    pub col: &'a [i64],
    pub data: &'a [f64],
}

impl Csr<'_> {
    fn rows(&self) -> usize {
        self.ptr.len() - 1
    }

    fn matvec(&self, h: &[f64], out: &mut [f64]) {
        out.par_chunks_mut(BLOCK).enumerate().for_each(|(c, chunk)| {
            for (k, o) in chunk.iter_mut().enumerate() {
                let i = c * BLOCK + k;
                let (a, b) = (self.ptr[i] as usize, self.ptr[i + 1] as usize);
                let mut s = self.data[a] * h[self.col[a] as usize];
                for e in a + 1..b {
                    s += h[self.col[e] as usize] * self.data[e];
                }
                *o = s;
            }
        });
    }
}

/// The matrix of a solve with 32-bit columns: a CG iteration streams the whole matrix, so its
/// columns are a third of the memory traffic. Same rows, same order of every sum.
struct Narrow<'a> {
    ptr: &'a [i64],
    col: Vec<u32>,
    data: &'a [f64],
}

impl<'a> Narrow<'a> {
    fn of(a: &Csr<'a>) -> Option<Narrow<'a>> {
        if a.rows() > u32::MAX as usize {
            return None;
        }
        let col = a.col.par_iter().map(|&c| c as u32).collect();
        Some(Narrow { ptr: a.ptr, col, data: a.data })
    }

    fn matvec(&self, h: &[f64], out: &mut [f64]) {
        out.par_chunks_mut(BLOCK).enumerate().for_each(|(c, chunk)| {
            for (k, o) in chunk.iter_mut().enumerate() {
                let i = c * BLOCK + k;
                let (a, b) = (self.ptr[i] as usize, self.ptr[i + 1] as usize);
                // as Csr::matvec (and numpy's reduceat on an empty row: the entry at a)
                let mut s = self.data[a] * h[self.col[a] as usize];
                for e in a + 1..b {
                    s += h[self.col[e] as usize] * self.data[e];
                }
                *o = s;
            }
        });
    }
}

pub fn matvec(a: &Csr, springs: &Springs, h: &[f64], out: &mut [f64], with_springs: bool) {
    a.matvec(h, out);
    if with_springs && springs.any() {
        springs.add(h, out, &mut Vec::new());
    }
}

/// fast_profile.solve's cg(b): (x, iterations, relative residual).
pub fn cg(a: &Csr, diag0: &[f64], springs: &Springs, b: &[f64], iterations: i64, tol: f64) -> (Vec<f64>, i64, f64) {
    let n = a.rows();
    let diag = springs.diagonal(diag0);
    let mut x = vec![0.0; n];
    let mut r = b.to_vec();
    let mut z: Vec<f64> = r.iter().zip(&diag).map(|(r, d)| r / d).collect();
    let mut p = z.clone();
    let mut rz = dot(&r, &z);
    let mut ap = vec![0.0; n];
    let norm0 = { let v = dot(b, b).sqrt(); if v == 0.0 { 1.0 } else { v } };
    let bins = springs.any().then(|| Bins::of(springs));
    let mut g = Vec::new();
    let narrow = Narrow::of(a);
    let mut it = 0i64;
    // r.r of the current r: the loop's test and the end both read it (dot gives the same sum
    // for the same r, so it is kept rather than summed again)
    let mut rr = dot(&r, &r);
    for i in 0..iterations.max(0) {
        it = i;
        if rr.sqrt() < tol * norm0 || rz <= 0.0 {
            break;
        }
        match &narrow {
            Some(m) => m.matvec(&p, &mut ap),
            None => a.matvec(&p, &mut ap),
        }
        if let Some(bins) = &bins {
            bins.add(springs, &p, &mut ap, &mut g);
        }
        let alpha = rz / dot(&p, &ap);
        // x += alpha p, r -= alpha ap and r.r in one pass, r.r in dot's blocks and order
        let parts: Vec<f64> = x
            .par_chunks_mut(BLOCK)
            .zip(r.par_chunks_mut(BLOCK))
            .zip(p.par_chunks(BLOCK).zip(ap.par_chunks(BLOCK)))
            .map(|((x, r), (p, ap))| {
                let mut s = 0.0;
                for i in 0..x.len() {
                    x[i] += p[i] * alpha;
                    r[i] -= ap[i] * alpha;
                    s += r[i] * r[i];
                }
                s
            })
            .collect();
        rr = parts.iter().sum();
        if rr.sqrt() < tol * norm0 {
            break;
        }
        // z = r / diag and r.z in one pass
        let parts: Vec<f64> = z
            .par_chunks_mut(BLOCK)
            .zip(r.par_chunks(BLOCK).zip(diag.par_chunks(BLOCK)))
            .map(|(z, (r, d))| {
                let mut s = 0.0;
                for i in 0..z.len() {
                    z[i] = r[i] / d[i];
                    s += r[i] * z[i];
                }
                s
            })
            .collect();
        let rz2: f64 = parts.iter().sum();
        let beta = rz2 / rz;
        p.par_iter_mut().zip(&z).for_each(|(p, z)| *p = *p * beta + z);
        rz = rz2;
    }
    let residual = rr.sqrt() / norm0;
    (x, it + 1, residual)
}

unsafe fn view<'a, T>(p: *const T, n: usize) -> &'a [T] {
    if n == 0 { &[] } else { unsafe { slice::from_raw_parts(p, n) } }
}

/// The C view of a solve: CSR (nvar + 1 pointers, nnz entries) and the clearance springs
/// (ncross crossings; xv, xc row-major 4 x ncross).
#[repr(C)]
pub struct System {
    pub nvar: usize,
    pub nnz: usize,
    pub ptr: *const i64,
    pub col: *const i64,
    pub data: *const f64,
    pub diag0: *const f64,
    pub ncross: usize,
    pub xv: *const i64,
    pub xc: *const f64,
    pub active: *const f64,
    pub clear_weight: f64,
}

unsafe fn parts<'a>(s: &'a System) -> (Csr<'a>, &'a [f64], Springs<'a>) {
    unsafe {
        let n = s.ncross;
        let xv = view(s.xv, 4 * n);
        let xc = view(s.xc, 4 * n);
        let quarter_v = |i: usize| &xv[i * n..(i + 1) * n];
        let quarter_c = |i: usize| &xc[i * n..(i + 1) * n];
        (
            Csr { ptr: view(s.ptr, s.nvar + 1), col: view(s.col, s.nnz), data: view(s.data, s.nnz) },
            view(s.diag0, s.nvar),
            Springs {
                xv: [quarter_v(0), quarter_v(1), quarter_v(2), quarter_v(3)],
                xc: [quarter_c(0), quarter_c(1), quarter_c(2), quarter_c(3)],
                active: view(s.active, n),
                weight: s.clear_weight,
            },
        )
    }
}

/// # Safety
/// Every pointer of `system` must hold the lengths it declares; `h` and `out` nvar values.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_profile_matvec(system: *const System, h: *const f64, out: *mut f64, springs: i32) -> i32 {
    unsafe {
        let s = &*system;
        let (a, _, sp) = parts(s);
        let out = slice::from_raw_parts_mut(out, s.nvar);
        matvec(&a, &sp, view(h, s.nvar), out, springs != 0);
    }
    0
}

/// # Safety
/// As earthng_profile_matvec; `b` and `x` hold nvar values.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_profile_cg(system: *const System, b: *const f64, iterations: i64, tol: f64,
                                            x: *mut f64, its: *mut i64, residual: *mut f64) -> i32 {
    unsafe {
        let s = &*system;
        let (a, diag0, sp) = parts(s);
        let (sol, n, res) = cg(&a, diag0, &sp, view(b, s.nvar), iterations, tol);
        slice::from_raw_parts_mut(x, s.nvar).copy_from_slice(&sol);
        *its = n;
        *residual = res;
    }
    0
}

/// fast_profile.crossings over n stations (pos n x 2; same n - 1; the rest n). Returns a handle
/// holding the crossings: their count by earthng_crossings_len, copied out and freed by
/// earthng_crossings_take.
///
/// # Safety
/// Every pointer must hold the lengths named.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_profile_crossings(n: usize, pos: *const f64, seg_of: *const i64, same: *const u8, upper: *const u8,
                                                   lower: *const u8, widths: *const f64, levels: *const f64) -> *mut crossings::Crossings {
    unsafe {
        let pos: &[[f64; 2]] = if n == 0 { &[] } else { slice::from_raw_parts(pos as *const [f64; 2], n) };
        let flags = |p: *const u8, len: usize| -> Vec<bool> { view(p, len).iter().map(|&b| b != 0).collect() };
        let found = crossings::crossings(pos, view(seg_of, n), &flags(same, n.saturating_sub(1)), &flags(upper, n), &flags(lower, n),
                                         view(widths, n), view(levels, n));
        Box::into_raw(Box::new(found))
    }
}

/// # Safety
/// `handle` from earthng_profile_crossings, not yet taken.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_crossings_len(handle: *const crossings::Crossings) -> usize {
    unsafe { (*handle).a.len() }
}

/// Copy the crossings out (each array earthng_crossings_len long) and free the handle.
///
/// # Safety
/// `handle` from earthng_profile_crossings, taken once; the arrays hold its length.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_crossings_take(handle: *mut crossings::Crossings, a: *mut i64, b: *mut i64, u: *mut f64, t: *mut f64) {
    unsafe {
        let c = Box::from_raw(handle);
        let n = c.a.len();
        if n > 0 {
            slice::from_raw_parts_mut(a, n).copy_from_slice(&c.a);
            slice::from_raw_parts_mut(b, n).copy_from_slice(&c.b);
            slice::from_raw_parts_mut(u, n).copy_from_slice(&c.u);
            slice::from_raw_parts_mut(t, n).copy_from_slice(&c.t);
        }
    }
}

/// Worker threads of the kernels (0: all cores). Only the first call takes effect.
#[unsafe(no_mangle)]
pub extern "C" fn earthng_threads(n: i64) -> i32 {
    match rayon::ThreadPoolBuilder::new().num_threads(n.max(0) as usize).build_global() {
        Ok(()) => 0,
        Err(_) => 1,
    }
}

/// A DEM reader (terrain::Dem) whose last error message stays readable after a failed call.
pub struct DemHandle {
    dem: terrain::Dem,
    error: String,
}

fn dem_result(h: &mut DemHandle, r: Result<(), terrain::DemError>) -> i32 {
    match r {
        Ok(()) => 0,
        Err(e) => {
            h.error = e.message();
            e.code()
        }
    }
}

/// A Terrain over the DEM cache folder `cache` (UTF-8, `len` bytes) at `zoom` (12, or 13 over
/// z12), in the frame `epsg` (a UTM zone) with origin (cx, cy); null for another CRS.
///
/// # Safety
/// `cache` holds `len` bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_dem_open(cache: *const u8, len: usize, zoom: i32, epsg: u32, cx: f64, cy: f64,
                                          lift: f64) -> *mut DemHandle {
    let Some(utm) = terrain::Dem::epsg(epsg) else { return std::ptr::null_mut() };
    if zoom != 12 && zoom != 13 {
        return std::ptr::null_mut();
    }
    let Ok(path) = std::str::from_utf8(unsafe { slice::from_raw_parts(cache, len) }) else {
        return std::ptr::null_mut();
    };
    let frame = geo::tm::Frame { utm, origin: (cx, cy) };
    let dem = terrain::Dem::new(path.into(), zoom as u32, frame, lift);
    Box::into_raw(Box::new(DemHandle { dem, error: String::new() }))
}

/// # Safety
/// `handle` comes from earthng_dem_open and is not used again.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_dem_close(handle: *mut DemHandle) {
    if !handle.is_null() {
        drop(unsafe { Box::from_raw(handle) });
    }
}

/// Copies the last error message into buf (at most cap bytes); returns its full length.
///
/// # Safety
/// `buf` holds `cap` bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_dem_error(handle: *mut DemHandle, buf: *mut u8, cap: usize) -> usize {
    let h = unsafe { &*handle };
    let bytes = h.error.as_bytes();
    let n = bytes.len().min(cap);
    unsafe { slice::from_raw_parts_mut(buf, n) }.copy_from_slice(&bytes[..n]);
    bytes.len()
}

fn points<'a>(xy: *const f64, n: usize) -> &'a [[f64; 2]] {
    if n == 0 { &[] } else { unsafe { slice::from_raw_parts(xy as *const [f64; 2], n) } }
}

fn values<'a>(out: *mut f64, n: usize) -> &'a mut [f64] {
    if n == 0 { &mut [] } else { unsafe { slice::from_raw_parts_mut(out, n) } }
}

/// Terrain.sample of n points (x, y interleaved) into out. flags: 1 the 5-tap filter, 2 NaN
/// where a tile is missing (Mosaic.sample's missing), 4 float32 pixels (a z13 Mosaic).
/// Returns 0, or 1 no_dem, 2 non-finite, 3 image.
///
/// # Safety
/// `xy` holds 2n values, `out` n.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_dem_sample(handle: *mut DemHandle, xy: *const f64, n: usize, flags: i32,
                                            out: *mut f64) -> i32 {
    let h = unsafe { &mut *handle };
    let r = h.dem.sample_with(points(xy, n), flags & 1 != 0, flags & 2 != 0, flags & 4 != 0, values(out, n));
    dem_result(h, r)
}

/// Despiked.sample of n points into out.
///
/// # Safety
/// As earthng_dem_sample.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_dem_despiked(handle: *mut DemHandle, xy: *const f64, n: usize, spacing: f64,
                                              spike: f64, out: *mut f64) -> i32 {
    let h = unsafe { &mut *handle };
    let r = h.dem.despiked(points(xy, n), spacing, spike, values(out, n));
    dem_result(h, r)
}

/// earthng_dem_despiked through every one of the 25 samples (a check of its calm-ground path).
///
/// # Safety
/// As earthng_dem_sample.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_dem_despiked_full(handle: *mut DemHandle, xy: *const f64, n: usize, spacing: f64,
                                                   spike: f64, out: *mut f64) -> i32 {
    let h = unsafe { &mut *handle };
    let r = h.dem.despiked_full(points(xy, n), spacing, spike, values(out, n));
    dem_result(h, r)
}

/// Despiked.grid of the lattice ys x xs into out (ny * nx, row-major).
///
/// # Safety
/// `xs` holds nx values, `ys` ny, `out` nx * ny.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn earthng_dem_grid(handle: *mut DemHandle, xs: *const f64, nx: usize, ys: *const f64, ny: usize,
                                          spacing: f64, spike: f64, out: *mut f64) -> i32 {
    let h = unsafe { &mut *handle };
    if nx == 0 || ny == 0 {
        return 0;
    }
    let (xs, ys) = unsafe { (slice::from_raw_parts(xs, nx), slice::from_raw_parts(ys, ny)) };
    let r = h.dem.grid(xs, ys, spacing, spike, values(out, nx * ny));
    dem_result(h, r)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cg_solves_a_small_spd_system() {
        // [[4,1,0],[1,3,1],[0,1,2]] x = [1,2,3]
        let ptr = [0i64, 2, 5, 7];
        let col = [0i64, 1, 0, 1, 2, 1, 2];
        let data = [4.0, 1.0, 1.0, 3.0, 1.0, 1.0, 2.0];
        let a = Csr { ptr: &ptr, col: &col, data: &data };
        let diag0 = [4.0, 3.0, 2.0];
        let none: [&[i64]; 4] = [&[], &[], &[], &[]];
        let springs = Springs { xv: none, xc: [&[], &[], &[], &[]], active: &[], weight: 1e4 };
        let (x, its, res) = cg(&a, &diag0, &springs, &[1.0, 2.0, 3.0], 100, 1e-12);
        let mut ax = [0.0; 3];
        matvec(&a, &springs, &x, &mut ax, true);
        assert!(res < 1e-12 && its <= 4, "{its} {res}");
        for (got, want) in ax.iter().zip([1.0, 2.0, 3.0]) {
            assert!((got - want).abs() < 1e-10);
        }
    }

    #[test]
    fn springs_add_like_bincount() {
        let ptr = [0i64, 1, 2];
        let col = [0i64, 1];
        let data = [1.0, 1.0];
        let a = Csr { ptr: &ptr, col: &col, data: &data };
        let v0 = [0i64];
        let v1 = [1i64];
        let springs = Springs { xv: [&v0, &v1, &v0, &v1], xc: [&[1.0], &[-1.0], &[0.0], &[0.0]], active: &[1.0], weight: 2.0 };
        let mut out = [0.0; 2];
        matvec(&a, &springs, &[3.0, 1.0], &mut out, true);
        // gap = 3 - 1 = 2, g = 4: out0 = 3 + 4, out1 = 1 - 4
        assert_eq!(out, [7.0, -3.0]);
    }
}
