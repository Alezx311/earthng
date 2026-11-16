"""One repeatable A/B run of the native world, with or without the experimental Rust bridge.

    .venv/Scripts/python.exe research/native-bridge/ab_run.py --name kyiv-q50-base --scenario kyiv
    .venv/Scripts/python.exe research/native-bridge/ab_run.py --name kyiv-q50-rust --scenario kyiv --bridge out/x.dll

Wraps earthng/test_world.py (isolated profile, replay along a fixed route, same pack, planet,
quality and graphics) and adds what it does not record: the game's CPU time and working set
sampled every second, and, with --bridge, the DLL loaded into that one test process through
loader.py (never a live profile). The bridge config is written into the test profile and put
back while the game's first start cleans unknown settings. summary.json beside report.json
holds the numbers compared in the night report (research/native-bridge/NIGHT_2026-11-16.md).
"""
import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / '.venv' / 'Scripts' / 'python.exe'
PACK = ROOT / 'out' / 'country-setup' / 'earthng_ukraine.zip'
ROUTES = ROOT / 'out' / 'night-1116' / 'routes'
# lat, lon, route: the landing is the route's start (test_world --replay)
SCENARIOS = {
    'kyiv': (50.447734, 30.52218, ROOT / 'out' / 'routes' / 'kyiv-center.json'),
    'yaremche': (48.45306, 24.55611, ROUTES / 'yaremche.json'),
    'pass': (48.3060, 24.4890, ROUTES / 'pass.json'),
}


def find_game(user, timeout):
    """The main BeamNG process started with -userpath <user> (not a CEF child)."""
    end = time.time() + timeout
    want = str(user.resolve()).lower()
    while time.time() < end:
        for p in psutil.process_iter(['name', 'cmdline']):
            try:
                if (p.info['name'] or '').lower() != 'beamng.drive.x64.exe':
                    continue
                cmd = p.info['cmdline'] or []
                if '-userpath' in cmd and not any(c.startswith('--type=') for c in cmd):
                    k = cmd.index('-userpath')
                    if k + 1 < len(cmd) and str(Path(cmd[k + 1]).resolve()).lower() == want:
                        return p
            except (psutil.Error, ValueError):
                pass
        time.sleep(0.3)
    return None


def sampler(proc, out, stop):
    """CPU seconds (user+system, all threads) and working set every second."""
    while not stop.is_set():
        try:
            t = proc.cpu_times()
            m = proc.memory_info()
            out.append([round(time.time(), 2), round(t.user + t.system, 2), m.rss // 2**20, m.private // 2**20,
                        proc.num_threads()])
        except psutil.Error:
            break
        stop.wait(1.0)


def bridge(args, user, game, log):
    """Load the DLL into this test process and point the profile's bridge config at it."""
    current = user / 'current'
    deadline = time.time() + 120
    while not current.exists() and time.time() < deadline:
        time.sleep(0.2)
    work = current / 'e2r_bridge'
    work.mkdir(parents=True, exist_ok=True)
    marker = work / f'marker-{int(time.time() * 1000)}.txt'
    r = subprocess.run([str(PY), str(ROOT / 'research' / 'native-bridge' / 'loader.py'), '--pid', str(game.pid),
                        '--user', str(user), '--dll', str(args.bridge), '--marker', str(marker)],
                       capture_output=True, text=True, timeout=60)
    log['loader'] = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise RuntimeError('loader failed: ' + log['loader'])
    port_file = work / 'bench-port.txt'
    deadline = time.time() + 30
    while not port_file.exists() and time.time() < deadline:
        time.sleep(0.1)
    port = int(port_file.read_text().strip())
    token_file = work / 'bench-token.txt'
    config = {'enabled': True, 'port': port, 'workers': args.workers, 'debug': True}
    if token_file.exists():
        config['token'] = token_file.read_text().strip()
    config.update(json.loads(args.bridge_config) if args.bridge_config else {})
    log['config'] = {k: v for k, v in config.items() if k != 'token'}
    # the tile worker pool (rust_bridge.lua) reads earthng-rust-bridge.json; the older roof/road
    # experiment (rust_tile_runtime.lua) earthng-rust-roofs.json
    settings = current / 'settings' / ('earthng-rust-roofs.json' if args.legacy else 'earthng-rust-bridge.json')
    text = json.dumps(config)
    # the game's first start removes unknown settings: put the file back until the landing
    result = current / 'e2r-world-result.json'
    end = time.time() + args.timeout
    while time.time() < end and game.is_running():
        try:
            landed = result.exists() and json.loads(result.read_text(encoding='utf8')).get('landedAt')
        except (OSError, ValueError):
            landed = False
        if not settings.exists() or settings.read_text(encoding='utf8') != text:
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(text, encoding='utf8')
            log.setdefault('configWrites', []).append(round(time.time(), 2))
        if landed:
            break
        time.sleep(0.25)
    if args.stop_bridge_after is not None and game.is_running():
        # the bridge goes away mid-drive: the game must drop its jobs and carry on in Lua
        time.sleep(args.stop_bridge_after)
        # the game's first start renames current/ to a dated backup and makes a new one; the DLL
        # still watches the old path (current/e2r_bridge), so the folder is made again for the signal
        work.mkdir(parents=True, exist_ok=True)
        (work / 'bench-stop').write_text('stop', encoding='utf8')
        log['stoppedAt'] = round(time.time(), 2)


def percentile(sorted_list, q):
    if not sorted_list:
        return None
    return sorted_list[min(len(sorted_list) - 1, int(q * len(sorted_list)))]


def summarize(out, samples, log):
    report = json.loads((out / 'report.json').read_text(encoding='utf8')) if (out / 'report.json').exists() else {}
    g = report.get('game', {})
    drive = g.get('driveFrames') or {}
    native = g.get('native') or {}
    final = (g.get('loadReal') or {}).get('final') or {}
    cpu = None
    if len(samples) > 1:
        span = samples[-1][0] - samples[0][0]
        cpu = {'seconds': round(samples[-1][1] - samples[0][1], 1), 'wallSeconds': round(span, 1),
               'meanCores': round((samples[-1][1] - samples[0][1]) / span, 2) if span > 0 else None,
               'peakRssMb': max(s[2] for s in samples), 'peakPrivateMb': max(s[3] for s in samples),
               'peakThreads': max(s[4] for s in samples)}
    s = {
        'status': report.get('status'), 'failures': g.get('failures'),
        'landSeconds': (g['landedAt'] - g['landRequestedAt']) if g.get('landedAt') and g.get('landRequestedAt') else None,
        'landedAt': g.get('landedAt'), 'spawnSeconds': g.get('spawnSeconds'),
        'landNativeMs': final.get('nativeMs'), 'landBuilt': final.get('built'), 'landHeapKb': final.get('heapKb'),
        'drive': {k: drive.get(k) for k in ('frames', 'meanFrameMs', 'p50FrameMs', 'p95FrameMs', 'p99FrameMs',
                                            'worstFrameMs', 'over33', 'over100', 'slowPairs15', 'slowPairs2')},
        'roadMissFrames': g.get('roadMissFrames', 0), 'deadlineMisses': len(g.get('deadlineMisses') or []),
        'sceneMissFrames': g.get('sceneMissFrames', 0), 'sceneViewMissFrames': g.get('sceneViewMissFrames', 0),
        'wallMissFrames': g.get('wallMissFrames', 0), 'replayDistanceM': g.get('replayDistanceM'),
        'built': native.get('built'), 'rebuilds': native.get('rebuilds'),
        'stageMs': native.get('stageMs'), 'spentMs': native.get('spentMs'),
        'rust': native.get('rust'),
        'collisionMsSum': g.get('collisionMsSum'), 'collisionReloads': g.get('collisionReloads'),
        'luaGarbageKbPerFrame': (g.get('luaProfile') or {}).get('garbageKbPerFrame'),
        'cpu': cpu, 'peakPrivateMbTestWorld': report.get('peak_private_mb'), 'bridge': log,
    }
    (out / 'summary.json').write_text(json.dumps(s, indent=2), encoding='utf8')
    (out / 'cpu.json').write_text(json.dumps(samples), encoding='utf8')
    return s


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--name', required=True)
    p.add_argument('--scenario', choices=sorted(SCENARIOS), required=True)
    p.add_argument('--planet', type=Path, help='planet ZIP; default: build from mod/ (test_world)')
    p.add_argument('--quality', type=int, default=50)
    p.add_argument('--graphics', default='Normal')
    p.add_argument('--speed', type=float, default=40)
    p.add_argument('--drive-seconds', type=float, default=75)
    p.add_argument('--timeout', type=int, default=600)
    p.add_argument('--bridge', type=Path, help='experimental bridge DLL to load into the test process')
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--bridge-config', help='extra JSON merged into the bridge config')
    p.add_argument('--legacy', action='store_true', help='the older roof/road bridge config instead of the tile pool')
    p.add_argument('--stop-bridge-after', type=float, help='stop the bridge this many seconds after the landing (fallback test)')
    p.add_argument('--root', type=Path, default=ROOT / 'out' / 'night-1116' / 'runs')
    p.add_argument('--extra', nargs=argparse.REMAINDER, default=[], help='more test_world.py arguments')
    a = p.parse_args()
    lat, lon, route = SCENARIOS[a.scenario]
    out = (a.root / a.name).resolve()
    a.root.mkdir(parents=True, exist_ok=True)
    cmd = [str(PY), str(ROOT / 'earthng' / 'test_world.py'), '--out', str(out), '--mod', str(PACK),
           '--lat', str(lat), '--lon', str(lon), '--route', str(route), '--replay', '--speed', str(a.speed),
           '--drive-seconds', str(a.drive_seconds), '--quality', str(a.quality), '--graphics', a.graphics,
           '--resolution', '1280x720', '--timeout', str(a.timeout)]
    if a.planet:
        cmd += ['--planet', str(a.planet.resolve())]
    cmd += a.extra
    for proc in psutil.process_iter(['name']):
        if (proc.info['name'] or '').lower().startswith('beamng'):
            raise SystemExit('another BeamNG process is running: timings would be contaminated')
    started = time.time()
    run = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log, samples, stop = {'cmd': cmd, 'started': started}, [], threading.Event()
    lines = []
    reader = threading.Thread(target=lambda: lines.extend(run.stdout), daemon=True)
    reader.start()
    game = find_game(out / 'user', 300)
    worker = None
    if game:
        worker = threading.Thread(target=sampler, args=(game, samples, stop), daemon=True)
        worker.start()
        if a.bridge:
            try:
                bridge(a, out / 'user', game, log)
            except Exception as e:  # the run continues on Lua: record why
                log['error'] = repr(e)
    else:
        log['error'] = 'game process not found'
    run.wait()
    stop.set()
    if worker:
        worker.join(5)
    reader.join(5)
    (out / 'test_world.txt').write_text(''.join(lines), encoding='utf8')
    log['seconds'] = round(time.time() - started, 1)
    s = summarize(out, samples, log)
    print(json.dumps({k: s[k] for k in ('status', 'landSeconds', 'landNativeMs', 'drive', 'roadMissFrames',
                                         'deadlineMisses', 'sceneMissFrames', 'sceneViewMissFrames', 'cpu')}, indent=1))


if __name__ == '__main__':
    sys.exit(main())
