-- Test-profile only. Compare real Kyiv XYZ footprints with production triangulate.
local ffi=require('ffi')
local generator=require('ge/extensions/e2r/generator')
local root='e2r_bridge/'
local data=assert(jsonReadFile(root..'roofs.json'))
local polygons,rect=data.polygons,data.rect
local function put(n,s) local f=assert(io.open(root..n,'wb'));assert(f:write(s));f:close() end
local function get(n) local f=assert(io.open(root..n,'rb'));local s=f:read('*a');f:close();return s end
local function word(x) local a=ffi.new('uint32_t[1]',x);return ffi.string(a,4) end
local function doubles(values) local a=ffi.new('double[?]',#values);for i,v in ipairs(values) do a[i-1]=v end;return ffi.string(a,8*#values) end
local function lua_run()
  local out={};for i,rings in ipairs(polygons) do out[i]=generator.triangulate(rings,nil,rect) end;return out
end
lua_run()
local times,expected,timer={},nil,hptimer()
for i=1,5 do timer:stopAndReset();expected=lua_run();times[i]=timer:stopAndReset() end
local payload={};local tris=0
for _,rings in ipairs(polygons) do
  payload[#payload+1]=word(#rings)
  for _,ring in ipairs(rings) do
    payload[#payload+1]=word(#ring)
    local nums={};for _,p in ipairs(ring) do assert(#p==3);nums[#nums+1]=p[1];nums[#nums+1]=p[2];nums[#nums+1]=p[3] end
    payload[#payload+1]=doubles(nums)
  end
end
for _,t in ipairs(expected) do tris=tris+#t end
local body=table.concat(payload)
local levels={1,4,1,4,1,4,1,4,1,4}
local report={buildings=#polygons,triangles=tris,luaMs=times,rect=rect,source=data.source,results={}}
local tcp,round,pending,elapsed=nil,0,nil,0
local function submit()
  round=round+1
  local request='ETG1'..word(levels[round])..word(#polygons)..doubles(rect)..body
  pending={clock=hptimer(),bytes=#request,send=word(#request)..request,at=1,recv='',need=4,header=true}
  local n,err,last=tcp:send(pending.send,pending.at)
  if n then pending.at=n+1 elseif err=='timeout' then pending.at=(last or 0)+1 else error('send: '..tostring(err)) end
end
local function receive()
  if pending.at<=#pending.send then
    local n,err,last=tcp:send(pending.send,pending.at)
    if n then pending.at=n+1 elseif err=='timeout' then pending.at=(last or pending.at-1)+1 else error('send: '..tostring(err)) end
    if pending.at<=#pending.send then return end
  end
  local part,err,partial=tcp:receive(pending.need-#pending.recv)
  pending.recv=pending.recv..(part or partial or '')
  if err and err~='timeout' then error('receive: '..tostring(err)) end
  if #pending.recv<pending.need then return end
  if pending.header then
    local a=ffi.new('uint32_t[1]');ffi.copy(a,pending.recv,4);pending.need=tonumber(a[0])
    assert(pending.need<16*1024*1024,'oversized response');pending.recv='';pending.header=false
    local d,e,p=tcp:receive(pending.need);pending.recv=d or p or ''
    if e and e~='timeout' then error('body: '..tostring(e)) end
    if #pending.recv<pending.need then return end
  end
  return pending.recv
end
local function verify(s)
  assert(s:sub(1,4)=='ETR1','bad response: '..s:sub(1,100))
  local head=ffi.new('uint32_t[3]');ffi.copy(head,s:sub(5,16),12);assert(head[0]==#polygons,'wrong count')
  local ms=(tonumber(head[1])+tonumber(head[2])*4294967296)/1000
  local pos,maxError=17,0
  local u,d=ffi.new('uint32_t[1]'),ffi.new('double[1]')
  for bi,want in ipairs(expected) do
    assert(pos+3<=#s,'truncated count');ffi.copy(u,s:sub(pos,pos+3),4);pos=pos+4
    assert(tonumber(u[0])==#want,'triangle count mismatch '..bi)
    for _,tri in ipairs(want) do for _,point in ipairs(tri) do for axis=1,3 do
      assert(pos+7<=#s,'truncated vertex');ffi.copy(d,s:sub(pos,pos+7),8);pos=pos+8
      local e=math.abs(tonumber(d[0])-point[axis]);maxError=math.max(maxError,e);assert(e<=1e-8,'vertex mismatch '..bi)
    end end end
  end
  assert(pos==#s+1,'trailing result')
  return ms,maxError
end
local socket=require('socket');tcp=assert(socket.tcp());tcp:settimeout(.1);tcp:setoption('tcp-nodelay',true)
assert(tcp:connect('127.0.0.1',tonumber(get('bench-port.txt'))));tcp:settimeout(0);submit()
return P.task(function(dt)
  elapsed=elapsed+(dt or 0);if elapsed>90 then tcp:close();put('bench-stop','1');return {error='timeout'} end
  local result=receive();if not result then return end
  local e2e=pending.clock:stopAndReset()
  local rustMs,maxError=verify(result);local verifyMs=pending.clock:stopAndReset()
  report.results[#report.results+1]={workers=levels[round],rustMs=rustMs,roundtripMs=e2e,verifyMs=verifyMs,maxError=maxError,requestBytes=pending.bytes,responseBytes=#result}
  if round<#levels then submit();return end
  tcp:close();put('bench-stop','1');jsonWriteFile(root..'roofs-report.json',report,true);return report
end)
