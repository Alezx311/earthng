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

Open land goes further: it takes the colour the land has from above. ground_targets.json
(earthng/ground_colour.py) holds the Sentinel-2 composite's median colour of each cover class of a
built pack, in the tone the far view's real-colour map is drawn in. A kind that is such a class
(SATELLITE) is brought to its colour; the other green lands (the lush grass of hollows, the
verge's grass, a grown-over track) keep their place beside the common grass and move with it
(GREEN, land_gain), so none of them is greener than the picture from space. Dry grass, bare
earth and the other climates' lands have no class in the picture and keep their class's tone.
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
    # (not a wood's floor: it lies in the canopy's shade, lit by the sky alone, and under the
    # land's cap of saturation its leaf litter was grey-blue beside green ferns: flora-04)
    ('land', re.compile(r'^(cut_|fade_|edge_grass|edge_dirt|ground$|meadow|grass_|dry_grass|earth$|scrub|'
                        r'heath|orchard|park$|steppe|vineyard|wetland|bare_ground|road_track|tundra)')),
    ('wall', re.compile(r'^(hw_|wall_|gable|plinth|chimney|fence_|clad_|parapet)')),
    ('roof', re.compile(r'^roof_')),
    ('pave', re.compile(r'^(sidewalk|curb|footway$|trodden|yard$|paved$|track$|manhole|drain)')),
    ('prop', re.compile(r'^(ac_unit|dish|door_|pipe|win_|rail$)')),
)
_MEANS = None
# kind -> the cover class of ground_targets.json whose colour it takes
SATELLITE = {'ground': 'ground', 'meadow': 'meadow', 'park': 'park', 'orchard': 'orchard', 'scrub': 'scrub',
             'wetland': 'wetland'}
GRASS_MAP = 'art/real/macro_grass.color.png'      # the common grass every other land is drawn beside
GREEN = re.compile(r'^(cut_grass|fade_grass|cut_lush|fade_lush|grass_lush|edge_grass|road_track)')
_TARGETS, _GAIN = None, None


def satellite():
    """{cover class: linear colour} of ground_targets.json, {} without the file."""
    global _TARGETS
    if _TARGETS is None:
        f = Path(__file__).with_name('ground_targets.json')
        kinds = json.loads(f.read_text(encoding='utf8'))['kinds'] if f.exists() else {}
        _TARGETS = {k: [_lin(c / 255) for c in v['srgb']] for k, v in kinds.items()}
    return _TARGETS


def land_gain():
    """What the common grass's toned colour is multiplied by, a channel, to be the satellite's
    ground: the same goes for every land that has no class of its own. (1, 1, 1) without data."""
    global _GAIN
    if _GAIN is None:
        grass, sat = means().get(GRASS_MAP), satellite().get('ground')
        if grass and sat:
            toned = _class_target([max(c, 1e-4) for c in grass], 'land')
            _GAIN = [sat[i] / max(toned[i], 1e-4) for i in range(3)]
        else:
            _GAIN = [1., 1., 1.]
    return _GAIN


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


def target(rgb, cls, kind=None):
    """The linear colour a material of class `cls` with linear colour `rgb` is pulled to: its
    class's range, and for land the colour of the land from above (SATELLITE, land_gain)."""
    if cls == 'land':
        sat = satellite().get(SATELLITE.get(kind, ''))
        if sat:
            return list(sat)
        if kind and GREEN.match(kind):
            return [c * g for c, g in zip(_class_target(rgb, cls), land_gain())]
    return _class_target(rgb, cls)


def _class_target(rgb, cls):
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
    t = target(rgb, cls, kind)
    return [round(min(_enc(t[i] / max(m[i], 1e-4)), 1.6), 3) for i in range(3)] + [f[3]]
