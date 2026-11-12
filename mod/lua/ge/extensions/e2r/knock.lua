-- Street furniture a vehicle knocks down (docs/KNOCKDOWN.md). No engine physics: the props are
-- items of the level's Forest; just before a vehicle reaches one, the item leaves the Forest and a
-- TSStatic of the same shape stands in its place (debris). When the vehicle touches it, the debris
-- gets the impulse of a collision of the two masses, the vehicle the opposite one (a velocity change
-- on its whole body), and Lua flies the debris as one rigid box: gravity, the ground under it, a
-- couple of bounces, tumbling, friction, a spring that lays it on its nearest face. Once still it
-- sleeps where it lies and costs nothing; it stays knocked until its tile is built again.
--   - Items are registered per tile (world.lua, when the Forest commits them) into a hash of CELL m
--     cells; a step looks only at the cells round each moving vehicle, so thousands of standing
--     props cost nothing while nothing drives past them.
--   - Debris has a hard cap (cap): the oldest one lying goes first (its prop disappears, it was far
--     behind), and at most maxFly fly at once (the oldest flier is laid down at once).
--   - KINDS is the table of what can be knocked, by the shape's file name: light ones fly, heavy ones
--     tip over and slow the vehicle. A shape not in it (trees, concrete bollards, poles, dumpsters,
--     bus stops) is solid and never registered.
-- The game calls go through `api` (M.gameApi in world.lua's glue), so earthng/test_knock.py runs this
-- in lupa. Numbers only in the per-frame path: no tables are made while debris flies or sleeps.
local M = {}

local sqrt, abs, floor, max, min = math.sqrt, math.abs, math.floor, math.max, math.min

M.CAP = 2000         -- debris live at most (flying and lying)
M.CELL = 8            -- m, side of a hash cell
M.LEAD = .25          -- s: an item a vehicle will touch within this long becomes debris
M.MISS_T = .6         -- s an armed debris waits past its predicted touch before it lies down untouched
-- No speed gate: a creeping car pushes, a fast one throws, one standing in a prop shoves it out.
M.V0 = 3              -- m/s closing speed at which a hit is half push, half throw: s = vn^2 / (vn^2 + V0^2)
M.ANCHOR = 4          -- a heavy prop at a crawl resists like (1 + ANCHOR) times its mass (it scrapes, digs in)
M.OUT_V = 1.2         -- m/s: a prop a vehicle stands in (spawned or teleported onto it) slides out with
M.STILL_V = .05       -- m/s: a vehicle slower than this is still: looked at once in STILL_EVERY steps
M.STILL_EVERY = 15
M.LOOK_MAX = 40       -- m: the look-ahead of a very fast vehicle (never under two steps of travel)
-- The look-ahead is reckoned with at most VN_MAX m/s and a STEP_MAX s step, and the cells swept round
-- a vehicle reach REACH_MAX m at most: a teleported car (a hand-off, a reset) reads thousands of m/s
-- for a frame, a hitch makes the step long, and together they swept a few km of cells in one step
-- (558 ms, central Kyiv with 400 flow cars, polish-02).
M.STEP_MAX, M.REACH_MAX = .25, 80
-- m/s: a vehicle seen for the first time (or after half a second) faster than this waits one step
-- before it touches anything, so a velocity its position does not yet bear out throws nothing
M.FRESH_V = 30
M.ESCAPE = .1         -- caught up in flight: sideways by this share of the vehicle's speed (a rounded front)
M.VN_MAX = 120        -- m/s: the closing speed a throw is computed with at most
M.ROOF = 1.8          -- m above a vehicle's position: debris higher than this flies over it
M.ARM_MAX = 6         -- swaps (Forest item -> debris) a step at most
M.RAY_EVERY = 3       -- steps between the wall rays of one flier
M.WALL_E, M.WALL_T = .2, .35   -- off a wall: the share of the speed into it bounced back, along it kept
M.G = 9.81
M.DV_MAX = 2.5        -- m/s: the most one prop changes a vehicle's velocity
M.FLY_MAX_T = 8       -- s a debris may fly before it is laid down where it is
M.SLEEP_V, M.SLEEP_W, M.SLEEP_T = .25, .5, .25
M.DRAG = {light = .012, heavy = .003}   -- quadratic air drag, 1/m (rho Cd A / 2m of a hollow bin ~0.01)
M.GROUND_E = .25      -- bounce of the ground
M.MU = .9             -- sliding friction on the ground (a tumbling box, not a sled)
M.IMPACT_LOSS = .3    -- share of the horizontal speed a hard landing (> 1 m/s down) takes
M.SETTLE_K, M.SETTLE_D = 30, 6   -- the spring that lays a box on its nearest face (1/s2, 1/s)
M.SETTLE_AFTER = .3   -- s after the hit before it acts (a heavy prop standing on the ground tips over first)

-- class: light (flies), heavy (tips over, short throw). mass kg; r plan radius m for the hit;
-- hx, hy, hz half extents of the box in the model's axes (the model's origin is the middle of its
-- base); e restitution of the hit; lift: the share of the hit speed thrown upwards; spin 1/s per m/s;
-- keep: the share of the throw a heavy one keeps (default 1).
-- Sizes from the installed DAE bounds (generator.lua fp, out/runtime-review/asset-bounds.jsonl);
-- heights and masses estimated.
local L, H = 'light', 'heavy'
M.KINDS = {
  ['garbage_bin_a.dae'] = {class = L, mass = 15, r = .36, hx = .25, hy = .25, hz = .5, e = 0.2, lift = .3, spin = .5},
  ['garbage_bin_b.dae'] = {class = L, mass = 15, r = .4, hx = .25, hy = .28, hz = .5, e = 0.2, lift = .3, spin = .5},
  ['italy_clutter_metal_bin.dae'] = {class = L, mass = 12, r = .25, hx = .17, hy = .17, hz = .45, e = 0.2, lift = .3, spin = .5},
  ['italy_clutter_metal_bin_small.dae'] = {class = L, mass = 6, r = .15, hx = .1, hy = .1, hz = .35, e = 0.25, lift = .35, spin = .6},
  ['clutter_city_bin_round.dae'] = {class = L, mass = 20, r = .36, hx = .35, hy = .35, hz = .45, e = 0.2, lift = .25, spin = .4},
  ['italy_clutter_big_dustbin.dae'] = {class = L, mass = 25, r = .4, hx = .35, hy = .35, hz = .55, e = 0.15, lift = .25, spin = .4},
  ['bollard_yellow.dae'] = {class = L, mass = 8, r = .2, hx = .15, hy = .15, hz = .5, e = 0.3, lift = .3, spin = .6},
  ['clutter_city_chalkboard_sign.dae'] = {class = L, mass = 8, r = .3, hx = .23, hy = .36, hz = .5, e = 0.2, lift = .35, spin = .6},
  ['clutter_city_wood_stool.dae'] = {class = L, mass = 5, r = .3, hx = .29, hy = .29, hz = .23, e = 0.25, lift = .4, spin = .7},
  ['clutter_city_wood_table_small.dae'] = {class = L, mass = 12, r = .45, hx = .29, hy = .44, hz = .38, e = 0.2, lift = .35, spin = .5},
  ['clutter_city_wood_table.dae'] = {class = L, mass = 25, r = .8, hx = .29, hy = .79, hz = .38, e = 0.15, lift = .3, spin = .4},
  ['clutter_barrels_red.dae'] = {class = L, mass = 15, r = .3, hx = .3, hy = .3, hz = .45, e = 0.25, lift = .3, spin = .5},
  ['clutter_barrels_white.dae'] = {class = L, mass = 15, r = .3, hx = .3, hy = .3, hz = .45, e = 0.25, lift = .3, spin = .5},
  ['hr_plasticbarrier.dae'] = {class = L, mass = 12, r = .75, hx = .74, hy = .27, hz = .5, e = 0.2, lift = .25, spin = .4},
  ['s_wheelbarrow.dae'] = {class = L, mass = 20, r = .9, hx = .92, hy = .39, hz = .35, e = 0.15, lift = .3, spin = .4},
  ['postbox_blue.dae'] = {class = L, mass = 40, r = .4, hx = .3, hy = .32, hz = .6, e = 0.1, lift = .2, spin = .35},
  ['clutter_city_bench_wood.dae'] = {class = H, mass = 60, r = 1, hx = 1, hy = .28, hz = .42, e = 0.1, lift = .12, spin = 0.38, keep = .6},
  ['clutter_city_bike_stand.dae'] = {class = H, mass = 45, r = 2.1, hx = 2.08, hy = .32, hz = .4, e = 0.1, lift = .08, spin = 0.3, keep = .6},
  ['planterbox.dae'] = {class = H, mass = 120, r = .6, hx = .46, hy = .46, hz = .4, e = 0.1, lift = .06, spin = 0.22, keep = .6},
  ['bollard_hoop_grey.dae'] = {class = H, mass = 25, r = .52, hx = .52, hy = .18, hz = .45, e = 0.1, lift = .1, spin = 0.45, keep = .6},
  ['bollard_hoop_red.dae'] = {class = H, mass = 25, r = .52, hx = .52, hy = .18, hz = .45, e = 0.1, lift = .1, spin = 0.45, keep = .6},
  ['hydrant1.dae'] = {class = H, mass = 90, r = .4, hx = .33, hy = .38, hz = .4, e = 0.1, lift = .08, spin = 0.3, keep = .6},
  ['s_wood_crate_closed.dae'] = {class = H, mass = 80, r = 1.5, hx = .79, hy = 1.5, hz = .5, e = 0.1, lift = .06, spin = 0.22, keep = .6},
  ['italy_clutter_dumpster.dae'] = {class = H, mass = 110, r = .8, hx = .78, hy = .41, hz = .6, e = 0.1, lift = .05, spin = 0.22, keep = .6},
  ['lamp1.dae'] = {class = H, mass = 140, r = .25, hx = .2, hy = .2, hz = 4, e = 0.1, lift = .03, spin = 0.18, keep = .6},
}
-- shapes known by the start of their name (the Italy traffic sign set: a post with a plate)
M.PREFIXES = {
  {'italy_traf_sign_', {class = L, mass = 22, r = .2, hx = .3, hy = .1, hz = 1.3, e = 0.1, lift = .15, spin = .3}},
}
-- What is solid on purpose, for the report and the doc (not used by the step): trees, poles,
-- concrete bollards, dumpsters, bus stops, and every shape not named above.
M.SOLID = {'trees', 'electric_pole_wood_old_01.dae', 'clutter_city_bollard_concrete.dae', 'ind_dumpster_full.dae',
  'ind_dumpster_empty.dae', 's_busstop_jri.dae'}

-- The paths the generator places these shapes at, for world.lua's load-time warm-up: a shape's first
-- TSStatic costs ~10 ms to create and ~26 ms in the next frame (p24b); later ones ~11 us and nothing.
-- Signs: the common ones only (a rarer sign's first knock pays that once).
local WCO, ECA = '/levels/west_coast_usa/art/shapes/objects/', '/levels/east_coast_usa/art/shapes/clutter/'
local GDC, ART = '/art/shapes/garage_and_dealership/Clutter/', '/art/shapes/objects/'
M.SHAPES = {
  WCO .. 'garbage_bin_a.dae', WCO .. 'garbage_bin_b.dae', WCO .. 'planterbox.dae', WCO .. 'bollard_hoop_grey.dae',
  WCO .. 'bollard_hoop_red.dae', WCO .. 'hydrant1.dae', WCO .. 'postbox_blue.dae',
  ART .. 'bollard_yellow.dae', ART .. 's_wood_crate_closed.dae', ART .. 's_wheelbarrow.dae', ART .. 'lamp1.dae',
  ECA .. 'clutter_city_bench_wood.dae', ECA .. 'clutter_city_bike_stand.dae', ECA .. 'clutter_city_chalkboard_sign.dae',
  ECA .. 'clutter_city_wood_stool.dae', ECA .. 'clutter_city_wood_table_small.dae', ECA .. 'clutter_city_wood_table.dae',
  GDC .. 'clutter_city_bin_round.dae', GDC .. 'italy_clutter_metal_bin.DAE', GDC .. 'italy_clutter_metal_bin_small.DAE',
  GDC .. 'italy_clutter_big_dustbin.DAE', GDC .. 'italy_clutter_dumpster.DAE', GDC .. 'clutter_barrels_red.dae',
  GDC .. 'clutter_barrels_white.dae', GDC .. 'hr_plasticbarrier.DAE',
  GDC .. 'italy_traf_sign_give_way.dae', GDC .. 'italy_traf_sign_stop.dae', GDC .. 'italy_traf_sign_zebra.dae',
  GDC .. 'italy_traf_sign_priorityroad.dae',
}

-- appends to list the knock shapes it lacks (exists: FS:fileExists or nil)
function M.warmShapes(list, exists)
  local have = {}
  for _, s in ipairs(list) do have[s] = true end
  for _, s in ipairs(M.SHAPES) do
    if not have[s] and (not exists or exists(s)) then list[#list + 1] = s; have[s] = true end
  end
  return list
end

-- the spec of a shape path, or nil (solid)
function M.kindOf(shape)
  if type(shape) ~= 'string' then return nil end
  local base = shape:match('([^/]+)$')
  if not base then return nil end
  base = base:lower()
  local k = M.KINDS[base]
  if k then return k end
  for _, p in ipairs(M.PREFIXES) do
    if base:sub(1, #p[1]) == p[1] then return p[2] end
  end
end

-- item states
local GONE, STAND, DEBRIS = 0, 1, 2
-- debris states
local IDLE, ARMED, FLY, LIE = 0, 1, 2, 3
M.STAND, M.DEBRIS, M.GONE = STAND, DEBRIS, GONE
M.IDLE, M.ARMED, M.FLY, M.LIE = IDLE, ARMED, FLY, LIE

function M.new(opts)
  opts = opts or {}
  local K = {
    enabled = opts.enabled ~= false, cap = opts.cap or M.CAP, maxFly = opts.maxFly or 48,
    cells = {}, tiles = {}, n = 0, free = {}, nfree = 0,
    -- items: parallel arrays by id
    X = {}, Y = {}, Z = {}, QZ = {}, QW = {}, SC = {}, SPEC = {}, SHAPE = {}, STATE = {}, TILE = {}, CELL = {}, SLOT = {},
    -- debris slots: parallel arrays by slot
    dn = 0, dfree = {}, ndfree = 0, nfly = 0,
    DI = {}, DO = {}, DS = {}, DT = {}, DH = {}, DQ = {}, HIT = {},
    PX = {}, PY = {}, PZ = {}, VX = {}, VY = {}, VZ = {}, QX = {}, QY = {}, DQZ = {}, DQW = {}, WX = {}, WY = {}, WZ = {},
    -- a wall ahead of a flier (from its last ray): m left to it, the wall's normal
    WD = {}, WNX = {}, WNY = {}, frame = 0, DG = {}, arms = 0,
    -- each vehicle's place at the last step (by vehicle id), to check its velocity
    LX = {}, LY = {}, LT = {},
    -- ms of this step in the game's calls (arm: hide + take, ray, ground), and the most of each
    part = {arm = 0, ray = 0, ground = 0}, partMax = {arm = 0, ray = 0, ground = 0},
    -- the slots flying or armed (a list with a count) and every live slot oldest first (a ring)
    act = {}, nact = 0, ring = {}, ringBorn = {}, rhead = 1, rtail = 0, live = 0, born = {}, items = 0,
    stats = {registered = 0, knocked = 0, recycled = 0, missed = 0, ms = 0, msMax = 0, flying = 0, lying = 0,
             walls = 0, rays = 0, contacts = 0},
  }
  return K
end

local function cellKey(x, y)
  return floor(x / M.CELL) * 1048576 + floor(y / M.CELL)
end
M.cellKey = cellKey

local function cellAdd(K, key, id)
  local c = K.cells[key]
  if not c then c = {n = 0}; K.cells[key] = c end
  c.n = c.n + 1
  c[c.n] = id
  K.CELL[id] = key
end

local function cellRemove(K, id)
  local key = K.CELL[id]
  local c = key and K.cells[key]
  if not c then return end
  for k = 1, c.n do
    if c[k] == id then
      c[k] = c[c.n]
      c[c.n] = nil
      c.n = c.n - 1
      break
    end
  end
  if c.n == 0 then K.cells[key] = nil end
  K.CELL[id] = nil
end

-- One prop of a tile: shape path, position, yaw quaternion parts (qz, qw), scale. Returns its id or
-- nil (a solid shape).
function M.register(K, tileKey, shape, x, y, z, qz, qw, scale)
  local spec = M.kindOf(shape)
  if not spec then return nil end
  local id
  if K.nfree > 0 then
    id = K.free[K.nfree]
    K.free[K.nfree] = nil
    K.nfree = K.nfree - 1
  else
    K.n = K.n + 1
    id = K.n
  end
  K.X[id], K.Y[id], K.Z[id], K.QZ[id], K.QW[id], K.SC[id] = x, y, z, qz or 0, qw or 1, scale or 1
  K.SPEC[id], K.SHAPE[id], K.STATE[id], K.TILE[id], K.SLOT[id] = spec, shape, STAND, tileKey, nil
  cellAdd(K, cellKey(x, y), id)
  local list = K.tiles[tileKey]
  if not list then list = {n = 0}; K.tiles[tileKey] = list end
  list.n = list.n + 1
  list[list.n] = id
  K.stats.registered = K.stats.registered + 1
  K.items = K.items + 1
  return id
end

-- --- debris slots ---------------------------------------------------------------------------------
local function actAdd(K, s)
  K.nact = K.nact + 1
  K.act[K.nact] = s
end

local function actRemove(K, s)
  for k = 1, K.nact do
    if K.act[k] == s then
      K.act[k] = K.act[K.nact]
      K.act[K.nact] = nil
      K.nact = K.nact - 1
      return
    end
  end
end

-- the slot leaves the world: its object back to the glue's pool, its item gone (or freed)
local function freeSlot(K, s, api)
  local st = K.DS[s]
  if st == ARMED or st == FLY then actRemove(K, s) end
  if st == FLY then K.nfly = K.nfly - 1 end
  if K.DO[s] then api.drop(K.DO[s], K.DH[s]) end
  local id = K.DI[s]
  if id and K.SLOT[id] == s then K.SLOT[id] = nil end
  K.DO[s], K.DI[s], K.DS[s], K.DH[s] = nil, nil, IDLE, nil
  K.born[s] = nil
  K.live = K.live - 1
  K.ndfree = K.ndfree + 1
  K.dfree[K.ndfree] = s
end

-- the oldest live slot that is lying (recycled for a new one); entries of freed or reused slots are
-- dropped from the front as they are met
local function oldestLying(K)
  local h = K.rhead
  while h <= K.rtail do
    local s = K.ring[h]
    local valid = s and K.DS[s] ~= IDLE and K.born[s] == K.ringBorn[h]
    if valid and K.DS[s] == LIE then return s, h end
    if not valid and h == K.rhead then
      K.ring[h], K.ringBorn[h] = nil, nil
      K.rhead = h + 1
    end
    h = h + 1
  end
end

local serial = 0
local function newSlot(K, api)
  if K.live >= K.cap then
    local s, h = oldestLying(K)
    if not s then return nil end
    local id = K.DI[s]
    -- its prop is gone until the tile is built again
    if id then
      K.STATE[id] = GONE
      cellRemove(K, id)
    end
    K.ring[h], K.ringBorn[h] = nil, nil
    freeSlot(K, s, api)
    K.stats.recycled = K.stats.recycled + 1
  end
  local s
  if K.ndfree > 0 then
    s = K.dfree[K.ndfree]
    K.dfree[K.ndfree] = nil
    K.ndfree = K.ndfree - 1
  else
    K.dn = K.dn + 1
    s = K.dn
  end
  K.live = K.live + 1
  serial = serial + 1
  K.born[s] = serial
  K.rtail = K.rtail + 1
  K.ring[K.rtail], K.ringBorn[K.rtail] = s, serial
  return s
end

-- the rotation's z row from a quaternion (how far each body axis points up)
local function zrow(x, y, z, w)
  return 2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)
end

-- writes the slot's object at its pose: the model's origin is the middle of its base, hz below the centre
local function show(K, s, api)
  local spec = K.SPEC[K.DI[s]]
  local x, y, z, w = K.QX[s], K.QY[s], K.DQZ[s], K.DQW[s]
  local sc = K.SC[K.DI[s]]
  local zx, zy, zz = zrow(x, y, z, w)
  -- body z axis in the world: the column 3 of the rotation
  local cx, cy, cz = 2 * (x * z + w * y), 2 * (y * z - w * x), zz
  local h = spec.hz * sc
  api.place(K.DO[s], K.PX[s] - cx * h, K.PY[s] - cy * h, K.PZ[s] - cz * h, x, y, z, w)
  return zx, zy
end

-- a standing item becomes debris: the Forest item goes, a TSStatic stands where it stood
local function arm(K, id, h, hit, now, api)
  -- at most ARM_MAX swaps a step (hide + take cost ~30 us each): the rest the next step, they are
  -- still ahead, and one already touched is pushed out of the box when it comes
  if K.arms >= M.ARM_MAX then return false end
  K.arms = K.arms + 1
  local s = newSlot(K, api)
  if not s then return false end
  local spec, sc = K.SPEC[id], K.SC[id]
  local t0 = api.clock and api.clock()
  local hidden = api.hide(id, K.SHAPE[id], K.X[id], K.Y[id], K.Z[id])
  if t0 then K.part.arm = K.part.arm + api.clock() - t0 end
  if not hidden then
    -- the item could not leave the Forest (not committed yet, or retiring): leave it standing
    K.born[s] = nil; K.live = K.live - 1; K.ndfree = K.ndfree + 1; K.dfree[K.ndfree] = s; K.DS[s] = IDLE
    return false
  end
  local t1 = api.clock and api.clock()
  local obj = api.take(K.SHAPE[id], sc)
  if t1 then K.part.arm = K.part.arm + api.clock() - t1 end
  K.DO[s], K.DH[s], K.DI[s], K.DS[s], K.DT[s], K.DQ[s] = obj, K.SHAPE[id], id, ARMED, now + hit, h.id
  K.PX[s], K.PY[s], K.PZ[s] = K.X[id], K.Y[id], K.Z[id] + spec.hz * sc
  K.VX[s], K.VY[s], K.VZ[s] = 0, 0, 0
  K.QX[s], K.QY[s], K.DQZ[s], K.DQW[s] = 0, 0, K.QZ[id], K.QW[id]
  K.WX[s], K.WY[s], K.WZ[s] = 0, 0, 0
  K.SLOT[id], K.STATE[id] = s, DEBRIS
  if obj then show(K, s, api) end
  actAdd(K, s)
  K.stats.knocked = K.stats.knocked + 1
  local by = K.stats.armBy
  if h.id and by then by[h.id] = (by[h.id] or 0) + 1 end
  return true
end

-- When a circle at (px, py) of radius r first touches a box moving (bvx, bvy) within T s: the box at
-- (bx, by), unit forward (fx, fy), half length hl, half width hw. Returns t and the axis that met
-- first (1 forward, 2 side) or nil.
local function sweep(px, py, r, bx, by, fx, fy, hl, hw, bvx, bvy, T)
  local dx, dy = px - bx, py - by
  local u, w = dx * fx + dy * fy, -dx * fy + dy * fx
  local du, dw = -(bvx * fx + bvy * fy), -(-bvx * fy + bvy * fx)
  local t0, t1, axis = 0, T, 0
  local hu, hv = hl + r, hw + r
  if abs(du) < 1e-9 then
    if abs(u) > hu then return nil end
  else
    local ta, tb = (-hu - u) / du, (hu - u) / du
    if ta > tb then ta, tb = tb, ta end
    if ta > t0 then t0, axis = ta, 1 end
    if tb < t1 then t1 = tb end
    if t0 > t1 then return nil end
  end
  if abs(dw) < 1e-9 then
    if abs(w) > hv then return nil end
  else
    local ta, tb = (-hv - w) / dw, (hv - w) / dw
    if ta > tb then ta, tb = tb, ta end
    if ta > t0 then t0, axis = ta, 2 end
    if tb < t1 then t1 = tb end
    if t0 > t1 then return nil end
  end
  return t0, axis
end
M.sweep = sweep

-- The touch of hitter h and debris s: an impulse along the contact normal (the face of the vehicle's
-- box that met it), only while they close; the vehicle's opposite share is summed in h.dvx, h.dvy
-- (M.step applies it once a step). One law from a crawl to any speed, no threshold: with
-- s = vn^2 / (vn^2 + V0^2) the restitution, lift, spin, spread and a heavy one's give (keep) grow
-- with s, and a heavy one's anchoring (ANCHOR) fades with it. At a crawl the prop goes with the
-- bumper (pushed, it scrapes: a car pushing a planter keeps paying for its friction every touch); fast,
-- it is thrown. A prop inside the box (a vehicle spawned on it) is first moved out to its face.
local function contact(K, s, h, fresh)
  local id = K.DI[s]
  local spec, sc = K.SPEC[id], K.SC[id]
  local dx, dy = K.PX[s] - h.x, K.PY[s] - h.y
  local u, w = dx * h.fx + dy * h.fy, -dx * h.fy + dy * h.fx
  local r = spec.r * sc
  local nx, ny, depth, off
  if abs(u) / max(h.hl, .1) >= abs(w) / max(h.hw, .1) then
    local sg = u >= 0 and 1 or -1
    nx, ny, depth = h.fx * sg, h.fy * sg, h.hl + r - abs(u)
    -- off the middle of the bumper it slides off sideways (a rounded front, not a dozer blade)
    off = w * sg / (h.hw + r)
  else
    local sg = w >= 0 and 1 or -1
    nx, ny, depth = -h.fy * sg, h.fx * sg, h.hw + r - abs(w)
    off = -u * sg / (h.hl + r)
  end
  local inside = depth > 0 and abs(u) < h.hl + r and abs(w) < h.hw + r
  if inside then
    K.PX[s], K.PY[s] = K.PX[s] + nx * depth, K.PY[s] + ny * depth
  end
  local rvx, rvy = h.vx - K.VX[s], h.vy - K.VY[s]
  local vn = rvx * nx + rvy * ny
  K.WD[s] = nil
  K.HIT[s] = K.now or 0
  if vn <= 0 then
    -- not closing: one standing in a still vehicle slides out of it, else nothing
    if inside then
      local out = M.OUT_V + vn
      if out > 0 then K.VX[s], K.VY[s] = K.VX[s] + nx * out, K.VY[s] + ny * out end
    end
    return 0
  end
  -- (a teleport reads as one step of a huge velocity: the throw is held to a real car's)
  if vn > M.VN_MAX then vn = M.VN_MAX end
  local v2 = vn * vn
  local q = v2 / (v2 + M.V0 * M.V0)
  local heavy = spec.class ~= 'light'
  local m = spec.mass
  local me = heavy and m * (1 + M.ANCHOR * (1 - q)) or m
  local M_ = h.mass or 1500
  local j = (1 + spec.e * q) * M_ * me / (M_ + me) * vn
  -- a deterministic spread per item (no random numbers)
  local hash = ((id * 2654435761) % 1000) / 1000 - .5
  local tx, ty = -ny, nx
  local along = rvx * tx + rvy * ty   -- the vehicle's slide along the face drags the prop a little
  -- keep: the share of the first throw a heavy prop keeps (the rest bends it, as an anchored bench
  -- would); pushed slowly it keeps it all and goes with the bumper
  local gain = j / me * (fresh and 1 - (1 - (spec.keep or 1)) * q or 1)
  -- caught up again in flight (it was slower than the car): it goes off to a side, not ahead of the
  -- bumper all the way
  local side = along * .2 * q + hash * vn * .15 * q + vn * .3 * off
  if not fresh then
    local o = off + (hash >= 0 and .3 or -.3)
    side = side + (o >= 0 and 1 or -1) * M.ESCAPE * max(0, h.vx * nx + h.vy * ny)
  end
  K.VX[s] = K.VX[s] + nx * gain + tx * side
  K.VY[s] = K.VY[s] + ny * gain + ty * side
  K.VZ[s] = max(K.VZ[s], spec.lift * vn * q)
  -- tumbling: the top tips away from the vehicle (axis up x n), light ones spin about up as well
  local rate = spec.spin * vn * q
  K.WX[s], K.WY[s] = K.WX[s] - ny * rate, K.WY[s] + nx * rate
  K.WZ[s] = K.WZ[s] + (heavy and hash * rate * .5 or hash * rate * 2)
  -- the vehicle: the opposite impulse
  local dv = j / M_
  h.dvx, h.dvy = (h.dvx or 0) - nx * dv, (h.dvy or 0) - ny * dv
  K.stats.contacts = K.stats.contacts + 1
  -- by vehicle (the glue names them in its report): who touches props
  local by = K.stats.touchBy
  if h.id and by then by[h.id] = (by[h.id] or 0) + 1 end
  return dv
end
M.contact = contact

local lieDown
local function launch(K, s, h, api)
  -- too many in the air: the one flying longest lies down where it is
  if K.nfly >= K.maxFly then
    local oldest, t = nil, -1
    for q = 1, K.nact do
      local o = K.act[q]
      if K.DS[o] == FLY and K.DT[o] > t then oldest, t = o, K.DT[o] end
    end
    if oldest then lieDown(K, oldest, api) end
  end
  contact(K, s, h, true)
  K.DS[s], K.DT[s], K.DQ[s], K.DG[s] = FLY, 0, 0, nil
  K.nfly = K.nfly + 1
end

function lieDown(K, s, api)
  actRemove(K, s)
  if K.DS[s] == FLY then K.nfly = K.nfly - 1 end
  K.DS[s] = LIE
  K.WD[s] = nil
  local id = K.DI[s]
  K.VX[s], K.VY[s], K.VZ[s], K.WX[s], K.WY[s], K.WZ[s] = 0, 0, 0, 0, 0, 0
  -- where it lies: the hash moves with it, so a vehicle can knock it again
  local x, y = K.PX[s], K.PY[s]
  K.X[id], K.Y[id] = x, y
  local key = cellKey(x, y)
  if key ~= K.CELL[id] then
    cellRemove(K, id)
    cellAdd(K, key, id)
  end
end

-- the box flies one step
local function fly(K, s, dt, api)
  local id = K.DI[s]
  local spec, sc = K.SPEC[id], K.SC[id]
  local vx, vy, vz = K.VX[s], K.VY[s], K.VZ[s] - M.G * dt
  -- air drag ~ v^2: a light hollow prop thrown at 40 m/s slows within a few tens of metres
  local sp2 = vx * vx + vy * vy + vz * vz
  if sp2 > 1 then
    local k = 1 / (1 + (spec.drag or M.DRAG[spec.class] or 0) * sqrt(sp2) * dt)
    vx, vy, vz = vx * k, vy * k, vz * k
  end
  local ox, oy = K.PX[s], K.PY[s]
  local px, py, pz = ox + vx * dt, oy + vy * dt, K.PZ[s] + vz * dt
  local wx, wy, wz = K.WX[s], K.WY[s], K.WZ[s]
  -- walls: one static ray along the flight every RAY_EVERY steps, as long as the next ones' travel;
  -- a wall it meets is kept (how far, its normal) until the box reaches it, then the box bounces off
  -- it, slowed hard, and drops (two more rays, only then, give the wall's direction)
  local hs = sqrt(vx * vx + vy * vy)
  if api.ray and hs > .5 then
    local hxy = max(spec.hx, spec.hy) * sc
    local wd = K.WD[s]
    -- (every step while a vehicle has just touched it: one pushing it can carry it into a wall)
    if not wd and ((K.frame + s) % M.RAY_EVERY == 0 or (K.now or 0) - (K.HIT[s] or -1e9) < .5) then
      local ux, uy = vx / hs, vy / hs
      local len = hs * dt * (M.RAY_EVERY + 1) + hxy
      K.stats.rays = K.stats.rays + 1
      local t0 = api.clock and api.clock()
      local d = api.ray(ox, oy, K.PZ[s], ux, uy, len)
      if t0 then K.part.ray = K.part.ray + api.clock() - t0 end
      -- a rising ground (a ramp, an embankment, a hill) meets the ray too: no wall when the ground
      -- just before the hit is up at the ray's height (a wall has the road at its foot)
      if d and d < len then
        local gh = api.ground(ox + ux * (d - .1), oy + uy * (d - .1), K.PZ[s])
        if gh and gh > K.PZ[s] - .25 then d = nil end
      end
      if d and d < len then
        -- the wall's line from two rays 20 degrees either side; a corner or a miss: head on
        local c, sn = .94, .342
        local la, lb = len * 1.6, len * 1.6
        local da = api.ray(ox, oy, K.PZ[s], ux * c - uy * sn, ux * sn + uy * c, la)
        local db = api.ray(ox, oy, K.PZ[s], ux * c + uy * sn, -ux * sn + uy * c, lb)
        local wnx, wny = -ux, -uy
        if da and db and da < la and db < lb then
          local ax, ay = (ux * c - uy * sn) * da, (ux * sn + uy * c) * da
          local bx, by = (ux * c + uy * sn) * db, (-ux * sn + uy * c) * db
          local tx, ty = bx - ax, by - ay
          local tl = sqrt(tx * tx + ty * ty)
          if tl > 1e-3 then
            wnx, wny = -ty / tl, tx / tl
            if wnx * ux + wny * uy > 0 then wnx, wny = -wnx, -wny end
          end
        end
        -- the distance along the flight at which the box's side meets the wall
        local cosi = -(wnx * ux + wny * uy)
        wd = (d * cosi - hxy) / max(cosi, .2)
        if wd < 0 then wd = 0 end
        K.WD[s], K.WNX[s], K.WNY[s] = wd, wnx, wny
      end
    end
    if wd then
      local stepLen = hs * dt
      if stepLen >= wd then
        local ux, uy = vx / hs, vy / hs
        px, py = ox + ux * wd, oy + uy * wd
        local nx, ny = K.WNX[s], K.WNY[s]
        local vn = vx * nx + vy * ny
        if vn < 0 then
          local tvx, tvy = vx - vn * nx, vy - vn * ny
          vx, vy = tvx * M.WALL_T - vn * M.WALL_E * nx, tvy * M.WALL_T - vn * M.WALL_E * ny
          if vz > 0 then vz = vz * M.WALL_T end
          wx, wy, wz = wx * .3, wy * .3, wz * .3
          K.stats.walls = K.stats.walls + 1
        end
        K.WD[s] = nil
      else
        K.WD[s] = wd - stepLen
      end
    end
  end
  -- q += dt/2 * (0, w) * q
  local qx, qy, qz, qw = K.QX[s], K.QY[s], K.DQZ[s], K.DQW[s]
  local hdt = dt * .5
  local nx = qx + hdt * (wx * qw + wy * qz - wz * qy)
  local ny = qy + hdt * (wy * qw + wz * qx - wx * qz)
  local nz = qz + hdt * (wz * qw + wx * qy - wy * qx)
  local nw = qw - hdt * (wx * qx + wy * qy + wz * qz)
  local l = sqrt(nx * nx + ny * ny + nz * nz + nw * nw)
  qx, qy, qz, qw = nx / l, ny / l, nz / l, nw / l
  -- how far the box reaches below its centre
  local zx, zy, zz = zrow(qx, qy, qz, qw)
  local hx, hy, hz = spec.hx * sc, spec.hy * sc, spec.hz * sc
  local ez = abs(zx) * hx + abs(zy) * hy + abs(zz) * hz
  -- the ground: asked every step near it, every other step while the box is well above the last
  -- ground it found (half a metre or more)
  local g = K.DG[s]
  if not g or pz - ez < g + .5 or (K.frame + s) % 2 == 0 then
    local t0 = api.clock and api.clock()
    g = api.ground(px, py, pz)
    if t0 then K.part.ground = K.part.ground + api.clock() - t0 end
    K.DG[s] = g
  end
  local touching = false
  if g and pz - ez < g then
    touching = true
    pz = g + ez
    if vz < -1 then
      vx, vy = vx * (1 - M.IMPACT_LOSS), vy * (1 - M.IMPACT_LOSS)
    end
    -- a bounce under 0.8 m/s dies; a box lifted by a hit (vz up already) leaves the ground as it is
    if vz < 0 then
      vz = -vz * M.GROUND_E
      if vz < .8 then vz = 0 end
    end
    -- sliding friction
    local sp = sqrt(vx * vx + vy * vy)
    if sp > 1e-6 then
      local k = max(0, sp - M.MU * M.G * dt) / sp
      vx, vy = vx * k, vy * k
    end
    -- the body axis pointing most nearly up or down, weighed by how thin the box is along it (a bench
    -- lies on its seat or back, not on its end), turns vertical: a spring towards it, damped
    local ax, ay, az
    -- world directions of the body axes: rows of R transposed; the z row gives their up components
    local ux, uy, uz = zx, zy, zz
    local bx, by, bz, best = 0, 0, 0, 0
    local sx, sy, sz = abs(ux) / hx, abs(uy) / hy, abs(uz) / hz
    -- a long box never comes to rest on its end (a knocked bench, bin or post lies down)
    local hmax, hmin = max(hx, hy, hz), min(hx, hy, hz)
    if hmax > 1.5 * hmin then
      if hx == hmax then sx = -1 elseif hy == hmax then sy = -1 else sz = -1 end
    end
    if sx >= sy and sx >= sz then
      local sg = ux > 0 and 1 or -1
      -- body x in the world: column 1 of R
      bx, by, bz, best = (1 - 2 * (qy * qy + qz * qz)) * sg, 2 * (qx * qy + qw * qz) * sg, zx * sg, abs(ux)
    elseif sy >= sz then
      local sg = uy > 0 and 1 or -1
      bx, by, bz, best = 2 * (qx * qy - qw * qz) * sg, (1 - 2 * (qx * qx + qz * qz)) * sg, zy * sg, abs(uy)
    else
      local sg = uz > 0 and 1 or -1
      bx, by, bz, best = 2 * (qx * qz + qw * qy) * sg, 2 * (qy * qz - qw * qx) * sg, zz * sg, abs(uz)
    end
    -- torque turning (bx, by, bz) to straight up: axis b x up = (by, -bx, 0)
    ax, ay, az = by, -bx, 0
    if K.DT[s] > M.SETTLE_AFTER then
      wx = wx + (ax * M.SETTLE_K - wx * M.SETTLE_D) * dt
      wy = wy + (ay * M.SETTLE_K - wy * M.SETTLE_D) * dt
      wz = wz - wz * M.SETTLE_D * dt
    end
    local _ = best
  end
  K.PX[s], K.PY[s], K.PZ[s], K.VX[s], K.VY[s], K.VZ[s] = px, py, pz, vx, vy, vz
  K.QX[s], K.QY[s], K.DQZ[s], K.DQW[s], K.WX[s], K.WY[s], K.WZ[s] = qx, qy, qz, qw, wx, wy, wz
  K.DT[s] = K.DT[s] + dt
  -- (a box that has all but stopped is not placed again: setPosRot is the dearest call here)
  if K.DO[s] and ((px - ox) ^ 2 + (py - oy) ^ 2 + vz * vz * dt * dt > 1e-6 or wx * wx + wy * wy + wz * wz > .01) then
    show(K, s, api)
  end
  local v2, w2 = vx * vx + vy * vy + vz * vz, wx * wx + wy * wy + wz * wz
  if touching and v2 < M.SLEEP_V * M.SLEEP_V and w2 < M.SLEEP_W * M.SLEEP_W then
    K.DQ[s] = (K.DQ[s] or 0) + dt
  else
    K.DQ[s] = 0
  end
  if K.DQ[s] >= M.SLEEP_T or K.DT[s] > M.FLY_MAX_T then lieDown(K, s, api) end
end

-- hitter records: {id, x, y, vx, vy, fx, fy, hl, hw, mass, z} (box centre, velocity, unit forward,
-- half length and width, kg, the position's height or nil); n of them are used. The step writes
-- dvx, dvy into them (its own scratch).
function M.step(K, hitters, n, now, dt, api)
  if not K.enabled then return end
  local timer = api.clock and api.clock()
  K.now = now
  local part = K.part
  part.arm, part.ray, part.ground = 0, 0, 0
  K.arms = 0
  -- a velocity the position does not bear out is not used: a car the script AI takes over reads
  -- tens of m/s for a frame or two standing still (46 m/s on a covet, knock_row.lua), and that would
  -- throw props 40 m round it. Each vehicle's last place (by id) gives how fast it really went; the
  -- step uses that (h.vx, h.vy put back at the end: the records are the caller's).
  local LX, LY, LT = K.LX, K.LY, K.LT
  for i = 1, n do
    local h = hitters[i]
    local id = h.id
    if id then
      local lt = LT[id]
      local sp2 = h.vx * h.vx + h.vy * h.vy
      h.ovx, h.ovy = h.vx, h.vy
      h.fresh = nil
      if not (lt and now - lt <= .5 and now > lt) then
        if sp2 > M.FRESH_V * M.FRESH_V then
          h.fresh = true
          K.stats.distrusted = (K.stats.distrusted or 0) + 1
        end
      else
        local dx, dy = h.x - LX[id], h.y - LY[id]
        local pv = sqrt(dx * dx + dy * dy) / (now - lt)
        if sp2 > (2 * pv + 1) ^ 2 then
          local k = (pv + .5) / sqrt(sp2)
          h.vx, h.vy = h.vx * k, h.vy * k
          K.stats.distrusted = (K.stats.distrusted or 0) + 1
        end
      end
      LX[id], LY[id], LT[id] = h.x, h.y, now
    end
  end
  local lead = M.LEAD
  local tp = api.clock and api.clock()
  part.p0 = tp and tp - timer or 0
  -- 1. armed debris: launched by the first box touching it, or lying down untouched
  local k = 1
  while k <= K.nact do
    local s = K.act[k]
    if K.DS[s] == ARMED then
      local id = K.DI[s]
      local r = K.SPEC[id].r * K.SC[id]
      local hit
      for i = 1, n do
        local h = hitters[i]
        if not h.fresh and sweep(K.PX[s], K.PY[s], r, h.x, h.y, h.fx, h.fy, h.hl, h.hw, h.vx, h.vy, dt) then hit = h; break end
      end
      if hit then
        launch(K, s, hit, api)
        k = k + 1
      elseif now > K.DT[s] + M.MISS_T then
        K.stats.missed = K.stats.missed + 1
        lieDown(K, s, api)   -- stands as it stood, a TSStatic now (removes s from act)
      else
        k = k + 1
      end
    else
      k = k + 1
    end
  end
  if tp then local t = api.clock(); part.p1, tp = t - tp, t end
  -- 2. the fliers: a vehicle catching one up (a pushed planter, a bin sliding ahead) touches it again
  -- every step it closes on it, then it flies a step
  k = 1
  while k <= K.nact do
    local s = K.act[k]
    if K.DS[s] == FLY then
      local id = K.DI[s]
      local spec, sc = K.SPEC[id], K.SC[id]
      local r = spec.r * sc
      local low = K.PZ[s] - max(spec.hx, spec.hy, spec.hz) * sc
      local px, py, pvx, pvy = K.PX[s], K.PY[s], K.VX[s], K.VY[s]
      for i = 1, n do
        local h = hitters[i]
        local rvx, rvy = h.vx - pvx, h.vy - pvy
        local dx, dy = px - h.x, py - h.y
        local rr = h.hl + h.hw + r + (abs(rvx) + abs(rvy)) * dt + .5
        if not h.fresh and dx * dx + dy * dy < rr * rr and not (h.z and low > h.z + M.ROOF)
           and sweep(px, py, r, h.x, h.y, h.fx, h.fy, h.hl, h.hw, rvx, rvy, dt) then
          contact(K, s, h)
          px, py, pvx, pvy = K.PX[s], K.PY[s], K.VX[s], K.VY[s]
        end
      end
      fly(K, s, dt, api)
      if K.act[k] == s then k = k + 1 end
    else
      k = k + 1
    end
  end
  if tp then local t = api.clock(); part.p2, tp = t - tp, t end
  -- 3. items about to be touched. Any vehicle that moves, at any speed: the look-ahead grows with the
  -- speed (LEAD s of travel, never less than two steps), and every touch is a continuous sweep, so
  -- nothing is jumped over. A still one is looked at once in STILL_EVERY steps (staggered by id) for
  -- a prop it stands in; a vehicle the glue does not list (asleep, far) costs nothing.
  local cell = M.CELL
  K.frame = K.frame + 1
  local frame = K.frame
  for i = 1, n do
    local h = hitters[i]
    local sp = sqrt(h.vx * h.vx + h.vy * h.vy)
    local still = sp < M.STILL_V
    if not h.fresh and (not still or (frame + (h.id or i)) % M.STILL_EVERY == 0) then
      local spl, dtl = min(sp, M.VN_MAX), min(dt, M.STEP_MAX)
      local look = still and 0 or min(spl * max(lead, 2 * dtl), max(M.LOOK_MAX, 2 * spl * dtl))
      local T = still and 0 or look / sp
      local reach = min(sqrt(h.hl * h.hl + h.hw * h.hw) + look + 2.5, M.REACH_MAX)
      local cx0, cx1 = floor((h.x - reach) / cell), floor((h.x + reach) / cell)
      local cy0, cy1 = floor((h.y - reach) / cell), floor((h.y + reach) / cell)
      for cx = cx0, cx1 do
        for cy = cy0, cy1 do
          local c = K.cells[cx * 1048576 + cy]
          if c then
            local j = 1
            while j <= c.n do
              local id = c[j]
              local st = K.STATE[id]
              local r = K.SPEC[id].r * K.SC[id]
              local t = sweep(K.X[id], K.Y[id], r, h.x, h.y, h.fx, h.fy, h.hl, h.hw, h.vx, h.vy, T)
              if t then
                if st == STAND then
                  arm(K, id, h, t, now, api)
                elseif st == DEBRIS then
                  local s = K.SLOT[id]
                  if s and K.DS[s] == LIE then
                    -- a lying one is struck again: no swap, just armed where it lies
                    K.DS[s], K.DT[s], K.DQ[s] = ARMED, now + t, h.id
                    actAdd(K, s)
                  end
                end
              end
              -- cellRemove inside lieDown may reorder this cell only for debris, never during this loop
              j = j + 1
            end
          end
        end
      end
    end
  end
  if tp then local t = api.clock(); part.p3, tp = t - tp, t end
  -- 4. each vehicle's share of this step's touches, once, capped
  for i = 1, n do
    local h = hitters[i]
    if h.ovx then h.vx, h.vy = h.ovx, h.ovy end
    local dvx, dvy = h.dvx, h.dvy
    if dvx and (dvx ~= 0 or dvy ~= 0) then
      local dv = sqrt(dvx * dvx + dvy * dvy)
      if dv > M.DV_MAX then dvx, dvy, dv = dvx * M.DV_MAX / dv, dvy * M.DV_MAX / dv, M.DV_MAX end
      if dv > .002 then api.push(h.id, dvx, dvy, 0) end
      if dv > (K.stats.dvMax or 0) then K.stats.dvMax = dv end
      h.dvx, h.dvy = 0, 0
    end
  end
  local st = K.stats
  st.flying, st.lying, st.active = K.nfly, K.live - K.nact, K.live
  if timer then
    local ms = api.clock() - timer
    st.ms = ms
    if ms > st.msMax then
      st.msMax = ms
      -- where the worst step went (the report): swaps, wall rays, ground reads, what was moving
      st.worst = {ms = ms, arm = part.arm, ray = part.ray, ground = part.ground, arms = K.arms, act = K.nact,
        fly = K.nfly, hitters = n, t = now, p0 = part.p0, p1 = part.p1, p2 = part.p2, p3 = part.p3,
        p4 = tp and api.clock() - tp}
    end
    local pm = K.partMax
    if part.arm > pm.arm then pm.arm = part.arm end
    if part.ray > pm.ray then pm.ray = part.ray end
    if part.ground > pm.ground then pm.ground = part.ground end
  end
end

-- a tile goes (or is built again): its items leave the hash, its debris the scene
function M.unregisterTile(K, tileKey, api)
  local list = K.tiles[tileKey]
  if not list then return 0 end
  for k = 1, list.n do
    local id = list[k]
    if K.STATE[id] then
      local s = K.SLOT[id]
      if s then freeSlot(K, s, api) end
      cellRemove(K, id)
      K.X[id], K.Y[id], K.Z[id], K.SPEC[id], K.SHAPE[id], K.STATE[id], K.TILE[id], K.SLOT[id] = nil, nil, nil, nil, nil, nil, nil, nil
      K.nfree = K.nfree + 1
      K.free[K.nfree] = id
      K.items = K.items - 1
    end
  end
  K.tiles[tileKey] = nil
  return list.n
end

function M.clear(K, api)
  for s = 1, K.dn do
    if K.DS[s] and K.DS[s] ~= IDLE then freeSlot(K, s, api) end
  end
  local fresh = M.new({enabled = K.enabled, cap = K.cap, maxFly = K.maxFly})
  local stats = K.stats
  for key, v in pairs(fresh) do K[key] = v end
  K.stats.knocked, K.stats.recycled, K.stats.missed = stats.knocked, stats.recycled, stats.missed
end

function M.count(K) return K.items end

-- is there a prop (standing or debris) in the cell of (x, y) or one round it? (a slow or still
-- vehicle is listed only then: pedhit.gameHitters' slow test)
function M.near(K, x, y)
  local cx, cy = floor(x / M.CELL), floor(y / M.CELL)
  local cells = K.cells
  for i = cx - 1, cx + 1 do
    for j = cy - 1, cy + 1 do
      if cells[i * 1048576 + j] then return true end
    end
  end
  return false
end

return M
