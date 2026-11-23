-- Fast tiles: the same two views of the tiles round the car, SHOT_LIFT m over the ground (0: the
-- world as the game built it; 250: the copy p6_worker_tiles.lua stood there). SHOT_NAME names
-- the files (screenshots/ft-<name>-oblique.jpg, -street.jpg). SHOT_AT: the point the views are
-- taken round (kept between calls, so both sets look at the same place).
local lift = SHOT_LIFT or 0
local name = SHOT_NAME or ('lift' .. lift)
if not SHOT_AT then
  local p = getPlayerVehicle(0):getPosition()
  SHOT_AT = {p.x, p.y, p.z}
end
local at = vec3(SHOT_AT[1], SHOT_AT[2], SHOT_AT[3] + lift)
local views = {
  {'oblique', vec3(at.x - 500, at.y - 900, at.z + 400), vec3(at.x, at.y, at.z)},
  {'street', vec3(at.x + 60, at.y - 140, at.z + 12), vec3(at.x, at.y + 40, at.z + 8)},
  {'roofs', vec3(at.x - 120, at.y - 160, at.z + 90), vec3(at.x + 40, at.y + 60, at.z + 10)},
}
local n, k = 0, 0
commands.setFreeCamera()
return P.task(function()
  n = n + 1
  if n % 120 == 1 then
    k = k + 1
    local v = views[k]
    if not v then return 'shots ' .. name end
    local q = quatFromDir((v[3] - v[2]):normalized(), vec3(0, 0, 1))
    core_camera.setPosRot(0, v[2].x, v[2].y, v[2].z, q.x, q.y, q.z, q.w)
  elseif n % 120 == 90 then
    createScreenshot2({filename = 'screenshots/ft-' .. name .. '-' .. views[k][1], writeJPG = true, superSampling = 1})
  end
end)
