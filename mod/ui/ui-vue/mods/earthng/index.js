// EarthNG on the pause menu: its own tab in the top row (the game's ui_pause_actions, 0.40.6 and
// later; an older game does not read this folder and keeps the ImGui widget).
// The tab and its three buttons are registered in Lua (world.lua M.pauseTab), which knows the
// player's language; the call below is the same registration for a game whose UI loaded before
// the mod's Lua, and the fallback for a Lua side that is not there yet.
import { useBridge } from "@/bridge"

const DIR = "/ui/ui-vue/mods/earthng/"
const TAB = "earthng"
const BUTTONS = [
  { id: "earthng-settings", label: "Налаштування", icon: "adjust", componentName: DIR + "Settings.vue" },
  { id: "earthng-lab", label: "Генератор", icon: "wrench", componentName: DIR + "Lab.vue" },
  { id: "earthng-polygon", label: "Полігон", icon: "mapPoint", componentName: DIR + "Polygon.vue" },
]

function fromLua(api) {
  return new Promise(resolve => {
    let done = false
    const finish = value => { if (!done) { done = true; resolve(value === true) } }
    try {
      api.engineLua(
        "(function() pcall(extensions.load, 'ui_pause_actions'); " +
        "if e2r_world and e2r_world.pauseTab then return e2r_world.pauseTab() end; return false end)()",
        finish)
    } catch (err) {
      finish(false)
    }
    setTimeout(() => finish(false), 1500)
  })
}

export async function onLoad() {
  const { api, lua } = useBridge()
  if (await fromLua(api)) return
  const actions = lua?.extensions?.ui_pause_actions
  if (!actions?.registerModTab) return
  await actions.registerModTab({ id: TAB, label: "EarthNG", icon: "globe" })
  for (const button of BUTTONS) await actions.registerModButton({ ...button, tabId: TAB })
}

export async function onUnload() {
  const { lua } = useBridge()
  const actions = lua?.extensions?.ui_pause_actions
  if (actions?.unregisterModTab) await actions.unregisterModTab(TAB)
}
