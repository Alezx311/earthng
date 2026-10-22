-- Country archives are discovered through BeamNG's mounted virtual filesystem. Archive
-- filenames and the user's real mods directory deliberately play no part in this catalog.
local M = {}
local ROOT = '/earthng/countries/'
local catalog, issues, landingCoverage = {}, {}, {}

local function finite(n)
  return type(n) == 'number' and n == n and n ~= math.huge and n ~= -math.huge
end

local function text(value)
  return type(value) == 'string' and value:find('%S') ~= nil and not value:find('[%z\1-\31]')
end

local function slug(value)
  return type(value) == 'string' and #value > 0 and not value:find('[^a-z0-9%-]')
    and not value:find('^%-') and not value:find('%-$')
end

-- JSON arrays must be dense: ipairs alone would silently accept an invalid suffix or holes.
local function array(value)
  if type(value) ~= 'table' then return false end
  local count = 0
  for key in pairs(value) do
    if type(key) ~= 'number' or key < 1 or key % 1 ~= 0 then return false end
    count = count + 1
  end
  return count == #value
end

local function boxes(value)
  if not array(value) or #value == 0 then return nil, 'coverage must be a nonempty array of boxes' end
  local result = {}
  for _, box in ipairs(value) do
    if not array(box) or #box ~= 4 then return nil, 'coverage boxes must be [west, south, east, north]' end
    local w, s, e, n = box[1], box[2], box[3], box[4]
    if not (finite(w) and finite(s) and finite(e) and finite(n))
      or w < -180 or w > 180 or e < -180 or e > 180
      or s < -90 or n > 90 or s >= n or w == e or (w == 180 and e == -180) then
      return nil, 'coverage box coordinates must be finite and within longitude/latitude bounds'
    end
    result[#result + 1] = {w, s, e, n}
  end
  return result
end

local function contains(box, lat, lon)
  return lat >= box[2] and lat <= box[4]
    and ((box[1] < box[3] and lon >= box[1] and lon <= box[3])
      or (box[1] > box[3] and (lon >= box[1] or lon <= box[3])))
end

local function containsAny(coverage, lat, lon)
  for _, box in ipairs(coverage) do if contains(box, lat, lon) then return true end end
  return false
end

-- Keep all runtime entrypoints inside their country's namespace. Reject ambiguous paths
-- rather than canonicalizing '..', backslashes, URLs or repeated separators.
local function pathIn(value, namespace)
  if not text(value) or value:find('[\\:%?%#%%]') or value:find('//', 1, true)
    or value:sub(-1) == '/' then return nil end
  local path = value:sub(1, 1) == '/' and value or namespace .. value
  if path:sub(1, #namespace) ~= namespace then return nil end
  for part in path:gmatch('[^/]+') do
    if part == '.' or part == '..' then return nil end
  end
  return path
end

local function exists(path)
  local ok, found = pcall(function() return FS:fileExists(path) end)
  return ok and found == true
end

local function addIssue(path, code, message, id)
  issues[#issues + 1] = {path = path, code = code, message = message, id = id}
end

local function copy(value)
  local result = {}
  for key, entry in pairs(value) do result[key] = entry end
  return result
end

local function validate(manifest, path)
  if type(manifest) ~= 'table' then return nil, 'manifest must be a JSON object' end
  if manifest.schemaVersion ~= 1 then return nil, 'unsupported schemaVersion (expected 1)' end
  if manifest.kind ~= 'earthng-country' then return nil, 'kind must be earthng-country' end
  if not slug(manifest.id) then return nil, 'id must be a lowercase slug' end
  local namespace = ROOT .. manifest.id .. '/'
  if path ~= namespace .. 'manifest.json' then return nil, 'manifest location must match its country id' end
  if not text(manifest.title) or not text(manifest.version) then return nil, 'title and version must be nonempty strings' end
  if manifest.runtime ~= 'native' and manifest.runtime ~= 'baked' and manifest.runtime ~= 'source' then
    return nil, 'runtime must be native, baked or source'
  end
  local coverage, message = boxes(manifest.coverage)
  if not coverage then return nil, message end
  if manifest.regions ~= nil and not array(manifest.regions) then return nil, 'regions must be an array' end
  local regions, ids = {}, {}
  for _, region in ipairs(manifest.regions or {}) do
    if type(region) ~= 'table' or not slug(region.id) then return nil, 'each region must have a lowercase slug id' end
    if ids[region.id] then return nil, 'duplicate region id: ' .. region.id end
    ids[region.id] = true
    local regionPath = pathIn(region.manifest, namespace)
    if not regionPath or regionPath:sub(-5) ~= '.json' then return nil, 'region manifest must be a JSON path inside its country namespace' end
    if not exists(regionPath) then return nil, 'missing mounted region manifest: ' .. regionPath end
    local regionCoverage, regionError = boxes(region.coverage)
    if not regionCoverage then return nil, 'region ' .. region.id .. ': ' .. regionError end
    local entry = copy(region)
    entry.manifest, entry.coverage = regionPath, regionCoverage
    regions[#regions + 1] = entry
  end
  -- sections first: a rebuilt county answers landings over the whole-country regions
  table.sort(regions, function(a, b)
    if (a.section == true) ~= (b.section == true) then return a.section == true end
    return a.id < b.id
  end)
  if manifest.runtime ~= 'source' and #regions == 0 then return nil, 'playable countries require at least one region' end
  local entry = copy(manifest)
  if manifest.entrypoint ~= nil then
    entry.entrypoint = pathIn(manifest.entrypoint, namespace)
    if not entry.entrypoint or not exists(entry.entrypoint) then return nil, 'entrypoint must be a mounted file inside its country namespace' end
  end
  entry.manifest, entry.namespace, entry.coverage, entry.regions = path, namespace, coverage, regions
  entry.available = manifest.runtime ~= 'source'
  if not entry.available then entry.reason = 'source-only' end
  return entry
end

local function appendCoverage(box)
  -- Split dateline boxes for consumers which draw ordinary west-to-east rectangles.
  if box[1] > box[3] then
    if box[1] < 180 then landingCoverage[#landingCoverage + 1] = {box[1], box[2], 180, box[4]} end
    if box[3] > -180 then landingCoverage[#landingCoverage + 1] = {-180, box[2], box[3], box[4]} end
  else
    landingCoverage[#landingCoverage + 1] = {box[1], box[2], box[3], box[4]}
  end
end

-- Mounted files named name whose paths match pattern, each once; a path mounted twice (two
-- archives with the same file) is reported and dropped.
local function mountedFiles(name, pattern)
  local ok, paths = pcall(function() return FS:findFiles(ROOT, name, -1, true, false) end)
  if not ok or type(paths) ~= 'table' then return nil end
  local sorted, repeated = {}, {}
  for _, path in ipairs(paths) do
    if type(path) == 'string' and path:match(pattern) then
      if repeated[path] ~= nil then repeated[path] = true else repeated[path] = false; sorted[#sorted + 1] = path end
    end
  end
  table.sort(sorted)
  local unique = {}
  for _, path in ipairs(sorted) do
    if repeated[path] then
      addIssue(path, 'duplicate', 'multiple mounted manifests resolve to the same country path')
    else
      unique[#unique + 1] = path
    end
  end
  return unique
end

-- A country built in sections (one zip per county while it is improved) mounts
-- sections/<id>/section.json files: each one region of the country with the country's own
-- fields. They join the country's manifest.json when one is mounted, else they make the country.
local function sectionsOf()
  local bySlug, order = {}, {}
  for _, path in ipairs(mountedFiles('section.json', '^/earthng/countries/[^/]+/sections/[^/]+/section%.json$') or {}) do
    local country, id = path:match('^/earthng/countries/([^/]+)/sections/([^/]+)/section%.json$')
    local readOk, section = pcall(jsonReadFile, path)
    if not readOk or type(section) ~= 'table' then
      addIssue(path, 'json', 'section manifest cannot be read as JSON', country)
    elseif section.kind ~= 'earthng-section' or section.country ~= country or section.id ~= id
      or type(section.region) ~= 'table' then
      addIssue(path, 'invalid', 'section must be kind earthng-section with its country, id and region', country)
    else
      if not bySlug[country] then bySlug[country] = {}; order[#order + 1] = country end
      local list = bySlug[country]
      list[#list + 1] = section
    end
  end
  return bySlug, order
end

local function withSections(manifest, list)
  local merged = copy(manifest)
  merged.regions, merged.coverage = {}, {}
  for _, region in ipairs(manifest.regions or {}) do merged.regions[#merged.regions + 1] = region end
  for _, box in ipairs(manifest.coverage or {}) do merged.coverage[#merged.coverage + 1] = box end
  for _, section in ipairs(list) do
    local region = copy(section.region)
    region.section = true
    merged.regions[#merged.regions + 1] = region
    for _, box in ipairs(type(section.coverage) == 'table' and section.coverage or {}) do
      merged.coverage[#merged.coverage + 1] = box
    end
  end
  return merged
end

local function fromSections(list)
  -- The country's fields from its first section (by id) which names a landing, else its first.
  local first = list[1]
  for _, section in ipairs(list) do
    if type(section.landing) == 'table' then first = section; break end
  end
  local manifest = copy(first)
  manifest.kind, manifest.id, manifest.regions = 'earthng-country', first.country, nil
  manifest.country, manifest.region, manifest.sectionTitle = nil, nil, nil
  manifest.coverage = nil
  return withSections(manifest, list)
end

local function scan()
  catalog, issues, landingCoverage = {}, {}, {}
  -- Region directories may also contain manifest.json; only direct country manifests
  -- define packages, and no path outside ROOT may enter through a faulty FS response.
  local sorted = mountedFiles('manifest.json', '^/earthng/countries/[^/]+/manifest%.json$')
  if not sorted then
    addIssue(ROOT, 'discovery', 'mounted country discovery failed')
    return catalog, issues
  end
  local sections, sectionOrder = sectionsOf()
  local mounted = {}
  for _, path in ipairs(sorted) do mounted[path] = true end
  for _, country in ipairs(sectionOrder) do
    table.sort(sections[country], function(a, b) return a.id < b.id end)
    local path = ROOT .. country .. '/manifest.json'
    if not mounted[path] then sorted[#sorted + 1] = path end
  end
  table.sort(sorted)
  local ids, conflicted = {}, {}
  for _, path in ipairs(sorted) do
    do
      local country = path:match('^/earthng/countries/([^/]+)/manifest%.json$')
      local list = sections[country]
      local readOk, manifest
      if list and not mounted[path] then
        readOk, manifest = true, fromSections(list)
      else
        readOk, manifest = pcall(jsonReadFile, path)
        if readOk and type(manifest) == 'table' and list then manifest = withSections(manifest, list) end
      end
      if not readOk or type(manifest) ~= 'table' then
        addIssue(path, 'json', 'country manifest cannot be read as JSON')
      else
        local entry, message = validate(manifest, path)
        if not entry then
          addIssue(path, 'invalid', message, type(manifest.id) == 'string' and manifest.id or nil)
        elseif ids[entry.id] then
          conflicted[entry.id] = true
          addIssue(path, 'duplicate', 'duplicate country id: ' .. entry.id, entry.id)
        else
          ids[entry.id] = entry
          catalog[#catalog + 1] = entry
        end
      end
    end
  end
  local accepted = {}
  for _, country in ipairs(catalog) do
    if not conflicted[country.id] then
      accepted[#accepted + 1] = country
      if country.available then
        for _, region in ipairs(country.regions) do
          for _, box in ipairs(region.coverage) do appendCoverage(box) end
        end
      end
    end
  end
  catalog = accepted
  table.sort(catalog, function(a, b) return a.id < b.id end)
  return catalog, issues
end

-- Country and region order is stable across mount order. Overlapping ready regions
-- resolve by country id, then region id, so a click never changes meaning at random.
local function at(lat, lon)
  if not finite(lat) or not finite(lon) or lat < -90 or lat > 90 or lon < -180 or lon > 180 then return nil end
  for _, country in ipairs(catalog) do
    if country.available and containsAny(country.coverage, lat, lon) then
      for _, region in ipairs(country.regions) do
        if containsAny(region.coverage, lat, lon) then return country, region end
      end
    end
  end
  return nil
end

M.scan = scan
M.refresh = scan
M.countries = function() return catalog end
M.errors = function() return issues end
M.coverage = function() return landingCoverage end
M.at = at
return M
