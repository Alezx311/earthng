"""Audit/download raw Terrarium sources. No road profiles or geometry are prepared here."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import math
import os
from pathlib import Path
import threading
import time

import tls


def audit(index, cache):
    """DEM under every source tile's coverage, not the package box: a country's box is half
    sea and neighbours (Ukraine: OSM tiles only where the data is)."""
    tile=lambda lon,lat: ((lon+180)/360*4096,(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*4096)
    keys=set()
    for t in index['tiles'].values():
        w,s,e,n=t['coverage']
        x0,y0=tile(w,n); x1,y1=tile(e,s)
        # One extra tile handles complete OSM features and filtered edge samples.
        keys.update((x,y) for x in range(math.floor(x0)-1,math.floor(x1)+2)
                    for y in range(math.floor(y0)-1,math.floor(y1)+2))
    return [Path(cache)/'terrain/12'/str(x)/f'{y}.png' for x,y in sorted(keys)]


# The AWS Open Data bucket of the Terrarium tiles (us-east-1). A new TLS connection per tile held
# the build at 11 tiles/s from Kyiv; one kept-alive connection per thread fetched 29 (2026-11-07).
HOST='elevation-tiles-prod.s3.us-east-1.amazonaws.com'
USER_AGENT='EarthNG/0.1 (+https://github.com/Alezx311/earth2road)'
# Some connections to S3 stall for minutes (an 11 MB file took 3 s, then 83 s and 433 s on the same
# line): a tile that sends nothing for STALL seconds, or is not in after DEADLINE, is abandoned and
# asked again on a fresh connection.
STALL=8
DEADLINE=20
_local=threading.local()


def _download(url_path):
    """GET over this thread's kept-alive connection; the connection is dropped on any failure."""
    conn=getattr(_local,'conn',None)
    if conn is None:
        conn=_local.conn=http.client.HTTPSConnection(HOST,timeout=STALL,context=tls.context())
    try:
        started=time.monotonic()
        conn.request('GET',url_path,headers={'User-Agent':USER_AGENT})
        response=conn.getresponse()
        chunks=[]
        while True:
            chunk=response.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if time.monotonic()-started>DEADLINE:
                raise TimeoutError(f'{url_path}: slower than {DEADLINE} s')
        if response.status!=200:
            raise OSError(f'https://{HOST}{url_path}: HTTP {response.status}')
        if response.will_close:
            conn.close(); _local.conn=None
        return b''.join(chunks)
    except BaseException:
        conn.close(); _local.conn=None
        raise


def fetch(path):
    from PIL import Image
    if path.exists():
        return
    url_path='/terrarium/12/'+path.parent.name+'/'+path.name
    url=f'https://{HOST}{url_path}'
    try:
        data=_download(url_path)
    except (OSError,http.client.HTTPException):
        # a kept-alive connection the server closed, or a stalled one: once more on a new one
        # at once (the callers' retries back off for seconds)
        data=_download(url_path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(f'.{os.getpid()}.png.part'); tmp.write_bytes(data)   # builds side by side
    with Image.open(tmp) as image:
        if image.size!=(256,256):
            raise ValueError(f'invalid DEM {url}')
        image.verify()
    for attempt in range(10):   # an antivirus may hold the fresh .part for a moment (WinError 32)
        try:
            os.replace(tmp,path); return
        except PermissionError:
            if attempt==9: raise
            time.sleep(1)


def height(lat,lon,cache):
    """Raw Terrarium height in metres at a point (bilinear in the z12 tile), fetched if missing.
    For placing cameras; the exporter samples its own despiked grid."""
    from PIL import Image
    fx=(lon+180)/360*4096*256-.5; fy=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*4096*256-.5
    x0,y0=math.floor(fx),math.floor(fy); u,v=fx-x0,fy-y0
    def at(px,py):
        path=Path(cache)/'terrain/12'/str(px//256)/f'{py//256}.png'
        fetch(path)
        with Image.open(path) as image:
            r,g,b=image.convert('RGB').getpixel((px%256,py%256))
        return r*256+g+b/256-32768
    return ((at(x0,y0)*(1-u)+at(x0+1,y0)*u)*(1-v)+(at(x0,y0+1)*(1-u)+at(x0+1,y0+1)*u)*v)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources',required=True); p.add_argument('--cache',required=True)
    p.add_argument('--download',action='store_true')
    a=p.parse_args(); index=json.loads((Path(a.sources)/'index.json').read_text())
    paths=audit(index,a.cache); missing=[p for p in paths if not p.exists()]
    print(f'DEM: {len(paths)-len(missing)}/{len(paths)} local; {len(missing)} missing',flush=True)
    if a.download:
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(fetch,missing))
        print('Raw DEM sources ready; no derived data generated.',flush=True)
    elif missing:
        raise SystemExit(1)


if __name__=='__main__':
    main()
