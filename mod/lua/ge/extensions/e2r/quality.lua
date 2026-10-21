-- Shared, deterministic quality policy. No engine graphics settings are changed.
local M = {}
local anchors = {
  {nearM=800, farM=1400, maxTrees=700, maxFarTrees=120, maxGrass=2600, maxRocks=70,
    forestSpacing=8, groundSpacing=12, grassM=45, rockM=220, grassBudget=600, rockBudget=250},
  {nearM=1000, farM=2400, maxTrees=1800, maxFarTrees=400, maxGrass=4000, maxRocks=120,
    forestSpacing=6, groundSpacing=8, grassM=100, rockM=500, grassBudget=2000, rockBudget=700},
  {nearM=1400, farM=4000, maxTrees=2400, maxFarTrees=800, maxGrass=4800, maxRocks=200,
    forestSpacing=5, groundSpacing=6, grassM=220, rockM=900, grassBudget=6000, rockBudget=1600},
}
local function number(v, default, lo, hi)
  v = tonumber(v)
  if not v or v ~= v or v == math.huge or v == -math.huge then v = default end
  return math.floor(math.max(lo, math.min(hi, v)) + .5)
end
M.number = number
function M.preset(detail, distance)
  detail, distance = number(detail, 50, 0, 100), number(distance, detail, 0, 100)
  -- parkedCars: the game's parked cars kept round the player (parking.lua); 0 draws the box cars
  local out = {quality=detail, detail=detail, distance=distance, groundTrees=true, parkedCars=8}
  for key in pairs(anchors[1]) do
    local q = (key == 'nearM' or key == 'farM' or key == 'grassM' or key == 'rockM') and distance or detail
    local a = q < 50 and 1 or 2
    local f = (q - (a - 1) * 50) / 50
    out[key] = math.floor(anchors[a][key] + (anchors[a+1][key] - anchors[a][key]) * f + .5)
  end
  return out
end
function M.clamp(tune)
  local t, out = type(tune) == 'table' and tune or {}, M.preset(50)
  local limits = {nearM={400,4000}, farM={800,8000}, maxTrees={0,2400}, maxFarTrees={0,1200},
    maxGrass={0,4800}, maxRocks={0,200}, forestSpacing={4,24}, groundSpacing={4,30},
    grassM={0,220}, rockM={0,900}, grassBudget={0,6000}, rockBudget={0,1600},
    quality={0,100}, detail={0,100}, distance={0,100}, parkedCars={0,24}}
  for key, range in pairs(limits) do out[key] = number(t[key], out[key], range[1], range[2]) end
  out.groundTrees = t.groundTrees ~= false and t.groundTrees ~= 0
  out.farM = math.max(out.nearM, out.farM)
  out.maxFarTrees = math.min(out.maxTrees, out.maxFarTrees)
  return out
end
function M.name(q)
  if q <= 15 then return 'Potato' elseif q < 40 then return 'Low' elseif q < 65 then return 'Balanced'
  elseif q < 90 then return 'High' else return 'OASIS' end
end
return M
