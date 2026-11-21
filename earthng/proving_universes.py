"""The universes round the proving ground's main grid (proving_ground.BLOCKS; the rules are
mod/lua/ge/extensions/e2r/universe.lua): a mountain range in the north, a desert in the south,
deep snow in the west, deep mud in the east, and a rainforest in the south-east corner.

A universe is tested by what it does to ordinary things, so each has the same SAMPLE of the
main grid's subjects (a panel block, a village, a motorway, a dirt road, a river with its
bridge, fields, a wood, road signs and so on), built again in its tiles by the very functions
of proving_zones.py, and beyond them land of its own: a pass road and a village on the slope,
a highway through the dunes and an oasis, an ice road over a frozen lake, a bog with a ford.
A rule tuned here has every kind of place to go wrong in before it meets the world.
"""
import math

from proving_ground import BLOCK, GRID, RING, TILE, code, tags
import proving_zones as z

# The main grid's subjects every universe builds again, the most telling first: (theme, place in
# the theme's row). A universe on the west or east side has room for the first 24.
SAMPLE = (
    ('town', 3), ('works', 0), ('classes', 0), ('surfaces', 9),        # panel block, village, motorway, dirt road
    ('water', 0), ('covers', 0), ('plants', 0), ('street', 5),         # river and bridge, open ground, woods, signs
    ('town', 0), ('works', 4), ('classes', 8), ('surfaces', 5),        # old town, plant, residential street, cobbles
    ('water', 7), ('covers', 2), ('relief', 1), ('street', 3),         # level crossing, fields, a 10 % grade, stops
    ('town', 5), ('works', 7), ('lanes', 3), ('surfaces', 8),          # new towers, fuel, four lanes, gravel
    ('water', 2), ('covers', 10), ('plants', 4), ('works', 9),         # lake, parks, park and garden, roadside shops
    ('town', 7), ('works', 3), ('classes', 4), ('street', 1),          # retail, farm, primary road, street trees
    ('relief', 11), ('covers', 6), ('street', 7), ('works', 12),       # studio, rock and water, fences, car parks
)


def name(named, x, y, title, title_en):
    """A place of a universe's own land: its tile takes the name and the car lands there."""
    named[(math.floor(x / TILE), math.floor(y / TILE))] = (title, title_en, x, y)


def wild(plan, block_id, named):
    """Every tile of a block without a subject: the universe's own land."""
    b = BLOCK[block_id]
    i0, i1, j0, j1 = b['tiles']
    for j in range(j0, j1):
        for i in range(i0, i1):
            if code(i, j) in plan.tiles:
                continue
            title, title_en, x, y = named.get((i, j)) or (b['title'], b['titleEn'], i * TILE + 250, j * TILE + 250)
            z.register(plan, i, j, 'wild', title, title_en)
            # the landing stays inside the tile it names (a summit may stand on a tile's edge)
            plan.tiles[code(i, j)]['at'] = (min(max(x, i * TILE + 20), i * TILE + TILE - 20),
                                            min(max(y, j * TILE + 20), j * TILE + TILE - 20))


def sample_rows(plan, block_id, rows, junctions):
    """The sample along two rows of a block (north or south of the main grid): the meridian
    crosses both, in a junction of its own kind each, and the rows' ends are joined."""
    i0, i1 = BLOCK[block_id]['tiles'][:2]
    n = 0
    for j, junction in zip(rows, junctions):
        for i in range(i0, i1):
            if i == 0:
                z.junction_tile(plan, 0, j, junction)
            else:
                theme, k = SAMPLE[n]
                z.TILES[theme](plan, i, j, k)
                n += 1
    ya, yb = z.centre_y(rows[0]), z.centre_y(rows[1])
    for x in (i0 * TILE + 8, i1 * TILE - 8):
        plan.way([(x, ya), (x, yb)], tags('highway=residential', name='Об’їзд'))


def sample_columns(plan, block_id, cols, collector, ring_x):
    """The sample in two columns of a block (west or east of the main grid), a row's avenue a
    kilometre long: every row runs out to a collector road on the wild side and, where the ring
    road passes it, to the ring."""
    j0, j1 = BLOCK[block_id]['tiles'][2:]
    far = cols[0] * TILE if collector < cols[0] * TILE else (cols[-1] + 1) * TILE      # the edge by the collector
    near = (cols[-1] + 1) * TILE if far == cols[0] * TILE else cols[0] * TILE          # the edge by the main grid
    n = 0
    for j in range(j1 - 1, j0 - 1, -1):
        for i in cols:
            theme, k = SAMPLE[n]
            z.TILES[theme](plan, i, j, k)
            n += 1
        yc = z.centre_y(j)
        plan.way([(far, yc), (collector, yc)], tags('highway=tertiary'))
        if GRID[1] < yc < GRID[3]:
            plan.way([(near, yc), (ring_x, yc)], tags('highway=tertiary', name=f'До кільцевої, ряд {j - j0 + 1}'))
    plan.way([(collector, z.centre_y(j0)), (collector, z.centre_y(j1 - 1))], tags('highway=tertiary', name='Збірна дорога'))


def basin(plan, cx, cy, r, drop=1.5):
    """A level floor of radius r where the land is not level (a lake needs one), 80 m of bank."""
    import numpy as np
    level = float(plan.height(np.float64(cx), np.float64(cy))) - drop

    def carve(x, y, h):
        d = np.hypot(x - cx, y - cy)
        w = z.smooth_((r + 80. - d) / 80.)
        return h * (1 - w) + level * w
    plan.carve.append(carve)
    return level


def circle(plan, cx, cy, r, tag, step=10.):
    return plan.area(plan.arc(cx, cy, r, 0, 360, step=step)[:-1], tag)


# --- mountains ------------------------------------------------------------------------------------
PEAKS = ((-2900., 5150., 820., 650., 520., 'Західна вершина', 'West Peak'),
         (-1300., 5250., 1120., 700., 560., 'Гора Немо', 'Mount Nemo'),
         (600., 5150., 930., 620., 520., 'Середня вершина', 'Middle Peak'),
         (2500., 5250., 1040., 700., 540., 'Східна вершина', 'East Peak'))


def mountains(plan):
    """A range of four peaks (Mount Nemo, 1290 m) behind two rows of the sample at its foot: a pass
    road in hairpins to the saddle at 395 m, a village on the slope, a tarn, a ski run, a pasture,
    a glacier."""
    sample_rows(plan, 'mountains', (6, 7), (10, 9))
    xm = z.MERIDIAN
    plan.way([(xm, GRID[3] + RING), (xm, 6 * TILE)], tags('highway=tertiary', name='Меридіан'))

    def massif(x, y):
        import numpy as np
        foot = z.smooth_((y - 4000.) / 650.)
        inside = z.smooth_((x + 4000.) / 500.) * z.smooth_((4000. - x) / 500.)
        ridge = sum(h * np.exp(-((x - px) / sx) ** 2 - ((y - py) / sy) ** 2) for px, py, h, sx, sy, *_ in PEAKS)
        high = 150. * z.smooth_((y - 4050.) / 900.)
        spurs = 55. * np.sin(x / 310.) * np.sin(y / 270.) + 30. * np.sin(x / 130. + 1.7) * np.cos(y / 170.)
        return (high + ridge + spurs * z.smooth_((high + ridge) / 220.)) * foot * inside
    plan.relief.append(massif)
    named = {}

    def ele(x, y):
        import numpy as np
        return round(float(plan.height(np.float64(x), np.float64(y))))

    # the pass road: from the meridian's end in hairpins up the valley between Mount Nemo and the
    # Middle Peak, 12-14 % on its steep legs
    road = [(xm, 4000.), (xm, 4070.), (70., 4170.), (-770., 4335.), (30., 4500.), (-560., 4640.), (-100., 4720.),
            (-520., 4800.), (-80., 4880.), (-450., 4995.), (-350., 5180.)]
    plan.way(road, tags('highway=secondary lanes=2', name='Перевальна дорога'))
    plan.node(-350., 5180., tags('highway=turning_circle tourism=viewpoint mountain_pass=yes', name='Перевал Немо', ele=ele(-350., 5180.)))
    z.house(plan, -320., 5150., 12, 8, tags('building=hut tourism=alpine_hut building:levels=2 roof:shape=gabled', name='Притулок на перевалі'))
    name(named, -350., 5180., 'Перевал', 'The pass')
    name(named, -200., 4250., 'Перевальна дорога', 'Pass road')
    # a village along the second leg: houses on both sides, a church above it, an inn
    (ax, ay), (bx, by) = road[3], road[4]
    length = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / length, (by - ay) / length
    turn = math.degrees(math.atan2(uy, ux))
    for k in range(12):
        t = 120 + k * 52
        side = 1 if k % 2 else -1
        z.house(plan, ax + ux * t - uy * side * 15, ay + uy * t + ux * side * 15, 10, 8,
                tags('building=house roof:shape=gabled', building__levels=1 + k % 2, addr__housenumber=k + 1), angle=turn)
    z.house(plan, ax + ux * 420 - uy * 45, ay + uy * 420 + ux * 45, 12, 24,
            tags('building=church amenity=place_of_worship height=22', name='Гірська церква'), angle=turn)
    z.house(plan, ax + ux * 520 + uy * 40, ay + uy * 520 - ux * 40, 26, 12,
            tags('building=hotel tourism=guest_house building:levels=3 roof:shape=gabled', name='Корчма «Під перевалом»'), angle=turn)
    name(named, ax + ux * 400, ay + uy * 400, 'Гірське село', 'Mountain village')
    # the summits, a path to the highest and a glacier under it
    for px, py, h, _, _, title, title_en in PEAKS:
        plan.node(px, py, tags('natural=peak', name=title, name__en=title_en, ele=ele(px, py)))
        name(named, px, py, title, title_en)
    plan.way([(-350., 5180.), (-800., 5230.), (-1300., 5250.)], tags('highway=path sac_scale=mountain_hiking', name='Стежка на гору Немо'))
    circle(plan, -1300., 5500., 170., tags('natural=glacier', name='Льодовик Немо'), step=20.)
    # a tarn in a hollow of the east side, its stream running down to a pond at the foot
    basin(plan, 1350., 4600., 85.)
    circle(plan, 1350., 4600., 80., tags('natural=water water=lake', name='Гірське озеро'))
    plan.way([(1350., 4520.), (1420., 4350.), (1380., 4180.), (1400., 4090.)], tags('waterway=stream', name='Потік'))
    circle(plan, 1400., 4065., 22., tags('natural=water water=pond'))
    name(named, 1350., 4600., 'Гірське озеро', 'Tarn')
    # a ski run under the East Peak: the road to the lodge runs up between two tiles of the sample
    plan.way([(2000., z.centre_y(7)), (2000., 4150.), (2300., 4330.)], tags('highway=residential', name='Курортна'))
    z.house(plan, 2330., 4385., 30, 14, tags('building=hotel tourism=hotel building:levels=3 roof:shape=gabled', name='Лижна база'))
    plan.area([(2275., 4430.), (2325., 4430.), (2525., 5050.), (2475., 5050.)],
              tags('landuse=meadow piste:type=downhill', name='Лижна траса'))
    plan.way([(2300., 4420.), (2500., 5060.)], tags('aerialway=chair_lift', name='Підйомник'))
    name(named, 2330., 4385., 'Лижний курорт', 'Ski resort')
    # a pasture in the west, reached by a track
    plan.way([(-2000., z.centre_y(7)), (-2000., 4200.), (-2250., 4500.)], tags('highway=track tracktype=grade3', name='Дорога на полонину'))
    for k in range(5):
        z.house(plan, -2290. - k * 22, 4520. + (k % 2) * 26, 6, 5, tags('building=hut building:levels=1 roof:shape=gabled'))
    circle(plan, -2500., 4750., 150., tags('natural=grassland', name='Полонина'), step=25.)
    name(named, -2250., 4500., 'Полонина', 'Alpine pasture')
    wild(plan, 'mountains', named)
    plan.zones.append({'id': 'mountains', 'title': 'Всесвіт: гори', 'titleEn': 'Universe: mountains',
                       'start': (BLOCK['mountains']['tiles'][0] * TILE + 30, z.centre_y(6) - 1.6)})


# --- desert ---------------------------------------------------------------------------------------
def desert(plan):
    """Two rows of the sample, then dunes, a mesa, a dry river: a highway eight kilometres straight
    through the dune field, an oasis with its village, an oil field, a fuel stop."""
    sample_rows(plan, 'desert', (-7, -8), (6, 3))
    xm = z.MERIDIAN
    plan.way([(xm, GRID[1] - RING), (xm, -6 * TILE)], tags('highway=tertiary', name='Меридіан'))
    named = {}

    def dunes(x, y):
        import numpy as np
        field = (z.smooth_((x + 3900.) / 300.) * z.smooth_((700. - x) / 300.)
                 * z.smooth_((-4050. - y) / 200.) * z.smooth_((y + 5480.) / 150.))
        crest = np.abs(np.sin((x + .55 * y) / 105.)) ** 1.6
        size = .55 + .45 * np.sin(y / 420. + x / 760.)
        return 16. * crest * size * field

    def mesa(x, y):
        import numpy as np
        return 70. * z.smooth_((400. - np.hypot(x - 2700., y + 5200.)) / 130.)

    def outcrop(x, y):
        import numpy as np
        return 28. * z.smooth_((190. - np.hypot(x + 3000., y + 4330.)) / 190.) ** 2
    plan.relief += [dunes, mesa, outcrop]
    plan.rect(-3900., -5480., 700., -4050., tags('natural=sand', name='Дюни'))

    # the highway and the road down to the south shore
    main = tags('highway=primary lanes=2 maxspeed=110 surface=asphalt', name='Пустельне шосе')
    plan.way([(xm, -4000.), (xm, -4750.)], tags('highway=primary lanes=2', name='Меридіан'))
    plan.way([(-3900., -4750.), (-1500., -4750.), (-700., -4750.), (xm, -4750.), (1330., -4750.)], main)
    plan.way([(1330., -4750.), (1410., -4750.)], dict(main, bridge='yes', layer='1'))
    plan.way([(1410., -4750.), (1700., -4750.), (2200., -4750.), (3900., -4750.)], main)
    for x in (-3900., 3900.):
        plan.node(x, -4750., tags('highway=turning_circle'))
    plan.way([(xm, -4750.), (xm, -5450.)], tags('highway=tertiary', name='До південного берега'))
    plan.node(xm, -5450., tags('highway=turning_circle'))
    name(named, -2500., -4750., 'Шосе крізь дюни', 'Highway through the dunes')
    name(named, xm, -5400., 'Південний берег', 'South shore')
    # a dry river from the north, under the highway's bridge, to the sea
    wadi = [(1150., -4150.), (1280., -4500.), (1370., -4750.), (1300., -5100.), (1100., -5450.)]
    plan.way(wadi, tags('waterway=stream intermittent=yes', name='Ваді'))
    z._bed(plan, wadi, 55., 5.)
    name(named, 1370., -4700., 'Міст через ваді', 'Wadi bridge')
    # the oasis: a pond in a level hollow of the dunes, palms round it, a village on the road in
    basin(plan, -1500., -4400., 150., drop=3.)
    circle(plan, -1500., -4400., 55., tags('natural=water water=pond', name='Оаза'))
    for k in range(36):
        a = math.radians(k * 10 + (k % 3) * 3)
        r = 72 + (k % 4) * 14
        plan.node(-1500. + r * math.cos(a), -4400. + r * math.sin(a), tags('natural=tree leaf_type=palm genus=Phoenix'))
    plan.way([(-1500., -4750.), (-1500., -4540.)], tags('highway=residential surface=compacted', name='До оази'))
    plan.node(-1500., -4540., tags('highway=turning_circle'))
    for k in range(10):
        side = 1 if k % 2 else -1
        z.house(plan, -1500. + side * 17, -4715. + (k // 2) * 36, 10, 9,
                tags('building=house roof:shape=flat', building__levels=1 + k % 2, building__material='plaster'))
    name(named, -1500., -4560., 'Оаза', 'Oasis')
    # a mesa south of the highway: a track winds up it to a mast
    track = [(2200., -4750.), (2300., -4900.)]
    for k in range(41):
        t = k / 40.
        a = math.radians(150 + 400 * t)
        r = 400 - 130 * t
        track.append((2700. + r * math.cos(a), -5200. + r * math.sin(a)))
    track.append((2700., -5200.))
    plan.way(track, tags('highway=track tracktype=grade3 surface=gravel', name='Дорога на столову гору'))
    plan.node(2700., -5200., tags('man_made=mast tower:type=communication height=40 tourism=viewpoint', name='Столова гора'))
    name(named, 2700., -5200., 'Столова гора', 'Mesa')
    # an oil field north of the highway
    plan.rect(1500., -4600., 1900., -4150., tags('landuse=industrial', name='Нафтопромисел'))
    plan.way([(1700., -4750.), (1700., -4300.)], tags('highway=service'))
    for k in range(4):
        circle(plan, 1560. + k * 90, -4220., 14., tags('man_made=storage_tank building=storage_tank height=10'), step=6.)
    for k in range(6):
        plan.node(1560. + (k % 3) * 120, -4420. - (k // 3) * 90, tags('man_made=petroleum_well'))
    z.house(plan, 1760., -4520., 24, 10, tags('building=industrial building:levels=1'))
    name(named, 1700., -4400., 'Нафтопромисел', 'Oil field')
    # a fuel stop on the highway
    plan.rect(-770., -4850., -630., -4775., tags('amenity=fuel', name='АЗС «Міраж»'))
    z.house(plan, -700., -4800., 40, 14, tags('building=roof layer=1 height=6'))
    z.house(plan, -700., -4832., 26, 12, tags('building=retail shop=convenience building:levels=1 roof:shape=flat', name='АЗС «Міраж»'))
    plan.way([(-790., -4750.), (-760., -4800.), (-640., -4800.), (-610., -4750.)], tags('highway=service oneway=yes'))
    name(named, -700., -4780., 'АЗС у пустелі', 'Desert fuel stop')
    wild(plan, 'desert', named)
    plan.zones.append({'id': 'desert', 'title': 'Всесвіт: пустеля', 'titleEn': 'Universe: desert',
                       'start': (BLOCK['desert']['tiles'][0] * TILE + 30, z.centre_y(-7) - 1.6)})


# --- snow -----------------------------------------------------------------------------------------
def snow(plan):
    """Two columns of the sample, then the north: an ice road over a frozen lake to a fishing
    camp, the taiga with a winter track through it, a polar station, a village under a ski hill."""
    collector = -5008.
    sample_columns(plan, 'snow', (-10, -9), collector, GRID[0] - RING)
    named = {}

    def drifts(x, y):
        import numpy as np
        land = z.smooth_((-5060. - x) / 200.)
        hill = 130. * z.smooth_((460. - np.hypot(x + 5950., y - 2250.)) / 460.)
        return (6. + 6. * np.sin(x / 260.) * np.sin(y / 330.) + 3. * np.sin(x / 95. + y / 140.)) * land + hill
    plan.relief.append(drifts)

    # the frozen lake and the ice road across it
    basin(plan, -5800., -300., 430., drop=2.)
    lake = [(-5800. + 420. * math.cos(math.radians(a)), -300. + 300. * math.sin(math.radians(a))) for a in range(0, 360, 8)]
    plan.area(lake, tags('natural=glacier', name='Крижане озеро'))
    plan.way([(collector, z.centre_y(-1)), (-5380., -280.), (-6220., -320.), (-6350., -300.)],
             tags('highway=track ice_road=yes surface=ice', name='Крижана дорога'))
    for k in range(6):
        z.house(plan, -6370. - (k % 3) * 14, -280. + (k // 3) * 40 - 20, 5, 4, tags('building=hut building:levels=1'))
    name(named, -5800., -290., 'Крижане озеро', 'Frozen lake')
    name(named, -6340., -300., 'Рибальський табір', 'Fishing camp')
    # the taiga and a winter track round it
    plan.rect(-6450., -2950., -5100., -1150., tags('landuse=forest leaf_type=needleleaved', name='Тайга'))
    plan.way([(collector, z.centre_y(-4)), (-6300., -1750.), (-6300., -2600.), (-5200., -2600.), (collector, z.centre_y(-6))],
             tags('highway=track tracktype=grade3', name='Зимник'))
    name(named, -5800., -1750., 'Тайга', 'Taiga')
    # a polar station
    plan.way([(collector, z.centre_y(1)), (-5700., 750.)], tags('highway=unclassified', name='До станції'))
    plan.rect(-5900., 640., -5700., 860., tags('barrier=fence fence_type=metal'))
    for k in range(4):
        z.house(plan, -5760. - (k % 2) * 60, 700. + (k // 2) * 80, 22, 9, tags('building=yes building:levels=1 roof:shape=flat', name=f'Модуль {k + 1}'))
    z.house(plan, -5870., 760., 12, 12, tags('building=yes roof:shape=dome height=8', name='Купол'))
    plan.node(-5870., 680., tags('man_made=mast tower:type=communication height=30'))
    for k in range(3):
        circle(plan, -5730. - k * 26, 670., 8., tags('man_made=storage_tank building=storage_tank height=5'), step=5.)
    name(named, -5720., 750., 'Полярна станція', 'Polar station')
    # a village on the road to the ski hill, a run down the hill
    plan.way([(collector, z.centre_y(4)), (-5480., 2250.)], tags('highway=residential', name='Північна вулиця'))
    for k in range(12):
        side = 1 if k % 2 else -1
        z.house(plan, -5070. - (k // 2) * 62, 2250. + side * 16, 10, 8,
                tags('building=house roof:shape=gabled building:material=wood', building__levels=1 + k % 2, addr__housenumber=k + 1))
    z.house(plan, -5500., 2290., 28, 12, tags('building=hotel tourism=hotel building:levels=2 roof:shape=gabled', name='Лижна хата'))
    plan.area([(-5520., 2228.), (-5520., 2272.), (-5950., 2262.), (-5950., 2238.)], tags('landuse=meadow piste:type=downhill', name='Спуск'))
    plan.node(-5950., 2250., tags('natural=peak ele=142', name='Лижна гора'))
    name(named, -5300., 2248., 'Північне село', 'Northern village')
    name(named, -5950., 2250., 'Лижна гора', 'Ski hill')
    plan.way([(-6400., 1400.), (-5100., 1400.)], tags('barrier=fence fence_type=wood', name='Оленяча огорожа'))
    wild(plan, 'snow', named)
    plan.zones.append({'id': 'snow', 'title': 'Всесвіт: сніг', 'titleEn': 'Universe: snow',
                       'start': (-10 * TILE + 30, z.centre_y(0) - 1.6)})


# --- mud ------------------------------------------------------------------------------------------
def mud(plan):
    """Two columns of the sample, then the lowland: a river with fords, a bog with its pools, peat
    fields cut by ditches, a logging ground of tracks, a village whose streets were never paved."""
    collector = 5008.
    sample_columns(plan, 'mud', (8, 9), collector, GRID[2] + RING)
    named = {}

    def lowland(x, y):
        import numpy as np
        land = z.smooth_((x - 5060.) / 400.)
        return (-7. + 1.4 * np.sin(x / 32.) * np.sin(y / 40.)) * land
    plan.relief.append(lowland)

    # the river: meanders from north to south, the tracks cross it by fords
    def river_x(y):
        return 6000. + 120. * math.sin(y / 260.)
    line = [(river_x(y), float(y)) for y in range(2900, -2901, -100)]
    plan.way(line, tags('waterway=river', name='Грузька'))
    plan.area([(x - 14, y) for x, y in line] + [(x + 14, y) for x, y in line[::-1]], tags('natural=water water=river'))
    z._bed(plan, line, 60., 3.)
    # the bog and its pools, a track through it to a hunting cabin over the river
    plan.rect(5080., -2950., 5850., -1500., tags('natural=wetland wetland=bog', name='Велике болото'))
    for k in range(12):
        circle(plan, 5150. + (k * 211) % 640, -2880. + (k * 337) % 1300, 14. + (k % 4) * 5, tags('natural=water water=pond'), step=6.)
    y = z.centre_y(-5)
    plan.way([(collector, y), (river_x(y), y), (6350., y)], tags('highway=track tracktype=grade5 surface=mud', name='Гать'))
    plan.node(river_x(y), y, tags('ford=yes'))
    z.house(plan, 6370., y + 14, 7, 6, tags('building=cabin building:levels=1 roof:shape=gabled', name='Мисливська хата'))
    name(named, 5450., -2200., 'Велике болото', 'Great bog')
    name(named, 6350., y, 'Мисливська хата', 'Hunting cabin')
    # peat fields: bare cut ground between ditches
    plan.rect(5080., -1350., 5850., -350., tags('landuse=farmland', name='Торфовище'))
    for k in range(7):
        plan.way([(5100. + k * 120, -1340.), (5100. + k * 120, -360.)], tags('waterway=ditch'))
    plan.way([(collector, z.centre_y(-2)), (5840., z.centre_y(-2))], tags('highway=track tracktype=grade4', name='Торфова дорога'))
    name(named, 5450., -850., 'Торфовище', 'Peat fields')
    # the logging ground: a wood, a grid of ruined tracks, clearings; one track fords the river
    plan.rect(5080., 100., 5850., 1400., tags('landuse=forest', name='Лісосіка'))
    for row in (0, 1, 2):
        y = z.centre_y(row)
        if row == 1:
            plan.way([(collector, y), (river_x(y), y), (6400., y)], tags('highway=track tracktype=grade5 surface=mud', name='Лісовозна'))
            plan.node(river_x(y), y, tags('ford=yes'))
            name(named, river_x(y), y, 'Брід', 'Ford')
        else:
            plan.way([(collector, y), (5800., y)], tags('highway=track tracktype=grade5 surface=ground'))
    for x in (5300., 5700.):
        plan.way([(x, 150.), (x, 1350.)], tags('highway=track tracktype=grade5 surface=mud'))
    for k, (x, y) in enumerate(((5450., 450.), (5550., 1000.), (5200., 1150.))):
        plan.rect(x - 70, y - 50, x + 70, y + 50, tags('natural=scrub', name='Вирубка'))
    name(named, 5450., 760., 'Лісосіка', 'Logging ground')
    # the village: homesteads along a dirt street, a cross street of mud, a shop
    y = z.centre_y(4)
    street = plan.way([(collector, y), (5450., y), (5860., y)], tags('highway=residential surface=dirt', name='Грузька вулиця'))
    plan.way([(5450., 1900.), (5450., y), (5450., 2600.)], tags('highway=residential surface=mud', name='Багнистий провулок'))
    for side in (1, -1):
        for n in range(12):
            x = 5060. + n * 31
            if abs(x + 14 - 5450.) > 24:
                z.lot(plan, x, y + side * 9, 28, 44, side, n + (12 if side < 0 else 0))
    z.house(plan, 5800., y + 26, 16, 10, tags('building=retail building:levels=1 roof:shape=gabled', name='Сільмаг'))
    z.shop(plan, 5800., y + 23, 'shop=convenience', 'Сільмаг', side=-1, depth=2.)
    name(named, 5300., y - 1.6, 'Село Грузьке', 'Mud village')
    wild(plan, 'mud', named)
    plan.zones.append({'id': 'mud', 'title': 'Всесвіт: багно', 'titleEn': 'Universe: mud',
                       'start': (8 * TILE + 30, z.centre_y(0) - 1.6)})


# What a rainforest is tested by: the places where plants decide the frame. In the block's two
# western columns, a row each pair, from the north.
JUNGLE = (('works', 0), ('plants', 0),        # village homesteads, woods
          ('covers', 2), ('plants', 4),       # fields, park and garden
          ('water', 0), ('covers', 10),       # river and bridge, parks
          ('water', 2), ('covers', 0),        # lake, open ground
          ('town', 3), ('street', 1))         # panel block, street trees


def jungle(plan):
    """The island's south-east corner under the rainforest's rules: two columns of the places a
    plant is looked at in (JUNGLE), then the forest itself: hills, a river with a ford, a track
    through the trees, a village in a clearing, a plantation, a swamp by the shore."""
    block = BLOCK['jungle']
    i0, _, j0, j1 = block['tiles']
    collector = 5008.
    n = 0
    for j in range(j1 - 1, j0 - 1, -1):
        for i in (i0, i0 + 1):
            theme, k = JUNGLE[n]
            z.TILES[theme](plan, i, j, k)
            n += 1
        yc = z.centre_y(j)
        plan.way([((i0 + 2) * TILE, yc), (collector, yc)], tags('highway=tertiary'))
    # the collector runs on north into the mud's; the rows' avenues meet the desert's at the block's edge
    plan.way([(collector, z.centre_y(j0)), (collector, z.centre_y(j1))], tags('highway=tertiary', name='Дорога крізь джунглі'))
    named = {}
    south, north = j0 * TILE, j1 * TILE

    def hills(x, y):
        import numpy as np
        land = z.smooth_((x - 5060.) / 400.) * z.smooth_((north - 250. - y) / 300.)
        return (15. + 9. * np.sin(x / 170.) * np.sin(y / 210.) + 4. * np.sin(x / 61. + y / 47.)) * land
    plan.relief.append(hills)

    # the river: from the hills to the southern shore; the track fords it
    def river_x(y):
        return 6050. + 110. * math.sin(y / 240.)
    line = [(river_x(y), float(y)) for y in range(int(north) - 150, int(south) + 49, -100)]
    plan.way(line, tags('waterway=river', name='Тиха'))
    plan.area([(x - 11, y) for x, y in line] + [(x + 11, y) for x, y in line[::-1]], tags('natural=water water=river'))
    z._bed(plan, line, 50., 2.5)
    # the forest, in three parts with the village's clearing and the plantation between them
    plan.rect(5080., north - 1150., 6480., north - 60., tags('landuse=forest leaf_type=broadleaved', name='Дощовий ліс'))
    plan.rect(5080., south + 760., 5700., north - 1750., tags('natural=wood leaf_type=broadleaved', name='Старий ліс'))
    plan.rect(6200., south + 60., 6480., north - 1250., tags('landuse=forest leaf_type=broadleaved', name='Ліс за річкою'))
    y = z.centre_y(j1 - 2)
    plan.way([(collector, y), (river_x(y), y), (6440., y)], tags('highway=track tracktype=grade4 surface=ground', name='Стежка крізь ліс'))
    plan.node(river_x(y), y, tags('ford=yes'))
    name(named, 5500., y - 1.6, 'Дощовий ліс', 'Rainforest')
    name(named, river_x(y), y, 'Брід у джунглях', 'Jungle ford')
    # a village in a clearing: homesteads along an earth street, kitchen gardens behind them
    y = z.centre_y(j1 - 3)
    plan.way([(collector, y), (5460., y), (5900., y)], tags('highway=residential surface=dirt', name='Пальмова вулиця'))
    for side in (1, -1):
        for k in range(12):
            z.lot(plan, 5060. + k * 31, y + side * 9, 28, 44, side, k + (12 if side < 0 else 0))
    plan.rect(5480., y + 70., 5880., y + 190., tags('landuse=allotments', name='Городи'))
    name(named, 5300., y - 1.6, 'Село в джунглях', 'Jungle village')
    # the plantation: an orchard in rows, a track round it, and fields beyond
    y = z.centre_y(j0 + 1)
    plan.rect(5760., y - 200., 5980., y + 240., tags('landuse=orchard trees=banana_plants', name='Плантація'))
    plan.rect(5080., south + 60., 5700., south + 700., tags('landuse=farmland', name='Поля'))
    plan.way([(collector, y), (5750., y)], tags('highway=track tracktype=grade3', name='Дорога на плантацію'))
    plan.way([(5750., y - 210.), (5750., y + 250.)], tags('highway=track tracktype=grade4'))
    name(named, 5740., y, 'Плантація', 'Plantation')
    # the swamp at the river's mouth
    plan.rect(5760., south + 60., 6190., south + 420., tags('natural=wetland wetland=swamp', name='Мангри'))
    name(named, 5900., south + 250., 'Мангри', 'Mangrove swamp')
    wild(plan, 'jungle', named)
    plan.zones.append({'id': 'jungle', 'title': 'Всесвіт: джунглі', 'titleEn': 'Universe: jungle',
                       'start': (i0 * TILE + 30, z.centre_y(j1 - 1) - 1.6)})


def build(plan):
    mountains(plan)
    desert(plan)
    snow(plan)
    mud(plan)
    jungle(plan)
