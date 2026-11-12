# EarthNG native mod migration

Newest first. How things work now: [docs/README.md](docs/README.md).

## 2026-11-12: polish for 0.9.0: no knock stall, pedestrians warmed at the landing

- `knock.step` stalled a frame for 375-558 ms once to four times a drive (central Kyiv, 400 flow
  cars, 200 pedestrians). Not the swap, rays or the collector: phase 3, the cell sweep round each
  vehicle. A car just teleported (a hand-off, a reset) reads thousands of m/s for a step, and with a
  long step after a hitch the look-ahead reached kilometres of cells. Now it is reckoned with at most
  120 m/s and a 0.25 s step, the cells reach 80 m at most, and a vehicle first seen faster than
  30 m/s touches nothing for a step (`knock.lua` `STEP_MAX`, `REACH_MAX`, `FRESH_V`). Worst step
  526-558 ms -> 0.35-1.4 ms (out/polish-01..04). The props "nobody" knocked are the game's parked
  cars (`gameplay_parking`) set down on a bench or a bin: it is shoved out from under them.
  `earthng/probe/knock_swap.lua`: the swap itself shows nothing (stills before and after, 5 kinds).
  The knock row (out/polish-knock2): ai 24 of 24, fling 16 and the car stops on the 16th as before,
  swarm 54 bins moved of 90 (59 before) with 4 idle swaps instead of 25, worst step 0.62 ms.
- Pedestrians: a walker's first posed set (nine shapes, ~12 ms each the first time) was a 110 ms
  frame in every drive with walkers. The landing now warms the walker and blood shapes when walkers
  come with the drive (`M.peopleShapes`): `drawMax` 110.8 -> 0.53 ms, the landing's shape warm-up
  626 -> 796 ms.
- Diagnosis in the automation report: a hitch (> 300 ms) carries the Lua parts of its frame over
  20 ms (`flow`, `walk`, `knock` are parts of their own now), `knock.worst` the phases of the worst
  step, `knockCalls` the slowest game call of each kind, `knockBy` who armed and touched props.

## 2026-11-12: blood stains that lie on the road, walls and the car

- In 0.8.7 a stain was a black square: the material's `translucent` blend sat in the stage, where
  the game does not read it, and the alpha was in `baseColorMap`, which it does not read either.
  The car stains hung as flat squares at a fixed height in front of the bonnet, in a row.
  Now (`world.lua` `BLOOD`, `pedhit.lua`, `earthng/people_art.py`): one atlas of a splat and a
  spray, cut by its own `opacityMap`, `alphaTest` on the material. A hit leaves a stain where it
  struck, one or two sprays along the car's way, one on a wall, post or fence within 4 m ahead
  (`castRayStatic`, an upright normal from two side rays) and one on the car, hung on three of its
  nodes on the bonnet so it moves and dents with it and goes when the car is reset. A body come to
  rest bleeds a pool that spreads for 8 s. Ground and walls keep 20 min or until 1.5 km away, the
  car 15 min, 96 in all. `earthng/probe/blood_hit.lua` places them in game: out/blood-06 (Kyiv),
  car stains moved with the car (2.8 m), all ground stains 2.4 cm over the surface below.

## 2026-11-12: release 0.8.7, pedestrians with bodies and blood, and the work since 0.8.2

- Planet and EarthNG.exe 0.8.7: everything since 0.8.2 (15a8ec5) in one release: the Overpass test
  query and the app's logo (EarthNG.exe), pedestrians (6a8c2ff), the faster landing (dc0ab1a, the
  11-10 and 11-11 entries below), engine water and open-land covers (e366b52), tiles ahead at
  speed, knockable street props and the options registry (dbbfe0a: docs/KNOCKDOWN.md,
  docs/INGAME_UI.md), six land levels (ecf3bf4). Checks: docs/RELEASE_CHECK.md.
- Pedestrians (`pedhit.lua`, `world.lua`, `earthng/people_art.py`): a body is placed outside the
  striking car's box with an outward kick and thrown clear on a confirmed hit; a lying body far from
  the player is taken back for a new hit; a walker about to be hit when no body is free is still
  struck (ghost hit), never driven through. Blood stains (`blood_splat.dae`, 48 at most) on the
  road for 180 s and on the car for 45 s. Walker figures of ~450 triangles (shaped limbs, shoes,
  collar, jaw, ears, hair). The pool holds up to 24 bodies: 4 at switch-on, then one at most every
  2 s, only when fewer than 2 are idle or a hit found none, and only with the player's car under
  8 m/s; two spawns a frame at speed were ~4 s of 340 ms frames right after landing (out/all-08).
  `world.lua`'s blood state is one table (`BLOOD`): the main chunk is at LuaJIT's 200 locals.
  Vytachiv, 150 walkers, route at 25 m/s for 70 s (out/all-08, all-10): 2 and 4 hits, all with a
  body, 4 and 8 stains, no ghost hit; with the fill on demand the pool stayed at 4 (all-10).
- Streaming (`native.lua` priorities, `world.lua` updateTiles): the tile under the car is never
  "behind" at speed: past mid-tile its centre lies rearwards, and the road under the wheels was
  dropped and rebuilt every few hundred metres. `keepBack` pads half a tile, as native's AHEAD.
- Far tiles (`native.lua` `trimTiles`, `update`): one evicted in this epoch is built again once it
  fits with a 20 % margin (`active.evictedSize`). After a fast drive the near refill's untaken
  geometry kept the cache over budget, each far tile was evicted as soon as it was built and
  waited for the next epoch (250 m of travel), which a parked car never reached. out/all-11:
  rebuilds 85 instead of 113, drive frames 13.4 ms, p99 31. docs/PERFORMANCE.md.
- Tests: gallery shots record the streaming state (`result.shotStream`: graves, queue, near and
  far wanted, far ready and loaded, cached tiles); the drive ends with the parking brake too (the
  car rolled on into a field while the gallery framed where it had stopped).

## 2026-11-12: open land in six levels, grass in four rings

- Open land (`generator.lua` `VEG.land`, docs/NATURE.md): the levels a land comes into another by
  are six, a seventh of the area each (`fast_style.LAND_COVER`, one mask, `alphaRef` per level):
  with three, a quarter each, their borders read from the road as a grid of 12.5 m squares. Each
  half of a piece takes the land at its own centre, so a border steps along the diagonals.
- Far tiles draw open land as the near ones do (`bio.landFarTri`: the mean of three points of the
  near lattice, a cut/fade pair) instead of one land per 100 m triangle from its centre.
- The lawn reads the land's raw field (`VEG.lawnLand`), each 2 m sample's thresholds shifted by
  its own hash (`VEG.lawnDither`): a thin lawn no longer ends in a straight line along the pieces.
  Thin lawn is the game's dry tufts (`VEG.dryLawn`). `detail.lua`: four grass rings
  (`grassNear`, `grassInner`, `grassMid`, `grass`), each ring's tufts wider than the nearer one's.
- Darker `grass` and `lush` sheets (`fast_photo.MACRO`, land art version 4).
- `test_generator_context`: the scheduler test drives at 60 m/s, so its corridor reaches a tile
  the landing did not build (at 25 m/s the keep bubble of dbbfe0a holds only built tiles).
- Cost (`biome_census`, Vytachiv 3x3): 63.6 k ground triangles (57.4 k with three levels, 42.3 k
  without the layer); up to 39 land materials a tile instead of 21.

## 2026-11-11: a third less generator garbage, the landing in ~28.8 s

- Generator output as FFI structs in the game (`generator.lua` `POINT`, `CORNER`, `MESHUV`): vertices
  and normals the game's vec3, faces `{int32 v, n, u}`, UVs `{double u, v}`. createMesh reads them
  by field name like tables (research/rust-in-mod/p20_mesh_cdata.lua), at 38-50 B each instead of
  120-170 B, and the collector does not walk them. Outside the game (lupa) they stay tables.
- Transient tables gone from hot loops: the press list, the slope closure per ground corner, the
  per-point normal cache entry, `ringBounds({ring})` in per-segment bounds tests (`BOX.*`), the
  spawn-search lerp, the double point in `SOLID.face`, `{x, y}` in `onAsphalt`. Output identical
  (digest of 3x3 central Kyiv tiles near and far, and a suburb).
- Garbage per central Kyiv tile 113 -> 76 MB; landing 31.3 -> 28.2-30.1 s (out/gc-01..07); landing
  LuaGC 6.0 -> 4.0-4.4 s; generator garbage per frame 664 -> 482-529 KB.
- `gc.lua` guard thresholds 96/48 -> 48/24 MB: with less traced garbage the old threshold came too
  late and a standing car got ~500 ms sweeps of ~100 MB every 15-20 s (p22/p23 probes).
  `result.hitches` records the heap before and after each hitch frame.
- `alloc_profile.py --game-structs`: the profile with the game's structs. docs/PERFORMANCE.md.

## 2026-11-11: fixed-width cells and an early arrival, measured: no faster landing

- EGB3 cells (`country_format.transcode_cell`, `cellformat.lua`, `rust/crates/pack/src/fixed.rs`):
  each cell's numbers as 16-bit words (0xffff escapes a larger value) and its elevation grid as
  decimetres above its lowest point, copied by the game into FFI arrays with one `ffi.copy`. The
  game, Python and Rust read both formats by the block's magic; Python and Rust write the same
  bytes. Decoding is 2.9 times faster under lupa (once the feature walk got its own copy per format:
  a reader swapped mid-cell kept LuaJIT's traces on the varint reader), but the landing in game was
  the same (generator 7.17 s against 7.29 s) and a pack 15 % larger, so packs stay v2;
  `EARTHNG_CELLS_V3=1` writes EGB3. docs/RUST_IN_MOD.md.
- Early arrival (`native` `job.early`, `world` `M.landFinal`): the world leaves the old place, warms
  textures and spawns tiles as soon as the tile under the requested point is built; it touches down
  when the whole landing square is ready. Same total time (31.3-32.1 s in every variant: the main
  thread is busy throughout), peak Lua heap 381-554 MB instead of 735. `test_world.py --late-arrival`
  switches it off. The engine's collector follows the generator's allocations, not the heap's size:
  less garbage in the generator is what is left. docs/PERFORMANCE.md.

## 2026-11-10: the landing in 38 s instead of 82; pedestrians keep off the roads

- Landing (`world.lua` `LIMIT.loadNativeMs`/`loadQueueMs`, `native.lua`, `gc.lua`): while the player
  waits for the tiles the generator takes 60 ms of a frame and the spawn queue 14, not the drive's
  4 ms; once the nine landing tiles are queued the generator steps back and the frame goes to the
  queue; the collector's step is 10 in the landing, with one full collection before the touch-down.
  Central Kyiv: 82.5 s -> 37.7-39.1 s from the request to the car on the road (Ukraine pack),
  33.6 s in the Kyiv oblast pack. What is
  left: the engine's own collector step (~7 s, not moved by the step size, stopping it or frame
  length), texture loading of every pack (~7 s), the generator itself (~9 s). docs/PERFORMANCE.md.
- Test report: `result.loadReal` (the landing's phases in real seconds), `result.loadEngine` (the
  engine's frame split per phase), `result.arrivalMs`, `test_world.py --sample` (LuaJIT profile of
  the landing every 5 ms), `--gc-cycle`, `--walkers`; `--manual` switches on `--flow`/`--walkers`.
- Pedestrians (`walkers.lua`): real traffic cars ran them over 12-16 times a minute. Sidewalks now
  lie beyond the lanes the flow drives in, and are cut wherever another road lies (crossings,
  mouths of side streets that join mid-road, the other carriageway); the pieces' ends are linked
  round corners and across roads. A walker waits at the kerb (standing pose) while a moving car
  would reach its crossing first; walkers on a crossing are obstacles to the flow. Kyiv oblast
  pack, 90 s: 1-3 hits. `result.walk.hitLog` says where each hit walker was and whose car it was.
- Kyiv oblast test pack rebuilt (`out/kyiv-oblast-polygon`, 256.4 MB, export 226.5 s with 6 jobs).
- Photogrammetry: no source that may be cached or packed for Kyiv; open city meshes only for
  Helsinki, Espoo, Melbourne, Launceston. docs/PHOTOGRAMMETRY.md.

## 2026-11-09: pedestrians, and a physical body in their place before a hit

- Pedestrians (`walkers.lua`): walkers on both sidewalks of every street of the loaded tiles' graph
  slower than 60 km/h, cut back at junctions to the corner; at the end of a sidewalk a walker goes
  round the corner or across the road to another street of the node. Each is 8 static pose shapes
  of our own (`earthng/people_art.py`, built into the planet), one shown, with its own clothes and
  skin colours. Traffic widget row "Pedestrians: Off / 100 / 200 / 400"; `test_world.py --walkers`.
  Kyiv, 200 walkers: 0.20-0.28 ms sim + 0.32-0.35 ms draw a frame.
- A physical body in a walker's place (`pedhit.lua`, vehicle `e2r_ped` from `earthng/ped_body.py`:
  41 nodes, joints that break at 1500 N): any vehicle with physics (the player, the hand-off's real
  cars, the game's traffic) about to touch a walker within 0.3 s meets a body from a pool of 6,
  in the walker's colours. Not hit within 0.8 s: back to the pool, the walker walks on. Hit: it lies
  until the player is 120 m away. Pickup at 30 km/h along a sidewalk: body on the bonnet, thrown
  16 m. Teleports (velocity of the jump) and freshly woken bodies no longer count as hits.
  Details: docs/CROWDS_AND_PACKS.md.

## 2026-11-09: Overpass test query before the real one

- EarthNG.exe: before asking an area from Overpass, every server gets a tiny query at once
  (`overpass_alive`), 10 s for all. Servers that do not answer it (502 "queue full", or silence)
  are skipped; when none answers, the build asks for the country's PBF after 10 s instead of
  waiting up to four minutes. The real query's 150 s silence limit stays: a live server runs the
  query before its first byte (43 s for 3 x 3 km on 8.11).

## 2026-11-09: release 0.8.2, real cars that match the traffic, kerbs and sidewalks

- Traffic hand-off (`handoff.lua`, `flow.lua`): the pool of real cars holds the flow's bodies in
  their shares (stock `simple_traffic` configs picked by name, `handoff.bodyOf`) with half again as
  many inactive spares, and a real car is repainted to the paint of the flow car it replaces. Flow
  cars turn real by how close they will come to the player within 4 s; one about to reach the
  player takes the place of a far real car driving away; a real car with no lane to go back to
  stays real. Kyiv, 400 flow cars and 8 real: wrong body 3 of 32 hand-offs (was about 70 %), flow
  step worst 48.6 -> 6.1 ms. Details: docs/NATIVE_MODS.md.
- Buildings (principles of MaGE, no code taken): a wall lying on a neighbour's wall is not drawn
  up to the neighbour's top, so windows, balconies and air conditioners no longer stand inside the
  next house; above a lower neighbour it is a blank fire wall. Windows get sills from detail 40 and
  wooden casings from 65.
- Sidewalks: a street side with its own `footway=sidewalk` way beside it (or `sidewalk=separate`)
  no longer draws a second 2 m sidewalk; it is paved from the kerb out to the footway, also on the
  left of a one-way street, and the paving runs on round junctions (`ROADS.endWalks`,
  `ROADS.ringInsets`) instead of stopping at every yard drive. Sidewalks stand 12 cm above the
  road with a kerb face. Bridges get a low parapet wall with a mesh railing and posts instead of a
  solid 0.9 m wall. Details: docs/CITY_DETAIL.md.

## 2026-11-09: release 0.8.1, your own objects through the World Editor

- In an EarthNG world Ctrl+S / File > Save Level saves the player's own meshes into
  `settings/earthng-editor-objects.json` instead of serializing the level (which would write the
  generated world into the user's `levels/e2r_world/main`); level autosave is off there. One save adds
  placed, duplicated or pasted meshes, updates moved, rotated, scaled or re-shaped saved ones and
  removes saved ones deleted in the editor (undo included). No selection, no restart:
  `native.reloadEditorObjects()` runs after the write.
- One scene name per object (`earthng_obj_<uuid>`) and the `E2R_editor` group keep tiles from drawing
  a second copy; a record's `rev` keeps scenes built before a save from bringing back a moved or
  removed object. Rotation is stored north-up (Bilychi's UTM grid is -2.05 deg off north). Records
  outside a landing's frame are skipped.
- Window **EarthNG objects** with the save state; a reminder when the editor closes with unsaved
  changes. Engine facts found in game: `SimGroup:getObject(i)` needs `Sim.upcast`; the stock Delete
  clears the selection without the selection hook.
- Checked in game with probes at Bilychi (quality 50): save, move, delete, undo, restart, editing the
  restored objects. Details and limits: docs/WORLD_EDITOR.md. Also in the planet: the opt-in
  experimental `settings/earthng-overrides.json` layer (`manual.lua`, off unless that file exists).

## 2026-11-08: release 0.8.0, EarthNG.exe replaces the Tk Map Builder

- One `EarthNG.exe` (Rust window, WebView2 page, embedded CPython 3.13) installs the planet and builds
  map packs; the Tk window, `MapBuilder.bat`, `Setup.bat` and `EarthNG-MapBuilder.zip` are gone. The
  first map installs or updates `earthng_planet.zip` too. Town and address search via Nominatim.
- A drawn area's OSM comes from Overpass first; a country file up to 100 MB is downloaded at once;
  a larger Geofabrik PBF only with the user's consent, with its size and time shown.
- The cut keeps every cell a region overlaps: no data lost at an extract's edge (Tokyo spot 12 -> 34
  tiles, London 24 -> 210, 0 road nodes outside the tiles).
- Planet 0.8.0 and EarthNG.exe 0.8.0 from 6326cf2, checks in docs/RELEASE_CHECK.md. Details:
  docs/MAPBUILDER_APP.md.

## 2026-11-05 to 11-07: the pack builder's heavy stages in Rust

- `rust/`: `earthng-mapbuilder.exe` and `earthng_native.dll` cut PBF tiles, solve road profiles,
  build the index, compile cells, read scenes, write routing graphs and read the PBF for Map detail.
  Each native stage writes the same bytes as the Python stage it replaces; `EARTHNG_NATIVE=0` keeps
  Python. Kyiv from PBF to pack: ~26 min -> ~45 s without downloads. Details: docs/MAPBUILDER_RS.md.
- Downloads: one kept-alive TLS connection per DEM thread, resumed PBF downloads, a box inside an
  already cut country takes its tiles by hardlink.

## 2026-11-05: branches merged, generator state across coroutines

- `feature/places`, `feature/navigation`, `feature/traffic-flow`, `perf/streaming-250`, the signs and
  lights of #23 and #24 and the two Claude worktree branches are in `master`. The flow takes the
  phase from the scene's traffic lights where an approach matches a road.
- The native scheduler saves and restores the generator's shared state (`ROADS`, `BLD`) when it
  switches tile coroutines; extra yields at verges were removed again. Streamed geometry is released
  from suspended coroutines. Notes in docs/GENERATION_GAPS.md and docs/PERFORMANCE.md.

## 2026-11-04: flow cars point along their lanes, four bodies

- The user saw flow cars slide sideways. BeamNG's quaternions turn the other way round
  (mathlib.lua setRotate is v - w t + q x t), so a car on a diagonal street stood at -yaw.
  `flow.quat` is the conjugate now. The game test reads each shape's +x back from the scene
  (`result.flow.poseErr`): 0.00001 degrees over 2104 cars.
- `flow_art.py`: sedan, hatchback, crossover and minibus, 8 paints each, ~470 triangles. Lofted
  lower body with rounded corners and dark sills, glass with a painted pillar, bumpers, grille,
  plates, lamps, mirrors, rimmed wheels proud of dark arches, smoothed normals. The 32 shapes are
  warmed at switch-on: the first fill was a 261 ms step, now 7.6 ms.
- Only a car faster than 3 m/s runs a yellow. A car creeping to the line crossed into the other
  road's green. At most two flow cars become real a check, because eight woken at once made a
  120 ms frame.

## 2026-11-04: traffic lights in the flow, and how many real cars

- The generator hands a tile's OSM `traffic_signals` points to the navgraph (`nav.signals`). The flow
  lights a junction of three or more roads with a light within 14 m, or on the last 45 m of a road
  into it. Lit junctions within 40 m are one crossing. The approaches along and across its biggest
  road take turns: 24 s green, 3 yellow, 2 all red (the #23 timing). Green goes only with room on the
  way out. The game's AI does not see these lights, so a real car on a red approach is held by a
  speed limit of 0. The lenses stay unlit: #23 is not merged. Old packs (before 1.11) have no lights.
- The widget sets the real cars round the player: Off/4/8/12/16 (default 8). Fewer hands the extra
  cars back to the flow.
- Kyiv centre, 400 flow cars, 8 real, new Ukraine pack: 25 lit crossings, up to 56 cars at red, 43
  holds, mean frame 22.9 ms, worst 87 ms. The one-time pool spawn is left out of the drive frames.
  Planet only.

## 2026-11-04: real cars round the player in place of flow cars

- `e2r/handoff.lua`: a flow car within 90 m of the player's car becomes one of 8 real
  `simple_traffic` cars under the game's AI, so it can be hit. Past 130 m it goes back into the flow
  on the lane under it, at its speed and paint. The 8 are a pool, spawned once when the flow is
  switched on and parked inactive. A swap is `setActive` plus `safeTeleport`, ~1.5 ms.
- A game spawn is 0.4-0.67 s of the frame, so the pool is spawned at once (one ~4 s wait) instead of
  one car every 0.5 s while driving (613 ms frames). 60 s drive with 200 flow cars: 32 promoted, 25
  back, 3 dropped, mean frame 24.3 ms. Hitting one by hand is not checked yet. Planet only.

## 2026-11-04: traffic flow without physics

- `e2r/flow.lua`: hundreds of cars on the navgraph of the loaded tiles, IDM car following, main
  roads through junctions with side roads waiting for 4 s gaps, all-way stops between equal roads,
  no entry without room on the way out, so queues spill back. The player's car and the game's AI
  cars are obstacles. Each car is a TSStatic without collision (`earthng/flow_art.py`, 128
  triangles, 8 paints, built into the planet). Widget: "Flow (no physics)" 0/100/200/400.
- Parked in Kyiv: 400 flow cars 15.3 ms mean (no traffic 13-16), sim 1.45 + draw 1.24 ms; 800 cars
  17.6 ms, 225 of them queued at junctions. Not yet: collision (hand-off to real cars near the
  player), traffic lights, lane changes, night lamps. Planet only, no pack rebuild.

## 2026-11-04: traffic kinds and the ceiling of physics cars

- The user wants hundreds of cars, enough for real jams. Step one measured the game's own cars. The
  widget picks simple (`simple_traffic`, PropTraffic), full (soft-body, no police) or Agent Traffic;
  `world.lua` builds the group itself, because the game's own one follows `trafficSimpleVehicles`
  (true by default in 0.40). Before, an installed Agent Traffic always won with its full cars.
- Parked in Kyiv: 0 cars 13-16 ms, 8 simple 23, 16 simple 35, 32 simple 62, 48 simple 95, 64 simple
  127; 16 full 65. A simple car is ~1.5 ms of the frame, linear. Buttons are 0/4/8/16/24 now; a crowd
  needs cars without physics on our navgraph (docs/NATIVE_MODS.md). Planet only, no pack rebuild.
## 2026-11-03: railway and tram tracks (PACK_DATA A5)

- The level crossing at 50.44322, 30.46409 in Kyiv had its St Andrew's crosses and no rails, on a
  shiny concrete pad (`landuse=railway` was drawn as `paved`). Now `fast_style.line_kind` gives
  `railway=rail/light_rail/tram/narrow_gauge` the line kind `rail` (not in a tunnel, no subway), with
  only `RAIL_TAGS`; index version fast-21, so tracks need a pack rebuild. The Kyiv spot pack
  rebuilt with them came out 61.9 MB against 62.9 MB before (the old one was cut by older code).
- `generator.lua` RAIL: off the road a bed of concrete sleepers on ballast (`fast_art.rail_art`, its
  ragged shoulders cut by opacity) and two steel rails 15 cm high, the gauge from `gauge` or 1520 /
  1435 mm by `look.block`. On a carriageway at grade only the rail heads, 12 mm over the asphalt: a
  crossing and a tram in the street are flush with the road. Knots every 8 m, every metre where a step
  meets the asphalt. On a bridge a track keeps only the part over a road deck. No collision.
- `landuse=railway` stays `paved` in the pack (an older planet keeps trees off it) and is drawn in
  `ballast`. `live.lua` asks Overpass for tracks too.
- Cost, `bench_native.py` on the spot pack, same generator: the yard by the crossing (~30 sidings)
  took a near tile from 22k to 100k triangles in the first try, 44k of them rail sides; with fine
  knots only at the asphalt's edge and the sides of `service=yard/siding/spur` rails only within 30 m
  of a road it is 41k. A tram tile in Podil (50.4718, 30.5040): 41.5k -> 42.7k.
- In game (`test_world.py`, separate profile, planet from this branch, the Kyiv spot pack, preset
  Normal, 1280x720): at the crossing 50.44322, 30.46409 the close top-down views show two rails on
  concrete sleepers and ballast, and the station yard north of it is rows of tracks on ballast, not a
  grey slab. On the tram in Podil (50.47175, 30.5041) the rail heads lie flush in the asphalt a gauge
  apart, with no bed. Both runs passed functionally; performance failed on `frame_over_100ms` (2
  frames each, worst 319 and 577 ms, means 22.9 and 26.9 ms), as the Kyiv run of 27.10 did before
  tracks. Not done: embankments and cuttings, catenary, rail bridges without a road deck.
## 2026-11-03: issues #23 and #24: lights that change, signs, the line of where the car is; MapBuilder

- Where the car is (#24, `location.lua`): top centre, the street or the road's number, what it is in
  (part of town, town, region, country), a limit roundel, a road number chip, the next turn of a route.
  Town names come from `map/places.json`, already in packs. Off in "Вигляд і трафік". A pack named
  after its town no longer says it twice.
- Traffic lights (#23, `signals.lua`): one clock for the world (green 24, yellow 3, all red 2 s), six
  groups: a lit lens mesh per group and colour, so a phase change is a few `setHidden`. Lights within
  45 m are one crossing, opposite ways share a phase. The game's AI gets the same colours through
  `mapmgr.setSignals` and the `trafficSignalUpdates` mailbox; `core_trafficSignals` is not used, its timer
  restarts on every `map.reset`. An edge stays in the table until the car is 3 km off: `ai.lua` indexes
  it unguarded.
- Signs: every kind the game has a model of, read off mapped nodes (country codes in `SIGNS.codes`)
  and off the roads: limits where they change and every 2 km, bends, slopes, narrow and rough road, no
  overtaking, dead ends, town limits; limits with no model are drawn, mph as a US board; street blades on
  a corner. New nodes, so packs need a rebuild (index fast-22): level crossings (a Saint Andrew's cross,
  a warning 120 m ahead out of town) and speed cameras.
- Left-hand countries (`ROADS.keepsLeft`): navgraph lanes, `rightHandDrive`, signs, stop lines, lane arrows,
  bus stops, parked cars.
- Foot bridges: a path with `bridge=yes` had no deck, so Pont Saint-Louis was lamps over the Seine.
  `fast_profile.foot_decks` lifts them; Paris pack: 1722 of 2507 foot ways, 572 over roads. Index fast-21.
  Their ends come level with the bank's street, 6 m over the DEM at most (`banks`, fast-22). The deck
  still lay under water: the quays of both banks pulled the ground, and the water drawn on it, 4 m up
  over the river. A lattice node under water no longer follows roads unless one runs on it (a causeway),
  and it takes the lowest DEM within 38 m (`ROADS.level`): the DEM's blur put 56 m by the banks of a river
  at 48 m. The strip where the water's edge meets a bank still climbs: its vertices lie on the ground.
- A city along the road never came up while driving. A near tile of central Kyiv is 100-140k triangles
  against `TRIANGLE_LIMIT` 80k, so `trimTiles` evicted built tiles before the renderer took them, and they
  were built again at the next epoch: 17 of 37 builds in a 200 s drive, 2 scenes of 13 round the car. A
  near tile the car still wants now stays. The same drive at 9 m/s: buildings on both sides all the way.
  It never showed in landings and stills, where the set is pinned.
- The London Eye's "white block on a leg" was no such thing: the camera stood inside St Thomas' South
  Wing (building 1644754826), and the leg was Centre Point. The real fault was 256 `building:part`s in
  slab 204068874: `link_parts` and `clad_metal` take them as one structure.
- MapBuilder: routing decoded every cell whole and used 5 % of it. `country_format.decode_roads` reads
  the roads alone, once each: a Paris region 71 -> 13 s, the file byte for byte the same. All of Ukraine (101 regions): ~40 -> 3.5 min at 3 jobs.
  Export: scene tiles through WKB and plain dicts, shop names remembered, nameless houses skip the
  lookup, `nature.partition` cuts by what is near, coordinates written by hand. London, 16 cells: 62.5 -> 44.4 s. All 7113 areas of
  the sample keep their shapes; only the numbers of cut parts and the start of a ring moved.
  The road solve keeps its buffers between multiplications: 161.6 -> 147.3 s in Paris, the same heights. Starting
  each pass from the last was 5x faster and is not in: at this tolerance it moved heights up to 9 m and left 1286
  edges over their grade against 774.
- Routing members of a pack had the clock in their zip header, so two builds differed: a fixed date now.
- Blades: letters of 22 cm on a 30 cm board, read from the road. The game test records the game's window by title: since the widget has an OS window of its own, the
  clip was of that. It also counts AI cars at red lights (`signalWatch`).

BeamNG 0.40.4, isolated profile. Paris (High, Balanced 50): Pont Saint-Louis, Pont des Arts with decks and
piers over the water (`out/night-paris-04`). London: left-hand signs, the wheel, Parliament Square. Kyiv, 1.3 km
from Maidan down Khreshchatyk and Velyka Vasylkivska at 9 m/s, Normal, Balanced 50, 1280x720: the location
line reads `вулиця Хрещатик`, `Центр, Київ`, a 50 roundel, red lenses lit, the autopilot that ignores lights was
hit by a car on its green (`out/night-kyiv-22`), `signalWatch` with 20 AI cars: 24 samples waiting at red, 4
crossing, 1 crossing at red. Level crossings and speed cameras stand where mapped (`out/night-kyiv-27`), but
packs have no tracks, so a crossing has no rails. 20 AI cars: mean 40.8 ms, p99 84.

Signs and lights cost no frames: the same drive with `SIGNS.plan` on and off, two runs each, no traffic. Khreshchatyk:
mean 17.2/18.2 ms on, 17.8/17.8 off; p99 36.5/38, 38/38.5; frames over 33 ms 149/160, 179/177; Lua garbage 72/80,
78/76 KB a frame. Embankment, 2.2 km at 15 m/s on average: mean 15.5/15.5, 15.4/15.4; p99 34/33.5, 32.5/33.5. Time per
tile was not measured. `frame_over_100ms` fails in every run with or without signs: the worst frame (0.4-0.7 s) is
the first one after the camera cut at touch-down, and the 2-10 frames over 100 ms are that and `reloadCollision`.
Unit suite: 705 tests, 4 skipped. Packs need a rebuild for level crossings, cameras and bank ends; the road rules
work on old packs. BeamNG 0.39 not run.

## 2026-11-02: after the 0.7.0 release, domes over Hagia Sophia's tombs

- A still from the south of Hagia Sophia showed its tombs as flats with balconies, and a dome hanging in
  the air with nothing under it. `historic=tomb` was no monument: `tomb`, `mausoleum` and `fountain` are
  now, and a part takes `historic` from its building.
- The dome is a `building:part` with `min_height` 17 over a `building=yes` outline. It covered most of
  the outline, so `link_parts` set `e2r_outline` and the tomb was gone. Only parts that reach the ground
  count as covering now; parts in the air leave the building standing, and a building with no height
  of its own reaches up to the lowest of them. Index version fast-20, so this one needs a pack rebuild.
  The tomb walls need only the planet.

## 2026-11-02: release 0.7.0, landmark fixes from the stills

- Stills of ten world landmarks showed what no bench had: the Eiffel Tower as floating plates (skillion
  roofs were not drawn, `partWalls` took `roof:height` off the walls), the Colosseum as a curved block of
  flats, window rows on the Golden Gate's towers, Tokyo Tower as an office (a stack of `building=yes`
  with `min_height`). Now: `BLD.skillion`, `BLD.isMonument` (bare stone), metal towers, lead domes, and a
  slim block hanging with nothing under it is a mast section.
- Golden Gate deck: the way is split at the north tower, where the DEM is the sea, and `solve` took
  every segment end for an abutment; the deck ran from 74 m down to the water and back. `fast_profile.spans`:
  a node only bridges meet at is no abutment, heights run linearly along the deck between the ends on
  the ground. Index version fast-19. In the rebuilt spot pack the deck stays at 55-75 over the strait.
- Port Jackson is `natural=water, water=harbour` and the coastline stops at the Heads: `_flood` sinks
  sea-level harbours under the sea (pack rebuild).
- Map Builder did not build routing graphs, so navigation found routes only in packs with a graph
  built by hand. `build_country._add_routing` writes them into every pack; Ukraine adds about 40 min.
- Stills only: with gen-budget 40 and dense tiles (~300k triangles) undelivered scenes were evicted
  and a parked camera kept the holes until the next epoch. In driving it heals, so the release keeps
  `CELL_LIMIT, TILE_LIMIT, TRIANGLE_LIMIT, VERTEX_LIMIT`; only the stills planets raise them.

## 2026-10-28 (branch feature/navigation): drive and route past the landing region

- The user: a marker cannot be set far away; 100 km at least, where the packs have the roads.
  The world came from the landing region's cells alone (Khreshchatyk is 37 km from the Kyiv
  region's west edge) and the route from its graph alone.
- native.lua: a cell the landing region lacks comes from a mounted neighbour region that has all
  of it (foreignOf), moved into this frame by an affine on the cell's corners (a translation in
  one UTM zone, ~2 degrees of turn across a zone border), its elevation resampled onto this
  cell's grid; neighbour roads get the region id as a prefix and their copies of this region's
  roads (same OSM end nodes) are dropped at a seam (75 ids collided at the Kyiv/Zhytomyr seam,
  none the same road; 4,985 roads shared by node pair). edgeKm counts every mounted region.
  Blocks are read in 256 KB pieces with pauses (own region too); features are decoded only
  from the neighbour cells meeting the tile.
- navigator.lua: the graphs of the regions round car and destination (native.routingRegions),
  6 ms a frame while standing.
- In game (out/nav-seam-01..03, nav-control-01): M06 at 50.433, 29.99 to Pereiaslav, 124.8 km over
  6 regions found in ~5 s; 15 km driven over the Zhytomyr/Kyiv seam (UTM 35/36), 2 frames
  waiting for tiles, 0 m off the line, roads, lamps, trees and ground markers past it. The p99
  rise past the seam (83-90 ms) is the place: the same stretch landed in the Kyiv region gives 93.

## 2026-10-27 (evening, branch feature/navigation): routing graph R4, not yet in the widget

- Issue #24 (a street line like BeamNG.Earth's) and markers the navigation leads to. The game's
  navgraph covers 1 km round the car, so long routes come from a routing graph per pack region
  (docs/NAVIGATION.md): `routing_format.py` (EGR1, navSegment's classes and one-way rules),
  `build_routing.py` (from a built pack's cells, no rebuild; a companion `<pack>_routing.zip`),
  `routing.lua` (ffi arrays, regions merged by OSM node id, A* on time with a pause budget,
  steps with street names). Kyiv region: 98,909 nodes, 2.78 MB, decode 158 ms, the whole region's
  diagonal (171 km) 39 ms; Khreshchatyk to Zhytomyr over two regions 140 km in 25 ms (lupa LuaJIT).
- Wired the same evening (navigator.lua, on M.navigator: world.lua is at the 200-local limit): a
  click on the minimap, or "Navigate here" on the big map, routes from the car in the driven
  region (2 ms a frame); the next 700 m go to core_groundMarkers as navgraph nodes `e2r_n<id>`
  that the game has; 45 m off the line for 3 s finds a new route; the line, a flag and
  "N km to go / In 300 m, left: <street>" show on the map. Not driven in the game yet.
- No turn restrictions yet (they come with the next pack rebuild).
- Driven in the game the same night (out/nav-kyiv-01, Khreshchatyk to Boryspil, 36.8 km): the graph
  came from the mounted companion zip, ground markers lie on the ProceduralMesh roads and the
  stock minimap draws the line; 7 km by the test autopilot, 0-12 m off the line, 47 marker
  updates. navigator.step 0.008 ms median. The first load had a 101 ms stretch (10 k name
  strings at once on the game's 384 MB heap) and an 18 ms read: names now stay in the file's
  bytes and the file is read in 256 KB pieces, 102 frames for load and search. A long straight
  handed over one node 58 m ahead: now also the first node past 700 m (to 950 m), and again near
  the last one (unit test; not driven again).
- Signs and lights: docs/SIGNS.md (OSM counts for Ukraine, rules that infer signs from data the
  packs already carry, the stock italy_traf_sign_* set, a frame budget via Forest and one text mesh
  per tile). Nothing placed yet.

## 2026-10-26 (evening): no rails in front of a high deck's piers, an audit that reads rails

- The user, in game at the Jüri overpass of Tallinna ringtee (0.6.4): the median rails still ran up to
  the deck's edge and ended in a cross rail in front of the pier. ROADS.onDeck.under (8 m) and
  .clear (3.5 m): where a deck is 3.5 m or more over the ground, OSM barriers stay 8 m off its edges
  and ends. Confirmed in game after the change.
- road_audit.py's near-tile barrier and spike checks read no rail mesh at all (the runtime's cover set
  lacked e2rf_clad_metal and e2rf_fence_mesh): every earlier "0 barrier, 0 spike" was empty. With
  the rails in: `underdeck` (rail triangles with asphalt more than 4 m over their tops; a road on an
  embankment is 3 to 4 m over the ground its rails stand on), `barrier` pixels must have asphalt on
  all four sides (a rail along the edge is not on the road: 109 -> 21 cells in the Jüri-Tallinn
  box), and a tall narrow triangle at a building's outline is the building's wall (60 -> 0 spike
  cells: they were warehouse corners, e.g. an 18 m one at 59.36823, 24.87883).
- Left: 4 near and 7 far cells of rails under a deck in that box, mostly the stacked interchange at
  Assaku (59.3594, 24.8735), where several decks cross and an abutment wall stands among the rails.

## 2026-10-26: lamps off the lanes, no walls at bridge joints

- The user, driving: more lamps standing in the middle of the road, and at bridges and flyovers a
  barrier across the road as if it were not there.
- Lamps: from 25.10 the packs carry OSM's surveyed lamps (203 k in the Kyiv region), placed at
  their node, and OSM maps many as nodes of the street or in its lanes. A lamp on a street at grade
  (its centre line within half its width, or on the drawn asphalt: junction plates and mouths)
  goes to that street's edge on its own side, 0.7 m into the sidewalk or 1.2 m onto the verge, and
  on off the asphalt half a metre at a time; one on a deck with no street at grade under it stands
  in the deck's parapet at its top. A mapped tree on the asphalt is left out (one in its pit by the
  curb stays). Kyiv, 570 tiles: 3,705 lamps and 172 trees on a carriageway -> 6 lamps and none; of
  4,738 OSM lamps in 36 central tiles 20 are left out, the rest moved. Lviv centre: 43 -> 1.
- Decks: liftDecks raised a deck for clearance over any road under its footprint, and a slip road
  level with the deck that joins it through another way counted: Mykoly Mikhnovskoho at the
  Druzhby Narodiv junction rose 12 m (deck 135.9 over a pack height of 123.6) and its ramps with it,
  a wall across the road from the other carriageway at 125.5. A road passes under a deck only from
  `DECK_CLEAR.below` (1 m) under it: packs and live.lua always keep a real crossing lower.
- Parapets: a deck side was drawn or left out whole per segment (2 of 3 samples on another
  carriageway), so where a slip road leaves a long segment its parapet stood across the mouth;
  the united deck (0.6.1) had no such check at all. Both now go in ~2 m pieces and leave out the
  ones over another carriageway at the deck's height (the united deck's own carriageways aside).
- road_audit.py finds these by itself now: `parapet` (a deck wall inside a carriageway), `prop`
  (street furniture on a carriageway; road_quality's build exports their positions) and `step`
  (the road's own asphalt jumping and staying there). Kyiv, 50.40-50.48 N, 30.45-30.65 E:
  parapet cells 267 (edge noise in) -> 23 with the edge rule -> 3; steps 25 -> 7; missing samples
  121 -> 42. The rest of the steps are pack heights (the South Bridge's layer 2 deck 2-3.6 m over
  the layer 1 ramp merging into it) or a junction plate the audit misreads (Karavaivskyi viaduct,
  whose profile follows the pack to 0.4 m).
- Cost: a central Kyiv near tile 1017 -> 1047 ms (the lamp checks, all in the scene phase: the road
  goes out as before). Unit check: 423 OK; new: lamps to the edge and on a parapet, trees on the
  asphalt, a deck not raised over a level slip road, a parapet open at a slip road's mouth; the
  repeated-abutment test's road under the deck is now 2 m lower, as an old pack keeps it. Not
  driven in the game.

## 2026-10-26: the road ahead first

- The user, driving at 300 km/h: tiles appeared in front of the car, and at times the road was not
  there yet and the car fell. A central Kyiv near tile cost 531 ms of Lua on 19.10 and 1024 ms now
  (`bench_native.py`, 9 tiles round Khreshchatyk): house massing and deck clearance +120 ms, city
  lawns +100, the yards +90 ms and +38 MB of garbage, the lamp rules +70. No single bug; at the
  game's 4 ms a frame one tile is ~4 s, and the tile was given out only when its scene was done.
  The road and its ground are ~230 of those ms, the scene the rest.
- generator.lua `options.roadReady(road, nav)`: the road layer is closed into its manifest as soon
  as nothing writes it any more (after the ground lattice) and handed out; the scene is built
  after it. The manifests are the same as a whole build (18 Kyiv and Bila Tserkva tiles: items,
  vertices, faces, materials, spawn, navgraph).
- native.lua (`AHEAD`): a near tile's priority is the seconds the car takes to reach it, along its
  heading, a step sideways or back counting 3x, blended in from 10 to 30 m/s (the old distance
  below). At speed the tiles 15 s ahead (within 150 m of the heading line, 2 km at most) are near
  even past nearM. While driving a build yields once its road is out and is parked; its scene
  waits 3 s plus 0.1 s per m/s over 10 behind the roads, at most 3 scenes are parked (a road due
  first gives up the latest, which is built again if its tile is wanted near once more), and at
  each frame's first step a scene build, or a far one while a road is urgent, goes back to the
  parked so a road due since goes first. A road due within 6 s raises the frame's generator budget
  from 4 to 6 ms. The landing still builds whole tiles.
- world.lua: the ready road started first is the one due first (native's seconds); a road due
  within 15 s starts however long the queue of scenes is (it waited for the queue to drop under
  400 items), and a corridor tile past loadR is not unloaded. A road due within 8 s at the queue's
  head gets 2.5 ms of spawning even when the generator took the frame (it had 0.5 ms).
- `bench_native.py` now releases every delivered layer as the renderer does (left in the generator
  they were evicted by its triangle budget: a Kyiv tile is ~65k of 80k) and reports the road ahead
  of the car driving along +x: the frames on a tile with no road and the lead in seconds.
  West to east across Kyiv from 50.45, 30.43 (5,200 frames of driving, generator only):
  - 83 m/s: before, from ~60 s in, every frame on a tile without road; now none, lead min 7.3 s.
  - 50 m/s: before 1,677 frames without road (lead p5 0); now none, lead min 12.1 s.
  - 25 m/s: none either way, lead min 13.5 -> 21.5 s; 32 full tiles built against 31.
  - Rural, west of Kyiv (50.40, 29.85), 83 m/s: lead min 1.4 -> 11.0 s (p5 5.6 -> 14.8), 264 full
    tiles against 270.
  At 300 km/h through central Kyiv about half as many scenes are finished (14 against 28 in the
  same time): the buildings beside the road come later, the road does not.
- Unit check: 419 OK; new: arrival-time priorities and the corridor, road before scene with at most
  3 parked, the urgent budget. Not driven in the game.

## 2026-10-25: roads in the far ring, no holes in staggered decks, a road audit

- A free camera past the near radius (nearM, ~1 km round the car) saw the Tallinna ringtee as
  grass between two lines of guard rail: far tiles drew ground, trees, buildings, rails and
  fences, but no road. A far tile now draws the surface of every road of class unclassified and
  up (and its junction plates), as decoration without collision (`ROADS.far`); service streets,
  tunnels and the horizon draw none. The far ground is coarse (100 m triangles, a fan to the fine
  lattice at the border) and ignores a road's cutting, so each far road vertex is lifted
  `ROADS.far.clear` (.25 m) over the far ground's own triangle under it, never lowered: Laagna tee,
  with the ground 4 m over its asphalt, stays on top. Cost: +4 to +19 % triangles a far tile (about
  1,700 road triangles a tile in the city, 40 in open country).
- The 0.6.1 united deck is one slab along the longer bridge of a dual carriageway and takes the other
  only where it runs beside it. A staggered deck sticking out past that end had no slab and, being
  in a group, no asphalt of its own: a hole with the lane marks floating over it (Tallinna ringtee,
  59.3126, 24.7376). A pair whose decks stick out more than 8 m past the host stays two whole decks.
- `earthng/road_audit.py` checks roads automatically instead of by eye: it builds every tile of an
  area with generator.lua (near or far tiles), walks every road every 6 m, and lists the stretches
  with no asphalt (missing) or ground over it (buried; tunnels are skipped), longest first with
  lat/lon. `road_quality.py` can read one region of a country pack and build far tiles for it.
- Tallinn area (59.30-59.52 N, 24.55-25.00 E, 2,808 tiles): near tiles 66,465 roads, 722,437 samples,
  3 missing and 76 buried (was 9 and 419 before the deck fix and the tunnel rule); far tiles 29,015
  roads, 379,524 samples, 103 missing (the Peterburi tee tunnel, before the checker skipped it)
  and 107 buried (6.8 % before the lift).
- The audit also finds a guard rail or mesh fence standing on a carriageway (kind `barrier`, its
  footprint on the asphalt in m2): none in the Tallinn area.
- road_quality's offline build now loads the 40 m of neighbouring cells round a tile as the game does
  (native.lua buildTile, `pad`). Without them a guard rail across a tile edge sampled a ground of 0 past
  the loaded terrain and dived 40 m into the ground there: an offline-only artefact (the game has the
  pad), seen first as railings running down under a bridge. The audit now reports such a rail (kind
  `spike`: a guard rail triangle taller than 3 m and no wider than 4 m); none in the Tallinn area.
  `Pack` also reads a one-region ZIP (a county download) that has no country manifest.
- `earthng/model_viewer.py` writes one HTML page of the tiles round a place (all meshes, built by
  generator.lua through road_quality, `tune.all = 1`): orbit, switch layers, click to measure, and
  paint the ground and roads by their deviation from the Land Board's LiDAR terrain (green within
  0.5 m, a model-minus-LiDAR height at every click). It replaces driving a road to check it.
- A guard rail or fence under a bridge deck is left out under it, at any angle and height (`ROADS.onDeck`;
  it was only a barrier across a carriageway or under a deck less than 3.5 m up). OSM carries the median
  and slip road rails of an overpass on under it, and at the Tallinna ringtee at Jüri they read as rails
  running down under the bridge and crossing each other at the piers (every rail drawn there is a
  mapped way). They stop at the deck's edges and go on past them. This reverses the earlier rule that
  kept the lower road's rail under a high deck: the old test now asserts the cut.
- Unit check: 381 OK (3 skipped); new: far roads and their lift in a cutting, staggered decks, the
  audit's grading, barrier and spike checks, a one-region ZIP, rails cut under a skewed deck, and the
  viewer's layers, raster sampling and page. Not driven in the game.

## 2026-10-25: the whole of Estonia at 10 m

- `build --place estonia --local-dem` over the whole country died or took every byte of RAM at
  z13: the profile solve stitched one dense DEM grid over the bounding box of every road
  (`fast_profile.Mosaic`: 4.7 GiB over Estonia, sea and empty bog included), and past that the
  four export workers grew to 3.6 GB each on the islands and filled the machine.
- `Mosaic` now stitches 8 x 8 tiles at a time and reads only the tiles its points reach (the
  grid never read the others: at the edge of a downloaded DEM a z13 tile upsamples from z12
  neighbours that may not be on disk). On 766,337 real Harju stations the heights equal the
  grid's exactly (max difference 0, 5 s, 157 MB).
- `_coastlines` kept every source tile's coastline for the life of a worker, as lists of
  tuples. On an island every tile carries the whole coastline (about 250k vertices, the same
  ways), so a worker over Saaremaa and Hiiumaa reached 4.9 GB in 40 blocks. Each way is now
  stored once, as an array; a worker holds ~200 MB over the same blocks. Exported blocks are
  byte-identical (same CRC and size on three blocks, Kuressaare among them).
- Result: `earthng_estonia.zip`, 527 MB, 18 regions; the export took 42 minutes with the
  region indexes already built (about 20 more to build them), Python memory 0.6-0.8 GB
  throughout. All 15 regions with land are on the 10 m grid; the 3 open-sea regions west of
  Saaremaa have no road and stay at 25 m. 4,778 sampled tiles of all regions build with
  generator.lua, none failed. Not driven in the game.
- Unit check: 354 OK (3 skipped), two new tests (the block sampler against a reference grid
  and its memory, the shared coastline cache).

## 2026-10-25: packs carry their data credits

- A map pack shared on its own (a Drive download) named only OpenStreetMap in its
  manifest. Every pack now carries `credits` in its country or section manifest and a
  `CREDITS.txt` beside it: OpenStreetMap (ODbL) and the Terrarium elevation tiles always,
  the Estonian Land Board's DTM with its licence link and extraction year whenever the
  pack's elevation tiles hold the burnt LiDAR (`est_dem.credit`, read from
  `cache/est/burnt.json`: a burn outlives the build that made it), and Transpordiamet's
  road register (CC BY 4.0, what was changed) when built with `--road-register`.
- The road register is open data, CC BY 4.0 on andmed.eesti.ee: the "keep register-built
  packs for local use" caveat is gone from README, ESTONIA.md and THIRD_PARTY_NOTICES.
- Unit check: 354 OK (three new tests: the pack's credits, the Land Board credit from the
  burn record, the export job's credits). On the local cache all six Estonian source
  indexes are credited to the Land Board.

## 2026-10-25: rails beside the road, concrete at deck ends

- OSM guard rails mapped off the road the pack draws (an old alignment, a ramp since rebuilt,
  a mapping offset) stood out in the grass: 8 to 17 m off round the Assaku - Juri overpass of
  the Tallinna ringtee, and one looped through the field inside a ringtee cloverleaf.
  `ROADS.besideRoads` (`generator.lua`) keeps a rail only within 4 m of a carriageway's edge;
  a short weave out to 7 m stays, so a rail along that line is not chopped into stubs.
  Harju-maakond: 6.8 of 83 km of OSM rail is dropped; the 291 km from the road register
  already stood on the edge.
- Decks barely longer than the road under them left the ground between the approach's bank
  and that road at 60-70 degrees on the 10 m lattice, a wall of grass by the abutment (Parnu
  mnt over Jarvevana tee, Tartu mnt at Pildikula). Ground and cover steeper than 55 degrees
  within 15 m of an abutment is now drawn in its concrete, a wing wall (`ROADS.wing`, through
  a hook in the mesh collector); the grass edge decals over it are left out, and a viaduct's
  valley sides between its ends stay ground. Round those two bridges: 259 and 179 m2 of ground
  over 55 degrees before, none now. Build time unchanged (36 tiles: 415 ms a tile before,
  410 after).
- A 5 m ground lattice would smooth those banks for real, but costs about 27 % more build
  time and 50 % more triangles a tile; not done.
- Unit check: `test_generator.py` 99 (two new tests; three rail tests now have a road beside
  their rail). Checked in offline 3D renders of the generated tiles; not driven in the game.

## 2026-10-24: no runaway hills at bridges

- The bridge clearance solve (`fast_profile.py`) and the runtime deck lift (`liftDecks`) both
  took any lower road whose ribbon touched a deck's overhang for something to clear. The
  two bridges of a dual carriageway sit a lane apart, so each one lifted the other's approach,
  and that lifted the first deck again: the Tallinna ringtee climbed to 866 m in the pack,
  and in the game 11 m hills stood at the ringtee bridges at Lasnamae and Pildikula.
- Now only a road whose centre line crosses the deck's centre line in plan is an overpass
  (`fast_profile.py`), and the runtime lift counts a road only when its centre line passes
  under the deck itself. The deck and the road beneath it share the 6 m of clearance, with
  the deck's extra lift capped at 6 m. Cache version `fast-18`.
- Harju-maakond, non-bridge segments against the terrain: more than 5 m off 2123 before,
  11 now (the largest 6.2 m, was 810 m). All 2318 bridge crossings reach full clearance
  (21 fell short). Parallel carriageway bridges are level again, and the Jarvevana
  Parnu mnt bridge profile is flat at 54.4-54.8 m.
- Unit check: `test_fast.py` 22, `test_generator.py` 81. Not driven in the game.

## 2026-10-24: city block silhouette

- Blocks from 8 m that are not houses or sheds, on a near tile at detail 40 and above,
  gain a concrete socle in front of the photo facade, a parapet and coping on a flat
  roof, one roof bulkhead (and a smaller vent from 26 m), and one concrete visor along
  each street facade of 12 m or more and along the longest yard facade. Collinear OSM
  edges count as one facade. Separate hoods every 28 m on a 180 m slab sat between
  the camera frames, so the visor is the whole wall (two quads, not up to eight).
  A pitched `roof:shape` keeps the socle and the visor and skips the rim.
- No new textures. The rim, canopies and bulkhead share `e2rf_parapet` (stock
  `concrete_plain`), which stays in static collision. Houses are unchanged.
  Low, Potato and the far ring stay boxes. Panel UVs are not split.
- Unit check: `test_generator.py` 80. Offline before the full-length visor
  (`mesh_pairs`, detail on, radius 0): Times Square parapet 7236 tris, still 3 pieces;
  Berlin Mitte 4275 (2); Obolon 1086 (1). Scene objects stayed 58 / 60 / 55.
  The visor is two quads a facade, so it does not add a piece. Live `mods` was not updated.
- Obolon, quality 50, graphics Normal, 1280×720, 50.5105, 30.4970.
  `out/city-mass-01`: 39.4 m, mean 19.4 ms, p99 56.5 ms, worst 565 ms, 3 frames over 100 ms.
  `out/city-mass-02`: 38.9 m, mean 19.2 ms, p99 56.5 ms, worst 308 ms, 4 frames over 100 ms.
  Both street shots showed the parapet band and the base skirt. The yard face had four
  short hoods on a ~180 m wall and the camera missed them.
  `out/city-mass-03` (full-length visor, still facing down): 39.3 m, mean 19.7 ms,
  p99 54 ms, worst 281 ms, 4 frames over 100 ms. The mesh has the ledge beside the car;
  the orbit camera is above it and did not draw the downward face.
  `out/city-mass-04`, top facing up: 38.8 m, mean 19.9 ms, p99 55.5 ms, worst 276 ms,
  4 frames over 100 ms. The ledge shows above the first window row and casts a shadow.
  Potato, night, the far ring and the other four cities were not driven.

## 2026-10-24: house massing on the near tile

- Houses (under 8 m, not panel or glass) on a near tile at detail 40 and above gain a
  board cornice, a door canopy, a brick chimney on the ridge, and on a quarter of
  two-storey houses one wooden balcony. A tall gable gets one attic window from the
  same atlas. `roof:shape` other than a pitched form still keeps a flat roof.
- Low steps windows to 4.2 m (at most 4 a wall) and skips those parts. Potato keeps
  one bay a wall. The far ring stays a box. The chimney is one material
  (`e2rf_chimney`, stock brick) and is left out of static collision.
- Panel photo facades are unchanged. The planet ZIP has to be rebuilt before the
  game knows the chimney material. Unit checks: `test_generator.py` 79,
  `test_styles.py` 18, `test_collision.py` 3.

## 2026-10-23: street furniture by place, merged into master

- `codex/street-assets-experiments` merged into master: `Rebuild.bat` builds from
  master, so the furniture never reached the installed planet before.
- Furniture now follows what the ground is, not one street mix everywhere: park and
  yard paths (benches with bins), squares (lattice of planters, benches, bollards,
  racks), blocks of flats (entrance benches turned from the wall, rows of 1100 l
  containers in the yard), shops (planters, bins, racks on street walls, a skip
  behind), houses (wheelie bin or bench at the gate), village sidewalks (a sparse
  set). Paths out of town get none; footways through car parks keep furniture out.
- New stock models from `/art/shapes/garage_and_dealership/Clutter/` (global art
  materials) and East Coast's concrete bollard; bounds measured from the DAEs.
  Every model is checked with `FS:fileExists`, so a game without one places less.
- `earthng/props_map.py`: offline top-down map, counts and lat/lon samples of the
  props of near tiles. Kyiv Obolon, Balanced: 439 → 535 props a tile; tile build
  391 → 382 ms mean over nine tiles (noise). Automated suite: 289 pass.

## 2026-10-23: unified street layout on the asset experiment branch

- Worktree: `C:/Users/Alezx311/.codex/worktrees/street-assets-night/EarthNG`,
  branch `codex/street-assets-experiments`. Continued the existing uncommitted
  footprint work; fixed its lost curb flag and missing inter-object clearance.
- Route: existing Lua generator plus collidable Forest kinds. No loader or
  personal game settings/saves changed. Test profiles are new directories under
  `out/city-detail`; base art comes from the prior isolated test planet. Game
  content is referenced in place, never copied into source.
- Shared plan for furniture, avenue trees and street lamps: full footprints,
  a pedestrian corridor, rare-fixture cadence, priority competition, tile halo,
  water/parking/mapped-point exclusions, vegetation reservations. Forest lamps
  retain the night light pool and retire its entries safely.
- Measured installed `lamp1.dae` bounds: approximately X ±0.604 m, Y ±0.312 m;
  planner uses ±0.61/0.32. Small East Coast oak crown fits the avenue envelope
  at scale 0.65 (raw XY extents −1.78..2.36, −2.28..1.48 m, height 8.16 m).
- Automated suite: 285 run, 282 pass, 3 missing-fixture skips. Offline central
  Kyiv nine-tile results and full game reports live in `out/city-detail/`.
  Current 6 m route drove 929 m; mean 18.64 ms, p99 48.5 ms; two >100 ms frames
  mean the strict performance gate still fails. See `docs/CITY_DETAIL.md` for
  comparisons, verification and remaining limits.
- Final 3 m stress: 928 m, 19.29 ms mean / 51.5 ms p99, 3 >100 ms frames;
  Potato/OASIS preserved the road. Post-drive ray smoke: 80/80 rays hit around
  10 solid trees and 10 lamps after collision rebuild. Not a vehicle-impact test.

## 2026-10-23: bridge substructure, Estonian road register, county sections

- Bridges: girder depth by class, piers every 25 m (none on a road under the deck),
  abutments, guard rails on main-road approaches. OSM railings and guard rails mapped
  beside a deck are no longer drawn on the ground across the road under it
  (`ROADS.offDecks`); the lower road's own rails still run under the deck.
- `--road-register` (Estonia): Transpordiamet carriageway widths, shoulders and guard
  rails matched onto OSM ways (`est_roads.py`); tagged shoulders win in the widths.
- Sections: `country_fetch.py sections` / `build --section <id>` writes one
  administrative area as `earthng_<country>_<section>.zip`. `countries.lua` joins
  mounted sections into their country and lets a section answer over the
  whole-country regions it overlaps; the map menu lists sections as jump points.
  A section's zip leaves the offline map to the country pack.
- Validation: unit suite 267 passed (3 skipped); native landing harness with the full
  Estonia pack plus the Harju section ready at Tallinn, Jüri, Tartu, Kuressaare and
  Narva, 0 failed tiles; driven in BeamNG (Tallinn, Loksa, Pärnu).

## 2026-10-22: offline map detail, search, stock minimap

- Route: existing GE Lua/ImGui APIs, no new loader. Read installed BeamNG
  `lua/ge/extensions/ui/apps/minimap/roads.lua`: it reads `map.getMap().nodes` once
  into a spatial tree, exposes `reset()`, and does not subscribe to navgraph reloads.
  EarthNG now refreshes that cache after its graph changes, even with traffic off.
  Stationary tile arrivals are batched every two seconds; old graph nodes are cleared
  on landing changes, country removal and extension unload.
- `build_map.py`: OSM settlement nodes (including villages/hamlets not attached to ways),
  names/aliases and simplified main roads at three levels. Spatial JSON tiles are
  generated offline, not decoded from driving blocks when zooming out. Original sources
  stay outside Git; Ukraine source reused from the earlier Earth2Road data cache.
- `mapCatalog.lua`: mounted-country filtering, lazy sidecars, bounded road cache.
  Country `map/` takes priority over planet `maps/<id>/`, so existing country ZIPs can
  gain detail through a planet update. Missing sidecars retain the original base map.
  New Map Builder and spot builds include their own sidecars. An old tile-only cache
  without its original PBF retains the fallback and reports the missing map source.
- Search: countries and settlements, aliases in local/English/Ukrainian names,
  exact/prefix matching before population, language/limit-aware cache, keyboard arrows,
  Enter, Escape, clear button, fixed search field, result kind and country context.
  Map has a car-centering control; overview roads continue below street zoom.
- Initial live Albania picker passed but cost ~20 ms/frame / 1.2 MB garbage with
  uncached line points. Reused projected ImVec2 objects and colors, capped point
  preparation per frame; close-up driving uses existing local lanes instead of the overview.
- Data prepared: Ukraine 35,985 settlement/district nodes, 165,208 main-road ways;
  Albania 4,514 nodes, 14,696 ways. Detailed sidecars in this update cover these two
  packs; global country/city search continues from Natural Earth.
- Validation in progress: initial full suite 222 passed, additional traffic-off minimap
  regression passed. Real game profiles and captures: `out/map-picker-01` and subsequent
  `out/map-*` runs. Personal profile not used for testing.

## 2026-10-22: climate biomes, the vista from summits, Death Valley above the sea

Detail and measurements: `docs/NATURE.md` (22.10).

- Planet: Köppen-Geiger 1991-2020 (Beck et al. 2023, CC BY 4.0) at one arc minute in 10 degree
  land blocks (`earthng/build_climate.py`, 2.9 MB), read lazily by the new `e2r/biome.lua`.
  Groups: rainforest, savanna, desert, steppe, Mediterranean, temperate, boreal, tundra, ice.
  Tree and snow lines by latitude and climate; a measured tundra ridge lowers the tree line.
- Generator (`bio` in `build()`): untagged ground of other climates is desert, dune, steppe, golden
  grass, tundra, alpine turf, scree, rock or snow (snow patches by height and aspect); verges and
  edge decals follow. Plants and stones from Utah, Johnson Valley, West Coast USA, Jungle Rock Island
  and Italy: junipers, creosote, yucca, sagebrush, live oaks, eucalyptus, palms, rainforest, holm and
  cork oaks, olives, krummholz near the tree line, dwarf alpine shrubs. Their level material files
  load once a tile names them (`stockMaterials`). Temperate climate builds byte-identical tiles.
- The sea plane no longer floods depressions far inland (Death Valley was 46 % water).
- Vista: from a summit or pass (camera 250 m over the lowest ground within 5 km, under 15 m/s) the
  horizon runs on to 24 km in 4 km blocks of 400 m steps, from elevation grids alone
  (`cellformat.terrain`); the level's far clip and fog follow it.
- Art: 9 ground sheets from ambientCG CC0 (desert, dune, steppe, dry grass, tundra, alpine, snow,
  snow edge, glacier), normals and smooth colours at 1024 px: planet ZIP +15 MB.
- Pack builder: a region without a single road (Everest's) no longer crashes and lands in its
  most central full cell. The Everest spot pack (`spot_pack.py --id everest`, 24 km) builds.
- Tools and tests: `earthng/biome_census.py` (ground and plants round any point of any pack, map),
  `test_biome.py` (4), native vista and terrain decoder tests.
- In game (8 places, `out/biome-game`): landing where no road is within 500 m now stands the car on
  the gentlest ground within ~80 m (summits failed with `no_drivable_spawn`); warm-up shapes hide 3 km
  under the landing (they hung over Whitney's east face); cross-folder level materials (Jungle Rock's
  lianas showed NO MATERIAL ribbons; `VEG.stockExtra`, planet `leaves_thin`); 80 m slopes and 150-200 m
  patches instead of a triangle mosaic; the vista's light tiles (380 instead of 762) over a 200 km
  plane at the lowest ground; European tree line lowered (45 deg 2050 m, 50 deg 1500 m). Frames:
  Las Vegas 18.4 -> 14.7 ms, Zanzibar 12.5 -> 10.7 ms against the planet before biomes.

## 2026-10-21: road quality by class, junction details, bridges that clear

Tested on an 8 x 8 km Map Builder selection south-east of Tallinn (Jüri, Assaku, Kurna, Vaida):
road 2/E263 trunk, its ring road and roundabouts.

- Export: a selection now cuts whole cells around it (`osm_tiles.source_box`); before, only the
  tiles wholly inside the selection survived (3 of 18 here), so most roads were missing.
- Widths by class (`fast_sources.road_width`, index `fast-11`): lane width per class (motorway
  3.75 ... residential 2.75), implied oneway for motorways and roundabouts (one lane by default),
  roundabouts at least 5.5 m, paved shoulders on motorway/trunk/primary/secondary. Every 2-lane
  class used to be 6.6 m.
- Generator `ROADS`: oneway (implied too), rank, material by rank (links follow their class),
  markings by class and surface: none on gravel or under 4.5 m, lane lines share the carriageway
  between the shoulders, edge lines on the main classes, a double solid centre on 4+ lane roads.
  Markings follow the trimmed strips, so they stop at a junction's mouth.
- Junctions: two ways meeting in a gentle bend (<= 60 degrees) join with a mitred edge, no star;
  a junction's fan takes the majority material of its mouths (a worn look had dark patches).
  Per-side `sidewalk:*` tags win.
- Junction details from OSM nodes (`fast_style.ROAD_DETAILS`, kept 30 m past a cell): zebra
  crossings across the carriageway, give-way teeth and stop bars at the junction mouth on the
  approach's right half, turning circles as round bulbs, mini-roundabout rings.
- Bridges: the height solve holds a bridge 5.5 m (per layer) over a road it crosses in plan
  (`fast_profile.crossings`, an active-set lower bound: decks already high stay where they are),
  and the road under a bridge end is no longer coupled to the bridge's approach (it dragged
  the trunk into an underpass: 43% grade). 33 crossings, 0 short; steepest ground road 5.7%.
  Lua draws deck edges, a soffit and parapets. Bridge/tunnel tests match `fast_profile.kind`.
- Estonia (`country_fetch.py build --local-dem`, `earthng/est_dem.py`): the Land Board's 10 m
  LiDAR DTM (19 sheets, no login) is burnt into the cached Terrarium z12 tiles, feathered over
  500 m at the survey's edge; originals kept in `terrain/12.orig`, `--restore` puts them back.
  Terrarium stood 3-10 m high under forest and towns (Jüri 61.7 -> 52.8 m).
- Bench (`road_quality.py`, 78 tiles): curb on road 0.5 -> 0.4, ground on road 5.64 -> 5.42,
  holes 5.78 -> 5.56 m2/km; no metric worse. 231 unit tests.

## 2026-10-18 (day): collision only where something can reach it, generator pauses

Detail and measurements: `docs/PERFORMANCE.md`.

- Found in game: a ProceduralMesh hidden during `be:reloadCollision` stays out of the static
  collision after it is shown again (nothing else excludes it: material flags, renderEnabled,
  disableCollision; `reloadStaticCollision` is the same call). New `e2r/collision.lua` records
  every mesh with its owner and hides, for the rebuild only: the horizon, far and near tiles out
  of reach (`want`/`keep` round the car, a parked car and every vehicle), markings, roofs and the
  scene's ground covers (drapes 2.5-4 cm over the ground mesh). Central Kyiv rebuild 133 + 34 ms
  physics -> 36-40 + ~12 ms. The rebuild check keeps running while any loaded tile is left out.
- Generator: pauses in the junction builder, in the ground press (its counter restarted on
  every road, so short city roads never paused) and in the plant sort (now per 25 m bucket, same
  output: digest of 3x3 tiles in Kyiv and Yaremche unchanged). Kyiv stream bench longest resume
  75.7 -> 59 ms. Cell decode pauses in the elevation grid.
- Minimap lanes are projected at most 1500 points a frame.
- Kyiv route: 15.1 -> 14.8 ms mean, p99 44 -> 39.5, frames > 100 ms 5 -> 2 (both the drive
  start). Yaremche unchanged (8.6 ms). Traffic (8 cars): ground under every car in 950 checks.
- Checks: 168 unit tests (new `test_collision.py`), Yaremche smoke with the quality cycle passed.

## 2026-10-18 (night): streaming cost, Forest commits, collision, fences

Detail and every measurement: `docs/PERFORMANCE.md`.

- Engine facts measured in game with a new probe (`earthng/probe.py`, `test_world.py --probe`) and
  `Engine.Debug.getLastPerformanceMetrics`: the built world renders in 5-7 ms; the cost was the
  streaming itself on one main thread (GPU ~30%). `rebuildForestManagerInstanceData` is not needed
  for crowns to show (identical frames) and cost 47-60 ms. Any Forest change costs ~3 ms of engine
  Ticking per touched crown kind. Every ProceduralMesh is static collision whatever its group;
  `be:reloadCollision` is ~0.27 ms per 1000 triangles plus ~35 us per object. A TSStatic is ~12 us,
  not 0.9 ms (that was the first load of a shape). A new (object, material) pair costs ~2.3 ms the
  first frame it is drawn. Vehicle Lua overlaps the frame only partly; no worker threads for GE Lua.
- Forest: no instance rebuild; adds/removals queue per kind, one kind per 0.12 s, each kind at most
  every 1.5 s; tiles find their crowns by rectangle (`getItemsBox`) instead of holding 160k userdata.
  Rocks are TSStatic again; grass and rocks stream in whole 32 m cells with their own reach and cap.
- Lua heap: delivered manifests keep only an item count; detail cells keep plain arrays.
  Yaremche heap 256 -> 190 MB; the 300-420 ms full collections are gone from the test drives.
- Meshes: near tiles one material per piece (pairs per city tile 113 -> ~49), distant tiles up to four;
  at most 3 new pairs a frame while driving. Horizon draws no verges, far tiles only in a 30 m band at
  the edge (city far tile 2950 -> 1215 triangles, horizon block 6340 -> 320).
- Generator: numeric lattice hashing, banded point-in-polygon, string-free caches (near tiles 36%
  faster); 2 ms budget once the landing is done and no near tile waits. Minimap: one ImVec2 per point.
- Bugs: chain-link fences no longer vanish from ~6 to ~35 m (`alphaRef` 80 -> 30, same DDS); the parked
  car no longer falls through the world when a free camera roams past 100 m; the test's `fell` check
  is a sudden drop, not Kyiv's 50 m descent to Podil.
- Checks: 164 unit tests pass (new: Forest commit queue, pair cap, rock cells, distant verges).
  Results table: `docs/PERFORMANCE.md`.

## 2026-10-18: bounded vegetation streaming and Potato / OASIS

- Grass and rocks use a 32 m spatial index and camera-relative residency with global caps;
  trees remain in the single Forest, queued in batches of 32. Decorative instances no
  longer trigger collision rebuilds. Candidate loops yield frequently enough to respect
  the native generation budget; the full Forest upload remains an indivisible cost.
- Compact bilingual widget: master Potato / OASIS, independent detail and draw distance,
  current FPS, preset buttons, collapsed advanced controls, style/traffic and statistics.
  Settings persist alongside language. Density changes preserve road meshes/collision,
  regenerate scenes separately, and invalidate prebuilt tiles at the old density.
- LuaJIT regression checks: detail 8, widget 7, native 23, nature 16, generator 34,
  styles 8 (96 passed). Test runtime: Earth2Road .venv; local Python 3.13 lacks luajit21.
- Real BeamNG comparison, same Yaremche start (48.45306, 24.55611), 20-second straight
  drive in fresh isolated profiles, one game process at a time. Different presets have
  different density/range; this is a user-preset comparison, not identical geometry.
  Before: 19.2 FPS, p99 92.5 ms. Balanced: 50.3 FPS, p99 59.5 ms. OASIS: 32.7 FPS,
  p99 76 ms. All functional gates passed; the >100 ms frame gate still fails (2 / 1 / 5
  frames respectively, worst 125.6 / 108.4 / 498.3 ms). No claim of locked 60 FPS.
- Actual in-game Potato -> OASIS cycle retained the road groups and collision; car height
  changed at most 0.27 m. Native screenshots and widget capture inspected. Test reports:
  out/quality-before, out/quality-balanced-final, out/quality-oasis; comparison.json and
  widget-final.png under out/quality-bench. The initial intermediate Balanced run is
  out/quality-balanced; use the final run for comparisons.
- Installed verified release ZIP in the normal BeamNG current/mods folder; previous ZIP
  backed up at out/quality-bench/installed-before.zip. Country packs need no rebuild.
  Release SHA256: da77174eec5f8056453173b0e83326cab4eade635d066c566de110b250612d00.

## 2026-10-18: country pack window

- `Country.bat` lists every Geofabrik extract. A ready zip can be installed from
  disk or from `earthng/ready_packs.json`. Otherwise the window downloads that
  extract, cuts tiles, fetches Terrarium and builds `earthng_<id>.zip`.
- The country manifest stores `look` (asset block and six slots) and `include`
  (which OSM layers were kept). Roads and the elevation grid always stay.
- The generator reads `look`: worn/fresh asphalt, white/yellow/no markings,
  verge material, untagged facade family, tree mix, lamps and stops.
  `mark_yellow` is a solid-colour material. Tagged buildings still follow OSM.
- Unit checks: `test_country_setup.py` 12, `test_generator.py` 34, `test_styles.py` 8.
  The window was not driven inside BeamNG.
- `Country.bat`, `EarthNG.bat` and the country build use this checkout's `.venv`
  (`requirements-fast.txt`). Earth2Road stays only for the optional `v2` generator.
- The country-pack window, its log and the asset-block labels are English.
- `Rebuild.bat` builds `earthng_planet.zip` with the local `.venv` and copies it into the BeamNG mods folder.

## 2026-10-17: one Forest, tiles paint again

- A Forest per tile is never frustum-culled (global bounds), so each loaded
  tile walked its own crowns on the main thread. The GPU sat near 30% and the
  frame sat near 20 FPS on one core. Crowns now share one `e2rForest`.
- `rebuildForestManagerInstanceData` reuploads every crown. It used to run
  every frame that planted or removed a tree, which stalled the tile queue.
  It now runs at most every 0.4 s. Ground meshes sort ahead of plants, so a
  nearer tile's crowns no longer block the next tile's road.
- The density panel shows the last rebuild time. Collidable stays off. The
  Forest object is still never deleted.

## 2026-10-17: grass blades are 20–30 cm

- The stock tufts are about 26 cm (short) and 52 cm (long). A shared scale of
  9–14 made them several metres tall, above the pickup. Scale is now the wanted
  blade height divided by that mesh span, so each tuft is 20–30 cm. The extra
  0.35 m lift is gone. The lowest vertex sits on the ground.
- Density is unchanged: town grass still 2.6 m, cap 4000. The old solid hedge
  was those same tufts blown up until they overlapped.
- Unit checks after the height change: `test_nature.py` 16, `test_generator.py` 33.

## 2026-10-17: frame time against vegetation

- A far cap of 2400 filled about 240k crowns and held the frame around 160 ms.
  Far default is 800 again (hard 1200). Near forest stays 2400. Forest adds
  per frame are 80.
- Residential trees are a 14 m lattice at chance 0.40, parks 12 m at 0.70.
  Grass spends its cap in town: residential and park at 2.6 m, cap 4000
  (hard 4800). Forest floor grass stays thin. Yard bushes are off.
- Unit checks: `test_nature.py` 16, `test_generator.py` 33, `test_styles.py` 8,
  `test_native.py` 22, `test_widget.py` 7.

## 2026-10-17: denser yards, lawns and canopy

- Forest step is 5 m, open ground 6 m, park and residential 8 m. Near and far
  tree caps are both 2400. Plants are round-robin across 25 m cells, so one
  grove cannot spend the whole tile. Open-ground keep chance is 0.94–1.00.
  Far grass stays off. Forest items are added in batches of 160.
- Grass scale is 10–16, default cap 1800 (hard 3200), and the road pad for tufts
  is 2.2 m. Bushes also fill ground, residential and park. The widget defaults
  and `clampTune` match these numbers, so Apply does not thin the world back.
- Unit checks: `test_nature.py` 16, `test_generator.py` 33, `test_styles.py` 8,
  `test_native.py` 22, `test_widget.py` 7.

## 2026-10-17: forests actually spawn, grass and stones show

- BeamNG 0.39 has `ForestItemData`, not `TSForestItemData`. The old call
  failed once per tree, so every crown was a TSStatic and the canopy flickered.
  A failed class is remembered for the session. Forest items refresh the
  forest manager after each batch. The far canopy is removed when the near
  scene of that tile starts, so the same trees are not drawn twice.
- Grass and rocks are queued before trees. Grass scale is 6.5–11 and the tuft
  is lifted 0.35 m. Slope stones start at about 20° (`nz` 0.94) instead of
  45°, with a lower chance on gentler slopes. Flat ground still has none.
- Forest groves fill at 0.80–1.00. Open ground fills at 0.88–1.00. The far
  tree cap default is 640 (hard 800). Far grass stays off.
- The density panel copies slider values even when ImGui does not return
  true, rebuilds when the slider is released, and shows the numbers that are
  actually in the world plus live grass, rock and crown counts.
- Unit checks: `test_nature.py` 16, `test_generator.py` 33, `test_styles.py` 8,
  `test_native.py` 22.

## 2026-10-17: dense woodland and a density panel

- Untagged ground gets its own tree lattice (8 m, about 40% Scots pine, the
  rest East Coast oak, beech and aspen). Forest polygons use a 6 m step.
  Near cap 1800, far cap 320. Far stays a prefix of the same sorted list.
  Far grass stays off.
- Grass and rocks spawn as TSStatic again. Forest is trees and bushes only,
  because an alpha tuft placed as a Forest item was not drawing.
- The driving widget has «Щільність і дистанція»: radii, caps, spacing, and
  an apply button that rebuilds near and far tiles. The horizon stays.
  Any camera that is not the cockpit or the hood, once it is 100 m from the
  car, owns the detail bubble. The panel shows the live camera name.
- Unit checks: `test_nature.py` 16, `test_generator.py` 33, `test_styles.py` 8,
  `test_native.py` 22.

## 2026-10-17: Yaremche draw distance, fences, Forest

- The near bubble follows a free or orbit camera once it is more than 100 m from
  the car. Velocity is zero in that mode, so look-ahead does not drop the tiles
  behind the lens. Cockpit driving stays on the vehicle.
- Far tiles draw fences. Paths and the horizon do not.
- Trees, bushes, grass and loose rocks spawn as non-colliding Forest items,
  one Forest per tile, returned to a pool after `removeItem`. Three failed
  creates fall back to TSStatic for the rest of the session. Deleting a
  colliding Forest is avoided: that hang is real.
- Open ground (no meadow polygon in the current Ukraine pack) gets grass.
  Slopes steeper than about 45° get rocks. Untagged ground keeps the ground
  material, so a far hill stays one mesh. Far grass stays off. Far rocks stay
  a subset of the near list.
- Unit checks: `test_nature.py` 16, `test_generator.py` 33, `test_styles.py` 8.

## 2026-10-17: P2 countryside scatter and road grades

- Grass tufts, forest understory and loose rock are TSStatic decor on the P1
  cover classes. Far keeps rocks only, as a subset of the near list. No Forest,
  GroundCover or TerrainBlock.
- Shapes and their materials stay in the player's BeamNG install (Italy pines,
  East Coast USA grass and rocks) and load through VFS.
- Rural carriageways take a grade 0–5 from surface, tracktype and smoothness.
  Grade 0–1 keeps the surveyed profile. Grade ≥ 2 undulates and drops sidewalks.
  Untagged city asphalt is unchanged. `highway=track` becomes a drivable ribbon
  and stays out of the navgraph.
- Planet manifest in source is 0.4.0; `natureVersion` stays 1. Country packs do
  not need a recompile. `earthng_planet.zip` is still the previous build until
  `build_mod.py` is run, so the five new road materials are missing in game.
- Unit checks in the Earth2Road venv: `test_nature.py` 15, `test_generator.py`
  32, `test_styles.py` 8. No in-game drive for this slice.
- Detail: `docs/NATURE.md`, section P2.

## 2026-10-17: P1 nature implementation

P1 land-cover classes, WorldCover and TSStatic trees are in tree. The note below
is the original working record.

- Starting from Grok P0 commit `11a7d67`; preserve its DEM horizon and road shaping.
- Route: existing native ProceduralMesh/TSStatic; v2 area strings carry new natural
  classes, optional offline WorldCover raster import, no companion or format fork.
- Verified stock rock/sand PBR in `content/assets/materials/terrain.zip` and Scots
  pine shapes in `content/levels/italy.zip`; load stock materials through VFS.
- Test profiles/packages go under `out/p1-*`; regular saves/profile are untouched.
- Baseline: generator 32, country 14, native 22 tests passed in Earth2Road venv.

2026-10-15, branch `codex/official-mod-packages`.

- User selected runtime Lua generation and compact country data, rather than
  distributing baked geometry or requiring a Python companion.
- Native entrypoint: `scripts/earth2road_world/modScript.lua`; GE extension
  `e2r_world`; carrier level `e2r_world`. Public ZIP: `earthng_planet.zip`.
- Countries: mounted VFS `/earthng/countries/<id>/manifest.json`. Disabled and
  unmounted mods must never contribute landing coverage.
- Country compiler exports source features and elevation grids from prepared
  OSM indexes. No game assets, interpreter, SQLite database or baked mesh shipped.
- Shared distributable art uses our drawings/CC0 photo sources. BeamNG assets
  are referenced from the player's installation, rather than copied.
- Installed test game: Steam 284160, build 20972 (integrity metadata dated
  2026-08-07), `C:/Program Files (x86)/Steam/steamapps/common/BeamNG.drive`.
- Tests run in fresh `out/native-*/user` profiles; regular game profile is not
  modified. No keyboard/mouse automation or profile/save migration is needed.
- Implementation and format: `docs/NATIVE_MODS.md`.

Validation: 57 unit/regression checks pass. The empty native planet starts in the
real game. Two-country native generation/landing/collision/25m driving work with
no companion process or request/pose files. Earlier feature run confirmed four
moving AI cars, rain and all four base texture packs. Native game test 03 still
fails the unchanged 100ms frame gate (p99 195.5ms, worst295.85ms); performance and
full generator parity remain release work, documented in `docs/NATIVE_MODS.md`.

Fixes verified during migration: road-only landing selection, source-cell building
datum continuity, safe country-button landing points, reset while generation is
pending, pinned startup geometry until touchdown, and release/unload of Lua mesh
arrays after engine upload. Exact UTM is tested against pyproj in both hemispheres.

## 2026-10-17: якість доріг і зависання з трафіком

- Полігон центру Києва 10 x 10 км (`out/polygon/earthng_kyiv10.zip`) і стенд
  `earthng/road_quality.py` з метриками дефектів. Генератор доведено за ними:
  земля притиснута під асфальт, суцільні стрічки доріг із мітрою, тротуари врівень
  і обрізані по чужому асфальту, узбіччя, покриття на землі, перехрестя-зірки.
  Перехрестя виводяться з кінців доріг у рантаймі: пакети v2 не перезбираються.
  Усі 400 тайлів: тротуар на дорозі 53,7 -> 1,9 м2/км, земля над асфальтом
  556 -> 7,6 м2/км, перепади на краю понад 30 см 44,6 -> 8,9 на км.
- Паркани йдуть по землі й мають товщину; автобусні зупинки стоять біля дороги.
- Вічне зависання під час трафіку: ребра навграфа нульової довжини зациклювали
  `graphpath.getRandomPathG` під час респавну. Виправлено в генераторі й `navBuild`.
- Сторож зависань пише стек Lua у `e2r-hang.txt`; `test_world.py` під'єднує
  моди жорсткими посиланнями.
- Подробиці: `docs/NATIVE_MODS.md`, розділи «Якість доріг» і «Трафік і зависання».


## 2026-10-18 — first native release preparation

Removed companion launch/server/package paths and the retired Python mesh generator;
kept native Lua runtime, shared source indexing and art tools. Country.bat bootstraps
Python 3.13 through Setup.bat. Worker logs, Windows cancellation and truncated-download
checks cover the local builder. The game harness now lives entirely in this checkout.

Validation: 159 tests pass; clean source copy skips only two generated-basemap tests.
Real Liechtenstein PBF → DEM → 144 cells → installed pack succeeds both through the
console backend (34.74 s) and Tk/pythonw (57.07 s). NYC physics drives pass functional
checks but fail the >100 ms frame gate under concurrent game/OSM worker load.
See docs/RELEASE_CHECK.md and docs/benchmarks for reproducible commands and results.
No personal game profile or existing OSM job was changed. Existing caches were not deleted. Tests use isolated
out/release-* profiles. MIT chosen by the user; target master confirmed by the user.

## 2026-10-21: асфальт із фото і справжні припарковані машини

- Дороги як у самої гри: основа — аерофото вулиці Poly Haven `aerial_asphalt_01` (4K на 30 м:
  тріщини, латки, сліди шин), деталь — фото асфальту на 2 м повного розміру через detail-карти
  (`asphalt_01` у місті, ambientCG `Asphalt026C` зношений, `Asphalt025C` свіжий). Розмітка —
  стерта лінія ambientCG `RoadLines025B`. Усе CC0, джерела в `data/textures/manifest.json`.
- Гра додає detail-карти до кольору лінійно (`defaultMat.hlsl`, `blendDetail`); BC1-кодувальник
  тепер округлює канали, а не обрізає (давав фіолетово-зелені плями).
- Коробки на стоянках замінено машинами гри: `parking.lua` віддає місця з OSM-стоянок системі
  `gameplay_parking` (легкі `simple_traffic` *_parked). Машини вантажаться під час спуску, місця без
  колізії заборонені. Вибір у панелі: Вимк (коробки) / Мало (8) / Багато (16). Підземні паркінги
  й паркінги на дахах пропускаються.
- Київ, Мінська, 60 с автопілота, два прогони кожної збірки: середній кадр 16,1 / 15,1 мс проти
  14,3 / 13,9 мс у старої планети, p99 42,5 / 38 проти 36,5 / 37,5 мс, кадрів >100 мс 2–4 в обох.
  Кадри: `out/park-vis-04`. Планета 86,5 → 127,6 МБ.
