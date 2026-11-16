-- Experimental opt-in roof bridge. This is not a complete Rust tile generator.
-- The caller never waits for Rust: missing/late results fall back to Lua.
local client = require('ge/extensions/e2r/rust_tile_client')
local roofs = require('ge/extensions/e2r/rust_tile_roofs')
local roads = require('ge/extensions/e2r/rust_tile_roads')
local M = {}
local sequence = 0

function M.begin(cells, rect, far, config, epoch)
  if type(config) ~= 'table' or config.enabled ~= true then return nil end
  local port = tonumber(config.port)
  if not port or port % 1 ~= 0 or port < 1 or port > 65535 then return nil end
  local ok, socket = pcall(require, 'socket')
  if not ok or type(socket) ~= 'table' then return nil end
  local tcp = socket.tcp()
  if not tcp then return nil end
  tcp:settimeout(0)
  pcall(function() tcp:setoption('tcp-nodelay', true) end)
  local connected, err = tcp:connect('127.0.0.1', port)
  if not connected and err ~= 'timeout' then tcp:close(); return nil end
  sequence = (sequence + 1) % 4294967296
  local workers = math.max(1, math.min(4, math.floor(tonumber(config.workers) or 2)))
  local job = roofs.start(client, tcp, cells, rect, far, sequence, (epoch or 0) % 4294967296, workers)
  if not job then tcp:close(); return nil end
  job.id, job.hits, job.attempts, job.debug = sequence, 0, 0, config.debug == true
  job.config, job.epoch, job.far, job.kind = config, epoch, far, 'roof'
  job.provider = setmetatable({}, {__index = function(_, building)
    M.pump(job)
    job.attempts = job.attempts + 1
    local found = job.cache[building]
    if found then job.hits = job.hits + 1 end
    return found
  end})
  return job
end

function M.beginRoad(parent, prepared, list, mitre)
  if not parent then return nil end
  local ok, socket = pcall(require, 'socket')
  if not ok or type(socket) ~= 'table' then return nil end
  local tcp=socket.tcp()
  if not tcp then return nil end
  tcp:settimeout(0)
  pcall(function() tcp:setoption('tcp-nodelay',true) end)
  local connected, err=tcp:connect('127.0.0.1', tonumber(parent.config.port))
  if not connected and err~='timeout' then tcp:close();return nil end
  sequence=(sequence+1)%4294967296
  local workers=math.max(1,math.min(4,math.floor(tonumber(parent.config.workers) or 2)))
  local job=roads.start(client,tcp,prepared,list,mitre,parent.far,sequence,(parent.epoch or 0)%4294967296,workers)
  if not job then tcp:close();return nil end
  job.id,job.hits,job.attempts,job.debug,job.kind=sequence,0,0,parent.debug,'road'
  return job
end

function M.roadResult(job,road)
  if not job then return nil end
  M.pump(job)
  job.attempts=job.attempts+1
  local pair=job.cache[road]
  if pair then job.hits=job.hits+1;return pair[1],pair[2] end
end

function M.pump(job)
  if not job or job.done then return end
  local ok, value = pcall(job.step, job)
  if not ok then job:cancel(); job.error = tostring(value) end
end

function M.finish(job)
  if not job then return end
  if not job.done then job:cancel(); job.error = 'cancelled' end
  if job.debug and type(log) == 'function' then
    log('I', 'e2r_rust', string.format('%s job=%d hits=%d attempts=%d status=%s',
      job.kind or 'roof', job.id, job.hits, job.attempts, tostring(job.error or 'ready')))
  end
end
return M
