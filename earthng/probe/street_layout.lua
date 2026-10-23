-- Run with probe.py during a test_world route with --gallery --gallery-wait 20.
-- Waits until the drive is over so diagnostics do not pollute drive-frame timings.
-- This is a raycast smoke test, not a vehicle-impact or mesh-identity test.
local dbg = extensions.e2r_world.dbg()
local samples, out, index, wait = nil, {counts = {}, rays = {}, lamps = 0}, 1, 0
return P.task(function()
  if not dbg.S.overviewTaken then return end
  if not samples then
    local f = scenetree.findObject('e2rForest')
    if not f then return {error = 'Forest missing'} end
    local v = be:getPlayerVehicle(0):getPosition()
    local b = Box3F()
    b.minExtents, b.maxExtents = v - vec3(250, 250, 100), v + vec3(250, 250, 100)
    samples = {}
    local selected = {}
    for _, item in ipairs(f:getData():getItemsBox(b)) do
      local d = item:getData()
      if tostring(d:getField('collidable', 0)) == '1' then
        local shape = d:getField('shapeFile', 0)
        local kind = shape:find('lamp1', 1, true) and 'lamp' or shape:find('/trees/', 1, true) and 'tree' or 'furniture'
        out.counts[kind] = (out.counts[kind] or 0) + 1
        if kind ~= 'furniture' and (selected[kind] or 0) < 10 then
          selected[kind] = (selected[kind] or 0) + 1
          samples[#samples + 1] = {kind = kind, pos = item:getPosition(), shape = shape}
        end
      end
    end
    for _ in pairs(dbg.S.lamps or {}) do out.lamps = out.lamps + 1 end
    out.pendingAdds, out.pendingRemoves = dbg.result.forestPendingAdds, dbg.result.forestPendingRemoves
    -- Explicitly activate recent Forest arrivals. Production still uses the normal rebuild.
    be:reloadCollision()
    return
  end
  wait = wait + 1
  if wait < 20 then return end
  local sample = samples[index]
  if sample then
    local p = sample.pos
    local distances = {}
    for _, axis in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
      distances[#distances + 1] = castRayStatic(vec3(p.x - axis[1] * 2, p.y - axis[2] * 2, p.z + 1),
        vec3(axis[1], axis[2], 0), 4)
    end
    out.rays[#out.rays + 1] = {kind = sample.kind, shape = sample.shape, distances = distances}
    index = index + 1
    return
  end
  jsonWriteFile('/e2r-street-check.json', out, true)
  return out
end)
