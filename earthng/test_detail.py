"""Execute the actual Lua streaming policy under LuaJIT, with a fake scene API."""
from pathlib import Path
import sys
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r'


class DetailTests(unittest.TestCase):
    def make(self):
        lua = LuaRuntime()
        lua.globals().detail = lua.execute((ROOT / 'detail.lua').read_text())
        lua.globals().quality = lua.execute((ROOT / 'quality.lua').read_text())
        lua.execute('''
          live, made, removed, serial = {}, 0, 0, 0
          stream = detail.new(function(parts, pause)
            pause(); serial=serial+1; live[serial]=parts; made=made+1; return serial
          end, function(id) assert(live[id]); live[id]=nil; removed=removed+1 end)
          tile={}; p={x=0,y=0,z=0}; tune=quality.preset(50); now=0
          timer={stop=function() return 0 end}
          function add(x,y,kind,owner)
            local it={kind='static',shape=kind=='rock' and '/rocks/a.dae' or '/3d_grass/a.dae',pos={x,y,0}}
            return stream:add(owner or tile,it)
          end
          function tufts() local n=0; for _,parts in pairs(live) do for _,part in ipairs(parts) do n=n+part.n end end; return n end
          function each(fn) for _,parts in pairs(live) do for _,part in ipairs(parts) do for k=1,part.n do fn(part.x[k],part.y[k]) end end end end
          function step(n)
            for i=1,n do
              now=now+.3; local before, gone=made, removed
              stream:step(p,tune,now,timer,1)
              assert(made-before<=2 and removed-gone<=16, 'unbounded engine mutations in a frame')
              assert(stream.count.grass<=tune.grassBudget and stream.count.rock<=tune.rockBudget)
              assert(stream.count.grass+stream.count.rock==tufts())
            end
          end
        ''')
        return lua

    def test_bubble_caps_distance_movement_and_return(self):
        lua = self.make()
        lua.execute('''
          tune.grassM=50; tune.grassBudget=400
          for x=-300,300,3 do for y=-80,80,3 do add(x,y) end end
          step(100); assert(stream.count.grass>0 and stream.count.grass<=400)
          local reach=(55+32*.71)^2
          each(function(x,y) assert(x^2+y^2<=reach*1.2) end)
          p={x=240,y=0,z=0}; step(100)
          each(function(x,y) assert((x-240)^2+y^2<=reach*1.2) end)
          p={x=0,y=0,z=0}; step(100); assert(stream.count.grass>0)
          p={x=0,y=0,z=500}; step(100); assert(stream.count.grass==0 and next(live)==nil)
        ''')

    def test_lawn_patch_expands_to_an_even_short_carpet(self):
        lua = self.make()
        lua.execute(r'''
          local part = {tile={}, n=10, staticN=1, patches={{
            x=0, y=0, shapes={'/3d_grass/a.dae','/3d_grass/b.dae','/3d_grass/c.dae'},
            spans={0.265, 0.258, 0.255}, bottoms={-0.038, -0.033, -0.019},
            samples={0, 10, 0.1, -0.2}}},
            x={4}, y={5}, z={6}, yaw={0.2}, scale={1}, shape={'/rocks/kept.dae'}}
          local out = detail.expand(part)
          assert(out.n==10 and out.x[1]==4 and out.shape[1]=='/rocks/kept.dae')
          local minx, maxx, miny, maxy = 1e9, -1e9, 1e9, -1e9
          for k=2,out.n do
            local span = out.shape[k]=='/3d_grass/a.dae' and 0.265 or out.shape[k]=='/3d_grass/b.dae' and 0.258 or 0.255
            local height = out.scale[k] * span
            assert(height>=0.32-1e-6 and height<=0.50+1e-6, height)
            local dx, dy = out.x[k]-1, out.y[k]-1
            local bottom = out.shape[k]=='/3d_grass/a.dae' and -0.038 or out.shape[k]=='/3d_grass/b.dae' and -0.033 or -0.019
            local expect = 10 + 0.1*dx - 0.2*dy - bottom*out.scale[k]
            assert(math.abs(out.z[k]-expect)<1e-6, out.z[k])
            if out.x[k]<minx then minx=out.x[k] end
            if out.x[k]>maxx then maxx=out.x[k] end
            if out.y[k]<miny then miny=out.y[k] end
            if out.y[k]>maxy then maxy=out.y[k] end
          end
          assert(maxx-minx>1.2 and maxy-miny>1.2)
          assert(maxx-minx<1.6 and maxy-miny<1.6)
          assert(minx>1-0.8 and maxx<1+0.8 and miny>1-0.8 and maxy<1+0.8)
        ''')

    def test_groundcover_patches_stream_with_the_grass(self):
        lua = self.make()
        lua.execute('''
          local function kind(shape) return detail.kind({kind='static', shape=shape}) end
          assert(kind('/levels/east_coast_usa/art/shapes/groundcover/Clover_closetop.dae') == 'grass')
          assert(kind('/levels/east_coast_usa/art/shapes/groundcover/lush_ferns_01_a.dae') == 'grass')
          assert(kind('/levels/east_coast_usa/art/shapes/trees/ECA_coast_bush/generibush.dae') == nil)
          assert(kind('/levels/east_coast_usa/art/shapes/rocks/eca_rock_small.dae') == 'rock')
        ''')

    def test_rocks_have_their_own_cells_and_negative_cells_unload(self):
        lua = self.make()
        lua.execute('''
          assert(add(0,0,'rock'))
          add(-1,-1); add(-33,-33); step(20)
          assert(stream.count.grass==2 and stream.count.rock==1 and stream.cellsLive==3)
          stream:remove(tile); tile.dropped=true
          local replacement={}; add(-1,-1,nil,replacement)
          step(30); assert(stream.count.grass==1 and stream.count.rock==0 and stream.cellsLive==1)
          assert(removed==3)
          stream:remove(replacement); step(30)
          assert(next(stream.cells)==nil and next(stream.live)==nil and next(live)==nil)
        ''')

    def test_rock_reach_and_cap_are_their_own(self):
        lua = self.make()
        lua.execute('''
          tune.grassM=40; tune.rockM=300; tune.rockBudget=5
          for x=0,600,40 do add(x,0,'rock'); add(x,4) end
          step(60)
          assert(stream.count.rock==5 and stream.count.grass<=3)
          tune.rockM=0; step(60); assert(stream.count.rock==0)
        ''')

    def test_time_budget_yields_and_camera_change_during_work(self):
        lua = self.make()
        lua.execute('''
          for x=0,150,2 do for y=0,150,2 do add(x,y) end end
          timer={stop=function() return 2 end}
          step(1); assert(stream.work and made==0)
          p={x=10000,y=10000,z=0}; step(3000)
          assert(stream.count.grass==0 and next(live)==nil)
        ''')

    def test_hysteresis_and_disable(self):
        lua = self.make()
        lua.execute('''
          tune.grassM=50; add(36,8); step(20); assert(made==1)
          p.x=-3; step(30); assert(removed==0)
          p.x=-40; step(30); assert(removed==1)
          p.x=0; step(30); assert(made==2)
          tune.grassM=0; step(30); assert(next(live)==nil)
        ''')

    def test_tile_replacement_while_selection_is_suspended(self):
        lua = self.make()
        lua.execute('''
          for x=0,100 do for y=0,100 do add(x,y) end end
          timer={stop=function() return 2 end}; step(1)
          stream:remove(tile); tile.dropped=true
          local replacement={}; add(0,0,nil,replacement)
          timer={stop=function() return 0 end}
          step(3000)
          assert(stream.count.grass==1 and stream.cellsLive==1)
        ''')

    def test_cell_rebuilt_when_its_tufts_change(self):
        lua = self.make()
        lua.execute('''
          add(1,1); step(10); assert(made==1 and stream.count.grass==1)
          local other={}; add(2,2,nil,other); step(10)
          assert(made==2 and removed==1 and stream.count.grass==2)
          stream:remove(other); step(10)
          assert(made==3 and removed==2 and stream.count.grass==1)
        ''')

    def test_presets_monotonic_and_invalid_saved_settings(self):
        lua = self.make()
        lua.execute('''
          local prev=quality.preset(0)
          for q=1,100 do
            local t=quality.preset(q)
            for _,k in ipairs({'nearM','farM','maxTrees','maxFarTrees','grassM','rockM','grassBudget','rockBudget'}) do
              assert(t[k]>=prev[k],k)
            end
            prev=t
          end
          assert(quality.name(0)=='Potato' and quality.name(100)=='OASIS')
          local t=quality.clamp({grassM=0/0,rockBudget=math.huge,maxTrees=10,maxFarTrees=900,nearM=4000,farM=800})
          assert(t.grassM==100 and t.rockBudget==700 and t.maxFarTrees==10 and t.farM==4000)
          local a,b=quality.preset(50,0),quality.preset(50,100)
          assert(a.maxTrees==b.maxTrees and a.grassM<b.grassM)
        ''')

    def world(self):
        lua = self.make()
        lua.globals().collision = lua.execute((ROOT / 'collision.lua').read_text())
        lua.globals().fifo = lua.execute((ROOT / 'fifo.lua').read_text())
        lua.execute('''
          ui_imgui = setmetatable({ArrayChar=function() return {} end}, {__index=function() return function() end end})
          native={setTune=quality.clamp,unload=function() end}
          require=function(n)
            if n=='ge/extensions/e2r/quality' then return quality end
            if n=='ge/extensions/e2r/detail' then return detail end
            if n=='ge/extensions/e2r/collision' then return collision end
            if n=='ge/extensions/e2r/fifo' then return fifo end
            if n=='ge/extensions/e2r/native' then return native end
            return {}
          end
          hptimer=function() return {stop=function() return 0 end} end
          scenetree={findObject=function() end}
          createObject=function() return {registerObject=function() end} end
          jsonReadFile=function() return {lang='en', unrelated='keep'} end
          jsonWriteFile=function(_,cfg) saved=cfg end
          function up(fn,name)
            for i=1,100 do local n,v=debug.getupvalue(fn,i); if n==name then return v end end
            error(name)
          end
        ''')
        lua.globals().world = lua.execute((ROOT / 'world.lua').read_text(encoding='utf8'))
        lua.execute("state=up(world.tick,'S')")
        return lua

    def forest(self):
        """world.lua's Forest commit with a fake Forest: two crown kinds, calls recorded."""
        lua = self.world()
        lua.execute('''
          spawnForest=up(up(world.tick,'stepQueue'),'spawnItem')
          spawnForest=up(spawnForest,'spawnForestItem')
          commit=up(world.onUpdate,'forestCommit')
          retire=up(up(world.tick,'updateTiles'),'retireForest')
          calls={adds={}, removes={}}
          local kinds={}
          local function kindOf(shape)
            kinds[shape]=kinds[shape] or {getName=function() return 'kind:'..shape end, shape=shape}
            return kinds[shape]
          end
          local items={}
          data={
            createNewItem=function(_, kind, m, scale)
              local pos, key = {x=m.pos.x,y=m.pos.y,z=m.pos.z}, #items+1
              local item={getData=function() return kind end, kind=kind.shape,
                getPosition=function() return pos end,getKey=function() return key end}
              items[#items+1]=item; calls.adds[#calls.adds+1]=kind.shape; return item
            end,
            removeItem=function(_, item) calls.removes[#calls.removes+1]=item.kind end,
            getItemsBox=function() local out={}; for _,it in ipairs(items) do out[#out+1]=it end; return out end,
          }
          local forest={getData=function() return data end, getID=function() return 7 end}
          scenetree={findObject=function(name) if name=='e2rForest' then return forest end end,
            findObjectById=function() return forest end}
          MatrixF=function() return {setFromEuler=function() end, setPosition=function(self,p) self.pos=p end} end
          vec3=function(x,y,z) return {x=x or 0,y=y or 0,z=z or 0} end
          Box3F=function() return {} end
          local plantData=up(spawnForest,'plantDataFor')
          for _,shape in ipairs({'/trees/a.dae','/trees/b.dae'}) do
            local k=kindOf(shape); up(plantData,'plantData')[shape]=k; up(plantData,'plantShape')[k:getName()]=shape
          end
          state.stream={tile=500}
          tile={i=0,j=0}
          function plant(shape,n) for k=1,n do assert(spawnForest({shape=shape,pos={k,k,0},rot={0,0,0,1}},tile)) end end
          function run(seconds) for f=1,math.floor(seconds*60) do state.now=(state.now or 0)+1/60; commit() end end
        ''')
        return lua

    def test_forest_commit_takes_one_kind_at_a_time(self):
        lua = self.forest()
        lua.execute('''
          plant('/trees/a.dae',300); plant('/trees/b.dae',200)
          assert(#calls.adds==0, 'nothing reaches the Forest outside a commit')
          state.now=10; commit()
          local first=calls.adds[1]
          assert(#calls.adds==300 or #calls.adds==200)
          for _,k in ipairs(calls.adds) do assert(k==first, 'one kind per commit') end
          run(0.05); assert(#calls.adds<=300, 'commits are spaced')
          run(0.2); assert(#calls.adds==500)
          plant('/trees/a.dae',10); run(0.5)
          assert(#calls.adds==500, 'a kind waits its interval')
          run(1.5); assert(#calls.adds==510)
        ''')

    def test_retired_tile_skips_pending_crowns_and_removes_by_box(self):
        lua = self.forest()
        lua.execute('''
          plant('/trees/a.dae',5); plant('/trees/b.dae',3)
          state.now=10; run(3)
          assert(#calls.adds==8 and tile.forestId)
          plant('/trees/a.dae',4)
          retire(tile)
          run(4)
          assert(#calls.adds==8, 'crowns queued before the retire are not planted')
          assert(#calls.removes==8, 'every planted crown found by the rectangle')
          local a,b=0,0
          for _,k in ipairs(calls.removes) do if k=='/trees/a.dae' then a=a+1 else b=b+1 end end
          assert(a==5 and b==3)
        ''')

    def test_new_material_pairs_per_frame_are_capped_while_driving(self):
        lua = self.world()
        lua.execute('''
          local step=up(world.tick,'stepQueue')
          made=0
          createObject=function() return {obj={}, registerObject=function() end, getID=function() return made end,
            createMesh=function() made=made+1 end, setPosition=function() end} end
          vec3=function(x,y,z) return {x,y,z} end
          local group={addObject=function() end}
          local tile={group=group, decor=group, sceneGroup=group, left=9, roadLeft=9}
          for k=1,4 do
            state.queue[#state.queue+1]={tile=tile, key='0_0', item={kind='proc', name='p'..k, pos={0,0,0},
              meshes={{material='a'},{material='b'}}}}
          end
          state.state='driving'; state.now=1; state.pairsFrame=0
          step()
          -- 3 pairs allowed: the first piece (2), then one more is started (4); the rest wait
          assert(made==2 and #state.queue==2, made)
          state.pairsFrame=0; step()
          assert(made==4 and #state.queue==0)
        ''')

    def test_batching_crowns_into_forest_jobs_rocks_stay_static(self):
        lua = self.world()
        lua.execute('''
          local queue=up(up(up(world.tick,'updateTiles'),'startScene'),'queueItems')
          local items={}
          for i=1,4800 do items[#items+1]={kind='static',shape='/3d_grass/a.dae',pos={i,0,0}} end
          for i=1,2304 do items[#items+1]={kind='static',shape='/trees/a.dae',pos={i,0,0}} end
          for i=1,96 do items[#items+1]={kind='static',shape='/art/shapes/rocks/a.dae',pos={i,0,0}} end
          local owner={}
          -- 2304 crowns in 18 Forest batches of 128; grass and rocks go to the cell streamer
          assert(queue(items,owner,'0_0','scene')==18)
          assert(#state.queue==18 and #owner.detailCells>0)
          local crowns, rocks=0, 0
          for _,job in ipairs(state.queue) do
            assert(job.scene)
            if job.item.kind=='plants' then crowns=crowns+#job.item.items else rocks=rocks+1 end
          end
          assert(crowns==2304 and rocks==0)
        ''')

    def test_quality_change_preserves_roads_and_unrelated_settings(self):
        lua = self.world()
        lua.execute('''
          local apply=up(up(up(world.onUpdate,'drawWindow'),'drawTune'),'applyTune')
          local roadGroup={sentinel=true}
          local tile={group=roadGroup,roadComplete=true,roadLeft=0,left=42,collided=true,sceneStarted=true}
          state.tiles={['0_0']=tile}; state.tune=quality.preset(100)
          state.queue={{tile=tile,item={kind='proc'}},{tile=tile,item={kind='plants'},scene=true}}
          apply()
          assert(state.tiles['0_0']==tile and tile.group==roadGroup and tile.collided and tile.roadComplete)
          assert(not tile.dropped and not tile.sceneStarted and tile.refreshScene)
          assert(#state.queue==1 and not state.queue[1].scene)
          assert(saved.unrelated=='keep' and saved.tune.quality==100)
        ''')


if __name__ == '__main__':
    unittest.main()
