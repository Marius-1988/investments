/* Dashboard en vivo – conexión por WebSocket con fallback a polling */
const $ = (s) => document.querySelector(s);
const fmt = (n, d = 2) => (n === null || n === undefined || Number.isNaN(n)) ? "—" :
  Number(n).toLocaleString("es-AR", { minimumFractionDigits: d, maximumFractionDigits: d });
const money = (n) => (n === null || n === undefined) ? "—" : "$ " + fmt(n, 2);
const pct = (n, d = 2) => (n === null || n === undefined) ? "—" : fmt(n * 100, d) + "%";
const cls = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "");
const time = (ts) => new Date(ts * 1000).toLocaleTimeString("es-AR");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const SLEEVE = { conservative: "Conservadora", aggressive: "Agresiva" };

let pnlChart, sleeveChart, lastState = null;

function initCharts() {
  pnlChart = new Chart($("#pnl-chart"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "P&L total", data: [], borderColor: "#4f8cff", backgroundColor: "rgba(79,140,255,.12)", fill: true, tension: .25, pointRadius: 0, borderWidth: 2 },
      { label: "Realizado", data: [], borderColor: "#19c37d", tension: .25, pointRadius: 0, borderWidth: 1.5 },
      { label: "No realizado", data: [], borderColor: "#a26bff", tension: .25, pointRadius: 0, borderWidth: 1, borderDash: [4, 3] },
    ]},
    options: { animation: false, responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: "#8a97ad" } } },
      scales: { x: { ticks: { color: "#8a97ad", maxTicksLimit: 8 }, grid: { color: "#1c2536" } },
                y: { ticks: { color: "#8a97ad" }, grid: { color: "#1c2536" } } } },
  });
  sleeveChart = new Chart($("#sleeve-chart"), {
    type: "bar",
    data: { labels: ["Conservadora", "Agresiva"], datasets: [
      { label: "Objetivo %", data: [80, 20], backgroundColor: "rgba(138,151,173,.35)" },
      { label: "Capital %", data: [80, 20], backgroundColor: "#4f8cff" },
      { label: "Invertido % del total invertido", data: [0, 0], backgroundColor: "#19c37d" },
    ]},
    options: { animation: false, responsive: true, maintainAspectRatio: false, indexAxis: "y",
      plugins: { legend: { labels: { color: "#8a97ad", boxWidth: 10, font: { size: 10 } } } },
      scales: { x: { max: 100, ticks: { color: "#8a97ad" }, grid: { color: "#1c2536" } }, y: { ticks: { color: "#8a97ad" } } } },
  });
}

function render(s) {
  lastState = s;
  // header
  $("#mode").innerHTML = s.live ? `<span class="badge live">LIVE · DINERO REAL</span> ${esc(s.broker)}` : esc(s.mode);
  $("#state-badge").className = "badge " + s.state; $("#state-badge").textContent = s.state;
  const ses = s.session || {};
  $("#session-badge").className = "badge " + (ses.phase || ""); $("#session-badge").textContent = ses.phase || "—";
  $("#clock").textContent = ses.now ? new Date(ses.now).toLocaleTimeString("es-AR", { timeZone: "America/Argentina/Buenos_Aires" }) + " ART" : "";
  $("#state-reason").textContent = `${s.state_reason} · Sesión: ${ses.reason || "—"}` + (ses.opens_at && !ses.is_open ? ` · Próxima apertura: ${new Date(ses.opens_at).toLocaleString("es-AR")}` : "");
  const st = s.state;
  $("#btn-start").disabled = st === "RUNNING" || st === "PAUSED";
  $("#btn-pause").disabled = st !== "RUNNING";
  $("#btn-resume").disabled = st !== "PAUSED";
  $("#btn-stop").disabled = st === "STOPPED";

  // KPIs
  const k = s.kpis;
  const kp = [
    ["Equity", money(k.equity), ""], ["P&L día", money(k.pnl), cls(k.pnl)], ["P&L %", pct(k.pnl_pct, 3), cls(k.pnl)],
    ["Realizado", money(k.realized), cls(k.realized)], ["No realizado", money(k.unrealized), cls(k.unrealized)],
    ["Operaciones", k.trades, ""], ["Win rate", k.win_rate == null ? "—" : pct(k.win_rate, 1), ""],
    ["Profit factor", k.profit_factor == null ? "—" : (k.profit_factor >= 999 ? "∞" : fmt(k.profit_factor)), k.profit_factor >= 1 ? "pos" : k.profit_factor == null ? "" : "neg"],
    ["Exposición", pct(k.exposure_pct, 1), ""], ["Costos pagados", money(k.fees), "neg"],
  ];
  $("#kpis").innerHTML = kp.map(([l, v, c]) => `<div class="kpi"><div class="l">${l}</div><div class="v ${c}">${v}</div></div>`).join("");

  // P&L chart
  const curve = s.equity_curve || [];
  pnlChart.data.labels = curve.map((p) => time(p.ts));
  pnlChart.data.datasets[0].data = curve.map((p) => p.pnl);
  pnlChart.data.datasets[1].data = curve.map((p) => p.realized);
  pnlChart.data.datasets[2].data = curve.map((p) => p.unrealized);
  const last = curve[curve.length - 1]; pnlChart.data.datasets[0].borderColor = last && last.pnl < 0 ? "#ff4d5e" : "#4f8cff";
  pnlChart.update();
  $("#pnl-label").textContent = `Capital asignado ${money(s.capital)} · minuto ${s.minute}`;

  // Mood
  const m = s.mood || {};
  $("#regime").className = "badge " + m.regime; $("#regime").textContent = m.regime || "—";
  $("#mood-needle").style.left = `calc(${(((m.score || 0) + 100) / 200) * 100}% - 2px)`;
  $("#mood-reason").textContent = m.reason || "";
  $("#mood-kv").innerHTML = [
    ["Score de ánimo", fmt(m.score, 1)], ["Amplitud (activos subiendo)", m.breadth == null ? "—" : pct(m.breadth, 0)],
    ["Tendencia índice 15m", m.trend_15m_pct == null ? "—" : fmt(m.trend_15m_pct, 3) + "%"],
    ["Ratio volatilidad", fmt(m.vol_ratio)], ["Z-score índice 1m", fmt(m.index_z)], ["Ensanche de spreads", fmt(m.spread_ratio)],
    ["Entradas permitidas", m.entries_allowed ? "SÍ" : "NO"], ["Multiplicador de tamaño", fmt(m.size_multiplier, 1)],
  ].map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join("");
  $("#anomalies").innerHTML = (m.anomalies || []).map((a) => `<li>${esc(a)}</li>`).join("");

  // Risk
  const r = s.risk, g = r.gate || {}, L = r.limits;
  const minHold = L.min_holding_minutes || 1;
  const maxHold = L.max_holding_minutes || 5;
  const titleEl = $("#assessments-title");
  if (titleEl) titleEl.textContent = `Riesgo por activo (ventana ${minHold}-${maxHold} min)`;
  const meter = (label, used, txt) => {
    const u = Math.max(0, Math.min(1, used || 0)); const color = u > .8 ? "var(--bad)" : u > .5 ? "var(--warn)" : "var(--ok)";
    return `<div class="meter"><div class="lbl"><span>${label}</span><span>${txt}</span></div><div class="bar"><div class="fill" style="width:${u * 100}%;background:${color}"></div></div></div>`;
  };
  $("#risk-meters").innerHTML =
    meter("Límite de pérdida diaria", g.daily_loss_used, `${pct(Math.min(0, g.day_pnl_pct || 0))} / -${pct(L.daily_max_loss_pct)}`) +
    meter("Drawdown intradiario", g.drawdown_used, `${pct(g.drawdown_pct || 0)} / ${pct(L.max_drawdown_pct)}`) +
    meter("Exposición", (k.exposure_pct || 0) / L.max_total_exposure_pct, `${pct(k.exposure_pct, 1)} / ${pct(L.max_total_exposure_pct, 0)}`) +
    meter("Operaciones última hora", r.trades_last_hour / r.max_trades_per_hour, `${r.trades_last_hour} / ${r.max_trades_per_hour}`) +
    meter("Pérdidas consecutivas", r.consecutive_losses / L.max_consecutive_losses, `${r.consecutive_losses} / ${L.max_consecutive_losses}`);
  $("#risk-kv").innerHTML = [
    ["Riesgo por operación", pct(L.risk_per_trade_pct)], ["Costo ida+vuelta", pct(L.round_trip_cost_pct)],
    ["Objetivo diario (lock)", "+" + pct(L.daily_profit_lock_pct)], ["Ventana máx. por trade", L.max_holding_minutes + " min"],
    ["Profit lock", g.profit_locked ? "ACTIVO" : "no"], ["Enfriamiento", r.cooldown_active ? "ACTIVO" : "no"],
    ["Circuit breaker", r.halted_reason ? esc(r.halted_reason) : "OK"],
  ].map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join("");

  // Sleeves
  const total = s.sleeves.reduce((a, x) => a + x.capital, 0) || 1;
  sleeveChart.data.datasets[0].data = s.sleeves.map((x) => x.target_weight * 100);
  sleeveChart.data.datasets[1].data = s.sleeves.map((x) => (x.capital / total) * 100);
  sleeveChart.data.datasets[2].data = s.sleeves.map((x) => x.share_of_invested * 100);
  sleeveChart.update();
  $("#sleeves").innerHTML = s.sleeves.map((x) => `<div class="sleeve"><b>${SLEEVE[x.name] || x.name}</b> (${x.allowed_risk.join("/")}) ·
    capital ${money(x.capital)} · invertido ${money(x.invested)} (${pct(x.utilization, 1)}) · posiciones ${x.open_positions}/${x.max_open_positions} ·
    realizado <span class="${cls(x.realized_pnl)}">${money(x.realized_pnl)}</span> · win ${x.win_rate == null ? "—" : pct(x.win_rate, 0)}</div>`).join("");

  // Agents
  $("#agents").innerHTML = s.agents.map((a) => `<div class="agent"><b>${esc(a.title)}</b><p>${esc(a.mission)}</p></div>`).join("");

  // Positions
  $("#pos-count").textContent = `${s.positions.length} abiertas`;
  $("#positions tbody").innerHTML = s.positions.map((p) => `<tr><td><b>${p.symbol}</b></td><td>${SLEEVE[p.sleeve] || p.sleeve}</td>
    <td class="lvl ${p.risk_level}">${p.risk_level}</td><td>${p.quantity}</td><td>${fmt(p.entry_price)}</td><td>${fmt(p.last_price)}</td>
    <td>${fmt(p.stop)}</td><td>${fmt(p.target)}</td><td class="${cls(p.r_multiple)}">${fmt(p.r_multiple)}</td>
    <td class="${cls(p.unrealized_pnl)}">${money(p.unrealized_pnl)}</td><td>${p.held_min}</td></tr>`).join("") ||
    `<tr><td colspan="11" class="muted">Sin posiciones abiertas</td></tr>`;

  // Assessments
  $("#assessments tbody").innerHTML = (s.assessments || []).map((a) => `<tr><td><b>${a.symbol}</b></td><td>${fmt(a.price)}</td>
    <td class="lvl ${a.risk_level}">${a.risk_level}</td><td>${fmt(a.risk_score, 0)}</td><td>${fmt(a.vol_1m_pct, 3)}</td>
    <td>${fmt(a.atr_pct, 3)}</td><td>${fmt(a.spread_pct, 3)}</td><td>${fmt(a.rsi, 0)}</td>
    <td class="${a.trend === "UP" ? "pos" : "neg"}">${a.trend}</td><td>${a.signal}</td><td>${fmt(a.confidence)}</td>
    <td class="${a.edge_vs_cost >= 2 ? "pos" : "neg"}">${fmt(a.edge_vs_cost)}x</td></tr>`).join("") ||
    `<tr><td colspan="12" class="muted">Calentando indicadores…</td></tr>`;

  // Decisions
  $("#decisions").innerHTML = (s.decisions || []).map((d) => `<div class="item ${d.approved ? "ok" : "rej"}">
    <div class="meta">${time(d.ts)} · ${d.symbol} · ${d.approved ? "APROBADA" : "RECHAZADA"} · ${SLEEVE[d.sleeve] || d.sleeve}</div>
    <ul>${d.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("") || `<div class="muted">Sin decisiones aún</div>`;

  // Trades
  $("#trades tbody").innerHTML = (s.trades || []).map((t) => `<tr><td><b>${t.symbol}</b></td><td>${SLEEVE[t.sleeve] || t.sleeve}</td>
    <td>${t.quantity}</td><td>${fmt(t.entry_price)}</td><td>${fmt(t.exit_price)}</td><td>${t.reason}</td><td>${t.held_minutes}</td>
    <td>${money(t.fees)}</td><td class="${cls(t.net_pnl)}">${money(t.net_pnl)}</td></tr>`).join("") ||
    `<tr><td colspan="9" class="muted">Sin operaciones cerradas</td></tr>`;

  // Activity
  $("#activity").innerHTML = (s.activity || []).map((a) => `<div class="item ${a.level}"><div class="meta">${time(a.ts)} · ${a.agent}</div>${esc(a.msg)}</div>`).join("");
}

async function control(action) {
  if (action === "kill" && !confirm("KILL SWITCH: se cierran TODAS las posiciones y se bloquea la operación por hoy. ¿Confirmás?")) return;
  if (action === "stop" && !confirm("Detener: se cierran las posiciones abiertas y se apaga el agente. ¿Confirmás?")) return;
  await fetch(`/api/control/${action}`, { method: "POST" });
  refresh();
}
document.querySelectorAll("[data-action]").forEach((b) => b.addEventListener("click", () => control(b.dataset.action)));

async function refresh() { try { render(await (await fetch("/api/state")).json()); } catch (e) { console.error(e); } }

function connectWS() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  let poll = null;
  ws.onmessage = (ev) => render(JSON.parse(ev.data));
  ws.onopen = () => { if (poll) clearInterval(poll); };
  ws.onclose = () => { poll = setInterval(refresh, 2000); setTimeout(connectWS, 3000); };
}

/* ------------------------- Broker wizard ------------------------- */
let brokerInfo = null, selected = null;
$("#btn-broker").addEventListener("click", openBroker);
$("#close-modal").addEventListener("click", () => $("#broker-modal").classList.add("hidden"));

async function openBroker() {
  brokerInfo = await (await fetch("/api/brokers")).json();
  $("#dma-note").textContent = "ℹ️ " + brokerInfo.direct_market_access;
  $("#plan").innerHTML = brokerInfo.plan.map((p) => `<li>${esc(p)}</li>`).join("");
  $("#broker-list").innerHTML = brokerInfo.ranking.map((b) => `<div class="broker ${b.id === brokerInfo.recommended ? "rec" : ""}">
    <div><b>${esc(b.name)}</b> ${b.id === brokerInfo.recommended ? '<span class="badge RUNNING">RECOMENDADO</span>' : ""}
      ${brokerInfo.current.broker === b.id ? '<span class="badge">CONECTADO</span>' : ""}
      <div class="small muted">${esc(b.kind)} · ${esc(b.markets)}</div>
      <ul>${b.pros.map((p) => `<li class="pos">${esc(p)}</li>`).join("")}${b.cons.map((c) => `<li class="neg">${esc(c)}</li>`).join("")}</ul></div>
    <div><div class="score">${b.score}</div>${b.adapter ? `<button class="btn ok" data-broker="${b.id}">Seleccionar</button>` : '<span class="small muted">Sin adaptador</span>'}</div>
  </div>`).join("");
  document.querySelectorAll("[data-broker]").forEach((btn) => btn.addEventListener("click", () => selectBroker(btn.dataset.broker)));
  $("#broker-form").classList.add("hidden");
  $("#broker-modal").classList.remove("hidden");
}

function selectBroker(id) {
  selected = brokerInfo.ranking.find((b) => b.id === id);
  $("#form-title").textContent = `Conectar: ${selected.name}`;
  $("#form-fields").innerHTML = selected.fields.map((f) => `<label class="small">${esc(f.label)}
    <input name="${f.key}" type="${f.secret ? "password" : "text"}" value="${esc(f.default || "")}" autocomplete="off"/></label>`).join("") ||
    `<p class="small muted">No requiere credenciales.</p>`;
  const live = id === "iol";
  $("#live-block").classList.toggle("hidden", !live && id !== "primary");
  $("#live-phrase").textContent = brokerInfo.live_confirmation_phrase;
  $("#form-msg").textContent = brokerInfo.live_allowed_by_env ? "" : "Modo LIVE bloqueado (ALLOW_LIVE_TRADING=false en .env). Sólo paper/demo.";
  $("#broker-form").classList.remove("hidden");
}

$("#broker-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const credentials = {};
  $("#form-fields").querySelectorAll("input").forEach((i) => (credentials[i.name] = i.value));
  $("#form-msg").textContent = "Validando…";
  const res = await fetch("/api/brokers/connect", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ broker: selected.id, credentials, confirmation: $("#live-confirm").value }) });
  const j = await res.json();
  $("#form-msg").innerHTML = res.ok ? `<span class="pos">✔ Conectado a ${esc(j.broker)} (${j.live ? "LIVE" : "demo/paper"}) · feed ${esc(j.feed)}</span>`
    : `<span class="neg">✘ ${esc(j.detail)}</span>`;
  refresh();
});

initCharts();
refresh();
connectWS();
