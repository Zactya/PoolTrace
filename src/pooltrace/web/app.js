"use strict";
const $ = (s) => document.querySelector(s);
const state = {
  view: "overview",
  overview: null,
  pool: "DEMO-ATLAS",
  scenario: {
    cpr: 0.08,
    discount_rate: 0.045,
    market_price: 100,
    volatility: 0.01,
    paths: 128,
    seed: 17,
  },
  analysis: null,
};
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (v, d = 2) =>
  Number(v).toLocaleString("en-US", {
    maximumFractionDigits: d,
    minimumFractionDigits: d,
  });
const money = (v) => "$" + num(v, 0);
const pct = (v) => num(v * 100, 2) + "%";
const compact = (v) => "$" + num(v / 1e6, 2) + "M";
const titles = {
  overview: [
    "The whole pool. Every detail.",
    "Cashflows, exceptions and the evidence behind them.",
  ],
  cashflows: [
    "Follow every cashflow.",
    "Reconstruct the past. Explore the assumptions ahead.",
  ],
  breaks: [
    "Differences worth understanding.",
    "Trace each break to its inputs, assumptions and owner.",
  ],
  timeline: [
    "What did we know, and when?",
    "Compare the original observation with a later correction.",
  ],
  prepayment: [
    "Test the prepayment story.",
    "Historical observations, transparent features and a temporal holdout.",
  ],
  ingestion: [
    "Good decisions start here.",
    "Immutable sources. Versioned records. Visible quality checks.",
  ],
  integrations: [
    "Built to connect.",
    "Import reference data, export results and track integration activity.",
  ],
};
async function api(path, method = "GET", body) {
  const options = { method, headers: { "X-PoolTrace-Client": "local-demo" } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const r = await fetch("/api/v1" + path, options);
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw Error(
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
    );
  }
  return r.json();
}
function validationMessage(reason) {
  return String(reason ?? "")
    .split("\n")
    .filter((line) => !/^\s*(?:\d+ validation errors? for |For further information visit )/.test(line))
    .map((line) => line.replace(/\s*\[type=[\s\S]*$/, "").replace(/^\s*Value error, /, "").trim())
    .filter(Boolean)
    .join(" · ");
}
function toast(message, error = false) {
  const t = $("#toast");
  t.textContent = message;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 6500);
}
async function action(button, fn) {
  if (button) button.disabled = true;
  try {
    await fn();
  } catch (e) {
    toast(e.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}
function pill(text, color = "") {
  return `<span class="pill ${color}">${esc(text)}</span>`;
}
function metric(label, value, foot, icon = "◈", alert = false) {
  return `<div class="metric ${alert ? "alert" : ""}"><div class="metric-label">${label}<span>${icon}</span></div><div class="metric-value">${value}</div><div class="metric-foot">${foot}</div></div>`;
}
function panel(title, subtitle, content, tag = "") {
  return `<section class="panel"><div class="panel-header"><div><h2>${title}</h2>${subtitle ? `<p>${subtitle}</p>` : ""}</div>${tag ? `<span class="panel-tag">${tag}</span>` : ""}</div>${content}</section>`;
}
function table(headers, rows, classes = "") {
  return `<div class="table-wrap"><table class="${classes}"><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
function chart(series, fields, colors, width = 650, height = 230) {
  if (!series.length)
    return '<div class="empty-inline">No observations for this selection.</div>';
  const values = series.flatMap((r) => fields.map((f) => Number(r[f] || 0)));
  const max = Math.max(...values) * 1.15 || 1;
  const left = 48,
    right = 10,
    top = 12,
    bottom = 25;
  const w = width - left - right,
    h = height - top - bottom;
  const x = (i) => left + (i * w) / Math.max(1, series.length - 1);
  const y = (v) => top + h - (v / max) * h;
  let svg = `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(fields.join(", "))} over time">`;
  for (let i = 0; i < 4; i++) {
    const v = (max * i) / 3;
    svg += `<line class="chart-grid" x1="${left}" y1="${y(v)}" x2="${width - right}" y2="${y(v)}"/><text x="${left - 8}" y="${y(v) + 4}" text-anchor="end">${max > 50000 ? num(v / 1000, 0) + "k" : max < 1 ? num(v * 100, 1) + "%" : num(v, 1)}</text>`;
  }
  fields.forEach((f, j) => {
    const points = series
      .map((r, i) => `${x(i)},${y(Number(r[f] || 0))}`)
      .join(" ");
    if (j === 0)
      svg += `<polygon points="${left},${top + h} ${points} ${x(series.length - 1)},${top + h}" fill="${colors[j]}" opacity=".06"/>`;
    svg += `<polyline points="${points}" fill="none" stroke="${colors[j]}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
  });
  [0, Math.floor((series.length - 1) / 2), series.length - 1].forEach((i) => {
    svg += `<text x="${x(i)}" y="${height - 3}" text-anchor="${i === 0 ? "start" : i === series.length - 1 ? "end" : "middle"}">${esc(series[i].period?.slice(0, 7) || "Month " + series[i].month)}</text>`;
  });
  return svg + "</svg>";
}
async function refresh(render = true) {
  state.overview = await api("/overview");
  const o = state.overview;
  $("#break-count").textContent = o.breaks.filter(
    (b) => ["open", "investigating"].includes(b.status),
  ).length;
  $("#data-badge").textContent = o.provenance.length
    ? o.provenance.every((p) => p === "synthetic")
      ? "SYNTHETIC DEMO"
      : "LOCAL IMPORTED DATA"
    : "NO DATA LOADED";
  $("#last-update").textContent =
    "Updated " + new Date(o.time).toLocaleTimeString();
  if (o.pools.length && !o.pools.some((p) => p.pool_id === state.pool))
    state.pool = o.pools[0].pool_id;
  if (render) await renderView();
}
function poolControl() {
  return `<label class="control-grow">Pool<select id="pool-select">${state.overview.pools.map((p) => `<option value="${esc(p.pool_id)}" ${p.pool_id === state.pool ? "selected" : ""}>${esc(p.name)} · ${esc(p.pool_id)}</option>`).join("")}</select></label>`;
}
function bindPool() {
  const el = $("#pool-select");
  if (el)
    el.onchange = () => {
      state.pool = el.value;
      state.analysis = null;
      action(el, renderView);
    };
}
function empty() {
  return `<div class="empty"><h2>Your workspace is ready.</h2><p>Load the synthetic demo to explore 72 loans across three pools,<br>with historical cashflows, a missing month and reference differences.</p><button class="button primary" id="empty-seed">Load synthetic demo</button></div>`;
}
async function renderOverview() {
  const o = state.overview;
  const active = o.breaks.filter((b) => ["open", "investigating"].includes(b.status));
  const balance = o.pools.reduce((s, p) => s + p.balance, 0);
  const count = o.pools.reduce((s, p) => s + p.loan_count, 0);
  const total = o.current_rows + o.counts.quarantine;
  const quality = total ? (o.current_rows / total) * 100 : 100;
  const history = await api(
    "/pools/" + encodeURIComponent(state.pool) + "/history",
  );
  const series = history.series;
  const recent = series.slice(-1)[0];
  const poolRows = o.pools.map(
    (p) =>
      `<tr><td><strong>${esc(p.name)}</strong><small>${esc(p.pool_id)}</small></td><td class="numeric">${compact(p.balance)}</td><td class="numeric">${pct(p.net_rate)}</td><td class="numeric">${p.loan_count}</td><td>${pill(o.gaps.some((g) => g.pool_id === p.pool_id) ? "Review data" : "Available", o.gaps.some((g) => g.pool_id === p.pool_id) ? "amber" : "")}</td><td><button class="text-link" data-open-pool="${esc(p.pool_id)}">Explore</button></td></tr>`,
  );
  const events = o.events
    .slice(0, 5)
    .map(
      (e) =>
        `<div class="activity"><span class="activity-icon">${e.kind.startsWith("ingestion") ? "⇥" : e.kind.startsWith("analytics") ? "≋" : "◈"}</span><div><p>${esc(e.kind.replace(".v1", "").replaceAll(".", " · "))}</p><small>${new Date(e.created_at).toLocaleTimeString()} · Event #${e.id}</small></div></div>`,
    )
    .join("");
  $("#content").innerHTML =
    `<div class="metrics">${metric("Outstanding balance", compact(balance), `Across <b>${o.pools.length} pools</b>`, "$")}${metric("Active loans", num(count, 0), num(o.current_rows, 0) + " monthly observations", "▤")}${metric("Open exceptions", num(active.length, 0), active.length ? "Awaiting review" : "Run reconciliation to compare sources", "⊞", active.length > 0)}${metric("Rows accepted", num(quality, 2) + "%", o.counts.quarantine + " row quarantined", "✓")}</div><div class="grid-main"><div>${panel("Cashflow pulse", "Historical reconstruction · " + esc(state.pool), `<div class="panel-body"><div class="legend"><span><i></i>Voluntary prepayment</span><span><i class="blue"></i>Net interest estimate</span><span><i class="amber"></i>Scheduled principal</span></div>${chart(series, ["prepayment", "net_interest", "scheduled_principal"], ["#318e78", "#638bd0", "#d2a365"])}</div><div class="panel-note">Monthly cashflows · ${series.length} observations · Known at latest ingestion</div>`, "24 MONTHS")}${panel("Pool monitor", "Current balances and data coverage", table(["Pool / identifier", "Balance", "Net coupon", "Loans", "Data", ""], poolRows))}</div><div>${panel("Data health", "Controls across the current workspace", `<div class="panel-body"><div class="quality-row"><span>Balance identities</span><strong>${num(quality, 2)}% accepted</strong></div><div class="quality-meter"><span style="width:${quality}%"></span></div><div class="quality-row"><span>Quarantined records</span>${pill(o.counts.quarantine + " row", "amber")}</div><div class="quality-row"><span>Missing / discontinuous months</span>${pill(o.gaps.length + " issue" + (o.gaps.length === 1 ? "" : "s"), o.gaps.length ? "amber" : "")}</div><div class="quality-row"><span>Versioned records</span><strong>${num(o.counts.loan_versions, 0)}</strong></div><div class="quality-row"><span>Latest observed CPR</span><strong>${pct(recent?.cpr || 0)}</strong></div><button class="text-link" data-nav="ingestion">Inspect quality controls</button></div>`)}${panel("Activity ledger", "Every operation leaves evidence", `<div class="panel-body">${events || '<p class="empty-inline">No operations yet.</p>'}</div>`, "LIVE LOCAL")}</div></div>`;
  $("#content")
    .querySelectorAll("[data-open-pool]")
    .forEach(
      (b) =>
        (b.onclick = () => {
          state.pool = b.dataset.openPool;
          navigate("cashflows");
        }),
    );
  bindNavLinks();
}
function bindNavLinks() {
  $("#content")
    .querySelectorAll("[data-nav]")
    .forEach((b) => (b.onclick = () => navigate(b.dataset.nav)));
}
async function renderView() {
  const t = titles[state.view];
  $("#page-title").textContent = t[0];
  $("#page-subtitle").textContent = t[1];
  $("#view-label").textContent = $(`#navigation [data-view="${state.view}"]`)
    .textContent.replace(/\d+/g, "")
    .trim();
  $("#navigation")
    .querySelectorAll("button")
    .forEach((b) => {
      b.classList.toggle("active", b.dataset.view === state.view);
      b.setAttribute(
        "aria-current",
        b.dataset.view === state.view ? "page" : "false",
      );
    });
  if (
    !state.overview.pools.length &&
    !["ingestion", "integrations"].includes(state.view)
  ) {
    $("#content").innerHTML = empty();
    $("#empty-seed").onclick = () => $("#seed-button").click();
    return;
  }
  const renderer = {
    overview: renderOverview,
    cashflows: renderCashflows,
    breaks: renderBreaks,
    timeline: renderTimeline,
    prepayment: renderPrepayment,
    ingestion: renderIngestion,
    integrations: renderIntegrations,
  }[state.view];
  try {
    await renderer();
  } catch (error) {
    $('#content').innerHTML = `<div class="controls">${poolControl()}</div><div class="empty"><h2>This view needs additional data.</h2><p>${esc(error.message)}</p></div>`;
    bindPool();
    return;
  }
  if (state.view === "ingestion") await appendFreddiePanel();
  if (state.view === "breaks") appendBreakTrend();
  bindPool();
}
function navigate(view) {
  state.view = view;
  window.scrollTo(0, 0);
  action(null, renderView);
}
async function renderCashflows() {
  const result = await api(
    "/pools/" + encodeURIComponent(state.pool) + "/analyze",
    "POST",
    state.scenario,
  );
  state.analysis = result;
  const h = await api("/pools/" + encodeURIComponent(state.pool) + "/history");
  const m = result.metrics;
  $("#content").innerHTML =
    `<div class="controls">${poolControl()}<label>CPR (%)<input id="cpr-input" type="number" min="0" max="80" step=".1" value="${state.scenario.cpr * 100}"></label><label>Discount rate (%)<input id="rate-input" type="number" min="0" max="25" step=".05" value="${state.scenario.discount_rate * 100}"></label><label>Target price / 100<input id="price-input" type="number" min="20.01" max="200" step=".05" value="${state.scenario.market_price}"></label><button class="button primary" id="run-scenario">Recalculate</button></div><div class="metrics">${metric("Projected price / 100", num(m.price, 3), "Current balance basis · no accrual", "$")}${metric("Weighted average life", num(m.wal, 2) + "<small> yr</small>", "Principal-weighted timing", "◷")}${metric("Fixed-cashflow duration", num(m.duration, 2) + "<small> yr</small>", "Parallel ±1 bp rate bump", "⌁")}${metric("Illustrative OAS", result.oas.oas_bps == null ? "—" : num(result.oas.oas_bps, 1) + "<small> bp</small>", "Assumed model · " + state.scenario.paths + " paths", "◈")}</div><div class="callout">${esc(result.oas.label)}. Price simulation error: ${num(result.oas.price_standard_error ?? result.oas.standard_error ?? 0, 4)} points. Projection uses a weighted-average representative loan; duration holds cashflows fixed.</div><div class="detail-grid">${panel("Projected cashflows", "Monthly principal and interest under the selected CPR", `<div class="panel-body"><div class="legend"><span><i></i>Principal</span><span><i class="blue"></i>Interest</span></div>${chart(result.projection, ["principal", "interest"], ["#318e78", "#638bd0"], 600, 230)}</div>`)}${panel("Historical reconstruction", "Reported components · monthly net-interest estimate", `<div class="panel-body">${chart(h.series, ["investor_cashflow_estimate", "prepayment"], ["#318e78", "#638bd0"], 600, 230)}</div>`)}<div class="wide">${panel(
      "Cashflow ledger",
      "Most recent twelve months",
      table(
        [
          "Period",
          "Opening balance",
          "Scheduled principal",
          "Prepayment",
          "Other reduction",
          "Net interest",
          "Closing balance",
        ],
        h.series
          .slice(-12)
          .reverse()
          .map(
            (r) =>
              `<tr><td><strong>${r.period.slice(0, 7)}</strong></td>${["beginning_balance", "scheduled_principal", "prepayment", "other_reduction", "net_interest", "ending_balance"].map((k) => `<td class="numeric">${money(r[k])}</td>`).join("")}</tr>`,
          ),
        "tight",
      ),
    )}</div></div><div class="callout">Run #${result.run_id} · Input fingerprint <code>${result.inputs_hash.slice(0, 24)}</code><br>Known at ${esc(result.knowledge_at)}. Agency payment lags, guarantees and REMIC waterfalls are outside this model.</div>`;
  $("#run-scenario").onclick = (e) =>
    action(e.currentTarget, async () => {
      const cprValue = Number($("#cpr-input").value),
        rate = Number($("#rate-input").value),
        price = Number($("#price-input").value);
      if (
        !Number.isFinite(cprValue) ||
        cprValue < 0 ||
        cprValue > 80 ||
        rate < 0 ||
        rate > 25 ||
        price <= 20 ||
        price > 200
      )
        throw Error("Check the scenario ranges.");
      state.scenario = {
        ...state.scenario,
        cpr: cprValue / 100,
        discount_rate: rate / 100,
        market_price: price,
      };
      await renderView();
      toast("Scenario recalculated and recorded.");
    });
}
async function renderBreaks() {
  const o = state.overview;
  const active = o.breaks.filter((b) => ["open", "investigating"].includes(b.status));
  $("#content").innerHTML =
    `<div class="metrics">${metric("Open / investigating", active.length, "Across all reference comparisons", "⊞", active.length > 0)}${metric("Explained by assumptions", o.breaks.filter((b) => b.classification === "assumptions_explained").length, "Measured counterfactual within tolerance", "✓")}${metric("Resolved", o.breaks.filter((b) => b.status === "resolved").length, "Every review retained in the ledger", "◈")}${metric("Reference metrics", "Price · WAL", "Duration · optional OAS", "≋")}</div>${panel(
      "Exception queue",
      "Candidates remain candidates until the numerical evidence explains the difference.",
      table(
        [
          "Pool / metric",
          "Our value",
          "Reference",
          "Difference",
          "Classification",
          "Age",
          "Owner",
          "Status",
          "",
        ],
        o.breaks.map(
          (b) =>
            `<tr><td><strong>${esc(b.pool_id)}</strong><small>${esc(b.metric)}</small></td><td class="numeric">${num(b.ours, 4)}</td><td class="numeric">${num(b.theirs, 4)}</td><td class="numeric danger-text">${b.delta > 0 ? "+" : ""}${num(b.delta, 4)}</td><td>${pill(b.classification.replaceAll("_", " "), b.classification === "assumptions_explained" ? "" : "amber")}</td><td>${Math.floor((Date.now() - Date.parse(b.opened_at)) / 86400000)}d</td><td>${esc(b.owner)}</td><td>${pill(b.status, b.status === "resolved" ? "" : b.status === "investigating" ? "blue" : "amber")}</td><td><button class="text-link" data-review="${b.id}">Review</button></td></tr>`,
        ),
      ),
    )}<div class="detail-grid">${panel(
      "Tolerance controls",
      "Absolute units: price points, years and OAS basis points.",
      `<form class="panel-body" id="tolerance-form"><div class="controls">${Object.entries(
        o.tolerances,
      )
        .map(
          ([k, v]) =>
            `<label>${esc(k)}<input name="${k}" type="number" step=".001" min="0" value="${v}" required></label>`,
        )
        .join(
          "",
        )}</div><button class="button secondary" type="submit">Save tolerances</button></form>`,
    )}${panel("Classification evidence", "Numerical attribution, not just a label", `<div class="panel-body"><p class="section-subtitle">The engine matches reference CPR and discount assumptions, then calculates the residual. An explained break means that residual is within tolerance. Date, convention and model mismatches require further review.</p><button class="text-link" data-nav="integrations">Import a reference through the API</button></div>`)}</div>`;
  $("#content")
    .querySelectorAll("[data-review]")
    .forEach((b) => (b.onclick = () => openBreak(Number(b.dataset.review))));
  $("#tolerance-form").onsubmit = (e) => {
    e.preventDefault();
    action(e.submitter, async () => {
      await api(
        "/tolerances",
        "PUT",
        Object.fromEntries(
          [...new FormData(e.currentTarget)].map(([k, v]) => [k, Number(v)]),
        ),
      );
      await refresh();
      toast("Tolerances saved. Rerun reconciliation to apply them.");
    });
  };
  bindNavLinks();
}
let currentBreak = null;
function openBreak(id) {
  currentBreak = state.overview.breaks.find((b) => b.id === id);
  $("#break-owner").value = currentBreak.owner;
  $("#break-status").value = currentBreak.status;
  $("#break-note").value = currentBreak.note;
  $("#break-evidence").innerHTML =
    `<p class="section-subtitle">${esc(currentBreak.pool_id)} · ${esc(currentBreak.metric)} · ${esc(currentBreak.classification.replaceAll("_", " "))}</p><pre>${esc(JSON.stringify(currentBreak.evidence, null, 2))}</pre>`;
  $("#break-dialog").showModal();
}
async function renderTimeline() {
  const versions = await api(
    "/pools/" + encodeURIComponent(state.pool) + "/versions",
  );
  const latest = await api(
    "/pools/" + encodeURIComponent(state.pool) + "/history",
  );
  const old = versions.find((v) => v.known_to);
  let before = null;
  if (old)
    before = await api(
      "/pools/" +
        encodeURIComponent(state.pool) +
        "/history?knowledge_at=" +
        encodeURIComponent(old.known_from),
    );
  $("#content").innerHTML =
    `<div class="controls">${poolControl()}<button class="button primary" id="restate">Apply demo correction</button><button class="button secondary" id="remap">Apply identifier change</button></div><div class="callout">Economic time answers “which month?”. Knowledge time answers “when did this system receive that version?”. Receipt times are real; the demo corrections and identifiers are synthetic.</div><div class="detail-grid">${panel("Original knowledge", before ? "As known at " + esc(old.known_from) : "Load a correction to compare two versions", `<div class="panel-body">${before ? chart(before.series, ["prepayment"], ["#638bd0"], 600, 220) : '<div class="empty-inline">The original version is retained when a correction arrives.</div>'}</div>`)}${panel("Latest knowledge", "Current version, with the correction applied", `<div class="panel-body">${chart(latest.series, ["prepayment"], ["#318e78"], 600, 220)}</div>`)}</div>${panel(
      "Version ledger",
      "Half-open knowledge intervals: known_from ≤ query time < known_to",
      table(
        [
          "Loan / period",
          "Prepayment",
          "Ending balance",
          "Known from",
          "Known until",
          "Version",
        ],
        versions.map(
          (v) =>
            `<tr><td><strong>${esc(v.loan_id)}</strong><small>${esc(v.valid_from)}</small></td><td class="numeric">${money(v.payload.prepayment)}</td><td class="numeric">${money(v.payload.ending_balance)}</td><td>${esc(v.known_from)}</td><td>${v.known_to ? esc(v.known_to) : pill("Current")}</td><td>#${v.id}</td></tr>`,
        ),
      ),
    )}${panel(
      "Identifier lineage",
      "Stable pool identity; aliases preserve both economic and knowledge time.",
      table(
        [
          "Pool",
          "Identifier",
          "Valid from",
          "Valid until",
          "Known from",
          "Known until",
        ],
        state.overview.identifiers
          .filter((i) => i.pool_id === state.pool)
          .map(
            (i) =>
              `<tr><td>${esc(i.pool_id)}</td><td><strong>${esc(i.identifier)}</strong></td><td>${esc(i.valid_from)}</td><td>${esc(i.valid_to || "Open")}</td><td>${esc(i.known_from)}</td><td>${esc(i.known_to || "Current")}</td></tr>`,
          ),
      ),
    )}`;
  $("#restate").onclick = (e) =>
    action(e.currentTarget, async () => {
      const r = await api("/demo/restate", "POST", {});
      await refresh();
      toast(
        r.idempotent
          ? "Correction already applied. No duplicates."
          : "Correction recorded. Both versions are available.",
      );
    });
  $("#remap").onclick = (e) =>
    action(e.currentTarget, async () => {
      await api("/demo/remap", "POST", {});
      await refresh();
      toast("Synthetic identifier history updated.");
    });
}
async function renderPrepayment() {
  const model = await api(
    "/pools/" + encodeURIComponent(state.pool) + "/prepayment",
  );
  $("#content").innerHTML =
    `<div class="controls">${poolControl()}<span class="pill blue">TEMPORAL HOLDOUT</span></div><div class="metrics">${metric("Holdout MAE", num(model.test_mae_cpr_pp, 3) + " pp", "CPR percentage points", "⌁")}${metric("Baseline MAE", num(model.baseline_mae_cpr_pp, 3) + " pp", "Training-period average SMM", "≋")}${metric("Training observations", num(model.training_rows, 0), "Before " + model.split_period.slice(0, 7), "▤")}${metric("Test observations", num(model.test_rows, 0), "On or after " + model.split_period.slice(0, 7), "◷")}</div>${panel("Observed vs projected CPR", "Green = observed · Blue = fitted model · Amber = training baseline", `<div class="panel-body">${chart(model.series, ["observed_cpr", "predicted_cpr", "baseline_cpr"], ["#318e78", "#638bd0", "#d2a365"], 1000, 260)}</div><div class="panel-note">Holdout starts ${model.split_period.slice(0, 7)}. Training excludes all later months.</div>`)}<div class="detail-grid">${panel(
      "Model specification",
      esc(model.method),
      table(
        ["Feature", "Coefficient"],
        model.features.map(
          (f, i) =>
            `<tr><td>${esc(f)}</td><td class="numeric">${num(model.coefficients[i], 5)}</td></tr>`,
        ),
      ),
    )}${panel("Interpretation boundaries", "What these results establish", `<div class="panel-body"><p class="section-subtitle">${esc(model.limitation)}</p><p class="section-subtitle">Liquidations and repurchases are excluded from the voluntary prepayment sample. The model is a transparent benchmark; its coefficients are not market estimates when fitted to this demo.</p></div>`)}</div>`;
}
async function renderIngestion() {
  const o = state.overview;
  const quarantine = await api("/quarantine");
  $("#content").innerHTML =
    `<div class="detail-grid">${panel("Import canonical loan-month data", "Schema 1.0 · CSV · Maximum 2 MB / 10,000 rows", `<form id="upload-form" class="panel-body"><div class="controls"><label class="control-grow">Source name<input name="source" value="user-canonical" required maxlength="80"></label><label class="control-grow">CSV file<input type="file" id="csv-file" accept=".csv" required></label></div><div class="inline-actions"><button class="button primary" type="submit">Validate & import</button><a class="button secondary" href="/api/v1/template">Download example</a></div><p class="section-subtitle">Files already imported are skipped. Corrections retain the previous version, and invalid rows are set aside for review.</p></form>`)}${panel("Backfill & source integrity", "Recover missing observations from source records.", `<div class="panel-body"><div class="quality-row"><span>Current records</span><strong>${num(o.current_rows, 0)}</strong></div><div class="quality-row"><span>Missing / discontinuous records</span>${pill(o.gaps.length, o.gaps.length ? "amber" : "")}</div><div class="inline-actions"><button class="button secondary" id="backfill">Recover demo missing month</button><button class="button secondary" id="reimport">Reimport demo</button></div><p class="section-subtitle">Recover the missing demo month from its original source records. Missing values are not estimated.</p></div>`)}</div>${panel(
      "Quality queue",
      "Invalid rows remain available with their validation reasons.",
      table(
        ["Batch", "CSV row", "Validation finding"],
        quarantine.map(
          (r) =>
            `<tr><td><code>${esc(r.batch_id.slice(0, 12))}</code></td><td>${r.row_number}</td><td class="wrap-cell">${esc(validationMessage(r.reason).slice(0, 280))}</td></tr>`,
        ),
      ),
    )}${panel(
      "Coverage findings",
      "Gaps and balance discontinuities by loan",
      table(
        ["Loan", "Pool", "Month", "Finding"],
        o.gaps
          .slice(0, 50)
          .map(
            (g) =>
              `<tr><td>${esc(g.loan_id)}</td><td>${esc(g.pool_id)}</td><td>${g.period}</td><td>${pill(g.kind.replaceAll("_", " "), "amber")}</td></tr>`,
          ),
      ),
    )}${panel(
      "Ingestion manifest",
      "Content fingerprint, schema and actual observation time",
      table(
        ["Source", "Hash / batch", "Observed at", "Accepted", "Quarantined"],
        o.batches.map(
          (b) =>
            `<tr><td><strong>${esc(b.source)}</strong><small>Schema ${esc(b.schema_version)}</small></td><td><code>${b.sha256.slice(0, 14)}…</code><small>${b.id}</small></td><td>${esc(b.observed_at)}</td><td>${num(b.accepted, 0)}</td><td>${b.rejected}</td></tr>`,
        ),
      ),
    )}`;
  $("#upload-form").onsubmit = (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    action(e.submitter, async () => {
      const file = $("#csv-file").files[0];
      if (file.size > 2e6) throw Error("Maximum CSV size is 2 MB.");
      const r = await api("/ingest", "POST", {
        source: form.elements.source.value,
        csv_text: await file.text(),
      });
      await refresh();
      toast(
        `${r.changed} changed · ${r.rejected} quarantined${r.idempotent ? " · already imported" : ""}`,
      );
    });
  };
  $("#backfill").onclick = (e) =>
    action(e.currentTarget, async () => {
      const r = await api("/demo/backfill", "POST", {});
      await refresh();
      toast(
        r.idempotent
          ? "Backfill already applied."
          : "Missing month recovered and recorded.",
      );
    });
  $("#reimport").onclick = () => $("#seed-button").click();
}
async function renderIntegrations() {
  const events = await api("/events?limit=6");
  $("#content").innerHTML = `<div class="detail-grid">${panel(
    "One API. A traceable workflow.",
    "Import data, compare results and export analysis.",
    `<div class="panel-body">${[
      ["POST", "/api/v1/ingest", "Canonical CSV"],
      ["POST", "/api/v1/references", "External metrics"],
      ["POST", "/api/v1/pools/{id}/analyze", "Valuation scenario"],
      ["POST", "/api/v1/pools/{id}/reconcile", "Break classification"],
      ["GET", "/api/v1/events?after={cursor}", "Incremental event log"],
      ["GET", "/api/v1/export/{id}", "Point-in-time CSV"],
    ]
      .map(
        ([method, path, description]) =>
          `<div class="endpoint"><b>${method}</b><code>${esc(path)}</code><small>${description}</small></div>`,
      )
      .join(
        "",
      )}<div class="inline-actions" style="margin-top:20px"><a class="button primary" href="/docs" target="_blank" rel="noopener">Open API reference</a><a class="button secondary" href="/openapi.json" target="_blank" rel="noopener">OpenAPI JSON</a></div></div>`,
  )}${panel(
    "Connector status",
    "Available imports and external connections",
    table(
      ["Source", "Status"],
      [
        ["Canonical CSV / JSON", "Available", ""],
        ["Freddie SFLLD tape", "File import · sample tested", ""],
        ["Event export", "Available via API", ""],
        ["PolyPaths", "Not connected", "amber"],
        ["Bloomberg / Intex", "Not connected", "amber"],
        ["Agency MBS disclosures", "Not available", "gray"],
      ].map(
        ([source, status, color]) =>
          `<tr><td>${source}</td><td>${pill(status, color)}</td></tr>`,
      ),
    ),
  )}</div>${panel("Latest integration event", "Details of the most recent recorded operation.", `<div class="panel-body"><pre><code>${esc(JSON.stringify(events.events.at(-1) || { events: [] }, null, 2))}</code></pre><p class="section-subtitle">Events are available for external systems to retrieve. Automatic delivery is not configured.</p></div>`)}`;
}
$("#navigation")
  .querySelectorAll("button")
  .forEach((b) => (b.onclick = () => navigate(b.dataset.view)));
$("#refresh").onclick = (e) => action(e.currentTarget, () => refresh());
$("#seed-button").onclick = (e) =>
  action(e.currentTarget, async () => {
    const r = await api("/demo/seed", "POST", {});
    await refresh();
    toast(
      r.idempotent
        ? "Demo already loaded. No duplicate records added."
        : `Demo loaded: ${r.accepted} accepted · ${r.rejected} quarantined.`,
    );
  });
$("#reconcile-all").onclick = (e) =>
  action(e.currentTarget, async () => {
    if (!state.overview?.pools.length)
      throw Error("Load or import data first.");
    for (const p of state.overview.pools)
      await api(
        "/pools/" + encodeURIComponent(p.pool_id) + "/reconcile",
        "POST",
        state.scenario,
      );
    await refresh();
    toast("All pools compared. Evidence recorded in the exception queue.");
  });
$("#close-dialog").onclick = () => $("#break-dialog").close();
$("#break-form").onsubmit = (e) => {
  e.preventDefault();
  action(e.submitter, async () => {
    await api("/breaks/" + currentBreak.id, "PATCH", {
      owner: $("#break-owner").value,
      status: $("#break-status").value,
      note: $("#break-note").value,
    });
    $("#break-dialog").close();
    await refresh();
    toast("Review saved to the audit trail.");
  });
};
if (document.modelContext?.registerTool) {
  Promise.resolve(
    document.modelContext.registerTool({
      name: "pooltrace_read_workspace",
      description:
        "Read the current local pools, quality findings and reconciliation breaks.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
      annotations: { readOnlyHint: true, untrustedContentHint: true },
      async execute(input) {
        if (!input || Object.keys(input).length)
          throw Error("This tool takes an empty object.");
        await refresh(false);
        return {
          pools: state.overview.pools,
          breaks: state.overview.breaks,
          gaps: state.overview.gaps,
        };
      },
    }),
  ).catch(() => {});
}
async function appendFreddiePanel() {
  const data = await api("/freddie/performance?limit=8");
  const html = panel(
    "Freddie Mac performance adapter",
    "User-supplied SFLLD tape · Credit history, separate from MBS cashflows",
    `<form id="freddie-form" class="panel-body"><div class="controls"><label>Release<select name="release"><option value="r47">R47 · July 2026 · 35 fields</option><option value="pre-r47">Before R47 · 32 fields</option></select></label><label class="control-grow">Pipe-delimited file<input id="freddie-file" type="file" accept=".txt,.csv" required></label><button class="button primary" type="submit">Import performance tape</button></div><p class="section-subtitle">${data.count} current performance observations. Reported balances and exit codes are preserved. Pool membership and voluntary prepayment must come from a separate source.</p></form>${table(
      ["Loan", "Month", "Actual UPB", "Rate (%)", "Exit interpretation"],
      data.rows.map(
        (r) =>
          `<tr><td>${esc(r.loan_id)}</td><td>${esc(r.period)}</td><td class="numeric">${r.payload.current_actual_upb == null ? "Unknown" : money(r.payload.current_actual_upb)}</td><td>${r.payload.current_rate_pct == null ? "Unknown" : num(r.payload.current_rate_pct)}</td><td>${esc(r.payload.exit_label.replaceAll("_", " "))}</td></tr>`,
      ),
    )}`,
  );
  $("#content").insertAdjacentHTML("beforeend", html);
  $("#freddie-form").onsubmit = (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    action(e.submitter, async () => {
      const file = $("#freddie-file").files[0];
      if (file.size > 2e6) throw Error("Maximum tape size is 2 MB.");
      const result = await api("/freddie/performance", "POST", {
        text: await file.text(),
        release: form.elements.release.value,
        source: "freddie-sfll",
      });
      await refresh();
      toast(
        `${result.accepted} accepted · ${result.rejected} held for review.`,
      );
    });
  };
}
function appendBreakTrend() {
  const runs = (state.overview.reconciliation_runs || [])
    .slice()
    .reverse()
    .map((r, i) => ({
      month: i + 1,
      exceptions: r.payload.exceptions ?? r.payload.outside_tolerance ?? 0,
    }));
  if (runs.length)
    $("#content").insertAdjacentHTML(
      "beforeend",
      panel(
        "Exception trend",
        "Exceptions per completed pool comparison · chronological runs",
        `<div class="panel-body">${chart(runs, ["exceptions"], ["#c4944d"], 1000, 200)}</div>`,
      ),
    );
}
action(null, () => refresh());
