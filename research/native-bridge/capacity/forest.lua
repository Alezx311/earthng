-- Forest capacity: create/remove cost per item, the engine's deferred cost of touching a kind
-- (Ticking) by the items standing in it, a second kind on an aliased path (dir/./name), and the
-- standing frame, as one kind grows to hundreds of thousands of trees round the car.
-- Run after common.lua: python earthng/probe.py --user <user> -f research/native-bridge/capacity/forest.lua --timeout 900
local LEVELS = _G.__capForest or {10000, 50000, 150000, 300000}
local CHUNK, RADIUS, SMALL, WINDOW, ROUNDS = 10000, 900, 100, 15, 4
local SHAPE = assert(CAP.TREE, 'no stock tree shape')
local forest = scenetree.findObject('e2rForest')
if not forest then return 'no e2rForest (land first)' end
local data = forest:getData()
local cx, cy, cz = CAP.origin()
local dir, file = SHAPE:match('^(.*/)([^/]+)$')

local function kind(name, shape)
  local d = scenetree.findObject(name)
  if d then return d end
  local ok
  ok, d = pcall(createObject, 'ForestItemData')
  assert(ok and d, 'ForestItemData')
  for field, value in pairs({shapeFile = shape, collidable = '0', windScale = '0'}) do
    if not pcall(function() d:setField(field, '', value) end) then d:setField(field, 0, value) end
  end
  d:registerObject(name)
  return d
end
local big = kind('e2rCapBig', SHAPE)
local alias = kind('e2rCapAlias', dir .. './' .. file)
local out = {shape = SHAPE, levels = {}}
local items, smalls = {}, {}
local m, timer = MatrixF(true), hptimer()
local at = vec3(0, 0, 0)

local function plant(d, k, n, list)
  local a, r = k * 2.399963, 10 + RADIUS * math.sqrt(k / n)
  at.x, at.y, at.z = cx + r * math.cos(a), cy + r * math.sin(a), cz - 1
  m:setPosition(at)
  local ok, item = pcall(data.createNewItem, data, d, m, 1)
  if ok and item then list[#list + 1] = item; return true end
end

-- Add one item to a kind and watch the engine's Ticking and the frame over WINDOW frames.
local function touch(d, list, key, n)
  local round, frame, worst, tick, frames = 0, 0, 0, 0, 0
  local res = {}
  return function(_, ms)
    if frame == 0 then
      round = round + 1
      CAP.phase(key)
      plant(d, n + round, n + ROUNDS + 1, list)
    end
    frame = frame + 1
    local e = CAP.engine()
    tick = math.max(tick, e.Ticking or 0)
    worst = math.max(worst, ms)
    frames = frames + 1
    if frame >= WINDOW then
      res[#res + 1] = {tickMax = tick, frameMax = worst}
      frame, tick, worst = 0, 0, 0
      if round >= ROUNDS then
        local sumT, sumF = 0, 0
        for _, r in ipairs(res) do sumT, sumF = sumT + r.tickMax, sumF + r.frameMax end
        out[key] = {tickMax = sumT / #res, frameMax = sumF / #res, rounds = res}
        round = 0
        return true
      end
    end
  end
end

local steps = {CAP.waitQuiet(90, 60), CAP.measure(out, 'base', 150, 30)}
-- a small aliased kind beside the big one
steps[#steps + 1] = function()
  for k = 1, SMALL do plant(alias, k, SMALL, smalls) end
  return true
end
for li, level in ipairs(LEVELS) do
  local L = {level = level}
  out.levels[li] = L
  steps[#steps + 1] = function()
    if out.stopped then return true end
    CAP.phase('grow-' .. level)
    local from = #items + 1
    local to = math.min(level, from + CHUNK - 1)
    timer:stopAndReset()
    for k = from, to do plant(big, k, LEVELS[#LEVELS], items) end
    local ms = timer:stop()
    L.createUs = ms * 1000 / math.max(1, to - from + 1)
    if ms > 3000 then out.stopped = 'create chunk ' .. ms .. ' ms at ' .. to end
    return #items >= level or #items < to
  end
  steps[#steps + 1] = CAP.measure(out, 'settle-' .. level, 30, 60)
  steps[#steps + 1] = touch(big, items, 'touchBig-' .. level, level)
  steps[#steps + 1] = touch(alias, smalls, 'touchAlias-' .. level, SMALL)
  steps[#steps + 1] = CAP.measure(out, 'stand-' .. level, 150, 30, nil, function() return {count = #items} end)
end
-- remove: each item once (a second removeItem of the same item crashes the game)
local removed, remMs = 0, 0
steps[#steps + 1] = function()
  CAP.phase('remove')
  timer:stopAndReset()
  local n = 0
  for k = #items, math.max(1, #items - CHUNK + 1), -1 do
    pcall(data.removeItem, data, items[k]); items[k] = nil; n = n + 1
  end
  remMs = remMs + timer:stop(); removed = removed + n
  if #items == 0 then
    for k = #smalls, 1, -1 do pcall(data.removeItem, data, smalls[k]); smalls[k] = nil end
    out.removeUs = remMs * 1000 / math.max(1, removed)
    return true
  end
end
steps[#steps + 1] = CAP.measure(out, 'after', 150, 90)
return CAP.run(steps, out)
