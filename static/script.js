const waitlistEl = document.getElementById("waitlist");
const waitForm = document.getElementById("waitForm");
const serverSelect = document.getElementById("serverSelect");
const layout = document.getElementById("layout");
const tableDetails = document.getElementById("tableDetails");
const serverLoadsEl = document.getElementById("serverLoads");
const serverSuggestion = document.getElementById("serverSuggestion");
const rotationSelect = document.getElementById("rotation");
const suggestBtn = document.getElementById("suggestBtn");
const refreshBtn = document.getElementById("refreshBtn");

let state = null;
let selectedTable = null;

async function fetchState(){
  const r = await axios.get("/api/state");
  state = r.data;
  renderWaitlist();
  renderServers();
  renderTables();
  updateServerSuggestion();
}

function formatDuration(iso){ 
  if(!iso) return "";
  const then = new Date(iso);
  const now = new Date();
  const diff = Math.floor((now - then)/1000);
  const m = Math.floor(diff/60);
  const s = diff%60;
  return `${m}m ${s}s`;
}

function renderWaitlist(){
  waitlistEl.innerHTML = "";
  serverSelect.innerHTML = '<option value="">Assign server (optional)</option>';
  (state.servers||[]).forEach(s=>{
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = s;
    serverSelect.appendChild(opt);
  });
  (state.waitlist||[]).forEach(w=>{
    const li = document.createElement("li");
    li.className = "list-group-item d-flex justify-content-between align-items-start";
    li.innerHTML = `<div><strong>${w.name}</strong> · ${w.party} • <small>${w.notes||""}</small><br><small class='text-muted'>Waiting: <span data-added='${w.added_at}'>${formatDuration(w.added_at)}</span></small></div>
    <div class="btn-group-vertical">
      <button class="btn btn-sm btn-success" onclick="seatFromWait('${w.id}')">Seat</button>
      <button class="btn btn-sm btn-outline-danger" onclick="removeWait('${w.id}')">Remove</button>
    </div>`;
    waitlistEl.appendChild(li);
  });
}

async function removeWait(id){
  await axios.post("/api/remove_wait",{id});
  fetchState();
}

async function seatFromWait(waitId){
  // choose selected table first
  if(!selectedTable){
    alert("Select a table first to seat the party.");
    return;
  }
  const server = prompt("Assign server (leave blank to leave unassigned):");
  await axios.post("/api/seat_table",{table_id:selectedTable.id, wait_id:waitId, server});
  fetchState();
}

waitForm.addEventListener("submit", async (e)=>{
  e.preventDefault();
  const fd = new FormData(waitForm);
  const data = {name: fd.get("name"), party: fd.get("party"), notes: fd.get("notes")};
  await axios.post("/api/add_wait", data);
  waitForm.reset();
  fetchState();
});

function renderTables(){
  // update button badges
  document.querySelectorAll(".table-btn").forEach(btn=>{
    const tid = btn.dataset.table;
    const t = state.tables[tid];
    if(!t) return;
    btn.classList.remove("btn-success","btn-warning","btn-danger");
    if(t.status=="seated") btn.classList.add("btn-success");
    if(t.status=="dirty") btn.classList.add("btn-danger");
    if(t.status=="waiting") btn.classList.add("btn-warning");
    btn.querySelector(".status-badge").textContent = t.status;
    btn.onclick = ()=> selectTable(tid);
  });
}

function selectTable(tid){
  selectedTable = state.tables[tid];
  renderTableDetails();
}

function renderTableDetails(){
  if(!selectedTable){
    tableDetails.innerHTML = "<em>Select a table</em>";
    return;
  }
  tableDetails.innerHTML = `<h6>${selectedTable.name}</h6>
    <p>Section ${selectedTable.section} · ${selectedTable.seats} seats</p>
    <p>Status: <strong>${selectedTable.status}</strong></p>
    <p>Server: <strong>${selectedTable.server||"—"}</strong></p>
    <p>Seated at: ${selectedTable.seated_at?new Date(selectedTable.seated_at).toLocaleString():"—"}</p>
    <p>Notes: <input id="tableNotes" class="form-control" value="${selectedTable.notes||""}"></p>
    <div class="d-grid gap-2 mt-2">
      <button class="btn btn-primary" onclick="seatTablePrompt()">Seat</button>
      <button class="btn btn-outline-secondary" onclick="busTable()">Bus</button>
      <button class="btn btn-outline-danger" onclick="clearTable()">Clear</button>
    </div>`;
}

async function seatTablePrompt(){
  const server = prompt("Assign server name (leave blank to keep current):", selectedTable.server||"");
  const notes = document.getElementById("tableNotes").value;
  await axios.post("/api/seat_table",{table_id:selectedTable.id, server:server||null, notes});
  await fetchState();
}

async function busTable(){
  await axios.post("/api/bus_table",{table_id:selectedTable.id});
  await fetchState();
}

async function clearTable(){
  await axios.post("/api/clear_table",{table_id:selectedTable.id});
  await fetchState();
}

function renderServers(){
  serverLoadsEl.innerHTML = "";
  for(const s of state.servers){
    const li = document.createElement("li");
    li.className = "list-group-item d-flex justify-content-between align-items-center";
    const load = state.server_loads[s]||0;
    li.innerHTML = `<div>${s}</div><span class="badge rounded-pill">${load}</span>`;
    serverLoadsEl.appendChild(li);
  }
}

async function updateServerSuggestion(){
  const r = await axios.get("/api/suggest_server");
  serverSuggestion.textContent = `Suggestion: ${r.data.suggestion} · loads: ${JSON.stringify(r.data.loads)}`;
}

rotationSelect.addEventListener("change", async ()=>{
  await axios.post("/api/set_rotation",{rotation: rotationSelect.value});
  fetchState();
});

suggestBtn.addEventListener("click", updateServerSuggestion);
refreshBtn.addEventListener("click", fetchState);

// initial fetch + interval for durations
fetchState();
setInterval(()=>{
  // update wait times and server loads every second locally by refetching minimal state
  fetchState();
}, 4000);
