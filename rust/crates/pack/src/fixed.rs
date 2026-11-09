//! Experiment (exp/rust-in-mod): a fixed-width source block, `EGB3`, that the game's LuaJIT reads
//! with `ffi.copy` into a `uint32_t[]` instead of decoding LEB128 varints byte by byte.
//!
//! In a v2 cell everything after the string table is a varint. A v3 cell keeps the string table
//! bytes as they are, then writes the count of the remaining values (u32 little-endian) and every
//! value as a u32 little-endian, in the same order and still zigzagged where v2 zigzags. The Lua
//! decoder therefore walks the cell exactly as `cellformat.cell` does and builds the same tables;
//! only its `u()` changes. The block header (`EGB3`, varint entry table) is the v2 header.
use crate::format::FormatError;

type Result<T> = std::result::Result<T, FormatError>;

pub const MAGIC_V3: &[u8; 4] = b"EGB3";

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

/// One v2 cell (data[at..end]) as a v3 cell.
pub fn transcode_cell(data: &[u8], mut at: usize, end: usize) -> Result<Vec<u8>> {
    let start = at;
    let n = varint(data, &mut at, end)?;
    for _ in 0..n {
        let len = varint(data, &mut at, end)? as usize;
        at += len;
        if at > end {
            return Err(FormatError("truncated source string"));
        }
    }
    let mut out = Vec::with_capacity((end - start) * 3);
    out.extend_from_slice(&data[start..at]);
    let mut values = Vec::with_capacity(end - at);
    while at < end {
        let v = varint(data, &mut at, end)?;
        values.push(u32::try_from(v).map_err(|_| FormatError("source value over u32"))?);
    }
    out.extend_from_slice(&(values.len() as u32).to_le_bytes());
    for v in values {
        out.extend_from_slice(&v.to_le_bytes());
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
    let mut out = Vec::with_capacity(data.len() * 3);
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn values_follow_the_string_table() {
        // two strings "ab", "c", then varints 300 and 5
        let cell = [2u8, 2, b'a', b'b', 1, b'c', 0xac, 0x02, 5];
        let v3 = transcode_cell(&cell, 0, cell.len()).unwrap();
        assert_eq!(&v3[..6], &cell[..6]);
        assert_eq!(&v3[6..10], &2u32.to_le_bytes());
        assert_eq!(&v3[10..14], &300u32.to_le_bytes());
        assert_eq!(&v3[14..18], &5u32.to_le_bytes());
    }
}
