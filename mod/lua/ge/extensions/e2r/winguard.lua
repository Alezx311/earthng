-- Keeps the EarthNG widget windows on the game's own screen.
-- BeamNG runs ImGui with multi-viewports on: a window dragged over the edge of the game window,
-- even by a few pixels, is moved by ImGui into an OS window of its own. Such a window takes the OS
-- focus from the game when clicked or when it appears (keys stop driving the car), can sit on
-- another monitor or behind the game, and imgui.ini remembers it there (ViewportPos=1899,150 for
-- EarthNG##mini on a 1920 px wide game: a 21 px strip left on screen). Each state of the widget is
-- a window of its own (mini, picker, landing, restore), each with its own remembered place, so the
-- widget seemed to jump off screen whenever the state changed.
-- So every EarthNG window is pinned to the main viewport (never an OS window), never focuses itself
-- on appearing, and is pulled back whole into the main viewport when it is found outside it (not
-- while a mouse button is down: the player may be dragging it; not while the game is minimised).
-- Cheap: the viewport ID is cached, one preallocated ImVec2, the position read every CHECK frames.
local M = {CHECK = 10, MIN_DISPLAY = 64}

local extra, viewportId, pos
local frame = 0

-- the flags every EarthNG window gets on top of its own (the stock wrapper's default
-- NoFocusOnAppearing is lost as soon as a window passes flags of its own)
function M.flags(im, base)
  if not extra then
    extra = 0
    for _, name in ipairs({'WindowFlags_NoFocusOnAppearing', 'WindowFlags_NoDocking'}) do
      local f = im[name]
      if type(f) == 'number' then extra = extra + f end
    end
  end
  return (base or 0) + extra
end

local function minimised(im, view)
  local flag = im.ViewportFlags_IsMinimized
  if type(flag) ~= 'number' or flag == 0 then return false end
  local ok, flags = pcall(function() return view.Flags end)
  return ok and type(flags) == 'number' and (bit or require('bit')).band(flags, flag) ~= 0
end

-- Inside Begin/End of the window: pull it back whole when any of it is outside the main viewport
-- (larger than the viewport: its top-left corner, i.e. the title bar, at the viewport's).
-- Returns true when it moved the window.
function M.keepInside(im)
  local view = im.GetMainViewport and im.GetMainViewport()
  if not view then return false end
  local vp, vs = view.Pos, view.Size
  if not vp or not vs or vs.x < M.MIN_DISPLAY or vs.y < M.MIN_DISPLAY or minimised(im, view) then return false end
  local at = im.GetWindowPos()
  local w, h = im.GetWindowWidth(), im.GetWindowHeight()
  if not at or type(w) ~= 'number' or type(h) ~= 'number' then return false end
  local x = math.max(vp.x, math.min(at.x, vp.x + vs.x - w))
  local y = math.max(vp.y, math.min(at.y, vp.y + vs.y - h))
  if x == at.x and y == at.y then return false end
  pos = pos or im.ImVec2(0, 0)
  pos.x, pos.y = x, y
  im.SetWindowPos1(pos, im.Cond_Always)
  return true
end

-- im.Begin for an EarthNG window: main viewport, no focus on appearing, kept on screen
function M.begin(im, name, flags)
  if viewportId == nil then
    local id = im.getMainViewPortId and im.getMainViewPortId()
    if id == nil then
      local view = im.GetMainViewport and im.GetMainViewport()
      id = view and view.ID
    end
    viewportId = id ~= nil and type(id) ~= 'function' and id or false
  end
  if viewportId and im.SetNextWindowViewport then im.SetNextWindowViewport(viewportId) end
  local open = im.Begin(name, nil, M.flags(im, flags))
  frame = frame + 1
  if (frame >= M.CHECK or im.IsWindowAppearing()) and not (im.IsMouseDown(0) or im.IsMouseDown(1)) then
    frame = 0
    M.keepInside(im)
  end
  return open
end

-- tests: forget the cached viewport, flags and counter
function M.reset() extra, viewportId, pos, frame = nil, nil, nil, 0 end

return M
