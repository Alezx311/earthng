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
    let springs_on = springs.any();
    let mut scratch = Vec::new();
    let mut it = 0i64;
    for i in 0..iterations.max(0) {
        it = i;
        if dot(&r, &r).sqrt() < tol * norm0 || rz <= 0.0 {
            break;
        }
        a.matvec(&p, &mut ap);
        if springs_on {
            springs.add(&p, &mut ap, &mut scratch);
        }
        let alpha = rz / dot(&p, &ap);
        x.par_iter_mut().zip(&p).for_each(|(x, p)| *x += p * alpha);
        r.par_iter_mut().zip(&ap).for_each(|(r, ap)| *r -= ap * alpha);
        if dot(&r, &r).sqrt() < tol * norm0 {
            break;
        }
        z.par_iter_mut().zip(&r).zip(&diag).for_each(|((z, r), d)| *z = r / d);
        let rz2 = dot(&r, &z);
        let beta = rz2 / rz;
        p.par_iter_mut().zip(&z).for_each(|(p, z)| *p = *p * beta + z);
        rz = rz2;
    }
    let residual = dot(&r, &r).sqrt() / norm0;
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

/// Worker threads of the kernels (0: all cores). Only the first call takes effect.
#[unsafe(no_mangle)]
pub extern "C" fn earthng_threads(n: i64) -> i32 {
    match rayon::ThreadPoolBuilder::new().num_threads(n.max(0) as usize).build_global() {
        Ok(()) => 0,
        Err(_) => 1,
    }
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
