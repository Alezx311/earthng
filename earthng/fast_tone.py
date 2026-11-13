"""One tone for the real pack: base colours brought into the range the game's own levels keep.

A stock level gives all its ground one desaturated base colour (sRGB saturation 0.13-0.26) and
keeps facades and paving at a linear albedo of ~0.25-0.45. The real pack drew each material on
its own: grass at saturation 0.4-0.65, sidewalks and metal roofs at 0.5-0.8, house paints at
0.5-0.6. Side by side, under the game's auto exposure, that read as patchy and pale
(docs/VISUAL_1_0.md). Here each material's rendered colour (map mean x factor, both linear) is
pulled toward its class: saturation scaled down and capped, brightness compressed above a
pivot (both ways for land). Only the factor changes; the maps and the other packs stay as
they are (fast_art.pack_fields(..., toned=False) feeds the seasonal packs).

The map means come from earthng/tone_means.py (tone_means.json). A material whose map is not
measured keeps its factor.
"""
import json
import re
from pathlib import Path

# class -> (keep of saturation, cap of sRGB saturation, pivot Y, gamma, max Y, both ways)
CLASSES = {
    'land': (.72, .32, .10, .60, .15, True),
    # a field's crop (fast_style.CROPS): ripe wheat stays gold and stubble straw beside the black
    # soil and the green rows; under the land's caps the three read as one grey beige
    'crop': (.85, .46, .10, .70, .21, True),
    'wall': (.62, .30, .30, .60, .50, False),
    'roof': (.62, .32, .18, .60, .36, False),
    'pave': (.70, .14, .16, .50, .28, False),
    'prop': (.70, .28, .28, .60, .45, False),
}
# glass towers (their colour is the sky they mirror), signs, paint, lights, water and snow keep theirs
SKIP = re.compile(r'(^wall_off_|glass|windows|^wall_shop_|roof_gold|lens|glyph|plate|paint_red|^mark|brand|'
                  r'^car$|wire|water|sign|fascia|snow|glacier|^farmap_|^col_|storefront)')
RULES = (
    ('crop', re.compile(r'^farmland')),
    ('land', re.compile(r'^(cut_|fade_|edge_grass|edge_dirt|ground$|meadow|grass_|dry_grass|earth$|forest$|scrub|'
                        r'heath|orchard|park$|steppe|vineyard|wetland|bare_ground|road_track|tundra)')),
    ('wall', re.compile(r'^(hw_|wall_|gable|plinth|chimney|fence_|clad_|parapet)')),
    ('roof', re.compile(r'^roof_')),
    ('pave', re.compile(r'^(sidewalk|curb|footway$|trodden|yard$|paved$|track$|manhole|drain)')),
    ('prop', re.compile(r'^(ac_unit|dish|door_|pipe|win_|rail$)')),
)
_MEANS = None


def key(path):
    """A map path as tone_means.json keys it: the art version and the dds/png suffix dropped."""
    p = re.sub(r'^/?e2r_stream/fast-art/[^/]+/', 'art/', path)
    p = p.lstrip('/')
    return p[:-4] + '.png' if p.endswith('.dds') else p


def means():
    global _MEANS
    if _MEANS is None:
        f = Path(__file__).with_name('tone_means.json')
        _MEANS = json.loads(f.read_text(encoding='utf8')) if f.exists() else {}
    return _MEANS


def klass(kind):
    if SKIP.search(kind):
        return None
    for name, rule in RULES:
        if rule.match(kind):
            return name
    return None


def _lin(c):
    return c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4


def _enc(c):
    c = max(c, 0)
    return 12.92 * c if c <= .0031308 else 1.055 * c ** (1 / 2.4) - .055


def _sat(rgb):
    s = [_enc(c) for c in rgb]
    return (max(s) - min(s)) / max(max(s), 1e-6)


def target(rgb, cls):
    """The linear colour a material of class `cls` with linear colour `rgb` is pulled to."""
    keep, cap, pivot, gamma, top, both = CLASSES[cls]
    y = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]
    if y <= 1e-4:
        return list(rgb)
    yt = pivot * (y / pivot) ** gamma if (both or y > pivot) else y
    yt = min(yt, top)
    want = min(_sat(rgb) * keep, cap)
    lo, hi = 0.0, 1.0          # how much of the colour off grey stays: the saturation wanted
    for _ in range(24):
        mid = (lo + hi) / 2
        if _sat([y + mid * (c - y) for c in rgb]) > want:
            hi = mid
        else:
            lo = mid
    return [(y + lo * (c - y)) * yt / y for c in rgb]


def factor(kind, stage):
    """The toned baseColorFactor [r, g, b, a] for a real-pack stage, or None to keep it."""
    cls = klass(kind)
    if not cls:
        return None
    path = stage.get('baseColorMap') or ''
    if not path:
        return None
    m = means().get(key(path))
    if not m:
        return None
    f = stage.get('baseColorFactor') or [1, 1, 1, 1]
    if isinstance(f, str):
        f = [float(x) for x in f.split()]
    f = list(f) + [1] * (4 - len(f))
    rgb = [max(m[i], 1e-4) * _lin(f[i]) for i in range(3)]
    t = target(rgb, cls)
    return [round(min(_enc(t[i] / max(m[i], 1e-4)), 1.6), 3) for i in range(3)] + [f[3]]
