//! numpy and Python number semantics compile_cell relies on, exactly.

/// np.interp(x, xp, fp) for non-decreasing xp of two or more values (numpy's compiled loop:
/// the last xp at or below x, its value where x equals it, else the slope from it).
pub fn interp(x: &[f64], xp: &[f64], fp: &[f64]) -> Vec<f64> {
    let n = xp.len();
    let (left, right) = (fp[0], fp[n - 1]);
    x.iter()
        .map(|&v| {
            if v.is_nan() {
                return v;
            }
            if v > xp[n - 1] {
                return right;
            }
            if v < xp[0] {
                return left;
            }
            let j = xp.partition_point(|&p| p <= v) - 1;
            if j == n - 1 || xp[j] == v {
                return fp[j];
            }
            let slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j]);
            let mut r = slope * (v - xp[j]) + fp[j];
            if r.is_nan() {
                r = slope * (v - xp[j + 1]) + fp[j + 1];
                if r.is_nan() && fp[j] == fp[j + 1] {
                    r = fp[j];
                }
            }
            r
        })
        .collect()
}

/// np.arange(start, stop, step) of floats: ceil((stop - start) / step) values start + i * delta,
/// delta being (start + step) - start as numpy fills it.
pub fn arange(start: f64, stop: f64, step: f64) -> Vec<f64> {
    let len = ((stop - start) / step).ceil();
    if !(len > 0.0) {
        return Vec::new();
    }
    let len = len as usize;
    let mut out = Vec::with_capacity(len);
    out.push(start);
    if len > 1 {
        let delta = (start + step) - start;
        for i in 1..len {
            out.push(start + i as f64 * delta);
        }
    }
    out
}

/// np.unique of finite values: sorted, exact duplicates dropped.
pub fn unique(mut v: Vec<f64>) -> Vec<f64> {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    v.dedup_by(|a, b| a == b);
    v
}

/// Python's float(text) for ASCII text without underscores; None where Python raises, Err
/// where this cannot answer for Python (non-ASCII digits or spaces, underscores).
pub fn py_float(text: &str) -> Result<Option<f64>, ()> {
    if !text.is_ascii() || text.contains('_') {
        return Err(());
    }
    // str.strip() of ASCII whitespace, as float() strips
    let t = text.trim_matches(|c: char| matches!(c, ' ' | '\t' | '\n' | '\r' | '\x0b' | '\x0c' | '\x1c'..='\x1f'));
    Ok(t.parse::<f64>().ok())
}

/// fast_sources.number(value, default): the first ';' value, ' m' and ',' tolerated.
pub fn number(value: Option<&str>, default: f64) -> Result<f64, ()> {
    let Some(value) = value else {
        return Ok(default); // str(None) is 'None': float() refuses it
    };
    let text = value.split(';').next().unwrap_or("").replace(" m", "").replace(',', ".");
    Ok(py_float(&text)?.unwrap_or(default))
}

/// Python's min(a, b) and max(a, b) of floats (NaN-faithful: the first unless the second compares).
pub fn py_min(a: f64, b: f64) -> f64 {
    if b < a { b } else { a }
}

pub fn py_max(a: f64, b: f64) -> f64 {
    if b > a { b } else { a }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn interp_as_numpy() {
        let xp = [0.0, 1.0, 1.0, 3.0];
        let fp = [0.0, 10.0, 20.0, 40.0];
        assert_eq!(interp(&[-1.0, 0.0, 0.5, 1.0, 2.0, 3.0, 4.0], &xp, &fp), vec![0.0, 0.0, 5.0, 20.0, 30.0, 40.0, 40.0]);
    }

    #[test]
    fn arange_and_numbers() {
        assert_eq!(arange(0.0, 41.0, 20.0), vec![0.0, 20.0, 40.0]);
        assert_eq!(arange(0.0, 40.0, 20.0), vec![0.0, 20.0]);
        assert_eq!(arange(0.0, 1025.0, 25.0).len(), 41);
        assert_eq!(number(Some("12 m"), 3.0), Ok(12.0));
        assert_eq!(number(Some("4;5"), 3.0), Ok(4.0));
        assert_eq!(number(Some("2,5"), 3.0), Ok(2.5));
        assert_eq!(number(Some("high"), 3.0), Ok(3.0));
        assert_eq!(number(None, 3.0), Ok(3.0));
        assert_eq!(number(Some(" 7 "), 3.0), Ok(7.0));
        assert!(number(Some("1_0"), 3.0).is_err());
        assert_eq!(py_max(2.5, py_min(850.0, f64::NAN)), 850.0);
    }
}
