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
};

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

function handleEvent(ev) {
  if (ev.source === "sysmontap" && ev.type === "process_tick") {
    clearError();
    applyTick(ev.data);
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
setInterval(() => {
  if (!lastTickAt) return;
  const age = Date.now() / 1000 - lastTickAt;
  els.tAge.textContent = age < 2 ? "a l'instant" : `il y a ${age.toFixed(0)} s`;
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
