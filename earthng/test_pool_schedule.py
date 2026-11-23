"""native.lua's scheduler with a pool of workers: a near tile's job stops after its scene, and
its grass is asked for when its turn comes. The pool here is a model of workers.lua and
tileworker.lua (test_tileworker.py runs the real two): each worker runs one job at a time, a
step a frame, and a job with `park` stops in its worker once its scene is out."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_native  # noqa: E402  (by its module: its own tests are not run again from here)

POOL = '''
-- every: a worker takes a step of its job once in this many frames (a tile is 15 steps)
pool = {size = 3, jobs = {}, workers = {}, serial = 0, parks = 0, goes = 0, goBusy = {}, cancelled = 0,
  cancelledParked = 0, cancelledInGrass = 0, parkedMost = 0, built = {}, payloads = {}, every = 1, frame = 0}
for k = 1, pool.size do pool.workers[k] = {current = nil, parked = 0} end
local function emit(job, kind, value)
  pool.serial = pool.serial + 1
  local path = '/temp/part' .. pool.serial
  files[path], pool.payloads[path] = path, value
  job.parts[#job.parts + 1] = {kind = kind, a = path}
end
local function start(job)
  local args = job.args
  job.co = coroutine.create(function()
    local options = {}
    for name, value in pairs(args.options) do options[name] = value end
    options.pause = function() coroutine.yield() end
    if args.roadEarly then
      options.roadReady = function(road, nav) emit(job, 'road', {road = road, nav = nav}) end
      if args.sceneEarly then
        options.sceneReady = function(scene)
          emit(job, 'scene', {scene = scene})
          job.sceneOut = true
          if args.park and not job.go then coroutine.yield('park') end
          job.inGrass = true
        end
      end
    end
    local road, scene, far, nav, grass = stubGenerator.build({}, args.i, args.j, options)
    local final = {far = far, grass = grass, lows = {}}
    if not args.roadEarly then final.road, final.nav = road, nav end
    if not (args.roadEarly and args.sceneEarly) or not grass then final.scene = scene end
    emit(job, 'final', final)
    pool.built[args.i .. '_' .. args.j] = (pool.built[args.i .. '_' .. args.j] or 0) + 1
  end)
end
-- a frame of the pool: every worker with a job in hand takes a step of it
function pool.tick()
  pool.frame = pool.frame + 1
  if pool.frame % pool.every ~= 0 then return end
  for k, w in ipairs(pool.workers) do
    if not w.current then
      for id, job in pairs(pool.jobs) do
        if job.worker == k and job.parked and job.go then
          job.parked, w.current, w.parked = false, id, w.parked - 1
          break
        end
      end
    end
    local job = w.current and pool.jobs[w.current]
    if job then
      local ok, what = coroutine.resume(job.co)
      assert(ok, what)
      if coroutine.status(job.co) == 'dead' then
        job.state, w.current = 'done', nil
        job.parts[#job.parts + 1] = {kind = 'done'}
      elseif what == 'park' then
        job.parked, w.current, w.parked = true, nil, w.parked + 1
        pool.parks = pool.parks + 1
      end
    end
  end
  local parked = 0
  for _, w in ipairs(pool.workers) do parked = parked + w.parked end
  pool.parkedMost = math.max(pool.parkedMost, parked)
end
fakeWorkers = {
  count = function()
    local free = 0
    for _, w in ipairs(pool.workers) do if not w.current then free = free + 1 end end
    return pool.size, free
  end,
  free = function()
    local best
    for k, w in ipairs(pool.workers) do
      if not w.current and (not best or w.parked < pool.workers[best].parked) then best = k end
    end
    return best
  end,
  news = function(id)
    local job = pool.jobs[id]
    return job == nil or #job.parts > 0 or job.state ~= 'running'
  end,
  parts = function(id)
    local job = pool.jobs[id]
    if not job then return nil end
    local parts = job.parts
    job.parts = {}
    if job.state ~= 'running' then pool.jobs[id] = nil end
    return parts
  end,
  forget = function() end,
  stats = function() return {} end,
  parked = function(id) local job = pool.jobs[id]; return job ~= nil and job.parked == true end,
  ready = function(id)
    local job = pool.jobs[id]
    return job ~= nil and job.state == 'running' and not job.go and pool.workers[job.worker].current == nil
  end,
}
function fakeWorkers.submit(args)
  local k = fakeWorkers.free()
  if not k then return nil end
  local id = #pool.jobs + 1
  while pool.jobs[id] do id = id + 1 end
  pool.next = (pool.next or 0) + 1
  id = pool.next
  local job = {id = id, worker = k, args = args, parts = {}, state = 'running', key = args.i .. '_' .. args.j}
  pool.jobs[id] = job
  pool.workers[k].current = id
  start(job)
  return id
end
function fakeWorkers.go(id)
  local job = pool.jobs[id]
  if not job or job.state ~= 'running' then return false end
  if job.go then return true end
  job.go = true
  pool.goes = pool.goes + 1
  -- told while its worker has another job in hand: how far away the car was (s)
  if pool.workers[job.worker].current ~= nil and pool.workers[job.worker].current ~= id then
    local wanted = nativeModule.status().stream.wanted or {}
    pool.goBusy[#pool.goBusy + 1] = wanted[job.key] or -1
  end
  return true
end
function fakeWorkers.cancel(id)
  local job = pool.jobs[id]
  if not job then return end
  pool.cancelled = pool.cancelled + 1
  if job.parked then
    pool.cancelledParked = pool.cancelledParked + 1
    pool.workers[job.worker].parked = pool.workers[job.worker].parked - 1
  elseif job.inGrass then
    pool.cancelledInGrass = pool.cancelledInGrass + 1
  end
  if pool.workers[job.worker].current == id then pool.workers[job.worker].current = nil end
  pool.jobs[id] = nil
end
fakeCodec = {decode = function(bytes) return pool.payloads[bytes] end, viewSets = function() end}
local old = require
require = function(name)
  if name == 'ge/extensions/e2r/workers' then return fakeWorkers end
  if name == 'ge/extensions/e2r/bridge_codec' then return fakeCodec end
  return old(name)
end
'''


class PoolScheduleTests(unittest.TestCase):
    def make(self, park=True, every=1):
        lua, mod, cv = test_native.NativeTests().make(test_native.fixture_v2(10), prelude=POOL)
        lua.globals().nativeModule = mod
        lat, lon = test_native.geographic(1250, 4750)
        mod.land(cv(dict(seq=21, lat=lat, lon=lon)))
        mod.pool(True)
        if not park:
            lua.execute('''
              local function upvalue(f, name)
                for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
              end
              upvalue(upvalue(nativeModule.update, 'buildTile'), 'REMOTE').park = false
            ''')
        for _ in range(600):
            lua.globals().pool.tick()
            mod.update(.016, 2)
            if mod.status().job.state != 'working':
                break
        self.assertEqual(mod.status().job.state, 'ready')
        # the tiles of the landing were built whole (their grass is in their scene)
        self.landed = set(mod.status().stream.ready.keys())
        lua.globals().pool.every = every
        return lua, mod, cv

    def drive(self, lua, mod, cv, frames=1500, speed=60.0, x=1250.0):
        pool = lua.globals().pool
        most = 0
        for _ in range(frames):
            x += speed / 60
            mod.pose(cv(dict(x=x, y=4750, vx=speed, vy=0, state='driving')))
            pool.tick()
            mod.update(.016, 4)
            most = max(most, mod.status().stream.parkedGrass or 0)
        return x, most

    def stand(self, lua, mod, cv, x, frames=4000):
        pool = lua.globals().pool
        mod.pose(cv(dict(x=x, y=4750, vx=0, vy=0, state='driving')))
        for _ in range(frames):
            pool.tick()
            mod.update(.016, 4)

    def test_the_landing_goes_through_the_pool_without_a_stop(self):
        lua, mod, _ = self.make()
        pool = lua.globals().pool
        self.assertGreater(mod.pool().sent, 0)
        # a landing's tiles are built whole: nothing parks
        self.assertEqual(pool.parks, 0)
        self.assertEqual(mod.pool().fell, 0)

    def test_a_tile_stops_after_its_scene_and_its_grass_comes_in_its_turn(self):
        # workers slow enough to be busy most of the drive: a tile takes one of them 180 frames
        lua, mod, cv = self.make(every=12)
        pool = lua.globals().pool
        x, most = self.drive(lua, mod, cv)
        stream = mod.status().stream
        self.assertGreater(pool.parks, 0)
        self.assertGreater(pool.goes, 0)
        # the scheduler keeps more grass builds waiting than it would of its own (4), up to the pool's 12
        self.assertLessEqual(most, 12)
        self.assertLessEqual(pool.parkedMost, 12)
        # a parked job is told to go on while its worker is busy only when the car is nearly there
        for eta in pool.goBusy.values():
            self.assertLessEqual(eta, 8, 'grass asked of a busy worker for a tile still far away')
        # no job was thrown away in the middle of its grass by the scheduler's own limit
        self.assertEqual(stream.lost.grass, 0)
        # stopped: every near tile gets its grass, nothing stays parked, nothing failed
        self.stand(lua, mod, cv, x)
        stream = mod.status().stream
        self.assertEqual(stream.parkedGrass, 0)
        self.assertEqual(stream.grassLost, 0)
        self.assertEqual(len(list(stream.failed.keys())), 0)
        self.assertEqual(mod.pool().fell, 0)
        near = [key for key, due in stream.wanted.items() if due < 1e6 and key not in self.landed]
        self.assertTrue(near)
        for key in near:
            self.assertTrue(stream.scenes[key], key)
            self.assertTrue(stream.grass[key], key)
        parked = sum(w.parked for w in pool.workers.values())
        self.assertEqual(parked, 0)

    def test_roads_come_sooner_when_the_grass_waits(self):
        # the same drive with jobs built to their end (as until 24.11) and with the stop: the
        # frames a near road was missing under the car's nose
        def missing(park):
            lua, mod, cv = self.make(park, every=12)
            pool = lua.globals().pool
            x, late = 1250.0, 0
            for _ in range(1500):
                x += 1.0
                mod.pose(cv(dict(x=x, y=4750, vx=60, vy=0, state='driving')))
                pool.tick()
                mod.update(.016, 4)
                stream = mod.status().stream
                # the tile 4 s ahead
                ahead = f'{int((x + 240) // 500)}_{int(4750 // 500)}'
                if stream.ready[ahead] is None:
                    late += 1
            return late, pool.parks, pool.cancelledInGrass
        late_whole, parks_whole, _ = missing(False)
        late_parked, parks_parked, _ = missing(True)
        self.assertEqual(parks_whole, 0)
        self.assertGreater(parks_parked, 0)
        self.assertLessEqual(late_parked, late_whole)


if __name__ == '__main__':
    unittest.main()
