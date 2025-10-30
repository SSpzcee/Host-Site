# main.py
import os
import json
import time
from typing import Dict, List, Any
from flask import Flask, jsonify, request, render_template_string, abort
import gspread
from google.oauth2 import service_account

app = Flask(__name__)

# ---------- Config ----------
SHEET_NAME = os.environ.get("Hosting Sheet", "HostCoordinatingSheet")
GCP_SERVICE_ACCOUNT_JSON = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")

if not GCP_SERVICE_ACCOUNT_JSON:
    raise RuntimeError("Missing environment variable GCP_SERVICE_ACCOUNT_JSON")

# ---------- Google Sheets helpers ----------
def get_gspread_client():
    try:
        creds_dict = json.loads(GCP_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
        )
        return gspread.authorize(creds)
    except Exception as e:
        raise RuntimeError(f"Error initializing Google Sheets client: {e}")

gc = get_gspread_client()

def get_sheet():
    """Open or create the spreadsheet and return the first worksheet."""
    try:
        sh = gc.open(SHEET_NAME)
    except gspread.SpreadsheetNotFound:
        sh = gc.create(SHEET_NAME)
        # Try to share with the service account email if present
        try:
            info = json.loads(GCP_SERVICE_ACCOUNT_JSON)
            email = info.get("client_email")
            if email:
                sh.share(email, perm_type="user", role="writer")
        except Exception:
            pass
    return sh.sheet1

ws = get_sheet()

# ---------- Persistent state helpers ----------
DEFAULT_KEYS = [
    "waitlist",
    "servers",
    "present_servers",
    "tables",
    "seating_rotation",
    "server_scores",
    "seating_direction",
    "last_sat_server",
]

def load_state_from_sheet() -> Dict[str, Any]:
    try:
        vals = ws.get_all_values()
        if vals and vals[0] and vals[0][0]:
            raw = vals[0][0]
            state = json.loads(raw)
            # Convert present_servers back to set for convenience
            if "present_servers" in state and isinstance(state["present_servers"], list):
                state["present_servers"] = set(state["present_servers"])
            return state
    except Exception as e:
        app.logger.error("Failed to load state: %s", e)
    # return default structure
    return {
        "waitlist": [],
        "servers": [],
        "present_servers": set(),
        "tables": [],  # will be initialized below if empty
        "seating_rotation": [],
        "server_scores": {},
        "seating_direction": "Up",
        "last_sat_server": None,
    }

def save_state_to_sheet(state: Dict[str, Any]):
    try:
        # convert sets to lists for JSON
        s = dict(state)
        if isinstance(s.get("present_servers"), set):
            s["present_servers"] = list(s["present_servers"])
        # ensure keys present
        for k in DEFAULT_KEYS:
            s.setdefault(k, [] if k in ("waitlist","servers","tables","seating_rotation") else ({} if k=="server_scores" else None))
        json_str = json.dumps(s, ensure_ascii=False)
        ws.update("A1", [[json_str]])
    except Exception as e:
        app.logger.error("Failed to save state to sheet: %s", e)
        raise

# ---------- Table plan / initialization ----------
TABLE_PLANS = {
    2: [
        [31,32,33,34,35,36,37,41,42,43],
        [1,2,3,4,5,6,7,8,9,10,11,21,22,23,24,25,26,27,28,29,30,51,52,53,54,55,61,62,63,64,65]
    ],
    3: [
        [31,32,33,34,35,36,37,41,42,43],
        [1,2,3,4,5,6,7,8,9,10,11,21,22,23,24,25,26,27,28,29,30],
        [51,52,53,54,55,61,62,63,64,65],
    ],
    4: [
        [31,32,33,34,35,36,37,41,42,43],
        [1,2,3,4,5,6,21,22,23,24,25],
        [51,52,53,54,55,61,62,63,64,65],
        [7,8,9,10,11,26,27,28,29,30],
    ],
    5: [
        [31,32,33,34,35,36,37,41,42,43],
        [4,5,6,7,8,25,26],
        [51,52,53,54,55,61,62,63,64,65],
        [9,10,11,27,28,29,30],
        [1,2,3,21,22,23,24],
    ],
    6: [
        [31,32,33,34,35],
        [4,5,6,7,8,25,26],
        [51,52,53,54,55,61,62,63,64,65],
        [9,10,11,27,28,29,30],
        [1,2,3,21,22,23,24],
        [36,37,41,42,43],
    ],
    7: [
        [31,32,33,34,35],
        [4,5,6,7,8,25,26],
        [54,55,63,64,65],
        [9,10,11,27,28,29,30],
        [1,2,3,21,22,23,24],
        [36,37,41,42,43],
        [51,52,53,61,62],
    ],
    8: [
        [31,32,33,34,35],
        [4,5,6,7,24,25],
        [54,55,63,64,65],
        [10,11,28,29,30],
        [1,2,3,21,22,23],
        [36,37,41,42,43],
        [51,52,53,61,62],
        [8,9,26,27],
    ],
    9: [
        [31,32,33,34,35],
        [4,5,6,7,26],
        [54,55,64,65],
        [10,11,29,30],
        [1,2,21,22],
        [36,37,41,42,43],
        [51,52,53,61,62,63],
        [8,9,27,28],
        [3,23,24,25],
    ],
}

def get_plan_tables(num_sections: int):
    plan = TABLE_PLANS.get(num_sections)
    if not plan:
        all_tables = sum(TABLE_PLANS[3], [])
        return [[t for t in all_tables]]
    return plan

def initialize_tables(num_sections: int):
    plan = get_plan_tables(num_sections)
    tables = []
    for section_idx, table_nums in enumerate(plan):
        for tnum in table_nums:
            tables.append({
                "table": tnum,
                "section": section_idx + 1,
                "status": "Available",
                "server": None,
                "party": None
            })
    return tables

# ---------- Load or initialize state ----------
STATE = load_state_from_sheet()

# Ensure tables exist
if not STATE.get("tables"):
    num_sections = min(max(len(STATE.get("servers", [])), 1), 9)
    STATE["tables"] = initialize_tables(num_sections)
    save_state_to_sheet(STATE)

# Ensure types are consistent
if "present_servers" in STATE and not isinstance(STATE["present_servers"], set):
    STATE["present_servers"] = set(STATE["present_servers"])

# ---------- Table positions (normalized percentages) ----------
# Tweak these to match the photo. Values are x_pct, y_pct (0..1)
TABLE_POSITIONS = {
    # left column 1..6 (approx)
    1: {"x": 0.08,"y":0.20},
    2: {"x": 0.08,"y":0.28},
    3: {"x": 0.08,"y":0.36},
    4: {"x": 0.08,"y":0.44},
    5: {"x": 0.08,"y":0.52},
    6: {"x": 0.06,"y":0.12},

    # top row 7-11
    7: {"x":0.20,"y":0.10},
    8: {"x":0.30,"y":0.10},
    9: {"x":0.40,"y":0.10},
    10: {"x":0.50,"y":0.10},
    11: {"x":0.60,"y":0.10},

    # 21-25 column to right of 1-5
    21: {"x":0.20,"y":0.20},
    22: {"x":0.20,"y":0.28},
    23: {"x":0.20,"y":0.36},
    24: {"x":0.20,"y":0.44},
    25: {"x":0.20,"y":0.52},

    # 26-30 below 7-11
    26: {"x":0.30,"y":0.20},
    27: {"x":0.40,"y":0.20},
    28: {"x":0.50,"y":0.20},
    29: {"x":0.60,"y":0.20},
    30: {"x":0.70,"y":0.20},

    # 31-34 column to right of 21-25 (vertical)
    31: {"x":0.32,"y":0.45},
    32: {"x":0.32,"y":0.55},
    33: {"x":0.32,"y":0.65},
    34: {"x":0.32,"y":0.35},

    # 35-37 small row under 28-30
    35: {"x":0.48,"y":0.30},
    36: {"x":0.58,"y":0.30},
    37: {"x":0.68,"y":0.30},

    # 41-43 circulars to left of 51-53
    41: {"x":0.78,"y":0.48},
    42: {"x":0.78,"y":0.58},
    43: {"x":0.78,"y":0.68},

    # 51-55 left-right block
    51: {"x":0.88,"y":0.48},
    52: {"x":0.88,"y":0.58},
    53: {"x":0.88,"y":0.68},
    54: {"x":0.96,"y":0.58},
    55: {"x":0.96,"y":0.48},

    # 61-65 far right column (bottom to top)
    61: {"x":0.98,"y":0.72},
    62: {"x":0.98,"y":0.62},
    63: {"x":0.98,"y":0.52},
    64: {"x":0.98,"y":0.42},
    65: {"x":0.98,"y":0.32},
}

# Ensure all tables exist in positions (fallback center)
for t in STATE["tables"]:
    if t["table"] not in TABLE_POSITIONS:
        TABLE_POSITIONS[t["table"]] = {"x":0.5,"y":0.5}

# ---------- Helper: find server for section ----------
def server_for_section(section: int) -> str | None:
    for s in STATE.get("servers", []):
        if s.get("section") == section:
            return s.get("name")
    return None

# ---------- API endpoints ----------
@app.route("/api/state", methods=["GET"])
def api_state():
    # Convert present_servers set to list for JSON
    s = dict(STATE)
    s["present_servers"] = list(s.get("present_servers", []))
    return jsonify(s)

@app.route("/api/add_waitlist", methods=["POST"])
def api_add_waitlist():
    payload = request.get_json()
    name = payload.get("name", "").strip()
    party_size = int(payload.get("party_size", 2))
    notes = payload.get("notes", "")
    min_wait = int(payload.get("min_wait", 0))
    max_wait = int(payload.get("max_wait", 30))
    if not name:
        return jsonify({"error":"name required"}), 400
    STATE["waitlist"].append({
        "name": name,
        "party_size": party_size,
        "notes": notes,
        "added_time": time.time(),
        "min_wait": min_wait,
        "max_wait": max_wait
    })
    save_state_to_sheet(STATE)
    return jsonify({"ok":True})

@app.route("/api/remove_waitlist", methods=["POST"])
def api_remove_waitlist():
    payload = request.get_json() or {}
    idx = int(payload.get("index", 0))
    if 0 <= idx < len(STATE["waitlist"]):
        removed = STATE["waitlist"].pop(idx)
        save_state_to_sheet(STATE)
        return jsonify({"ok":True, "removed": removed})
    return jsonify({"error":"invalid index"}), 400

@app.route("/api/add_server", methods=["POST"])
def api_add_server():
    payload = request.get_json()
    name = payload.get("name", "").strip()
    if not name:
        return jsonify({"error":"name required"}), 400
    current_sections = [s["section"] for s in STATE.get("servers",[])]
    next_section = max(current_sections, default=0) + 1 if len(current_sections) < 9 else None
    if next_section is None:
        return jsonify({"error":"max servers reached"}), 400
    STATE["servers"].append({"name": name, "section": next_section})
    STATE["server_scores"].setdefault(name, 0)
    num_sections = min(max(len(STATE["servers"]), 1), 9)
    STATE["tables"] = initialize_tables(num_sections)
    save_state_to_sheet(STATE)
    return jsonify({"ok":True})

@app.route("/api/remove_server", methods=["POST"])
def api_remove_server():
    payload = request.get_json() or {}
    idx = int(payload.get("index", 0))
    if 0 <= idx < len(STATE["servers"]):
        removed = STATE["servers"].pop(idx)
        STATE["present_servers"].discard(removed["name"])
        STATE["server_scores"].pop(removed["name"], None)
        num_sections = min(max(len(STATE["servers"]), 1), 9)
        STATE["tables"] = initialize_tables(num_sections)
        save_state_to_sheet(STATE)
        return jsonify({"ok":True, "removed": removed})
    return jsonify({"error":"invalid index"}), 400

@app.route("/api/mark_present", methods=["POST"])
def api_mark_present():
    payload = request.get_json() or {}
    present_list = payload.get("present", [])
    STATE["present_servers"] = set(present_list)
    for name in STATE["present_servers"]:
        STATE["server_scores"].setdefault(name, 0)
    save_state_to_sheet(STATE)
    return jsonify({"ok":True})

@app.route("/api/toggle_table", methods=["POST"])
def api_toggle_table():
    payload = request.get_json() or {}
    table_num = int(payload.get("table"))
    tbl = next((t for t in STATE["tables"] if t["table"] == table_num), None)
    if not tbl:
        return jsonify({"error":"table not found"}), 404
    old = tbl.get("status", "Available")
    if old == "Available":
        tbl["status"] = "Taken"
        # increment server score for that section's server
        sec = tbl.get("section")
        serv = server_for_section(sec)
        if serv:
            STATE["server_scores"].setdefault(serv, 0)
            STATE["server_scores"][serv] += 1
            STATE["last_sat_server"] = serv
    elif old == "Taken":
        tbl["status"] = "Bussing"
    else:
        tbl["status"] = "Available"
        tbl["party"] = None
        tbl["server"] = None
    save_state_to_sheet(STATE)
    return jsonify({"ok":True,"status":tbl["status"]})

# Endpoint to set table explicitly (seat a particular waitlist guest)
@app.route("/api/seat_table", methods=["POST"])
def api_seat_table():
    payload = request.get_json() or {}
    table_num = int(payload.get("table"))
    wait_idx = payload.get("wait_index")  # optional
    manual_name = payload.get("manual_name","").strip()
    server_name = payload.get("server","")
    tbl = next((t for t in STATE["tables"] if t["table"] == table_num), None)
    if not tbl:
        return jsonify({"error":"table not found"}), 404
    if wait_idx is not None:
        try:
            wait_idx = int(wait_idx)
            guest = STATE["waitlist"].pop(wait_idx)
            name = guest["name"]
        except Exception:
            return jsonify({"error":"invalid waitlist index"}), 400
    else:
        name = manual_name or "Unknown Party"
    tbl["status"] = "Taken"
    tbl["party"] = name
    tbl["server"] = server_name or tbl.get("server")
    # increment server score
    if tbl.get("server"):
        STATE["server_scores"].setdefault(tbl["server"],0)
        STATE["server_scores"][tbl["server"]] += 1
        STATE["last_sat_server"] = tbl["server"]
    save_state_to_sheet(STATE)
    return jsonify({"ok":True})

# ---------- Simple root page rendering ----------
# This template uses absolute-positioned divs sized responsively.
TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Host Coordinating (Flask)</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body { font-family: Arial, Helvetica, sans-serif; margin:0; padding:0; background:#f7f7f7; }
    header { padding:12px 18px; background:#1f2937; color:white; display:flex; justify-content:space-between; align-items:center; }
    .wrap { padding: 12px; max-width: 1400px; margin: 0 auto; }
    .cols { display:flex; gap:12px; align-items:flex-start; }
    .left { width: 320px; }
    .center { flex:1; position:relative; min-height:720px; background:white; border:1px solid #ddd; overflow:hidden; }
    .right { width: 320px; }
    .panel { background:white; border:1px solid #ddd; padding:10px; margin-bottom:12px; }
    .table-btn { position:absolute; border-radius:6px; width:56px; height:46px; display:flex; align-items:center; justify-content:center; color:white; font-weight:bold; cursor:pointer; box-shadow:0 2px 6px rgba(0,0,0,0.12); border:2px solid rgba(0,0,0,0.08); text-decoration:none; }
    .table-available { background:#2ecc71; }
    .table-taken { background:#e74c3c; }
    .table-bussing { background:#f1c40f; color:#222; }
    .section-label { position:absolute; padding:6px 8px; border-radius:6px; color:#111; font-weight:600; }
    .bar-shape { position:absolute; left:37%; top:35%; width:26%; height:32%; border: 6px solid #222; border-radius:40px 40px 6px 6px; box-sizing:border-box; background:transparent; pointer-events:none; }
    .circular { border-radius:50%; width:56px; height:56px; display:flex; align-items:center; justify-content:center; color:white; font-weight:bold; box-shadow:0 1px 6px rgba(0,0,0,0.2); }
    .legend { display:flex; gap:8px; align-items:center; margin-bottom:6px; }
    .legend span { display:inline-block; width:16px; height:16px; border-radius:4px; margin-right:6px; vertical-align:middle; }
    .small { font-size:12px; color:#333; }
    .btn { padding:8px 10px; border-radius:6px; border: none; background:#0ea5a4; color:white; cursor:pointer; }
    input[type=text], input[type=number] { width:100%; padding:6px; margin-bottom:6px; box-sizing:border-box; }
  </style>
</head>
<body>
  <header>
    <div><strong>Host Coordinating</strong></div>
    <div class="small">Connected to Sheet: {{ sheet_name }}</div>
  </header>

  <div class="wrap">
    <div class="cols">
      <div class="left">
        <div class="panel">
          <h3>Waitlist</h3>
          <div id="waitlist_area" class="small"></div>
          <hr/>
          <input id="wl_name" type="text" placeholder="Guest name"/>
          <input id="wl_party" type="number" min="1" value="2"/>
          <input id="wl_notes" type="text" placeholder="Notes (optional)"/>
          <div style="display:flex; gap:6px;">
            <button class="btn" onclick="addWaitlist()">Add</button>
            <button class="btn" style="background:#f97316" onclick="refreshState()">Refresh</button>
          </div>
        </div>

        <div class="panel">
          <h3>Servers & Sections</h3>
          <div id="servers_area" class="small"></div>
          <hr/>
          <input id="sv_name" type="text" placeholder="Server name"/>
          <button class="btn" onclick="addServer()">Add server</button>
          <hr/>
          <div>
            <strong>Present servers</strong>
            <div id="present_area" style="margin-top:8px;"></div>
            <button class="btn" style="margin-top:8px;" onclick="savePresent()">Save present</button>
          </div>
        </div>
      </div>

      <div class="center" id="center">
        <!-- center drawing area; positions are percentages relative to center container -->
        <div class="bar-shape" title="Bar (non-clickable)"></div>
        <div id="tables_container"></div>
      </div>

      <div class="right">
        <div class="panel">
          <h3>Rotation & Scores</h3>
          <div id="rotation_area" class="small"></div>
          <hr/>
          <div class="legend small">
            <span style="background:#2ecc71"></span> Available
            <span style="background:#e74c3c;margin-left:8px"></span> Taken
            <span style="background:#f1c40f;margin-left:8px"></span> Bussing
          </div>
          <div id="debug_area" class="small"></div>
        </div>
      </div>
    </div>
  </div>

<script>
const TABLE_POSITIONS = {{ table_positions | tojson }};
let STATE = null;
const CENTER = document.getElementById('center');

function pxFromPct(pctX, pctY) {
  // compute pixel position relative to center element dimensions
  const r = CENTER.getBoundingClientRect();
  const x = Math.round(pctX * r.width);
  const y = Math.round(pctY * r.height);
  return {x,y};
}

function renderTables() {
  const container = document.getElementById('tables_container');
  container.innerHTML = '';
  for (const t of STATE.tables) {
    const tnum = t.table;
    const pos = TABLE_POSITIONS[tnum] || {x:0.5,y:0.5};
    const coords = pxFromPct(pos.x, pos.y);
    const el = document.createElement('div');
    el.className = 'table-btn';
    el.style.left = coords.x + 'px';
    el.style.top = coords.y + 'px';
    el.style.transform = 'translate(-50%,-50%)';
    // size/shape for circular ones
    if ([41,42,43].includes(tnum)) {
      el.style.width = '56px';
      el.style.height = '56px';
      el.classList.add('circular');
    } else {
      el.style.width = '64px';
      el.style.height = '44px';
    }
    // status classes
    if (t.status === 'Available') el.classList.add('table-available');
    else if (t.status === 'Taken') el.classList.add('table-taken');
    else if (t.status === 'Bussing') el.classList.add('table-bussing');

    // show table number and optional small party
    el.innerHTML = `<div style="text-align:center">${t.table}</div>`;
    el.title = `Table ${t.table}\\nSection ${t.section}\\nServer: ${t.server || 'None'}\\nStatus: ${t.status}`;

    el.onclick = (ev) => {
      ev.preventDefault();
      toggleTable(t.table);
    };
    container.appendChild(el);
  }
  renderServerLabels();
}

function renderServerLabels() {
  // remove existing labels
  const existing = document.querySelectorAll('.section-label');
  existing.forEach(n => n.remove());
  // for each section, find a suitable table to anchor a label
  const sections = {};
  for (const t of STATE.tables) {
    const sec = t.section;
    sections[sec] = sections[sec] || [];
    sections[sec].push(t.table);
  }
  const COLORS = ['#a8d0e6','#f7d794','#f6b93b','#f8a5c2','#c7ecee','#d6a2e8','#b8e994','#f6e58d','#badc58'];
  for (const secStr in sections) {
    const sec = parseInt(secStr);
    const tables = sections[sec];
    // anchor label to first table in that section
    const tnum = tables[0];
    const pos = TABLE_POSITIONS[tnum] || {x:0.5,y:0.5};
    const coords = pxFromPct(pos.x - 0.08, pos.y - 0.06); // offset left-up
    const label = document.createElement('div');
    label.className = 'section-label';
    label.style.left = coords.x + 'px';
    label.style.top = coords.y + 'px';
    label.style.background = COLORS[(sec-1) % COLORS.length];
    const serv = STATE.servers.find(s => s.section === sec);
    const servname = serv ? serv.name : 'No server';
    label.innerHTML = `Section ${sec}<br/><small style="font-weight:600">${servname}</small>`;
    label.style.transform = 'translate(-50%,-50%)';
    CENTER.appendChild(label);
  }
}

async function toggleTable(table) {
  const resp = await fetch('/api/toggle_table', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({table})
  });
  if (!resp.ok) {
    alert('Failed to toggle table');
    return;
  }
  await refreshState();
}

async function seatTable(table, wait_index=null, manual_name='', server=null) {
  const resp = await fetch('/api/seat_table', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({table, wait_index, manual_name, server})
  });
  if (!resp.ok) {
    alert('Failed to seat table');
  }
  await refreshState();
}

async function addWaitlist() {
  const name = document.getElementById('wl_name').value.trim();
  const party = parseInt(document.getElementById('wl_party').value) || 2;
  const notes = document.getElementById('wl_notes').value || '';
  if (!name) { alert('Name required'); return; }
  await fetch('/api/add_waitlist', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, party_size:party, notes})
  });
  document.getElementById('wl_name').value='';
  document.getElementById('wl_notes').value='';
  await refreshState();
}

async function addServer() {
  const name = document.getElementById('sv_name').value.trim();
  if (!name) { alert('Server name required'); return; }
  await fetch('/api/add_server', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name})
  });
  document.getElementById('sv_name').value='';
  await refreshState();
}

async function savePresent() {
  const checks = document.querySelectorAll('.present-check');
  const present = [];
  checks.forEach(c => { if (c.checked) present.push(c.value); });
  await fetch('/api/mark_present', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({present})
  });
  await refreshState();
}

function renderWaitlist() {
  const area = document.getElementById('waitlist_area');
  area.innerHTML = '';
  if (!STATE.waitlist || STATE.waitlist.length===0) {
    area.innerHTML = '<div class="small">Waitlist empty</div>';
    return;
  }
  const ul = document.createElement('div');
  STATE.waitlist.forEach((g, i) => {
    const now = Date.now()/1000;
    const waitmins = Math.floor((now - (g.added_time || now))/60);
    const div = document.createElement('div');
    div.innerHTML = `${i+1}. <strong>${g.name}</strong> (${g.party_size}) - ${g.notes || ''} — ${waitmins} min`;
    // remove button
    const rem = document.createElement('button');
    rem.style.marginLeft = '8px';
    rem.className = 'btn';
    rem.style.background='#ef4444';
    rem.textContent = 'Remove';
    rem.onclick = async () => {
      await fetch('/api/remove_waitlist', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({index: i})
      });
      await refreshState();
    };
    div.appendChild(rem);
    ul.appendChild(div);
  });
  area.appendChild(ul);
}

function renderServers() {
  const area = document.getElementById('servers_area');
  area.innerHTML = '';
  if (!STATE.servers || STATE.servers.length===0) {
    area.innerHTML = '<div class="small">No servers</div>';
    return;
  }
  STATE.servers.forEach((s,i) => {
    const div = document.createElement('div');
    div.innerHTML = `${i+1}. <strong>${s.name}</strong> (Section ${s.section}) `;
    const rem = document.createElement('button');
    rem.className='btn';
    rem.style.background='#ef4444';
    rem.style.marginLeft='6px';
    rem.textContent = 'Remove';
    rem.onclick = async () => {
      await fetch('/api/remove_server', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({index:i})
      });
      await refreshState();
    };
    div.appendChild(rem);
    area.appendChild(div);
  });
  // present checkboxes
  const presentArea = document.getElementById('present_area');
  presentArea.innerHTML = '';
  STATE.servers.forEach(s => {
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = s.name;
    cb.className = 'present-check';
    cb.checked = STATE.present_servers.includes(s.name);
    const lbl = document.createElement('label');
    lbl.appendChild(cb);
    lbl.appendChild(document.createTextNode(' ' + s.name));
    presentArea.appendChild(lbl);
    presentArea.appendChild(document.createElement('br'));
  });
}

function renderRotation() {
  const rot = document.getElementById('rotation_area');
  rot.innerHTML = '';
  if (!STATE.seating_rotation || STATE.seating_rotation.length===0) {
    rot.innerHTML = '<div class="small">No rotation</div>';
    return;
  }
  let inner = '<div class="small">';
  STATE.seating_rotation.forEach(s => {
    const score = STATE.server_scores[s] || 0;
    inner += `<div>${s} — ${score}</div>`;
  });
  inner += '</div>';
  rot.innerHTML = inner;
}

function renderDebug() {
  const dbg = document.getElementById('debug_area');
  dbg.innerHTML = '<pre class="small">' + JSON.stringify(STATE.server_scores, null, 2) + '</pre>';
}

async function refreshState() {
  try {
    const resp = await fetch('/api/state');
    STATE = await resp.json();
    // ensure present_servers array present
    STATE.present_servers = STATE.present_servers || [];
    renderWaitlist();
    renderServers();
    renderTables();
    renderRotation();
    renderDebug();
  } catch (e) {
    console.error('Failed to refresh state', e);
  }
}

// initial load + responsive redraw
window.addEventListener('load', async () => {
  await refreshState();
  window.addEventListener('resize', () => {
    // redraw positions
    renderTables();
  });
});
</script>
</body>
</html>
"""

@app.route("/")
def index():
    # render template with positions and sheet name
    # convert present_servers to list for template use
    try:
        return render_template_string(
            TEMPLATE,
            table_positions = TABLE_POSITIONS,
            sheet_name = SHEET_NAME
        )
    except Exception as e:
        return f"Template rendering error: {e}", 500

# ---------- Run (for debug only) ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
