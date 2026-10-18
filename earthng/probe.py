"""Run Lua inside a running test game (the e2rprobe mod, test_world.py --probe).

    python earthng/probe.py --user out/run-01/user "return P.frames(300)"
    python earthng/probe.py --user out/run-01/user -f experiment.lua --timeout 60

The snippet runs once with P (frames, task, ser) in scope; a P.task(fn) result arrives when
fn returns a value. Prints the serialized return value.
"""
import argparse
import json
from pathlib import Path
import sys
import time


def run(user, code, timeout=30.0):
    probe = Path(user) / 'current' / 'e2r_probe'
    probe.mkdir(parents=True, exist_ok=True)
    out = probe / 'out.txt'
    if out.exists():
        out.unlink()
    tmp = probe / 'cmd.tmp'
    tmp.write_text(code, encoding='utf8')
    tmp.replace(probe / 'cmd.txt')
    deadline = time.time() + timeout
    while time.time() < deadline:
        if out.exists():
            time.sleep(0.05)
            text = out.read_text(encoding='utf8', errors='replace')
            out.unlink()
            return text
        time.sleep(0.05)
    return 'TIMEOUT'


def wait_landed(user, timeout):
    """Block until the test profile reports a landing (test_world.py --manual)."""
    path = Path(user) / 'current' / 'e2r-world-result.json'
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if json.loads(path.read_text(encoding='utf8')).get('landedAt'):
                return True
        except (OSError, ValueError):
            pass
        time.sleep(1)
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--user', required=True, type=Path, help='the test user folder (<out>/user)')
    p.add_argument('-f', '--file', type=Path)
    p.add_argument('--timeout', type=float, default=30)
    p.add_argument('--wait-landed', action='store_true', help='first wait (up to --timeout) for the landing')
    p.add_argument('code', nargs='?')
    a = p.parse_args()
    if a.wait_landed:
        if not wait_landed(a.user, a.timeout):
            sys.exit('not landed')
        if not a.code and not a.file:
            print('landed')
            return
    code = a.file.read_text(encoding='utf8') if a.file else a.code
    if not code:
        p.error('code or -f required')
    text = run(a.user, code, a.timeout)
    sys.stdout.write(text + '\n')
    sys.exit(1 if text.startswith(('ERROR', 'COMPILE', 'TIMEOUT')) else 0)


if __name__ == '__main__':
    main()
