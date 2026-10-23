# Estonia

Estonia support is maintained by [Mitz Racing](https://github.com/mitzracing), who added
the Estonian LiDAR terrain, the road register import and county sections, and keeps
fixing Estonian roads, bridges and junctions found in game. Bug reports and help from
other Estonian players are welcome.

## What the Estonia pack adds over a plain OSM build

- **LiDAR terrain** (`--local-dem`): the Land Board's (Maa- ja Ruumiamet) 10 m bare-earth
  DTM replaces the SRTM-based Terrarium heights, which stand 3–10 m too high under forest
  and towns. 578 sheets cover the country (about 1.8 GB cache in `out/world/cache/est`).
  The sheets are burnt into z13 tiles and the region carries a 10 m elevation grid, so
  ditches, embankments and small rises survive; the ground is pulled to the roads only
  within 15 m of their edge.
- **Road register** (`--road-register`): carriageway widths, shoulders and guard rails of
  the state roads from the Transpordiamet road register. Its terms for redistributing
  derived packs are not yet confirmed: keep register-built packs for local use.
- **Sections**: each county can be rebuilt on its own and replaces that area of the
  country pack in game.

## Build

```powershell
# the whole country (about 1 h on a desktop, ~330 MB)
.venv\Scripts\python.exe earthng/country_fetch.py build --place estonia --mods "<BeamNG user folder>" --local-dem
# one county, after a fix there (10–15 min)
.venv\Scripts\python.exe earthng/country_fetch.py sections --place estonia
.venv\Scripts\python.exe earthng/country_fetch.py build --place estonia --section harju-maakond --mods "<BeamNG user folder>" --local-dem
```

Add `--road-register` for local builds with the register's widths and rails. `--block`,
`--asphalt`, `--buildings` and the other look options work as for any country.

## Reporting a problem

Open an issue with:

1. the place: coordinates (lat, lon) or a link to openstreetmap.org at that spot;
2. a screenshot from the game;
3. what it looks like in reality (a photo or a street-level image link).

Many road problems are OSM data (a missing `bridge`, `lanes`, `junction=roundabout` or a
wrong class). Those are best fixed in OpenStreetMap itself; the next build picks them up.
Problems in how the data is drawn (geometry, bridges, markings) are fixed in the generator
with a test (`earthng/test_generator.py`), then the affected county is rebuilt.

## Data and credits

- © OpenStreetMap contributors, ODbL.
- Elevation: Republic of Estonia Land and Spatial Development Board (Maa- ja Ruumiamet),
  open data licence, https://geoportaal.maaruum.ee/opendata-licence .
- State roads (optional): Transpordiamet, Teeregister, https://teeregister.mnt.ee/ .
