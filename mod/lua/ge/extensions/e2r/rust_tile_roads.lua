-- Experimental batched road strip normals and distances. The caller owns the
-- prepared points and falls back to Lua whenever a result is unavailable.
local ffi = require('ffi')
local M = {}
local MAX_POINTS, MAX_ROADS, MAX_REQUEST = 300000, 20000, 8 * 1024 * 1024
local function finite(v) return type(v)=='number' and v==v and v~=math.huge and v~=-math.huge end
local function word(n) return ffi.string(ffi.new('uint32_t[1]',n),4) end
local function numbers(values)
  local a=ffi.new('double[?]',#values)
  for i,v in ipairs(values) do a[i-1]=v end
  return ffi.string(a,#values*8)
end
local function readword(s,p) local a=ffi.new('uint32_t[1]');ffi.copy(a,s:sub(p,p+3),4);return tonumber(a[0]) end
local function readdouble(s,p) local a=ffi.new('double[1]');ffi.copy(a,s:sub(p,p+7),8);return tonumber(a[0]) end

function M.start(client,sock,prepared,roads,mitre,far,job,epoch,workers)
  if not finite(mitre) or mitre<0 then return nil,'mitre' end
  local pieces, selected, counts, total = {}, {}, {}, 0
  for _, road in ipairs(roads) do
    local prep=prepared[road]
    if prep then
      local pts,joints=prep.points,prep.joints or {}
      if #pts<2 then return nil,'points' end
      local coords, flags, jv = {},0,{}
      for i=1,2 do
        local j=joints[i]
        if j then
          if not finite(j[1]) or not finite(j[2]) or not finite(j[3]) then return nil,'joint' end
          flags=flags+2^(i-1)
        end
        for k=1,3 do jv[#jv+1]=j and j[k] or 0 end
      end
      for i,p in ipairs(pts) do
        if not finite(p[1]) or not finite(p[2]) then return nil,'coordinate' end
        if i>1 and p[1]==pts[i-1][1] and p[2]==pts[i-1][2] then return nil,'duplicate' end
        coords[#coords+1],coords[#coords+2]=p[1],p[2]
      end
      total=total+#pts
      if total>MAX_POINTS or #selected>=MAX_ROADS then return nil,'limit' end
      selected[#selected+1]=road
      counts[road]=#pts
      pieces[#pieces+1]=word(#pts)..word(flags)..numbers({mitre})..numbers(jv)..numbers(coords)
    end
  end
  local body='ERD1'..word(workers)..word(#selected)..table.concat(pieces)
  if #body>MAX_REQUEST then return nil,'request limit' end
  local ok,transport=pcall(client.new,sock,body,job,epoch,far and 1 or 0)
  if not ok then return nil,'transport' end
  local state={transport=transport,roads=selected,counts=counts,cache={},done=false}
  function state:cancel() self.transport:cancel();self.done=true end
  function state:step()
    if self.done then return self.error and false or true,self.error end
    local data,err=self.transport:step()
    if data==nil then return nil end
    if data==false then self.done,self.error=true,err;return false,err end
    if #data<8 or data:sub(1,4)~='ERR1' or readword(data,5)~=#self.roads then
      self.done,self.error=true,'invalid response';return false,self.error
    end
    local pos,cache=9,{}
    for _,road in ipairs(self.roads) do
      if pos+3>#data then self.done,self.error=true,'truncated result';return false,self.error end
      local n=readword(data,pos);pos=pos+4
      if n~=self.counts[road] or n>math.floor((#data-pos+1)/24) then
        self.done,self.error=true,'point count';return false,self.error
      end
      local normals,dist={},{}
      for k=1,n do
        local x,y,d=readdouble(data,pos),readdouble(data,pos+8),readdouble(data,pos+16);pos=pos+24
        if not finite(x) or not finite(y) or not finite(d) then self.done,self.error=true,'coordinate';return false,self.error end
        normals[k],dist[k]={x,y},d
      end
      cache[road]={normals,dist}
    end
    if pos~=#data+1 then self.done,self.error=true,'trailing data';return false,self.error end
    self.cache,self.done=cache,true
    return true
  end
  return state
end
return M
