-- Experimental, opt-in: GE Lua's side of the Rust tile worker pool
-- (research/native-bridge/NIGHT_2026-11-16.md). A test profile enables it with
-- settings/earthng-rust-bridge.json {enabled, port, token, workers}; without that file, a
-- running DLL or a healthy link, native.lua builds every tile in Lua as before.
-- One persistent nonblocking TCP link to 127.0.0.1: the game never waits for it. pump() moves
-- bytes within a small budget each frame; parts and results are collected per job for
-- native.lua to decode and deliver inside its own frame budget.
local ffi = require('ffi')
local codec = require('ge/extensions/e2r/bridge_codec')
local M = {}
local HELLO, SOURCES, REGION, JOB, PRIORITY, CANCEL, FS_FALSE, BYE = 1, 2, 3, 4, 5, 6, 7, 8
local HELLO_OK, PART, DONE, NOTE = 101, 102, 103, 104
M.VERSION = 2
M.OK, M.CANCELLED, M.FAILED, M.BUSY = 0, 1, 2, 3
-- the worker's require names, read from the mounted planet so the worker runs this very code
M.SOURCES = {'generator', 'biome', 'knock', 'cellformat', 'bridge_codec', 'bridge_worker'}
local MAX_FRAME = 64 * 1024 * 1024
-- LuaSocket reads the socket 8 KB at a time and builds a receive(n) result in a luaL_Buffer that
-- concatenates its pieces as it goes: a 4 MB receive left ~5 times its bytes of strings in the
-- heap (kyivfast-q50-rust-6v1: 2.08 GB grown in pump for 397 MB received, more than all of
-- decoding). One piece per call is one string; the frame's own concatenation makes it two.
M.RECV_PIECE = 8192

local u32buf, f64buf = ffi.new('uint32_t[2]'), ffi.new('double[1]')
local function u32(n) u32buf[0] = n; return ffi.string(u32buf, 4) end
local function u64(n) u32buf[0] = n % 4294967296; u32buf[1] = math.floor(n / 4294967296); return ffi.string(u32buf, 8) end
local function f64(x) f64buf[0] = x; return ffi.string(f64buf, 8) end
local function getu32(s, p) ffi.copy(u32buf, s:sub(p, p + 3), 4); return tonumber(u32buf[0]) end
local function getu64(s, p) ffi.copy(u32buf, s:sub(p, p + 7), 8); return tonumber(u32buf[0]) + tonumber(u32buf[1]) * 4294967296 end
local function getf64(s, p) ffi.copy(f64buf, s:sub(p, p + 7), 8); return tonumber(f64buf[0]) end
local function frame(kind, payload) return u32(#payload + 4) .. u32(kind) .. payload end

local function readSource(name)
  local f = io.open('/lua/ge/extensions/e2r/' .. name .. '.lua', 'rb')
  if not f then return nil end
  local data = f:read('*a')
  f:close()
  return data
end

local Link = {}
Link.__index = Link

-- config: {port, token, workers, memoryMb, maxJobs}; nil, why when it cannot even start
function M.connect(config)
  if type(config) ~= 'table' or config.enabled ~= true then return nil, 'disabled' end
  local port = tonumber(config.port)
  if not port or port % 1 ~= 0 or port < 1 or port > 65535 or type(config.token) ~= 'string' then return nil, 'config' end
  local ok, socket = pcall(require, 'socket')
  if not ok or type(socket) ~= 'table' then return nil, 'no socket' end
  local tcp = socket.tcp()
  if not tcp then return nil, 'no tcp' end
  -- a local connect completes at once; this is the only blocking call, 50 ms at most, once
  tcp:settimeout(0.05)
  local connected, err = tcp:connect('127.0.0.1', port)
  if not connected then tcp:close(); return nil, 'connect: ' .. tostring(err) end
  tcp:settimeout(0)
  pcall(function() tcp:setoption('tcp-nodelay', true) end)
  local workers = math.max(1, math.min(8, math.floor(tonumber(config.workers) or 4)))
  local link = setmetatable({tcp = tcp, out = {}, outAt = 1, inParts = {}, inHave = 0, need = 8, header = true,
    ready = false, dead = false, jobs = {}, nextId = 1, regions = {}, workers = workers,
    piece = math.max(512, math.floor(tonumber(config.recvPiece) or M.RECV_PIECE)),
    stats = {sent = 0, received = 0, frames = 0, pumpMs = 0, pumpMaxMs = 0}}, Link)
  link:queue(HELLO, u32(M.VERSION) .. u32(workers) .. u32(math.floor(tonumber(config.memoryMb) or 512))
    .. u32(math.floor(tonumber(config.maxJobs) or 64)) .. config.token)
  local parts = {}
  for _, name in ipairs(M.SOURCES) do
    local src = readSource(name)
    if not src then tcp:close(); return nil, 'source ' .. name end
    local full = 'ge/extensions/e2r/' .. name
    parts[#parts + 1] = u32(#full) .. full .. u32(#src) .. src
  end
  link:queue(SOURCES, table.concat(parts))
  return link
end

function Link:queue(kind, payload)
  self.out[#self.out + 1] = frame(kind, payload)
end

function Link:fail(why)
  if self.dead then return end
  self.dead, self.why = true, why
  pcall(function() self.tcp:close() end)
end

-- region data once per id (the worker decodes it in each VM)
function Link:region(id, data)
  if self.regions[id] then return end
  self.regions[id] = true
  self:queue(REGION, u32(#id) .. id .. codec.encode(data))
end

-- args: the worker's job table; returns the job id
function Link:submit(args, priority, epoch, flags)
  local id = self.nextId
  self.nextId = id + 1
  local job = {id = id, parts = {}, done = nil, submitted = os.clock()}
  self.jobs[id] = job
  self:queue(JOB, u64(id) .. u32(epoch % 4294967296) .. f64(priority) .. u32(flags or 0) .. codec.encode(args))
  return id, job
end

function Link:priority(id, p) self:queue(PRIORITY, u64(id) .. f64(p)) end
function Link:cancel(id) self:queue(CANCEL, u64(id) .. u32(0)); self.jobs[id] = nil end
function Link:fsFalse(paths) self:queue(FS_FALSE, table.concat(paths, '\n')) end
function Link:close()
  if self.dead then return end
  self:queue(BYE, '')
  self:pump(5, 1e6)
  self:fail('closed')
end

local function dispatch(self, kind, s)
  self.stats.frames = self.stats.frames + 1
  if kind == HELLO_OK then
    self.ready, self.serverWorkers, self.pid = true, getu32(s, 5), getu32(s, 9)
  elseif kind == PART then
    local id = getu64(s, 1)
    local job = self.jobs[id]
    -- the part stays in its payload string; decode starts past the 16-byte header
    if job then job.parts[#job.parts + 1] = {kind = getu32(s, 13), data = s, base = 16} end
  elseif kind == DONE then
    local id = getu64(s, 1)
    local job = self.jobs[id]
    if job then
      job.done = {status = getu32(s, 13), queueMs = getf64(s, 17), runMs = getf64(s, 25), worker = getu32(s, 33),
        message = s:sub(37)}
    end
  elseif kind == NOTE then
    self.note = s
  else
    self:fail('frame ' .. tostring(kind))
  end
end

-- Moves bytes both ways: at most maxBytes in, about budgetMs of time.
function Link:pump(budgetMs, maxBytes)
  if self.dead then return false end
  local t0 = os.clock()
  local tcp = self.tcp
  while self.out[1] do
    local s = self.out[1]
    local sent, err, partial = tcp:send(s, self.outAt)
    local last = sent or partial
    if last then self.stats.sent = self.stats.sent + (last - self.outAt + 1); self.outAt = last + 1 end
    if err and err ~= 'timeout' then self:fail('send: ' .. tostring(err)); return false end
    if self.outAt > #s then table.remove(self.out, 1); self.outAt = 1 else break end
    if (os.clock() - t0) * 1000 > budgetMs then break end
  end
  local got = 0
  while got < maxBytes do
    local want = math.min(self.need - self.inHave, self.piece or M.RECV_PIECE)
    local data, err, partial = tcp:receive(want)
    local chunk = data or partial
    if chunk and #chunk > 0 then
      self.inParts[#self.inParts + 1] = chunk
      self.inHave, got = self.inHave + #chunk, got + #chunk
      self.stats.received = self.stats.received + #chunk
    end
    if err and err ~= 'timeout' then self:fail('receive: ' .. tostring(err)); return false end
    if self.inHave >= self.need then
      local s = #self.inParts == 1 and self.inParts[1] or table.concat(self.inParts)
      self.inParts, self.inHave = {}, 0
      if self.header then
        local n = getu32(s, 1)
        if n < 4 or n > MAX_FRAME then self:fail('frame length'); return false end
        self.header, self.need, self.kind = false, n - 4, getu32(s, 5)
        if self.need == 0 then
          dispatch(self, self.kind, '')
          self.header, self.need = true, 8
        end
      else
        dispatch(self, self.kind, s)
        self.header, self.need = true, 8
      end
    elseif not data then
      break
    end
    if (os.clock() - t0) * 1000 > budgetMs then break end
  end
  local ms = (os.clock() - t0) * 1000
  self.stats.pumpMs = self.stats.pumpMs + ms
  if ms > self.stats.pumpMaxMs then self.stats.pumpMaxMs = ms end
  return true
end

M.decode = codec.decode
-- a delivery dropped at a pause gives the codec's views back
M.release = codec.release
-- sets of persistent views (one per delivery lane) and the fresh arrays decoded past them
M.viewSets = codec.viewSets
M.codecStats = codec.stats
return M
