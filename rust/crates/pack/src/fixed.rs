//! Fixed-width source blocks, `EGB3`, that the game's LuaJIT copies into FFI arrays with one
//! `ffi.copy` instead of decoding LEB128 varints byte by byte (docs/RUST_IN_MOD.md).
//!
//! The reference is `earthng/country_format.py` (`transcode_cell`, `cell_to_v2`); packs are written
//! there. A v3 cell keeps the v2 string table bytes, then
//!
//! ```text
//! u32 count, count * u16 words, nx*ny * u16 heights
//! ```
//!
//! The words are the varints a v2 cell has after its strings, in the same order and zigzagged where
//! v2 zigzags: a value under 0xffff is one word, a larger one 0xffff and then its low and high 16
//! bits. The elevation grid is the exception: nx, ny and the cell's lowest height (decimetres,
//! zigzag) stay among the values, and the heights follow the words as decimetres above it. The
//! block header (`EGB3`, varint entry table) is the v2 header. `decode_block` and `decode_roads`
//! read both versions; [`cell_to_v2`] gives back the exact v2 bytes.
use crate::format::FormatError;

type Result<T> = std::result::Result<T, FormatError>;

pub const MAGIC_V3: &[u8; 4] = b"EGB3";
pub const ESCAPE: u32 = 0xffff;

fn varint(data: &[u8], at: &mut usize, end: usize) -> Result<u64> {
    let (mut value, mut shift) = (0u64, 0u32);
    loop {
        if *at >= end || shift > 56 {
            return Err(FormatError("truncated or invalid source varint"));
        }
        let b = data[*at];
        *at += 1;
        value |= u64::from(b & 0x7f) << shift;
        if b < 0x80 {
            return Ok(value);
        }
        shift += 7;
    }
}

fn put_u(out: &mut Vec<u8>, mut value: u64) {
    while value >= 0x80 {
        out.push((value as u8 & 0x7f) | 0x80);
        value >>= 7;
    }
    out.push(value as u8);
}

fn zig(v: i64) -> u64 {
    if v >= 0 { (v as u64) << 1 } else { ((-v as u64) << 1) - 1 }
}

fn unzig(v: u64) -> i64 {
    if v % 2 == 0 { (v >> 1) as i64 } else { -(((v + 1) >> 1) as i64) }
}

/// Where the string table of the cell data[at..end] ends.
fn strings_end(data: &[u8], mut at: usize, end: usize) -> Result<usize> {
    let n = varint(data, &mut at, end)?;
    for _ in 0..n {
        let len = varint(data, &mut at, end)? as usize;
        at += len;
        if at > end {
            return Err(FormatError("truncated source string"));
        }
    }
    Ok(at)
}

/// One v2 cell (data[at..end]) as a v3 cell.
pub fn transcode_cell(data: &[u8], at: usize, end: usize) -> Result<Vec<u8>> {
    let s = strings_end(data, at, end)?;
    let mut at2 = s;
    let mut values = Vec::with_capacity(end - s);
    while at2 < end {
        values.push(varint(data, &mut at2, end)?);
    }
    if values.len() < 2 {
        return Err(FormatError("invalid source elevation grid"));
    }
    let n = (values[0] * values[1]) as usize;
    if values.len() < 2 + n {
        return Err(FormatError("truncated source elevation grid"));
    }
    let mut heights = Vec::with_capacity(n);
    let mut h = 0i64;
    for &v in &values[2..2 + n] {
        h += unzig(v);
        heights.push(h);
    }
    let base = heights.iter().copied().min().unwrap_or(0);
    let mut out = Vec::with_capacity((end - at) * 2);
    out.extend_from_slice(&data[at..s]);
    let mut words: Vec<u16> = Vec::with_capacity(values.len());
    let rest = [values[0], values[1], zig(base)].into_iter().chain(values[2 + n..].iter().copied());
    for v in rest {
        let v = u32::try_from(v).map_err(|_| FormatError("source value over u32"))?;
        if v >= ESCAPE {
            words.extend_from_slice(&[ESCAPE as u16, v as u16, (v >> 16) as u16]);
        } else {
            words.push(v as u16);
        }
    }
    out.extend_from_slice(&(words.len() as u32).to_le_bytes());
    for w in words {
        out.extend_from_slice(&w.to_le_bytes());
    }
    for h in heights {
        let rel = u16::try_from(h - base).map_err(|_| FormatError("cell relief over the u16 range"))?;
        out.extend_from_slice(&rel.to_le_bytes());
    }
    Ok(out)
}

/// One v3 cell (data[at..end]) back as the v2 bytes it was transcoded from.
pub fn cell_to_v2(data: &[u8], at: usize, end: usize) -> Result<Vec<u8>> {
    let s = strings_end(data, at, end)?;
    if s + 4 > end {
        return Err(FormatError("truncated source cell"));
    }
    let count = u32::from_le_bytes(data[s..s + 4].try_into().unwrap()) as usize;
    let after = s + 4 + 2 * count;
    if after > end {
        return Err(FormatError("truncated source cell"));
    }
    let word = |k: usize| u32::from(u16::from_le_bytes([data[s + 4 + 2 * k], data[s + 5 + 2 * k]]));
    let mut values = Vec::with_capacity(count);
    let mut k = 0;
    while k < count {
        let w = word(k);
        if w == ESCAPE {
            if k + 2 >= count {
                return Err(FormatError("truncated source cell"));
            }
            values.push(u64::from(word(k + 1) | (word(k + 2) << 16)));
            k += 3;
        } else {
            values.push(u64::from(w));
            k += 1;
        }
    }
    if values.len() < 3 {
        return Err(FormatError("truncated source cell"));
    }
    let n = (values[0] * values[1]) as usize;
    if after + 2 * n != end {
        return Err(FormatError("source cell size mismatch"));
    }
    let base = unzig(values[2]);
    let mut out = Vec::with_capacity((end - at) * 2);
    out.extend_from_slice(&data[at..s]);
    put_u(&mut out, values[0]);
    put_u(&mut out, values[1]);
    let mut previous = 0i64;
    for k in 0..n {
        let h = base + i64::from(u16::from_le_bytes([data[after + 2 * k], data[after + 2 * k + 1]]));
        put_u(&mut out, zig(h - previous));
        previous = h;
    }
    for &v in &values[3..] {
        put_u(&mut out, v);
    }
    Ok(out)
}

/// A whole v2 block file as a v3 block file (same slots, same order).
pub fn transcode_block(data: &[u8]) -> Result<Vec<u8>> {
    let cells = crate::format::decode_block(data)?;
    let mut payloads = Vec::with_capacity(cells.len());
    for &(slot, at, end) in &cells {
        payloads.push((slot, transcode_cell(data, at, end)?));
    }
    let mut out = Vec::with_capacity(data.len() * 2);
    out.extend_from_slice(MAGIC_V3);
    put_u(&mut out, payloads.len() as u64);
    for (slot, p) in &payloads {
        put_u(&mut out, u64::from(*slot));
        put_u(&mut out, p.len() as u64);
    }
    for (_, p) in &payloads {
        out.extend_from_slice(p);
    }
    Ok(out)
}

/// Is this block file EGB3?
pub fn is_v3(data: &[u8]) -> bool {
    data.len() >= 4 && &data[..4] == MAGIC_V3
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn values_follow_the_string_table_as_words_and_the_grid_as_heights() {
        // two strings "ab", "c"; grid 2 x 1 with heights 5, 3 (zigzag deltas 10, 3); then 300, 70000
        let mut cell = vec![2u8, 2, b'a', b'b', 1, b'c', 2, 1, 10, 3];
        put_u(&mut cell, 300);
        put_u(&mut cell, 70000);
        let v3 = transcode_cell(&cell, 0, cell.len()).unwrap();
        assert_eq!(&v3[..6], &cell[..6]);
        let words: Vec<u16> = [2, 1, 6, 300, 0xffff, (70000 & 0xffff) as u16, (70000 >> 16) as u16].to_vec();
        assert_eq!(&v3[6..10], &(words.len() as u32).to_le_bytes());
        let mut at = 10;
        for w in words {
            assert_eq!(&v3[at..at + 2], &w.to_le_bytes());
            at += 2;
        }
        assert_eq!(&v3[at..], &[2, 0, 0, 0]);
        assert_eq!(cell_to_v2(&v3, 0, v3.len()).unwrap(), cell);
    }
}
