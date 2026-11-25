-- A Cyrillic name in Latin letters, for a player who reads the UI in English (25.11, the user: the
-- map's points, the card's facts and the street names were Ukrainian in English). A name with its
-- own English form (name:en) keeps that one; the rest are written out as the country's own rule
-- writes them on its signs and in its passports: Ukrainian by the national system of 2010 (the
-- Cabinet's resolution 55: 'Zghurivka', 'Yahotyn', 'Vinnytsia'), Russian by BGN/PCGN ('Tverskaya',
-- 'Ilyinka'). A name is Russian when it has a letter Ukrainian has not (ы э ё ъ), else Ukrainian.
-- Latin text, digits and the rest pass as they are.
local M = {}

local LOWER = {
  ['А'] = 'а', ['Б'] = 'б', ['В'] = 'в', ['Г'] = 'г', ['Ґ'] = 'ґ', ['Д'] = 'д', ['Е'] = 'е', ['Є'] = 'є',
  ['Ё'] = 'ё', ['Ж'] = 'ж', ['З'] = 'з', ['И'] = 'и', ['І'] = 'і', ['Ї'] = 'ї', ['Й'] = 'й', ['К'] = 'к',
  ['Л'] = 'л', ['М'] = 'м', ['Н'] = 'н', ['О'] = 'о', ['П'] = 'п', ['Р'] = 'р', ['С'] = 'с', ['Т'] = 'т',
  ['У'] = 'у', ['Ф'] = 'ф', ['Х'] = 'х', ['Ц'] = 'ц', ['Ч'] = 'ч', ['Ш'] = 'ш', ['Щ'] = 'щ', ['Ъ'] = 'ъ',
  ['Ы'] = 'ы', ['Ь'] = 'ь', ['Э'] = 'э', ['Ю'] = 'ю', ['Я'] = 'я', ['Ў'] = 'ў'}

-- Ukrainian (KMU 2010): the forms at a word's start apart
M.UK = {['а'] = 'a', ['б'] = 'b', ['в'] = 'v', ['г'] = 'h', ['ґ'] = 'g', ['д'] = 'd', ['е'] = 'e', ['є'] = 'ie',
  ['ж'] = 'zh', ['з'] = 'z', ['и'] = 'y', ['і'] = 'i', ['ї'] = 'i', ['й'] = 'i', ['к'] = 'k', ['л'] = 'l',
  ['м'] = 'm', ['н'] = 'n', ['о'] = 'o', ['п'] = 'p', ['р'] = 'r', ['с'] = 's', ['т'] = 't', ['у'] = 'u',
  ['ф'] = 'f', ['х'] = 'kh', ['ц'] = 'ts', ['ч'] = 'ch', ['ш'] = 'sh', ['щ'] = 'shch', ['ь'] = '', ['ю'] = 'iu',
  ['я'] = 'ia', ['ё'] = 'io', ['ы'] = 'y', ['э'] = 'e', ['ъ'] = '', ['ў'] = 'w'}
M.UK_START = {['є'] = 'ye', ['ї'] = 'yi', ['й'] = 'y', ['ю'] = 'yu', ['я'] = 'ya'}
-- Russian (BGN/PCGN, without its diacritics)
M.RU = {['а'] = 'a', ['б'] = 'b', ['в'] = 'v', ['г'] = 'g', ['д'] = 'd', ['е'] = 'e', ['ё'] = 'yo', ['ж'] = 'zh',
  ['з'] = 'z', ['и'] = 'i', ['й'] = 'y', ['к'] = 'k', ['л'] = 'l', ['м'] = 'm', ['н'] = 'n', ['о'] = 'o',
  ['п'] = 'p', ['р'] = 'r', ['с'] = 's', ['т'] = 't', ['у'] = 'u', ['ф'] = 'f', ['х'] = 'kh', ['ц'] = 'ts',
  ['ч'] = 'ch', ['ш'] = 'sh', ['щ'] = 'shch', ['ъ'] = '', ['ы'] = 'y', ['ь'] = '', ['э'] = 'e', ['ю'] = 'yu',
  ['я'] = 'ya', ['є'] = 'ye', ['і'] = 'i', ['ї'] = 'yi', ['ґ'] = 'g', ['ў'] = 'w'}
M.RU_START = {['е'] = 'ye'}
-- the apostrophes inside a word (В'язовий, Обʼєкт): not written
local APOSTROPHE = {["'"] = true, ['’'] = true, ['ʼ'] = true}
local RUSSIAN = {['ы'] = true, ['э'] = true, ['ё'] = true, ['ъ'] = true}
local UKRAINIAN = {['і'] = true, ['ї'] = true, ['є'] = true, ['ґ'] = true}
-- the rule for a name with neither's own letters: world.lua sets 'ru' for a landing in Russia
M.rule = nil

local cache, cached = {}, 0

-- s in Latin letters ('uk' or 'ru' forces the rule); s itself when it has no Cyrillic
function M.latin(s, rule)
  if type(s) ~= 'string' or not s:find('[\208\209\210]') then return s end
  local key = (rule or M.rule or '') .. '\0' .. s
  local hit = cache[key]
  if hit then return hit end
  local chars = {}
  for ch in s:gmatch('[%z\1-\127\194-\244][\128-\191]*') do chars[#chars + 1] = ch end
  if not rule then
    -- by a letter only one of the two has, else by the country the car is in (M.rule)
    for _, ch in ipairs(chars) do
      local low = LOWER[ch] or ch
      if RUSSIAN[low] then rule = 'ru'; break end
      if UKRAINIAN[low] then rule = 'uk'; break end
    end
    rule = rule or M.rule or 'uk'
  end
  local T, START = rule == 'ru' and M.RU or M.UK, rule == 'ru' and M.RU_START or M.UK_START
  local out, n = {}, #chars
  local function cyrillic(ch) return ch ~= nil and (LOWER[ch] or T[ch]) ~= nil end
  local function letter(ch) return cyrillic(ch) or (ch ~= nil and ch:find('^%a$') ~= nil) end
  for k = 1, n do
    local ch = chars[k]
    local low = LOWER[ch]
    local lower = low or ch
    local tr = T[lower]
    if tr then
      local prev = chars[k - 1]
      -- a word starts after anything that is not a letter or an apostrophe inside one
      local start = not (prev and (letter(prev) or (APOSTROPHE[prev] and letter(chars[k - 2]))))
      if start and START[lower] then tr = START[lower] end
      -- зг is zgh, apart from ж (Згурівка: Zghurivka)
      if rule ~= 'ru' and lower == 'г' and prev and (LOWER[prev] or prev) == 'з' then tr = 'gh' end
      if low and tr ~= '' then
        -- a capital: the whole word in capitals when the next letter is one too
        local nextCh = chars[k + 1]
        if nextCh and LOWER[nextCh] then tr = tr:upper()
        else tr = tr:sub(1, 1):upper() .. tr:sub(2) end
      end
      out[#out + 1] = tr
    elseif APOSTROPHE[ch] and cyrillic(chars[k - 1]) and cyrillic(chars[k + 1]) then
      -- (dropped between two Cyrillic letters)
    else
      out[#out + 1] = ch
    end
  end
  local text = table.concat(out)
  cached = cached + 1
  if cached > 8000 then cache, cached = {}, 1 end
  cache[key] = text
  return text
end

-- The name a player reading `lang` sees: the English form when there is one, else in Latin
-- letters for English, else the name itself
function M.show(name, en, lang)
  if lang ~= 'en' then return name end
  if en and en ~= '' then return M.latin(en) end
  return M.latin(name)
end

return M
