-- Fast tiles, probe 0b: the mod's own Lua by part over P0_FRAMES frames (world.lua S.prof), and
-- what the generator still has queued. Says what the 20+ ms of Lua in a standing frame is.
local FRAMES = P0_FRAMES or 300
local w = extensions.e2r_world
local d = w.dbg()
local S, native = d.S, d.native
local P0 = S.prof
local sum0, kb0, frames0 = {}, {}, P0.frames
for k, v in pairs(P0.sum) do sum0[k] = v end
for k, v in pairs(P0.kb) do kb0[k] = v end
local n = 0
return P.task(function()
  n = n + 1
  if n < FRAMES then return end
  local Pn = S.prof
  local frames = Pn.frames - frames0
  local out = {frames = frames, ms = {}, kb = {}}
  if frames <= 0 then out.note = 'profile restarted'; frames = Pn.frames; sum0, kb0 = {}, {} end
  for k, v in pairs(Pn.sum) do
    local ms = (v - (sum0[k] or 0)) / frames
    if ms >= 0.03 then out.ms[k] = math.floor(ms * 100 + .5) / 100 end
  end
  for k, v in pairs(Pn.kb) do
    local kb = (v - (kb0[k] or 0)) / frames
    if kb >= 1 then out.kb[k] = math.floor(kb) end
  end
  local st = native.status()
  local stream = st.stream or {}
  out.stream = {}
  for k, v in pairs(stream) do if type(v) ~= 'table' then out.stream[k] = v end end
  out.queue = #S.queue
  out.state = S.state
  out.tiles = tableSize(S.tiles)
  return out
end)
