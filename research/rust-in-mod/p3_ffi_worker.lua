-- FFI data path pieces + a worker from a file in the user folder + the same loop in LuaJIT.
local ffi = require('ffi')
local r = {}
local function try(name, fn) local ok, v = pcall(fn); r[name] = ok and v or ('ERR ' .. tostring(v)) end
-- raw little-endian bytes of floats 1.5, -2.25 and of uint32 7, 70000
local fbytes = '\0\0\192\63' .. '\0\0\16\192'
try('copyFloat', function() local a = ffi.new('float[2]'); ffi.copy(a, fbytes, 8); return a[0] .. ' ' .. a[1] end)
try('copyFloatOffset', function() local s = 'xx' .. fbytes; local a = ffi.new('float[2]'); ffi.copy(a, s:sub(3), 8); return a[1] end)
try('copyU32', function() local a = ffi.new('uint32_t[2]'); ffi.copy(a, '\7\0\0\0\112\17\1\0', 8); return a[0] .. ' ' .. a[1] end)
try('copyStruct', function()
  ffi.cdef('typedef struct { float x, y, z; uint16_t kind, flags; } e2rp_pt;')
  local a = ffi.new('e2rp_pt[1]'); ffi.copy(a, fbytes .. fbytes:sub(1, 4) .. '\3\0\5\0', 16); return a[0].x .. ' ' .. a[0].z .. ' ' .. a[0].kind .. ' ' .. a[0].flags end)
try('union', function()
  ffi.cdef('typedef union { uint8_t b[4]; float f; uint32_t u; } e2rp_pun;')
  local u = ffi.new('e2rp_pun'); u.f = 1.5; return u.b[3] .. ' ' .. u.u end)
try('vla', function() local a = ffi.new('float[?]', 1000000); return ffi.sizeof(a) end)
try('arrToString', function() local a = ffi.new('float[2]', 1.5, -2.25); return ffi.string(a, 8) == fbytes end)
-- garbage of a 1M float array vs a table of 1M numbers
try('gcArr', function()
  collectgarbage('collect'); local k0 = collectgarbage('count')
  local a = ffi.new('float[?]', 1000000); local k1 = collectgarbage('count')
  local t = {}; for i = 1, 1000000 do t[i] = i * 0.5 end; local k2 = collectgarbage('count')
  return string.format('ffi %.0f KB, table %.0f KB', k1 - k0, k2 - k1) end)
-- the JS loop, in LuaJIT
try('luaLoop1e8ms', function()
  local t = hptimer(); local x = 0
  for i = 0, 1e8 - 1 do x = bit.tobit(x + i * 7) end
  return string.format('%.1f %d', t:stop(), x) end)
-- worker from a file in the user folder (VFS)
local f = io.open('e2r_probe/w.js', 'w'); f:write('onmessage=function(e){postMessage([e.data*2, typeof WebAssembly])}'); f:close()
_G.__e2rjs = function(s) _G.__e2rjsOut = s end
_G.__e2rjsOut = nil
be:executeJS([[
(async function(){
 const out = {};
 for (const u of ['local://local/e2r_probe/w.js', '/e2r_probe/w.js']) {
  try {
   const w = new Worker(u);
   out[u] = await new Promise((res,rej)=>{w.onmessage=e=>res(e.data); w.onerror=e=>rej('onerror ' + (e.message||'')); w.postMessage(21); setTimeout(()=>rej('timeout'),3000)});
   w.terminate();
  } catch(e) { out[u] = 'ERR ' + e; }
 }
 window.beamng.sendEngineLua('__e2rjs(' + bngApi.serializeToLua(JSON.stringify(out)) + ')');
})();]])
local t0 = 0
return P.task(function(dt)
  t0 = t0 + (dt or 0)
  if _G.__e2rjsOut or t0 > 15 then r.worker = _G.__e2rjsOut or 'TIMEOUT'; return r end
end)
