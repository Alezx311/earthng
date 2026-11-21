// The page's calls into the world extension (world.lua). Only plain ids, numbers and booleans go
// into a Lua call: a value that is none of them is sent as nil.
import { useBridge } from "@/bridge"

export function luaValue(v) {
  if (v === null || v === undefined) return "nil"
  if (typeof v === "boolean") return v ? "true" : "false"
  if (typeof v === "number" && isFinite(v)) return String(v)
  const s = String(v)
  return /^[A-Za-z0-9_.:\-]*$/.test(s) ? '"' + s + '"' : "nil"
}

// world("labSet", "crown", 0.03, "tile") -> e2r_world.labSet("crown", 0.03, "tile")
export function world(name, ...args) {
  const { api } = useBridge()
  api.engineLua(
    "if e2r_world and e2r_world." + name + " then e2r_world." + name + "(" + args.map(luaValue).join(", ") + ") end")
}

// the game's JSON encoder writes an empty Lua table as {}: lists are read through this
export function list(x) {
  return Array.isArray(x) ? x : []
}

export function text(label, lang) {
  if (!label) return ""
  if (typeof label === "string") return label
  return label[lang] || label.en || label.uk || ""
}
