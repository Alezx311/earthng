"""Parity and timing of the Rust tile worker pool, offline (not a game test).

    .venv/Scripts/python.exe research/native-bridge/test_tile_pool.py --lat 50.447734 --lon 30.52218

Loads research/native-bridge/bridge's DLL into this Python process (its listener thread runs
here, as it would in the game), then lands twice with native.lua in lupa (earthng/bench_native
runtime, the game's vec3 as FFI structs): once with the Lua builder alone, once with the bridge
config on, so eligible near tiles go through rust_bridge.lua over a real local socket to the
worker VMs and back through bridge_codec and DELIVER. Each landing tile's road, scene and nav are
compared as canonical bridge_codec bytes (sorted keys): equal bytes = equal manifests.
Optionally --drive moves the pose along a straight line to exercise road/scene early parts.
"""
import argparse
import ctypes
import hashlib
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
import bench_native  # noqa: E402

DLL = ROOT / 'research' / 'native-bridge' / 'bridge' / 'target' / 'release' / 'earthng_bridge.dll'
LUA_DIR = ROOT / 'mod' / 'lua' / 'ge' / 'extensions' / 'e2r'

SHIM = r'''
local ffi = package.loaded.ffi or require('ffi')
local function ptr(s) local n = #s; local buf = ffi.new('uint8_t[?]', math.max(1, n)); ffi.copy(buf, s, n)
  return buf, tonumber(ffi.cast('uintptr_t', buf)), n end
socketShim = {tcp = function()
  local h = py_tcp_new()
  local o = {}
  function o:settimeout(t) py_tcp_settimeout(h, t) end
  function o:connect(host, port) return py_tcp_connect(h, host, port) end
  function o:setoption() return true end
  function o:send(s, i) local buf, addr, n = ptr(s); local a, b, c = py_tcp_send(h, addr, n, i or 1); buf = nil; return a, b, c end
  function o:receive(n) return py_tcp_receive(h, n) end
  function o:close() py_tcp_close(h) end
  return o
end}
function bytesOf(s) local buf, addr, n = ptr(s); keepAlive = buf; return addr, n end
local oldExists, oldJson, oldOpen = FS.fileExists, jsonReadFile, io.open
FS.fileExists = function(self, p)
  if p == 'settings/earthng-rust-bridge.json' then return BRIDGE_CONFIG ~= nil end
  if type(p) == 'string' and p:sub(1, 16) == '/earthng/planet/' then return py_planet_has(p) end
  if type(p) == 'string' and p:sub(1, 12) == '/e2r_stream/' then return true end
  return oldExists(self, p)
end
jsonReadFile = function(p)
  if p == 'settings/earthng-rust-bridge.json' then return BRIDGE_CONFIG end
  return oldJson(p)
end
io.open = function(p, mode)
  if type(p) == 'string' and p:sub(1, 16) == '/earthng/planet/' then
    local data = py_planet(p)
    if not data then return nil end
    local pos = 1
    return {read = function(_, n)
      if n == '*a' or n == nil then local c = data:sub(pos); pos = #data + 1; return c end
      if pos > #data then return nil end
      local last = math.min(#data, pos + n - 1)
      local c = data:sub(pos, last); pos = last + 1
      return c
    end, close = function() end}
  end
  if type(p) == 'string' and p:sub(1, 5) == '/lua/' then
    local data = py_source(p)
    if not data then return nil end
    return {read = function() return data end, close = function() end}
  end
  return oldOpen(p, mode)
end
'''

CAPTURE = r'''
local native, codec, keys = ...
local function upvalue(f, name)
  for k = 1, 300 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
local active = upvalue(native.update, 'active')
local out = {}
local ffi = package.loaded.ffi
captureKeep = {}
local function B(v)
  local n = #v
  local buf = ffi.new('uint8_t[?]', math.max(1, n)); ffi.copy(buf, v, n)
  captureKeep[#captureKeep + 1] = buf
  return {tonumber(ffi.cast('uintptr_t', buf)), n}
end
for _, key in ipairs(keys) do
  local e = active.tiles[key]
  if e then
    out[key] = {road = e.road and B(codec.encode(e.road, true)), scene = e.scene and B(codec.encode(e.scene, true)),
      nav = e.nav and B(codec.encode(e.nav, true)), grass = e.grass and B(codec.encode(e.grass, true))}
  end
end
return out
'''


class Sockets:
    def __init__(self):
        self.s = {}
        self.n = 0

    def new(self):
        self.n += 1
        self.s[self.n] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        return self.n

    def settimeout(self, h, t):
        self.s[h].settimeout(None if t is None else float(t))

    def connect(self, h, host, port):
        try:
            self.s[h].connect((host.decode() if isinstance(host, bytes) else host, int(port)))
            return 1
        except OSError as e:
            return None, str(e)

    def send(self, h, addr, n, i):
        data = ctypes.string_at(addr, n)
        i = int(i)
        try:
            sent = self.s[h].send(data[i - 1:])
            return i - 1 + sent
        except (BlockingIOError, socket.timeout):
            return None, 'timeout', i - 1
        except OSError as e:
            return None, 'closed', i - 1

    def receive(self, h, n):
        n = int(n)
        got = b''
        sock = self.s[h]
        while len(got) < n:
            try:
                chunk = sock.recv(n - len(got))
            except (BlockingIOError, socket.timeout):
                return None, 'timeout', got
            except OSError:
                return None, 'closed', got
            if not chunk:
                return None, 'closed', got
            got += chunk
        return got

    def close(self, h):
        self.s[h].close()


def start_bridge(pack, planet):
    work = Path(tempfile.mkdtemp(prefix='e2r-pool-'))
    mods = work / 'current' / 'mods'
    mods.mkdir(parents=True)
    for z in (pack, planet):
        try:
            os.link(z, mods / Path(z).name)
        except OSError:
            import shutil
            shutil.copy2(z, mods / Path(z).name)
    bridge = work / 'current' / 'e2r_bridge'
    bridge.mkdir()
    # the DLL in a process of its own (bridge_host.py): its LuaJIT beside lupa's crashed the stand
    import subprocess
    lib = subprocess.Popen([sys.executable, str(Path(__file__).with_name('bridge_host.py')), str(DLL),
                            str(bridge / 'marker.txt')], stdin=subprocess.PIPE)
    for _ in range(200):
        if (bridge / 'bench-port.txt').exists() and (bridge / 'bench-token.txt').exists():
            break
        if lib.poll() is not None:
            raise SystemExit(f'bridge host exited with {lib.returncode}')
        time.sleep(0.05)
    port = int((bridge / 'bench-port.txt').read_text())
    token = (bridge / 'bench-token.txt').read_text()
    return lib, port, token, work


def land(pack, lat, lon, config, budget, drive, timeout, planet):
    import zipfile
    lua, mods, _ = bench_native.runtime(pack, game_structs=True)
    g = lua.globals()
    pz = zipfile.ZipFile(planet)
    pnames = set(pz.namelist())
    def key(p):
        return (p.decode() if isinstance(p, bytes) else p).lstrip('/')
    g.py_planet_has = lambda p: key(p) in pnames
    g.py_planet = lambda p: pz.read(key(p)) if key(p) in pnames else None
    socks = Sockets()
    g.py_tcp_new, g.py_tcp_settimeout, g.py_tcp_connect = socks.new, socks.settimeout, socks.connect
    g.py_tcp_send, g.py_tcp_receive, g.py_tcp_close = socks.send, socks.receive, socks.close
    def source(p):
        p = p.decode() if isinstance(p, bytes) else p
        f = ROOT / 'mod' / p.lstrip('/')
        return f.read_bytes() if f.exists() else None
    g.py_source = source
    lua.execute(SHIM)
    if config:
        g.BRIDGE_CONFIG = lua.table_from(config)
    load = lua.eval('function(source, name) return assert(load(source, "@" .. name))() end')
    g.mods['socket'] = g.socketShim
    lua.execute("mods.ffi = package.loaded.ffi")
    # the game has these: the climate (biome.lua, from the planet) and knock.lua's warm shapes;
    # the generator is loaded again so it finds them, as in the game and in a worker VM
    for name in ('biome', 'knock', 'generator', 'bridge_codec', 'rust_bridge'):
        g.mods[name] = load((LUA_DIR / f'{name}.lua').read_text(encoding='utf8'), f'{name}.lua')
    native = load((LUA_DIR / 'native.lua').read_text(encoding='utf8'), 'native.lua')
    t0 = time.perf_counter()
    job = native.land(lua.table_from({'seq': 1, 'lat': lat, 'lon': lon}))
    if job.state == 'error':
        raise SystemExit(job.message)
    frames = 0
    land_s = None
    pose = native.status().stream
    x0 = y0 = None
    while time.perf_counter() - t0 < timeout:
        native.update(1 / 60, budget)
        frames += 1
        st = native.status()
        if st.job.state == 'error':
            raise SystemExit(st.job.message)
        if st.job.state == 'ready' and land_s is None:
            land_s = time.perf_counter() - t0
            if not drive:
                break
        if land_s is not None and drive:
            break
        if config:
            time.sleep(0.001)
    rust = native.status().stream.rust
    up = lua.eval('''function(native, name)
      for k = 1, 300 do local n, v = debug.getupvalue(native.update, k); if not n then return end; if n == name then return v end end
    end''')
    active = up(native, 'active')
    keys = sorted(k for k in active.landing.required.keys())
    capture = lua.execute(CAPTURE, native, g.mods['bridge_codec'], lua.table_from(keys))
    digests = {}
    for key in keys:
        entry = capture[key]
        if entry is None:
            digests[key] = None
            continue
        d = {}
        for layer in ('road', 'scene', 'nav', 'grass'):
            v = entry[layer]
            if v is None:
                continue
            addr, n = int(v[1]), int(v[2])
            blob = ctypes.string_at(addr, n)
            d[layer] = (n, hashlib.sha256(blob).hexdigest()[:16])
            if DUMP:
                DUMP.mkdir(parents=True, exist_ok=True)
                (DUMP / f'{key}-{layer}.emc').write_bytes(blob)
        digests[key] = d
    stats = None
    if rust is not None:
        stats = {k: (dict(v) if hasattr(v, 'items') and not isinstance(v, (int, float, str, bytes)) else v)
                 for k, v in rust.items()}
        stats = json.loads(json.dumps(stats, default=lambda o: dict(o.items()) if hasattr(o, 'items') else str(o)))
    return {'landSeconds': land_s, 'frames': frames, 'digests': digests, 'rust': stats}


DUMP = None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--pack', default=str(ROOT / 'out' / 'country-setup' / 'earthng_ukraine.zip'))
    p.add_argument('--planet', default=str(ROOT / 'out' / 'night-1116' / 'planet-base' / 'earthng_planet.zip'))
    p.add_argument('--lat', type=float, default=50.447734)
    p.add_argument('--lon', type=float, default=30.52218)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--budget', type=float, default=100)
    p.add_argument('--timeout', type=float, default=600)
    p.add_argument('--skip-lua', action='store_true')
    p.add_argument('--skip-rust', action='store_true')
    p.add_argument('--out', type=Path)
    p.add_argument('--dump', type=Path, help='write each canonical layer encoding here (<tile>-<layer>.emc)')
    a = p.parse_args()
    global DUMP
    DUMP = a.dump
    # Python's cyclic collector crashed the stand inside lupa (faulthandler: access violation while
    # "Garbage-collecting", no Python frame), mid-landing or at exit, with or without the DLL in the
    # process (parity5). The Lua heap has its own collector; the Python wrappers are few.
    import gc
    gc.disable()
    lib, port, token, work = start_bridge(a.pack, a.planet)

    def finish(rc):
        # skip lupa's teardown at exit (the same crash); the bridge host goes with its stdin
        sys.stdout.flush()
        lib.stdin.close()
        lib.wait(15)
        os._exit(rc)
    config = {'enabled': True, 'port': port, 'token': token, 'workers': a.workers}
    res = {}
    if not a.skip_rust:
        res['rust'] = land(a.pack, a.lat, a.lon, config, a.budget, False, a.timeout, a.planet)
    else:
        res['rust'] = {'digests': {}, 'landSeconds': None, 'rust': None}
    if not a.skip_lua:
        print('lua landing', flush=True)
        res['lua'] = land(a.pack, a.lat, a.lon, None, a.budget, False, a.timeout, a.planet)
    bridge_log = work / 'current' / 'e2r_bridge' / 'bridge-log.txt'
    res['bridgeLog'] = bridge_log.read_text() if bridge_log.exists() else None
    same = diff = 0
    if 'lua' in res:
        for key, d in res['lua']['digests'].items():
            r = res['rust']['digests'].get(key)
            for layer, v in (d or {}).items():
                if r and r.get(layer) == v:
                    same += 1
                else:
                    diff += 1
                    print('DIFF', key, layer, v, r and r.get(layer))
    res['parity'] = {'same': same, 'diff': diff}
    print(json.dumps({'rustLand': res['rust']['landSeconds'], 'luaLand': res.get('lua', {}).get('landSeconds'),
                      'parity': res['parity'], 'rust': res['rust']['rust']}, indent=1, default=str)[:4000])
    if a.out:
        a.out.write_text(json.dumps(res, indent=1, default=str), encoding='utf8')
    finish(0 if diff == 0 else 1)


if __name__ == '__main__':
    sys.exit(main())
