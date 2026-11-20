"""Exercise packaged image bounds and the same draw call the driving widget uses."""
import json
import math
from pathlib import Path
import unittest

from PIL import Image
from lupa.luajit21 import LuaRuntime

MOD = Path(__file__).resolve().parents[1] / 'mod'
ROOT = '/earthng/planet/photos/'


class MapPhotoTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.sheets = json.loads((MOD / ROOT.strip('/') / 'index.json').read_text())
        self.lua.globals().sheets = self.lua.table_from(self.sheets, recursive=True)
        self.lua.execute('''
            FS = {fileExists=function(_, p) return p:match('/index.json$') ~= nil end}
            function jsonReadFile(p) return p:match('/photos/') and sheets or {tiles={}} end
            function require() return {texObj=function(p) return {texId=p} end, step=function() end} end
            local function vec(x,y) return {x=x, y=y} end
            im = {ImVec2=vec, ImDrawList_AddRectFilled=function() end,
                  ImDrawList_AddImage=function(_,file,a,b,uv0,uv1) drawn[file]={a,b,uv0,uv1} end}
            function merc(lat,lon,z)
              local n=256*2^z
              return n*(lon+180)/360, n*(1-math.log(math.tan(math.pi/4+math.rad(lat)/2))/math.pi)/2
            end
            function render(lat,lon,z,w,h,photo)
              drawn={}
              return planet.draw(im, 0, vec(10,20), w,h,{center={lat=lat,lon=lon},zoom=z,photo=photo},
                                 merc, nil, function() return 1 end)
            end
        ''')
        self.lua.globals().planet = self.lua.execute(
            (MOD / 'lua/ge/extensions/e2r/planetMap.lua').read_text(encoding='utf8'))
        self.render = self.lua.globals().render

    def test_local_images_stay_georeferenced_after_resize(self):
        for lat, lon in [(37.8021, -122.4187), (50.4529, 30.5143)]:
            filename, credit = 'selection.dds', 'Regional imagery'
            x = (lon + 180) / 360
            y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2
            box = [x - .001, y - .001, x + .001, y + .001]
            self.lua.globals().localSheets = self.lua.table_from([
                {'file': filename, 'box': box, 'minZoom': 8, 'maxZoom': 18, 'credit': credit}], recursive=True)
            self.lua.execute('''
              local read = jsonReadFile
              jsonReadFile = function(p)
                if p == '/earthng/countries/demo/photos/index.json' then return localSheets end
                return read(p)
              end
              planet.update({})
              planet.update({{id='demo',title='Demo',available=true}})
            ''')
            for w, h in [(360, 180), (920, 580)]:
                self.assertIn(credit, self.render(lat, lon, 16, w, h, True))
                quad = self.lua.globals().drawn['/earthng/countries/demo/photos/' + filename]
                a, b, uv0, uv1 = (quad[i] for i in range(1, 5))
                u = uv0.x + (w / 2 + 10 - a.x) / (b.x - a.x) * (uv1.x - uv0.x)
                v = uv0.y + (h / 2 + 20 - a.y) / (b.y - a.y) * (uv1.y - uv0.y)
                self.assertAlmostEqual(box[0] + u * (box[2] - box[0]), x)
                self.assertAlmostEqual(box[1] + v * (box[3] - box[1]), y)

    def test_switch_world_coverage_and_chart_fallback(self):
        self.assertEqual(self.render(0, 179.9, 3, 360, 180, True), 'NASA Blue Marble')
        self.assertIsNone(self.render(50.45, 30.52, 16, 360, 180, False))
        self.assertEqual(len(list(self.lua.globals().drawn)), 0)
        self.assertIsNone(self.render(52, -2, 16, 360, 180, True))
        self.assertEqual(len(list(self.lua.globals().drawn)), 0)

    def test_shipped_sheets_decode(self):
        for sheet in self.sheets:
            with self.subTest(file=sheet['file']), Image.open(MOD / ROOT.strip('/') / sheet['file']) as image:
                self.assertIn(image.width, (1024, 2048))
                self.assertEqual(image.width, image.height)
                image.load()
                if image.mode == 'RGBA':
                    self.assertLess(image.getpixel((0, 0))[3], 10)
                    self.assertEqual(image.getpixel((image.width // 2, image.height // 2))[3], 255)

    def test_country_and_section_images_are_mounted_and_removed_with_the_pack(self):
        self.lua.execute('''
          local roots = {
            ['/earthng/countries/new/photos/index.json'] = {{file='country.png', box={.27,.42,.28,.43},
              minZoom=6,maxZoom=18,credit='Country imagery'}},
            ['/earthng/countries/new/sections/area/photos/index.json'] = {{file='section.png',box={.277,.425,.279,.427},
              minZoom=6,maxZoom=18,credit='Section imagery'}}}
          local exists, read = FS.fileExists, jsonReadFile
          FS.fileExists = function(self,p) return roots[p] ~= nil or exists(self,p) end
          jsonReadFile = function(p) return roots[p] or read(p) end
          local countries={{id='new',title='New place',available=true,regions={{id='area',section=true}}}}
          planet.update(countries)
          -- Miami: both country and county imagery have no hard-coded city dependency.
          credit=render(25.78,-80.22,15,920,580,true)
          assert(drawn['/earthng/countries/new/photos/country.png'])
          assert(drawn['/earthng/countries/new/sections/area/photos/section.png'])
          assert(credit:find('Section imagery',1,true))
          planet.update({})
          render(25.78,-80.22,15,920,580,true)
          assert(not next(drawn))
        ''')
