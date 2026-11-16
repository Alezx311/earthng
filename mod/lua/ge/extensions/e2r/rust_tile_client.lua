-- Experimental nonblocking client for a single tile roof request. The caller
-- owns scheduling/timeouts and must discard this object if the tile expires.
-- It is used only by the explicitly enabled experimental runtime.
local ffi = require('ffi')
local M = {}
local MAX_REQUEST, MAX_REPLY = 8 * 1024 * 1024, 16 * 1024 * 1024
local function u32(n)
  local a = ffi.new('uint32_t[1]', n)
  return ffi.string(a, 4)
end
local function word(s, pos)
  local a = ffi.new('uint32_t[1]')
  ffi.copy(a, s:sub(pos, pos + 3), 4)
  return tonumber(a[0])
end

function M.new(sock, body, job, epoch, lod)
  assert(type(body) == 'string' and #body <= MAX_REQUEST, 'invalid request size')
  assert(job >= 0 and job < 4294967296 and job % 1 == 0, 'invalid job')
  assert(epoch >= 0 and epoch < 4294967296 and epoch % 1 == 0, 'invalid epoch')
  local magic = body:sub(1,4)
  assert((lod == 0 and (magic == 'ETG1' or magic == 'EWP1' or magic == 'ERD1')) or
         (lod == 1 and (magic == 'EFG1' or magic == 'ERD1')), 'invalid LOD')
  local expected = magic == 'ERD1' and 'ERR1' or (magic == 'EWP1' and 'EWR1' or 'ETR1')
  local payload = 'ETB1' .. u32(job) .. u32(0) .. u32(epoch) .. u32(0)
    .. u32(lod) .. u32(#body) .. body
  local state = {sock = sock, send = u32(#payload) .. payload, at = 1,
    recv = '', need = 4, header = true, job = job, epoch = epoch, lod = lod, expected = expected}

  local function fail(why)
    state.done, state.error = true, why
    pcall(function() sock:close() end)
    return false, why
  end
  function state:cancel()
    if not self.done then fail('cancelled') end
  end
  function state:step()
    if self.done then return false, self.error or 'complete' end
    if self.at <= #self.send then
      local sent, err, partial = self.sock:send(self.send, self.at)
      if sent then self.at = sent + 1
      elseif err == 'timeout' then self.at = (partial or self.at - 1) + 1
      else return fail('send: ' .. tostring(err)) end
      if self.at <= #self.send then return nil end
      self.send = ''
    end
    local data, err, partial = self.sock:receive(self.need - #self.recv)
    self.recv = self.recv .. (data or partial or '')
    if err and err ~= 'timeout' then return fail('receive: ' .. tostring(err)) end
    if #self.recv < self.need then return nil end
    if self.header then
      self.need = word(self.recv, 1)
      if self.need < 28 or self.need > MAX_REPLY + 28 then return fail('response length') end
      self.recv, self.header = '', false
      return nil
    end
    local reply = self.recv
    if reply:sub(1,4) ~= 'ETC1' or word(reply,5) ~= self.job or word(reply,9) ~= 0
      or word(reply,13) ~= self.epoch or word(reply,17) ~= 0 or word(reply,21) ~= self.lod then
      return fail('stale or invalid response')
    end
    local n = word(reply,25)
    if n ~= #reply - 28 or reply:sub(29,32) ~= self.expected then return fail('response payload') end
    self.done = true
    pcall(function() self.sock:close() end)
    return reply:sub(29)
  end
  return state
end
return M
