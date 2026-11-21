// The look of the EarthNG tab, as one plain stylesheet put into the page once. The game's runtime
// compiles a mod's <style> blocks with a small SCSS subset that resolves no imports; three cards
// that share a frame, rows and buttons need one sheet, and plain CSS depends on nothing.
const ID = "earthng-pause-style"

const CSS = `
.eng-card{display:flex;flex-direction:column;width:100%;height:100%;min-height:0;box-sizing:border-box;
font-family:"Overpass",var(--fnt-defs,sans-serif);font-size:1rem;line-height:1.3;color:#fff;user-select:none}
.eng-card *{box-sizing:border-box}
.eng-head{display:flex;align-items:baseline;flex-wrap:wrap;gap:.6em;padding:.55em .8em;background:rgba(0,0,0,.35);
border-bottom:2px solid var(--bng-orange,#ff6600);flex:0 0 auto}
.eng-title{font-weight:800;letter-spacing:.04em;font-size:1.1em}
.eng-sub{color:rgba(255,255,255,.65);font-size:.9em}
.eng-body{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;padding:.2em .2em .8em}
.eng-body::-webkit-scrollbar{width:6px}
.eng-body::-webkit-scrollbar-thumb{background:rgba(255,255,255,.25);border-radius:3px}
.eng-empty{padding:1.2em .9em;color:rgba(255,255,255,.75)}
.eng-group{margin:.4em .3em 0;background:rgba(255,255,255,.04);border-radius:3px}
.eng-group.closed .eng-arrow{transform:rotate(-90deg)}
.eng-group.closed .eng-rows{display:none}
.eng-ghead{display:flex;align-items:center;width:100%;padding:.45em .6em;cursor:pointer;border:0;
background:rgba(255,255,255,.07);color:#fff;font:inherit;font-weight:700;text-transform:uppercase;font-size:.82em;
letter-spacing:.07em;border-radius:3px;text-align:left}
.eng-ghead:hover{background:rgba(255,102,0,.3)}
.eng-arrow{margin-left:auto;transition:transform .12s;opacity:.75}
.eng-count{margin-left:.6em;padding:0 .45em;border-radius:.6em;background:var(--bng-orange,#ff6600);font-size:.9em}
.eng-rows{padding:.15em .7em .5em}
.eng-bar{display:flex;flex-wrap:wrap;gap:.35em;padding:.5em .5em .2em}
.eng-btn{padding:.4em .8em;border:0;border-radius:3px;cursor:pointer;font:inherit;color:#fff;
background:rgba(255,255,255,.12);white-space:nowrap}
.eng-btn:hover{background:rgba(255,255,255,.24)}
.eng-btn.main,.eng-btn.on{background:var(--bng-orange,#ff6600);font-weight:700}
.eng-btn.main:hover{background:#ff8533}
.eng-btn:disabled{opacity:.4;cursor:default}
.eng-info{padding:.45em .8em .1em;color:rgba(255,255,255,.85)}
.eng-info strong{color:#ffb380}
.eng-mono{font-family:"Overpass Mono","Noto Sans Mono",monospace;font-size:.9em;color:rgba(255,255,255,.6);
word-break:break-word}

.eng-knob{padding:.45em 0 .35em;border-bottom:1px solid rgba(255,255,255,.07)}
.eng-knob:last-child{border-bottom:0}
.eng-knob.off{opacity:.45}
.eng-knob.marked .eng-knob-label{color:#ffb380}
.eng-knob-line{display:flex;align-items:center;gap:.6em}
.eng-knob-label{flex:1 1 auto;min-width:0}
.eng-knob-badge{margin-left:.5em;padding:.05em .45em;border-radius:.6em;background:rgba(255,102,0,.35);
font-size:.75em;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}
.eng-knob-hint{color:rgba(255,255,255,.55);font-size:.85em;margin-top:.1em}
.eng-knob-note{color:rgba(255,190,150,.9);font-size:.85em;margin-top:.15em}
.eng-knob-num{flex:0 0 auto;min-width:3.4em;text-align:right;font-family:"Overpass Mono","Noto Sans Mono",monospace;
color:#ffb380}
.eng-knob-reset{flex:0 0 auto;width:1.5em;height:1.5em;border:0;border-radius:50%;background:rgba(255,255,255,.14);
color:#fff;font:inherit;line-height:1;cursor:pointer;padding:0}
.eng-knob-reset:hover{background:var(--bng-orange,#ff6600)}
.eng-range{-webkit-appearance:none;appearance:none;width:100%;height:1.4em;margin:.25em 0 0;background:transparent;
cursor:pointer;--p:0%}
.eng-range:focus{outline:none}
.eng-range::-webkit-slider-runnable-track{height:4px;border-radius:2px;
background:linear-gradient(to right,var(--bng-orange,#ff6600) var(--p),rgba(255,255,255,.18) var(--p))}
.eng-range::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;margin-top:-5px;border-radius:50%;
background:#fff;border:2px solid var(--bng-orange,#ff6600)}
.eng-range:disabled{cursor:default}
.eng-seg{display:flex;flex-wrap:wrap;gap:2px;margin-top:.35em}
.eng-seg button{flex:1 1 auto;min-width:2.8em;padding:.32em .6em;border:0;border-radius:2px;cursor:pointer;font:inherit;
font-size:.92em;color:#fff;background:rgba(255,255,255,.1);white-space:nowrap}
.eng-seg button:hover{background:rgba(255,255,255,.2)}
.eng-seg button.on{background:var(--bng-orange,#ff6600);font-weight:700}
.eng-seg button:disabled{cursor:default}
.eng-switch{flex:0 0 auto;position:relative;width:2.6em;height:1.4em;border:0;border-radius:.7em;
background:rgba(255,255,255,.2);cursor:pointer;padding:0;transition:background .12s}
.eng-switch::after{content:"";position:absolute;top:.2em;left:.2em;width:1em;height:1em;border-radius:50%;
background:#fff;transition:left .12s}
.eng-switch.on{background:var(--bng-orange,#ff6600)}
.eng-switch.on::after{left:1.4em}
.eng-switch:disabled{cursor:default}

.eng-scope{display:flex;gap:2px;padding:.5em .5em 0}
.eng-scope button{flex:1 1 0;padding:.5em .6em;border:0;cursor:pointer;font:inherit;color:#fff;
background:rgba(255,255,255,.1)}
.eng-scope button:first-child{border-radius:3px 0 0 3px}
.eng-scope button:last-child{border-radius:0 3px 3px 0}
.eng-scope button.on{background:var(--bng-orange,#ff6600);font-weight:700}
.eng-state{display:inline-block;margin-left:.6em;padding:.05em .5em;border-radius:.6em;font-size:.82em;
background:rgba(255,255,255,.14)}
.eng-state.busy{background:#b34700}
.eng-state.ok{background:#2e7d32}

.eng-map{display:grid;gap:2px;padding:.5em;grid-template-columns:repeat(var(--cols,14),minmax(0,1fr))}
.eng-tile{aspect-ratio:1/1;min-height:2em;border:0;border-radius:2px;cursor:pointer;font:inherit;font-size:.8em;color:#fff;
padding:0;background:rgba(255,255,255,.1);overflow:hidden}
.eng-tile:hover{outline:2px solid #fff;outline-offset:-2px}
.eng-tile.here{box-shadow:inset 0 0 0 2px #fff}
.eng-tile.picked{outline:2px solid var(--bng-orange,#ff6600);outline-offset:-2px}
.eng-tile.touched::after{content:"•";color:#ffb380;margin-left:.1em}
.eng-z-classes{background:#5c6b7a}.eng-z-surfaces{background:#7a6a55}.eng-z-lanes{background:#4f6f8f}
.eng-z-town{background:#8a5a4a}.eng-z-works{background:#7d6a3c}.eng-z-street{background:#6b5a86}
.eng-z-covers{background:#5f7d3f}.eng-z-plants{background:#3f7d4f}.eng-z-water{background:#3d6f96}
.eng-z-relief{background:#75695c}.eng-z-junctions{background:#8f4f6a}.eng-z-studio{background:#9a8f7a}.eng-z-free{background:rgba(255,255,255,.08)}
.eng-legend{display:flex;flex-wrap:wrap;gap:.3em;padding:0 .5em .3em}
.eng-legend button{padding:.25em .6em;border:0;border-radius:2px;cursor:pointer;font:inherit;font-size:.85em;color:#fff}
.eng-legend button:hover{outline:2px solid #fff;outline-offset:-2px}
`

export function ensureStyle() {
  if (typeof document === "undefined" || document.getElementById(ID)) return
  const element = document.createElement("style")
  element.id = ID
  element.textContent = CSS
  document.head.appendChild(element)
}
