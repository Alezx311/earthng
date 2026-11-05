//! The PROJ library pyproj ships (pyproj.libs/proj_9-*.dll), loaded at run time: fast_sources.Frame
//! is pyproj.Transformer.from_crs('EPSG:4326', crs, always_xy=True), and the same PROJ build with
//! the same operation gives its metres to the last bit (the geo crate's series agrees only to
//! nanometres).

use std::ffi::{CString, c_char, c_double, c_int, c_void};
use std::path::Path;
use std::sync::OnceLock;

use anyhow::{Context, Result, anyhow, bail};

type Pj = *mut c_void;
type PjCtx = *mut c_void;

#[allow(non_snake_case)]
struct Api {
    _lib: libloading::Library,
    proj_context_create: unsafe extern "C" fn() -> PjCtx,
    proj_context_destroy: unsafe extern "C" fn(PjCtx) -> PjCtx,
    proj_context_set_search_paths: unsafe extern "C" fn(PjCtx, c_int, *const *const c_char),
    proj_context_errno: unsafe extern "C" fn(PjCtx) -> c_int,
    proj_create_crs_to_crs: unsafe extern "C" fn(PjCtx, *const c_char, *const c_char, *mut c_void) -> Pj,
    proj_normalize_for_visualization: unsafe extern "C" fn(PjCtx, Pj) -> Pj,
    proj_destroy: unsafe extern "C" fn(Pj) -> Pj,
    #[allow(clippy::type_complexity)]
    proj_trans_generic: unsafe extern "C" fn(
        Pj, c_int,
        *mut c_double, usize, usize,
        *mut c_double, usize, usize,
        *mut c_double, usize, usize,
        *mut c_double, usize, usize,
    ) -> usize,
}

static API: OnceLock<Api> = OnceLock::new();

macro_rules! sym {
    ($lib:expr, $name:ident) => {
        *unsafe { $lib.get(concat!(stringify!($name), "\0").as_bytes()) }.with_context(|| concat!("PROJ lacks ", stringify!($name)))?
    };
}

pub fn load(path: &Path) -> Result<()> {
    if API.get().is_some() {
        return Ok(());
    }
    #[cfg(windows)]
    let lib = unsafe {
        // sqlite3, tiff, curl and the C++ runtime sit beside it in pyproj.libs
        libloading::os::windows::Library::load_with_flags(path, libloading::os::windows::LOAD_WITH_ALTERED_SEARCH_PATH)
    }
    .map(libloading::Library::from);
    #[cfg(not(windows))]
    let lib = unsafe { libloading::Library::new(path) };
    let lib = lib.with_context(|| format!("load {}", path.display()))?;
    let api = Api {
        proj_context_create: sym!(lib, proj_context_create),
        proj_context_destroy: sym!(lib, proj_context_destroy),
        proj_context_set_search_paths: sym!(lib, proj_context_set_search_paths),
        proj_context_errno: sym!(lib, proj_context_errno),
        proj_create_crs_to_crs: sym!(lib, proj_create_crs_to_crs),
        proj_normalize_for_visualization: sym!(lib, proj_normalize_for_visualization),
        proj_destroy: sym!(lib, proj_destroy),
        proj_trans_generic: sym!(lib, proj_trans_generic),
        _lib: lib,
    };
    let _ = API.set(api);
    Ok(())
}

/// pyproj.Transformer.from_crs('EPSG:4326', crs, always_xy=True), forward only.
pub struct Forward {
    ctx: PjCtx,
    pj: Pj,
}

impl Forward {
    /// data: pyproj.datadir.get_data_dir() (proj.db)
    pub fn new(crs: &str, data: &Path) -> Result<Forward> {
        let a = API.get().ok_or_else(|| anyhow!("PROJ is not loaded"))?;
        unsafe {
            let ctx = (a.proj_context_create)();
            if ctx.is_null() {
                bail!("PROJ context failed");
            }
            let dir = CString::new(data.to_string_lossy().as_bytes())?;
            let paths = [dir.as_ptr()];
            (a.proj_context_set_search_paths)(ctx, 1, paths.as_ptr());
            let (src, dst) = (CString::new("EPSG:4326")?, CString::new(crs)?);
            let raw = (a.proj_create_crs_to_crs)(ctx, src.as_ptr(), dst.as_ptr(), std::ptr::null_mut());
            if raw.is_null() {
                let e = (a.proj_context_errno)(ctx);
                (a.proj_context_destroy)(ctx);
                bail!("PROJ EPSG:4326 -> {crs} failed ({e})");
            }
            let pj = (a.proj_normalize_for_visualization)(ctx, raw);
            (a.proj_destroy)(raw);
            if pj.is_null() {
                (a.proj_context_destroy)(ctx);
                bail!("PROJ normalize_for_visualization failed");
            }
            Ok(Forward { ctx, pj })
        }
    }

    /// Lon/lat in place to easting/northing, as Transformer.transform(x, y) does on arrays.
    pub fn transform(&self, x: &mut [f64], y: &mut [f64]) -> Result<()> {
        let a = API.get().unwrap();
        let n = x.len();
        assert_eq!(n, y.len());
        if n == 0 {
            return Ok(());
        }
        let s = std::mem::size_of::<f64>();
        let done = unsafe {
            (a.proj_trans_generic)(
                self.pj, 1,
                x.as_mut_ptr(), s, n,
                y.as_mut_ptr(), s, n,
                std::ptr::null_mut(), 0, 0,
                std::ptr::null_mut(), 0, 0,
            )
        };
        if done != n {
            bail!("PROJ transformed {done} of {n} points");
        }
        Ok(())
    }
}

impl Drop for Forward {
    fn drop(&mut self) {
        let a = API.get().unwrap();
        unsafe {
            (a.proj_destroy)(self.pj);
            (a.proj_context_destroy)(self.ctx);
        }
    }
}
