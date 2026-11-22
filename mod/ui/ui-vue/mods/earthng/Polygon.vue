<template>
  <div class="eng-card">
    <div class="eng-head">
      <span class="eng-title">{{ T.title }}</span>
      <span class="eng-sub">{{ data && data.title ? data.title : T.sub }}</span>
    </div>
    <div class="eng-body">
      <div v-if="!data" class="eng-empty">{{ T.empty }}</div>
      <div v-else-if="!plan" class="eng-empty">
        {{ T.missing }}
        <div class="eng-mono">python earthng/proving_ground.py</div>
      </div>
      <template v-else>
        <div v-if="detail" class="eng-here">
          <div class="eng-here-head">
            <span class="eng-here-code" :class="'eng-z-' + (detail.zone || 'free')">{{ detail.code || detail.key }}</span>
            <span class="eng-here-title">{{ detail.code ? pickText(detail.title, detail.titleEn) : T.offPlan }}</span>
            <span v-if="detail.pinned" class="eng-state">{{ T.pinned }}</span>
            <span v-if="detail.state" class="eng-state" :class="stateClass">{{ stateText }}</span>
          </div>
          <div class="eng-here-sub">{{ whereLine }}</div>
          <div v-if="detail.theme" class="eng-here-about">
            <strong>{{ pickText(detail.theme.title, detail.theme.titleEn) }}.</strong>
            {{ pickText(detail.theme.about, detail.theme.aboutEn) }}
          </div>
          <div v-if="detail.tags" class="eng-mono eng-here-tags">{{ detail.tags }}</div>

          <div class="eng-here-h">{{ T.rules }}</div>
          <div class="eng-kv">
            <span class="eng-k">{{ T.universe }}</span>
            <span class="eng-v">
              {{ detail.universe ? text(detail.universe.label, lang) : T.own }}
              <span v-if="detail.universe" class="eng-knob-badge">{{ fromName(detail.universe.from) }}</span>
            </span>
          </div>
          <div v-if="detail.universe && detail.universe.about" class="eng-here-note">{{ text(detail.universe.about, lang) }}</div>
          <div v-for="row in ruleRows" :key="row.key" class="eng-kv">
            <span class="eng-k">{{ row.label }}</span>
            <span class="eng-v">
              {{ row.value }}
              <span v-if="row.from" class="eng-knob-badge">{{ fromName(row.from) }}</span>
            </span>
          </div>

          <div class="eng-here-h">{{ T.look }}</div>
          <div v-for="slot in list(detail.look)" :key="slot.key" class="eng-kv">
            <span class="eng-k">{{ text(slot.label, lang) }}</span>
            <span class="eng-v">
              {{ valueText(slot) }}
              <span v-if="slot.from !== 'default'" class="eng-knob-badge">{{ fromName(slot.from) }}</span>
            </span>
          </div>

          <div class="eng-here-h">
            {{ T.changed }}
            <span v-if="list(detail.changed).length" class="eng-count">{{ list(detail.changed).length }}</span>
          </div>
          <div v-if="!list(detail.changed).length" class="eng-here-note">{{ T.unchanged }}</div>
          <div v-for="knob in list(detail.changed)" :key="knob.key" class="eng-kv">
            <span class="eng-k">{{ text(knob.label, lang) }}</span>
            <span class="eng-v">
              {{ valueText(knob) }}
              <span class="eng-knob-badge">{{ fromName(knob.from) }}</span>
              <span v-if="knob.default !== undefined && knob.default !== null" class="eng-here-was">{{ T.was }} {{ plain(knob.default) }}</span>
            </span>
          </div>
        </div>

        <div class="eng-info">{{ T.zones }}</div>
        <div class="eng-legend">
          <button v-for="zone in list(plan.zones)" :key="zone.id" :class="'eng-z-' + zone.id" bng-nav-item
            @click="world('polygonZone', zone.id)">{{ lang === 'en' ? zone.titleEn : zone.title }}</button>
        </div>
        <div class="eng-info">{{ T.blocks }}</div>
        <div class="eng-legend">
          <button v-for="b in list(plan.blocks)" :key="b.id" :class="['eng-z-' + (b.universe || 'main'), { on: block && b.id === block.id }]"
            bng-nav-item @click="blockId = b.id">{{ lang === 'en' ? b.titleEn : b.title }}</button>
        </div>
        <div class="eng-info">{{ T.map }}</div>
        <div class="eng-map" :style="{ '--cols': cols.length }">
          <template v-for="j in rows" :key="j">
            <button
              v-for="i in cols"
              :key="i + '_' + j"
              class="eng-tile"
              :class="tileClass(i, j)"
              :title="tileTitle(i, j)"
              bng-nav-item
              @click="pick(i, j)"
            >{{ at(i, j) ? short(at(i, j).code) : '' }}</button>
          </template>
        </div>
        <template v-if="picked">
          <div class="eng-info">
            <strong>{{ picked.code }}</strong> · {{ lang === 'en' ? picked.titleEn || picked.title : picked.title }}
            <span v-if="picked.code === data.here" class="eng-state ok">{{ T.here }}</span>
            <div v-if="pickedTheme" class="eng-here-note">
              {{ pickText(pickedTheme.title, pickedTheme.titleEn) }}. {{ pickText(pickedTheme.about, pickedTheme.aboutEn) }}
            </div>
            <div v-if="picked.tags" class="eng-mono">{{ picked.tags }}</div>
          </div>
          <div class="eng-bar">
            <button class="eng-btn main" bng-nav-item @click="world('polygonGo', picked.code)">{{ T.go }}</button>
            <button
              v-for="view in list(picked.views)"
              :key="view.id"
              class="eng-btn"
              :class="{ on: data.view && data.view.code === picked.code && data.view.id === view.id }"
              bng-nav-item
              @click="world('polygonView', picked.code, view.id)"
            >{{ viewName(view.id) }}</button>
            <button class="eng-btn" :disabled="!data.view" bng-nav-item @click="world('polygonViewOff')">{{ T.car }}</button>
            <button class="eng-btn" bng-nav-item @click="world('polygonShot')">{{ T.shot }}</button>
          </div>
          <div v-if="shot" class="eng-info eng-mono">{{ T.saved }}: {{ shot }}</div>
          <div class="eng-info">{{ T.note }}</div>
        </template>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue"
import { useBridge } from "@/bridge"
import { list, text, world } from "./call.js"
import { ensureStyle } from "./style.js"

// The proving ground (earthng/proving_ground.py): the tile under the car with what it shows and
// the rules it is built by, the island's tiles as a map to land on, and each tile's cameras. The
// plan comes from the pack's manifest and the tile's card from world.lua polygonDetail, both
// with the hook EarthNGPolygon.
ensureStyle()
const { events } = useBridge()
const data = ref(null)
const chosen = ref(null)
const blockId = ref(null)      // the block on the map: the car's own until another is picked
const shot = ref("")

const lang = computed(() => (data.value?.lang === "en" ? "en" : "uk"))
const plan = computed(() => data.value?.plan || null)
const detail = computed(() => data.value?.detail || null)
const T = computed(() => lang.value === "en"
  ? { title: "Proving ground", sub: "a test island at Point Nemo", empty: "Waiting for the mod.",
      missing: "The proving ground pack is not mounted. Build it and put earthng_polygon.zip into mods:",
      zones: "Zones (land at the start of a row)", map: "Tiles: north is up, one subject a tile", here: "the car is here",
      blocks: "The island: the main grid and a universe on each side",
      go: "Land here", car: "Back to the car", shot: "Screenshot", saved: "Saved", street: "Street", over: "From above",
      top: "Plan", note: "A camera looks at loaded ground: land in the tile first, then pick its views.",
      offPlan: "Outside the plan's subjects", pinned: "pinned", tile: "tile", metres: "m",
      rules: "Rules in force here", universe: "Universe", own: "none: the place's own rules",
      climate: "Climate", flora: "Vegetation zone", feel: "Under the tyres", swaps: "Materials swapped",
      hidden: "Not drawn", generator: "Generator", look: "Asset set", changed: "Generator numbers off their defaults",
      unchanged: "None: the tile is built by the rules above and the generator's defaults.", was: "default",
      climates: {},
      byPlace: "by the place", byPlaceFlora: "by the place and the climate", feelOn: "the physics of the land drawn (snow, sand, mud)",
      feelOff: "grass everywhere", treeline: "tree line", snowline: "snow from", snowAll: "snow everywhere",
      classN: "Köppen class", families: "families by pattern", on: "on", off: "off",
      from: { tile: "this tile", world: "whole world", universe: "universe", pack: "the pack's plan" },
      state: { ready: "built", scene: "road built, scenery coming", busy: "building", wait: "not built yet" } }
  : { title: "Полігон", sub: "тестовий острів у точці Немо", empty: "Чекаю на мод.",
      missing: "Пак полігона не змонтовано. Зберіть його й покладіть earthng_polygon.zip у mods:",
      zones: "Зони (висадка на початку ряду)", map: "Тайли: північ угорі, один тайл — одна тема", here: "машина тут",
      blocks: "Острів: основна сітка і всесвіт з кожного боку",
      go: "Висадитися тут", car: "Камеру до машини", shot: "Знімок", saved: "Збережено", street: "З вулиці", over: "Згори",
      top: "План", note: "Камера показує завантажену землю: спершу висадіться в тайлі, потім обирайте його кадри.",
      offPlan: "Поза темами плану", pinned: "закріплено", tile: "тайл", metres: "м",
      rules: "Які правила тут діють", universe: "Всесвіт", own: "немає: правила самого місця",
      climate: "Клімат", flora: "Зона рослинності", feel: "Під колесами", swaps: "Підміна матеріалів",
      hidden: "Не малюється", generator: "Генератор", look: "Набір асетів", changed: "Числа генератора не як типові",
      unchanged: "Немає: тайл зібрано за правилами вище і типовими числами генератора.", was: "типово",
      climates: { rainforest: "дощовий ліс", savanna: "савана", desert: "пустеля", steppe: "степ", mediterranean: "середземноморський",
        temperate: "помірний", boreal: "бореальний", tundra: "тундра", ice: "лід" },
      byPlace: "за місцем", byPlaceFlora: "за місцем і кліматом", feelOn: "фізика намальованої землі (сніг, пісок, багно)",
      feelOff: "усюди трава", treeline: "межа лісу", snowline: "сніг від", snowAll: "сніг усюди",
      classN: "клас Кеппена", families: "родин за шаблоном", on: "увімкнено", off: "вимкнено",
      from: { tile: "цей тайл", world: "увесь світ", universe: "всесвіт", pack: "план пака" },
      state: { ready: "зібрано", scene: "дорога є, наповнення будується", busy: "будується", wait: "ще не зібрано" } })

const hereTile = computed(() => list(plan.value?.tiles).find(t => t.code === data.value?.here) || null)
const block = computed(() => {
  const blocks = list(plan.value?.blocks)
  return blocks.find(b => b.id === blockId.value) || blocks.find(b => hereTile.value && b.id === hereTile.value.block) || blocks[0] || null
})
const cols = computed(() => {
  const c = list(block.value?.cols)
  const out = []
  for (let i = c[0]; i <= c[1]; i++) out.push(i)
  return out
})
const rows = computed(() => {
  const r = list(block.value?.rows)
  const out = []
  for (let j = r[1]; j >= r[0]; j--) out.push(j)
  return out
})
const byKey = computed(() => {
  const out = {}
  for (const tile of list(plan.value?.tiles)) out[tile.i + "_" + tile.j] = tile
  return out
})
const picked = computed(() => {
  const tiles = list(plan.value?.tiles)
  return tiles.find(t => t.code === chosen.value) || tiles.find(t => t.code === data.value?.here) || null
})
const pickedTheme = computed(() => {
  const themes = plan.value?.themes
  return picked.value && themes && typeof themes === "object" ? themes[picked.value.zone] || null : null
})

// --- the card of the tile under the car ---------------------------------------------------------
function pickText(uk, en) {
  return (lang.value === "en" ? en || uk : uk || en) || ""
}
function fromName(from) {
  return T.value.from[from] || ""
}
// a number without a float's tail, a switch as a word, anything else as it is
function plain(v) {
  if (v === true) return T.value.on
  if (v === false) return T.value.off
  if (typeof v === "number") return String(Math.round(v * 1000) / 1000)
  return v === null || v === undefined ? "" : String(v)
}
function valueText(entry) {
  return entry.text ? text(entry.text, lang.value) : plain(entry.value)
}
function pairs(table) {
  return table && typeof table === "object" && !Array.isArray(table) ? Object.entries(table) : []
}
const stateClass = computed(() => {
  const s = detail.value?.state
  if (!s) return ""
  return s.ready && s.scene ? "ok" : (s.building || s.queued) ? "busy" : ""
})
const stateText = computed(() => {
  const s = detail.value?.state
  if (!s) return ""
  if (s.ready && s.scene) return T.value.state.ready
  if (s.ready) return T.value.state.scene
  return s.building || s.queued ? T.value.state.busy : T.value.state.wait
})
const whereLine = computed(() => {
  const d = detail.value
  if (!d) return ""
  const parts = []
  if (d.block) parts.push(pickText(d.block.title, d.block.titleEn))
  parts.push(T.value.tile + " " + d.key + " · " + d.size + " × " + d.size + " " + T.value.metres)
  const at = list(d.at)
  if (at.length >= 2) parts.push(at[0].toFixed(5) + ", " + at[1].toFixed(5))
  return parts.join(" · ")
})
// The rules as lines: the lab's own knob where one is set, the universe's rule otherwise.
const ruleRows = computed(() => {
  const d = detail.value
  if (!d) return []
  const t = T.value
  const u = d.universe || null
  const knob = {}
  for (const entry of list(d.rules)) knob[entry.key] = entry
  const set = entry => entry && entry.value !== "auto" && entry.from !== "default"
  const out = []

  if (set(knob.climate)) {
    out.push({ key: "climate", label: t.climate, value: t.climates[knob.climate.value] || valueText(knob.climate), from: knob.climate.from })
  } else if (u && u.climate) {
    const c = u.climate
    const bits = [(t.climates[c.name] || c.name || "") + " (" + t.classN + " " + c.class + ")"]
    if (typeof c.treeline === "number") bits.push(t.treeline + " " + c.treeline + " " + t.metres)
    if (typeof c.snowline === "number") bits.push(c.snowline <= 0 ? t.snowAll : t.snowline + " " + c.snowline + " " + t.metres)
    out.push({ key: "climate", label: t.climate, value: bits.join(" · "), from: "universe" })
  } else {
    out.push({ key: "climate", label: t.climate, value: t.byPlace })
  }

  if (set(knob.floraZone)) {
    out.push({ key: "flora", label: t.flora, value: valueText(knob.floraZone), from: knob.floraZone.from })
  } else if (u && u.flora) {
    out.push({ key: "flora", label: t.flora, value: u.flora, from: "universe" })
  } else {
    out.push({ key: "flora", label: t.flora, value: t.byPlaceFlora })
  }

  if (set(knob.feel)) {
    out.push({ key: "feel", label: t.feel, value: knob.feel.value === "on" ? t.feelOn : t.feelOff, from: knob.feel.from })
  } else {
    out.push({ key: "feel", label: t.feel, value: u && u.feel ? t.feelOn : t.feelOff, from: u && u.feel ? "universe" : "" })
  }

  if (u) {
    const swapped = list(u.swaps).filter(s => s[1] !== false).map(s => s[0] + " → " + s[1])
    const hidden = list(u.swaps).filter(s => s[1] === false).map(s => s[0])
    if (u.patterns) swapped.push("+ " + u.patterns + " " + t.families)
    if (swapped.length) out.push({ key: "swaps", label: t.swaps, value: swapped.join(", ") })
    if (hidden.length) out.push({ key: "hidden", label: t.hidden, value: hidden.join(", ") })
    // (a rule that is a knob of the lab is in the list below under its own name)
    const listed = new Set(list(d.changed).map(entry => entry.key))
    const numbers = [...pairs(u.tune), ...pairs(u.option)].filter(([k]) => !listed.has(k)).map(([k, v]) => k + " = " + plain(v))
    if (numbers.length) out.push({ key: "generator", label: t.generator, value: numbers.join(", ") })
  }
  return out
})

function at(i, j) {
  return byKey.value[i + "_" + j]
}
function tileClass(i, j) {
  const t = at(i, j)
  if (!t) return "eng-z-free"
  return ["eng-z-" + t.zone, t.code === data.value?.here ? "here" : "", picked.value && t.code === picked.value.code ? "picked" : ""]
}
function tileTitle(i, j) {
  const t = at(i, j)
  return t ? t.code + " · " + (lang.value === "en" ? t.titleEn || t.title : t.title) : ""
}
function pick(i, j) {
  const t = at(i, j)
  if (t) chosen.value = t.code
}
// a universe's tiles are named 'MT-C2': the map of one block shows the 'C2'
function short(code) {
  const at = code.indexOf("-")
  return at < 0 ? code : code.slice(at + 1)
}
function viewName(id) {
  return T.value[id] || id
}
function onPolygon(payload) {
  data.value = payload
}
function onShot(payload) {
  shot.value = payload?.path || ""
}

onMounted(() => {
  events.on("EarthNGPolygon", onPolygon)
  events.on("EarthNGShot", onShot)
  world("polygonList")
})
onUnmounted(() => {
  events.off("EarthNGPolygon", onPolygon)
  events.off("EarthNGShot", onShot)
})
</script>
