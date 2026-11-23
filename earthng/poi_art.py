"""The pictograms of the points of interest (poi_types.py): what an info stand, a wall plaque or a
blade sign shows of its type without a word, so the same art reads in any country.

  python earthng/poi_art.py --lua               # mod/lua/ge/extensions/e2r/poi_lib.lua from poi_types.py
  python earthng/poi_art.py --sheet out/poi-marks.png

One atlas of PER x PER cells of CELL px: white marks as opacity (poi_marks_o.data.png) over a
white sheet, like the glyphs, so one mark is drawn in white on a plate of its group's colour and
in dark ink on a white board (fast_style 'poi_marks', 'poi_marks_dark'). A mark keeps its cell
by its place in poi_types.marks(). Drawn at art build time, nothing paid.
"""
import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

import poi_types

HERE = Path(__file__).resolve().parent
LUA = HERE.parent / 'mod/lua/ge/extensions/e2r/poi_lib.lua'
VERSION = '1'           # change whenever a mark's drawing or its cell changes
PER, CELL = 8, 256
INK, CLEAR = 255, 0


class Pen:
    """A drawing layer of side s with coordinates in 0..1."""
    def __init__(self, s):
        self.s = s
        self.im = Image.new('L', (s, s), CLEAR)
        self.d = ImageDraw.Draw(self.im)

    def _p(self, pts):
        return [(x * self.s, y * self.s) for x, y in pts]

    def poly(self, *pts, fill=INK):
        self.d.polygon(self._p(pts), fill=fill)

    def rect(self, x0, y0, x1, y1, fill=INK, r=0):
        box = (x0 * self.s, y0 * self.s, x1 * self.s, y1 * self.s)
        if r:
            self.d.rounded_rectangle(box, r * self.s, fill=fill)
        else:
            self.d.rectangle(box, fill=fill)

    def disc(self, x, y, r, fill=INK, ry=None):
        ry = r if ry is None else ry
        self.d.ellipse(((x - r) * self.s, (y - ry) * self.s, (x + r) * self.s, (y + ry) * self.s), fill=fill)

    def ring(self, x, y, r, w, fill=INK):
        self.d.ellipse(((x - r) * self.s, (y - r) * self.s, (x + r) * self.s, (y + r) * self.s), outline=fill, width=round(w * self.s))

    def line(self, *pts, w=.06, fill=INK):
        self.d.line(self._p(pts), fill=fill, width=round(w * self.s), joint='curve')
        for x, y in (pts[0], pts[-1]):
            self.disc(x, y, w / 2, fill)

    def arc(self, x, y, r, a0, a1, w=.06, fill=INK):
        self.d.arc(((x - r) * self.s, (y - r) * self.s, (x + r) * self.s, (y + r) * self.s), a0, a1, fill=fill, width=round(w * self.s))

    def pie(self, x, y, r, a0, a1, fill=INK):
        self.d.pieslice(((x - r) * self.s, (y - r) * self.s, (x + r) * self.s, (y + r) * self.s), a0, a1, fill=fill)


def _peak(p):
    p.poly((.06, .84), (.42, .2), (.62, .56), (.72, .42), (.94, .84))
    p.poly((.42, .2), (.33, .37), (.4, .44), (.45, .36), (.52, .42), fill=CLEAR)        # the snow cap's edge
    p.poly((.42, .2), (.36, .31), (.41, .36), (.45, .3), (.49, .33))


def _volcano(p):
    p.poly((.06, .86), (.36, .36), (.64, .36), (.94, .86))
    p.poly((.36, .36), (.5, .46), (.64, .36), fill=CLEAR)
    for x, y, r in ((.5, .24, .08), (.4, .14, .06), (.6, .12, .07)):
        p.disc(x, y, r)


def _pass(p):
    p.poly((.04, .84), (.3, .22), (.5, .62), (.7, .3), (.96, .84))
    p.line((.5, .84), (.5, .72), (.46, .64), w=.05, fill=CLEAR)                           # the road over it


def _drop(p, x, y, r):
    p.disc(x, y, r)
    p.poly((x - r * .92, y - r * .36), (x, y - r * 2.1), (x + r * .92, y - r * .36))


def _spring(p):
    _drop(p, .5, .5, .2)
    for r in (.3, .42):
        p.arc(.5, .66, r, 20, 160, w=.05)


def _waterfall(p):
    p.rect(.1, .14, .46, .26)
    p.rect(.1, .26, .24, .9)
    for x in (.34, .46, .58):
        p.line((x, .22), (x, .7), w=.07)
    for x in (.3, .46, .62, .78):
        p.disc(x, .82, .08)
    p.rect(.24, .82, .84, .9)


def _cave(p):
    p.poly((.04, .86), (.2, .4), (.42, .16), (.66, .22), (.84, .48), (.96, .86))
    p.pie(.5, .86, .26, 180, 360, fill=CLEAR)
    p.rect(.24, .8, .76, .87, fill=CLEAR)


def _rock(p):
    p.poly((.08, .84), (.2, .44), (.44, .2), (.6, .5), (.56, .84))
    p.poly((.5, .84), (.66, .46), (.86, .56), (.94, .84))
    p.line((.44, .2), (.4, .52), (.5, .84), w=.035, fill=CLEAR)


def _view(p):
    for x in (.3, .7):                                                                    # binoculars
        p.rect(x - .15, .2, x + .15, .74, r=.07)
        p.disc(x, .74, .15)
        p.disc(x, .74, .08, fill=CLEAR)
    p.rect(.42, .34, .58, .48)


def _castle(p):
    p.rect(.14, .44, .86, .88)
    for x in (.08, .7):
        p.rect(x, .22, x + .22, .88)
        for k in range(3):
            p.rect(x + k * .085, .12, x + k * .085 + .05, .24)
    for k in range(4):
        p.rect(.34 + k * .09, .34, .39 + k * .09, .46)
    p.pie(.5, .88, .11, 180, 360, fill=CLEAR)
    p.rect(.39, .78, .61, .89, fill=CLEAR)


def _gate(p):
    p.rect(.12, .2, .88, .88)
    p.poly((.06, .2), (.5, .04), (.94, .2))
    p.pie(.5, .56, .2, 180, 360, fill=CLEAR)
    p.rect(.3, .55, .7, .89, fill=CLEAR)


def _manor(p):
    p.poly((.04, .42), (.5, .12), (.96, .42))
    p.rect(.1, .42, .9, .88)
    for x in (.2, .44, .68):
        p.rect(x, .52, x + .12, .7, fill=CLEAR)
    p.rect(.44, .7, .56, .89, fill=CLEAR)
    p.rect(.7, .16, .8, .34)


def _ruins(p):
    p.poly((.08, .88), (.08, .3), (.2, .3), (.2, .42), (.3, .42), (.3, .24), (.42, .36), (.42, .88))
    p.poly((.56, .88), (.56, .5), (.66, .4), (.72, .56), (.84, .52), (.92, .88))
    p.rect(.2, .58, .3, .76, fill=CLEAR)
    p.rect(.04, .86, .96, .92)


def _dig(p):
    p.pie(.5, .86, .4, 180, 360)                                                          # a mound
    p.rect(.1, .84, .9, .9)
    p.line((.66, .1), (.44, .56), w=.05)                                                   # a spade in it
    p.poly((.38, .5), (.52, .56), (.42, .74), (.32, .66))


def _monument(p):
    p.poly((.42, .76), (.46, .12), (.5, .04), (.54, .12), (.58, .76))
    p.rect(.32, .76, .68, .84)
    p.rect(.22, .84, .78, .93)


def _memorial(p):
    p.rect(.24, .2, .76, .82, r=.14)
    p.rect(.24, .5, .76, .82)
    p.rect(.14, .82, .86, .92)
    for y in (.4, .52, .64):
        p.line((.36, y), (.64, y), w=.04, fill=CLEAR)


def _statue(p):
    p.disc(.5, .14, .08)
    p.poly((.38, .26), (.62, .26), (.66, .54), (.58, .54), (.58, .72), (.42, .72), (.42, .54), (.34, .54))
    p.line((.62, .3), (.76, .14), w=.06)                                                   # a raised arm
    p.rect(.3, .72, .7, .8)
    p.rect(.22, .8, .78, .93)


def _bust(p):
    p.disc(.5, .26, .15)
    p.poly((.24, .62), (.34, .44), (.66, .44), (.76, .62))
    p.rect(.36, .62, .64, .8)
    p.rect(.26, .8, .74, .92)


def _plaque(p):
    p.rect(.14, .2, .86, .8, r=.05)
    p.rect(.2, .26, .8, .74, fill=CLEAR, r=.03)
    for y, x1 in ((.38, .7), (.5, .7), (.62, .56)):
        p.line((.3, y), (x1, y), w=.05)
    for x, y in ((.17, .23), (.83, .23), (.17, .77), (.83, .77)):
        p.disc(x, y, .018, fill=CLEAR)


def _tank(p):
    p.rect(.1, .58, .9, .78, r=.1)
    for x in (.24, .41, .59, .76):
        p.disc(x, .68, .055, fill=CLEAR)
    p.poly((.2, .58), (.26, .46), (.74, .46), (.8, .58))
    p.rect(.36, .3, .64, .46, r=.04)
    p.line((.62, .37), (.94, .3), w=.05)


def _plane(p):
    p.poly((.5, .04), (.57, .2), (.57, .4), (.96, .62), (.96, .7), (.57, .6), (.56, .8), (.68, .9), (.68, .95),
           (.5, .9), (.32, .95), (.32, .9), (.44, .8), (.43, .6), (.04, .7), (.04, .62), (.43, .4), (.43, .2))


def _locomotive(p):
    p.rect(.1, .4, .62, .7, r=.03)
    p.rect(.58, .22, .9, .7)
    p.rect(.66, .3, .82, .46, fill=CLEAR)
    p.rect(.18, .22, .28, .42)
    p.poly((.14, .22), (.32, .22), (.3, .14), (.16, .14))
    for x, r in ((.24, .09), (.46, .09), (.74, .12)):
        p.disc(x, .76, r)
        p.disc(x, .76, r * .4, fill=CLEAR)
    p.poly((.1, .7), (.02, .84), (.1, .84))


def _cross(p):
    p.rect(.44, .08, .56, .86)
    p.rect(.22, .28, .78, .4)
    p.rect(.3, .86, .7, .94)


def _shrine(p):
    p.poly((.2, .4), (.5, .16), (.8, .4))
    p.rect(.28, .4, .72, .9)
    p.pie(.5, .66, .12, 180, 360, fill=CLEAR)
    p.rect(.38, .65, .62, .8, fill=CLEAR)
    p.rect(.475, .02, .525, .2)
    p.rect(.42, .07, .58, .11)


def _windmill(p):
    p.poly((.36, .92), (.44, .42), (.56, .42), (.64, .92))
    for k in range(4):
        a = math.radians(30 + k * 90)
        ux, uy = math.cos(a), math.sin(a)
        px, py = -uy, ux
        p.poly((.5 + ux * .06, .4 + uy * .06), (.5 + ux * .42 + px * .1, .4 + uy * .42 + py * .1),
               (.5 + ux * .42, .4 + uy * .42), (.5 + ux * .1 - px * .02, .4 + uy * .1 - py * .02))
        p.line((.5, .4), (.5 + ux * .42, .4 + uy * .42), w=.03)
    p.disc(.5, .4, .05)


def _lighthouse(p):
    p.poly((.36, .9), (.42, .36), (.58, .36), (.64, .9))
    p.rect(.38, .52, .62, .62, fill=CLEAR)
    p.rect(.37, .74, .63, .82, fill=CLEAR)
    p.rect(.36, .28, .64, .36)
    p.rect(.42, .16, .58, .28)
    p.poly((.4, .16), (.5, .06), (.6, .16))
    for side in (-1, 1):                                                                  # the beams
        p.poly((.5 + side * .12, .2), (.5 + side * .46, .1), (.5 + side * .46, .16))
        p.poly((.5 + side * .12, .24), (.5 + side * .46, .28), (.5 + side * .46, .34))
    p.rect(.26, .9, .74, .95)


def _tower(p):
    p.rect(.24, .1, .76, .44, r=.06)
    p.poly((.3, .44), (.7, .44), (.58, .56), (.42, .56))
    p.rect(.44, .56, .56, .9)
    p.line((.44, .9), (.3, .56), w=.035)
    p.line((.56, .9), (.7, .56), w=.035)
    p.rect(.24, .88, .76, .94)


def _museum(p):
    p.poly((.5, .06), (.94, .3), (.06, .3))
    p.rect(.1, .33, .9, .39)
    for x in (.16, .36, .56, .76):
        p.rect(x, .42, x + .08, .8)
    p.rect(.06, .83, .94, .93)


def _frame(p):
    p.rect(.1, .16, .9, .84)
    p.rect(.18, .24, .82, .76, fill=CLEAR)
    p.poly((.2, .74), (.4, .44), (.52, .6), (.62, .5), (.8, .74))
    p.disc(.68, .36, .055)


def _sculpture(p):
    p.ring(.5, .4, .26, .11)                                                              # an abstract form
    p.disc(.62, .26, .09)
    p.rect(.44, .64, .56, .8)
    p.rect(.26, .8, .74, .92)


def _star(p):
    pts = []
    for k in range(10):
        a = math.radians(-90 + k * 36)
        r = .44 if k % 2 == 0 else .18
        pts.append((.5 + math.cos(a) * r, .52 + math.sin(a) * r))
    p.poly(*pts)


def _paw(p):
    p.disc(.5, .66, .2, ry=.17)
    for x, y, r in ((.2, .44, .09), (.38, .26, .1), (.62, .26, .1), (.8, .44, .09)):
        p.disc(x, y, r, ry=r * 1.2)


def _wheel(p):
    p.ring(.5, .44, .36, .05)
    for k in range(8):
        a = math.radians(k * 45)
        p.line((.5, .44), (.5 + math.cos(a) * .34, .44 + math.sin(a) * .34), w=.025)
        p.disc(.5 + math.cos(a) * .36, .44 + math.sin(a) * .36, .055)
    p.line((.5, .44), (.3, .92), w=.05)
    p.line((.5, .44), (.7, .92), w=.05)
    p.rect(.2, .9, .8, .95)


def _fish(p):
    p.disc(.44, .5, .32, ry=.2)
    p.poly((.7, .5), (.94, .3), (.94, .7))
    p.disc(.28, .44, .035, fill=CLEAR)
    p.arc(.3, .5, .2, -50, 50, w=.03, fill=CLEAR)


def _info(p):
    p.disc(.5, .2, .1)
    p.rect(.4, .38, .6, .86)
    p.rect(.32, .38, .5, .47)
    p.rect(.3, .8, .7, .88)


def _book(p):
    p.poly((.5, .24), (.1, .16), (.1, .76), (.5, .86))
    p.poly((.5, .24), (.9, .16), (.9, .76), (.5, .86))
    p.line((.5, .24), (.5, .86), w=.03, fill=CLEAR)
    for y in (.36, .48, .6):
        p.line((.18, y - .05), (.42, y), w=.03, fill=CLEAR)
        p.line((.58, y), (.82, y - .05), w=.03, fill=CLEAR)


def _masks(p):
    p.rect(.08, .14, .56, .5)                                                             # the glad mask
    p.pie(.32, .5, .24, 0, 180)
    for x in (.22, .42):
        p.disc(x, .34, .045, fill=CLEAR)
    p.arc(.32, .46, .12, 20, 160, w=.04, fill=CLEAR)
    p.rect(.48, .4, .92, .68)                                                             # the sad one behind
    p.pie(.7, .68, .22, 0, 180)
    p.rect(.46, .36, .58, .76, fill=CLEAR)
    p.rect(.08, .14, .56, .5)
    p.pie(.32, .5, .24, 0, 180)
    for x in (.22, .42):
        p.disc(x, .34, .045, fill=CLEAR)
    p.arc(.32, .46, .12, 20, 160, w=.04, fill=CLEAR)
    for x in (.64, .8):
        p.disc(x, .56, .04, fill=CLEAR)
    p.arc(.72, .84, .1, 200, 340, w=.04, fill=CLEAR)


def _film(p):
    p.rect(.08, .36, .7, .84, r=.04)
    p.poly((.7, .52), (.92, .4), (.92, .8), (.7, .68))
    for x in (.26, .54):
        p.disc(x, .22, .13)
        p.disc(x, .22, .05, fill=CLEAR)


def _cap(p):
    p.poly((.5, .2), (.96, .42), (.5, .64), (.04, .42))
    p.poly((.24, .56), (.5, .68), (.76, .56), (.76, .74), (.5, .86), (.24, .74))
    p.line((.9, .44), (.9, .72), w=.035)
    p.disc(.9, .74, .04)


def _hospital(p):
    p.rect(.14, .14, .86, .86, r=.1)
    p.rect(.3, .28, .42, .72, fill=CLEAR)
    p.rect(.58, .28, .7, .72, fill=CLEAR)
    p.rect(.3, .44, .7, .56, fill=CLEAR)


def _plus(p):
    p.rect(.36, .12, .64, .88, r=.03)
    p.rect(.12, .36, .88, .64, r=.03)


def _tree(p):
    for x, y, r in ((.5, .28, .22), (.32, .44, .2), (.68, .44, .2), (.5, .5, .2)):
        p.disc(x, y, r)
    p.rect(.45, .58, .55, .9)
    p.rect(.3, .88, .7, .94)


def _flower(p):
    for k in range(6):
        a = math.radians(k * 60)
        p.disc(.5 + math.cos(a) * .17, .32 + math.sin(a) * .17, .11)
    p.disc(.5, .32, .08, fill=CLEAR)
    p.line((.5, .52), (.5, .92), w=.05)
    p.poly((.5, .78), (.72, .62), (.7, .78))
    p.poly((.5, .84), (.28, .68), (.3, .84))


def _stadium(p):
    p.disc(.5, .5, .44, ry=.32)
    p.disc(.5, .5, .3, ry=.19, fill=CLEAR)
    p.disc(.5, .5, .2, ry=.11)
    p.line((.5, .39), (.5, .61), w=.025, fill=CLEAR)


def _ball(p):
    p.disc(.5, .5, .4)
    pts = [(.5 + math.cos(math.radians(-90 + k * 72)) * .13, .5 + math.sin(math.radians(-90 + k * 72)) * .13) for k in range(5)]
    for k in range(5):
        a = math.radians(-90 + k * 72)
        p.line(pts[k], (.5 + math.cos(a) * .4, .5 + math.sin(a) * .4), w=.03, fill=CLEAR)
        p.line(pts[k], pts[(k + 1) % 5], w=.03, fill=CLEAR)


def _waves(p):
    for y in (.34, .54, .74):
        pts = [(.06 + k * .0293, y + math.sin(k * math.pi / 5) * .06) for k in range(31)]
        p.line(*pts, w=.07)


def _train(p):
    p.rect(.2, .08, .8, .74, r=.1)
    p.rect(.28, .18, .72, .42, fill=CLEAR, r=.03)
    for x in (.34, .66):
        p.disc(x, .58, .055, fill=CLEAR)
    p.line((.3, .74), (.16, .94), w=.05)
    p.line((.7, .74), (.84, .94), w=.05)
    p.line((.26, .86), (.74, .86), w=.04)


def _metro(p):
    p.ring(.5, .5, .42, .07)
    p.line((.26, .7), (.26, .32), (.5, .6), (.74, .32), (.74, .7), w=.09)


def _boat(p):
    p.poly((.06, .6), (.94, .6), (.8, .82), (.2, .82))
    p.rect(.3, .42, .7, .6)
    p.rect(.44, .24, .56, .42)
    for x in (.36, .5, .64):
        p.disc(x, .51, .03, fill=CLEAR)
    pts = [(.04 + k * .046, .9 + math.sin(k * math.pi / 2.5) * .025) for k in range(21)]
    p.line(*pts, w=.04)


def _bus(p):
    p.rect(.14, .12, .86, .78, r=.08)
    p.rect(.2, .2, .8, .46, fill=CLEAR, r=.03)
    p.line((.5, .2), (.5, .46), w=.03)
    for x in (.28, .72):
        p.disc(x, .64, .045, fill=CLEAR)
        p.rect(x - .08, .78, x + .08, .9, r=.03)


def _bag(p):
    p.poly((.16, .34), (.84, .34), (.9, .9), (.1, .9))
    p.arc(.5, .36, .17, 180, 360, w=.055)
    for x in (.33, .67):
        p.disc(x, .44, .035, fill=CLEAR)


def _bread(p):
    p.disc(.5, .52, .42, ry=.26)
    p.rect(.1, .56, .9, .78, r=.08)
    for x in (.3, .5, .7):
        p.line((x - .06, .38), (x + .06, .58), w=.04, fill=CLEAR)


def _knife(p):
    p.poly((.12, .2), (.62, .2), (.62, .5), (.26, .5), (.12, .34))                          # a cleaver
    p.rect(.62, .27, .92, .39, r=.03)
    p.disc(.2, .28, .03, fill=CLEAR)
    p.rect(.14, .64, .86, .72, r=.03)                                                      # the block
    p.rect(.22, .72, .3, .88)
    p.rect(.7, .72, .78, .88)


def _hanger(p):
    p.arc(.5, .2, .09, 150, 400, w=.045)
    p.line((.5, .29), (.5, .4), w=.045)
    p.line((.5, .4), (.08, .68), (.92, .68), (.5, .4), w=.06)
    p.rect(.14, .68, .86, .74, r=.02)


def _screen(p):
    p.rect(.08, .16, .92, .7, r=.05)
    p.rect(.15, .23, .85, .63, fill=CLEAR)
    p.rect(.44, .7, .56, .82)
    p.rect(.28, .82, .72, .89, r=.02)


def _scissors(p):
    for x in (.32, .68):
        p.ring(x, .76, .13, .055)
    p.line((.38, .66), (.72, .1), w=.07)
    p.line((.62, .66), (.28, .1), w=.07)
    p.disc(.5, .46, .03, fill=CLEAR)


def _gem(p):
    p.poly((.26, .2), (.74, .2), (.94, .44), (.5, .9), (.06, .44))
    p.line((.06, .44), (.94, .44), w=.03, fill=CLEAR)
    p.line((.26, .2), (.38, .44), (.5, .9), w=.03, fill=CLEAR)
    p.line((.74, .2), (.62, .44), (.5, .9), w=.03, fill=CLEAR)
    p.line((.5, .2), (.38, .44), w=.03, fill=CLEAR)
    p.line((.5, .2), (.62, .44), w=.03, fill=CLEAR)


def _bottle(p):
    p.rect(.43, .06, .57, .3)
    p.poly((.43, .3), (.57, .3), (.68, .46), (.68, .9), (.32, .9), (.32, .46))
    p.rect(.37, .56, .63, .76, fill=CLEAR)
    p.rect(.41, .04, .59, .1)


def _bike(p):
    for x in (.24, .76):
        p.ring(x, .64, .2, .05)
    p.line((.24, .64), (.42, .36), (.68, .36), (.76, .64), w=.045)
    p.line((.42, .36), (.52, .64), (.68, .36), w=.045)
    p.line((.24, .64), (.52, .64), w=.045)
    p.line((.36, .3), (.48, .3), w=.05)
    p.line((.68, .36), (.64, .22), (.74, .2), w=.045)


def _chair(p):
    p.rect(.22, .1, .32, .9, r=.02)
    p.rect(.22, .5, .78, .6, r=.02)
    p.rect(.68, .5, .78, .9, r=.02)
    p.rect(.22, .14, .4, .46, r=.03)


def _hammer(p):
    p.poly((.2, .18), (.66, .18), (.72, .26), (.72, .36), (.2, .36), (.1, .27))
    p.line((.48, .36), (.72, .9), w=.1)


def _toy(p):
    p.rect(.14, .5, .5, .86, r=.03)                                                        # blocks
    p.rect(.5, .5, .86, .86, r=.03)
    p.rect(.32, .14, .68, .5, r=.03)
    p.line((.5, .5), (.5, .86), w=.03, fill=CLEAR)
    p.line((.14, .5), (.86, .5), w=.03, fill=CLEAR)
    p.disc(.5, .32, .07, fill=CLEAR)


def _car(p):
    p.poly((.08, .72), (.08, .52), (.22, .48), (.34, .3), (.68, .3), (.8, .48), (.92, .52), (.92, .72))
    p.poly((.3, .46), (.38, .35), (.49, .35), (.49, .46), fill=CLEAR)
    p.poly((.53, .46), (.53, .35), (.64, .35), (.72, .46), fill=CLEAR)
    for x in (.28, .72):
        p.disc(x, .72, .11)
        p.disc(x, .72, .045, fill=CLEAR)


MARKS = {name[1:]: f for name, f in list(globals().items()) if name.startswith('_') and callable(f) and name != '_drop'}


def mark(name, size=CELL):
    """The pictogram `name` as opacity (L) on a clear square of `size` px, drawn 4x and scaled down,
    inside a margin of a tenth: a neighbour's mips never reach it."""
    pen = Pen(size * 4)
    MARKS[name](pen)
    inner = round(size * .8)
    out = Image.new('L', (size, size), CLEAR)
    out.paste(pen.im.resize((inner, inner), Image.Resampling.LANCZOS), ((size - inner) // 2, (size - inner) // 2))
    return out


def cells():
    """mark -> its cell in the atlas."""
    names = poi_types.marks()
    if len(names) > PER * PER:
        raise ValueError(f'{len(names)} marks, the atlas holds {PER * PER}')
    return {name: k for k, name in enumerate(names)}


def build(real):
    """poi_marks.color.png (white) and poi_marks_o.data.png (the marks) in `real`, flipped like
    the glyphs so v grows upward."""
    size = PER * CELL
    alpha = Image.new('L', (size, size), CLEAR)
    for name, k in cells().items():
        alpha.paste(mark(name), (k % PER * CELL, k // PER * CELL))
    Image.new('RGB', (64, 64), (255, 255, 255)).save(real / 'poi_marks.color.png')
    alpha.convert('RGB').transpose(Image.FLIP_TOP_BOTTOM).save(real / 'poi_marks_o.data.png')
    (real / 'poi.version').write_text(VERSION)


def lua_text():
    """poi_lib.lua: the types, their marks' cells and the groups' plate colours."""
    def q(text):
        return json.dumps(text, ensure_ascii=False)
    cell = cells()
    rows = []
    for key in sorted(poi_types.TYPES):
        t = poi_types.TYPES[key]
        fields = [f'cell = {cell[t["mark"]]}', f'group = {q(t["group"])}', f'look = {q(t["look"])}']
        if t['bare']:
            fields.append('bare = true')
        fields += [f'uk = {q(t["uk"])}', f'en = {q(t["en"])}']
        if t['textUk']:
            fields += [f'textUk = {q(t["textUk"])}', f'textEn = {q(t["textEn"])}']
        rows.append(f'    [{q(key)}] = {{{", ".join(fields)}}},')
    return '\n'.join([
        '-- Generated by earthng/poi_art.py (--lua) from poi_types.py: the types of the points of interest.',
        '-- Do not edit.',
        f'return {{version = {VERSION}, per = {PER},',
        '  -- the tag keys a type is looked up by, the most telling first',
        '  keys = {' + ', '.join(q(k) for k in poi_types.KEYS) + '},',
        "  -- group -> YARD.cell name (generator.lua): its plates' colour",
        '  groups = {' + ', '.join(f'{g} = {q(c)}' for g, c in sorted(poi_types.GROUPS.items())) + '},',
        "  -- a category's own type where no key tells more",
        '  category = {' + ', '.join(f'{c} = {q(k)}' for c, k in sorted(poi_types.CATEGORY.items())) + '},',
        '  types = {', *rows, '  }}', ''])


def sheet(path):
    """The marks white on their groups' colours, their names under them: for the eye."""
    import fast_art
    from PIL import ImageFont
    names = poi_types.marks()
    group = {}
    for t in poi_types.TYPES.values():
        group.setdefault(t['mark'], t['group'])
    yard = dict(zip(('red', 'yellow', 'blue', 'green', 'orange', 'wood', 'metal', 'dark', 'sand', 'paint', 'white', 'rubber',
                     'concrete', 'bollard', 'light', 'brown'), fast_art.YARD_COLOURS))
    per, px = 11, 128
    out = Image.new('RGB', (per * (px + 8), ((len(names) + per - 1) // per) * (px + 26)), (236, 236, 232))
    d = ImageDraw.Draw(out)
    font = ImageFont.load_default()
    for k, name in enumerate(names):
        x, y = k % per * (px + 8) + 4, k // per * (px + 26) + 4
        d.rounded_rectangle((x, y, x + px, y + px), 12, fill=yard[poi_types.GROUPS[group[name]]])
        out.paste((255, 255, 255), (x, y), mark(name, px))
        d.text((x + 4, y + px + 4), name, fill=(20, 20, 20), font=font)
    out.save(path)
    return len(names)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--lua', action='store_true', help='write poi_lib.lua from poi_types.py')
    ap.add_argument('--sheet', type=Path)
    a = ap.parse_args()
    if a.lua:
        LUA.write_text(lua_text(), encoding='utf8', newline='\n')
        print(f'{LUA.name}: {len(poi_types.TYPES)} types, {len(cells())} marks')
    if a.sheet:
        print('sheet of', sheet(a.sheet), 'marks')
