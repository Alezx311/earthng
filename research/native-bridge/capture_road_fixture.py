"""Capture one real Lua generator input and its road/nav outputs for parity work.

This is a LuaJIT reference fixture, not an in-game screenshot or an engine mesh.
The source country ZIP is read-only; output belongs under out/ and is not committed.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
from bench_native import runtime  # noqa: E402
from lupa.luajit21 import lua_type  # noqa: E402

CODE = r'''
local native,generator = ...
local function upvalue(f,name)
  for k=1,200 do local n,v=debug.getupvalue(f,k); if not n then return end; if n==name then return v end end
end
local active=assert(upvalue(native.update,'active'))
local d=active.region.data
local i,j=math.floor(active.landing.x/500),math.floor(active.landing.y/500)
local ci,cj=math.floor(i*500/d.cellSize),math.floor(j*500/d.cellSize)
local loadCell=assert(upvalue(upvalue(native.update,'buildTile'),'loadCell'))
local co=coroutine.create(function() return loadCell(string.format('%d_%d',ci,cj),ci,cj,{i*500,j*500,(i+1)*500,(j+1)*500}) end)
local cell
while true do
  local ok,value=coroutine.resume(co); assert(ok,value)
  if coroutine.status(co)=='dead' then cell=assert(value,'empty cell'); break end
end
local road,scene,far,nav=generator.build({cell},i,j,{tileSize=500,far=false,pause=function() end,seaLevel=d.seaLevel})
return {tile={i=i,j=j},cell=cell,road=road,nav=nav,seaLevel=d.seaLevel}
'''

def plain(value, seen=None):
    if lua_type(value) != 'table':
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise TypeError(f'unsupported Lua value: {type(value).__name__}')
    seen = seen or set()
    identity = repr(value)
    if identity in seen:
        raise ValueError('cycle in Lua fixture')
    seen.add(identity)
    try:
        keys = list(value.keys())
        if all(isinstance(k, int) and not isinstance(k, bool) and k >= 1 for k in keys) and set(keys) == set(range(1, len(keys)+1)):
            return [plain(value[k], seen) for k in range(1, len(keys)+1)]
        if not all(isinstance(k, str) for k in keys):
            raise ValueError('fixture contains a non-string map key or sparse array')
        return {k: plain(value[k], seen) for k in sorted(keys)}
    finally:
        seen.remove(identity)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--lat', type=float, default=50.447734)
    p.add_argument('--lon', type=float, default=30.52218)
    a=p.parse_args()
    if a.out.exists(): raise SystemExit('Refusing to overwrite fixture')
    started=time.perf_counter()
    lua,mods,_=runtime(a.pack)
    mods['native'].refresh()
    job=mods['native'].land(lua.table_from({'seq':1,'lat':a.lat,'lon':a.lon}))
    if job.state=='error': raise SystemExit(job.message)
    captured=plain(lua.execute(CODE,mods['native'],mods['generator']))
    captured.update({'schema':1,'lat':a.lat,'lon':a.lon,'pack':str(a.pack.resolve()),'note':'LuaJIT offline; road and nav only; not an in-game engine object'})
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(a.out,'xt',encoding='utf8',compresslevel=3) as f:
        json.dump(captured,f,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    with a.out.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    print(json.dumps({'path':str(a.out),'tile':captured['tile'],'bytes':a.out.stat().st_size,'sha256':digest,'seconds':round(time.perf_counter()-started,2)}))

if __name__=='__main__': main()
