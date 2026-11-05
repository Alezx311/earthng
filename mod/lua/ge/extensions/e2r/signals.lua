-- Traffic lights that run (issue #23, docs/SIGNS.md). One clock for the whole world: every light
-- of a group (generator.lua SIGNS.phases: slot * 2 + axis) has the same colour, so a phase change
-- is a few setHidden on the lit lens meshes of each tile, no work in between. The game's AI reads
-- the same colours: mapmgr.setSignals with the lights on the navgraph round the car, the mailbox
-- for each change, as core_trafficSignals sends them (its own sequences restart with every
-- map.reset, and the navgraph here is rebuilt every 250 m).
local M = {}

local GREEN, YELLOW, CLEAR = 24, 3, 2     -- s: of each axis; CLEAR all red
local CYCLE = 2 * (GREEN + YELLOW + CLEAR)
local SLOTS = 3
local GROUPS = SLOTS * 2
local EVERY = .2                          -- s between looks at the clock
local REACH = 1000                        -- m: world.lua NAV_R
local KEEP = 3000                         -- m: a light farther than this leaves what AI is sent
local RESEND = 15                         -- s: for the cars spawned since
local ACTION = {green = 0, yellow = 1, red = 2}   -- core_trafficSignals signalActions: none, alert, stop

local function fresh()
  return {tiles = {}, meshes = {}, colours = {}, nextAt = -math.huge, edges = {}, sendAt = -math.huge}
end
local st = fresh()

function M.colour(group, now)
  local slot, axis = math.floor(group / 2), group % 2
  local at = (now + slot * CYCLE / SLOTS + axis * CYCLE / 2) % CYCLE
  if at < GREEN then return 'green' end
  if at < GREEN + YELLOW then return 'yellow' end
  return 'red'
end

-- The lenses and AI update at EVERY, not continuously. Consumers must use the phase actually
-- displayed, including the small interval between a clock boundary and the next update.
function M.current(group, now)
  return st.colours[group] or M.colour(group, now)
end

local function show(id, on)
  local obj = scenetree.findObjectById(id)
  if obj then obj:setHidden(not on) end
  return obj ~= nil
end

function M.clear() st = fresh() end

-- a lens mesh is in the scene (world.lua spawnItem)
function M.addMesh(id, group, colour)
  local key = group .. colour
  local list = st.meshes[key]
  if not list then list = {}; st.meshes[key] = list end
  list[#list + 1] = id
  show(id, (st.colours[group] or M.colour(group, st.now or 0)) == colour)
end

-- the lights a tile's scene brought {road, x, y, z, dx, dy, group}
function M.addTile(key, lights) st.tiles[key] = lights and #lights > 0 and lights or nil end
function M.dropTile(key) st.tiles[key] = nil end

local function shown(key, on)
  local list = st.meshes[key]
  if not list then return end
  local kept = 0
  for k = 1, #list do
    local id = list[k]
    if show(id, on) then kept = kept + 1; list[kept] = id end
  end
  for k = #list, kept + 1, -1 do list[k] = nil end
end

-- The piece of a segment a light's stop point is on, as the navgraph's edge in the direction of
-- travel: its nodes are named as world.lua navBuild names them. nil if the graph has no such edge.
function M.edge(sid, seg, q, nodes)
  local s = seg.s
  local n = (#s - 7) / 3
  local function id(k)
    if k == 1 then return 'e2r_n' .. tostring(s[2]) end
    if k == n then return 'e2r_n' .. tostring(s[3]) end
    return 'e2r_s' .. sid .. '_' .. k
  end
  local best, bestK = math.huge, nil
  for k = 1, n - 1 do
    local o = 8 + 3 * (k - 1)
    local ax, ay, bx, by = s[o], s[o + 1], s[o + 3], s[o + 4]
    local dx, dy = bx - ax, by - ay
    local l2 = dx * dx + dy * dy
    if l2 > 0 then
      local f = math.max(0, math.min(1, ((q.x - ax) * dx + (q.y - ay) * dy) / l2))
      local ex, ey = ax + f * dx - q.x, ay + f * dy - q.y
      local d = ex * ex + ey * ey
      if d < best then best, bestK = d, k end
    end
  end
  if not bestK then return nil end
  local o = 8 + 3 * (bestK - 1)
  local forward = (s[o + 3] - s[o]) * q.dx + (s[o + 4] - s[o + 1]) * q.dy >= 0
  local a, b = id(bestK), id(bestK + 1)
  if not forward then a, b = b, a end
  local node = nodes[a]
  if node and node.links[b] then return a, b end
  return nil
end

local function dictionary(now)
  local dict = {}
  for a, out in pairs(st.edges) do
    for b, e in pairs(out) do
      local colour = st.colours[e.group] or M.colour(e.group, now)
      dict[a] = dict[a] or {}
      dict[a][b] = {{instance = a .. '>' .. b, pos = e.pos, state = colour, action = ACTION[colour]}}
    end
  end
  return dict
end

local function send(now)
  st.sendAt = now
  be:queueAllObjectLua(string.format('mapmgr.setSignals(%s)', serialize(dictionary(now))))
end

-- After a navBuild: the lights on the new graph. An edge stays until the car is KEEP m off: a car
-- that has a light in its plan indexes the table by it (ai.lua), and a missing one stops its Lua.
function M.navgraph(nodes, nav, x, y, traffic, makePos)
  for a, out in pairs(st.edges) do
    for b, e in pairs(out) do
      if (e.x - x) ^ 2 + (e.y - y) ^ 2 > KEEP * KEEP then out[b] = nil end
    end
    if not next(out) then st.edges[a] = nil end
  end
  for _, lights in pairs(st.tiles) do
    for _, q in ipairs(lights) do
      if (q.x - x) ^ 2 + (q.y - y) ^ 2 < REACH * REACH then
        local seg = nav[q.road]
        local a, b
        if seg then a, b = M.edge(q.road, seg, q, nodes) end
        if a then
          local out = st.edges[a]
          if not out then out = {}; st.edges[a] = out end
          if not out[b] then
            out[b] = {group = q.group, x = q.x, y = q.y, dx = q.dx, dy = q.dy, pos = makePos(q.x, q.y, q.z)}
          end
        end
      end
    end
  end
  if traffic and st.now then send(st.now) end
end

-- The game test's look at the AI: cars {x, y, vx, vy} against the lights it was given. waiting: stand
-- short of a red line, ran: cross it at speed, crossed: cross a line that is not red.
function M.watch(cars, tally)
  for _, out in pairs(st.edges) do
    for _, e in pairs(out) do
      tally.lights = (tally.lights or 0) + 1
      local red = st.colours[e.group] == 'red'
      for _, c in ipairs(cars) do
        local rx, ry = c.x - e.x, c.y - e.y
        local along, across = rx * e.dx + ry * e.dy, math.abs(rx * e.dy - ry * e.dx)
        local speed = c.vx * e.dx + c.vy * e.dy
        if across < 8 then
          if red and along > -25 and along < 2 and math.abs(speed) < 1 then tally.waiting = (tally.waiting or 0) + 1
          elseif along > -4 and along < 4 and speed > 3 then
            local key = red and 'ran' or 'crossed'
            tally[key] = (tally[key] or 0) + 1
          end
        end
      end
    end
  end
end

-- once a frame: traffic is true while the game's AI drives
function M.step(now, traffic)
  st.now = now
  if now < st.nextAt then return end
  st.nextAt = now + EVERY
  local changed
  for group = 0, GROUPS - 1 do
    local colour = M.colour(group, now)
    local old = st.colours[group]
    if colour ~= old then
      st.colours[group] = colour
      if old then shown(group .. old, false) end
      shown(group .. colour, true)
      changed = changed or {}
      changed[group] = true
    end
  end
  if not traffic or not next(st.edges) then return end
  if now - st.sendAt >= RESEND then send(now)
  elseif changed then
    local list = {}
    for a, out in pairs(st.edges) do
      for b, e in pairs(out) do
        if changed[e.group] then
          list[#list + 1], list[#list + 2], list[#list + 3], list[#list + 4] = a, b, 1, ACTION[st.colours[e.group]]
        end
      end
    end
    if #list > 0 then be:sendToMailbox('trafficSignalUpdates', lpack.encodeBin(list)) end
  end
end

return M
