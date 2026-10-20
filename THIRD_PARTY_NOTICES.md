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
- Natural Earth: public-domain map data. https://www.naturalearthdata.com/about/terms-of-use/
- Panelka pack by kureca and ambientCG textures: CC0, as recorded in the texture
  source manifest distributed with the developer assets.
  https://kureca.itch.io/panelka-pack and https://ambientcg.com/
- BeamNG.drive models and materials are referenced from the player's installed
  game. They are not included in EarthNG release archives. BeamNG.drive is
  required and is not supplied by this project.

Python packages retain their own licenses and are installed separately by pip.
The planet builder uses `distributable=True` to avoid embedding game textures.
