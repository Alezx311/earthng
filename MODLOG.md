# EarthNG native mod migration

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
