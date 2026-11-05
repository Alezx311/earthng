//! build_country.compile_cell for inland cells without sea harbours, then country_format's
//! encoder. Every step follows the Python line it replaces; comments name them.

use std::collections::HashSet;
use std::path::PathBuf;

use anyhow::{Context, Result, anyhow, bail};
use earthng_native::terrain::Dem;
use pack::format::{self, Area, Building, Cell, Junction, Line, P3, Point, Road, Terrain};
use serde::Deserialize;
use serde_json::Value;

use crate::geos::{self, Geom, POINT, POLYGON, LINESTRING, Shape};
use crate::numeric::{arange, interp, number, py_max, py_min, unique};
use crate::scene::{self, Scene, Tags};

pub const CELL: f64 = 1000.0;
pub const HALO: f64 = 100.0;
pub const GRID: f64 = 25.0;
pub const SPIKE: f64 = 40.0; // Despiked.SPIKE
pub const ROAD_LIFT: f64 = 0.12;
const SCENES: usize = 9;

#[derive(Deserialize, Clone)]
pub struct DemSpec {
    pub cache: PathBuf,
    pub zoom: u32,
    pub epsg: u32,
    pub cx: f64,
    pub cy: f64,
    pub lift: f64,
}

#[derive(Deserialize, Clone)]
pub struct Config {
    pub index: PathBuf,
    pub scenes: PathBuf,
    pub dem: DemSpec,
    /// grid_step(store): 25, or 10 over a z13 DEM
    pub step: f64,
    #[serde(default)]
    pub include: Option<Value>,
}

/// One cell: (i, j) and the scenery leaves _scenery reads, [x0, y0, x1, y1, tile key].
#[derive(Deserialize)]
pub struct CellTask {
    pub i: i64,
    pub j: i64,
    pub scenery: Vec<(f64, f64, f64, f64, String)>,
}

pub enum Outcome {
    Done { payload: Vec<u8>, roads: usize },
    /// Python compiles it (a case not ported, or any error, which Python then raises itself)
    Python(String),
}

pub struct Worker {
    config: Config,
    db: rusqlite::Connection,
    dem: Dem,
    scenes: Vec<(String, Scene)>,
    /// seconds per stage: query, scene files, scenery, DEM, partition, grid, encode
    pub times: [f64; 7],
}

fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// looks.keep_scenery
pub fn keep_scenery(kind: &str, include: Option<&Value>) -> bool {
    let Some(include) = include.filter(|v| truthy(v)) else { return true };
    let get = |key: &str| include.get(key).map(truthy).unwrap_or(true);
    match kind {
        "building" => get("buildings"),
        "water" => get("water"),
        "fence" | "wall" | "guard_rail" | "hedge" => get("barriers"),
        "tree_row" => get("treeRows"),
        "fuel" | "grocery" | "fast_food" | "post" | "service" | "fuel_site" | "grocery_site" | "fast_food_site"
        | "post_site" | "service_site" | "venue" => get("buildings"),
        "stop" => get("stops"),
        "poi" | "bench" | "waste_basket" | "gate" | "lift_gate" => get("pois"),
        "power" => get("barriers"),
        "path" | "signal" | "traffic_sign" | "road" | "junction" | "crossing" | "give_way" | "stop_sign"
        | "mini_roundabout" | "turning_circle" | "island" | "gantry" | "rail" => true,
        _ => get("cover"),
    }
}

fn floats(v: &Value) -> Option<Vec<f64>> {
    v.as_array()?.iter().map(|x| x.as_f64()).collect()
}

fn string_tags(v: Option<&Value>) -> Result<Tags> {
    let Some(v) = v else { return Ok(Vec::new()) };
    let o = v.as_object().context("tags not an object")?;
    o.iter()
        .map(|(k, v)| Ok((k.clone(), v.as_str().context("a tag value that is not a string")?.to_owned())))
        .collect()
}

/// build_country.road_feature
pub fn road_feature(fid: i64, data: &Value) -> Result<Road> {
    let rows = data["xy"].as_array().context("road xy")?;
    let xy: Vec<[f64; 2]> = rows
        .iter()
        .map(|p| {
            let p = floats(p).filter(|p| p.len() >= 2).context("road xy point")?;
            Ok([p[0], p[1]])
        })
        .collect::<Result<_>>()?;
    let prof = data["prof"].as_array().context("road prof")?;
    let profile: Vec<Vec<f64>> = prof.iter().map(|r| floats(r).context("road prof row")).collect::<Result<_>>()?;
    if xy.len() < 2 || profile.len() != 2 || profile[0].len() != profile[1].len() || profile[0].len() < 2 {
        bail!("road {fid}: invalid centre line or height profile");
    }
    if !xy.iter().flatten().all(|v: &f64| v.is_finite()) || !profile.iter().flatten().all(|v: &f64| v.is_finite()) {
        bail!("road {fid}: non-finite centre line or height profile");
    }
    // np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    let mut distance = Vec::with_capacity(xy.len());
    distance.push(0.0);
    let mut total = 0.0;
    for w in xy.windows(2) {
        let (dx, dy) = (w[1][0] - w[0][0], w[1][1] - w[0][1]);
        total += (dx * dx + dy * dy).sqrt();
        distance.push(total);
    }
    let end = *distance.last().unwrap();
    if !(end > 0.0) || profile[0].windows(2).any(|w| w[1] - w[0] < 0.0) {
        bail!("road {fid}: invalid profile distances");
    }
    let mut all = distance.clone();
    all.extend_from_slice(&profile[0]);
    all.extend(arange(0.0, end, 20.0));
    let knots: Vec<f64> = unique(all).into_iter().filter(|&k| k >= 0.0 && k <= end).collect();
    let xs: Vec<f64> = xy.iter().map(|p| p[0]).collect();
    let ys: Vec<f64> = xy.iter().map(|p| p[1]).collect();
    let (px, py, pz) = (interp(&knots, &distance, &xs), interp(&knots, &distance, &ys), interp(&knots, &profile[0], &profile[1]));
    let points = (0..knots.len()).map(|k| [px[k], py[k], pz[k]]).collect();
    let width = data["width"].as_f64().context("road width")?;
    if !width.is_finite() || width <= 0.0 {
        bail!("road {fid}: invalid width");
    }
    let nodes = data["nodes"]
        .as_array()
        .context("road nodes")?
        .iter()
        .map(|n| match n {
            Value::String(s) => Ok(s.clone()),
            n if n.is_i64() || n.is_u64() => Ok(n.to_string()),
            _ => Err(anyhow!("a node id that is neither an integer nor text")),
        })
        .collect::<Result<_>>()?;
    Ok(Road { id: fid.to_string(), width, tags: string_tags(data.get("tags"))?, nodes, points })
}

fn polygons<S: Shape>(g: &S) -> Vec<geos::Part<'_>> {
    let mut out = Vec::new();
    geos::parts(g, POLYGON, &mut out);
    out
}

fn of_kind<S: Shape>(g: &S, kind: i32) -> Vec<geos::Part<'_>> {
    let mut out = Vec::new();
    geos::parts(g, kind, &mut out);
    out
}

/// One coordinate list still waiting for its terrain heights (_xyz with pending).
fn flat(xy: &[[f64; 2]]) -> Vec<P3> {
    xy.iter().map(|p| [p[0], p[1], f64::NAN]).collect()
}

/// nature.PRIORITY
const PRIORITY: [&str; 17] = ["paved", "water", "glacier", "bare_rock", "scree", "beach", "wetland", "orchard", "vineyard",
    "farmland", "meadow", "heath", "scrub", "forest", "park", "bare_ground", "residential"];

/// nature.partition
pub fn partition(areas: Vec<Area>) -> Result<Vec<Area>> {
    let rank = |kind: &str| PRIORITY.iter().position(|k| *k == kind);
    let mut order: Vec<Area> = areas;
    order.sort_by(|a, b| {
        (rank(&a.kind).unwrap_or(100), a.id.as_bytes()).cmp(&(rank(&b.kind).unwrap_or(100), b.id.as_bytes()))
    });
    let mut claimed: Vec<([f64; 4], Geom)> = Vec::new();
    let mut result = Vec::with_capacity(order.len());
    for feature in order {
        if rank(&feature.kind).is_none() {
            result.push(feature);
            continue;
        }
        let original = geos::polygon(&feature.rings)?.make_valid()?;
        let b = original.bounds()?;
        let near: Vec<&Geom> =
            claimed.iter().filter(|(c, _)| c[0] <= b[2] && c[2] >= b[0] && c[1] <= b[3] && c[3] >= b[1]).map(|(_, g)| g).collect();
        // geometry is original itself when nothing near: equals() still decides, as in Python
        let difference = if near.is_empty() { None } else { Some(original.difference(&geos::union_all(&near)?)?) };
        let geometry = difference.as_ref().unwrap_or(&original);
        if geometry.equals(&original)? {
            drop(difference);
            claimed.push((b, original));
            result.push(feature);
            continue;
        }
        for (n, part) in polygons(geometry).into_iter().enumerate() {
            if part.is_empty()? || part.area()? < 0.01 {
                continue;
            }
            let rings = part
                .rings()
                .iter()
                .map(|r| Ok(r.coords()?.into_iter().map(|p| [p[0], p[1], 0.0]).collect()))
                .collect::<Result<Vec<Vec<P3>>>>()?;
            result.push(Area { id: format!("{}:cover:{n}", feature.id), kind: feature.kind.clone(), tags: feature.tags.clone(), rings });
        }
        drop(difference);
        claimed.push((b, original));
    }
    Ok(result)
}

impl Worker {
    pub fn new(config: Config) -> Result<Worker> {
        let db = rusqlite::Connection::open_with_flags(&config.index, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
            .with_context(|| format!("open {}", config.index.display()))?;
        let utm = Dem::epsg(config.dem.epsg).with_context(|| format!("EPSG:{} is not a UTM zone", config.dem.epsg))?;
        let frame = geo::tm::Frame { utm, origin: (config.dem.cx, config.dem.cy) };
        let dem = Dem::new(config.dem.cache.clone(), config.dem.zoom, frame, config.dem.lift);
        Ok(Worker { config, db, dem, scenes: Vec::new(), times: [0.0; 7] })
    }

    fn scene(&mut self, key: &str) -> Result<usize> {
        if let Some(at) = self.scenes.iter().position(|(k, _)| k == key) {
            let entry = self.scenes.remove(at);
            self.scenes.push(entry);
        } else {
            let path = self.config.scenes.join(format!("{key}.scene"));
            let scene = scene::read(&path)?;
            self.scenes.push((key.to_owned(), scene));
            if self.scenes.len() > SCENES {
                self.scenes.remove(0);
            }
        }
        Ok(self.scenes.len() - 1)
    }

    fn sample(&mut self, points: &mut [P3]) -> Result<()> {
        let xy: Vec<[f64; 2]> = points.iter().map(|p| [p[0], p[1]]).collect();
        let mut z = vec![0.0; xy.len()];
        self.dem.despiked(&xy, GRID, SPIKE, &mut z).map_err(|e| anyhow!(e.message()))?;
        for (p, h) in points.iter_mut().zip(z) {
            if !h.is_finite() {
                bail!("source geometry contains non-finite coordinates or elevations");
            }
            p[2] = h;
        }
        Ok(())
    }

    pub fn compile(&mut self, task: &CellTask) -> Outcome {
        match self.compile_cell(task) {
            Ok(Ok(done)) => done,
            Ok(Err(reason)) => Outcome::Python(reason.into()),
            Err(e) => Outcome::Python(format!("{e:#}")),
        }
    }

    /// Ok(Err(reason)) for a cell left to Python on purpose.
    fn compile_cell(&mut self, task: &CellTask) -> Result<std::result::Result<Outcome, &'static str>> {
        let rect = [task.i as f64 * CELL, task.j as f64 * CELL, (task.i + 1) as f64 * CELL, (task.j + 1) as f64 * CELL];
        let padded = [rect[0] - HALO, rect[1] - HALO, rect[2] + HALO, rect[3] + HALO];
        let include = self.config.include.clone();
        let mut cell = Cell {
            terrain: Terrain { nx: 0, ny: 0, heights: Vec::new() },
            roads: Vec::new(),
            junctions: Vec::new(),
            buildings: Vec::new(),
            areas: Vec::new(),
            lines: Vec::new(),
            points: Vec::new(),
        };
        let mut clock = std::time::Instant::now();
        let mut lap = |times: &mut [f64; 7], k: usize| {
            let now = std::time::Instant::now();
            times[k] += (now - clock).as_secs_f64();
            clock = now;
        };
        // store.query(padded)
        let rows: Vec<(i64, String, String, Vec<u8>)> = {
            let mut q = self.db.prepare_cached(
                "SELECT f.id,f.kind,f.data,f.geom FROM bounds b JOIN features f ON f.id=b.id \
                 WHERE b.x1>=? AND b.x0<=? AND b.y1>=? AND b.y0<=? ORDER BY f.id",
            )?;
            let found = q
                .query_map((padded[0] as i64, padded[2] as i64, padded[1] as i64, padded[3] as i64), |r| {
                    Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get::<_, Option<Vec<u8>>>(3)?.unwrap_or_default()))
                })?
                .collect::<rusqlite::Result<_>>()?;
            found
        };
        let mut seen: HashSet<(String, i64)> = HashSet::new();
        for (fid, kind, data, geom) in rows {
            if !seen.insert((kind.clone(), fid)) {
                continue;
            }
            if kind == "road" {
                let data: Value = serde_json::from_str(&data)?;
                cell.roads.push(road_feature(fid, &data)?);
            } else if kind == "junction" {
                let data: Value = serde_json::from_str(&data)?;
                let height = data["h"].as_f64().context("junction h")? - ROAD_LIFT;
                let geometry = geos::from_wkb(&geom)?;
                for (n, part) in polygons(&geometry).into_iter().enumerate() {
                    let rings = part
                        .rings()
                        .iter()
                        .map(|r| {
                            let ring: Vec<P3> = r.coords()?.into_iter().map(|p| [p[0], p[1], height]).collect();
                            if !ring.iter().flatten().all(|v: &f64| v.is_finite()) {
                                bail!("source geometry contains non-finite coordinates or elevations");
                            }
                            Ok(ring)
                        })
                        .collect::<Result<_>>()?;
                    cell.junctions.push(Junction { id: format!("{fid}:{n}"), height, rings });
                }
            }
        }
        seen.clear();
        lap(&mut self.times, 0);
        let padded_box = geos::rectangle(padded)?;
        let mut point_index = Vec::new();
        for (x0, y0, x1, y1, key) in &task.scenery {
            lap(&mut self.times, 2);
            let at = self.scene(key)?;
            lap(&mut self.times, 1);
            let scene = &self.scenes[at].1;
            for record in scene.query([*x0, *y0, *x1, *y1]) {
                let kind = record.kind.as_str();
                if kind == "coastline" || seen.contains(&(record.kind.clone(), record.fid)) || !keep_scenery(kind, include.as_ref()) {
                    continue;
                }
                seen.insert((record.kind.clone(), record.fid));
                let tags = &record.tags;
                if kind == "water" && tags.iter().find(|(k, _)| k == "water").is_some_and(|(_, v)| v == "harbour") {
                    return Ok(Err("a water=harbour (_at_sea_level, _flood)"));
                }
                let clipped;
                let geometry: &Geom = if kind != "building" && kind != "power" && !padded_box.contains(&record.geom)? {
                    clipped = record.geom.clip_by_rect(padded)?;
                    &clipped
                } else {
                    &record.geom
                };
                let fid = record.fid;
                for (n, part) in polygons(geometry).into_iter().enumerate() {
                    let rings = part
                        .rings()
                        .iter()
                        .map(|r| {
                            let c = r.coords()?;
                            if c.is_empty() {
                                bail!("an empty ring");
                            }
                            Ok(flat(&c))
                        })
                        .collect::<Result<Vec<_>>>()?;
                    let id = format!("{fid}:{n}");
                    if kind == "building" {
                        let get = |k: &str| tags.iter().find(|(t, _)| t == k).map(|(_, v)| v.as_str());
                        let num = |v, d| number(v, d).map_err(|_| anyhow!("a number Python reads differently"));
                        let height = py_max(2.5, py_min(850.0, num(get("height"), num(get("building:levels"), 3.0)? * 3.0)?));
                        let min_height = py_max(0.0, num(get("min_height"), num(get("building:min_level"), 0.0)? * 3.0)?);
                        cell.buildings.push(Building { id, kind: kind.to_owned(), height, min_height, tags: tags.clone(), rings });
                    } else {
                        cell.areas.push(Area { id, kind: kind.to_owned(), tags: tags.clone(), rings });
                    }
                }
                for (n, part) in of_kind(geometry, LINESTRING).into_iter().enumerate() {
                    let c = part.coords()?;
                    if c.is_empty() {
                        bail!("an empty line");
                    }
                    cell.lines.push(Line { id: format!("{fid}:{n}"), kind: kind.to_owned(), tags: tags.clone(), points: flat(&c) });
                }
                for (n, part) in of_kind(geometry, POINT).into_iter().enumerate() {
                    let c = part.coords()?;
                    if c.is_empty() {
                        bail!("an empty point");
                    }
                    point_index.push(cell.points.len());
                    cell.points.push(Point { id: format!("{fid}:{n}"), kind: kind.to_owned(), tags: tags.clone(), pos: [c[0][0], c[0][1], f64::NAN] });
                }
            }
        }
        lap(&mut self.times, 2);
        // _sample_pending: one DEM read of every scenery coordinate
        let mut pending: Vec<P3> = Vec::new();
        for f in &cell.buildings {
            f.rings.iter().for_each(|r| pending.extend_from_slice(r));
        }
        for f in &cell.areas {
            f.rings.iter().for_each(|r| pending.extend_from_slice(r));
        }
        for f in &cell.lines {
            pending.extend_from_slice(&f.points);
        }
        for f in &cell.points {
            pending.push(f.pos);
        }
        self.sample(&mut pending)?;
        let mut z = pending.into_iter();
        let mut fill = |ring: &mut Vec<P3>| ring.iter_mut().for_each(|p| *p = z.next().unwrap());
        cell.buildings.iter_mut().for_each(|f| f.rings.iter_mut().for_each(&mut fill));
        cell.areas.iter_mut().for_each(|f| f.rings.iter_mut().for_each(&mut fill));
        cell.lines.iter_mut().for_each(|f| fill(&mut f.points));
        for f in cell.points.iter_mut() {
            f.pos = z.next().unwrap();
        }
        lap(&mut self.times, 3);
        cell.areas = partition(std::mem::take(&mut cell.areas))?;
        lap(&mut self.times, 4);
        // features.sort(key=id), stable
        cell.roads.sort_by(|a, b| a.id.as_bytes().cmp(b.id.as_bytes()));
        cell.junctions.sort_by(|a, b| a.id.as_bytes().cmp(b.id.as_bytes()));
        cell.buildings.sort_by(|a, b| a.id.as_bytes().cmp(b.id.as_bytes()));
        cell.areas.sort_by(|a, b| a.id.as_bytes().cmp(b.id.as_bytes()));
        cell.lines.sort_by(|a, b| a.id.as_bytes().cmp(b.id.as_bytes()));
        cell.points.sort_by(|a, b| a.id.as_bytes().cmp(b.id.as_bytes()));
        // terrain: Despiked.grid of the cell's lattice
        let step = self.config.step;
        let xs = arange(rect[0], rect[2] + step, step);
        let ys = arange(rect[1], rect[3] + step, step);
        let mut heights = vec![0.0; xs.len() * ys.len()];
        self.dem.grid(&xs, &ys, GRID, SPIKE, &mut heights).map_err(|e| anyhow!(e.message()))?;
        if !heights.iter().all(|h| h.is_finite()) {
            bail!("non-finite terrain grid");
        }
        // _coast: a cell whose DEM reaches near the sea may meet a coastline
        let low = heights.iter().copied().fold(f64::INFINITY, f64::min);
        if !(low > self.config.dem.lift + 60.0) {
            return Ok(Err("near sea level (_coast)"));
        }
        cell.terrain = Terrain { nx: xs.len(), ny: ys.len(), heights };
        let roads = cell.roads.len();
        lap(&mut self.times, 5);
        let payload = format::encode_cell(&cell, [rect[0], rect[1]]).map_err(|e| anyhow!("{e}"))?;
        lap(&mut self.times, 6);
        Ok(Ok(Outcome::Done { payload, roads }))
    }
}

/// Compile cells (in order) with one worker; results by cell.
pub fn run(config: Config, cells: &[CellTask]) -> Result<Vec<Outcome>> {
    let mut worker = Worker::new(config)?;
    let out = cells.iter().map(|c| worker.compile(c)).collect();
    if std::env::var_os("EARTHNG_CELLS_PROFILE").is_some() {
        let names = ["query", "scene files", "scenery", "DEM", "partition", "grid", "encode"];
        for (name, t) in names.iter().zip(worker.times) {
            eprintln!("  {name:12} {t:6.2} s");
        }
    }
    Ok(out)
}
