local M = {}

local function onServerHello(data)
  log("I", "myPlugin", "server says: " .. tostring(data))
end

M.onExtensionLoaded = function()
  AddEventHandler("myPlugin:hello", onServerHello)
  TriggerServerEvent("myPlugin:ping", '{"from":"client"}')
end

return M
