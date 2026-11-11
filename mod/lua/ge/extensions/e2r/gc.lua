-- The GE Lua collector while EarthNG is the level. BeamNG steps the collector every frame, so a
-- new cycle starts as soon as one ends: setpause changes nothing, and each KB the generator
-- allocates pays stepmul/100 KB of collector work in the same frame. With the default 200 that
-- was ~100 ms of LuaGC a second in central Kyiv, in runs of 15-50 ms frames while a cycle swept
-- (a stock map: 4 ms). LOW halves that work. A fixed LOW let the garbage pile up after the car
-- stood still: then the engine swept 100-220 MB in one 0.7-1.2 s frame every ~9 s. So the
-- default comes back while the heap is RISE_MB over its recent floor (the live heap after a
-- sweep), and LOW again under BACK_MB (out/stutter, 28.10).
-- The landing (loading: the player waits for the tiles) is different: the generator fills the heap
-- with tile geometry (~900 MB live when the nine tiles are ready), and there is nothing to free.
-- There the step is LOAD: the collector's steps inside the generator's own allocations all but go
-- (the nine tiles 12.7 s -> 8.8 s of generator time, load-03 -> load-05; probe p19: a task filling
-- the heap 9.5 -> 1.9 ms a frame). The engine's own step of each frame stays: ~0.6-0.8 ms of LuaGC
-- per ms of generator whatever the step is (1, 10, 100, 400), with the collector stopped, and
-- with frames of 40 or 90 ms (load-06, load-07). The default comes back over LOAD_CAP_MB.
-- M.collect() empties the heap at once where a long frame hides it (the touch-down).
-- RISE_MB 96 was too late once the generator's mesh output became cdata (11.11): a standing car
-- got a ~500 ms sweep of ~100 MB every 15-20 s again (out/gc-02, gc-03); at 48/24 none in the
-- same game (research/rust-in-mod/p23_gc_rise.lua).
local M = {LOW = 100, RISE_MB = 48, BACK_MB = 24, FLOOR_S = 20, LOAD = 10, LOAD_CAP_MB = 1300}
local saved, floor, mode

function M.count() return collectgarbage('count') end

function M.step(ours, dt, loading)
  if not ours then
    if saved then collectgarbage('setstepmul', saved) end
    saved, floor, mode = nil, nil, nil
    return
  end
  local kb = M.count()
  if not saved then
    saved = collectgarbage('setstepmul', M.LOW)
    floor, mode = kb, M.LOW
    return
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
    floor = kb   -- what the landing leaves is live data or M.collect()'s, not garbage piling up
    return
  end
  -- the floor follows a sweep down at once and creeps up with the live heap
  if kb < floor then floor = kb else floor = floor + (kb - floor) * math.min(1, (dt or 0) / M.FLOOR_S) end
  local over = (kb - floor) / 1024
  local want = mode
  if over > M.RISE_MB then want = saved elseif over < M.BACK_MB then want = M.LOW end
  if want ~= mode then
    collectgarbage('setstepmul', want)
    mode = want
  end
end

-- a full collection now (seconds-long frames of the landing hide it); returns the ms it took
function M.collect()
  local t = os.clock()
  collectgarbage('collect')
  if floor then floor = M.count() end
  return (os.clock() - t) * 1000
end

function M.lowered() return mode ~= nil and mode == M.LOW and saved ~= M.LOW end

return M
