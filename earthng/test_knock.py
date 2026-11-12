"""Knockable street furniture (mod/lua/ge/extensions/e2r/knock.lua) in LuaJIT: the sweep finds the touch
before the car gets there, the item swaps for debris, the hit throws light props far and heavy ones a
little, the car slows by the mass ratio, debris sleeps, the cap recycles the oldest, a tile takes its
items and debris away, and the same drive gives the same result. No ghost props: one contact law from
a crawl (pushed, a planter stops the car) to a throw with no step between, nothing passes through at
0.3 or 90 m/s, a car standing in a prop shoves it out once. Debris bounces off walls (a stubbed ray)."""
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

KNOCK = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/knock.lua'

HARNESS = '''
-- a stand-in for the game: flat ground at z 0, objects are tables, pushes recorded per vehicle
function fakeApi()
  local api = {hidden = {}, objs = {}, pushes = {}, taken = 0, dropped = 0, placed = 0, refuse = {}}
  function api.hide(id, shape, x, y, z)
    if api.refuse[id] then return false end
    api.hidden[#api.hidden + 1] = id
    return true
  end
  function api.take(shape, scale)
    api.taken = api.taken + 1
    local o = {shape = shape}
    api.objs[#api.objs + 1] = o
    return o
  end
  function api.drop(o) api.dropped = api.dropped + 1; o.dropped = true end
  function api.place(o, x, y, z, qx, qy, qz, qw)
    api.placed = api.placed + 1
    o.x, o.y, o.z, o.qx, o.qy, o.qz, o.qw = x, y, z, qx, qy, qz, qw
  end
  function api.ground(x, y, z) return 0 end
  function api.push(id, dvx, dvy, dvz)
    local p = api.pushes[id] or {0, 0, 0}
    p[1], p[2], p[3] = p[1] + dvx, p[2] + dvy, p[3] + dvz
    api.pushes[id] = p
  end
  return api
end
-- a car (box 4.6 x 1.9 m, 1500 kg) driving along +x at speed v from x0; the pushes change its velocity
function car(id, x0, y, v, mass)
  return {id = id, x = x0, y = y, vx = v, vy = 0, fx = 1, fy = 0, hl = 2.3, hw = .95, mass = mass or 1500}
end
-- drive: the car moves at its velocity (plus pushes) for seconds at 60 Hz; returns the frames run
function drive(K, api, cars, seconds, now)
  local dt = 1 / 60
  now = now or 0
  for f = 1, math.floor(seconds * 60) do
    now = now + dt
    for _, c in ipairs(cars) do
      local p = api.pushes[c.id]
      if p then c.vx, c.vy = c.vx + p[1], c.vy + p[2]; api.pushes[c.id] = nil end
      c.x, c.y = c.x + c.vx * dt, c.y + c.vy * dt
    end
    knock.step(K, cars, #cars, now, dt, api)
  end
  return now
end
'''

BIN = '/levels/west_coast_usa/art/shapes/objects/garbage_bin_a.dae'
BENCH = '/levels/east_coast_usa/art/shapes/clutter/clutter_city_bench_wood.dae'
TREE = '/levels/east_coast_usa/art/shapes/trees/trees_oak/tree_oak_large_a.dae'
PLANTER = '/levels/west_coast_usa/art/shapes/objects/planterbox.dae'


class KnockTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('knock = loadfile([[%s]])()' % KNOCK)
        self.lua.execute(HARNESS)

    def run_lua(self, code):
        return self.lua.execute(code)

    def test_table_classes(self):
        r = self.run_lua(f'''
          local a, b, c = knock.kindOf("{BIN}"), knock.kindOf("{BENCH}"), knock.kindOf("{TREE}")
          local sign = knock.kindOf("/art/shapes/garage_and_dealership/Clutter/italy_traf_sign_stop.dae")
          local caps = knock.kindOf("/art/shapes/garage_and_dealership/Clutter/italy_clutter_metal_bin.DAE")
          return a.class, b.class, c == nil, sign.class, caps ~= nil,
            knock.kindOf("/levels/east_coast_usa/art/shapes/clutter/clutter_city_bollard_concrete.dae") == nil
        ''')
        self.assertEqual(r, ('light', 'heavy', True, 'light', True, True))

    def test_every_kind_complete(self):
        bad = self.run_lua('''
          local bad = {}
          local need = {'mass', 'r', 'hx', 'hy', 'hz', 'e', 'lift', 'spin'}
          for name, k in pairs(knock.KINDS) do
            for _, f in ipairs(need) do if type(k[f]) ~= 'number' or k[f] < 0 then bad[#bad + 1] = name .. '.' .. f end end
            if k.class ~= 'light' and k.class ~= 'heavy' then bad[#bad + 1] = name .. '.class' end
          end
          -- every warm-up path names a known kind
          for _, s in ipairs(knock.SHAPES) do if not knock.kindOf(s) then bad[#bad + 1] = s end end
          return table.concat(bad, ',')
        ''')
        self.assertEqual(bad, '')

    def test_solid_not_registered(self):
        r = self.run_lua(f'''
          local K = knock.new()
          return knock.register(K, 't', "{TREE}", 0, 0, 0, 0, 1, 1) == nil, knock.count(K)
        ''')
        self.assertEqual(r, (True, 0))

    def test_swap_before_touch(self):
        # a bin 1 m off the car's line, 30 m ahead, car at 20 m/s: the item becomes debris before the
        # front reaches it, and is launched when the box touches it
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          knock.register(K, 't', "{BIN}", 30, .5, 0, 0, 1, 1)
          local c = car(7, 0, 0, 20)
          local dt, now, swappedAt, frontAt = 1 / 60, 0, nil, nil
          for f = 1, 200 do
            now = now + dt
            c.x = c.x + c.vx * dt
            knock.step(K, {{c}}, 1, now, dt, api)
            if not swappedAt and #api.hidden > 0 then swappedAt = c.x + c.hl end
            if K.DS[1] == knock.FLY then frontAt = c.x + c.hl; break end
          end
          return swappedAt, frontAt, K.stats.knocked
        ''')
        swapped_front, launch_front, knocked = r
        self.assertEqual(knocked, 1)
        # swapped within LEAD (0.25 s = 5 m) before the front reaches the bin's near edge (30 - 0.36)
        self.assertLess(swapped_front, 30 - .36)
        self.assertGreater(swapped_front, 30 - .36 - 5.5)
        self.assertGreater(launch_front, 30 - .36 - .5)

    def test_miss_lies_in_place(self):
        # the car passes 3 m beside the bin: no swap at all
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          knock.register(K, 't', "{BIN}", 30, 3.5, 0, 0, 1, 1)
          drive(K, api, {{car(1, 0, 0, 20)}}, 3)
          return #api.hidden, K.stats.knocked
        ''')
        self.assertEqual(r, (0, 0))

    def test_light_flies_heavy_falls(self):
        r = self.run_lua(f'''
          local out = {{}}
          for k, shape in ipairs({{"{BIN}", "{BENCH}"}}) do
            local K, api = knock.new(), fakeApi()
            knock.register(K, 't', shape, 40, 0, 0, 0, 1, 1)
            local c = car(1, 0, 0, 15)
            drive(K, api, {{c}}, 9)
            local s = 1
            out[k] = {{K.PX[s] - 40, K.DS[s], 15 - c.vx}}
          end
          return out[1][1], out[1][2], out[1][3], out[2][1], out[2][2], out[2][3]
        ''')
        bin_throw, bin_state, bin_dv, bench_throw, bench_state, bench_dv = r
        lie = self.run_lua('return knock.LIE')
        self.assertEqual((bin_state, bench_state), (lie, lie))
        # 54 km/h: the bin flies ~10-30 m, the bench a few metres past where the car first met it
        self.assertGreater(bin_throw, 8)
        self.assertLess(bin_throw, 45)
        self.assertGreater(bench_throw, 1)
        self.assertLess(bench_throw, bin_throw)
        # the car feels the 60 kg bench ~4 times more than the 15 kg bin
        self.assertGreater(bin_dv, .1)
        self.assertLess(bin_dv, .4)
        self.assertGreater(bench_dv, 3 * bin_dv)
        self.assertLess(bench_dv, 1.6)

    def test_fast_car_capped(self):
        # 150 km/h into a 120 kg planter: the velocity change is capped, the debris lands and sleeps
        r = self.run_lua('''
          local K, api = knock.new(), fakeApi()
          knock.register(K, 't', "/levels/west_coast_usa/art/shapes/objects/planterbox.dae", 80, 0, 0, 0, 1, 1)
          local c = car(1, 0, 0, 41.7)
          local push, most = api.push, 0
          api.push = function(id, x, y, z) most = math.max(most, math.sqrt(x * x + y * y)); push(id, x, y, z) end
          drive(K, api, {c}, 9)
          local s = 1
          local finite = K.PX[s] == K.PX[s] and math.abs(K.PX[s]) < 1e4 and K.PZ[s] >= 0
          return 41.7 - c.vx, K.DS[s], finite, K.PZ[s], most
        ''')
        dv, state, finite, z, most = r
        cap = self.run_lua('return knock.DV_MAX')
        # one step's change is capped; the first hit and the catch-up after it: about the
        # momentum of a 120 kg block at 150 km/h (3.4 m/s for 1500 kg), not more
        self.assertLessEqual(most, cap + 1e-9)
        self.assertGreater(dv, 1)
        self.assertLess(dv, 2 * cap)
        self.assertEqual(state, self.run_lua('return knock.LIE'))
        self.assertTrue(finite)
        # lies on a face: its centre at one of its half extents above the ground (0.25..0.46 m)
        self.assertLess(z, .5)

    def test_sleeping_costs_nothing(self):
        # 3000 knocked props lying: a step with a car far away touches no slot
        r = self.run_lua(f'''
          local K, api = knock.new{{cap = 5000}}, fakeApi()
          api.push = function() end   -- the car keeps its speed through 3000 bins
          for k = 1, 3000 do knock.register(K, 't', "{BIN}", k * 2, 0, 0, 0, 1, 1) end
          drive(K, api, {{car(1, -5, 0, 40)}}, 170)
          local placed = api.placed
          drive(K, api, {{car(2, 0, 5000, 40)}}, 1)
          return K.stats.knocked, K.stats.flying, api.placed - placed, K.nact
        ''')
        knocked, flying, placed, nact = r
        self.assertGreater(knocked, 2900)
        self.assertEqual((flying, placed, nact), (0, 0, 0))

    def test_cap_recycles_oldest(self):
        r = self.run_lua(f'''
          local K, api = knock.new{{cap = 10}}, fakeApi()
          api.push = function() end
          for k = 1, 30 do knock.register(K, 't', "{BIN}", 20 + k * 6, 0, 0, 0, 1, 1) end
          drive(K, api, {{car(1, 0, 0, 15)}}, 14)
          -- the first props knocked are gone (recycled), the last ones are debris
          return K.live, K.stats.recycled, K.STATE[1] == knock.GONE, K.STATE[30] == knock.DEBRIS, api.dropped
        ''')
        live, recycled, first_gone, last_debris, dropped = r
        self.assertLessEqual(live, 10)
        self.assertGreaterEqual(recycled, 15)
        self.assertTrue(first_gone)
        self.assertTrue(last_debris)
        self.assertEqual(dropped, recycled)

    def test_max_fly(self):
        # a car through 40 bins 1 m apart: never more than maxFly in the air at once
        r = self.run_lua(f'''
          local K, api = knock.new{{maxFly = 5}}, fakeApi()
          api.push = function() end   -- the car keeps its speed through the pile
          for k = 1, 40 do knock.register(K, 't', "{BIN}", 20 + k, 0, 0, 0, 1, 1) end
          local worst = 0
          local c = car(1, 0, 0, 20)
          local now = 0
          for f = 1, 300 do
            now = drive(K, api, {{c}}, 1 / 60, now)
            worst = math.max(worst, K.stats.flying)
          end
          return worst, K.stats.knocked
        ''')
        worst, knocked = r
        self.assertLessEqual(worst, 5)
        self.assertEqual(knocked, 40)

    def test_unregister_tile(self):
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          for k = 1, 5 do knock.register(K, 'a', "{BIN}", 30 + k * 4, 0, 0, 0, 1, 1) end
          for k = 1, 5 do knock.register(K, 'b', "{BIN}", 30 + k * 4, 50, 0, 0, 1, 1) end
          drive(K, api, {{car(1, 0, 0, 15)}}, 4)
          local live = K.live
          local n = knock.unregisterTile(K, 'a', api)
          local cellsLeft = 0
          for _, c in pairs(K.cells) do cellsLeft = cellsLeft + c.n end
          -- the freed ids are reused by the next registration
          local id = knock.register(K, 'c', "{BIN}", 0, 0, 0, 0, 1, 1)
          return live, n, K.live, knock.count(K), cellsLeft, api.dropped, id <= 5
        ''')
        self.assertEqual(r, (5, 5, 0, 6, 5, 5, True))

    def test_refused_hide_stays_standing(self):
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          knock.register(K, 't', "{BIN}", 30, 0, 0, 0, 1, 1)
          api.refuse[1] = true
          drive(K, api, {{car(1, 0, 0, 15)}}, 0.5)
          return K.STATE[1] == knock.STAND, K.live, K.stats.knocked, api.taken
        ''')
        self.assertEqual(r, (True, 0, 0, 0))

    def test_lying_knocked_again(self):
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          knock.register(K, 't', "{BIN}", 30, 0, 0, 0, 1, 1)
          local now = drive(K, api, {{car(1, 0, 0, 10)}}, 8)
          local x1 = K.PX[1]
          drive(K, api, {{car(2, x1 - 20, K.PY[1], 10)}}, 8, now)
          return K.PX[1] > x1 + 3, K.DS[1] == knock.LIE, api.taken
        ''')
        self.assertEqual(r, (True, True, 1))

    def test_deterministic(self):
        code = f'''
          local K, api = knock.new(), fakeApi()
          for k = 1, 20 do knock.register(K, 't', k % 2 == 0 and "{BIN}" or "{BENCH}", 20 + k * 3, (k % 3 - 1) * .8, 0, 0, 1, 1) end
          local c = car(1, 0, 0, 18)
          drive(K, api, {{c}}, 8)
          local h = c.vx
          for s = 1, K.dn do h = h + (K.PX[s] or 0) * 3 + (K.PY[s] or 0) * 7 + (K.DQW[s] or 0) end
          return string.format('%.9f', h)
        '''
        self.assertEqual(self.run_lua(code), self.run_lua(code))

    def test_no_garbage_while_flying(self):
        # 20 debris in the air and 5000 props registered: the steps allocate nothing
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          api.ray = function(x, y, z, dx, dy, len) return nil end   -- open space: the rays cost but hit nothing
          for k = 1, 5000 do knock.register(K, 't', "{BIN}", (k % 100) * 3, math.floor(k / 100) * 3 + 10, 0, 0, 1, 1) end
          for k = 1, 20 do knock.register(K, 'u', "{BIN}", 20 + k * 1.5, -200, 0, 0, 1, 1) end
          local c = car(1, 0, -200, 20)
          local list, now, dt = {{c}}, 0, 1 / 60
          for f = 1, 168 do now = now + dt; c.x = c.x + c.vx * dt; knock.step(K, list, 1, now, dt, api) end
          local flying = K.stats.flying
          -- the least of twenty windows of 8 steps in a row after one full collect: LuaJIT's trace
          -- recording allocates on its own while it compiles the loop, and the first steps after a
          -- collect regrow the Lua stack it shrank (~1 KB, 0 with jit.off after that); the steps
          -- themselves allocate nothing
          local grown = 1e9
          collectgarbage('collect'); collectgarbage('stop')
          for w = 1, 20 do
            local kb = collectgarbage('count')
            for f = 1, 8 do now = now + dt; c.x = c.x + c.vx * dt; knock.step(K, list, 1, now, dt, api) end
            grown = math.min(grown, collectgarbage('count') - kb)
          end
          collectgarbage('restart')
          return flying, grown
        ''')
        flying, grown = r
        self.assertGreater(flying, 5)
        self.assertLess(grown, 1.0)

    def test_side_hit_normal(self):
        # a bin hit by the car's left side while it moves sideways (sliding): thrown to the left
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          knock.register(K, 't', "{BIN}", 0, 5, 0, 0, 1, 1)
          local c = car(1, 0, 0, 0)
          c.vy = 12
          drive(K, api, {{c}}, 4)
          return K.PY[1] > 8, math.abs(K.PX[1]) < K.PY[1] / 2, c.vy < 12
        ''')
        self.assertEqual(r, (True, True, True))

    # --- no ghost props: any speed, a still car, one law from a push to a throw --------------------
    FIRST_TOUCH = '''
      -- the law of the first touch (knock.contact) of a car at speed v along +x with a prop of
      -- shape it has just armed, the bumper at the prop's face: the prop's velocity after it, its
      -- lift and spin, the car's velocity change
      function firstTouch(shape, v)
        local K, api = knock.new(), fakeApi()
        local id = knock.register(K, 't', shape, 10, 0, 0, 0, 1, 1)
        local c = car(1, 10 - 2.3 - K.SPEC[id].r - v * .1, 0, v)
        knock.step(K, {c}, 1, 0, 1 / 60, api)
        if K.STATE[id] ~= knock.DEBRIS then return end
        local s = K.SLOT[id]
        c.x = 10 - c.hl - K.SPEC[id].r
        c.dvx, c.dvy = 0, 0
        knock.contact(K, s, c, true)
        return math.sqrt(K.VX[s] ^ 2 + K.VY[s] ^ 2), K.VZ[s], math.sqrt(K.WX[s] ^ 2 + K.WY[s] ^ 2 + K.WZ[s] ^ 2), -c.dvx
      end
    '''

    def test_push_to_throw_is_continuous(self):
        # the closing speed from a crawl to 25 m/s in 0.05 m/s steps: the prop's speed, lift, spin
        # and the car's loss at the first touch change smoothly (no step anywhere), and grow with it
        self.lua.execute(self.FIRST_TOUCH)
        for shape in (BIN, BENCH, PLANTER):
            rows = self.run_lua(f'''
              local out = {{}}
              for k = 1, 500 do
                local v = k * .05
                local a, b, c, d = firstTouch("{shape}", v)
                out[k] = {{v, a, b, c, d}}
              end
              local worst, name = 0, ''
              for k = 2, #out do
                local dv = out[k][1] - out[k - 1][1]
                for f = 2, 5 do
                  local slope = math.abs(out[k][f] - out[k - 1][f]) / dv
                  if slope > worst then worst, name = slope, f .. '@' .. out[k][1] end
                end
              end
              return worst, name, out[17][2], out[17][5], out[500][2], out[500][5], out[17][3], out[500][3]
            ''')
            worst, where, prop_slow, car_slow, prop_fast, car_fast, lift_slow, lift_fast = rows
            # no jump: every quantity changes by at most 3x the speed step (a jump of even 0.3 m/s
            # between neighbours would read 6 here)
            self.assertLess(worst, 3, f'{shape} {where}')
            # at a crawl the prop goes with the bumper, barely lifted; fast it is thrown and lifted
            self.assertGreater(prop_slow, .5)
            self.assertLess(prop_slow, 1.2)
            self.assertLess(lift_slow, .02)
            self.assertGreater(prop_fast, 15)
            self.assertGreater(lift_fast, 10 * lift_slow + .5)
            self.assertGreater(car_fast, car_slow)

    def test_crawl_planter_is_an_obstacle_bin_is_shoved(self):
        # 3 km/h, coasting: the 120 kg planter stops the car within half a metre of travel, it barely
        # moves; the 15 kg bin is pushed along and aside, the car hardly feels it
        r = self.run_lua(f'''
          local out = {{}}
          for k, shape in ipairs({{"{PLANTER}", "{BIN}"}}) do
            local K, api = knock.new(), fakeApi()
            knock.register(K, 't', shape, 10, .2, 0, 0, 1, 1)
            local c = car(1, 10 - 2.3 - .6 - .3, 0, .83)
            local x0 = c.x
            drive(K, api, {{c}}, 8)
            local s = K.SLOT[1]
            local px, py = s and K.PX[s] or 10, s and K.PY[s] or .2
            out[k] = {{c.vx, c.x - x0, math.sqrt((px - 10) ^ 2 + (py - .2) ^ 2), K.stats.knocked}}
          end
          return out[1][1], out[1][2], out[1][3], out[1][4], out[2][1], out[2][2], out[2][3], out[2][4]
        ''')
        pv, ptravel, pmoved, pknocked, bv, btravel, bmoved, bknocked = r
        self.assertEqual((pknocked, bknocked), (1, 1))
        self.assertLess(pv, .05)
        self.assertLess(ptravel, .6 + .3 + .5)   # it had 0.3 m to the planter's face
        self.assertLess(pmoved, .5)
        self.assertGreater(bv, .7)
        self.assertGreater(bmoved, .5)

    def no_overlap(self, shapes, v, seconds, dt='1 / 60', y=0, x0=0):
        # every step of the drive: no prop's centre inside the car's box (shrunk by 5 cm)
        return self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          local shapes = {{{', '.join(f'"{s}"' for s in shapes)}}}
          for k = 1, 12 do knock.register(K, 't', shapes[(k - 1) % #shapes + 1], 15 + k * 6, {y} + (k % 3 - 1) * .4, 0, 0, 1, 1) end
          local c = car(1, {x0}, 0, {v})
          local dt, now, worst = {dt}, 0, 0
          for f = 1, math.floor({seconds} / dt) do
            now = now + dt
            local p = api.pushes[1]
            if p then c.vx, c.vy = c.vx + p[1], c.vy + p[2]; api.pushes[1] = nil end
            c.x, c.y = c.x + c.vx * dt, c.y + c.vy * dt
            knock.step(K, {{c}}, 1, now, dt, api)
            for id = 1, 12 do
              local s = K.SLOT[id]
              local x, y = s and K.PX[s] or K.X[id], s and K.PY[s] or K.Y[id]
              if K.STATE[id] ~= knock.GONE and not (s and K.PZ[s] > 2.5) then
                local u, w = math.abs(x - c.x), math.abs(y - c.y)
                if u < c.hl - .05 and w < c.hw - .05 then worst = worst + 1 end
              end
            end
          end
          return worst, K.stats.knocked, c.vx, c.x
        ''')

    def test_no_pass_through_at_a_crawl(self):
        # 0.3 m/s, a creeping car with the throttle held (its speed restored every step): it pushes
        # what it meets, nothing ends up inside it
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          knock.register(K, 't', "{PLANTER}", 6, 0, 0, 0, 1, 1)
          knock.register(K, 't', "{BIN}", 9, .5, 0, 0, 1, 1)
          local c = car(1, 0, 0, .3)
          local dt, now, inside = 1 / 60, 0, 0
          for f = 1, 60 * 40 do
            now = now + dt
            api.pushes[1] = nil
            c.vx = .3
            c.x = c.x + c.vx * dt
            knock.step(K, {{c}}, 1, now, dt, api)
            for id = 1, 2 do
              local s = K.SLOT[id]
              local x, y = s and K.PX[s] or K.X[id], s and K.PY[s] or K.Y[id]
              if math.abs(x - c.x) < c.hl - .05 and math.abs(y - c.y) < c.hw - .05 then inside = inside + 1 end
            end
          end
          return inside, K.stats.knocked, c.x
        ''')
        inside, knocked, x = r
        self.assertEqual(inside, 0)
        self.assertEqual(knocked, 2)
        self.assertGreater(x, 11)
        # coasting at a crawl into a row: never inside either
        worst, knocked, vx, x = self.no_overlap([PLANTER, BIN, BENCH], .3, 30, x0=21 - 2.3 - 1.2)
        self.assertEqual(worst, 0)
        self.assertGreaterEqual(knocked, 1)

    def test_no_pass_through_at_90(self):
        # 90 m/s (324 km/h) through a row of 12, at 60 and at 30 steps a second: every prop on the
        # line is knocked, none is ever inside the car
        for dt in ('1 / 60', '1 / 30'):
            worst, knocked, vx, x = self.no_overlap([BIN, BENCH, PLANTER], 90, 3, dt)
            self.assertEqual(worst, 0, dt)
            self.assertEqual(knocked, 12, dt)
            self.assertGreater(x, 15 + 12 * 6)

    def test_standing_inside_shoved_out_once(self):
        # a car spawned standing on a bin and a bench: each slides out of it once and stays out; the
        # still car is looked at once in STILL_EVERY steps, and costs no more touches after
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          knock.register(K, 't', "{BIN}", 1.5, .3, 0, 0, 1, 1)
          knock.register(K, 't', "{BENCH}", -1, -.5, 0, 0, 1, 1)
          local c = car(1, 0, 0, 0)
          local now = drive(K, api, {{c}}, 3)
          local contacts = K.stats.contacts
          drive(K, api, {{c}}, 5, now)
          local out = 0
          for id = 1, 2 do
            local s = K.SLOT[id]
            local x, y = K.PX[s], K.PY[s]
            local r = K.SPEC[id].r
            if math.abs(x - c.x) >= c.hl + r - .01 or math.abs(y - c.y) >= c.hw + r - .01 then out = out + 1 end
          end
          return out, K.stats.knocked, K.stats.contacts - contacts, c.vx, K.DS[K.SLOT[1]] == knock.LIE
        ''')
        out, knocked, later, vx, lying = r
        self.assertEqual((out, knocked, later), (2, 2, 0))
        self.assertLess(abs(vx), 1e-6)
        self.assertTrue(lying)

    def test_still_car_far_costs_nothing(self):
        # a still car next to nothing: no slot, no hide; near a prop (not in it) nothing happens either
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          for k = 1, 100 do knock.register(K, 't', "{BIN}", k * 3, 50, 0, 0, 1, 1) end
          drive(K, api, {{car(1, 0, 0, 0), car(2, 30, 50 - 3, 0)}}, 5)
          return #api.hidden, K.nact, K.stats.contacts, knock.near(K, 0, -50), knock.near(K, 30, 47)
        ''')
        self.assertEqual(r, (0, 0, 0, False, True))

    def test_velocity_the_position_does_not_bear_out(self):
        # a car standing still reads 46 m/s for a few steps (the script AI taking it over): it throws
        # nothing; once it really drives, the same props go
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          for k = 1, 6 do knock.register(K, 't', "{BIN}", 6 + k * 4, 0, 0, 0, 1, 1) end
          local c = car(1, 0, 0, 0)
          local dt, now = 1 / 60, 0
          for f = 1, 30 do
            now = now + dt
            c.vx = (f >= 10 and f <= 14) and 46 or 0
            knock.step(K, {{c}}, 1, now, dt, api)
          end
          local before = K.stats.knocked
          c.vx = 15
          drive(K, api, {{c}}, 3, now)
          return before, K.stats.knocked, K.stats.distrusted
        ''')
        before, after, distrusted = r
        self.assertEqual(before, 0)
        self.assertEqual(after, 6)
        self.assertGreaterEqual(distrusted, 5)

    def test_teleport_on_a_long_step_sweeps_no_far_cells(self):
        # a car teleported into the street (a hand-off) reads 5000 m/s for one step, and the step after
        # a hitch is 0.4 s long: that swept km of cells (558 ms in Kyiv, polish-02) and would arm props far
        # off its path. Now: nothing armed, few cells looked at; the same car driving for real knocks.
        r = self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          knock.register(K, 't', "{BIN}", 300, 0, 0, 0, 1, 1)
          knock.register(K, 't', "{BIN}", 20, 0, 0, 0, 1, 1)
          local cells = 0
          local raw = K.cells
          K.cells = setmetatable({{}}, {{__index = function(_, key) cells = cells + 1; return raw[key] end}})
          local c = car(3, 0, 0, 5000)
          knock.step(K, {{c}}, 1, 1, .4, api)
          local first, firstCells = K.stats.knocked, cells
          -- the next frame it stands (the spike is gone) and then drives at 15 m/s
          c.vx = 0
          knock.step(K, {{c}}, 1, 1 + 1 / 60, 1 / 60, api)
          cells = 0
          c.vx = 20
          knock.step(K, {{c}}, 1, 1 + 2 / 60, .4, api)
          local longStepCells = cells
          c.vx = 15
          drive(K, api, {{c}}, 3, 1 + 2 / 60)
          return first, firstCells, longStepCells, K.stats.knocked, K.STATE[1] == knock.STAND
        ''')
        first, first_cells, long_cells, knocked, far_standing = r
        self.assertEqual(first, 0)
        self.assertEqual(first_cells, 0)
        # REACH_MAX 80 m in 8 m cells: at most 21 x 21
        self.assertLessEqual(long_cells, 21 * 21)
        self.assertEqual(knocked, 1)
        self.assertTrue(far_standing)

    # --- debris vs walls ------------------------------------------------------------------------
    def wall_run(self, ray, v=15):
        return self.run_lua(f'''
          local K, api = knock.new(), fakeApi()
          {ray}
          knock.register(K, 't', "{BIN}", 10, 0, 0, 0, 1, 1)
          local c = car(1, 0, 0, {v})
          local maxX, maxS, now, after = -1e9, -1e9, 0, nil
          for f = 1, 60 * 6 do
            now = drive(K, api, {{c}}, 1 / 60, now)
            -- the driver brakes at the hit (the car is not what this is about: it has no wall)
            if K.stats.contacts > 0 then c.vx = 0 end
            local s = K.SLOT[1]
            if s and K.PX[s] then
              maxX = math.max(maxX, K.PX[s])
              maxS = math.max(maxS, K.PX[s] + K.PY[s])
              if not after and K.stats.walls > 0 then after = {{K.VX[s], K.VY[s]}} end
            end
          end
          local s = K.SLOT[1]
          after = after or {{0, 0}}
          return maxX, maxS, K.PX[s], K.PY[s], K.stats.walls, K.stats.rays, K.DS[s] == knock.LIE, after[1], after[2]
        ''')

    def test_wall_head_on(self):
        # a wall across the flight at x = 20: the bin never gets through, bounces back weakly, lies
        ray = '''api.ray = function(x, y, z, dx, dy, len)
            if dx <= 0 then return nil end
            local d = (20 - x) / dx
            if d >= 0 and d < len then return d end
          end'''
        maxX, _, x, y, walls, rays, lying, vx, vy = self.wall_run(ray)
        self.assertLessEqual(maxX, 20 - .25 + 1e-6)
        # back off it, slowly (WALL_E of ~18 m/s)
        self.assertLess(vx, 0)
        self.assertGreater(vx, -5)
        self.assertGreater(maxX, 19)
        self.assertGreaterEqual(walls, 1)
        self.assertTrue(lying)
        self.assertLess(x, 20)
        # without the wall it flies well past 20
        free = self.wall_run('api.ray = function() return nil end')
        self.assertGreater(free[0], 25)
        self.assertGreater(free[5], 0)

    def test_wall_oblique(self):
        # a wall along x + y = 26 (45 degrees): the bin glances off it towards -y, never crosses it
        ray = '''api.ray = function(x, y, z, dx, dy, len)
            local den = dx + dy
            if den <= 0 then return nil end
            local d = (26 - x - y) / den
            if d >= 0 and d < len then return d end
          end'''
        maxX, maxS, x, y, walls, rays, lying, vx, vy = self.wall_run(ray)
        self.assertLess(maxS, 26)
        self.assertGreaterEqual(walls, 1)
        # along the wall (towards +x, -y), slowed: the wall's direction came from the side rays
        self.assertLess(vy, -.5)
        self.assertGreater(vx, .5)
        self.assertLess(vx * vx + vy * vy, 8 ** 2)
        self.assertTrue(lying)

    def test_slope_is_not_a_wall(self):
        # ground rising 1 in 4 from x = 20 meets the ray as a wall would: the bin runs up it, no bounce
        ray = '''api.ray = function(x, y, z, dx, dy, len)
            if dx <= 0 then return nil end
            -- where the ray at height z meets the slope z = (x - 20) / 4
            local d = (20 + 4 * z - x) / dx
            if d >= 0 and d < len then return d end
          end
          api.ground = function(x, y, z) return x > 20 and (x - 20) / 4 or 0 end'''
        maxX, _, x, y, walls, rays, lying, vx, vy = self.wall_run(ray)
        self.assertEqual(walls, 0)
        self.assertGreater(maxX, 21)

    def test_step_time_48_flying(self):
        # 48 in the air with the ray stub: the step's own Lua cost (the game adds the engine calls)
        r = self.run_lua(f'''
          local K, api = knock.new{{maxFly = 48}}, fakeApi()
          api.ray = function() return nil end
          api.push = function() end
          for k = 1, 48 do knock.register(K, 't', "{BIN}", 20 + k * .5, (k % 2) * .6 - .3, 0, 0, 1, 1) end
          local c = car(1, 0, 0, 40)
          local now = drive(K, api, {{c}}, 1.05)
          local fl = K.stats.flying
          local t0 = os.clock()
          for f = 1, 60 do now = drive(K, api, {{c}}, 1 / 60, now) end
          return fl, (os.clock() - t0) / 60 * 1000
        ''')
        flying, ms = r
        self.assertGreater(flying, 40)
        self.assertLess(ms, .5)


if __name__ == '__main__':
    unittest.main()
