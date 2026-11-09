(async () => {
  const { h, fmt } = Kit;
  const me = await Kit.boot({ admin: true });
  if (!me) return;
  const { page, right } = Kit.shell({ active: "perf", title: "Observability", subtitle: "Health, delivery, drift and dashboards for the whole platform" });

  const S = { tab: 0, win: "1h", live: true, evalTimer: null, dash: null, design: null, sig: {} };
  const view = h("div");
  const live = h("span", { class: "livechip" }, h("i", { class: "dot live-dot" }), "Live");
  const liveSw = h("button", { class: "switch", role: "switch", "aria-checked": "true", "aria-label": "Auto refresh", onclick: () => { S.live = !S.live; liveSw.setAttribute("aria-checked", String(S.live)); live.style.opacity = S.live ? 1 : 0.35; } });
  right.prepend(live, liveSw);
  const winTabs = Kit.tabs(["1h", "24h", "7d"], (i, w) => { S.win = w; if (S.tab === 1) { view.replaceChildren(); refresh(); } });
  const TABS = ["Platform", "LLM", "Delivery", "Drift", "Dashboards", "Evaluations", "Traces"];
  const tabsEl = Kit.tabs(TABS, (i) => { S.tab = i; clearTimeout(S.evalTimer); view.replaceChildren(); winTabs.style.display = i === 1 ? "" : "none"; refresh(); });
  winTabs.style.display = "none"; // the 1h / 24h / 7d switch only applies to the LLM tab
  page.append(h("div", { class: "toolbar" }, tabsEl, winTabs), view);

  const card = (title, body, cls = "") => h("div", { class: `panel panel-pad in in-rise ${cls}` }, title ? h("h2", { class: "section" }, title) : null, body);
  const emptyState = (msg, icon = "gauge") => h("div", { class: "empty" }, h("div", { html: Kit.icon(icon) }), h("span", null, msg));
  const modelLabel = (id) => (Kit.config.models.find((m) => m.id === id) || {}).label || id;
  const th = (cols) => h("thead", null, h("tr", null, ...cols.map((c) => h("th", null, c))));
  const hhmm = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const agoTs = (t) => Kit.fmt.ago(new Date(t * 1000).toISOString());

  const fv = (unit, v) => {
    if (v == null) return "–";
    if (unit === "%") return v.toFixed(v < 10 ? 1 : 0) + "%";
    if (unit === "ms") return fmt.ms(v);
    if (unit === "USD") return fmt.usd(v);
    if (unit === "ratio") return fmt.pct(v);
    if (unit === "s") return v >= 60 ? (v / 60).toFixed(1) + " min" : v.toFixed(1) + " s";
    if (unit === "MB") return fmt.n(v, v < 100 ? 1 : 0) + " MB";
    if (unit === "req/s") return fmt.n(v, 2) + " /s";
    return fmt.n(v, Math.abs(v) < 10 && v % 1 ? 2 : 0) + (unit ? " " + unit : "");
  };
  const scalar = (r) => (r.value && typeof r.value === "object" ? Object.values(r.value).reduce((a, b) => a + (b || 0), 0) : r.value);
  const tone = (w, r) => {
    const v = scalar(r);
    if (v == null) return "";
    const dir = r.good === "high" ? -1 : 1;
    if (w.crit != null && dir * (v - w.crit) >= 0) return "bad";
    if (w.warn != null && dir * (v - w.warn) >= 0) return "warn";
    return "ok";
  };

  // ======================================================================= widgets (shared by every dashboard)
  function gauge(w, r) {
    const v = scalar(r) ?? 0, max = w.max ?? (r.unit === "%" ? 100 : r.unit === "ratio" ? 1 : (w.crit || v * 1.5 || 1) * 1.25), f = Math.max(0, Math.min(1, v / max)), t = tone(w, r), L = 157;
    const col = { ok: "var(--ok)", warn: "var(--warn)", bad: "var(--bad)" }[t] || "var(--a2)";
    const g = h("div", { class: "gauge2", html: `<svg viewBox="0 0 120 70"><path d="M10 62 A50 50 0 0 1 110 62" fill="none" stroke="var(--surface-2)" stroke-width="11" stroke-linecap="round"/><path class="arc" d="M10 62 A50 50 0 0 1 110 62" fill="none" stroke="${col}" stroke-width="11" stroke-linecap="round" stroke-dasharray="${L}" stroke-dashoffset="${L}"/></svg><b style="color:${col}">${fv(r.unit, scalar(r))}</b>` });
    requestAnimationFrame(() => requestAnimationFrame(() => { const a = g.querySelector(".arc"); if (a) a.style.strokeDashoffset = L * (1 - f); }));
    return g;
  }
  function seriesOf(results) {
    const out = [];
    results.forEach((r) => r.series.forEach((s) => out.push({ name: results.length > 1 ? `${r.label}${s.name && s.name !== "all services" && s.name !== "all" ? " · " + s.name : ""}` : s.name, pts: s.points })));
    return out;
  }
  function widget(w, results, platform) {
    const body = h("div", { class: "wbody" });
    const r = results[0];
    if (w.type === "status") {
      const sv = (platform && platform.services) || {};
      body.append(h("div", { class: "svc-list" }, ...Object.entries(sv).map(([id, s]) => h("div", { class: "svc-row" }, h("i", { class: `dot ${s.up ? "live-dot" : ""}`, style: { color: s.up === false ? "var(--bad)" : s.up ? "var(--ok)" : "var(--faint)" } }), h("span", null, s.label || id), h("span", { class: "muted mono" }, s.up ? `${Math.round(s.health_ms || 0)} ms` : s.up === false ? "down" : "…")))));
    } else if (!r) {
      body.append(emptyState("No query"));
    } else if (w.type === "stat") {
      const t = tone(w, r);
      body.append(h("div", { class: `bigval ${t}` }, fv(r.unit, scalar(r))), r.series[0] && r.series[0].points.length > 1 ? h("div", { class: "spk" }, Kit.charts.spark(r.series[0].points.map((p) => p[1]), { w: 140, h: 34, color: t === "bad" ? "var(--bad)" : t === "warn" ? "var(--warn)" : "var(--a2)" })) : null, h("div", { class: "muted wsub" }, `${r.agg} · last ${r.window}`));
    } else if (w.type === "gauge") {
      body.append(gauge(w, r), h("div", { class: "muted wsub", style: { textAlign: "center" } }, `${r.agg} · last ${r.window}`));
    } else if (w.type === "timeseries") {
      const ss = seriesOf(results).filter((s) => s.pts.length);
      if (!ss.length) body.append(emptyState("No data in this window yet"));
      else {
        const base = ss.reduce((a, b) => (b.pts.length > a.pts.length ? b : a)).pts, labels = base.map((p) => hhmm(p[0]));
        const align = (s) => { const m = new Map(s.pts.map((p) => [Math.round(p[0]), p[1]])); let last = 0; return base.map((p) => { const v = m.get(Math.round(p[0])); if (v != null) last = v; return v ?? last; }); };
        body.append(Kit.charts.line(labels, ss.map((s) => ({ name: s.name, values: align(s) })), { height: 150, area: ss.length === 1 }));
      }
    } else if (w.type === "bar") {
      const entries = r.value && typeof r.value === "object" ? Object.entries(r.value) : r.series.map((s) => [s.name, s.points.length ? s.points[s.points.length - 1][1] : 0]);
      if (!entries.length) body.append(emptyState("No data in this window yet"));
      else body.append(Kit.charts.bar(entries.map((e) => e[0]), [{ name: r.label, values: entries.map((e) => e[1] || 0) }], { height: 150 }), h("div", { class: "muted wsub" }, `${r.label} (${r.unit}) · ${r.agg} · last ${r.window}`));
    } else if (w.type === "table") {
      const rows = new Map();
      results.forEach((res, ci) => { const v = res.value && typeof res.value === "object" ? res.value : { all: res.value }; Object.entries(v).forEach(([k, x]) => { if (!rows.has(k)) rows.set(k, {}); rows.get(k)[ci] = fv(res.unit, x); }); });
      body.append(h("div", { class: "tblwrap" }, h("table", { class: "tbl" }, th(["", ...results.map((x) => x.label)]), h("tbody", null, ...[...rows].map(([k, c]) => h("tr", null, h("td", null, k), ...results.map((_, ci) => h("td", { class: "mono" }, c[ci] || "–"))))))));
    }
    const t = r && (w.warn != null || w.crit != null) ? tone(w, r) : "";
    return h("div", { class: `panel wcard in in-rise w${w.width || 2}`, title: w.note || "" }, h("div", { class: "wt" }, w.title, t ? h("i", { class: `dot ${t}` }) : null), body);
  }
  async function renderSpec(spec) {
    const [data, platform] = await Promise.all([Kit.api("/api/dashboards/render", { method: "POST", body: { title: spec.title, description: spec.description || "", widgets: spec.widgets } }), Kit.api("/api/platform")]);
    return h("div", { class: "wgrid" }, ...spec.widgets.map((w, i) => widget(w, data.widgets[i] || [], platform)));
  }

  // ======================================================================= Platform
  async function platform() {
    const [snap, inc, spec] = await Promise.all([Kit.api("/api/platform"), Kit.api("/api/incidents"), Kit.api("/api/dashboards/builtin-platform")]);
    const sig = JSON.stringify([inc.open.map((i) => i.id), Object.entries(snap.services).map(([k, s]) => [k, s.up])]);
    const host = snap.host;
    const hostRow = h("div", { class: "grid cols-3", style: { marginBottom: "16px" } },
      ...[["Machine CPU", host.cpu_percent, 70, 90], ["Machine memory", host.memory_percent, 80, 92], ["Disk", host.disk_percent, 80, 92]].map(([t, v, wn, cr]) => card(t, gauge({ warn: wn, crit: cr, max: 100 }, { value: v, unit: "%", good: "low" }))));
    const svcCards = h("div", { class: "grid cols-3" }, ...Object.entries(snap.services).map(([id, s]) => h("div", { class: `panel svc2 ${s.up === false ? "down" : ""}` },
      h("div", { class: "n" }, h("i", { class: `dot ${s.up ? "live-dot" : ""}`, style: { color: s.up === false ? "var(--bad)" : s.up ? "var(--ok)" : "var(--faint)" } }), s.label || id, s.availability_1h != null ? h("span", { class: "muted", style: { marginLeft: "auto", fontSize: "12px" } }, `${s.availability_1h}% up (1h)`) : null),
      s.up ? h("dl", { class: "kv" }, h("dt", null, "CPU"), h("dd", null, fv("%", s.cpu_percent)), h("dt", null, "Memory"), h("dd", null, fv("MB", s.memory_mb)), h("dt", null, "Throughput"), h("dd", null, fv("req/s", s.rps)),
        h("dt", null, "Latency p95"), h("dd", null, fv("ms", s.latency_p95_ms)), h("dt", null, "Errors"), h("dd", null, fv("ratio", s.error_rate)), h("dt", null, "Event-loop lag"), h("dd", null, fv("ms", s.loop_lag_ms)),
        h("dt", null, "Uptime"), h("dd", null, s.uptime_s != null ? fv("s", s.uptime_s) : "–")) : h("div", { class: "muted" }, s.up === false ? "Not answering its health check." : "Waiting for the first probe…"),
      s.up && (s.top_routes || []).length ? h("div", { class: "routes" }, ...s.top_routes.slice(0, 3).map((r) => h("div", null, h("span", { class: "mono" }, r.route), h("span", { class: "muted" }, ` ${r.count} · ${fv("ms", r.avg_ms)}`)))) : null)));
    const incPanel = h("div", { class: "grid", style: { marginBottom: "16px" } },
      inc.open.length ? card(`Incidents (${inc.open.length})`, h("div", { class: "incs" }, ...inc.open.map((i) => h("div", { class: `inc ${i.severity} ${i.needs_user ? "needs" : ""}` },
        h("div", { class: "it" }, h("span", { class: `badge ${i.severity === "critical" ? "bad" : "warn"}` }, i.severity), h("b", null, i.title), i.needs_user ? h("span", { class: "badge warn" }, "needs you") : null, h("span", { class: "muted", style: { marginLeft: "auto", fontSize: "12px" } }, agoTs(i.opened_at))),
        i.detail ? h("div", { class: "muted", style: { fontSize: "13px" } }, i.detail) : null, i.how_to_fix ? h("div", { class: "fixit" }, `${i.needs_user ? "What to do: " : "Hint: "}${i.how_to_fix}`) : null))))
        : card("", h("div", { class: "allgood", html: Kit.checkIcon(34) + "<span>All clear. No open incidents.</span>" })));
    const widgets = { title: spec.title, widgets: spec.widgets.filter((w) => w.type !== "gauge" && w.type !== "status") };
    const fresh = await renderSpec(widgets);
    if (S.sig.plat !== sig || !view.querySelector("#plat")) {
      S.sig.plat = sig;
      view.replaceChildren(h("div", { id: "plat" }, incPanel, hostRow, svcCards, h("div", { style: { height: "16px" } }), fresh));
    } else {
      view.querySelector(".wgrid").replaceWith(fresh);
      const cur = view.querySelectorAll(".svc2"), nxt = svcCards.querySelectorAll(".svc2");
      cur.forEach((c, i) => nxt[i] && c.replaceChildren(...nxt[i].childNodes)); // numbers refresh without replaying entrance animations
    }
  }

  // ======================================================================= LLM
  const kpiNodes = {};
  function upsertKpi(host, key, label, icon, value, sub, spark) {
    let k = kpiNodes[key];
    if (!k || !host.contains(k.el)) {
      const row = Kit.odo(value), subEl = h("div", { class: "sub" }, sub), sp = h("div", { class: "sp" });
      const el = h("div", { class: "panel kpi in in-rise" }, h("div", { class: "l", html: Kit.icon(icon) + label }), h("div", { class: "v" }, row), subEl, sp);
      host.append(el);
      k = kpiNodes[key] = { el, row, subEl, sp, sig: "" };
    }
    Kit.setOdo(k.row, value);
    k.subEl.textContent = sub || " ";
    const sig = JSON.stringify(spark);
    if (sig !== k.sig) { k.sig = sig; k.sp.replaceChildren(Kit.charts.spark(spark)); }
  }
  async function llm() {
    const d = await Kit.api(`/api/overview?window=${S.win}`), t = d.totals, s = d.series;
    if (!view.querySelector("#kp")) { S.sig = {}; view.replaceChildren(h("div", { class: "kpis", id: "kp" }), h("div", { class: "grid cols-2", id: "ch" }), h("div", { id: "tb", style: { marginTop: "16px", display: "grid", gap: "16px" } })); }
    const perMin = t.requests / { "1h": 60, "24h": 1440, "7d": 10080 }[S.win], kp = view.querySelector("#kp");
    upsertKpi(kp, "req", "Requests", "zap", fmt.n(t.requests), `${fmt.n(perMin, 2)} / min`, s.map((x) => x.requests));
    upsertKpi(kp, "p95", "p95 latency", "gauge", fmt.ms(t.p95_ms), `p50 ${fmt.ms(t.p50_ms)} · p99 ${fmt.ms(t.p99_ms)}`, s.map((x) => x.p95_ms));
    upsertKpi(kp, "err", "Error rate", "shield", fmt.pct(t.error_rate), `${fmt.n(t.errors)} failed calls`, s.map((x) => x.errors));
    upsertKpi(kp, "tok", "Tokens", "file", fmt.n(t.input_tokens + t.output_tokens), `${fmt.n(t.input_tokens)} in · ${fmt.n(t.output_tokens)} out`, s.map((x) => x.input_tokens + x.output_tokens));
    upsertKpi(kp, "usd", "Spend", "spark", fmt.usd(t.cost_usd), t.requests ? `${fmt.usd(t.cost_usd / t.requests)} per call` : "no calls yet", s.map((x) => x.cost_usd));
    const labels = s.map((x) => x.label), chSig = JSON.stringify([S.win, labels, s.map((x) => [x.requests, x.errors, x.p95_ms])]);
    if (S.sig.ch !== chSig) {
      S.sig.ch = chSig;
      view.querySelector("#ch").replaceChildren(
        card("Requests over time", Kit.charts.bar(labels, [{ name: "Requests", values: s.map((x) => x.requests) }, { name: "Errors", values: s.map((x) => x.errors) }])),
        card("p95 latency (ms)", Kit.charts.line(labels, [{ name: "p95", values: s.map((x) => x.p95_ms) }])));
    }
    const tbSig = JSON.stringify([d.agents, d.models, d.recent.map((r) => r.id || r.created_at)]);
    if (S.sig.tb === tbSig) return;
    S.sig.tb = tbSig;
    const models = Object.entries(d.models), agents = Object.entries(d.agents), maxReq = Math.max(1, ...agents.map(([, g]) => g.requests));
    view.querySelector("#tb").replaceChildren(
      h("div", { class: "grid cols-3" }, ...models.map(([m, g]) => card(modelLabel(m), h("dl", { class: "kv" }, h("dt", null, "Requests"), h("dd", null, fmt.n(g.requests)), h("dt", null, "p50 / p95"), h("dd", null, `${fmt.ms(g.p50_ms)} / ${fmt.ms(g.p95_ms)}`), h("dt", null, "Error rate"), h("dd", null, fmt.pct(g.error_rate)), h("dt", null, "Tokens"), h("dd", null, fmt.n(g.input_tokens + g.output_tokens)), h("dt", null, "Spend"), h("dd", null, fmt.usd(g.cost_usd)), h("dt", null, "Cost / 1k calls"), h("dd", null, g.requests ? fmt.usd((g.cost_usd / g.requests) * 1000) : "–"))))),
      h("div", { class: "grid cols-2" },
        card("By agent", agents.length ? h("div", null, ...agents.map(([a, g]) => h("div", { class: "bar-row" }, h("span", null, a), h("div", { class: "track" }, h("div", { class: "fill", style: { width: (g.requests / maxReq) * 100 + "%" } })), h("span", { class: "mono muted" }, `${g.requests} · ${fmt.ms(g.p95_ms)}`)))) : emptyState("No calls in this window yet.")),
        card("Recent calls", h("div", { class: "tblwrap" }, h("table", { class: "tbl" }, th(["When", "Agent", "Model", "Status", "Latency", "Cost"]), h("tbody", null, ...d.recent.slice(0, 10).map((r) => h("tr", null, h("td", null, fmt.ago(r.created_at)), h("td", null, r.agent), h("td", null, modelLabel(r.model)), h("td", null, h("span", { class: `badge ${r.status === "ok" ? "ok" : "bad"}` }, r.status)), h("td", { class: "mono" }, fmt.ms(r.latency_ms)), h("td", { class: "mono" }, fmt.usd(r.cost_usd))))))))));
  }

  // ======================================================================= Delivery (CI/CD monitoring + auto-heal)
  async function delivery() {
    const d = await Kit.api("/api/delivery"), s = d.stats;
    const ACT = { auto_rerun: ["info", "Auto-retry"], healed: ["ok", "Healed"], needs_human: ["warn", "Needs you"] };
    view.replaceChildren(
      d.error ? card("", h("div", { class: "muted" }, `Cannot reach the CI/CD agent right now (${d.error}).`)) : h("span"),
      h("div", { class: "grid cols-4", style: { marginBottom: "16px" } },
        card("Success rate", h("div", { class: "bigval" }, s.success_rate == null ? "–" : fmt.pct(s.success_rate, 0))), card("Finished runs", h("div", { class: "bigval" }, fmt.n(s.finished))),
        card("Auto-heal retries", h("div", { class: "bigval" }, fmt.n(s.auto_heals), s.healed ? h("small", { class: "muted" }, ` ${s.healed} healed`) : null)), card("Waiting on you", h("div", { class: `bigval ${s.needs_human ? "warn" : ""}` }, fmt.n(s.needs_human)))),
      h("div", { class: "grid cols-2" },
        card("How auto-heal works", h("div", { class: "policy" }, h("p", null, h("b", null, "Retried automatically: "), d.policy.auto, `, at most ${d.policy.max_auto_heals} times with a short back-off.`), h("p", null, h("b", null, "Never automatic: "), d.policy.never_auto, ". These become an incident that tells you exactly what to do."), h("p", { class: "muted", style: { fontSize: "13px" } }, "The team never edits code or infrastructure on its own."))),
        card("Auto-heal log", d.heal_log.length ? h("div", { class: "timeline" }, ...d.heal_log.map((x) => h("div", { class: "tl" }, h("span", { class: `badge ${ACT[x.action][0]}` }, ACT[x.action][1]), h("div", null, h("b", null, x.title), h("div", { class: "muted", style: { fontSize: "12.5px" } }, `${x.reason}${x.attempt ? ` · attempt ${x.attempt}` : ""} · ${agoTs(x.t)}`))))) : emptyState("Nothing to heal yet. Failed pipelines with transient causes are retried here.", "rocket"))),
      h("div", { style: { marginTop: "16px" } }, card("Recent pipeline runs", d.runs.length ? h("div", { class: "tblwrap" }, h("table", { class: "tbl" }, th(["Run", "Status", "Cause", "Auto retries", "Stages"]), h("tbody", null, ...d.runs.slice(0, 12).map((r) => h("tr", null, h("td", null, r.title), h("td", null, h("span", { class: `badge ${r.status === "succeeded" ? "ok" : r.status === "failed" ? "bad" : "info"}` }, r.status)), h("td", null, r.kind || "–"), h("td", { class: "mono" }, r.heal_attempts), h("td", { class: "muted" }, r.stages.map((x) => `${x.id}:${x.status}`).join("  "))))))) : emptyState("No pipeline runs yet.", "rocket"))));
  }

  // ======================================================================= Drift
  async function drift() {
    const d = await Kit.api("/api/drift");
    const check = h("button", { class: "btn btn-primary btn-sm", html: Kit.icon("refresh") + " Check now" });
    check.onclick = async () => { check.disabled = true; try { await Kit.api("/api/drift/check", { method: "POST" }); } catch (e) { Kit.toast(e.message, { kind: "bad" }); } check.disabled = false; refresh(); };
    const ST = { in_sync: ["ok", "In sync"], drift: ["warn", "Drifted"], cannot_check: ["bad", "Cannot check"], unchecked: ["info", "Not checked yet"] };
    const stacks = d.stacks || [];
    const remediate = (s) => {
      const ok = h("input", { type: "checkbox", id: "okd" });
      const go = h("button", { class: "btn btn-primary", disabled: true }, "Put it back in line");
      ok.onchange = () => (go.disabled = !ok.checked);
      go.onclick = async () => { go.disabled = true; try { await Kit.api(`/api/drift/${s.id}/remediate`, { method: "POST" }); m.remove(); Kit.toast("Infrastructure matches its code again.", { kind: "ok" }); refresh(); } catch (e) { Kit.toast(e.message, { kind: "bad" }); go.disabled = false; } };
      const m = h("div", { class: "modal", role: "dialog", "aria-modal": "true" }, h("div", { class: "panel modal-card panel-pad" }, h("h2", { style: { margin: "0 0 8px" } }, `Put ${s.title} back in line?`), h("p", { class: "muted" }, "This runs terraform apply with the stack's code, changing the real cloud resources listed below. It can cost money or remove manual changes."),
        h("ul", null, ...s.findings.map((f) => h("li", null, h("span", { class: "mono" }, f.resource), ` ${f.summary}`))), h("label", { class: "check", for: "okd", style: { cursor: "pointer" } }, ok, h("span", null, "I have reviewed the differences and approve this change")),
        h("div", { style: { display: "flex", gap: "10px", justifyContent: "flex-end", marginTop: "16px" } }, h("button", { class: "btn", onclick: () => m.remove() }, "Cancel"), go)));
      document.body.append(m);
    };
    view.replaceChildren(h("div", { class: "toolbar" }, h("span", { class: "muted" }, d.error ? `⚠ ${d.error}` : d.checked_at ? `Last checked ${agoTs(d.checked_at)}. Stacks are re-checked about every 5 minutes.` : "Waiting for the first check…"), h("span", { style: { marginLeft: "auto" } }, check)),
      stacks.length ? h("div", { class: "grid cols-2" }, ...stacks.map((s) => card("", h("div", null, h("div", { style: { display: "flex", gap: "10px", alignItems: "center", marginBottom: "6px" } }, h("b", null, s.title), h("span", { class: `badge ${ST[s.status][0]}`, style: { marginLeft: "auto" } }, ST[s.status][1])),
        h("div", { class: "muted", style: { fontSize: "13px" } }, `${s.cloud || "cloud"} · ${s.region || ""} · ${s.resources || 0} resource types · applied ${agoTs(s.applied_at)}`),
        s.status === "cannot_check" ? h("div", { class: "fixit", style: { marginTop: "10px" } }, h("b", null, "Needs you: "), s.error, h("div", null, h("b", null, "What to do: "), s.how_to_fix || "")) : null,
        s.findings.length ? h("div", { style: { marginTop: "10px" } }, ...s.findings.map((f) => h("div", { class: "find2" }, h("span", { class: `badge ${f.risk_score >= 70 ? "bad" : "warn"}` }, `risk ${f.risk_score}`), h("div", null, h("span", { class: "mono" }, f.resource), h("div", { class: "muted", style: { fontSize: "12.5px" } }, f.summary))))) : null,
        s.status === "drift" ? h("div", { style: { marginTop: "12px" } }, h("button", { class: "btn btn-sm btn-primary", onclick: () => remediate(s) }, "Put it back in line…")) : null)))) : card("", emptyState("No applied stacks yet. Once the Infrastructure agent applies a design, it appears here and is checked for drift automatically.", "cloud")));
  }

  // ======================================================================= Dashboards (built-in, custom, AI designer)
  async function dashboards() {
    const list = await Kit.api("/api/dashboards");
    const sel = S.dash === "__design__" || (S.dash && list.find((x) => x.id === S.dash)) ? S.dash : list[0].id;
    S.dash = sel;
    const stage = h("div");
    const side = h("div", { class: "dlist" }, ...list.map((x) => h("button", { class: `dbtn ${x.id === sel ? "on" : ""}`, onclick: () => { S.dash = x.id; S.design = null; refresh(); } }, h("b", null, x.title), h("small", null, `${x.builtin ? "Built-in" : "Custom"} · ${x.widgets} widgets`))),
      h("button", { class: "btn btn-primary", style: { marginTop: "10px" }, onclick: () => { S.dash = "__design__"; S.design = { msgs: [], current: null, busy: false }; refresh(); }, html: Kit.icon("spark") + " Design with AI" }));
    view.replaceChildren(h("div", { class: "dash-layout" }, side, stage));
    if (S.dash === "__design__") { S.design = S.design || { msgs: [], current: null, busy: false }; return designer(stage); }
    const spec = await Kit.api(`/api/dashboards/${S.dash}`);
    const actions = h("div", { class: "actions-row" }, spec.builtin ? h("button", { class: "btn btn-sm", onclick: async () => { const r = await Kit.api("/api/dashboards", { method: "POST", body: { title: `${spec.title} (copy)`, description: spec.description, widgets: spec.widgets } }); S.dash = r.id; Kit.toast("Saved a copy you can customise with AI.", { kind: "ok" }); refresh(); } }, "Save a copy")
      : h("button", { class: "btn btn-sm btn-danger", onclick: async () => { if (confirm(`Delete "${spec.title}"?`)) { await Kit.api(`/api/dashboards/${spec.id}`, { method: "DELETE" }); S.dash = null; refresh(); } } }, "Delete"),
      !spec.builtin ? h("button", { class: "btn btn-sm", onclick: () => { S.dash = "__design__"; S.design = { msgs: [{ role: "user", content: `I want to change the dashboard "${spec.title}"` }], current: spec, busy: false, edit: spec.id }; refresh(); } }, "Edit with AI") : null);
    stage.append(h("div", { class: "toolbar" }, h("div", null, h("h2", { style: { margin: 0 } }, spec.title), h("div", { class: "muted", style: { fontSize: "13px" } }, spec.description || "")), h("span", { style: { marginLeft: "auto" } }, actions)), h("div", { id: "wholder" }));
    S.dashSpec = spec;
    await paintDash();
  }
  async function paintDash() {
    const holder = view.querySelector("#wholder");
    if (!holder || !S.dashSpec) return;
    try {
      const fresh = await renderSpec(S.dashSpec);
      if (!holder.firstChild) holder.append(fresh); else holder.replaceChildren(fresh);
    } catch (e) { holder.replaceChildren(emptyState(e.message)); }
  }

  function designer(stage) {
    const D = S.design;
    const thread = h("div", { class: "dthread" }), prev = h("div", { class: "dprev" });
    const input = h("input", { class: "input", placeholder: "e.g. Show me how the support chat is doing: speed, errors and cost", "aria-label": "Describe the dashboard" });
    const send = h("button", { class: "btn btn-primary", type: "submit" }, "Send");
    const form = h("form", { class: "dform", onsubmit: (e) => { e.preventDefault(); say(input.value.trim()); } }, input, send);
    const paint = () => {
      thread.replaceChildren(...D.msgs.map((m, i) => {
        const b = h("div", { class: `dmsg ${m.role}` }, h("span", { class: "who" }, m.role === "user" ? "You" : "Dana"), h("div", null, m.content));
        if (m.questions && i === D.msgs.length - 1 && !D.busy) {
          const wrap = h("div", { class: "dq" });
          m.questions.forEach((q) => wrap.append(h("div", { class: "dqr" }, h("span", { class: "muted" }, q.text), ...q.options.map((o) => { const rec = o.includes("*"), label = o.replace(/\s*\*\s*/g, ""); return h("button", { class: `chip ${rec ? "rec" : ""}`, type: "button", onclick: () => { input.value = (input.value ? input.value + "; " : "") + `${q.text.replace(/\?+$/, "")}: ${label}`; input.focus(); } }, label); }))));
          wrap.append(h("div", { class: "muted", style: { fontSize: "12px" } }, "Click your answers, then press Send once."));
          b.append(wrap);
        }
        return b;
      }), D.busy ? h("div", { class: "muted", style: { padding: "6px" } }, Kit.dots(), " Designing…") : h("span"));
      thread.scrollTop = thread.scrollHeight;
      send.disabled = D.busy;
    };
    const say = async (text) => {
      if (!text || D.busy) return;
      input.value = "";
      D.msgs.push({ role: "user", content: text });
      D.busy = true; paint();
      try {
        const r = await Kit.api("/api/dashboards/design", { method: "POST", body: { messages: D.msgs.map((m) => ({ role: m.role, content: m.content })), current: D.current } });
        if (r.mode === "ask") D.msgs.push({ role: "assistant", content: r.message, questions: r.questions });
        else { D.msgs.push({ role: "assistant", content: r.message }); D.current = r.dashboard; await showPreview(); }
      } catch (e) { D.msgs.push({ role: "assistant", content: `Needs you: ${e.message}` }); }
      D.busy = false; paint();
    };
    const showPreview = async () => {
      prev.replaceChildren();
      if (!D.current) return;
      const save = h("button", { class: "btn btn-primary", onclick: async () => {
        try { const r = D.edit ? await Kit.api(`/api/dashboards/${D.edit}`, { method: "PUT", body: D.current }) : await Kit.api("/api/dashboards", { method: "POST", body: D.current }); Kit.toast("Dashboard saved", { kind: "ok" }); Kit.confetti(30); S.dash = r.id; S.design = null; refresh(); } catch (e) { Kit.toast(e.message, { kind: "bad" }); } } }, "Save dashboard");
      prev.append(h("div", { class: "toolbar" }, h("div", null, h("b", null, D.current.title), h("div", { class: "muted", style: { fontSize: "13px" } }, D.current.description || "Preview. Ask for changes below, or save it.")), h("span", { style: { marginLeft: "auto", display: "flex", gap: "8px" } }, save)), await renderSpec(D.current));
    };
    stage.append(h("div", { class: "panel panel-pad" }, h("h2", { class: "section" }, "Design a dashboard"), h("p", { class: "muted", style: { marginTop: 0 } }, "Describe what you want to see. If I need anything to get it right, I will ask all my questions at once."), thread, form), prev);
    paint();
    if (D.current) showPreview();
  }

  // ======================================================================= Evaluations
  async function evaluations() {
    const [suites, hist] = await Promise.all([Kit.api("/api/evals/suites"), Kit.api("/api/evals/history")]);
    const suiteSel = h("select", { class: "select", "aria-label": "Suite", style: { width: "auto" } }, ...suites.map((s) => h("option", { value: s.id }, `${s.id.replace(/_/g, " ")} (${s.cases.length} cases)`)));
    const checks = Kit.config.models.map((m) => h("label", { class: "chip" }, h("input", { type: "checkbox", checked: true, value: m.alias }), m.label));
    const out = h("div", { style: { marginTop: "16px", display: "grid", gap: "16px" } });
    const run = h("button", { class: "btn btn-primary", html: Kit.icon("play") + " Run evaluation" });
    run.onclick = async () => {
      const mods = checks.map((l) => l.firstChild).filter((c) => c.checked).map((c) => c.value);
      if (!mods.length) return Kit.toast("Pick at least one model", { kind: "bad" });
      run.disabled = true;
      try { const { run_id } = await Kit.api("/api/evals/run", { method: "POST", body: { suite: suiteSel.value, models: mods } }); poll(run_id); } catch (e) { Kit.toast(e.message, { kind: "bad" }); run.disabled = false; }
    };
    const poll = async (id) => { const r = await Kit.api(`/api/evals/runs/${id}`); showRun(r); if (r.status === "running") S.evalTimer = setTimeout(() => poll(id), 1500); else { run.disabled = false; Kit.toast("Evaluation finished", { kind: "ok" }); } };
    const showRun = (r) => {
      const summary = Object.entries(r.models || {}).map(([m, g]) => h("div", { class: "panel kpi" }, h("div", { class: "l" }, modelLabel(m)), h("div", { class: "v" }, Kit.odo(Math.round(g.pass_rate * 100) + "%")), h("div", { class: "sub" }, `pass rate · score ${g.avg_score} · ${fmt.ms(g.avg_latency_ms)} avg`)));
      out.replaceChildren(card(`${r.suite.replace(/_/g, " ")} · ${r.status}`, h("div", null, h("div", { class: "progress" }, h("i", { style: { width: (r.done / r.total) * 100 + "%" } })), h("div", { class: "muted" }, `${r.done} of ${r.total} graded`))), h("div", { class: "kpis", style: { margin: 0 } }, ...summary),
        card("Cases", h("div", { class: "tblwrap" }, h("table", { class: "tbl" }, th(["Case", "Model", "Result", "Score", "Latency", "Judge says"]), h("tbody", null, ...r.results.map((x) => h("tr", null, h("td", null, x.case_id), h("td", null, modelLabel(x.model)), h("td", null, h("span", { class: `badge ${x.passed ? "ok" : "bad"}` }, x.passed ? "pass" : "fail")), h("td", { class: "mono" }, x.score), h("td", { class: "mono" }, fmt.ms(x.latency_ms)), h("td", { class: "reason" }, (x.detail && ((x.detail.judge && x.detail.judge.reason) || x.detail.error)) || ""))))))));
    };
    view.replaceChildren(card("Run a suite", h("div", null, h("p", { class: "muted", style: { marginTop: 0 } }, "Each case is answered by the candidate model and graded against a rubric by the other model, so a model never grades itself. A full suite costs a few cents."), h("div", { class: "toolbar", style: { marginBottom: 0 } }, suiteSel, ...checks, run))), out,
      h("div", { style: { marginTop: "16px" } }, card("History", hist.length ? h("div", { class: "tblwrap" }, h("table", { class: "tbl" }, th(["When", "Suite", "Model", "Pass rate", "Avg score"]), h("tbody", null, ...hist.flatMap((g) => Object.entries(g.models).map(([m, v]) => h("tr", null, h("td", null, fmt.ago(g.created_at)), h("td", null, g.suite), h("td", null, modelLabel(m)), h("td", null, fmt.pct(v.pass_rate, 0)), h("td", { class: "mono" }, v.avg_score))))))) : emptyState("No evaluation runs yet."))));
  }

  // ======================================================================= Traces
  async function traces() {
    view.replaceChildren(card("LangSmith", h("div", null, h("div", { class: "skeleton", style: { height: "18px", marginBottom: "10px" } }), h("div", { class: "skeleton", style: { height: "18px", marginBottom: "10px" } }), h("div", { class: "skeleton", style: { height: "18px" } }))));
    const [d, lt] = await Promise.all([Kit.api("/api/langsmith?limit=25"), Kit.api("/api/loadtests")]);
    view.replaceChildren(card(`LangSmith · ${d.project || ""}`, d.error ? emptyState(d.error) : !d.enabled ? emptyState("LangSmith isn't configured.") : d.runs.length ? h("div", { class: "tblwrap" }, h("table", { class: "tbl" }, th(["Started", "Run", "Status", "Latency", "Tokens", "Tags"]), h("tbody", null, ...d.runs.map((r) => h("tr", null, h("td", null, r.start ? fmt.ago(r.start) : "–"), h("td", null, r.name), h("td", null, h("span", { class: `badge ${r.status === "success" ? "ok" : r.error ? "bad" : "info"}` }, r.status)), h("td", { class: "mono" }, fmt.ms(r.latency_ms)), h("td", { class: "mono" }, fmt.n(r.tokens)), h("td", null, (r.tags || []).join(", "))))))) : emptyState("No traces yet.")),
      lt.length ? h("div", { style: { marginTop: "16px" } }, card("Load test reports", h("div", { class: "grid cols-2" }, ...lt.map((r) => h("div", { class: "panel panel-pad" }, h("b", null, r.name), h("div", { class: "muted" }, r.when), h("dl", { class: "kv", style: { marginTop: "8px" } }, ...Object.entries(r.summary).flatMap(([k, v]) => [h("dt", null, k), h("dd", null, String(v))]))))))) : h("span"));
  }

  const pages = [platform, llm, delivery, drift, dashboards, evaluations, traces];
  async function refresh() {
    try { await pages[S.tab](); } catch (e) { view.replaceChildren(h("div", { class: "panel empty" }, h("b", null, "Couldn't load data"), h("span", null, e.message))); }
  }
  // live refresh: only tabs that watch changing numbers, and never while the designer is open
  setInterval(() => {
    if (!S.live || document.hidden) return;
    if (S.tab <= 3) refresh();
    else if (S.tab === 4 && S.dash && S.dash !== "__design__") paintDash();
  }, 6000);
  refresh();
})();
