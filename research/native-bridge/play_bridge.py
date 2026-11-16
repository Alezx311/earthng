"""Start BeamNG for manual play in a separate test profile, with a test planet and the bridge.

    .venv/Scripts/python.exe research/native-bridge/play_bridge.py
    .venv/Scripts/python.exe research/native-bridge/play_bridge.py --lat 48.45306 --lon 24.55611 --no-bridge

The profile is its own folder (out/night-1116/manual/<time>/user by default; test_world.py wants
a folder that does not exist yet, so every start gets a new one), never the live BeamNG user folder: earthng/test_world.py --manual lands at the point and hands the car over; this script
then loads the experimental tile-pool DLL into that one game process (loader.py) and writes
the profile's settings/earthng-rust-bridge.json. Closing the game ends everything; without
the DLL (or with --no-bridge) the same planet builds every tile in Lua.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import ab_run  # noqa: E402

ROOT = ab_run.ROOT


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path, default=ROOT / 'out' / 'night-1116' / 'manual')
    p.add_argument('--planet', type=Path, default=ROOT / 'out' / 'night-1116' / 'planet-final' / 'earthng_planet.zip')
    p.add_argument('--pack', type=Path, default=ab_run.PACK)
    p.add_argument('--dll', type=Path, default=ROOT / 'research' / 'native-bridge' / 'bridge' / 'target' / 'release' / 'earthng_bridge.dll')
    p.add_argument('--lat', type=float, default=50.447734)
    p.add_argument('--lon', type=float, default=30.52218)
    p.add_argument('--quality', type=int, default=50)
    p.add_argument('--graphics', default='Normal')
    p.add_argument('--resolution', default='1920x1080')
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--no-bridge', action='store_true', help='the same profile and planet, every tile in Lua')
    a = p.parse_args()
    for proc in ab_run.psutil.process_iter(['name']):
        if (proc.info['name'] or '').lower().startswith('beamng'):
            raise SystemExit('another BeamNG process is running: close it first')
    root = a.out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    out = root / time.strftime('%m%d-%H%M%S')   # test_world.py refuses a folder that exists
    cmd = [str(ab_run.PY), str(ROOT / 'earthng' / 'test_world.py'), '--out', str(out), '--mod', str(a.pack.resolve()),
           '--lat', str(a.lat), '--lon', str(a.lon), '--planet', str(a.planet.resolve()), '--manual', '--sound',
           '--quality', str(a.quality), '--graphics', a.graphics, '--resolution', a.resolution]
    log_file = open(root / (out.name + '-play_bridge.txt'), 'w', encoding='utf8')
    flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: outlives this script
    subprocess.Popen(cmd, cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT, creationflags=flags)
    log = {'cmd': cmd, 'started': time.time()}
    game = ab_run.find_game(out / 'user', 300)
    if not game:
        raise SystemExit('the game did not start; see ' + log_file.name)
    print('game pid', game.pid)
    if not a.no_bridge:
        args = SimpleNamespace(bridge=a.dll.resolve(), workers=a.workers, bridge_config=None, legacy=False,
                               timeout=900, stop_bridge_after=None)
        try:
            ab_run.bridge(args, out / 'user', game, log)
            print('bridge loaded:', log.get('loader', '')[:200])
        except Exception as e:  # the game carries on in Lua
            log['error'] = repr(e)
            print('bridge not loaded, the game builds in Lua:', e)
    (root / (out.name + '-play_bridge.json')).write_text(json.dumps(log, indent=1, default=str), encoding='utf8')
    print('the game is yours; profile', out / 'user')


if __name__ == '__main__':
    sys.exit(main())
