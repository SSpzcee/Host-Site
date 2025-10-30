#!/usr/bin/env python3
import os
import json
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, send_from_directory

app = Flask(__name__)
app.logger.setLevel("DEBUG")

# Configuration
GOOGLE_CREDS_ENV = "GOOGLE_CREDS"   # env var containing service account JSON
SPREADSHEET_ID_ENV = "SPREADSHEET_ID"
STATE_FILE = Path("/tmp/state_store.json")  # fallback local persistence

# Default state (adjust table positions to match your map image)
DEFAULT_STATE = {
    "waitlist": [],
    "servers": [],
    "present_servers": [],
    "tables": {},
    "table_positions": {
        "t1": {"left": 10, "top": 20},
        "t2": {"left": 30, "top": 20},
        "t3": {"left": 50, "top": 20},
        "t4": {"left": 70, "top": 20},
        "t5": {"left": 20, "top": 60},
        "t6": {"left": 40, "top": 60},
        "t7": {"left": 60, "top": 60},
    },
    "rotation_direction": "clockwise"
}

def load_state_from_sheet():
    """Try Sheets; if that fails, fallback to a local JSON file; if that fails, use DEFAULT_STATE."""
    creds_json = os.environ.get(GOOGLE_CREDS_ENV)
    if creds_json:
        try:
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            creds_dict = json.loads(creds_json)
            scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            SPREADSHEET_ID = os.environ.get(SPREADSHEET_ID_ENV)
            if SPREADSHEET_ID:
                sh = client.open_by_key(SPREADSHEET_ID)
                try:
                    ws = sh.worksheet("state")
                    raw = ws.acell("A1").value or ""
                    if raw:
                        app.logger.debug("Loaded state from Google Sheets")
                        return json.loads(raw)
                except Exception:
                    app.logger.exception("Failed reading 'state' worksheet")
            else:
                app.logger.debug("SPREADSHEET_ID not set; skipping Sheets load")
        except Exception:
            app.logger.exception("Google Sheets load failed (falling back)")

    # Fallback local file
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            app.logger.debug("Loaded state from local file")
            return data
        except Exception:
            app.logger.exception("Failed to parse local state file")

    app.logger.debug("Using DEFAULT_STATE")
    return DEFAULT_STATE.copy()

def save_state_to_sheet(state):
    """Try to save to Sheets; if that fails, save to local file."""
    creds_json = os.environ.get(GOOGLE_CREDS_ENV)
    if creds_json:
        try:
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            creds_dict = json.loads(creds_json)
            scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            SPREADSHEET_ID = os.environ.get(SPREADSHEET_ID_ENV)
            if SPREADSHEET_ID:
                sh = client.open_by_key(SPREADSHEET_ID)
                try:
                    ws = sh.worksheet("state")
                except Exception:
                    ws = sh.add_worksheet(title="state", rows="100", cols="20")
                ws.update_acell("A1", json.dumps(state))
                app.logger.debug("Saved state to Google Sheets")
                return
        except Exception:
            app.logger.exception("Saving to Google Sheets failed; will fallback to file")

    # fallback to local
    try:
        STATE_FILE.write_text(json.dumps(state))
        app.logger.debug("Saved state to local file")
    except Exception:
        app.logger.exception("Saving to local file failed")

# In-memory global state
STATE = load_state_from_sheet()

def next_id(prefix="id"):
    return f"{prefix}_{int(datetime.utcnow().timestamp()*1000)}"

# ---------- API endpoints ----------
@app.route("/api/state", methods=["GET"])
def api_state():
    try:
        return jsonify(STATE)
    except Exception:
        app.logger.exception("api_state failed")
        return jsonify({"error": "failed"}), 500

@app.route("/api/add_waitlist", methods=["POST"])
def api_add_waitlist():
    try:
        payload = request.get_json() or {}
        name = payload.get("name", "").strip() or "Guest"
        party = int(payload.get("party", 1))
        notes = payload.get("notes", "")
        item = {"id": next_id("wl"), "name": name, "party": party, "notes": notes, "ts": datetime.utcnow().isoformat()}
        STATE["waitlist"].append(item)
        save_state_to_sheet(STATE)
        return jsonify({"ok": True, "item": item})
    except Exception:
        app.logger.exception("add_waitlist failed")
        return jsonify({"error":"failed"}), 500

@app.route("/api/remove_waitlist", methods=["POST"])
def api_remove_waitlist():
    try:
        payload = request.get_json() or {}
        item_id = payload.get("id")
        STATE["waitlist"] = [w for w in STATE["waitlist"] if w["id"] != item_id]
        save_state_to_sheet(STATE)
        return jsonify({"ok": True})
    except Exception:
        app.logger.exception("remove_waitlist failed")
        return jsonify({"error":"failed"}), 500

@app.route("/api/add_server", methods=["POST"])
def api_add_server():
    try:
        payload = request.get_json() or {}
        name = payload.get("name", "").strip() or "Server"
        server = {"id": next_id("sv"), "name": name}
        STATE["servers"].append(server)
        save_state_to_sheet(STATE)
        return jsonify({"ok": True, "server": server})
    except Exception:
        app.logger.exception("add_server failed")
        return jsonify({"error":"failed"}), 500

@app.route("/api/remove_server", methods=["POST"])
def api_remove_server():
    try:
        payload = request.get_json() or {}
        sid = payload.get("id")
        STATE["servers"] = [s for s in STATE["servers"] if s["id"] != sid]
        STATE["present_servers"] = [p for p in STATE["present_servers"] if p != sid]
        save_state_to_sheet(STATE)
        return jsonify({"ok": True})
    except Exception:
        app.logger.exception("remove_server failed")
        return jsonify({"error":"failed"}), 500

@app.route("/api/toggle_present", methods=["POST"])
def api_toggle_present():
    try:
        payload = request.get_json() or {}
        sid = payload.get("id")
        if sid in STATE["present_servers"]:
            STATE["present_servers"].remove(sid)
        else:
            STATE["present_servers"].append(sid)
        save_state_to_sheet(STATE)
        return jsonify({"ok": True, "present": STATE["present_servers"]})
    except Exception:
        app.logger.exception("toggle_present failed")
        return jsonify({"error":"failed"}), 500

@app.route("/api/toggle_table", methods=["POST"])
def api_toggle_table():
    try:
        payload = request.get_json() or {}
        tid = payload.get("id")
        if tid not in STATE["tables"]:
            STATE["tables"][tid] = {"occupied_by": None, "available": True}
        STATE["tables"][tid]["available"] = not STATE["tables"][tid].get("available", True)
        save_state_to_sheet(STATE)
        return jsonify({"ok": True, "table": STATE["tables"][tid]})
    except Exception:
        app.logger.exception("toggle_table failed")
        return jsonify({"error":"failed"}), 500

@app.route("/api/seat_table", methods=["POST"])
def api_seat_table():
    try:
        payload = request.get_json() or {}
        tid = payload.get("id")
        server_id = payload.get("server_id")
        guest_name = payload.get("guest_name", "Guest")
        if tid not in STATE["tables"]:
            STATE["tables"][tid] = {"occupied_by": None, "available": True}
        STATE["tables"][tid]["occupied_by"] = {"server_id": server_id, "guest_name": guest_name, "ts": datetime.utcnow().isoformat()}
        save_state_to_sheet(STATE)
        return jsonify({"ok": True, "table": STATE["tables"][tid]})
    except Exception:
        app.logger.exception("seat_table failed")
        return jsonify({"error":"failed"}), 500

@app.route("/api/bus_table", methods=["POST"])
def api_bus_table():
    try:
        payload = request.get_json() or {}
        tid = payload.get("id")
        if tid in STATE["tables"]:
            STATE["tables"][tid]["occupied_by"] = None
            save_state_to_sheet(STATE)
        return jsonify({"ok": True})
    except Exception:
        app.logger.exception("bus_table failed")
        return jsonify({"error":"failed"}), 500

@app.route("/api/save_state", methods=["POST"])
def api_save_state():
    try:
        payload = request.get_json() or {}
        new_state = payload.get("state")
        if not new_state:
            return jsonify({"error": "no state provided"}), 400
        global STATE
        STATE = new_state
        save_state_to_sheet(STATE)
        return jsonify({"ok": True})
    except Exception:
        app.logger.exception("api_save_state failed")
        return jsonify({"error":"failed"}), 500

# Serve local static map if present (place your map.jpg in /static/map.jpg)
@app.route('/static/<path:filename>')
def static_files(filename):
    static_dir = Path.cwd() / "static"
    if (static_dir / filename).exists():
        return send_from_directory(str(static_dir), filename)
    return ("", 404)

# ---------- UI template (single-file) ----------
TEMPLATE = '''<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Host Console</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial; margin:0; background:#f7f7f8; }
    header { padding:12px 16px; background:#fff; border-bottom:1px solid #eee; }
    .container { padding:12px; max-width:1200px; margin:auto; }
    .grid { display:flex; gap:12px; align-items:flex-start; }
    .col { background:#fff; border-radius:8px; padding:12px; box-shadow:0 1px 3px rgba(0,0,0,0.06); }
    .col.left { width:360px; }
    .center-wrap { width:100%; display:flex; justify-content:center; }
    .center { width:100%; max-width:900px; aspect-ratio:16/9; position:relative; border-radius:8px; overflow:hidden;
             background:#fafafa; border:1px solid #e6e6e6; background-size:cover; background-position:center; }
    .center.map-bg { background-image:url('/static/map.jpg'); }
    .table { position:absolute; transform:translate(-50%,-50%); width:64px; height:48px; border-radius:6px;
             display:flex; align-items:center; justify-content:center; font-weight:600; cursor:pointer; user-select:none;
             box-shadow:0 2px 6px rgba(0,0,0,0.08); }
    .table.available { background:#e6ffed; color:#0a7a3b; }
    .table.occupied { background:#ffdede; color:#7a0a0a; }
    .table.unavailable { background:#f0f0f0; color:#666; text-decoration:line-through; }
    button{ padding:8px 10px; border-radius:6px; border:1px solid #ddd; background:#fff; cursor:pointer; }
    input { padding:8px; border-radius:6px; border:1px solid #ddd; width:100%; box-sizing:border-box; }
    #debug_area { max-height:120px; overflow:auto; padding:8px; background:#111; color:#fff; font-family:monospace; font-size:12px; border-radius:6px; margin-top:12px; }
    .list { display:flex; flex-direction:column; gap:8px; margin-top:8px; }
    .list .item { padding:8px; border-radius:6px; border:1px solid #eee; display:flex; justify-content:space-between; align-items:center; gap:8px; }
  </style>
</head>
<body>
  <header><h2>Host Console</h2></header>
  <div class="container">
    <div class="grid">
      <div class="col left">
        <h3>Waitlist</h3>
        <input id="wl_name" placeholder="Name" />
        <div style="display:flex; gap:8px; margin-top:8px;">
          <input id="wl_party" placeholder="Party size" type="number" value="1" style="width:100px;" />
          <button onclick="addWaitlist()">Add</button>
        </div>
        <div class="list" id="waitlist_area"></div>

        <h3 style="margin-top:16px;">Servers</h3>
        <div style="display:flex; gap:8px;">
          <input id="sv_name" placeholder="Server name" />
          <button onclick="addServer()">Add</button>
        </div>
        <div class="list" id="servers_area"></div>

        <h3 style="margin-top:16px;">Options</h3>
        <div class="small">Rotation direction</div>
        <div style="display:flex; gap:8px; margin-top:8px;">
          <button onclick="setRotation('clockwise')">Clockwise</button>
          <button onclick="setRotation('counterclockwise')">Counter</button>
        </div>

        <div id="debug_area"></div>
      </div>

      <div class="col right" style="flex:1;">
        <h3>Seating Chart</h3>
        <div class="center-wrap">
          <div id="center" class="center map-bg"></div>
        </div>
        <div style="margin-top:12px;"><small>Put a <code>/static/map.jpg</code> file in your repo for the background map.</small></div>
      </div>
    </div>
  </div>

<script>
const TABLE_POSITIONS = {{ table_positions | tojson }};
let STATE = null, CENTER = null;

function debug(msg, level='log') {
  const area = document.getElementById('debug_area');
  if (!area) return;
  const p = document.createElement('div');
  p.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  if (level === 'error') p.style.color = 'salmon';
  area.prepend(p);
  console[level]?.(msg);
}

async function fetchJSON(url, opts) {
  try {
    const res = await fetch(url, opts);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch(e){}
    if (!res.ok) {
      const msg = `Request ${url} returned ${res.status} - ${text}`;
      debug(msg, 'error');
      throw new Error(msg);
    }
    return data;
  } catch (err) {
    debug(`Network/error calling ${url}: ${err.message}`, 'error');
    throw err;
  }
}

async function safePostJSON(path, payload) {
  return await fetchJSON(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload || {})
  });
}

document.addEventListener('DOMContentLoaded', () => {
  CENTER = document.getElementById('center');
  if (!CENTER) { debug('center element not found', 'error'); return; }
  refreshState().catch(e => debug('refreshState failed: '+e.message,'error'));
});

async function refreshState() {
  const data = await fetchJSON('/api/state', {method:'GET'});
  if (!data) { debug('No state returned','error'); return; }
  STATE = data;
  renderUI();
}

function renderUI() {
  try { renderWaitlist(); renderServers(); renderTables(); }
  catch(e){ debug('renderUI error: '+e.message,'error'); }
}

/* Waitlist */
function renderWaitlist(){
  const area = document.getElementById('waitlist_area'); area.innerHTML = '';
  (STATE.waitlist||[]).forEach(item=>{
    const d = document.createElement('div'); d.className='item';
    d.innerHTML = `<div>${item.name} (${item.party})</div><div style="display:flex;gap:8px"><button onclick="removeWaitlist('${item.id}')">Remove</button></div>`;
    area.appendChild(d);
  });
}
async function addWaitlist(){
  const name = document.getElementById('wl_name').value || '';
  const party = parseInt(document.getElementById('wl_party').value || 1,10);
  try { await safePostJSON('/api/add_waitlist',{name,party}); await refreshState(); document.getElementById('wl_name').value=''; }
  catch(e){ debug('addWaitlist failed: '+e.message,'error'); }
}
async function removeWaitlist(id){
  try{ await safePostJSON('/api/remove_waitlist',{id}); await refreshState(); } catch(e){ debug('removeWaitlist failed: '+e.message,'error'); }
}

/* Servers */
function renderServers(){
  const area = document.getElementById('servers_area'); area.innerHTML = '';
  (STATE.servers||[]).forEach(s=>{
    const present = (STATE.present_servers||[]).includes(s.id);
    const d = document.createElement('div'); d.className='item';
    d.innerHTML = `<div>${s.name} ${present? ' (present)': ''}</div><div style="display:flex;gap:8px"><button onclick="togglePresent('${s.id}')">${present? 'Unset' : 'Present'}</button><button onclick="removeServer('${s.id}')">Remove</button></div>`;
    area.appendChild(d);
  });
}
async function addServer(){ const name = document.getElementById('sv_name').value || ''; try{ await safePostJSON('/api/add_server',{name}); await refreshState(); document.getElementById('sv_name').value=''; }catch(e){ debug('addServer failed: '+e.message,'error'); } }
async function removeServer(id){ try{ await safePostJSON('/api/remove_server',{id}); await refreshState(); }catch(e){ debug('removeServer failed: '+e.message,'error'); } }
async function togglePresent(id){ try{ await safePostJSON('/api/toggle_present',{id}); await refreshState(); }catch(e){ debug('togglePresent failed: '+e.message,'error'); } }

/* Rotation */
async function setRotation(dir){ try{ STATE.rotation_direction = dir; await safePostJSON('/api/save_state',{state:STATE}); debug('Rotation set to '+dir);}catch(e){ debug('setRotation failed: '+e.message,'error'); } }

/* Tables */
function renderTables(){
  CENTER.innerHTML = '';
  const positions = STATE.table_positions || TABLE_POSITIONS;
  Object.keys(positions).forEach(tid=>{
    if(!STATE.tables) STATE.tables = {};
    if(!(tid in STATE.tables)) STATE.tables[tid] = {"occupied_by": null, "available": True};
    const pos = positions[tid];
    const el = document.createElement('div');
    el.className = 'table ' + (STATE.tables[tid].available ? 'available' : 'unavailable');
    if (STATE.tables[tid].occupied_by) el.classList.add('occupied');
    el.style.left = pos.left + '%';
    el.style.top = pos.top + '%';
    el.id = 'table_' + tid;
    el.innerHTML = `<div style="text-align:center">${tid}</div>`;
    el.onclick = () => tableClicked(tid);
    CENTER.appendChild(el);
  });
}

async function tableClicked(tid){
  try{
    const action = prompt("Action for " + tid + " (seat/toggle/bus):", "seat");
    if(!action) return;
    if(action === 'toggle'){ await safePostJSON('/api/toggle_table',{id:tid}); }
    else if(action === 'bus'){ await safePostJSON('/api/bus_table',{id:tid}); }
    else if(action === 'seat'){
      const serverName = prompt("Server name to seat (leave blank for none):", "");
      let sid = null;
      if(serverName){ const s = (STATE.servers||[]).find(x=>x.name.toLowerCase() === serverName.toLowerCase()); if(s) sid = s.id; }
      const guest = prompt("Guest name:", "Guest");
      await safePostJSON('/api/seat_table',{id:tid, server_id:sid, guest_name:guest});
    }
    await refreshState();
  }catch(e){ debug('tableClicked failed: '+e.message,'error'); }
}

</script>
</body>
</html>'''

@app.route("/", methods=["GET"])
def index():
    try:
        return render_template_string(TEMPLATE, table_positions=STATE.get("table_positions", DEFAULT_STATE["table_positions"]))
    except Exception:
        app.logger.exception("Rendering index failed")
        return "Server error", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
