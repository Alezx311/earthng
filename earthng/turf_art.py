"""The level's terrain materials for the engine's grass (mod/lua/ge/extensions/e2r/turf.lua).

The game's dense grass (GroundCover) grows only on a TerrainBlock, on the squares of the terrain
materials its types name. EarthNG's ground is its own mesh, so turf.lua keeps one small
TerrainBlock under the car that is never drawn: its heights are the ground's and its layer map
says where the lawn is and of which kind. These are the layers: materials with nothing to show
(flat maps, the smallest the engine takes without resizing them at every rebuild), a ground model
each and a name. They are part of the level, not made at run time: a TerrainMaterial made in Lua
cost about a second at every material update (BeamNG.Earth's finding, terrain.lua).
"""
import io
import json
import uuid

from PIL import Image

SIZE = 256                      # px of every map: the texture set's slots
TEXTURE_SET = 'e2rTurfTextureSet'
# layer (the TerrainMaterial's name; its place here is its number in the block's layer map):
# what the tyres feel, should a wheel ever reach the hidden block
LAYERS = (('e2rTurfNone', 'DIRT'), ('e2rTurfGrass', 'GRASS'), ('e2rTurfLush', 'GRASS'), ('e2rTurfDry', 'GRASS'),
          ('e2rTurfCrop', 'GRASS'))
MAPS = {'b': (96, 104, 70), 'nm': (128, 128, 255), 'r': (236, 236, 236), 'ao': (255, 255, 255), 'h': (128, 128, 128)}
_SLOTS = (('baseColor', 'b'), ('normal', 'nm'), ('roughness', 'r'), ('ao', 'ao'), ('height', 'h'))


def _png(rgb):
    out = io.BytesIO()
    Image.new('RGB', (SIZE, SIZE), rgb).save(out, 'PNG')
    return out.getvalue()


def _id(name):
    # the same file from the same sources: no random ids
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'earthng/turf/' + name))


def material(root, name, ground):
    m = {'name': name, 'internalName': name, 'class': 'TerrainMaterial', 'persistentId': _id(name),
         'groundmodelName': ground, 'detailDistances': [0, 0, 30, 60], 'macroDistances': [0, 10, 100, 3000],
         'baseColorDetailStrength': [0, 0], 'normalDetailStrength': [0, 0], 'roughnessDetailStrength': [0, 0],
         'aoDetailStrength': [0, 0], 'baseColorMacroStrength': [0, 0], 'normalMacroStrength': [0, 0],
         'roughnessMacroStrength': [0, 0]}
    for slot, suffix in _SLOTS:
        path = f'/{root}/art/terrains/turf_{suffix}.png'
        for part, size in (('Base', SIZE), ('Detail', 2), ('Macro', 64)):
            m[f'{slot}{part}Tex'] = path
            m[f'{slot}{part}TexSize'] = size
    return m


def level_files(level):
    """{path in the planet ZIP: bytes or text} of the turf's terrain assets for a level."""
    root = f'levels/{level}'
    defs = {name: material(root, name, ground) for name, ground in LAYERS}
    defs[TEXTURE_SET] = {'name': TEXTURE_SET, 'class': 'TerrainMaterialTextureSet', 'persistentId': _id(TEXTURE_SET),
                         'baseTexSize': [SIZE, SIZE], 'detailTexSize': [SIZE, SIZE], 'macroTexSize': [SIZE, SIZE]}
    files = {f'{root}/art/terrains/main.materials.json': json.dumps(defs, indent=1)}
    for suffix, rgb in MAPS.items():
        files[f'{root}/art/terrains/turf_{suffix}.png'] = _png(rgb)
    return files
