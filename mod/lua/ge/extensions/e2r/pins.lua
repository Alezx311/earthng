-- Points of interest on the map (docs/POI.md, wave 1): the look of each 'pin' category
-- (fast_style.PIN_RULES, OSM tags, so every country's pack has them) and of the networks' points,
-- and drawing them on the minimap and the big map. Icons read without a language: pictograms and
-- the international letters P, WC, H, ATM. A tile hands its small records over in manifest.brandPOIs (generator.lua SPLIT.out): a
-- network's point {kind = 'fuel' ...} or a pin {kind = 'pin', cat = ...}. A category not in STYLE
-- is skipped, so a pack from a newer builder never breaks the map.
--
-- A marker is a round badge of its group's colour with a white rim, a soft shadow and its mark
-- from the atlas of pictograms (earthng/map_icons.py: the same drawings as on the plaques in the
-- world, map_icons.lua names the mark of each category); a point too minor for a badge at the
-- zoom is a ringed dot. Without the atlas (a dev build, a test) the letters and line drawings
-- below stand in.
--
-- Every frame: no tables are made. The candidates go into reused buckets by priority, a record
-- keeps its geographic position after its first frame, and glyph widths are measured once.

local M = {}
local okIcons, icons = pcall(require, 'ge/extensions/e2r/map_icons')
if not okIcons or type(icons) ~= 'table' or type(icons.cells) ~= 'table' then icons = nil end
M.icons = icons
M.texture = nil   -- function(path) -> a texture with texId (world.lua: imguiUtils.texObj)

-- colours of the groups (r, g, b): blue for the driver's services as on road signs, brown for
-- sights as on tourist signs
local GROUP = {
  car = {0.16, 0.38, 0.78}, stay = {0.52, 0.24, 0.56}, money = {0.08, 0.50, 0.30},
  shop = {0.86, 0.44, 0.10}, water = {0.12, 0.56, 0.86}, sight = {0.55, 0.34, 0.18},
  nature = {0.34, 0.44, 0.22}, transport = {0.80, 0.16, 0.22},
  health = {0.06, 0.52, 0.56}, civic = {0.33, 0.38, 0.50},
}

-- category: group, glyph (text) or shape, zoom it shows from, priority (1 first when crowded),
-- labelZoom: its name from that zoom (default 17)
local STYLE = {
  parking = {group = 'car', text = 'P', zoom = 16, priority = 5},
  car_dealer = {group = 'car', shape = 'car', zoom = 15, priority = 4},
  car_parts = {group = 'car', shape = 'wrench', zoom = 16, priority = 6},
  rest_area = {group = 'car', shape = 'table', zoom = 14, priority = 3, labelZoom = 15},
  toilets = {group = 'car', text = 'WC', zoom = 16, priority = 6},
  hotel = {group = 'stay', shape = 'bed', zoom = 15, priority = 3},
  motel = {group = 'stay', shape = 'bed', zoom = 14, priority = 3, labelZoom = 15},
  atm = {group = 'money', text = 'ATM', zoom = 16, priority = 5},
  payment_terminal = {group = 'money', shape = 'terminal', zoom = 17, priority = 8},
  exchange = {group = 'money', text = '$', zoom = 16, priority = 6},
  kiosk = {group = 'shop', shape = 'kiosk', zoom = 17, priority = 8},
  coffee_vending = {group = 'shop', shape = 'cup', zoom = 17, priority = 8},
  water_vending = {group = 'water', shape = 'drop', zoom = 17, priority = 8},
  drinking_water = {group = 'water', shape = 'drop', zoom = 17, priority = 8},
  spring = {group = 'water', shape = 'drop', zoom = 15, priority = 6, labelZoom = 16},
  well = {group = 'water', shape = 'drop', zoom = 16, priority = 7},
  picnic = {group = 'sight', shape = 'table', zoom = 15, priority = 7},
  viewpoint = {group = 'sight', shape = 'eye', zoom = 13, priority = 2, labelZoom = 15},
  cross = {group = 'sight', shape = 'cross', zoom = 15, priority = 6},
  shrine = {group = 'sight', shape = 'shrine', zoom = 15, priority = 6},
  peak = {group = 'nature', shape = 'peak', zoom = 12, priority = 2, labelZoom = 13},
  pass = {group = 'nature', shape = 'pass', zoom = 13, priority = 3, labelZoom = 14},
  tram_stop = {group = 'transport', shape = 'tram', zoom = 17, priority = 8},
  food = {group = 'shop', text = 'F', zoom = 16, priority = 6},
  service_map = {group = 'car', text = 'S', zoom = 16, priority = 6},
  shop_map = {group = 'shop', shape = 'kiosk', zoom = 17, priority = 8},
  sight = {group = 'sight', shape = 'eye', zoom = 15, priority = 4},
  leisure_map = {group = 'nature', text = 'L', zoom = 16, priority = 6},
  station_map = {group = 'transport', shape = 'tram', zoom = 16, priority = 5},
  -- networks and big formats (wave 2)
  mall = {group = 'shop', shape = 'bag', zoom = 13, priority = 3, labelZoom = 14},
  diy = {group = 'shop', shape = 'house', zoom = 15, priority = 5, labelZoom = 16},
  clinic = {group = 'health', shape = 'plus', zoom = 16, priority = 6},
  parcel_locker = {group = 'shop', shape = 'locker', zoom = 17, priority = 8},
  -- sights (wave 4)
  monument = {group = 'sight', shape = 'obelisk', zoom = 15, priority = 4, labelZoom = 17},
  castle = {group = 'sight', shape = 'castle', zoom = 11, priority = 2, labelZoom = 13},
  windmill = {group = 'sight', shape = 'windmill', zoom = 13, priority = 3, labelZoom = 15},
  cave = {group = 'nature', shape = 'cave', zoom = 14, priority = 4, labelZoom = 15},
  rock = {group = 'nature', shape = 'rock', zoom = 15, priority = 6, labelZoom = 16},
  waterfall = {group = 'water', shape = 'drop', zoom = 13, priority = 3, labelZoom = 14},
  -- the grey zone (decided 15.11.2026); military places are never in a pack
  metro = {group = 'transport', text = 'M', zoom = 14, priority = 3, labelZoom = 16},
  station = {group = 'transport', shape = 'train', zoom = 12, priority = 2, labelZoom = 13},
  airfield = {group = 'transport', shape = 'plane', zoom = 11, priority = 2, labelZoom = 12},
  ferry = {group = 'transport', shape = 'boat', zoom = 13, priority = 3, labelZoom = 14},
  lighthouse = {group = 'sight', shape = 'lighthouse', zoom = 12, priority = 2, labelZoom = 14},
  water_tower = {group = 'sight', shape = 'tower', zoom = 15, priority = 6},
  library = {group = 'civic', shape = 'book', zoom = 16, priority = 6},
  culture = {group = 'civic', shape = 'columns', zoom = 15, priority = 5, labelZoom = 16},
  hospital = {group = 'health', text = 'H', zoom = 13, priority = 3, labelZoom = 15},
  school = {group = 'civic', shape = 'cap', zoom = 15, priority = 6, labelZoom = 17},
}
M.STYLE, M.GROUP = STYLE, GROUP
-- the categories' names in the map search: {Ukrainian, English}
M.NAMES = {
  parking = {'парковка', 'parking'}, car_dealer = {'автосалон', 'car dealer'}, car_parts = {'автозапчастини', 'car parts'},
  rest_area = {'місце відпочинку', 'rest area'}, toilets = {'туалет', 'toilets'}, hotel = {'готель', 'hotel'},
  motel = {'мотель', 'motel'}, atm = {'банкомат', 'ATM'}, payment_terminal = {'термінал', 'payment terminal'},
  exchange = {'обмін валют', 'exchange'}, kiosk = {'кіоск', 'kiosk'}, coffee_vending = {'кавовий автомат', 'coffee machine'},
  water_vending = {'автомат з водою', 'water machine'}, drinking_water = {'питна вода', 'drinking water'},
  spring = {'джерело', 'spring'}, well = {'криниця', 'well'}, picnic = {'пікнік', 'picnic'}, viewpoint = {'оглядовий майданчик', 'viewpoint'},
  cross = {'хрест', 'wayside cross'}, shrine = {'капличка', 'shrine'}, peak = {'вершина', 'peak'}, pass = {'перевал', 'pass'},
  tram_stop = {'трамвайна зупинка', 'tram stop'}, food = {'їжа', 'food'}, service_map = {'сервіс', 'service'},
  shop_map = {'магазин', 'shop'}, sight = {'пам\'ятка', 'sight'}, leisure_map = {'відпочинок', 'leisure'},
  station_map = {'зупинка', 'stop'}, mall = {'ТРЦ', 'mall'}, diy = {'гіпермаркет', 'home and garden'},
  clinic = {'клініка', 'clinic'}, parcel_locker = {'поштомат', 'parcel locker'}, monument = {'пам\'ятник', 'monument'},
  castle = {'замок', 'castle'}, windmill = {'вітряк', 'windmill'}, cave = {'печера', 'cave'}, rock = {'скеля', 'rock'},
  waterfall = {'водоспад', 'waterfall'}, metro = {'метро', 'metro'}, station = {'вокзал', 'station'},
  airfield = {'аеродром', 'airfield'}, ferry = {'пором', 'ferry'}, lighthouse = {'маяк', 'lighthouse'},
  water_tower = {'водонапірна вежа', 'water tower'}, library = {'бібліотека', 'library'},
  culture = {'будинок культури', 'community centre'}, hospital = {'лікарня', 'hospital'}, school = {'школа', 'school'},
}
-- a far tile hands over only the pins seen from afar (generator.lua SPLIT.out)
M.FAR = {peak = true, pass = true, viewpoint = true, castle = true, airfield = true, lighthouse = true}

local LEVELS = 8
local MAX = 160          -- markers drawn at most (a town centre at z16 had 200 badges: a carpet)
local CELL = 60          -- world-anchored pixels, including breathing room around a badge
local buckets, counts = {}, {}
for k = 1, LEVELS do buckets[k], counts[k] = {}, 0 end
local occupied = {}
local widths = {}

-- the style of a record, nil to skip it; networks' points keep their old look (priority 1)
function M.style(poi)
  if poi.kind == 'pin' then return STYLE[poi.cat] end
  return nil
end

-- draw the shape `name` centred at x, y, about 12 px across times k, in ink
local shapeIm, shapeX, shapeY, shapeK
local function V(ax, ay)
  return shapeIm.ImVec2(shapeX + (ax - shapeX) * shapeK, shapeY + (ay - shapeY) * shapeK)
end
local function shape(im, dl, name, x, y, ink, fill, k)
  shapeIm, shapeX, shapeY, shapeK = im, x, y, k or 1
  if name == 'cross' or name == 'shrine' then
    im.ImDrawList_AddLine(dl, V(x, y - 5), V(x, y + 5), ink, 2)
    im.ImDrawList_AddLine(dl, V(x - 3.5, y - 2), V(x + 3.5, y - 2), ink, 2)
    if name == 'shrine' then im.ImDrawList_AddTriangleFilled(dl, V(x - 4.5, y - 4), V(x + 4.5, y - 4), V(x, y - 7), ink) end
  elseif name == 'peak' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 5, y + 4), V(x + 5, y + 4), V(x, y - 5), ink)
  elseif name == 'pass' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6, y + 4), V(x - 0.5, y + 4), V(x - 3.2, y - 4), ink)
    im.ImDrawList_AddTriangleFilled(dl, V(x + 0.5, y + 4), V(x + 6, y + 4), V(x + 3.2, y - 4), ink)
  elseif name == 'drop' then
    im.ImDrawList_AddCircleFilled(dl, V(x, y + 1.5), 3.5, ink)
    im.ImDrawList_AddTriangleFilled(dl, V(x - 3.2, y + 0.5), V(x + 3.2, y + 0.5), V(x, y - 5.5), ink)
  elseif name == 'eye' then
    im.ImDrawList_AddCircle(dl, V(x, y), 4.5, ink, 12, 1.5)
    im.ImDrawList_AddCircleFilled(dl, V(x, y), 2, ink)
  elseif name == 'table' then
    im.ImDrawList_AddLine(dl, V(x - 5, y - 1.5), V(x + 5, y - 1.5), ink, 2)
    im.ImDrawList_AddLine(dl, V(x - 3, y - 1.5), V(x - 4.5, y + 4.5), ink, 1.5)
    im.ImDrawList_AddLine(dl, V(x + 3, y - 1.5), V(x + 4.5, y + 4.5), ink, 1.5)
  elseif name == 'car' then
    im.ImDrawList_AddRectFilled(dl, V(x - 5.5, y - 1.5), V(x + 5.5, y + 2.5), ink, 1)
    im.ImDrawList_AddRectFilled(dl, V(x - 3, y - 4.5), V(x + 3, y - 1), ink, 1)
  elseif name == 'wrench' then
    im.ImDrawList_AddLine(dl, V(x - 4, y + 4), V(x + 2, y - 2), ink, 2)
    im.ImDrawList_AddCircle(dl, V(x + 3, y - 3), 2.5, ink, 8, 1.5)
  elseif name == 'terminal' then
    im.ImDrawList_AddRect(dl, V(x - 3.5, y - 5.5), V(x + 3.5, y + 5.5), ink, 1, 0, 1.5)
    im.ImDrawList_AddRectFilled(dl, V(x - 2, y - 4), V(x + 2, y - 1), ink)
  elseif name == 'kiosk' then
    im.ImDrawList_AddRectFilled(dl, V(x - 4.5, y - 1), V(x + 4.5, y + 5), ink)
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6, y - 1), V(x + 6, y - 1), V(x, y - 6), ink)
  elseif name == 'cup' then
    im.ImDrawList_AddRectFilled(dl, V(x - 3.5, y - 3), V(x + 2, y + 4), ink, 1)
    im.ImDrawList_AddCircle(dl, V(x + 3, y + .5), 2, ink, 8, 1.5)
  elseif name == 'tram' then
    im.ImDrawList_AddRectFilled(dl, V(x - 4, y - 3), V(x + 4, y + 4), ink, 1.5)
    im.ImDrawList_AddLine(dl, V(x, y - 3), V(x, y - 6), ink, 1.5)
    im.ImDrawList_AddLine(dl, V(x - 2.5, y - 6), V(x + 2.5, y - 6), ink, 1.5)
  elseif name == 'train' then
    im.ImDrawList_AddRectFilled(dl, V(x - 4, y - 5.5), V(x + 4, y + 3), ink, 2)
    im.ImDrawList_AddLine(dl, V(x - 3, y + 3), V(x - 5, y + 6), ink, 1.5)
    im.ImDrawList_AddLine(dl, V(x + 3, y + 3), V(x + 5, y + 6), ink, 1.5)
  elseif name == 'bed' then
    im.ImDrawList_AddRectFilled(dl, V(x - 5.5, y), V(x + 5.5, y + 2.5), ink)
    im.ImDrawList_AddRectFilled(dl, V(x - 5.5, y - 4), V(x - 4, y + 4.5), ink)
    im.ImDrawList_AddCircleFilled(dl, V(x - 1.8, y - 1.8), 1.8, ink)
    im.ImDrawList_AddRectFilled(dl, V(x + .5, y - 2.5), V(x + 5.5, y), ink, 1)
  elseif name == 'bag' then
    im.ImDrawList_AddRectFilled(dl, V(x - 4.5, y - 2), V(x + 4.5, y + 5), ink, 1)
    im.ImDrawList_AddCircle(dl, V(x, y - 2.5), 2.5, ink, 10, 1.5)
  elseif name == 'house' then
    im.ImDrawList_AddRectFilled(dl, V(x - 4, y - 1), V(x + 4, y + 5), ink)
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6, y - 1), V(x + 6, y - 1), V(x, y - 6), ink)
  elseif name == 'plus' then
    im.ImDrawList_AddRectFilled(dl, V(x - 1.6, y - 5), V(x + 1.6, y + 5), ink)
    im.ImDrawList_AddRectFilled(dl, V(x - 5, y - 1.6), V(x + 5, y + 1.6), ink)
  elseif name == 'locker' then
    for i = -1, 1 do
      for j = -1, 0 do
        im.ImDrawList_AddRectFilled(dl, V(x + i * 3.6 - 1.4, y + j * 4.4 - .4), V(x + i * 3.6 + 1.4, y + j * 4.4 + 3.6), ink)
      end
    end
  elseif name == 'obelisk' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 2, y + 3), V(x + 2, y + 3), V(x, y - 6), ink)
    im.ImDrawList_AddRectFilled(dl, V(x - 4.5, y + 3), V(x + 4.5, y + 5.5), ink)
  elseif name == 'castle' then
    im.ImDrawList_AddRectFilled(dl, V(x - 5, y - 2), V(x + 5, y + 5), ink)
    for i = -1, 1 do im.ImDrawList_AddRectFilled(dl, V(x + i * 4 - 1.2, y - 5), V(x + i * 4 + 1.2, y - 2), ink) end
  elseif name == 'windmill' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 3, y + 5), V(x + 3, y + 5), V(x, y - 1), ink)
    im.ImDrawList_AddLine(dl, V(x - 5, y - 6), V(x + 5, y + 2), ink, 1.5)
    im.ImDrawList_AddLine(dl, V(x + 5, y - 6), V(x - 5, y + 2), ink, 1.5)
  elseif name == 'cave' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6, y + 5), V(x + 6, y + 5), V(x, y - 5), ink)
    im.ImDrawList_AddCircleFilled(dl, V(x, y + 3.5), 2.4, fill)
  elseif name == 'rock' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 5.5, y + 4), V(x + 4, y + 4), V(x - 1.5, y - 4), ink)
    im.ImDrawList_AddTriangleFilled(dl, V(x, y + 4), V(x + 5.5, y + 4), V(x + 3, y - 1), ink)
  elseif name == 'plane' then
    im.ImDrawList_AddLine(dl, V(x, y - 6), V(x, y + 6), ink, 2)
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6, y + 1), V(x + 6, y + 1), V(x, y - 3), ink)
    im.ImDrawList_AddLine(dl, V(x - 2.5, y + 5.5), V(x + 2.5, y + 5.5), ink, 1.5)
  elseif name == 'boat' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6, y + 1), V(x + 6, y + 1), V(x + 3.5, y + 5), ink)
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6, y + 1), V(x + 3.5, y + 5), V(x - 3.5, y + 5), ink)
    im.ImDrawList_AddTriangleFilled(dl, V(x - .5, y), V(x - .5, y - 6), V(x + 4, y), ink)
  elseif name == 'lighthouse' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 3.5, y + 5.5), V(x + 3.5, y + 5.5), V(x, y - 3), ink)
    im.ImDrawList_AddRectFilled(dl, V(x - 2, y - 6), V(x + 2, y - 3), ink)
    im.ImDrawList_AddLine(dl, V(x - 6, y - 5), V(x - 3, y - 4.5), ink, 1)
    im.ImDrawList_AddLine(dl, V(x + 6, y - 5), V(x + 3, y - 4.5), ink, 1)
  elseif name == 'tower' then
    im.ImDrawList_AddRectFilled(dl, V(x - 1.5, y - 1), V(x + 1.5, y + 6), ink)
    im.ImDrawList_AddRectFilled(dl, V(x - 4.5, y - 5), V(x + 4.5, y - 1), ink, 1)
  elseif name == 'book' then
    im.ImDrawList_AddRectFilled(dl, V(x - 5.5, y - 4), V(x - .5, y + 4), ink)
    im.ImDrawList_AddRectFilled(dl, V(x + .5, y - 4), V(x + 5.5, y + 4), ink)
  elseif name == 'columns' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6, y - 3), V(x + 6, y - 3), V(x, y - 6.5), ink)
    for i = -1, 1 do im.ImDrawList_AddRectFilled(dl, V(x + i * 3.5 - 1, y - 2), V(x + i * 3.5 + 1, y + 4), ink) end
    im.ImDrawList_AddRectFilled(dl, V(x - 6, y + 4.5), V(x + 6, y + 6), ink)
  elseif name == 'pump' then
    im.ImDrawList_AddRectFilled(dl, V(x - 4.5, y - 5.5), V(x + 1.5, y + 5.5), ink, 1)
    im.ImDrawList_AddRectFilled(dl, V(x - 3.2, y - 4.2), V(x + .2, y - 1.2), fill)
    im.ImDrawList_AddLine(dl, V(x + 1.5, y - 3), V(x + 4.5, y - 1), ink, 1.5)
    im.ImDrawList_AddLine(dl, V(x + 4.5, y - 1), V(x + 4.5, y + 4), ink, 1.5)
  elseif name == 'bolt' then
    im.ImDrawList_AddTriangleFilled(dl, V(x + 2.5, y - 6.5), V(x - 4, y + 1), V(x + .5, y + 1), ink)
    im.ImDrawList_AddTriangleFilled(dl, V(x - .5, y - 1), V(x + 4, y - 1), V(x - 2.5, y + 6.5), ink)
  elseif name == 'cap' then
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6.5, y - 1.5), V(x + 6.5, y - 1.5), V(x, y - 5), ink)
    im.ImDrawList_AddTriangleFilled(dl, V(x - 6.5, y - 1.5), V(x + 6.5, y - 1.5), V(x, y + 2), ink)
    im.ImDrawList_AddRectFilled(dl, V(x - 3.5, y), V(x + 3.5, y + 4), ink, 1)
  end
end

-- the atlas of marks, loaded on its first use; false when it cannot be
local atlasTex
local function atlas()
  if atlasTex == nil then
    atlasTex = false
    if icons and M.texture then
      local ok, obj = pcall(M.texture, icons.file)
      if ok and obj and obj.texId then atlasTex = obj end
    end
  end
  return atlasTex or nil
end
M.atlas = atlas

local C, A, B, U0, U1
local function vectors(im)
  if not C then
    C, A, B = im.ImVec2(0, 0), im.ImVec2(0, 0), im.ImVec2(0, 0)
    U0, U1 = im.ImVec2(0, 0), im.ImVec2(1, 1)
  end
end

-- The badge of a point at x, y: a circle of radius r in `fill`, white-rimmed over a shadow, with
-- the mark of its category `cat` ('fuel', 'service_map/pharmacy' ...), else of its style s
-- (a STYLE entry: letters or a line drawing). Returns r.
function M.badge(im, dl, cat, s, x, y, r, fill, white, shade)
  vectors(im)
  local circle = im.ImDrawList_AddCircleFilled
  local sides = r > 9 and 24 or 16
  C.x, C.y = x, y + 1.6
  circle(dl, C, r + 2.6, shade, sides)
  C.y = y
  circle(dl, C, r + 1.8, white, sides)
  circle(dl, C, r, fill, sides)
  local mark = icons and cat and icons.category[cat]
  local cell = mark and icons.cells[mark]
  local tex = cell and atlas()
  if tex then
    local h = r * .8
    local per, rows = icons.per, icons.rows
    local cx, cy = cell % per, math.floor(cell / per)
    A.x, A.y, B.x, B.y = x - h, y - h, x + h, y + h
    U0.x, U0.y, U1.x, U1.y = cx / per, cy / rows, (cx + 1) / per, (cy + 1) / rows
    im.ImDrawList_AddImage(dl, tex.texId, A, B, U0, U1, white)
  elseif s and s.text and #s.text <= 2 then
    local w = widths[s.text]
    if not w then w = im.CalcTextSize(s.text).x; widths[s.text] = w end
    im.ImDrawList_AddText1(dl, im.ImVec2(x - w / 2, y - 7), white, s.text)
  elseif s and s.text then
    -- letters wider than the badge: the first one
    local t = s.text:sub(1, 1)
    local w = widths[t]
    if not w then w = im.CalcTextSize(t).x; widths[t] = w end
    im.ImDrawList_AddText1(dl, im.ImVec2(x - w / 2, y - 7), white, t)
  elseif s and s.shape then
    shape(im, dl, s.shape, x, y, white, fill, r / 10)
  end
  return r
end

-- a point too minor for a badge: a dot of radius r in `fill`, ringed white over a shadow
function M.dot(im, dl, x, y, r, fill, white, shade)
  vectors(im)
  local circle = im.ImDrawList_AddCircleFilled
  C.x, C.y = x, y + 1
  circle(dl, C, r + 2, shade, 12)
  C.y = y
  circle(dl, C, r + 1.4, white, 12)
  circle(dl, C, r, fill, 12)
end

-- tiles: the streamed tiles (each with .brandPOIs); toGeo(x, y) -> lat, lon; screen(lat, lon) -> px;
-- col(r, g, b, a) an ImGui colour; brands: generator BRANDS (key -> {cell, name, rgb})
local function pinOrder(a, b)
  if a.lat ~= b.lat then return a.lat > b.lat end
  if a.lon ~= b.lon then return a.lon < b.lon end
  if a.kind ~= b.kind then return a.kind < b.kind end
  if a.cat ~= b.cat then return (a.cat or '') < (b.cat or '') end
  if a.brand ~= b.brand then return (a.brand or '') < (b.brand or '') end
  return (a.label or '') < (b.label or '')
end

function M.draw(im, dl, tiles, z, box, toGeo, screen, col, brands, layout, accepts)
  local north, south, east, west = box.n, box.s, box.e, box.w
  for k = 1, LEVELS do counts[k] = 0 end
  for _, tile in pairs(tiles) do
    local list = tile.brandPOIs
    if list then
      for i = 1, #list do
        local poi = list[i]
        if poi.lat == nil then
          poi.lat, poi.lon = toGeo(poi.x, poi.y)
          if poi.lat == nil then poi.lat = false end
        end
        local lat, lon = poi.lat, poi.lon
        if lat and lat <= north and lat >= south and lon >= west and lon <= east
          and (not accepts or accepts(poi)) then
          local level
          if poi.kind == 'pin' then
            local s = STYLE[poi.cat]
            level = s and z >= s.zoom and s.priority or nil
          elseif z >= 15 then
            level = poi.brand and 1 or 7
          end
          if level then
            local n = counts[level] + 1
            counts[level], buckets[level][n] = n, poi
          end
        end
      end
    end
  end
  for key in pairs(occupied) do occupied[key] = nil end
  local drawn, white, dark, shade = 0, col(1, 1, 1), col(0.12, 0.12, 0.12), col(0, 0, 0, .30)
  local ox, oy = screen(0, 0)
  local function labelAt(x, y, text)
    local w = widths[text]
    if not w then w = im.CalcTextSize(text).x; widths[text] = w end
    if not layout or layout.place(x - 2, y - 9, x + w + 3, y + 9) then
      im.ImDrawList_AddRectFilled(dl, im.ImVec2(x - 2, y - 8), im.ImVec2(x + w + 2, y + 8), col(1, 1, 1, .9), 3)
      im.ImDrawList_AddText1(dl, im.ImVec2(x, y - 7), dark, text)
    end
  end
  for level = 1, LEVELS do
    local bucket = buckets[level]
    for i = #bucket, counts[level] + 1, -1 do bucket[i] = nil end
    table.sort(bucket, pinOrder)
    for i = 1, counts[level] do
      if drawn >= MAX then return end
      local poi = bucket[i]
      local x, y = screen(poi.lat, poi.lon)
      local key = math.floor((x - ox) / CELL) * 4194304 + math.floor((y - oy) / CELL)
      local s = poi.kind == 'pin' and STYLE[poi.cat]
      local half = 12
      if not occupied[key] and (not layout or layout.place(x - half, y - half, x + half, y + half)) then
        occupied[key], drawn = true, drawn + 1
        local brand = poi.brand and brands[poi.brand]
        if s then
          local g = GROUP[s.group]
          local rgb = brand and brand[3]
          local fill = rgb and col(rgb[1] / 255, rgb[2] / 255, rgb[3] / 255) or col(g[1], g[2], g[3])
          M.badge(im, dl, poi.mapCategory or poi.cat, s, x, y, 10, fill, white, shade)
          local label = poi.label
          if s.group == 'nature' and poi.ele then label = label and (label .. ' ' .. poi.ele) or poi.ele end
          if label and z >= (s.labelZoom or 17) then
            labelAt(x + math.max(half + 5, 13), y, label)
          end
        else
          local rgb = poi.rgb or (brand and brand[3])
          local c = rgb and col(rgb[1] / 255, rgb[2] / 255, rgb[3] / 255)
            or (poi.kind == 'fuel' and col(0.10, 0.43, 0.70) or col(0.16, 0.55, 0.27))
          M.badge(im, dl, poi.kind == 'fuel' and 'fuel' or 'shop', nil, x, y, 9, c, white, shade)
          if z >= 17 and (poi.brand or poi.label) then
            labelAt(x + 13, y, poi.label or (brand and brand[2] or poi.brand))
          end
        end
      end
    end
  end
end

return M
