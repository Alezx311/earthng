"""Compass bearings, nearby landmarks and a destination behind the camera."""
from pathlib import Path
import unittest
from lupa.luajit21 import LuaRuntime
ROOT=Path(__file__).resolve().parents[1]

class CompassTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute("package.path = '"+(ROOT/'mod/lua').as_posix()+"/?.lua;' .. package.path")
        self.lua.execute("C=require('ge/extensions/e2r/compass')")

    def test_cardinal_and_wrapped_bearings(self):
        self.assertAlmostEqual(self.lua.eval('C.bearing(0,0,1,0)'),0)
        self.assertAlmostEqual(self.lua.eval('C.bearing(0,0,0,1)'),90)
        self.assertAlmostEqual(self.lua.eval('C.bearing(0,0,-1,0)'),180)
        self.assertAlmostEqual(self.lua.eval('C.bearing(0,0,0,-1)'),270)
        self.assertEqual(self.lua.eval('C.offset(1,359)'),2)
        self.assertAlmostEqual(self.lua.eval('C.distance(0,179.99,0,-179.99)'),2223.9,delta=1)

    def test_marker_behind_is_kept_and_no_label_overlap(self):
        self.lua.execute(r"""
          texts={}; local index=require('ge/extensions/e2r/poiindex')
          local pins=require('ge/extensions/e2r/pins')
          local cat={id='test',files={['pois.tsv']='castle\t0.01\t0\tcastle\tCastle\tCastle\n'}}
          index.attach({catalogs=function() return {cat} end,text=function(c,n) return c.files[n] end},pins)
          local tiles={{brandPOIs={{cat='monument',label='Local Tower',x=.01,y=0}}}}
          for i=1,30 do C.step(i/10,0,0,'en',tiles,function(x,y) return y,x end) end
          local flags={WindowFlags_NoDecoration=1,WindowFlags_NoInputs=2,WindowFlags_NoNav=4,
            WindowFlags_NoSavedSettings=8,WindowFlags_NoFocusOnAppearing=16,
            WindowFlags_NoBringToFrontOnFocus=32,WindowFlags_NoDocking=64,Cond_Always=1,Col_WindowBg=1}
          im=setmetatable(flags,{__index=function() return function() end end})
          im.ImVec2=function(x,y) return {x=x,y=y} end
          im.ImVec4=function(...) return {} end
          im.GetColorU322=function() return 1 end
          im.GetMainViewport=function() return {Pos={x=0,y=0},Size={x=800,y=600}} end
          im.GetCursorScreenPos=function() return {x=0,y=0} end
          im.GetTextLineHeight=function() return 14 end
          im.CalcTextSize=function(s) return {x=#s*7,y=14} end
          im.ImDrawList_AddText1=function(dl,at,col,s) texts[#texts+1]=s; assert(at.x>=4) end
          C.draw(im,0,0,0,{lat=-1,lon=0},'en')
        """)
        texts=list(self.lua.globals().texts.values())
        self.assertTrue(any('Marker' in s for s in texts),texts)
        self.assertTrue(any(s.startswith('Castle') for s in texts),texts)
        self.assertTrue(any(s.startswith('Local Tower') for s in texts),texts)
