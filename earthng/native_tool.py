"""The native Map Builder (rust/): build steps rewritten in Rust, used when the executable is here.

A release ships it as bin/earthng-mapbuilder.exe; a checkout builds it with
`cargo build --release` in rust/. EARTHNG_NATIVE=0 keeps every step in Python.
Each native step writes exactly what the Python step it replaces writes (the cut: the same
objects in every tile, tests in rust/ and earthng/test_native_tool.py).
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = 'earthng-mapbuilder.exe' if os.name == 'nt' else 'earthng-mapbuilder'
CANDIDATES = (ROOT / 'bin' / NAME, ROOT / 'rust' / 'target' / 'release' / NAME)


def tool():
    """Path of the native executable, or None (absent, or switched off by EARTHNG_NATIVE=0)."""
    if os.environ.get('EARTHNG_NATIVE', '1').strip() in ('0', 'no', 'off', 'false'):
        return None
    for path in CANDIDATES:
        if path.is_file():
            return path
    return None


def cut_command(pbf, out, box=None, threads=None):
    """The native tile cut (osm_tiles_country.py's result in one process), or None."""
    exe = tool()
    if exe is None:
        return None
    command = [str(exe), 'cut', str(pbf), '--out', str(out)]
    if threads:
        command += ['--threads', str(threads)]
    if box:
        command += ['--package-box', *(repr(float(v)) for v in box)]
    return command
