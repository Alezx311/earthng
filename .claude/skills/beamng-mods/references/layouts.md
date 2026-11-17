# Folder Layouts

## BeamMP server plugin

```text
Resources/
  Server/
    MyPlugin/
      main.lua
      lib/
        helpers.lua
```

Notes:
- Keep entry file as `main.lua`.
- Top-level `.lua` files load alphabetically.
- Subfolders are ignored unless required from top-level files.

## BeamMP client resource (sent by server)

```text
Resources/
  Client/
    MyPlugin.zip/
      scripts/
        modScript.lua
      lua/
        ge/
          extensions/
            myPlugin.lua
```

Notes:
- `Resources/Client` should contain zip mods.
- `modScript.lua` loads your extension for the client.

## BeamNG extension mod

```text
(myMod.zip or mods/unpacked/myMod)/
  lua/
    common/extensions/
    ge/extensions/
    vehicle/extensions/
```

VM mapping:
- `/lua/ge/` -> GELUA
- `/lua/vehicle/` -> VLUA
- `/lua/common/` -> shared libs used by GE/VLUA

## Multiplayer event flow

Server -> client:
1. `MP.TriggerClientEvent(...)`
2. `AddEventHandler("event", handler)` on client

Client -> server:
1. `TriggerServerEvent(...)`
2. `MP.RegisterEvent("event", "handler")` on server
