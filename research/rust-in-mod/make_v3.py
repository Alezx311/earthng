"""Generate research/rust-in-mod/cellformat3.lua (EGB3 decoder) from mod/.../cellformat.lua.

The EGB3 decoder must build exactly the tables cellformat.cell builds, so it is derived from that
function: the string table is still read byte by byte, and every later number comes from a
uint32_t[] filled by one ffi.copy (rust/crates/pack/src/fixed.rs writes it).

    .venv\\Scripts\\python.exe research\\rust-in-mod\\make_v3.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'mod/lua/ge/extensions/e2r/cellformat.lua'
TARGET = Path(__file__).with_name('cellformat3.lua')

NEW_U = '''  local function bu()
    local value, mul = 0, 1
    while true do
      if pos > last or mul > 2 ^ 49 then error('truncated source cell') end
      local b = byte(data, pos)
      pos = pos + 1
      if b < 128 then return value + b * mul end
      value, mul = value + (b - 128) * mul, mul * 128
    end
  end
  local vals, vi, vn
  local function u()
    if vi >= vn then error('truncated source cell') end
    local v = vals[vi]
    vi = vi + 1
    return v
  end
'''

NEW_STRINGS = '''  local strings = {}
  for k = 1, bu() do
    local n = bu()
    if pos + n - 1 > last then error('truncated source string') end
    strings[k] = sub(data, pos, pos + n - 1)
    pos = pos + n
  end
  -- the fixed-width part: count, then count little-endian u32 values (EGB3)
  if pos + 3 > last then error('truncated source cell') end
  local b1, b2, b3, b4 = byte(data, pos, pos + 3)
  vn = b1 + b2 * 256 + b3 * 65536 + b4 * 16777216
  pos = pos + 4
  if pos + 4 * vn - 1 ~= last then error('source cell size mismatch') end
  -- M.values (optional {first = array}): a cell read by several tiles is copied once
  vals = M.values and M.values[first]
  if not vals then
    vals = ffi.new('uint32_t[?]', vn)
    ffi.copy(vals, sub(data, pos, last), 4 * vn)
    if M.values then M.values[first] = vals end
  end
  vi = 0
'''

HEAD = '''-- Experiment (exp/rust-in-mod): the EGB3 source cell, written by rust/crates/pack/src/fixed.rs.
-- Same walk and same tables as cellformat.cell (generated from it by research/rust-in-mod/make_v3.py);
-- only the numbers after the string table come from a uint32_t[] that ffi.copy fills in one call.
-- The game's sandbox allows ffi.new arrays and ffi.copy from a string (not pointers, casts or ffi.load).
local ffi = require('ffi')
local CF = require('e2r/cellformat')
local M = {}
local byte, sub, floor = string.byte, string.sub, math.floor
local KINDS = CF.KINDS
M.ROAD_MARGIN, M.MARGIN, M.DETAIL_MARGIN, M.DETAILS = CF.ROAD_MARGIN, CF.MARGIN, CF.DETAIL_MARGIN, CF.DETAILS

-- Byte ranges of the cells in an EGB3 block (the header is the EGB2 header).
function M.block(data)
  if type(data) ~= 'string' or sub(data, 1, 4) ~= 'EGB3' then error('not an EGB3 source block') end
  return CF.block('EGB2' .. sub(data, 5))
end

'''


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f'cellformat.lua changed: {old[:60]!r} is not there exactly once')
    return text.replace(old, new)


def main():
    src = SOURCE.read_text(encoding='utf8')
    body = src[src.index('function M.cell('):src.index('-- Only the elevation grid of a cell')]
    body = replace_once(body, body[body.index('  local function u()'):body.index('  local function s()')], NEW_U)
    body = replace_once(body, body[body.index('  local strings = {}'):body.index('  local function ref()')], NEW_STRINGS)
    body = replace_once(body, 'nx, ny, heights, pos = grid.nx, grid.ny, grid.heights, grid.after',
                        'nx, ny, heights, vi = grid.nx, grid.ny, grid.heights, grid.after')
    body = replace_once(body, 'grid.nx, grid.ny, grid.heights, grid.after = nx, ny, heights, pos',
                        'grid.nx, grid.ny, grid.heights, grid.after = nx, ny, heights, vi')
    body = replace_once(body, "  if pos ~= last + 1 then error('trailing bytes after source cell') end",
                        "  if vi ~= vn then error('trailing values after source cell') end")
    TARGET.write_text(HEAD + body + '\nreturn M\n', encoding='utf8', newline='\n')
    print(TARGET)


if __name__ == '__main__':
    main()
