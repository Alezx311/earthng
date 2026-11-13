"""Measure the colour maps of the real pack: the linear mean of each map, for fast_tone.

    .venv\\Scripts\\python.exe earthng/tone_means.py

Reads the art built by fast_art (data/art/<VERSION>/) and the game's own textures (the zips
under content/), and writes earthng/tone_means.json: map key (fast_tone.key) -> linear RGB.
Run it again after the art or a game texture of the real pack changes; a map missing from the
file leaves its material as it was (fast_tone.factor).
"""
import io
import json
import struct
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

import fast_art as art
import fast_style as style
import fast_tone as tone

ROOT = Path(__file__).resolve().parent.parent


def _undx10(d):
    """A DX10 DDS header (BC1/BC3 formats) as the legacy FourCC Pillow reads."""
    if d[:4] != b'DDS ' or d[84:88] != b'DX10':
        return d
    fmt = struct.unpack('<I', d[128:132])[0]
    cc = {70: b'DXT1', 71: b'DXT1', 72: b'DXT1', 73: b'DXT3', 74: b'DXT3', 75: b'DXT3',
          76: b'DXT5', 77: b'DXT5', 78: b'DXT5'}.get(fmt)
    return d[:84] + cc + d[88:128] + d[148:] if cc else d


class Game:
    def __init__(self):
        content = Path(art.game_dir()) / 'content'
        self.zips = [zipfile.ZipFile(z) for sub in ('assets/materials', 'assets', 'levels')
                     for z in sorted((content / sub).glob('*.zip'))]

    def read(self, path):
        rel = path.lstrip('/')
        cands = [rel, rel[:-4] + '.dds'] if rel.endswith('.png') else [rel, rel[:-4] + '.png']
        cands += ['content/' + c for c in cands]
        for z in self.zips:
            for c in cands:
                try:
                    return z.read(c)
                except KeyError:
                    pass
        return None


def read_art(path):
    rel = path.split('/fast-art/', 1)[1].split('/', 1)[1]
    f = ROOT / 'data' / 'art' / art.VERSION / rel
    for c in (f, f.with_suffix('.dds'), f.with_suffix('.png')):
        if c.exists():
            return c.read_bytes()
    return None


def mean(data):
    im = Image.open(io.BytesIO(_undx10(data))).convert('RGB')
    im.thumbnail((256, 256))
    a = np.asarray(im, np.float32) / 255
    a = np.where(a <= .04045, a / 12.92, ((a + .055) / 1.055) ** 2.4)
    return [round(float(v), 4) for v in a.reshape(-1, 3).mean(0)]


def maps():
    base = '/e2r_stream/fast-art/' + art.VERSION
    out = set()
    for f in art.pack_fields('real', base, toned=False).values():
        if f.get('baseColorMap'):
            out.add(f['baseColorMap'])
    for m in style.MATERIALS.values():
        stage = (m.get('Stages') or [{}])[0]
        if stage.get('baseColorMap'):
            out.add(stage['baseColorMap'])
    return sorted(out)


def main():
    game, means, missing = Game(), {}, []
    for path in maps():
        data = read_art(path) if '/fast-art/' in path else game.read(path)
        if data is None:
            missing.append(path)
            continue
        try:
            means[tone.key(path)] = mean(data)
        except Exception as e:      # an unreadable format: the material stays as it is
            missing.append(f'{path} ({e})')
    out = Path(__file__).with_name('tone_means.json')
    rows = [f'  {json.dumps(k)}: {json.dumps(v)}' for k, v in sorted(means.items())]
    out.write_text('{\n' + ',\n'.join(rows) + '\n}\n', encoding='utf8')
    print(len(means), 'maps ->', out)
    for m in missing:
        print('missing', m)


if __name__ == '__main__':
    main()
