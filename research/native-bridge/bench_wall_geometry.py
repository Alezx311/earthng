"""Compare Rust wall-run splitting to Lua using actual building footprints.

Hidden runs are computed by Lua; this does not port detection, materials, facade
details or full building meshes and is not an in-game benchmark.
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

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'earthng'))
from bench_native import runtime  # noqa: E402


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--pack',type=Path,required=True)
    p.add_argument('--cli',type=Path,required=True)
    a=p.parse_args()
    with gzip.open(a.fixture,'rt',encoding='utf8') as f: fixture=json.load(f)
    buildings=[];seen=set()
    for cell in fixture['cells']:
        for i,b in enumerate(cell.get('buildings',[]),1):
            key=str(b.get('id',i))
            if key not in seen: seen.add(key);buildings.append(b)
    lua,mods,_=runtime(a.pack)
    def table(v):
        if isinstance(v,dict): return lua.table_from({k:table(x) for k,x in v.items()})
        if isinstance(v,list): return lua.table_from([table(x) for x in v])
        return v
    walls=lua.execute('''
      local generator, buildings = ...
      local function upvalue(f, key)
        for i=1,200 do local name,v=debug.getupvalue(f,i);if not name then break end;if name==key then return v end end
        error('missing '..key)
      end
      local BLD, clean = upvalue(generator.coverIndex,'BLD'),upvalue(generator.coverIndex,'cleanRing')
      local ground=function() return 0 end
      local index=generator.coverIndex(buildings,ground,false)
      local out={}
      for _, building in ipairs(buildings) do
        local tags=building.tags or {}
        local span=BLD.span(building,ground,false)
        if span and not span.lifted and not tags.e2r_outline and tags.building~='roof' then
          for _, raw in ipairs(building.rings or {}) do
            local ring=clean(raw)
            for k, p in ipairs(ring) do
              local q=ring[k%#ring+1]
              local dx,dy=q[1]-p[1],q[2]-p[2]
              local length=math.sqrt(dx*dx+dy*dy)
              if length>1e-3 then
                local runs=generator.hiddenRuns(index,building,p,q,length,span.bottom)
                out[#out+1]={a=p,b=q,length=length,runs=runs,pieces=generator.wallPieces(p,q,length,runs)}
              end
            end
          end
        end
      end
      local a,b={0,0,1},{10,0,2}
      local runs={{1,3,5},{3.2,7,7}}
      out[#out+1]={a=a,b=b,length=10,runs=runs,pieces=generator.wallPieces(a,b,10,runs)}
      return out
    ''',mods['generator'],table(buildings))
    request=bytearray(b'EWP1'+struct.pack('<II',4,len(walls))); hidden=0
    for wall in walls.values():
        pa,pb=wall.a,wall.b;runs=wall.runs
        count=len(runs) if runs is not None else 0
        flags=(1 if pa[3] is not None else 0)|(2 if pb[3] is not None else 0)|(4 if runs is not None else 0)
        request.extend(struct.pack('<II7d',flags,count,pa[1],pa[2],pa[3] or 0,pb[1],pb[2],pb[3] or 0,wall.length))
        if runs is not None:
            hidden+=1
            for r in runs.values(): request.extend(struct.pack('<3d',r[1],r[2],r[3]))
    with tempfile.TemporaryDirectory() as td:
        src,out=Path(td)/'request',Path(td)/'response';src.write_bytes(request)
        subprocess.run([str(a.cli.resolve()),str(src),str(out)],check=True)
        data=out.read_bytes()
    assert data[:4]==b'EWR1' and struct.unpack_from('<I',data,4)[0]==len(walls)
    pos=8;max_error=0.;pieces=0
    for wall in walls.values():
        count,=struct.unpack_from('<I',data,pos);pos+=4
        assert count==len(wall.pieces)
        for k in range(1,count+1):
            flags,*values=struct.unpack_from('<I9d',data,pos);pos+=76
            want=wall.pieces[k]
            expected=[want[1][1],want[1][2],want[1][3] or 0,
                      want[2][1],want[2][2],want[2][3] or 0,want[3],want[4],want[5] or 0]
            expected_flags=(1 if want[1][3] is not None else 0)|(2 if want[2][3] is not None else 0)|(4 if want[5] is not None else 0)
            assert flags==expected_flags
            for x,y in zip(values,expected):
                if not math.isfinite(x) or abs(x-y)>1e-9: raise AssertionError(f'piece {pieces}: {values} != {expected}')
                max_error=max(max_error,abs(x-y))
            pieces+=1
    assert pos==len(data)
    print(json.dumps({'buildings':len(buildings),'walls':len(walls),'walls_with_hidden_runs':hidden,
                      'pieces':pieces,'max_abs_error':max_error,'result':'equal'}))


if __name__=='__main__':main()
