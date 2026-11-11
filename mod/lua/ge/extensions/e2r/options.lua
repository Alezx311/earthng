-- One registry of the player's settings for two views: the ImGui widget (world.lua) and the
-- game's own UI app (ui/modules/apps/EarthNG, docs/INGAME_UI.md). Pure Lua: nothing here calls
-- the engine at load, so lupa tests run it as is (earthng/test_options.py).
--
-- An option is a value with a kind (bool, int, float, enum), a range, a group and labels in both
-- languages. `read` returns the live value from where the game keeps it, `apply` changes it there;
-- an option without `read` keeps its value here. `path` names its place in settings/earthng.json
-- when the registry saves it; options whose owner already saves them (the language, the world
-- quality) leave `path` out. A change from anywhere (set, touch, or a value that moved under
-- poll) reaches every onChange listener; the UI bridge pushes the list to the page from there.
local M = {REGISTRY = true}

local KINDS = {bool = true, int = true, float = true, enum = true}
local specs, order = {}, {}            -- key -> spec; keys in definition order
local groups, groupOrder = {}, {}      -- key -> {key, label, collapsed}; keys in order
local stored = {}                      -- values of options without read()
local seen = {}                        -- what listeners last heard, for poll()
local seenWatch = {}                   -- the same for each option's watch() (its note's numbers)
local notes = {}                       -- key -> {watch, lang, text}: noteText's cache
local listeners, listenerNames = {}, {}
local busy = false                     -- inside an apply: touch() from the owner's code is ours
local pollAt = -math.huge
M.POLL_EVERY = 0.25                    -- s between poll() looks at the live values
M.dirty = false
-- {read = function() return cfg end, write = function(cfg) end}; world.lua points it at
-- settings/earthng.json. Without it set() only marks the registry dirty.
M.storage = nil

local function round(v) return math.floor(v + .5) end

-- the value as the option's kind accepts it, or nil
local function normalise(spec, v)
  local kind = spec.kind
  if kind == 'bool' then
    if v == true or v == 1 or v == 'true' then return true end
    if v == false or v == 0 or v == 'false' then return false end
    return nil
  end
  if kind == 'enum' then
    local values = spec.values
    if type(values) == 'function' then values = values() end
    for _, entry in ipairs(values or {}) do
      local value = entry.value
      if value == nil then value = entry[1] end
      if value == v or (type(value) == 'number' and tonumber(v) == value) or (type(value) == 'string' and tostring(v) == value) then
        return value
      end
    end
    return nil
  end
  v = tonumber(v)
  if not v or v ~= v or v == math.huge or v == -math.huge then return nil end
  local lo, hi, step = spec.min, spec.max, spec.step
  if lo and v < lo then v = lo end
  if hi and v > hi then v = hi end
  if kind == 'int' then
    step = step or 1
    v = (lo or 0) + round((v - (lo or 0)) / step) * step
    if hi and v > hi then v = v - step end
    return round(v)
  end
  if step and step > 0 then
    v = (lo or 0) + round((v - (lo or 0)) / step) * step
    if hi and v > hi then v = hi end
  end
  return v
end
M.normalise = normalise

local function snapshot()
  for k = 1, #order do
    local key = order[k]
    seen[key] = M.get(key)
    local watch = specs[key].watch
    if watch then seenWatch[key] = watch() end
  end
end

local function notify(key, value, source)
  for i = 1, #listeners do
    local ok, err = pcall(listeners[i], key, value, source)
    if not ok and log then log('E', 'e2r_options', tostring(err)) end
  end
  snapshot()
end

-- group{key=, label={uk=, en=}, collapsed=} — the groups are shown in the order they are made
function M.group(spec)
  assert(type(spec) == 'table' and type(spec.key) == 'string', 'options.group: key')
  if not groups[spec.key] then groupOrder[#groupOrder + 1] = spec.key end
  groups[spec.key] = {key = spec.key, label = spec.label or {uk = spec.key, en = spec.key}, collapsed = spec.collapsed or nil}
end

-- define{key=, kind=, min=, max=, step=, values=, default=, group=, label={uk=, en=}, hint={uk=, en=},
--        apply=function(value) end, read=function() return current end, available=function() end,
--        path={'json', 'keys'}, encode=, decode=, note=function() return {uk=, en=} end,
--        watch=function() return number end, live=true}
-- live (int/float): the page may send while the slider moves (throttled), not only on release.
-- values (enum): a list of {value=, label={uk=, en=}} or of {value, 'uk label', 'en label'} (the widget's
-- rows); a function returning such a list is read on every list(). Defining a key again replaces it
-- in place, so another module can take an option over.
function M.define(spec)
  assert(type(spec) == 'table' and type(spec.key) == 'string', 'options.define: key')
  assert(KINDS[spec.kind], 'options.define: kind of ' .. spec.key)
  if spec.kind == 'int' or spec.kind == 'float' then
    assert(type(spec.min) == 'number' and type(spec.max) == 'number' and spec.min <= spec.max,
      'options.define: min/max of ' .. spec.key)
  end
  if spec.kind == 'enum' then assert(spec.values, 'options.define: values of ' .. spec.key) end
  if not specs[spec.key] then order[#order + 1] = spec.key end
  specs[spec.key] = spec
  if not spec.read then
    local v = normalise(spec, stored[spec.key])
    if v == nil then v = normalise(spec, spec.default) end
    stored[spec.key] = v
  end
  seen[spec.key] = M.get(spec.key)
  seenWatch[spec.key] = spec.watch and spec.watch() or nil
  notes[spec.key] = nil
  return spec
end

function M.has(key) return specs[key] ~= nil end

function M.get(key)
  local spec = specs[key]
  if not spec then return nil end
  local v
  if spec.read then v = spec.read() else v = stored[key] end
  if v == nil then v = spec.default end
  return v
end

-- Validates and clamps, applies, saves (options with a path), tells the listeners.
-- Returns the value now in force and whether it changed; nil and a reason when refused.
function M.set(key, value, source)
  local spec = specs[key]
  if not spec then return nil, 'unknown option ' .. tostring(key) end
  if spec.available and not spec.available() then return nil, 'unavailable' end
  local v = normalise(spec, value)
  if v == nil then return nil, 'invalid value' end
  if v == M.get(key) then return v, false end
  local prev = stored[key]
  if not spec.read then stored[key] = v end
  if spec.apply then
    busy = true
    local ok, err = pcall(spec.apply, v)
    busy = false
    if not ok then
      if not spec.read then stored[key] = prev end
      if log then log('E', 'e2r_options', key .. ': ' .. tostring(err)) end
      notify(key, M.get(key), source)
      return nil, tostring(err)
    end
  end
  if spec.path then
    M.dirty = true
    M.flush()
  end
  local now = M.get(key)
  notify(key, now, source)
  return now, true
end

-- the owner changed a value itself (the widget, an automation): tell the listeners now
function M.touch(key)
  if busy then return end
  notify(key, M.get(key), 'external')
end

-- Called every frame; looks at the live values every POLL_EVERY s and tells the listeners once if
-- any moved, so a change made where the registry does not see it still reaches the page.
-- No garbage: reads return numbers, strings or booleans.
function M.poll(now)
  if now < pollAt then return false end
  pollAt = now + M.POLL_EVERY
  if #listeners == 0 then return false end
  local changed
  for k = 1, #order do
    local key = order[k]
    local v = M.get(key)
    if v ~= seen[key] then changed = changed or key end
    local watch = specs[key].watch
    if watch and watch() ~= seenWatch[key] then changed = changed or key end
  end
  if changed then notify(changed, M.get(changed), 'poll') end
  return changed ~= nil
end

-- An option's note: a line of live state beside it ("320 / 400 ..."), {uk=, en=} from spec.note().
-- spec.watch() returns a number that changes whenever the note would (no string per poll); the
-- widget draws noteText every frame, which builds the string again only when watch() or the
-- language changed.
function M.noteText(key, lang)
  local spec = specs[key]
  if not (spec and spec.note) then return nil end
  local w = spec.watch and spec.watch()
  local c = notes[key]
  if c and c.watch == w and c.lang == lang and w ~= nil then return c.text end
  local n = spec.note()
  local text = n and (n[lang] or n.en or n.uk) or nil
  notes[key] = {watch = w, lang = lang, text = text}
  return text
end

-- onChange(fn[, name]): fn(key, value, source). A named listener replaces the earlier one of that
-- name (an extension reloaded registers again). Returns a function that removes it.
function M.onChange(fn, name)
  if name then
    for i = #listeners, 1, -1 do
      if listenerNames[i] == name then table.remove(listeners, i); table.remove(listenerNames, i) end
    end
  end
  listeners[#listeners + 1] = fn
  listenerNames[#listeners] = name or false
  return function()
    for i = #listeners, 1, -1 do
      if listeners[i] == fn then table.remove(listeners, i); table.remove(listenerNames, i) end
    end
  end
end

local function label(l, fallback)
  if type(l) == 'table' then return {uk = l.uk or l.en or fallback, en = l.en or l.uk or fallback} end
  if type(l) == 'string' then return {uk = l, en = l} end
  return {uk = fallback, en = fallback}
end

local function describe(spec)
  local d = {key = spec.key, kind = spec.kind, group = spec.group or 'other', label = label(spec.label, spec.key),
    hint = spec.hint and label(spec.hint, '') or nil, min = spec.min, max = spec.max, step = spec.step,
    default = spec.default, value = M.get(spec.key)}
  if spec.kind == 'int' and not d.step then d.step = 1 end
  if spec.live then d.live = true end
  if spec.note then
    local n = spec.note()
    if n then d.note = label(n, '') end
  end
  if spec.available and not spec.available() then d.disabled = true end
  if spec.kind == 'enum' then
    local values = spec.values
    if type(values) == 'function' then values = values() end
    d.values = {}
    for i, entry in ipairs(values or {}) do
      local value = entry.value
      if value == nil then value = entry[1] end
      local text = entry.label or (entry[2] and {uk = entry[2], en = entry[3] or entry[2]}) or tostring(value)
      d.values[i] = {value = value, label = label(text, tostring(value))}
    end
  end
  return d
end

-- every option with its current value, in definition order; plain tables only (no functions),
-- built on demand
function M.list()
  local out = {}
  for k = 1, #order do out[k] = describe(specs[order[k]]) end
  return out
end

-- what the page draws: {lang=, groups={{key=, label=, collapsed=, options={...}}, ...}}
function M.payload()
  local byGroup, out = {}, {}
  for _, d in ipairs(M.list()) do
    local g = byGroup[d.group]
    if not g then
      local spec = groups[d.group] or {key = d.group, label = {uk = d.group, en = d.group}}
      g = {key = spec.key, label = spec.label, collapsed = spec.collapsed, options = {}}
      byGroup[d.group] = g
    end
    g.options[#g.options + 1] = d
  end
  for _, key in ipairs(groupOrder) do
    if byGroup[key] then out[#out + 1] = byGroup[key]; byGroup[key] = nil end
  end
  for _, key in ipairs(order) do   -- groups nobody declared: in the order of their first option
    local g = byGroup[specs[key].group or 'other']
    if g then out[#out + 1] = g; byGroup[g.key] = nil end
  end
  local lang = M.get('lang')
  return {lang = (lang == 'en' or lang == 'uk') and lang or 'uk', groups = out}
end

-- --- settings/earthng.json -----------------------------------------------------------------------
local function getPath(cfg, path)
  local t = cfg
  for i = 1, #path do
    if type(t) ~= 'table' then return nil end
    t = t[path[i]]
  end
  return t
end

local function setPath(cfg, path, v)
  local t = cfg
  for i = 1, #path - 1 do
    if type(t[path[i]]) ~= 'table' then t[path[i]] = {} end
    t = t[path[i]]
  end
  t[path[#path]] = v
end

-- writes the options that have a path into cfg (the rest of cfg stays as it was)
function M.save(cfg)
  for k = 1, #order do
    local spec = specs[order[k]]
    if spec.path then
      local v = M.get(spec.key)
      if spec.encode then v = spec.encode(v) end
      setPath(cfg, spec.path, v)
    end
  end
  return cfg
end

function M.flush()
  if not M.dirty or not M.storage then return false end
  local cfg = M.storage.read()
  if type(cfg) ~= 'table' then cfg = {} end
  M.storage.write(M.save(cfg))
  M.dirty = false
  return true
end

-- reads the options that have a path from cfg (or the storage); apply = true hands each value
-- to its owner too. Returns how many were taken.
function M.restore(cfg, apply)
  if cfg == nil and M.storage then cfg = M.storage.read() end
  if type(cfg) ~= 'table' then return 0 end
  local n = 0
  for k = 1, #order do
    local spec = specs[order[k]]
    local raw = spec.path and getPath(cfg, spec.path)
    if raw ~= nil then
      if spec.decode then raw = spec.decode(raw) end
      local v = normalise(spec, raw)
      if v ~= nil then
        n = n + 1
        local before = M.get(spec.key)
        if not spec.read then stored[spec.key] = v end
        if apply and spec.apply and v ~= before then   -- the owner already has it: nothing to do
          busy = true
          local ok, err = pcall(spec.apply, v)
          busy = false
          if not ok and log then log('E', 'e2r_options', spec.key .. ': ' .. tostring(err)) end
        end
      end
    end
  end
  snapshot()
  return n
end

return M
