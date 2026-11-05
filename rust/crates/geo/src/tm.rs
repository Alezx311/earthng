//! UTM on WGS84 by Krüger's series to sixth order in n (Karney 2011), as PROJ's default
//! transverse Mercator computes it: within a zone the two agree to nanometres. fast_sources.Frame
//! is pyproj EPSG:4326 -> EPSG:326xx/327xx; this is the same mapping without PROJ.

const A: f64 = 6_378_137.0;
const F: f64 = 1.0 / 298.257_223_563;
const K0: f64 = 0.9996;
const FALSE_EASTING: f64 = 500_000.0;
const FALSE_NORTHING_SOUTH: f64 = 10_000_000.0;

#[derive(Clone, Copy, Debug)]
pub struct Utm {
    pub zone: u32,
    pub north: bool,
    lon0: f64,
    e: f64,
    a_k0: f64,
    alpha: [f64; 6],
    beta: [f64; 6],
}

fn series() -> (f64, [f64; 6], [f64; 6]) {
    let n = F / (2.0 - F);
    let (n2, n3) = (n * n, n * n * n);
    let (n4, n5, n6) = (n3 * n, n3 * n2, n3 * n3);
    let big_a = A / (1.0 + n) * (1.0 + n2 / 4.0 + n4 / 64.0 + n6 / 256.0);
    let alpha = [
        n / 2.0 - 2.0 * n2 / 3.0 + 5.0 * n3 / 16.0 + 41.0 * n4 / 180.0 - 127.0 * n5 / 288.0 + 7891.0 * n6 / 37800.0,
        13.0 * n2 / 48.0 - 3.0 * n3 / 5.0 + 557.0 * n4 / 1440.0 + 281.0 * n5 / 630.0 - 1983433.0 * n6 / 1935360.0,
        61.0 * n3 / 240.0 - 103.0 * n4 / 140.0 + 15061.0 * n5 / 26880.0 + 167603.0 * n6 / 181440.0,
        49561.0 * n4 / 161280.0 - 179.0 * n5 / 168.0 + 6601661.0 * n6 / 7257600.0,
        34729.0 * n5 / 80640.0 - 3418889.0 * n6 / 1995840.0,
        212378941.0 * n6 / 319334400.0,
    ];
    let beta = [
        n / 2.0 - 2.0 * n2 / 3.0 + 37.0 * n3 / 96.0 - n4 / 360.0 - 81.0 * n5 / 512.0 + 96199.0 * n6 / 604800.0,
        n2 / 48.0 + n3 / 15.0 - 437.0 * n4 / 1440.0 + 46.0 * n5 / 105.0 - 1118711.0 * n6 / 3870720.0,
        17.0 * n3 / 480.0 - 37.0 * n4 / 840.0 - 209.0 * n5 / 4480.0 + 5569.0 * n6 / 90720.0,
        4397.0 * n4 / 161280.0 - 11.0 * n5 / 504.0 - 830251.0 * n6 / 7257600.0,
        4583.0 * n5 / 161280.0 - 108847.0 * n6 / 3991680.0,
        20648693.0 * n6 / 638668800.0,
    ];
    (big_a, alpha, beta)
}

/// fast_sources.utm_crs: the zone and hemisphere of a point.
pub fn zone_of(lon: f64, lat: f64) -> (u32, bool) {
    let zone = ((((lon + 180.0) / 6.0).floor() as i64).rem_euclid(60) + 1) as u32;
    (zone, lat >= 0.0)
}

impl Utm {
    pub fn new(zone: u32, north: bool) -> Utm {
        let (big_a, alpha, beta) = series();
        let e = (F * (2.0 - F)).sqrt();
        Utm { zone, north, lon0: (f64::from(zone) * 6.0 - 183.0).to_radians(), e, a_k0: K0 * big_a, alpha, beta }
    }

    /// From an EPSG code 326zz / 327zz.
    pub fn epsg(code: u32) -> Option<Utm> {
        match code {
            32601..=32660 => Some(Utm::new(code - 32600, true)),
            32701..=32760 => Some(Utm::new(code - 32700, false)),
            _ => None,
        }
    }

    pub fn epsg_code(&self) -> u32 {
        if self.north { 32600 + self.zone } else { 32700 + self.zone }
    }

    /// (lon, lat) degrees -> (easting, northing) metres.
    pub fn forward(&self, lon: f64, lat: f64) -> (f64, f64) {
        let phi = lat.to_radians();
        let lam = (lon.to_radians() - self.lon0 + std::f64::consts::PI).rem_euclid(2.0 * std::f64::consts::PI) - std::f64::consts::PI;
        let s = phi.sin();
        let t = (s.atanh() - self.e * (self.e * s).atanh()).sinh();
        let xi1 = t.atan2(lam.cos());
        let eta1 = (lam.sin() / (t * t + lam.cos() * lam.cos()).sqrt()).asinh();
        let (mut xi, mut eta) = (xi1, eta1);
        for (j, a) in self.alpha.iter().enumerate() {
            let k = 2.0 * (j as f64 + 1.0);
            xi += a * (k * xi1).sin() * (k * eta1).cosh();
            eta += a * (k * xi1).cos() * (k * eta1).sinh();
        }
        let x = FALSE_EASTING + self.a_k0 * eta;
        let y = self.a_k0 * xi + if self.north { 0.0 } else { FALSE_NORTHING_SOUTH };
        (x, y)
    }

    /// (easting, northing) metres -> (lon, lat) degrees.
    pub fn inverse(&self, x: f64, y: f64) -> (f64, f64) {
        let xi = (y - if self.north { 0.0 } else { FALSE_NORTHING_SOUTH }) / self.a_k0;
        let eta = (x - FALSE_EASTING) / self.a_k0;
        let (mut xi1, mut eta1) = (xi, eta);
        for (j, b) in self.beta.iter().enumerate() {
            let k = 2.0 * (j as f64 + 1.0);
            xi1 -= b * (k * xi).sin() * (k * eta).cosh();
            eta1 -= b * (k * xi).cos() * (k * eta).sinh();
        }
        let tau1 = xi1.sin() / (eta1.sinh().powi(2) + xi1.cos().powi(2)).sqrt();
        let lam = eta1.sinh().atan2(xi1.cos());
        // conformal tangent tau1 -> geodetic tangent tau (Newton, Karney eq. 19-21)
        let e2 = self.e * self.e;
        let mut tau = tau1;
        for _ in 0..5 {
            let sigma = (self.e * (self.e * tau / (1.0 + tau * tau).sqrt()).atanh()).sinh();
            let tau_p = tau * (1.0 + sigma * sigma).sqrt() - sigma * (1.0 + tau * tau).sqrt();
            let d = (tau1 - tau_p) / (1.0 + tau_p * tau_p).sqrt() * (1.0 + (1.0 - e2) * tau * tau)
                / ((1.0 - e2) * (1.0 + tau * tau).sqrt());
            tau += d;
            if d.abs() < 1e-15 {
                break;
            }
        }
        let lat = tau.atan().to_degrees();
        let lon = (lam + self.lon0).to_degrees();
        (lon, lat)
    }
}

/// fast_sources.Frame: world metres = UTM metres minus a whole-metre origin.
#[derive(Clone, Copy, Debug)]
pub struct Frame {
    pub utm: Utm,
    pub origin: (f64, f64),
}

impl Frame {
    /// Frame.at: the point's zone, origin at the point rounded to whole metres.
    pub fn at(lon: f64, lat: f64) -> Frame {
        let (zone, north) = zone_of(lon, lat);
        let utm = Utm::new(zone, north);
        let (x, y) = utm.forward(lon, lat);
        Frame { utm, origin: (py_round(x), py_round(y)) }
    }

    pub fn local(&self, lon: f64, lat: f64) -> (f64, f64) {
        let (x, y) = self.utm.forward(lon, lat);
        (x - self.origin.0, y - self.origin.1)
    }

    pub fn geographic(&self, x: f64, y: f64) -> (f64, f64) {
        self.utm.inverse(x + self.origin.0, y + self.origin.1)
    }
}

/// Python's round(x): half to even.
pub fn py_round(x: f64) -> f64 {
    let r = x.round();
    if (x - x.trunc()).abs() == 0.5 { 2.0 * (x / 2.0).round() } else { r }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_inside_a_zone() {
        let utm = Utm::new(36, true);
        for &(lon, lat) in &[(30.52, 50.45), (33.0, 0.001), (35.9, 70.0), (30.0, 44.4)] {
            let (x, y) = utm.forward(lon, lat);
            let (lo, la) = utm.inverse(x, y);
            assert!((lo - lon).abs() < 1e-11 && (la - lat).abs() < 1e-11, "{lon} {lat} -> {lo} {la}");
        }
    }

    #[test]
    fn matches_pyproj() {
        // pyproj 3.7 (PROJ), EPSG:4326 -> EPSG:326xx/327xx, always_xy
        let cases = [
            (32636, 30.5234, 50.4501, 324182.2094294755, 5591607.607408224),
            (32636, 33.0, 0.001, 499999.9999999993, 110.5300461113784),
            (32636, 35.9, 70.0, 610660.4649010521, 7768505.452278187),
            (32636, 30.0, 44.4, 261097.0333600668, 4920679.574877161),
            (32636, 27.1, 48.2, 61676.95973292389, 5355381.967701849),
            (32723, -43.2, -22.9, 684623.6732645986, 7466421.400670482),
            (32723, -47.99, -0.5, 167148.33778428624, 9944659.120527474),
            (32610, -122.42, 37.77, 551081.2998441748, 4180454.9025255637),
        ];
        for (code, lon, lat, ex, ey) in cases {
            let utm = Utm::epsg(code).unwrap();
            let (x, y) = utm.forward(lon, lat);
            assert!((x - ex).abs() < 1e-6 && (y - ey).abs() < 1e-6, "{code} {lon} {lat}: {x} {y} vs {ex} {ey}");
            let (lo, la) = utm.inverse(ex, ey);
            assert!((lo - lon).abs() < 1e-10 && (la - lat).abs() < 1e-10, "{code} inverse {lo} {la}");
        }
        assert_eq!(zone_of(30.52, 50.45), (36, true));
        assert_eq!(zone_of(-43.2, -22.9), (23, false));
        assert_eq!(py_round(2.5), 2.0);
        assert_eq!(py_round(-3.5), -4.0);
    }
}
