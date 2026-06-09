#!/usr/bin/env python3
"""Small browser UI for Afterglow diaries, emotion gauges, recall, and pulse state."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402
from afterglow_config import load_config  # noqa: E402


WORKSPACE = afterglow.WORKSPACE
BRAIN = afterglow.BRAIN
DIARY_DIR = Path(os.environ.get("AFTERGLOW_DIARY_DIR") or WORKSPACE / "memory" / "afterglow_diary")
SOUL_STATE = BRAIN / "soul_state.json"
EMOTIONAL_STATE = BRAIN / "context" / "emotional_state.md"
PULSE_STATE = BRAIN / "pulse_state.json"
DB_PATH = BRAIN / "memory_index" / "afterglow.sqlite"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def one_line(text: str, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean if len(clean) <= limit else clean[: max(0, limit - 3)].rstrip() + "..."


def api_summary() -> dict:
    try:
        data = afterglow.summary()
    except Exception as exc:
        data = {"error": str(exc), "db": str(DB_PATH)}
    data["config"] = load_config()
    data["pulse_state"] = load_json(PULSE_STATE, {})
    return data


def api_diaries(limit: int = 30) -> dict:
    rows = []
    if DIARY_DIR.exists():
        for path in sorted(DIARY_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            rows.append({"name": path.name, "mtime": path.stat().st_mtime, "summary": one_line(text, 520), "text": text})
    return {"diary_dir": str(DIARY_DIR), "entries": rows}


def api_emotion() -> dict:
    state = load_json(SOUL_STATE, {})
    text = EMOTIONAL_STATE.read_text(encoding="utf-8", errors="replace") if EMOTIONAL_STATE.exists() else ""
    drives = {}
    raw_drives = state.get("mood_drives") if isinstance(state.get("mood_drives"), dict) else {}
    for key, value in raw_drives.items():
        if isinstance(value, dict):
            drives[key] = float(value.get("value", value.get("intensity", 0)) or 0)
        else:
            try:
                drives[key] = float(value)
            except Exception:
                drives[key] = 0
    return {"state": state, "drives": drives, "markdown": text}


def api_recall(query: str, limit: int = 8) -> dict:
    if not query.strip():
        return {"query": query, "results": []}
    try:
        return {"query": query, "results": afterglow.semantic_recall(query, limit=limit)}
    except Exception as exc:
        return {"query": query, "error": str(exc), "results": []}


def api_tables() -> dict:
    if not DB_PATH.exists():
        return {"tables": {}}
    out = {}
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        for table in ("memories", "semantic_facts", "semantic_entities", "memory_recall_stats", "import_sources"):
            try:
                out[table] = con.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            except Exception:
                out[table] = 0
    return {"tables": out}


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Afterglow Companion System</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #67717f;
      --line: #d8dde5;
      --accent: #246bfe;
      --good: #1e9e69;
      --warn: #c07819;
      --bad: #c33b3b;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #101316;
        --panel: #171c21;
        --text: #eef2f6;
        --muted: #9aa6b2;
        --line: #2b333c;
        --accent: #7aa7ff;
      }
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Inter, system-ui, Segoe UI, Arial, sans-serif; background: var(--bg); color: var(--text); }
    header { display: flex; justify-content: space-between; align-items: center; padding: 16px 22px; border-bottom: 1px solid var(--line); background: var(--panel); position: sticky; top: 0; z-index: 2; }
    h1 { margin: 0; font-size: 18px; letter-spacing: 0; }
    main { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 16px; padding: 16px; }
    section, aside { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }
    h2 { margin: 0 0 12px; font-size: 15px; }
    .muted { color: var(--muted); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
    .stat { border: 1px solid var(--line); border-radius: 8px; padding: 10px; }
    .stat strong { display: block; font-size: 22px; }
    .gauge { margin: 10px 0; }
    .gauge label { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px; }
    .bar { height: 9px; background: rgba(127, 127, 127, .18); border-radius: 999px; overflow: hidden; }
    .bar span { display: block; height: 100%; background: var(--accent); width: 0%; }
    input, button { font: inherit; border-radius: 6px; border: 1px solid var(--line); padding: 9px 10px; background: var(--panel); color: var(--text); }
    button { background: var(--accent); color: white; border-color: transparent; cursor: pointer; }
    .search { display: flex; gap: 8px; margin-bottom: 12px; }
    .search input { flex: 1; }
    .item { border-top: 1px solid var(--line); padding: 10px 0; }
    .item:first-child { border-top: 0; }
    .item h3 { margin: 0 0 4px; font-size: 14px; }
    pre { white-space: pre-wrap; word-wrap: break-word; background: rgba(127,127,127,.12); padding: 10px; border-radius: 8px; max-height: 420px; overflow: auto; }
    @media (max-width: 860px) { main { grid-template-columns: 1fr; } header { align-items: flex-start; gap: 8px; flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <h1>Afterglow Companion System</h1>
    <div class="muted" id="workspace"></div>
  </header>
  <main>
    <aside>
      <h2>Emotional Gauges</h2>
      <div id="gauges"></div>
      <h2>Pulse</h2>
      <pre id="pulse"></pre>
    </aside>
    <div>
      <section>
        <h2>Memory Summary</h2>
        <div class="grid" id="stats"></div>
      </section>
      <section style="margin-top:16px">
        <h2>Recall Search</h2>
        <div class="search">
          <input id="query" placeholder="Search memory...">
          <button id="search">Search</button>
        </div>
        <div id="results"></div>
      </section>
      <section style="margin-top:16px">
        <h2>Recent Diaries</h2>
        <div id="diaries"></div>
      </section>
    </div>
  </main>
  <script>
    async function get(path) {
      const res = await fetch(path);
      return await res.json();
    }
    function esc(s) {
      return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    async function load() {
      const [summary, emotion, diaries] = await Promise.all([get('/api/summary'), get('/api/emotion'), get('/api/diaries')]);
      document.getElementById('workspace').textContent = summary.workspace || '';
      const tables = summary.tables || {};
      document.getElementById('stats').innerHTML = Object.entries(tables).map(([k,v]) => `<div class="stat"><span class="muted">${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');
      document.getElementById('pulse').textContent = JSON.stringify(summary.pulse_state || {}, null, 2);
      const drives = emotion.drives || {};
      document.getElementById('gauges').innerHTML = Object.entries(drives).map(([k,v]) => {
        const n = Math.max(0, Math.min(100, Number(v) || 0));
        return `<div class="gauge"><label><span>${esc(k.replaceAll('_',' '))}</span><span>${n.toFixed(0)}</span></label><div class="bar"><span style="width:${n}%"></span></div></div>`;
      }).join('') || '<p class="muted">No soul_state.json yet.</p>';
      document.getElementById('diaries').innerHTML = (diaries.entries || []).map(d => `<div class="item"><h3>${esc(d.name)}</h3><p>${esc(d.summary)}</p></div>`).join('') || '<p class="muted">No diary entries yet.</p>';
    }
    async function search() {
      const q = document.getElementById('query').value.trim();
      const data = await get('/api/recall?q=' + encodeURIComponent(q));
      document.getElementById('results').innerHTML = (data.results || []).map(r => `<div class="item"><h3>${esc(r.type)} ${esc(r.score)}</h3><p>${esc(r.summary || r.text)}</p><p class="muted">${esc(r.timestamp_iso || r.timestamp)} ${esc(r.source_kind || '')}</p></div>`).join('') || '<p class="muted">No results.</p>';
    }
    document.getElementById('search').addEventListener('click', search);
    document.getElementById('query').addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
    load();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                self.send_html(INDEX_HTML)
            elif parsed.path == "/api/summary":
                self.send_json(api_summary())
            elif parsed.path == "/api/tables":
                self.send_json(api_tables())
            elif parsed.path == "/api/diaries":
                self.send_json(api_diaries(int(qs.get("limit", ["30"])[0])))
            elif parsed.path == "/api/emotion":
                self.send_json(api_emotion())
            elif parsed.path == "/api/recall":
                self.send_json(api_recall(qs.get("q", [""])[0], int(qs.get("limit", ["8"])[0])))
            else:
                self.send_json({"error": "not found"}, status=404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> int:
    config = load_config()
    ui = config.get("ui") if isinstance(config.get("ui"), dict) else {}
    parser = argparse.ArgumentParser(description="Run Afterglow browser UI")
    parser.add_argument("--host", default=str(ui.get("host") or "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(ui.get("port") or 8765))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Afterglow UI: http://{args.host}:{args.port}")
    print(f"Workspace: {WORKSPACE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
