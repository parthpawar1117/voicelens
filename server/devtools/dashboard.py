"""Live test dashboard for VoiceLens. Standard library only.

Run from the repo root:
    server/.venv/Scripts/python server/devtools/dashboard.py
Then open http://127.0.0.1:8800

It watches the source and test folders. Whenever a file changes it re-runs the
server tests (pytest) and the glasses-app tests (Vitest), and the page updates
itself every 2 seconds. It also shows the latest real voice-note run
(server/tmp/last_run.json, written by try_transcribe.py) and recent commits.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
APP = ROOT / "g2-app"
TMP = SERVER / "tmp"
WATCH = [APP / "src", SERVER / "voicelens", SERVER / "tests", SERVER / "devtools"]
PORT = 8800


# ---------- parsers (tested) ----------

def parse_junit(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    tests = []
    for case in root.iter("testcase"):
        status, message = "passed", ""
        for tag in ("failure", "error"):
            node = case.find(tag)
            if node is not None:
                status, message = "failed", node.get("message", "")
        if case.find("skipped") is not None:
            status = "skipped"
        tests.append({
            "file": case.get("classname", "").split(".")[-1],
            "name": case.get("name", ""),
            "status": status,
            "ms": round(float(case.get("time", 0)) * 1000, 1),
            "message": message,
        })
    return tests


def parse_vitest(data: dict) -> list[dict]:
    tests = []
    for file_result in data.get("testResults", []):
        file_name = Path(file_result.get("name", "")).name
        for a in file_result.get("assertionResults", []):
            name = " > ".join([*a.get("ancestorTitles", []), a.get("title", "")])
            tests.append({
                "file": file_name,
                "name": name,
                "status": a.get("status", "unknown"),
                "ms": a.get("duration") or 0,
                "message": " ".join(a.get("failureMessages", []))[:300],
            })
    return tests


# ---------- runners ----------

def run_pytest() -> list[dict]:
    TMP.mkdir(exist_ok=True)
    report = TMP / "pytest.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"--junitxml={report}"],
        cwd=SERVER, capture_output=True, text=True,
    )
    return parse_junit(report.read_text(encoding="utf-8")) if report.exists() else []


def run_vitest() -> list[dict]:
    TMP.mkdir(exist_ok=True)
    report = TMP / "vitest.json"
    entry = APP / "node_modules" / "vitest" / "vitest.mjs"
    if not entry.exists():
        return []
    subprocess.run(
        ["node", str(entry), "run", "--reporter=json", f"--outputFile={report}"],
        cwd=APP, capture_output=True, text=True,
    )
    try:
        return parse_vitest(json.loads(report.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return []


def recent_commits(n: int = 8) -> list[str]:
    out = subprocess.run(
        ["git", "log", f"-{n}", "--pretty=%h  %ad  %s", "--date=format:%H:%M"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return out.stdout.strip().splitlines()


def live_feed() -> dict | None:
    path = TMP / "live_feed.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def last_real_run() -> dict | None:
    path = TMP / "last_run.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------- state + watcher ----------

STATE: dict = {"running": True, "suites": {}, "ran_at": None, "runs": 0}
LOCK = threading.Lock()


def snapshot_mtime() -> float:
    newest = 0.0
    for folder in WATCH:
        for f in folder.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                newest = max(newest, f.stat().st_mtime)
    return newest


def run_all() -> None:
    with LOCK:
        STATE["running"] = True
    started = time.perf_counter()
    suites = {"Glasses app (Vitest)": run_vitest(), "Server (pytest)": run_pytest()}
    with LOCK:
        STATE.update(
            running=False, suites=suites, runs=STATE["runs"] + 1,
            ran_at=datetime.now().strftime("%H:%M:%S"),
            seconds=round(time.perf_counter() - started, 1),
        )


def watch_forever() -> None:
    last = None
    while True:
        current = snapshot_mtime()
        if current != last:
            last = current
            run_all()
        time.sleep(2)


# ---------- web ----------

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoiceLens · live tests</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#141614;color:#e6e6e6;font:14px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:28px 0 10px;color:#bdbdbd}
.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.pill{padding:4px 12px;border-radius:999px;font-size:12px;border:1px solid #3a3a3a}
.ok{color:#3cfa44;border-color:#3cfa44}.bad{color:#ff5a4f;border-color:#ff5a4f}.run{color:#e0c341;border-color:#e0c341}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px}
.stat{background:#1d201d;border:1px solid #2c302c;border-radius:10px;padding:14px}
.stat b{display:block;font-size:26px}.stat span{color:#9a9a9a;font-size:12px}
table{width:100%;border-collapse:collapse;background:#1d201d;border:1px solid #2c302c;border-radius:10px;overflow:hidden}
td,th{padding:8px 12px;border-bottom:1px solid #262a26;text-align:left;vertical-align:top}
th{color:#9a9a9a;font-weight:500;font-size:12px}td.s{width:28px}td.ms{width:80px;color:#9a9a9a;text-align:right}
.file{color:#9a9a9a;font-size:12px}.msg{color:#ff8a80;font-size:12px}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;color:#cfcfcf;white-space:pre}
.voice td{font-size:13px}.src{color:#3cfa44}
</style></head><body><main>
<div class="top"><h1>VoiceLens · live test dashboard</h1><span id="badge" class="pill run">starting…</span></div>
<h2>Live transcription <span id="livebadge" class="pill">listener not running</span></h2>
<div class="stats">
 <div class="stat"><b id="l_count">–</b><span>notes transcribed</span></div>
 <div class="stat"><b id="l_avg">–</b><span>avg transcription time</span></div>
 <div class="stat"><b id="l_total">–</b><span>avg send → text ready</span></div>
 <div class="stat"><b id="l_factor">–</b><span>avg speed factor (below 1× = faster than audio)</span></div>
</div>
<div id="live" style="margin-top:12px"></div>
<h2>Tests</h2>
<div class="stats">
 <div class="stat"><b id="total">–</b><span>tests</span></div>
 <div class="stat"><b id="passed" style="color:#3cfa44">–</b><span>passed</span></div>
 <div class="stat"><b id="failed">–</b><span>failed</span></div>
 <div class="stat"><b id="when">–</b><span id="whenlbl">last run</span></div>
</div>
<div id="suites"></div>
<h2>Latest real voice-note run</h2><div id="voice"></div>
<h2>Recent commits</h2><div id="commits" class="mono"></div>
</main><script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const icon={passed:'✅',failed:'❌',skipped:'⏭️'};
async function tick(){
 let s; try{ s=await (await fetch('/api/state')).json() }catch(e){ return }
 const all=Object.values(s.suites).flat(), f=all.filter(t=>t.status==='failed').length;
 // Look elements up explicitly: Chrome now defines a global `when`, which
 // shadows the implicit id-global for <b id="when">.
 $('total').textContent=all.length; $('passed').textContent=all.filter(t=>t.status==='passed').length;
 $('failed').textContent=f; $('failed').style.color=f?'#ff5a4f':'#e6e6e6';
 $('when').textContent=s.ran_at||'–'; $('whenlbl').textContent=`last run · ${s.seconds??'–'} s · run #${s.runs}`;
 $('badge').className='pill '+(s.running?'run':f?'bad':'ok');
 $('badge').textContent=s.running?'running tests…':f?`${f} failing`:'all passing';
 $('suites').innerHTML=Object.entries(s.suites).map(([name,tests])=>{
  const p=tests.filter(t=>t.status==='passed').length;
  return `<h2>${esc(name)} — ${p}/${tests.length} passing</h2><table>`+
  tests.map(t=>`<tr><td class="s">${icon[t.status]||'•'}</td><td>${esc(t.name)}<div class="file">${esc(t.file)}</div>${t.message?`<div class="msg">${esc(t.message)}</div>`:''}</td><td class="ms">${(+t.ms).toFixed(1)} ms</td></tr>`).join('')+'</table>'}).join('');
 const v=s.voice;
 $('voice').innerHTML=!v?'<p class="file">No real run yet. Run server/try_transcribe.py.</p>':
  `<p class="file">Ran at ${esc(v.ran_at)}</p><table class="voice"><tr><th>Note</th><th>Engine</th><th>Time</th><th>Text on glasses</th></tr>`+
  v.notes.map(n=>`<tr><td>${esc(n.duration)} s</td><td class="src">${esc(n.source||'—')}</td><td>${n.seconds??'–'} s</td><td>${esc(n.text||n.error)}</td></tr>`).join('')+'</table>';
 $('commits').textContent=(s.commits||[]).join('\\n');
 const L=s.live, lb=$('livebadge');
 if(!L){ lb.className='pill'; lb.textContent='listener not running';
  $('live').innerHTML='<p class="file">Start it: server\\\\.venv\\\\Scripts\\\\python server\\\\devtools\\\\live_listener.py</p>'; return }
 lb.className='pill '+(L.processing?'run':L.listening&&L.model_ready?'ok':L.listening?'run':'bad');
 lb.textContent=L.processing?`transcribing ${L.processing}…`:!L.listening?'listener stopped':!L.model_ready?'loading model…':`listening on ${L.device==='cuda'?'GPU':(L.device||'CPU').toUpperCase()} · send a voice note`;
 const m=L.summary||{};
 $('l_count').textContent=m.count??0;
 $('l_avg').textContent=m.avg_transcribe_s!=null?m.avg_transcribe_s+' s':'–';
 $('l_total').textContent=m.avg_total_s!=null?m.avg_total_s+' s':'–';
 $('l_factor').textContent=m.avg_speed_factor!=null?m.avg_speed_factor+'×':'–';
 $('live').innerHTML=!L.feed.length?'<p class="file">Waiting for your first voice note in Saved Messages…</p>':
  '<table><tr><th>Received</th><th>Audio</th><th>Engine</th><th>Download</th><th>Transcribe</th><th>Send → ready</th><th>Speed</th><th>Text on glasses</th></tr>'+
  L.feed.map(e=>e.error?`<tr><td>${esc(e.received)}</td><td>${esc(e.duration)} s</td><td colspan="6" class="msg">${esc(e.error)}</td></tr>`:
   `<tr><td>${esc(e.received)}</td><td>${(+e.duration).toFixed(0)} s</td><td class="src">${esc(e.source)}</td><td>${e.download_s} s</td><td><b>${e.transcribe_s} s</b>${e.steps&&e.steps.model_s!=null?`<div class="file">model ${e.steps.model_s} · decode ${e.steps.decode_s} · wait ${e.steps.thread_wait_s}</div>`:''}</td><td>${e.total_s} s</td><td>${e.speed_factor??'–'}×</td><td>${esc(e.text)}</td></tr>`).join('')+'</table>'+
  `<p class="file">Fastest ${m.fastest_s??'–'} s · slowest ${m.slowest_s??'–'} s · ${m.errors||0} errors · updated ${esc(L.updated)}</p>`;
}
tick(); setInterval(tick,2000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/api/state":
            with LOCK:
                body = dict(STATE)
            body["voice"] = last_real_run()
            body["live"] = live_feed()
            body["commits"] = recent_commits()
            self._send(json.dumps(body).encode(), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(PAGE.encode(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def _send(self, data: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main() -> None:
    threading.Thread(target=watch_forever, daemon=True).start()
    print(f"VoiceLens dashboard on http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
