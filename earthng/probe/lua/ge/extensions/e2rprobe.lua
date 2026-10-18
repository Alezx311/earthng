-- Development probe (earthng/probe.py): runs e2r_probe/cmd.txt from the user folder inside the
-- running game and writes what it returns to e2r_probe/out.txt. Only test profiles get it.
local M = {}
local frameTimer = hptimer()
local ring, ringAt, RING = {}, 0, 3000
local tasks, pollAt, now = {}, 0, 0

local function ser(v, depth, seen)
  depth, seen = depth or 0, seen or {}
  local t = type(v)
  if t == 'string' then return string.format('%q', v) end
  if t == 'number' or t == 'boolean' or t == 'nil' then return tostring(v) end
  if t ~= 'table' then return '"<' .. t .. ':' .. tostring(v) .. '>"' end
  if seen[v] or depth > 6 then return '"<table>"' end
  seen[v] = true
  local parts, n = {}, 0
  for k, x in pairs(v) do
    n = n + 1
    if n > 400 then parts[#parts + 1] = '"..."'; break end
    parts[#parts + 1] = '[' .. ser(k, depth + 1, seen) .. ']=' .. ser(x, depth + 1, seen)
  end
  seen[v] = nil
  return '{' .. table.concat(parts, ',') .. '}'
end

local function write(path, text)
  local f = io.open(path, 'w')
  if f then f:write(text); f:close() end
end

-- Frame statistics over the last n frames (ms between onUpdate calls).
local function frames(n)
  n = math.min(n or 300, math.min(#ring, RING))
  local list, total, worst = {}, 0, 0
  for k = 0, n - 1 do
    local ms = ring[(ringAt - k - 1) % RING + 1]
    list[#list + 1] = ms
    total, worst = total + ms, math.max(worst, ms)
  end
  table.sort(list)
  return {n = n, mean = n > 0 and total / n or 0, worst = worst,
    p50 = list[math.max(1, math.ceil(n * .5))] or 0, p99 = list[math.max(1, math.ceil(n * .99))] or 0}
end

M.P = {frames = frames, ser = ser, tasks = tasks, now = function() return now end}

-- A task runs every frame until it returns a value; that value is the command's output.
function M.P.task(fn) tasks[#tasks + 1] = fn; return '__task__' end

function M.onUpdate(dtReal)
  local ms = frameTimer:stopAndReset()
  ringAt = ringAt % RING + 1
  ring[ringAt] = ms
  now = now + (dtReal or 0)
  for k = #tasks, 1, -1 do
    local ok, value = pcall(tasks[k], dtReal, ms)
    if not ok then table.remove(tasks, k); write('e2r_probe/out.txt', 'ERROR ' .. tostring(value))
    elseif value ~= nil then table.remove(tasks, k); write('e2r_probe/out.txt', ser(value)) end
  end
  if now - pollAt < 0.1 then return end
  pollAt = now
  if not FS:fileExists('/e2r_probe/cmd.txt') then return end
  local f = io.open('e2r_probe/cmd.txt', 'r')
  local src = f and f:read('*a')
  if f then f:close() end
  FS:removeFile('/e2r_probe/cmd.txt')
  if not src then return end
  local fn, err = loadstring(src, '=probe')
  if not fn then write('e2r_probe/out.txt', 'COMPILE ' .. tostring(err)); return end
  -- One environment for every command: a later snippet sees what an earlier one stored.
  M.env = M.env or setmetatable({P = M.P}, {__index = _G})
  setfenv(fn, M.env)
  local ok, value = pcall(fn)
  if not ok then write('e2r_probe/out.txt', 'ERROR ' .. tostring(value))
  elseif value ~= '__task__' then write('e2r_probe/out.txt', ser(value)) end
end

function M.onExtensionLoaded() setExtensionUnloadMode(M, 'manual') end
return M
