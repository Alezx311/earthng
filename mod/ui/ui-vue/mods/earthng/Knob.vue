<template>
  <div class="eng-knob" :class="{ off: knob.disabled, marked }">
    <div class="eng-knob-line">
      <div class="eng-knob-label">
        {{ text(knob.label, lang) }}
        <span v-if="badge" class="eng-knob-badge">{{ badge }}</span>
      </div>
      <span v-if="isNumber" class="eng-knob-num">{{ shown }}</span>
      <button
        v-if="knob.kind === 'bool'"
        class="eng-switch"
        :class="{ on: !!local }"
        role="switch"
        :aria-checked="!!local"
        :disabled="knob.disabled"
        bng-nav-item
        @click="toggle"
      ></button>
      <button v-if="marked" class="eng-knob-reset" :title="resetTitle" bng-nav-item @click="$emit('reset')">×</button>
    </div>
    <div v-if="hint" class="eng-knob-hint">{{ hint }}</div>
    <input
      v-if="isNumber"
      class="eng-range"
      type="range"
      :min="knob.min"
      :max="knob.max"
      :step="knob.step || (knob.kind === 'int' ? 1 : 'any')"
      :value="local"
      :disabled="knob.disabled"
      :style="{ '--p': percent + '%' }"
      bng-nav-item
      @input="onInput"
      @change="onChange"
    />
    <div v-if="knob.kind === 'enum'" class="eng-seg">
      <button
        v-for="choice in list(knob.values)"
        :key="String(choice.value)"
        :class="{ on: choice.value === local }"
        :disabled="knob.disabled"
        bng-nav-item
        @click="pick(choice.value)"
      >{{ text(choice.label, lang) }}</button>
    </div>
    <div v-if="note" class="eng-knob-note">{{ note }}</div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { list, text } from "./call.js"

// One setting as a row: a switch, a slider with its number, or a row of choices. The value shown
// is the page's own while a slider moves, and the game's again when its answer comes.
const props = defineProps({
  knob: { type: Object, required: true },
  lang: { type: String, default: "uk" },
  marked: { type: Boolean, default: false },   // set away from its default: the row offers a reset
  badge: { type: String, default: "" },
  resetTitle: { type: String, default: "" },
  offText: { type: String, default: "" },
})
const emit = defineEmits(["change", "reset"])

const LIVE_MS = 100
const local = ref(props.knob.value)
const dragging = ref(false)
let lastAt = 0
let lastSent = null

watch(() => props.knob.value, v => { if (!dragging.value) local.value = v })

const isNumber = computed(() => props.knob.kind === "int" || props.knob.kind === "float")
const digits = computed(() => {
  if (props.knob.kind === "int") return 0
  const s = String(props.knob.step || 0.01)
  const i = s.indexOf(".")
  return i < 0 ? 0 : Math.min(4, s.length - i - 1)
})
const shown = computed(() => (local.value === null || local.value === undefined ? "" : Number(local.value).toFixed(digits.value)))
const percent = computed(() => {
  const { min, max } = props.knob
  if (!(max > min)) return 0
  return Math.max(0, Math.min(100, ((Number(local.value) - min) / (max - min)) * 100))
})
const hint = computed(() => (props.knob.disabled ? props.offText : text(props.knob.hint, props.lang)))
const note = computed(() => text(props.knob.note, props.lang))

function send(v) {
  lastSent = v
  emit("change", v)
}
function toggle(event) {
  local.value = !local.value
  send(local.value)
  event.currentTarget.blur()
}
function pick(v) {
  local.value = v
  send(v)
}
// a cheap setting (knob.live) goes while the slider moves, at most every LIVE_MS; the others
// only when it is let go, so the world is built again once
function onInput(event) {
  dragging.value = true
  local.value = Number(event.target.value)
  const now = Date.now()
  if (props.knob.live && now - lastAt >= LIVE_MS) {
    lastAt = now
    send(local.value)
  }
}
function onChange(event) {
  dragging.value = false
  const v = Number(event.target.value)
  local.value = v
  if (!props.knob.live || v !== lastSent) send(v)
  event.target.blur()
}
</script>

