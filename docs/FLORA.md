# Flora: the real species of a region

EarthNG plants a wood, a street and a yard with the species that grow there, in the layers a
real wood has. This guide covers what the planet does on its own and how to build the optional
flora pack with models from [FoliMesh](https://folimesh.com).

## What the planet does without any pack

`mod/lua/ge/extensions/e2r/flora.lua` holds the rules; they are written for Ukraine and apply
inside its bounds. Elsewhere the generator plants the sets of the climate, as before.

| Step | Rule |
| --- | --- |
| Zone | Polissia, forest-steppe, steppe, the Carpathians by height (oak and hornbeam foothills, beech from about 520 m, spruce from about 1080 m) and the Crimean mountains. The zone borders wander by a few kilometres of noise. |
| Stand | A wood is stands of 100 to 300 m. The map's `leaf_type` decides conifer or broadleaf where it is set; where it is not, the zone's share does (64 % conifer in the Polissia, 14 % in the forest-steppe). Each stand has a leading species and an age. |
| Tree | 62 % of a stand's trees are its leader, the rest come from the zone's list. A tree is asked for by height; the model nearest to it is scaled to it. |
| Water | Within about 24 m of a water body or a wetland the stand is alder and willow. A swamp is wooded, a bog has stunted pine and birch, a marsh almost no trees. |
| Streets and yards | A mapped tree row is one species along its whole length (linden, poplar, chestnut...). Parks, towns and village yards have their own planted lists; a yard is mostly fruit trees and a walnut. |
| Undergrowth | Hazel, elder, juniper, rowan and the young growth of the wood's own trees, thicker in old stands and along the wood's edge. |
| Deadwood | Fallen trunks, snags and stumps. |
| Floor | Leaf and needle litter with moss, and the engine's ground cover on it: ferns and herbs under broadleaves, sparser herbs under conifers. |

The species are drawn with the game's own trees until the flora pack has models for them: oak,
beech, aspen (for birch), Scots pine and Douglas fir (for spruce and fir) stand in for the
twenty-odd species of the rules.

### Under 50 km/h

At speed a wood is a tile's cap of crowns and a few ground cover definitions a layer. Once the
car (or a free camera) has been under 50 km/h for about a second:

- the ground cover fills up: flowers, daisies and buttercups, seeded grass heads, nettles, wet
  plants in the hollows, the wood's second and third herbs;
- the wood fills up to the full lattice within 90 m of the place the car will be in three
  seconds: the trees the cap left out are planted, the farthest first;
- with the flora pack, the small plants stand too: ferns, bracken and mushrooms on a wood's
  floor, flowers in a meadow, reed and cattail on a bank, a kitchen garden's sunflowers and
  pumpkins, wheat and maize along a field's edge.

The ground cover goes back to the fast set once the car has held more than 60 km/h for two
seconds; what was planted stays until its tile unloads.

### By climate

The engine's ground cover (the lawn, the wood's floor and the layers that fill up under 50 km/h)
is one of ten sets, picked by the climate under the car: the temperate continent, the oceanic
west, the humid subtropics, the taiga, the steppe, the Mediterranean, the Pacific's dry summer,
a desert, a savanna and the wet tropics. Every set is made of the game's own ground cover
(Italy, Utah, Johnson Valley, Jungle Rock Island, Small Island, Cliff, West and East Coast),
read from the player's installation; `turf.lua` `M.SETS` lists them. A steppe, a savanna and a
desert grow their dry cover only with the engine's grass on.

### Beside a road

The lawn comes up to the edge of the paving: within three metres of a road it is short trodden
grass with weeds, rising from a hand's height at the asphalt to the meadow's own. The verge under
it has its own sheet. `earthng/verge_census.py --turf` counts, outside the game, how much of the
land beside a tile's roads has lawn on it.

### From afar and at speed

A far tile's trees are cards cut out of one drawn sheet, four triangles a tree, at the places
the near tile's trees will stand; they stay until those are planted. The game's detail scale
follows the car's speed (the player's own under 50 km/h, 0.45 of it from 150 km/h), so at speed
the trees of the middle distance stay billboards instead of changing model on the way. The
option "Model detail by speed" turns it off.

## The flora pack (FoliMesh)

FoliMesh is a procedural vegetation generator: a species, a seed and an age make one model with
its levels of detail, always the same file. Its MCP endpoint needs a paid plan and an API key
of your own account.

1. Create a key in your FoliMesh account ("API keys & MCP") and put it in the environment
   variable `FOLIMESH_KEY`, or as one line in `data/folimesh.key`.
2. Check the balance and what the recipes would export:

   ```powershell
   .venv\Scripts\python.exe earthng\folimesh.py balance
   .venv\Scripts\python.exe earthng\folimesh.py fetch --region all --dry-run
   ```

3. Export models (one download each; a model already in `data/folimesh/` is never paid for
   again) and build the pack:

   ```powershell
   .venv\Scripts\python.exe earthng\build_flora.py --fetch 20
   ```

   The result is `out/flora/earthng_flora.zip`. Put it beside `earthng_planet.zip` in `mods/`.
   `out/flora/blocks.json` lists what the pack holds, a model a line, by place and layer.

   A few species (the meadow flowers: poppy, cornflower, daisy, dandelion, clover, bellflower,
   and the generic bush) are not built on FoliMesh's servers: the export answers "this species
   has no photo leaves on the server". Open folimesh.com/editor in your browser, signed in, and
   fetch again: the export then builds in that tab. A refused export costs nothing.

The recipes are `earthng/flora/*.json`: `ukraine` (the woods, towns, villages, fields and banks
of Ukraine), `tropics` (a rainforest) and `arid` (deserts, savannas and the Mediterranean). Each
species has its FoliMesh slug, seeds and ages, the places it belongs to (`use`) and its layer.
`earthng/flora_catalog.py` measures every species of the FoliMesh catalogue for free (height,
triangles a level) before a download is spent.

`earthng/flora_mesh.py` turns a GLB into a Collada shape: the game's level-of-detail nodes with
sizes set by what a level costs, a billboard, collision prisms from the model's own capsules,
cut-out leaf materials, the model's wind data as the game's vertex colours, and its tints
(berries, a mushroom's cap, moss) as materials. A model's level 0 is tens of thousands of
triangles: its thinnest twigs are left out, and `--no-hero` builds a pack without level 0.

### Cooking the shapes

The game compiles a Collada shape into its own `.cdae` the first time it meets it and bakes the
billboard a far tree is drawn as. Its own levels ship both beside every tree, and so must the
pack: baking a hundred imposters in the middle of a landing reset the graphics device in three
test runs of five. `build_flora.py` says how many of the pack's shapes are still raw. To cook
them:

```powershell
.venv\Scripts\python.exe earthng\test_world.py --out out\flora\cook-01 --lat -48.8860814 --lon -123.4474206 --planet <earthng_planet.zip> --mod out\polygon\earthng_polygon.zip --mod out\flora\earthng_flora.zip --cook-flora
.venv\Scripts\python.exe earthng\flora_cook.py out\flora\cook-01
.venv\Scripts\python.exe earthng\build_flora.py
```

The cook run loads every shape of the pack at the landing; `flora_cook.py` keeps what the game
made of each in `data/flora/cooked/` with the hash of the Collada file, and the next build puts
it beside the shape. A change of the converter that alters a shape makes it raw again. Cook in
batches: a pack with many raw shapes is what crashed.

### With the pack, outside Ukraine

Where the pack has the trees of a climate's usual woods, they stand instead of the climate's
old sets: a temperate wood, taiga, a rainforest (canopy, palms, banana, tree fern, bamboo and
lianas under it), a savanna, a desert (saguaro, opuntia, agave, date palms at an oasis) and the
Mediterranean (stone pine, cypress, olive). Towns and yards take what is planted there.

The lab's knob "Vegetation zone" (pause menu, EarthNG tab) gives any tile or the whole world a
zone whatever the place; a universe may name one (the jungle does).

### Looking at the models without the game

```powershell
blender -b --factory-startup -P earthng\flora_preview.py -- --pack data\flora\all out\flora\blocks --top
.venv\Scripts\python.exe earthng\flora_sheet.py
```

Blender renders what the converter wrote (it reads the shapes itself: Blender 5 has no Collada
importer); the sheets are `out/flora/blocks.jpg` and one a place. They check the files, not the
game's shading.

### Licence

The FoliMesh licence forbids redistributing the models as files or putting them in an open
repository (section 4). The models therefore live only in `data/` (not in Git) and in the
built mod archive. Read [the licence](https://folimesh.com/license) before you publish a pack
you built: whether a BeamNG mod ZIP counts as the "engine archive" the licence allows is the
licensor's call, not ours.

## Checks

```powershell
.venv\Scripts\python.exe -m unittest discover -s earthng -p "test_fl*.py"
.venv\Scripts\python.exe -m unittest discover -s earthng -p "test_folimesh.py"
.venv\Scripts\python.exe earthng\universe_census.py --flora data\flora\all --plants A3 A6 C4 E3 JG-B5
.venv\Scripts\python.exe earthng\biome_census.py --pack <mods>\earthng_kyiv-oblast.zip --lat 50.87 --lon 30.73 --label wood --tiles 1 --quality 100
```

`universe_census.py --plants` counts what stands in a tile of the proving ground by species,
and how much of it waits for a slow car. The test plot for the look of a wood is the pine
forest of the Desna-Dnipro interfluve at 50.87, 30.73 (Kyiv oblast pack); the proving ground's
vegetation tiles are A3-D3 (woods), E3 and L4 (parks), A6 and C6 (a village, allotments), C4
(fields), E2 and J3 (wetlands) and the jungle block JG.
