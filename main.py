from flask import Flask, render_template, request, jsonify
from datetime import datetime
import threading

app = Flask(__name__)

# In-memory state (replace with a DB for production)
state = {
    "waitlist": [],  # list of dicts: {id, name, party, notes, added_at, status}
    "tables": {},    # table_id -> {id, name, seats, section, status, server, seated_at, notes}
    "servers": [],   # list of server names
    "rotation": "up" # "up" or "down"
}

# initialize some tables and servers
def init_state():
    if state["tables"]:
        return
    # Example layout: 12 tables across 3 sections
    tid = 1
    for section in range(1,4):
        for tnum in range(1,5):
            table_id = f"T{tid}"
            state["tables"][table_id] = {
                "id": table_id,
                "name": f"Table {tid}",
                "seats": 4 if tnum%2==1 else 2,
                "section": section,
                "status": "empty", # empty, waiting, seated, dirty
                "server": None,
                "seated_at": None,
                "notes": ""
            }
            tid += 1
    # servers
    state["servers"] = ["Alice","Ben","Carmen","Diego"]
init_state()

# utility to compute server loads (count of currently seated tables per server)
def server_loads():
    loads = {s:0 for s in state["servers"]}
    for t in state["tables"].values():
        if t["server"] and t["status"]=="seated":
            loads[t["server"]] = loads.get(t["server"],0) + 1
    return loads

@app.route("/")
def index():
    return render_template("index.html", state=state, server_loads=server_loads())

@app.route("/api/state")
def api_state():
    # return current state
    return jsonify({
        "waitlist": state["waitlist"],
        "tables": state["tables"],
        "servers": state["servers"],
        "server_loads": server_loads(),
        "rotation": state["rotation"],
        "now": datetime.utcnow().isoformat()+"Z"
    })

@app.route("/api/add_wait", methods=["POST"])
def add_wait():
    data = request.json or {}
    name = data.get("name","").strip()
    party = int(data.get("party",1))
    notes = data.get("notes","")
    if not name:
        return jsonify({"error":"Name required"}),400
    wid = f"W{int(datetime.utcnow().timestamp()*1000)}"
    entry = {
        "id": wid,
        "name": name,
        "party": party,
        "notes": notes,
        "added_at": datetime.utcnow().isoformat()+"Z",
        "status": "waiting"
    }
    state["waitlist"].append(entry)
    return jsonify(entry)

@app.route("/api/remove_wait", methods=["POST"])
def remove_wait():
    data = request.json or {}
    wid = data.get("id")
    state["waitlist"] = [w for w in state["waitlist"] if w["id"]!=wid]
    return jsonify({"ok":True})

@app.route("/api/seat_table", methods=["POST"])
def seat_table():
    data = request.json or {}
    table_id = data.get("table_id")
    wait_id = data.get("wait_id")  # optional: seat from waitlist
    server = data.get("server")
    notes = data.get("notes","")
    if table_id not in state["tables"]:
        return jsonify({"error":"Invalid table"}),400
    table = state["tables"][table_id]
    table["status"] = "seated"
    table["server"] = server
    table["seated_at"] = datetime.utcnow().isoformat()+"Z"
    table["notes"] = notes
    # remove waitlist entry if provided
    if wait_id:
        state["waitlist"] = [w for w in state["waitlist"] if w["id"]!=wait_id]
    return jsonify(table)

@app.route("/api/bus_table", methods=["POST"])
def bus_table():
    data = request.json or {}
    table_id = data.get("table_id")
    if table_id not in state["tables"]:
        return jsonify({"error":"Invalid table"}),400
    table = state["tables"][table_id]
    table["status"] = "dirty"
    return jsonify(table)

@app.route("/api/clear_table", methods=["POST"])
def clear_table():
    data = request.json or {}
    table_id = data.get("table_id")
    if table_id not in state["tables"]:
        return jsonify({"error":"Invalid table"}),400
    table = state["tables"][table_id]
    table["status"] = "empty"
    table["server"] = None
    table["seated_at"] = None
    table["notes"] = ""
    return jsonify(table)

@app.route("/api/set_rotation", methods=["POST"])
def set_rotation():
    data = request.json or {}
    rot = data.get("rotation","up")
    if rot not in ("up","down"):
        return jsonify({"error":"bad rotation"}),400
    state["rotation"] = rot
    return jsonify({"rotation":rot})

@app.route("/api/suggest_server", methods=["GET"])
def suggest_server():
    loads = server_loads()
    # choose server with minimum load; rotate based on state["rotation"]
    servers = list(state["servers"])
    if state["rotation"]=="down":
        servers = list(reversed(servers))
    # pick min load among servers with rotation bias
    min_load = min(loads.values()) if loads else 0
    candidates = [s for s in servers if loads.get(s,0)==min_load]
    # pick the first candidate in rotation order
    suggestion = candidates[0] if candidates else (servers[0] if servers else None)
    return jsonify({"suggestion":suggestion,"loads":loads})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
