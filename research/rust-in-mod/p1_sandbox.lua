-- What the GE Lua sandbox allows: FFI pieces, native loading, LuaJIT extras.
local r = {}
local function try(name, fn) local ok, v = pcall(fn); r[name] = ok and v or ('ERR ' .. tostring(v)) end
local okffi, ffi = pcall(require, 'ffi')
r.ffi = okffi
r.jitVersion = jit and jit.version
try('jitStatus', function() local t = {jit.status()}; for i = 1, #t do t[i] = tostring(t[i]) end; return table.concat(t, ' ') end)
r.ffiLoadType = okffi and type(ffi.load)
try('ffiLoadKernel32', function() return tostring(ffi.load('kernel32')) end)
r.loadlibType = type(package.loadlib)
r.cpath = tostring(package.cpath)
r.path = tostring(package.path)
try('loadlib', function() local f, e = package.loadlib('kernel32.dll', 'GetTickCount'); return tostring(f) .. ' / ' .. tostring(e) end)
try('ffiCdefC', function() ffi.cdef('unsigned long GetTickCount(void);'); return tonumber(ffi.C.GetTickCount()) end)
try('castArr', function() local a = ffi.new('uint8_t[4]', 1, 2, 3, 4); local p = ffi.cast('uint32_t*', a); return p[0] end)
try('castStr', function() local s = '\1\0\0\0\2\0\0\0'; local p = ffi.cast('const uint32_t*', s); return p[0] + p[1] * 10 end)
try('castFloat', function() local a = ffi.new('float[2]', 1.5, 2.5); local p = ffi.cast('const uint8_t*', a); return p[3] end)
try('copy', function() local a = ffi.new('uint8_t[4]'); ffi.copy(a, 'abcd', 4); return a[3] end)
try('ffiString', function() local a = ffi.new('uint8_t[3]', 65, 66, 67); return ffi.string(a, 3) end)
try('typeofStruct', function()
  ffi.cdef('typedef struct { float x, y, z; } e2rp_v3;')
  local v = ffi.new('e2rp_v3[2]'); v[1].z = 7; return v[1].z end)
try('sizeofPtr', function() return ffi.sizeof('void*') end)
try('abi', function() return tostring(ffi.abi('64bit')) .. ' ' .. tostring(ffi.abi('le')) end)
try('strbuf', function() local sb = require('string.buffer'); local b = sb.new(); b:put('xy'); return b:tostring() .. ' ' .. type(b.ref) end)
try('strbufRef', function()
  local sb = require('string.buffer'); local b = sb.new(); b:set('\5\0\0\0')
  local p, n = b:ref(); return tostring(ffi.cast('const uint32_t*', p)[0]) .. ' len ' .. n end)
try('tablenew', function() local tn = require('table.new'); return type(tn(10, 0)) end)
try('tableclear', function() local tc = require('table.clear'); return type(tc) end)
r.bit = type(bit)
try('jitOpt', function() local o = require('jit.opt'); return type(o.start) end)
try('jitProfile', function() return type(require('jit.profile').start) end)
try('vec3cdata', function() return type(vec3(1, 2, 3)) .. ' ' .. tostring(ffi and ffi.istype and pcall(ffi.typeof, vec3(1,2,3))) end)
try('io', function() return type(io.open) .. ' ' .. type(io.popen) .. ' ' .. type(os.execute) end)
try('readZipBytes', function()
  local f = io.open('/lua/ge/extensions/e2r/quality.lua', 'rb'); if not f then return 'no' end
  local s = f:read('*a'); f:close(); return #s end)
return r
