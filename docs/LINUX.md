# EarthNG on Linux

The EarthNG mod itself is Lua and art inside ZIP files, so it runs in BeamNG.drive on Linux as it
does on Windows: in the native Linux client and in the Windows build under Steam Proton. What is
Windows-only is EarthNG.exe, the window that installs the planet and builds map packs. On Linux the
same builder ships as **EarthNG-linux-x86_64.tar.gz** and opens in your web browser.

## Install and play

1. Download **EarthNG-linux-x86_64.tar.gz** from the
   [release](https://github.com/Alezx311/earthng/releases/tag/v1.1.0) and unpack it anywhere:

   ```sh
   tar -xzf EarthNG-linux-x86_64.tar.gz -C ~
   ~/EarthNG/EarthNG
   ```

2. The Map Builder opens in your browser at `http://127.0.0.1:<port>/`. The terminal shows the
   address if no browser opens.
3. Search for a town, draw an area or choose a route, and press **Create the map**. The planet
   (bundled in the package) and your map are installed into the game's `mods` folder.
4. In BeamNG.drive open **Freeroam → EarthNG - Planet** and land inside your map.

The proving ground (`earthng_polygon.zip`) and other packs are copied into the same `mods` folder.

## Where things are

| What | Where |
| --- | --- |
| BeamNG user folder, native client | `~/.local/share/BeamNG/BeamNG.drive/current` ([BeamNG docs](https://documentation.beamng.com/support/userfolder/)) |
| BeamNG user folder, Steam Proton | `<Steam library>/steamapps/compatdata/284160/pfx/drive_c/users/steamuser/AppData/Local/BeamNG/BeamNG.drive/current` |
| Downloads, tiles, built packs, projects | `~/.local/share/EarthNG/data` |
| Logs (`app.log`, `service.log`), map tile cache | `~/.local/share/EarthNG/logs`, `~/.local/share/EarthNG/cache` |

The builder looks for the native client first, then for a Proton prefix in every Steam library
(`~/.steam/steam`, `~/.local/share/Steam`, the Flatpak Steam and the libraries listed in
`libraryfolders.vdf`). `$XDG_DATA_HOME` is honoured. If your user folder is elsewhere, choose it in
**Settings**. `EARTHNG_LOCAL` moves EarthNG's own folder.

## What is in the package

| Path | Contents |
| --- | --- |
| `EarthNG` | The launcher: starts `earthng/app_web.py` with the bundled Python |
| `python/` | CPython 3.13 ([python-build-standalone](https://github.com/astral-sh/python-build-standalone)) with numpy, shapely, pyproj, osmium and Pillow |
| `bin/` | `earthng-mapbuilder` and `libearthng_native.so`, the native build stages |
| `earthng/`, `app/ui/`, `mod/` | The same pipeline, page and planet code as EarthNG.exe |
| `earthng_planet.zip` | The planet of this version |

Nothing is installed system-wide and nothing else is needed: x86_64 Linux with glibc 2.28 or newer
(Ubuntu 20.04+, Debian 11+, Fedora, Arch, SteamOS) and a browser. The launcher points the bundled
Python at your distribution's CA certificates.

## Options

```sh
./EarthNG --help
./EarthNG --port 8080        # a fixed port instead of a free one
./EarthNG --no-browser       # print the address only
./EarthNG --stay             # keep running with no page open
```

The server listens on 127.0.0.1 only. It answers only the page it served: another site open in the
same browser cannot reach the builder (the session key, the Host check and the custom request
header). With no page open and no build running it stops after ten minutes; close the terminal or
press Ctrl+C to stop it at once. A build stops with it.

## Updating

Download the new package and unpack it over the old folder (or next to it). Your data stays in
`~/.local/share/EarthNG/data`. The in-app update of EarthNG.exe is Windows-only.

## For developers

- `earthng/app_web.py` stands in for `rust/crates/app`: it serves `app/ui`, proxies the OSM
  background tiles with a disk cache, hands the page's messages to `earthng/app_service.py`
  (POST `/ipc`) and streams the service's lines back as server-sent events (`/events`).
  `app/ui/web.js` gives the page the `window.ipc` that WebView2 gives it in the exe. It also runs on
  Windows from a checkout: `.venv\Scripts\python.exe earthng\app_web.py`.
- `earthng/prepare_linux.py` builds the package from a committed snapshot. The Linux parts
  (Rust tools, Python and wheels) are built in `quay.io/pypa/manylinux_2_28_x86_64`: through Docker
  on Windows, or with `--native` on a Linux host. `--test` also runs `cargo test` and the Python
  unit tests on Linux with the packaged interpreter. `--repack PACKAGE --planet ZIP` adds the
  planet to a package built without one.
- `.github/workflows/linux.yml` builds and tests the package on Linux (without the planet, whose
  art is not in Git), then unpacks it on a bare Ubuntu 20.04 and builds Monaco end to end through
  the HTTP page (`earthng/linux_smoke.py`). The release takes that artifact and adds the planet
  with `--repack`.
- Tests: `earthng/test_linux.py` (user folders on Linux and Proton, the server's guards, the
  tarball's modes and symlinks).
