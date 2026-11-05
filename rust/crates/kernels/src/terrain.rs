//! fast_sources.Terrain and build_country.Despiked: Terrarium heights sampled bilinearly in a
//! local UTM frame, single-spot spikes replaced by the median of their 5 x 5 neighbourhood.
//!
//! The arithmetic follows the numpy code operation for operation. The frame's inverse
//! projection is geo::tm (Krüger series), not PROJ: lon/lat agree to ~1e-11 degrees, so a
//! height can differ in its last bits and, very rarely, round to the next centimetre.

use std::collections::HashMap;
use std::fs::File;
use std::io::BufReader;
use std::path::PathBuf;
use std::rc::Rc;

use geo::tm::{Frame, Utm};

const SIDE: i64 = 256;
const CACHE: usize = 96;

#[derive(Debug)]
pub enum DemError {
    /// a tile that is not in the cache: the cell has no elevation there
    Missing(PathBuf),
    /// a z12 neighbour a z13 tile is upsampled from: an error even where a missing tile is NaN
    MissingBelow(PathBuf),
    NonFinite,
    Image(String),
}

impl DemError {
    pub fn code(&self) -> i32 {
        match self {
            DemError::Missing(_) | DemError::MissingBelow(_) => 1,
            DemError::NonFinite => 2,
            DemError::Image(_) => 3,
        }
    }

    pub fn message(&self) -> String {
        match self {
            DemError::Missing(path) | DemError::MissingBelow(path) => format!("no_dem: {}", path.display()),
            DemError::NonFinite => "non-finite DEM".into(),
            DemError::Image(text) => text.clone(),
        }
    }
}

type Image = Rc<Vec<f64>>;

pub struct Dem {
    cache: PathBuf,
    zoom: u32,
    frame: Frame,
    lift: f64,
    images: HashMap<(i64, i64), (Image, u64)>,
    clock: u64,
    last: Option<((i64, i64), Image)>,
    coarse: Option<Box<Dem>>,
}

impl Dem {
    pub fn new(cache: PathBuf, zoom: u32, frame: Frame, lift: f64) -> Dem {
        let coarse = (zoom == 13).then(|| Box::new(Dem::new(cache.clone(), 12, frame, lift)));
        Dem { cache, zoom, frame, lift, images: HashMap::new(), clock: 0, last: None, coarse }
    }

    pub fn epsg(code: u32) -> Option<Utm> {
        Utm::epsg(code)
    }

    fn path(&self, a: i64, b: i64) -> PathBuf {
        self.cache.join("terrain").join(self.zoom.to_string()).join(a.to_string()).join(format!("{b}.png"))
    }

    fn decode(path: &PathBuf) -> Result<Vec<f64>, DemError> {
        let file = File::open(path).map_err(|e| DemError::Image(format!("{}: {e}", path.display())))?;
        let mut decoder = png::Decoder::new(BufReader::new(file));
        decoder.set_transformations(png::Transformations::normalize_to_color8());
        let mut reader = decoder.read_info().map_err(|e| DemError::Image(format!("{}: {e}", path.display())))?;
        let mut buf = vec![0; reader.output_buffer_size()];
        let info = reader.next_frame(&mut buf).map_err(|e| DemError::Image(format!("{}: {e}", path.display())))?;
        if info.width as i64 != SIDE || info.height as i64 != SIDE {
            return Err(DemError::Image(format!("{}: not a 256 x 256 tile", path.display())));
        }
        let channels = info.color_type.samples();
        let rgb = |k: usize| -> (u8, u8, u8) {
            let p = &buf[k * channels..];
            match info.color_type {
                png::ColorType::Grayscale | png::ColorType::GrayscaleAlpha => (p[0], p[0], p[0]),
                _ => (p[0], p[1], p[2]),
            }
        };
        // rgb[:,:,0]*256 + rgb[:,:,1] + rgb[:,:,2]/256 - 32768, in float64 as numpy does it
        Ok((0..(SIDE * SIDE) as usize)
            .map(|k| {
                let (r, g, b) = rgb(k);
                r as f64 * 256.0 + g as f64 + b as f64 / 256.0 - 32768.0
            })
            .collect())
    }

    /// Terrain.upsampled: z13 tile a/b from the z12 heights (pixel X of z13 is X/2 of z12).
    fn upsampled(&mut self, a: i64, b: i64) -> Result<Vec<f64>, DemError> {
        let coarse = self.coarse.as_mut().expect("z13 has a coarse level");
        let mut out = Vec::with_capacity((SIDE * SIDE) as usize);
        for row in 0..SIDE {
            let gy = (b * SIDE + row) as f64 / 2.0;
            let iy = gy.floor() as i64;
            let v = gy - iy as f64;
            for col in 0..SIDE {
                let gx = (a * SIDE + col) as f64 / 2.0;
                let ix = gx.floor() as i64;
                let u = gx - ix as f64;
                let (p0, p1) = (coarse.pixel(ix, iy)?, coarse.pixel(ix + 1, iy)?);
                let (p2, p3) = (coarse.pixel(ix, iy + 1)?, coarse.pixel(ix + 1, iy + 1)?);
                out.push((p0 * (1.0 - u) + p1 * u) * (1.0 - v) + (p2 * (1.0 - u) + p3 * u) * v);
            }
        }
        Ok(out)
    }

    fn image(&mut self, a: i64, b: i64) -> Result<Image, DemError> {
        if let Some((key, image)) = &self.last
            && *key == (a, b)
        {
            return Ok(image.clone());
        }
        self.clock += 1;
        let clock = self.clock;
        let image = if let Some((image, used)) = self.images.get_mut(&(a, b)) {
            *used = clock;
            image.clone()
        } else {
            let path = self.path(a, b);
            let heights = if path.is_file() {
                Dem::decode(&path)?
            } else if self.zoom == 13 && self.coarse.as_ref().is_some_and(|c| c.path(a.div_euclid(2), b.div_euclid(2)).is_file()) {
                // Terrain.has: the z12 tile under it is there; a neighbour it reaches into must be
                self.upsampled(a, b).map_err(|e| match e {
                    DemError::Missing(p) => DemError::MissingBelow(p),
                    other => other,
                })?
            } else {
                return Err(DemError::Missing(path));
            };
            if self.images.len() >= CACHE {
                let oldest = *self.images.iter().min_by_key(|(_, (_, used))| *used).unwrap().0;
                self.images.remove(&oldest);
            }
            let image = Rc::new(heights);
            self.images.insert((a, b), (image.clone(), clock));
            image
        };
        self.last = Some(((a, b), image.clone()));
        Ok(image)
    }

    #[inline]
    fn pixel(&mut self, x: i64, y: i64) -> Result<f64, DemError> {
        let image = self.image(x.div_euclid(SIDE), y.div_euclid(SIDE))?;
        Ok(image[(y.rem_euclid(SIDE) * SIDE + x.rem_euclid(SIDE)) as usize])
    }

    /// Web Mercator pixel coordinates of a local point at the DEM's zoom.
    #[inline]
    fn pixel_xy(&self, x: f64, y: f64) -> (f64, f64) {
        let (lon, lat) = self.frame.geographic(x, y);
        let scale = (256u64 << self.zoom) as f64;
        let px = (lon + 180.0) / 360.0 * scale;
        let py = (1.0 - lat.to_radians().tan().asinh() / std::f64::consts::PI) / 2.0 * scale;
        (px, py)
    }

    /// True when every pixel the 5 x 5 samples `spacing` apart round p can read lies within less
    /// than `spike` of every other: then the median is within `spike` of the centre, and
    /// despike() keeps the centre. The pixel box is grown by one pixel past the four corners'
    /// (the map from metres to pixels is affine to far less than a pixel over 100 m). False
    /// where a pixel is not available: the full path then reads (and fails) as before.
    fn calm(&mut self, p: [f64; 2], spacing: f64, spike: f64) -> bool {
        let r = 2.0 * spacing;
        let a = self.pixel_xy(p[0] - r, p[1] - r);
        let b = self.pixel_xy(p[0] + r, p[1] - r);
        let c = self.pixel_xy(p[0] - r, p[1] + r);
        let d = (b.0 + c.0 - a.0, b.1 + c.1 - a.1);
        let (xs, ys) = ([a.0, b.0, c.0, d.0], [a.1, b.1, c.1, d.1]);
        if !xs.iter().chain(&ys).all(|v| v.is_finite()) {
            return false;
        }
        let lo = |v: &[f64; 4]| v.iter().copied().fold(f64::INFINITY, f64::min).floor() as i64 - 1;
        let hi = |v: &[f64; 4]| v.iter().copied().fold(f64::NEG_INFINITY, f64::max).floor() as i64 + 2;
        let (x0, x1, y0, y1) = (lo(&xs), hi(&xs), lo(&ys), hi(&ys));
        if (x1 - x0 + 1) * (y1 - y0 + 1) > 1024 {
            return false;
        }
        let (mut low, mut high) = (f64::INFINITY, f64::NEG_INFINITY);
        for y in y0..=y1 {
            for x in x0..=x1 {
                match self.pixel(x, y) {
                    Ok(v) => {
                        low = low.min(v);
                        high = high.max(v);
                    }
                    Err(_) => return false,
                }
            }
        }
        // the margin covers the rounding of the bilinear sums and of the lift
        high - low < spike - 1e-6
    }

    /// Terrain.sample of one local point, without the finite check and the lift. single: the
    /// pixels rounded to float32 as fast_profile.Mosaic keeps a z13 grid.
    fn height(&mut self, x: f64, y: f64, smooth: bool, single: bool) -> Result<f64, DemError> {
        let (px, py) = self.pixel_xy(x, y);
        let (ix, iy) = (px.floor() as i64, py.floor() as i64);
        let (u, v) = (px - ix as f64, py - iy as f64);
        const ONE: [(i64, i64, f64); 1] = [(0, 0, 1.0)];
        const FIVE: [(i64, i64, f64); 5] = [(0, 0, 0.5), (-1, 0, 0.125), (1, 0, 0.125), (0, -1, 0.125), (0, 1, 0.125)];
        let mut z = 0.0;
        for &(dx, dy, weight) in if smooth { &FIVE[..] } else { &ONE[..] } {
            let (x0, y0) = (ix + dx, iy + dy);
            let (mut p0, mut p1) = (self.pixel(x0, y0)?, self.pixel(x0 + 1, y0)?);
            let (mut p2, mut p3) = (self.pixel(x0, y0 + 1)?, self.pixel(x0 + 1, y0 + 1)?);
            if single {
                (p0, p1, p2, p3) = (p0 as f32 as f64, p1 as f32 as f64, p2 as f32 as f64, p3 as f32 as f64);
            }
            z += weight * ((p0 * (1.0 - u) + p1 * u) * (1.0 - v) + (p2 * (1.0 - u) + p3 * u) * v);
        }
        Ok(z)
    }

    /// Terrain.sample: heights of local points plus the lift.
    pub fn sample(&mut self, xy: &[[f64; 2]], smooth: bool, out: &mut [f64]) -> Result<(), DemError> {
        self.sample_with(xy, smooth, false, false, out)
    }

    /// sample(), or fast_profile.Mosaic.sample with `missing`: NaN where a tile is not in the
    /// cache instead of an error, and no finite check.
    pub fn sample_with(&mut self, xy: &[[f64; 2]], smooth: bool, missing: bool, single: bool, out: &mut [f64])
                       -> Result<(), DemError> {
        let mut finite = true;
        for (p, o) in xy.iter().zip(out.iter_mut()) {
            *o = match self.height(p[0], p[1], smooth, single) {
                Err(DemError::Missing(_)) if missing => f64::NAN,
                other => other?,
            };
            finite &= o.is_finite();
        }
        if !finite && !missing {
            return Err(DemError::NonFinite);
        }
        for o in out.iter_mut() {
            *o += self.lift;
        }
        Ok(())
    }

    /// Despiked.sample: each point's height, or the median of the 5 x 5 samples `spacing` apart
    /// round it when the point lies more than `spike` from that median.
    ///
    /// The same values and errors as sampling all 25 points of every point in one sample()
    /// call (a missing tile fails at once, a non-finite height after the last point), but a
    /// point over calm ground (calm()) reads only its centre: four of five over flat land.
    pub fn despiked(&mut self, xy: &[[f64; 2]], spacing: f64, spike: f64, out: &mut [f64]) -> Result<(), DemError> {
        let mut finite = true;
        let mut heights = [0.0; 25];
        // over rough ground calm() mostly fails: after a run of failures it is tried on every
        // fourth point only (which path a point takes never changes its value)
        let mut rough = 0u32;
        for (n, (p, o)) in xy.iter().zip(out.iter_mut()).enumerate() {
            let tried = rough < 8 || n % 4 == 0;
            let calm = tried && self.calm(*p, spacing, spike);
            if tried {
                rough = if calm { 0 } else { rough + 1 };
            }
            if calm {
                let h = self.height(p[0], p[1], false, false)?;
                finite &= h.is_finite();
                *o = h + self.lift;
                continue;
            }
            let mut k = 0;
            for dy in -2..=2 {
                for dx in -2..=2 {
                    let h = self.height(p[0] + dx as f64 * spacing, p[1] + dy as f64 * spacing, false, false)?;
                    finite &= h.is_finite();
                    heights[k] = h;
                    k += 1;
                }
            }
            for h in heights.iter_mut() {
                *h += self.lift;
            }
            *o = despike(&heights, 12, spike);
        }
        if !finite {
            return Err(DemError::NonFinite);
        }
        Ok(())
    }

    /// despiked() reading all 25 points of every point (the reference calm() must match).
    pub fn despiked_full(&mut self, xy: &[[f64; 2]], spacing: f64, spike: f64, out: &mut [f64]) -> Result<(), DemError> {
        let mut around = Vec::with_capacity(xy.len() * 25);
        for p in xy {
            for dy in -2..=2 {
                for dx in -2..=2 {
                    around.push([p[0] + dx as f64 * spacing, p[1] + dy as f64 * spacing]);
                }
            }
        }
        let mut heights = vec![0.0; around.len()];
        self.sample(&around, false, &mut heights)?;
        for (k, o) in out.iter_mut().enumerate().take(xy.len()) {
            *o = despike(&heights[k * 25..k * 25 + 25], 12, spike);
        }
        Ok(())
    }

    /// Despiked.grid: despiked() of the lattice ys x xs (row-major), each raw height read once.
    pub fn grid(&mut self, xs: &[f64], ys: &[f64], spacing: f64, spike: f64, out: &mut [f64]) -> Result<(), DemError> {
        let step = if xs.len() > 1 { xs[1] - xs[0] } else { spacing };
        let extend = |v: &[f64]| -> Vec<f64> {
            let (first, last) = (v[0], v[v.len() - 1]);
            let mut e = vec![first - 2.0 * step, first - step];
            e.extend_from_slice(v);
            e.extend([last + step, last + 2.0 * step]);
            e
        };
        let (ex, ey) = (extend(xs), extend(ys));
        let points: Vec<[f64; 2]> = ey.iter().flat_map(|&y| ex.iter().map(move |&x| [x, y])).collect();
        let mut raw = vec![0.0; points.len()];
        self.sample(&points, false, &mut raw)?;
        let w = ex.len();
        let mut window = [0.0; 25];
        for r in 0..ys.len() {
            for c in 0..xs.len() {
                for dy in 0..5 {
                    window[dy * 5..dy * 5 + 5].copy_from_slice(&raw[(r + dy) * w + c..(r + dy) * w + c + 5]);
                }
                out[r * xs.len() + c] = despike(&window, 12, spike);
            }
        }
        Ok(())
    }
}

/// np.where(|centre - median| > spike, median, centre) over 25 heights (an odd count: the median
/// is the middle value).
fn despike(values: &[f64], centre: usize, spike: f64) -> f64 {
    let mut sorted = [0.0; 25];
    sorted.copy_from_slice(values);
    sorted.sort_unstable_by(|a, b| a.total_cmp(b));
    let (c, m) = (values[centre], sorted[12]);
    if (c - m).abs() > spike { m } else { c }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn despike_takes_the_median_of_a_spike() {
        let mut v = [10.0; 25];
        v[12] = 300.0;
        assert_eq!(despike(&v, 12, 40.0), 10.0);
        v[12] = 30.0;
        assert_eq!(despike(&v, 12, 40.0), 30.0);
    }
}
