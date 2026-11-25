# Offline map and navigation

While driving, EarthNG puts no window of its own on the screen. The horizontal compass at
the top follows the camera heading. It shows cardinal directions and named landmarks
within 5 km, including sights, stations, large shopping centres and hospitals. Nearby
points use the installed offline map catalog. Gold marks your chosen map destination and
its straight-line distance. When the destination is behind the camera, an arrow at the
edge keeps it visible. The location and navigation text appears below the compass.

The map itself is in two places: the game's own minimap in the corner of the screen,
which EarthNG widens and fills with points of interest, and the atlas on **M**. Settings
are in the **EarthNG** tab of the pause menu.

## The game's minimap

The stock minimap shows about 200 m across at rest and 350 m at speed. On an EarthNG
level it shows three times as much by default. **Minimap range** in the pause menu's
EarthNG tab sets it: as the game, ×2, ×3 or ×5. The game's own easing by speed stays,
and a road keeps a readable width however far the minimap sees.

Points of interest round the car are drawn as round markers in the colour of their
group (blue for the driver's services, brown for sights, red for transport and so on),
larger for the weightier ones. They come from the installed packs' map data, so they
show before the place itself is built, and from the tiles already streamed round the car
(a pack built before its map data carried points has only these). A category switched
off on the atlas leaves the minimap as well. The destination of a route is the blue marker; at the edge it becomes
a pointer.

`minimap.lua` does this without replacing a file of the game: it wraps the scale the
minimap asks its vehicles module for and the scale its roads module draws with, and
draws the markers through the minimap's `onDrawOnMinimap` hook. The wraps are put back
when the level is left.

## The landing picker

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

## Moving the map

The zoom is continuous. A notch of the wheel is one level, eased over a quarter of a
second round the point under the cursor; the +/− buttons and PageUp/PageDown zoom round
the centre. Drag to pan; a map let go while it moves glides on and slows down. Choosing a
search result, **To the car** and **Show** fly the view to the place (a place many
screens away is a jump). The @ button returns to the car.

Between two whole zoom levels the map is the nearer level stretched (`mapmotion.lua`):
tiles, roads, names and markers are prepared once per level, so a zoom on its way costs
no more than a still map.

## Roads

Roads show at every zoom from 5:

- **Zoom 5–10**: the pack's overview tiles (main roads from 5, secondary from 9), drawn
  with a dark rim so the lines read on the chart and on a photograph.
- **Zoom 11 and closer**: motorways to tertiary roads as strokes by class, with casings.
- **Zoom 11.5 and closer**: tertiary roads.
- **Zoom 13.2 and closer**: the streets of the pack's blocks under the view; service
  roads and tracks from 15.5.
- **Zoom 14.5 and closer**: the blocks' own lines for every class, once decoded. They
  are exact; the overview lines are simplified by about 11 m.

A road tile is read as text and taken apart a slice a frame, so panning does not
stall on a megabyte of JSON. A frame sends at most `maproads.BUDGET` points to the
engine. The classes take the budget in the order of their weight, and within a class the
long lines before the short ones: a spent budget leaves out the shortest streets all over
the view, never a motorway. A view with more road than the budget is drawn with fewer
bends from the next frame on, not with holes.

Walking the lines cost more than the engine's calls, so a line keeps its thinned points for
the level and the coarseness it was last drawn at, each set of lines has a grid of 1.5 km
cells, and a frame whose view has not moved sends the last frame's points again. While
the atlas is open the 3D world behind it is not rendered. Over central Kyiv at zoom 14 the
frame is about 13.5 ms still and 18 ms while the map moves.

## Map imagery

**Map imagery** in the atlas's Layers switches the background for the picker and the
atlas. The planet includes only a global NASA Blue Marble overview (17 sheets, down to
zoom 6). A pack carries Sentinel-2 imagery of its own area (ESA
WorldCover 2021 composite, CC BY 4.0) as a pyramid: the finest level the sheet budget
allows (a town at 10 m a pixel, Kyiv oblast at 24 m, Ukraine at about 100 m) over
coarser levels for wide views. The coarser levels are composed from the finest, and the
sheets are lifted for a map: brighter (gamma 0.7, gain 1.15) and a little more saturated
than the raw composite, which reads dark on a screen. Zoomed in past a
level's detail the photograph fades towards the chart, so streets and names stay
legible; over a photograph names are white with a dark halo. Other areas use the
offline cartographic base. Hover
over **© Sources** on a narrow map for attribution.

A pack built before 24.11.2026 has one coarse level or none. It gets the imagery
without a rebuild, as a second ZIP to put into `mods` beside it:

```powershell
.venv\Scripts\python.exe earthng/build_area_photos.py --pack earthng_ukraine.zip --out out/photos
```

`--plan` only prints the levels and their sheet counts. Sheets are fetched once into
`data/map-imagery` and reused, one request at a time with a pause (the imagery service
answers HTTP 429 to a crowd and is retried after its `Retry-After`). Only the builder
uses the network; the game stays offline.

## Markers

A point of interest is a round badge in its group's colour with a white rim and its
pictogram: the same drawings as on the plaques and info stands in the world, and the
driver's own (fuel pump, P, bed, cup, cash, WC). `earthng/map_icons.py` draws them into
`mod/earthng/planet/map_icons.png` and writes `map_icons.lua`, which names the mark of
each category. Run it after changing a mark or a category; a test compares.

- **Zoom 6–12**: the weightiest points of the zoom are badges (castles, airfields and
  stations first, fuel and hospitals from zoom 9), the rest ringed dots.
- **Zoom 13 and closer**: every point kept is a badge; names appear beside them from
  zoom 15, earlier for sights.

The highest-priority point in each geographic grid cell gets the first available
space; the streamed tiles' points keep 60 px apart, at most 160 on the screen. Settlement names, the vehicle and map controls have priority over markers and
venue names.

## World map (M)

M (the game's own big-map binding, or the key itself) opens `worldmap.lua`: the whole planet
on one screen instead of the stock 3D big map, which shows only the loaded tiles. The game
pauses while it is open (a switch in the panel; a game the player paused stays paused).

- **Side panel.** **Places** contains the pack and category selectors, search and
  lists. **Place card** keeps the selected place and its actions. **Layers** holds
  map imagery, landing coverage, pause and detailed marker filters. While a route is
  followed its distance and next turn stand at the top with **Cancel the route**.
- **Filters.** Groups (car, transport, stay, shops and food, money, health, sights, nature,
  water, civic) with their colour and point count; `+` opens a group's categories, each with its
  own switch and count. With `poi_tags.tsv` the broad categories split into finer kinds told by
  their OSM tag (`poiindex.SUB`): fuel, EV charging, car wash, car repair, tyres, pharmacy, bank,
  post; cafe, restaurant, fast food, bar; museum, zoo, theme park, ruins; park, stadium, pool,
  cinema, theatre; bus stop and station. A fuel station stands before the other services.
- **Hover.** Hovering identifies a point by name and category. Selecting it opens
  the available OSM facts, coordinates and distance from the car in the side panel.
- **Field guide.** Press **M**. Select the **Field guide** category with all packs
  selected, click a teal map label, or search for its Ukrainian or English
  title. Each article includes a description and a source you can copy. To contribute
  an entry, add a record to `guide.json` in the country or section pack root. Give it a unique stable
  `id`, coordinates, `minZoom`, Ukrainian and English `title`, `area` and `summary`,
  and a `source` name and `url`. The game reads the catalog while its regional pack is mounted.
- **Click.** It only picks: a point, or a plain spot on the map. The card in the panel offers
  "Navigate here" (driving, within the current pack), "Land here" (where a pack covers it),
  "Show" and "Clear". A stray click never moves the car. To land somewhere else while
  driving, pick the place here and press "Land here".
- **Keys.** Wheel and the +/− buttons zoom, drag pans, PageUp/PageDown zoom, C goes to the car,
  Esc clears the search, then shuts the map; M shuts it too, unless the search field has the keys.

Speed: `poiindex.lua` reads each catalog's `pois.tsv` (already kept for the search) into ffi
arrays a slice a frame (3 ms of `os.clock`; 1.2 ms while driving, for the minimap), with no
per-line strings for coordinates, then sorts the points into 0.05° cells best first. Ukraine's
290 k points index in a few seconds; afterwards a frame only walks the cells in view and takes
the best enabled points of each, and only when the whole zoom level, the view's box or a filter
changes. Names and facts are read from the kept text for the drawn and hovered points only.

`poi_tags.tsv` (`build_map.py` GENERATION 3) holds, line for line with `pois.tsv`, the OSM id and
the `POI_DETAILS` tags (`key=value`, tab-separated, whitespace collapsed, values cut at 160
characters, no e-mail). `pois.tsv` keeps its six columns, so an older runtime reads a new sidecar.
An older sidecar without the file still gives the points, the filters by broad category and the
names. A sidecar gains the facts on its next build; the GENERATION bump makes `country_fetch`
choose a new cache directory.

## Windows

The picker, the landing progress and "Show map" stay in the game window:
`winguard.lua` keeps them off separate ImGui OS windows (BeamNG runs multi-viewports),
never lets them take focus on appearing and pulls one back whole when it is found
outside the screen (not while a mouse button is held, not while minimised). While driving
there is no window of ours. A line low on the screen appears only when it has something to
say: the edge of a downloaded area, or the world under the car still being built.

Villages appear as you zoom in, with collision avoidance for labels. The route shown
is the navigator's own (`navigator.lua`); the minimap draws the part ahead that the
navigator hands to the game.

## Data compatibility

The planet carries no regional OSM sidecars: map detail comes from the installed packs.
Older packs retain Natural Earth city/country labels and their existing local
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
output directory. Planet builds never embed regional map caches.
Country builds can supply `map_data=` to `build_country`; spot and EarthNG.exe
pipelines do this automatically. Code-only planet refresh does not create data.

Country sidecars live under `earthng/countries/<id>/map/`; standalone sections use
`earthng/countries/<id>/sections/<section>/map/`. Each has `index.json`, `places.json`,
points and road tiles. A section gets a local subset of the reusable source map.
Only mounted, available packs contribute their sidecars. The planet has no regional
fallback: rebuild older packs to add missing map data. OSM data remains ODbL,
credited in the map and index; there are no BeamNG assets in these files.

Tests: `test_map_data.py` covers PBF extraction, villages, aliases, country search,
cache/language/limit changes, unmounted packs and `poi_tags.tsv` line for line.
`test_map_view.py` covers the map's motion (the eased zoom round the cursor, a thrown
map, flights), the roads (a tile taken apart in slices, classes, the budget, lines off
the view, the coarsening, a still view sent again, the grid, overview tiles stretched
with their rim), the markers' atlas and the game's minimap (its wraps, the markers by
weight and filter, the streamed tiles' points). `test_widget.py` covers the
picker, the atlas's map, streamed pins as badges and what stands on the screen while
driving. `test_world_map.py` covers the point index (slices, a broken line, finer kinds,
mismatched facts, a crowded cell), the card, markers, filters, hover, click, Esc and the
pause. `test_area_photos.py` covers the imagery pyramid and the ZIP for an installed pack.
