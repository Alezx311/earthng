# Offline map and navigation

Search the widget by city, village, district or country name. Local, Ukrainian,
English and OSM alternate names are searchable. Exact matches come before prefixes
and partial matches. Use the arrow keys and Enter, or click a result. Escape or X
clears the search. Results identify places without an installed landing pack.
Country results frame the country; select a place to choose a landing point.

Scroll to zoom around the cursor, drag to pan, and use +/− for centered zoom.
The @ button returns to the car. The small widget follows the car again after this
button is pressed. The scale bar shows ground distances.

The widget windows (picker, landing, minimap, "Show map") stay in the game window:
`winguard.lua` keeps them off separate ImGui OS windows (BeamNG runs multi-viewports),
never lets them take focus on appearing and pulls one back whole when it is found
outside the screen (not while a mouse button is held, not while minimised).

Main roads use simplified overviews from zoom 5, secondary roads from zoom 9 and
tertiary roads from zoom 11. Existing block-derived streets supply closer detail.
Villages appear as you zoom in, with collision avoidance for labels. The stock
BeamNG minimap shows the generated drivable roads near the car, even with traffic
disabled; new roads are added as the world loads. This is road display, not a new
long-distance route planner.

## World map (M)

M (the game's own big-map binding, or the key itself) opens `worldmap.lua`: the whole planet
on one screen instead of the stock 3D big map, which shows only the loaded tiles. The game
pauses while it is open (a switch in the panel; a game the player paused stays paused).

- **Side panel.** Search (places of `labels.json`/`places.json` and named points of `pois.tsv`),
  "To the car", "Whole world", layers (points, where a landing works, the pause), the picked
  point's card and the point filters.
- **Filters.** Groups (car, transport, stay, shops and food, money, health, sights, nature,
  water, civic) with their colour and point count; `+` opens a group's categories, each with its
  own switch and count. With `poi_tags.tsv` the broad categories split into finer kinds told by
  their OSM tag (`poiindex.SUB`): fuel, EV charging, car wash, car repair, tyres, pharmacy, bank,
  post; cafe, restaurant, fast food, bar; museum, zoo, theme park, ruins; park, stadium, pool,
  cinema, theatre; bus stop and station. A fuel station stands before the other services.
- **Points on the map.** Below zoom 10 the points are dots in their group's colour (one per 9 px
  square, at most `MAX_DOTS` 1200): where things are. From zoom 10, icons (`pins.icon`, one per
  24 px square, at most `MAX_ICONS` 240), the best of a crowded square first (`pins.STYLE`
  priority, a castle before a kiosk); names beside them (at most 60) from zoom 15 or a category's
  `labelZoom`, before the place names. The squares are fixed to the world, not the screen. The
  points are collected only when the zoom or the filters change or the view leaves the collected
  box (the view and half of it again on each side), 2 ms a frame (`SLICE`) with the last points
  shown meanwhile; a frame only shifts and draws them (zoomed out over 1.08 M points: under
  3.5 ms a frame, a drag 0.1 ms).
- **Hover.** The point under the cursor gets a ring and a card: name, kind and pack, address,
  fuels, opening hours, phone, website, cuisine, operator, brand, wheelchair access, elevation,
  heritage, Wikipedia, the OSM kind (`amenity=fuel`) and `osm.org/node/<id>`, coordinates, the
  distance from the car. Without `poi_tags.tsv` the card says the facts come with updated data.
- **Click.** It only picks: a point, or a plain spot on the map. The card in the panel offers
  "Navigate here" (driving, within the current pack), "Land here" (where a pack covers it),
  "Show" and "Clear". A stray click never moves the car.
- **Keys.** Wheel and the +/− buttons zoom, drag pans, PageUp/PageDown zoom, C goes to the car,
  Esc clears the search, then shuts the map; M shuts it too, unless the search field has the keys.

Speed: `poiindex.lua` reads each catalog's `pois.tsv` (already kept for the search) into ffi
arrays a slice a frame (3 ms of `os.clock`), with no per-line strings for coordinates, then
sorts the points into 0.05° cells best first. Ukraine's 290 k points index in a few seconds on
the first opening; afterwards a frame only walks the cells in view and takes the best enabled
points of each, and only when the view or a filter changes. Names and facts are read from the
kept text for the drawn and hovered points only; dots reuse one ImVec2.

`poi_tags.tsv` (`build_map.py` GENERATION 3) holds, line for line with `pois.tsv`, the OSM id and
the `POI_DETAILS` tags (`key=value`, tab-separated, whitespace collapsed, values cut at 160
characters, no e-mail). `pois.tsv` keeps its six columns, so an older runtime reads a new sidecar.
An older sidecar without the file still gives the points, the filters by broad category and the
names. A sidecar gains the facts on its next build; the GENERATION bump makes `country_fetch`
choose a new cache directory.

## Data compatibility

The planet (0.8.x) carries detailed OSM sidecars for **Ukraine, Albania and Estonia**.
Other older packs retain Natural Earth city/country labels and their existing local
streets until a sidecar is built. Packs built by EarthNG.exe or `country_fetch.py`,
and spot exports, include a sidecar when their original PBF is available (an
Overpass-only area has its own small PBF, which `build_map.py` reads too). With the
Rust tools built, the PBF is read natively (`earthng-mapbuilder map-source`, see
[MAPBUILDER_RS.md](MAPBUILDER_RS.md)). The runtime stays fully offline.

Generate map detail independently of world geometry:

```powershell
.venv\Scripts\python.exe earthng/build_map.py --pbf data/pbf/albania.osm.pbf --out out/map-data/albania
.venv\Scripts\python.exe earthng/build_mod.py --out out/mod --lang uk
```

The output directory name must be the installed country's manifest ID. A matching
source fingerprint reuses completed output. For a changed source use a fresh
output directory. Planet builds embed completed `out/map-data/<id>/` directories.
Country builds can supply `map_data=` to `build_country`; spot and EarthNG.exe
pipelines do this automatically. Code-only planet refresh does not create data.

Country sidecars live under `earthng/countries/<id>/map/`; planet fallback sidecars
live under `earthng/planet/maps/<id>/`. Each has `index.json`, `places.json` and
road tiles. Only mounted, available countries contribute their sidecars. The country's
own sidecar takes priority over the planet fallback, unless the planet's is of a newer
generation (its `sourceStamp[0]`, `build_map.py` GENERATION): then an older pack gains
the points and their facts from the planet without a rebuild. OSM data remains ODbL,
credited in the map and index; there are no BeamNG assets in these files.

Tests: `test_map_data.py` covers PBF extraction, villages, aliases, country search,
cache/language/limit changes, overview zooms, unmounted packs and `poi_tags.tsv` line for
line. `test_widget.py` also checks streaming while the map is open and minimap graph updates
with no traffic. `test_world_map.py` covers the point index (slices, a broken line, finer kinds,
mismatched facts, a crowded cell), the card, markers, filters, hover, click, Esc and the pause.
