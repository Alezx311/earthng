# Промпт для дизайну вікна MapBuilder

Для Figma Make (або іншого генератора макетів). Англійською, бо так генератори точніші; інтерфейс
двомовний, тож довжину рядків варто перевірити й українською.

---

Design a desktop app window for **EarthNG Map Builder**, a companion app for the BeamNG.drive mod
EarthNG. EarthNG generates drivable real-world roads, buildings, trees and terrain around the
player's car on the fly from "map packs". Map Builder lets a player get packs for the area they
want, keep them up to date, see community edits, and build a custom pack from open data.

**Platform and frame**
- Windows 11 desktop app, single window, 1440x900 default, must work down to 1100x700.
- Light and dark themes. Calm, technical, map-first; think of a modern game launcher crossed with
  a GIS tool. No marketing hero images. Dense but readable, 13-14 px UI text.
- Every label must fit both English and Ukrainian (Ukrainian runs ~25 % longer).

**Layout**
- Left: narrow icon rail with sections Map, Library, Edits, Build, Settings.
- Centre: a full-height interactive world map (vector basemap). This is the main surface.
- Right: a 360 px contextual panel that changes with the selection.
- Bottom: a thin status bar: BeamNG folder found (version 0.39 / 0.40), planet mod version and
  whether it matches, "BeamNG is running" warning, disk free, active task with progress.

**Map surface**
- Coverage overlay as a grid of regions (rectangles about 1.5 by 1 degree) with four states:
  installed, update available, available to download, not available yet (can be built).
- Inside a selected region, smaller square blocks (8 by 8 km) are shown when zoomed in.
- Optional heat overlay: how many community edits each block has.
- Search box at the top of the map: city, address or coordinates. Selecting a result flies to it.
- Selection tools: click a region, shift-click to add, or drag a rectangle/lasso for a custom area.
- Legend chip in a corner; layer toggles (coverage, edits, my builds).

**Right panel states**
1. *Nothing selected*: short onboarding: "Pick a place on the map", recent places, installed packs.
2. *Region selected*: name, country, size on disk, OSM data date, pack version, what changed since
   the installed version, buttons "Install" / "Update (+12 MB)" / "Remove", and "Drive here"
   (copies a spawn point for the game).
3. *Custom area selected*: area in km2, estimated build time (seconds to minutes), download size,
   disk and memory needed, list of data sources with toggles and their licences (OpenStreetMap,
   Copernicus DEM, ESA WorldCover, Overture buildings, national lidar where available), layer
   toggles (buildings, trees, street furniture, signs, rail, water), button "Build pack".
4. *Building*: a live pipeline view, one row per stage (Fetch sources, Cut, Terrain, Roads,
   Buildings, Nature, Pack, Install), each with its own progress bar, throughput and time; sources
   download in parallel so several rows move at once. The map shows blocks turning from grey to
   done as they finish. Stop and Resume buttons. Builds of a city should feel like 1-2 minutes.
5. *Edits for a block*: list of edit sets touching this area (author, date, votes, "official" badge),
   toggle each on or off, a before/after slider on a 2D preview, and two actions: "Fix the data in
   OpenStreetMap" (opens the OSM editor at this spot) and "Edit in game".

**Other screens**
- *Library*: table/cards of installed packs and edit sets: size, version, last update, update all,
  remove, open folder.
- *Edits*: browse and subscribe to community edit sets (like mods), my own edits waiting to sync,
  sign-in state for publishing.
- *Settings*: BeamNG user folder (auto-detected, can browse), cache folder and its size with a
  cleanup button, language (English / Українська), theme, download speed limit, CPU and memory
  limits for builds.

**States to show as separate frames**
- First launch with BeamNG folder not found.
- Planet mod outdated (blocking banner with "Update planet").
- BeamNG running: installs are queued until the game is closed.
- Offline: map tiles cached, downloads paused, local builds still possible.
- Error in one build stage with a readable message and "Copy log".

Deliver: the main window in light and dark, all five right-panel states, Library, Edits, Settings,
and the special states above. Use a small component set (buttons, toggles, chips, progress rows,
region popover) so it can be rebuilt in a web UI (Tauri + MapLibre).
