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


    def test_paints_match_the_shapes_and_left_hand_countries(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import flow_art
        lua = self.lua()
        self.assertEqual(list(lua.eval('flow.PAINTS').values()), [name for name, _ in flow_art.PAINTS])
        self.assertEqual(list(lua.eval('flow.SHARE').values()), flow_art.PAINT_SHARE)
        left = lua.eval('flow.leftHand')
        for country in ('uk-london-south-east', 'uk-northern-ireland', 'zanzibar'):
            self.assertTrue(left(country), country)
        for country in ('ukraine', 'kyiv-oblast', 'new-york', 'germany-berlin', None):
            self.assertFalse(left(country), country)

    HANDOFF_API = '''
      -- a fake game: real cars keep the pose they were given and drive straight on
      real = {}
      api = {nextId = 100}
      function api.spawn(paint) api.nextId = api.nextId + 1; real[api.nextId] = {paint = paint, active = false}; return api.nextId end
      function api.alive(id) return real[id] ~= nil end
      function api.activate(id, x, y, z, yaw, v)
        local r = real[id]
        r.active, r.x, r.y, r.hx, r.hy, r.v = true, x, y, math.cos(yaw), math.sin(yaw), v
      end
      function api.deactivate(id) real[id].active = false end
      function api.delete(id) real[id] = nil end
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
          local H = handoff.new{size = 8, paints = 8}
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
          for _, c in ipairs(flow.near(F, 1000, 0, handoff.ENTER_R - 5)) do if c.d > 12 then near = near + 1 end end
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
        self.assertLessEqual(near, 2)          # only flow cars by a real car (CLEAR_R) stay in the zone
        self.assertEqual(min_count, 60)        # real cars count towards the target
        self.assertEqual(real_after, 0)
        self.assertEqual(promoted_after, 0)
        self.assertEqual(back, promoted)

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

if __name__ == '__main__':
    unittest.main()
