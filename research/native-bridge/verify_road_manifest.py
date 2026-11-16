"""Inject actual Rust road-strip results into an offline Lua tile build.

The bridge process in this parity harness is synchronous; the game uses the
separate nonblocking transport. Compare the entire road manifest and nav graph.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'earthng'))
from bench_native import runtime  # noqa: E402
from capture_road_fixture import plain  # noqa: E402


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--pack',type=Path,required=True)
    p.add_argument('--cli',type=Path,required=True)
    p.add_argument('--fallback-every',type=int,default=0,
                   help='omit every Nth result to exercise mixed Lua/Rust tiles')
    a=p.parse_args()
    with gzip.open(a.fixture,'rt',encoding='utf8') as f: fixture=json.load(f)
    lua,mods,_=runtime(a.pack)
    def table(v):
        if isinstance(v,dict): return lua.table_from({k:table(x) for k,x in v.items()})
        if isinstance(v,list): return lua.table_from([table(x) for x in v])
        return v
    i,j=fixture['tile']['i'],fixture['tile']['j']
    opts=fixture['options']
    baseline=mods['generator'].build(table(fixture['cells']),i,j,table(opts))
    expected=(plain(baseline[0]),plain(baseline[3]),plain(baseline[2]))
    cache=lua.table(); seen=[]
    def start(prepared,roads,mitre):
        request=bytearray(b'ERD1'+struct.pack('<II',4,0)); selected=[]
        for k in range(1,len(roads)+1):
            road=roads[k];prep=prepared[road]
            if not prep: continue
            pts,joints=prep.points,prep.joints
            flags=0;jv=[]
            for ji in (1,2):
                joint=joints[ji] if joints else None
                if joint: flags|=1<<(ji-1)
                jv.extend([joint[x] if joint else 0 for x in (1,2,3)])
            request.extend(struct.pack('<IId6d',len(pts),flags,mitre,*jv))
            for n in range(1,len(pts)+1): request.extend(struct.pack('<2d',pts[n][1],pts[n][2]))
            selected.append((road,len(pts)))
        struct.pack_into('<I',request,8,len(selected))
        with tempfile.TemporaryDirectory() as td:
            src,out=Path(td)/'request',Path(td)/'response';src.write_bytes(request)
            subprocess.run([str(a.cli.resolve()),str(src),str(out)],check=True)
            data=out.read_bytes()
        assert data[:4]==b'ERR1' and struct.unpack_from('<I',data,4)[0]==len(selected)
        pos=8
        for index,(road,count) in enumerate(selected,1):
            n,=struct.unpack_from('<I',data,pos);pos+=4
            assert n==count
            normals,dist=lua.table(),lua.table()
            for k in range(1,n+1):
                x,y,d=struct.unpack_from('<3d',data,pos);pos+=24
                normals[k],dist[k]=table([x,y]),d
            if not a.fallback_every or index % a.fallback_every:
                cache[road]=table([normals,dist])
        assert pos==len(data)
        seen.append(len(selected))
    lua.globals().py_start=start
    lua.globals().road_cache=cache
    hooks=lua.eval('''function(options)
      options.roadStart=function(prepared,roads,mitre) py_start(prepared,roads,mitre) end
      options.roadResult=function(road)
        local result=road_cache[road]
        if result then return result[1],result[2] end
      end
      return options
    end''')
    got=mods['generator'].build(table(fixture['cells']),i,j,hooks(table(opts)))
    actual=(plain(got[0]),plain(got[3]),plain(got[2]))
    for name,x,y in zip(('road','nav','far'),expected,actual):
        a_json=json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        b_json=json.dumps(y,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        if a_json != b_json: raise AssertionError(name+' manifest differs')
        print(json.dumps({'layer':name,'sha256':hashlib.sha256(a_json.encode()).hexdigest(),
                          'rust_roads':seen[0], 'result':'equal'}))


if __name__=='__main__':main()
