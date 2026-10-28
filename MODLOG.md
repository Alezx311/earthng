# EarthNG native mod migration

## 2026-10-28: no parked cars by default, streaming takes a share of the frame and stops on time

- The user: rubber banding / low FPS on every EarthNG map, never on other custom maps, on a high-end PC
  (GPU 20-70 %, the game's main thread at 86-88 % of a core in a clean test profile too).
- Measured with `earthng/test_world.py` (22 s autopilot drive, 1920x1080, Normal, Balanced, 3 to 6 runs each),
  frames over 33 ms ~ 10 per drive, one every 2 s: the generator's fixed 4 ms a frame (a third of a 10 ms frame),
  Lua GC steps of 10 to 50 ms (the Lua heap is 340 MB; the generator made ~500 KB of garbage a frame), and the game's
  parked cars (`gameplay_parking.setupVehicles`: 8 vehicles spawned in one 190-220 ms frame, then respawned ahead of the car).
- `quality.preset` parkedCars 8 -> 0 (the box cars stay; BeamNG has its own traffic; the window's slider still
  turns real parked cars on). 2 or 4 cars were as bad as 8 (frames of 540 to 750 ms).
- `quality.genBudget`: while driving, streaming gets 22 % of the frame's EMA (floor 0.5 ms, cap BUDGET_MS = 4); landing
  and warmup keep BUDGET_MS, and native.lua still raises it to 6 ms when the road ahead is missing.
- Result on the same drive (6 runs each): mean frame 10.1 -> 7.2 ms, p99 28 -> 20 ms, frames over 33 ms 10.7 -> 4.2,
  Lua GC frames over 10 ms 65 -> 17, worst frame after landing under 100 ms (the two frames over 100 ms left in a run
  are the landing itself, the engine's first move of the car). The world fills a little slower: 75 tile layers built
  in the drive instead of 84.
- native.lua's pause reads the clock at every pause point, not every 8th: a frame ran on for 8 points past its
  budget (the generator's part 4 to 13 ms against 1 to 2 ms, 206 such frames in a drive). With it (one drive each,
  every frame recorded): generator frames over 4 ms 206 -> 44, frames over 16.7 ms 101 -> 51, p99 20.6 -> 17.6 ms,
  as many tiles built (70 -> 77). Lua GC (frames over 3 ms ~ 210) and shadows of new meshes are what is left.
- Tried and dropped: setstepmul 100 / 50 (more frames over 100 ms), stopping the GC and stepping it by hand, one new
  mesh a frame (pairsDriving 1: no change).

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
