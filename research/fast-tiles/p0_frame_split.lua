-- Fast tiles, probe 0: where a frame goes. The engine's own split of the frame (Lua, LuaGC, Ticking,
-- Render, shadows, physics...) averaged over P0_FRAMES frames, the mod's Lua profile if it keeps one,
-- and the size of the scene.
local FRAMES = P0_FRAMES or 240
local sums, n, list = {}, 0, {}
local m = {}
return P.task(function(dt, ms)
  n = n + 1
  list[n] = ms
  Engine.Debug.getLastPerformanceMetrics(m)
  for k, v in pairs(m) do
    if type(v) == 'number' then sums[k] = (sums[k] or 0) + v end
  end
  if n < FRAMES then return end
  table.sort(list)
  local out = {frames = n, p50 = list[math.ceil(n * .5)], p99 = list[math.ceil(n * .99)], split = {}}
  local total = 0
  for k = 1, n do total = total + list[k] end
  out.mean = total / n
  for k, v in pairs(sums) do
    local avg = v / n
    if avg >= 0.05 then out.split[k] = math.floor(avg * 100 + .5) / 100 end
  end
  out.heapMB = math.floor(collectgarbage('count') / 1024)
  local counts = {}
  for _, class in ipairs({'ProceduralMesh', 'TSStatic', 'Forest', 'DynamicShapeBatch', 'GroundCover', 'DecalRoad',
    'PointLight', 'SpotLight', 'WaterBlock', 'River', 'TerrainBlock'}) do
    local found = scenetree.findClassObjects(class)
    counts[class] = found and #found or 0
  end
  out.scene = counts
  local w = rawget(_G, 'e2r_world')
  if w and w.dbg then
    local ok, d = pcall(w.dbg)
    if ok and type(d) == 'table' then
      out.world = {}
      for k, v in pairs(d) do if type(v) ~= 'table' and type(v) ~= 'function' then out.world[k] = v end end
    end
  end
  return out
end)
