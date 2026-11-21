# Flora: the real species of a region

EarthNG plants a wood, a street and a yard with the species that grow there, in the layers a
real wood has. This guide covers what the planet does on its own and how to build the optional
flora pack with models from [FoliMesh](https://folimesh.com).

## What the planet does without any pack

`mod/lua/ge/extensions/e2r/flora.lua` holds the rules; they are written for Ukraine and apply
inside its bounds. Elsewhere the generator plants what it planted before.

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

### Standing still

Driving, a wood is a tile's cap of crowns and a few ground cover definitions a layer. Once the
car (or a free camera) has stood for about a second:

- the ground cover fills up: flowers, daisies and buttercups, seeded grass heads, nettles, wet
  plants in the hollows, the wood's second and third herbs;
- the wood round the car fills up to the full lattice within 90 m: the trees the cap left out
  are planted, the farthest first.

Both go back to the driving set when the car moves off; the extra trees stay until their tile
unloads.

## The flora pack (FoliMesh)

FoliMesh is a procedural vegetation generator: a species, a seed and an age make one model with
four levels of detail, always the same file. Its MCP endpoint needs a paid plan and an API key
of your own account.

1. Create a key in your FoliMesh account ("API keys & MCP") and put it in the environment
   variable `FOLIMESH_KEY`, or as one line in `data/folimesh.key`.
2. Check the balance and what the recipe would export:

   ```powershell
   .venv\Scripts\python.exe earthng\folimesh.py balance
   .venv\Scripts\python.exe earthng\folimesh.py fetch --region ukraine --dry-run
   ```

3. Export models (one download each; a model already in `data/folimesh/` is never paid for
   again) and build the pack:

   ```powershell
   .venv\Scripts\python.exe earthng\build_flora.py --region ukraine --fetch 20
   ```

   The result is `out/flora/earthng_flora.zip`. Put it beside `earthng_planet.zip` in `mods/`.

The recipe is `earthng/flora/<region>.json`: each species with its FoliMesh slug, seeds and
ages, the most needed first. `earthng/flora_mesh.py` turns a GLB into a Collada shape with the
game's level-of-detail nodes, a billboard, a trunk collision prism, cut-out leaf materials and
vertex colours for the game's wind. The pack's `flora.json` lists the models with their heights;
`flora.lua` takes a species' own models as soon as the pack has them.

### Licence

The FoliMesh licence forbids redistributing the models as files or putting them in an open
repository (section 4). The models therefore live only in `data/` (not in Git) and in the
built mod archive. Read [the licence](https://folimesh.com/license) before you publish a pack
you built: whether a BeamNG mod ZIP counts as the "engine archive" the licence allows is the
licensor's call, not ours.

## Checks

```powershell
.venv\Scripts\python.exe -m unittest discover -s earthng -p "test_flora*.py"
.venv\Scripts\python.exe -m unittest discover -s earthng -p "test_folimesh.py"
.venv\Scripts\python.exe earthng\biome_census.py --pack <mods>\earthng_kyiv-oblast.zip --lat 50.87 --lon 30.73 --label wood --tiles 1 --quality 100
```

The test plot for the look of a wood is the pine forest of the Desna-Dnipro interfluve at
50.87, 30.73 (Kyiv oblast pack).
