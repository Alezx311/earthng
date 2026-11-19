-- Heading and nearby named landmarks, sharing the world map's sliced POI index.
local M = {}
local index = require('ge/extensions/e2r/poiindex')
local RADIUS = 5000
local IMPORTANT = {castle=true, monument=true, lighthouse=true, station=true, ferry=true,
  mall=true, hospital=true, sight=true, ['sight/museum']=true, ['sight/attraction']=true,
  ['sight/building']=true, ['leisure_map/stadium']=true, ['leisure_map/theatre']=true}
local candidates, query, nextQuery, revision, queryLat, queryLon = {}, nil, 0, -1
local enabled, look = {}, nil
local rad, deg = math.rad, math.deg
local CARDINAL = {en={'N','NE','E','SE','S','SW','W','NW'}, uk={'Пн','ПнСх','Сх','ПдСх','Пд','ПдЗх','Зх','ПнЗх'}}

function M.bearing(lat, lon, targetLat, targetLon)
  local a, b, delta = rad(lat), rad(targetLat), rad(targetLon-lon)
  return (deg(math.atan2(math.sin(delta)*math.cos(b),
    math.cos(a)*math.sin(b)-math.sin(a)*math.cos(b)*math.cos(delta)))+360)%360
end

function M.distance(lat, lon, targetLat, targetLon)
  local a = math.sin(rad(targetLat-lat)/2)^2 + math.cos(rad(lat))*math.cos(rad(targetLat))*math.sin(rad(targetLon-lon)/2)^2
  return 12742017.6*math.asin(math.sqrt(math.min(1, a)))
end

function M.offset(bearing, heading) return (bearing-heading+180)%360-180 end

local function distanceText(m, en)
  return m >= 1000 and string.format(en and '%.1f km' or '%.1f км', m/1000)
    or string.format(en and '%d m' or '%d м', math.floor(m+.5))
end

function M.step(now, lat, lon, lang, tiles, toGeo)
  index.step()
  if revision ~= index.revision or not queryLat or M.distance(lat, lon, queryLat, queryLon)>250 or now>=nextQuery then
    if not query then
      revision, queryLat, queryLon, nextQuery = index.revision, lat, lon, now+2
      for id, cat in ipairs(index.CATS) do enabled[id] = IMPORTANT[cat] == true end
      query = coroutine.create(function()
        local found, seen = {}, {}
        local started = os.clock()
        local function pause()
          if os.clock()-started>.001 then coroutine.yield(); started=os.clock() end
        end
        local function add(e, i, priority)
          local a, b = index.position(e, i)
          local d = M.distance(lat, lon, a, b)
          if d<=RADIUS then found[#found+1]={e=e, i=i, lat=a, lon=b, distance=d, priority=priority} end
          pause()
        end
        local dy, dx = RADIUS/111320, RADIUS/111320/math.max(.01, math.cos(rad(lat)))
        local west, east = lon-dx, lon+dx
        index.collect(west, lat-dy, east, lat+dy, 64, enabled, add, pause)
        if west < -180 then index.collect(west+360, lat-dy, 180, lat+dy, 64, enabled, add, pause) end
        if east > 180 then index.collect(-180, lat-dy, east-360, lat+dy, 64, enabled, add, pause) end
        -- Older packs can still supply landmarks through their loaded map pins.
        for _, tile in pairs(tiles or {}) do
          for _, p in ipairs(tile.brandPOIs or {}) do
            if IMPORTANT[p.cat] and p.label and toGeo then
              local a, b = toGeo(p.x, p.y)
              if a then
                local d = M.distance(lat, lon, a, b)
                if d<=RADIUS then
                  found[#found+1]={lat=a, lon=b, distance=d, priority=4, name=p.label}
                end
              end
            end
            pause()
          end
        end
        table.sort(found, function(a,b) return a.priority<b.priority or a.priority==b.priority and a.distance<b.distance end)
        local kept = {}
        for _, p in ipairs(found) do
          local name = p.name or index.name(p.e, p.i, lang)
          local key = name..':'..string.format('%.4f,%.4f',p.lat,p.lon)
          if name~='' and not seen[key] then
            seen[key]=true; p.name=name; kept[#kept+1]=p
            if #kept>=16 then break end
          end
        end
        candidates=kept
      end)
    end
  end
  if query then
    local ok = coroutine.resume(query)
    if not ok or coroutine.status(query)=='dead' then query=nil end
  end
end

function M.clear()
  candidates, query, queryLat, nextQuery = {}, nil, nil, 0
end

function M.draw(im, lat, lon, heading, marker, lang)
  local view = im.GetMainViewport()
  if not view or not lat or not heading then return 0 end
  if not look then
    look={a=im.ImVec2(0,0),b=im.ImVec2(0,0),c=im.ImVec2(0,0),pos=im.ImVec2(0,0),size=im.ImVec2(0,0),pivot=im.ImVec2(.5,0),
      white=im.GetColorU322(im.ImVec4(.93,.95,1,1)),muted=im.GetColorU322(im.ImVec4(.6,.67,.75,1)),
      gold=im.GetColorU322(im.ImVec4(1,.76,.25,1)),blue=im.GetColorU322(im.ImVec4(.52,.79,1,1)),
      background=im.ImVec4(0,0,0,0),
      panel=im.GetColorU322(im.ImVec4(.035,.055,.075,.62)),
      edge=im.GetColorU322(im.ImVec4(.65,.8,.9,.15)),
      fade=im.GetColorU322(im.ImVec4(.6,.67,.75,.35)),
      glow=im.GetColorU322(im.ImVec4(1,.73,.23,.07)),
      shadow=im.GetColorU322(im.ImVec4(0,0,0,.17)),
      flags=im.WindowFlags_NoDecoration+im.WindowFlags_NoInputs+im.WindowFlags_NoNav+im.WindowFlags_NoSavedSettings
        +im.WindowFlags_NoFocusOnAppearing+im.WindowFlags_NoBringToFrontOnFocus+im.WindowFlags_NoDocking}
    look.gradient = {}
    for band=1,12 do
      look.gradient[band]=im.GetColorU322(im.ImVec4(.12,.2,.28,.12*(1-band/13)))
    end
  end
  local v, en = look, lang=='en'
  local width = math.max(180, math.min(960, view.Size.x-32))
  local height = im.GetTextLineHeight()
  local total = height*3.7+20
  v.pos.x,v.pos.y = view.Pos.x+view.Size.x/2,view.Pos.y+8
  v.size.x,v.size.y = width,total
  im.SetNextWindowPos(v.pos,im.Cond_Always,v.pivot)
  im.SetNextWindowSize(v.size,im.Cond_Always)
  im.PushStyleColor2(im.Col_WindowBg,v.background)
  im.PushStyleVar1(im.StyleVar_WindowBorderSize,0)
  im.Begin('EarthNG##compass',nil,v.flags)
  local at, dl = im.GetCursorScreenPos(),im.GetWindowDrawList()
  local left, right, top = at.x+4,at.x+width-24,at.y
  local center, half = (left+right)/2,(right-left)/2
  local function rect(x,y,x1,y1,color,radius)
    v.a.x,v.a.y,v.b.x,v.b.y=x,y,x1,y1
    im.ImDrawList_AddRectFilled(dl,v.a,v.b,color,radius or 0)
  end
  local function line(x,y,x1,y1,color)
    v.a.x,v.a.y,v.b.x,v.b.y=x,y,x1,y1
    im.ImDrawList_AddLine(dl,v.a,v.b,color,1)
  end
  local function text(x,y,label,color)
    local w=im.CalcTextSize(label).x
    v.a.x,v.a.y=math.max(left,math.min(right-w,x-w/2)),y
    im.ImDrawList_AddText1(dl,v.a,color,label)
    return w
  end
  rect(left-4,top+2,right+4,top+total-12,v.shadow,8)
  rect(left-4,top-5,right+4,top+total-16,v.panel,8)
  for band,color in ipairs(v.gradient) do
    local y=top-3+(band-1)*(total-15)/12
    rect(left, y, right, y+(total-15)/12, color)
  end
  for band=3,1,-1 do
    rect(center-band*15,top-3,center+band*15,top+height*1.8,v.glow,5)
  end
  line(left+8,top-4,right-8,top-4,v.edge)
  line(left,top+height*1.35,right,top+height*1.35,v.fade)
  local names = en and CARDINAL.en or CARDINAL.uk
  for angle=0,345,15 do
    local offset=M.offset(angle,heading)
    if math.abs(offset)<=90 then
      local x=center+offset/90*half
      local color = math.abs(offset)>65 and v.fade or v.muted
      line(x,top+height, x,top+height*1.35,color)
      if angle%45==0 then text(x,top-2,names[angle/45+1],math.abs(offset)>65 and v.muted or v.white) end
    end
  end
  v.a.x,v.a.y,v.b.x,v.b.y,v.c.x,v.c.y=center-4,top+height*1.45,center+4,top+height*1.45,center,top+height*1.1
  im.ImDrawList_AddTriangleFilled(dl,v.a,v.b,v.c,v.gold)
  if marker and marker.lat and marker.lon then
    local offset=M.offset(M.bearing(lat,lon,marker.lat,marker.lon),heading)
    local x=center+math.max(-90,math.min(90,offset))/90*half
    local label=(offset < -90 and '< ' or offset > 90 and '> ' or '')
      ..(en and 'Marker ' or 'Мітка ')..distanceText(M.distance(lat,lon,marker.lat,marker.lon),en)
    text(x,top+height*1.65,label,v.gold)
    rect(x-3,top+height*1.2,x+3,top+height*1.5,v.glow,2)
    line(x,top+height*1.35,x,top+height*1.6,v.gold)
  end
  local occupied = {}
  for _, p in ipairs(candidates) do
    local d=M.distance(lat,lon,p.lat,p.lon)
    local offset=M.offset(M.bearing(lat,lon,p.lat,p.lon),heading)
    if d<=RADIUS and math.abs(offset)<=90 then
      local x=center+offset/90*half
      line(x,top+height*1.35,x,top+height*1.5,v.blue)
      local name=p.name
      -- Fit UTF-8 labels by removing whole characters.
      while #name>0 and im.CalcTextSize(name).x>math.min(170,width/3) do name=name:gsub('[%z\1-\127\194-\244][\128-\191]*$','') end
      local label=name..'  '..distanceText(d,en)
      local w=im.CalcTextSize(label).x+14
      local a=math.max(left,math.min(right-w,x-w/2))
      local free=true
      for _, span in ipairs(occupied) do if a<span[2] and a+w>span[1] then free=false; break end end
      if free then
        occupied[#occupied+1]={a,a+w}
        text(a+w/2,top+height*2.8,label,v.white)
      end
    end
  end
  im.End()
  im.PopStyleVar(1)
  im.PopStyleColor(1)
  return total+8
end

return M
