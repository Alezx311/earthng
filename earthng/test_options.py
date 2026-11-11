"""The settings registry (options.lua) and its two views: the ImGui widget and the game's UI app.

    .venv/Scripts/python.exe -m unittest discover -s earthng -p "test_options.py"

docs/INGAME_UI.md. Lua checks need lupa.luajit21.
"""
import json
import re
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

from test_widget import load_world

ROOT = Path(__file__).resolve().parents[1]
E2R = ROOT / 'mod/lua/ge/extensions/e2r'
APP = ROOT / 'mod/ui/modules/apps/EarthNG'


def to_py(value):
    """A Lua value as plain Python (tables with 1..n keys become lists); functions raise."""
    if hasattr(value, 'keys') or type(value).__name__ == '_LuaTable':
        items = dict(value.items())
        if items and all(isinstance(k, int) for k in items) and sorted(items) == list(range(1, len(items) + 1)):
            return [to_py(items[k]) for k in sorted(items)]
        return {str(k): to_py(v) for k, v in items.items()}
    if callable(value):
        raise TypeError('a function in the list')
    return value


def registry():
    lua = LuaRuntime()
    lua.globals().options = lua.execute((E2R / 'options.lua').read_text(encoding='utf8'))
    return lua


class RegistryTests(unittest.TestCase):
    def test_define_get_set_clamp(self):
        lua = registry()
        lua.execute('''
          applied = {}
          options.define{key='n', kind='int', min=0, max=1000, step=50, default=200, group='g',
            label={uk='Число', en='Number'}, apply=function(v) applied[#applied+1]=v end}
          options.define{key='f', kind='float', min=0, max=1, default=.5}
          options.define{key='b', kind='bool', default=false}
          options.define{key='e', kind='enum', values={{0,'Вимк','Off'},{100,'100','100'}}, default=0}
          options.define{key='s', kind='enum', values={{value='uk', label={uk='Укр', en='Ukr'}}, {value='en'}}, default='uk'}
        ''')
        ev = lua.eval
        self.assertEqual(ev("options.get('n')"), 200)
        self.assertEqual(ev("(options.set('n', 1234))"), 1000)        # clamped
        self.assertEqual(ev("(options.set('n', 74))"), 50)            # snapped to the step
        self.assertEqual(ev("(options.set('n', '-5'))"), 0)           # a string from the page
        self.assertEqual(list(lua.eval('applied').values()), [1000, 50, 0])
        changed = lua.eval("{options.set('n', 0)}")
        self.assertFalse(changed[2])                                  # unchanged: no apply
        self.assertEqual(len(lua.eval('applied')), 3)
        self.assertAlmostEqual(ev("(options.set('f', 7))"), 1.0)
        self.assertTrue(ev("(options.set('b', 'true'))"))
        self.assertEqual(ev("(options.set('e', '100'))"), 100)
        self.assertIsNone(ev("(options.set('e', 50))"))                # not one of the values
        self.assertEqual(ev("options.get('e')"), 100)
        self.assertEqual(ev("(options.set('s', 'en'))"), 'en')
        self.assertIsNone(ev("(options.set('nope', 1))"))
        self.assertIsNone(ev("(options.set('f', 0/0))"))
        # an option another module defines again takes the old one's place, not a new row
        lua.execute("options.define{key='n', kind='int', min=0, max=10, default=3}")
        keys = [d['key'] for d in to_py(lua.eval('options.list()'))]
        self.assertEqual(keys, ['n', 'f', 'b', 'e', 's'])
        self.assertEqual(ev("options.get('n')"), 0)

    def test_unavailable_and_failing_apply(self):
        lua = registry()
        lua.execute('''
          on = false
          options.define{key='a', kind='bool', default=false, available=function() return on end}
          options.define{key='x', kind='int', min=0, max=9, default=1, apply=function() error('boom') end}
        ''')
        self.assertIsNone(lua.eval("(options.set('a', true))"))
        lua.execute('on = true')
        self.assertTrue(lua.eval("(options.set('a', true))"))
        self.assertIsNone(lua.eval("(options.set('x', 5))"))
        self.assertEqual(lua.eval("options.get('x')"), 1)           # the old value stays

    def test_persist_round_trip(self):
        lua = registry()
        lua.execute('''
          disk = {lang='en', tune={quality=70}, locationOff=false}
          writes = 0
          options.storage = {read=function() local c={}; for k,v in pairs(disk) do c[k]=v end; return c end,
                             write=function(cfg) disk = cfg; writes = writes + 1 end}
          options.define{key='streetLine', kind='bool', default=true, path={'locationOff'},
            encode=function(v) return not v end, decode=function(raw) return not raw end}
          options.define{key='deep', kind='int', min=0, max=9, default=2, path={'ui', 'deep'}}
          options.define{key='free', kind='int', min=0, max=9, default=2}
        ''')
        self.assertEqual(lua.eval('options.restore()'), 1)            # locationOff only
        self.assertTrue(lua.eval("options.get('streetLine')"))
        lua.execute("options.set('streetLine', false); options.set('deep', 7); options.set('free', 5)")
        self.assertEqual(lua.eval('writes'), 2)                       # 'free' has no path
        disk = to_py(lua.eval('disk'))
        self.assertEqual(disk['locationOff'], True)                   # the old key, inverted
        self.assertEqual(disk['ui'], {'deep': 7})
        self.assertEqual(disk['lang'], 'en')                          # the rest of the file stays
        self.assertEqual(disk['tune'], {'quality': 70})
        self.assertNotIn('free', disk)
        self.assertFalse(lua.eval('options.dirty'))
        # a new session reads them back
        other = registry()
        other.globals().saved = other.table_from(to_py(lua.eval('disk')), recursive=True)
        other.execute('''
          options.define{key='streetLine', kind='bool', default=true, path={'locationOff'},
            encode=function(v) return not v end, decode=function(raw) return not raw end}
          options.define{key='deep', kind='int', min=0, max=9, default=2, path={'ui', 'deep'}}
          applied = nil
          options.define{key='late', kind='int', min=0, max=9, default=2, path={'late'}, read=function() return 4 end,
            apply=function(v) applied = v end}
          saved.late = 99
        ''')
        self.assertEqual(other.eval('options.restore(saved, true)'), 3)
        self.assertFalse(other.eval("options.get('streetLine')"))
        self.assertEqual(other.eval("options.get('deep')"), 7)
        self.assertEqual(other.eval('applied'), 9)                    # clamped before apply

    def test_listeners_touch_and_poll(self):
        lua = registry()
        lua.execute('''
          heard = {}
          live = 1
          options.define{key='v', kind='int', min=0, max=9, read=function() return live end,
            apply=function(v) live = v; options.touch('v') end}   -- the owner's own notice is folded in
          options.define{key='w', kind='bool', default=false}
          off = options.onChange(function(key, value, source) heard[#heard+1] = key..'='..tostring(value)..'/'..source end, 'ui')
        ''')
        lua.execute("options.set('v', 3, 'ui')")
        self.assertEqual(list(lua.eval('heard').values()), ['v=3/ui'])
        lua.execute('options.touch("w")')
        self.assertEqual(lua.eval('heard')[2], 'w=false/external')
        # a value changed behind the registry's back: poll tells once, then is quiet
        lua.execute('live = 6')
        self.assertTrue(lua.eval('options.poll(1)'))
        self.assertEqual(lua.eval('heard')[3], 'v=6/poll')
        self.assertFalse(lua.eval('options.poll(2)'))
        lua.execute('live = 7')
        self.assertFalse(lua.eval('options.poll(2.1)'))               # within POLL_EVERY
        self.assertTrue(lua.eval('options.poll(2.3)'))
        # a listener of the same name replaces the old one; the remover removes
        lua.execute("count = 0; options.onChange(function() count = count + 1 end, 'ui')")
        lua.execute("options.set('w', true)")
        self.assertEqual(lua.eval('count'), 1)
        self.assertEqual(len(lua.eval('heard')), 4)
        lua.execute("drop = options.onChange(function() count = count + 10 end); drop(); options.set('w', false)")
        self.assertEqual(lua.eval('count'), 2)

    def test_list_is_plain_json(self):
        lua = registry()
        lua.execute('''
          options.group{key='traffic', label={uk='Трафік', en='Traffic'}}
          options.group{key='advanced', label={uk='Точні', en='Advanced'}, collapsed=true}
          options.define{key='walk', kind='enum', group='traffic', label={uk='Пішоходи', en='Pedestrians'},
            values={{0,'Вимк','Off'},{100,'100','100'}, source='x', group=function() end}, default=0}
          options.define{key='style', kind='enum', group='view', values=function() return {{value='real', label={uk='Реальний', en='Real'}}} end,
            read=function() return 'real' end, available=function() return false end}
          options.define{key='grass', kind='int', min=0, max=220, group='advanced', default=45, hint={uk='м', en='m'},
            apply=function() end}
          options.define{key='lang', kind='enum', values={{'uk'},{'en'}}, default='en', group='view'}
        ''')
        listed = to_py(lua.eval('options.list()'))
        json.dumps(listed)
        walk = listed[0]
        self.assertEqual(walk['values'], [{'value': 0, 'label': {'uk': 'Вимк', 'en': 'Off'}},
                                          {'value': 100, 'label': {'uk': '100', 'en': '100'}}])
        self.assertEqual(listed[1]['disabled'], True)
        self.assertEqual(listed[2]['step'], 1)
        payload = to_py(lua.eval('options.payload()'))
        json.dumps(payload)
        self.assertEqual(payload['lang'], 'en')
        self.assertEqual([g['key'] for g in payload['groups']], ['traffic', 'advanced', 'view'])
        self.assertTrue(payload['groups'][1]['collapsed'])
        self.assertEqual([o['key'] for o in payload['groups'][2]['options']], ['style', 'lang'])


WORLD_IM = '''
  ui_imgui = setmetatable({ArrayChar=function() return {} end,
    Button=function(label) return label == clicked end,
    Checkbox=function(label, ptr) if label == clicked then ptr[0] = not ptr[0]; return true end return false end,
    BoolPtr=function(v) return {[0]=v} end,
    IntPtr=function(v) return {[0]=v} end,
    SliderInt=function(label, ptr, lo, hi) if label == slid then ptr[0] = slideTo; return true end return false end,
    CollapsingHeader1=function(label) return label == openHeader end,
    GetIO=function() return {MouseWheel=0} end,
    GetMousePos=function() return {x=0,y=0} end,
    GetItemRectMin=function() return {x=0,y=0} end,
    IsItemHovered=function() return false end,
    IsMouseDown=function() return false end,
    CalcTextSize=function() return {x=10,y=10} end,
    GetStyle=function() return {ItemSpacing={x=4}} end,
    ImVec2=function(x, y) return {x=x, y=y} end,
    GetContentRegionAvailWidth=function() return 360 end,
    GetContentRegionAvail=function() return {x=1100, y=640} end,
    GetFrameHeightWithSpacing=function() return 26 end,
    WindowFlags_NoCollapse=1, WindowFlags_AlwaysAutoResize=2, WindowFlags_NoScrollbar=4,
    WindowFlags_NoScrollWithMouse=8},
    {__index=function() return function() end end})
  FS={fileExists=function() return false end}
  disk = {lang='uk', locationOff=true, tune={quality=50}}
  writes = {}
  jsonReadFile=function(path) local c = {}; for k, v in pairs(disk) do c[k] = v end; return c end
  jsonWriteFile=function(path, tbl) if path == 'settings/earthng.json' then disk = tbl; writes[#writes+1] = path end end
  hptimer=function() return {stopAndReset=function() return 1 end, stop=function() return 1 end} end
  pushed = {}
  guihooks = {trigger=function(name, data) pushed[#pushed+1] = {name=name, data=data} end}
  require=function(n)
    if n == 'ge/extensions/e2r/parking' then return parking_mod end
    if n == 'ge/extensions/e2r/handoff' then return {SIZE=8} end
    if n == 'ge/extensions/e2r/winguard' then return winguard_mod end
    return {}
  end
  function up(fn, name, replacement)
    for i=1,200 do
      local n,v=debug.getupvalue(fn,i)
      if not n then break end
      if n==name then
        if replacement then debug.setupvalue(fn,i,replacement) end
        return v
      end
    end
    error('missing upvalue '..name)
  end
'''


class WidgetSyncTests(unittest.TestCase):
    """world.lua's options: the widget and the registry show the same value whichever changed it."""

    def world(self, disk=None):
        """world.lua (NATIVE off) with the registry bound; disk: Lua table source of settings/earthng.json.
        walkersSet/walkersGet are fakes with walkers.lua's contract (asked, walking, room)."""
        lua = LuaRuntime()
        lua.globals().parking_mod = lua.execute((E2R / 'parking.lua').read_text(encoding='utf8'))
        lua.globals().winguard_mod = lua.execute((E2R / 'winguard.lua').read_text(encoding='utf8'))
        lua.execute(WORLD_IM)
        src = (E2R / 'world.lua').read_text(encoding='utf8').replace('local NATIVE = true', 'local NATIVE = false')
        mod = load_world(lua, src)
        lua.globals().mod = mod
        if disk:
            lua.execute('disk = ' + disk)
        lua.execute('''
          S = up(mod.tick, 'S')
          fake = {asked = 0, walking = 0, room = 590, calls = {}}
          mod.walkersSet = function(n)
            n = math.max(0, math.min(1000, math.floor(tonumber(n) or 0)))
            fake.asked = n; fake.calls[#fake.calls + 1] = n
            S.walk = n > 0 and {parked = S.state ~= 'driving', W = {target = n}} or nil
          end
          mod.walkersGet = function() return fake.asked, fake.walking, fake.room end
          draw = up(mod.onUpdate, 'drawWindow')
          drawTune = up(draw, 'drawTune')
          o = mod.options
          assert(o and o.REGISTRY, 'world.lua has no registry')
          mod.optionsBind()
          o.restore(nil, true)
        ''')
        return lua

    def test_every_widget_setting_is_registered(self):
        lua = self.world()
        keys = [d['key'] for d in to_py(lua.eval('o.list()'))]
        for key in ('quality', 'detail', 'distance', 'grassM', 'rockM', 'nearM', 'farM', 'maxTrees', 'maxFarTrees',
                    'maxGrass', 'maxRocks', 'grassBudget', 'rockBudget', 'forestSpacing', 'groundSpacing',
                    'groundTrees', 'trafficKind', 'trafficAmount', 'flow', 'flowReal', 'walkers', 'walkersOn',
                    'knock', 'parkedCars', 'lang', 'streetLine', 'style'):
            self.assertIn(key, keys)
        payload = to_py(lua.eval('o.payload()'))
        json.dumps(payload)
        self.assertEqual([g['key'] for g in payload['groups']], ['quality', 'traffic', 'view', 'advanced'])
        # the widget's tune sliders and the registry's ranges agree
        src = (E2R / 'world.lua').read_text(encoding='utf8')
        listed = {d['key']: d for d in to_py(lua.eval('o.list()'))}
        for key, lo, hi in re.findall(r"tuneSlider\('(\w+)', (\d+), (\d+),", src):
            self.assertEqual((listed[key]['min'], listed[key]['max']), (int(lo), int(hi)), key)
        # pedestrians: a live 0..1000 slider and a switch, usable before the drive (the count is kept)
        w = listed['walkers']
        self.assertEqual((w['kind'], w['min'], w['max'], w['step'], w.get('live')), ('int', 0, 1000, 10, True))
        self.assertNotIn('disabled', w)
        self.assertEqual(listed['walkersOn']['kind'], 'bool')
        self.assertEqual(listed['knock']['kind'], 'bool')
        self.assertIn('hint', listed['knock'])
        # nothing saved: what the game did before the registry (no walkers, props knockable)
        self.assertEqual((w['value'], listed['walkersOn']['value'], listed['knock']['value']), (200, False, True))
        self.assertEqual(len(lua.eval('fake.calls')), 0)

    def test_registry_change_reaches_the_widget(self):
        lua = self.world()
        lua.execute('''
          tunePtr = up(drawTune, 'tunePtr')
          tunePtr.maxTrees = {[0] = 1}; tunePtr.quality = {[0] = 1}; tunePtr.groundTrees = {[0] = true}
          assert(o.set('quality', 100, 'ui') == 100)
        ''')
        self.assertEqual(lua.eval('S.tune.quality'), 100)
        self.assertEqual(lua.eval('S.tune.maxTrees'), 2400)           # the OASIS preset, as the widget's slider
        self.assertEqual(lua.eval('tunePtr.maxTrees[0]'), 2400)        # the widget's slider copy follows
        self.assertEqual(lua.eval('tunePtr.quality[0]'), 100)
        lua.execute("o.set('groundTrees', false)")
        self.assertFalse(lua.eval('tunePtr.groundTrees[0]'))
        self.assertEqual(lua.eval("(o.set('maxTrees', 1234))"), 1250)    # step 50
        self.assertEqual(lua.eval('tunePtr.maxTrees[0]'), 1250)
        # every change is pushed to the page
        last = to_py(lua.eval('pushed[#pushed]'))
        self.assertEqual(last['name'], 'EarthNGOptions')
        advanced = next(g for g in last['data']['groups'] if g['key'] == 'advanced')
        self.assertEqual(next(x['value'] for x in advanced['options'] if x['key'] == 'maxTrees'), 1250)

    def test_widget_change_reaches_the_registry_and_page(self):
        lua = self.world()
        lua.execute('''
          S.state = 'driving'; S.now = 10; S.stream = {}
          up(draw, 'focus', function() return nil end)
        ''')
        # the street line was off on disk: restored at load, both views agree
        self.assertFalse(lua.eval("o.get('streetLine')"))
        self.assertTrue(lua.eval('S.locationOff'))
        before = lua.eval('#pushed')
        # the widget's own checkbox
        lua.execute('''
          openHeader = 'Вигляд і трафік'
          clicked = 'Рядок з назвою вулиці'
          draw()
        ''')
        self.assertTrue(lua.eval("o.get('streetLine')"))
        self.assertFalse(lua.eval('S.locationOff'))
        self.assertIs(lua.eval('disk.locationOff'), False)             # saved under the old key
        self.assertGreater(lua.eval('#pushed'), before)
        # and back from the page: the widget's checkbox shows it
        lua.execute("mod.optionsSet('streetLine', false)")
        self.assertFalse(lua.eval('S.locationShown[0]'))
        self.assertTrue(lua.eval('S.locationOff'))
        # the widget's tune slider writes S.tune itself; poll carries it to the page
        lua.execute("S.tune = S.tune or {}; S.tune.maxRocks = 77; n = #pushed; o.poll(100)")
        self.assertEqual(lua.eval("o.get('maxRocks')"), 77)
        self.assertEqual(lua.eval('#pushed'), lua.eval('n') + 1)
        # the widget's UA/EN button
        lua.execute("clicked = 'EN##lang'; openHeader = nil; draw(); o.poll(200)")
        self.assertEqual(lua.eval("o.get('lang')"), 'en')
        self.assertEqual(to_py(lua.eval('pushed[#pushed]'))['data']['lang'], 'en')
        # a refused value from the page: the page gets the value in force back
        lua.execute("n = #pushed; mod.optionsSet('lang', 'de')")
        self.assertEqual(lua.eval('#pushed'), lua.eval('n') + 1)
        self.assertEqual(lua.eval("o.get('lang')"), 'en')

    def test_traffic_rows_share_state(self):
        lua = self.world()
        lua.execute('''
          S.state = 'driving'
          flowCalls = {}
          mod.flowSet = function(n) flowCalls[#flowCalls+1] = n; S.flow = {F = {target = n}} end
        ''')
        self.assertEqual(lua.eval("(o.set('flow', 200))"), 200)
        self.assertEqual(lua.eval('flowCalls[1]'), 200)
        self.assertEqual(lua.eval("o.get('flow')"), 200)
        lua.execute("o.set('walkersOn', true)")
        self.assertEqual(lua.eval("(o.set('walkers', 400))"), 400)
        self.assertEqual(lua.eval("o.get('walkers')"), 400)
        self.assertEqual(lua.eval('fake.asked'), 400)
        self.assertEqual(lua.eval("(o.set('parkedCars', 16))"), 16)
        self.assertEqual(lua.eval('S.parkedPick'), 16)                  # updateParking applies it, as for the widget
        lua.execute('S.flow = nil')                                      # (the fake flow has no hand-off pool)
        self.assertEqual(lua.eval("(o.set('flowReal', 12))"), 12)
        self.assertEqual(lua.eval('S.flowReal'), 12)
        lua.execute("S.state = 'pick'")
        self.assertIsNone(lua.eval("(o.set('flow', 0))"))                 # only while driving


    def test_walkers_switch_keeps_the_count(self):
        lua = self.world()
        lua.execute("S.state = 'driving'")
        # the count alone, while off: nothing walks, the count is kept
        self.assertEqual(lua.eval("(o.set('walkers', 2000))"), 1000)       # clamped at walkers.MAX
        self.assertEqual(lua.eval("(o.set('walkers', 333))"), 330)         # step 10
        self.assertEqual(len(lua.eval('fake.calls')), 0)
        lua.execute("o.set('walkersOn', true)")
        self.assertEqual(lua.eval('fake.asked'), 330)
        lua.execute("o.set('walkers', 500)")                                  # live while on
        self.assertEqual(lua.eval('fake.asked'), 500)
        lua.execute("o.set('walkersOn', false)")
        self.assertEqual(lua.eval('fake.asked'), 0)
        self.assertEqual(lua.eval("o.get('walkers')"), 500)                  # off keeps the count
        lua.execute("o.set('walkersOn', true)")
        self.assertEqual(lua.eval('fake.asked'), 500)
        # test_world.py --walkers N calls walkersSet itself: the options follow by poll
        lua.execute("mod.walkersSet(240); n = #pushed")
        self.assertTrue(lua.eval('o.poll(50)'))
        self.assertEqual(lua.eval("o.get('walkers')"), 240)
        self.assertTrue(lua.eval("o.get('walkersOn')"))
        lua.execute("o.set('walkersOn', false); o.set('walkersOn', true)")
        self.assertEqual(lua.eval('fake.asked'), 240)                        # its count was kept

    def test_walkers_note_follows_the_counts(self):
        lua = self.world()
        self.assertIsNone(lua.eval("o.noteText('walkers', 'uk')"))           # off: no line
        lua.execute("o.set('walkersOn', true)")                               # before the drive
        self.assertEqual(lua.eval("o.noteText('walkers', 'en')"), 'They come with the drive')
        lua.execute("S.state = 'driving'; mod.walkersSet(400); fake.walking = 320")
        self.assertEqual(lua.eval("o.noteText('walkers', 'uk')"), 'Ходять 320 з 400 · місця на 590')
        self.assertEqual(lua.eval("o.noteText('walkers', 'en')"), 'Walking 320 of 400 · room for 590')
        # the same counts: the cached string, not a new one (no garbage per frame)
        lua.execute("a = o.noteText('walkers', 'en')")
        self.assertTrue(lua.eval("rawequal(a, o.noteText('walkers', 'en'))"))
        # the page gets it in the payload, and poll pushes when only the counts move
        lua.execute("o.poll(10); n = #pushed; fake.walking = 330")
        self.assertTrue(lua.eval('o.poll(20)'))
        self.assertEqual(lua.eval('#pushed'), lua.eval('n') + 1)
        traffic = next(g for g in to_py(lua.eval('pushed[#pushed].data'))['groups'] if g['key'] == 'traffic')
        note = next(x for x in traffic['options'] if x['key'] == 'walkers')['note']
        self.assertEqual(note, {'uk': 'Ходять 330 з 400 · місця на 590', 'en': 'Walking 330 of 400 · room for 590'})
        self.assertFalse(lua.eval('o.poll(30)'))                             # nothing moved: quiet

    def test_people_settings_persist(self):
        lua = self.world()
        lua.execute("o.set('walkers', 350); o.set('walkersOn', true); o.set('knock', false)")
        disk = to_py(lua.eval('disk'))
        self.assertEqual((disk['walkers'], disk['walkersOn'], disk['knock']), (350, True, False))
        self.assertEqual(disk['lang'], 'uk')                                  # the rest stays
        # a new session restores them (on first, then the count, which follows: before the drive
        # walkersSet only remembers it)
        again = self.world("{lang='uk', walkers=350, walkersOn=true, knock=false}")
        self.assertEqual(again.eval('fake.asked'), 350)
        self.assertEqual(again.eval("o.get('walkers')"), 350)
        self.assertFalse(again.eval('mod.knockGet()'))
        self.assertTrue(again.eval("o.get('walkersOn')"))
        # saved off with a count: the count is shown, nobody walks
        off = self.world("{walkers=780, walkersOn=false}")
        self.assertEqual(off.eval("o.get('walkers')"), 780)
        self.assertEqual(len(off.eval('fake.calls')), 0)
        self.assertTrue(off.eval('mod.knockGet()'))                          # no key: knockable, as before

    def test_knock_switch_calls_knockSet(self):
        lua = self.world()
        lua.execute("calls = {}; local real = mod.knockSet; mod.knockSet = function(v) calls[#calls+1] = v; real(v) end")
        lua.execute("o.set('knock', false)")
        self.assertEqual(list(lua.eval('calls').values()), [False])
        self.assertFalse(lua.eval('mod.knockGet()'))
        lua.execute("mod.knockSet(true)")                                     # switched elsewhere
        self.assertTrue(lua.eval("o.get('knock')"))

    def test_widget_rows_go_through_the_registry(self):
        lua = self.world()
        lua.execute("S.state = 'driving'")
        # the switch, then the slider while it is on (live, each frame of the drag)
        lua.execute("clicked = 'Пішоходи##walkOn'; mod.drawPeopleRows()")
        self.assertTrue(lua.eval("o.get('walkersOn')"))
        self.assertEqual(lua.eval('fake.asked'), 200)
        lua.execute("clicked = nil; slid = '##walkN'; slideTo = 640; mod.drawPeopleRows()")
        self.assertEqual(lua.eval('fake.asked'), 640)
        self.assertEqual(lua.eval('S.peoplePtrs.n[0]'), 640)
        # from the page: the widget's controls show it on the next frame
        lua.execute("slid = nil; mod.optionsSet('walkers', 120); mod.optionsSet('knock', false); mod.drawPeopleRows()")
        self.assertEqual(lua.eval('S.peoplePtrs.n[0]'), 120)
        self.assertFalse(lua.eval('S.peoplePtrs.knock[0]'))
        lua.execute("mod.optionsSet('walkersOn', false); mod.drawPeopleRows()")
        self.assertFalse(lua.eval('S.peoplePtrs.on[0]'))
        self.assertEqual(lua.eval('S.peoplePtrs.n[0]'), 120)                 # the count stays on the slider
        # the knock checkbox
        lua.globals().clicked = "Збивані об'єкти##knock"
        lua.execute("mod.drawPeopleRows()")
        self.assertTrue(lua.eval('mod.knockGet()'))
        self.assertIs(lua.eval('disk.knock'), True)


class AppFilesTests(unittest.TestCase):
    """ui/modules/apps/EarthNG: the files the game's app list needs, packed by build_mod.py (mod/ as is)."""

    def test_app_manifest_matches_the_directive(self):
        manifest = json.loads((APP / 'app.json').read_text(encoding='utf8'))
        js = (APP / 'app.js').read_text(encoding='utf8')
        self.assertIn(f"directive('{manifest['directive']}'", js)
        tag = re.sub(r'([A-Z])', lambda m: '-' + m.group(1).lower(), manifest['directive'])
        self.assertEqual(manifest['domElement'], f'<{tag}></{tag}>')
        self.assertTrue((APP / 'app.png').is_file())
        self.assertIn("angular.module('beamng.apps')", js)
        # the page talks to the world extension only through these and the hook
        self.assertIn('e2r_world.optionsList', js)
        self.assertIn('e2r_world.optionsSet', js)
        self.assertIn("'EarthNGOptions'", js)
        self.assertIn('o.live', js)                                       # live sliders, throttled
        self.assertIn('o.note', js)                                       # the live state line
        self.assertNotRegex(js, r'https?://')                           # nothing from the network


if __name__ == '__main__':
    unittest.main()
