-- Many copies of a shape as one scene object each shape: the engine's DynamicShapeBatch (BeamNG
-- 0.40.5; the engine facts table of docs/PERFORMANCE.md). A TSStatic per copy is a scene object per
-- copy, and every setPosRot / setHidden in the level costs more the more scene objects there are
-- (+0.6-0.8 us per 1000: 2 us at 2000 objects, 10 at 30 000); setInstance costs 0.5 us whatever the
-- scene holds, and a batch is one object however many copies it draws (1000 walkers in view: the
-- frame unchanged, dsb-01). What the engine does, from the probes (dsb3-5.lua in
-- research/native-bridge/capacity/ on the branch codex/native-bridge-benchmark):
--   - setInstance(slot, pos, dir, scale, ColorF): dir is no rotation but the direction the shape's
--     +y axis points; the rest of the frame follows as Torque's createOrientFromDir does (x = y
--     cross world up, z = x cross y). A shape facing +x (the flow's cars, the walkers) is turned to
--     heading (hx, hy) by dir (-hy, hx, 0): upright always, a slope (pitch) cannot be given (dsb-02/03).
--   - The ColorF paints the shape's first palette slot (instanceColor of a TSStatic: the walkers'
--     shirts); there is no second or third. setMaterialRemap(from, to) before finalizeShape puts
--     another material in a batch's shape (dsb-02): the walkers' trousers and skin.
--   - finalizeShape costs 11-27 ms a call (dsb-03: 25 ms with the shape loading in it, 13-15 ms on
--     a shape loaded before), so a batch is made once and a layer has few of them: M.add makes at
--     most PER_FRAME new batches a frame (M.tick) and returns nothing for a kind still waiting.
--   - finalizeShape on a shape a TSStatic began to load up to ~20 frames before leaves a batch that
--     draws nothing (dsb-02, dsb-03); on a shape not loaded at all it loads it there and draws.
--     So the flow's view warms no TSStatic of its batched shapes. The landing's warm-up of the
--     walkers' shapes stays: it is long done when the first batch is made, and a batch of a loaded
--     shape is the cheaper one (6 ms on average, 10 at most, on-01).
--   - getLastVisibleCount / getLastSubmittedCount read 0 in the mod even for copies on screen
--     (probe-01): whether a batch draws is seen on a still only.
--   - A copy is placed by setInstance, then shown by setInstanceEnabled(slot, true); enabled before
--     its first setInstance it stays unseen, and setInstance on a hidden slot does not show it.
--     resize keeps the copies standing. A slot past the size is taken without an error and must
--     never be used; clearInstances leaves a batch that shows nothing again: neither is done here.
-- One batch per kind (a shape and its material remaps), made on first use; its copies are slots
-- 0..size-1, free ones in a list, a full batch doubles its size. No garbage per call: one vec3 for
-- the place and one for the direction, filled in place.
-- M.available() is false where the class or its calls are missing (an older game): the callers
-- keep a TSStatic per copy there. Pure Lua with a stand-in createObject: earthng/test_shapebatch.py.
local M = {}

local FIRST = 16          -- slots of a new batch
M.PER_FRAME = 1           -- new batches a frame (each ~13-25 ms of finalizeShape)

-- the class is there and takes the calls this module makes (checked once a session)
function M.available()
  if M.ok == nil then
    local ok, o = pcall(createObject, 'DynamicShapeBatch')
    M.ok = ok and o ~= nil and o.setInstance ~= nil and o.setInstanceEnabled ~= nil and o.resize ~= nil
      and o.setShape ~= nil and o.finalizeShape ~= nil and o.setMaterialRemap ~= nil or false
    -- deleted registered, as every probe did (an object never registered was never deleted)
    if ok and o then pcall(function() o:registerObject(''); o:delete() end) end
  end
  return M.ok
end

-- P = M.new(group): the batches of a layer (the flow, the walkers), in group (nil: none). P takes
-- this module's calls as methods (P:add(...)), so flow.lua and walkers.lua need not require it.
local Pool = {__index = M}
function M.new(group)
  return setmetatable({group = group, kinds = {}, list = {}, frame = 0, made = 0, objects = 0, live = 0, resizes = 0,
    waits = 0, finalMs = 0, finalMax = 0, timer = hptimer and hptimer() or nil, pos = vec3(0, 0, 0), dir = vec3(0, 1, 0),
    white = ColorF(1, 1, 1, 1)}, Pool)
end

-- A kind: shape with its materials remapped ({from, to, from2, to2, ...}; nil: none), the same
-- table for the same key (make the kinds once, not per copy).
function M.kind(P, shape, remap, key)
  key = key or shape
  local K = P.kinds[key]
  if not K then
    K = {shape = shape, remap = remap, key = key}
    P.kinds[key] = K
  end
  return K
end

local function batchOf(P, K)
  local B = K.batch
  if B then return B end
  local o = createObject('DynamicShapeBatch')
  o.canSave = false
  o:registerObject('')
  if P.group then P.group:addObject(o) end
  o:setShape(K.shape)
  local remap = K.remap
  if remap then
    for k = 1, #remap - 1, 2 do o:setMaterialRemap(remap[k], remap[k + 1]) end
  end
  local timer = P.timer
  if timer then timer:stopAndReset() end
  o:finalizeShape()
  if timer then
    local ms = timer:stop()
    P.finalMs, P.finalMax = P.finalMs + ms, math.max(P.finalMax, ms)
  end
  o:resize(FIRST)
  B = {obj = o, kind = K, size = FIRST, free = {}, nfree = FIRST, live = 0, on = {}, c = {}}
  -- slot 0 is taken first
  for k = 1, FIRST do B.free[k] = FIRST - k end
  K.batch = B
  P.list[#P.list + 1] = B
  P.objects, P.made = P.objects + 1, P.made + 1
  return B
end

-- the kind's batch made now, whatever this frame made already (a layer's start: its shapes load
-- then, not with its first copies)
function M.warm(P, K) return batchOf(P, K) end

-- every frame: the budget of new batches starts again
function M.tick(P)
  P.frame, P.made = P.frame + 1, 0
end

local function place(P, B, i, x, y, z, dx, dy, dz)
  local p, d = P.pos, P.dir
  p.x, p.y, p.z = x, y, z
  d.x, d.y, d.z = dx, dy, dz
  B.obj:setInstance(i, p, d, 1, B.c[i] or P.white)
end

local function grow(P, B)
  local old, size = B.size, B.size * 2
  B.obj:resize(size)
  B.size = size
  for i = size - 1, old, -1 do
    B.nfree = B.nfree + 1
    B.free[B.nfree] = i
  end
  P.resizes = P.resizes + 1
end

-- A copy of kind K at (x, y, z), its shape's +y along the unit vector (dx, dy, dz), in colour (a
-- ColorF; nil: white), shown. Returns its batch and slot (move / drop take them), or nothing when
-- K has no batch yet and this frame made its PER_FRAME already (ask again next frame).
function M.add(P, K, x, y, z, dx, dy, dz, colour)
  local B = K.batch
  if not B then
    if P.made >= M.PER_FRAME then
      P.waits = P.waits + 1
      return nil
    end
    B = batchOf(P, K)
  end
  if B.nfree == 0 then grow(P, B) end
  local i = B.free[B.nfree]
  B.free[B.nfree] = nil
  B.nfree = B.nfree - 1
  B.live, P.live = B.live + 1, P.live + 1
  B.on[i], B.c[i] = true, colour
  place(P, B, i, x, y, z, dx, dy, dz)
  B.obj:setInstanceEnabled(i, true)
  return B, i
end

-- the copy placed again (colour nil: as it was)
function M.move(P, B, i, x, y, z, dx, dy, dz, colour)
  if colour then B.c[i] = colour end
  place(P, B, i, x, y, z, dx, dy, dz)
end

-- the copy hidden and its slot free
function M.drop(P, B, i)
  if not B.on[i] then return end
  B.obj:setInstanceEnabled(i, false)
  B.on[i], B.c[i] = nil, nil
  B.nfree = B.nfree + 1
  B.free[B.nfree] = i
  B.live, P.live = B.live - 1, P.live - 1
end

-- every batch deleted (the kinds stay, without batches)
function M.clear(P)
  for _, B in ipairs(P.list) do
    pcall(function() B.obj:delete() end)
    B.kind.batch = nil
  end
  P.list, P.objects, P.live = {}, 0, 0
end

-- the direction of a +x shape's +y axis for heading yaw (radians about z)
function M.yAxis(yaw) return -math.sin(yaw), math.cos(yaw), 0 end

return M
