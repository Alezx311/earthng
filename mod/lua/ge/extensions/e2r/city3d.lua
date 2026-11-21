-- First-person Kyiv asset experiment. Footprints and POI identities remain OSM facts;
-- the supplied shop architecture and inferred outdoor displays are artistic reconstructions.
-- These are ordinary streamed scene items, never a second static city or road renderer.
local M = {}
M.root = '/art/shapes/earthng/kyiv3d/'
M.assets = {bakery = {6.5, 3.6, 3.2}, coffee = {2.65, 2.65, 3.05}, pharmacy = {7, 2.65, 3.15},
  flowers = {5.4, 5.7, 3.2}, copycentre = {7, 5.5, 3.2}, produce = {3.5, 1.8, 2.7},
  flower_display = {1.5, .7, 1.25}, aircon = {.85, .36, .62}}
M.shops = {
  ['872829200:0'] = {asset = 'pharmacy', count = 2, front = {0, -1}},
  ['641265722:0'] = {asset = 'bakery', count = 1, front = {0, 1}},
  ['872829202:0'] = {asset = 'coffee', count = 1, front = {0, -1}},
  ['617382430:0'] = {asset = 'flowers', count = 7, front = {-1, 0}},
  ['792923346:0'] = {asset = 'copycentre', count = 2, front = {0, 1}},
}
-- Painted loggias and existing geometric balconies are never covered by random modules.
-- At these four mapped blocks the existing AC placement rule may substitute its model.
M.acBlocks = {['97578072:0'] = true, ['120211286:0'] = true, ['634330402:0'] = true, ['120211308:0'] = true}
local NONE = {}

local function owned(rect, x, y)
  return x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4]
end
local function halo(rect, x, y)
  return x >= rect[1] - 12 and x < rect[3] + 12 and y >= rect[2] - 12 and y < rect[4] + 12
end
local function exists(path)
  local ok, found = pcall(function() return FS and FS:fileExists(path) end)
  return ok and found == true
end
function M.available(asset)
  local folder = M.root .. asset .. '/'
  return M.assets[asset] and exists(folder .. asset .. '.dae') and exists(folder .. 'main.materials.json')
end
local function distance2(x, y, a, b)
  local dx, dy = b[1] - a[1], b[2] - a[2]
  local length = dx * dx + dy * dy
  local t = length > 0 and math.max(0, math.min(1, ((x-a[1])*dx + (y-a[2])*dy) / length)) or 0
  return (x-a[1]-dx*t)^2 + (y-a[2]-dy*t)^2
end
local function inPolygon(x, y, rings, radius)
  local inside = false
  for _, ring in ipairs(rings or NONE) do
    local hit = false
    for k, a in ipairs(ring) do
      local b = ring[k % #ring + 1]
      if distance2(x, y, a, b) < radius * radius then return true end
      if (a[2] > y) ~= (b[2] > y) and x < (b[1]-a[1]) * (y-a[2]) / (b[2]-a[2]) + a[1] then hit = not hit end
    end
    if hit then inside = not inside end
  end
  return inside
end

-- Full source footprint, independent of the tile's clipping and enumeration order.
-- The module's negative Y points through the chosen frontage.
function M.frame(building, front)
  local ring = (building.rings or NONE)[1]
  if not ring or #ring < 3 then return nil end
  local best, ux, uy = 0, 1, 0
  for k, a in ipairs(ring) do
    local b = ring[k % #ring + 1]
    local dx, dy = b[1]-a[1], b[2]-a[2]
    local length = math.sqrt(dx*dx + dy*dy)
    if length > best then best, ux, uy = length, dx/length, dy/length end
  end
  if best < .1 then return nil end
  if uy * front[1] - ux * front[2] < 0 then ux, uy = -ux, -uy end
  local vx, vy, loU, hiU, loV, hiV = -uy, ux, math.huge, -math.huge, math.huge, -math.huge
  for _, p in ipairs(ring) do
    local u, v = p[1]*ux + p[2]*uy, p[1]*vx + p[2]*vy
    loU, hiU, loV, hiV = math.min(loU, u), math.max(hiU, u), math.min(loV, v), math.max(hiV, v)
  end
  return {x = ux*(loU+hiU)/2 + vx*(loV+hiV)/2, y = uy*(loU+hiU)/2 + vy*(loV+hiV)/2,
    ux = ux, uy = uy, nx = -vx, ny = -vy, width = hiU-loU, depth = hiV-loV,
    yaw = math.atan2(-uy, ux)}
end

local function item(asset, id, x, y, z, yaw, scale, collision)
  local folder = M.root .. asset .. '/'
  return {kind = 'static', name = 'e2r_city3d_' .. id:gsub('[^%w_]', '_'),
    shape = folder .. asset .. '.dae', materials = folder .. 'main.materials.json',
    pos = {x, y, z}, rot = {0, 0, math.sin(yaw/2), math.cos(yaw/2)},
    scale = scale or 1, layer = 'scene', collision = collision or 'None', city3d = true,
    city3dAsset = asset, city3dRole = asset == 'aircon' and 'facade'
      or (asset == 'produce' or asset == 'flower_display') and 'display' or 'pavilion'}
end
local function count(plan, asset, role)
  plan.report[role] = plan.report[role] + 1
  plan.report.assets[asset] = (plan.report.assets[asset] or 0) + 1
end

-- Replacement requires the complete model set, so a missing file always leaves the
-- original building and collision intact. The footprint stays in every occupancy list.
function M.plan(ctx)
  local options = ctx.options or NONE
  if options.city3d == false or options.realStyle == false or options.far or options.horizon then return nil end
  local plan = {replaced = {}, items = {}, candidates = {}, frames = {}, rect = ctx.rect,
    ground = ctx.ground, ac = M.available('aircon'),
    report = {pavilions = 0, aircon = 0, displays = 0, reservations = 0, rejected = 0, assets = {}, rejections = {}}}
  local buildings = {}
  for _, building in ipairs(ctx.lists.buildings or NONE) do buildings[#buildings + 1] = building end
  table.sort(buildings, function(a, b) return tostring(a.id) < tostring(b.id) end)
  for _, building in ipairs(buildings) do
    local id, spec = tostring(building.id), M.shops[tostring(building.id)]
    if spec and M.available(spec.asset) then
      local frame = M.frame(building, spec.front)
      if frame and frame.width > .5 and frame.depth > .5 then
        local source, count = M.assets[spec.asset], spec.count
        plan.replaced[id], plan.frames[id] = true, frame
        for n = 1, count do
          local along = ((n-.5)/count - .5) * frame.width
          local x, y = frame.x + frame.ux*along, frame.y + frame.uy*along
          if owned(ctx.rect, x, y) then
            plan.items[#plan.items + 1] = item(spec.asset, id .. '_' .. n, x, y, ctx.ground(x, y) -.03,
              frame.yaw, {frame.width/count/source[1], frame.depth/source[2], 1}, 'Visible Mesh')
            plan.report.pavilions = plan.report.pavilions + 1
            plan.report.assets[spec.asset] = (plan.report.assets[spec.asset] or 0) + 1
          end
        end
      end
    end
    -- Loose displays are attached to mapped retail frontages, not random scatter.
    local asset = id == '617382424:0' and 'produce' or id == '617382430:0' and 'flower_display'
    if asset and M.available(asset) then
      local frame = plan.frames[id] or M.frame(building, {-1, 0})
      if frame then
        local source, count = M.assets[asset], asset == 'produce' and 6 or 5
        local radius = math.sqrt(source[1]^2 + source[2]^2)/2
        for n = 1, count do
          local along = ((n-.5)/count - .5) * math.max(0, frame.width-3)
          local offset = frame.depth/2 + source[2]/2 + .35
          local x = frame.x + frame.ux*along + frame.nx*offset
          local y = frame.y + frame.uy*along + frame.ny*offset
          if halo(ctx.rect, x, y) then
            local footprint = {}
            for _, signs in ipairs({{-1, -1}, {1, -1}, {1, 1}, {-1, 1}}) do
              footprint[#footprint + 1] = {x + frame.ux*source[1]*signs[1]/2 + frame.nx*source[2]*signs[2]/2,
                y + frame.uy*source[1]*signs[1]/2 + frame.ny*source[2]*signs[2]/2}
            end
            plan.candidates[#plan.candidates + 1] = {id = id .. '_' .. asset .. '_' .. n, owner = building,
              x = x, y = y, yaw = frame.yaw, radius = radius, height = 0, asset = asset, footprint = footprint}
          end
        end
      end
    end
  end
  return plan
end

-- Substitute one already-selected AC cell, preserving BLD.acUnits' exact floor,
-- facade grid, balcony exclusions, deterministic density and storefront clearance.
function M.aircon(plan, scene, a, b, length, s, z)
  if not plan or not plan.ac or not plan.currentAC then return false end
  local ux, uy = (b[1]-a[1])/length, (b[2]-a[2])/length
  local x, y = a[1] + ux*s + uy*.20, a[2] + uy*s - ux*.20
  if owned(plan.rect, x, y) then
    local id = plan.currentAC .. '_ac_' .. math.floor(x*100+.5) .. '_' .. math.floor(y*100+.5) .. '_' .. math.floor(z*100+.5)
    scene.items[#scene.items + 1] = item('aircon', id, x, y, z, math.atan2(-uy, ux))
    count(plan, 'aircon', 'aircon')
  end
  return true
end

-- The same reservation records go to streetProps, yards and vegetation. A halo
-- candidate reserves both neighbouring tiles, but only its half-open owner draws it.
function M.reserve(plan, lists, segments, scene, signs, existing, pause)
  if not plan then return {}, {} end
  local accepted, rejected = {}, {}
  for _, p in ipairs(plan.candidates) do
    local x, y, r, reason = p.x, p.y, p.radius + .3, nil
    -- A display's circular reservation can touch its owner; its complete model
    -- footprint must remain outside with a real .15 m clearance at every corner.
    for _, corner in ipairs(p.footprint or NONE) do
      if p.owner and inPolygon(corner[1], corner[2], p.owner.rings, .15) then reason = 'owner footprint'; break end
    end
    for _, road in ipairs(segments or NONE) do
      if road.surface and distance2(x, y, road.a, road.b) < (r + road.width/2 + .3)^2 then reason = 'road'; break end
    end
    if not reason then for _, building in ipairs(lists.buildings or NONE) do
      if building ~= p.owner and inPolygon(x, y, building.rings, r + .2) then reason = 'building'; break end
    end end
    if not reason then for _, area in ipairs(lists.areas or NONE) do
      local tags = area.tags or NONE
      if (area.kind == 'water' or area.kind == 'parking' or tags.amenity == 'parking'
        or area.kind == 'paved' and tags.landuse ~= 'retail') and inPolygon(x, y, area.rings, r) then reason = 'area'; break end
    end end
    if not reason then for _, line in ipairs(lists.lines or NONE) do
      local tags, points = line.tags or NONE, line.points or NONE
      if line.kind == 'path' and tags.bridge ~= 'yes' and tags.tunnel ~= 'yes' then
        for k = 1, #points-1 do
          if distance2(x, y, points[k], points[k+1]) < (r + math.max(.5, (tonumber(tags.width) or 2)/2) + .3)^2 then reason = 'path'; break end
        end
      end
      if reason then break end
    end end
    if not reason then for _, point in ipairs(lists.points or NONE) do
      if point.pos and (point.kind == 'tree' or point.kind == 'lamp' or point.kind == 'stop') then
        local reach = point.kind == 'tree' and 3 or point.kind == 'stop' and 5 or 1
        if (x-point.pos[1])^2 + (y-point.pos[2])^2 < (r+reach)^2 then reason = 'mapped point'; break end
      end
    end end
    if not reason then for _, sign in ipairs(signs or NONE) do
      if (x-sign[1])^2 + (y-sign[2])^2 < (r+2.6)^2 then reason = 'sign'; break end
    end end
    if not reason then for _, other in ipairs(existing or NONE) do
      if (x-other.x)^2 + (y-other.y)^2 < (r+other.radius+.4)^2 then reason = 'authored object'; break end
    end end
    if not reason then for _, other in ipairs(accepted) do
      if (x-other.x)^2 + (y-other.y)^2 < (r+other.radius+.3)^2 then reason = 'display'; break end
    end end
    if reason then
      rejected[#rejected + 1] = {id = p.id, reason = reason}
      plan.report.rejected = plan.report.rejected + 1
      plan.report.rejections[reason] = (plan.report.rejections[reason] or 0) + 1
    else
      accepted[#accepted + 1] = p
      plan.report.reservations = plan.report.reservations + 1
      if owned(plan.rect, x, y) then
        scene.items[#scene.items + 1] = item(p.asset, p.id, x, y, plan.ground(x, y), p.yaw, 1, 'Visible Mesh')
        count(plan, p.asset, 'displays')
      end
    end
    if pause then pause() end
  end
  return accepted, rejected
end
return M
