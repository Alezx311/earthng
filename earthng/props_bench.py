"""Street props microbenchmark in a running test game (test_world.py --manual --probe).

    python earthng/props_bench.py out/props/user out/props/runs.jsonl "method='forest', count=6000" ...
    python earthng/props_bench.py --table out/props/runs.jsonl

Each config is the argument table of B.run in earthng/probe/street_props.lua: method 'static'
(TSStatic, no collision), 'staticColl' or 'forest' (collidable=true for solid items), count,
radius (m round the car), view={dx, dy, dz} for a free camera. Prints frames before and after
the props, spawn and removal cost, and the engine's Render/Ticking.
"""
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import probe  # noqa: E402


def lua(text):
    """The probe's serialized Lua table as JSON."""
    s = re.sub(r'\[("(?:[^"\\]|\\.)*")\]=', r'\1:', text)
    s = re.sub(r'\[(\d+)\]=', r'"\1":', s).replace('=inf', '=0').replace(':inf', ':0')
    return json.loads(s)


def metric(samples, name):
    vals = [m.get(name, 0) for m in samples.values()] if isinstance(samples, dict) else []
    return sum(vals) / len(vals) if vals else float('nan')


def table(path):
    print(f'{"config":44s}  base after delta p99b p99a spawnMs us/item remove render tick')
    for line in open(path, encoding='utf8'):
        rec = json.loads(line)
        try:
            r = lua(rec['result'])
        except ValueError:
            print(f'{rec["cfg"]:44s}  {rec["result"][:60]}')
            continue
        b, a = r['base'], r['after']
        print(f'{rec["cfg"]:44s} ' + ' '.join(f'{v:5.1f}' for v in (
            b['mean'], a['mean'], a['mean'] - b['mean'], b['p99'], a['p99'], r.get('spawnMs', 0), r.get('perItemUs', 0),
            r.get('removeMs', 0), metric(r.get('afterMetrics'), 'Render'), metric(r.get('afterMetrics'), 'Ticking'))))


def main():
    if sys.argv[1] == '--table':
        table(sys.argv[2])
        return
    user, out = sys.argv[1], Path(sys.argv[2])
    print(probe.run(user, (HERE / 'probe' / 'street_props.lua').read_text(encoding='utf8'), 30))
    for cfg in sys.argv[3:]:
        text = probe.run(user, f'return B.run{{{cfg}}}', 600)
        with out.open('a', encoding='utf8') as f:
            f.write(json.dumps({'cfg': cfg, 'result': text}) + '\n')
    table(out)


if __name__ == '__main__':
    main()
