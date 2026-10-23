-- Streaming FIFO. Popping releases the value immediately and does not copy the
-- remaining queue (tens of thousands of pending Forest props during a landing).
local M = {}
function M.new() return {first = 1, last = 0} end
function M.size(q) return q.last - q.first + 1 end
function M.push(q, value)
  assert(value ~= nil, 'cannot queue nil')
  q.last = q.last + 1
  q[q.last] = value
end
function M.pop(q)
  if q.first > q.last then return nil end
  local value = q[q.first]
  q[q.first] = nil
  q.first = q.first + 1
  if q.first > q.last then q.first, q.last = 1, 0 end
  return value
end
return M
