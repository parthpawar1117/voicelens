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

sys.path.insert(0, str(SERVER))
from devtools.demo_friend import DemoFriend, clean_token, make_bot_api, to_ogg_opus  # noqa: E402


# ---------- glasses controls (tested) ----------
# The dashboard drives the Even Hub simulator through its automation API and
# reads the inbox and current screen from the VoiceLens server.

SIM = "http://127.0.0.1:9898"         # evenhub-simulator --automation-port 9898
VOICELENS = "http://127.0.0.1:8787"   # server/run.py
ALLOWED_ACTIONS = ("up", "down", "click", "double_click", "long_press", "long_press_release")


def validate_action(action: str) -> str:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"not a G2 gesture: {action!r}")
    return action


def steps_to_open(index: int, total: int, screen: str | None, current: int | None = None) -> list[str]:
    """Simulator inputs that open inbox row `index` from wherever the glasses are.

    Back out first: not on the inbox, once from a message, twice from a reply
    screen (reply -> message -> inbox; the first also cancels a pending draft).
    Backing out keeps the same message selected, so if its row `current` is
    known, move only the difference; otherwise go to the top and down.
    """
    if not 0 <= index < total:
        raise ValueError(f"row {index} does not exist (inbox has {total})")
    backs = 0 if screen in (None, "inbox") else 1 if screen == "message" else 2
    if current is not None and 0 <= current < total:
        delta = index - current
        moves = ["down"] * delta if delta > 0 else ["up"] * -delta
    else:
        moves = ["up"] * total + ["down"] * index
    return ["double_click"] * backs + moves + ["click"]


def simulator_command() -> list[str]:
    exe = "npx.cmd" if sys.platform == "win32" else "npx"
    return [exe, "evenhub-simulator", "--automation-port", "9898", "http://localhost:5173"]


def restart_simulator() -> bool:
    """Close the simulator window and open a fresh one (reloads the glasses app)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/IM", "evenhub-simulator.exe", "/F"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "evenhub-simulator"], capture_output=True)
    time.sleep(0.8)
    # Start it as its own process (own group, no console window) so it keeps
    # running when the dashboard restarts; it used to close along with it.
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if sys.platform == "win32" else 0
    subprocess.Popen(simulator_command(), cwd=APP, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=sys.platform != "win32")
    for _ in range(30):  # wait until its automation API answers
        if _http(f"{SIM}/api/ping", timeout=1) is not None:
            return True
        time.sleep(0.5)
    return False


def _http(url: str, data: dict | None = None, timeout: float = 2.0) -> bytes | None:
    import urllib.request

    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except OSError:
        return None


def send_gesture(action: str) -> bool:
    return _http(f"{SIM}/api/input", {"action": validate_action(action)}) is not None


def glasses_status() -> dict:
    inbox = _http(f"{VOICELENS}/inbox")
    ui = _http(f"{VOICELENS}/ui-state")
    return {
        "simulator": _http(f"{SIM}/api/ping") is not None,
        "server": inbox is not None,
        "inbox": json.loads(inbox)["items"] if inbox else [],
        "ui": json.loads(ui) if ui else None,
    }


def open_row(index: int) -> list[str]:
    status = glasses_status()
    ui = status["ui"] or {}
    ids = [m["id"] for m in status["inbox"]]
    current = ids.index(ui["selected_id"]) if ui.get("selected_id") in ids else None
    steps = steps_to_open(index, len(ids), ui.get("screen"), current)
    for action in steps:
        send_gesture(action)
        time.sleep(0.25 if action == "double_click" else 0.12)  # let each gesture land in order
    return steps


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
.gl{display:grid;grid-template-columns:minmax(0,620px) minmax(0,1fr);gap:16px;margin-top:14px}
@media (max-width:900px){.gl{grid-template-columns:1fr}}
.glcard{background:#1d201d;border:1px solid #2c302c;border-radius:10px;padding:14px;min-width:0}
#glimg{display:block;width:100%;aspect-ratio:2/1;background:#000;border-radius:8px;cursor:pointer;image-rendering:pixelated;border:1px solid #2c302c;outline:none}
#glimg:focus-visible{border-color:#3cfa44}
.pad{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}
.pad button{background:#262a26;color:#e6e6e6;border:1px solid #3a3f3a;border-radius:8px;padding:12px 6px;font:600 14px system-ui;cursor:pointer}
.pad button:hover{border-color:#3cfa44}.pad button.hit{background:#3cfa44;color:#0b0f0b}
.pad button small{display:block;font-weight:400;color:#9a9a9a;font-size:11px;margin-top:2px}
.pad button.hit small{color:#0b0f0b}
.hold{display:block;width:100%;margin-top:8px;background:#262a26;color:#e6e6e6;border:1px solid #3a3f3a;border-radius:8px;padding:14px 6px;font:600 15px system-ui;cursor:pointer;user-select:none;touch-action:none}
.hold small{display:block;font-weight:400;color:#9a9a9a;font-size:11px;margin-top:2px}
.replybar{margin-top:10px;border:1px solid #3cfa44;border-radius:10px;padding:12px;background:rgba(60,250,68,.05)}
.rbtitle{font:600 14px system-ui;color:#3cfa44}.rbtext{margin:6px 0 10px;font-size:15px;color:#e6e6e6;white-space:pre-wrap}
.rbchoices{display:grid;grid-template-columns:1fr 1fr auto;gap:8px}
.rbchoices button{background:#262a26;color:#e6e6e6;border:1px solid #3a3f3a;border-radius:8px;padding:12px 10px;font:600 14px system-ui;cursor:pointer}
.rbchoices button.cur{background:#3cfa44;color:#0b0f0b;border-color:#3cfa44}
.rbchoices button:hover{border-color:#3cfa44}.rbchoices .cancel:hover{border-color:#ff5a4f;color:#ff5a4f}
.frchat{display:flex;flex-direction:column;gap:8px;max-height:320px;overflow:auto;padding:4px 2px 10px}
.bub{max-width:75%;padding:8px 12px;border-radius:12px;font-size:14px;white-space:pre-wrap;word-break:break-word}
.bub.friend{align-self:flex-start;background:#262a26;border:1px solid #3a3f3a}
.bub.you{align-self:flex-end;background:rgba(60,250,68,.12);border:1px solid #3cfa44}
.bub small{display:block;font-size:11px;color:#9a9a9a;margin-bottom:3px}
.bub audio{display:block;margin-top:6px;max-width:100%}
.frsend{display:grid;grid-template-columns:1fr auto;gap:8px}
.frsend input{background:#141614;border:1px solid #3a3f3a;color:#e6e6e6;border-radius:8px;padding:10px 12px;font:14px system-ui;min-width:0}
.frsend input:focus{outline:none;border-color:#3cfa44}
.frsend #frtextbtn{background:#262a26;color:#e6e6e6;border:1px solid #3a3f3a;border-radius:8px;padding:10px 14px;font:600 14px system-ui;cursor:pointer}
.frsend #frvoicebtn{grid-column:1 / -1}
.gloff{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;background:rgba(0,0,0,.85);border-radius:8px;text-align:center}
.gloff[hidden]{display:none}
.gloff p{margin:0;color:#e6e6e6;font-size:15px}
.gloff button{background:#3cfa44;color:#0b0f0b;border:0;border-radius:10px;padding:14px 28px;font:700 17px system-ui;cursor:pointer}
.gloff small{color:#9a9a9a}
.mini{background:none;border:1px solid #3a3f3a;color:#9a9a9a;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px}
.mini:hover{border-color:#3cfa44;color:#3cfa44}
.hold:hover{border-color:#3cfa44}.hold.on{background:#ff5a4f;border-color:#ff5a4f;color:#fff}.hold.on small{color:#fff}
.glmeta{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:#9a9a9a}
#gllog{font:12px ui-monospace,Consolas,monospace;color:#9a9a9a}
.inrow{display:grid;grid-template-columns:1fr auto;gap:10px;padding:10px 0;border-bottom:1px solid #262a26;align-items:start}
.inrow:last-child{border-bottom:0}.inrow.sel{background:rgba(60,250,68,.06)}
.inrow b{font-size:13px}.inrow .k{font-size:11px;color:#3cfa44;margin-left:6px}
.inrow p{margin:4px 0 0;font-size:13px;color:#cfcfcf;white-space:pre-wrap;word-break:break-word}
.inrow button{background:none;border:1px solid #3a3f3a;color:#e6e6e6;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:12px;white-space:nowrap}
.inrow button:hover{border-color:#3cfa44;color:#3cfa44}
#inlist{max-height:430px;overflow:auto}
</style></head><body><main>
<div class="top"><h1>VoiceLens · live test dashboard</h1><span id="badge" class="pill run">starting…</span></div>
<h2>Glasses <span id="glbadge" class="pill">checking…</span></h2>
<div class="gl">
 <div class="glcard">
  <div style="position:relative">
   <img id="glimg" tabindex="0" alt="Live G2 glasses screen. Click to tap, double-click to double-tap, scroll to swipe." src="/glasses.png">
   <div id="gloff" class="gloff" hidden>
    <p>The glasses simulator is off.</p>
    <button id="glstart">▶ Start glasses</button>
    <small>Takes about 5 seconds</small>
   </div>
  </div>
  <div class="pad">
   <button data-a="up">▲ Swipe up<small>key ↑ · wheel up</small></button>
   <button data-a="down">▼ Swipe down<small>key ↓ · wheel down</small></button>
   <button data-a="click">● Tap<small>Enter · click screen</small></button>
   <button data-a="double_click">◀ Double-tap<small>Esc · double-click</small></button>
  </div>
  <button id="holdbtn" class="hold">🎤 Hold to talk<small>hold this button, or hold Space · speak · release</small></button>
  <div id="replybar" class="replybar" hidden>
   <div id="rbtitle" class="rbtitle"></div>
   <div id="rbtext" class="rbtext"></div>
   <div id="rbchoices" class="rbchoices">
    <button data-fmt="text">💬 Send as text<small style="display:block;font-weight:400;font-size:11px">glasses: swipe up · key ↑</small></button>
    <button data-fmt="voice">🎤 Send as voice<small style="display:block;font-weight:400;font-size:11px">glasses: swipe down · key ↓</small></button>
    <button id="rbcancel" class="cancel">✕ Cancel</button>
   </div>
  </div>
  <div class="glmeta"><span id="glui">screen: –</span><span id="gllog">no gestures yet</span></div>
  <div class="glmeta"><span>Screen blank or stuck?</span><button id="restartbtn" class="mini">↻ Restart glasses app</button></div>
 </div>
 <div class="glcard"><b style="font-size:13px;color:#9a9a9a">FULL INBOX · newest first · <span id="incount">0</span></b><div id="inlist"></div></div>
</div>
<h2>📱 <span id="frname">Demo friend</span>'s phone <span id="frbadge" class="pill">checking…</span></h2>
<div class="glcard" style="margin-top:14px">
 <p class="file" id="frhelp" style="margin:0 0 10px">Plays the person who messages you, so a demo video shows two sides.</p>
 <div id="frchat" class="frchat"></div>
 <div class="frsend">
  <input id="frtext" type="text" placeholder="Type what your friend says, e.g. Where are you? Dinner is ready." autocomplete="off">
  <button id="frtextbtn">Send text</button>
  <button id="frvoicebtn" class="hold" style="margin:0">🎤 Hold to record their voice note</button>
 </div>
</div>
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
 lb.textContent=L.processing?`transcribing ${L.processing}…`:!L.listening?'listener stopped':!L.model_ready?'loading model…':`listening on ${L.device==='cuda'?'GPU':(L.device||'CPU').toUpperCase()}${L.keep_alive?' + keep-alive':''} · send a voice note`;
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
// ---- glasses panel: live screen, gestures, full inbox ----
const glimg=$('glimg'), log=[]; let busy=false, glStatus=null;
const labels={up:'swipe up',down:'swipe down',click:'tap',double_click:'double-tap',long_press:'hold',long_press_release:'release'};
function refreshShot(){ glimg.src='/glasses.png?t='+Date.now() }
function flash(a){ const b=document.querySelector(`.pad button[data-a="${a}"]`); if(b){b.classList.add('hit'); setTimeout(()=>b.classList.remove('hit'),180)} }
function note(t){ log.unshift(t); log.length=Math.min(log.length,4); $('gllog').textContent=log.join(' · ') }
async function gesture(a){
 flash(a); note(labels[a]||a);
 try{ await fetch('/api/gesture',{method:'POST',body:JSON.stringify({action:a})}) }catch(e){}
 setTimeout(refreshShot,120); setTimeout(refreshShot,450); setTimeout(glTick,450);
}
async function openRow(i){
 if(busy) return; busy=true; note('open row '+(i+1));
 try{ await fetch('/api/open',{method:'POST',body:JSON.stringify({index:i})}) }catch(e){}
 busy=false; refreshShot(); setTimeout(refreshShot,300); glTick();
}
document.querySelectorAll('.pad button').forEach(b=>b.addEventListener('click',()=>gesture(b.dataset.a)));
let clickTimer=null;
glimg.addEventListener('click',()=>{ clearTimeout(clickTimer); clickTimer=setTimeout(()=>gesture('click'),230) });
glimg.addEventListener('dblclick',()=>{ clearTimeout(clickTimer); gesture('double_click') });
let wheelLock=0;
glimg.addEventListener('wheel',e=>{ e.preventDefault(); const now=Date.now(); if(now-wheelLock<250) return; wheelLock=now; gesture(e.deltaY>0?'down':'up') },{passive:false});
// Hold to talk: press = long_press (mic on), release = long_press_release.
const holdBtn=$('holdbtn'); let holding=false;
function holdStart(){ if(holding) return; holding=true; holdBtn.classList.add('on'); holdBtn.firstChild.textContent='● Recording… release to finish'; gesture('long_press') }
function holdEnd(){ if(!holding) return; holding=false; holdBtn.classList.remove('on'); holdBtn.firstChild.textContent='🎤 Hold to talk'; gesture('long_press_release') }
holdBtn.addEventListener('pointerdown',e=>{ e.preventDefault(); holdBtn.setPointerCapture(e.pointerId); holdStart() });
holdBtn.addEventListener('pointerup',holdEnd); holdBtn.addEventListener('pointercancel',holdEnd);
window.addEventListener('blur',holdEnd);
// ---- demo friend: type or record what the friend says; see your replies ----
let frCount=-1, frPlaying=new Set();
async function frTick(){
 let f; try{ f=await (await fetch('/api/friend')).json() }catch(e){ return }
 const b=$('frbadge'); $('frname').textContent=f.name||'Demo friend';
 if(!f.enabled){ b.className='pill'; b.textContent='not set up'; $('frhelp').textContent='To use: create a bot with @BotFather, add TELEGRAM_DEMO_BOT_TOKEN to server/.env, restart the dashboard.'; return }
 b.className='pill '+(f.ready?'ok':'run'); b.textContent=f.ready?'connected':'open the bot in Telegram and press Start';
 if(f.conversation.length===frCount) return; frCount=f.conversation.length;
 const box=$('frchat');
 box.innerHTML=!f.conversation.length?'<p class="file">No messages yet. Type below or hold the button to record.</p>':
  f.conversation.map(m=>{
   const who=m.from==='friend'?(f.name||'Friend'):'You · replied from G2 glasses';
   const body=m.kind==='voice'?(m.file_id?`🎤 voice note${m.duration?' · '+m.duration+'s':''}<audio controls preload="none" src="/api/friend/audio?file_id=${encodeURIComponent(m.file_id)}"></audio>`:'🎤 voice note'):esc(m.text);
   return `<div class="bub ${m.from==='friend'?'friend':'you'}"><small>${esc(who)}</small>${body}</div>`}).join('');
 box.scrollTop=box.scrollHeight;
}
async function frSendText(){
 const i=$('frtext'), t=i.value.trim(); if(!t) return;
 i.value=''; note('friend: text');
 const r=await (await fetch('/api/friend/text',{method:'POST',body:JSON.stringify({text:t})})).json();
 if(!r.ok){ alertLine(r.error) } frCount=-1; frTick();
}
function alertLine(msg){ $('frhelp').textContent='⚠ '+msg }
$('frtextbtn').addEventListener('click',frSendText);
$('frtext').addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); frSendText() } });
// Hold to record the friend's voice note in the browser (localhost may use the mic).
let rec=null, recChunks=[];
const vb=$('frvoicebtn');
async function frRecStart(){
 if(rec) return;
 try{
  const stream=await navigator.mediaDevices.getUserMedia({audio:true});
  recChunks=[]; rec=new MediaRecorder(stream,{mimeType:'audio/webm;codecs=opus'});
  rec.ondataavailable=e=>{ if(e.data.size) recChunks.push(e.data) };
  rec.onstop=async()=>{
   stream.getTracks().forEach(t=>t.stop());
   const blob=new Blob(recChunks,{type:'audio/webm'}); rec=null;
   if(blob.size<1000){ alertLine('Too short. Hold the button while speaking.'); return }
   vb.firstChild.textContent='Sending…';
   const r=await (await fetch('/api/friend/voice',{method:'POST',body:blob})).json();
   vb.firstChild.textContent='🎤 Hold to record their voice note';
   if(!r.ok) alertLine(r.error); frCount=-1; frTick();
  };
  rec.start(); vb.classList.add('on'); vb.firstChild.textContent='● Recording friend… release to send';
 }catch(e){ alertLine('Microphone blocked: allow it in the address bar, then try again.') }
}
function frRecStop(){ if(rec&&rec.state==='recording'){ rec.stop(); vb.classList.remove('on') } }
vb.addEventListener('pointerdown',e=>{ e.preventDefault(); vb.setPointerCapture(e.pointerId); frRecStart() });
vb.addEventListener('pointerup',frRecStop); vb.addEventListener('pointercancel',frRecStop);
frTick(); setInterval(frTick,1500);
document.addEventListener('keydown',e=>{
 if(e.target.closest&&e.target.closest('input,textarea')) return;
 if(e.code==='Space'){ e.preventDefault(); if(!e.repeat) holdStart(); return }
 const a={ArrowUp:'up',ArrowDown:'down',Enter:'click',Escape:'double_click'}[e.key];
 if(a){ e.preventDefault(); gesture(a) }
});
document.addEventListener('keyup',e=>{ if(e.code==='Space'){ e.preventDefault(); holdEnd() } });
glimg.addEventListener('error',()=>{ glimg.removeAttribute('src'); glimg.alt='Simulator not running' });
async function glTick(){
 try{ glStatus=await (await fetch('/api/glasses')).json() }catch(e){ return }
 const s=glStatus, b=$('glbadge');
 b.className='pill '+(s.simulator&&s.server?'ok':'bad');
 b.textContent=!s.simulator?'simulator not running':!s.server?'VoiceLens server not running':'connected · live';
 $('gloff').hidden=s.simulator;
 const ui=s.ui||{}, sel=s.inbox.find(i=>i.id===ui.selected_id);
 $('glui').textContent=ui.screen?`screen: ${ui.screen}${sel?' · '+sel.chat_name+' ('+sel.kind+')':''}${ui.screen==='message'?' · page '+(ui.page+1):''}`:'screen: –';
 $('incount').textContent=s.inbox.length;
 $('inlist').innerHTML=!s.inbox.length?'<p class="file">No messages yet. Send a text or voice note to Saved Messages.</p>':
  s.inbox.map((m,i)=>`<div class="inrow${m.id===ui.selected_id?' sel':''}"><div><b>${esc(m.chat_name)}</b><span class="k">${m.kind==='voice'?'voice '+Math.round(m.duration||0)+'s'+(m.source?' · '+m.source:''):'text'}</span><span class="file" style="margin-left:6px">${esc(m.received_at)}</span><p>${esc(m.text)}</p></div><button data-i="${i}">Open on glasses</button></div>`).join('');
 document.querySelectorAll('#inlist button').forEach(b=>b.addEventListener('click',()=>openRow(+b.dataset.i)));
 renderReply(ui);
}
// Reply bar: plain-language choices while a reply is being made.
function renderReply(ui){
 const bar=$('replybar'), scr=ui&&ui.screen, choices=$('rbchoices');
 const show=['recording','thinking','confirm','sending','sent','error'].includes(scr);
 bar.hidden=!show; if(!show) return;
 const t={recording:'● Recording… release the button (or Space) to finish',thinking:'Preparing your preview…',confirm:`Sending as ${ui.reply_format} in ${ui.countdown} s — choose or wait`,sending:'Sending…',sent:'✓ Sent',error:'Reply not sent'}[scr];
 $('rbtitle').textContent=t;
 $('rbtext').textContent=ui.reply_text?`You said: “${ui.reply_text}”`:'';
 choices.style.display=scr==='confirm'?'grid':'none';
 choices.querySelectorAll('[data-fmt]').forEach(b=>b.classList.toggle('cur',b.dataset.fmt===ui.reply_format));
}
$('rbchoices').querySelectorAll('[data-fmt]').forEach(b=>b.addEventListener('click',()=>{
 const ui=glStatus&&glStatus.ui; if(!ui||ui.screen!=='confirm') return;
 gesture(b.dataset.fmt==='text'?'up':'down'); // same as the glasses: swipe up = text, down = voice
}));
$('rbcancel').addEventListener('click',()=>gesture('double_click'));
async function restartGlasses(btn,label){
 btn.disabled=true; btn.textContent='Starting…'; note('start glasses');
 try{ await fetch('/api/restart',{method:'POST',body:'{}'}) }catch(e){}
 btn.disabled=false; btn.textContent=label; setTimeout(refreshShot,800); glTick();
}
$('restartbtn').addEventListener('click',()=>restartGlasses($('restartbtn'),'↻ Restart glasses app'));
$('glstart').addEventListener('click',()=>restartGlasses($('glstart'),'▶ Start glasses'));
glTick(); setInterval(glTick,800); setInterval(()=>{ if(glStatus&&glStatus.simulator) refreshShot() },700);
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
        elif self.path.startswith("/glasses.png"):
            png = _http(f"{SIM}/api/screenshot/glasses")
            if png:
                self._send(png, "image/png")
            else:
                self.send_error(503, "simulator not running")
        elif self.path == "/api/glasses":
            self._send(json.dumps(glasses_status()).encode(), "application/json")
        elif self.path == "/api/friend":
            body = {"enabled": FRIEND is not None, "name": FRIEND_NAME,
                    "ready": bool(FRIEND and FRIEND.chat_id), "conversation": FRIEND.conversation if FRIEND else []}
            self._send(json.dumps(body).encode(), "application/json")
        elif self.path.startswith("/api/friend/audio?file_id=") and FRIEND:
            try:
                self._send(FRIEND.file_bytes(FRIEND_TOKEN, self.path.split("=", 1)[1]), "audio/ogg")
            except Exception:
                self.send_error(502, "could not fetch the voice note from Telegram")
        elif self.path in ("/", "/index.html"):
            self._send(PAGE.encode(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if self.path == "/api/friend/voice":  # raw browser recording, not JSON
            return self._friend(lambda f: f.send_voice(to_ogg_opus(raw)))
        try:
            body = json.loads(raw or b"{}")
            if self.path == "/api/friend/text":
                return self._friend(lambda f: f.send_text(str(body.get("text", "")).strip() or "..."))
            if self.path == "/api/gesture":
                ok = send_gesture(body.get("action", ""))
                self._send(json.dumps({"ok": ok}).encode(), "application/json")
            elif self.path == "/api/restart":
                self._send(json.dumps({"ok": restart_simulator()}).encode(), "application/json")
            elif self.path == "/api/open":
                steps = open_row(int(body.get("index", -1)))
                self._send(json.dumps({"ok": True, "steps": steps}).encode(), "application/json")
            else:
                self.send_error(404)
        except (ValueError, json.JSONDecodeError) as err:
            self._send(json.dumps({"ok": False, "error": str(err)}).encode(), "application/json")

    def _friend(self, action) -> None:
        if FRIEND is None:
            return self._send(json.dumps({"ok": False, "error": "Add TELEGRAM_DEMO_BOT_TOKEN to server/.env and restart the dashboard"}).encode(), "application/json")
        try:
            action(FRIEND)
            self._send(json.dumps({"ok": True}).encode(), "application/json")
        except Exception as err:  # show bot errors in the panel instead of crashing
            self._send(json.dumps({"ok": False, "error": str(err)}).encode(), "application/json")

    def _send(self, data: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


# ---------- demo friend (optional bot that plays the person messaging you) ----------

FRIEND = None
FRIEND_NAME = None
FRIEND_TOKEN = None
FRIEND_STATE = TMP / "demo_friend.json"  # remembers your chat id after you press Start


def start_demo_friend() -> None:
    global FRIEND, FRIEND_NAME, FRIEND_TOKEN
    import os

    from dotenv import load_dotenv

    load_dotenv(SERVER / ".env")
    raw = os.getenv("TELEGRAM_DEMO_BOT_TOKEN") or ""
    if not raw.strip():
        return
    try:
        FRIEND_TOKEN = clean_token(raw)
    except ValueError as err:
        print(f"Demo friend bot disabled: {err}")  # never prints the token
        return
    try:
        chat_id = json.loads(FRIEND_STATE.read_text(encoding="utf-8")).get("chat_id")
    except (OSError, json.JSONDecodeError):
        chat_id = None
    api = make_bot_api(FRIEND_TOKEN)
    FRIEND = DemoFriend(api, chat_id)
    try:
        FRIEND_NAME = api("getMe", timeout=10)["result"].get("first_name")
    except Exception:
        FRIEND_NAME = "Demo friend"

    def poll_forever():
        while True:
            try:
                before = FRIEND.chat_id
                FRIEND.poll_once()
                if FRIEND.chat_id and FRIEND.chat_id != before:
                    TMP.mkdir(exist_ok=True)
                    FRIEND_STATE.write_text(json.dumps({"chat_id": FRIEND.chat_id}), encoding="utf-8")
            except Exception:
                time.sleep(3)  # network blip: retry

    threading.Thread(target=poll_forever, daemon=True).start()
    print(f"Demo friend bot '{FRIEND_NAME}' is running.")


def main() -> None:
    start_demo_friend()
    threading.Thread(target=watch_forever, daemon=True).start()
    print(f"VoiceLens dashboard on http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
