"""Global climate classes for the planet's biomes (generator.lua through e2r/biome.lua).

    python earthng/build_climate.py            # builds out/climate/<VERSION>/ once
    python earthng/build_climate.py --force    # again

Köppen-Geiger classes 1991-2020 of Beck et al. (2023), 1 km, CC BY 4.0, taken every second
pixel (1 arc minute, about 1.85 km). The tree line, the alpine belt and the snow line come from
the pack's DEM at runtime, so the coarser grid only has to tell desert from steppe, tropics,
Mediterranean scrub, temperate and boreal forest and tundra.

One file per 10 x 10 degree block with land, `<col>_<row>.bin`, col = floor((lon + 180) / 10),
row = floor((lat + 90) / 10): b'EKG1', u16 width, u16 height (little endian), then one byte per
cell, rows from the south edge up, columns from the west edge (0 = sea or no data, 1..30 the
classes of the source's legend.txt). Open-sea blocks are not written.

Source (downloaded once to data/climate/, 130 MB):
https://doi.org/10.6084/m9.figshare.21789074 (koppen_geiger_tif.zip)
Beck, H. E. et al. High-resolution (1 km) Köppen-Geiger maps for 1901-2099 based on constrained
CMIP6 projections. Scientific Data 10, 724 (2023).
"""
import argparse
from pathlib import Path
import shutil
import struct
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / 'data/climate'
OUT = ROOT / 'out/climate'
VERSION = '1'
URL = 'https://ndownloader.figshare.com/files/61012822'
MEMBER = '1991_2020/koppen_geiger_0p00833333.tif'
BLOCK_DEG = 10
STRIDE = 2           # source pixels (1/120 degree) per output cell
MAGIC = b'EKG1'


def source():
    """The 1 km GeoTIFF, extracted from the archive (downloaded if missing)."""
    tif = SRC / 'kg' / MEMBER
    if tif.is_file():
        return tif
    archive = SRC / 'koppen_geiger_tif.zip'
    if not archive.is_file():
        sys.path.insert(0, str(HERE))
        import country_fetch
        country_fetch.download(URL, archive)
    with zipfile.ZipFile(archive) as z:
        z.extract(MEMBER, SRC / 'kg')
        z.extract('legend.txt', SRC / 'kg')
    return tif


def build(force=False):
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    out = OUT / VERSION
    if (out / 'index.txt').is_file() and not force:
        return out
    tif = source()
    tmp = out.with_name(out.name + '.tmp')
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    names = []
    with rasterio.open(tif) as r:
        per = round(1 / r.transform.a)                  # source pixels per degree
        if abs(r.transform.c + 180) > 1e-6 or abs(r.transform.f - 90) > 1e-6 or r.width != 360 * per:
            raise SystemExit(f'{tif}: unexpected grid {r.transform}')
        side = BLOCK_DEG * per
        for row in range(180 // BLOCK_DEG):
            for col in range(360 // BLOCK_DEG):
                top = (180 // BLOCK_DEG - 1 - row) * side    # the raster runs from the north
                a = r.read(1, window=Window(col * side, top, side, side))
                if not a.any():
                    continue
                a = np.where(a <= 30, a, 0).astype(np.uint8)[::-1][::STRIDE, ::STRIDE]
                h, w = a.shape
                name = f'{col}_{row}.bin'
                (tmp / name).write_bytes(MAGIC + struct.pack('<HH', w, h) + np.ascontiguousarray(a).tobytes())
                names.append(name)
    (tmp / 'index.txt').write_text('\n'.join(names) + '\n', encoding='utf-8')
    shutil.rmtree(out, ignore_errors=True)
    tmp.replace(out)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--force', action='store_true')
    out = build(p.parse_args().force)
    files = list(out.glob('*.bin'))
    print(out, len(files), 'blocks', sum(f.stat().st_size for f in files) // 1000, 'kB')


if __name__ == '__main__':
    main()
