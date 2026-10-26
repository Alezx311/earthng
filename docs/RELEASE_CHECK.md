# Release verification

## Map Builder — 2026-10-26, morning

Only `EarthNG-MapBuilder.zip` on the `EarthNG` release is replaced, built from e8e2285.
`earthng_planet.zip` stays the 0.6.3 file: nothing the planet carries (mod/, fast_art,
fast_packs, materials in fast_style) changed since c7ac7be, so Refresh planet code writes
the same Lua and materials. The previous Map Builder ZIP is kept in
`out/release/mapbuilder-20261026-backup`.

The overnight changes are in docs/MAPBUILDER_REVIEW.md: Ukraine from scratch builds in
1 h 25 min instead of about 4 h, the export resumes after Stop, and a build checks the
disk, holds a lock and keeps a current PBF when HEAD fails.

- Full unit suite: 395 tests OK (`.venv`).
- Map Builder ZIP unpacked into `out/release/test mapbuilder 20261026` (a folder with
  spaces): `test_country` 22, `test_country_setup` 25, `test_mapbuilder` 37, `test_tiles` 6,
  all OK; the window's modules import there with `python -I`.
- Ukraine built from scratch with this code into a disposable profile; that pack was not
  driven in BeamNG.

## Planet 0.6.3 and Map Builder — 2026-10-26

The `EarthNG` player release gets a new `earthng_planet.zip` (manifest 0.6.3) and
`EarthNG-MapBuilder.zip`, both from c7ac7be. `earthng_albania.zip` stays the published
0.4.0 file. The previous two assets are kept in `out/release/player-0.6.3-backup`.
Country packs on Drive are not replaced; the live mods folder is not touched.

Since 0.6.1: the 0.6.2 lawns, yards of blocks of flats (cars on driveways,
playgrounds, porches, front gardens), and an inferred lamp no longer stands within
12 m of a lamp OSM maps. Map Builder: the fixes of docs/MAPBUILDER_REVIEW.md, packs
with point lamps and trees, lone stops and entrances, separate sidewalks and pedestrian
squares, recut of tile caches made by older rules, parallel region index and worker
counts sized to cores and free memory.

- Full unit suite before packaging: 387 tests OK (`.venv`).
- Map Builder ZIP unpacked into `out/release/test 0.6.3` (a folder with a space):
  `test_country` 21, `test_country_setup` 24, `test_mapbuilder` 32, `test_tiles` 5, all
  OK; the window's modules import from that folder with `python -I`.
- Ukraine built through Map Builder's own path into a disposable profile
  (`out/mapbuilder-ukraine-20261025`): 3.32 GB, timings in docs/MAPBUILDER_REVIEW.md.
  That pack was not driven in BeamNG, and this planet was not driven in a disposable
  profile before publication.

## Planet 0.6.2 — 2026-10-25

The `EarthNG` player line stays on the 0.6.1 download. This planet is a separate
GitHub release, tag `0.6.2` (manifest 0.6.2, built from aca4265). `earthng_albania.zip` is still the
0.4.0 file on the `EarthNG` release. Country packs are not rebuilt and are not
replaced in the live mods folder.

Lawns, parks, meadows and residential yards are stock soil (`t_macro_clumpy`)
with a 2 m vegetation detail, and a short-grass carpet of the three East Coast
`short` tufts. The flat lawn photo is no longer the city sheet. Forest, fields,
orchards and vineyards keep the thin scatter. Dry and cold climates do not get
the green carpet. Balanced keeps about 9000 live tufts, OASIS about 14000.

- Unit suite before the tag: `test_detail` 15, `test_styles` 20, `test_nature` 18,
  `test_biome` 4, `test_generator` 96, with `C:\js\Earth2Road\.venv` and
  `PYTHONPATH=out/test-tools`. The full `discover` was not re-run after the
  manifest string changed.
- **Obolon**, 50.5105, 30.4970, Balanced (quality 50), graphics Normal, 1280×720,
  disposable profile `out/grass-soil-obolon-20261025`, BeamNG 0.40. Drive: 575
  frames, mean 19.5 ms, p99 55.5 ms, 36 frames over 33 ms, 2 over 100 ms. The
  worst drive frame was 585 ms at landing. `liveGrass` 8968 of the 9000 budget.
  Close views show clumpy soil between the tufts; from above the yard is still
  a green plane once the carpet ends. The run's only harness failure was
  `frame_over_100ms`.

## Planet 0.6.1 — 2026-10-24

The `EarthNG` player release gets a new `earthng_planet.zip` (manifest 0.6.1, built
from 1fb5d15) and `EarthNG-MapBuilder.zip` from the same tree. `earthng_albania.zip`
stays the published 0.4.0 file. Country packs are not rebuilt and are not replaced
in the live mods folder.

Since the 23 October 0.6.0 planet: side-by-side bridge carriageways share one deck,
with parapets only on the outer edges, and the ramp eases onto the approach. A long
bridge line drops a sharp kink and keeps a real bend. Deck clearance is 6 m from the
road below to the deck surface, so about 4.5 m remains under the girder, including
when an old pack is drawn. A repeated abutment no longer leaves a second step.
County sections are the map jump buttons; grid regions no longer repeat the country
name. Map Builder trusts unexpired system certificates plus the bundled ISRG roots,
and runs the region index and country export outside the window process.

- Unit suite: **351 tests passed** (the printed `RuntimeError: broken region list`
  and two `ResourceWarning`s are the existing builder checks).
- **Not done:** this planet was not driven in BeamNG before publication. The long
  bridge near Kyiv at 50.45730, 30.38654 was not looked at in the game again.
  BeamNG 0.39 was not run. The Ukraine file on Google Drive is still the 16 October
  pack.

## Planet 0.6.0 — 2026-10-23

The `EarthNG` player release gets a new `earthng_planet.zip` (manifest 0.6.0, 173.1 MB, built
from ab8c854) and `EarthNG-MapBuilder.zip` (378 KB, same commit). `earthng_albania.zip` is
byte-for-byte the 0.4.0 file. Everything on master since 0.5.0 ships: climate and biomes,
photo asphalt and the game's parked cars, the offline map, road quality and bridges (#5, #2),
the Map Builder start (#4).

- Planet vs 0.5.0: 20,552 → 22,816 entries, none removed. Added: offline maps of Ukraine and
  Albania (1,761 files, 31 MB), climate grid (464 files, 2.9 MB), 35 road and ground textures.
  Every texture `materials.json` and `packs.json` name is inside the ZIP; no stock game files.
  The notices now say the offline maps are derived OSM data (ODbL).
- **Refresh planet code** from the new Map Builder changes nothing in the new planet and keeps
  its language (it used to switch an English planet to Ukrainian). On a 0.5.0 planet it would
  name 35 textures that planet lacks: the notes say to replace the planet first.
- Unit suite: **267 tests passed**. Extracted Map Builder (folder with spaces): first start
  installs `.venv` and shows the window in ~30 s, a second start in 1.6–4.4 s; 57 builder,
  country, map and tile tests passed; the three CLIs answer `--help`.
- **Bridges, Kyiv** (`out/overnight/build_kyiv_bridges.py`, `grade_audit.py`): the user found the
  bridge by Beresteiska too low and a "bridge lying in the road" on Povitroflotskyi (now
  Povitrianykh Syl). Three causes:
  1. The Ukraine download (built 16.10) predates the clearance solve: in game the car hits the
     Vasylenka bridge over Beresteiskyi avenue at 13 m/s. A pack built now clears it by 5.47 m
     and the car drives under at 13.5 m/s. Needs a pack rebuild.
  2. The solve raised decks over 50–80 m: Borshchahivska 14 %, the Povitrianykh Syl overpass
     11.4 %. Grade limits by class (`fast_profile.GRADE_MAX`, index fast-13): 5.1 % and 6.0 %;
     roads over 8 % near a crossing 17 → 5, all 61 crossings ≥ 5.45 m. Bratislava: 235
     crossings ≥ 5.39 m (was 5.31), roads over 12 % near a crossing 15 → 2.
  3. A rail yard's wall from OSM stood across the Povitrianykh Syl overpass, and the
     parapets of the two side-by-side decks stood on each other's carriageway; both stopped
     the car at the same spot. Fixed in the planet, so it holds for old packs too: the
     overpass route (552 m) now drives through at 11–12 m/s on the new and on the old pack.
- Release ZIPs in disposable profiles, BeamNG 0.40.2: Albania (Tirana) 423 m, 17.6 ms mean;
  Kyiv centre route 1.78 km, 18.6 ms mean, p99 47 ms. Every run had 2–3 frames over 100 ms at
  the drive start or while landing, as before, so the performance gate reports failure.
- Ukraine pack rebuilt with these fixes (`build_packs.py --only ukraine`, index fast-13): 3.03 GB,
  101 regions, 871,422 cells, 128 min, no index block short of clearance. With the 0.6.0 planet
  both Kyiv routes drive through without assists: under the Vasylenka bridge at Beresteiska (min
  13.2 m/s) and over the Povitrianykh Syl overpass (min 10.8 m/s). File:
  `out/release/ukraine-0.6.0/earthng_ukraine.zip`, SHA-256 `91eac3b5e402c1adc925707cb562cf72d69d34fe7b6374fd8013e073fc2a2691`.
- **Not done:** BeamNG 0.39 not run (its files are gone). The rebuilt Ukraine pack still has to
  be uploaded to Google Drive in place of the 16.10 file; until then players get the old,
  partly too low bridges.

## Planet 0.5.0 — 2026-10-21

The `EarthNG` player release gets a new `earthng_planet.zip` (planet manifest 0.5.0,
built from b88dc1a) and `EarthNG-MapBuilder.zip`. The update covers road decals,
the buildings pass, vegetation density and species, and the BeamNG 0.40 Freeroam tile.
Map Builder also gets the optional online OSM street detail (#3).
Country packs are not rebuilt: `earthng_albania.zip` is byte-for-byte the 0.4.0 file.

- Planet vs 0.4.0: the same 20,552 entries, 9 changed (five Lua modules, `materials.json`,
  fast-art `packs.json`, the manifest and the level's `info.json`); art and basemap unchanged.
  The spawn point is now "Country picker" with `preview.jpg`.
- Apart from the manifest version, the planet matches the planet in the development
  profile where the changes were checked in BeamNG 0.40.
- Unit suite, with #3 merged: **209 tests passed**.
- Extracted Map Builder (folder with spaces): 50 files, as in 0.4.0. **55 builder, country,
  map and tile tests passed**. The `country_fetch`, `build_country` and `osm_tiles_country`
  CLIs answer `--help`, and `country_ui` imports.
- Development A/B runs at Obolon, Kyiv, BeamNG 0.40, after the groundcover fix: 4 drives,
  mean 16.3–17.9 ms, p99 51–53.5 ms, worst 73–122 ms. All functional checks passed. Three
  of the four drives had one frame over 100 ms, so the performance gate failed in those runs.
  These were development builds, not the release ZIP.
- **Not done:** no separate smoke test of the release ZIPs in a disposable profile, because
  the game was in use. BeamNG 0.39 was not re-run because its game files are gone; road
  decals fall back to the previous look when stock maps are missing (`e2rFallback`).

## Player package update — 2026-10-19

The `EarthNG` release now separates the native planet (86.5 MB), the Albania demo
(225.8 MB, 8 regions) and `EarthNG-MapBuilder.zip` (about 300 KB). Developer assets,
full source and the small Liechtenstein test pack are in `developer-assets-0.4.0`.
The player archive includes only the builder's local module dependencies, runtime
resources, startup files, instructions and licenses. Its ready-pack catalog links
to Albania. `prepare_release.py` reads committed source, leaving local work out.

- Extracted Map Builder: 50 builder, country and UI tests passed; both CLI entry
  points load. Package lint: no failures or warnings. Initial verification caught
  a missing material JSON; the final archive includes it and passes these checks.
- The native planet is byte-for-byte the previously published release ZIP.
- Albania ZIP integrity passed. BeamNG 0.39.4, disposable profile, Tirana at
  41.3275 / 19.8187: loaded, rendered and drove 147.9 m; functional checks passed.
- Performance gate **failed**: 2 of 918 driving frames exceeded 100 ms;
  mean 18.68 ms, p99 50.5 ms, worst 167.12 ms. This is a smoke test at one place,
  not verification of every region or a stable-performance guarantee.
- Local evidence: `out/release-albania-game/report.json` and its screenshots.

## Original candidate verification — 2026-10-18

Target: `master` (the repository does not currently have a `main` branch).
Candidate manifest version: 0.4.0. The following records the checks before publication.

## Country builder

- Python 3.13.2, Windows. `Setup.bat` succeeded in a fresh source directory containing
  spaces; `Country.bat` started the Tk window with that checkout's interpreter.
- Tk smoke: loaded the real Geofabrik index, searched/selected Liechtenstein, checked
  the western asset block and parsed a custom bounding box.
- Clean Liechtenstein build, with no PBF/OSM/DEM cache: **34.74 s**, **3,755,929 bytes**.
  Downloaded the PBF, cut 6 source tiles, fetched 30 DEM tiles, exported 144 cells,
  and installed `earthng_liechtenstein.zip` into a disposable profile.
- Full Tk **Build my own** flow under `pythonw.exe` in the clean directory: **passed**,
  **57.07 s**, same 3,755,929-byte pack. The captured UI log includes tile-cutting
  progress and the final installed path; 554 Geofabrik regions were available.
- Download truncation now preserves the partial file and never overwrites a complete
  destination. Tile-worker output reaches the UI; Stop terminates the tile-cutting
  process tree on Windows. Later stages stop after the current stage, before installation.
- Default country-build parallelism is capped at four workers to limit memory pressure.
- Freshly built Liechtenstein ZIP also loaded in BeamNG: **functional pass**,
  **58.08 m** travelled in the 12-second drive. Performance gate still failed
  (one drive frame >100 ms); the same background-load caveat applies.
- Final unit suite: **159 tests passed** with local basemap resources. A source-only
  copy: **159 run, 2 skipped**, both tests requiring the optional generated basemap.

## Dense-city benchmark

Times Square / Manhattan, **40.758, -73.9855**. Existing native New York pack,
BeamNG.drive **0.39.4.0.20972**, Direct3D12, fresh disposable profiles,
Configured for 1280×720, Normal graphics, no traffic, 45-second scripted physics drives.
Engine logs show the actual window changing between 1264×681, 1180×720 and
392×719 during both runs; screenshots are internally rendered at 1280×720.
AMD Ryzen 7 3800X (8C/16T), RTX 2070 SUPER, approximately 32 GiB RAM.

**Environment limitation:** Vampire Survivors and pre-existing OSM-cutting workers
were running concurrently. They were not stopped. These are loaded-machine observations,
not an isolated hardware benchmark or a fixed-resolution FPS baseline. Do not infer
that Potato is slower from these runs. Both background load and window resizing must
be controlled for a release performance baseline.

| Metric | Default EarthNG quality | Potato (0) |
|---|---:|---:|
| Mean frame time | 20.63 ms | 25.05 ms |
| Approx. FPS (1000 / mean frame time) | 48.5 | 39.9 |
| p99 frame time | 62.0 ms | 86.5 ms |
| Worst drive frame | 186.87 ms | 231.59 ms |
| Drive frames >100 ms | 3 / 2420 | 15 / 2001 |
| Travelled | 842.3 m | 718.9 m |
| Peak process private memory | 4257 MiB | 4116 MiB |
| Functional result | passed | passed |
| Performance gate | **failed** | **failed** |

Default-quality request-to-land time: **28.29 s**. Cold asset warmup had a worst
frame of **4.806 s**, outside the driving measurement. Loading and driving must
be reported separately. Game screenshots were inspected: populated streets,
buildings, terrain and vegetation render; no claim of photorealistic city fidelity.

The LuaJIT-only benchmark (25 near/far tiles, 1800 simulated frames, 4 ms update
budget) measured mean **5.77 ms**, p99 **21.81 ms**, max **58.99 ms**, landing ready
at simulated frame **931**. It excludes rendering, physics and BeamNG object creation,
and is not an FPS estimate. Reports: [default](benchmarks/2026-10-18-nyc-default.json),
[Potato](benchmarks/2026-10-18-nyc-potato.json),
[LuaJIT](benchmarks/2026-10-18-nyc-luajit.json).

## Removed / retained

Removed the companion servers, launcher, all-in-one Python packager, startup scripts,
Python mesh generator, v2/Earth2Road bridge, spike scripts and obsolete handoff docs.
Shared OSM/DEM indexing, road profiles, art generation and native benchmark tools remain.
`world.lua` still contains dormant protocol branches used by isolated widget regressions;
release builds always use native mode and no longer expose `--legacy`.

The old implementations remain recoverable in Git history. Local PBFs, packs,
caches and existing user data were not deleted. Original code is MIT; third-party
attribution is kept separately. CI installs explicit tested dependencies on Python 3.13.

## Release disposition

Prepared for review as a **draft**, not a claim that every release gate passes.
Before a stable release: repeat performance runs with background workloads closed
and decide whether the remaining >100 ms frames are acceptable for an experimental
first release or should block it. Country coverage and performance for untested
large extracts remain unverified.

Reproduce/stage locally (after staging intended source changes in Git):

```powershell
.venv\Scripts\python.exe -m unittest discover -s earthng -p "test_*.py"
.venv\Scripts\python.exe earthng/build_mod.py --out out/mod --lang en
.venv\Scripts\python.exe earthng/prepare_release.py --out out/release/0.4.0-rc.1 --planet out/mod/earthng_planet.zip --country out/country-setup/earthng_liechtenstein.zip
```

The staging command writes native mod ZIPs, source ZIP, developer-assets ZIP,
licenses and SHA256SUMS.txt. It does not publish, tag, merge or change a game profile.
