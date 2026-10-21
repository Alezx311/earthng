# Release verification

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
