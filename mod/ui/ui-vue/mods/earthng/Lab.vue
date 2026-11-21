<template>
  <div class="eng-card">
    <div class="eng-head">
      <span class="eng-title">{{ T.title }}</span>
      <span class="eng-sub">{{ T.sub }}</span>
    </div>
    <div class="eng-body">
      <div v-if="!data" class="eng-empty">{{ T.empty }}</div>
      <template v-else>
        <div class="eng-scope">
          <button :class="{ on: scope === 'tile' }" :disabled="!tile" bng-nav-item @click="scope = 'tile'">
            {{ T.tile }}<span v-if="data.tileTouched" class="eng-count">•</span>
          </button>
          <button :class="{ on: scope === 'world' }" bng-nav-item @click="scope = 'world'">
            {{ T.world }}<span v-if="data.worldTouched" class="eng-count">•</span>
          </button>
        </div>
        <div class="eng-info">
          <template v-if="tile">
            <strong>{{ tile.code || tile.key }}</strong>
            <span v-if="tile.code"> · {{ lang === 'en' ? tile.titleEn || tile.title : tile.title }}</span>
            <span class="eng-mono"> · {{ tile.key }}</span>
            <span class="eng-state" :class="stateClass">{{ stateText }}</span>
            <div v-if="tile.tags" class="eng-mono">{{ tile.tags }}</div>
          </template>
          <template v-else>{{ T.noTile }}</template>
        </div>
        <div class="eng-bar">
          <button class="eng-btn main" :disabled="!tile" bng-nav-item @click="world('labRebuild', 'tile')">{{ T.rebuildTile }}</button>
          <button class="eng-btn" bng-nav-item @click="world('labRebuild', 'near')">{{ T.rebuildAll }}</button>
          <button class="eng-btn" :class="{ on: tile && tile.pinned }" :disabled="!tile" bng-nav-item
            @click="world('labPin', !(tile && tile.pinned))">{{ T.pin }}</button>
          <button class="eng-btn" :disabled="scope === 'tile' ? !data.tileTouched : !data.worldTouched" bng-nav-item
            @click="world('labReset', null, scope)">{{ scope === 'tile' ? T.resetTile : T.resetWorld }}</button>
          <button class="eng-btn" :disabled="!data.tileTouched && !data.worldTouched && !list(data.scopes).length" bng-nav-item
            @click="world('labReset', null, 'all')">{{ T.resetAll }}</button>
        </div>
        <div v-if="list(data.scopes).length" class="eng-info eng-mono">{{ T.touched }}: {{ list(data.scopes).join(', ') }}</div>
        <div v-for="group in groups" :key="group.key" class="eng-group" :class="{ closed: isClosed(group) }">
          <button class="eng-ghead" bng-nav-item @click="toggle(group)">
            <span>{{ text(group.label, lang) }}</span>
            <span v-if="count(group)" class="eng-count">{{ count(group) }}</span>
            <span class="eng-arrow">▾</span>
          </button>
          <div class="eng-rows">
            <Knob
              v-for="knob in group.knobs"
              :key="scope + ':' + knob.key"
              :knob="knob"
              :lang="lang"
              :marked="knob.marked"
              :badge="knob.badge"
              :reset-title="T.reset"
              @change="value => world('labSet', knob.key, value, scope)"
              @reset="world('labReset', knob.key, scope)"
            />
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue"
import { useBridge } from "@/bridge"
import Knob from "./Knob.vue"
import { list, text, world } from "./call.js"
import { ensureStyle } from "./style.js"

// The generator's knobs (lab.lua) for the tile under the car or for the whole world. A change
// goes to e2r_world.labSet, which builds the tile (or every tile) again at once: the game stays
// paused and the ground changes behind the menu. EarthNGLab carries the list back.
ensureStyle()
const { events } = useBridge()
const data = ref(null)
const scope = ref("tile")
const closed = reactive({})
let timer = null

const lang = computed(() => (data.value?.lang === "en" ? "en" : "uk"))
const tile = computed(() => data.value?.tile || null)
const T = computed(() => lang.value === "en"
  ? { title: "Generator", sub: "what the world is built with", empty: "The generator's settings appear once the mod has loaded.",
      tile: "This tile", world: "Whole world", noTile: "Land first: a tile is the 500 m square under the car.",
      rebuildTile: "Rebuild this tile", rebuildAll: "Rebuild all", pin: "Keep this tile", resetTile: "Reset the tile",
      resetWorld: "Reset the world", resetAll: "Reset everything", touched: "Tiles with their own values", reset: "Back to the default",
      fromTile: "tile", fromWorld: "world", building: "building", queued: "queued", ready: "ready", waiting: "waiting" }
  : { title: "Генератор", sub: "з чого збирається світ", empty: "Налаштування генератора з’являться, щойно мод завантажиться.",
      tile: "Цей тайл", world: "Увесь світ", noTile: "Спершу висадіться: тайл — це квадрат 500 м під машиною.",
      rebuildTile: "Перебудувати тайл", rebuildAll: "Перебудувати все", pin: "Тримати цей тайл", resetTile: "Скинути тайл",
      resetWorld: "Скинути світ", resetAll: "Скинути все", touched: "Тайли з власними значеннями", reset: "Повернути типове",
      fromTile: "тайл", fromWorld: "світ", building: "будується", queued: "у черзі", ready: "готово", waiting: "чекає" })

// A knob as the chosen scope sees it: the tile's own value over the world's over the default.
const groups = computed(() => list(data.value?.groups).map(group => ({
  key: group.key,
  label: group.label,
  collapsed: group.collapsed,
  knobs: list(group.knobs).map(knob => {
    const own = scope.value === "tile" ? knob.tile : knob.world
    const set = own !== undefined && own !== null
    let value = knob.value
    if (scope.value === "world") value = knob.world !== undefined && knob.world !== null ? knob.world : knob.default
    let badge = ""
    if (scope.value === "tile") badge = knob.from === "tile" ? T.value.fromTile : knob.from === "world" ? T.value.fromWorld : ""
    else if (set) badge = T.value.fromWorld
    return { ...knob, value, marked: set, badge }
  }),
})))

const stateClass = computed(() => {
  const s = data.value?.stream
  if (!s) return ""
  return s.ready && s.scene ? "ok" : "busy"
})
const stateText = computed(() => {
  const s = data.value?.stream
  if (!s) return T.value.waiting
  if (s.ready && s.scene) return T.value.ready
  return s.ready ? T.value.building : T.value.queued
})

function count(group) {
  return group.knobs.filter(knob => knob.marked).length
}
function isClosed(group) {
  return closed[group.key] === undefined ? !!group.collapsed : closed[group.key]
}
function toggle(group) {
  closed[group.key] = !isClosed(group)
}
function onLab(payload) {
  data.value = payload
  if (!payload?.tile && scope.value === "tile") scope.value = "world"
}

watch(scope, () => world("labList"))

onMounted(() => {
  events.on("EarthNGLab", onLab)
  world("labList")
  // the tile's state (queued, building, ready) moves while the menu is open: once a second
  timer = setInterval(() => world("labList"), 1000)
})
onUnmounted(() => {
  events.off("EarthNGLab", onLab)
  if (timer) clearInterval(timer)
})
</script>
