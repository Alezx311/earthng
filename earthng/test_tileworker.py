"""The worker pool's protocol (workers.lua in GE Lua, tileworker.lua in each worker's VM) under
LuaJIT: fake vehicles run the real tileworker.lua, each its own instance, with a generator that
only walks through a tile's stages. What is checked is who runs what and when a worker is free."""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r'

SETUP = '''
local workerSource, workersSource = ...
-- what a worker's VM and GE Lua have, as far as the two files use it
package.loaded.ffi = {new = function() return {} end}
written, log = {}, {}
local realOpen = io.open
io.open = function(path, mode)
  if mode == 'wb' then
    return {write = function(_, bytes) written[path] = bytes end, close = function() end}
  end
  return realOpen(path, mode)
end
jsonReadFile = function() return {blocks = {}, tileSize = 500, cellSize = 1000} end
serialize = function(v)
  local t = type(v)
  if t == 'table' then
    local parts = {}
    for k, x in pairs(v) do
      parts[#parts + 1] = '[' .. (type(k) == 'number' and tostring(k) or string.format('%q', k)) .. '] = ' .. serialize(x)
    end
    return '{' .. table.concat(parts, ', ') .. '}'
  end
  if t == 'string' then return string.format('%q', v) end
  return tostring(v)
end
-- a generator that only walks through a tile's stages; steps[key] counts its pauses by stage
steps = {}
package.loaded['ge/extensions/e2r/generator'] = {
  build = function(cells, i, j, options)
    local key = i .. '_' .. j
    local function work(stage, n)
      for _ = 1, n do
        steps[key .. ':' .. stage] = (steps[key .. ':' .. stage] or 0) + 1
        options.pause()
      end
      log[#log + 1] = key .. ':' .. stage
    end
    work('road', 3)
    if options.roadReady then options.roadReady({items = {}}, {}) end
    work('scene', 3)
    if options.sceneReady then options.sceneReady({items = {}}) end
    work('grass', 3)
    return {items = {}}, {items = {}}, nil, {}, {items = {}}
  end,
  resumeBuild = function(co)
    resumes = (resumes or 0) + 1
    return coroutine.resume(co)
  end}
package.loaded['ge/extensions/e2r/bridge_codec'] = {encode = function(value) return 'part' end}
package.loaded['ge/extensions/e2r/cellformat'] = {BLOCK = 8}
package.loaded['ge/extensions/e2r/tileshapes'] = {pack = function() return nil end}
loadfile = function() return assert(load(workerSource, '@tileworker.lua')) end
hptimer = function() return {stop = function() return 1 end, stopAndReset = function() return 1 end} end
vec3 = function(x, y, z) return {x = x, y = y, z = z} end
quat = function() return {} end
be = {}
FS = {findFiles = function() return {} end, removeFile = function() end}
-- a vehicle: its own instance of the worker and its own obj; a command runs when the frame steps
vehicles, toGame = {}, {}
local function vehicle(name)
  local v = {name = name, commands = {}, id = #vehicles + 100}
  v.obj = {queueGameEngineLua = function(_, source) toGame[#toGame + 1] = source end}
  function v:getID() return self.id end
  function v:setHidden() end
  function v:delete() end
  function v:queueLuaCommand(source) self.commands[#self.commands + 1] = source end
  vehicles[#vehicles + 1] = v
  return v
end
core_vehicles = {spawnNewVehicle = function(model, opts) return vehicle(opts.vehicleName) end}
workers = assert(load(workersSource, '@workers.lua'))()
-- One frame: GE Lua's update, then every vehicle runs what was queued to it, then GE Lua hears
-- what they said (at its next update). slice: the workers' ms a frame (0: a pause at every point).
function frame(landing, need)
  workers.update(landing, need)
  for _, v in ipairs(vehicles) do
    local commands = v.commands
    v.commands = {}
    e2rTileWorker, obj = v.worker, v.obj
    for _, source in ipairs(commands) do assert(load(source))() end
    v.worker = e2rTileWorker
  end
  local said = toGame
  toGame = {}
  for _, source in ipairs(said) do assert(load(source))() end
end
function settle(n) for _ = 1, n or 3 do frame(true) end end
-- everything a job has sent, by kind, in order
function kinds(id)
  local out = {}
  for _, part in ipairs(workers.parts(id) or {}) do out[#out + 1] = part.kind end
  return table.concat(out, ' ')
end
function job(i, j, park)
  return workers.submit({manifest = 'm', i = i, j = j, size = 500, options = {}, roadEarly = true, sceneEarly = true, park = park})
end
'''


class PoolTests(unittest.TestCase):
    def make(self, count=2):
        lua = LuaRuntime(unpack_returned_tuples=True)
        run = lua.eval('function(setup, a, b) return assert(load(setup, "@setup"))(a, b) end')
        run(SETUP, (ROOT / 'tileworker.lua').read_text(encoding='utf8'), (ROOT / 'workers.lua').read_text(encoding='utf8'))
        lua.execute(f'workers.SLICE_LANDING = 1000; workers.start({count}, 0, 0, 0); settle({count + 2})')
        return lua

    def test_a_job_without_a_stop_runs_to_its_end_and_frees_its_worker(self):
        lua = self.make(1)
        lua.execute('''
          local ready, free = workers.count()
          assert(ready == 1 and free == 1)
          local id = job(0, 0)
          assert(id and workers.free() == nil and job(1, 0) == nil, 'one job a worker')
          settle()
          assert(kinds(id) == 'road scene final done', 'parts')
          assert(workers.free() ~= nil and workers.stats().done == 1)
          assert(table.concat(log, ' ') == '0_0:road 0_0:scene 0_0:grass')
        ''')

    def test_a_parked_job_stops_after_its_scene_and_its_worker_takes_another(self):
        lua = self.make(1)
        lua.execute('''
          local first = job(0, 0, true)
          settle()
          -- the scene is out, the grass is not built, and the worker is free again
          assert(kinds(first) == 'road scene', kinds(first))
          assert(workers.parked(first) and workers.ready(first) and workers.free() ~= nil)
          assert(steps['0_0:grass'] == nil and workers.stats().parkedNow == 1)
          -- another tile goes through the same worker while the first stands parked
          local second = job(1, 0, true)
          assert(not workers.ready(first), 'its worker has a job in hand')
          settle()
          assert(kinds(second) == 'road scene' and workers.stats().parkedNow == 2)
          assert(steps['0_0:grass'] == nil and steps['1_0:grass'] == nil)
          -- the first one's grass is asked for: only it goes on, to its end
          assert(workers.go(first) and not workers.parked(first) and workers.free() == nil)
          settle()
          assert(kinds(first) == 'final done' and steps['0_0:grass'] == 3 and steps['1_0:grass'] == nil)
          assert(workers.free() ~= nil and workers.stats().parkedNow == 1)
          assert(table.concat(log, ' ') == '0_0:road 0_0:scene 1_0:road 1_0:scene 0_0:grass')
          -- the builds took turns in one VM through the generator's own resume (it keeps each
          -- build's scratch state): every slice after the VM's first
          assert(resumes == 2, resumes)
        ''')

    def test_a_new_job_goes_before_a_parked_one_told_to_go(self):
        lua = self.make(1)
        lua.execute('''
          local first = job(0, 0, true)
          settle()
          -- asked to go on in the same frame a new tile is handed over: the new tile first
          local second = job(1, 0, true)
          assert(workers.go(first))
          settle(4)
          assert(table.concat(log, ' ') == '0_0:road 0_0:scene 1_0:road 1_0:scene 0_0:grass', table.concat(log, ' '))
          assert(kinds(first) == 'road scene final done' and kinds(second) == 'road scene')
          assert(workers.parked(second) and workers.free() ~= nil)
        ''')

    def test_go_before_the_stop_means_no_stop(self):
        lua = self.make(1)
        lua.execute('''
          workers.SLICE_LANDING = 0     -- a pause at every point: the job takes many frames
          local id = job(0, 0, true)
          frame(true); frame(true)
          assert(steps['0_0:road'] and not steps['0_0:grass'])
          assert(workers.go(id) and workers.go(id), 'told once, true again')
          for _ = 1, 30 do frame(true) end
          assert(kinds(id) == 'road scene final done', 'parts')
          assert(workers.stats().parks == nil and workers.free() ~= nil)
        ''')

    def test_a_cancelled_parked_job_is_forgotten_and_leaves_its_worker_free(self):
        lua = self.make(1)
        lua.execute('''
          local first = job(0, 0, true)
          settle()
          assert(workers.parked(first))
          workers.cancel(first)
          assert(workers.stats().parkedNow == 0 and not workers.parked(first) and not workers.go(first))
          settle()
          assert(workers.free() ~= nil)
          -- nothing of it runs later
          local second = job(1, 0)
          settle()
          assert(kinds(second) == 'road scene final done' and steps['0_0:grass'] == nil)
          -- a job cancelled in the middle of its build frees the worker too
          workers.SLICE_LANDING = 0
          local third = job(2, 0, true)
          frame(true); frame(true)
          workers.cancel(third)
          for _ = 1, 4 do frame(true) end
          assert(workers.free() ~= nil and steps['2_0:grass'] == nil)
        ''')

    def test_a_free_older_than_the_last_command_does_not_free_the_worker(self):
        lua = self.make(1)
        lua.execute('''
          local first = job(0, 0, true)
          settle()
          -- the worker's "free" of the frame the next job is handed over in is on its way
          local second = job(1, 0, true)
          e2rWorkerSays(1, 0, 'free', 1, 1)
          workers.update(true)
          assert(workers.free() == nil, 'still busy: a command was sent after that answer')
          settle()
          assert(workers.free() ~= nil and kinds(second) == 'road scene')
        ''')

    def test_jobs_spread_over_the_pool_and_the_emptier_worker_is_taken_first(self):
        lua = self.make(2)
        lua.execute('''
          local a, b = job(0, 0, true), job(1, 0, true)
          assert(a and b and job(2, 0) == nil)
          settle()
          assert(workers.parked(a) and workers.parked(b))
          -- one worker's parked job ends: that worker is the one a new job goes to
          workers.go(a)
          settle()
          local c = job(2, 0, true)
          settle()
          local d = job(3, 0, true)
          settle()
          local per = {}
          for _, v in ipairs(vehicles) do per[#per + 1] = v.worker.parkedCount() end
          table.sort(per)
          assert(per[1] == 1 and per[2] == 2, per[1] .. ' ' .. per[2])
          assert(workers.stats().parkedNow == 3)
        ''')


if __name__ == '__main__':
    unittest.main()
