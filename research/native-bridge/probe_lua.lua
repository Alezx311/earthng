-- Run only in a disposable profile via earthng/probe.py.
local root = 'e2r_bridge/'
local function put(name, data)
  local f = assert(io.open(root .. name, 'wb'))
  f:write(data)
  f:close()
end
put('bridge-request.txt', '17 123456 789')
put('bridge-request.ready', 'ready')
local elapsed = 0
return P.task(function(dt)
  elapsed = elapsed + (dt or 0)
  if FS:fileExists('/e2r_bridge/bridge-response.ready') then
    local f = assert(io.open(root .. 'bridge-response.txt', 'rb'))
    local result = f:read('*a')
    f:close()
    put('bridge-stop', 'stop')
    return {answer = result, seconds = elapsed}
  end
  if elapsed > 10 then return {error = 'timeout'} end
end)
