"""Engine capacity sweep in one isolated test game: how many models the game thread can create,
stand, move, hide and delete, Forest at hundreds of thousands of items, createMesh input forms,
geometry from a file, DynamicShapeBatch, and the link's receive cost.

    .venv/Scripts/python.exe research/native-bridge/capacity/run.py --name cap-01
    .venv/Scripts/python.exe research/native-bridge/capacity/run.py --name cap-02 --only static,forest

Lands in central Kyiv (quality 50, Normal, 1280x720) with test_world.py --manual --probe, runs the
probes one by one through earthng/probe.py, samples the game's memory by probe phase, writes
<out>/capacity.json and closes the game with shutdown(0). Refuses to start beside another BeamNG.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PY = ROOT / '.venv' / 'Scripts' / 'python.exe'
PACK = ROOT / 'out' / 'country-setup' / 'earthng_ukraine.zip'
PLANET = ROOT / 'out' / 'night-1116' / 'planet-final' / 'earthng_planet.zip'
sys.path.insert(0, str(ROOT / 'earthng'))
sys.path.insert(0, str(HERE.parent))
import probe  # noqa: E402
from ab_run import find_game  # noqa: E402

PROBES = ['socket', 'batch', 'mesh', 'static', 'forest']
TIMEOUTS = {'dsb5': 300, 'dsb4': 300, 'dsb3': 300, 'batch2': 300, 'mesh2': 120, 'static2': 900, 'socket': 300, 'batch': 300, 'mesh': 600, 'static': 1200, 'forest': 1200}


def lua_to_py(text):
    """The probe's serialized Lua table -> Python (through LuaJIT)."""
    try:
        import lupa.luajit21 as lj
    except ImportError:
        import lupa as lj
    L = lj.LuaRuntime(unpack_returned_tuples=True)
    fn = L.eval('function(s) local f = loadstring("return " .. s); if not f then return nil end; return f() end')
    value = fn(text)

    def conv(v):
        if lj.lua_type(v) == 'table':
            keys = list(v.keys())
            if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
                return [conv(v[k]) for k in sorted(keys)]
            return {str(k): conv(v[k]) for k in keys}
        return v
    return conv(value)


def sampler(game, user, samples, stop):
    phase_file = user / 'current' / 'e2r_probe' / 'phase.txt'
    while not stop.is_set():
        try:
            m = game.memory_info()
            phase = phase_file.read_text(encoding='utf8') if phase_file.exists() else ''
            samples.append([round(time.time(), 2), phase, m.private // 2**20, m.rss // 2**20, game.num_threads()])
        except (psutil.Error, OSError):
            break
        stop.wait(0.5)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--name', required=True)
    p.add_argument('--only', help='comma list of probes (default: ' + ','.join(PROBES) + ')')
    p.add_argument('--planet', type=Path, default=PLANET)
    p.add_argument('--lat', type=float, default=50.4475)
    p.add_argument('--lon', type=float, default=30.5225)
    p.add_argument('--quality', type=int, default=50)
    p.add_argument('--graphics', default='Normal')
    p.add_argument('--keep', action='store_true', help='leave the game open at the end')
    p.add_argument('--root', type=Path, default=ROOT / 'out' / 'capacity-1116')
    a = p.parse_args()
    probes = a.only.split(',') if a.only else PROBES
    for proc in psutil.process_iter(['name']):
        if (proc.info['name'] or '').lower().startswith('beamng'):
            raise SystemExit('another BeamNG process is running: close it first (numbers would be contaminated)')
    out = (a.root / a.name).resolve()
    if out.exists():
        raise SystemExit(f'{out} exists: pick a new --name')
    cmd = [str(PY), str(ROOT / 'earthng' / 'test_world.py'), '--out', str(out), '--mod', str(PACK),
           '--planet', str(a.planet.resolve()), '--lat', str(a.lat), '--lon', str(a.lon), '--manual', '--probe',
           '--quality', str(a.quality), '--graphics', a.graphics, '--resolution', '1280x720', '--timeout', '7200']
    run = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    threading.Thread(target=lambda: lines.extend(run.stdout), daemon=True).start()
    user = out / 'user'
    game = find_game(user, 300)
    result = {'cmd': cmd, 'probes': {}, 'started': time.time()}
    samples, stop = [], threading.Event()
    try:
        if not game:
            raise RuntimeError('game process not found')
        threading.Thread(target=sampler, args=(game, user, samples, stop), daemon=True).start()
        if not probe.wait_landed(user, 600):
            raise RuntimeError('not landed')
        result['landed'] = time.time()
        text = probe.run(user, (HERE / 'common.lua').read_text(encoding='utf8'), timeout=60)
        result['common'] = text
        print('common', text, flush=True)
        for name in probes:
            t0 = time.time()
            text = probe.run(user, (HERE / f'{name}.lua').read_text(encoding='utf8'), timeout=TIMEOUTS[name])
            entry = {'seconds': round(time.time() - t0, 1), 'raw': text}
            if text and not text.startswith(('ERROR', 'COMPILE', 'TIMEOUT')):
                try:
                    entry['data'] = lua_to_py(text)
                except Exception as e:  # keep the raw text
                    entry['parseError'] = repr(e)
            result['probes'][name] = entry
            print(name, entry['seconds'], 's', text[:300], flush=True)
            (out / 'capacity.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf8')
            if text == 'TIMEOUT':
                break
    except Exception as e:
        result['error'] = repr(e)
        print('error', e, flush=True)
    finally:
        stop.set()
        result['memory'] = samples
        (out / 'capacity.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf8')
        if game and not a.keep:
            probe.run(user, 'shutdown(0) return "bye"', timeout=10)
            try:
                game.wait(60)
            except psutil.TimeoutExpired:
                game.kill()
        run.wait(120)
        (out / 'test_world.txt').write_text(''.join(lines), encoding='utf8')
    print('wrote', out / 'capacity.json')


if __name__ == '__main__':
    sys.exit(main())
