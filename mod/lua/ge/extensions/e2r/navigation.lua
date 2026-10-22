-- Simplify road-profile knots once when streamed, keeping junction endpoints and real bends.
-- Iterative RDP tests every removed point: <=1 m horizontal and <=0.5 m vertical deviation.
local M = {}
function M.simplify(s)
  local last = #s - 2
  if last <= 11 then return s end
  local keep, stack = {[8] = true, [last] = true}, {{8, last}}
  while #stack > 0 do
    local span = table.remove(stack)
    local a, b = span[1], span[2]
    local dx, dy, dz = s[b]-s[a], s[b+1]-s[a+1], s[b+2]-s[a+2]
    local length2 = dx*dx + dy*dy
    local worst, at = 1, nil
    for k = a+3, b-3, 3 do
      local f = length2 > 1e-8 and math.max(0, math.min(1, ((s[k]-s[a])*dx + (s[k+1]-s[a+1])*dy)/length2)) or 0
      local ex, ey, ez = s[k]-s[a]-f*dx, s[k+1]-s[a+1]-f*dy, s[k+2]-s[a+2]-f*dz
      local error = math.max(ex*ex+ey*ey, 4*ez*ez)
      if error > worst then worst, at = error, k end
    end
    if at then
      keep[at] = true
      stack[#stack+1], stack[#stack+2] = {a,at}, {at,b}
    end
  end
  local out = {}
  for k=1,7 do out[k] = s[k] end
  for k=8,last,3 do
    if keep[k] then out[#out+1],out[#out+2],out[#out+3] = s[k],s[k+1],s[k+2] end
  end
  return out
end
return M
