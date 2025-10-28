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

# Get or create sheet
try:
    sh = gc.open(SHEET_NAME)
except gspread.SpreadsheetNotFound:
    sh = gc.create(SHEET_NAME)
    sh.share(st.secrets["gcp_service_account"]["client_email"], perm_type="user", role="writer")

ws = sh.sheet1

# --- Persistence config (Google Sheets) ---
def load_persistent_state():
    try:
        data = ws.get_all_values()
        if data and data[0] and data[0][0]:
            raw = data[0][0]
            json_data = json.loads(raw)
            for k, v in json_data.items():
                if k == "present_servers" and isinstance(v, list):
                    st.session_state[k] = set(v)
                else:
                    st.session_state[k] = v
    except Exception as e:
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
                if isinstance(v, set):
                    v = list(v)
                data[k] = v
        json_str = json.dumps(data, ensure_ascii=False)
        ws.update("A1", [[json_str]])
    except Exception as e:
        print("Failed to save persistent state:", e)

# --- Callbacks ---
def _remove_mark_callback(server_name: str, section_idx: int):
    cur = st.session_state["server_scores"].get(server_name, 0)
    if cur > 0:
        st.session_state["server_scores"][server_name] = cur - 1
    st.session_state[f"remove_mark_msg_{section_idx}"] = server_name
    save_persistent_state()

def _skip_server_callback(server_name: str, section_idx: int):
    st.session_state["server_scores"].setdefault(server_name, 0)
    st.session_state["server_scores"][server_name] += 1
    st.session_state[f"skip_msg_{section_idx}"] = server_name
    save_persistent_state()

def seat_table_callback(table_num: int, server_name: str):
    select_key = f"waitlist_select_{table_num}"
    manual_key = f"manual_party_{table_num}"
    selected = st.session_state.get(select_key, "-- None --")
    selected_idx = None
    if isinstance(selected, str) and selected != "-- None --":
        waitlist_names = [
            f"{idx+1}. {g['name']} (Party of {g['party_size']})"
            for idx, g in enumerate(st.session_state["waitlist"])
        ]
        try:
            selected_idx = waitlist_names.index(selected)
        except ValueError:
            selected_idx = None
    guest_name = st.session_state.get(manual_key, "").strip()

    this_table = None
    for table in st.session_state["tables"]:
        if table["table"] == table_num:
            this_table = table
            break
    if this_table is None:
        st.session_state[f"seat_msg_{table_num}"] = "Table not found"
        return

    if server_name:
        st.session_state["server_scores"].setdefault(server_name, 0)
        st.session_state["server_scores"][server_name] += 1
        st.session_state["last_sat_server"] = server_name

    if selected_idx is not None and 0 <= selected_idx < len(st.session_state["waitlist"]):
        guest = st.session_state["waitlist"].pop(selected_idx)
        this_table["status"] = "Taken"
        this_table["party"] = guest["name"]
        this_table["server"] = server_name
        st.session_state[f"seat_msg_{table_num}"] = f"Seated {guest['name']} at Table {table_num}."
    else:
        this_table["status"] = "Taken"
        this_table["party"] = guest_name if guest_name else "Unknown Party"
        this_table["server"] = server_name
        st.session_state[f"seat_msg_{table_num}"] = f"Seated {this_table['party']} at Table {table_num}."

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

if "tables" not in st.session_state:
    num_sections = min(max(len(st.session_state["servers"]), 1), 9)
    st.session_state["tables"] = initialize_tables(num_sections)


# --- PAGE SETUP ---
st.title("Host Coordinating")
tab1, tab2, tab3 = st.tabs(["Waitlist", "Servers & Sections", "Seating Chart"])


# --- Waitlist Tab ---
with tab1:
    st.header("Waitlist")
    with st.form("Add to Waitlist"):
        name = st.text_input("Guest Name")
        party_size = st.number_input("Party Size", min_value=1, max_value=20, value=2)
        notes = st.text_input("Notes (optional)")
        min_wait = st.number_input("Minimum Wait (minutes)", min_value=0, max_value=180, value=0)
        max_wait = st.number_input("Maximum Wait (minutes)", min_value=0, max_value=180, value=30)
        submitted = st.form_submit_button("Add to Waitlist")
        if submitted and name:
            st.session_state["waitlist"].append(
                {
                    "name": name,
                    "party_size": party_size,
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
            if wait_mins < min_wait:
                indicator = f"🟢 Can wait longer ({min_wait - wait_mins} min left)"
            elif wait_mins >= max_wait:
                indicator = f"🔴 Must be seated now! ({wait_mins} min)"
            else:
                indicator = f"🟡 Should be seated soon ({max_wait - wait_mins} min left)"
            st.write(
                f"{i+1}. {guest['name']} (Party of {guest['party_size']}) - {guest['notes']} | Wait: {wait_mins} min | Min: {min_wait} | Max: {max_wait} | {indicator}"
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
    # (Keep all your current seating rotation, suggestions, and section expanders)

    # --- ADD VISUAL LAYOUT HERE ---
    st.subheader("Visual Table Layout")

    tables = st.session_state["tables"]
    table_map = {t["table"]: t for t in tables}
    sorted_tables = sorted(table_map.keys())

    cols_per_row = 8
    rows = [sorted_tables[i:i + cols_per_row] for i in range(0, len(sorted_tables), cols_per_row)]

    for row in rows:
        cols = st.columns(len(row))
        for i, table_num in enumerate(row):
            table = table_map[table_num]
            status = table["status"]
            color = "green"
            label = f"Table {table_num}"
            if status == "Taken":
                color = "red"
                label = f"🧍 {table['party']}"
            elif status == "Bussing":
                color = "orange"
                label = f"🧹 Table {table_num}"

            with cols[i]:
                if st.button(label, key=f"visual_table_{table_num}"):
                    st.session_state["selected_table"] = table_num

    # --- Details Panel ---
    if "selected_table" in st.session_state:
        selected_num = st.session_state["selected_table"]
        selected_table = table_map[selected_num]
        st.markdown(f"### Table {selected_num} Details")

        status = selected_table["status"]
        st.write(f"**Status:** {status}")
        st.write(f"**Section:** {selected_table['section']}")
        st.write(f"**Server:** {selected_table.get('server', 'N/A')}")
        st.write(f"**Party:** {selected_table.get('party', 'N/A')}")

        if status == "Available":
            st.text_input("Party Name", key=f"visual_manual_party_{selected_num}")
            waitlist_names = [f"{i+1}. {g['name']} (Party of {g['party_size']})" for i, g in enumerate(st.session_state["waitlist"])]
            if waitlist_names:
                st.selectbox("From Waitlist", ["-- None --"] + waitlist_names, key=f"visual_waitlist_select_{selected_num}")
            section_server = next((s["name"] for s in st.session_state["servers"] if s["section"] == selected_table["section"]), None)
            st.button("Seat", on_click=seat_table_callback, args=(selected_num, section_server))

        elif status == "Taken":
            st.button("Bus", on_click=bus_table_callback, args=(selected_num,))
        elif status == "Bussing":
            st.button("Clear", on_click=clear_table_callback, args=(selected_num,))
