// EarthNG in a browser (earthng/app_web.py, the Linux package): the window.ipc that EarthNG.exe's
// WebView2 gives the page. Messages go out as POST /ipc, the service's lines come back as
// server-sent events on /events and reach window.earthng.receive as they do in the exe.
'use strict';
(() => {
  const key = window.EARTHNG_KEY || '';
  window.EARTHNG_WEB = true;
  const deliver = message => { if (window.earthng) window.earthng.receive(message); };
  const fail = (text, error) => {
    let id = null;
    try { id = JSON.parse(text).id; } catch (_) { /* not JSON: no answer to make */ }
    if (id != null) deliver({ id, ok: false, error });
  };
  window.ipc = {
    postMessage(text) {
      fetch('ipc', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-EarthNG-Key': key }, body: text })
        .then(r => { if (!r.ok) fail(text, `EarthNG answered ${r.status}`); })
        .catch(() => fail(text, 'EarthNG is not running: start it again'));
    },
  };
  const source = new EventSource(`events?k=${encodeURIComponent(key)}`);
  source.onmessage = e => {
    let message;
    try { message = JSON.parse(e.data); } catch (_) { return; }
    deliver(message);
  };
})();
