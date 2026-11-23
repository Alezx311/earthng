"""The vehicle a tile worker lives in: no body, nothing to draw, four nodes nailed to the spot.

The engine runs every vehicle's Lua on its own thread beside the frame, so a pool of these is the
mod's worker threads (mod/lua/ge/extensions/e2r/workers.lua spawns them, tileworker.lua runs in
their VMs; Knowledge/docs/FAST_TILES.md). All it must be is cheap and inert: its nodes are fixed
(it neither falls nor rolls), collide with nothing, and it has no mesh.

    python earthng/worker_vehicle.py <user>/current      # into a test profile, for a probe
"""
import json
import sys
from pathlib import Path

MODEL = 'e2r_worker'


def jbeam():
    nodes = [['id', 'posX', 'posY', 'posZ'],
             {'nodeWeight': 1, 'collision': False, 'selfCollision': False, 'fixed': True, 'frictionCoef': 0,
              'nodeMaterial': '|NM_METAL'},
             ['w0', 0, 0, 0], ['w1', 0, .3, 0], ['w2', .3, 0, 0], ['w3', 0, 0, .3]]
    beams = [['id1:', 'id2:'],
             {'beamType': '|NORMAL', 'beamSpring': 1000, 'beamDamp': 10, 'beamDeform': 'FLT_MAX',
              'beamStrength': 'FLT_MAX'},
             ['w0', 'w1'], ['w0', 'w2'], ['w0', 'w3'], ['w1', 'w2'], ['w1', 'w3'], ['w2', 'w3']]
    return {MODEL: {
        'information': {'name': 'EarthNG tile worker', 'authors': 'EarthNG'},
        'slotType': 'main',
        'refNodes': [['ref:', 'back:', 'left:', 'up:'], ['w0', 'w1', 'w2', 'w3']],
        'nodes': nodes,
        'beams': beams,
    }}


def files():
    return {
        f'{MODEL}.jbeam': json.dumps(jbeam(), indent=1),
        'info.json': json.dumps({'Name': 'EarthNG tile worker', 'Brand': 'EarthNG', 'Type': 'Prop',
                                 'default_pc': 'base', 'Author': 'EarthNG'}, indent=2),
        'base.pc': json.dumps({'format': 2, 'model': MODEL, 'parts': {}, 'vars': {}}, indent=2),
    }


def vehicle_files():
    """For the planet ZIP (build_mod.py): {path in the planet: text}."""
    return {f'vehicles/{MODEL}/{name}': text for name, text in files().items()}


if __name__ == '__main__':
    target = Path(sys.argv[1])
    for path, text in vehicle_files().items():
        file = target / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf8')
        print(file)
