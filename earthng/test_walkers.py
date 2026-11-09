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
  local best = 1e9
  for i = 0, n - 1 do
    local c = i * step
    if y >= -10 and y <= (n - 1) * step + 10 then best = math.min(best, math.abs(x - c)) end
    if x >= -10 and x <= (n - 1) * step + 10 then best = math.min(best, math.abs(y - c)) end
  end
  return best
end
-- a stand-in for the game: bodies are points the test moves
function fakeApi()
  local api = {bodies = {}, calls = {}}
  local n = 0
  function api.spawn() n = n + 1; api.bodies[n] = {x = 0, y = -2000, vx = 0, vy = 0, active = false}; return n end
  function api.pose(id) local b = api.bodies[id]; if b then return b.x, b.y, b.vx, b.vy end end
  function api.place(id, x, y, z, hx, hy, v)
    local b = api.bodies[id]
    b.x, b.y, b.z, b.vx, b.vy, b.active = x, y, z, hx * v, hy * v, true
    api.calls[#api.calls + 1] = 'place ' .. id
  end
  function api.reset(id) api.calls[#api.calls + 1] = 'reset ' .. id end
  function api.park(id) local b = api.bodies[id]; b.y, b.active = -2000, false; api.calls[#api.calls + 1] = 'park ' .. id end
  function api.delete(id) api.bodies[id] = nil end
  return api
end
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
        # half width 3.5 + gap 1.7 = 5.2 m off the middle line; mitred corners stand further out
        self.assertGreater(worst_in, 5.0)
        self.assertLess(worst_out, 5.2 * 2.5 + .1)
        self.assertGreater(moved, 100)
        self.assertGreater(transits, 50)
        self.assertEqual(turned, 0)   # the grid has no dead ends

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

    def test_sidewalks_stop_at_the_corners_and_a_dead_end_turns_walkers_back(self):
        out = self.lua().execute('''
          local W = walkers.new{seed = 9}
          local segs = grid(3, 100)
          walkers.sync(W, segs, 100, 100)
          -- h0_1 runs from 0_1 (an edge node of three roads) to 1_1 (four): both ends cut by 5.2 m
          local rec = W.segs['h0_1']
          local cum, line = rec.cums[1], rec.lines[1]
          local inner = {cum[#cum], line[1], line[2], line[#line - 2], line[#line - 1]}
          -- one street alone: its ends are dead ends, uncut
          local one = walkers.new{seed = 9}
          walkers.sync(one, {h0_0 = segs['h0_0']}, 50, 0)
          walkers.setTarget(one, 10)
          for t = 1, 900 do walkers.step(one, 1 / 10, 50, 0) end
          local c1 = one.segs['h0_0'].cums[1]
          return {inner[1], inner[2], inner[3], inner[4], inner[5], c1[#c1], one.stats.turned, one.count}
        ''')
        length, x0, y0, x1, y1, alone, turned, count = (out[k] for k in range(1, 9))
        self.assertAlmostEqual(length, 100 - 2 * 5.2, places=6)
        self.assertAlmostEqual(x0, 5.2, places=6)
        self.assertAlmostEqual(x1, 94.8, places=6)
        self.assertAlmostEqual(abs(y0 - 100), 5.2, places=6)
        self.assertAlmostEqual(y0, y1, places=6)
        self.assertAlmostEqual(alone, 100, places=6)
        self.assertGreater(turned, 5)
        self.assertEqual(count, 10)

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
        # placed within LEAD (0.3 s at 15 m/s: 4.5 m) of the touch
        self.assertLess(gap, 2.3 + .3 + 15 * .3 + .6)
        self.assertGreater(hit_at, placed_at)
        self.assertEqual((placed, hit, freed), (1, 1, 1))
        self.assertEqual(after_far, 'reset')
        self.assertEqual(final, 'idle')
        self.assertEqual(freed_slot, 1)
        self.assertEqual(calls, 'place 1,reset 1,park 1')

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
          local car = {x = w.x - w.hx * 4.8, y = w.y - w.hy * 4.8, vx = w.hx * 10, vy = w.hy * 10, fx = w.hx, fy = w.hy, hl = 2.3, hw = .95}
          pedhit.step(P, walkers, W, {car}, 0, api, car.x, car.y)
          return {P.stats.noBody, w.taken and 1 or 0}
        ''')
        self.assertEqual(out[1], 1)
        self.assertEqual(out[2], 0)


if __name__ == '__main__':
    unittest.main()
