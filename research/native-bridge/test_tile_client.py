"""Protocol/client checks without starting or modifying the game."""
from pathlib import Path
import unittest
from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[2] / 'mod/lua/ge/extensions/e2r/rust_tile_client.lua'


class TileClientTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.client = self.lua.execute(SOURCE.read_text(encoding='utf8'))

    def run_fake(self, response_epoch, request='EFG1', response='ETR1', lod=1):
        return self.lua.execute('''
          local client, epoch, request, response, lod = ...
          local ffi = require('ffi')
          local function u(n) return ffi.string(ffi.new('uint32_t[1]', n),4) end
          local body = response .. u(0) .. u(0) .. u(0)
          local reply = 'ETC1' .. u(7) .. u(0) .. u(epoch) .. u(0)
            .. u(lod) .. u(#body) .. body
          reply = u(#reply) .. reply
          local sock = {bytes='', cursor=1, closed=false}
          function sock:send(s, start)
            local last=math.min(#s, start+6)
            self.bytes=self.bytes .. s:sub(start,last)
            if last<#s then return nil,'timeout',last end
            return last
          end
          function sock:receive(n)
            local count=math.min(n,5)
            local chunk=reply:sub(self.cursor,self.cursor+count-1)
            self.cursor=self.cursor+#chunk
            if #chunk<n then return nil,'timeout',chunk end
            return chunk
          end
          function sock:close() self.closed=true end
          local job=client.new(sock,request,7,12,lod)
          for i=1,100 do
            local result, err=job:step()
            if result ~= nil then return result,err,sock.closed,sock.bytes end
          end
          error('not completed')
        ''', self.client, response_epoch, request, response, lod)

    def test_fragmented_transport(self):
        result, error, closed, sent = self.run_fake(12)
        self.assertTrue(result.startswith('ETR1'))
        self.assertIsNone(error)
        self.assertTrue(closed)
        self.assertEqual(sent[4:8], 'ETB1')

    def test_stale_response_is_discarded(self):
        result, error, closed, _ = self.run_fake(13)
        self.assertFalse(result)
        self.assertEqual(error, 'stale or invalid response')
        self.assertTrue(closed)

    def test_road_and_wall_response_types(self):
        for request,response,lod in [('ERD1','ERR1',0),('ERD1','ERR1',1),('EWP1','EWR1',0)]:
            with self.subTest(request=request,lod=lod):
                result,error,closed,_=self.run_fake(12,request,response,lod)
                self.assertTrue(result.startswith(response))
                self.assertIsNone(error)
                self.assertTrue(closed)

    def test_wrong_payload_type_is_rejected(self):
        result,error,closed,_=self.run_fake(12,'ERD1','EWR1',0)
        self.assertFalse(result)
        self.assertEqual(error,'response payload')
        self.assertTrue(closed)


if __name__ == '__main__':
    unittest.main()
