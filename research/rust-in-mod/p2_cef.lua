-- CEF side: WebAssembly, workers, fetch of mod files; result comes back through sendEngineLua.
_G.__e2rjs = function(s) _G.__e2rjsOut = s end
_G.__e2rjsOut = nil
local js = [[
(async function(){
 const out = {};
 const send = (o) => window.beamng.sendEngineLua('__e2rjs(' + bngApi.serializeToLua(JSON.stringify(o)) + ')');
 try {
  out.ua = navigator.userAgent; out.cores = navigator.hardwareConcurrency; out.location = location.href;
  out.wasm = typeof WebAssembly;
  out.wasmGlobalNames = Object.getOwnPropertyNames(self).filter(n=>/wasm|assembly/i.test(n)).join(',');


  out.worker = typeof Worker; out.sab = typeof SharedArrayBuffer; out.coi = self.crossOriginIsolated;
  try {
   const w = new Worker(URL.createObjectURL(new Blob(['onmessage=e=>postMessage([e.data*2, typeof WebAssembly])'],{type:'text/javascript'})));
   out.workerRes = await new Promise((res,rej)=>{w.onmessage=e=>res(e.data); w.onerror=e=>rej(e.message||'err'); w.postMessage(21); setTimeout(()=>rej('timeout'),3000)});
   w.terminate();
  } catch(e){ out.workerErr = String(e); }
  const urls = ['/lua/ge/extensions/e2r/quality.lua', 'local://local/lua/ge/extensions/e2r/quality.lua',
    '/earthng/countries/ukraine/regions/e0210-n480/blocks/3_-6.bin', 'local://local/earthng/countries/ukraine/regions/e0210-n480/blocks/3_-6.bin'];
  for (const u of urls) {
   try { const t0 = performance.now(); const r = await fetch(u); const b = await r.arrayBuffer(); out['fetch ' + u] = r.status + ' ' + b.byteLength + ' ' + (performance.now()-t0).toFixed(1) + 'ms'; }
   catch(e) { out['fetch ' + u] = 'ERR ' + e; }
  }
  try { const t0 = performance.now(); let x = 0; for (let i = 0; i < 1e8; i++) x = (x + i * 7) | 0; out.jsLoop1e8ms = (performance.now()-t0).toFixed(1) + ' ' + x; } catch(e) {}
 } catch(e) { out.err = String(e) + ' ' + (e && e.stack); }
 send(out);
})();
]]
be:executeJS(js)
local t0 = 0
return P.task(function(dt)
  t0 = t0 + (dt or 0)
  if _G.__e2rjsOut then return _G.__e2rjsOut end
  if t0 > 20 then return 'TIMEOUT in game' end
end)
