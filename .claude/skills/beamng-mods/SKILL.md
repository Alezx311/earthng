---
name: beamng-mods
description: Build and debug BeamNG.drive and BeamMP mods, resources, and server plugins using Lua. Use this skill whenever the user mentions BeamNG modding, BeamMP, `Resources/Server`, `Resources/Client`, `modScript.lua`, `lua/ge/extensions`, `extensions.load`, `MP.RegisterEvent`, `AddEventHandler`, client/server event wiring, custom vehicles, gameplay scripts, or BeamNG Lua hooks.
version: 1.0.0
source: local
license: MIT
---

# BeamNG + BeamMP Modding

Build, scaffold, and debug:
- BeamMP server plugins
- BeamMP client mods (`modScript.lua` + GE extension)
- BeamNG Lua extensions (`common/ge/vehicle`)

Keep responses concise and implementation-first. Prefer small working patches.

## First Decision

Choose one target before writing code:
1. `beammp-server`
2. `beammp-client`
3. `beamng-only`

If target is unclear, ask one short clarifying question.

## Progressive Loading

Load only what is needed.

For `beammp-server`:
- `references/layouts.md`
- `references/beammp-server-api.md`
- `examples/beammp-server-main.lua` (when scaffolding code)

For `beammp-client`:
- `references/layouts.md`
- `references/beammp-client-api.md`
- `examples/beammp-client-extension.lua`
- `examples/modScript.lua`

For `beamng-only`:
- `references/layouts.md`
- `references/beamng-extension-api.md`
- `examples/beamng-ge-extension.lua` (or adapt for common/vehicle VM)

## Core Rules

- Namespace custom events as `pluginName:eventName`.
- Use JSON payloads for client/server boundaries and validate inputs.
- Keep event handlers short; avoid long blocking loops/sleeps.
- Prefer one small, testable feature per iteration.
- If any local stubs are provided, treat them as helper hints only; prefer official docs on conflicts.

## Output Format

When implementing/scaffolding, include:
1. Target type (`beammp-server`, `beammp-client`, or `beamng-only`)
2. Final file tree
3. Code changes
4. Quick test steps

## Sources

Prefer official docs first:
- https://docs.beammp.com/scripting/server/latest-server-reference/
- https://docs.beammp.com/scripting/mod-reference/
- https://docs.beammp.com/guides/mod-creation/server/getting-started/
- https://docs.beamng.com/modding/programming/extensions/
- https://docs.beamng.com/modding/programming/virtualmachines/

Optional local sources (only if present in the current repo):
- BeamMP/BeamNG Lua stubs
