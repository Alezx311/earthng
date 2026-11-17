local PLUGIN = "myPlugin"

function onInit()
  MP.RegisterEvent("onChatMessage", "onChatMessage")
  MP.RegisterEvent("myPlugin:ping", "onPing")
  print(PLUGIN .. " loaded")
end

function onChatMessage(pid, name, msg)
  if msg == "/ping" then
    MP.SendChatMessage(pid, "pong")
    return 1
  end
  return 0
end

function onPing(payload)
  print("client ping: " .. tostring(payload))
end

MP.RegisterEvent("onInit", "onInit")
