<template>
  <div class="eng-card">
    <div class="eng-head">
      <span class="eng-title">EarthNG</span>
      <span class="eng-sub">{{ T.sub }}</span>
    </div>
    <div class="eng-body">
      <div v-if="!groups.length" class="eng-empty">{{ T.empty }}</div>
      <div v-for="group in groups" :key="group.key" class="eng-group" :class="{ closed: isClosed(group) }">
        <button class="eng-ghead" bng-nav-item @click="toggle(group)">
          <span>{{ text(group.label, lang) }}</span>
          <span class="eng-arrow">▾</span>
        </button>
        <div class="eng-rows">
          <Knob
            v-for="option in list(group.options)"
            :key="option.key"
            :knob="option"
            :lang="lang"
            :off-text="T.off"
            @change="value => world('optionsSet', option.key, value)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from "vue"
import { useBridge } from "@/bridge"
import Knob from "./Knob.vue"
import { list, text, world } from "./call.js"
import { ensureStyle } from "./style.js"

// The player's settings (options.lua): the page holds none of its own. It draws what the hook
// EarthNGOptions carries and sends a change with e2r_world.optionsSet; a new option in Lua is
// here with no change to this file.
ensureStyle()
const { events } = useBridge()
const data = ref(null)
const closed = reactive({})

const lang = computed(() => (data.value?.lang === "en" ? "en" : "uk"))
const groups = computed(() => list(data.value?.groups))
const T = computed(() => lang.value === "en"
  ? { sub: "settings", empty: "EarthNG settings appear once the mod has loaded.", off: "Available after landing" }
  : { sub: "налаштування", empty: "Налаштування EarthNG з’являться, щойно мод завантажиться.", off: "Доступно після висадки" })

function isClosed(group) {
  return closed[group.key] === undefined ? !!group.collapsed : closed[group.key]
}
function toggle(group) {
  closed[group.key] = !isClosed(group)
}
function onOptions(payload) {
  data.value = payload
}

onMounted(() => {
  events.on("EarthNGOptions", onOptions)
  world("optionsList")
})
onUnmounted(() => events.off("EarthNGOptions", onOptions))
</script>

