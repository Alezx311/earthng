# Offline map and navigation

While driving, the horizontal compass at the top follows the camera heading. It shows
cardinal directions and named landmarks within 5 km, including sights, stations,
large shopping centres and hospitals. Nearby points use the installed offline map
catalog. Gold marks your chosen map destination and its straight-line distance.
When the destination is behind the camera, an arrow at the edge keeps it visible.
The location and navigation text appears below the compass.

The landing picker and atlas have the same place browser. Select an installed
pack to browse its starting points and settlements. Use the category selector
to find places such as sights, fuel and transport. With an empty query, these
categories list places within about 25 km of the map centre or the selected
pack's start. Use **Refresh nearby places** after moving the map. Listings of
settlements and points of interest use the installed pack's map data. Packs
with only a landing point still show their start.

Search by a local, Ukrainian, English or OSM alternate name. Use the arrow keys
and Enter or choose a result with the mouse. Escape and × clear the search.
The atlas opens the place card. The landing picker sets the landing marker.

Scroll to zoom around the cursor, drag to pan, and use +/− for centered zoom.
The @ button returns to the car. The small widget follows the car again after this
button is pressed. Resize the driving widget by dragging its corner. The centre
and ground scale stay fixed as more streets come into view.

**Map imagery** in the atlas switches the background for the driving widget,
picker and full map. The planet includes a global NASA Blue Marble overview
and local imagery around Kyiv and San Francisco, including a higher-resolution
NAIP sheet at Russian Hill. Other areas use the offline cartographic base at
street scale. Hover over **© Sources** on a narrow map for attribution.

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

- **Side panel.** **Places** contains the pack and category selectors, search and
  lists. **Place card** keeps the selected place and its actions. **Layers** holds
  map imagery, landing coverage, pause and detailed marker filters.
- **Filters.** Groups (car, transport, stay, shops and food, money, health, sights, nature,
  water, civic) with their colour and point count; `+` opens a group's categories, each with its
  own switch and count. With `poi_tags.tsv` the broad categories split into finer kinds told by
  their OSM tag (`poiindex.SUB`): fuel, EV charging, car wash, car repair, tyres, pharmacy, bank,
  post; cafe, restaurant, fast food, bar; museum, zoo, theme park, ruins; park, stadium, pool,
  cinema, theatre; bus stop and station. A fuel station stands before the other services.
- **Points on the map.** At zooms 6–14, coloured dots show nearby points of interest.
  At zoom 15 and above, pictograms distinguish services and sights. The highest-priority
  point in each geographic grid cell gets the first available space. Settlement names,
  the vehicle and map controls have priority over icons and venue names.
- **Hover.** Hovering identifies a point by name and category. Selecting it opens
  the available OSM facts, coordinates and distance from the car in the side panel.
- **Field guide.** Open **Find a place** from the minimap or press **M**. Select the
  **Field guide** category with all packs selected, click a teal map label, or search for its Ukrainian or English
  title. Each article includes a description and a source you can copy. To contribute
  an entry, add a record to `mod/earthng/planet/guide.json`. Give it a unique stable
  `id`, coordinates, `minZoom`, Ukrainian and English `title`, `area` and `summary`,
  and a `source` name and `url`. The planet build includes the catalog automatically.
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

The planet carries detailed OSM sidecars for selected countries.
Other older packs retain Natural Earth city/country labels and their existing local
streets until a sidecar is built. Packs built by EarthNG.exe or `country_fetch.py`,
and spot exports, include a sidecar when their original PBF is available (an
Overpass-only area has its own small PBF, which `build_map.py` reads too). With the
Rust tools built, the PBF is read natively (`earthng-mapbuilder map-source`, see
[MAPBUILDER_RS.md](MAPBUILDER_RS.md)). The runtime stays fully offline.

Generate map detail independently of world geometry:

```powershell
.venv\Scripts\python.exe earthng/build_map.py --pbf data/pbf/ukraine.osm.pbf --out out/map-data/ukraine
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
