# Data and assets

The MIT license covers EarthNG's original code. It does not replace the terms
of the following data and assets:

- OpenStreetMap contributors: ODbL 1.0. Country and section packs contain derived
  OSM data, including their offline maps (settlements, points and road overviews);
  retain their manifests and attribution. https://www.openstreetmap.org/copyright
- Geofabrik provides the regional OSM extracts: https://download.geofabrik.de/
- ISRG Root X1 and ISRG Root X2 are bundled so the builder can verify Let's Encrypt
  chains when the system store cannot: https://letsencrypt.org/certificates/
- EarthNG.exe's map shows OpenStreetMap standard tiles, used under the tile usage
  policy: https://operations.osmfoundation.org/policies/tiles/ . Its town and address
  search asks Nominatim (https://operations.osmfoundation.org/policies/nominatim/), and
  the OSM data of a drawn area may come from public Overpass API servers
  (overpass-api.de, overpass.private.coffee, overpass.kumi.systems).
- Leaflet (`app/ui/vendor/leaflet`) draws EarthNG.exe's map: BSD 2-Clause, see its
  LICENSE file there. https://leafletjs.com/
- Terrarium elevation tiles: https://registry.opendata.aws/terrain-tiles/
  See the source attribution and terms there when redistributing elevation data.
- Estonian elevation (`--local-dem`): Map data: Republic of Estonia Land and Spatial
  Development Board (Maa- ja Ruumiamet), under its open data licence:
  https://geoportaal.maaruum.ee/opendata-licence . State the extraction year
  when redistributing packs built with it.
- Estonian state roads (`--road-register`): Transpordiamet, Teeregister
  (https://teeregister.mnt.ee/), open data listed as CC BY 4.0 on
  https://andmed.eesti.ee/ . Packs built with it may be redistributed with this credit.
- Natural Earth: public-domain map data. https://www.naturalearthdata.com/about/terms-of-use/
- The global photo overview uses NASA's **Blue Marble: Next Generation with Topography**,
  July 2004 (Reto Stöckli, NASA Earth Observatory), reprojected to Web Mercator and reduced
  for offline display. [Source imagery](https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography/)
- Map Builder's offline area imagery in regional packs consists of RGB
  composites. © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data
  (2021) processed by ESA WorldCover consortium.
  Area imagery is obtained from Terrascope's WMS true-colour 2021 composite, reprojected
  to Web Mercator and encoded as mipmapped DXT5 sheets; no imagery service is used in game.
  [Data and attribution](https://esa-worldcover.org/en/data-access) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- The land's real colour in a pack built with `--real-colour` (`far/<region>.s2.color.dds`,
  `far/<region>.s2.bin`; `earthng/s2_colour.py`) is the same ESA WorldCover 2021 annual
  composite of Sentinel-2 (red, green and blue at 10 m), read from the open bucket
  `esa-worldcover-s2`, resampled to the region's frame, brightened and encoded as BC1 maps.
  © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021)
  processed by ESA WorldCover consortium.
  [Registry of Open Data on AWS](https://registry.opendata.aws/esa-worldcover-vito-composites/) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- The engine's grass on a hidden terrain block (`mod/lua/ge/extensions/e2r/turf.lua`) follows
  BeamNG.Earth by TecnaGamer (MIT, https://github.com/TecnaGamer/BeamNG.Earth): that a
  TerrainBlock which is not drawn still carries GroundCover, CPU placement with
  `flushGroundCoverGrids`, and the way a stock GroundCover definition is read from the
  game's own level files and bound to another layer (`fieldsFor`, adapted from its
  `groundcover.lua`). Copyright (c) TecnaGamer; the MIT terms apply to those parts.
- The address plates' letters (`real/glyphs` in the planet's art) are rendered from Noto
  Sans Mono Bold, which BeamNG.drive ships in `ui/common/Noto_Sans_Mono`; the font itself
  is not copied. Copyright 2022 The Noto Project Authors, SIL Open Font License 1.1:
  https://openfontlicense.org/
- Panelka pack by kureca, ambientCG and Poly Haven textures: CC0, as recorded in
  the texture source manifest distributed with the developer assets. Road surfaces
  and line paint: Poly Haven asphalt_01 and aerial_asphalt_01, ambientCG Asphalt025C,
  Asphalt026C and RoadLines025B. Desert, dune, steppe, tundra, alpine and snow ground:
  ambientCG Ground037, Ground063, Ground068, Ground079S, Ground080, Ground097,
  Ground102, Ground110, Snow014 and Snow015. Drawn facades, walls, roofs, fences, setts
  and fields (`earthng/fast_facade.py`): the sets of `MATERIAL_SETS` in
  `earthng/fetch_textures.py`, ambientCG Concrete035, Concrete037, Concrete043A,
  Ground048, Ground072, PaintedPlaster014, PaintedPlaster018, Plaster002,
  RoofingTiles013B, RoofingTiles014A, ThatchedRoof001A, WoodSiding003, WoodSiding005 and
  WoodSiding009; Poly Haven bitumen, box_profile_metal_sheet, brick_wall_10, clay_plaster,
  clay_roof_tiles_02, cobblestone_03, exterior_wall_cladding_02, exterior_wall_cladding_03,
  grey_roof_01, medieval_red_brick, red_brick_03, red_laterite_soil_stones,
  roof_slates_03, rough_block_wall, rusty_corrugated_iron, sandstone_blocks_05,
  t_concrete_wall_002, white_sandstone_blocks_02, whitewashed_brick, worn_corrugated_iron
  and yellow_brick.
  https://kureca.itch.io/panelka-pack, https://ambientcg.com/ and https://polyhaven.com/
- Climate classes (the planet's `earthng/planet/climate`): Köppen-Geiger 1991-2020,
  resampled to one arc minute, from Beck, H. E., T. R. McVicar, N. Vergopolan, A. Berg,
  N. J. Lutsko, A. Dufour, Z. Zeng, X. Jiang, A. I. J. M. van Dijk and D. G. Miralles,
  High-resolution (1 km) Köppen-Geiger maps for 1901-2099 based on constrained CMIP6
  projections, Scientific Data 10, 724 (2023). CC BY 4.0.
  https://doi.org/10.6084/m9.figshare.21789074
- BeamNG.drive models and materials are referenced from the player's installed
  game. They are not included in EarthNG release archives. BeamNG.drive is
  required and is not supplied by this project.

Python packages retain their own licenses. EarthNG.exe embeds CPython 3.13 (PSF License)
and the packages of `requirements-fast.txt`, each under its own license. The Rust crates
compiled into `earthng-mapbuilder.exe` and `earthng_native.dll` are listed with their
licenses in `bin/THIRD_PARTY_RUST.txt` inside the exe's runtime; the native tools load
GEOS (LGPL 2.1) from shapely and PROJ (MIT) from pyproj at run time.
The planet builder uses `distributable=True` to avoid embedding game textures.


## Flora (21 November 2026)

The species rules of `mod/lua/ge/extensions/e2r/flora.lua` (zones, stands, lists of trees and
shrubs) are written from the general forestry of Ukraine's natural zones. They copy no dataset.

The optional flora pack (`earthng_flora.zip`, built by `earthng/build_flora.py`) holds models
made with FoliMesh (https://folimesh.com), a procedural vegetation generator by individual
entrepreneur Voliansky Filipp Andriyovych, Kyiv. They are exported through the service's API
with the pack maker's own account and are licensed to that account under the
[FoliMesh License Agreement](https://folimesh.com/license). The licence forbids the models in
an open repository and as standalone files: this repository holds only the recipe (species,
seed, age: `earthng/flora/*.json`) and the converter, never a model or a texture of theirs.
FoliMesh states that its generator was inspired by EZ-Tree by Dan Greenheck (MIT) and
rewritten from scratch.

Without the pack every species is drawn with the installed game's own trees, which stay in the
player's install. The wood's ground cover (`turf.lua`) reads stock GroundCover definitions from
the game's own level files (Hirochi Raceway, East Coast USA, Driver Training, West Coast USA)
at run time and binds them to EarthNG's layers; none of those files is copied.

The wood's floor sheet is composed from ambientCG ScatteredLeaves002 and Ground037 (CC0, the
sets `leaves_brown` and `moss_earth` of `earthng/fetch_textures.py`) and the project's own
ground photos; its fine detail is the installed game's forest floor texture, referenced through
the VFS.

## Experimental Kyiv 3D art (fal, 21 November 2026)

Original prototype art in `mod/art/shapes/earthng/kyiv3d/` was generated through fal
with `fal-ai/nano-banana-2` (concept images) and `fal-ai/trellis-2` (textured 3D).
The recipes are in `earthng/kyiv3d_assets.py`; the art folder contains provenance
(endpoint, request IDs, seeds and source hashes) and metric conversion reports.
This is artistic regional reconstruction, not a surveyed replica.

Upstream model pages: [Nano Banana 2](https://fal.ai/models/fal-ai/nano-banana-2),
[Trellis 2](https://fal.ai/models/fal-ai/trellis-2). Both pages label commercial use;
provider terms apply. No BeamNG stock meshes or reference photographs are included
in this generated art. Installed stock resources remain VFS references.

## Building kit art (fal, 21 November 2026)

The building kit's maps (`kw_*`, `kit_cells*`, `kit_trim*` in the planet's art; recipes and
processing in `earthng/kit_art.py`) were generated through fal: wall and roof surfaces with
`fal-ai/patina/material` (seamless colour, normal, roughness and height), the sheets of
windows, doors and facade fittings and the trim strips with `fal-ai/nano-banana-2`. The
prompts are in `kit_art.py`; endpoints, request IDs and seeds are logged in
`data/textures/kit/fal_manifest.jsonl` beside the generated originals. The atlas, the panel
sheets, the glass masks and the tints are computed from those originals at art build.
These are artistic regional types, not photographs or surveys of real buildings.

Upstream model pages: [PATINA](https://fal.ai/models/fal-ai/patina/material),
[Nano Banana 2](https://fal.ai/models/fal-ai/nano-banana-2). Provider terms apply.
