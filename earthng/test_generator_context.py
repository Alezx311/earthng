"""Isolation of generator scratch state across budget and delivery yields."""
from copy import deepcopy
import math
from pathlib import Path
import unittest

import test_native


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'mod/lua/ge/extensions/e2r/generator.lua'


def plain(value):
    if hasattr(value, 'items'):
        return {key: plain(item) for key, item in value.items()}
    return value


def cell(buildings=None, lines=None):
    return dict(roads=[], junctions=[], buildings=buildings or [], areas=[],
                lines=lines or [], points=[],
                terrain=dict(rect=[0, 0, 500, 500], nx=2, ny=2, heights=[0, 0, 0, 0]))


def many_walled_building():
    # 64 walls trigger an existing budget checkpoint while city grammar is active.
    ring = [[250 + 90 * math.cos(2 * math.pi * k / 64),
             250 + 90 * math.sin(2 * math.pi * k / 64), 0] for k in range(64)]
    return dict(id='city', height=18, kind='building', tags={'building': 'apartments'}, rings=[ring])


class GeneratorContextTests(unittest.TestCase):
    def setUp(self):
        self.lua, self.native, self.convert = test_native.NativeTests().make(real_generator=True)
        self.lua.execute("local old=FS.fileExists; FS.fileExists=function(s,p) if p:find('/e2r_stream/fast-art/',1,true) then return true end return old(s,p) end")

    def test_interleaved_real_builds_keep_their_context(self):
        lines = SOURCE.read_text(encoding='utf8').splitlines()
        fence_start = next(i for i, line in enumerate(lines) if 'local function fence(line)' in line)
        fence_pause = next(i + 1 for i in range(fence_start, len(lines)) if lines[i] == '    pause()')
        # The checkpoint of the building wall loop, found by its neighbour rather than by a line
        # number: other loops (road sidewalks) have the same pause line and move with every edit.
        walls_pause = [i + 2 for i, line in enumerate(lines[:-1]) if line.strip() == 'along = along + length'
                       and lines[i + 1].strip() == 'if k % 32 == 0 then pause() end']
        self.assertEqual(len(walls_pause), 1, 'wall loop checkpoint not found exactly once')
        walls_pause = walls_pause[0]
        fences = [dict(id='f1', kind='fence', tags={'barrier': 'fence'}, points=[[50, 310], [450, 310]]),
                  dict(id='f2', kind='fence', tags={'barrier': 'fence'}, points=[[50, 320], [450, 320]])]
        tiny = dict(id='tiny', height=3, kind='building', tags={'building': 'shed'},
                    rings=[[[100, 100], [120, 100], [120, 120], [100, 120]]])
        run = self.lua.eval('''function(a, b, far, stage, pauseLine, sameCountry, interleave)
          local function spawn(cells, country, watched)
            local state = {}
            local options = {tileSize=500, terrainStep=100, maxTrees=0, maxGrass=0, maxRocks=0,
                             far=far, country=country, leftHand=false}
            local once = false
            options.pause = function()
              if watched and not once and debug.getinfo(2, 'l').currentline == pauseLine then
                once = true; coroutine.yield('budget')
              end
            end
            options.roadReady = function() if watched and stage == 'road' then coroutine.yield('road') end end
            options.sceneReady = function() if watched and stage == 'scene' then coroutine.yield('scene') end end
            state.co = coroutine.create(function()
              -- A non-generator yield exercises a parked loadCell before build starts.
              if watched and stage == 'before' then coroutine.yield('before') end
              state.result = {stubGenerator.build(cells, 0, 0, options)}
            end)
            return state
          end
          local function step(s)
            local ok, value = stubGenerator.resumeBuild(s.co)
            assert(ok, value)
            return value
          end
          local aa = spawn(a, 'ukraine', interleave)
          if interleave then
            local marker = step(aa)
            local expected = (stage == 'fence' or stage == 'building') and 'budget' or stage
            assert(coroutine.status(aa.co) == 'suspended' and marker == expected, tostring(marker))
            local bb = spawn(b, sameCountry and 'ukraine' or 'united-kingdom', false)
            step(bb); assert(coroutine.status(bb.co) == 'dead')
          end
          step(aa); assert(coroutine.status(aa.co) == 'dead')
          return aa.result
        end''')
        # The scheduler's resumeBuild returns one message; complete results are retained in the
        # coroutine-owned state. With sceneReady, the fifth result is the actual grass layer.
        scenarios = [
            ('fence', False, fence_pause, False, cell(lines=fences), cell()),
            ('fence', True, fence_pause, False, cell(lines=fences), cell()),
            ('building', False, walls_pause, True, cell(buildings=[many_walled_building()]), cell(buildings=[tiny])),
            ('road', False, -1, False, cell(lines=fences), cell()),
            ('scene', False, -1, False, cell(lines=fences), cell()),
            ('before', False, -1, False, cell(lines=fences), cell()),
        ]
        for stage, far, line, same_country, a, b in scenarios:
            with self.subTest(stage=stage, far=far):
                expected = run(self.convert([deepcopy(a)]), self.convert([deepcopy(b)]), far, stage, line, same_country, False)
                actual = run(self.convert([deepcopy(a)]), self.convert([deepcopy(b)]), far, stage, line, same_country, True)
                self.assertEqual(plain(expected), plain(actual))

        # The same-country case must exercise an actual corruption, rather than merely
        # observing a yield: raw resume drops the suspended city's BLD scratch fields.
        self.lua.execute('stubGenerator.resumeBuild = coroutine.resume')
        a, b = cell(buildings=[many_walled_building()]), cell(buildings=[tiny])
        expected = run(self.convert([deepcopy(a)]), self.convert([deepcopy(b)]), False, 'building', walls_pause, True, False)
        unsafe = run(self.convert([deepcopy(a)]), self.convert([deepcopy(b)]), False, 'building', walls_pause, True, True)
        self.assertNotEqual(plain(expected), plain(unsafe))

    def test_native_scheduler_uses_context_resume_for_prebuild_and_delivery_yields(self):
        # Stub generator exposes resumeBuild; this tests the actual scheduler call site, including
        # the real AHEAD/GRASS callbacks supplied by native.buildTile rather than test markers.
        lua, mod, cv = test_native.NativeTests().make()
        lua.execute('''resumeStates={}
          hptimer=function() local t=0; return {stop=function() t=t+5; return t end} end
          stubGenerator.resumeBuild=function(co)
            local ok, value=coroutine.resume(co)
            resumeStates[#resumeStates+1]={ok=ok, value=value, status=coroutine.status(co), builds=buildCalls}
            return ok,value
          end''')
        lat, lon = test_native.geographic(1750, 1750)
        mod.land(cv(dict(seq=1, lat=lat, lon=lon)))
        test_native.NativeTests().pump(mod, count=8000)
        mod.pose(cv(dict(x=1750, y=1750, vx=25, vy=0, state='driving')))
        for _ in range(600):
            mod.update(.016, 2)
        states = list(lua.globals().resumeStates.values())
        self.assertTrue(any(s.status == 'suspended' and s.value is None for s in states))
        self.assertTrue(any(s.status == 'suspended' and s.builds == 0 for s in states),
                        'expected a source-load yield before the first generator.build')
        # The two different table markers are native's AHEAD and GRASS yields.
        distinct_markers = lua.eval('''function(states)
          local found, count = {}, 0
          for _, s in ipairs(states) do
            if s.status == 'suspended' and type(s.value) == 'table' and not found[s.value] then
              found[s.value] = true; count = count + 1
            end
          end
          return count
        end''')
        self.assertEqual(distinct_markers(lua.globals().resumeStates), 2)
        self.assertTrue(any(s.status == 'dead' for s in states))

    def test_context_is_removed_on_error_and_collected_when_coroutine_is_abandoned(self):
        self.lua.execute('''
          local contexts
          for i = 1, 100 do
            local name, value = debug.getupvalue(stubGenerator.resumeBuild, i)
            if not name then break end
            if name == 'buildContexts' then contexts = value; break end
          end
          assert(contexts, 'context map is not an upvalue of resumeBuild')

          local failed = coroutine.create(function()
            coroutine.yield('first')
            error('tile build failed')
          end)
          local ok, message = stubGenerator.resumeBuild(failed)
          assert(ok and message == 'first' and contexts[failed])
          ok, message = stubGenerator.resumeBuild(failed)
          assert(not ok and tostring(message):find('tile build failed', 1, true))
          assert(coroutine.status(failed) == 'dead' and contexts[failed] == nil,
                 'failed coroutine retained its context')

          local weak = setmetatable({}, {__mode='v'})
          do
            local abandoned = coroutine.create(function() coroutine.yield('parked') end)
            ok, message = stubGenerator.resumeBuild(abandoned)
            assert(ok and message == 'parked' and contexts[abandoned])
            weak[1], weak[2] = abandoned, contexts[abandoned]
          end
          collectgarbage('collect'); collectgarbage('collect')
          assert(weak[1] == nil and weak[2] == nil,
                 'abandoned coroutine or its context was retained')
        ''')


if __name__ == '__main__':
    unittest.main()
