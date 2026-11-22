"""Traffic against tile streaming: the same replayed route with and without the flow.

    .venv\\Scripts\\python.exe earthng\\traffic_ab.py --out out/traffic/ab-01 --route out/routes/kyiv-avenue.json
        --mod <earthng_kyiv-oblast.zip> --run base:walkers=1000 --run flow:flow=100,flow-real=8,walkers=1000

Every --run is one game session of test_world.py --replay (the camera flies the route at a
constant speed, so every run asks for the same tiles at the same moments; with a flow the
hand-off's real cars follow the replayed pose and their physics is in the frame). The planet is
built once from the working tree. Prints a table: frames, the gate (opened, held, timeouts), the
tiles that were late under the pose (deadline misses, scene-miss frames) and the Lua of the
frame by part.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def summary(report):
    g = report.get('game', {})
    frames = g.get('driveFrames') or {}
    gate = g.get('gate') or {}
    prof = (g.get('luaProfile') or {}).get('meanMs') or {}
    flow = g.get('flow') or {}
    walk = g.get('walk') or {}
    native = g.get('native') or {}
    n = max(1, frames.get('frames', 0))
    return {
        'status': g.get('status'), 'failures': g.get('failures'),
        'frames': frames.get('frames'), 'meanMs': round(frames.get('meanFrameMs', 0), 1), 'p50': frames.get('p50FrameMs'),
        'p99': frames.get('p99FrameMs'), 'over100': frames.get('over100'), 'slowPairs2': frames.get('slowPairs2'),
        'gateBase': gate.get('base'), 'gateOpened': gate.get('opened'), 'gateHeld': gate.get('held'),
        'gateTimeouts': gate.get('timeouts'), 'openedPer100': round(100 * (gate.get('opened') or 0) / n, 1),
        'deadlineMisses': len(g.get('deadlineMisses') or []), 'sceneMissFrames': g.get('sceneMissFrames', 0),
        'sceneMisses': len(g.get('sceneMisses') or []), 'replayM': round(g.get('replayDistanceM') or 0),
        'tilesBuilt': native.get('built'), 'tilesLoaded': g.get('tilesLoaded'),
        'lua': {k: round(v, 2) for k, v in sorted(prof.items()) if v >= .05},
        'garbageKb': round((g.get('luaProfile') or {}).get('garbageKbPerFrame', 0)),
        'flow': dict({k: flow.get(k) for k in ('cars', 'real', 'pool', 'simMax', 'drawMax', 'syncMax', 'handoff', 'handoffMs')},
                     simMean=round(flow.get('simSum', 0) / max(1, flow.get('steps', 0)), 3),
                     drawMean=round(flow.get('drawSum', 0) / max(1, flow.get('steps', 0)), 3),
                     kb=round(flow.get('kbSum', 0) / max(1, flow.get('steps', 0)), 1)) if flow else None,
        'walk': {k: walk.get(k) for k in ('walkers', 'simMax', 'drawMax', 'syncMax', 'bodies', 'pool')} if walk else None,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--route', type=Path, required=True)
    p.add_argument('--mod', action='append', default=[], type=Path)
    p.add_argument('--speed', type=float, default=25)
    p.add_argument('--seconds', type=float, default=120)
    p.add_argument('--quality', type=int, default=100)
    p.add_argument('--planet', type=Path, help='an existing planet ZIP instead of a build of the working tree')
    p.add_argument('--drive', action='store_true', help='the autopilot drives the car (physics) instead of a replay')
    p.add_argument('--run', action='append', required=True, metavar='NAME:key=value,...',
                   help='a session: test_world options without the dashes (flow=100,flow-real=8,walkers=1000,no-pace)')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    planet = a.planet
    if not planet:
        sys.path.insert(0, str(HERE))
        import build_mod
        planet = build_mod.build(a.out / 'planet')
    rows = {}
    for spec in a.run:
        name, _, opts = spec.partition(':')
        cmd = [sys.executable, str(HERE / 'test_world.py'), '--out', str(a.out / name), '--route', str(a.route),
               '--speed', str(a.speed), '--drive-seconds', str(a.seconds), '--quality', str(a.quality),
               '--planet', str(planet)]
        if not a.drive:
            cmd.append('--replay')
        for mod in a.mod:
            cmd += ['--mod', str(mod)]
        for item in filter(None, opts.split(',')):
            key, eq, value = item.partition('=')
            cmd += ['--' + key] + ([value] if eq else [])
        with open(a.out / f'{name}.log', 'w', encoding='utf8') as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        report = a.out / name / 'report.json'
        rows[name] = summary(json.loads(report.read_text(encoding='utf8'))) if report.exists() else {'status': 'no report'}
        print(name, json.dumps(rows[name]), flush=True)
        (a.out / 'summary.json').write_text(json.dumps(rows, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
