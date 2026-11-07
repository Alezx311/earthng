//! The back half of fast_sources.write_index: the JSON of every node, junction and road (as
//! json.dumps writes it, floats in Python's repr), road WKB and bounds, the Morton order of the
//! R-tree and the rows of sources.sqlite in Python's order. Mouths and junction hulls stay in
//! Python (numpy, GEOS); this takes their arrays.

use std::fmt::Write as _;
use std::slice;

use rayon::prelude::*;

/// Python's repr of a float, as json.dumps writes it (NaN, Infinity, -Infinity included).
pub fn py_float(x: f64, out: &mut String) {
    if x.is_nan() {
        out.push_str("NaN");
        return;
    }
    if x.is_infinite() {
        out.push_str(if x > 0.0 { "Infinity" } else { "-Infinity" });
        return;
    }
    if x == 0.0 {
        out.push_str(if x.is_sign_negative() { "-0.0" } else { "0.0" });
        return;
    }
    // the shortest digits that read back, of those the closest, a tie to the even digit: Python's
    // repr (dtoa mode 0). Rust's shortest form breaks an exact tie its own way (9127.1505126953125
    // reads 9127.150512695313), so the correctly rounded string of that length wins when it reads back.
    let a = x.abs();
    let mut sci = format!("{a:e}");
    let n = sci.split_once('e').unwrap().0.chars().filter(|c| c.is_ascii_digit()).count();
    let rounded = format!("{a:.*e}", n - 1);
    if rounded != sci && rounded.parse::<f64>() == Ok(a) {
        sci = rounded;
    }
    let (mantissa, exp) = sci.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let decpt = exp + 1; // value = 0.DIGITS * 10^decpt
    if x < 0.0 {
        out.push('-');
    }
    if decpt <= -4 || decpt > 16 {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        let e = decpt - 1;
        let _ = write!(out, "e{}{:02}", if e < 0 { '-' } else { '+' }, e.abs());
    } else if decpt <= 0 {
        out.push_str("0.");
        for _ in 0..-decpt {
            out.push('0');
        }
        out.push_str(&digits);
    } else {
        let d = decpt as usize;
        if digits.len() <= d {
            out.push_str(&digits);
            for _ in digits.len()..d {
                out.push('0');
            }
            out.push_str(".0");
        } else {
            out.push_str(&digits[..d]);
            out.push('.');
            out.push_str(&digits[d..]);
        }
    }
}

fn floats(v: &[f64], sep: &str, out: &mut String) {
    out.push('[');
    for (i, &x) in v.iter().enumerate() {
        if i > 0 {
            out.push_str(sep);
        }
        py_float(x, out);
    }
    out.push(']');
}

fn pairs(v: &[f64], sep: &str, out: &mut String) {
    out.push('[');
    for (i, p) in v.chunks_exact(2).enumerate() {
        if i > 0 {
            out.push_str(sep);
        }
        floats(p, sep, out);
    }
    out.push(']');
}

fn ints(v: &[i64], sep: &str, out: &mut String) {
    out.push('[');
    for (i, &x) in v.iter().enumerate() {
        if i > 0 {
            out.push_str(sep);
        }
        let _ = write!(out, "{x}");
    }
    out.push(']');
}

/// What write_index hands over, every array in the order Python made it.
#[repr(C)]
pub struct IndexIn {
    /// segments, ids 1..=ns
    pub ns: usize,
    /// 0: a road segment composed here; 1: its whole JSON is in text
    pub layout: *const u8,
    pub way: *const i64,
    pub node_a: *const i64,
    pub node_b: *const i64,
    pub width: *const f64,
    /// 1 where the width is a Python int
    pub width_int: *const u8,
    /// x y of road segments (2 per point), point offsets (ns + 1)
    pub xy: *const f64,
    pub xy_off: *const i64,
    pub ps: *const f64,
    pub ps_off: *const i64,
    pub ph: *const f64,
    pub ph_off: *const i64,
    /// 2 per segment
    pub cuts: *const f64,
    /// a road's tags JSON, or a text segment's whole JSON (byte offsets, ns + 1)
    pub text: *const u8,
    pub text_off: *const i64,
    /// the unrounded line of every segment (WKB, bounds), point offsets (ns + 1)
    pub raw: *const f64,
    pub raw_off: *const i64,
    /// nodes in mouths order
    pub nn: usize,
    pub nid: *const i64,
    pub node_xy: *const f64,
    pub lift: *const f64,
    pub h: *const f64,
    /// segment of every mouth, node by node (offsets nn + 1)
    pub mouth_sid: *const i64,
    pub mouth_off: *const i64,
    /// junctions kept (hull area over 0.01), in nodes order: node row, corners (point offsets
    /// nj + 1) with their cz, hull WKB (byte offsets nj + 1), bounds x0 y0 x1 y1
    pub nj: usize,
    pub j_node: *const i64,
    pub corners: *const f64,
    pub corner_off: *const i64,
    pub cz: *const f64,
    pub wkb: *const u8,
    pub wkb_off: *const i64,
    pub j_bounds: *const f64,
    pub path: *const u8,
    pub path_len: usize,
}

unsafe fn view<'a, T>(p: *const T, n: usize) -> &'a [T] {
    if n == 0 { &[] } else { unsafe { slice::from_raw_parts(p, n) } }
}

fn span(off: &[i64], i: usize) -> std::ops::Range<usize> {
    off[i] as usize..off[i + 1] as usize
}

/// LineString WKB as shapely.to_wkb writes a 2-D line (little endian, ISO type 2)
fn line_wkb(pts: &[f64]) -> Vec<u8> {
    let mut w = Vec::with_capacity(9 + pts.len() * 8);
    w.push(1u8);
    w.extend_from_slice(&2u32.to_le_bytes());
    w.extend_from_slice(&((pts.len() / 2) as u32).to_le_bytes());
    for v in pts {
        w.extend_from_slice(&v.to_le_bytes());
    }
    w
}

/// # Safety
/// Every pointer of `i` holds the lengths its comment names.
pub unsafe fn write(i: &IndexIn) -> Result<(), String> {
    let t0 = std::time::Instant::now();
    let tick = |what: &str| if std::env::var_os("EARTHNG_INDEX_TIMES").is_some() { eprintln!("{:7.2} {what}", t0.elapsed().as_secs_f64()) };
    let ns = i.ns;
    let nn = i.nn;
    let nj = i.nj;
    let (layout, way, node_a, node_b, width, width_int, xy_off, ps_off, ph_off, cuts, text_off, raw_off) = unsafe {
        (
            view(i.layout, ns),
            view(i.way, ns),
            view(i.node_a, ns),
            view(i.node_b, ns),
            view(i.width, ns),
            view(i.width_int, ns),
            view(i.xy_off, ns + 1),
            view(i.ps_off, ns + 1),
            view(i.ph_off, ns + 1),
            view(i.cuts, 2 * ns),
            view(i.text_off, ns + 1),
            view(i.raw_off, ns + 1),
        )
    };
    let (xy, ps, ph, text, raw) = unsafe {
        (
            view(i.xy, 2 * xy_off[ns] as usize),
            view(i.ps, ps_off[ns] as usize),
            view(i.ph, ph_off[ns] as usize),
            view(i.text, text_off[ns] as usize),
            view(i.raw, 2 * raw_off[ns] as usize),
        )
    };
    let (nid, node_xy, lift, h, mouth_off) =
        unsafe { (view(i.nid, nn), view(i.node_xy, 2 * nn), view(i.lift, nn), view(i.h, nn), view(i.mouth_off, nn + 1)) };
    let mouth_sid = unsafe { view(i.mouth_sid, mouth_off[nn] as usize) };
    let (j_node, corner_off, wkb_off, j_bounds) =
        unsafe { (view(i.j_node, nj), view(i.corner_off, nj + 1), view(i.wkb_off, nj + 1), view(i.j_bounds, 4 * nj)) };
    let (corners, cz, wkb) =
        unsafe { (view(i.corners, 2 * corner_off[nj] as usize), view(i.cz, corner_off[nj] as usize), view(i.wkb, wkb_off[nj] as usize)) };
    let path = std::str::from_utf8(unsafe { view(i.path, i.path_len) }).map_err(|e| e.to_string())?;
    let utf8 = |r: std::ops::Range<usize>| std::str::from_utf8(&text[r]).map_err(|e| e.to_string());

    // node JSON (json.dumps defaults: ", " and ": ") and the junctions' (compact)
    let node_json: Vec<String> = (0..nn)
        .into_par_iter()
        .map(|n| {
            let mut s = String::with_capacity(96);
            s.push_str("{\"xy\": ");
            floats(&node_xy[2 * n..2 * n + 2], ", ", &mut s);
            s.push_str(", \"raise\": ");
            py_float(lift[n], &mut s);
            s.push_str(", \"segments\": ");
            ints(&mouth_sid[span(mouth_off, n)], ", ", &mut s);
            s.push_str(", \"h\": ");
            py_float(h[n], &mut s);
            s.push('}');
            s
        })
        .collect();
    let junction_json: Vec<String> = (0..nj)
        .into_par_iter()
        .map(|j| {
            let n = j_node[j] as usize;
            let mut s = String::with_capacity(512);
            s.push_str("{\"xy\":");
            floats(&node_xy[2 * n..2 * n + 2], ",", &mut s);
            s.push_str(",\"raise\":");
            py_float(lift[n], &mut s);
            s.push_str(",\"segments\":");
            ints(&mouth_sid[span(mouth_off, n)], ",", &mut s);
            s.push_str(",\"h\":");
            py_float(h[n], &mut s);
            let _ = write!(s, ",\"node\":{},\"corners\":", nid[n]);
            let c = span(corner_off, j);
            pairs(&corners[2 * c.start..2 * c.end], ",", &mut s);
            s.push_str(",\"cz\":");
            floats(&cz[c], ",", &mut s);
            s.push('}');
            s
        })
        .collect();
    tick("node json");
    // road rows: JSON (compact), line WKB, padded bounds
    let roads: Vec<Result<(String, Vec<u8>, [f64; 4]), String>> = (0..ns)
        .into_par_iter()
        .map(|k| {
            let json = if layout[k] == 0 {
                let mut s = String::with_capacity(256 + 24 * (xy_off[k + 1] - xy_off[k]) as usize);
                let _ = write!(s, "{{\"id\":{},\"way\":{},\"tags\":", k + 1, way[k]);
                s.push_str(utf8(span(text_off, k))?);
                s.push_str(",\"xy\":");
                let p = span(xy_off, k);
                pairs(&xy[2 * p.start..2 * p.end], ",", &mut s);
                let _ = write!(s, ",\"nodes\":[{},{}],\"width\":", node_a[k], node_b[k]);
                if width_int[k] != 0 {
                    let _ = write!(s, "{}", width[k] as i64);
                } else {
                    py_float(width[k], &mut s);
                }
                s.push_str(",\"prof\":[");
                floats(&ps[span(ps_off, k)], ",", &mut s);
                s.push(',');
                floats(&ph[span(ph_off, k)], ",", &mut s);
                s.push_str("],\"cuts\":");
                floats(&cuts[2 * k..2 * k + 2], ",", &mut s);
                s.push('}');
                s
            } else {
                utf8(span(text_off, k))?.to_string()
            };
            let r = span(raw_off, k);
            let pts = &raw[2 * r.start..2 * r.end];
            let mut b = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
            for p in pts.chunks_exact(2) {
                b[0] = b[0].min(p[0]);
                b[1] = b[1].min(p[1]);
                b[2] = b[2].max(p[0]);
                b[3] = b[3].max(p[1]);
            }
            let pad = width[k] / 2.0 + 1.0;
            Ok((json, line_wkb(pts), [b[0] - pad, b[2] + pad, b[1] - pad, b[3] + pad]))
        })
        .collect();
    let roads: Vec<(String, Vec<u8>, [f64; 4])> = roads.into_iter().collect::<Result<_, _>>()?;

    tick("road rows");
    // bounds: junctions (-node) then roads, in 1 km Morton order (a stable sort)
    let mut bound_rows: Vec<(i64, [f64; 4])> = Vec::with_capacity(nj + ns);
    for j in 0..nj {
        let b = &j_bounds[4 * j..4 * j + 4];
        bound_rows.push((-nid[j_node[j] as usize], [b[0], b[2], b[1], b[3]]));
    }
    for (k, r) in roads.iter().enumerate() {
        bound_rows.push(((k + 1) as i64, r.2));
    }
    let code: Vec<i64> = bound_rows
        .iter()
        .map(|(_, b)| {
            let cx = (((b[0] + b[1]) / 2000.0) as i64) & 0xffff;
            let cy = (((b[2] + b[3]) / 2000.0) as i64) & 0xffff;
            let mut c = 0i64;
            for bit in 0..16 {
                c |= ((cx >> bit) & 1) << (2 * bit) | ((cy >> bit) & 1) << (2 * bit + 1);
            }
            c
        })
        .collect();
    let mut order: Vec<usize> = (0..bound_rows.len()).collect();
    order.sort_by_key(|&r| code[r]);
    let mut links: Vec<(i64, i64)> = Vec::with_capacity(mouth_sid.len());
    for n in 0..nn {
        for &s in &mouth_sid[span(mouth_off, n)] {
            links.push((nid[n], s));
        }
    }
    links.sort_by_key(|l| l.0);
    let mut node_rows: Vec<usize> = (0..nn).collect();
    node_rows.sort_by_key(|&n| nid[n]);
    let mut junction_rows: Vec<usize> = (0..nj).collect();
    junction_rows.sort_by_key(|&j| -nid[j_node[j] as usize]);

    tick("order");
    let fail = |e: rusqlite::Error| e.to_string();
    let mut db = rusqlite::Connection::open(path).map_err(fail)?;
    db.execute_batch(
        "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-262144;
            PRAGMA temp_store=MEMORY;
            CREATE TABLE features(id INTEGER PRIMARY KEY, kind TEXT, data TEXT, geom BLOB);
            CREATE VIRTUAL TABLE bounds USING rtree(id,x0,x1,y0,y1);
            CREATE TABLE nodes(id INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE links(node INTEGER, segment INTEGER);",
    )
    .map_err(fail)?;
    tick("schema");
    let tx = db.transaction().map_err(fail)?;
    {
        let mut st = tx.prepare("INSERT INTO bounds VALUES(?,?,?,?,?)").map_err(fail)?;
        for &r in &order {
            let (id, b) = &bound_rows[r];
            st.execute(rusqlite::params![id, b[0], b[1], b[2], b[3]]).map_err(fail)?;
        }
        tick("bounds");
        let mut st = tx.prepare("INSERT INTO links VALUES(?,?)").map_err(fail)?;
        for (n, s) in &links {
            st.execute(rusqlite::params![n, s]).map_err(fail)?;
        }
    }
    tick("bounds links");
    tx.execute("CREATE INDEX links_node ON links(node)", []).map_err(fail)?;
    {
        let mut st = tx.prepare("INSERT INTO nodes VALUES(?,?)").map_err(fail)?;
        for &n in &node_rows {
            st.execute(rusqlite::params![nid[n], node_json[n]]).map_err(fail)?;
        }
        let mut st = tx.prepare("INSERT INTO features VALUES(?,?,?,?)").map_err(fail)?;
        for &j in &junction_rows {
            let w = &wkb[span(wkb_off, j)];
            st.execute(rusqlite::params![-nid[j_node[j] as usize], "junction", junction_json[j], w]).map_err(fail)?;
        }
        for (k, (json, w, _)) in roads.iter().enumerate() {
            st.execute(rusqlite::params![(k + 1) as i64, "road", json, w]).map_err(fail)?;
        }
    }
    tick("nodes features");
    tx.commit().map_err(fail)?;
    tick("commit");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn r(x: f64) -> String {
        let mut s = String::new();
        py_float(x, &mut s);
        s
    }

    #[test]
    fn floats_read_as_python_repr() {
        assert_eq!(r(1.0), "1.0");
        assert_eq!(r(-2.5), "-2.5");
        assert_eq!(r(0.1), "0.1");
        assert_eq!(r(1e16), "1e+16");
        assert_eq!(r(1234567890123456.0), "1234567890123456.0");
        assert_eq!(r(0.0001), "0.0001");
        assert_eq!(r(0.00001), "1e-05");
        assert_eq!(r(1.5e-7), "1.5e-07");
        assert_eq!(r(-0.0), "-0.0");
        assert_eq!(r(123.456), "123.456");
        assert_eq!(r(1e22), "1e+22");
        assert_eq!(r(f64::NAN), "NaN");
        assert_eq!(r(-9127.1505126953125), "-9127.150512695312");
    }
}
