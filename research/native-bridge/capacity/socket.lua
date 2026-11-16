-- The link's own cost on the game thread: LuaSocket receive over loopback in pieces of different
-- sizes, plus the ffi.copy into a typed buffer the codec does. Sender and receiver are both in
-- this Lua (the DLL sends from its own thread in the real link); only receive + copy is timed.
-- Run after common.lua: python earthng/probe.py --user <user> -f research/native-bridge/capacity/socket.lua --timeout 300
local ffi = require('ffi')
local socket = require('socket')
local MB = 1024 * 1024
local TOTAL = 32 * MB
local out = {totalMb = TOTAL / MB, pieces = {}}
-- the game's LuaSocket has no socket.bind shortcut
local srv = assert(socket.tcp())
assert(srv:bind('127.0.0.1', 0))
assert(srv:listen(1))
local _, port = srv:getsockname()
local cli = socket.tcp()
cli:settimeout(1)
assert(cli:connect('127.0.0.1', port))
srv:settimeout(1)
local conn = assert(srv:accept())
cli:settimeout(0); conn:settimeout(0)
pcall(function() cli:setoption('tcp-nodelay', true) end)
local block = string.rep('EarthNG bridge payload 0123456789abcdef', math.ceil(MB / 39)):sub(1, MB)
local staging = ffi.new('uint8_t[?]', 4 * MB)
local timer = hptimer()

for _, piece in ipairs({8192, 65536, 1048576}) do
  collectgarbage('collect')
  local kb0 = collectgarbage('count')
  local sent, got, recvMs, copyMs, calls = 0, 0, 0, 0, 0
  local guard = 0
  while got < TOTAL and guard < 2000000 do
    guard = guard + 1
    if sent < TOTAL then
      local i = sent % MB + 1
      local last, err, partial = cli:send(block, i, math.min(MB, i + 256 * 1024 - 1))
      local n = (last or partial or (i - 1)) - (i - 1)
      sent = sent + math.max(0, n)
    end
    timer:stopAndReset()
    local data, err, partial = conn:receive(piece)
    local s = data or partial
    recvMs = recvMs + timer:stop()
    if s and #s > 0 then
      calls = calls + 1
      timer:stopAndReset()
      -- the codec copies a whole message to the start of its view (no pointer arithmetic in the sandbox)
      ffi.copy(staging, s, math.min(#s, 4 * MB))
      copyMs = copyMs + timer:stop()
      got = got + #s
    end
  end
  local garbage = collectgarbage('count') - kb0
  out.pieces[tostring(piece)] = {mb = got / MB, recvMsPerMb = recvMs / (got / MB), copyMsPerMb = copyMs / (got / MB),
    calls = calls, garbageKbPerMb = garbage / (got / MB)}
end
cli:close(); conn:close(); srv:close()
return out
