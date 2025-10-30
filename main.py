#!/usr/bin/env python3
"""
Flask-based Host Coordinating app (single-file).

Features:
- Visual floor layout with 41 tables positioned by normalized coordinates.
- Table status cycles: Available -> Taken -> Bussing -> Available
- Seat from waitlist or manual name, increment server score when seating.
- Sections adapt by seating plan (2-9) and display server name in each section.
- Persistent state stored as JSON in cell A1 of a Google Sheet via gspread.
- Credentials pulled from environment variables:
  - GCP_SERVICE_ACCOUNT_JSON : JSON string with your service account (full dict)
  - SHEET_NAME               : spreadsheet title
"""

import time
import threading
from typing import List, Dict, Optional

from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
import json
import gspread
from google.oauth2.service_account import Credentials
from google.oauth2 import service_account

app = Flask(__name__)

@app.route("/")
def index():
    return "Google Sheets + Flask running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

# -------------------------
# GOOGLE SHEETS SETUP
# -------------------------
# Load the credentials from the environment variable (Render dashboard)
GCP_SERVICE_ACCOUNT_JSON = os.getenv("GCP_SERVICE_ACCOUNT_JSON")

def get_gspread_client():
    if not GCP_SERVICE_ACCOUNT_JSON:
        raise ValueError("Missing GCP_SERVICE_ACCOUNT_JSON environment variable")

    try:
        service_account_info = json.loads(GCP_SERVICE_ACCOUNT_JSON)
        gc = gspread.service_account_from_dict(service_account_info)
        print("✅ Connected to Google Sheets successfully!")
        return gc
    except Exception as e:
        print("❌ Error initializing Google Sheets client:", e)
        raise

# -------------------
# Google Sheets init
# -------------------
def get_gspread_client():
    if GCP_SERVICE_ACCOUNT_JSON:
        info = json.loads(GCP_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            GCP_SERVICE_ACCOUNT_JSON_PATH,
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
        )
    return gspread.authorize(creds)


gc = get_gspread_client()
try:
    sh = gc.open("Hosting Sheet")
except gspread.SpreadsheetNotFound:
    sh = gc.create("Hosting Sheet")
    # try to share with client_email if available
    try:
        sa_email = (
            json.loads(GCP_SERVICE_ACCOUNT_JSON)["client_email"]
            if GCP_SERVICE_ACCOUNT_JSON
            else None
        )
        if sa_email:
            sh.share(sa_email, perm_type="user", role="writer")
    except Exception:
        pass

ws = sh.sheet1

# -------------------
# App & Locking
# -------------------
app = Flask(__name__, static_folder="static", static_url_path="/static")
state_lock = threading.Lock()

# -------------------
# Table plans & positions (normalized)
# -------------------
TABLE_PLANS = {
    2: [
        [31, 32, 33, 34, 35, 36, 37, 41, 42, 43],
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 51, 52, 53, 54, 55, 61, 62, 63, 64, 65],
    ],
    3: [
        [31, 32, 33, 34, 35, 36, 37, 41, 42, 43],
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30],
        [51, 52, 53, 54, 55, 61, 62, 63, 64, 65],
    ],
    4: [
        [31, 32, 33, 34, 35, 36, 37, 41, 42, 43],
        [1, 2, 3, 4, 5, 6, 21, 22, 23, 24, 25],
        [51, 52, 53, 54, 55, 61, 62, 63, 64, 65],
        [7, 8, 9, 10, 11, 26, 27, 28, 29, 30],
    ],
    5: [
        [31, 32, 33, 34, 35, 36, 37, 41, 42, 43],
        [4, 5, 6, 7, 8, 25, 26],
        [51, 52, 53, 54, 55, 61, 62, 63, 64, 65],
        [9, 10, 11, 27, 28, 29, 30],
        [1, 2, 3, 21, 22, 23, 24],
    ],
    6: [
        [31, 32, 33, 34, 35],
        [4, 5, 6, 7, 8, 25, 26],
        [51, 52, 53, 54, 55, 61, 62, 63, 64, 65],
        [9, 10, 11, 27, 28, 29, 30],
        [1, 2, 3, 21, 22, 23, 24],
        [36, 37, 41, 42, 43],
    ],
    7: [
        [31, 32, 33, 34, 35],
        [4, 5, 6, 7, 8, 25, 26],
        [54, 55, 63, 64, 65],
        [9, 10, 11, 27, 28, 29, 30],
        [1, 2, 3, 21, 22, 23, 24],
        [36, 37, 41, 42, 43],
        [51, 52, 53, 61, 62],
    ],
    8: [
        [31, 32, 33, 34, 35],
        [4, 5, 6, 7, 24, 25],
        [54, 55, 63, 64, 65],
        [10, 11, 28, 29, 30],
        [1, 2, 3, 21, 22, 23],
        [36, 37, 41, 42, 43],
        [51, 52, 53, 61, 62],
        [8, 9, 26, 27],
    ],
    9: [
        [31, 32, 33, 34, 35],
        [4, 5, 6, 7, 26],
        [54, 55, 64, 65],
        [10, 11, 29, 30],
        [1, 2, 21, 22],
        [36, 37, 41, 42, 43],
        [51, 52, 53, 61, 62, 63],
        [8, 9, 27, 28],
        [3, 23, 24, 25],
    ],
}

# normalized coordinates based on the photo (0..1)
TABLE_POSITIONS = {
    1: {"x": 0.06, "y": 0.20},
    2: {"x": 0.12, "y": 0.20},
    3: {"x": 0.18, "y": 0.20},
    4: {"x": 0.24, "y": 0.20},
    5: {"x": 0.30, "y": 0.20},
    6: {"x": 0.36, "y": 0.26},
    7: {"x": 0.50, "y": 0.14},
    8: {"x": 0.58, "y": 0.14},
    9: {"x": 0.66, "y": 0.14},
    10: {"x": 0.74, "y": 0.14},
    11: {"x": 0.82, "y": 0.20},
    21: {"x": 0.06, "y": 0.33},
    22: {"x": 0.12, "y": 0.33},
    23: {"x": 0.18, "y": 0.33},
    24: {"x": 0.24, "y": 0.33},
    25: {"x": 0.30, "y": 0.33},
    26: {"x": 0.50, "y": 0.40},
    27: {"x": 0.58, "y": 0.40},
    28: {"x": 0.66, "y": 0.40},
    29: {"x": 0.74, "y": 0.40},
    30: {"x": 0.82, "y": 0.40},
    31: {"x": 0.44, "y": 0.08},
    32: {"x": 0.52, "y": 0.08},
    33: {"x": 0.60, "y": 0.08},
    34: {"x": 0.68, "y": 0.08},
    35: {"x": 0.76, "y": 0.08},
    36: {"x": 0.84, "y": 0.08},
    37: {"x": 0.92, "y": 0.08},
    41: {"x": 0.40, "y": 0.12},
    42: {"x": 0.48, "y": 0.12},
    43: {"x": 0.56, "y": 0.12},
    51: {"x": 0.14, "y": 0.60},
    52: {"x": 0.22, "y": 0.60},
    53: {"x": 0.30, "y": 0.60},
    54: {"x": 0.38, "y": 0.60},
    55: {"x": 0.46, "y": 0.60},
    61: {"x": 0.70, "y": 0.60},
    62: {"x": 0.76, "y": 0.60},
    63: {"x": 0.82, "y": 0.60},
    64: {"x": 0.88, "y": 0.60},
    65: {"x": 0.94, "y": 0.60},
}
for t in range(1, 66):
    if t not in TABLE_POSITIONS:
        TABLE_POSITIONS[t] = {"x": 0.5, "y": 0.5}

# -------------------
# State (in-memory mirror of sheet)
# -------------------
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

def default_state():
    # default minimal state
    num_sections = 3
    tables = []
    plan = get_plan_tables(num_sections)
    for idx, sec in enumerate(plan):
        for t in sec:
            tables.append({"table": t, "section": idx + 1, "status": "Available", "server": None, "party": None})
    return {
        "waitlist": [],
        "servers": [],
        "present_servers": [],
        "tables": tables,
        "seating_rotation": [],
        "server_scores": {},
        "seating_direction": "Up",
        "last_sat_server": None,
    }

def read_state_from_sheet() -> Dict:
    """Read JSON payload from A1"""
    try:
        val = ws.acell("A1").value
        if not val:
            return default_state()
        return json.loads(val)
    except Exception as e:
        print("read_state_from_sheet error:", e)
        return default_state()

def write_state_to_sheet(state: Dict):
    """Write JSON to A1"""
    try:
        ws.update("A1", [[json.dumps(state, ensure_ascii=False)]])
    except Exception as e:
        print("write_state_to_sheet error:", e)

# load initial state
with state_lock:
    STATE = read_state_from_sheet()

# -------------------
# Helper utils
# -------------------
def persist_state():
    with state_lock:
        write_state_to_sheet(STATE)

def get_plan_tables(num_sections: int):
    plan = TABLE_PLANS.get(num_sections)
    if not plan:
        # fallback to 3-plan flattened
        flat = []
        for sec in TABLE_PLANS[3]:
            flat += sec
        return [flat]
    return plan

def initialize_tables(num_sections: int):
    plan = get_plan_tables(num_sections)
    tables = []
    for idx, sec in enumerate(plan):
        for t in sec:
            tables.append({"table": t, "section": idx + 1, "status": "Available", "server": None, "party": None})
    return tables

# -------------------
# API endpoints
# -------------------

@app.route("/api/state", methods=["GET"])
def api_get_state():
    """Return current STATE"""
    with state_lock:
        return jsonify(STATE)

@app.route("/api/add_waitlist", methods=["POST"])
def api_add_waitlist():
    payload = request.json or {}
    name = payload.get("name")
    party_size = int(payload.get("party_size", 2))
    phone = payload.get("phone", "")
    notes = payload.get("notes", "")
    min_wait = int(payload.get("min_wait", 0))
    max_wait = int(payload.get("max_wait", 30))
    if not name:
        return jsonify({"ok": False, "error": "Missing name"}), 400
    entry = {
        "name": name,
        "party_size": party_size,
        "phone": phone,
        "notes": notes,
        "added_time": time.time(),
        "min_wait": min_wait,
        "max_wait": max_wait,
    }
    with state_lock:
        STATE["waitlist"].append(entry)
        persist_state()
    return jsonify({"ok": True, "entry": entry})

@app.route("/api/remove_waitlist", methods=["POST"])
def api_remove_waitlist():
    idx = int((request.json or {}).get("index", -1))
    with state_lock:
        if 0 <= idx < len(STATE["waitlist"]):
            removed = STATE["waitlist"].pop(idx)
            persist_state()
            return jsonify({"ok": True, "removed": removed})
        else:
            return jsonify({"ok": False, "error": "Invalid index"}), 400

@app.route("/api/add_server", methods=["POST"])
def api_add_server():
    name = (request.json or {}).get("name")
    if not name:
        return jsonify({"ok": False, "error": "Missing name"}), 400
    with state_lock:
        current_sections = [s["section"] for s in STATE["servers"]]
        next_section = max(current_sections, default=0) + 1 if len(current_sections) < 9 else None
        if next_section is None:
            return jsonify({"ok": False, "error": "Maximum servers reached"}), 400
        STATE["servers"].append({"name": name, "section": next_section})
        STATE["server_scores"].setdefault(name, 0)
        # re-initialize table sections count
        num_sections = min(max(len(STATE["servers"]), 1), 9)
        STATE["tables"] = initialize_tables(num_sections)
        persist_state()
    return jsonify({"ok": True})

@app.route("/api/remove_server", methods=["POST"])
def api_remove_server():
    idx = int((request.json or {}).get("index", -1))
    with state_lock:
        if 0 <= idx < len(STATE["servers"]):
            removed = STATE["servers"].pop(idx)
            STATE["present_servers"] = [p for p in STATE.get("present_servers", []) if p != removed["name"]]
            STATE["server_scores"].pop(removed["name"], None)
            num_sections = min(max(len(STATE["servers"]), 1), 9)
            STATE["tables"] = initialize_tables(num_sections)
            persist_state()
            return jsonify({"ok": True, "removed": removed})
        return jsonify({"ok": False, "error": "Invalid index"}), 400

@app.route("/api/set_present_servers", methods=["POST"])
def api_set_present_servers():
    names = request.json.get("present", [])
    with state_lock:
        STATE["present_servers"] = list(names)
        # ensure scores exist
        for n in names:
            STATE["server_scores"].setdefault(n, 0)
        persist_state()
    return jsonify({"ok": True})

@app.route("/api/click_table", methods=["POST"])
def api_click_table():
    """Cycle a table's status: Available -> Taken -> Bussing -> Available.
    If moving Available->Taken, increment server score for that section's server (if present).
    """
    tnum = int((request.json or {}).get("table", -1))
    with state_lock:
        tbl = next((t for t in STATE["tables"] if t["table"] == tnum), None)
        if not tbl:
            return jsonify({"ok": False, "error": "Table not found"}), 404
        old = tbl.get("status", "Available")
        if old == "Available":
            tbl["status"] = "Taken"
            sec = tbl.get("section")
            server_for_section = next((s["name"] for s in STATE["servers"] if s["section"] == sec), None)
            if server_for_section:
                STATE["server_scores"].setdefault(server_for_section, 0)
                STATE["server_scores"][server_for_section] += 1
                STATE["last_sat_server"] = server_for_section
        elif old == "Taken":
            tbl["status"] = "Bussing"
        else:
            tbl["status"] = "Available"
            tbl["party"] = None
            tbl["server"] = None
        persist_state()
    return jsonify({"ok": True, "status": tbl["status"]})

@app.route("/api/seat_table", methods=["POST"])
def api_seat_table():
    data = request.json or {}
    tnum = int(data.get("table", -1))
    wait_idx = data.get("wait_index")  # optional index
    manual_name = data.get("manual_name")
    with state_lock:
        tbl = next((t for t in STATE["tables"] if t["table"] == tnum), None)
        if not tbl:
            return jsonify({"ok": False, "error": "Table not found"}), 404
        sec = tbl.get("section")
        server_for_section = next((s["name"] for s in STATE["servers"] if s["section"] == sec), None)
        # increment server score if seating from Available
        if tbl.get("status", "Available") == "Available" and server_for_section:
            STATE["server_scores"].setdefault(server_for_section, 0)
            STATE["server_scores"][server_for_section] += 1
            STATE["last_sat_server"] = server_for_section
        if wait_idx is not None:
            try:
                wait_idx = int(wait_idx)
                if 0 <= wait_idx < len(STATE["waitlist"]):
                    guest = STATE["waitlist"].pop(wait_idx)
                    tbl["status"] = "Taken"
                    tbl["party"] = guest["name"]
                    tbl["server"] = server_for_section
                    persist_state()
                    return jsonify({"ok": True, "seated": guest})
                else:
                    return jsonify({"ok": False, "error": "Invalid waitlist index"}), 400
            except Exception:
                return jsonify({"ok": False, "error": "Invalid wait_index"}), 400
        elif manual_name:
            tbl["status"] = "Taken"
            tbl["party"] = manual_name
            tbl["server"] = server_for_section
            persist_state()
            return jsonify({"ok": True})
        else:
            # seat unknown
            tbl["status"] = "Taken"
            tbl["party"] = "Unknown Party"
            tbl["server"] = server_for_section
            persist_state()
            return jsonify({"ok": True})

@app.route("/api/clear_table", methods=["POST"])
def api_clear_table():
    tnum = int((request.json or {}).get("table", -1))
    with state_lock:
        tbl = next((t for t in STATE["tables"] if t["table"] == tnum), None)
        if not tbl:
            return jsonify({"ok": False, "error": "Table not found"}), 404
        tbl["status"] = "Available"
        tbl["party"] = None
        tbl["server"] = None
        persist_state()
    return jsonify({"ok": True})

# -------------------
# Frontend page
# -------------------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Host Coordinating — Visual</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    body { font-family: Inter, system-ui, Arial; margin:0; padding:16px; background:#fafafa; color:#111; }
    .topbar { display:flex; gap:12px; align-items:center; margin-bottom:12px; }
    .container { display:flex; gap:12px; }
    .left, .right { width: 360px; max-width: 360px; }
    .main { flex:1; min-width:300px; }
    .floor { position:relative; width:100%; height:72vh; background:white; border-radius:8px; border:1px solid rgba(0,0,0,0.06); overflow:hidden; }
    .table { position:absolute; width:56px; height:56px; border-radius:28px; display:flex; align-items:center; justify-content:center; color:#fff; font-weight:700; cursor:pointer; transform:translate(-50%,-50%); box-shadow:0 2px 8px rgba(0,0,0,0.08); border:2px solid rgba(0,0,0,0.06); text-decoration:none; }
    .available { background:#2ecc71; }
    .taken { background:#e74c3c; }
    .bussing { background:#f1c40f; color:#000; }
    .section-label { position:absolute; padding:6px 8px; border-radius:6px; font-weight:600; color:#111; box-shadow:0 1px 3px rgba(0,0,0,0.06); transform:translate(-50%,-50%); }
    .bar-area { position:absolute; border:2px dashed rgba(0,0,0,0.12); border-radius:8px; background:rgba(0,0,0,0.02); }
    .controls { background:#fff; border-radius:8px; padding:12px; border:1px solid rgba(0,0,0,0.06); }
    input, select, button { font-size:14px; padding:8px; margin:6px 0; width:100%; box-sizing:border-box; border-radius:6px; border:1px solid rgba(0,0,0,0.08); }
    button { cursor:pointer; background:#2b8cff; color:white; border:none; }
    .legend { display:flex; gap:8px; align-items:center; }
    .legend div { display:flex; gap:6px; align-items:center; }
    .legend .box { width:16px; height:16px; border-radius:4px; }
    .small { font-size:13px; color:#555; }
    .server-list { max-height:220px; overflow:auto; }
  </style>
</head>
<body>
  <div class="topbar">
    <h2 style="margin:0">Host Coordinating — Visual</h2>
    <div style="flex:1"></div>
    <div class="legend">
      <div><div class="box" style="background:#2ecc71"></div> Available</div>
      <div><div class="box" style="background:#e74c3c"></div> Taken</div>
      <div><div class="box" style="background:#f1c40f"></div> Bussing</div>
    </div>
  </div>

  <div class="container">
    <div class="left controls">
      <h4>Waitlist</h4>
      <div id="waitlist_area" class="small"></div>
      <hr/>
      <h4>Add to Waitlist</h4>
      <input id="w_name" placeholder="Name"/>
      <input id="w_party" placeholder="Party size (2)"/>
      <input id="w_phone" placeholder="Phone (optional)"/>
      <input id="w_notes" placeholder="Notes (optional)"/>
      <button onclick="addWaitlist()">Add</button>
      <hr/>
      <h4>Servers</h4>
      <div class="server-list" id="servers_area"></div>
      <input id="srv_name" placeholder="Server name"/>
      <button onclick="addServer()">Add server</button>
      <hr/>
      <h4>Present Servers (daily)</h4>
      <div id="present_area"></div>
      <button onclick="savePresent()">Save present servers</button>
    </div>

    <div class="main">
      <div id="floor" class="floor"></div>
      <div style="margin-top:8px">
        <div id="selected_info" class="small">Click a table to select it.</div>
      </div>
    </div>

    <div class="right controls">
      <h4>Quick Actions</h4>
      <div id="selected_controls">
        <div class="small" id="sel_details">No table selected</div>
        <select id="seat_select"></select>
        <input id="manual_name" placeholder="Manual party name"/>
        <button onclick="seatSelected()">Seat selected / manual</button>
        <button onclick="clearSelected()">Clear selected</button>
        <button onclick="bussSelected()">Mark bussing</button>
      </div>
      <hr/>
      <h4>Seating Suggestion</h4>
      <div id="suggestion" class="small"></div>
    </div>
  </div>

<script>
let STATE = null;
let selected_table = null;

function fetchState(){
  fetch('/api/state').then(r=>r.json()).then(s=>{
    STATE = s;
    renderWaitlist();
    renderServers();
    renderFloor();
    renderSuggestion();
  });
}

function renderWaitlist(){
  const el = document.getElementById('waitlist_area');
  if(!STATE.waitlist || STATE.waitlist.length===0){
    el.innerHTML = "<div class='small'>Waitlist empty</div>";
    return;
  }
  let html = '<ol>';
  const now = Date.now()/1000;
  STATE.waitlist.forEach((g,i)=>{
    const waitm = Math.floor((now - (g.added_time||now))/60);
    html += `<li><strong>${g.name}</strong> (p:${g.party_size}) — ${g.phone || 'No phone'} — ${waitm} min</li>`;
  });
  html += '</ol>';
  el.innerHTML = html;
  // populate seat select
  const sel = document.getElementById('seat_select');
  sel.innerHTML = '<option value="">-- none --</option>';
  STATE.waitlist.forEach((g,i)=>{
    sel.innerHTML += `<option value="${i}">${i+1}. ${g.name} (p:${g.party_size})</option>`;
  });
}

function renderServers(){
  const el = document.getElementById('servers_area');
  if(!STATE.servers || STATE.servers.length===0){
    el.innerHTML = "<div class='small'>No servers</div>";
  } else {
    let html = '<ul class="small">';
    STATE.servers.forEach((s,i)=>{
      html += `<li>${i+1}. ${s.name} (Section ${s.section})</li>`;
    });
    html += '</ul>';
    el.innerHTML = html;
  }

  // present servers checkboxes
  const pres = document.getElementById('present_area');
  pres.innerHTML = '';
  STATE.servers.forEach(s=>{
    const ch = document.createElement('div');
    ch.innerHTML = `<label><input type="checkbox" value="${s.name}" ${STATE.present_servers && STATE.present_servers.indexOf(s.name)!==-1 ? 'checked':''}/> ${s.name} (sec ${s.section})</label>`;
    pres.appendChild(ch);
  });
}

function savePresent(){
  const boxes = Array.from(document.querySelectorAll('#present_area input[type=checkbox]'));
  const vals = boxes.filter(b=>b.checked).map(b=>b.value);
  fetch('/api/set_present_servers', {
    method:'POST',
    headers:{'content-type':'application/json'},
    body: JSON.stringify({present: vals})
  }).then(()=>fetchState());
}

function renderFloor(){
  const el = document.getElementById('floor');
  el.innerHTML = '';
  // draw bar area (non-clickable) - fixed region
  const bar = document.createElement('div');
  bar.className = 'bar-area';
  bar.style.left = '45%'; bar.style.top = '6%';
  bar.style.width = '40%'; bar.style.height = '18%';
  bar.style.transform = 'translate(-50%,-50%)';
  el.appendChild(bar);

  // section labels
  const plan = (function(){
    const numS = Math.max(1, Math.min(9, STATE.servers.length || 3));
    // build plan using server count
    let plan = null;
    try {
      plan = {{plan_map}};
    } catch(e){
      plan = null;
    }
    return plan;
  })();

  // draw tables
  STATE.tables.forEach(tbl=>{
    const pos = ({{pos_map}})[tbl.table] || {x:0.5,y:0.5};
    const node = document.createElement('a');
    node.className = 'table ' + (tbl.status==='Available'?'available':(tbl.status==='Taken'?'taken':'bussing'));
    node.style.left = (pos.x*100)+'%';
    node.style.top = (pos.y*100)+'%';
    node.innerText = tbl.table;
    node.title = `Table ${tbl.table} | Section ${tbl.section} | Server: ${tbl.server || 'No server'} | Status: ${tbl.status}`;
    node.onclick = (ev)=>{
      ev.preventDefault();
      // call API to toggle
      fetch('/api/click_table', {
        method:'POST',
        headers:{'content-type':'application/json'},
        body: JSON.stringify({table: tbl.table})
      }).then(r=>r.json()).then(()=>fetchState());
    };
    el.appendChild(node);
  });

  // section labels (center computed via positions)
  // compute centers here in JS for display of server name
  const planTables = ({{plan_map}})[Math.max(1, Math.min(9, STATE.servers.length || 3))] || [];
  // compute centers:
  const sections = planTables.map((sec, idx)=>{
    let xs = 0, ys = 0;
    sec.forEach(t=>{
      const p = ({{pos_map}})[t] || {x:0.5,y:0.5};
      xs += p.x; ys += p.y;
    });
    const cx = (xs / sec.length) * 100;
    const cy = (ys / sec.length) * 100 - 8;
    return {x: cx, y: cy};
  });
  sections.forEach((c, idx)=>{
    const secn = idx+1;
    const svr = STATE.servers.find(s=>s.section===secn);
    const label = document.createElement('div');
    label.className = 'section-label';
    label.style.left = c.x + '%';
    label.style.top = c.y + '%';
    label.style.background = ['#a8d0e6','#f7d794','#f6b93b','#f8a5c2','#c7ecee','#d6a2e8','#b8e994','#f6e58d','#badc58'][(idx)%9];
    label.innerHTML = `Section ${secn}<br/><span style="font-weight:700">${svr ? svr.name : 'No server'}</span>`;
    document.getElementById('floor').appendChild(label);
  });

  // update selected info if selected_table matches
  if(selected_table){
    const t = STATE.tables.find(x=>x.table===selected_table);
    if(t){
      document.getElementById('sel_details').innerText = `Selected ${selected_table} — Status: ${t.status} — Section: ${t.section} — Server: ${t.server || 'No server'}`;
    } else {
      document.getElementById('sel_details').innerText = `Selected ${selected_table}`;
    }
  }
}

function renderSuggestion(){
  let suggestionText = 'No suggestion available.';
  const present = STATE.present_servers || [];
  const rotation = STATE.seating_rotation ? STATE.seating_rotation.filter(r=>present.indexOf(r)!==-1) : [];
  if(rotation.length){
    let minScore = Infinity;
    rotation.forEach(s=>{
      const sc = STATE.server_scores && STATE.server_scores[s] ? STATE.server_scores[s] : 0;
      if(sc < minScore) minScore = sc;
    });
    const candidates = rotation.filter(s => (STATE.server_scores && STATE.server_scores[s] ? STATE.server_scores[s] : 0) === minScore);
    if(candidates.length){
      suggestionText = `Suggested server: ${candidates[0]}.`;
      if(STATE.waitlist && STATE.waitlist.length){
        suggestionText = `Seat next party (${STATE.waitlist[0].name}) with server: ${candidates[0]}`;
      }
    }
  }
  document.getElementById('suggestion').innerText = suggestionText;
}

function addWaitlist(){
  const name = document.getElementById('w_name').value.trim();
  const party = parseInt(document.getElementById('w_party').value || 2);
  const phone = document.getElementById('w_phone').value.trim();
  const notes = document.getElementById('w_notes').value.trim();
  if(!name) return alert('Name required');
  fetch('/api/add_waitlist', {
    method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({name, party_size: party, phone, notes})
  }).then(()=>fetchState());
}

function addServer(){
  const name = document.getElementById('srv_name').value.trim();
  if(!name) return alert('Server name required');
  fetch('/api/add_server', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({name})})
    .then(()=>fetchState());
}

function seatSelected(){
  if(!selected_table) return alert('Select a table from the floor first');
  const sel = document.getElementById('seat_select').value;
  const manual = document.getElementById('manual_name').value.trim();
  let payload = {table: selected_table};
  if(sel) payload.wait_index = parseInt(sel);
  if(manual) payload.manual_name = manual;
  fetch('/api/seat_table', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(payload)})
    .then(()=>{ fetchState(); });
}

function clearSelected(){
  if(!selected_table) return alert('Select a table');
  fetch('/api/clear_table', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({table:selected_table})})
    .then(()=>{ selected_table = null; fetchState(); });
}

function bussSelected(){ 
  if(!selected_table) return alert('Select a table');
  fetch('/api/click_table', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({table:selected_table})})
    .then(()=>fetchState());
}

document.addEventListener('click', function(e){
  // if clicked a table element, set selected_table
  const el = e.target;
  if(el.classList && el.classList.contains('table')){
    selected_table = parseInt(el.innerText);
    // show selected area details
    const t = STATE.tables.find(x=>x.table===selected_table);
    document.getElementById('sel_details').innerText = `Selected ${selected_table} — Status: ${t.status} — Section: ${t.section} — Server: ${t.server || 'No server'}`;
    // set the seat_select dropdown to none to avoid mismatch
    document.getElementById('seat_select').value = '';
  }
});

fetchState();
setInterval(fetchState, 5000); // poll every 5s
</script>

</body>
</html>
"""

# -------------------
# Template injection helpers
# -------------------
# We inject the TABLE_POSITIONS and TABLE_PLANS as JSON strings into the HTML template
@app.route("/")
def index():
    template = INDEX_HTML
    # basic injection: plan_map and pos_map placeholders replaced by JSON literals
    plan_map_json = json.dumps({k: v for k, v in TABLE_PLANS.items()})
    pos_map_json = json.dumps(TABLE_POSITIONS)
    # replace the placeholders ({{plan_map}} and {{pos_map}}) safely
    template = template.replace("{{plan_map}}", plan_map_json)
    template = template.replace("{{pos_map}}", pos_map_json)
    return render_template_string(template)

# -------------------
# Run
# -------------------
if __name__ == "__main__":
    # ensure STATE consistency on startup
    with state_lock:
        # if sheet was empty/contains {}, initialize default
        if not STATE or (isinstance(STATE, dict) and len(STATE)==0):
            STATE = default_state()
            write_state_to_sheet(STATE)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8501)), debug=False)
