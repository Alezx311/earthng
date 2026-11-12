"""Pedestrians (mod/lua/ge/extensions/e2r/walkers.lua) and the physical body put in a walker's place
before a hit (pedhit.lua) in LuaJIT: walkers keep to the sidewalks, the sweep finds the touch, the
pool places, keeps and takes back its bodies."""
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

WALKERS = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/walkers.lua'
PEDHIT = WALKERS.with_name('pedhit.lua')

# the grid of test_flow.py: `n` x `n` crossings `step` m apart, half width 3.5 m
GRID = '''
function grid(n, step, speed)
  local segs = {}
  local function add(id, a, b, x0, y0, x1, y1)
    local s = {id, a, b, '-+', speed or 13.9, 3.5, 1}
    for k = 0, 4 do
      local f = k / 4
      s[#s + 1], s[#s + 2], s[#s + 3] = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, 0
    end
    segs[id] = {s = s, x = (x0 + x1) / 2, y = (y0 + y1) / 2}
  end
  for i = 0, n - 1 do
    for j = 0, n - 1 do
      local here = i .. '_' .. j
      if i < n - 1 then add('h' .. here, here, (i + 1) .. '_' .. j, i * step, j * step, (i + 1) * step, j * step) end
      if j < n - 1 then add('v' .. here, here, i .. '_' .. (j + 1), i * step, j * step, i * step, (j + 1) * step) end
    end
  end
  return segs
end
-- the distance of (x, y) from the nearest street's middle line of grid(n, step)
function offStreet(x, y, n, step)
  local best, last = 1e9, (n - 1) * step
  for i = 0, n - 1 do
    local c = i * step
    -- the street along x = c from y = 0 to last, and the one along y = c
    best = math.min(best, math.sqrt((x - c) ^ 2 + (y - math.max(0, math.min(last, y))) ^ 2))
    best = math.min(best, math.sqrt((y - c) ^ 2 + (x - math.max(0, math.min(last, x))) ^ 2))
  end
  return best
end
-- a stand-in for the game: bodies are points the test moves
function fakeApi()
  local api = {bodies = {}, calls = {}}
  local n = 0
  function api.spawn() n = n + 1; api.bodies[n] = {x = 0, y = -2000, vx = 0, vy = 0, active = false}; return n end
  function api.pose(id) local b = api.bodies[id]; if b then return b.x, b.y, b.vx, b.vy end end
  function api.place(id, x, y, z, hx, hy, v, w, opts)
    local b = api.bodies[id]
    local vx = opts and opts.vx or (hx * v)
    local vy = opts and opts.vy or (hy * v)
    b.x, b.y, b.z, b.vx, b.vy, b.active = x, y, z, vx, vy, true
    api.calls[#api.calls + 1] = 'place ' .. id
  end
  function api.nudge(id, x, y) local b = api.bodies[id]; if b then b.x, b.y = x, y end; api.calls[#api.calls + 1] = 'nudge ' .. id end
  function api.eject(id, dvx, dvy, dvz)
    local b = api.bodies[id]
    if b then b.vx, b.vy = b.vx + dvx, b.vy + dvy end
    api.calls[#api.calls + 1] = 'eject ' .. id
  end
  function api.splat(x, y) api.calls[#api.calls + 1] = string.format('splat %.1f %.1f', x, y) end
  function api.reset(id) api.calls[#api.calls + 1] = 'reset ' .. id end
  function api.park(id) local b = api.bodies[id]; b.y, b.active = -2000, false; api.calls[#api.calls + 1] = 'park ' .. id end
  function api.delete(id) api.bodies[id] = nil end
  return api
end
-- the game's TSStatic as a table that counts its calls (walkers.view / draw)
OBJ = {made = 0, alive = 0, pos = 0, shown = 0}
local Obj = {}
Obj.__index = Obj
function Obj:setField() end
function Obj:registerObject() end
function Obj:setPosRot(x, y) OBJ.pos = OBJ.pos + 1; self.x, self.y = x, y end
function Obj:setHidden(h)
  -- shown: hidden == false (a new object is hidden)
  if (self.hidden == false) ~= (h == false) then OBJ.shown = OBJ.shown + (h and -1 or 1) end
  self.hidden = h
end
function Obj:delete() OBJ.alive = OBJ.alive - 1; if self.hidden == false then OBJ.shown = OBJ.shown - 1 end; self.deleted = true end
function createObject() OBJ.made, OBJ.alive = OBJ.made + 1, OBJ.alive + 1; return setmetatable({}, Obj) end
local Col = {}
Col.__index = Col
function Col:asLinear4F() return self end
function ColorF(r, g, b, a) return setmetatable({r, g, b, a}, Col) end
function shapes() local s = {}; for k = 1, walkers.POSES + 1 do s[k] = 'pose' .. k end; return s end
'''


class WalkerTests(unittest.TestCase):
    def lua(self):
        lua = LuaRuntime()
        lua.globals().walkers = lua.execute(WALKERS.read_text(encoding='utf8'))
        lua.globals().pedhit = lua.execute(PEDHIT.read_text(encoding='utf8'))
        lua.execute(GRID)
        return lua

    def test_walkers_fill_up_and_keep_to_the_sidewalks(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 3}
          walkers.sync(W, grid(5, 100), 200, 200)
          walkers.setTarget(W, 150)
          local worstIn, worstOut, bad, moved = 1e9, 0, 0, 0
          local start = {}
          for t = 1, 1800 do
            walkers.step(W, 1 / 30, 200, 200)
            if t == 30 then for k, w in pairs(W.slots) do start[k] = {w.x, w.y} end end
            for _, w in pairs(W.slots) do
              if not w.free then
                if w.x ~= w.x or w.y ~= w.y then bad = bad + 1 end
                if not w.transit then
                  local d = offStreet(w.x, w.y, 5, 100)
                  worstIn, worstOut = math.min(worstIn, d), math.max(worstOut, d)
                end
              end
            end
          end
          for k, w in pairs(W.slots) do
            local s = start[k]
            if s and not w.free and ((w.x - s[1]) ^ 2 + (w.y - s[2]) ^ 2) > 25 then moved = moved + 1 end
          end
          return {W.count, worstIn, worstOut, bad, moved, W.stats.transits, W.stats.turned}
        ''')
        count, worst_in, worst_out, bad, moved, transits, turned = (out[k] for k in range(1, 8))
        self.assertEqual(count, 150)
        self.assertEqual(bad, 0)
        # half width 3.5 + gap 1.7 = 5.2 m off its own middle line, and no nearer than 4.9 m to another's
        self.assertGreater(worst_in, 4.85)
        self.assertLess(worst_out, 5.2 * 2.5 + .1)
        self.assertGreater(moved, 100)
        self.assertGreater(transits, 50)
        self.assertEqual(turned, 0)   # every end of the grid's sidewalks has a way on

    def test_fast_roads_have_no_walkers_and_a_lost_road_takes_its_walkers(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 1}
          walkers.sync(W, grid(3, 100, 25), 100, 100)
          walkers.setTarget(W, 20)
          walkers.step(W, .1, 100, 100)
          local onMotorway = W.count
          walkers.sync(W, grid(3, 100), 100, 100)
          for t = 1, 10 do walkers.step(W, .1, 100, 100) end
          local before = W.count
          walkers.sync(W, {}, 100, 100)
          walkers.step(W, .1, 100, 100)
          return {onMotorway, before, W.count, W.stats.lostRoad or 0}
        ''')
        self.assertEqual(out[1], 0)
        self.assertEqual(out[2], 20)
        self.assertEqual(out[3], 0)
        self.assertGreater(out[4], 0)

    def test_sidewalks_stop_at_the_corners_and_a_lone_street_is_walked_round(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 9}
          local segs = grid(3, 100)
          walkers.sync(W, segs, 100, 100)
          -- h0_1 runs along y = 100 from x = 0 (an edge node of three roads) to x = 100 (four): each
          -- side is one piece, cut 4.9 m from the crossing roads' middle lines (samples every 2 m)
          local rec = W.segs['h0_1']
          local piece = rec.pieces[1]
          local line = piece.line
          local inner = {#rec.pieces, piece.len, line[1], line[2], line[#line - 2], line[#line - 1]}
          -- one street alone: its sidewalks are whole, and at its ends a walker crosses to the other side
          -- (no cap by sidewalk: a lone street would hold 4)
          local one = walkers.new{seed = 9, spacing = 0}
          walkers.sync(one, {h0_0 = segs['h0_0']}, 50, 0)
          walkers.setTarget(one, 10)
          for t = 1, 1800 do walkers.step(one, 1 / 10, 50, 0) end
          local alone = one.segs['h0_0'].pieces
          return {inner[1], inner[2], inner[3], inner[4], inner[5], inner[6], #alone, alone[1].len,
            one.stats.transits, one.stats.turned, one.count}
        ''')
        pieces, length, x0, y0, x1, y1, alone, alone_len, transits, turned, count = (out[k] for k in range(1, 12))
        self.assertEqual(pieces, 2)
        self.assertTrue(4.9 <= x0 <= 7, x0)
        self.assertTrue(93 <= x1 <= 95.1, x1)
        self.assertAlmostEqual(length, x1 - x0, places=6)
        self.assertAlmostEqual(abs(y0 - 100), 5.2, places=6)
        self.assertAlmostEqual(y0, y1, places=6)
        self.assertEqual(alone, 2)
        self.assertAlmostEqual(alone_len, 100, places=6)
        self.assertGreater(transits, 5)
        self.assertEqual(turned, 0)
        self.assertEqual(count, 10)

    def test_a_side_street_joining_in_the_middle_of_a_road_cuts_its_sidewalk(self):
        out = self.lua().execute('''
          -- a main road along y = 0 and a side street from its middle (100, 0) north; the graph has
          -- no node of the main road there
          local function road(id, a, b, x0, y0, x1, y1)
            local s = {id, a, b, '-+', 13.9, 3.5, 1}
            for k = 0, 4 do
              local f = k / 4
              s[#s + 1], s[#s + 2], s[#s + 3] = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, 0
            end
            return {s = s, x = (x0 + x1) / 2, y = (y0 + y1) / 2}
          end
          local segs = {main = road('main', 'm0', 'm1', 0, 0, 200, 0), side = road('side', 's0', 's1', 100, 0, 100, 100)}
          local W = walkers.new{seed = 6}
          walkers.sync(W, segs, 100, 20)
          local north, south, gap = {}, {}, nil
          for _, piece in ipairs(W.segs.main.pieces) do
            -- the line's left side is north (y = 5.2)
            if piece.line[2] > 0 then north[#north + 1] = piece else south[#south + 1] = piece end
          end
          table.sort(north, function(a, b) return a.line[1] < b.line[1] end)
          if #north == 2 then gap = {north[1].line[#north[1].line - 2], north[2].line[1]} end
          local sideStart = 1e9
          for _, piece in ipairs(W.segs.side.pieces) do sideStart = math.min(sideStart, piece.line[2], piece.line[#piece.line - 1]) end
          -- the ends at the mouth: straight on across it, and round the corner into the side street
          local E = north[1] and north[1].ends[1]
          local across, corner = 0, 0
          for _, link in ipairs(E and E.links or {}) do
            if link.cross and link.to.piece == north[2] then across = across + 1 end
            if not link.cross and link.to.piece.rec == W.segs.side then corner = corner + 1 end
          end
          -- walkers never stand in either road except on a leg across it
          walkers.setTarget(W, 60)
          local inRoad, crossed = 0, 0
          for t = 1, 6000 do
            walkers.step(W, 1 / 10, 100, 20)
            for _, w in pairs(W.slots) do
              if not w.free then
                local dMain = (w.x >= 0 and w.x <= 200) and math.abs(w.y) or 1e9
                local dSide = (w.y >= 0 and w.y <= 100) and math.abs(w.x - 100) or 1e9
                if math.min(dMain, dSide) < 4.5 then
                  if w.transit and w.transit.cross then crossed = crossed + 1 else inRoad = inRoad + 1 end
                end
              end
            end
          end
          return {#north, #south, gap and gap[1] or -1, gap and gap[2] or -1, sideStart, across, corner, inRoad, crossed, W.stats.rebuilt or 0}
        ''')
        north, south, gap0, gap1, side_start, across, corner, in_road, crossed, rebuilt = (out[k] for k in range(1, 11))
        self.assertEqual((north, south), (2, 1))
        self.assertTrue(93 <= gap0 <= 95.2, gap0)
        self.assertTrue(104.8 <= gap1 <= 107, gap1)
        self.assertTrue(4.9 <= side_start <= 7, side_start)   # where the main road's cars no longer reach
        self.assertEqual((across, corner), (1, 1))
        self.assertEqual(in_road, 0)
        self.assertGreater(crossed, 20)

    def test_a_new_road_cuts_the_sidewalks_it_crosses(self):
        out = self.lua().execute('''
          local function road(id, x0, y0, x1, y1)
            local s = {id, id .. 'a', id .. 'b', '-+', 13.9, 3.5, 1}
            for k = 0, 4 do
              local f = k / 4
              s[#s + 1], s[#s + 2], s[#s + 3] = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, 0
            end
            return {s = s, x = (x0 + x1) / 2, y = (y0 + y1) / 2}
          end
          local segs = {main = road('main', 0, 0, 200, 0), far = road('far', 0, 300, 200, 300)}
          local W = walkers.new{seed = 6}
          walkers.sync(W, segs, 100, 20)
          local before, farPiece = #W.segs.main.pieces, W.segs.far.pieces[1]
          local again = walkers.sync(W, segs, 100, 20)
          -- the next tile brings a street across the main road
          segs.cross = road('cross', 100, -100, 100, 100)
          local changed = walkers.sync(W, segs, 100, 20)
          return {before, again and 1 or 0, changed and 1 or 0, #W.segs.main.pieces, W.stats.rebuilt,
            W.segs.far.pieces[1] == farPiece and 1 or 0, farPiece.dead and 1 or 0}
        ''')
        self.assertEqual(out[1], 2)
        self.assertEqual(out[2], 0)          # nothing came or went: nothing is built
        self.assertEqual(out[3], 1)
        self.assertEqual(out[4], 4)          # both sides cut in two
        self.assertEqual(out[5], 1)          # only the road beside the new one is built again
        self.assertEqual((out[6], out[7]), (1, 0))

    def test_a_walker_waits_at_the_kerb_for_a_car_and_crosses_when_the_road_is_clear(self):
        out = self.lua().execute('''
          -- one walker made to cross the road from (0, 0) to (0, 9) at 1.5 m/s
          local function crossing()
            local W = walkers.new{seed = 1}
            walkers.sync(W, grid(2, 100), 50, 50)
            walkers.setTarget(W, 1)
            walkers.step(W, .01, 50, 50)
            local w = W.slots[1]
            w.speed = 1.5
            w.transit = {x0 = 0, y0 = 0, z0 = 0, x1 = 0, y1 = 9, z1 = 0, len = 9, s = 0, hx = 0, hy = 1, cross = true}
            return W, w
          end
          local function run(W, w, seconds, cars, flow)
            local onRoad = 0
            for t = 1, seconds * 20 do
              walkers.step(W, .05, 50, 50, cars, flow)
              if #W.onRoad > 0 then onRoad = onRoad + 1 end
            end
            return onRoad
          end
          -- a car 60 m down the road coming at 14 m/s: there in 4 s, the walker needs 6 + 2
          local W, w = crossing()
          local coming = run(W, w, 2, {{x = -60, y = 4.5, vx = 14, vy = 0}})
          local waited = {w.waiting and 1 or 0, w.transit and w.transit.s or -1, coming}
          -- the same car as the flow draws it
          local W2, w2 = crossing()
          run(W2, w2, 2, nil, {{drawnX = -60, drawnY = 4.5, drawnYaw = 0, v = 14}})
          local flowWait = w2.waiting and 1 or 0
          -- a car that has passed, one far up a side street, a standing one: the walker goes
          local W3, w3 = crossing()
          local on3 = run(W3, w3, 2, {{x = 30, y = 4.5, vx = 14, vy = 0}, {x = -60, y = 40, vx = 14, vy = 0}, {x = -10, y = 4.5, vx = 0, vy = 0}})
          local went = {w3.waiting and 1 or 0, w3.transit and w3.transit.s or -1, on3}
          -- a street that never clears: after 25 s the walker goes anyway
          local W4, w4 = crossing()
          local cars = {{x = -40, y = 4.5, vx = 14, vy = 0}}
          run(W4, w4, 24, cars)
          local still = w4.waiting and 1 or 0
          run(W4, w4, 3, cars)
          return {waited[1], waited[2], waited[3], flowWait, went[1], went[2], went[3], still, w4.waiting and 1 or 0, W.stats.waits}
        ''')
        self.assertEqual((out[1], out[2], out[3]), (1, 0, 0))     # waits, has not moved, not on the road
        self.assertEqual(out[4], 1)
        self.assertEqual(out[5], 0)
        self.assertAlmostEqual(out[6], 3.0, delta=.3)             # 2 s at 1.5 m/s
        self.assertGreater(out[7], 30)
        self.assertEqual((out[8], out[9]), (1, 0))
        self.assertEqual(out[10], 1)

    def test_sidewalks_lie_beyond_the_lanes_the_flow_drives_in(self):
        out = self.lua().execute('''
          local function edge(lanes, half) return walkers.roadEdge({'id', 'a', 'b', lanes, 13.9, half, 1}) end
          -- a 7 m street with one lane each way: its own edge
          local plain = edge('-+', 3.5)
          -- tagged four lanes on the same 7 m: the flow's lanes are 2.6 m, two each way
          local narrow = edge('--++', 3.5)
          -- one way, three lanes on 7 m: 3 x 2.6 round the middle line
          local oneway = edge('+++', 3.5)
          -- a wide avenue holds its lanes
          local wide = edge('---+++', 12)
          local W = walkers.new{seed = 1}
          local s = {'s', 'a', 'b', '--++', 13.9, 3.5, 1, 0, 0, 0, 50, 0, 0, 100, 0, 0}
          walkers.sync(W, {s = {s = s, x = 50, y = 0}}, 50, 0)
          local pieces = W.segs.s.pieces
          return {plain, narrow, oneway, wide, math.abs(pieces[1].line[2]), math.abs(pieces[2].line[2])}
        ''')
        self.assertAlmostEqual(out[1], 3.5)
        self.assertAlmostEqual(out[2], 5.2)
        self.assertAlmostEqual(out[3], 3.9)
        self.assertAlmostEqual(out[4], 12)
        self.assertAlmostEqual(out[5], 5.2 + 1.7)
        self.assertAlmostEqual(out[6], 5.2 + 1.7)

    def test_new_walkers_appear_out_of_sight(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 5}
          walkers.sync(W, grid(8, 100), 350, 350)
          walkers.setTarget(W, 100)
          for t = 1, 20 do walkers.step(W, .1, 350, 350) end
          -- now the focus jumps: the walkers far behind go, the new ones are no nearer than 90 m
          local looks = {}
          for k, w in pairs(W.slots) do looks[k] = w.look end
          local nearest = 1e9
          for t = 1, 60 do
            walkers.step(W, .1, 600, 600)
            for k, w in pairs(W.slots) do
              if not w.free and w.look ~= looks[k] then
                looks[k] = w.look
                nearest = math.min(nearest, math.sqrt((w.x - 600) ^ 2 + (w.y - 600) ^ 2))
              end
            end
          end
          return {nearest, W.count}
        ''')
        self.assertGreaterEqual(out[1], 89)
        self.assertEqual(out[2], 100)

    def test_sweep_finds_the_touch_of_a_box(self):
        out = self.lua().execute('''
          -- a car 4.6 x 1.9 at the origin heading +x at 10 m/s; a walker standing 10 m ahead
          local t1 = pedhit.sweep(10, 0, 0, 0, .3, 0, 0, 1, 0, 2.3, .95, 10, 0, 2)
          -- the same walker 2 m to the side: missed
          local t2 = pedhit.sweep(10, 2, 0, 0, .3, 0, 0, 1, 0, 2.3, .95, 10, 0, 2)
          -- a walker crossing into the car's path from its left
          local t3 = pedhit.sweep(10, 3, 0, -1.5, .3, 0, 0, 1, 0, 2.3, .95, 10, 0, 2)
          -- too far for the time asked
          local t4 = pedhit.sweep(30, 0, 0, 0, .3, 0, 0, 1, 0, 2.3, .95, 10, 0, 2)
          -- a car heading +y (rotated box)
          local t5 = pedhit.sweep(0, 10, 0, 0, .3, 0, 0, 0, 1, 2.3, .95, 0, 10, 2)
          return {t1, t2 or -1, t3 or -1, t4 or -1, t5 or -1}
        ''')
        self.assertAlmostEqual(out[1], (10 - 2.3 - .3) / 10, places=6)
        self.assertEqual(out[2], -1)
        self.assertGreater(out[3], .7)
        self.assertLess(out[3], 1.2)
        self.assertEqual(out[4], -1)
        self.assertAlmostEqual(out[5], (10 - 2.3 - .3) / 10, places=6)

    def test_a_body_takes_the_place_lies_after_the_hit_and_goes_back_to_the_pool(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 2}
          walkers.sync(W, grid(3, 100), 100, 0)
          walkers.setTarget(W, 1)
          walkers.step(W, .01, 100, 0)
          local w = W.slots[1]
          w.speed = 0.0001
          local api, P = fakeApi(), pedhit.new{size = 2}
          pedhit.prewarm(P, api, 0, 0)
          -- a car 20 m behind the walker along its heading, at 15 m/s
          local cx, cy = w.x - w.hx * 20, w.y - w.hy * 20
          local car = {x = cx, y = cy, vx = w.hx * 15, vy = w.hy * 15, fx = w.hx, fy = w.hy, hl = 2.3, hw = .95}
          local placedAt, hitAt, now = nil, nil, 0
          local events = {}
          for t = 1, 200 do
            now = t / 30
            car.x, car.y = car.x + car.vx / 30, car.y + car.vy / 30
            -- the struck body flies on with the car
            local b = api.bodies[1]
            if b.active and (car.x - b.x) ^ 2 + (car.y - b.y) ^ 2 < 2.5 ^ 2 then b.vx, b.vy = car.vx * .8, car.vy * .8 end
            if b.active then b.x, b.y = b.x + b.vx / 30, b.y + b.vy / 30 end
            pedhit.step(P, walkers, W, {car}, now, api, car.x, car.y)
            if not placedAt and P.stats.placed > 0 then placedAt = now; events.gap = math.sqrt((car.x - w.x) ^ 2 + (car.y - w.y) ^ 2) end
            if not hitAt and P.stats.hit > 0 then hitAt = now end
          end
          events.takenWhilePlaced = w.taken
          -- the car drives on 15 m/s for 6 s: 90 m, not far enough; then it is 200 m away
          pedhit.step(P, walkers, W, {}, now + 1, api, 1000, 1000)
          local stateAfterFar = P.pool[1].state
          pedhit.step(P, walkers, W, {}, now + 2, api, 1000, 1000)
          return {placedAt or -1, hitAt or -1, events.gap or -1, P.stats.placed, P.stats.hit, P.stats.freed,
            stateAfterFar, P.pool[1].state, w.free and 1 or 0, table.concat(api.calls, ',')}
        ''')
        placed_at, hit_at, gap, placed, hit, freed, after_far, final, freed_slot, calls = (out[k] for k in range(1, 11))
        self.assertGreater(placed_at, 0)
        # placed within LEAD (0.45 s at 15 m/s) of the touch
        self.assertLess(gap, 2.3 + .3 + 15 * .45 + .8)
        self.assertGreater(hit_at, placed_at)
        self.assertEqual((placed, hit, freed), (1, 1, 1))
        self.assertEqual(after_far, 'reset')
        self.assertEqual(final, 'idle')
        self.assertEqual(freed_slot, 1)
        self.assertIn('place 1', calls)
        self.assertIn('eject 1', calls)
        self.assertIn('splat', calls)
        self.assertIn('reset 1', calls)
        self.assertIn('park 1', calls)

    def test_a_missed_walker_walks_on_and_the_body_is_taken_back(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 4}
          walkers.sync(W, grid(3, 100), 100, 0)
          walkers.setTarget(W, 1)
          walkers.step(W, .01, 100, 0)
          local w = W.slots[1]
          local api, P = fakeApi(), pedhit.new{size = 1}
          pedhit.prewarm(P, api, 0, 0)
          -- a car 4 m short of the walker coming at 10 m/s: the body is placed, then the car stops dead
          local car = {x = w.x - w.hx * 4.8, y = w.y - w.hy * 4.8, vx = w.hx * 10, vy = w.hy * 10, fx = w.hx, fy = w.hy, hl = 2.3, hw = .95}
          pedhit.step(P, walkers, W, {car}, 0, api, car.x, car.y)
          local taken = w.taken and 1 or 0
          car.vx, car.vy = 0, 0
          local states = {}
          for t = 1, 45 do
            walkers.step(W, 1 / 30, 100, 0)
            pedhit.step(P, walkers, W, {car}, t / 30, api, car.x, car.y)
            states[P.pool[1].state] = true
          end
          return {taken, P.stats.placed, P.stats.missed, P.stats.hit, w.taken and 1 or 0, w.free and 1 or 0,
            P.pool[1].state, states.reset and 1 or 0}
        ''')
        self.assertEqual(out[1], 1)
        self.assertEqual((out[2], out[3], out[4]), (1, 1, 0))
        self.assertEqual(out[5], 0)   # walks on
        self.assertEqual(out[6], 0)
        self.assertEqual(out[7], 'idle')
        self.assertEqual(out[8], 1)

    def test_a_teleported_car_places_nobody_and_a_fresh_body_is_not_hit_by_its_own_jump(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 4}
          walkers.sync(W, grid(3, 100), 100, 0)
          walkers.setTarget(W, 1)
          walkers.step(W, .01, 100, 0)
          local w = W.slots[1]
          local api, P = fakeApi(), pedhit.new{size = 1}
          pedhit.prewarm(P, api, 0, 0)
          -- a car that jumped 150 m in a frame: 4500 m/s, aimed at the walker
          local jump = {x = w.x - w.hx * 150, y = w.y - w.hy * 150, vx = w.hx * 4500, vy = w.hy * 4500, fx = w.hx, fy = w.hy, hl = 2.3, hw = .95}
          pedhit.step(P, walkers, W, {jump}, 0, api, jump.x, jump.y)
          local placedByJump = P.stats.placed
          -- a real one: placed; the body reads the jump from z -2000 in its first frame, the car beside it
          local car = {x = w.x - w.hx * 4.8, y = w.y - w.hy * 4.8, vx = w.hx * 10, vy = w.hy * 10, fx = w.hx, fy = w.hy, hl = 2.3, hw = .95}
          pedhit.step(P, walkers, W, {car}, 1, api, car.x, car.y)
          api.bodies[1].vx = 3000
          car.x, car.y = w.x - w.hx * 3, w.y - w.hy * 3
          pedhit.step(P, walkers, W, {car}, 1 + 1 / 30, api, car.x, car.y)
          return {placedByJump, P.stats.placed, P.stats.hit, P.pool[1].state}
        ''')
        self.assertEqual(out[1], 0)
        self.assertEqual(out[2], 1)
        self.assertEqual(out[3], 0)
        self.assertEqual(out[4], 'placed')

    def test_no_free_body_leaves_the_walker_walking(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 4}
          walkers.sync(W, grid(3, 100), 100, 0)
          walkers.setTarget(W, 1)
          walkers.step(W, .01, 100, 0)
          local w = W.slots[1]
          local api, P = fakeApi(), pedhit.new{size = 0}
          -- still ~0.22 s from touch: count noBody, walker keeps walking until ghost range
          local car = {x = w.x - w.hx * 4.8, y = w.y - w.hy * 4.8, vx = w.hx * 10, vy = w.hy * 10, fx = w.hx, fy = w.hy, hl = 2.3, hw = .95}
          pedhit.step(P, walkers, W, {car}, 0, api, car.x, car.y)
          return {P.stats.noBody, w.taken and 1 or 0, w.free and 1 or 0, P.stats.ghost}
        ''')
        self.assertEqual(out[1], 1)
        self.assertEqual(out[2], 0)
        self.assertEqual(out[3], 0)
        self.assertEqual(out[4], 0)

    def test_ghost_hit_removes_a_walker_when_the_pool_is_empty(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 4}
          walkers.sync(W, grid(3, 100), 100, 0)
          walkers.setTarget(W, 1)
          walkers.step(W, .01, 100, 0)
          local w = W.slots[1]
          local api, P = fakeApi(), pedhit.new{size = 0}
          -- within GHOST_LEAD of the bumper: no body, but the walker still dies
          local car = {x = w.x - w.hx * 2.7, y = w.y - w.hy * 2.7, vx = w.hx * 10, vy = w.hy * 10, fx = w.hx, fy = w.hy, hl = 2.3, hw = .95}
          pedhit.step(P, walkers, W, {car}, 0, api, car.x, car.y)
          return {P.stats.ghost, P.stats.hit, w.free and 1 or 0, table.concat(api.calls, ',')}
        ''')
        self.assertEqual(out[1], 1)
        self.assertEqual(out[2], 1)
        self.assertEqual(out[3], 1)
        self.assertIn('splat', out[4])

    def test_box_hit_pushes_a_point_out_of_a_vehicle(self):
        out = self.lua().execute('''
          local h = {x = 0, y = 0, fx = 1, fy = 0, hl = 2.3, hw = .95}
          local inside, nx, ny, depth = pedhit.boxHit(0, 0, .3, h)
          local outX = 0 + nx * (depth + .22)
          local outY = 0 + ny * (depth + .22)
          local inside2 = pedhit.boxHit(outX, outY, .3, h)
          -- a point already outside: negative depth on the nearest face
          local i3, nx3, ny3, d3 = pedhit.boxHit(4, 0, .3, h)
          return {inside and 1 or 0, depth, outX, outY, inside2 and 1 or 0, i3 and 1 or 0, d3}
        ''')
        self.assertEqual(out[1], 1)
        self.assertGreater(out[2], 2)
        self.assertAlmostEqual(out[3], out[2] + .22, places=5)  # pushed along +x
        self.assertEqual(out[5], 0)
        self.assertEqual(out[6], 0)
        self.assertLess(out[7], 0)

    def test_an_embedded_body_is_forced_out_on_hit(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 2}
          walkers.sync(W, grid(3, 100), 100, 0)
          walkers.setTarget(W, 1)
          walkers.step(W, .01, 100, 0)
          local w = W.slots[1]
          w.speed = 0.0001
          local api, P = fakeApi(), pedhit.new{size = 1}
          pedhit.prewarm(P, api, 0, 0)
          local car = {x = w.x - w.hx * 3.2, y = w.y - w.hy * 3.2, vx = w.hx * 12, vy = w.hy * 12, fx = w.hx, fy = w.hy, hl = 2.3, hw = .95, id = 9}
          pedhit.step(P, walkers, W, {car}, 0, api, car.x, car.y)
          local b = api.bodies[1]
          -- force the body into the car's middle (the old bug) after settle
          b.x, b.y = car.x + car.fx * .2, car.y + car.fy * .2
          b.vx, b.vy = car.vx, car.vy
          car.x, car.y = b.x, b.y
          pedhit.step(P, walkers, W, {car}, .2, api, car.x, car.y)
          local dx, dy = b.x - car.x, b.y - car.y
          local along = dx * car.fx + dy * car.fy
          return {P.stats.hit, P.pool[1].state, P.stats.eject, along, table.concat(api.calls, ',')}
        ''')
        self.assertEqual(out[1], 1)
        self.assertEqual(out[2], 'down')
        self.assertEqual(out[3], 1)
        # nudged outward along the car's forward (or back) so it is no longer at the centre
        self.assertGreater(abs(out[4]), .2)
        self.assertIn('nudge 1', out[5])
        self.assertIn('eject 1', out[5])

    def test_the_count_changes_in_place_and_is_clamped(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 3}
          walkers.sync(W, grid(8, 100), 350, 350)
          walkers.setTarget(W, 300)
          for t = 1, 60 do walkers.step(W, 1 / 30, 350, 350) end
          local first, slot1 = W.count, W.slots[1]
          local look1, version = slot1.look, W.version
          -- a slider dragged: up, down, up again; the walkers already there keep walking
          walkers.setTarget(W, 500)
          walkers.step(W, 1 / 30, 350, 350)
          local grown = W.count
          walkers.setTarget(W, 120)
          local shrunk = W.count
          walkers.setTarget(W, 2000)
          local clamped = W.target
          walkers.setTarget(W, -5)
          local zero = {W.target, W.count}
          walkers.setTarget(W, 7.8)
          local asked, walking, room = walkers.counts(W)
          return {first, grown, shrunk, clamped, zero[1], zero[2], asked, slot1.look == look1 and 1 or 0,
            W.slots[1] == slot1 and 1 or 0, version == W.version and 1 or 0, room}
        ''')
        first, grown, shrunk, clamped, zero_target, zero_count, asked, same_look, same_slot, no_sync, room = (out[k] for k in range(1, 12))
        self.assertEqual(first, 300)
        self.assertEqual(grown, 312)          # FILL_PER_STEP new ones a step
        self.assertEqual(shrunk, 120)
        self.assertEqual(clamped, 1000)
        self.assertEqual((zero_target, zero_count), (0, 0))
        self.assertEqual(asked, 7)
        self.assertEqual((same_look, same_slot, no_sync), (1, 1, 1))
        self.assertEqual(room, 1000)          # an 8 x 8 grid of streets holds them all (M.MAX)

    def test_little_sidewalk_holds_fewer_walkers_than_asked(self):
        out = self.lua().execute('''
          local segs = grid(8, 100)
          -- one street alone (a village road) and the whole grid (a town)
          local lone = walkers.new{seed = 2}
          walkers.sync(lone, {h0_0 = segs['h0_0']}, 50, 0)
          walkers.setTarget(lone, 200)
          for t = 1, 60 do walkers.step(lone, 1 / 30, 50, 0) end
          local town = walkers.new{seed = 2}
          walkers.sync(town, segs, 350, 350)
          local loneWeight, townWeight = lone.list[1].weight, 0
          for _, piece in ipairs(town.list) do townWeight = math.max(townWeight, piece.weight) end
          local a1, p1, r1 = walkers.counts(lone)
          return {a1, p1, r1, loneWeight, townWeight}
        ''')
        asked, placed, room, lone_weight, town_weight = (out[k] for k in range(1, 6))
        self.assertEqual(asked, 200)
        self.assertEqual(placed, room)
        self.assertLess(room, 10)
        self.assertLess(lone_weight, .1)
        self.assertGreater(town_weight, .5)

    def test_far_walkers_move_less_often_but_as_far(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 4, spacing = 0}
          walkers.sync(W, grid(8, 100), 320, 320)
          walkers.setTarget(W, 400)
          walkers.step(W, 1 / 60, 320, 320)
          local start = {}
          for slot, w in pairs(W.slots) do if not w.free then start[slot] = {w.walked, w.x, w.y} end end
          local turns = {}
          for t = 1, 600 do
            walkers.step(W, 1 / 60, 320, 320)
            for slot, w in pairs(W.slots) do if w.dirty then turns[slot] = (turns[slot] or 0) + 1; w.dirty = nil end end
          end
          -- by distance: walked (m) over the 10 s against the walker's speed, and turns taken
          local nearTurns, farTurns, worst, n = 0, 0, 0, 0
          for slot, s in pairs(start) do
            local w = W.slots[slot]
            if not w.free and w.look then
              local d = math.sqrt((w.x - 320) ^ 2 + (w.y - 320) ^ 2)
              local ratio = (w.walked - s[1]) / (w.speed * 10)
              if not w.waiting and not w.transit then worst = math.max(worst, math.abs(1 - ratio)) end
              if d < 30 and math.sqrt((s[2] - 320) ^ 2 + (s[3] - 320) ^ 2) < 30 then nearTurns = math.max(nearTurns, turns[slot] or 0) end
              if d > 220 and math.sqrt((s[2] - 320) ^ 2 + (s[3] - 320) ^ 2) > 220 then farTurns = math.max(farTurns, turns[slot] or 0) end
              n = n + 1
            end
          end
          return {nearTurns, farTurns, worst, walkers.periodOf(10 ^ 2), walkers.periodOf(100 ^ 2), walkers.periodOf(250 ^ 2)}
        ''')
        near_turns, far_turns, worst, p10, p100, p250 = (out[k] for k in range(1, 7))
        self.assertEqual(near_turns, 600)
        self.assertLess(worst, 20 / 600 + .001)   # skipped turns are walked at the next: behind by a period at most
        self.assertLessEqual(far_turns, 600 / 20 + 2)
        self.assertGreater(far_turns, 0)
        self.assertEqual((p10, p100, p250), (1, 5, 20))

    def test_near_finds_the_walkers_round_a_point_from_the_grid(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 8, spacing = 0}
          walkers.sync(W, grid(8, 100), 350, 350)
          walkers.setTarget(W, 600)
          for t = 1, 300 do walkers.step(W, 1 / 30, 350, 350) end
          local bad, total, buf = 0, 0, {}
          for k = 1, 40 do
            local x, y, r = 200 + k * 7, 250 + k * 3, 5 + k % 4 * 10
            local got, n = walkers.near(W, x, y, r, buf)
            if got ~= buf then bad = bad + 1000 end
            local want = 0
            for _, w in pairs(W.slots) do
              if not w.free and not w.taken and (w.x - x) ^ 2 + (w.y - y) ^ 2 < r * r then want = want + 1 end
            end
            if want ~= n or #got ~= n then bad = bad + 1 end
            total = total + n
          end
          return {bad, total}
        ''')
        self.assertEqual(out[1], 0)
        self.assertGreater(out[2], 20)

    def test_shapes_by_distance_stay_bounded_and_go_when_off(self):
        out = self.lua().execute('''
          for k in pairs(OBJ) do OBJ[k] = 0 end
          local W = walkers.new{seed = 5, spacing = 0}
          walkers.sync(W, grid(12, 100), 550, 550)
          local V = walkers.view(W, shapes(), nil)
          walkers.setTarget(W, 1000)
          local maxMade = 0
          for t = 1, 900 do
            walkers.step(W, 1 / 60, 550, 550)
            walkers.draw(W, V, 550, 550)
            maxMade = math.max(maxMade, OBJ.made)
          end
          -- every walker within 60 m posed (one shape shown of its set), within 200 m one shape, none further
          local posedFar, drawnFar, hiddenNear, shownSlots = 0, 0, 0, 0
          for slot, w in pairs(W.slots) do
            if not w.free then
              local d = math.sqrt((w.x - 550) ^ 2 + (w.y - 550) ^ 2)
              if V.near[slot] and d > 70.01 then posedFar = posedFar + 1 end
              if V.far[slot] and d > 215.01 then drawnFar = drawnFar + 1 end
              if d < 190 and not (V.near[slot] or V.far[slot]) then hiddenNear = hiddenNear + 1 end
              if V.near[slot] or V.far[slot] then shownSlots = shownSlots + 1 end
            end
          end
          local busy = {W.count, OBJ.alive, OBJ.shown, V.nearUsed, V.farUsed, posedFar, drawnFar, hiddenNear, shownSlots}
          -- off: nothing shown at once, the spare objects trimmed a few a frame later
          walkers.setTarget(W, 0)
          walkers.step(W, 1 / 60, 550, 550)
          walkers.draw(W, V, 550, 550)
          local shownOff = OBJ.shown
          for t = 1, 400 do walkers.step(W, 1 / 60, 550, 550); walkers.draw(W, V, 550, 550) end
          local aliveTrimmed = OBJ.alive
          walkers.clear(W, V)
          return {busy[1], busy[2], busy[3], busy[4], busy[5], busy[6], busy[7], busy[8], busy[9], shownOff, aliveTrimmed, OBJ.alive}
        ''')
        count, alive, shown, posed, drawn, posed_far, drawn_far, hidden_near, shown_slots, shown_off, trimmed, cleared = (out[k] for k in range(1, 13))
        self.assertEqual(count, 1000)
        self.assertEqual(shown, posed + drawn)
        self.assertEqual(shown_slots, posed + drawn)
        self.assertLessEqual(posed, 96)
        self.assertLess(alive, 1000 + 96 * 9)
        self.assertLess(drawn + posed, 1000)              # those beyond 200 m have none
        self.assertEqual((posed_far, drawn_far, hidden_near), (0, 0, 0))
        self.assertEqual(shown_off, 0)
        self.assertLessEqual(trimmed, 48 + 6 * 9)
        self.assertEqual(cleared, 0)

    def test_no_garbage_while_walking(self):
        out = self.lua().execute('''
          jit.off()
          local W = walkers.new{seed = 6, spacing = 0}
          walkers.sync(W, grid(12, 100), 550, 550)
          local V = walkers.view(W, shapes(), nil)
          local api, P = fakeApi(), pedhit.new{size = 2}
          pedhit.prewarm(P, api, 0, 0)
          local car = {x = 550, y = 545, vx = 8, vy = 0, fx = 1, fy = 0, hl = 2.3, hw = .95}
          local flow = {{drawnX = 500, drawnY = 500, drawnYaw = 0, v = 10}}
          walkers.setTarget(W, 1000)
          local function frame(t)
            walkers.step(W, 1 / 60, 550, 550, {car}, flow)
            pedhit.step(P, walkers, W, {car}, t / 60, api, 550, 550)
            walkers.draw(W, V, 550, 550, function(x, y, z) return z + .1 end)
          end
          -- every walker has turned a corner once, every shape is made
          for t = 1, 3600 do frame(t) end
          collectgarbage('collect')
          collectgarbage('stop')
          local kb = collectgarbage('count')
          for t = 3601, 4200 do frame(t) end
          kb = collectgarbage('count') - kb
          collectgarbage('restart')
          jit.on()
          return {kb / 600, W.count}
        ''')
        # the draw's ground closure above is 1 per frame (the game makes it once): ~0.03 KB
        self.assertLess(out[1], .25, out[1])
        self.assertEqual(out[2], 1000)

    def test_a_sync_in_slices_builds_what_a_whole_one_does_while_walkers_walk(self):
        out = self.lua().execute('''
          local all = grid(10, 100)
          local part = {}
          for sid, seg in pairs(all) do if seg.x < 600 then part[sid] = seg end end
          local function signature(W)
            local n, links, len = 0, 0, 0
            for _, piece in ipairs(W.list) do
              n, len = n + 1, len + piece.len
              for e = -1, 1, 2 do links = links + #piece.ends[e].links end
            end
            return n .. ' ' .. links .. ' ' .. math.floor(len)
          end
          -- the whole sync, and the same in slices (pause yields every call) with walkers walking between
          local A = walkers.new{seed = 1, spacing = 0}
          walkers.sync(A, part, 450, 450)
          walkers.sync(A, all, 450, 450)
          local B = walkers.new{seed = 1, spacing = 0}
          walkers.sync(B, part, 450, 450)
          walkers.setTarget(B, 300)
          for t = 1, 120 do walkers.step(B, 1 / 30, 450, 450) end
          local co = coroutine.create(function() walkers.sync(B, all, 450, 450, coroutine.yield) end)
          local slices = 0
          while coroutine.status(co) ~= 'dead' do
            assert(coroutine.resume(co))
            slices = slices + 1
            walkers.step(B, 1 / 30, 450, 450)
          end
          for t = 1, 300 do walkers.step(B, 1 / 30, 450, 450) end
          -- and all at once from nothing: the ends linked again only round the change are the same
          local C = walkers.new{seed = 1, spacing = 0}
          walkers.sync(C, all, 450, 450)
          return {signature(A), signature(B), slices, B.count, signature(C)}
        ''')
        self.assertEqual(out[1], out[2])
        self.assertEqual(out[1], out[5])
        self.assertGreater(out[3], 20)
        self.assertEqual(out[4], 300)

    def test_a_teleport_brings_the_walkers_to_the_new_place(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 7, spacing = 0}
          walkers.sync(W, grid(14, 100), 200, 200)
          walkers.setTarget(W, 200)
          for t = 1, 60 do walkers.step(W, 1 / 30, 200, 200) end
          -- 900 m away in one step (a landing elsewhere on the same graph): the old ones go, the new
          -- ones may appear in sight (the camera cut), so the place fills at once
          walkers.step(W, 1 / 30, 1100, 1100)
          walkers.sync(W, grid(14, 100), 1100, 1100)   -- the new place's tiles (S.navAt changed)
          for t = 1, 30 do walkers.step(W, 1 / 30, 1100, 1100) end
          local nearest, all = 1e9, 0
          for _, w in pairs(W.slots) do
            if not w.free then
              all = all + 1
              nearest = math.min(nearest, math.sqrt((w.x - 1100) ^ 2 + (w.y - 1100) ^ 2))
            end
          end
          return {all, nearest, W.stats.far}
        ''')
        self.assertEqual(out[1], 200)
        self.assertLess(out[2], 90)
        self.assertEqual(out[3], 200)


if __name__ == '__main__':
    unittest.main()
