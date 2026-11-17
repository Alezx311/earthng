# BeamNG Extension API Quick Reference

## Extension shape

```lua
local M = {}

M.onExtensionLoaded = function()
  -- init
end

M.onUpdate = function(dtReal, dtSim, dtRaw)
  -- per-frame (GE)
end

return M
```

## Typical operations

- Load extension: `extensions.load("myMod_myExtension")`
- Broadcast hook to loaded extensions: `extensions.hook("eventName", ...)`
- Unload extension: `extensions.unload("myMod_myExtension")`

## VM placement guide

- Use `lua/ge/extensions` for game-engine systems and world logic.
- Use `lua/vehicle/extensions` for per-vehicle behavior.
- Use `lua/common/extensions` for shared helpers used across VMs.

## Dev reload shortcuts

- GELUA reload: `Ctrl-L`
- VLUA reload (focused vehicle): `Ctrl-R`
- UI reload: `F5`
