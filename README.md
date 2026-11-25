# EarthNG

Drive through real places in BeamNG.drive. EarthNG builds roads, buildings and
terrain from OpenStreetMap and elevation data as you drive.

The game runs entirely in Lua with installed ZIP mods. Map packs are prepared
beforehand, either downloaded ready-made or built with EarthNG.exe. No companion
server is required.

What is generated on the road: roads with junctions, bridges with railings, raised
sidewalks with kerbs and lane markings; buildings with roofs, windows and shop fronts;
trees, grass and ground cover by climate; street furniture, signs and traffic lights
that change. Optional traffic flow: hundreds of cars without physics queue at junctions
and lights, and the nearest ones turn into real cars of the same body and paint that
you can hit. A line at the top shows the street, town and region, and the map can
route you to a marker.

## Install and play

1. Download and open **EarthNG.exe** from the [player release](https://github.com/Alezx311/earthng/releases/tag/v1.1.0).
2. Search for a city such as Miami and press Enter, draw a rectangle, or choose a route.
   Press **Create the map**. The builder installs the planet and the selected area.
3. Open **Freeroam → EarthNG - Planet** in BeamNG.drive. Pick a point inside the
   installed coverage and land there.

EarthNG 1.1 includes the planet inside **EarthNG.exe**. Try generating a map of any
place on Earth: your hometown, a favourite road, or somewhere you have always wanted
to drive. Existing country packs can also be used alongside the installed planet.

**Proving ground.** The release also has **earthng_polygon.zip**: a made-up island at
Point Nemo where every 500 m tile shows one theme (road classes, ground covers,
buildings, relief), ringed by mountains, desert, snow, mud and jungle, a block of
bridges and tunnels, and Supporters' Alley. Copy it into your `mods` folder next to the
1.1 planet, restart the game and land on the island (48.89° S, 123.36° W). The pause
menu's EarthNG tab has a generator lab for the whole world or a single tile.

**Flora pack.** **earthng_flora.zip** in the same release puts real species in place of the
stock trees: 106 models made with [FoliMesh](https://folimesh.com), by natural zone. Copy it into
`mods` next to the 1.1 planet. See [flora](docs/FLORA.md).

The atlas on **M** and the landing picker search cities, villages, countries and points
of interest in local, Ukrainian and English names. Use Enter or click a result, scroll to
zoom smoothly and drag to pan. Roads show at every zoom, points of interest are round
markers with pictograms, and packs carry Sentinel-2 imagery of their area. While driving
there is no EarthNG window on the screen: BeamNG's own minimap is widened (three times by
default) and shows the points of interest round the car. Village, road and imagery detail
depends on the data in the planet and installed packs. See
[map controls and data](docs/MAP.md).

**Place your own objects.** In an EarthNG world open the World Editor (F11), place
stock meshes from the Asset Browser, move, rotate, scale, duplicate or delete them as
usual, and press **Ctrl+S**: EarthNG keeps them at once, without a restart, for every
landing and the next game start (`settings/earthng-editor-objects.json` in your user
folder). Generated streets, buildings and trees are not saved. See
[World Editor objects](docs/WORLD_EDITOR.md).

**Pedestrians and street props.** In the pause menu's EarthNG tab, **Pedestrians** (0 to 1000)
puts people on the sidewalks; a car that hits one meets a physical body in its place.
**Knockable props** (on by default) lets bins, bollards and benches be knocked over.
See [crowds](docs/CROWDS_AND_PACKS.md) and [knockdown](docs/KNOCKDOWN.md).

Use BeamNG's launcher to find your user folder; custom locations are supported.
Restart the game after replacing a ZIP. Remove the old companion-era
`earth2road_world.zip` if it is installed. Old all-in-one Python packages cannot
be used as native country packs.

Release files belong in [GitHub Releases](https://github.com/Alezx311/earthng/releases),
not in Git. See [release verification](docs/RELEASE_CHECK.md) for the tested build
and performance limits. OSM completeness,
terrain detail and performance vary between places.

## Linux

The mod runs in BeamNG.drive's native Linux client and in the Windows build under Steam
Proton. The map builder for Linux is
**[EarthNG-linux-x86_64.tar.gz](https://github.com/Alezx311/earthng/releases/download/v1.1.0/EarthNG-linux-x86_64.tar.gz)**:
unpack it and run `./EarthNG`. It opens the same Map Builder in your browser, finds the game's
user folder (`~/.local/share/BeamNG/BeamNG.drive/current` or the Proton prefix) and needs nothing
installed: Python, the build tools and the planet are inside. See [EarthNG on Linux](docs/LINUX.md).

## Build your own map (Windows)

Download **[EarthNG.exe](https://github.com/Alezx311/earthng/releases/download/v1.1.0/EarthNG.exe)**
and run it. It needs nothing else: Python and the build tools are inside, unpacked
once to `%LOCALAPPDATA%\EarthNG\runtime`. Downloaded data and built packs live in
`%LOCALAPPDATA%\EarthNG\data`. The window uses Microsoft Edge WebView2, which
Windows 10 and 11 already have.

1. The top of the window shows whether BeamNG's user folder was found (choose it in
   Settings if not) and whether the EarthNG mod is installed.
2. **Choose an area.** Search for a town or address and press Enter, select a whole
   region, or draw a rectangle. For a road trip, mark the waypoints in order or
   import a GPX track or GeoJSON LineString. Choose **1, 10 or 100 km on each side**.
   Follow the bends of your intended drive when placing waypoints.
3. Press **Create the map**. If `earthng_planet.zip` is missing or older than the
   packs need, it is installed from the bundled planet first. Look, layers and
   project options are folded under the button.
4. Watch the stages. When it says **The map is installed**, start BeamNG.drive and
   open **Freeroam → EarthNG - Planet**.

The builder can fetch small selections from Overpass and uses regional Geofabrik
extracts for larger areas. Check the source list before a long build. A route
crossing several regions can require several downloads. The builder keeps source
files and completed tiles for later selections. Large countries can take many GB
and hours of processing.

Save a frequently driven area as a project. When a major release adds map data,
reopen the project and build it again. To extend your coverage, build an adjacent
area or another route. EarthNG loads the installed sections together.

**Updating.** EarthNG.exe checks the player release when it opens. If a newer build is
published, choose **Update** in the window. That replaces `EarthNG.exe` and opens the
window again. Maps you already built, downloaded country files and the mods in BeamNG
stay where they are: this is not a clean reinstall, and you do not remove the old
program first. The game mod still updates with the next map when the installed planet
is older than the one the new program expects. Publish `EarthNG.json` from the release
folder next to `EarthNG.exe`; the window reads it to know the version and the file hash.

Console equivalent (also useful for Linux/macOS with a local Python environment):

```powershell
.venv\Scripts\python.exe earthng/country_fetch.py build --place liechtenstein --mods "D:\BeamNG\current" --jobs 2
.venv\Scripts\python.exe earthng/country_fetch.py build --box -80.32 25.68 -80.10 25.87 --mods "D:\BeamNG\current"
.venv\Scripts\python.exe earthng/country_fetch.py build --route drive.geojson --width-km 10 --mods "D:\BeamNG\current"
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

The repository has three parts: the planet's Lua and art (`mod/`, built by
`earthng/build_mod.py`), the Python pack builder (`earthng/`) with native Rust
copies of its heavy stages (`rust/`), and EarthNG.exe (`rust/crates/app`, the page in
`app/ui`, the service `earthng/app_service.py`). Documents are listed in
[docs/README.md](docs/README.md).

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s earthng -p "test_*.py"
```

The native tools need [Rust](https://rustup.rs). Without them every stage runs in
Python (slower, same output); `EARTHNG_NATIVE=0` forces that.

```powershell
cd rust
cargo build --release
cargo test --release
```

`rust\target\release\EarthNG.exe` started from the checkout uses `.venv`, the code in
`earthng/` and the page in `app/ui` on disk, so page edits need no rebuild. A
standalone EarthNG.exe with the embedded Python is built by
`.venv\Scripts\python.exe earthng/prepare_app.py --out out/app` from committed source.
How the exe and the native stages work: [EarthNG.exe](docs/MAPBUILDER_APP.md),
[native builder](docs/MAPBUILDER_RS.md).

To rebuild the planet, extract **earthng-developer-assets.zip** from the separate
[developer resources](https://github.com/Alezx311/earthng/releases/tag/developer-assets-0.4.0) into
this checkout first. It supplies the separately distributed CC0 texture sources,
prebuilt distributable art and offline basemap. Then run `Rebuild.bat`, or:

```powershell
.venv\Scripts\python.exe earthng/build_mod.py --out out/mod --lang en
```

Stage player downloads from committed source (excluding local uncommitted work):

```powershell
.venv\Scripts\python.exe earthng/prepare_release.py --out out/release/player --planet out/mod/earthng_planet.zip
```

Use an empty output directory. The script copies the native mod and any selected
country pack, builds EarthNG.exe from the committed source, writes `EarthNG.json`
(version, size and sha256 of that exe, for the in-app update) and prints SHA-256 sums
for the release description. Upload `EarthNG.json` with `EarthNG.exe`. The exe's runtime follows local Python imports,
includes runtime resources and embeds a ready-pack catalog. Developer assets, tests and research notes are not player downloads.

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
