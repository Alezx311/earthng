-- Experimental opt-in adapter: source cells -> async Rust request -> per-building
-- roof triangles. No engine calls; all missing/invalid data falls back to Lua.
local ffi = require('ffi')
local M = {}
local MAX_POLYGONS, MAX_POINTS, MAX_REQUEST = 20000, 300000, 8 * 1024 * 1024
local function finite(v) return type(v) == 'number' and v == v and v ~= math.huge and v ~= -math.huge end
local function word(n) return ffi.string(ffi.new('uint32_t[1]', n), 4) end
local function numbers(values)
  local a = ffi.new('double[?]', #values)
  for i, value in ipairs(values) do a[i-1] = value end
  return ffi.string(a, #values * 8)
end
local function readword(data, p)
  local a = ffi.new('uint32_t[1]'); ffi.copy(a, data:sub(p,p+3),4); return tonumber(a[0])
end
local function readdouble(data, p)
  local a = ffi.new('double[1]'); ffi.copy(a, data:sub(p,p+7),8); return tonumber(a[0])
end

function M.start(client, sock, cells, rect, far, job, epoch, workers)
  if type(rect) ~= 'table' or #rect ~= 4 then return nil, 'rectangle' end
  for _, x in ipairs(rect) do if not finite(x) then return nil, 'rectangle' end end
  if rect[1] > rect[3] or rect[2] > rect[4] then return nil, 'rectangle' end
  if type(workers) ~= 'number' or workers % 1 ~= 0 or workers < 1 or workers > 32 then return nil, 'workers' end
  local seen, buildings, pieces, total = {}, {}, {}, 0
  for _, cell in ipairs(cells or {}) do
    for index, building in ipairs(cell.buildings or {}) do
      local id = tostring(building.id or index)
      if not seen[id] then
        seen[id] = true
        local rings = building.rings
        local valid = type(rings) == 'table' and #rings <= 10000
        local part, count = {}, 0
        if valid then
          part[#part+1] = word(#rings)
          for _, ring in ipairs(rings) do
            local vals = {}
            if type(ring) ~= 'table' then valid = false; break end
            part[#part+1] = word(#ring)
            for _, p in ipairs(ring) do
              if type(p) ~= 'table' or not finite(p[1]) or not finite(p[2]) or not finite(p[3]) then
                valid = false; break
              end
              vals[#vals+1], vals[#vals+2], vals[#vals+3] = p[1],p[2],p[3]
              count = count + 1
              if total + count > MAX_POINTS then return nil, 'point limit' end
            end
            if not valid then break end
            part[#part+1] = numbers(vals)
          end
        end
        if valid then
          buildings[#buildings+1] = building
          pieces[#pieces+1] = table.concat(part)
          total = total + count
          if #buildings > MAX_POLYGONS then return nil, 'polygon limit' end
        end
      end
    end
  end
  local body = (far and 'EFG1' or 'ETG1') .. word(workers) .. word(#buildings)
    .. numbers(rect) .. table.concat(pieces)
  if #body > MAX_REQUEST then return nil, 'request limit' end
  local ok, transport = pcall(client.new, sock, body, job, epoch, far and 1 or 0)
  if not ok then return nil, 'transport' end
  local state = {transport=transport, buildings=buildings, cache={}, done=false}
  function state:cancel() self.transport:cancel(); self.done=true end
  function state:step()
    if self.done then return self.error and false or true, self.error end
    local data, err = self.transport:step()
    if data == nil then return nil end
    if data == false then self.done,self.error=true,err; return false,err end
    if #data < 16 or data:sub(1,4) ~= 'ETR1' or readword(data,5) ~= #self.buildings then
      self.done,self.error=true,'invalid response'; return false,self.error
    end
    local pos, cache = 17, {}
    for _, building in ipairs(self.buildings) do
      if pos+3 > #data then self.done,self.error=true,'truncated result'; return false,self.error end
      local count=readword(data,pos); pos=pos+4
      if count > math.floor((#data-pos+1)/72) then self.done,self.error=true,'triangle limit'; return false,self.error end
      local triangles={}
      for i=1,count do
        local tri={}
        for j=1,3 do
          local x,y,z=readdouble(data,pos),readdouble(data,pos+8),readdouble(data,pos+16)
          if not finite(x) or not finite(y) or not finite(z) then self.done,self.error=true,'invalid coordinate'; return false,self.error end
          tri[j]={x,y,z}; pos=pos+24
        end
        triangles[i]=tri
      end
      cache[building]=triangles
    end
    if pos ~= #data+1 then self.done,self.error=true,'trailing data'; return false,self.error end
    self.cache,self.done=cache,true
    return true
  end
  return state
end
return M
