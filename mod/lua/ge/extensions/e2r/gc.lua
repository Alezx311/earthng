-- The GE Lua collector while EarthNG is the level.
--
-- What the engine does (BeamNG 0.40.5, research/rust-in-mod/p26_engine_step.lua, out/gcdebt-04):
-- it steps the collector a little every frame (LuaGC 0.2-0.4 ms), and each KB our code allocates
-- pays stepmul/100 KB of collector work in that allocation. When the heap reaches ~4/3 of what its
-- own last full collection left, it runs a full collection in one frame: 0.4-0.6 s at a 400-480 MB
-- heap, the "sweep" of 80-150 MB every 15-25 s while driving (out/rel090-vyt: 427->348 MB, then
-- 462 = 4/3 x 348, 490 = 4/3 x 368...). Our own collectgarbage('collect') costs as much (370-415
-- ms) and does not move that point. The incremental cycle never ended before it: at stepmul 100
-- (LOW) a cycle needs far more allocation than the 4/3 leaves, and the default 200 (the old
-- RISE_MB guard) only made the collector's work follow the generator's bursts (15-50 ms frames).
--
-- So, while driving, the collector gets a slice of every frame (M.pace): collectgarbage('step') until
-- the slice is spent. The slice grows with the share of the room the garbage has taken: the room is
-- from the live heap (the heap at the end of the last cycle, or what the engine's full collection
-- left if that is lower) to the top, MARGIN under the engine's 4/3 (SPAN over the live heap while no
-- full collection of the engine's has been seen). Nothing up to PACE_FROM of it, PACE_MS at
-- PACE_FULL, PACE_RUSH_MS over it. A cycle costs about as much as a full collection (~440 ms at
-- 350 MB), so it is the number of cycles that costs: a cycle ends with the room ~half full, not just
-- over the live heap (out/gcfix-01: 24 cycles in 70 s, 2.1 ms a frame). The mutator's step stays
-- LOW: the generator's own allocations do not pay more for the collector inside its frame budget.
--
-- The touch-down (M.nudge): the engine's 4/3 counts from its last full collection, which was in the
-- landing, so its first full collection came 15-35 s into the drive (out/gcpace-01: 379 MB). The
-- touch-down lifts the heap over that 4/3 with an FFI array nobody holds: the engine's full collection
-- runs there, where the landing's long frame hides it, and frees the landing's garbage. A second
-- array (HELD of the heap) is held through it, so that the engine counts its 4/3 from the live heap
-- and that array; then it is let go, and the room for the drive is a third of the live heap and
-- four thirds of the array. If the engine's collection has not come within NUDGE_FRAMES frames (another
-- engine), a collection of our own does what the touch-down did before (M.collect).
--
-- The engine's full collection is told by a fall of ENGINE_DROP of the heap between two frames and the
-- engine's own collector time of that frame (Engine.Debug.getLastPerformanceMetrics LuaGC, BeamNG
-- 0.40) over ENGINE_GC_MS (its full collections: 141-321 ms in the landing, 415-442 ms driving; its
-- step that frees the touch-down's held array: 32-50 ms, out/gcfix-03..04). Without that metric, a
-- frame over ENGINE_MS_PER_MB ms a MB of the heap: a full collection takes ~1 ms a MB, while the sweep
-- of a cycle of ours, which the mutator's steps also do, can free as much in a frame of the
-- streaming's own 100-210 ms (out/gcfix-02: a scene object of 166 ms, 78 s, read as the engine's
-- collection, and the room shrank for the rest of the drive).
--
-- The landing (loading: the player waits for the tiles) is different: the generator fills the heap
-- with tile geometry, and there is nothing to free. There the step is LOAD: the collector's steps
-- inside the generator's own allocations all but go (the nine tiles 12.7 s -> 8.8 s of generator
-- time, load-03 -> load-05; probe p19). The default comes back over LOAD_CAP_MB.
local M = {LOW = 100, LOAD = 10, LOAD_CAP_MB = 1300,
  ENGINE_RATIO = 4 / 3, ENGINE_DROP = 0.08, ENGINE_GC_MS = 100, ENGINE_MS_PER_MB = 0.6,
  MARGIN = 0.94, SPAN = 0.25, MIN_ROOM = 0.1,
  PACE_FROM = 0.4, PACE_FULL = 0.85, PACE_MS = 2.5, PACE_RUSH_MS = 6, PACE_K = 16,
  HELD = 0.35, NUDGE = 0.4, NUDGE_MIN = 0.1, NUDGE_FRAMES = 20}
local saved, mode, clock
local base, ref, lastKb, nudged
local ffi
do
  local ok, lib = pcall(require, 'ffi')
  if ok and type(lib) == 'table' and type(lib.new) == 'function' then ffi = lib end
end

function M.count() return collectgarbage('count') end

-- the heap the garbage is measured from: the end of the last cycle, or the engine's full collection
local function live() return (ref and ref < base) and ref or base end

-- the heap the slices keep under (see the top); never less than MIN_ROOM over the live heap: when the
-- live heap itself nears the engine's point, its full collection comes, and counts from there
local function top(low)
  local t = ref and ref * M.ENGINE_RATIO * M.MARGIN or low * (1 + M.SPAN)
  return math.max(t, low * (1 + M.MIN_ROOM))
end

-- the report's lists: the first 30 cycles' ends, engine's collections and other falls (s of the level, MB)
local function note(name, kb, more)
  local list = M[name]
  if not list then list = {}; M[name] = list end
  if #list < 30 then list[#list + 1] = string.format('%.1f s %.0f MB', M.t or 0, kb / 1024) .. (more or '') end
end

-- the engine's own collector time in the last frame, ms (nil where the engine has no such metric)
local metrics = {}
local function engineGcMs()
  local engine = rawget(_G, 'Engine')
  local dbg = type(engine) == 'table' and engine.Debug
  if not (dbg and dbg.getLastPerformanceMetrics) then return nil end
  if not pcall(dbg.getLastPerformanceMetrics, metrics) then return nil end
  return tonumber(metrics.LuaGC)
end

-- the collector's share of this frame while driving; returns the ms spent
function M.pace(kb)
  if kb < base then base = kb end
  local low = live()
  local used = (kb - low) / (top(low) - low)
  M.used = used
  if used < M.PACE_FROM then return 0 end
  local budget = used >= M.PACE_FULL and M.PACE_RUSH_MS
    or M.PACE_MS * (used - M.PACE_FROM) / (M.PACE_FULL - M.PACE_FROM)
  local timer, spent = hptimer(), 0
  repeat
    local ended = collectgarbage('step', M.PACE_K)
    local now = timer:stop()
    -- the longest single step: the atomic phase, or one big table
    if now - spent > (M.worstStepMs or 0) then M.worstStepMs = now - spent end
    spent = now
    if ended then
      -- the cycle ended: what is left is the live heap (and this cycle's own new garbage)
      base = M.count()
      M.cycles = (M.cycles or 0) + 1
      note('cycleLog', base)
      break
    end
  until spent >= budget
  return spent
end

function M.step(ours, dt, loading)
  if not ours then
    if saved then collectgarbage('setstepmul', saved) end
    saved, mode, clock, base, ref, lastKb, nudged = nil, nil, nil, nil, nil, nil, nil
    return
  end
  local kb = M.count()
  if not saved then
    saved = collectgarbage('setstepmul', M.LOW)
    mode, base = M.LOW, kb
    M.cycles, M.cycleLog, M.engineCollections, M.engineLog, M.sweepLog, M.t = nil, nil, nil, nil, nil, 0
  end
  M.t = M.t + (dt or 0)
  local frameMs = clock and clock:stopAndReset() or 0
  clock = clock or hptimer()
  -- the heap fell since the last frame: the engine's full collection, or a sweep (see the top)
  local fall = lastKb and lastKb - kb > M.ENGINE_DROP * kb
  local gcMs = fall and engineGcMs()
  if fall then
    local more = string.format(' from %.0f, frame %.0f ms, LuaGC %s', lastKb / 1024, frameMs, gcMs and string.format('%.0f', gcMs) or '-')
    if gcMs then fall = gcMs > M.ENGINE_GC_MS else fall = frameMs > M.ENGINE_MS_PER_MB * kb / 1024 end
    note(fall and 'engineLog' or 'sweepLog', kb, more)
  end
  if fall then
    ref = kb
    M.engineCollections = (M.engineCollections or 0) + 1
    base = kb
    if nudged then
      -- the held array is garbage now: the live heap is what is left without it
      base = math.max(kb - nudged.heldKb, 1)
      M.nudgeFrames, nudged = nudged.frames, nil
    end
  end
  if loading then
    local want = kb / 1024 > M.LOAD_CAP_MB and saved or M.LOAD
    -- automation (M.try, world.lua test.gcCycle): another step for this frame; negative: the
    -- collector is stopped as well, so only the engine's own step of the frame runs
    if M.try then
      want = math.abs(M.try)
      if M.try < 0 then collectgarbage('stop') end
    end
    -- every frame, and what it was is kept for the report (M.seen): whether anything else moves it
    M.seen = collectgarbage('setstepmul', want)
    mode = want
    M.paceMs = 0
    -- what the landing leaves is live data or the touch-down's to free, not garbage piling up
    base, lastKb = kb, kb
    return
  end
  if mode ~= M.LOW then
    collectgarbage('setstepmul', M.LOW)
    mode = M.LOW
  end
  if nudged then
    -- waiting for the engine's collection: the arrays are its to free, not work for the pace
    nudged.frames = nudged.frames + 1
    if nudged.frames > M.NUDGE_FRAMES then
      nudged = nil   -- the held array goes with the rest
      M.nudgeFallbackMs = M.collect()
    end
    M.paceMs = 0
  else
    M.paceMs = M.pace(kb)
  end
  lastKb = M.count()
end

-- a full collection now (seconds-long frames of the landing hide it); returns the ms it took
function M.collect()
  local t = os.clock()
  collectgarbage('collect')
  local kb = M.count()
  base, lastKb = kb, kb
  return (os.clock() - t) * 1000
end

-- The touch-down: an array held through the engine's full collection and garbage that lifts the heap
-- over its 4/3, so that its collection runs now (see the top). Without FFI, the old collection of our
-- own. Returns the ms it took.
function M.nudge()
  if not ffi then return M.collect() end
  local t = os.clock()
  local kb = M.count()
  local heldKb = kb * M.HELD
  -- over the 4/3 of the landing's last full collection, if one was seen; else NUDGE of the heap
  local garbageKb = ref and ref * M.ENGINE_RATIO * 1.05 - kb - heldKb or kb * M.NUDGE
  garbageKb = math.max(garbageKb, kb * M.NUDGE_MIN)
  local ok, held = pcall(ffi.new, 'uint8_t[?]', math.floor(heldKb * 1024))
  if not ok or not pcall(ffi.new, 'uint8_t[?]', math.floor(garbageKb * 1024)) then
    return M.collect()
  end
  nudged = {frames = 0, held = held, heldKb = heldKb}
  M.nudgeMb = {held = heldKb / 1024, garbage = garbageKb / 1024, landingRef = ref and ref / 1024}
  lastKb = M.count()
  return (os.clock() - t) * 1000
end

function M.lowered() return mode ~= nil and mode == M.LOW and saved ~= M.LOW end

-- for the test report (world.lua runTest): what the collector did in the level
function M.report()
  return {cycles = M.cycles, cycleLog = M.cycleLog, engine = M.engineCollections, engineLog = M.engineLog, sweepLog = M.sweepLog,
    nudgeFrames = M.nudgeFrames, nudgeFallbackMs = M.nudgeFallbackMs, nudgeMb = M.nudgeMb,
    worstStepMs = M.worstStepMs, used = M.used}
end

return M
