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
-- 0..size-1, free ones in a list, a full batch doubles its size. No garbage per call. Each copy
-- keeps the vec3 it was placed with: the engine reads those vectors when it draws, after the call
-- has returned, and one shared vec3 left every copy on the last place written that frame (the
-- crowd blinked). A freed slot keeps its vectors for the next copy.
-- A batch's copies cast no shadow: they are not drawn into the shadow maps at all, and what is
-- seen under one is the screen's own contact shadow, a hand wide (a row of test copies beside the
-- same shape as a TSStatic, shadow-01: on the ground, lifted, scaled, any draw distance). So the
-- copies near the player are "solid" ones (M.addSolid): a TSStatic each from a pool a kind, with
-- the copy's colour as its instance colour and, unlike a batch's copy, its nose up a slope. They
-- answer M.move and M.drop as a batch's copies do. A kind that has a batch as well (K.batchToo)
-- gets no TSStatic before that batch is made (the trap of a TSStatic loading the shape first,
-- above): M.addSolid gives a batch copy until then.
-- M.available() is false where the class or its calls are missing (an older game): the callers
-- keep a TSStatic per copy there. Pure Lua with a stand-in createObject: earthng/test_shapebatch.py.
local M = {}

local FIRST = 16          -- slots of a new batch
M.PER_FRAME = 1           -- new batches a frame (each ~13-25 ms of finalizeShape)
-- A batch whose finalizeShape is what first loads its shape draws nothing, for as long as it
-- lives, when the shape is a textured model of a few thousand triangles (the fal cars: 400
-- copies placed and enabled, none on the road; the flow made again a while later, its shapes
-- loaded by then, drew them all: look-07). The drawn shapes of a few hundred triangles never
-- showed it. So a kind's first batch is a primer that only loads the shape, and the batch of its
-- copies is made PRIME_FRAMES later, the primer deleted once that one is there. 0: no primer (the
-- tests; world.lua sets it for the game).
M.PRIME_FRAMES = 0
M.SOLID_PER_FRAME = 6     -- new TSStatics of solid copies a frame (~0.1 ms each of a loaded shape)
local SOLID_SPARE, SOLID_TRIM_AFTER = 4, 600   -- hidden ones kept a kind; frames unused before the rest go

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
    waits = 0, finalMs = 0, finalMax = 0, timer = hptimer and hptimer() or nil, white = ColorF(1, 1, 1, 1),
    solids = {}, solidMade = 0, solidObjects = 0, solidLive = 0, trimAt = 0}, Pool)
end

-- A kind: shape with its materials remapped ({from, to, from2, to2, ...}; nil: none), the same
-- table for the same key (make the kinds once, not per copy). batchToo: its solid copies
-- (M.addSolid) wait for its batch, which its other copies are in.
function M.kind(P, shape, remap, key, batchToo)
  key = key or shape
  local K = P.kinds[key]
  if not K then
    K = {shape = shape, remap = remap, key = key, batchToo = batchToo}
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
  B = {obj = o, kind = K, size = FIRST, free = {}, nfree = FIRST, live = 0, on = {}, c = {}, p = {}, d = {}}
  -- slot 0 is taken first
  for k = 1, FIRST do B.free[k] = FIRST - k end
  K.batch = B
  P.list[#P.list + 1] = B
  P.objects, P.made = P.objects + 1, P.made + 1
  return B
end

-- the kind's primer: a batch without copies that loads the shape
local function prime(P, K)
  local o = createObject('DynamicShapeBatch')
  o.canSave = false
  o:registerObject('')
  if P.group then P.group:addObject(o) end
  o:setShape(K.shape)
  local timer = P.timer
  if timer then timer:stopAndReset() end
  o:finalizeShape()
  if timer then
    local ms = timer:stop()
    P.finalMs, P.finalMax = P.finalMs + ms, math.max(P.finalMax, ms)
  end
  K.primer, K.primeAt = o, P.frame
  P.objects, P.made = P.objects + 1, P.made + 1
end

-- the kind's shape loaded now, whatever this frame made already (a layer's start: its shapes load
-- then, not with its first copies): its batch at once, or with primers its primer (the batch
-- then comes with the first copy asked for PRIME_FRAMES later)
function M.warm(P, K)
  if M.PRIME_FRAMES > 0 then
    if not K.batch and not K.primer then prime(P, K) end
    return K.batch
  end
  return batchOf(P, K)
end

-- every frame: the budgets of new batches and new solid copies start again; now and then the
-- hidden TSStatics a kind has not needed for a while go (one kind a call)
function M.tick(P)
  P.frame, P.made, P.solidMade = P.frame + 1, 0, 0
  local solids = P.solids
  if #solids > 0 and P.frame % 30 == 0 then
    local at = P.trimAt % #solids + 1
    P.trimAt = at
    local B = solids[at]
    if P.frame - B.usedAt > SOLID_TRIM_AFTER then
      local cut = 0
      while B.nfree > SOLID_SPARE and cut < 4 do
        -- the highest slot only, while it is a free one: the slots below keep their numbers
        local i, at = B.top, nil
        for k = B.nfree, 1, -1 do
          if B.free[k] == i then at = k break end
        end
        if not at then break end
        B.free[at] = B.free[B.nfree]
        B.free[B.nfree] = nil
        B.nfree, B.top, cut = B.nfree - 1, B.top - 1, cut + 1
        local o = B.objs[i]
        B.objs[i], B.c[i] = nil, nil
        pcall(function() o:delete() end)
        P.solidObjects = P.solidObjects - 1
      end
    end
  end
end

local function place(P, B, i, x, y, z, dx, dy, dz)
  local p, d = B.p[i], B.d[i]
  if not p then
    p, d = vec3(x, y, z), vec3(dx, dy, dz)
    B.p[i], B.d[i] = p, d
  else
    p.x, p.y, p.z = x, y, z
    d.x, d.y, d.z = dx, dy, dz
  end
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
    if M.PRIME_FRAMES > 0 then
      if not K.primer then
        prime(P, K)
        P.waits = P.waits + 1
        return nil
      end
      if P.frame - K.primeAt < M.PRIME_FRAMES then
        P.waits = P.waits + 1
        return nil
      end
    end
    B = batchOf(P, K)
    -- (after its batch is made: the shape never goes without a holder)
    if K.primer then
      local primer = K.primer
      pcall(function() primer:delete() end)
      K.primer = nil
      P.objects = P.objects - 1
    end
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

-- --- solid copies: a TSStatic each (they cast shadows) ------------------------------------------
local function solidOf(P, K)
  local B = K.solid
  if not B then
    B = {static = true, kind = K, objs = {}, free = {}, nfree = 0, on = {}, c = {}, top = 0, live = 0, usedAt = P.frame}
    K.solid = B
    P.solids[#P.solids + 1] = B
  end
  return B
end

local function solidMake(P, B)
  local o = createObject('TSStatic')
  o:setField('shapeName', 0, B.kind.shape)
  o:setField('collisionType', 0, 'None')
  o:setField('decalType', 0, 'None')
  o.useInstanceRenderData = true
  o.canSave = false
  o:setPosRot(0, 0, -5000, 0, 0, 0, 1)
  o:registerObject('')
  o:setHidden(true)
  if P.group then P.group:addObject(o) end
  P.solidObjects = P.solidObjects + 1
  return o
end

-- the TSStatic turned so that the shape's +y points along (dx, dy), its +x (the nose of a car)
-- pitch radians up: the rotation setPosRot takes (flow.quat: the conjugate of the textbook one)
local function solidPlace(o, x, y, z, dx, dy, pitch)
  local h = math.atan2(-dx, dy) / 2
  if pitch and pitch ~= 0 then
    local cy, sy, ca, sa = math.cos(h), math.sin(h), math.cos(-pitch / 2), math.sin(-pitch / 2)
    o:setPosRot(x, y, z, sy * sa, -cy * sa, -sy * ca, cy * ca)
  else
    o:setPosRot(x, y, z, 0, 0, -math.sin(h), math.cos(h))
  end
end

-- the copy's colour as the TSStatic's instance colour (linear, made once a ColorF)
local function solidColour(P, o, colour)
  local lin = P.lin
  if not lin then lin = setmetatable({}, {__mode = 'k'}); P.lin = lin end
  local c = lin[colour]
  if not c then
    c = colour.asLinear4F and colour:asLinear4F() or colour
    lin[colour] = c
  end
  o.instanceColor = c
  if o.updateInstanceRenderData then o:updateInstanceRenderData() end
end

-- the kind's shape loaded by a hidden TSStatic now (a layer's start), for a kind without a batch
function M.warmSolid(P, K)
  local B = solidOf(P, K)
  if B.top == 0 then
    B.top, B.nfree = 1, 1
    B.objs[1] = solidMake(P, B)
    B.free[1] = 1
  end
end

-- As M.add, the copy a TSStatic: it casts a shadow and takes pitch (radians, the shape's +x up).
-- Returns its bucket and slot for M.move / M.drop, or nothing when this frame made its
-- SOLID_PER_FRAME already. A kind with a batch as well whose batch is not there yet: a batch copy.
function M.addSolid(P, K, x, y, z, dx, dy, dz, colour, pitch)
  if K.batchToo and not K.batch then return M.add(P, K, x, y, z, dx, dy, dz, colour) end
  local B = solidOf(P, K)
  local i
  if B.nfree > 0 then
    i = B.free[B.nfree]
    B.free[B.nfree] = nil
    B.nfree = B.nfree - 1
  else
    if P.solidMade >= M.SOLID_PER_FRAME then
      P.waits = P.waits + 1
      return nil
    end
    P.solidMade = P.solidMade + 1
    i = B.top + 1
    B.top = i
    B.objs[i] = solidMake(P, B)
  end
  local o = B.objs[i]
  colour = colour or P.white
  if B.c[i] ~= colour then
    B.c[i] = colour
    solidColour(P, o, colour)
  end
  solidPlace(o, x, y, z, dx, dy, pitch)
  o:setHidden(false)
  B.on[i], B.usedAt = true, P.frame
  B.live, P.solidLive = B.live + 1, P.solidLive + 1
  return B, i
end

-- the copy placed again (colour nil: as it was). setInstance leaves a hidden slot hidden, so a
-- copy that is already shown is enabled again: a step must not blink it off. pitch: a solid
-- copy's nose up (a batch's copy stands level).
function M.move(P, B, i, x, y, z, dx, dy, dz, colour, pitch)
  if B.static then
    local o = B.objs[i]
    if colour and B.c[i] ~= colour then
      B.c[i] = colour
      solidColour(P, o, colour)
    end
    solidPlace(o, x, y, z, dx, dy, pitch)
    return
  end
  if colour then B.c[i] = colour end
  place(P, B, i, x, y, z, dx, dy, dz)
  if B.on[i] then B.obj:setInstanceEnabled(i, true) end
end

-- the copy hidden and its slot free
function M.drop(P, B, i)
  if not B.on[i] then return end
  if B.static then
    B.objs[i]:setHidden(true)
    B.on[i] = nil
    B.nfree = B.nfree + 1
    B.free[B.nfree] = i
    B.live, P.solidLive, B.usedAt = B.live - 1, P.solidLive - 1, P.frame
    return
  end
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
  for _, K in pairs(P.kinds) do
    if K.primer then
      local primer = K.primer
      pcall(function() primer:delete() end)
      K.primer = nil
    end
  end
  for _, B in ipairs(P.solids) do
    for i = 1, B.top do
      local o = B.objs[i]
      if o then pcall(function() o:delete() end) end
    end
    B.kind.solid = nil
  end
  P.list, P.objects, P.live = {}, 0, 0
  P.solids, P.solidObjects, P.solidLive = {}, 0, 0
end

-- the direction of a +x shape's +y axis for heading yaw (radians about z)
function M.yAxis(yaw) return -math.sin(yaw), math.cos(yaw), 0 end

return M
