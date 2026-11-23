"""A drive's report side by side with others: frames, what the long ones did, the engine's parts,
collision rebuilds and the worker pool.

    python research/fast-tiles/run_summary.py out/quanta/drive-a1 out/quanta/drive-b1 ...

Reads each folder's report.json (earthng/test_world.py). The ledger (result.ledger, world.lua
LIMIT.ledger) is in reports of planets from 24.11.2026 on.
"""
import json
import sys
from pathlib import Path


def load(folder):
    path = Path(folder)
    report = json.loads((path / 'report.json' if path.is_dir() else path).read_text(encoding='utf-8'))
    return report.get('game') or {}


def cell(value, digits=1):
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.{digits}f}'
    return str(value)


def table(title, names, rows):
    print(f'\n{title}')
    width = max(len(r[0]) for r in rows) if rows else 10
    print(' ' * width + '  ' + '  '.join(f'{n:>16}' for n in names))
    for label, values in rows:
        print(f'{label:<{width}}  ' + '  '.join(f'{v:>16}' for v in values))


def main():
    folders = sys.argv[1:]
    games = [load(f) for f in folders]
    names = [Path(f).name[:16] for f in folders]

    def each(fn, digits=1):
        out = []
        for g in games:
            try:
                out.append(cell(fn(g), digits))
            except (KeyError, TypeError, ZeroDivisionError, IndexError):
                out.append('-')
        return out

    table('frames of the drive', names, [
        ('frames', each(lambda g: g['driveFrames']['frames'])),
        ('mean ms', each(lambda g: g['driveFrames']['meanFrameMs'])),
        ('median ms', each(lambda g: g['driveFrames']['p50FrameMs'])),
        ('p99 ms', each(lambda g: g['driveFrames']['p99FrameMs'])),
        ('over 33 ms', each(lambda g: g['driveFrames']['over33'])),
        ('over 100 ms', each(lambda g: g['driveFrames']['over100'])),
        ('worst ms', each(lambda g: g['driveFrames']['worstFrameMs'], 0)),
        ('slow pairs 1.5x', each(lambda g: g['driveFrames']['slowPairs15'])),
        ('landing s', each(lambda g: g['landedAt'] - g['landRequestedAt'])),
        ('travelled m', each(lambda g: g.get('travelledM'), 0)),
        ('tiles built', each(lambda g: g['native']['built'])),
    ])

    def ledger_rows():
        causes = {}
        for g in games:
            for band, tally in (g.get('ledger') or {}).get('bands', {}).items():
                for cause, row in tally.items():
                    causes.setdefault((band, cause), 0)
                    causes[(band, cause)] += row[1]
        order = {'17-33': 0, '33-50': 1, '50-100': 2, '100+': 3}
        keys = sorted(causes, key=lambda k: (order.get(k[0], 9), -causes[k]))
        rows = []
        for band, cause in keys:
            if band == '17-33':
                continue
            values = []
            for g in games:
                row = ((g.get('ledger') or {}).get('bands', {}).get(band) or {}).get(cause)
                values.append(f'{row[0]} / {row[1]}' if row else '-')
            rows.append((f'{band} {cause}', values))
        return rows

    rows = ledger_rows()
    if rows:
        table('frames over 33 ms by what they did (frames / ms)', names, rows)
        table('frames that changed nothing', names, [
            ('calm frames', each(lambda g: g['ledger']['calm'][0])),
            ('calm mean ms', each(lambda g: g['ledger']['calm'][1] / g['ledger']['calm'][0])),
            ('with workers', each(lambda g: g['ledger']['worked'][0])),
            ('with workers mean ms', each(lambda g: g['ledger']['worked'][1] / g['ledger']['worked'][0])),
            ('their slices ms a frame', each(lambda g: g['ledger']['worked'][2] / g['ledger']['worked'][0])),
            ('wait for vehicles <1 / 3 / 6 / 10 / 20 / over ms, %', each(lambda g: ' '.join(
                f'{v * 100 / sum(g["ledger"]["waits"]):.0f}' for v in g['ledger']['waits']))),
        ])
        parts = {}
        for g in games:
            L = g.get('ledger') or {}
            for name, ms in (L.get('engine') or {}).items():
                parts[name] = max(parts.get(name, 0), ms / max(1, L.get('frames', 1)))
        top = [n for n, ms in sorted(parts.items(), key=lambda kv: -kv[1]) if ms >= .15][:14]
        table("the engine's parts, mean ms a frame", names,
              [(n, each(lambda g, n=n: g['ledger']['engine'].get(n, 0) / g['ledger']['frames'], 2)) for n in top])

        def shape_fit(g):
            """ms a new shape file adds to a frame: a + b * materials, least squares over the
            frames that put in one shape and nothing else, against the calm frame."""
            L = g['ledger']
            rows_ = L.get('shapes') or []
            if isinstance(rows_, dict):
                rows_ = list(rows_.values())
            if len(rows_) < 8:
                return None
            calm = L['calm'][1] / max(1, L['calm'][0])
            xs = [r[0] for r in rows_]
            ys = [r[2] - calm for r in rows_]
            n = len(xs)
            mx, my = sum(xs) / n, sum(ys) / n
            sxx = sum((x - mx) ** 2 for x in xs)
            b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0
            return f'{my - b * mx:.1f}+{b:.2f}m n{n}'
        table('a new shape file (ms over a calm frame = a + b x materials)', names, [('fit', each(shape_fit))])

    def collisions(g):
        log = g.get('collisionLog') or []
        if isinstance(log, dict):
            log = list(log.values())
        return log
    table('collision rebuilds', names, [
        ('rebuilds', each(lambda g: g.get('collisionReloads'))),
        ('ms summed', each(lambda g: g.get('collisionMsSum'), 0)),
        ('mean ms (driving)', each(lambda g: sum(r[1] for r in collisions(g)) / len(collisions(g)))),
        ('kept scene k tris', each(lambda g: sum((r[4].get('scene') or 0) for r in collisions(g)) / len(collisions(g)), 0)),
        ('kept road k tris', each(lambda g: sum((r[4].get('road') or 0) for r in collisions(g)) / len(collisions(g)), 0)),
        ('frames >100: collision', each(lambda g: (g.get('slow100') or {}).get('lua:collision', [0])[0])),
        ('frames >100: vehicle Lua', each(lambda g: (g.get('slow100') or {}).get('engine:PhysicsAndVLUA', [0])[0])),
    ])
    stages = {}
    for g in games:
        for name, ms in ((g.get('native') or {}).get('pool') or {}).get('stages', {}).items():
            stages[name] = max(stages.get(name, 0), ms)
    top = [n for n, ms in sorted(stages.items(), key=lambda kv: -kv[1])][:10]
    pool = lambda g: g['native']['pool']  # noqa: E731
    table('the worker pool', names, [
        ('jobs sent', each(lambda g: pool(g)['sent'])),
        ('done', each(lambda g: pool(g)['done'])),
        ('cancelled', each(lambda g: pool(g)['cancelled'])),
        ('parked / went on', each(lambda g: f"{pool(g).get('parks', 0)} / {pool(g).get('resumed', 0)}")),
        ('parked, then dropped', each(lambda g: pool(g).get('parkedDropped', 0))),
        ('work s', each(lambda g: pool(g)['busyMs'] / 1000)),
        ('work a done job, s', each(lambda g: pool(g)['busyMs'] / 1000 / pool(g)['done'], 2)),
        ('longest slice ms', each(lambda g: pool(g)['longest'], 0)),
        ('longer slices / their extra s', each(lambda g: f"{pool(g).get('boosts', 0)} / {pool(g).get('boostMs', 0) / 1000:.1f}")),
        ('ticks', each(lambda g: pool(g)['slices'])),
        ('  asked ms a tick', each(lambda g: pool(g)['askedMs'] / pool(g)['slices'], 2)),
        ('  build ms a tick', each(lambda g: pool(g)['busyMs'] / pool(g)['slices'], 2)),
        ('  collector ms a tick', each(lambda g: pool(g)['gcMs'] / pool(g)['slices'], 2)),
        ('  ticks <=1.5 / 3 / 6 / over, %', each(lambda g: ' '.join(f"{v * 100 / pool(g)['slices']:.0f}" for v in (
            pool(g)['ticks'].values() if isinstance(pool(g)['ticks'], dict) else pool(g)['ticks'])))),
    ] + [(f'  {n} s', each(lambda g, n=n: pool(g)['stages'].get(n, 0) / 1000)) for n in top])
    table('ahead of the car (share of frames without it)', names, [
        ('road 4 / 8 / 12 s, %', each(lambda g: ' '.join(f"{g['ahead'][k] * 100 / g['ahead']['frames']:.1f}" for k in ('road4', 'road8', 'road12')))),
        ('scene 4 / 8 / 12 s, %', each(lambda g: ' '.join(f"{g['ahead'][k] * 100 / g['ahead']['frames']:.1f}" for k in ('scene4', 'scene8', 'scene12')))),
        ('ground 2 km, %', each(lambda g: g['ahead']['ground2km'] * 100 / g['ahead']['frames'])),
        ('scenes on time / behind', each(lambda g: f"{g.get('scenesOnTime', 0)} / {g.get('scenesBehind', 0)}")),
        ('Lua errors', each(lambda g: g.get('errors', 0))),
    ])


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
