// Dashboard minimal: consomme le bus d'events (enveloppe unique) via WebSocket.
// Aucune metrique fabriquee: si le collector est en reconnexion ou en erreur, on
// l'affiche tel quel.

const els = {
  device: document.getElementById("device"),
  conn: document.getElementById("conn"),
  banner: document.getElementById("banner"),
  tCpu: document.getElementById("t-cpu"),
  tCount: document.getElementById("t-count"),
  tRss: document.getElementById("t-rss"),
  tTop: document.getElementById("t-top"),
  tInterval: document.getElementById("t-interval"),
  tAge: document.getElementById("t-age"),
  rows: document.getElementById("rows"),
  statusLine: document.getElementById("status-line"),
  bLevel: document.getElementById("b-level"),
  bState: document.getElementById("b-state"),
  bTemp: document.getElementById("b-temp"),
  bVolt: document.getElementById("b-volt"),
  bAmp: document.getElementById("b-amp"),
  bCycles: document.getElementById("b-cycles"),
  bHealth: document.getElementById("b-health"),
  bAdapter: document.getElementById("b-adapter"),
  bAge: document.getElementById("b-age"),
  idxDot: document.getElementById("idx-dot"),
  idxState: document.getElementById("idx-state"),
  idxDetail: document.getElementById("idx-detail"),
  syslog: document.getElementById("syslog"),
};

let lastBatteryAt = 0;

let sort = { key: "cpu", dir: "desc" };
let lastTick = null;      // dernier data de process_tick
let lastTickAt = 0;       // ts host du dernier tick (epoch s)

function setConn(state) {
  const map = {
    connected: ["pill-ok", "connecte"],
    connecting: ["pill-warn", "connexion..."],
    reconnecting: ["pill-warn", "reconnexion..."],
    starting: ["pill-unknown", "demarrage..."],
    stopped: ["pill-err", "arrete"],
    closed: ["pill-err", "websocket ferme"],
  };
  const [cls, label] = map[state] || ["pill-unknown", state];
  els.conn.className = "pill " + cls;
  els.conn.textContent = label;
}

function showError(msg) {
  els.banner.textContent = msg;
  els.banner.classList.remove("hidden");
}
function clearError() {
  els.banner.classList.add("hidden");
}

function fmtBytes(mb) {
  if (mb >= 1024) return (mb / 1024).toFixed(2) + " Go";
  return mb.toFixed(1);
}

function renderTotals(data) {
  const t = data.totals || {};
  els.tCpu.textContent = (t.aggregate_cpu ?? "-") + " %";
  els.tCount.textContent = t.process_count ?? "-";
  els.tRss.textContent = t.rss_mb_total != null ? fmtBytes(t.rss_mb_total) : "-";
  els.tTop.textContent = t.top_name ? `${t.top_name} (${t.top_cpu} %)` : "-";
  els.tInterval.textContent = data.interval_ms ? data.interval_ms + " ms" : "-";
}

function renderRows(processes) {
  const sorted = [...processes].sort((a, b) => {
    let av = a[sort.key], bv = b[sort.key];
    if (typeof av === "string") { av = av.toLowerCase(); bv = bv.toLowerCase(); }
    if (av < bv) return sort.dir === "asc" ? -1 : 1;
    if (av > bv) return sort.dir === "asc" ? 1 : -1;
    return 0;
  });
  const frag = document.createDocumentFragment();
  for (const p of sorted) {
    const tr = document.createElement("tr");
    const cpuHot = p.cpu >= 50 ? " cpu-hot" : "";
    tr.innerHTML =
      `<td class="num">${p.pid}</td>` +
      `<td>${escapeHtml(p.name)}</td>` +
      `<td class="num${cpuHot}">${p.cpu.toFixed(1)}</td>` +
      `<td class="num">${p.rss_mb.toFixed(1)}</td>` +
      `<td class="num">${p.threads}</td>`;
    frag.appendChild(tr);
  }
  els.rows.replaceChildren(frag);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
  ));
}

function applyTick(data) {
  lastTick = data;
  lastTickAt = Date.now() / 1000;
  renderTotals(data);
  renderRows(data.processes || []);
  els.statusLine.textContent =
    `${(data.processes || []).length} process, maj toutes les ${data.interval_ms} ms`;
}

function fmtNum(v, suffix = "", digits = 0) {
  if (v === null || v === undefined) return "n/d";
  return (typeof v === "number" ? v.toFixed(digits) : v) + suffix;
}

function renderBattery(b) {
  lastBatteryAt = Date.now() / 1000;
  els.bLevel.textContent = fmtNum(b.level_pct, " %");
  let state = "inconnu";
  if (b.is_charging) state = "en charge";
  else if (b.fully_charged && b.external_connected) state = "plein (branche)";
  else if (b.external_connected) state = "branche";
  else state = "sur batterie";
  els.bState.textContent = state;
  els.bTemp.textContent = fmtNum(b.temperature_c, " C", 1);
  els.bVolt.textContent = fmtNum(b.voltage_v, " V", 3);
  els.bAmp.textContent = fmtNum(b.amperage_ma, " mA");
  els.bCycles.textContent = fmtNum(b.cycle_count);
  if (b.health_pct != null && b.full_capacity_mah != null && b.design_capacity_mah != null) {
    els.bHealth.textContent =
      `${b.health_pct} % (${b.full_capacity_mah}/${b.design_capacity_mah} mAh)`;
  } else {
    els.bHealth.textContent = fmtNum(b.health_pct, " %", 1);
  }
  els.bAdapter.textContent = b.adapter
    ? (b.adapter.watts != null ? `${b.adapter.watts} W` : "") +
      (b.adapter.description ? ` ${b.adapter.description}` : "") || "branche"
    : "aucun";
}

function renderIndexing(d) {
  const map = {
    indexing: ["dot-indexing", "Indexation en cours"],
    idle: ["dot-idle", "Indexation terminee"],
    unknown: ["dot-unknown", "Indexation: evaluation..."],
  };
  const [cls, label] = map[d.state] || map.unknown;
  els.idxDot.className = "dot " + cls;
  els.idxState.textContent = label;
  if (d.state === "indexing" && d.active_now) {
    const names = (d.daemons || []).map((x) => `${x.name} ${x.cpu.toFixed(0)} %`).join(", ");
    els.idxDetail.textContent = `${d.active_cpu} % CPU cumule${names ? " (" + names + ")" : ""}`;
  } else if (d.state === "indexing") {
    els.idxDetail.textContent = `refroidissement, calme depuis ${d.quiet_for_s} s`;
  } else if (d.state === "idle") {
    els.idxDetail.textContent = `calme depuis ${d.quiet_for_s} s`;
  } else {
    els.idxDetail.textContent = "";
  }
}

function appendLog(d) {
  const c = els.syslog;
  const atBottom = c.scrollHeight - c.scrollTop - c.clientHeight < 40;
  const div = document.createElement("div");
  div.className = "log-line lvl-" + (d.level || "");
  const sub = d.subsystem ? `(${d.subsystem})` : "";
  div.innerHTML =
    `<span class="lt">${escapeHtml(d.time)}</span> ` +
    `<span class="lp">${escapeHtml(d.process)}${escapeHtml(sub)}</span> ` +
    `<span class="lm">${escapeHtml(d.message)}</span>`;
  c.appendChild(div);
  while (c.childElementCount > 200) c.removeChild(c.firstElementChild);
  if (atBottom) c.scrollTop = c.scrollHeight;
}

function handleEvent(ev) {
  if (ev.source === "sysmontap" && ev.type === "process_tick") {
    clearError();
    applyTick(ev.data);
  } else if (ev.source === "diagnostics" && ev.type === "battery") {
    renderBattery(ev.data);
  } else if (ev.source === "analyzer" && ev.type === "indexing") {
    renderIndexing(ev.data);
  } else if (ev.source === "syslog" && ev.type === "line") {
    appendLog(ev.data);
  } else if (ev.source === "collector" && ev.type === "device") {
    const d = ev.data;
    els.device.textContent = `${d.name} (${d.model}, iOS ${d.ios}, ${d.transport})`;
  } else if (ev.source === "collector" && ev.type === "status") {
    setConn(ev.data.state);
    if (ev.data.state === "connected") clearError();
  } else if (ev.source === "collector" && ev.type === "error") {
    showError(`[${ev.data.scope}] ${ev.data.message}`);
  }
}

// Tri par clic sur les entetes
document.querySelectorAll("th[data-key]").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.key;
    if (sort.key === key) {
      sort.dir = sort.dir === "asc" ? "desc" : "asc";
    } else {
      sort.key = key;
      sort.dir = key === "name" ? "asc" : "desc";
    }
    document.querySelectorAll("th[data-key]").forEach((h) => {
      h.classList.remove("sorted-asc", "sorted-desc");
    });
    th.classList.add(sort.dir === "asc" ? "sorted-asc" : "sorted-desc");
    if (lastTick) renderRows(lastTick.processes || []);
  });
});

// Age du dernier tick, rafraichi en continu
function ageLabel(at) {
  const age = Date.now() / 1000 - at;
  return age < 2 ? "a l'instant" : `il y a ${age.toFixed(0)} s`;
}
setInterval(() => {
  if (lastTickAt) els.tAge.textContent = ageLabel(lastTickAt);
  if (lastBatteryAt) els.bAge.textContent = "(" + ageLabel(lastBatteryAt) + ")";
}, 500);

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === "hello") {
      if (data.udid) els.device.textContent = data.udid;
      setConn(data.state);
      (data.events || []).forEach(handleEvent);
    } else {
      handleEvent(data);
    }
  };

  ws.onclose = () => {
    setConn("closed");
    setTimeout(connect, 1500);
  };
  ws.onerror = () => ws.close();
}

connect();
