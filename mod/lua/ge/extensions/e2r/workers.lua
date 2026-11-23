-- The pool of tile workers: small bodiless vehicles (vehicles/e2r_worker) whose Lua VMs build
-- tiles off the game thread (tileworker.lua). The engine runs each vehicle's Lua on its own
-- thread beside the frame; GE Lua here only spawns the pool, hands out jobs, gives every busy
-- worker its slice of the frame and collects what they wrote. Knowledge/docs/FAST_TILES.md.
--
-- A worker must stay active: a vehicle switched off (setActive 0) drops the commands queued to
-- it. It is hidden, belongs to no traffic, and the player cannot switch into it.
local M = {}

local MODEL = 'e2r_worker'
local SCRIPT = '/lua/ge/extensions/e2r/tileworker.lua'
local NOTIFY = 'e2rWorkerSays'
-- ms of a frame a worker builds for. The frame waits for a vehicle's Lua, and about three times
-- the slice when that Lua allocates as the generator does (research/fast-tiles, p6 and p9): 4 ms
-- took a 9 ms frame to 17. While the player waits for a landing the frame is not what matters.
-- So the slice follows what is owed (native.lua M.poolNeed): 6 ms while a road is due within
-- seconds, 4 while near tiles are owed, 2 when only the far ring is left to fill. A town driven
-- at 58 km/h with 4 ms throughout had the workers busy nearly all the time and the frame no
-- shorter than without them (24.7 against 24.4 ms, drive-pool-5).
M.SLICE, M.SLICE_LANDING = 4, 40
M.SLICES = {[0] = 2, [1] = 4, [2] = 6}
M.FOLDER = '/temp/e2r_tiles'

-- [k] = {veh, id, state = 'loading' | 'idle' | 'busy', sent = the commands sent to it (a job, a
-- go, a cancel), parked = the jobs it holds stopped after their scene}. A worker is idle from
-- its "free" that counts every command sent (tileworker.lua): it has nothing to run then,
-- whatever it holds parked.
local pool = {}
local byId = {}        -- vehicle id -> k
local jobs = {}        -- [job id] = {worker, parts = {}, state = 'running' | 'done' | 'error', args}
local inbox = {}
local nextJob, session, wanted, at = 0, nil, 0, nil
local stats = {spawned = 0, spawnMs = 0, jobs = 0, done = 0, failed = 0, cancelled = 0, busyMs = 0, wallMs = 0,
  longest = 0, parts = 0, over = {}}
local doomed = {}      -- files to remove, a few frames after their objects went

rawset(_G, NOTIFY, function(worker, id, kind, a, bytes, ms, detail)
  inbox[#inbox + 1] = {worker = worker, id = id, kind = kind, a = a, bytes = bytes, ms = ms, detail = detail}
end)

local function exists() return rawget(_G, 'core_vehicles') ~= nil and rawget(_G, 'be') ~= nil end

local function removeFolder()
  if not (FS and FS.findFiles) then return end
  local ok, files = pcall(function() return FS:findFiles(M.FOLDER, '*', -1, false, false) end)
  if not ok or type(files) ~= 'table' then return end
  for _, file in ipairs(files) do pcall(function() FS:removeFile(file) end) end
end

local function spawnOne(k)
  local name = MODEL .. '_' .. k
  local t = hptimer()
  local ok, veh = pcall(core_vehicles.spawnNewVehicle, MODEL, {
    pos = vec3(at.x + k * 2, at.y, at.z - 100), rot = quat(0, 0, 0, 1),
    autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = name})
  -- (the spawn returns nothing for a vehicle without a body: find it by its name)
  if not ok or not veh then
    local found = scenetree and scenetree.findObject and scenetree.findObject(name)
    veh = found and getObjectByID and getObjectByID(found:getID()) or nil
  end
  stats.spawnMs = stats.spawnMs + t:stop()
  if not veh then
    stats.spawnError = tostring(ok and 'no vehicle' or veh)
    return false
  end
  pcall(function() veh.playerUsable = false end)
  pcall(function() veh:setHidden(true) end)
  local id = veh:getID()
  pool[k] = {veh = veh, id = id, state = 'loading', sent = 0, parked = 0}
  byId[id] = k
  stats.spawned = stats.spawned + 1
  veh:queueLuaCommand(string.format(
    "local ok, w = pcall(function() return assert(loadfile(%q))() end) e2rTileWorker = ok and w or nil "
    .. "obj:queueGameEngineLua(string.format('%s(%d, 0, %%q, %%q)', ok and 'ready' or 'broken', ok and '' or tostring(w)))",
    SCRIPT, NOTIFY, k))
  return true
end

-- Ask for a pool of n workers round the point (a landing). They are spawned one a frame by
-- update(): a vehicle's spawn is a frame of 0.1-0.6 s, which a landing hides.
function M.start(n, x, y, z)
  if not exists() then return false end
  if not session then
    session = tostring(os.time() % 1000000)
    removeFolder()
  end
  wanted, at = math.max(0, math.min(16, math.floor(n or 0))), {x = x, y = y, z = z}
  return true
end

function M.stop()
  for k, w in pairs(pool) do
    pcall(function() if w.veh then w.veh:delete() end end)
    pool[k] = nil
  end
  byId, jobs, inbox, wanted = {}, {}, {}, 0
  removeFolder()
  session = nil
end

-- is the vehicle one of the pool's (the world leaves them out of its collision and its traffic)
function M.is(id) return byId[id] ~= nil end

function M.count()
  local ready, free = 0, 0
  for _, w in pairs(pool) do
    if w.state ~= 'loading' then ready = ready + 1 end
    if w.state == 'idle' then free = free + 1 end
  end
  return ready, free
end

-- an idle worker: the one that holds the fewest parked jobs
function M.free()
  local best
  for k, w in pairs(pool) do
    if w.state == 'idle' and (not best or w.parked < pool[best].parked) then best = k end
  end
  return best
end

-- Hand a tile to a free worker. args: what tileworker.job takes, without id, worker, notify and
-- out. Returns the job's id, or nil when no worker is free.
function M.submit(args)
  local k = M.free()
  if not k then return nil end
  nextJob = nextJob + 1
  local id = nextJob
  args.id, args.worker, args.notify = id, k, NOTIFY
  args.out = string.format('%s/%s/%d_%d_%d', M.FOLDER, session, args.i, args.j, id)
  local w = pool[k]
  w.state, w.sent = 'busy', w.sent + 1
  jobs[id] = {worker = k, parts = {}, state = 'running', timer = hptimer(), key = args.i .. '_' .. args.j}
  stats.jobs = stats.jobs + 1
  w.veh:queueLuaCommand('if e2rTileWorker then e2rTileWorker.job(' .. serialize(args) .. ') end')
  return id
end

-- Is the job stopped after its scene (args.park), its worker gone on to other tiles?
function M.parked(id)
  local job = jobs[id]
  return job ~= nil and job.parked == true
end

-- Can the rest of a parked job start at once: its worker has nothing else to run. (Its build
-- lives in that worker's VM: no other worker can take it.)
function M.ready(id)
  local job = jobs[id]
  local w = job and pool[job.worker]
  return job ~= nil and job.state == 'running' and not job.went and w ~= nil and w.state == 'idle'
end

-- Ask for the rest of the job (its grass layer). Its worker runs it after the job it has in hand.
-- True when the job was told now or before.
function M.go(id)
  local job = jobs[id]
  if not job or job.state ~= 'running' then return false end
  if job.went then return true end
  local w = pool[job.worker]
  if not w then return false end
  job.went = true
  if job.parked then
    job.parked = false
    w.parked = math.max(0, w.parked - 1)
    stats.resumed = (stats.resumed or 0) + 1
  end
  w.state, w.sent = 'busy', w.sent + 1
  w.veh:queueLuaCommand('if e2rTileWorker then e2rTileWorker.go(' .. id .. ') end')
  return true
end

-- Give the job up: its worker drops it and is free again; what it wrote already is removed.
function M.cancel(id)
  local job = jobs[id]
  if not job then return end
  if job.state == 'running' then
    local w = pool[job.worker]
    if w then
      -- (the worker says "free" when the cancel leaves it nothing to run)
      w.sent = w.sent + 1
      w.veh:queueLuaCommand('if e2rTileWorker then e2rTileWorker.cancel(' .. id .. ') end')
      if job.parked then
        w.parked = math.max(0, w.parked - 1)
        stats.parkedDropped = (stats.parkedDropped or 0) + 1
      end
    end
    stats.cancelled = stats.cancelled + 1
  end
  for _, part in ipairs(job.parts) do
    if part.kind ~= 'done' and part.kind ~= 'error' then doomed[#doomed + 1] = {file = part.a, frames = 2} end
  end
  jobs[id] = nil
end

-- the job has parts not taken yet, or has ended
function M.news(id)
  local job = jobs[id]
  return job == nil or #job.parts > 0 or job.state ~= 'running'
end

-- The parts that came since the last call, in order: {kind = 'road' | 'scene' | 'final', a = the
-- file}, then {kind = 'done', detail} or {kind = 'error', a = the message}. A job taken to its
-- end is forgotten. nil: no such job (it was cancelled).
function M.parts(id)
  local job = jobs[id]
  if not job then return nil end
  local parts = job.parts
  job.parts = {}
  if job.state ~= 'running' then
    jobs[id] = nil
  else
    -- its last part taken: what the worker says after it (the job's end) needs no reader
    for _, part in ipairs(parts) do
      if part.kind == 'final' then job.closed = true end
    end
  end
  return parts
end

-- Remove a file a worker wrote, once it is read (a few frames from now).
function M.forget(file)
  if type(file) == 'string' and file:sub(1, #M.FOLDER) == M.FOLDER then doomed[#doomed + 1] = {file = file, frames = 8} end
end

-- A shape file belongs to the object made of it: when the object is gone (its tile was unloaded
-- by whichever path), the file goes too. A long drive would otherwise leave gigabytes behind.
local owned, ownedAt = {}, 0
function M.own(file, id)
  if type(file) == 'string' and file:sub(1, #M.FOLDER) == M.FOLDER then owned[#owned + 1] = {file = file, id = id} end
end
local function sweep()
  -- a few of them a frame, in turn
  for _ = 1, math.min(12, #owned) do
    ownedAt = ownedAt % #owned + 1
    local o = owned[ownedAt]
    local alive = scenetree and scenetree.findObjectById and scenetree.findObjectById(o.id)
    if not alive then
      doomed[#doomed + 1] = {file = o.file, frames = 4}
      owned[ownedAt] = owned[#owned]
      owned[#owned] = nil
      if #owned == 0 then break end
    end
  end
end

-- Every frame: spawn what is owed and take what the workers said (update), then give the busy
-- ones their slice (tick). A caller that never calls tick has update do both, as until 24.11.
function M.update(landing, need, noTick)
  if not exists() then return end
  if at and #pool < wanted then spawnOne(#pool + 1) end
  local said = inbox
  if #said > 0 then
    inbox = {}
    for _, part in ipairs(said) do
      local w = pool[part.worker]
      if part.id == 0 then
        if part.kind == 'free' then
          -- nothing to run, as of the commands it had taken: idle unless one was sent since
          if w and w.state ~= 'loading' and w.state ~= 'broken' and tonumber(part.a) == w.sent then w.state = 'idle' end
        else
          if w then w.state = part.kind == 'ready' and 'idle' or 'broken' end
          if part.kind ~= 'ready' then stats.broken = tostring(part.a) end
        end
      elseif part.kind == 'parked' then
        -- its scene is out and it waits for go(): the worker goes on to other jobs
        local job = jobs[part.id]
        if job and job.state == 'running' and not job.went and not job.parked then
          job.parked = true
          if w then w.parked = w.parked + 1 end
          stats.parks = (stats.parks or 0) + 1
        end
      else
        local job = jobs[part.id]
        local ended = part.kind == 'done' or part.kind == 'error'
        if ended then
          if part.kind == 'done' then
            stats.done = stats.done + 1
            local d = type(part.detail) == 'table' and part.detail or {}
            stats.busyMs = stats.busyMs + (d.ms or 0)
            stats.packMs = (stats.packMs or 0) + (d.packMs or 0)
            -- the workers' ticks by their length against the slice asked (tileworker.lua)
            stats.slices = (stats.slices or 0) + (d.slices or 0)
            stats.gcMs, stats.askedMs = (stats.gcMs or 0) + (d.gcMs or 0), (stats.askedMs or 0) + (d.askedMs or 0)
            stats.ticks = stats.ticks or {0, 0, 0, 0}
            for k = 1, 4 do stats.ticks[k] = stats.ticks[k] + (type(d.ticks) == 'table' and d.ticks[k] or 0) end
            if job then stats.wallMs = stats.wallMs + job.timer:stop() end
            -- (part.a: 'stage=ms stage=ms ...', the generator's stages of this job)
            stats.stages = stats.stages or {}
            for stage, ms in tostring(part.a or ''):gmatch('([%w_%-]+)=(%d+)') do
              -- ('parked' is the time the job stood stopped, not work)
              if stage == 'parked' then stats.parkedMs = (stats.parkedMs or 0) + tonumber(ms)
              else stats.stages[stage] = (stats.stages[stage] or 0) + tonumber(ms) end
            end
            if (d.longest or 0) > stats.longest then stats.longest = d.longest end
            -- the slices that ran far past what was asked, by the generator's stage they began
            -- in: where it needs a pause point (the frame waits for a vehicle's Lua)
            for stage, ms in tostring(d.over50 or ''):gmatch('([^>%s]+)[^:%s]*:(%d+)') do
              local row = stats.over[stage] or {0, 0}
              stats.over[stage] = row
              row[1], row[2] = row[1] + 1, math.max(row[2], tonumber(ms) or 0)
            end
          else
            stats.failed = stats.failed + 1
            stats.error = tostring(part.a)
          end
        end
        if job and not job.closed then
          job.parts[#job.parts + 1] = part
          stats.parts = stats.parts + 1
          if ended then job.state = part.kind end
        elseif job and ended then
          jobs[part.id] = nil
        elseif not ended then
          -- a part of a job given up meanwhile
          doomed[#doomed + 1] = {file = part.a, frames = 2}
        end
      end
    end
  end
  if not noTick then M.tick(landing, need) end
  if #owned > 0 then sweep() end
  for k = #doomed, 1, -1 do
    local d = doomed[k]
    d.frames = d.frames - 1
    if d.frames <= 0 then
      pcall(function() FS:removeFile(d.file) end)
      table.remove(doomed, k)
    end
  end
end

-- The busy workers' slice of this frame. A vehicle's VM runs what is queued to it after GE Lua's
-- update of this frame and has until the end of GE Lua's update of the next one: a slice that
-- fits there costs the frame nothing, and one that does not makes it wait (research/fast-tiles
-- p10, 24.11: 15 ms of plain work in eight VMs under a 20 ms step of the game thread: frame
-- 31.4 ms with it and 31.5 without; 16 ms in a 10 ms frame: 22 ms). boostMs: the ms the game
-- thread's next update will take over its usual (a new shape file, a collision rebuild: the
-- world knows a frame ahead): the slice grows by BOOST of it, BOOST_MAX at most.
M.BOOST, M.BOOST_MAX = .7, 24
function M.tick(landing, need, boostMs)
  if not exists() then return end
  local slice = landing and M.SLICE_LANDING or (M.SLICES[need or 1] or M.SLICE)
  local boost = 0
  if not landing and boostMs and boostMs > 0 then boost = math.min(M.BOOST_MAX, boostMs * M.BOOST) end
  local tick = string.format('if e2rTileWorker then e2rTileWorker.tick(%.1f) end', slice + boost)
  -- (M.sliced, M.boosted: the ms of building asked of the pool this frame, for the world's ledger)
  M.sliced, M.boosted = 0, 0
  for _, w in pairs(pool) do
    if w.state == 'busy' then
      w.veh:queueLuaCommand(tick)
      M.sliced, M.boosted = M.sliced + slice + boost, M.boosted + boost
    end
  end
  if boost > 0 then
    stats.boosts, stats.boostMs = (stats.boosts or 0) + 1, (stats.boostMs or 0) + M.boosted
  end
end

function M.stats()
  local ready, free = M.count()
  local out = {workers = ready, free = free, wanted = wanted}
  out.parkedNow = 0
  for _, w in pairs(pool) do out.parkedNow = out.parkedNow + (w.parked or 0) end
  for k, v in pairs(stats) do out[k] = v end
  return out
end

return M
