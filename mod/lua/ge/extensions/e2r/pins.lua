-- Points of interest on the map (docs/POI.md, wave 1): the look of each 'pin' category
-- (fast_style.PIN_RULES, OSM tags, so every country's pack has them) and of the networks' points,
-- and drawing them on the minimap and the big map. Icons read without a language: pictograms and
-- the international letters P, WC, H, ATM. A tile hands its small records over in manifest.brandPOIs (generator.lua SPLIT.out): a
-- network's point {kind = 'fuel' ...} or a pin {kind = 'pin', cat = ...}. A category not in STYLE
-- is skipped, so a pack from a newer builder never breaks the map.
--
-- Every frame: no tables are made. The candidates go into reused buckets by priority, a record
-- keeps its geographic position after its first frame, and glyph widths are measured once.

local M = {}

-- colours of the groups (r, g, b): blue for the driver's services as on road signs, brown for
-- sights as on tourist signs
local GROUP = {
  car = {0.16, 0.38, 0.78}, stay = {0.52, 0.24, 0.56}, money = {0.08, 0.50, 0.30},
  shop = {0.86, 0.44, 0.10}, water = {0.12, 0.56, 0.86}, sight = {0.55, 0.34, 0.18},
  nature = {0.34, 0.44, 0.22}, transport = {0.80, 0.16, 0.22},
}

-- category: group, glyph (text) or shape, zoom it shows from, priority (1 first when crowded),
-- labelZoom: its name from that zoom (default 17)
local STYLE = {
  parking = {group = 'car', text = 'P', zoom = 16, priority = 5},
  car_dealer = {group = 'car', shape = 'car', zoom = 15, priority = 4},
  car_parts = {group = 'car', shape = 'wrench', zoom = 16, priority = 6},
  rest_area = {group = 'car', shape = 'table', zoom = 14, priority = 3, labelZoom = 15},
  toilets = {group = 'car', text = 'WC', zoom = 16, priority = 6},
  hotel = {group = 'stay', text = 'H', zoom = 15, priority = 3},
  motel = {group = 'stay', text = 'H', zoom = 14, priority = 3, labelZoom = 15},
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
}
M.STYLE, M.GROUP = STYLE, GROUP
-- a far tile hands over only the pins seen from afar (generator.lua SPLIT.out)
M.FAR = {peak = true, pass = true, viewpoint = true}

local LEVELS = 8
local MAX = 120          -- markers drawn at most
local CELL = 20          -- px: one marker per CELL x CELL square
local buckets, counts = {}, {}
for k = 1, LEVELS do buckets[k], counts[k] = {}, 0 end
local occupied = {}
local widths = {}

-- the style of a record, nil to skip it; networks' points keep their old look (priority 1)
function M.style(poi)
  if poi.kind == 'pin' then return STYLE[poi.cat] end
  return nil
end

-- draw the shape `name` centred at x, y, r px across, in ink
local function shape(im, dl, name, x, y, ink)
  local V = im.ImVec2
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
  end
end

local function textWidth(im, text)
  local w = widths[text]
  if not w then
    w = im.CalcTextSize(text).x
    widths[text] = w
  end
  return w
end

-- tiles: the streamed tiles (each with .brandPOIs); toGeo(x, y) -> lat, lon; screen(lat, lon) -> px;
-- col(r, g, b, a) an ImGui colour; brands: generator BRANDS (key -> {cell, name, rgb})
function M.draw(im, dl, tiles, z, box, toGeo, screen, col, brands)
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
        if lat and lat <= north and lat >= south and lon >= west and lon <= east then
          local level
          if poi.kind == 'pin' then
            local s = STYLE[poi.cat]
            level = s and z >= s.zoom and s.priority or nil
          elseif z >= 15 then
            level = 1
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
  local drawn, white, dark = 0, col(1, 1, 1), col(0.12, 0.12, 0.12)
  for level = 1, LEVELS do
    local bucket = buckets[level]
    for i = 1, counts[level] do
      if drawn >= MAX then return end
      local poi = bucket[i]
      local x, y = screen(poi.lat, poi.lon)
      local key = math.floor(x / CELL) * 65536 + math.floor(y / CELL)
      if not occupied[key] then
        occupied[key], drawn = true, drawn + 1
        local s = poi.kind == 'pin' and STYLE[poi.cat]
        local brand = poi.brand and brands[poi.brand]
        if s then
          local g = GROUP[s.group]
          local rgb = brand and brand[3]
          local fill = rgb and col(rgb[1] / 255, rgb[2] / 255, rgb[3] / 255) or col(g[1], g[2], g[3])
          local half = s.text and math.max(7, textWidth(im, s.text) / 2 + 3) or 7
          im.ImDrawList_AddRectFilled(dl, im.ImVec2(x - half - 1.5, y - 8.5), im.ImVec2(x + half + 1.5, y + 8.5), white, 5)
          im.ImDrawList_AddRectFilled(dl, im.ImVec2(x - half, y - 7), im.ImVec2(x + half, y + 7), fill, 4)
          if s.text then
            im.ImDrawList_AddText1(dl, im.ImVec2(x - textWidth(im, s.text) / 2, y - 7), white, s.text)
          else
            shape(im, dl, s.shape, x, y, white)
          end
          local label = poi.label
          if s.group == 'nature' and poi.ele then label = label and (label .. ' ' .. poi.ele) or poi.ele end
          if label and z >= (s.labelZoom or 17) then
            im.ImDrawList_AddText1(dl, im.ImVec2(x + half + 4, y - 7), dark, label)
          end
        else
          local rgb = poi.rgb or (brand and brand[3])
          local c = rgb and col(rgb[1] / 255, rgb[2] / 255, rgb[3] / 255)
            or (poi.kind == 'fuel' and col(0.10, 0.43, 0.70) or col(0.16, 0.55, 0.27))
          im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y), 7, white)
          im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y), 5.5, c)
          if z >= 17 and (poi.brand or poi.label) then
            im.ImDrawList_AddText1(dl, im.ImVec2(x + 8, y - 7), dark, poi.label or (brand and brand[2] or poi.brand))
          end
        end
      end
    end
  end
end

return M
