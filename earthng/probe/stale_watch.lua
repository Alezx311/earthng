-- A watcher for invisible collision while the player drives (test_world.py --manual --probe):
--   python earthng/probe.py --user <out>/user --timeout 2 -f earthng/probe/stale_watch.lua   (start)
--   python earthng/probe.py --user <out>/user "return E2R_STALE.report()"                    (read)
-- Every `every` s: level rays of the static collision from the car (`dirs` ways, `heights` over the
-- ground under it, `reach` m). A stop that stands `stands` m over the ground before it and that the
-- drawn world does not answer within `near` m (Engine.castRay on render geometry: it sees the
-- shapes of the tiles and objects, not a ProceduralMesh) is written down with the tile it lies in:
-- is that tile loaded and collided now, when it last left (a near tile unloaded, a far tile
-- dropped) and came, and how long ago the world's last collision rebuild was.
local every, dirs, heights, reach, stands, near = 1.0, 24, {.25, .6}, 9, .08, .6
local W = extensions.e2r_world
local S = W.dbg().S
local t, last = 0, -1e9
local seenTiles, seenFar, left, came, farLeft = {}, {}, {}, {}, {}
local stops, count = {}, 0
local function groundAt(x, y, z)
  local d = castRayStatic(vec3(x, y, z + 4), vec3(0, 0, -1), 12)
  return d and d < 12 and (z + 4 - d) or nil
end
local function track()
  local now = {}
  for key in pairs(S.tiles or {}) do now[key] = true; if not seenTiles[key] then came[key] = t end end
  for key in pairs(seenTiles) do if not now[key] then left[key] = t end end
  seenTiles = now
  local f = {}
  for key in pairs(S.far or {}) do f[key] = true end
  for key in pairs(seenFar) do if not f[key] then farLeft[key] = t end end
  seenFar = f
end
local function look()
  local veh = getPlayerVehicle(0)
  if not veh then return end
  local at = veh:getPosition()
  local g = groundAt(at.x, at.y, at.z)
  if not g then return end
  local speed = veh:getVelocity():length()
  for _, h in ipairs(heights) do
    for d = 0, dirs - 1 do
      local a = d * 2 * math.pi / dirs
      local dir = vec3(math.cos(a), math.sin(a), 0)
      local from = vec3(at.x, at.y, g + h)
      local dist = castRayStatic(from, dir, reach)
      if dist and dist < reach - .05 then
        local hx, hy = at.x + dir.x * dist, at.y + dir.y * dist
        local before = groundAt(at.x + dir.x * math.max(0, dist - .3), at.y + dir.y * math.max(0, dist - .3), g + h)
        if before and g + h - before >= stands then
          local ok, hit = pcall(Engine.castRay, from, vec3(at.x + dir.x * (dist + near), at.y + dir.y * (dist + near), g + h), true, true)
          local drawn = ok and type(hit) == 'table' and hit.pt and (hit.pt - from):length() < dist + near
          if not drawn then
            local size = S.stream and S.stream.tile or 500
            local key = math.floor(hx / size) .. '_' .. math.floor(hy / size)
            local tile = S.tiles and S.tiles[key]
            count = count + 1
            local rec = string.format('t %.0f: %.1f,%.1f +%.2f (ray %.2f, %.1f m, car %.0f m/s) tile %s %s; came %s, left %s, far left %s; rebuild %.0f s ago',
              t, hx, hy, g + h - before, h, dist, speed, key,
              tile and ((tile.roadComplete and 'road' or 'loading') .. (tile.collided and ' collided' or ' not-collided')
                .. (tile.sceneComplete and ' scene' or '') .. (tile.sceneCollided and ' scene-collided' or '')) or 'NOT LOADED',
              came[key] and string.format('%.0f', came[key]) or '-', left[key] and string.format('%.0f', left[key]) or '-',
              farLeft[key] and string.format('%.0f', farLeft[key]) or '-', (S.now or 0) - (S.collisionAt or 0))
            stops[#stops + 1] = rec
            if #stops > 60 then table.remove(stops, 1) end
          end
        end
      end
    end
  end
end
E2R_STALE = {report = function() return {count = count, stops = stops, now = t} end}
return P.task(function(dt)
  t = t + (dt or 0)
  if t - last < every then return end
  last = t
  pcall(track)
  local ok, err = pcall(look)
  if not ok then stops[#stops + 1] = 'error ' .. tostring(err) end
end)
