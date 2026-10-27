# Estonia

[Mitz Racing](https://github.com/mitzracing) contributes to EarthNG's Estonia support: the
Estonian LiDAR terrain, the road register import and county sections, and fixes for the
roads, bridges and junctions found in game. The project is Alex's (Alezx311) and his
releases carry it; we help develop it, with LiDAR. Bug reports and help from other
Estonian players are welcome.

## What the Estonia pack adds over a plain OSM build

- **LiDAR terrain** (`--local-dem`): the Land Board's (Maa- ja Ruumiamet) 10 m bare-earth
  DTM replaces the SRTM-based Terrarium heights, which stand 3–10 m too high under forest
  and towns. 578 sheets cover the country (about 1.8 GB cache in `out/world/cache/est`),
  fetched from the Land Board's coverage service (WCS, `teenus.maaamet.ee/ows/wcs-dtm`):
  the geoportal itself blocks scripted downloads from some countries.
  The sheets are burnt into z13 tiles and the region carries a 10 m elevation grid, so
  ditches, embankments and small rises survive; the ground is pulled to the roads only
  within 15 m of their edge.
- **Road register** (`--road-register`): carriageway widths, shoulders and guard rails of
  the state roads from the Transpordiamet road register, open data under CC BY 4.0
  (andmed.eesti.ee): register-built packs may be shared with its credit.
- **Sections**: each county can be rebuilt on its own and replaces that area of the
  country pack in game.

## Build

```powershell
# the whole country at 10 m (about 1 h on a desktop, ~530 MB, under 1 GB of RAM)
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
- State roads (optional): Transpordiamet, Teeregister, https://teeregister.mnt.ee/ ,
  CC BY 4.0.

A pack carries these credits itself (`CREDITS.txt` and the manifest's `credits`): the
Land Board's whenever its elevation tiles hold the burnt-in LiDAR (a burn stays in the
cache after the build that made it), the register's when built with `--road-register`.
