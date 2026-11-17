# BeamMP Server API Quick Reference

## Main functions

- `MP.RegisterEvent(eventName, handlerName)`
- `MP.CreateEventTimer(eventName, intervalMs[, strategy])`
- `MP.CancelEventTimer(eventName)`
- `MP.TriggerLocalEvent(eventName, ...)`
- `MP.TriggerGlobalEvent(eventName, ...)`
- `MP.TriggerClientEvent(playerId, eventName, dataString)`
- `MP.TriggerClientEventJson(playerId, eventName, dataTable)`
- `MP.SendChatMessage(playerIdOrMinus1, message)`
- `MP.GetPlayers()`, `MP.GetPlayerCount()`, `MP.GetPlayerName(id)`
- `MP.GetPlayerIdentifiers(id)`, `MP.IsPlayerGuest(id)`, `MP.DropPlayer(id, reason)`
- `MP.GetPlayerVehicles(id)`, `MP.RemoveVehicle(id, vehicleId)`, `MP.GetPositionRaw(pid, vid)`
- `Util.JsonEncode`, `Util.JsonDecode`
- `FS.CreateDirectory`, `FS.Exists`, `FS.ListFiles`, `FS.ConcatPaths`

## High-value built-in events

- `onInit`, `onShutdown`, `onConsoleInput`
- `onPlayerAuth`, `onPlayerConnecting`, `onPlayerJoining`, `onPlayerDisconnect`
- `onChatMessage`
- `onVehicleSpawn`, `onVehicleEdited`, `onVehicleDeleted`, `onVehicleReset`
- `onFileChanged` (v3.1.0+)

## Event order on join

1. `onPlayerAuth`
2. `onPlayerConnecting`
3. `onPlayerJoining`
4. `onPlayerJoin`

## Practical notes

- For cancellable events, return `1` (or rejection string where supported).
- Use `-1` as player id to broadcast in send/trigger functions.
- Keep timer counts low; reuse shared periodic events when possible.
