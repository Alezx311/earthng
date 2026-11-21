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
        <div class="eng-info">{{ T.zones }}</div>
        <div class="eng-legend">
          <button v-for="zone in list(plan.zones)" :key="zone.id" :class="'eng-z-' + zone.id" bng-nav-item
            @click="world('polygonZone', zone.id)">{{ lang === 'en' ? zone.titleEn : zone.title }}</button>
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
            >{{ at(i, j) ? at(i, j).code : '' }}</button>
          </template>
        </div>
        <template v-if="picked">
          <div class="eng-info">
            <strong>{{ picked.code }}</strong> · {{ lang === 'en' ? picked.titleEn || picked.title : picked.title }}
            <span v-if="picked.code === data.here" class="eng-state ok">{{ T.here }}</span>
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
import { list, world } from "./call.js"
import { ensureStyle } from "./style.js"

// The proving ground (earthng/proving_ground.py): its tiles as a map to land on, and each tile's
// cameras. The plan comes from the pack's manifest with the hook EarthNGPolygon.
ensureStyle()
const { events } = useBridge()
const data = ref(null)
const chosen = ref(null)
const shot = ref("")

const lang = computed(() => (data.value?.lang === "en" ? "en" : "uk"))
const plan = computed(() => data.value?.plan || null)
const T = computed(() => lang.value === "en"
  ? { title: "Proving ground", sub: "a test island at Point Nemo", empty: "Waiting for the mod.",
      missing: "The proving ground pack is not mounted. Build it and put earthng_polygon.zip into mods:",
      zones: "Zones (land at the start of a row)", map: "Tiles: north is up, one subject a tile", here: "the car is here",
      go: "Land here", car: "Back to the car", shot: "Screenshot", saved: "Saved", street: "Street", over: "From above",
      top: "Plan", note: "A camera looks at loaded ground: land in the tile first, then pick its views." }
  : { title: "Полігон", sub: "тестовий острів у точці Немо", empty: "Чекаю на мод.",
      missing: "Пак полігона не змонтовано. Зберіть його й покладіть earthng_polygon.zip у mods:",
      zones: "Зони (висадка на початку ряду)", map: "Тайли: північ угорі, один тайл — одна тема", here: "машина тут",
      go: "Висадитися тут", car: "Камеру до машини", shot: "Знімок", saved: "Збережено", street: "З вулиці", over: "Згори",
      top: "План", note: "Камера показує завантажену землю: спершу висадіться в тайлі, потім обирайте його кадри." })

const cols = computed(() => {
  const c = list(plan.value?.cols)
  const out = []
  for (let i = c[0]; i <= c[1]; i++) out.push(i)
  return out
})
const rows = computed(() => {
  const r = list(plan.value?.rows)
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
