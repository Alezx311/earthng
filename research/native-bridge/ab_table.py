"""A/B table of ab_run.py runs (summary.json + report.json), markdown for the night report.

    .venv/Scripts/python.exe research/native-bridge/ab_table.py out/night-1116/runs/kyiv-q50-lua-1 out/night-1116/runs/kyiv-q50-rust-1 ...

Landing marks are real seconds since the landing request (world.lua loadReal: S.now stands
still in a long frame): ready = the tile under the car (early arrival), final = the whole
landing set built, landed = touch-down (roads spawned with collision round the car).
"""
import json
import sys
from pathlib import Path


def row(d):
    d = Path(d)
    s = json.loads((d / 'summary.json').read_text(encoding='utf8'))
    r = json.loads((d / 'report.json').read_text(encoding='utf8'))
    g = r.get('game', {})
    lr = g.get('loadReal') or {}
    sp = (g.get('loadEngine') or {}).get('spawning') or {}
    dr = s.get('drive') or {}
    c = s.get('cpu') or {}
    rs = (g.get('native') or {}).get('rust') or {}
    mark = lambda k: (lr.get(k) or {}).get('s')
    f = lambda v, n=1: '—' if v is None else (f'{v:.{n}f}' if isinstance(v, float) else str(v))
    rust = '—'
    if rs:
        rust = (f"{rs.get('finished', 0)}/{rs.get('submitted', 0)} ok, fail {rs.get('failed', 0)}, "
                f"dec {rs.get('decodeMs', 0) / 1000:.1f} s (max {rs.get('decodeMaxMs', 0):.0f} ms), "
                f"{rs.get('bytes', 0) / 2**20:.0f} MB")
    return (f"| {d.name} | {f(mark('ready'))} | {f(mark('final'))} | {f(mark('landed'))} | "
            f"{f((sp.get('Lua') or 0) / 1000)} / {f((sp.get('LuaGC') or 0) / 1000)} | "
            f"{f(dr.get('p50FrameMs'), 0)} / {f(dr.get('p95FrameMs'))} / {f(dr.get('p99FrameMs'), 0)} | {f(dr.get('over100'))} | "
            f"{s.get('roadMissFrames', 0)} | {s.get('sceneMissFrames', 0)} / {s.get('sceneViewMissFrames', 0)} | "
            f"{f(c.get('meanCores'), 2)} | {f(c.get('peakPrivateMb'))} | {rust} |")


HEAD = ('| прогін | ready, с | final, с | landed, с | Lua / GC спавну, с | кадр p50 / p95 / p99, мс | >100 мс | road miss | '
        'scene miss | ядер | private, МБ | міст |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |')

if __name__ == '__main__':
    print(HEAD)
    for d in sys.argv[1:]:
        try:
            print(row(d))
        except (OSError, ValueError, KeyError) as e:
            print(f'| {Path(d).name} | помилка: {e} |')
