"""Dense streaming queues preserve order while releasing retired references."""
import unittest
from pathlib import Path
from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]


class ForestQueueTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.fifo = self.lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/fifo.lua').read_text())

    def test_interleaved_batches_preserve_fifo_and_reuse_empty_queue(self):
        q = self.fifo.new()
        for batch in range(20):
            for i in range(100):
                self.fifo.push(q, batch * 100 + i)
            for i in range(50):
                self.assertEqual(self.fifo.pop(q), batch * 50 + i)
        self.assertEqual(self.fifo.size(q), 1000)
        for i in range(1000, 2000):
            self.assertEqual(self.fifo.pop(q), i)
        self.assertIsNone(self.fifo.pop(q))
        self.assertEqual(self.fifo.size(q), 0)
        self.fifo.push(q, 'next landing')
        self.assertEqual(self.fifo.pop(q), 'next landing')

    def test_consumed_items_do_not_retain_tile_or_mesh_tables(self):
        self.lua.globals().fifo = self.fifo
        self.assertTrue(self.lua.execute('''
          local q, weak = fifo.new(), setmetatable({}, {__mode='v'})
          do local tile={}; weak[1]=tile; fifo.push(q,{tile=tile}) end
          fifo.pop(q)
          collectgarbage('collect')
          return weak[1] == nil
        '''))

    def world(self):
        """Exercise the real scheduler with a strict, position-aware engine stand-in."""
        self.lua.globals().fifo = self.fifo
        self.lua.globals().quality = self.lua.execute(
            (ROOT / 'mod/lua/ge/extensions/e2r/quality.lua').read_text(encoding='utf8'))
        self.lua.execute('''
          require=function(name)
            if name=='ge/extensions/e2r/fifo' then return fifo end
            if name=='ge/extensions/e2r/quality' then return quality end
            return {}
          end
          ui_imgui=setmetatable({ArrayChar=function() return {} end},
            {__index=function() return function() end end})
          hptimer=function() return {stop=function() return 0 end} end
          vec3=function(x,y,z) return {x=x,y=y,z=z} end
          Box3F=function() return {} end
          MatrixF=function() return {setFromEuler=function() end,setPosition=function() end} end
          function findUp(fn, target, seen)
            seen=seen or {}; if seen[fn] then return end; seen[fn]=true
            local children={}
            for i=1,200 do
              local n,v=debug.getupvalue(fn,i); if not n then break end
              if n==target then return v end
              if type(v)=='function' then children[#children+1]=v end
            end
            for _,child in ipairs(children) do local v=findUp(child,target,seen);if v then return v end end
          end
          items={}; removed={}; created=0
          kind={getName=function() return 'bench' end}
          data={getItemsBox=function() return items end,
            removeItem=function(_,item)
              assert(not removed[item.key], 'duplicate engine removal')
              removed[item.key]=true
            end,
            createNewItem=function() created=created+1;return {} end}
          forest={getID=function() return 1 end,getData=function() return data end}
          scenetree={findObject=function(name) if name=='e2rForest' then return forest end;return kind end,
            findObjectById=function() return forest end}
          function item(key,x,y)
            return {key=key,getKey=function(self) return self.key end,
              getPosition=function() return vec3(x,y,0) end,getData=function() return kind end}
          end
        ''')
        src = (ROOT / 'mod/lua/ge/extensions/e2r/world.lua').read_text(encoding='utf8')
        self.lua.globals().world = self.lua.execute(src)
        self.lua.execute('''
          S=world.dbg().S; S.stream={tile=500};S.now=10
          retire=findUp(world.tick,'retireForest');commit=findUp(world.onUpdate,'forestCommit')
          shapes=findUp(retire,'plantShape');shapes.bench='bench.dae#solid'
        ''')

    def test_retirement_owns_half_open_tile_and_deduplicates_pending_items(self):
        self.world()
        self.lua.execute('''
          -- Engine bounds overlap includes objects anchored outside this tile.
          items={item(1,499.995,250),item(2,500,250),item(3,-.005,250),
            item(4,0,0),item(5,250,500),item(6,250,-.005)}
          retire({forestId=1,i=0,j=0});retire({forestId=1,i=0,j=0})
          assert(fifo.size(S.forestQ['bench.dae#solid'].removes)==2)
          commit()
          assert(removed[1] and removed[4] and not removed[2] and not removed[3]
            and not removed[5] and not removed[6])
          assert(next(S.forestQ['bench.dae#solid'].removing)==nil)
          items={item(7,-500,-500),item(8,0,-250)}
          retire({forestId=1,i=-1,j=-1});S.now=12;commit()
          assert(removed[7] and not removed[8])
        ''')

    def test_instanced_lamps_register_only_on_commit_and_retire_their_light(self):
        self.world()
        self.lua.execute('''
          local lamp='/art/shapes/objects/lamp1.dae'
          local queue=findUp(retire,'forestQueue')
          local q=queue(lamp .. '#solid')
          fifo.push(q.adds,{{shape=lamp,pos={250,250,10}},{forestGen=1},0})
          fifo.push(q.adds,{{shape=lamp,pos={260,250,10}},{forestGen=1},1})
          commit()
          assert(S.lamps['250_250']==nil and S.lamps['260_250'][3]==10)
          shapes.bench=lamp .. '#solid'
          items={item(1,260,250)}
          retire({forestId=1,i=0,j=0})
          assert(S.lamps['260_250']==nil)
        ''')

    def test_dense_retirements_share_batch_budget_with_adds_and_drop_stale_generations(self):
        self.world()
        self.lua.execute('''
          for i=1,1300 do items[i]=item(i,250,250) end
          retire({forestId=1,i=0,j=0})
          local q=S.forestQ['bench.dae#solid']
          for i=1,700 do fifo.push(q.adds,{{pos={0,0,0}},{forestGen=1},i==1 and 0 or 1}) end
          commit();assert(fifo.size(q.removes)==700 and created==0)
          S.now=12;commit();assert(fifo.size(q.removes)==100 and created==0)
          S.now=14;commit();assert(fifo.size(q.removes)==0 and created==499)
          S.now=16;commit();assert(created==699 and q.since==nil)
          local result=world.dbg().result
          assert(result.forestPendingAdds==0 and result.forestPendingRemoves==0)
        ''')


if __name__ == '__main__':
    unittest.main()
