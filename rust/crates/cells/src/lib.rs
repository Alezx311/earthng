//! Cells of a native country pack, compiled as earthng/build_country.py compile_cell does, from
//! the same inputs: the source index (sources.sqlite), the raw OSM scenes Python read
//! (Store.save_scene files) and the DEM cache. Geometry goes through shapely's own GEOS, so the
//! encoded payloads are the bytes Python writes. A cell this code does not cover (a coast, a
//! sea harbour) or any error goes back to Python, which compiles it or raises its own error.

pub mod compile;
pub mod geos;
pub mod numeric;
pub mod scene;
