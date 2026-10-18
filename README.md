# EarthNG

Drive through real places in BeamNG.drive. EarthNG builds roads, buildings and
terrain from OpenStreetMap and elevation data as you drive.

The game runs entirely in Lua with installed ZIP mods. Python is used only to
prepare country packs locally. No companion server or Earth2Road checkout is required.

## Install and play

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
Download or clone this repository, extract it to a writable folder, then open
**Country.bat**. On first use it runs **Setup.bat** to create `.venv` and install
the required packages. An internet connection is required for setup and new data.

In the country window:

1. Select your **BeamNG user folder** (the folder containing `mods`, not `mods` itself).
2. Search for a country or smaller Geofabrik region.
3. Choose **Install a ready pack** when available, or adjust the look/layers and
   choose **Build my own**. Roads and terrain are always included.
4. Wait for the `installed ...` message. The ZIP is also retained in
   `out/country-setup` for reuse or sharing.

The planet ZIP must also be installed. **Refresh planet code** updates code in an
existing planet ZIP; it does not create the base assets.

For a small test, choose Liechtenstein. Large countries can require many GB of
source data, temporary files and hours of processing. A custom bounding box limits
the exported area, but still downloads the selected region's complete PBF.
The Stop button cancels downloads/tile cutting; later steps finish the current
stage, then stop before installation. Keep the window open until the worker stops.

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

To rebuild the planet, extract the release's **earthng-developer-assets.zip** into
this checkout first. It supplies the separately distributed CC0 texture sources,
prebuilt distributable art and offline basemap. Then run `Rebuild.bat`, or:

```powershell
.venv\Scripts\python.exe earthng/build_mod.py --out out/mod --lang en
```

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
