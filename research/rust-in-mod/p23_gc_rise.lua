-- The adaptive guard's thresholds live (gc.lua): RISE_MB/BACK_MB lower, then 60 s of frames over
-- 250 ms with the heap before and after (p22). Edit the two numbers before each run.
local gc = require('ge/extensions/e2r/gc')
local before = string.format('RISE %s BACK %s mode-low %s', gc.RISE_MB, gc.BACK_MB, tostring(gc.lowered()))
gc.RISE_MB, gc.BACK_MB = RISE or 48, BACK or 24
local timer = hptimer()
local last, lastHeap, frames, hits = 0, collectgarbage('count'), 0, {}
local minHeap, maxHeap = math.huge, 0
return P.task(function()
  local now = timer:stop()
  local heap = collectgarbage('count')
  frames = frames + 1
  minHeap, maxHeap = math.min(minHeap, heap), math.max(maxHeap, heap)
  if frames > 1 and now - last > 150 then
    hits[#hits + 1] = string.format('t=%.1f dt=%.0f heap %.0f->%.0f', now / 1000, now - last, lastHeap / 1024, heap / 1024)
  end
  last, lastHeap = now, heap
  if now > 60000 then return {before = before, after = gc.RISE_MB .. '/' .. gc.BACK_MB, frames = frames,
    heapMB = math.floor(minHeap / 1024) .. '-' .. math.floor(maxHeap / 1024), hits = hits} end
end)
