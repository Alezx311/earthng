# EarthNG

Drive through real places in BeamNG.drive. EarthNG builds roads, buildings and
terrain from OpenStreetMap and elevation data as you drive.

The game runs entirely in Lua with installed ZIP mods. Python is used only to
prepare country packs locally. No companion server or Earth2Road checkout is required.

## Install and play

The [player release](https://github.com/Alezx311/earthng/releases/tag/EarthNG)
has three downloads:

| Download | Purpose |
| --- | --- |
| **earthng_planet.zip** (~87 MB) | Required native mod. Put in BeamNG's `mods` folder, keep packed. |
| **earthng_albania.zip** (~226 MB) | Ready Albania demo map. Put beside the planet ZIP, keep packed. |
| **EarthNG-MapBuilder.zip** (~300 KB) | Optional tool for making other maps. Extract to a separate writable folder and run **MapBuilder.bat**. |

**To play the demo, download only the first two files. Python is not required.**

1. Install **earthng_planet.zip** and at least one **earthng_<country>.zip** in the
   `mods` directory of your BeamNG user folder. Keep the ZIPs packed.
2. Start BeamNG.drive and open **Freeroam → EarthNG - Planet**.
3. Pick a point inside an installed country's coverage and land there.

Use BeamNG's launcher to find your user folder; custom locations are supported.
Restart the game after replacing a ZIP. Remove the old companion-era
`earth2road_world.zip` if it is installed. Old all-in-one Python packages cannot
be used as native country packs.

Release files belong in [GitHub Releases](https://github.com/Alezx311/earthng/releases),
not in Git. See [release verification](docs/RELEASE_CHECK.md) for the tested build
and performance limits. This is an experimental first release: OSM completeness,
terrain detail and performance vary between places.

## Build your own country (Windows)

Install **Python 3.13** from python.org, including the Python launcher and Tcl/Tk.
Download **[EarthNG-MapBuilder.zip](https://github.com/Alezx311/earthng/releases/download/EarthNG/EarthNG-MapBuilder.zip)**,
extract the entire archive to a writable folder, then open **MapBuilder.bat**.
You can also clone this repository (Country.bat starts the same window). On first use it runs
**Setup.bat** to create `.venv` and install the required packages. An internet
connection is required for setup and new data.

In the country window:

1. Select your **BeamNG user folder** (the folder containing `mods`, not `mods` itself).
2. Search for a country or smaller Geofabrik region, or use **Select area** and drag
   a rectangle on the map. The smallest available extract covering the entire
   selection is chosen automatically. Scroll to zoom, use **Move map** to pan,
   or type in **Find city** (English or Ukrainian) and press Enter. **Use whole
   region** clears the rectangle; coordinates remain available in the second tab.
3. Check **Look & preview**, then choose **Install a ready pack** when available, or adjust the look/layers and
   choose **Build my own**. Roads and terrain are always included.
4. Watch the current stage, elapsed time and approximate remaining time. Wait for
   the `installed ...` message. The ZIP is also retained in
   `out/country-setup` for reuse or sharing.

Map Builder reuses the offline Natural Earth map from `out/basemap/3` or the
installed planet ZIP, with a coastline fallback. It is a regional map, without
street-level detail. City search requires the offline map's labels. Extract
boundaries are downloaded once from Geofabrik and cached; selecting a source
from the list still works if that download is unavailable.

The preview is an illustrative 2D street using the selected materials from the
installed planet, local developer assets, and game textures. Trees and props are
schematic; missing textures are explicitly marked as fallback colours. It is not
a BeamNG render: lighting, actual buildings, OSM tags and the in-game style can
change the final appearance.

Build estimates are broad planning ranges, not a completion guarantee. They
account for source size, selected area, layers and cached source tiles. Successful
stage timings are saved locally in `out/country-setup/build-times.json` and reused
for the same selection, layers and source-cache state. Network speed, terrain
cache, hardware and OSM density can change the duration.

The planet ZIP must also be installed. **Refresh planet code** updates code in an
existing planet ZIP; it does not create the base assets.

For a small test, choose Liechtenstein. Large countries can require many GB of
source data, temporary files and hours of processing. A custom bounding box limits
the exported area, but still downloads and scans the selected region's complete PBF
on the first build. Rebuilding an area with completed source tiles skips the PBF
download and scan entirely; it uses that cached OSM snapshot. To deliberately
update OSM data, use a fresh source-tile cache for that region under `data/osm_tiles`.
The Stop button cancels the build before the pack is installed. Tile cutting stops
at once. A download, the region index and the export stop at the next chunk, region
or block. Closing the window requests cancellation and waits for the worker to stop.
Settings are locked while a job runs. Elevation downloads use a bounded queue of
eight workers, with cancellable retry delays; network requests already in flight
may still need to finish or time out.

Console equivalent (also useful for Linux/macOS with a local Python environment):

```powershell
.venv\Scripts\python.exe earthng/country_fetch.py build --place liechtenstein --mods "D:\BeamNG\current" --jobs 2
```

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
[separate attribution and terms](THIRD_PARTY_NOTICES.md).
