# BeamMP Client + BeamNG Extension API

## BeamMP client scripting

- `AddEventHandler(eventName, function(data) ... end)`
- `TriggerServerEvent(eventName, dataString)`
- `TriggerClientEvent(eventName, dataString)`

Notes:
- Event payloads are typically strings; JSON is the usual convention.
- Use namespaced event names, e.g. `myPlugin:sync`.

## BeamNG extension system (GE/common/vehicle)

- `extensions.load("myMod_myExtension")`
- `extensions.unload("myMod_myExtension")`
- `extensions.hook("eventName", ...)`
- `extensions.isExtensionLoaded("name")`

Common extension fields/callbacks:
- `M.onExtensionLoaded`
- `M.onUpdate`
- `M.onGuiUpdate`
- `M.onSerialize`
- `M.dependencies = { ... }`

Useful bridge:
- `guihooks.trigger("eventName", payload)`
