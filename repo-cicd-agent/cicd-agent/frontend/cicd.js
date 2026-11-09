(async () => {
  const { h, fmt } = Kit;
  const me = await Kit.boot({ admin: true });
  if (!me) return;
  const { page, right } = Kit.shell({ active: "cicd", title: "CI/CD", subtitle: "Review, approve the summary, then ship" });

  const S = { id: null, run: null, timer: null, model: "primary", samples: [], override: false };
  const modelSel = h("select", { class: "select", "aria-label": "Model", onchange: (e) => (S.model = e.target.value) }, ...Kit.config.models.map((m) => h("option", { value: m.alias }, m.label)));
  right.prepend(modelSel);

  const list = h("div", { class: "list" });
  const side = h("aside", { class: "side", "aria-label": "Runs" }, h("button", { class: "btn btn-primary", onclick: () => showNew(), html: Kit.icon("plus") + " New change" }), h("h2", { class: "section", style: { margin: "4px 4px 0" } }, "Recent runs"), list);
  const pane = h("div", { class: "main-pane" });
  page.append(h("div", { class: "cd" }, side, pane));

  const STATUS = { reviewing: ["info", "Reviewing"], awaiting_approval: ["warn", "Awaiting approval"], running: ["info", "Running"], succeeded: ["ok", "Succeeded"], failed: ["bad", "Failed"], rejected: ["", "Rejected"], error: ["bad", "Error"] };
  const badge = (s, run) => {
    const skipped = run && s === "succeeded" ? run.stages.filter((x) => x.status === "skipped").length : 0;
    return h("span", { class: `badge statuspill ${skipped ? "warn" : (STATUS[s] || [""])[0]}`, title: skipped ? "Some stages could not run on this machine. See the stage logs." : "" }, (STATUS[s] || [0, s])[1] + (skipped ? ` · ${skipped} skipped` : ""));
  };

  // ----- list -----
  async function loadList() {
    let rows = [];
    try { rows = await Kit.api("/api/runs"); } catch (e) { return Kit.toast(e.message, { kind: "bad" }); }
    list.replaceChildren(...(rows.length ? rows.map((r) => {
      const del = h("button", { class: "btn btn-icon del", "aria-label": "Delete run", html: Kit.icon("trash"), onclick: async (ev) => { ev.stopPropagation(); await Kit.api(`/api/runs/${r.id}`, { method: "DELETE" }); if (S.id === r.id) showNew(); loadList(); } });
      return h("div", { class: `conv ${S.id === r.id ? "active" : ""}`, tabindex: 0, onclick: () => openRun(r.id), onkeydown: (e) => e.key === "Enter" && openRun(r.id) }, h("div", { class: "ti" }, r.title, h("small", null, badge(r.status), r.created_at ? Kit.fmt.ago(new Date(r.created_at * 1000).toISOString()) : "")), del);
    }) : [h("div", { class: "empty muted" }, "No runs yet")]));
  }

  // ----- new change -----
  async function showNew() {
    clearTimeout(S.timer); S.id = null; S.run = null; Kit.mood("calm"); loadList();
    const title = h("input", { class: "input", placeholder: "Title (optional)", maxlength: 80 });
    const diff = h("textarea", { class: "input", placeholder: "Paste a unified diff here (git diff output)…" });
    const repo = h("input", { class: "input", placeholder: "Local repo path, e.g. D:\\multiagent\\repo-office" });
    const base = h("input", { class: "input", value: "HEAD~1", "aria-label": "Base ref" }), head = h("input", { class: "input", value: "HEAD", "aria-label": "Head ref" });
    const start = async (body) => { try { const r = await Kit.api("/api/runs", { method: "POST", body: { model: S.model, ...body } }); S.id = r.id; S.run = r; render(true); poll(); loadList(); } catch (e) { Kit.toast(e.message, { kind: "bad" }); } };
    const forms = [
      h("div", { class: "form" }, h("div", { class: "samples" }, ...S.samples.map((s, i) => h("button", { class: "tile in in-rise", style: { "--i": i }, onclick: () => start({ sample_id: s.id }) }, h("b", null, s.label), h("span", null, s.blurb))))),
      h("div", { class: "form" }, title, diff, h("div", null, h("button", { class: "btn btn-primary", onclick: () => diff.value.trim() ? start({ title: title.value, diff: diff.value }) : Kit.toast("Paste a diff first", { kind: "bad" }), html: Kit.icon("send") + " Review this change" }))),
      h("div", { class: "form" }, repo, h("div", { class: "row2" }, h("label", { class: "field" }, "Base", base), h("label", { class: "field" }, "Head", head)), h("div", null, h("button", { class: "btn btn-primary", onclick: () => repo.value.trim() ? start({ repo_path: repo.value.trim(), base: base.value, head: head.value, title: title.value }) : Kit.toast("Enter a repository path", { kind: "bad" }), html: Kit.icon("send") + " Review this change" }))),
    ];
    const body = h("div", null, forms[0]);
    const tabs = Kit.tabs(["Try a sample", "Paste a diff", "Local repository"], (i) => body.replaceChildren(forms[i]));
    pane.replaceChildren(h("div", { class: "wrap" }, h("div", { class: "hero" }, h("div", { class: "rocket in in-zoom", html: Kit.icon("rocket") }), h("h2", { class: "in in-blur" }, "Ship a change with ", h("span", { class: "grad-text" }, "confidence")),
      h("p", { class: "in in-rise", style: { "--i": 1 } }, "The reviewer writes a plain-language summary. You approve the summary, not the raw diff. Then tests, scans and the rollout run.")), h("div", { class: "in in-rise", style: { "--i": 2, justifySelf: "center" } }, tabs), h("div", { class: "panel panel-pad in in-rise", style: { "--i": 3 } }, body)));
  }

  // ----- run view -----
  async function openRun(id) { clearTimeout(S.timer); S.id = id; S.run = await Kit.api(`/api/runs/${id}`); render(true); loadList(); poll(); }
  function poll() {
    clearTimeout(S.timer);
    if (!S.run || !["reviewing", "running"].includes(S.run.status)) return;
    S.timer = setTimeout(async () => {
      try { const prev = S.run.status; S.run = await Kit.api(`/api/runs/${S.id}`); render(false); if (prev !== S.run.status) loadList(); } catch (_) {}
      poll();
    }, 1000);
  }

  const NODES = [["review", "Review", "Cody"], ["approve", "Approval", "You"], ["tests", "Tests", "Tess"], ["scan", "Scan", "Sasha"], ["build", "Build", "Bo"], ["deploy", "Roll out", "Rae"]];
  function nodeStates(r) {
    const st = r.status, stg = Object.fromEntries(r.stages.map((s) => [s.id, s.status]));
    const review = st === "reviewing" ? "active" : st === "error" && !r.review ? "failed" : "done";
    let approve = "todo";
    if (st === "awaiting_approval") approve = "wait"; else if (st === "rejected") approve = "failed"; else if (r.review && st !== "reviewing" && st !== "error") approve = "done";
    return [review, approve, ...["tests", "scan", "build", "deploy"].map((k) => stg[k] === "pending" ? "todo" : stg[k])];
  }
  const nodeIcon = (s, i) => s === "done" || s === "passed" ? Kit.icon("check") : s === "failed" ? Kit.icon("x") : s === "skipped" ? "–" : String(i + 1);

  function riskGauge(risk) {
    const f = { low: 0.25, medium: 0.6, high: 0.95 }[risk] || 0.3, col = { low: "var(--ok)", medium: "var(--warn)", high: "var(--bad)" }[risk];
    const L = 157;
    const g = h("div", { class: "gauge", html: `<svg viewBox="0 0 120 70"><path d="M10 62 A50 50 0 0 1 110 62" fill="none" stroke="var(--surface-2)" stroke-width="12" stroke-linecap="round"/><path class="arc" d="M10 62 A50 50 0 0 1 110 62" fill="none" stroke="${col}" stroke-width="12" stroke-linecap="round" stroke-dasharray="${L}" stroke-dashoffset="${L}"/></svg><b style="color:${col}">${risk} risk</b>` });
    requestAnimationFrame(() => requestAnimationFrame(() => { const a = g.querySelector(".arc"); if (a) a.style.strokeDashoffset = L * (1 - f); }));
    return g;
  }
  const card = (title, ...kids) => h("div", { class: "panel panel-pad in in-rise" }, title ? h("h2", { class: "section" }, title) : null, ...kids);

  function diffView(text) {
    return h("div", { class: "diff" }, ...text.split("\n").slice(0, 400).map((l) => h("div", { class: l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : "" }, l || " ")));
  }

  async function act(path, body, okMsg) {
    try { S.run = await Kit.api(`/api/runs/${S.id}/${path}`, { method: "POST", body }); if (okMsg) Kit.toast(okMsg, { kind: "ok" }); render(true); poll(); loadList(); }
    catch (e) { Kit.toast(e.message, { kind: "bad" }); }
  }

  function render(full) {
    const r = S.run;
    if (!r) return;
    const states = nodeStates(r);
    const rv = r.review;
    Kit.mood(r.status === "succeeded" ? "celebrate" : r.status === "failed" || r.status === "error" ? "urgent" : r.status === "reviewing" || r.status === "running" ? "thinking" : "calm");
    const blocks = [];
    // header + pipeline
    blocks.push(h("div", { class: "head" }, h("div", null, h("h2", null, (rv && rv.title) || r.title), h("div", { class: "muted", style: { fontSize: "13px" } }, `${r.source === "repo" ? "Repository" : "Pasted change"} · ${r.diff_lines} diff lines · ${(Kit.config.models.find((m) => m.alias === r.model) || {}).label || r.model}`)), badge(r.status, r)));
    const pipe = h("div", { class: "pipeline panel panel-pad", role: "list" });
    NODES.forEach(([id, label, who], i) => {
      const s = states[i];
      pipe.append(h("div", { class: `node ${s}`, role: "listitem" }, h("div", { class: "dotn", html: nodeIcon(s, i) }), h("small", null, label), h("em", null, who)));
      if (i < NODES.length - 1) pipe.append(h("div", { class: `beam-c ${["done", "passed"].includes(s) ? "on" : ""} ${["active", "running"].includes(states[i + 1]) || ["active", "running"].includes(s) ? "flow" : ""}` }));
    });
    blocks.push(pipe);
    if (r.status === "reviewing") blocks.push(card("", h("div", { style: { display: "flex", gap: "12px", alignItems: "center" } }, Kit.dots(), h("span", { class: "shimmer" }, "Cody is reading the diff…"))));
    if (r.error) blocks.push(card("", h("div", { style: { color: "var(--bad)" } }, r.error)));
    const todo = (r.attention || []).filter((a) => a.severity !== "info"), notes = (r.attention || []).filter((a) => a.severity === "info");
    if (todo.length) blocks.push(h("div", { class: "panel panel-pad needs in in-rise" }, h("h2", { class: "section" }, "Needs your attention"), ...todo.map((a) => h("div", { class: `todo ${a.severity}` }, h("b", null, `⚠ ${a.title}`), a.detail ? h("div", null, a.detail) : null, h("div", { class: "muted" }, `What to do: ${a.how_to_fix}`)))));
    if (notes.length) blocks.push(h("div", { class: "panel panel-pad in in-rise" }, h("h2", { class: "section" }, "Optional steps that were skipped"), ...notes.map((a) => h("div", { class: "todo info" }, h("b", null, a.title), h("div", { class: "muted" }, a.how_to_fix)))));
    if (r.heal_attempts) blocks.push(h("div", { class: "panel panel-pad in in-rise" }, h("span", { class: "badge info" }, `Auto-heal retried this ${r.heal_attempts} time${r.heal_attempts === 1 ? "" : "s"}`)));

    if (rv) {
      const hard = (rv.findings || []).some((f) => f.severity === "blocker" && f.issue.includes("added to source")), anyBlock = (rv.findings || []).some((f) => f.severity === "blocker");
      blocks.push(h("div", { class: "panel panel-pad in in-rise" }, h("h2", { class: "section" }, "Change summary"), h("div", { class: "review" }, riskGauge(rv.risk),
        h("div", null, h("ul", { class: "bul" }, ...rv.summary.map((s) => h("li", null, h("span", { html: Kit.icon("check") }), h("span", null, s)))),
          h("div", { style: { marginTop: "12px" } }, h("span", { class: `badge ${rv.recommend_approval ? "ok" : "bad"}` }, rv.recommend_approval ? "Reviewer recommends approval" : "Reviewer does not recommend approval"))))));
      if (rv.findings.length) blocks.push(card(`Findings (${rv.findings.length})`, ...rv.findings.map((f) => h("div", { class: "find" }, h("span", { class: `badge ${f.severity === "blocker" ? "bad" : f.severity === "warning" ? "warn" : "info"}` }, f.severity), h("div", null, f.file ? h("div", { class: "loc" }, `${f.file}${f.line ? ":" + f.line : ""}`) : null, h("div", null, f.issue), f.suggestion ? h("div", { class: "sg" }, f.suggestion) : null)))));
      if (r.status === "awaiting_approval") {
        const ov = h("button", { class: "switch", role: "switch", "aria-checked": String(S.override), "aria-label": "Override blockers", onclick: () => { S.override = !S.override; ov.setAttribute("aria-checked", String(S.override)); ap.disabled = anyBlock && !S.override; } });
        const ap = h("button", { class: "btn btn-primary", disabled: hard || (anyBlock && !S.override), onclick: () => act("approve", { override_warnings: S.override }, "Approved. Pipeline started."), html: Kit.icon("check") + " Approve summary" });
        blocks.push(h("div", { class: "panel panel-pad approve in in-zoom" }, h("div", null, h("b", null, "Your decision"), h("div", { class: "muted", style: { fontSize: "13px" } }, hard ? "A credential was found. This cannot be overridden: remove and rotate it, then submit again." : anyBlock ? "The reviewer found blockers. You can still proceed if you accept the risk." : "You are approving the summary above. Nothing runs until you do.")),
          h("div", { class: "acts" }, anyBlock && !hard ? h("label", { class: "muted", style: { display: "flex", gap: "8px", alignItems: "center", fontSize: "13px" } }, ov, "Override blockers") : null, h("button", { class: "btn btn-danger", onclick: () => act("reject", {}, "Change rejected") }, "Reject"), ap)));
      }
      if (rv.tests_suggested && rv.tests_suggested.length) blocks.push(card("Tests the reviewer suggests", ...rv.tests_suggested.map((t) => h("div", { class: "check" }, h("span", { class: "bx" }), h("span", null, t)))));
    }

    if (["running", "succeeded", "failed"].includes(r.status) || r.stages.some((s) => s.status !== "pending")) {
      blocks.push(card("Stages", h("div", { style: { display: "grid", gap: "10px" } }, ...r.stages.map((s) => {
        const d = h("details", { class: "stage", ...(s.status === "failed" ? { open: true } : {}) },
          h("summary", null, h("span", { class: "t" }, s.label), s.duration_ms != null ? h("span", { class: "muted mono", style: { fontSize: "12px" } }, fmt.ms(s.duration_ms)) : null, h("span", { class: `badge ${s.status === "passed" ? "ok" : s.status === "failed" ? "bad" : s.status === "running" ? "info" : ""}` }, s.status)),
          s.log ? h("pre", { class: "code" }, s.log) : h("div", { class: "muted", style: { padding: "0 14px 12px", fontSize: "13px" } }, s.status === "pending" ? "Waiting…" : "No output."));
        return d;
      }))));
    }
    if (r.heal) blocks.push(h("div", { class: "panel panel-pad in in-flip" }, h("h2", { class: "section" }, `Self-heal diagnosis · ${r.heal.stage}`), h("p", { style: { margin: "0 0 10px" } }, r.heal.diagnosis),
      r.heal.suggested_fix ? h("div", { class: "blk" }, h("div", { class: "t" }, "Suggested fix (for a human to apply)"), h("div", { class: "muted", html: Kit.md(String(r.heal.suggested_fix)) })) : null,
      h("div", { style: { marginTop: "12px", display: "flex", gap: "10px", alignItems: "center" } }, h("button", { class: "btn btn-sm", onclick: () => act("rerun", undefined, "Re-running stages"), html: Kit.icon("refresh") + " Re-run stages" }), r.notified ? h("span", { class: "muted", style: { fontSize: "12.5px" } }, `Telegram: ${r.notified}`) : null)));
    else if (r.status === "succeeded" || r.status === "failed") blocks.push(h("div", null, h("button", { class: "btn btn-sm", onclick: () => act("rerun", undefined, "Re-running stages"), html: Kit.icon("refresh") + " Re-run stages" })));
    if (r.events && r.events.length) blocks.push(card("Team activity", h("div", { class: "feed" }, ...r.events.slice(-8).reverse().map((e) => h("div", null, h("b", null, e.member), h("span", null, e.text))))));
    blocks.push(h("details", { class: "panel panel-pad" }, h("summary", { style: { cursor: "pointer" } }, "View the raw diff"), h("div", { style: { marginTop: "10px" } }, diffView(r.diff_preview || ""))));
    pane.replaceChildren(h("div", { class: "wrap" }, ...blocks));
  }

  try { S.samples = await Kit.api("/api/samples"); } catch (_) {}
  showNew();
})();
