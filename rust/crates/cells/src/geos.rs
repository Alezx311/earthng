//! The GEOS C API of the geos_c library shapely ships (loaded at run time): the same build, so
//! clipping, validity repair and overlay give shapely's vertices exactly.
//!
//! Only what compile_cell calls. Each thread has its own GEOS context; a geometry is used only
//! on the thread that made it.

use std::cell::RefCell;
use std::ffi::{c_char, c_double, c_int, c_uint, c_void};
use std::path::Path;
use std::sync::OnceLock;

use anyhow::{Context, Result, anyhow, bail};

type Ctx = *mut c_void;
type G = *mut c_void;
type Cs = *mut c_void;

macro_rules! api {
    ($($name:ident : fn($($arg:ty),*) $(-> $ret:ty)?;)*) => {
        #[allow(non_snake_case)]
        struct Api { _lib: libloading::Library, $($name: unsafe extern "C" fn($($arg),*) $(-> $ret)?,)* }
        impl Api {
            #[allow(non_snake_case)]
            unsafe fn load(lib: libloading::Library) -> Result<Api> {
                $(let $name = unsafe {
                    *lib.get::<unsafe extern "C" fn($($arg),*) $(-> $ret)?>(concat!(stringify!($name), "\0").as_bytes())
                        .with_context(|| concat!("GEOS lacks ", stringify!($name)))?
                };)*
                Ok(Api { _lib: lib, $($name,)* })
            }
        }
    };
}

api! {
    GEOS_init_r: fn() -> Ctx;
    GEOS_finish_r: fn(Ctx);
    GEOSversion: fn() -> *const c_char;
    GEOSWKBReader_create_r: fn(Ctx) -> *mut c_void;
    GEOSWKBReader_destroy_r: fn(Ctx, *mut c_void);
    GEOSWKBReader_read_r: fn(Ctx, *mut c_void, *const u8, usize) -> G;
    GEOSGeom_destroy_r: fn(Ctx, G);
    GEOSGeom_clone_r: fn(Ctx, G) -> G;
    GEOSGeomTypeId_r: fn(Ctx, G) -> c_int;
    GEOSisEmpty_r: fn(Ctx, G) -> c_char;
    GEOSGetNumGeometries_r: fn(Ctx, G) -> c_int;
    GEOSGetGeometryN_r: fn(Ctx, G, c_int) -> G;
    GEOSGetExteriorRing_r: fn(Ctx, G) -> G;
    GEOSGetNumInteriorRings_r: fn(Ctx, G) -> c_int;
    GEOSGetInteriorRingN_r: fn(Ctx, G, c_int) -> G;
    GEOSGeom_getCoordSeq_r: fn(Ctx, G) -> Cs;
    GEOSCoordSeq_getSize_r: fn(Ctx, Cs, *mut c_uint) -> c_int;
    GEOSCoordSeq_copyToBuffer_r: fn(Ctx, Cs, *mut c_double, c_int, c_int) -> c_int;
    GEOSCoordSeq_copyFromBuffer_r: fn(Ctx, *const c_double, c_uint, c_int, c_int) -> Cs;
    GEOSGeom_getXMin_r: fn(Ctx, G, *mut c_double) -> c_int;
    GEOSGeom_getYMin_r: fn(Ctx, G, *mut c_double) -> c_int;
    GEOSGeom_getXMax_r: fn(Ctx, G, *mut c_double) -> c_int;
    GEOSGeom_getYMax_r: fn(Ctx, G, *mut c_double) -> c_int;
    GEOSContains_r: fn(Ctx, G, G) -> c_char;
    GEOSEquals_r: fn(Ctx, G, G) -> c_char;
    GEOSClipByRect_r: fn(Ctx, G, c_double, c_double, c_double, c_double) -> G;
    GEOSGeom_createLinearRing_r: fn(Ctx, Cs) -> G;
    GEOSGeom_createPolygon_r: fn(Ctx, G, *mut G, c_uint) -> G;
    GEOSGeom_createCollection_r: fn(Ctx, c_int, *mut G, c_uint) -> G;
    GEOSMakeValidParams_create_r: fn(Ctx) -> *mut c_void;
    GEOSMakeValidParams_destroy_r: fn(Ctx, *mut c_void);
    GEOSMakeValidParams_setMethod_r: fn(Ctx, *mut c_void, c_int) -> c_int;
    GEOSMakeValidParams_setKeepCollapsed_r: fn(Ctx, *mut c_void, c_int) -> c_int;
    GEOSMakeValidWithParams_r: fn(Ctx, G, *const c_void) -> G;
    GEOSDifference_r: fn(Ctx, G, G) -> G;
    GEOSUnaryUnion_r: fn(Ctx, G) -> G;
    GEOSArea_r: fn(Ctx, G, *mut c_double) -> c_int;
    GEOSPointOnSurface_r: fn(Ctx, G) -> G;
    GEOSCovers_r: fn(Ctx, G, G) -> c_char;
    GEOSFree_r: fn(Ctx, *mut c_void);
    GEOSWKBWriter_create_r: fn(Ctx) -> *mut c_void;
    GEOSWKBWriter_destroy_r: fn(Ctx, *mut c_void);
    GEOSWKBWriter_setOutputDimension_r: fn(Ctx, *mut c_void, c_int);
    GEOSWKBWriter_write_r: fn(Ctx, *mut c_void, G, *mut usize) -> *mut u8;
    GEOSSTRtree_create_r: fn(Ctx, usize) -> *mut c_void;
    GEOSSTRtree_insert_r: fn(Ctx, *mut c_void, G, *mut c_void);
    GEOSSTRtree_build_r: fn(Ctx, *mut c_void) -> c_int;
    GEOSSTRtree_query_r: fn(Ctx, *mut c_void, G, extern "C" fn(*mut c_void, *mut c_void), *mut c_void);
    GEOSSTRtree_destroy_r: fn(Ctx, *mut c_void);
}

static API: OnceLock<Api> = OnceLock::new();

/// Load geos_c (shapely's: shapely.libs/geos_c-*.dll on Windows, beside its geos dll).
pub fn load(path: &Path) -> Result<String> {
    if API.get().is_none() {
        #[cfg(windows)]
        let lib = unsafe {
            // its geos and msvcp140 dependencies sit beside it, as shapely's wheel has them
            libloading::os::windows::Library::load_with_flags(path, libloading::os::windows::LOAD_WITH_ALTERED_SEARCH_PATH)
        }
        .map(libloading::Library::from);
        #[cfg(not(windows))]
        let lib = unsafe { libloading::Library::new(path) };
        let lib = lib.with_context(|| format!("load {}", path.display()))?;
        let api = unsafe { Api::load(lib)? };
        let _ = API.set(api);
    }
    Ok(version())
}

pub fn version() -> String {
    let api = api();
    unsafe { std::ffi::CStr::from_ptr((api.GEOSversion)()) }.to_string_lossy().into_owned()
}

fn api() -> &'static Api {
    API.get().expect("GEOS is not loaded")
}

struct Local {
    ctx: Ctx,
    reader: *mut c_void,
    writer: *mut c_void,
    valid: *mut c_void,
}

impl Drop for Local {
    fn drop(&mut self) {
        let a = api();
        unsafe {
            (a.GEOSWKBReader_destroy_r)(self.ctx, self.reader);
            (a.GEOSWKBWriter_destroy_r)(self.ctx, self.writer);
            (a.GEOSMakeValidParams_destroy_r)(self.ctx, self.valid);
            (a.GEOS_finish_r)(self.ctx);
        }
    }
}

thread_local! {
    static CONTEXT: RefCell<Option<Local>> = const { RefCell::new(None) };
}

fn with<T>(f: impl FnOnce(&Local) -> T) -> T {
    CONTEXT.with(|c| {
        let mut c = c.borrow_mut();
        if c.is_none() {
            let a = api();
            unsafe {
                let ctx = (a.GEOS_init_r)();
                let reader = (a.GEOSWKBReader_create_r)(ctx);
                // shapely.to_wkb's defaults: output_dimension 3, the machine's byte order, extended flavor
                let writer = (a.GEOSWKBWriter_create_r)(ctx);
                (a.GEOSWKBWriter_setOutputDimension_r)(ctx, writer, 3);
                // shapely.make_valid's defaults: method 'linework', keep_collapsed True
                let valid = (a.GEOSMakeValidParams_create_r)(ctx);
                (a.GEOSMakeValidParams_setMethod_r)(ctx, valid, 0);
                (a.GEOSMakeValidParams_setKeepCollapsed_r)(ctx, valid, 1);
                *c = Some(Local { ctx, reader, writer, valid });
            }
        }
        f(c.as_ref().unwrap())
    })
}

fn ctx() -> Ctx {
    with(|c| c.ctx)
}

pub const POINT: i32 = 0;
pub const LINESTRING: i32 = 1;
pub const POLYGON: i32 = 3;
pub const COLLECTION: i32 = 7;

/// An owned GEOS geometry.
pub struct Geom(G);

/// A part owned by a parent geometry.
#[derive(Clone, Copy)]
pub struct Part<'a>(G, std::marker::PhantomData<&'a Geom>);

fn owned(g: G, what: &str) -> Result<Geom> {
    if g.is_null() { Err(anyhow!("GEOS {what} failed")) } else { Ok(Geom(g)) }
}

fn flag(v: c_char, what: &str) -> Result<bool> {
    match v {
        0 => Ok(false),
        1 => Ok(true),
        _ => bail!("GEOS {what} failed"),
    }
}

impl Drop for Geom {
    fn drop(&mut self) {
        unsafe { (api().GEOSGeom_destroy_r)(ctx(), self.0) }
    }
}

pub trait Shape {
    fn ptr(&self) -> G;

    fn type_id(&self) -> i32 {
        unsafe { (api().GEOSGeomTypeId_r)(ctx(), self.ptr()) }
    }
    fn is_empty(&self) -> Result<bool> {
        flag(unsafe { (api().GEOSisEmpty_r)(ctx(), self.ptr()) }, "isEmpty")
    }
    fn count(&self) -> usize {
        unsafe { (api().GEOSGetNumGeometries_r)(ctx(), self.ptr()) }.max(0) as usize
    }
    fn part(&self, n: usize) -> Part<'_> {
        Part(unsafe { (api().GEOSGetGeometryN_r)(ctx(), self.ptr(), n as c_int) }, Default::default())
    }
    /// A polygon's exterior then interior rings.
    fn rings(&self) -> Vec<Part<'_>> {
        let (a, c) = (api(), ctx());
        let mut out = vec![Part(unsafe { (a.GEOSGetExteriorRing_r)(c, self.ptr()) }, Default::default())];
        let n = unsafe { (a.GEOSGetNumInteriorRings_r)(c, self.ptr()) }.max(0);
        for k in 0..n {
            out.push(Part(unsafe { (a.GEOSGetInteriorRingN_r)(c, self.ptr(), k) }, Default::default()));
        }
        out
    }
    /// XY of a point, line or ring, as shapely's .coords.
    fn coords(&self) -> Result<Vec<[f64; 2]>> {
        let (a, c) = (api(), ctx());
        unsafe {
            let seq = (a.GEOSGeom_getCoordSeq_r)(c, self.ptr());
            if seq.is_null() {
                bail!("GEOS getCoordSeq failed");
            }
            let mut n: c_uint = 0;
            if (a.GEOSCoordSeq_getSize_r)(c, seq, &mut n) == 0 {
                bail!("GEOS getSize failed");
            }
            let mut out = vec![[0.0; 2]; n as usize];
            if n > 0 && (a.GEOSCoordSeq_copyToBuffer_r)(c, seq, out.as_mut_ptr() as *mut f64, 0, 0) == 0 {
                bail!("GEOS copyToBuffer failed");
            }
            Ok(out)
        }
    }
    /// shapely's bounds: NaN for an empty geometry.
    fn bounds(&self) -> Result<[f64; 4]> {
        if self.is_empty()? {
            return Ok([f64::NAN; 4]);
        }
        let (a, c) = (api(), ctx());
        let mut b = [0.0; 4];
        unsafe {
            if (a.GEOSGeom_getXMin_r)(c, self.ptr(), &mut b[0]) == 0
                || (a.GEOSGeom_getYMin_r)(c, self.ptr(), &mut b[1]) == 0
                || (a.GEOSGeom_getXMax_r)(c, self.ptr(), &mut b[2]) == 0
                || (a.GEOSGeom_getYMax_r)(c, self.ptr(), &mut b[3]) == 0
            {
                bail!("GEOS bounds failed");
            }
        }
        Ok(b)
    }
    fn contains(&self, other: &impl Shape) -> Result<bool> {
        flag(unsafe { (api().GEOSContains_r)(ctx(), self.ptr(), other.ptr()) }, "contains")
    }
    fn equals(&self, other: &impl Shape) -> Result<bool> {
        flag(unsafe { (api().GEOSEquals_r)(ctx(), self.ptr(), other.ptr()) }, "equals")
    }
    fn area(&self) -> Result<f64> {
        let mut v = 0.0;
        if unsafe { (api().GEOSArea_r)(ctx(), self.ptr(), &mut v) } == 0 {
            bail!("GEOS area failed");
        }
        Ok(v)
    }
    fn clip_by_rect(&self, r: [f64; 4]) -> Result<Geom> {
        owned(unsafe { (api().GEOSClipByRect_r)(ctx(), self.ptr(), r[0], r[1], r[2], r[3]) }, "clipByRect")
    }
    fn make_valid(&self) -> Result<Geom> {
        with(|c| owned(unsafe { (api().GEOSMakeValidWithParams_r)(c.ctx, self.ptr(), c.valid) }, "makeValid"))
    }
    fn difference(&self, other: &impl Shape) -> Result<Geom> {
        owned(unsafe { (api().GEOSDifference_r)(ctx(), self.ptr(), other.ptr()) }, "difference")
    }
    fn clone_geom(&self) -> Result<Geom> {
        owned(unsafe { (api().GEOSGeom_clone_r)(ctx(), self.ptr()) }, "clone")
    }
    fn covers(&self, other: &impl Shape) -> Result<bool> {
        flag(unsafe { (api().GEOSCovers_r)(ctx(), self.ptr(), other.ptr()) }, "covers")
    }
    /// shapely's representative_point()
    fn point_on_surface(&self) -> Result<Geom> {
        owned(unsafe { (api().GEOSPointOnSurface_r)(ctx(), self.ptr()) }, "pointOnSurface")
    }
    /// shapely.to_wkb(geometry) with its defaults
    fn wkb(&self) -> Result<Vec<u8>> {
        with(|c| unsafe {
            let mut n = 0usize;
            let buf = (api().GEOSWKBWriter_write_r)(c.ctx, c.writer, self.ptr(), &mut n);
            if buf.is_null() {
                bail!("GEOS WKB write failed");
            }
            let out = std::slice::from_raw_parts(buf, n).to_vec();
            (api().GEOSFree_r)(c.ctx, buf as *mut c_void);
            Ok(out)
        })
    }
}

impl Shape for Geom {
    fn ptr(&self) -> G {
        self.0
    }
}

impl Shape for Part<'_> {
    fn ptr(&self) -> G {
        self.0
    }
}

pub fn from_wkb(wkb: &[u8]) -> Result<Geom> {
    with(|c| owned(unsafe { (api().GEOSWKBReader_read_r)(c.ctx, c.reader, wkb.as_ptr(), wkb.len()) }, "WKB read"))
}

fn ring(points: &[[f64; 3]]) -> Result<Geom> {
    let (a, c) = (api(), ctx());
    // shapely closes an open ring (all dimensions compared) and needs four coordinates
    let mut pts = points.to_vec();
    if let (Some(first), Some(last)) = (pts.first().copied(), pts.last().copied()) {
        if first != last {
            pts.push(first);
        }
    }
    if pts.len() < 4 {
        bail!("a linearring requires at least 4 coordinates");
    }
    let seq = unsafe { (a.GEOSCoordSeq_copyFromBuffer_r)(c, pts.as_ptr() as *const f64, pts.len() as c_uint, 1, 0) };
    if seq.is_null() {
        bail!("GEOS coordinate sequence failed");
    }
    owned(unsafe { (a.GEOSGeom_createLinearRing_r)(c, seq) }, "linearRing")
}

/// shapely.Polygon(rings[0], rings[1:]) of XYZ rings.
pub fn polygon(rings: &[Vec<[f64; 3]>]) -> Result<Geom> {
    let shell = ring(&rings[0])?;
    let mut holes = rings[1..].iter().map(|r| ring(r)).collect::<Result<Vec<_>>>()?;
    let mut raw: Vec<G> = holes.iter().map(|h| h.0).collect();
    let g = unsafe { (api().GEOSGeom_createPolygon_r)(ctx(), shell.0, raw.as_mut_ptr(), raw.len() as c_uint) };
    // the polygon owns its rings now (or GEOS freed them on failure)
    std::mem::forget(shell);
    for h in holes.drain(..) {
        std::mem::forget(h);
    }
    owned(g, "polygon")
}

/// shapely.box(x0, y0, x1, y1): counter-clockwise from (x1, y0).
pub fn rectangle(r: [f64; 4]) -> Result<Geom> {
    let [x0, y0, x1, y1] = r;
    let pts = [[x1, y0, 0.0], [x1, y1, 0.0], [x0, y1, 0.0], [x0, y0, 0.0], [x1, y0, 0.0]];
    let (a, c) = (api(), ctx());
    // XY only, as shapely's box
    let xy: Vec<f64> = pts.iter().flat_map(|p| [p[0], p[1]]).collect();
    let seq = unsafe { (a.GEOSCoordSeq_copyFromBuffer_r)(c, xy.as_ptr(), 5, 0, 0) };
    if seq.is_null() {
        bail!("GEOS coordinate sequence failed");
    }
    let shell = owned(unsafe { (a.GEOSGeom_createLinearRing_r)(c, seq) }, "linearRing")?;
    let g = unsafe { (a.GEOSGeom_createPolygon_r)(c, shell.0, std::ptr::null_mut(), 0) };
    std::mem::forget(shell);
    owned(g, "box")
}

/// shapely.union_all(geometries): a GeometryCollection of clones, unary-unioned.
pub fn union_all(geometries: &[&Geom]) -> Result<Geom> {
    let clones = geometries.iter().map(|g| g.clone_geom()).collect::<Result<Vec<_>>>()?;
    let mut raw: Vec<G> = clones.iter().map(|g| g.0).collect();
    let collection = unsafe { (api().GEOSGeom_createCollection_r)(ctx(), COLLECTION, raw.as_mut_ptr(), raw.len() as c_uint) };
    for g in clones {
        std::mem::forget(g);
    }
    let collection = owned(collection, "collection")?;
    owned(unsafe { (api().GEOSUnaryUnion_r)(ctx(), collection.0) }, "unaryUnion")
}

/// shapely's _parts(geometry, kind) order: the geometry itself, else its members depth first.
pub fn parts<'a, S: Shape>(g: &'a S, kind: i32, out: &mut Vec<Part<'a>>) {
    // every member is owned by g, so all of them live as long as g
    fn walk<'a>(p: G, kind: i32, out: &mut Vec<Part<'a>>) {
        let part = Part::<'a>(p, Default::default());
        let t = part.type_id();
        if t == kind {
            out.push(part);
        } else if (4..=7).contains(&t) {
            for n in 0..part.count() {
                walk(part.part(n).0, kind, out);
            }
        }
    }
    walk(g.ptr(), kind, out)
}

/// shapely.STRtree(geometries) (node_capacity 10, empty geometries left out) and its query
/// without a predicate: indices in the order GEOS visits them, which shapely does not sort.
pub struct Tree<'a> {
    tree: *mut c_void,
    _geoms: std::marker::PhantomData<&'a Geom>,
}

extern "C" fn collect(item: *mut c_void, data: *mut c_void) {
    unsafe { (*(data as *mut Vec<usize>)).push(item as usize) }
}

impl<'a> Tree<'a> {
    pub fn new(geometries: &[&'a Geom]) -> Result<Tree<'a>> {
        let (a, c) = (api(), ctx());
        let tree = unsafe { (a.GEOSSTRtree_create_r)(c, 10) };
        if tree.is_null() {
            bail!("GEOS STRtree failed");
        }
        let mut count = 0;
        for (i, g) in geometries.iter().enumerate() {
            if !g.is_empty()? {
                unsafe { (a.GEOSSTRtree_insert_r)(c, tree, g.0, i as *mut c_void) };
                count += 1;
            }
        }
        if count > 0 {
            unsafe { (a.GEOSSTRtree_build_r)(c, tree) };
        }
        Ok(Tree { tree, _geoms: Default::default() })
    }

    pub fn query(&self, g: &impl Shape) -> Result<Vec<usize>> {
        let mut out: Vec<usize> = Vec::new();
        if g.is_empty()? {
            return Ok(out);
        }
        unsafe { (api().GEOSSTRtree_query_r)(ctx(), self.tree, g.ptr(), collect, &mut out as *mut Vec<usize> as *mut c_void) };
        Ok(out)
    }
}

impl Drop for Tree<'_> {
    fn drop(&mut self) {
        unsafe { (api().GEOSSTRtree_destroy_r)(ctx(), self.tree) }
    }
}
