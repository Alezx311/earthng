//! Python's text behaviour where scene records depend on it: retail._key (NFKC, casefold, then
//! re's \w), and repr()/str() of a float. \w and casefold come from tables Python itself wrote
//! (gen_unicode.py); NFKC is the unicode-normalization crate.

use unicode_normalization::UnicodeNormalization;

#[path = "pytext_tables.rs"]
mod tables;

pub use tables::UNIDATA;

fn is_word(c: char) -> bool {
    let c = c as u32;
    tables::WORD
        .binary_search_by(|&(a, b)| if b < c { std::cmp::Ordering::Less } else if a > c { std::cmp::Ordering::Greater } else { std::cmp::Ordering::Equal })
        .is_ok()
}

fn fold(c: char, out: &mut String) {
    match tables::FOLD.binary_search_by_key(&(c as u32), |&(k, _)| k) {
        Ok(i) => out.push_str(tables::FOLD[i].1),
        Err(_) => out.push(c),
    }
}

/// retail._key: re.sub(r'[^\w]+', '', unicodedata.normalize('NFKC', value).casefold())
pub fn key(value: &str) -> String {
    let mut folded = String::with_capacity(value.len());
    if value.is_ascii() {
        // NFKC leaves ASCII as it is
        for c in value.chars() {
            fold(c, &mut folded);
        }
    } else {
        for c in value.nfkc() {
            fold(c, &mut folded);
        }
    }
    folded.retain(is_word);
    folded
}

/// Python's repr(float), which str(float) is too.
pub fn repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf" } else { "-inf" }.into();
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0" } else { "0.0" }.into();
    }
    // Rust's {:e} is the shortest digits that round-trip, as Python's repr
    let e = format!("{:e}", x);
    let (mantissa, exp) = e.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let neg = mantissa.starts_with('-');
    let digits: String = mantissa.chars().filter(|c| c.is_ascii_digit()).collect();
    let mut out = String::new();
    if neg {
        out.push('-');
    }
    if !(-4..16).contains(&exp) {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push_str(&format!("e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs()));
    } else if exp >= 0 {
        let whole = exp as usize + 1;
        if digits.len() <= whole {
            out.push_str(&digits);
            out.push_str(&"0".repeat(whole - digits.len()));
            out.push_str(".0");
        } else {
            out.push_str(&digits[..whole]);
            out.push('.');
            out.push_str(&digits[whole..]);
        }
    } else {
        out.push_str("0.");
        out.push_str(&"0".repeat((-exp - 1) as usize));
        out.push_str(&digits);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repr_as_python() {
        for (x, s) in [
            (3.0, "3.0"), (12.5, "12.5"), (1e16, "1e+16"), (1e15, "1000000000000000.0"), (0.0001, "0.0001"),
            (0.00001, "1e-05"), (-2.5e-7, "-2.5e-07"), (0.1 + 0.2, "0.30000000000000004"), (123456.789, "123456.789"),
            (1.5e300, "1.5e+300"), (-0.0, "-0.0"), (f64::INFINITY, "inf"), (9999999999999998.0, "9999999999999998.0"),
        ] {
            assert_eq!(repr(x), s);
        }
    }

    #[test]
    fn key_as_retail() {
        assert_eq!(key("Аптека 9-1-1"), "аптека911");
        assert_eq!(key("Нова Пошта №12"), "новапоштаno12");
        assert_eq!(key("McDonald's"), "mcdonalds");
        assert_eq!(key("Straße"), "strasse");
        assert_eq!(key("Бажаємо здоровʼя"), "бажаємоздоровʼя");
        assert_eq!(key("ＡＴＢ"), "atb");
    }
}
