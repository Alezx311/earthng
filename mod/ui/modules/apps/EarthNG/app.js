// EarthNG settings in the game's own UI (docs/INGAME_UI.md). The page holds no settings of its own:
// it draws options.payload() that the world extension sends with the hook EarthNGOptions, and sends
// a change back with e2r_world.optionsSet(key, value). The controls are generated from the list, so
// a new option in Lua appears here with no change to this file.
// The game's CEF runs JS without a JIT: nothing here runs per frame, only on hooks and clicks.
angular.module('beamng.apps')
.directive('earthngOptions', [function () {
  var CSS = [
    '.eng{width:100%;height:100%;display:flex;flex-direction:column;overflow:hidden;box-sizing:border-box;',
    'font-family:"Overpass",var(--fnt-defs,sans-serif);font-size:13px;line-height:1.3;color:#fff;',
    'background:rgba(0,0,0,.55);border-radius:4px;padding:0;user-select:none}',
    '.eng *{box-sizing:border-box}',
    '.eng-head{display:flex;align-items:center;gap:.5em;padding:.55em .8em;background:rgba(0,0,0,.35);',
    'border-bottom:2px solid #ff6600;flex:0 0 auto}',
    '.eng-title{font-weight:800;letter-spacing:.04em;font-size:1.08em}',
    '.eng-sub{color:rgba(255,255,255,.6);font-size:.9em;margin-left:auto;white-space:nowrap}',
    '.eng-body{flex:1 1 auto;overflow-y:auto;overflow-x:hidden;padding:.2em .2em .6em}',
    '.eng-body::-webkit-scrollbar{width:6px}',
    '.eng-body::-webkit-scrollbar-thumb{background:rgba(255,255,255,.25);border-radius:3px}',
    '.eng-empty{padding:1.2em .9em;color:rgba(255,255,255,.7)}',
    '.eng-group{margin:.35em .3em 0;background:rgba(255,255,255,.04);border-radius:3px}',
    '.eng-ghead{display:flex;align-items:center;width:100%;padding:.45em .6em;cursor:pointer;border:0;',
    'background:rgba(255,255,255,.06);color:#fff;font:inherit;font-weight:700;text-transform:uppercase;',
    'font-size:.82em;letter-spacing:.07em;border-radius:3px;text-align:left}',
    '.eng-ghead:hover{background:rgba(255,102,0,.25)}',
    '.eng-arrow{margin-left:auto;transition:transform .12s;opacity:.75}',
    '.eng-group.closed .eng-arrow{transform:rotate(-90deg)}',
    '.eng-group.closed .eng-rows{display:none}',
    '.eng-rows{padding:.15em .6em .45em}',
    '.eng-row{padding:.45em 0 .3em;border-bottom:1px solid rgba(255,255,255,.06)}',
    '.eng-row:last-child{border-bottom:0}',
    '.eng-row.off{opacity:.42}',
    '.eng-line{display:flex;align-items:center;gap:.6em}',
    '.eng-label{flex:1 1 auto;min-width:0}',
    '.eng-hint{color:rgba(255,255,255,.5);font-size:.85em;margin-top:.1em}',
    '.eng-note{color:rgba(255,190,150,.85);font-size:.85em;margin-top:.15em}',
    '.eng-note:empty{display:none}',
    '.eng-num{flex:0 0 auto;min-width:3.2em;text-align:right;font-family:"Noto Sans Mono",monospace;',
    'color:#ffb380;font-size:.95em}',
    '.eng-range{-webkit-appearance:none;appearance:none;width:100%;height:1.4em;margin:.25em 0 0;',
    'background:transparent;cursor:pointer;--p:0%}',
    '.eng-range:focus{outline:none}',
    '.eng-range::-webkit-slider-runnable-track{height:4px;border-radius:2px;',
    'background:linear-gradient(to right,#ff6600 var(--p),rgba(255,255,255,.18) var(--p))}',
    '.eng-range::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;margin-top:-5px;',
    'border-radius:50%;background:#fff;border:2px solid #ff6600}',
    '.eng-range:disabled{cursor:default}',
    '.eng-seg{display:flex;flex-wrap:wrap;gap:2px;margin-top:.35em}',
    '.eng-seg button{flex:1 1 0;min-width:2.8em;padding:.32em .4em;border:0;border-radius:2px;cursor:pointer;',
    'font:inherit;font-size:.92em;color:#fff;background:rgba(255,255,255,.1);white-space:nowrap}',
    '.eng-seg button:hover{background:rgba(255,255,255,.2)}',
    '.eng-seg button.on{background:#ff6600;color:#fff;font-weight:700}',
    '.eng-seg button:disabled,.eng-switch:disabled{cursor:default}',
    '.eng-switch{flex:0 0 auto;position:relative;width:2.6em;height:1.4em;border:0;border-radius:.7em;',
    'background:rgba(255,255,255,.2);cursor:pointer;padding:0;transition:background .12s}',
    '.eng-switch::after{content:"";position:absolute;top:.2em;left:.2em;width:1em;height:1em;border-radius:50%;',
    'background:#fff;transition:left .12s}',
    '.eng-switch.on{background:#ff6600}',
    '.eng-switch.on::after{left:1.4em}'
  ].join('')

  // (Ukrainian as \u escapes: the file stays ASCII whatever charset the game's UI reads it with)
  var TEXT = {
    uk: {sub: '\u043D\u0430\u043B\u0430\u0448\u0442\u0443\u0432\u0430\u043D\u043D\u044F', empty: '\u041D\u0430\u043B\u0430\u0448\u0442\u0443\u0432\u0430\u043D\u043D\u044F EarthNG \u0437\u2019\u044F\u0432\u043B\u044F\u0442\u044C\u0441\u044F, \u0449\u043E\u0439\u043D\u043E \u043C\u043E\u0434 \u0437\u0430\u0432\u0430\u043D\u0442\u0430\u0436\u0438\u0442\u044C\u0441\u044F.',
      off: '\u0414\u043E\u0441\u0442\u0443\u043F\u043D\u043E \u043F\u0456\u0441\u043B\u044F \u0432\u0438\u0441\u0430\u0434\u043A\u0438'},
    en: {sub: 'settings', empty: 'EarthNG settings appear once the mod has loaded.',
      off: 'Available after landing'}
  }

  var LIVE_MS = 100   // a live slider sends at most ~10 values a second while it moves

  // only plain ids and numbers go into the Lua call
  function luaValue(v) {
    if (typeof v === 'boolean') return v ? 'true' : 'false'
    if (typeof v === 'number' && isFinite(v)) return String(v)
    var s = String(v)
    return /^[A-Za-z0-9_.\-]*$/.test(s) ? '"' + s + '"' : 'nil'
  }

  // the game's JSON encoder writes an empty Lua table as {}: lists are read through this
  function arr(x) { return Array.isArray(x) ? x : [] }

  function el(tag, cls, text) {
    var e = document.createElement(tag)
    if (cls) e.className = cls
    if (text !== undefined) e.textContent = text
    return e
  }

  function decimals(step) {
    var s = String(step || 1)
    var i = s.indexOf('.')
    return i < 0 ? 0 : s.length - i - 1
  }

  return {
    template: '<div class="bngApp eng"><style>' + CSS + '</style>' +
      '<div class="eng-head"><span class="eng-title">EarthNG</span><span class="eng-sub"></span></div>' +
      '<div class="eng-body"><div class="eng-empty"></div></div></div>',
    replace: true,
    restrict: 'EA',
    scope: true,
    link: function (scope, element) {
      var root = element[0]
      var body = root.querySelector('.eng-body')
      var sub = root.querySelector('.eng-sub')
      var lang = 'uk'
      var shape = null        // what the drawn controls were built from
      var controls = {}       // key -> {set(value, disabled)}
      var dragging = null     // the slider under the mouse: a push does not move it
      var closed = {}
      try { closed = JSON.parse(localStorage.getItem('earthng.options.closed') || '{}') || {} } catch (e) { closed = {} }

      function tr(label) { return label ? (label[lang] || label.en || label.uk || '') : '' }
      function lua(code) { bngApi.engineLua(code) }
      function send(key, value) {
        lua('if e2r_world and e2r_world.optionsSet then e2r_world.optionsSet(' + luaValue(key) + ', ' + luaValue(value) + ') end')
      }
      function request() { lua('if e2r_world and e2r_world.optionsList then e2r_world.optionsList() end') }

      function showEmpty() {
        sub.textContent = TEXT[lang].sub
        body.innerHTML = ''
        body.appendChild(el('div', 'eng-empty', TEXT.uk.empty + ' / ' + TEXT.en.empty))
      }

      function shapeOf(data) {
        var parts = [data.lang]
        ;arr(data.groups).forEach(function (g) {
          parts.push('#' + g.key)
          ;arr(g.options).forEach(function (o) {
            parts.push(o.key, o.kind, o.min, o.max, o.step, o.disabled ? 1 : 0)
            arr(o.values).forEach(function (v) { parts.push(v.value) })
          })
        })
        return parts.join('|')
      }

      function rowFor(o) {
        var row = el('div', 'eng-row')
        var line = el('div', 'eng-line')
        var label = el('div', 'eng-label', tr(o.label))
        line.appendChild(label)
        row.appendChild(line)
        var hintText = o.disabled ? TEXT[lang].off : tr(o.hint)
        if (hintText) row.appendChild(el('div', 'eng-hint', hintText))
        if (o.disabled) row.classList.add('off')
        var ctl = {}

        if (o.kind === 'bool') {
          var sw = el('button', 'eng-switch')
          sw.setAttribute('role', 'switch')
          sw.disabled = !!o.disabled
          line.appendChild(sw)
          ctl.set = function (v) { ctl.value = !!v; sw.classList.toggle('on', ctl.value); sw.setAttribute('aria-checked', ctl.value) }
          sw.addEventListener('click', function () { ctl.set(!ctl.value); send(o.key, ctl.value); sw.blur() })
        } else if (o.kind === 'int' || o.kind === 'float') {
          var num = el('span', 'eng-num')
          line.appendChild(num)
          var range = el('input', 'eng-range')
          range.type = 'range'
          range.min = o.min; range.max = o.max; range.step = o.step || (o.kind === 'int' ? 1 : 'any')
          range.disabled = !!o.disabled
          row.appendChild(range)
          var digits = o.kind === 'int' ? 0 : decimals(o.step)
          var paint = function (v) {
            num.textContent = Number(v).toFixed(digits)
            var p = o.max > o.min ? (v - o.min) / (o.max - o.min) * 100 : 0
            range.style.setProperty('--p', Math.max(0, Math.min(100, p)) + '%')
          }
          ctl.set = function (v) {
            if (dragging === o.key) return
            range.value = v
            paint(v)
          }
          // o.live: cheap to apply, so the value goes while the slider moves, at most every
          // LIVE_MS; the final one always goes on release. Otherwise only on release (one rebuild).
          var lastAt = 0, lastSent = null
          var push = function (v) { lastSent = v; send(o.key, v) }
          range.addEventListener('input', function () {
            dragging = o.key
            paint(range.value)
            var now = Date.now()
            if (o.live && now - lastAt >= LIVE_MS) { lastAt = now; push(Number(range.value)) }
          })
          range.addEventListener('change', function () {
            dragging = null
            var v = Number(range.value)
            if (!o.live || v !== lastSent) push(v)
            range.blur()                                   // arrow keys go back to driving
          })
        } else if (o.kind === 'enum') {
          var seg = el('div', 'eng-seg')
          var buttons = []
          ;arr(o.values).forEach(function (v) {
            var b = el('button', '', tr(v.label))
            b.disabled = !!o.disabled
            b.addEventListener('click', function () { ctl.set(v.value); send(o.key, v.value); b.blur() })
            buttons.push({b: b, value: v.value})
            seg.appendChild(b)
          })
          row.appendChild(seg)
          ctl.set = function (v) {
            buttons.forEach(function (x) { x.b.classList.toggle('on', x.value === v) })
          }
        } else {
          ctl.set = function () {}
        }
        // a line of live state under the control (options.lua note), refreshed with every push
        var note = el('div', 'eng-note')
        row.appendChild(note)
        ctl.note = function (n) { var t = tr(n); if (note.textContent !== t) note.textContent = t }
        ctl.set(o.value)
        ctl.note(o.note)
        controls[o.key] = ctl
        return row
      }

      function build(data) {
        controls = {}
        body.innerHTML = ''
        ;arr(data.groups).forEach(function (g) {
          var box = el('div', 'eng-group')
          if (closed[g.key] === undefined ? g.collapsed : closed[g.key]) box.classList.add('closed')
          var head = el('button', 'eng-ghead')
          head.appendChild(el('span', '', tr(g.label)))
          head.appendChild(el('span', 'eng-arrow', '\u25BE'))
          head.addEventListener('click', function () {
            var isClosed = !box.classList.contains('closed')
            box.classList.toggle('closed', isClosed)
            closed[g.key] = isClosed
            try { localStorage.setItem('earthng.options.closed', JSON.stringify(closed)) } catch (e) {}
            head.blur()
          })
          box.appendChild(head)
          var rows = el('div', 'eng-rows')
          ;arr(g.options).forEach(function (o) { rows.appendChild(rowFor(o)) })
          box.appendChild(rows)
          body.appendChild(box)
        })
      }

      function render(data) {
        if (!data || !data.groups) { showEmpty(); return }
        lang = data.lang === 'en' ? 'en' : 'uk'
        sub.textContent = TEXT[lang].sub
        var s = shapeOf(data)
        if (s !== shape) {               // new options, another language, availability: draw anew
          shape = s
          build(data)
          return
        }
        arr(data.groups).forEach(function (g) {   // the same controls: only the values move
          ;arr(g.options).forEach(function (o) {
            var c = controls[o.key]
            if (c) { c.set(o.value); c.note(o.note) }
          })
        })
      }

      // also sent unasked: on every change and after the world extension (re)loads
      scope.$on('EarthNGOptions', function (event, data) { render(data) })
      showEmpty()
      request()
    }
  }
}])
