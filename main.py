
import streamlit as st
from typing import List, Dict

st.set_page_config(page_title="Coordinating", layout="wide")

# --- Session State Initialization ---
import time
if 'waitlist' not in st.session_state:
	st.session_state['waitlist'] = []  # List of dicts: {name, party_size, notes, added_time, min_wait, max_wait}
if 'servers' not in st.session_state:
	st.session_state['servers'] = []  # List of dicts: {name, section}
if 'present_servers' not in st.session_state:
	st.session_state['present_servers'] = set()

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

def get_plan_tables(num_sections):
	plan = TABLE_PLANS.get(num_sections)
	if not plan:
		# fallback: all tables in one section
		all_tables = sum(TABLE_PLANS[3], [])
		return [[t for t in all_tables]]
	return plan

def initialize_tables(num_sections):
	plan = get_plan_tables(num_sections)
	tables = []
	for section_idx, table_nums in enumerate(plan):
		for tnum in table_nums:
			tables.append({'table': tnum, 'section': section_idx+1, 'status': 'Available', 'server': None, 'party': None})
	return tables

if 'tables' not in st.session_state:
	num_sections = min(max(len(st.session_state['servers']), 1), 9)
	st.session_state['tables'] = initialize_tables(num_sections)

st.title("Restaurant Host Management")

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
			st.session_state['waitlist'].append({
				'name': name,
				'party_size': party_size,
				'notes': notes,
				'added_time': time.time(),
				'min_wait': min_wait,
				'max_wait': max_wait
			})
			st.success(f"Added {name} (Party of {party_size}) to waitlist.")
	# Auto-refresh every 30 seconds to update timers, even if switching tabs
	streamlit_autorefresh(interval=30 * 1000, key="waitlistreamlit_autorefresh")
	if st.session_state['waitlist']:
		st.write("### Current Waitlist:")
		now = time.time()
		for i, guest in enumerate(st.session_state['waitlist']):
			wait_mins = int((now - guest.get('added_time', now)) // 60)
			min_wait = guest.get('min_wait', 0)
			max_wait = guest.get('max_wait', 0)
			# Indicator logic
			if wait_mins < min_wait:
				indicator = f"🟢 Can wait longer ({min_wait - wait_mins} min left)"
			elif wait_mins >= max_wait:
				indicator = f"🔴 Must be seated now! ({wait_mins} min)"
			else:
				indicator = f"🟡 Should be seated soon ({max_wait - wait_mins} min left)"
			st.write(f"{i+1}. {guest['name']} (Party of {guest['party_size']}) - {guest['notes']} | Wait: {wait_mins} min | Min: {min_wait} | Max: {max_wait} | {indicator}")
		remove_idx = st.number_input("Remove guest # (optional)", min_value=1, max_value=len(st.session_state['waitlist']), step=1, value=1)
		if st.button("Remove from Waitlist"):
			removed = st.session_state['waitlist'].pop(remove_idx-1)
			st.success(f"Removed {removed['name']} from waitlist.")
	else:
		st.info("Waitlist is empty.")

# --- Servers & Sections Tab ---
with tab2:
	st.header("Servers & Sections")
	with st.form("Add Server"):
		server_name = st.text_input("Server Name")
		# Section is auto-assigned as next available (max 9)
		current_sections = [s['section'] for s in st.session_state['servers']]
		next_section = max(current_sections, default=0) + 1 if len(current_sections) < 9 else None
		add_server = st.form_submit_button("Add Server")
		if add_server and server_name:
			if next_section is not None:
				st.session_state['servers'].append({'name': server_name, 'section': next_section})
				st.success(f"Added server {server_name} to section {next_section}.")
				# Re-initialize tables for new plan
				num_sections = min(max(len(st.session_state['servers']), 1), 9)
				st.session_state['tables'] = initialize_tables(num_sections)
			else:
				st.error("Maximum number of servers (9) reached.")

	# Seating chart direction option
	st.write("### Seating Chart Direction:")
	if 'seating_direction' not in st.session_state:
		st.session_state['seating_direction'] = 'Up'
	direction = st.radio(
		"Choose seating chart direction:",
		options=["Up", "Down"],
		index=0 if st.session_state['seating_direction'] == 'Up' else 1,
		key="seating_direction_radio"
	)
	st.session_state['seating_direction'] = direction

	# Mark present servers
	if st.session_state['servers']:
		st.write("### Mark Present Servers:")
		all_server_names = [s['name'] for s in st.session_state['servers']]
		present = st.multiselect(
			"Select servers who are present:",
			options=all_server_names,
			default=list(st.session_state['present_servers']),
			key="present_servers_select"
		)
		st.session_state['present_servers'] = set(present)
	if st.session_state['servers']:
		st.write("### Current Servers:")
		for idx, s in enumerate(st.session_state['servers']):
			st.write(f"{idx+1}. {s['name']} (Section {s['section']})")
		remove_idx = st.number_input("Remove server # (optional)", min_value=1, max_value=len(st.session_state['servers']), step=1, value=1, key="remove_server_idx")
		if st.button("Remove Server"):
			removed = st.session_state['servers'].pop(remove_idx-1)
			st.success(f"Removed server {removed['name']} from section {removed['section']}.")
			# Re-initialize tables for new plan
			num_sections = min(max(len(st.session_state['servers']), 1), 9)
			st.session_state['tables'] = initialize_tables(num_sections)
	else:
		st.info("No servers added yet.")

with tab3:
	# --- Seating Chart Tab ---
	# All variables must be defined before debug output
	st.header("Seating Chart")
	st.write("#### Table Status:")
	# Number of sections = number of servers (max 9, min 1)
	num_sections = min(max(len(st.session_state['servers']), 1), 9)
	# Only show present servers in seating chart
	present_server_names = st.session_state.get('present_servers', set())
	present_servers = [s for s in st.session_state['servers'] if s['name'] in present_server_names]
	# Sort servers by section number
	present_servers_sorted = sorted(present_servers, key=lambda s: s['section'])
	# Seating direction
	direction = st.session_state.get('seating_direction', 'Up')
	if direction == 'Down':
		present_servers_sorted = list(reversed(present_servers_sorted))

	# --- Seating Rotation State ---
	if 'seating_rotation' not in st.session_state:
		st.session_state['seating_rotation'] = []  # list of server names in rotation order
	if 'last_sat_server' not in st.session_state:
		st.session_state['last_sat_server'] = None
	# Score system: server_name -> score (number of times sat)
	if 'server_scores' not in st.session_state or not isinstance(st.session_state['server_scores'], dict):
		st.session_state['server_scores'] = {}

	# Update rotation if present servers or direction changes
	current_rotation = [s['name'] for s in present_servers_sorted]
	if st.session_state['seating_rotation'] != current_rotation:
		st.session_state['seating_rotation'] = current_rotation
		st.session_state['last_sat_server'] = None
	# Remove scores for servers no longer present
	for k in list(st.session_state['server_scores'].keys()):
		if k not in current_rotation:
			del st.session_state['server_scores'][k]
	# Ensure all present servers have a score
	for k in current_rotation:
		if k not in st.session_state['server_scores']:
			st.session_state['server_scores'][k] = 0

	# Debug: Show present servers, sections, and scores
	import pandas as pd
	debug_data = []
	for s in present_servers_sorted:
		debug_data.append({
			'Server': s['name'],
			'Section': s['section'],
			'Amount of Tables': st.session_state['server_scores'].get(s['name'], 0)
		})
	if debug_data:
		st.markdown("#### Server Rotation & Scores")
		st.table(pd.DataFrame(debug_data))

	# Suggestion logic (score-based)
	waitlist = st.session_state['waitlist']
	suggestion = None
	rotation = st.session_state['seating_rotation']
	scores = st.session_state['server_scores']
	# Only use present servers in rotation
	rotation = [s for s in rotation if s in present_server_names]

	# Suggestion logic (score-based)
	if rotation:
		# Defensive: ensure all servers in rotation have a score
		for s in rotation:
			if s not in scores:
				scores[s] = 0
		min_score = min(scores[s] for s in rotation)
		suggestion_candidates = [s for s in rotation if scores[s] == min_score]
		if suggestion_candidates:
			suggestion = suggestion_candidates[0]

	st.markdown("### Seating Suggestion")
	if suggestion:
		if waitlist:
			st.info(f"Seat next party ({waitlist[0]['name']}) with server: {suggestion}")
		else:
			st.info(f"Next server to be sat: {suggestion}")
	else:
		st.info("No suggestion available. All present servers may be skipped.")
	# Compact grid: show all present sections as expandable, with tables in a grid
	for section in range(1, num_sections+1):
		section_server = next((s['name'] for s in st.session_state['servers'] if s['section'] == section), None)
		if section_server not in present_server_names:
			continue
		with st.expander(f"Section {section} ({section_server})", expanded=False):
			section_tables = [t for t in st.session_state['tables'] if t['section'] == section]
			# Show tables in a grid, 3 per row for mobile/tablet friendliness
			grid_cols = 3
			rows = [section_tables[i:i+grid_cols] for i in range(0, len(section_tables), grid_cols)]
			for row in rows:
				cols = st.columns(len(row))
				for i, table in enumerate(row):
					with cols[i]:
						st.markdown(f"**Table {table['table']}**")
						if table['status'] == 'Available':
							st.success("Available", icon="✅")
						else:
							st.error(f"Taken: {table['party']}", icon="❌")
						# Seating controls
						if table['status'] == 'Available':
							waitlist_names = [f"{idx+1}. {g['name']} (Party of {g['party_size']})" for idx, g in enumerate(st.session_state['waitlist'])]
							selected_idx = None
							selected = None
							if waitlist_names:
								selected = st.selectbox(
									"Waitlist (optional)",
									options=["-- None --"] + waitlist_names,
									key=f"waitlist_select_{table['table']}"
								)
								if selected != "-- None --":
									selected_idx = waitlist_names.index(selected)
							guest_name = st.text_input("Party name (optional)", key=f"manual_party_{table['table']}")
							seat_btn = st.button("Seat", key=f"seat_{table['table']}")
							if seat_btn:
								# Score-based: increment this server's score
								rotation = st.session_state.get('seating_rotation', [])
								scores = st.session_state.get('server_scores', {})
								present_server_names = st.session_state.get('present_servers', set())
								rotation = [s for s in rotation if s in present_server_names]
								this_server = section_server
								if this_server in scores:
									st.session_state['server_scores'][this_server] += 1
								st.session_state['last_sat_server'] = this_server
								if selected_idx is not None:
									guest = st.session_state['waitlist'].pop(selected_idx)
									table['status'] = 'Taken'
									table['party'] = guest['name']
									table['server'] = section_server
									st.success(f"Seated {guest['name']} at Table {table['table']}.")
								else:
									table['status'] = 'Taken'
									table['party'] = guest_name if guest_name else 'Unknown Party'
									table['server'] = section_server
									st.success(f"Seated {table['party']} at Table {table['table']}.")
						else:
							st.caption(f"Party: {table['party']}")
							st.caption(f"Server: {table['server']}")
							# Remove seating mark button
							if table['server']:
								remove_mark_btn = st.button("Remove seating mark", key=f"remove_mark_{table['table']}")
								if remove_mark_btn:
									scores = st.session_state.get('server_scores', {})
									if table['server'] in scores and scores[table['server']] > 0:
										st.session_state['server_scores'][table['server']] -= 1
										st.success(f"Removed a seating mark from {table['server']}.")
							clear_btn = st.button("Clear", key=f"clear_{table['table']}")
							if clear_btn:
								table['status'] = 'Available'
								table['party'] = None
								table['server'] = None
