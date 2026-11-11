-- Watch frames for 60 s: each frame over 250 ms with the Lua heap before and after it, the
-- collector's state and the generator's activity, to tell a collector step from engine work.
local timer = hptimer()
local last = 0
local lastHeap = collectgarbage('count')
local hits, frames = {}, 0
local native = extensions and extensions.e2r_native
return P.task(function()
  local now = timer:stop() -- ms since start (stop() reads without stopping in GE's hptimer)
  local heap = collectgarbage('count')
  frames = frames + 1
  local dt = now - last
  if frames > 1 and dt > 250 then
    hits[#hits + 1] = string.format('t=%.1f s dt=%.0f ms heap %.0f -> %.0f MB', now / 1000, dt, lastHeap / 1024, heap / 1024)
  end
  last, lastHeap = now, heap
  if now > 60000 then return {frames = frames, hits = hits} end
end)
