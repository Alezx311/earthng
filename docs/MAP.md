# Offline map and navigation

Search the widget by city, village, district or country name. Local, Ukrainian,
English and OSM alternate names are searchable. Exact matches come before prefixes
and partial matches. Use the arrow keys and Enter, or click a result. Escape or X
clears the search. Results identify places without an installed landing pack.
Country results frame the country; select a place to choose a landing point.

Scroll to zoom around the cursor, drag to pan, and use +/− for centered zoom.
The @ button returns to the car. The small widget follows the car again after this
button is pressed. The scale bar shows ground distances.

Main roads use simplified overviews from zoom 5, secondary roads from zoom 9 and
tertiary roads from zoom 11. Existing block-derived streets supply closer detail.
Villages appear as you zoom in, with collision avoidance for labels. The stock
BeamNG minimap shows the generated drivable roads near the car, even with traffic
disabled; new roads are added as the world loads. This is road display, not a new
long-distance route planner.

## Data compatibility

The map update includes detailed OSM sidecars for **Ukraine and Albania**. Other
older packs retain Natural Earth city/country labels and their existing local
streets until a sidecar is built. New Map Builder and spot exports include a
sidecar when their original PBF is available. The runtime stays fully offline.

Generate map detail independently of world geometry:

```powershell
.venv\Scripts\python.exe earthng/build_map.py --pbf data/pbf/albania.osm.pbf --out out/map-data/albania
.venv\Scripts\python.exe earthng/build_mod.py --out out/mod --lang uk
```

The output directory name must be the installed country's manifest ID. A matching
source fingerprint reuses completed output. For a changed source use a fresh
output directory. Planet builds embed completed `out/map-data/<id>/` directories.
Country builds can supply `map_data=` to `build_country`; spot and Map Builder
pipelines do this automatically. Code-only planet refresh does not create data.

Country sidecars live under `earthng/countries/<id>/map/`; planet fallback sidecars
live under `earthng/planet/maps/<id>/`. Each has `index.json`, `places.json` and
road tiles. Only mounted, available countries contribute their sidecars. A newer
country sidecar takes priority over the planet fallback. OSM data remains ODbL,
credited in the map and index; there are no BeamNG assets in these files.

Tests: `test_map_data.py` covers PBF extraction, villages, aliases, country search,
cache/language/limit changes, overview zooms and unmounted packs. `test_widget.py`
also checks streaming while the map is open and minimap graph updates with no traffic.
