from flask import Flask, render_template, request, jsonify
from datetime import datetime
import os

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), 'static')
)

# In-memory data
state = {
    "waitlist": [],
    "tables": {},
    "servers": {},  # {name: {"present": bool, "section": int}}
    "rotation": "up"
}

def init_state():
    if state["tables"]:
        return
    tid = 1
    for section in range(1, 4):
        for tnum in range(1, 5):
            table_id = f"T{tid}"
            state["tables"][table_id] = {
                "id": table_id,
                "name": f"Table {tid}",
                "seats": 4 if tnum % 2 == 1 else 2,
                "section": section,
                "status": "empty",
                "server": None,
                "seated_at": None,
                "notes": ""
            }
            tid += 1
    # default servers
    for name in ["Alice", "Ben", "Carmen", "Diego"]:
        state["servers"][name] = {"present": True, "section": 1}
init_state()

def server_loads():
    loads = {s: 0 for s in state["servers"].keys()}
    for t in state["tables"].values():
        if t["server"] and t["status"] == "seated":
            loads[t["server"]] = loads.get(t["server"], 0) + 1
    return loads

@app.route("/")
def index():
    return render_template("index.html", state=state, server_loads=server_loads())

@app.route("/api/state")
def api_state():
    return jsonify({
        "waitlist": state["waitlist"],
        "tables": state["tables"],
        "servers": state["servers"],
        "server_loads": server_loads(),
        "rotation": state["rotation"],
        "now": datetime.utcnow().isoformat() + "Z"
    })

@app.route("/api/add_server", methods=["POST"])
def add_server():
    data = request.json or {}
    name = data.get("name", "").strip()
    section = int(data.get("section", 1))
    if not name:
        return jsonify({"error": "Server name required"}), 400
    if name in state["servers"]:
        return jsonify({"error": "Server already exists"}), 400
    state["servers"][name] = {"present": True, "section": section}
    return jsonify({"ok": True, "servers": state["servers"]})

@app.route("/api/update_server", methods=["POST"])
def update_server():
    data = request.json or {}
    name = data.get("name")
    present = data.get("present", True)
    section = int(data.get("section", 1))
    if name not in state["servers"]:
        return jsonify({"error": "Server not found"}), 400
    state["servers"][name]["present"] = bool(present)
    state["servers"][name]["section"] = section
    return jsonify({"ok": True, "servers": state["servers"]})

@app.route("/api/add_wait", methods=["POST"])
def add_wait():
    data = request.json or {}
    name = data.get("name", "").strip()
    party = int(data.get("party", 1))
    notes = data.get("notes", "")
    if not name:
        return jsonify({"error": "Name required"}), 400
    wid = f"W{int(datetime.utcnow().timestamp() * 1000)}"
    entry = {
        "id": wid,
        "name": name,
        "party": party,
        "notes": notes,
        "added_at": datetime.utcnow().isoformat() + "Z",
        "status": "waiting"
    }
    state["waitlist"].append(entry)
    return jsonify(entry)

@app.route("/api/remove_wait", methods=["POST"])
def remove_wait():
    wid = (request.json or {}).get("id")
    state["waitlist"] = [w for w in state["waitlist"] if w["id"] != wid]
    return jsonify({"ok": True})

@app.route("/api/seat_table", methods=["POST"])
def seat_table():
    data = request.json or {}
    table_id = data.get("table_id")
    wait_id = data.get("wait_id")
    server = data.get("server")
    notes = data.get("notes", "")
    if table_id not in state["tables"]:
        return jsonify({"error": "Invalid table"}), 400
    table = state["tables"][table_id]
    table["status"] = "seated"
    table["server"] = server
    table["seated_at"] = datetime.utcnow().isoformat() + "Z"
    table["notes"] = notes
    if wait_id:
        state["waitlist"] = [w for w in state["waitlist"] if w["id"] != wait_id]
    return jsonify(table)

@app.route("/api/bus_table", methods=["POST"])
def bus_table():
    tid = (request.json or {}).get("table_id")
    if tid not in state["tables"]:
        return jsonify({"error": "Invalid table"}), 400
    table = state["tables"][tid]
    table["status"] = "dirty"
    return jsonify(table)

@app.route("/api/clear_table", methods=["POST"])
def clear_table():
    tid = (request.json or {}).get("table_id")
    if tid not in state["tables"]:
        return jsonify({"error": "Invalid table"}), 400
    t = state["tables"][tid]
    t.update({"status": "empty", "server": None, "seated_at": None, "notes": ""})
    return jsonify(t)

@app.route("/api/set_rotation", methods=["POST"])
def set_rotation():
    rot = (request.json or {}).get("rotation", "up")
    if rot not in ("up", "down"):
        return jsonify({"error": "Invalid rotation"}), 400
    state["rotation"] = rot
    return jsonify({"rotation": rot})

@app.route("/api/suggest_server")
def suggest_server():
    loads = server_loads()
    present_servers = [s for s, v in state["servers"].items() if v["present"]]
    if not present_servers:
        return jsonify({"suggestion": None, "loads": loads})
    servers = sorted(present_servers) if state["rotation"] == "up" else sorted(present_servers, reverse=True)
    min_load = min([loads.get(s, 0) for s in servers]) if servers else 0
    candidates = [s for s in servers if loads.get(s, 0) == min_load]
    suggestion = candidates[0] if candidates else servers[0]
    return jsonify({"suggestion": suggestion, "loads": loads})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
