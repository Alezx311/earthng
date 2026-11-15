"""Pictograms drawn at art build time: what a plain sign or a shop window says without a word, so
the same art reads in any country (fast_art.NEUTRAL_SIGNS, fast_storefront.NEUTRAL_POSTERS).

Each is drawn in one colour on a clear square layer: mark(name, size, ink) -> PIL RGBA image.
"""
import math

from PIL import Image, ImageDraw


def _fuel(d, s, ink):
    w = s * .07
    d.rounded_rectangle((s * .18, s * .14, s * .58, s * .9), s * .05, fill=ink)              # the pump
    d.rectangle((s * .26, s * .22, s * .50, s * .42), fill=(0, 0, 0, 0))                      # its window
    d.rectangle((s * .12, s * .86, s * .64, s * .92), fill=ink)                               # the foot
    # the hose and nozzle on its hook
    d.line([(s * .58, s * .30), (s * .72, s * .30), (s * .80, s * .40), (s * .80, s * .70),
            (s * .86, s * .76), (s * .90, s * .70), (s * .90, s * .30), (s * .82, s * .22)], fill=ink, width=round(w), joint='curve')


def _cart(d, s, ink):
    w = round(s * .07)
    d.line([(s * .06, s * .2), (s * .2, s * .2), (s * .32, s * .66), (s * .80, s * .66)], fill=ink, width=w, joint='curve')
    d.polygon([(s * .24, s * .3), (s * .92, s * .3), (s * .82, s * .58), (s * .31, s * .58)], fill=ink)
    for x in (.38, .76):
        d.ellipse((s * (x - .07), s * .74, s * (x + .07), s * .88), fill=ink)


def _wrench(d, s, ink):
    a = math.radians(45)
    ux, uy = math.cos(a), math.sin(a)
    cx, cy = s * .5, s * .5
    half, wide = s * .34, s * .07
    px, py = -uy * wide, ux * wide
    d.polygon([(cx - ux * half + px, cy - uy * half + py), (cx + ux * half * .6 + px, cy + uy * half * .6 + py),
               (cx + ux * half * .6 - px, cy + uy * half * .6 - py), (cx - ux * half - px, cy - uy * half - py)], fill=ink)
    for k, r in ((-1, .17), (1, .15)):
        hx, hy = cx + ux * half * k * (1 if k > 0 else 1.05), cy + uy * half * k * (1 if k > 0 else 1.05)
        d.ellipse((hx - s * r, hy - s * r, hx + s * r, hy + s * r), fill=ink)
        # the jaw: a slot cut into the head along the handle
        jx, jy = hx + ux * s * r * .55 * k, hy + uy * s * r * .55 * k
        q = s * .07
        d.polygon([(jx - uy * q + ux * q * 2 * k, jy + ux * q + uy * q * 2 * k), (jx - uy * q - ux * q * k, jy + ux * q - uy * q * k),
                   (jx + uy * q - ux * q * k, jy - ux * q - uy * q * k), (jx + uy * q + ux * q * 2 * k, jy - ux * q + uy * q * 2 * k)],
                  fill=(0, 0, 0, 0))


def _tyre(d, s, ink):
    c, r = s * .5, s * .42
    d.ellipse((c - r, c - r, c + r, c + r), fill=ink)
    d.ellipse((c - r * .55, c - r * .55, c + r * .55, c + r * .55), fill=(0, 0, 0, 0))
    d.ellipse((c - r * .3, c - r * .3, c + r * .3, c + r * .3), fill=ink)
    for k in range(12):                                                                   # the tread
        a = k * math.pi / 6
        x, y = c + math.cos(a) * r * .86, c + math.sin(a) * r * .86
        d.ellipse((x - s * .03, y - s * .03, x + s * .03, y + s * .03), fill=(0, 0, 0, 0))


def _car(d, s, ink, top=.5):
    d.polygon([(s * .12, s * (top + .32)), (s * .12, s * (top + .16)), (s * .26, s * (top + .12)), (s * .36, s * top),
               (s * .66, s * top), (s * .78, s * (top + .12)), (s * .88, s * (top + .16)), (s * .88, s * (top + .32))], fill=ink)
    for x in (.3, .7):
        d.ellipse((s * (x - .08), s * (top + .26), s * (x + .08), s * (top + .42)), fill=ink)


def _wash(d, s, ink):
    _car(d, s, ink, top=.46)
    for x in (.3, .5, .7):                                                                # the drops over it
        d.polygon([(s * x, s * .06), (s * (x - .06), s * .24), (s * (x + .06), s * .24)], fill=ink)
        d.ellipse((s * (x - .06), s * .18, s * (x + .06), s * .3), fill=ink)


def _charge(d, s, ink):
    d.rounded_rectangle((s * .22, s * .16, s * .66, s * .9), s * .06, fill=ink)
    d.rectangle((s * .30, s * .24, s * .58, s * .44), fill=(0, 0, 0, 0))
    d.polygon([(s * .47, s * .48), (s * .34, s * .7), (s * .45, s * .7), (s * .40, s * .86), (s * .55, s * .62),
               (s * .44, s * .62), (s * .50, s * .48)], fill=(0, 0, 0, 0))                     # the bolt cut out
    d.line([(s * .66, s * .36), (s * .80, s * .36), (s * .80, s * .14)], fill=ink, width=round(s * .06))


def _cross(d, s, ink):
    a, b = s * .34, s * .66
    d.rectangle((a, s * .12, b, s * .88), fill=ink)
    d.rectangle((s * .12, a, s * .88, b), fill=ink)


def _bank(d, s, ink):
    d.polygon([(s * .5, s * .08), (s * .92, s * .3), (s * .08, s * .3)], fill=ink)          # the pediment
    d.rectangle((s * .1, s * .33, s * .9, s * .39), fill=ink)
    for x in (.18, .38, .58, .78):
        d.rectangle((s * x, s * .42, s * (x + .08), s * .8), fill=ink)
    d.rectangle((s * .06, s * .83, s * .94, s * .92), fill=ink)


def _cup(d, s, ink):
    d.polygon([(s * .16, s * .42), (s * .70, s * .42), (s * .64, s * .84), (s * .22, s * .84)], fill=ink)
    d.ellipse((s * .6, s * .48, s * .9, s * .74), outline=ink, width=round(s * .06))
    d.rectangle((s * .1, s * .86, s * .78, s * .91), fill=ink)
    for x in (.3, .44, .58):                                                              # the steam
        d.arc((s * (x - .05), s * .1, s * (x + .05), s * .24), 90, 270, fill=ink, width=round(s * .04))
        d.arc((s * (x - .05), s * .22, s * (x + .05), s * .36), 270, 90, fill=ink, width=round(s * .04))


def _cutlery(d, s, ink):
    w = round(s * .07)
    d.line([(s * .34, s * .4), (s * .34, s * .92)], fill=ink, width=w)                      # the fork
    for x in (.24, .34, .44):
        d.line([(s * x, s * .08), (s * x, s * .32)], fill=ink, width=round(s * .045))
    d.rounded_rectangle((s * .22, s * .28, s * .46, s * .42), s * .05, fill=ink)
    d.pieslice((s * .52, s * .06, s * .84, s * .7), 270, 90, fill=ink)                        # the knife
    d.line([(s * .68, s * .38), (s * .68, s * .92)], fill=ink, width=w)


def _beer(d, s, ink):
    d.rectangle((s * .2, s * .3, s * .64, s * .9), fill=ink)
    d.ellipse((s * .6, s * .4, s * .9, s * .76), outline=ink, width=round(s * .07))
    for x in (.2, .34, .48):                                                              # the foam
        d.ellipse((s * x, s * .14, s * (x + .18), s * .34), fill=ink)
    for x in (.3, .42, .54):
        d.rectangle((s * x, s * .42, s * (x + .03), s * .82), fill=(0, 0, 0, 0))


def _card(d, s, ink):
    d.rounded_rectangle((s * .08, s * .2, s * .92, s * .8), s * .07, fill=ink)
    d.rectangle((s * .08, s * .32, s * .92, s * .42), fill=(0, 0, 0, 0))                     # the stripe
    d.rounded_rectangle((s * .18, s * .52, s * .34, s * .66), s * .02, fill=(0, 0, 0, 0))   # the chip


def _clock(d, s, ink):
    c, r = s * .5, s * .4
    d.ellipse((c - r, c - r, c + r, c + r), outline=ink, width=round(s * .08))
    d.line([(c, c), (c, c - r * .62)], fill=ink, width=round(s * .07))
    d.line([(c, c), (c + r * .46, c + r * .2)], fill=ink, width=round(s * .07))


MARKS = {'fuel': _fuel, 'cart': _cart, 'wrench': _wrench, 'tyre': _tyre, 'wash': _wash, 'charge': _charge,
         'cross': _cross, 'bank': _bank, 'cup': _cup, 'cutlery': _cutlery, 'beer': _beer, 'card': _card, 'clock': _clock}


def mark(name, size=256, ink=(255, 255, 255)):
    """The pictogram `name` in `ink` on a clear square of `size` px, drawn 4x and scaled down."""
    big = size * 4
    im = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    MARKS[name](ImageDraw.Draw(im), big, (*ink, 255))
    return im.resize((size, size), Image.Resampling.LANCZOS)
