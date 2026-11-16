"""Compare experimental roof triangulation to production Lua on a real Kyiv fixture."""
import argparse
import gzip
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'earthng'))
from bench_native import runtime  # noqa: E402

def pack(buildings,rect,workers,far=False):
    out=bytearray(b'EFG1' if far else b'ETG1')
    out.extend(struct.pack('<II4d',workers,len(buildings),*rect))
    for b in buildings:
        rings=b['rings']; out.extend(struct.pack('<I',len(rings)))
        for ring in rings:
            out.extend(struct.pack('<I',len(ring)))
            for p in ring:
                if len(p)!=3 or not all(math.isfinite(x) for x in p): raise ValueError('requires finite XYZ vertices')
                out.extend(struct.pack('<3d',*p))
    return out

def unpack(data,count):
    if len(data)<16 or data[:4]!=b'ETR1': raise ValueError('bad response header')
    n,us=struct.unpack_from('<IQ',data,4)
    if n!=count: raise ValueError('wrong response count')
    pos=16; out=[]
    for _ in range(n):
        ntri,=struct.unpack_from('<I',data,pos); pos+=4; tris=[]
        for _ in range(ntri):
            points=[]
            for _ in range(3): points.append(struct.unpack_from('<3d',data,pos));pos+=24
            tris.append(points)
        out.append(tris)
    if pos!=len(data): raise ValueError('trailing response bytes')
    return out,us/1000

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',type=Path,required=True);p.add_argument('--pack',type=Path,required=True)
    p.add_argument('--cli',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--repeat',type=int,default=10)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    with gzip.open(a.fixture,'rt',encoding='utf8') as f: fixture=json.load(f)
    cells = fixture.get('cells') or [fixture['cell']]
    # collect() keeps the first building id across neighbouring source cells.
    seen, buildings = set(), []
    for cell in cells:
        for index, building in enumerate(cell.get('buildings', []), 1):
            key = str(building.get('id', index))
            if key not in seen:
                seen.add(key)
                buildings.append(building)
    buildings.sort(key=lambda b: str(b.get('id', '')))
    i,j=fixture['tile']['i'],fixture['tile']['j']
    size=fixture.get('options', {}).get('tileSize', 500)
    rect=[i*size,j*size,(i+1)*size,(j+1)*size]
    request=a.out/'roof-request.bin';response=a.out/'roof-response.bin'
    request.write_bytes(pack(buildings,rect,a.workers))
    lua,mods,_=runtime(a.pack); g=lua.globals();g.generator=mods['generator']
    def table(v):
        if isinstance(v,list):return lua.table_from([table(x) for x in v])
        return v
    g.polygons=table([b['rings'] for b in buildings]);g.rect=table(rect)
    lua.execute('''function roofRun() local out={} for i,rings in ipairs(polygons) do out[i]=generator.triangulate(rings,nil,rect) end return out end''')
    run=g.roofRun;run()
    lua_ms=[]
    for _ in range(a.repeat):
        start=time.perf_counter(); expected=run();lua_ms.append((time.perf_counter()-start)*1000)
    native=[]; native_ms=[];wall_ms=[]
    for _ in range(a.repeat):
        start=time.perf_counter()
        subprocess.run([str(a.cli.resolve()),str(request),str(response)],check=True)
        wall_ms.append((time.perf_counter()-start)*1000)
        native,ms=unpack(response.read_bytes(),len(buildings));native_ms.append(ms)
    max_error=0.;total=0
    for i,got in enumerate(native,1):
        want=expected[i]
        if len(got)!=len(want): raise AssertionError(f'building {i}: triangle count {len(got)} != {len(want)}')
        for k,tri in enumerate(got,1):
            for v,point in enumerate(tri,1):
                for axis,x in enumerate(point,1):
                    err=abs(x-want[k][v][axis]);max_error=max(max_error,err)
                    if err>1e-8: raise AssertionError(f'building {i}, triangle {k}, vertex {v}, axis {axis}: {err}')
        total+=len(got)
    report={'buildings':len(buildings),'triangles':total,'rect':rect,'workers':a.workers,'repeats':a.repeat,
            'max_abs_error':max_error,'lua_ms':lua_ms,'rust_ms':native_ms,'subprocess_wall_ms':wall_ms,
            'request_bytes':request.stat().st_size,'response_bytes':response.stat().st_size}
    (a.out/'roof-benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))
if __name__=='__main__':main()
