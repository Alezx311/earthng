-- In-game comparison: production routing.search vs Rust batch A*, file and socket.
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
local q=256
if exists('route-count.txt') then q=assert(tonumber(get('route-count.txt'))) end
assert(q>=1 and q<=256 and q%1==0, 'route count must be 1..256')
local pairs=ffi.new('uint32_t[?]', 2*q)
for i=0,q-1 do
  local n=(i*7919+17)%g.n
  local target=assert(routing.nearest(g,g.x[n]+1500,g.y[n]+1500))
  pairs[2*i],pairs[2*i+1]=n,target
end
for i=0,math.min(1,q-1) do routing.search(g,tonumber(pairs[2*i]),tonumber(pairs[2*i+1])) end
local dists, expanded, luaMs = {}, {}, {}
local clock=hptimer()
for r=1,3 do
  clock:stopAndReset()
  for i=0,q-1 do dists[i],expanded[i]=routing.search(g,tonumber(pairs[2*i]),tonumber(pairs[2*i+1])) end
  luaMs[r]=clock:stopAndReset()
end
local graph='ERG1'..word(g.n)..word(g.arcs)..ffi.string(g.x,8*g.n)..ffi.string(g.y,8*g.n)
  ..ffi.string(g.first,4*(g.n+1))..ffi.string(g.used,4*g.n)..ffi.string(g.to,4*g.arcs)..ffi.string(g.cost,4*g.arcs)
local points=ffi.string(pairs,8*q)
local levels={}
for _,workers in ipairs({1,2,4,8,12,16}) do for _=1,12 do levels[#levels+1]=workers end end
local reachable=0; for i=0,q-1 do if dists[i] then reachable=reachable+1 end end
local report={nodes=g.n,arcs=g.arcs,queries=q,reachable=reachable,luaMs=luaMs,graphBytes=#graph,queryBytes=8+#points,file={},socket={}}
local mode, step, round, elapsed, pending, tcp = 'file', 'load', 0, 0, nil, nil
local function result(data)
  assert(data:sub(1,4)=='ERR1' and #data==24+12*q,'invalid response')
  local head=ffi.new('uint32_t[3]'); ffi.copy(head,data:sub(5,16),12)
  assert(head[0]==q,'invalid count')
  local u,d=ffi.new('uint32_t[1]'),ffi.new('double[1]')
  for i=0,q-1 do
    local p=17+12*i
    ffi.copy(d,data:sub(p,p+7),8); ffi.copy(u,data:sub(p+8,p+11),4)
    local got=tonumber(d[0]); local want=dists[i]
    assert((want==nil and got==math.huge) or (want and math.abs(got-want)<1e-7), 'cost mismatch '..i)
    assert(tonumber(u[0])==expanded[i], 'expanded mismatch '..i..' '..tonumber(u[0])..' '..expanded[i])
  end
  local cpu=ffi.new('uint32_t[2]'); ffi.copy(cpu,data:sub(17+12*q,24+12*q),8)
  local cpuMs=(tonumber(cpu[0])+tonumber(cpu[1])*4294967296)/1000
  return (tonumber(head[1])+tonumber(head[2])*4294967296)/1000, cpuMs
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
local lastPhase
local function send(data)
  local phase=mode..'-'..tostring(levels[round])
  if phase~=lastPhase then put('bench-phase.txt',phase); lastPhase=phase end
  if mode=='file' then file_send(data) else socket_send(data) end
end
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
  if elapsed>180 then if tcp then tcp:close() end; put('bench-stop','1'); return {error='timeout',partial=report} end
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
    step='query'; round=1; send('ERQ1'..word(levels[round])..points); return
  end
  local rustMs,cpuMs=result(data)
  local ms=pending.clock:stopAndReset()
  local list=report[mode]
  local group=list[#list]
  if not group or group.workers~=levels[round] then
    group={workers=levels[round],roundtripMs={},rustMs={},cpuMs={},bytes=pending.bytes,mismatches=0}
    list[#list+1]=group
  end
  group.roundtripMs[#group.roundtripMs+1]=ms
  group.rustMs[#group.rustMs+1]=rustMs
  group.cpuMs[#group.cpuMs+1]=cpuMs
  if round<#levels then round=round+1; send('ERQ1'..word(levels[round])..points); return end
  if mode=='file' then step='connect'; return end
  tcp:close(); put('bench-stop','1'); put('bench-phase.txt','done')
  jsonWriteFile(root..'bench-scaling.json',report,true)
  return report
end)
