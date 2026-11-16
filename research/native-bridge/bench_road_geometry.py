"""Compare Rust strip normals/UV distances to the actual Lua road code.

Uses cleaned source polylines, not the fully prepared runtime road inputs;
it does not compare meshes, intersections, navigation or performance in game.
"""
import argparse
import gzip
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'earthng'))
from bench_native import runtime  # noqa: E402


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--pack',type=Path,required=True)
    p.add_argument('--cli',type=Path,required=True)
    a=p.parse_args()
    with gzip.open(a.fixture,'rt',encoding='utf8') as f: fixture=json.load(f)
    roads=[]; seen=set()
    for cell in fixture['cells']:
        for i,road in enumerate(cell.get('roads',[]),1):
            key=str(road.get('id',i))
            if key in seen: continue
            seen.add(key); points=[]
            for point in road.get('points',[]):
                if not points or abs(points[-1][0]-point[0])+abs(points[-1][1]-point[1])>1e-4:
                    points.append(point[:2])
            if len(points)>=2: roads.append((points,[None,None]))
    # Test the actual end-joint override, a sharp bend and a near-U-turn too.
    roads.extend([([[0,0],[10,0],[10,10]], [[0,1,1.5],[1,0,1.25]]),
                  ([[0,0],[10,0],[0,1e-5]], [None,None])])
    request=bytearray(b'ERD1'+struct.pack('<II',4,len(roads)))
    for points,joints in roads:
        flags=sum((1<<i) for i,j in enumerate(joints) if j is not None)
        request.extend(struct.pack('<IId',len(points),flags,2.0))
        for joint in joints: request.extend(struct.pack('<3d',*(joint or [0,0,0])))
        for point in points: request.extend(struct.pack('<2d',*point))
    with tempfile.TemporaryDirectory() as td:
        src,out=Path(td)/'request',Path(td)/'response'
        src.write_bytes(request)
        subprocess.run([str(a.cli.resolve()),str(src),str(out)],check=True)
        data=out.read_bytes()
    assert data[:4]==b'ERR1' and struct.unpack_from('<I',data,4)[0]==len(roads)
    generator=(ROOT/'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8')
    normals=generator.split('      normals = {}\n',1)[1].split('      dist = {0}\n',1)[0]
    dist=generator.split('      dist = {0}\n',1)[1].split('      end\n      local joints = prep.joints',1)[0]
    lua,_,_=runtime(a.pack)
    reference=lua.eval('''function(points, mitre, joints)
      local EPS, tune, prep = 1e-8, {mitre=mitre}, {joints=joints}
      local normals = {}
    '''+normals+'''\n      local dist = {0}\n'''+dist+'''\n      return normals,dist end''')
    def tab(v):
        if isinstance(v,list): return lua.table_from({i:tab(x) for i,x in enumerate(v,1) if x is not None})
        return v
    pos=8; max_error=0.; count=0
    for points,joints in roads:
        n,=struct.unpack_from('<I',data,pos);pos+=4
        assert n==len(points)
        normals,distances=reference(tab(points),2,tab(joints))
        for k in range(1,n+1):
            values=struct.unpack_from('<3d',data,pos);pos+=24
            expected=[normals[k][1],normals[k][2],distances[k]]
            for x,y in zip(values,expected):
                if not math.isfinite(x) or abs(x-y)>1e-10:
                    raise AssertionError(f'road {count}, point {k}: {values} vs {expected}')
                max_error=max(max_error,abs(x-y))
        count+=1
    assert pos==len(data)
    print(json.dumps({'roads':count,'max_abs_error':max_error,'result':'equal',
                      'scope':'clean source points; no junction trims, densification or full meshes'}))


if __name__=='__main__': main()
