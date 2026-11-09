"""The traffic flow (mod/lua/ge/extensions/e2r/flow.lua) in LuaJIT: cars keep their gaps, junctions
queue, obstacles stop the cars behind them, the graph follows the tiles."""
import time
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

FLOW = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/flow.lua'
HANDOFF = FLOW.with_name('handoff.lua')

# a grid of two-way streets, `n` x `n` crossings `step` m apart; segment ids 'h<i>_<j>' / 'v<i>_<j>'
GRID = '''
function grid(n, step, lanes, speed)
  local segs = {}
  local function add(id, a, b, x0, y0, x1, y1)
    local s = {id, a, b, lanes or '-+', speed or 13.9, 3.5, 1}
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
function overlaps(F)
  local bad = 0
  for _, link in pairs(F.links) do
    for _, list in ipairs(link.cars) do
      for k = 2, #list do
        if list[k].s < list[k - 1].s then bad = bad + 1000 end
        if list[k].s - list[k - 1].s < flow.LEN - 0.3 then bad = bad + 1 end
      end
    end
  end
  return bad
end
'''


class FlowTests(unittest.TestCase):
    def lua(self):
        lua = LuaRuntime()
        lua.globals().flow = lua.execute(FLOW.read_text(encoding='utf8'))
        lua.globals().handoff = lua.execute(HANDOFF.read_text(encoding='utf8'))
        lua.execute(GRID)
        return lua

    def test_cars_drive_without_overlap_and_keep_the_target(self):
        lua = self.lua()
        out = lua.execute('''
          local F = flow.new{seed = 7, paints = {1, 1, 1}}
          flow.sync(F, grid(6, 120))
          F.target = 120
          local worst, moving = 0, 0
          for t = 1, 1800 do
            flow.step(F, 1 / 30)
            worst = math.max(worst, overlaps(F))
          end
          for _, car in pairs(F.cars) do if car.v > 2 then moving = moving + 1 end end
          return {F.count, worst, moving, F.stats.spawned}
        ''')
        count, worst, moving, spawned = out[1], out[2], out[3], out[4]
        self.assertEqual(count, 120)
        self.assertEqual(worst, 0)
        self.assertGreater(moving, 30)
        self.assertGreaterEqual(spawned, 120)

    def test_a_busy_junction_queues_and_lets_cars_through_one_by_one(self):
        lua = self.lua()
        out = lua.execute('''
          -- four arms into one crossing, all one way in (and one way out to the east)
          local segs = {}
          local function road(id, a, b, x0, y0, x1, y1)
            local s = {id, a, b, '+', 13.9, 3.5, 1, x0, y0, 0, (x0 + x1) / 2, (y0 + y1) / 2, 0, x1, y1, 0}
            segs[id] = {s = s, x = (x0 + x1) / 2, y = (y0 + y1) / 2}
          end
          road('w', 'W', 'C', -300, 0, 0, 0)
          road('s', 'S', 'C', 0, -300, 0, 0)
          road('n', 'N', 'C', 0, 300, 0, 0)
          road('e', 'C', 'E', 0, 0, 600, 0)
          road('back', 'E', 'W2', 600, 0, 600, 300)
          local F = flow.new{seed = 3}
          flow.sync(F, segs)
          local through, seen = 0, {}
          for t = 1, 3600 do
            -- demand far over the capacity: every arm gets a car whenever its start has room
            for _, id in ipairs({'w+', 's+', 'n+'}) do flow.spawn(F, F.links[id], 3, 1, 8) end
            flow.step(F, 1 / 30)
            for _, car in ipairs(F.links['e+'].cars[1]) do
              if not seen[car.id] then seen[car.id] = true; through = through + 1 end
            end
          end
          local queued = #F.links['w+'].cars[1] + #F.links['s+'].cars[1] + #F.links['n+'].cars[1]
          return {through, queued, overlaps(F)}
        ''')
        through, queued, bad = out[1], out[2], out[3]
        # 120 s at one car per 1.9 s is 63 at most; from a stop each takes ~3 s (an all-way stop)
        self.assertLessEqual(through, 64)
        self.assertGreater(through, 25)
        self.assertGreater(queued, 60)
        self.assertEqual(bad, 0)

    def test_the_main_road_goes_on_and_the_side_road_waits_for_a_gap(self):
        lua = self.lua()
        out = lua.execute('''
          local segs = {}
          local function road(id, a, b, x0, y0, x1, y1, lanes, speed)
            local s = {id, a, b, lanes, speed, 3.5, 1, x0, y0, 0, (x0 + x1) / 2, (y0 + y1) / 2, 0, x1, y1, 0}
            segs[id] = {s = s, x = (x0 + x1) / 2, y = (y0 + y1) / 2}
          end
          road('w', 'W', 'C', -400, 0, 0, 0, '++', 16.7)
          road('e', 'C', 'E', 0, 0, 400, 0, '++', 16.7)
          road('s', 'S', 'C', 0, -120, 0, 0, '+', 11.1)
          local F = flow.new{seed = 9}
          flow.sync(F, segs)
          local stops, sideThrough, mainThrough, seen = 0, 0, 0, {}
          local function count(every)
            for t = 1, 1800 do
              if t % every == 0 then flow.spawn(F, F.links['w+'], 3, nil, 15) end
              if t % 180 == 0 then flow.spawn(F, F.links['s+'], 3, 1, 10) end
              flow.step(F, 1 / 30)
              for _, car in ipairs(F.links['w+'].cars[1]) do if car.v < 1 and car.s > 300 then stops = stops + 1 end end
              for _, list in ipairs(F.links['e+'].cars) do
                for _, car in ipairs(list) do
                  if not seen[car.id] then
                    seen[car.id] = true
                    if car.fromSide then sideThrough = sideThrough + 1 else mainThrough = mainThrough + 1 end
                  end
                end
              end
              for _, car in ipairs(F.links['s+'].cars[1]) do car.fromSide = true end
            end
          end
          count(300)   -- light main road: a car every 10 s
          local light = {stops, sideThrough, mainThrough}
          stops, sideThrough, mainThrough = 0, 0, 0
          count(25)    -- dense: two lanes, a car every 0.8 s
          return {light[1], light[2], light[3], stops, sideThrough, #F.links['s+'].cars[1], overlaps(F)}
        ''')
        light_stops, light_side, light_main, dense_stops, dense_side, side_queue, bad = list(out.values())
        self.assertEqual(light_stops, 0)       # main road cars never stop
        self.assertGreaterEqual(light_side, 6)  # side cars (one every 6 s) find gaps
        self.assertGreaterEqual(light_main, 3)
        self.assertGreater(side_queue, 2)      # a dense main road leaves the side road waiting
        self.assertGreater(dense_side, 0)      # but it still gets in, now and then
        self.assertEqual(bad, 0)

    def test_a_stopped_car_on_the_lane_holds_the_flow_behind_it(self):
        lua = self.lua()
        out = lua.execute('''
          local s = {'r', 'A', 'B', '+', 20, 3.5, 1, 0, 0, 0, 500, 0, 0, 1000, 0, 0}
          local F = flow.new{seed = 1}
          flow.sync(F, {r = {s = s, x = 500, y = 0}})
          local car = flow.spawn(F, F.links['r+'], 50, 1, 15)
          local lane = flow.laneOffset(F, F.links['r+'], 1)
          for t = 1, 900 do flow.step(F, 1 / 30, nil, nil, {{x = 400, y = -lane, vx = 0, vy = 0}}) end
          return {car.s, car.v}
        ''')
        s, v = out[1], out[2]
        self.assertLess(v, 0.5)
        self.assertGreater(s, 400 - 4.6 - 8)
        self.assertLess(s, 400 - 4.6)

    def test_lanes_sit_on_the_right_or_the_left_by_the_country(self):
        lua = self.lua()
        out = lua.execute('''
          local s = {'r', 'A', 'B', '-+', 20, 3.5, 1, 0, 0, 0, 100, 0, 0}
          local R, L = flow.new{}, flow.new{leftHand = true}
          flow.sync(R, {r = {s = s}}); flow.sync(L, {r = {s = s}})
          local _, yr = flow.pose(R, R.links['r+'], 50, 1)
          local _, yl = flow.pose(L, L.links['r+'], 50, 1)
          local _, yb = flow.pose(R, R.links['r-'], 50, 1)
          return {yr, yl, yb}
        ''')
        self.assertLess(out[1], -1)   # eastbound, right-hand: south of the axis
        self.assertGreater(out[2], 1)
        self.assertGreater(out[3], 1)  # westbound: north

    def test_cars_go_with_their_roads_and_come_back_elsewhere(self):
        lua = self.lua()
        out = lua.execute('''
          local F = flow.new{seed = 5}
          local all = grid(6, 120)
          flow.sync(F, all)
          F.target = 60
          for t = 1, 60 do flow.step(F, 1 / 30) end
          -- the western half of the town unloads
          local half = {}
          for id, seg in pairs(all) do if seg.x > 290 then half[id] = seg end end
          flow.sync(F, half)
          local stale = 0
          for _, car in pairs(F.cars) do
            if not F.links[car.link.id] then stale = stale + 1 end
            if car.next and F.links[car.next.id] ~= car.next then stale = stale + 1 end
          end
          for t = 1, 300 do flow.step(F, 1 / 30) end
          local west = 0
          for _, car in pairs(F.cars) do if not half[car.link.sid] then west = west + 1 end end
          return {stale, west, F.count}
        ''')
        self.assertEqual(out[1], 0)
        self.assertEqual(out[2], 0)
        self.assertEqual(out[3], 60)

    def test_thousand_car_target_can_be_reduced_without_overlaps(self):
        lua = self.lua()
        out = lua.execute('''
          local F = flow.new{seed = 11, paints = {1, 1}}
          flow.sync(F, grid(16, 100, '--++'))
          flow.setTarget(F, 1000)
          for t = 1, 600 do flow.step(F, 1 / 60, 750, 750) end
          local full, fullOverlaps = F.count, overlaps(F)
          flow.setTarget(F, 200)
          for t = 1, 120 do flow.step(F, 1 / 60, 750, 750) end
          return {full, fullOverlaps, F.count, overlaps(F)}
        ''')
        self.assertEqual((out[1], out[2]), (1000, 0))
        self.assertEqual((out[3], out[4]), (200, 0))

    def test_four_hundred_cars_step_in_a_fraction_of_a_frame(self):
        lua = self.lua()
        lua.execute('''
          F = flow.new{seed = 11, paints = {1, 1}}
          flow.sync(F, grid(16, 100, '--++'))
          F.target = 400
          for t = 1, 300 do flow.step(F, 1 / 60, 750, 750, {{x = 750, y = 748, vx = 10, vy = 0}}) end
        ''')
        start = time.perf_counter()
        lua.execute('for t = 1, 600 do flow.step(F, 1 / 60, 750, 750, {{x = 750, y = 748, vx = 10, vy = 0}}) end')
        ms = (time.perf_counter() - start) * 1000 / 600
        print(f'\nflow: 400 cars, {ms:.3f} ms a step')
        self.assertEqual(lua.eval('F.count'), 400)
        self.assertEqual(lua.eval('overlaps(F)'), 0)
        self.assertLess(ms, 2.0)


    def test_a_shape_points_along_its_lane_as_the_game_turns_it(self):
        lua = self.lua()
        out = lua.execute('''
          -- the game's rotation of a vector by a quaternion (lua/common/mathlib.lua LuaVec3:setRotate)
          local function rotate(qx, qy, qz, qw, x, y, z)
            local tx, ty, tz = 2 * (qy * z - qz * y), 2 * (qz * x - qx * z), 2 * (qx * y - qy * x)
            return x - tx * qw + (qy * tz - qz * ty), y - ty * qw + (qz * tx - qx * tz), z - tz * qw + (qx * ty - qy * tx)
          end
          local worst = 0
          for _, yaw in ipairs({0, .5, 1.2, 2.4, -.8, -2.9}) do
            for _, pitch in ipairs({0, .08, -.12}) do
              local qx, qy, qz, qw = flow.quat(yaw, pitch)
              local x, y, z = rotate(qx, qy, qz, qw, 1, 0, 0)
              local ex, ey, ez = math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), math.sin(pitch)
              worst = math.max(worst, math.abs(x - ex), math.abs(y - ey), math.abs(z - ez))
              -- the roof stays up
              local _, _, uz = rotate(qx, qy, qz, qw, 0, 0, 1)
              if uz < .9 then worst = 9 end
            end
          end
          return worst
        ''')
        self.assertLess(out, 1e-9)

    def test_paints_match_the_shapes_and_left_hand_countries(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import flow_art
        lua = self.lua()
        self.assertEqual(list(lua.eval('flow.PAINTS').values()), [name for name, _ in flow_art.PAINTS])
        self.assertEqual(list(lua.eval('flow.SHARE').values()), flow_art.PAINT_SHARE)
        self.assertEqual(list(lua.eval('flow.BODIES').values()), [name for name, _ in flow_art.BODIES])
        self.assertEqual(list(lua.eval('flow.BODY_SHARE').values()), flow_art.BODY_SHARE)
        left = lua.eval('flow.leftHand')
        for country in ('uk-london-south-east', 'uk-northern-ireland', 'zanzibar'):
            self.assertTrue(left(country), country)
        for country in ('ukraine', 'kyiv-oblast', 'new-york', 'germany-berlin', None):
            self.assertFalse(left(country), country)

    HANDOFF_API = '''
      -- a fake game: real cars keep the pose they were given and drive straight on
      real = {}
      api = {nextId = 100}
      function api.spawn(body) api.nextId = api.nextId + 1; real[api.nextId] = {body = body, active = false}; return api.nextId end
      function api.alive(id) return real[id] ~= nil end
      function api.activate(id, x, y, z, yaw, v, paint)
        local r = real[id]
        r.active, r.x, r.y, r.hx, r.hy, r.v, r.paint = true, x, y, math.cos(yaw), math.sin(yaw), v, paint
      end
      function api.deactivate(id) real[id].active = false end
      function api.delete(id) real[id] = nil end
      holds = 0
      function api.hold(id, on) real[id].held = on; if on then holds = holds + 1 end end
      function api.pose(id)
        local r = real[id]
        return r.x, r.y, r.hx * r.v, r.hy * r.v, r.hx, r.hy
      end
      function drive(dt)
        for _, r in pairs(real) do if r.active then r.x, r.y = r.x + r.hx * r.v * dt, r.y + r.hy * r.v * dt end end
      end
    '''

    def test_flow_cars_near_the_player_become_real_and_come_back(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        out = lua.execute('''
          local s = {'r', 'A', 'B', '--++', 13.9, 7, 1, 0, 0, 0, 1000, 0, 0, 2000, 0, 0}
          local F = flow.new{seed = 4, paints = {1, 1, 1, 1, 1, 1, 1, 1}}
          flow.sync(F, {r = {s = s, x = 1000, y = 0}})
          F.target = 60
          local H = handoff.new{size = 8, spare = 0}
          local now, maxReal, minCount = 0, 0, 1e9
          for t = 1, 600 do
            now = now + 1 / 30
            local obs = handoff.obstacles(H, api, {})
            flow.step(F, 1 / 30, 1000, 0, obs)
            handoff.step(H, flow, F, 1000, 0, now, api)
            drive(1 / 30)
            maxReal = math.max(maxReal, handoff.activeCount(H))
            if t > 60 then minCount = math.min(minCount, F.count) end
          end
          local pool, near = #H.pool, 0
          -- a flow car left in the zone away from the player: only by a real car, or with the pool all out
          local full = handoff.activeCount(H) == #H.pool
          for _, c in ipairs(flow.near(F, 1000, 0, handoff.ENTER_R - 5)) do
            local byReal = false
            for _, e in ipairs(H.pool) do
              if e.active then
                local x, y = api.pose(e.id)
                if (x - c.x) ^ 2 + (y - c.y) ^ 2 < 144 then byReal = true end
              end
            end
            if c.d > 12 and not byReal and not full then near = near + 1 end
          end
          local promoted = H.stats.promoted
          -- the player leaves: every real car goes back into the flow
          for t = 1, 60 do
            now = now + 1 / 30
            flow.step(F, 1 / 30, 1000, 3000, {})
            handoff.step(H, flow, F, 1000, 3000, now, api)
          end
          return {pool, maxReal, promoted, near, minCount, handoff.activeCount(H), F.promoted, H.stats.demoted + H.stats.dropped}
        ''')
        pool, max_real, promoted, near, min_count, real_after, promoted_after, back = list(out.values())
        self.assertEqual(pool, 8)
        self.assertEqual(max_real, 8)          # never more than the pool
        self.assertGreaterEqual(promoted, 8)
        self.assertEqual(near, 0)              # only flow cars by a real car (CLEAR_R) stay in the zone
        self.assertEqual(min_count, 60)        # real cars count towards the target
        self.assertEqual(real_after, 0)
        self.assertEqual(promoted_after, 0)
        self.assertEqual(back, promoted)

    def test_the_pool_shrinks_and_grows_with_the_setting(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        out = lua.execute('''
          local s = {'r', 'A', 'B', '--++', 13.9, 7, 1, 0, 0, 0, 1000, 0, 0, 2000, 0, 0}
          local F = flow.new{seed = 4, paints = {1, 1, 1, 1, 1, 1, 1, 1}}
          flow.sync(F, {r = {s = s, x = 1000, y = 0}})
          F.target = 60
          local H = handoff.new{size = 8, spare = 0}
          handoff.prewarm(H, api, 1000, 0)
          local now = 0
          local function run(steps)
            local most = 0
            for t = 1, steps do
              now = now + 1 / 30
              flow.step(F, 1 / 30, 1000, 0, handoff.obstacles(H, api, {}))
              handoff.step(H, flow, F, 1000, 0, now, api)
              drive(1 / 30)
              most = math.max(most, handoff.activeCount(H))
            end
            return most
          end
          local out = {run(300)}
          H.size = 2
          out[#out + 1] = run(30)
          out[#out + 1] = #H.pool
          local alive = 0
          for _ in pairs(real) do alive = alive + 1 end
          out[#out + 1] = alive
          out[#out + 1] = F.count
          H.size = 0
          run(30)
          out[#out + 1] = #H.pool
          out[#out + 1] = F.promoted
          H.size = 4
          handoff.prewarm(H, api, 1000, 0)
          out[#out + 1] = run(300)
          return out
        ''')
        full, after_shrink, pool, alive, count, pool_zero, promoted_zero, regrown = list(out.values())
        self.assertEqual(full, 8)
        self.assertLessEqual(after_shrink, 8)
        self.assertEqual((pool, alive, count), (2, 2, 60))   # the extra real cars went back into the flow
        self.assertEqual((pool_zero, promoted_zero), (0, 0))
        self.assertEqual(regrown, 4)

    def test_a_real_car_comes_back_on_its_lane_with_its_paint_and_speed(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        out = lua.execute('''
          local s = {'r', 'A', 'B', '-+', 13.9, 3.5, 1, 0, 0, 0, 1000, 0, 0}
          local F = flow.new{seed = 2}
          flow.sync(F, {r = {s = s, x = 500, y = 0}})
          local lane = flow.laneOffset(F, F.links['r-'], 1)
          F.promoted = 1
          -- westbound at 400 m, on the north half of the road
          local car = flow.put(F, 400, lane, -1, 0, 11, 6)
          local wrongWay = flow.put(F, 300, lane, 1, 0, 11, 6)
          return {car.link.id, car.lane, car.s, car.v, car.paint, F.promoted, wrongWay == nil}
        ''')
        link, lane, s, v, paint, promoted, wrong_way_dropped = list(out.values())
        self.assertEqual(link, 'r-')
        self.assertAlmostEqual(s, 600, delta=1)
        self.assertEqual((v, paint, promoted), (11, 6, 0))
        self.assertTrue(wrong_way_dropped)

    # a straight two-way road along x through the player at (0, 0); car(F, x, dir, v, body, paint)
    # puts a flow car at x heading +x (dir 1) or -x (dir -1)
    ROAD = '''
      function road()
        local s = {'r', 'A', 'B', '-+', 13.9, 3.5, 1, -1000, 0, 0, 0, 0, 0, 1000, 0, 0}
        local F = flow.new{seed = 5}
        flow.sync(F, {r = {s = s, x = 0, y = 0}})
        return F
      end
      function car(F, x, dir, v, body, paint)
        local link = F.links[dir > 0 and 'r+' or 'r-']
        return flow.spawn(F, link, dir > 0 and x + 1000 or 1000 - x, 1, v, paint or 1, nil, body or 1)
      end
    '''

    def test_stock_configs_have_the_flow_bodies(self):
        lua = self.lua()
        configs = (
            'ardente_ev bastion_base bx_base_coupe bx_sport_hatch covet_base etk800_base_sedan etk800_eu_high_wagon '
            'etk800_xc etkc_kc4 etki_eu_pre fullsize_taxi lansdale_eu_pre_van lansdale_facelift_mid '
            'legran_wagon_pre_s midsize_v6 pessima_tuner pickup_d15 roamer_ext_high sunburst2_eu_sedan_base '
            'tograc_ev van_cargobox van_passenger_facelift vivace_wide wendover_pre_high').split()
        body = lua.eval('handoff.bodyOf')
        got = {c: body(c) for c in configs}
        self.assertTrue(all(got.values()), got)
        expected = {'bastion_base': 1, 'covet_base': 2, 'vivace_wide': 2, 'bx_base_coupe': 2, 'etk800_xc': 3,
                    'roamer_ext_high': 3, 'lansdale_eu_pre_van': 3, 'pickup_d15': 3, 'van_cargobox': 4,
                    'etk800_eu_high_wagon': 1}
        for name, b in expected.items():
            self.assertEqual(got[name], b, name)
        self.assertEqual(body('vehicles/simple_traffic/van_delivery.pc'), 4)
        self.assertIsNone(body('robotvan_stock'))
        self.assertIsNone(body(None))
        # the stand-ins for a body the game's group lacks are of that body
        stock = lua.eval('handoff.STOCK')
        for b in range(1, 5):
            for name in stock[b].values():
                self.assertEqual(body(name), b, name)

    def test_the_pool_holds_the_flow_bodies_and_a_flow_car_takes_its_own_in_its_paint(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        lua.execute(self.ROAD)
        out = lua.execute('''
          local H = handoff.new{size = 8, spare = 0, bodies = {40, 30, 22, 8}}
          handoff.prewarm(H, api, 0, 0)
          local counts = {0, 0, 0, 0}
          for _, e in ipairs(H.pool) do counts[e.body] = counts[e.body] + 1 end
          local F = road()
          -- a white van and a red hatch coming at the player
          car(F, -70, 1, 12, 4, 1)
          car(F, 60, -1, 12, 2, 6)
          handoff.step(H, flow, F, 0, 0, 1, api)
          local got = {}
          for _, e in ipairs(H.pool) do
            if e.active then got[#got + 1] = {real[e.id].body, real[e.id].paint, e.flowBody} end
          end
          table.sort(got, function(a, b) return a[1] < b[1] end)
          return {counts, got, H.stats.mismatched}
        ''')
        counts, got, mismatched = list(out.values())
        self.assertEqual(list(counts.values()), [3, 2, 2, 1])
        self.assertEqual([list(g.values()) for g in got.values()], [[2, 6, 2], [4, 1, 4]])
        self.assertEqual(mismatched, 0)

    def test_a_flow_car_waits_for_its_own_body_until_it_comes_near(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        lua.execute(self.ROAD)
        out = lua.execute('''
          local H = handoff.new{size = 2, bodies = {1}}
          handoff.prewarm(H, api, 0, 0)
          local F = road()
          local van = car(F, -80, 1, 3, 4, 2)
          handoff.step(H, flow, F, 0, 0, 1, api)
          local before = handoff.activeCount(H)
          van.s = 1000 - 30
          handoff.step(H, flow, F, 0, 0, 2, api)
          return {before, handoff.activeCount(H), H.stats.mismatched}
        ''')
        self.assertEqual(list(out.values()), [0, 1, 1])

    def test_the_car_that_will_come_nearest_goes_first_and_one_driving_away_stays(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        lua.execute(self.ROAD)
        out = lua.execute('''
          local H = handoff.new{size = 1}
          handoff.prewarm(H, api, 0, 0)
          local F = road()
          car(F, 40, 1, 10)      -- past the player, driving away
          car(F, 70, 1, 0)       -- standing ahead
          car(F, -85, 1, 14)     -- coming up fast from behind
          handoff.step(H, flow, F, 0, 0, 1, api)
          local x = real[H.pool[1].id].x
          -- with free cars in the pool the one driving away is still left alone
          local H2 = handoff.new{size = 3}
          handoff.prewarm(H2, api, 0, 0)
          local F2 = road()
          car(F2, 40, 1, 10)
          handoff.step(H2, flow, F2, 0, 0, 1, api)
          return {x, handoff.activeCount(H2)}
        ''')
        x, away = list(out.values())
        self.assertAlmostEqual(x, -85, delta=1)
        self.assertEqual(away, 0)

    def test_a_car_about_to_reach_the_player_takes_a_far_real_car_going_away(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        lua.execute(self.ROAD)
        out = lua.execute('''
          local H = handoff.new{size = 1}
          handoff.prewarm(H, api, 0, 0)
          local F = road()
          car(F, -60, 1, 10, 1, 3)
          handoff.step(H, flow, F, 0, 0, 1, api)
          -- the real car drives on to 100 m ahead, away from the player; another comes up behind
          local r = real[H.pool[1].id]
          r.x = 100
          car(F, -40, 1, 12, 1, 5)
          handoff.step(H, flow, F, 0, 0, 2, api)
          local back = 0
          for _, c in ipairs(flow.near(F, 100, 0, 10)) do if c.car.paint == 3 then back = back + 1 end end
          return {H.stats.preempted, real[H.pool[1].id].x, real[H.pool[1].id].paint, back, F.promoted}
        ''')
        preempted, x, paint, back, promoted = list(out.values())
        self.assertEqual(preempted, 1)
        self.assertAlmostEqual(x, -40, delta=1)
        self.assertEqual(paint, 5)
        self.assertEqual(back, 1)          # the one that gave its place drives on in the flow
        self.assertEqual(promoted, 1)

    def test_an_urgent_car_takes_a_far_real_car_of_its_body_before_a_free_one_of_another(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        lua.execute(self.ROAD)
        out = lua.execute('''
          -- a sedan and a van in the pool
          local H = handoff.new{size = 2, bodies = {1, 0, 0, 1}}
          handoff.prewarm(H, api, 0, 0)
          local F = road()
          car(F, -60, 1, 10, 4, 3)
          handoff.step(H, flow, F, 0, 0, 1, api)
          -- the van drives on away; another van comes right up behind the player
          for _, e in ipairs(H.pool) do if e.active then real[e.id].x = 100 end end
          car(F, -30, 1, 12, 4, 5)
          handoff.step(H, flow, F, 0, 0, 2, api)
          local bodies = {}
          for _, e in ipairs(H.pool) do if e.active then bodies[#bodies + 1] = real[e.id].body end end
          return {H.stats.preempted, H.stats.mismatched, #bodies, bodies[1]}
        ''')
        self.assertEqual(list(out.values()), [1, 0, 1, 4])

    def test_a_real_car_with_no_lane_under_it_stays_real_rather_than_vanish(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        lua.execute(self.ROAD)
        out = lua.execute('''
          local H = handoff.new{size = 1}
          handoff.prewarm(H, api, 0, 0)
          local F = road()
          car(F, -60, 1, 10)
          handoff.step(H, flow, F, 0, 0, 1, api)
          -- it left the road (a field 140 m away, driving away)
          local r = real[H.pool[1].id]
          r.x, r.y = 0, 140
          r.hx, r.hy = 0, 1
          handoff.step(H, flow, F, 0, 0, 2, api)
          local still = handoff.activeCount(H)
          r.y = 200
          handoff.step(H, flow, F, 0, 0, 3, api)
          return {still, handoff.activeCount(H), H.stats.dropped, F.promoted}
        ''')
        self.assertEqual(list(out.values()), [1, 0, 1, 0])

    def test_spares_wait_in_the_pool_and_never_drive_over_the_setting(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        out = lua.execute('''
          local s = {'r', 'A', 'B', '--++', 13.9, 7, 1, 0, 0, 0, 1000, 0, 0, 2000, 0, 0}
          local F = flow.new{seed = 4, bodies = {40, 30, 22, 8}}
          flow.sync(F, {r = {s = s, x = 1000, y = 0}})
          F.target = 60
          local H = handoff.new{size = 8, bodies = {40, 30, 22, 8}}
          handoff.prewarm(H, api, 1000, 0)
          local pool, now, most, total = #H.pool, 0, 0, 0
          local function run(steps)
            local m = 0
            for t = 1, steps do
              now = now + 1 / 30
              flow.step(F, 1 / 30, 1000, 0, handoff.obstacles(H, api, {}))
              handoff.step(H, flow, F, 1000, 0, now, api)
              drive(1 / 30)
              m = math.max(m, handoff.activeCount(H))
            end
            return m
          end
          most = run(600)
          H.size = 2
          local after = run(30)
          return {pool, most, H.stats.promoted, H.stats.mismatched, #H.pool, after, F.count}
        ''')
        pool, most, promoted, mismatched, pool_after, after, count = list(out.values())
        self.assertEqual(pool, 12)
        self.assertEqual(most, 8)
        self.assertGreater(promoted, 8)
        self.assertLessEqual(mismatched, promoted // 4)
        self.assertEqual((pool_after, after, count), (3, 2, 60))

    def test_at_speed_an_oncoming_car_is_made_real_early_and_kept_while_it_comes(self):
        lua = self.lua()
        lua.execute(self.HANDOFF_API)
        lua.execute(self.ROAD)
        out = lua.execute('''
          local H = handoff.new{size = 2}
          handoff.prewarm(H, api, 0, 0)
          local F = road()
          car(F, 150, -1, 14)
          -- the player drives at 30 m/s towards it
          handoff.step(H, flow, F, 0, 0, 1, api, 30, 0)
          local first = handoff.activeCount(H)
          handoff.step(H, flow, F, 0, 0, 2, api, 30, 0)
          local kept = handoff.activeCount(H)
          -- standing still the same car is too far to matter
          local H2 = handoff.new{size = 2}
          handoff.prewarm(H2, api, 0, 0)
          local F2 = road()
          car(F2, 150, -1, 14)
          handoff.step(H2, flow, F2, 0, 0, 1, api)
          return {first, kept, handoff.activeCount(H2)}
        ''')
        self.assertEqual(list(out.values()), [1, 1, 0])


    # a crossing of two two-way streets at C (0, 0), arms 300 m; `extra` adds segments
    CROSS = '''
      function crossing(extra)
        local segs = {}
        local function road(id, a, b, x0, y0, x1, y1, lanes, speed)
          local s = {id, a, b, lanes or '-+', speed or 13.9, 3.5, 1, x0, y0, 0, (x0 + x1) / 2, (y0 + y1) / 2, 0, x1, y1, 0}
          segs[id] = {s = s, x = (x0 + x1) / 2, y = (y0 + y1) / 2}
        end
        road('w', 'W', 'C', -300, 0, 0, 0, '--++', 16.7)
        road('e', 'C', 'E', 0, 0, 300, 0, '--++', 16.7)
        road('s', 'S', 'C', 0, -300, 0, 0)
        road('n', 'C', 'N', 0, 0, 0, 300)
        if extra then extra(road) end
        return segs
      end
    '''

    def test_a_lit_crossing_lets_its_two_roads_take_turns(self):
        lua = self.lua()
        lua.execute(self.CROSS)
        out = lua.execute('''
          local F = flow.new{seed = 6}
          flow.sync(F, crossing(), nil, nil, {{2, 3}})
          local inbound = {['w+'] = 'main', ['e-'] = 'main', ['s+'] = 'side', ['n-'] = 'side'}
          local was, through, wrong, axes = {}, {main = 0, side = 0}, 0, {}
          for id in pairs(inbound) do axes[id] = F.links[id].light.axis end
          for t = 1, 30 * 240 do
            for id in pairs(inbound) do flow.spawn(F, F.links[id], 3, nil, 10) end
            flow.step(F, 1 / 30)
            for id, car in pairs(F.cars) do
              local from = was[id]
              if from and inbound[from.id] and car.link ~= from then
                through[inbound[from.id]] = through[inbound[from.id]] + 1
                -- never while the other road has green
                local other = flow.colour(from.light.c.offset, 1 - from.light.axis, F.now)
                if other == 'green' then wrong = wrong + 1 end
              end
              was[id] = car.link
            end
          end
          local waiting = 0
          for id in pairs(inbound) do waiting = waiting + #F.links[id].cars[1] end
          return {F.crossings, axes['w+'], axes['e-'], axes['s+'], axes['n-'], through.main, through.side, wrong, overlaps(F)}
        ''')
        crossings, w, e, s, n, main, side, wrong, bad = list(out.values())
        self.assertEqual(crossings, 1)
        self.assertEqual(w, e)                 # the street's two ways share a phase
        self.assertEqual(s, n)
        self.assertNotEqual(w, s)
        # 240 s is four cycles of 24 s green a road: both roads get through, in turns
        self.assertGreater(main, 40)
        self.assertGreater(side, 20)
        self.assertEqual(wrong, 0)
        self.assertEqual(bad, 0)

    def test_flow_and_real_cars_follow_the_displayed_signal_phase(self):
        lua = self.lua()
        lua.globals().signals = lua.execute(FLOW.with_name('signals.lua').read_text(encoding='utf8'))
        lua.execute(self.CROSS)
        out = lua.execute('''
          local F = flow.new{}
          local scene = {
            {road = 'w', x = -10, y = 0, dx = 1, dy = 0, group = 4},
            {road = 'e', x = 10, y = 0, dx = -1, dy = 0, group = 4},
            {road = 's', x = 0, y = -10, dx = 0, dy = 1, group = 5},
            {road = 'n', x = 0, y = 10, dx = 0, dy = -1, group = 5},
          }
          flow.sync(F, crossing(), nil, nil, {{2, 3}}, scene)
          local mismatch, heldWrong, seen = 0, 0, {}
          local lane = flow.laneOffset(F, F.links['w+'], 1)
          -- The flow may be started long after the scene and can run in slow motion. Its local
          -- simulation clock is deliberately very different from the light's world clock.
          for now = 1000, 1060, .5 do
            signals.step(now, false)
            flow.step(F, .01, nil, nil, nil, now, signals.current)
            for _, entry in ipairs({{'w+', 4}, {'e-', 4}, {'s+', 5}, {'n-', 5}}) do
              if flow.lightOf(F, F.links[entry[1]]) ~= signals.colour(entry[2], now) then
                mismatch = mismatch + 1
              end
            end
            local colour = signals.colour(4, now)
            seen[colour] = true
            local held = flow.holdAt(F, -20, -lane, 1, 0, 8)
            if held ~= (colour ~= 'green') then heldWrong = heldWrong + 1 end
          end
          return {mismatch, heldWrong, seen.green, seen.yellow, seen.red}
        ''')
        self.assertEqual(list(out.values()), [0, 0, True, True, True])

    def test_signal_updates_match_the_display_and_missing_scene_has_a_fallback(self):
        lua = self.lua()
        lua.globals().signals = lua.execute(FLOW.with_name('signals.lua').read_text(encoding='utf8'))
        lua.execute(self.CROSS)
        out = lua.execute('''
          local F = flow.new{}
          local scene = {{road = 'w', x = -10, y = 0, dx = 1, dy = 0, group = 0}}
          flow.sync(F, crossing(), nil, nil, {{2, 3}}, scene)
          signals.step(23.9, false)
          flow.step(F, .01, nil, nil, nil, 23.9, signals.current)
          local green = flow.lightOf(F, F.links['w+'])
          -- The clock crosses the boundary, but the displayed lens has not updated yet.
          signals.step(24.01, false)
          flow.step(F, .01, nil, nil, nil, 24.01, signals.current)
          local stillGreen = flow.lightOf(F, F.links['w+'])
          signals.step(24.11, false)
          flow.step(F, .01, nil, nil, nil, 24.11, signals.current)
          local yellow = flow.lightOf(F, F.links['w+'])
          -- An unloaded scene restores the inferred junction behaviour, without a nil phase.
          flow.sync(F, crossing(), nil, nil, {{2, 3}}, {})
          local fallback = flow.lightOf(F, F.links['w+'])
          return {green, stillGreen, yellow, fallback ~= nil}
        ''')
        self.assertEqual(list(out.values()), ['green', 'green', 'yellow', True])

    def test_lights_light_the_junction_they_stand_at(self):
        lua = self.lua()
        lua.execute(self.CROSS)
        out = lua.execute('''
          local function lit(lights, extra)
            local F = flow.new{}
            flow.sync(F, crossing(extra), nil, nil, lights)
            return F.crossings
          end
          -- a dual carriageway: a second junction D 20 m east, joined to C by a short road
          local function dual(road)
            road('cd', 'C', 'D', 0, 0, 20, 0)
            road('d', 'D', 'X', 20, 0, 20, -300)
            road('d2', 'D', 'Y', 20, 0, 20, 300)
          end
          local F = flow.new{}
          flow.sync(F, crossing(dual), nil, nil, {{0, 4}, {22, -3}})
          return {
            lit({{-30, -4}}),          -- on the approach, 30 m before the junction
            lit({{-120, -4}}),         -- too far up the road
            lit({{-150, 0}}),          -- in the middle of a road: no junction there
            F.crossings, F.links['cd+'].light == true, F.links['w+'].light ~= true and F.links['w+'].light ~= nil,
          }
        ''')
        approach, far, middle, dual_crossings, inner_free, outer_lit = list(out.values())
        self.assertEqual((approach, far, middle), (1, 0, 0))
        self.assertEqual(dual_crossings, 1)
        self.assertTrue(inner_free)
        self.assertTrue(outer_lit)

    def test_a_real_car_is_held_at_a_red_light(self):
        lua = self.lua()
        lua.execute(self.CROSS)
        out = lua.execute('''
          local F = flow.new{}
          flow.sync(F, crossing(), nil, nil, {{2, 3}})
          local link = F.links['w+']
          local light = link.light
          local function at(colour)
            -- a moment of the cycle with this colour for the western approach
            for t = 0, flow.CYCLE, .5 do
              if flow.colour(light.c.offset, light.axis, t) == colour then return t end
            end
          end
          local lane = flow.laneOffset(F, link, 1)
          local out = {}
          for _, c in ipairs({'red', 'green'}) do
            F.now = at(c)
            out[#out + 1] = flow.holdAt(F, -20, -lane, 1, 0, 8)      -- 20 m before the line at 8 m/s
            out[#out + 1] = flow.holdAt(F, -200, -lane, 1, 0, 8)     -- still far
          end
          F.now = at('red')
          out[#out + 1] = flow.holdAt(F, -20, lane, -1, 0, 8)        -- the other way, away from C
          return out
        ''')
        self.assertEqual(list(out.values()), [True, False, False, False, False])

    def test_real_cars_at_a_red_light_stand_and_go_on_green(self):
        lua = self.lua()
        lua.execute(self.CROSS)
        lua.execute(self.HANDOFF_API)
        out = lua.execute('''
          local F = flow.new{seed = 8}
          flow.sync(F, crossing(), nil, nil, {{2, 3}})
          F.target = 40
          local H = handoff.new{size = 8, paints = 1}
          -- the player stands by the crossing; a held real car does not move
          local now, heldMoved, released = 0, 0, 0
          for t = 1, 30 * 120 do
            now = now + 1 / 30
            flow.step(F, 1 / 30, -40, 10, handoff.obstacles(H, api, {}))
            handoff.step(H, flow, F, -40, 10, now, api)
            for _, r in pairs(real) do
              if r.active and not r.held then r.x, r.y = r.x + r.hx * r.v / 30, r.y + r.hy * r.v / 30 end
              if r.wasHeld and not r.held then released = released + 1 end
              r.wasHeld = r.held
            end
          end
          return {holds, released, H.stats.promoted}
        ''')
        holds, released, promoted = list(out.values())
        self.assertGreater(promoted, 0)
        self.assertGreater(holds, 0)       # real cars on a red approach were held
        self.assertGreater(released, 0)    # and let go when it turned green

if __name__ == '__main__':
    unittest.main()
