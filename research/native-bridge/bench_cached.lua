-- In-game comparison: same graph, same solver, file vs loopback socket.
local ffi = require('ffi')
local routing = require('ge/extensions/e2r/routing')
local root, path = 'e2r_bridge/', '/earthng/countries/ukraine/routing/e0300-n500.bin'
local function put(n, s) local f = assert(io.open(root..n, 'wb')); assert(f:write(s)); f:close() end
local function get(n) local f = assert(io.open(root..n, 'rb')); local s=f:read('*a'); f:close(); return s end
local function exists(n) return FS:fileExists('/'..root..n) end
local function del(n) FS:removeFile('/'..root..n) end
local function word(x) local a=ffi.new('uint32_t[1]', x); return ffi.string(a, 4) end
local f=assert(io.open(path,'rb')); local b=f:read('*a'); f:close()
local g=routing.graph({routing.decode(b)})
local q=128
local coords=ffi.new('double[?]', 2*q)
for i=0,q-1 do local n=(i*7919+17)%g.n; coords[2*i]=g.x[n]+13.25; coords[2*i+1]=g.y[n]-9.75 end
for i=0,7 do routing.nearest(g,coords[2*i],coords[2*i+1]) end
local ids, dists, luaMs = {}, {}, {}
local clock=hptimer()
for r=1,3 do
  clock:stopAndReset()
  for i=0,q-1 do ids[i],dists[i]=routing.nearest(g,coords[2*i],coords[2*i+1]) end
  luaMs[r]=clock:stopAndReset()
end
local graph='ENG1'..word(g.n)..ffi.string(g.x,8*g.n)..ffi.string(g.y,8*g.n)..ffi.string(g.used,4*g.n)
local points=ffi.string(coords,16*q)
local levels={1,4,1,4,1,4}
local report={nodes=g.n,queries=q,luaMs=luaMs,graphBytes=#graph,queryBytes=8+#points,file={},socket={}}
local mode, step, round, elapsed, pending, tcp = 'file', 'load', 0, 0, nil, nil
local function result(data)
  assert(data:sub(1,4)=='ENR1' and #data==16+12*q,'invalid response')
  local head=ffi.new('uint32_t[3]'); ffi.copy(head,data:sub(5,16),12)
  assert(head[0]==q,'invalid count')
  local u,d=ffi.new('uint32_t[1]'),ffi.new('double[1]')
  for i=0,q-1 do
    local p=17+12*i
    ffi.copy(u,data:sub(p,p+3),4); ffi.copy(d,data:sub(p+4,p+11),8)
    assert(tonumber(u[0])==ids[i] and math.abs(tonumber(d[0])-dists[i])<1e-7,'parity mismatch '..i)
  end
  return (tonumber(head[1])+tonumber(head[2])*4294967296)/1000
end
local function file_send(data)
  pending={clock=hptimer(),bytes=#data}
  put('bench-request.bin',data); put('bench-request.ready','1')
end
local function socket_send(data)
  pending={clock=hptimer(),bytes=#data,send=word(#data)..data,at=1,recv='',need=4,header=true}
  local n,err,last=tcp:send(pending.send,pending.at)
  if n then pending.at=n+1 elseif err=='timeout' then pending.at=(last or 0)+1 else error('socket send: '..tostring(err)) end
end
local function send(data) if mode=='file' then file_send(data) else socket_send(data) end end
local function receive()
  if mode=='file' then
    if not exists('bench-response.ready') then return end
    local e=exists('bench-error.txt') and get('bench-error.txt')
    assert(not e,e)
    local data=get('bench-response.bin'); del('bench-response.ready'); del('bench-response.bin')
    return data
  end
  if pending.at<=#pending.send then
    local n,err,last=tcp:send(pending.send,pending.at)
    if n then pending.at=n+1 elseif err=='timeout' then pending.at=(last or pending.at-1)+1 else error('socket send: '..tostring(err)) end
    if pending.at<=#pending.send then return end
  end
  local part,err,partial=tcp:receive(pending.need-#pending.recv)
  pending.recv=pending.recv..(part or partial or '')
  if err and err~='timeout' then error('socket read: '..tostring(err)) end
  if #pending.recv<pending.need then return end
  if pending.header then
    local a=ffi.new('uint32_t[1]'); ffi.copy(a,pending.recv,4)
    pending.need=tonumber(a[0]); assert(pending.need<=65536,'invalid frame')
    pending.recv=''; pending.header=false
    local body,bodyerr,bodypartial=tcp:receive(pending.need)
    pending.recv=body or bodypartial or ''
    if bodyerr and bodyerr~='timeout' then error('socket body: '..tostring(bodyerr)) end
    if #pending.recv<pending.need then return end
  end
  return pending.recv
end
file_send(graph)
return P.task(function(dt)
  elapsed=elapsed+(dt or 0)
  if elapsed>100 then if tcp then tcp:close() end; put('bench-stop','1'); return {error='timeout',partial=report} end
  if step=='connect' then
    local ok,err=pcall(function()
      local socket=require('socket'); tcp=assert(socket.tcp()); tcp:settimeout(0.1); tcp:setoption('tcp-nodelay',true)
      assert(tcp:connect('127.0.0.1',tonumber(get('bench-port.txt'))))
      tcp:settimeout(0)
    end)
    if not ok then report.socketError=tostring(err); put('bench-stop','1'); return report end
    mode='socket'; step='load'; socket_send(graph); return
  end
  local ok,data=pcall(receive)
  if not ok then
    if mode=='socket' then report.socketError=tostring(data); if tcp then tcp:close() end; put('bench-stop','1'); return report end
    error(data)
  end
  if not data then return end
  if step=='load' then
    assert(data=='EOK1',data)
    report[mode..'LoadMs']=pending.clock:stopAndReset()
    step='query'; round=1; send('ENQ1'..word(levels[round])..points); return
  end
  local rustMs=result(data)
  local ms=pending.clock:stopAndReset()
  report[mode][#report[mode]+1]={workers=levels[round],rustMs=rustMs,roundtripMs=ms,bytes=pending.bytes,mismatches=0}
  if round<#levels then round=round+1; send('ENQ1'..word(levels[round])..points); return end
  if mode=='file' then step='connect'; return end
  tcp:close(); put('bench-stop','1'); return report
end)
