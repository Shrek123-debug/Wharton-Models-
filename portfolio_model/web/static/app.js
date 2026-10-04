/* Portfolio analysis dashboard — renders deterministic pipeline output with local plotly.js. */
"use strict";

const state = { jobId: null, payload: null, pollTimer: null };

/* ---------------------------------------------------------------- formatting */
const PCT = new Set(["weight","target_weight","difference","volatility","expected_return","var_95","cvar_95",
  "historical_VaR","historical_CVaR","parametric_VaR","parametric_CVaR","return_12m","contribution_12m",
  "portfolio_return","cumulative_return","drawdown","rolling_vol_12m","prob_success","prob_all_payments_funded",
  "prob_depletion","prob_payments_funded","median_max_dd","max_drawdown","worst_day","worst_week","worst_month",
  "worst_holding_return","best_holding_return","sector_return_12m","current_weight","target","lower_band",
  "upper_band","suggested_trade","turnover","return_shift","mean_return","std_return","equity","bond","cash",
  "annual_return","shock_return","contribution","confidence"]);
const MONEY = new Set(["terminal_value","median_terminal","p5_terminal","min_value","market_value",
  "required_reserve","total_contributions","median_facility"]);

const pct = v => v === null || v === undefined ? "—" : (v * 100).toFixed(1) + "%";
const money = v => v === null || v === undefined ? "—" : "$" + Math.round(v).toLocaleString("en-US");
const fixed = (v, d) => v === null || v === undefined ? "—" : Number(v).toFixed(d);

function fmtCell(col, v, row) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "TRIGGERED" : "ok";
  if (col === "turnover" && row && row.mode !== undefined) return fixed(v, 1);
  if (PCT.has(col)) return pct(v);
  if (MONEY.has(col)) return money(v);
  const metric = (row && (row.metric || row.Metric)) || "";
  if (col === "value") {
    if (/HHI|bets|Sharpe|Sortino|deviation|duration|Overall|Score/i.test(metric)) return fixed(v, 2);
    if (Math.abs(v) <= 1.5) return pct(v);
    return money(v);
  }
  if (["Monte Carlo", "Markov", "Historical Bootstrap"].includes(col)) {
    if (/Probability/i.test(metric)) return pct(v);
    return money(v);
  }
  if (Math.abs(v) < 1.5 && /prob|weight|return|shift|band|dd|drawdown|var|cvar/i.test(col)) return pct(v);
  if (Math.abs(v) >= 1000) return money(v);
  return fixed(v, 3);
}

function fmtDashboard(v, fmt) {
  if (v === null || v === undefined) return "—";
  if (fmt === "#,##0") return money(v);
  if (fmt && fmt.includes("%")) return pct(v);
  if (fmt === "0.00") return fixed(v, 2);
  if (fmt === "0.0") return fixed(v, 1);
  return String(v);
}

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------------------------------------------------------------- tables */
const tableData = {};
function tableHTML(name, rows, opts = {}) {
  tableData[name] = { rows, sortCol: null, asc: true };
  if (!rows || !rows.length) return `<div class="table-empty">No rows.</div>`;
  const cols = Object.keys(rows[0]);
  const head = cols.map(c => `<th data-table="${name}" data-col="${esc(c)}" class="sortable">${esc(c)}</th>`).join("");
  const cap = opts.cap && rows.length > opts.cap ? ` <span class="cap-note">(showing ${opts.cap} of ${rows.length})</span>` : "";
  const shown = opts.cap ? rows.slice(0, opts.cap) : rows;
  const bodyShown = shown.map(r => `<tr>${cols.map(c => `<td>${fmtCell(c, r[c], r)}</td>`).join("")}</tr>`).join("");
  return `<div class="table-title">${esc(opts.title || name)}${cap}</div><table><thead><tr>${head}</tr></thead><tbody>${bodyShown}</tbody></table>`;
}

function rerenderTable(name) {
  const t = tableData[name];
  const wrap = document.querySelector(`.table-block[data-table-block="${name}"]`);
  if (!t || !wrap) return;
  let rows = t.rows;
  if (t.sortCol) {
    rows = [...rows].sort((a, b) => {
      const x = a[t.sortCol], y = b[t.sortCol];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      if (typeof x === "number" && typeof y === "number") return t.asc ? x - y : y - x;
      return t.asc ? String(x).localeCompare(String(y)) : String(y).localeCompare(String(x));
    });
  }
  const cols = Object.keys(rows[0] || {});
  wrap.querySelector("tbody").innerHTML = rows.map(r => `<tr>${cols.map(c => `<td>${fmtCell(c, r[c], r)}</td>`).join("")}</tr>`).join("");
}

/* ---------------------------------------------------------------- blocks */
const chart = key => `<div class="chart" data-chart="${key}"></div>`;
const tableBlock = (key, opts) => `<div class="table-block" data-table-block="${key}">${tableHTML(key, state.payload.tables[key], opts)}</div>`;
const textBlock = key => `<p class="narrative">${esc(state.payload.texts[key] || "")}</p>`;
const listBlock = (key, cls) => `<ul class="${cls || "plain-list"}">${(state.payload[key] || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul>`;
const dictBlock = obj => Object.entries(obj || {}).map(([k, v]) =>
  `<div class="sub-head">${esc(k)}</div><ul class="plain-list">${(v || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul>`).join("");

const SEV_ICON = { CRITICAL: "⛔", HIGH: "🔴", WARNING: "🟠", MONITOR: "🟡", INFO: "ℹ️" };
function flagCard(f) {
  const fmt = f.format === "pct" ? pct : f.format === "count" ? (v => String(v)) : (v => fixed(v, 2));
  return `<div class="flag-card sev-${f.severity}">
    <div class="flag-head"><span class="sev-badge sev-${f.severity}">${SEV_ICON[f.severity] || ""} ${f.severity}</span>
      <span class="flag-id">${esc(f.id)}</span><span class="flag-cat">${esc(f.category)}</span></div>
    <div class="flag-metric">${esc(f.metric)}</div>
    <div class="flag-values"><span><b>Current:</b> ${fmt(f.current_value, 3)}</span>
      <span><b>Threshold:</b> ${fmt(f.threshold, 3)}</span></div>
    <div class="flag-rule"><b>Rule:</b> ${esc(f.rule)}</div>
    <div class="flag-action"><b>Suggested action:</b> ${esc(f.action)}</div>
    <div class="flag-evidence">${esc(f.evidence)}</div>
  </div>`;
}

/* ---------------------------------------------------------------- tabs */
const TABS = [
  { id: "overview", label: "Overview", render: renderOverview },
  { id: "holdings", label: "Holdings & Sectors", render: renderHoldings },
  { id: "history", label: "History", render: renderHistory },
  { id: "mc", label: "Monte Carlo", render: renderMC },
  { id: "markov", label: "Markov Regime", render: renderMarkov },
  { id: "bs", label: "Historical Bootstrap", render: renderBS },
  { id: "comparison", label: "Model Comparison", render: renderComparison },
  { id: "sensitivity", label: "Sensitivity", render: renderSensitivity },
  { id: "stress", label: "Stress Tests", render: renderStress },
  { id: "risk", label: "Risk & Concentration", render: renderRisk },
  { id: "rebalance", label: "Rebalance & Glide", render: renderRebalance },
  { id: "flags", label: "Flags & Actions", render: renderFlags },
  { id: "dq", label: "Data Quality", render: renderDQ },
  { id: "method", label: "Methodology", render: renderMethod },
];

function renderOverview() {
  const p = state.payload;
  const counts = {};
  p.rule_flags.forEach(f => counts[f.severity] = (counts[f.severity] || 0) + 1);
  const chips = ["CRITICAL", "HIGH", "WARNING", "MONITOR"].map(s =>
    `<span class="sev-badge sev-${s}">${s}: ${counts[s] || 0}</span>`).join(" ");
  return `
    <div class="grid2">
      <div class="card">${chart("allocation")}</div>
      <div class="card">${chart("sector_bar")}</div>
    </div>
    <div class="card">
      <div class="sub-head">Executive summary</div>
      ${p.exec_summary.map(l => `<p class="summary-line">${esc(l)}</p>`).join("")}
    </div>
    <div class="card">
      <div class="sub-head">Rule-based flags (deterministic)</div>
      <div class="chip-row">${chips}</div>
      ${p.rule_flags.slice(0, 6).map(flagCard).join("") || `<p class="narrative">No rule flags triggered.</p>`}
      <p class="mini-note">Full list in the Flags &amp; Actions tab. Each flag = metric → current value → threshold → rule → action → severity.</p>
    </div>
    <div class="card"><div class="sub-head">Portfolio scorecard</div>${chart("scorecard")}</div>`;
}

function renderHoldings() {
  return `
    <div class="card">${tableBlock("holdings", { title: "Holdings" })}</div>
    <div class="grid2">
      <div class="card">${chart("contribution")}</div>
      <div class="card">${chart("concentration")}</div>
    </div>
    <div class="card">${tableBlock("sectors", { title: "Sector Allocation & Attribution" })}</div>
    <div class="grid2">
      <div class="card">${chart("sec_corr_heatmap")}</div>
      <div class="card"><div class="sub-head">Sector narrative</div>${listBlock("sector_narrative")}</div>
    </div>
    <div class="card">${tableBlock("theses", { title: "Investment Theses" })}</div>`;
}

function renderHistory() {
  return `
    <div class="card">${chart("cumulative")}</div>
    <div class="card">${chart("drawdown")}</div>
    <div class="card"><div class="sub-head">Historical analysis</div>${textBlock("historical_text")}</div>
    <div class="grid2">
      <div class="card">${tableBlock("recovery", { title: "Major Drawdown Recovery Events" })}</div>
      <div class="card">${tableBlock("history", { title: "Monthly History", cap: 24 })}</div>
    </div>`;
}

function renderMC() {
  return `
    <div class="card"><div class="sub-head">Monte Carlo</div>${textBlock("mc_text")}</div>
    <div class="card">${chart("mc_fan")}</div>
    <div class="grid2">
      <div class="card">${chart("terminal_dist")}</div>
      <div class="card">${chart("dd_dist")}</div>
    </div>
    <div class="card">${tableBlock("mc_percentiles", { title: "MC Percentile Summary" })}</div>`;
}

function renderMarkov() {
  return `
    <div class="card"><div class="sub-head">Markov regime model</div>${textBlock("markov_text")}</div>
    <div class="grid2">
      <div class="card">${chart("markov_P")}</div>
      <div class="card">${chart("markov_dist")}</div>
    </div>
    <div class="grid2">
      <div class="card">${tableBlock("markov_states", { title: "State Statistics" })}</div>
      <div class="card">${tableBlock("markov_misc", { title: "Regime Diagnostics" })}</div>
    </div>
    <div class="card">${tableBlock("markov_timeline", { title: "Historical State Assignment" })}</div>`;
}

function renderBS() {
  return `
    <div class="card"><div class="sub-head">Historical bootstrap</div>${textBlock("bs_text")}</div>
    <div class="card">${chart("bs_fan")}</div>
    <div class="card"><div class="sub-head">Terminal distributions (all engines overlaid)</div>${chart("terminal_dist")}</div>`;
}

function renderComparison() {
  return `
    <div class="card">${chart("comparison")}</div>
    <div class="card">${tableBlock("comparison", { title: "Monte Carlo vs Markov vs Historical Bootstrap" })}</div>
    <div class="card"><div class="sub-head">Disagreement analysis</div>${textBlock("disagreement_text")}
      ${tableBlock("disagreement", { title: "Model Disagreement" })}</div>`;
}

function renderSensitivity() {
  return `
    <div class="card"><div class="sub-head">Interpretation</div>${textBlock("sensitivity_text")}</div>
    <div class="grid2">
      <div class="card">${chart("sens_success")}</div>
      <div class="card">${chart("sens_terminal")}</div>
    </div>
    <div class="card">${tableBlock("sensitivity", { title: "Sensitivity Grid" })}</div>`;
}

function renderStress() {
  return `
    <div class="card">${chart("crisis")}</div>
    <div class="card">${tableBlock("stress", { title: "Historical Crisis Stress Tests" })}</div>
    <div class="card">${tableBlock("hypothetical", { title: "Hypothetical Forward Scenarios (assumptions, not forecasts)" })}</div>`;
}

function renderRisk() {
  return `
    <div class="grid2">
      <div class="card">${tableBlock("risk", { title: "Portfolio Risk Metrics" })}</div>
      <div class="card">${tableBlock("var_table", { title: "VaR / CVaR (one-month horizon)" })}</div>
    </div>
    <div class="card"><div class="sub-head">Concentration &amp; correlation</div>${textBlock("concentration_text")}${textBlock("correlation_text")}${textBlock("risk_text")}</div>
    <div class="card">${chart("corr_heatmap")}</div>
    <div class="card">${tableBlock("stops", { title: "Stop-Loss Backtests (historical, not advice)", cap: 30 })}</div>`;
}

function renderRebalance() {
  return `
    <div class="card"><div class="sub-head">Rebalancing framework</div>${textBlock("rebalance_text")}
      ${tableBlock("rebalance", { title: "Band Triggers & Suggested Trades" })}</div>
    <div class="card">${chart("glide")}</div>
    <div class="grid2">
      <div class="card">${tableBlock("glide", { title: "Glide Path Targets" })}</div>
      <div class="card">${tableBlock("glide_impact", { title: "Glide Path Impact" })}</div>
    </div>
    <div class="card"><div class="sub-head">Optimization diagnostic</div>
      <p class="mini-note">${esc(state.payload.opt_note)}</p>
      ${tableBlock("optimization", { title: "Max-Sharpe Suggestion (diagnostic, not mandatory)" })}</div>`;
}

function renderFlags() {
  const p = state.payload;
  const th = p.thresholds;
  const thRow = `<div class="chip-row">
    <span class="th-chip">Max position ${pct(th.max_position_weight)}</span>
    <span class="th-chip">Max sector ${pct(th.max_sector_weight)}</span>
    <span class="th-chip">Max group ${pct(th.max_correlated_group_weight)}</span>
    <span class="th-chip">Min cash ${pct(th.min_cash_weight)}</span>
    <span class="th-chip">Correlation ${th.correlation_threshold.toFixed(2)}</span>
    <span class="th-chip">Band ±${pct(th.rebalancing_band)}</span>
    <span class="th-chip">Txn cost ${pct(th.transaction_cost)}</span>
    <span class="th-chip">Required reserve ${money(th.required_reserve)}</span>
  </div>`;
  return `
    <div class="card"><div class="sub-head">Configured thresholds (editable in Run options)</div>${thRow}</div>
    <div class="card"><div class="sub-head">Rule-based risk &amp; rebalancing flags</div>
      <p class="mini-note">These are rule-based portfolio risk flags, not AI-generated recommendations.</p>
      ${p.rule_flags.map(flagCard).join("") || `<p class="narrative">No rule flags triggered.</p>`}</div>
    <div class="card"><div class="sub-head">Key risks</div>${listBlock("key_risks")}</div>
    <div class="card"><div class="sub-head">Recommended actions (rule-derived)</div>${dictBlock(p.recommendations)}</div>
    <div class="card"><div class="sub-head">Risk discipline rules</div>${listBlock("risk_discipline")}</div>
    <div class="card"><div class="sub-head">Decision matrix</div>${tableBlock("decision_matrix", { title: "Final Decision Matrix" })}</div>
    <div class="card"><div class="sub-head">Conclusions</div>${dictBlock(p.conclusions)}</div>
    <div class="card"><div class="sub-head">Monitoring checklist</div>${listBlock("monitoring")}</div>`;
}

function renderDQ() {
  return `
    <div class="card">${tableBlock("data_quality", { title: "Data Quality Flags & Limitations" })}</div>
    <div class="card"><div class="sub-head">Assumptions</div>${listBlock("assumptions")}</div>
    <div class="card"><div class="sub-head">Limitations</div>${listBlock("limitations")}</div>`;
}

function renderMethod() {
  const m = state.payload.meta;
  return `
    <div class="card"><div class="sub-head">Reproducibility manifest</div>
      <div class="chip-row">
        <span class="th-chip">Seed ${m.seed}</span><span class="th-chip">Sims ${Number(m.n_sims).toLocaleString()}</span>
        <span class="th-chip">Model v${m.version}</span><span class="th-chip">Generated ${esc(m.generated_utc)}</span>
        <span class="th-chip">Python ${esc(m.python)}</span><span class="th-chip">Weights: ${esc(m.weights_source)}</span>
      </div></div>
    <div class="card"><div class="sub-head">Methodology</div>${listBlock("methodology")}</div>
    <div class="card"><div class="sub-head">Assumptions</div>${listBlock("assumptions")}</div>`;
}

/* ---------------------------------------------------------------- rendering */
function renderKPIs() {
  const strip = document.getElementById("kpi-strip");
  strip.classList.remove("hidden");
  strip.innerHTML = state.payload.dashboard.map(([l, v, f]) =>
    `<div class="kpi"><div class="kpi-label">${esc(l)}</div><div class="kpi-value">${fmtDashboard(v, f)}</div></div>`).join("");
}

function renderTabs() {
  const nav = document.getElementById("tabs");
  nav.classList.remove("hidden");
  if (!nav.childElementCount) {
    nav.innerHTML = TABS.map((t, i) =>
      `<button class="tab${i === 0 ? " active" : ""}" data-tab="${t.id}">${t.label}</button>`).join("");
    nav.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => selectTab(btn.dataset.tab)));
  }
  selectTab(nav.querySelector(".tab.active").dataset.tab);
}

function selectTab(id) {
  const tab = TABS.find(t => t.id === id);
  document.querySelectorAll("#tabs .tab").forEach(b => b.classList.toggle("active", b.dataset.tab === id));
  const content = document.getElementById("tab-content");
  content.innerHTML = tab.render();
  content.querySelectorAll("[data-chart]").forEach(el => {
    const spec = state.payload.charts[el.dataset.chart];
    if (spec) Plotly.newPlot(el, spec.data, spec.layout, { responsive: true, displaylogo: false });
  });
  content.querySelectorAll("th.sortable").forEach(th => th.addEventListener("click", () => {
    const t = tableData[th.dataset.table];
    if (t.sortCol === th.dataset.col) t.asc = !t.asc; else { t.sortCol = th.dataset.col; t.asc = true; }
    rerenderTable(th.dataset.table);
  }));
}

function renderAll() {
  document.getElementById("empty-state").classList.add("hidden");
  renderKPIs();
  renderTabs();
  const m = state.payload.meta;
  document.getElementById("meta-line").textContent =
    `${m.portfolio_name} · seed ${m.seed} · ${Number(m.n_sims).toLocaleString()} sims · ${m.generated_utc}`;
  document.getElementById("btn-xlsx").disabled = false;
  document.getElementById("btn-docx").disabled = false;
}

/* ---------------------------------------------------------------- run flow */
function collectOptions() {
  return {
    sims: parseInt(document.getElementById("opt-sims").value, 10),
    seed: parseInt(document.getElementById("opt-seed").value, 10),
    model: document.getElementById("opt-model").value,
    glide_method: document.getElementById("opt-glide").value,
    glide_end_equity: parseFloat(document.getElementById("opt-end-eq").value),
    band: parseFloat(document.getElementById("opt-band").value),
    corr_threshold: parseFloat(document.getElementById("opt-corr").value),
    max_position: parseFloat(document.getElementById("opt-maxpos").value),
    max_sector: parseFloat(document.getElementById("opt-maxsec").value),
    max_group: parseFloat(document.getElementById("opt-maxgrp").value),
    min_cash: parseFloat(document.getElementById("opt-mincash").value),
    transaction_cost: parseFloat(document.getElementById("opt-tcost").value),
    bootstrap_method: document.getElementById("opt-bs").value,
    block_size_days: parseInt(document.getElementById("opt-block").value, 10),
    sensitivity_sims: parseInt(document.getElementById("opt-sens").value, 10),
  };
}

function setStatus(html, cls) {
  const el = document.getElementById("status");
  el.className = "status " + (cls || "");
  el.innerHTML = html;
}

async function startRun(withFile) {
  const btn = document.getElementById("btn-run");
  btn.disabled = true;
  setStatus(`<span class="spinner"></span>Running analysis… (simulations execute locally)`, "running");
  const fd = new FormData();
  if (withFile) fd.append("file", withFile);
  fd.append("options", JSON.stringify(collectOptions()));
  try {
    const res = await fetch("/api/analyze", { method: "POST", body: fd });
    const body = await res.json();
    if (!res.ok) { setStatus(`✗ ${esc(body.detail || res.statusText)}`, "error"); btn.disabled = false; return; }
    pollJob(body.job_id);
  } catch (e) {
    setStatus(`✗ ${esc(e.message)}`, "error");
    btn.disabled = false;
  }
}

function pollJob(jobId) {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/job/${jobId}`);
      const j = await res.json();
      if (j.status === "running") {
        setStatus(`<span class="spinner"></span>Running… ${Math.round(j.elapsed || 0)}s elapsed`, "running");
        return;
      }
      clearInterval(state.pollTimer);
      const btn = document.getElementById("btn-run");
      btn.disabled = false;
      if (j.status === "error") { setStatus(`✗ ${esc(j.error)}`, "error"); return; }
      const rr = await fetch(`/api/results/${jobId}`);
      state.payload = await rr.json();
      state.jobId = jobId;
      setStatus(`✓ Analysis complete in ${Math.round(j.elapsed)}s — ${state.payload.rule_flags.length} rule flags triggered.`, "done");
      renderAll();
    } catch (e) { /* transient */ }
  }, 1000);
}

/* ---------------------------------------------------------------- init */
async function init() {
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    document.getElementById("opt-sims").value = String(cfg.sims);
    document.getElementById("opt-seed").value = cfg.seed;
    document.getElementById("opt-model").value = cfg.model;
    document.getElementById("opt-glide").value = cfg.glide_method;
    document.getElementById("opt-end-eq").value = cfg.glide_end_equity;
    document.getElementById("opt-band").value = cfg.band;
    document.getElementById("opt-corr").value = cfg.corr_threshold;
    document.getElementById("opt-maxpos").value = cfg.max_position;
    document.getElementById("opt-maxsec").value = cfg.max_sector;
    document.getElementById("opt-maxgrp").value = cfg.max_group;
    document.getElementById("opt-mincash").value = cfg.min_cash;
    document.getElementById("opt-tcost").value = cfg.transaction_cost;
    document.getElementById("opt-bs").value = cfg.bootstrap_method;
    document.getElementById("opt-block").value = String(cfg.block_size_days);
    document.getElementById("opt-sens").value = String(cfg.sensitivity_sims);
  } catch (e) { /* defaults stay */ }

  document.getElementById("btn-run").addEventListener("click", () => {
    const f = document.getElementById("file").files[0];
    startRun(f || null);
  });
  document.getElementById("btn-example").addEventListener("click", () => startRun(null));
  document.getElementById("btn-xlsx").addEventListener("click", () => {
    if (state.jobId) window.location.href = `/api/export/${state.jobId}/xlsx`;
  });
  document.getElementById("btn-docx").addEventListener("click", () => {
    if (state.jobId) window.location.href = `/api/export/${state.jobId}/docx`;
  });

  try {
    const res = await fetch("/api/latest");
    if (res.ok) {
      const j = await res.json();
      state.payload = j.payload;
      state.jobId = j.id;
      setStatus("✓ Loaded previous analysis result.", "done");
      renderAll();
    }
  } catch (e) { /* nothing yet */ }
}

document.addEventListener("DOMContentLoaded", init);
