import json
import os
from pathlib import Path
import time
from typing import List, Dict

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import gspread
from google.oauth2 import service_account

st.set_page_config(page_title="Coordinating", layout="wide")

# --- Google Sheets setup ---
SHEET_NAME = st.secrets["gcp_service_account"]["sheet_name"]

# Authenticate using secrets
creds = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
)
gc = gspread.authorize(creds)

# Try opening the sheet; if it doesn't exist, create it
try:
    sh = gc.open(SHEET_NAME)
except gspread.SpreadsheetNotFound:
    sh = gc.create(SHEET_NAME)
    sh.share(
        st.secrets["gcp_service_account"]["client_email"],
        perm_type="user",
        role="writer",
    )
ws = sh.sheet1

# --- Persistence config (Google Sheets) ---
def load_persistent_state():
    try:
        data = ws.get_all_values()
        if data and data[0] and data[0][0]:
            raw = data[0][0]
            json_data = json.loads(raw)
            for k, v in json_data.items():
                # restore present_servers as set
                if k == "present_servers" and isinstance(v, list):
                    st.session_state[k] = set(v)
                else:
                    st.session_state[k] = v
    except Exception as e:
        # don't crash the app on load errors
        print("Failed to load persistent state:", e)


def save_persistent_state():
    try:
        keys = [
            "waitlist",
            "servers",
            "present_servers",
            "tables",
            "seating_rotation",
            "server_scores",
            "seating_direction",
            "last_sat_server",
        ]
        data = {}
        for k in keys:
            if k in st.session_state:
                v = st.session_state[k]
                # JSON can't encode sets; convert to list
                if isinstance(v, set):
                    v = list(v)
                data[k] = v
        json_str = json.dumps(data, ensure_ascii=False)
        ws.update("A1", [[json_str]])
    except Exception as e:
        print("Failed to save persistent state:", e)


# --- Callbacks (use on_click to avoid double-click issues) ---
def _remove_mark_callback(server_name: str, section_idx: int):
    cur = st.session_state["server_scores"].get(server_name, 0)
    if cur > 0:
        st.session_state["server_scores"][server_name] = cur - 1
    st.session_state[f"remove_mark_msg_{section_idx}"] = server_name
    save_persistent_state()


def _skip_server_callback(server_name: str, section_idx: int):
    # increment by 1 only
    st.session_state["server_scores"].setdefault(server_name, 0)
    st.session_state["server_scores"][server_name] += 1
    st.session_state[f"skip_msg_{section_idx}"] = server_name
    save_persistent_state()


def seat_table_callback(table_num: int, server_name: str, selected_waitlist_idx: int | None = None, manual_name: str | None = None):
    """
    Seat either the selected waitlist person (selected_waitlist_idx) or the manual_name at table_num.
    If selected_waitlist_idx is provided, remove that person from the waitlist.
    This function updates table status and server score.
    """
    this_table = next((t for t in st.session_state["tables"] if t["table"] == table_num), None)
    if this_table is None:
        st.session_state[f"seat_msg_{table_num}"] = "Table not found"
        return

    # increment server score once for seating
    if server_name:
        st.session_state["server_scores"].setdefault(server_name, 0)
        st.session_state["server_scores"][server_name] += 1
        st.session_state["last_sat_server"] = server_name

    if selected_waitlist_idx is not None and 0 <= selected_waitlist_idx < len(st.session_state["waitlist"]):
        guest = st.session_state["waitlist"].pop(selected_waitlist_idx)
        this_table["status"] = "Taken"
        this_table["party"] = guest["name"]
        this_table["server"] = server_name
        st.session_state[f"seat_msg_{table_num}"] = f"Seated {guest['name']} at Table {table_num}."
    elif manual_name:
        this_table["status"] = "Taken"
        this_table["party"] = manual_name
        this_table["server"] = server_name
        st.session_state[f"seat_msg_{table_num}"] = f"Seated {manual_name} at Table {table_num}."
    else:
        # If nothing chosen, still mark as taken with unknown party
        this_table["status"] = "Taken"
        this_table["party"] = "Unknown Party"
        this_table["server"] = server_name
        st.session_state[f"seat_msg_{table_num}"] = f"Seated Unknown Party at Table {table_num}."

    save_persistent_state()


def bus_table_callback(table_num: int):
    for table in st.session_state["tables"]:
        if table["table"] == table_num:
            table["status"] = "Bussing"
            st.session_state[f"bus_msg_{table_num}"] = f"Table {table_num} marked as Bussing."
            save_persistent_state()
            return
    st.session_state[f"bus_msg_{table_num}"] = "Table not found"


def clear_table_callback(table_num: int):
    for table in st.session_state["tables"]:
        if table["table"] == table_num:
            table["status"] = "Available"
            table["party"] = None
            table["server"] = None
            st.session_state[f"clear_msg_{table_num}"] = f"Table {table_num} is now available."
            save_persistent_state()
            return
    st.session_state[f"clear_msg_{table_num}"] = "Table not found"


def remove_waitlist_callback():
    idx = st.session_state.get("remove_waitlist_idx", 1) - 1
    if 0 <= idx < len(st.session_state["waitlist"]):
        removed = st.session_state["waitlist"].pop(idx)
        st.session_state["remove_waitlist_msg"] = f"Removed {removed['name']} from waitlist."
        save_persistent_state()
    else:
        st.session_state["remove_waitlist_msg"] = "Invalid index"


def remove_server_callback():
    idx = st.session_state.get("remove_server_idx", 1) - 1
    if 0 <= idx < len(st.session_state["servers"]):
        removed = st.session_state["servers"].pop(idx)
        st.session_state["present_servers"].discard(removed["name"])
        if removed["name"] in st.session_state["server_scores"]:
            del st.session_state["server_scores"][removed["name"]]
        num_sections = min(max(len(st.session_state["servers"]), 1), 9)
        st.session_state["tables"] = initialize_tables(num_sections)
        st.session_state["remove_server_msg"] = f"Removed server {removed['name']} from section {removed['section']}."
        save_persistent_state()
    else:
        st.session_state["remove_server_msg"] = "Invalid server index"


# --- Session State Initialization ---
load_persistent_state()

if "waitlist" not in st.session_state:
    st.session_state["waitlist"] = []
if "servers" not in st.session_state:
    st.session_state["servers"] = []
if "present_servers" not in st.session_state:
    st.session_state["present_servers"] = set()
if "seating_direction" not in st.session_state:
    st.session_state["seating_direction"] = "Up"
if "seating_rotation" not in st.session_state:
    st.session_state["seating_rotation"] = []
if "last_sat_server" not in st.session_state:
    st.session_state["last_sat_server"] = None
if "server_scores" not in st.session_state or not isinstance(st.session_state["server_scores"], dict):
    st.session_state["server_scores"] = {}
# track last table clicked for the seat-from-waitlist panel
if "last_clicked_table" not in st.session_state:
    st.session_state["last_clicked_table"] = None

# --- Table Plan Definitions ---
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
            tables.append({"table": tnum, "section": section_idx + 1, "status": "Available", "server": None, "party": None})
    return tables


# Ensure tables exist
if "tables" not in st.session_state:
    num_sections = min(max(len(st.session_state["servers"]), 1), 9)
    st.session_state["tables"] = initialize_tables(num_sections)


st.title("Host Coordinating")
tab1, tab2, tab3 = st.tabs(["Waitlist", "Servers & Sections", "Seating Chart"])


# --- Waitlist Tab ---
with tab1:
    st.header("Waitlist")
    with st.form("Add to Waitlist"):
        name = st.text_input("Guest Name")
        party_size = st.number_input("Party Size", min_value=1, max_value=20, value=2)
        phone = st.text_input("Phone (optional) — digits only, include country code if needed")
        notes = st.text_input("Notes (optional)")
        min_wait = st.number_input("Minimum Wait (minutes)", min_value=0, max_value=180, value=0)
        max_wait = st.number_input("Maximum Wait (minutes)", min_value=0, max_value=180, value=30)
        submitted = st.form_submit_button("Add to Waitlist")
        if submitted and name:
            st.session_state["waitlist"].append(
                {
                    "name": name,
                    "party_size": party_size,
                    "phone": phone,
                    "notes": notes,
                    "added_time": time.time(),
                    "min_wait": min_wait,
                    "max_wait": max_wait,
                }
            )
            save_persistent_state()
            st.success(f"Added {name} (Party of {party_size}) to waitlist.")

    st_autorefresh(interval=30 * 1000, key="waitlist_autorefresh")

    if st.session_state["waitlist"]:
        st.write("### Current Waitlist:")
        now = time.time()
        for i, guest in enumerate(st.session_state["waitlist"]):
            wait_mins = int((now - guest.get("added_time", now)) // 60)
            min_wait = guest.get("min_wait", 0)
            max_wait = guest.get("max_wait", 0)
            phone_display = guest.get("phone") or "No phone"
            if wait_mins < min_wait:
                indicator = f"🟢 Can wait longer ({min_wait - wait_mins} min left)"
            elif wait_mins >= max_wait:
                indicator = f"🔴 Must be seated now! ({wait_mins} min)"
            else:
                indicator = f"🟡 Should be seated soon ({max_wait - wait_mins} min left)"
            st.write(
                f"{i+1}. {guest['name']} (Party of {guest['party_size']}) - {guest['notes']} | Phone: {phone_display} | Wait: {wait_mins} min | Min: {min_wait} | Max: {max_wait} | {indicator}"
            )

        remove_idx = st.number_input(
            "Remove guest # (optional)",
            min_value=1,
            max_value=len(st.session_state["waitlist"]),
            step=1,
            value=1,
            key="remove_waitlist_idx",
        )
        st.button("Remove from Waitlist", on_click=remove_waitlist_callback, key="remove_from_waitlist_btn")
        remove_msg = st.session_state.pop("remove_waitlist_msg", None)
        if remove_msg:
            st.success(remove_msg)
    else:
        st.info("Waitlist is empty.")


# --- Servers & Sections Tab ---
with tab2:
    st.header("Servers & Sections")
    with st.form("Add Server"):
        server_name = st.text_input("Server Name")
        current_sections = [s["section"] for s in st.session_state["servers"]]
        next_section = max(current_sections, default=0) + 1 if len(current_sections) < 9 else None
        add_server = st.form_submit_button("Add Server")
        if add_server and server_name:
            if next_section is not None:
                st.session_state["servers"].append({"name": server_name, "section": next_section})
                st.session_state["server_scores"].setdefault(server_name, 0)
                num_sections = min(max(len(st.session_state["servers"]), 1), 9)
                st.session_state["tables"] = initialize_tables(num_sections)
                save_persistent_state()
                st.success(f"Added server {server_name} to section {next_section}.")
            else:
                st.error("Maximum number of servers (9) reached.")

    st.write("### Seating Chart Direction:")
    direction = st.radio(
        "Choose seating chart direction:",
        options=["Up", "Down"],
        index=0 if st.session_state.get("seating_direction", "Up") == "Up" else 1,
        key="seating_direction_radio",
    )
    if st.session_state.get("seating_direction") != direction:
        st.session_state["seating_direction"] = direction
        save_persistent_state()

    if st.session_state["servers"]:
        st.write("### Mark Present Servers:")
        all_server_names = [s["name"] for s in st.session_state["servers"]]
        present = st.multiselect(
            "Select servers who are present:",
            options=all_server_names,
            default=list(st.session_state["present_servers"]),
            key="present_servers_select",
        )
        new_present_set = set(present)
        if st.session_state.get("present_servers") != new_present_set:
            st.session_state["present_servers"] = new_present_set
            for name in new_present_set:
                st.session_state["server_scores"].setdefault(name, 0)
            save_persistent_state()

    if st.session_state["servers"]:
        st.write("### Current Servers:")
        for idx, s in enumerate(st.session_state["servers"]):
            st.write(f"{idx+1}. {s['name']} (Section {s['section']})")

        remove_idx = st.number_input(
            "Remove server # (optional)",
            min_value=1,
            max_value=len(st.session_state["servers"]),
            step=1,
            value=1,
            key="remove_server_idx",
        )
        st.button("Remove Server", on_click=remove_server_callback, key="remove_server_btn")
        server_msg = st.session_state.pop("remove_server_msg", None)
        if server_msg:
            st.success(server_msg)
    else:
        st.info("No servers added yet.")


# --- Seating Chart Tab ---
with tab3:
    st.header("Seating Chart")
    st.write("#### Table Status:")

    num_sections = min(max(len(st.session_state["servers"]), 1), 9)
    present_server_names = st.session_state.get("present_servers", set())
    present_servers = [s for s in st.session_state["servers"] if s["name"] in present_server_names]
    present_servers_sorted = sorted(present_servers, key=lambda s: s["section"])
    direction = st.session_state.get("seating_direction", "Up")
    if direction == "Down":
        present_servers_sorted = list(reversed(present_servers_sorted))

    current_rotation = [s["name"] for s in present_servers_sorted]
    if st.session_state.get("seating_rotation") != current_rotation:
        st.session_state["seating_rotation"] = current_rotation
        st.session_state["last_sat_server"] = None
        save_persistent_state()

    for k in list(st.session_state["server_scores"].keys()):
        if k not in current_rotation:
            del st.session_state["server_scores"][k]
    for k in current_rotation:
        st.session_state["server_scores"].setdefault(k, 0)

    debug_data: List[Dict] = []
    for s in present_servers_sorted:
        debug_data.append(
            {"Server": s["name"], "Section": s["section"], "Amount of Tables": st.session_state["server_scores"].get(s["name"], 0)}
        )
    if debug_data:
        st.markdown("#### Server Rotation & Scores")
        st.table(pd.DataFrame(debug_data))

    waitlist = st.session_state["waitlist"]
    suggestion = None
    rotation = st.session_state.get("seating_rotation", [])
    rotation = [s for s in rotation if s in present_server_names]
    if rotation:
        for s in rotation:
            st.session_state["server_scores"].setdefault(s, 0)
        min_score = min(st.session_state["server_scores"][s] for s in rotation)
        suggestion_candidates = [s for s in rotation if st.session_state["server_scores"][s] == min_score]
        if suggestion_candidates:
            suggestion = suggestion_candidates[0]

    st.markdown("### Seating Suggestion")
    if suggestion:
        if waitlist:
            st.info(f"Seat next party ({waitlist[0]['name']}) with server: {suggestion}")
        else:
            st.info(f"Next server to be sat: {suggestion}")
    else:
        st.info("No suggestion available.")

    # ----------------------------
    # VISUAL LAYOUT (NO IMAGE) — normalized positions
    # ----------------------------

    # Default table positions (normalized percentages). These match your photo layout conceptually.
    # Edit the percentages to fine-tune positions; values are 0.0..1.0 (left/top).
    TABLE_POSITIONS = {
        31: {"x_pct": 0.08, "y_pct": 0.08},
        32: {"x_pct": 0.16, "y_pct": 0.08},
        33: {"x_pct": 0.24, "y_pct": 0.08},
        34: {"x_pct": 0.32, "y_pct": 0.08},
        35: {"x_pct": 0.40, "y_pct": 0.08},
        36: {"x_pct": 0.48, "y_pct": 0.08},
        37: {"x_pct": 0.56, "y_pct": 0.08},
        41: {"x_pct": 0.64, "y_pct": 0.08},
        42: {"x_pct": 0.72, "y_pct": 0.08},
        43: {"x_pct": 0.80, "y_pct": 0.08},

        1: {"x_pct": 0.08, "y_pct": 0.28},
        2: {"x_pct": 0.18, "y_pct": 0.28},
        3: {"x_pct": 0.28, "y_pct": 0.28},
        4: {"x_pct": 0.38, "y_pct": 0.28},
        5: {"x_pct": 0.48, "y_pct": 0.28},
        6: {"x_pct": 0.58, "y_pct": 0.28},
        7: {"x_pct": 0.68, "y_pct": 0.28},
        8: {"x_pct": 0.78, "y_pct": 0.28},
        9: {"x_pct": 0.88, "y_pct": 0.28},
        10: {"x_pct": 0.96, "y_pct": 0.28},
        11: {"x_pct": 0.92, "y_pct": 0.36},

        21: {"x_pct": 0.08, "y_pct": 0.36},
        22: {"x_pct": 0.18, "y_pct": 0.36},
        23: {"x_pct": 0.28, "y_pct": 0.36},
        24: {"x_pct": 0.38, "y_pct": 0.36},
        25: {"x_pct": 0.48, "y_pct": 0.36},
        26: {"x_pct": 0.58, "y_pct": 0.36},
        27: {"x_pct": 0.68, "y_pct": 0.36},
        28: {"x_pct": 0.78, "y_pct": 0.36},
        29: {"x_pct": 0.88, "y_pct": 0.36},
        30: {"x_pct": 0.96, "y_pct": 0.36},

        51: {"x_pct": 0.14, "y_pct": 0.60},
        52: {"x_pct": 0.24, "y_pct": 0.60},
        53: {"x_pct": 0.34, "y_pct": 0.60},
        54: {"x_pct": 0.44, "y_pct": 0.60},
        55: {"x_pct": 0.54, "y_pct": 0.60},

        61: {"x_pct": 0.64, "y_pct": 0.60},
        62: {"x_pct": 0.74, "y_pct": 0.60},
        63: {"x_pct": 0.84, "y_pct": 0.60},
        64: {"x_pct": 0.92, "y_pct": 0.60},
        65: {"x_pct": 0.98, "y_pct": 0.60},
    }

    # ensure all tables have a position; fallback to center
    for t in st.session_state["tables"]:
        tnum = t["table"]
        if tnum not in TABLE_POSITIONS:
            TABLE_POSITIONS[tnum] = {"x_pct": 0.5, "y_pct": 0.5}

    # CSS for the full-width visual layout
    st.markdown(
        """
        <style>
        .floorplan-container {
            position: relative;
            width: 100%;
            height: 70vh; /* fills viewport height - adjust if you want taller/shorter */
            border: 1px solid rgba(0,0,0,0.08);
            background: linear-gradient(180deg, #ffffff, #fafafa);
            margin-bottom: 12px;
            overflow: visible;
        }
        .table-btn {
            position: absolute;
            width: 56px;
            height: 56px;
            line-height: 56px;
            border-radius: 28px;
            text-align: center;
            font-weight: 700;
            color: white;
            border: 2px solid rgba(0,0,0,0.08);
            box-shadow: 0 2px 6px rgba(0,0,0,0.12);
            transform: translate(-50%, -50%);
            cursor: pointer;
            display: inline-block;
            text-decoration: none;
        }
        .available { background: #2ecc71; }   /* green */
        .taken { background: #e74c3c; }       /* red */
        .bussing { background: #f1c40f; color: black; } /* yellow */
        .table-label {
            position: absolute;
            transform: translate(-50%, -50%);
            font-size: 11px;
            padding: 4px 6px;
            border-radius: 6px;
            color: #222;
            background: rgba(255,255,255,0.9);
            border: 1px solid rgba(0,0,0,0.06);
        }
        .section-name {
            position: absolute;
            transform: translate(-50%, -50%);
            padding: 6px 8px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            color: #111;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }
        .legend {
            display:flex;
            gap:12px;
            align-items:center;
            margin-bottom:6px;
        }
        .legend .item { display:flex; gap:6px; align-items:center; }
        .legend .dot { width:16px; height:16px; border-radius:8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Show legend and instructions
    st.markdown(
        """
        <div class="legend">
            <div class="item"><div class="dot" style="background:#2ecc71"></div>Available</div>
            <div class="item"><div class="dot" style="background:#e74c3c"></div>Taken (clicking Available→Taken increments server score)</div>
            <div class="item"><div class="dot" style="background:#f1c40f"></div>Bussing</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Compute per-plan section assignment and section label positions (average table positions)
    plan = get_plan_tables(num_sections)
    # plan is list of sections; compute center for each section
    section_centers = {}
    for idx, table_nums in enumerate(plan):
        sec = idx + 1
        xs = []
        ys = []
        for tnum in table_nums:
            pos = TABLE_POSITIONS.get(tnum, {"x_pct": 0.5, "y_pct": 0.5})
            xs.append(pos["x_pct"])
            ys.append(pos["y_pct"])
        if xs and ys:
            section_centers[sec] = {"x_pct": sum(xs) / len(xs), "y_pct": max(0.02, sum(ys) / len(ys) - 0.08)}
        else:
            section_centers[sec] = {"x_pct": 0.5, "y_pct": 0.05}

    # Section colors palette
    SECTION_COLORS = ["#a8d0e6", "#f7d794", "#f6b93b", "#f8a5c2", "#c7ecee", "#d6a2e8", "#b8e994", "#f6e58d", "#badc58"]

    # Create container and render layout (use HTML anchors for clicks with query param to detect)
    st.markdown('<div class="floorplan-container" id="floorplan">', unsafe_allow_html=True)

    # Render section labels (server names)
    for sec in range(1, num_sections + 1):
        center = section_centers.get(sec, {"x_pct": 0.5, "y_pct": 0.05})
        left_pct = int(center["x_pct"] * 100)
        top_pct = int(center["y_pct"] * 100)
        # find server assigned to this section (if any)
        server_for_section = next((s["name"] for s in st.session_state["servers"] if s["section"] == sec), None)
        server_display = server_for_section or "No server"
        color = SECTION_COLORS[(sec - 1) % len(SECTION_COLORS)]
        st.markdown(
            f'<div class="section-name" style="left:{left_pct}%; top:{top_pct}%; background:{color}">Section {sec}<br/>{server_display}</div>',
            unsafe_allow_html=True,
        )

    # Render table buttons
    for t in st.session_state["tables"]:
        tnum = t["table"]
        pos = TABLE_POSITIONS.get(tnum, {"x_pct": 0.5, "y_pct": 0.5})
        left_pct = pos["x_pct"] * 100
        top_pct = pos["y_pct"] * 100
        status = t.get("status", "Available")
        section = t.get("section") or "-"
        server_for_section = next((s["name"] for s in st.session_state["servers"] if s["section"] == section), None)
        server_display = server_for_section or "No server"

        if status == "Available":
            cls = "available"
            emoji = "🟢"
        elif status == "Taken":
            cls = "taken"
            emoji = "🔴"
        elif status == "Bussing":
            cls = "bussing"
            emoji = "🟡"
        else:
            cls = "available"
            emoji = "⚪️"

        title = f"Table {tnum} | Section {section} | Server: {server_display} | Status: {status}"
        href = f"?table_click={tnum}"

        st.markdown(
            f'''
            <a class="table-btn {cls}" href="{href}" title="{title}" style="left:{left_pct}%; top:{top_pct}%">
                <div style="font-size:18px;">{tnum}</div>
            </a>
            ''',
            unsafe_allow_html=True,
        )

    st.markdown('</div>', unsafe_allow_html=True)

    # ----------------------------
    # handle clicks (query param)
    # ----------------------------
    params = st.experimental_get_query_params()
    if "table_click" in params:
        try:
            clicked_table = int(params["table_click"][0])
            # cycle status for clicked table immediately (user requested click cycles)
            tbl_obj = next((x for x in st.session_state["tables"] if x["table"] == clicked_table), None)
            if tbl_obj:
                old = tbl_obj.get("status", "Available")
                if old == "Available":
                    tbl_obj["status"] = "Taken"
                    # increment server score for that section's server
                    sec = tbl_obj.get("section")
                    server_for_section = next((s["name"] for s in st.session_state["servers"] if s["section"] == sec), None)
                    if server_for_section:
                        st.session_state["server_scores"].setdefault(server_for_section, 0)
                        st.session_state["server_scores"][server_for_section] += 1
                        st.session_state["last_sat_server"] = server_for_section
                elif old == "Taken":
                    tbl_obj["status"] = "Bussing"
                else:
                    tbl_obj["status"] = "Available"
                    tbl_obj["party"] = None
                    tbl_obj["server"] = None
                # set last_clicked_table for optional manual seating UI
                st.session_state["last_clicked_table"] = clicked_table
                save_persistent_state()
        except Exception as e:
            print("Error processing table_click param:", e)
        # clear param so click isn't processed repeatedly
        st.experimental_set_query_params()

    # ----------------------------
    # Right-side control panel: seat selected table from waitlist (optional)
    # ----------------------------
    st.markdown("---")
    st.subheader("Table Controls / Seat from Waitlist (optional)")

    col_a, col_b = st.columns([2, 1])
    with col_a:
        if st.session_state["last_clicked_table"]:
            tnum = st.session_state["last_clicked_table"]
            st.write(f"Selected Table: **{tnum}**")
            tbl_obj = next((x for x in st.session_state["tables"] if x["table"] == tnum), None)
            if tbl_obj:
                st.write(f"Current status: **{tbl_obj.get('status', 'Available')}**")
                st.write(f"Section: **{tbl_obj.get('section')}**")
                server_for_section = next((s["name"] for s in st.session_state["servers"] if s["section"] == tbl_obj.get("section")), None)
                st.write(f"Server: **{server_for_section or 'No server'}**")

                # Choose waitlist person to seat
                waitlist_names = [f"{idx+1}. {g['name']} (Party {g['party_size']})" for idx, g in enumerate(st.session_state["waitlist"])]
                selected_idx = None
                if waitlist_names:
                    sel = st.selectbox("Choose a guest from the waitlist to seat (optional)", options=["-- None --"] + waitlist_names, key=f"seat_select_{tnum}")
                    if sel and sel != "-- None --":
                        try:
                            selected_idx = waitlist_names.index(sel)
                        except ValueError:
                            selected_idx = None

                manual_party = st.text_input("Or enter manual party name (optional)", key=f"manual_seat_{tnum}")
                seat_btn = st.button("Seat Selected / Manual", key=f"seat_now_{tnum}")
                if seat_btn:
                    server_name = server_for_section or None
                    if selected_idx is not None:
                        seat_table_callback(tnum, server_name, selected_waitlist_idx=selected_idx, manual_name=None)
                    else:
                        seat_table_callback(tnum, server_name, selected_waitlist_idx=None, manual_name=manual_party if manual_party else None)
                    st.experimental_rerun()
            else:
                st.info("Selected table not found in state.")
        else:
            st.info("Click a table in the visual layout to select it for manual seating or inspection.")

    with col_b:
        st.write("Quick actions:")
        if st.button("Clear selected table"):
            if st.session_state["last_clicked_table"]:
                clear_table_callback(st.session_state["last_clicked_table"])
                st.session_state["last_clicked_table"] = None
                st.experimental_rerun()
        if st.button("Mark selected table Bussing"):
            if st.session_state["last_clicked_table"]:
                bus_table_callback(st.session_state["last_clicked_table"])
                st.experimental_rerun()
