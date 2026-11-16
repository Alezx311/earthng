"""Sample the isolated BeamNG main process until exit (CPU % uses one core = 100%)."""
import argparse
import json
from pathlib import Path
import time
import psutil

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid', type=int, required=True)
    p.add_argument('--user', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--phase', type=Path, help='optional file with the current benchmark phase')
    p.add_argument('--interval', type=float, default=.25)
    a = p.parse_args()
    proc = psutil.Process(a.pid)
    cmd = proc.cmdline()
    if proc.name().lower() != 'beamng.drive.x64.exe' or '-userpath' not in cmd or any(x.startswith('--type=') for x in cmd):
        raise SystemExit('Expected the main BeamNG test process')
    if Path(cmd[cmd.index('-userpath')+1]).resolve() != a.user.resolve():
        raise SystemExit('User path mismatch')
    if a.out.exists():
        raise SystemExit('Refusing to overwrite existing output')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    proc.cpu_percent(None)
    psutil.cpu_percent(None, percpu=True)
    start = time.perf_counter()
    with a.out.open('x', encoding='utf-8') as f:
        while proc.is_running():
            time.sleep(a.interval)
            try:
                mem = proc.memory_info()
                row = {'elapsed_s': round(time.perf_counter()-start, 3), 'process_cpu_one_core_pct': proc.cpu_percent(None),
                       'system_core_pct': psutil.cpu_percent(None, percpu=True), 'threads': proc.num_threads(),
                       'rss_bytes': mem.rss, 'private_bytes': getattr(mem, 'private', None)}
                if a.phase:
                    try: row['phase'] = a.phase.read_text(encoding='utf-8').strip()
                    except OSError: row['phase'] = ''
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                break
            f.write(json.dumps(row) + '\n'); f.flush()

if __name__ == '__main__':
    main()
