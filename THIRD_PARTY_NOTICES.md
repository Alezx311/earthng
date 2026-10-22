# Data and assets

The MIT license covers EarthNG's original code. It does not replace the terms
of the following data and assets:

- OpenStreetMap contributors: ODbL 1.0. Country packs contain derived OSM data;
  retain their manifests and attribution. https://www.openstreetmap.org/copyright
- Geofabrik provides the regional OSM extracts: https://download.geofabrik.de/
- Map Builder's optional street detail shows OpenStreetMap standard tiles, used
  under the tile usage policy: https://operations.osmfoundation.org/policies/tiles/
- Terrarium elevation tiles: https://registry.opendata.aws/terrain-tiles/
  See the source attribution and terms there when redistributing elevation data.
- Estonian elevation (`--local-dem`): Map data: Republic of Estonia Land and Spatial
  Development Board (Maa- ja Ruumiamet), under its open data licence:
  https://geoportaal.maaruum.ee/opendata-licence . State the extraction year
  when redistributing packs built with it.
- Natural Earth: public-domain map data. https://www.naturalearthdata.com/about/terms-of-use/
- Panelka pack by kureca, ambientCG and Poly Haven textures: CC0, as recorded in
  the texture source manifest distributed with the developer assets. Road surfaces
  and line paint: Poly Haven asphalt_01 and aerial_asphalt_01, ambientCG Asphalt025C,
  Asphalt026C and RoadLines025B. Desert, dune, steppe, tundra, alpine and snow ground:
  ambientCG Ground037, Ground063, Ground068, Ground079S, Ground080, Ground097,
  Ground102, Ground110, Snow014 and Snow015.
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

Python packages retain their own licenses and are installed separately by pip.
The planet builder uses `distributable=True` to avoid embedding game textures.
