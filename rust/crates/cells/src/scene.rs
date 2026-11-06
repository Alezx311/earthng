//! Scene files (fast_sources.Store.save_scene): the records of one raw OSM tile.
//!
//! ```text
//! 'ESC1' u32 count, count x (i64 fid, u16 kind length, kind, u32 tags length, tags as a JSON
//! list of [key, value], u32 WKB length, WKB of the local geometry), little-endian, by fid
//! ```

use std::path::Path;

use anyhow::{Context, Result, bail};

use crate::geos::{self, Geom, Shape};

pub type Tags = Vec<(String, String)>;

pub struct Record {
    pub fid: i64,
    pub kind: String,
    pub tags: Tags,
    pub geom: Geom,
    /// envelope (x0, y0, x1, y1): what shapely's STRtree indexes
    pub envelope: [f64; 4],
}

pub struct Scene {
    /// records with a non-empty geometry (an STRtree leaves out the empty ones)
    pub records: Vec<Record>,
}

fn take<'a>(data: &'a [u8], at: &mut usize, n: usize) -> Result<&'a [u8]> {
    let end = at.checked_add(n).filter(|&e| e <= data.len()).context("truncated scene")?;
    let out = &data[*at..end];
    *at = end;
    Ok(out)
}

pub fn read(path: &Path) -> Result<Scene> {
    let data = std::fs::read(path).with_context(|| format!("read {}", path.display()))?;
    let mut at = 0;
    if take(&data, &mut at, 4)? != b"ESC1" {
        bail!("{} is not a scene file", path.display());
    }
    let count = u32::from_le_bytes(take(&data, &mut at, 4)?.try_into()?) as usize;
    let mut records = Vec::with_capacity(count);
    for _ in 0..count {
        let fid = i64::from_le_bytes(take(&data, &mut at, 8)?.try_into()?);
        let n = u16::from_le_bytes(take(&data, &mut at, 2)?.try_into()?) as usize;
        let kind = std::str::from_utf8(take(&data, &mut at, n)?)?.to_owned();
        let n = u32::from_le_bytes(take(&data, &mut at, 4)?.try_into()?) as usize;
        let tags: Tags = serde_json::from_slice(take(&data, &mut at, n)?).context("scene tags")?;
        let n = u32::from_le_bytes(take(&data, &mut at, 4)?.try_into()?) as usize;
        let geom = geos::from_wkb(take(&data, &mut at, n)?)?;
        if geom.is_empty()? {
            continue;
        }
        let envelope = geom.bounds()?;
        records.push(Record { fid, kind, tags, geom, envelope });
    }
    Ok(Scene { records })
}

/// (fid, geometry) of a scene's records of one kind with a non-empty geometry, in file order,
/// as read() keeps them; other records are skipped unparsed (a coast tile's coastlines cost a
/// scan, not a whole scene).
pub fn read_kind(path: &Path, want: &str) -> Result<Vec<(i64, Geom)>> {
    let data = std::fs::read(path).with_context(|| format!("read {}", path.display()))?;
    let mut at = 0;
    if take(&data, &mut at, 4)? != b"ESC1" {
        bail!("{} is not a scene file", path.display());
    }
    let count = u32::from_le_bytes(take(&data, &mut at, 4)?.try_into()?) as usize;
    let mut out = Vec::new();
    for _ in 0..count {
        let fid = i64::from_le_bytes(take(&data, &mut at, 8)?.try_into()?);
        let n = u16::from_le_bytes(take(&data, &mut at, 2)?.try_into()?) as usize;
        let kind = take(&data, &mut at, n)?;
        let n = u32::from_le_bytes(take(&data, &mut at, 4)?.try_into()?) as usize;
        take(&data, &mut at, n)?;
        let n = u32::from_le_bytes(take(&data, &mut at, 4)?.try_into()?) as usize;
        let wkb = take(&data, &mut at, n)?;
        if kind == want.as_bytes() {
            let geom = geos::from_wkb(wkb)?;
            if !geom.is_empty()? {
                out.push((fid, geom));
            }
        }
    }
    Ok(out)
}

impl Scene {
    /// Store.scenery: the records whose envelope meets rect, in file order.
    pub fn query(&self, r: [f64; 4]) -> impl Iterator<Item = &Record> {
        self.records.iter().filter(move |rec| {
            let e = rec.envelope;
            e[0] <= r[2] && e[2] >= r[0] && e[1] <= r[3] && e[3] >= r[1]
        })
    }
}
