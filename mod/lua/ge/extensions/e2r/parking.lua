-- Parked cars: the game's own parking system (gameplay_parking) with its light 'parked' configs
-- (simple_traffic), in place of the box cars generator.lua drew on OSM parking areas. The game
-- keeps a pool of real cars and moves them to free spots ahead of the player; the spots are the
-- bays the generator lays out (scene manifest .parking: {x, y, z, yaw} each).
--   - A pool car keeps the id of its spot, so spots are only ever added while the player stays in
--     one place; a spot whose tile is gone or has no collision (yet, or any more) is banned
--     instead, so a car is never put where it would fall through the world.
--   - A bay is SPOT wide and long: the lattice is 2.7 m across, rows 5.5 m apart back to back.
local M = {}

local SPOT = {2.6, 5.4, 3}
local SITES = '/lua/ge/extensions/gameplay/sites/sites'
-- the widget's choices (world.lua drawTraffic): 0 draws the box cars instead
M.AMOUNTS = {{0, 'Вимк', 'Off'}, {8, 'Мало', 'Few'}, {16, 'Багато', 'Many'}}
M.EVERY = 2   -- s between syncs of the spots

-- the game's parking extension and the traffic one, whose focus (the player) it follows
local function ensureGame()
  if not gameplay_traffic then extensions.load('gameplay_traffic') end
  if not gameplay_parking then extensions.load('gameplay_parking') end
  return gameplay_parking ~= nil and gameplay_traffic ~= nil
end

local function spotKey(s) return string.format('%.1f:%.1f', s[1], s[2]) end

function M.new()
  -- spotsOf: a tile's spot objects, kept with the list they came from (weak: tiles come and go)
  return {sites = nil, byKey = {}, spotsOf = setmetatable({}, {__mode = 'k'}), live = {}, count = 0,
    total = 0, spawned = 0}
end

-- tiles: key -> {parking = list, collided, state}. Adds the spots not seen yet, bans the ones
-- that cannot hold a car now. Returns the number of usable spots. A tile whose list is the one
-- seen before costs only its spots' membership (the first pass over Kyiv's 1600 took 24 ms).
function M.sync(P, tiles)
  local added, live, count = 0, {}, 0
  for _, tile in pairs(tiles) do
    local spots = P.spotsOf[tile]
    if not spots or spots.src ~= tile.parking then
      spots = {src = tile.parking}
      for _, s in ipairs(tile.parking or {}) do
        local key = spotKey(s)
        local ps = P.byKey[key]
        if not ps then
          P.sites = P.sites or require(SITES)('EarthNG parking')
          ps = P.sites.parkingSpots:create(nil, nil, true)
          ps:set(vec3(s[1], s[2], s[3]), quatFromDir(vec3(math.cos(s[4]), math.sin(s[4]), 0), vec3(0, 0, 1)),
            vec3(SPOT[1], SPOT[2], SPOT[3]))
          ps.customFields:addTag('banned')
          P.byKey[key] = ps
          added = added + 1
        end
        spots[#spots + 1] = ps
      end
      P.spotsOf[tile] = spots
    end
    if tile.collided and tile.state == 'loaded' and not tile.failed then
      for _, ps in ipairs(spots) do
        if not live[ps] then live[ps] = true; count = count + 1 end
      end
    end
  end
  for ps in pairs(P.live) do
    if not live[ps] then ps.customFields:addTag('banned') end
  end
  for ps in pairs(live) do
    if not P.live[ps] then ps.customFields:removeTag('banned') end
  end
  P.live, P.count = live, count
  if added > 0 then
    P.total = P.total + added
    P.sites.parkingSpots:sort()
    P.sites:finalizeSites()
    if gameplay_parking then gameplay_parking.setSites(P.sites) end
  end
  return count
end

-- Keeps `amount` parked cars round pos once there are twice as many usable spots (the game puts
-- the first ones on spots near the player; with too few it falls back to road spawns, and our
-- navgraph exists only while traffic runs). Returns true when a spawn was asked for.
function M.step(P, amount, pos)
  if amount == P.spawned or not P.sites then return false end
  if amount > 0 and P.count < amount * 2 then return false end
  if not ensureGame() then return false end
  if amount == 0 then
    gameplay_parking.deleteVehicles()
    gameplay_parking.deactivate()
    P.spawned = 0
    return false
  end
  gameplay_parking.setSites(P.sites)
  local ok = gameplay_parking.setupVehicles(amount, {pos = pos})
  P.spawned = amount
  return ok and true or false
end

-- the place is left: its cars and spots go
function M.clear(P)
  if gameplay_parking and P.spawned > 0 then
    gameplay_parking.deleteVehicles()
    gameplay_parking.deactivate()
  end
  if gameplay_parking and P.sites then gameplay_parking.setSites(nil) end
  P.sites, P.byKey, P.live, P.count, P.total, P.spawned = nil, {}, {}, 0, 0, 0
  P.spotsOf = setmetatable({}, {__mode = 'k'})
end

return M
