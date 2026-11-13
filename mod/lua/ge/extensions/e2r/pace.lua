-- Frames that change the scene, kept apart by calm frames (the gate).
--
-- The engine does not move the world by the real gap between two frames but by a smoothed one
-- (a median of the last few frames and a slow average; BeamNG.Earth's governor.lua, MIT, and the
-- Ticino streamer measured it the same way, see docs/PERFORMANCE.md). A lone slow frame is
-- filtered out: a hitch, and the car keeps its speed. Two slow frames in a row, or slow, fast,
-- slow, pass the filter: the game runs slow and then catches up, which reads as a stutter even
-- at a high mean frame rate. Streaming that spawns a little in every frame makes exactly that
-- pattern once each spawn frame costs the engine more than the Lua shows (createMesh, a Forest
-- commit, a collision rebuild, the shadow cache the new static object invalidates).
--
-- So a scene-changing step runs only once QUIET frames before it changed nothing and were calm
-- (no longer than the median calm frame plus a margin), at most one such step a frame, and it
-- gets a burst budget instead of a trickle. A gate that waited TIMEOUT frames opens anyway (a
-- slow PC never has calm frames), and it stays open while the game is paused (a landing, a jump:
-- there is no game time to warp).
local M = {}

M.QUIET = 2          -- calm frames before a scene-changing frame (and so after the one before)
M.MARGIN_MS = 2.0    -- calm: no longer than the median calm frame + max(MARGIN_MS, SHARE * median)
M.SHARE = .25
M.TIMEOUT = 24       -- frames a waiting gate holds at most
M.BASE = 63          -- calm frames the median is taken over (odd)

local floor, max, min = math.floor, math.max, math.min

local Gate = {}
Gate.__index = Gate

function M.newGate()
  return setmetatable({frame = 0, last = -1e9, since = nil, ring = {}, n = 0, head = 0, base = nil, recent = {},
    worked = false, paused = false, opened = 0, timeouts = 0, held = 0, sorted = {}}, Gate)
end

local function median(self)
  local s, n = self.sorted, self.n
  for k = 1, n do s[k] = self.ring[k] end
  for k = n + 1, #s do s[k] = nil end
  table.sort(s)
  if n == 0 then return nil end
  return s[floor((n + 1) / 2)]
end

-- once a frame, before any step: ms = the wall time of the frame that just ended
function Gate:beginFrame(ms, paused)
  if ms and ms > 0 then
    -- a frame with no scene change, after one with none either, is a sample of the calm frame
    if not self.worked and self.frame - self.last > 1 then
      self.head = self.head % M.BASE + 1
      self.ring[self.head] = ms
      self.n = min(self.n + 1, M.BASE)
      if self.head % 8 == 0 or not self.base then self.base = median(self) end
    end
    table.insert(self.recent, 1, ms)
    if #self.recent > M.QUIET then self.recent[#self.recent] = nil end
  end
  self.frame = self.frame + 1
  self.worked = false
  self.paused = paused and true or false
end

function Gate:calm()
  if not self.base or #self.recent < M.QUIET then return false end
  local limit = self.base + max(M.MARGIN_MS, M.SHARE * self.base)
  for k = 1, M.QUIET do
    if self.recent[k] > limit then return false end
  end
  return true
end

-- may this frame change the scene? The caller then runs its step and calls done()
function Gate:open()
  if self.paused then return true end
  if self.worked then return false end
  if self.frame - self.last <= M.QUIET then return false end
  self.since = self.since or self.frame
  if self:calm() then return true end
  if self.frame - self.since >= M.TIMEOUT then
    self.timeouts = self.timeouts + 1
    return true
  end
  self.held = self.held + 1
  return false
end

-- the step changed the scene in this frame
function Gate:done()
  if not self.worked then self.opened = self.opened + 1 end
  self.worked, self.last, self.since = true, self.frame, nil
end

-- the slot was open but the only candidate waits (the spawn packet is once a second):
-- the next change still stands two calm frames away, and this one is not counted
function Gate:yield()
  self.worked, self.last, self.since = true, self.frame, nil
end

function Gate:report()
  return {base = self.base and floor(self.base * 100) / 100, opened = self.opened, timeouts = self.timeouts,
    held = self.held}
end

return M
