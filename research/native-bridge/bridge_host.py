"""Host the tile-pool DLL in a process of its own for the lupa stand (test_tile_pool.py).

    python research/native-bridge/bridge_host.py <dll> <marker>

In the stand's own process the DLL's vendored LuaJIT sat beside lupa's: the stand crashed
(access violations mid-landing and at exit, out/night-1116/parity3..4) once the DLL's workers
ran with the game's JIT options. Here the DLL starts its listener (earthng_probe writes
bench-port.txt and bench-token.txt next to the marker) and this process waits until stdin
closes or bench-stop appears; the stand talks to it over TCP as the game does.
"""
import ctypes
import sys
import threading
import time
from pathlib import Path


def main(dll, marker):
    marker = Path(marker)
    lib = ctypes.WinDLL(str(dll))
    lib.earthng_probe.argtypes = [ctypes.c_wchar_p]
    lib.earthng_probe.restype = ctypes.c_uint32
    code = lib.earthng_probe(str(marker))
    if code != 0:
        print('earthng_probe returned', code, flush=True)
        return 1
    closed = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.read(), closed.set()), daemon=True).start()
    stop = marker.parent / 'bench-stop'
    while not closed.is_set() and not stop.exists():
        time.sleep(0.2)
    stop.write_text('stop', encoding='utf8')
    time.sleep(1.0)   # the listener sees the signal every 0.5 s and closes its session
    return 0


if __name__ == '__main__':
    import os
    code = main(sys.argv[1], sys.argv[2])
    sys.stdout.flush()
    os._exit(code)   # no interpreter teardown under the DLL's running threads
