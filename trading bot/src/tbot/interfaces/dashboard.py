"""A local, read-only web dashboard, served from the standard library.

Design constraints, all deliberate:

* **Read-only.** The page shows state; it cannot send an order, move a stop or
  pause the bot. Commands go through Telegram, so there is exactly one control
  path to secure rather than two.
* **Localhost only.** The server binds ``127.0.0.1`` by default. Nothing on the
  network can reach it, which is the correct default for something that reveals
  account balance and open positions.
* **No database access from the web thread.** The page is fed by a snapshot dict
  and a ring buffer of recent events, both updated by the trading thread. SQLite
  connections are not shared across threads, and a dashboard query must never be
  able to block or lock the journal the bot is writing to.
* **No external assets.** The HTML, CSS and JavaScript are inline. A dashboard
  that needs a CDN stops working exactly when you most want it: offline, on a
  VPS, at 3am.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..engine.events import Event
from ..obs import log as obs_log

MAX_EVENTS = 300


class DashboardState:
    """Thread-safe snapshot the web thread reads and the trading thread writes."""

    def __init__(self, max_events: int = MAX_EVENTS) -> None:
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {"started": False}
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._equity: deque[dict[str, Any]] = deque(maxlen=2000)

    def update_status(self, status: dict[str, Any]) -> None:
        with self._lock:
            self._status = dict(status)
            equity = status.get("equity")
            if isinstance(equity, (int, float)):
                self._equity.append(
                    {"ts": datetime.now(timezone.utc).isoformat(), "equity": float(equity)}
                )

    def on_event(self, event: Event) -> None:
        with self._lock:
            self._events.appendleft(event.to_dict())

    def payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": dict(self._status),
                "events": list(self._events),
                "equity": list(self._equity),
                "served_at": datetime.now(timezone.utc).isoformat(),
            }


class _Handler(BaseHTTPRequestHandler):
    state: DashboardState  # injected by DashboardServer
    server_version = "tbot"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        pass  # the access log is noise; real events go to the JSONL log

    def _send(self, body: bytes, content_type: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Defence in depth for a page that is localhost-only anyway.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - required name
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/state":
            body = json.dumps(self.state.payload(), default=str).encode("utf-8")
            self._send(body, "application/json; charset=utf-8")
        elif path == "/healthz":
            self._send(b'{"ok":true}', "application/json")
        else:
            self._send(b"not found", "text/plain; charset=utf-8", code=404)


class DashboardServer:
    """Runs the HTTP server on a background thread."""

    def __init__(self, state: DashboardState, host: str = "127.0.0.1", port: int = 8787) -> None:
        self.state = state
        self.host = host
        self.port = port
        self.log = obs_log.get("dashboard")
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> None:
        if self._server is not None:
            return
        handler = type("BoundHandler", (_Handler,), {"state": self.state})
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="dashboard", daemon=True
        )
        self._thread.start()
        self.log.info("dashboard on %s", self.url, extra={"event": "dashboard_start"})

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>tbot</title>
<style>
:root{--bg:#f7f7f8;--card:#fff;--fg:#17171a;--muted:#6b6b76;--line:#e3e3e8;
      --up:#0a7d4f;--down:#b3261e;--accent:#2f6fed}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e7e9ee;
      --muted:#9aa0ad;--line:#262b35;--up:#3fbf87;--down:#ef6b61;--accent:#6c9bff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;
       padding:16px 20px;border-bottom:1px solid var(--line)}
h1{font-size:16px;margin:0;letter-spacing:.02em}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted);display:inline-block}
.dot.live{background:var(--up)}.dot.paused{background:#d4a017}
main{padding:20px;display:grid;gap:16px;max-width:1100px;margin:0 auto}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
         color:var(--muted);margin:0 0 10px}
.big{font-size:24px;font-variant-numeric:tabular-nums}
.up{color:var(--up)}.down{color:var(--down)}.muted{color:var(--muted)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.scroll{overflow-x:auto}
.ev{display:grid;grid-template-columns:64px 78px 1fr;gap:10px;padding:6px 0;
    border-bottom:1px solid var(--line);align-items:baseline}
.tag{font-size:11px;padding:1px 7px;border-radius:99px;border:1px solid var(--line);
     text-align:center;color:var(--muted)}
.tag.order{color:var(--accent);border-color:var(--accent)}
.tag.closed{color:var(--up);border-color:var(--up)}
.tag.declined,.tag.error{color:var(--down);border-color:var(--down)}
#spark{width:100%;height:56px;display:block}
footer{padding:0 20px 24px;color:var(--muted);font-size:12px}
</style></head><body>
<header>
  <h1>tbot</h1>
  <span><span class="dot" id="dot"></span> <span id="mode" class="muted">connecting…</span></span>
  <span class="muted" id="clock" style="margin-left:auto"></span>
</header>
<main>
  <div class="grid">
    <div class="card"><h2>Balance</h2><div class="big" id="balance">–</div>
      <div class="muted" id="equity"></div></div>
    <div class="card"><h2>Today</h2><div class="big" id="daypnl">–</div>
      <div class="muted" id="daytrades"></div></div>
    <div class="card"><h2>Open positions</h2><div class="big" id="poscount">–</div>
      <div class="muted" id="posrisk"></div></div>
    <div class="card"><h2>Equity</h2><canvas id="spark"></canvas></div>
  </div>

  <div class="card"><h2>Positions</h2><div class="scroll"><table id="positions">
    <thead><tr><th>Symbol</th><th>Side</th><th>Volume</th><th>Entry</th>
    <th>SL</th><th>TP</th><th>Open P/L</th></tr></thead><tbody></tbody></table></div></div>

  <div class="card"><h2>Strategy state</h2><div class="scroll"><table id="phases">
    <thead><tr><th>Symbol</th><th>Phase</th><th>Structure</th><th>Last rejection</th></tr></thead>
    <tbody></tbody></table></div></div>

  <div class="card"><h2>Recent activity</h2><div id="events"></div></div>
</main>
<footer>Read-only view. Commands go through Telegram. Refreshes every 2s.</footer>
<script>
const fmt = (n, d = 2) => (n === undefined || n === null || isNaN(n)) ? '–'
  : Number(n).toLocaleString(undefined, {minimumFractionDigits: d, maximumFractionDigits: d});
const el = id => document.getElementById(id);
const txt = (id, v) => { el(id).textContent = v; };

function sparkline(points) {
  const c = el('spark'), w = c.clientWidth || 300, h = 56;
  c.width = w * devicePixelRatio; c.height = h * devicePixelRatio;
  const g = c.getContext('2d'); g.scale(devicePixelRatio, devicePixelRatio);
  g.clearRect(0, 0, w, h);
  if (points.length < 2) return;
  const ys = points.map(p => p.equity), lo = Math.min(...ys), hi = Math.max(...ys);
  const span = (hi - lo) || 1;
  const style = getComputedStyle(document.documentElement);
  g.strokeStyle = style.getPropertyValue(ys[ys.length - 1] >= ys[0] ? '--up' : '--down').trim();
  g.lineWidth = 1.5; g.beginPath();
  ys.forEach((y, i) => {
    const x = (i / (ys.length - 1)) * (w - 2) + 1;
    const py = h - 4 - ((y - lo) / span) * (h - 8);
    i ? g.lineTo(x, py) : g.moveTo(x, py);
  });
  g.stroke();
}

function render(d) {
  const s = d.status || {};
  el('dot').className = 'dot ' + (s.started ? (s.paused ? 'paused' : 'live') : '');
  txt('mode', s.started
    ? `${s.mode} on ${s.broker}${s.paused ? ' — PAUSED' : ''}` : 'not running');
  txt('clock', new Date(d.served_at).toLocaleTimeString());
  txt('balance', fmt(s.balance));
  txt('equity', 'equity ' + fmt(s.equity));
  const pnl = s.day_pnl || 0;
  const pe = el('daypnl');
  pe.textContent = (pnl >= 0 ? '+' : '') + fmt(pnl);
  pe.className = 'big ' + (pnl > 0 ? 'up' : pnl < 0 ? 'down' : '');
  txt('daytrades', `${s.day_trades || 0} trade(s) closed`);

  const pos = s.positions || [];
  txt('poscount', pos.length);
  txt('posrisk', `${(s.symbols || []).length} symbol(s) watched`);

  const pb = document.querySelector('#positions tbody');
  pb.innerHTML = pos.length ? '' : '<tr><td colspan="7" class="muted">none</td></tr>';
  pos.forEach(p => {
    const tr = document.createElement('tr');
    const cls = (p.pnl || 0) >= 0 ? 'up' : 'down';
    tr.innerHTML = `<td>${p.symbol}</td><td>${p.side}</td><td>${p.volume}</td>
      <td>${p.entry}</td><td>${p.sl}</td><td>${p.tp}</td>
      <td class="${cls}">${fmt(p.pnl)}</td>`;
    pb.appendChild(tr);
  });

  const phases = s.phases || {};
  const fb = document.querySelector('#phases tbody');
  const keys = Object.keys(phases);
  fb.innerHTML = keys.length ? '' : '<tr><td colspan="4" class="muted">none</td></tr>';
  keys.forEach(k => {
    const v = phases[k] || {}, snap = v.snapshot || {};
    const structure = snap.available
      ? `${snap.status} · ${snap.bias || ''}` : (snap.available === false ? 'no snapshot' : '–');
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${k}</td><td>${v.phase || '–'}</td><td class="muted">${structure}</td>
      <td class="muted">${(v.last_reject || '').slice(0, 70)}</td>`;
    fb.appendChild(tr);
  });

  const ev = el('events');
  ev.innerHTML = (d.events || []).length ? '' : '<div class="muted">nothing yet</div>';
  (d.events || []).slice(0, 60).forEach(e => {
    const row = document.createElement('div');
    row.className = 'ev';
    const when = new Date(e.ts).toLocaleTimeString();
    const detail = e.kind === 'order'
        ? `${e.side} ${e.volume} @ ${e.price} — ${e.reason || ''}`
      : e.kind === 'closed'
        ? `${e.side} ${e.volume} pnl ${fmt(e.pnl)} (${e.reason})`
      : e.kind === 'declined' ? e.reason
      : e.kind === 'exit' ? e.reason
      : e.kind === 'signal' ? `${e.side} @ ${e.price} RR ${e.rr}`
      : (e.message || e.reason || '');
    row.innerHTML = `<span class="muted">${when}</span>
      <span class="tag ${e.kind}">${e.kind}</span>
      <span>${e.symbol ? '<b>' + e.symbol + '</b> ' : ''}${detail}</span>`;
    ev.appendChild(row);
  });

  sparkline(d.equity || []);
}

async function tick() {
  try {
    const r = await fetch('/api/state', {cache: 'no-store'});
    render(await r.json());
  } catch (e) {
    txt('mode', 'disconnected');
    el('dot').className = 'dot';
  }
}
tick(); setInterval(tick, 2000);
</script></body></html>
"""
