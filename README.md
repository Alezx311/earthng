# EarthNG

Drive through real places in BeamNG.drive. EarthNG builds roads, buildings and
terrain from OpenStreetMap and elevation data as you drive.

The game runs entirely in Lua with installed ZIP mods. Python is used only to
prepare country packs locally. No companion server or Earth2Road checkout is required.

## Install and play

Choose your downloads from the [player release](https://github.com/Alezx311/earthng/releases/tag/EarthNG):

| Download | Purpose |
| --- | --- |
| **earthng_planet.zip** (~270 MB) | Required native mod. Put in BeamNG's `mods` folder, keep packed. |
| **[earthng_ukraine.zip](https://drive.google.com/file/d/1WriRBq6pBBjSUyySV81RMgzRViK83NpJ/view)** (2.96 GB, Google Drive) | Ready Ukraine map, 80 regions. Put beside the planet ZIP, keep packed. |
| **EarthNG.exe** (~48 MB) | Optional: makes a map of any area you choose and installs it, together with the planet. No Python needed. |

**To play the demo, download only the first two files. Python is not required.**

**[Download more ready maps from Google Drive](https://drive.google.com/drive/folders/1n3A-msXrJtuQ2qJKn7YqzCooLZyliKMy?usp=drive_link)**
or use the [individual map links](docs/READY_MAPS.md). No generation is needed.
For a smaller first download, **earthng_albania.zip** (~226 MB) remains available
in the GitHub release. Always use the current **planet ZIP from GitHub** with these
country packs. If Drive wraps several downloads in an extra ZIP, extract that
wrapper; keep each `earthng_<country>.zip` inside packed.

1. Install **earthng_planet.zip** and at least one **earthng_<country>.zip** in the
   `mods` directory of your BeamNG user folder. Keep the ZIPs packed.
2. Start BeamNG.drive and open **Freeroam → EarthNG - Planet**.
3. Pick a point inside an installed country's coverage and land there.

The widget searches cities, villages and countries in local, Ukrainian and English
names. Use Enter or click a result, scroll to zoom and drag to pan. Main-road
overviews remain visible when zooming out, and BeamNG's stock minimap shows nearby
generated roads even with traffic off. Detailed village/overview data is currently
included for Ukraine and Albania; see [map controls and data](docs/MAP.md).

Use BeamNG's launcher to find your user folder; custom locations are supported.
Restart the game after replacing a ZIP. Remove the old companion-era
`earth2road_world.zip` if it is installed. Old all-in-one Python packages cannot
be used as native country packs.

Release files belong in [GitHub Releases](https://github.com/Alezx311/earthng/releases),
not in Git. See [release verification](docs/RELEASE_CHECK.md) for the tested build
and performance limits. This is an experimental first release: OSM completeness,
terrain detail and performance vary between places.

## Build your own map (Windows)

Download **[EarthNG.exe](https://github.com/Alezx311/earthng/releases/download/EarthNG/EarthNG.exe)**
and run it. It needs nothing else: Python and the build tools are inside, unpacked
once to `%LOCALAPPDATA%\EarthNG\runtime`. Downloaded data and built packs live in
`%LOCALAPPDATA%\EarthNG\data`. The window uses Microsoft Edge WebView2, which
Windows 10 and 11 already have.

1. The top of the window shows whether BeamNG's user folder was found (choose it in
   Settings if not) and whether the EarthNG mod is installed.
2. **Choose an area**: search for a town or address (Enter), or press **Draw an area
   on the map** and drag a rectangle. A town found by the search becomes the area.
3. Press **Create the map**. If `earthng_planet.zip` is missing or older than the
   packs need, it is downloaded from GitHub and installed first. Look, layers and
   project options are folded under the button.
4. Watch the stages. When it says **The map is installed**, start BeamNG.drive and
   open **Freeroam → EarthNG - Planet**.

The smallest Geofabrik extract covering the whole area is downloaded once and cut
into tiles; later builds in that region reuse the tiles. A town builds in a few
minutes. Large countries can require many GB of source data and hours of processing;
the estimate shown before building is a broad range. **Stop** cancels before the pack
is installed, and building again continues where it stopped.

Console equivalent (also useful for Linux/macOS with a local Python environment):

```powershell
.venv\Scripts\python.exe earthng/country_fetch.py build --place liechtenstein --mods "D:\BeamNG\current" --jobs 2
```

Estonia has its own notes and credits: [docs/ESTONIA.md](docs/ESTONIA.md).
For Estonia, `--local-dem` replaces the SRTM-based heights under the area with the
Land Board's 10 m LiDAR terrain (bare ground, about 4 m lower under forest and towns,
feathered into Terrarium over 500 m at the survey's edge). It needs `rasterio`
(`requirements-nature.txt`); the sheets are cached in `out/world/cache/est`, the
original tiles in `out/world/cache/terrain/12.orig`, and
`.venv\Scripts\python.exe earthng/est_dem.py --cache out/world/cache --restore` puts
them back.

`--road-register` (Estonia) takes the state roads' carriageway widths and shoulders and
their guard rails from the Transpordiamet road register (teeregister.mnt.ee WFS, cached
under `out/world/cache`). The register is open data, CC BY 4.0 on the national portal
(andmed.eesti.ee): a pack built with it may be shared, crediting Transpordiamet, Teeregister.

A large country can be built and improved in sections, one administrative area at a time:
`country_fetch.py sections --place estonia` lists them, and
`country_fetch.py build --place estonia --section harju-maakond ...` writes
`earthng_estonia_harju-maakond.zip`. The game joins every installed section into the one
country, and where a section overlaps the whole-country pack the section answers, so a
rebuilt county replaces just that area.

Data downloads/cache live under `data`, intermediates under `out`; neither is
committed. The default build uses at most four worker processes. Linux/macOS
country building has not been validated for this release.

## Development

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s earthng -p "test_*.py"
```

To rebuild the planet, extract **earthng-developer-assets.zip** from the separate
[developer resources](https://github.com/Alezx311/earthng/releases/tag/developer-assets-0.4.0) into
this checkout first. It supplies the separately distributed CC0 texture sources,
prebuilt distributable art and offline basemap. Then run `Rebuild.bat`, or:

```powershell
.venv\Scripts\python.exe earthng/build_mod.py --out out/mod --lang en
```

Stage player downloads from committed source (excluding local uncommitted work):

```powershell
.venv\Scripts\python.exe earthng/prepare_release.py --out out/release/player --planet out/mod/earthng_planet.zip --country out/country-setup/earthng_albania.zip
```

Use an empty output directory. The script produces the native mod, selected country
pack and a focused Map Builder archive, and prints SHA-256 sums for the release
description. It follows local Python imports, includes runtime resources and embeds
a ready-pack catalog. Developer assets, tests and research notes are not player downloads.

The basemap can regenerate from Natural Earth over the network. Rebuilding art
requires the texture sources; the helper for seasonal textures alone does not
supply the complete source set. Developer assets contain no BeamNG game files.

A repeatable game test uses a disposable profile, never your normal profile:

```powershell
.venv\Scripts\python.exe earthng/test_world.py --out out/nyc-test --lat 40.758 --lon -73.9855 --mod out/native-packs/earthng_new-york.zip --drive-seconds 45 --gallery
```

Set `BEAMNG_EXE` to the game executable if automatic Steam discovery fails.
`earthng/bench_native.py` measures Lua generation outside the game; its timings
are not FPS. [Native format and architecture](docs/NATIVE_MODS.md).

## License

Original code: [MIT](LICENSE). Country data and third-party art retain their
[separate attribution and terms](THIRD_PARTY_NOTICES.md). Every map pack carries the
credits of the data it was built from (`CREDITS.txt` beside its manifest, and the
manifest's `credits`), so a pack shared on its own still names its sources.
