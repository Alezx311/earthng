-- Does the physics follow the turf block (turf.lua) when it moves? A session of
-- test_world.py --manual --probe, the player driving:
--   python earthng/probe.py --user <out>/user --timeout 2 -f earthng/probe/turf_sync.lua   (start)
--   python earthng/probe.py --user <out>/user "return E2R_TURF.report()"                   (read)
-- The block lies DEEP m under everything where there is no lawn. A static ray cast down from just
-- under the drawn ground at such a point meets the block's floor as the physics has it; the block's
-- own height there (core_terrain) is where it is now. For each move of the block (turf.stats.moves)
-- the probe samples those points the frame after it, then again after the world's next collision
-- rebuild: how far the physics' floor stands from the block's, and how many points have a floor
-- in the physics at all within 80 m.
local T = package.loaded['ge/extensions/e2r/turf']
local W = extensions.e2r_world
local S = W.dbg().S
local log, last, moves, frame, pending = {}, nil, nil, 0, nil

local function sample()
  local veh = getPlayerVehicle(0)
  local tb = scenetree.findObject(T.NAME)
  if not veh or not tb then return nil end
  local at, base = veh:getPosition(), tb:getPosition().z
  local function th(x, y)
    local ok, h = pcall(function() return core_terrain.getTerrainHeight(vec3(x, y, at.z)) end)
    return ok and h or nil
  end
  -- floor points: the block flat at its floor round the point (no lawn within 3 m). A static ray
  -- from 3 m over the floor, which is DEEP m under the lowest lawn, meets nothing else.
  local n, same, off, none, lawn, maxOff = 0, 0, 0, 0, 0, 0
  local examples = {}
  for dx = -80, 80, 6 do
    for dy = -80, 80, 6 do
      local x, y = at.x + dx + .3, at.y + dy + .7
      local flat = true
      for _, o in ipairs({{0, 0}, {3, 0}, {-3, 0}, {0, 3}, {0, -3}}) do
        local h = th(x + o[1], y + o[2])
        if not h or math.abs(h - base) > .05 then flat = false; break end
      end
      if not flat then lawn = lawn + 1
      else
        n = n + 1
        local d = castRayStatic(vec3(x, y, base + 3), vec3(0, 0, -1), 30)
        if not d or d >= 30 then none = none + 1
        elseif math.abs(d - 3) < .1 then same = same + 1
        else
          off = off + 1
          if math.abs(3 - d) > math.abs(maxOff) then maxOff = 3 - d end
          if #examples < 4 then examples[#examples + 1] = string.format('%.1f,%.1f phys %.2f floor %.2f', x, y, base + 3 - d, base) end
        end
      end
    end
  end
  local pos = tb:getPosition()
  return {points = n, same = same, off = off, none = none, notFlat = lawn, maxOff = maxOff,
    block = string.format('%.0f,%.0f,%.1f', pos.x, pos.y, pos.z), examples = examples}
end

E2R_TURF = {report = function() return {log = log, moves = T and T.stats and T.stats.moves, now = S.now} end,
  sample = sample}
return P.task(function()
  frame = frame + 1
  if not T or not T.stats then return end
  local m = T.stats.moves or 0
  if moves == nil then moves = m; last = S.collisionAt; return end
  if m ~= moves then
    moves = m
    -- the frame after the move: the block's file is in, the physics as it is
    pending = {move = m, at = S.now, rebuildAt = S.collisionAt, frame = frame}
    return
  end
  if pending and not pending.after and frame == pending.frame + 1 then
    pending.after = sample()
    pending.rebuiltBefore = S.collisionAt ~= pending.rebuildAt
  end
  if pending and pending.after and S.collisionAt ~= pending.rebuildAt and not pending.rebuilt then
    -- the world's own rebuild ran since the move
    pending.rebuilt = sample()
    pending.rebuildDelay = S.collisionAt - pending.at
    log[#log + 1] = pending
    if #log > 20 then table.remove(log, 1) end
    pending = nil
  elseif pending and pending.after and S.now - pending.at > 30 then
    pending.rebuildDelay = 'none in 30 s'
    log[#log + 1] = pending
    pending = nil
  end
end)
