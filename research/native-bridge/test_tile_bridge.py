"""Exercise the experimental DLL and framed tile protocol outside BeamNG."""
import argparse
import ctypes
import gzip
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
from bench_native import runtime  # noqa: E402
from bench_roofs import pack, unpack  # noqa: E402
from lupa.luajit21 import LuaRuntime  # noqa: E402


def read_exact(sock, n):
    chunks = bytearray()
    while len(chunks) < n:
        data = sock.recv(n-len(chunks))
        if not data:
            raise EOFError('bridge closed the connection')
        chunks.extend(data)
    return bytes(chunks)


def lua_client_roundtrip(dll, cells, buildings, rect, expected):
    """Run the Lua cell adapter and client over a real nonblocking socket."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        if dll.earthng_probe(str(root/'marker.txt')) != 0:
            raise RuntimeError('second bridge did not start')
        deadline = time.monotonic()+10
        while not (root/'bench-port.txt').exists():
            if time.monotonic()>deadline:
                raise TimeoutError('second bridge did not publish its port')
            time.sleep(.02)
        sock = socket.create_connection(('127.0.0.1', int((root/'bench-port.txt').read_text())), timeout=10)
        sock.setblocking(False)
        lua = LuaRuntime(encoding=None, unpack_returned_tuples=True)
        client = lua.execute((ROOT/'mod/lua/ge/extensions/e2r/rust_tile_client.lua').read_bytes())
        roofs = lua.execute((ROOT/'mod/lua/ge/extensions/e2r/rust_tile_roofs.lua').read_bytes())
        roads = lua.execute((ROOT/'mod/lua/ge/extensions/e2r/rust_tile_roads.lua').read_bytes())

        def lua_value(value):
            if isinstance(value, dict):
                return lua.table_from({k.encode(): lua_value(v) for k,v in value.items()})
            if isinstance(value, list):
                return lua.table_from([lua_value(v) for v in value])
            return value.encode() if isinstance(value, str) else value

        lua_cells = lua_value(cells)

        def send(data, start):
            try:
                count = sock.send(data[start-1:])
            except BlockingIOError:
                return None, b'timeout', start-1
            last = start+count-1
            return last if last == len(data) else (None, b'timeout', last)

        def receive(count):
            try:
                data = sock.recv(count)
            except BlockingIOError:
                return None, b'timeout', b''
            if not data:
                return None, b'closed', b''
            return data if len(data) == count else (None, b'timeout', data)

        g = lua.globals()
        g.py_send, g.py_receive, g.py_close = send, receive, sock.close
        adapter = lua.execute(b'''return {
          send=function(_,data,start) return py_send(data,start) end,
          receive=function(_,n) return py_receive(n) end,
          close=function() py_close() end,
          settimeout=function() end, setoption=function() end,
          connect=function() return true end,
        }''')
        lua.globals().clientModule = client
        lua.globals().roofModule = roofs
        lua.globals().roadModule = roads
        lua.globals().socketAdapter = adapter
        lua.execute(b'''local old = require
          require = function(name)
            if name == 'ge/extensions/e2r/rust_tile_client' then return clientModule end
            if name == 'ge/extensions/e2r/rust_tile_roofs' then return roofModule end
            if name == 'ge/extensions/e2r/rust_tile_roads' then return roadModule end
            if name == 'socket' then return {tcp=function() return socketAdapter end} end
            return old(name)
          end''')
        runtime = lua.execute((ROOT/'mod/lua/ge/extensions/e2r/rust_tile_runtime.lua').read_bytes())
        job = runtime[b'begin'](lua_cells, lua_value(rect), True,
                                 lua_value({'enabled':True,'port':1234,'workers':4}), 5)
        assert job is not None, 'runtime did not start the tile job'
        deadline = time.monotonic()+10
        try:
            while time.monotonic()<deadline:
                runtime[b'pump'](job)
                if job[b'done']:
                    assert job[b'error'] is None, f'Lua client error: {job[b"error"]!r}'
                    cache, index, seen = job[b'provider'], 0, set()
                    for ci, cell in enumerate(cells,1):
                        for bi, building in enumerate(cell.get('buildings',[]),1):
                            key = str(building.get('id',bi))
                            if key in seen:
                                continue
                            seen.add(key)
                            result = cache[lua_cells[ci][b'buildings'][bi]]
                            got = [[tuple(result[ti][vi][axis] for axis in (1,2,3))
                                    for vi in (1,2,3)] for ti in range(1,len(result)+1)]
                            assert got == expected[index], f'Lua adapter mismatch for {key}'
                            index += 1
                    assert index == len(expected)
                    assert job[b'hits'] == index
                    runtime[b'finish'](job)
                    print(json.dumps({'lua_client': 'equal', 'job': job[b'id'], 'epoch': 5,
                                      'lod': 1, 'buildings': index}))
                    # A new connection uses the real runtime road adapter. The
                    # prepared mapping may be replaced as the generator advances.
                    sock=socket.create_connection(('127.0.0.1', int((root/'bench-port.txt').read_text())), timeout=10)
                    sock.setblocking(False)
                    road=lua_value({'id':'bend'})
                    prepared=lua.table()
                    prepared[road]=lua_value({'points':[[0,0],[10,0],[10,10]],
                                               'joints':[[0,1,1.5],None]})
                    road_job=runtime[b'beginRoad'](job,prepared,lua.table_from([road]),2.)
                    assert road_job is not None
                    prepared[road]=lua.table_from([1,2,3])
                    road_deadline=time.monotonic()+10
                    while time.monotonic()<road_deadline and not road_job[b'done']:
                        runtime[b'pump'](road_job);time.sleep(.001)
                    assert road_job[b'done'] and road_job[b'error'] is None
                    normals,dist=runtime[b'roadResult'](road_job,road)
                    assert abs(normals[1][1]+1.5)<1e-12
                    assert abs(normals[2][1]+1.)<1e-12 and abs(normals[2][2]-1.)<1e-12
                    assert [dist[k] for k in (1,2,3)]==[0.,10.,20.]
                    runtime[b'finish'](road_job)
                    print(json.dumps({'lua_road_adapter':'equal','road_job':road_job[b'id']}))
                    break
                time.sleep(.001)
            else:
                raise TimeoutError('Lua client did not finish')
        finally:
            sock.close()
            (root/'bench-stop').write_text('1',encoding='ascii')
            time.sleep(.05)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dll', type=Path, required=True)
    p.add_argument('--fixture', type=Path, required=True)
    p.add_argument('--pack', type=Path, required=True)
    a = p.parse_args()
    with gzip.open(a.fixture, 'rt', encoding='utf8') as f:
        fixture = json.load(f)
    seen, buildings = set(), []
    for cell in fixture['cells']:
        for i, b in enumerate(cell.get('buildings', []), 1):
            key = str(b.get('id', i))
            if key not in seen:
                seen.add(key)
                buildings.append(b)
    size = fixture['options']['tileSize']
    i, j = fixture['tile']['i'], fixture['tile']['j']
    rect = [i*size,j*size,(i+1)*size,(j+1)*size]
    lua, mods, _ = runtime(a.pack)

    def table(value):
        if isinstance(value, (list, tuple)):
            return lua.table_from([table(v) for v in value])
        return value

    dll = ctypes.WinDLL(str(a.dll.resolve()))
    dll.earthng_probe.argtypes = [ctypes.c_wchar_p]
    dll.earthng_probe.restype = ctypes.c_uint32
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        if dll.earthng_probe(str(root/'marker.txt')) != 0:
            raise RuntimeError('bridge did not start')
        deadline = time.monotonic()+10
        while not (root/'bench-port.txt').exists():
            if time.monotonic()>deadline:
                raise TimeoutError('bridge did not publish its port')
            time.sleep(.02)
        for lod in (0, 1):
            with socket.create_connection(('127.0.0.1', int((root/'bench-port.txt').read_text())), timeout=10) as sock:
                body = pack(buildings, rect, 4, far=bool(lod))
                request = b'ETB1' + struct.pack('<QQII', 41+lod, 3, lod, len(body)) + body
                sock.sendall(struct.pack('<I',len(request)) + request)
                size, = struct.unpack('<I', read_exact(sock,4))
                reply = read_exact(sock,size)
                magic, job, epoch, got_lod, length = struct.unpack('<4sQQII',reply[:28])
                assert (magic,job,epoch,got_lod,length) == (b'ETC1',41+lod,3,lod,len(reply)-28)
                triangles, _ = unpack(reply[28:], len(buildings))
                if lod == 1:
                    far_triangles = triangles
                compared = 0
                for building, got in zip(buildings, triangles):
                    rings = building['rings']
                    if lod:
                        points = [p for ring in rings for p in ring]
                        if not points:
                            rings = []
                        else:
                            x0,y0 = min(p[0] for p in points),min(p[1] for p in points)
                            x1,y1 = max(p[0] for p in points),max(p[1] for p in points)
                            rings = [[[x0,y0,0],[x1,y0,0],[x1,y1,0],[x0,y1,0]]]
                    expected = mods['generator'].triangulate(table(rings),None,table(rect))
                    assert len(got) == len(expected)
                    for ti, triangle in enumerate(got,1):
                        for vi, point in enumerate(triangle,1):
                            for axis, value in enumerate(point,1):
                                assert abs(value-expected[ti][vi][axis]) < 1e-8
                    compared += len(got)
                print(json.dumps({'lod': lod, 'job': job, 'epoch': epoch,
                                  'buildings': len(buildings), 'triangles': compared, 'result': 'equal'}))
        # A dropped/finished tile must not shut down the listener for the next one.
        with socket.create_connection(('127.0.0.1', int((root/'bench-port.txt').read_text())), timeout=10) as sock:
            body = pack([], rect, 1)
            request = b'ETB1' + struct.pack('<QQII', 99, 4, 0, len(body)) + body
            sock.sendall(struct.pack('<I',len(request)) + request)
            n, = struct.unpack('<I',read_exact(sock,4))
            reply = read_exact(sock,n)
            assert reply[:4] == b'ETC1' and struct.unpack_from('<Q',reply,4)[0] == 99
        # Road strip and wall splitting use the same tile identity envelope.
        road=(b'ERD1'+struct.pack('<II',2,1)+struct.pack('<IId6d',3,0,2.,*[0.]*6)
              +struct.pack('<6d',0.,0.,10.,0.,10.,10.))
        wall=(b'EWP1'+struct.pack('<II',2,1)+struct.pack('<II7d',7,1,0.,0.,1.,10.,0.,2.,10.)
              +struct.pack('<3d',2.,5.,7.))
        for job, body, magic in [(100,road,b'ERR1'),(101,wall,b'EWR1')]:
            with socket.create_connection(('127.0.0.1', int((root/'bench-port.txt').read_text())), timeout=10) as sock:
                request=b'ETB1'+struct.pack('<QQII',job,4,0,len(body))+body
                sock.sendall(struct.pack('<I',len(request))+request)
                n,=struct.unpack('<I',read_exact(sock,4)); reply=read_exact(sock,n)
                assert reply[:4]==b'ETC1' and struct.unpack_from('<Q',reply,4)[0]==job
                assert reply[28:32]==magic and struct.unpack_from('<I',reply,32)[0]==1
                assert struct.unpack_from('<I',reply,36)[0]==3
        (root/'bench-stop').write_text('1',encoding='ascii')
        time.sleep(.05)
    lua_client_roundtrip(dll, fixture['cells'], buildings, rect, far_triangles)


if __name__ == '__main__':
    main()
