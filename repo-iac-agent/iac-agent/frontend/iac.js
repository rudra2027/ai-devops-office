(async () => {
  const { h } = Kit;
  const me = await Kit.boot({ admin: true });
  if (!me) return;
  const { page, right } = Kit.shell({ active: "iac", title: "Infrastructure", subtitle: "Describe what you need. The team designs it on any cloud." });

  const S = { id: null, data: null, busy: false, timer: null, model: "primary", file: 0, lastCount: 0, examples: [] };
  const COLORS = { requirements: "#7c5cff", architect: "#22d3b6", writer: "#ff7ab6", reviewer: "#fbbf24", operator: "#60a5fa", drift: "#a78bfa" };
  const NAMES = { requirements: "Rhea", architect: "Arjun", writer: "Tara", reviewer: "Rex", operator: "Ira", drift: "Dev" };
  const ROLES = { requirements: "Requirements", architect: "Architecture", writer: "Terraform", reviewer: "Review", operator: "Operations" };

  const modelSel = h("select", { class: "select", "aria-label": "Model", onchange: (e) => (S.model = e.target.value) }, ...Kit.config.models.map((m) => h("option", { value: m.alias }, m.label)));
  right.prepend(modelSel);

  // ----- layout -----
  const list = h("div", { class: "list" });
  const side = h("aside", { class: "side", "aria-label": "Sessions" }, h("button", { class: "btn btn-primary", onclick: () => newSession(), html: Kit.icon("plus") + " New infrastructure" }), h("h2", { class: "section", style: { margin: "4px 4px 0" } }, "History"), list);
  const col = h("div", { class: "col" });
  const scroll = h("div", { class: "scroll" }, col);
  const input = h("textarea", { rows: 1, placeholder: "e.g. A web app on Hetzner with Postgres and a bucket…", "aria-label": "Describe your infrastructure", maxlength: 4000 });
  const send = h("button", { class: "send", type: "submit", "aria-label": "Send", html: Kit.icon("send") });
  const fileInput = h("input", { type: "file", hidden: true, accept: ".png,.jpg,.jpeg,.webp,.gif,.pdf,.docx,.txt,.md,.json,.yaml,.yml,.xml,.drawio,.mmd,.puml,.tf,.svg", onchange: (e) => { stage1(e.target.files[0]); e.target.value = ""; } });
  const clip = h("button", { class: "clip", type: "button", title: "Attach an architecture diagram or design document (image, PDF, Word, draw.io, text)", "aria-label": "Attach a diagram or document", html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>', onclick: () => fileInput.click() });
  const chip = h("div", { class: "filechip", hidden: true });
  const composer = h("form", { class: "panel composer beam", onsubmit: (e) => { e.preventDefault(); submit(); } }, chip, clip, fileInput, input, send, h("div", { class: "hint" }, "Any cloud works. Attach an architecture diagram (image, PDF, Word) and name the cloud to build it on. Nothing is created until you approve."));
  const stage = h("section", { class: "stage" }, scroll, h("div", { class: "composer-wrap" }, composer));
  const bp = h("aside", { class: "bp", "aria-label": "Blueprint" });
  const root = h("div", { class: "iac" }, side, stage, bp);
  page.append(root);
  const archBtn = h("button", { class: "btn btn-primary btn-sm", onclick: () => showArchitecture(), title: "See the architecture diagram", html: Kit.icon("cloud") + " Architecture" });
  right.append(archBtn, h("button", { class: "btn btn-sm only-narrow", onclick: () => root.classList.toggle("showbp"), title: "Show or hide the details panel" }, "Details"));

  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 170) + "px"; });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
  // ----- attaching a diagram or document -----
  const MAX_MB = 15;
  function stage1(f) {
    if (!f) return;
    if (f.size > MAX_MB * 1048576) return Kit.toast(`That file is over ${MAX_MB} MB.`, { kind: "bad" });
    S.attached = f;
    chip.hidden = false;
    chip.replaceChildren(h("span", null, "📎 " + f.name), h("small", { class: "muted" }, ` ${(f.size / 1024).toFixed(0)} KB`), h("button", { type: "button", class: "x", "aria-label": "Remove attachment", onclick: () => unstage(), html: "&times;" }));
    if (!input.value.trim()) input.placeholder = "Which cloud should this be built on? Anything else the team should know…";
    input.focus();
  }
  function unstage() { S.attached = null; chip.hidden = true; chip.replaceChildren(); input.placeholder = "e.g. A web app on Hetzner with Postgres and a bucket…"; }
  ["dragenter", "dragover"].forEach((ev) => stageEl().addEventListener(ev, (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); stageEl().classList.add("drop"); } }));
  ["dragleave", "drop"].forEach((ev) => stageEl().addEventListener(ev, (e) => { if (ev === "drop" || e.target === stageEl()) stageEl().classList.remove("drop"); }));
  stageEl().addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) { e.preventDefault(); stage1(f); } });
  input.addEventListener("paste", (e) => { const f = [...(e.clipboardData?.files || [])][0]; if (f) { e.preventDefault(); stage1(f.name && f.name !== "image.png" ? f : new File([f], `pasted-diagram.${(f.type.split("/")[1] || "png")}`, { type: f.type })); } });
  function stageEl() { return stage; }
  const stick = () => (scroll.scrollTop = scroll.scrollHeight);

  const avatar = (m, cls = "av") => h("span", { class: cls, style: { background: COLORS[m] || "var(--grad)" }, title: `${NAMES[m] || m}, ${ROLES[m] || ""}` }, (NAMES[m] || m)[0]);

  // ----- welcome -----
  function welcome() {
    Kit.mood("calm");
    bp.replaceChildren(h("div", { class: "empty" }, h("div", { class: "orb sm" }), h("b", null, "Your blueprint appears here"), h("span", null, "Pipeline progress, cloud mapping, Terraform files and review findings.")));
    const tiles = S.examples.map((x, i) => {
      const t = h("button", { class: "tile in in-rise", style: { "--i": 2 + i, textAlign: "left", font: "inherit", color: "inherit" }, onclick: () => submit(x.prompt) }, h("b", null, h("span", { class: "cl" }, x.cloud[0]), x.cloud), h("span", null, x.prompt));
      t.addEventListener("pointermove", (e) => { const r = t.getBoundingClientRect(); t.style.setProperty("--mx", ((e.clientX - r.left) / r.width) * 100 + "%"); t.style.setProperty("--my", ((e.clientY - r.top) / r.height) * 100 + "%"); });
      return t;
    });
    col.replaceChildren(h("div", { class: "welcome" }, h("div", { class: "orb in in-zoom" }), h("h2", { class: "in in-blur", style: { "--i": 1 } }, "What should we ", h("span", { class: "grad-text" }, "build"), " today?"),
      h("p", { class: "in in-rise", style: { "--i": 1 } }, "Tell us in plain words. Name any cloud, even a small one, and the team works out the right resources."), h("div", { class: "tiles" }, ...tiles)));
  }

  // ----- sessions -----
  async function loadList() {
    let rows = [];
    try { rows = await Kit.api("/iac/sessions"); } catch (e) { return Kit.toast(e.message, { kind: "bad" }); }
    list.replaceChildren(...(rows.length ? rows.filter((r) => r.title !== "New infrastructure" || r.id === S.id).map((r) => {
      const del = h("button", { class: "btn btn-icon del", "aria-label": "Delete session", html: Kit.icon("trash"), onclick: async (ev) => { ev.stopPropagation(); await Kit.api(`/iac/sessions/${r.id}`, { method: "DELETE" }); if (S.id === r.id) newSession(); loadList(); } });
      return h("div", { class: `conv ${S.id === r.id ? "active" : ""}`, tabindex: 0, onclick: () => openSession(r.id), onkeydown: (e) => e.key === "Enter" && openSession(r.id) }, h("div", { class: "ti" }, r.title, h("small", null, `${(r.status || "").replace(/_/g, " ")} · ${Kit.fmt.ago(r.updated_at)}`)), del);
    }) : [h("div", { class: "empty muted" }, "No sessions yet")]));
  }
  function newSession() { clearTimeout(S.timer); S.id = null; S.data = null; S.busy = false; S.lastCount = 0; welcome(); loadList(); input.focus(); }
  async function openSession(id) {
    clearTimeout(S.timer); S.id = id;
    S.data = await Kit.api(`/iac/sessions/${id}`);
    S.lastCount = S.data.activity.length; render(true); loadList();
    if (S.data.busy) poll();
  }

  // ----- sending -----
  async function ensureSession() { if (!S.id) { const d = await Kit.api("/iac/sessions", { method: "POST", body: { model: S.model } }); S.id = d.id; } }
  async function submit(text) {
    text = (text ?? input.value).trim();
    if ((!text && !S.attached) || S.busy) return;
    const file = S.attached;
    input.value = ""; input.style.height = "auto"; unstage();
    try {
      await ensureSession();
      S.busy = true; send.disabled = true;
      S.lastCount = S.data ? S.data.activity.length : 0;
      if (file) {
        const form = new FormData();
        form.append("file", file); form.append("message", text); form.append("model", S.model);
        S.data = await Kit.api(`/iac/sessions/${S.id}/attachments`, { method: "POST", form });
      } else S.data = await Kit.api(`/iac/sessions/${S.id}/messages`, { method: "POST", body: { content: text, model: S.model } });
      render(true); poll();
    } catch (e) { S.busy = false; send.disabled = false; Kit.toast(e.message, { kind: "bad" }); }
  }
  function poll() {
    clearTimeout(S.timer);
    S.timer = setTimeout(async () => {
      try { S.data = await Kit.api(`/iac/sessions/${S.id}`); } catch (_) { return poll(); }
      render(false);
      if (S.data.busy) poll(); else { S.busy = false; send.disabled = false; loadList(); }
    }, 1000);
  }

  // ----- chat thread -----
  function feedItem(a) {
    return h("div", { class: `fi ${a.kind === "tool_call" || a.kind === "tool_result" ? "tool" : ""} ${a.kind === "error" ? "error" : ""}` }, avatar(a.member), h("div", null, h("div", { class: "who" }, NAMES[a.member] || a.member, h("span", { class: "muted", style: { fontWeight: 400 } }, ` · ${ROLES[a.member] || ""}`)), h("div", { class: "tx" }, (a.kind === "tool_call" ? "🔧 " : a.kind === "handoff" ? "➜ " : "") + a.text)));
  }
  const uiFor = (d) => {
    const blocks = [], files = d.files || [], req = d.requirements, arch = d.architecture, rev = d.review;
    if (arch) blocks.push({ type: "stats", items: [{ label: "Cloud", value: arch.provider.cloud, tone: "neutral" }, { label: "Components", value: String(req ? req.components.length : 0), tone: "neutral" }, { label: "Files", value: String(files.length), tone: "neutral" }, { label: "Findings", value: String(rev ? rev.findings.length : 0), delta: rev && rev.approved_for_plan ? "ready to plan" : rev ? "needs attention" : "", tone: rev && rev.approved_for_plan ? "success" : "warning" }] });
    if (arch && arch.gaps.length) blocks.push({ type: "card", title: "Worth knowing", icon: "💡", tone: "warning", body: arch.gaps.map((g) => "- " + g).join("\n") });
    if (d.status === "needs_answers" && d.requirements?.questions?.length) blocks.push({ type: "checklist", title: "Questions for you", items: d.requirements.questions.map((q) => ({ text: q, done: false })) });
    if (d.status === "applied") blocks.push({ type: "card", title: "Infrastructure applied", icon: "🎉", tone: "success", body: "Everything in the approved plan has been created." });
    return { mood: d.status === "applied" ? "celebrate" : d.status === "failed" ? "urgent" : d.status === "needs_answers" ? "thinking" : d.status === "collecting" ? "thinking" : "upbeat", blocks, quick_replies: [] };
  };

  function render(full) {
    const d = S.data;
    if (!d) return;
    if (full || !col.querySelector(".msg")) {
      col.replaceChildren();
      d.history.forEach((m) => {
        if (m.role === "user") col.append(h("div", { class: "msg user in in-rise" }, h("div", { class: "bub" }, m.text)));
        else col.append(h("div", { class: "msg assistant" }, h("div", { class: "orb sm" }), h("div", null, h("div", { class: "text", html: Kit.md(m.text.replace(/\s*\[[^\]]+\|[^\]]+\]/g, "")) }))));
      });
      col.querySelectorAll(".msg.assistant:last-of-type").forEach(() => {});
    }
    col.querySelector(".livefeed")?.remove();
    const acts = d.activity || [];
    if (d.busy) {
      const f = h("div", { class: "feed livefeed" }, h("h4", null, Kit.dots(), "The team is working"), ...acts.slice(-6).map(feedItem));
      col.append(f);
    } else if (acts.length) {
      col.querySelector("details.notes")?.remove();
      col.append(h("details", { class: "notes" }, h("summary", null, `Team notes (${acts.length})`), h("div", { style: { display: "grid", gap: "8px", marginTop: "10px" } }, ...acts.map(feedItem))));
      if (!col.querySelector(".gen")) {
        const last = [...col.querySelectorAll(".msg.assistant")].pop();
        const ui = uiFor(d);
        if (last && ui.blocks.length) { const g = h("div", { class: "gen" }, Kit.blocks.render(ui)); last.lastChild.append(g); Kit.mood(ui.mood); }
      }
    }
    if (!d.busy) {
      // everything the team needs from you, in one place: answers to questions (click, then send once) and things only you can fix
      col.querySelector(".needs")?.remove();
      const last = d.history.length ? d.history[d.history.length - 1] : null;
      const qs = last && last.role === "agent" ? last.text.split("\n").map((l) => l.match(/^\s*[-*\d.]*\s*(.*?)\s*\[([^\]]+\|[^\]]+)\]\s*$/)).filter(Boolean).map((m) => ({ q: m[1], opts: m[2].split("|").map((o) => o.trim()) })) : [];
      const todo = (d.attention || []).filter((a) => a.kind !== "question");
      if (qs.length || todo.length) {
        const box = h("div", { class: "needs panel panel-pad in in-rise" }, h("h2", { class: "section" }, "Needs your attention"));
        qs.forEach((q) => box.append(h("div", { class: "qrow" }, h("span", { class: "muted" }, q.q), ...q.opts.map((o) => { const rec = o.includes("*"), label = o.replace(/\s*\*\s*/g, ""); return h("button", { class: `chip ${rec ? "rec" : ""}`, type: "button", onclick: () => { input.value = (input.value ? input.value + "; " : "") + `${q.q.replace(/\?+$/, "")}: ${label}`; input.focus(); input.dispatchEvent(new Event("input")); } }, label); }))));
        if (qs.length) box.append(h("div", { class: "muted", style: { fontSize: "12.5px", marginTop: "6px" } }, "Click your answers, adjust if you like, then press Send once."));
        todo.forEach((a) => box.append(h("div", { class: `todo ${a.severity}` }, h("b", null, `⚠ ${a.title}`), h("div", null, a.detail), h("div", { class: "muted" }, `What to do: ${a.how_to_fix}`))));
        col.append(box);
      }
    }
    if (d.error && !d.busy) col.append(h("div", { class: "err", style: { fontSize: "13px" } }, d.error));
    stick();
    renderBlueprint();
  }

  // ----- blueprint panel -----
  const STAGES = [["requirements", "Requirements", "Rhea"], ["architect", "Architecture", "Arjun"], ["writer", "Terraform", "Tara"], ["reviewer", "Review", "Rex"], ["plan", "Plan", "Ira"], ["approve", "Approval", "You"], ["apply", "Apply", "Ira"]];
  function stageStates(d) {
    const has = [d.requirements && d.requirements.components.length > 0 && !(d.requirements.questions || []).length, !!d.architecture, d.files.length > 0, !!d.review];
    const st = d.status, out = [];
    const planned = ["planned", "approved", "applying", "applied"].includes(st), approved = ["approved", "applying", "applied"].includes(st);
    const flags = [...has, planned, approved, st === "applied"];
    let activeSet = false;
    flags.forEach((done, i) => {
      let s = done ? "done" : "todo";
      if (!done && !activeSet) {
        activeSet = true;
        if (d.busy && i <= 3) s = "active";
        else if (st === "needs_answers" && i === 0) s = "wait";
        else if (st === "needs_answers" && i === 3) s = "wait";
        else if (st === "ready_for_plan" && i === 4) s = "wait";
        else if (st === "planned" && i === 5) s = "wait";
        else if (st === "applying" && i === 6) s = "active";
        else if (st === "failed") s = "bad";
      }
      out.push(s);
    });
    return out;
  }
  // ----- architecture diagram -----
  function legend(d) {
    const kinds = [...new Set(d.nodes.map((n) => n.kind))];
    return h("div", { class: "legend-row" }, ...kinds.map((k) => h("span", null, h("i", { style: { background: (window.Diagram.COLOR[k] || "#94a3b8") } }), k.replace(/_/g, " "))));
  }
  function showArchitecture() {
    const d = S.data && S.data.architecture && S.data.architecture.diagram;
    if (!d) { Kit.toast(S.data && S.data.busy ? "The architect is still designing. The diagram appears when the design is ready." : "Describe your infrastructure first. The diagram is drawn from the design.", {}); return; }
    const close = () => { m.remove(); document.removeEventListener("keydown", esc); };
    const esc = (e) => e.key === "Escape" && close();
    const resources = S.data.architecture.mappings;
    const m = h("div", { class: "modal arch-modal", role: "dialog", "aria-modal": "true", "aria-label": "Architecture diagram", onclick: (e) => e.target === m && close() },
      h("div", { class: "panel modal-card panel-pad" },
        h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px" } }, h("div", null, h("h2", { style: { margin: 0 } }, d.title || "Architecture"),
          h("div", { class: "muted", style: { fontSize: "13px" } }, `${S.data.architecture.provider.cloud} · ${S.data.architecture.region} · scroll to zoom, drag to move`)), h("button", { class: "btn btn-sm", onclick: close }, "Close")),
        window.Diagram.render(d, { height: Math.max(380, Math.min(620, window.innerHeight - 330)) }),
        h("div", null, legend(d), h("div", { class: "tblwrap", style: { marginTop: "10px", maxHeight: "150px", overflow: "auto" } }, h("table", { class: "tbl" }, h("thead", null, h("tr", null, ...["Component", "Cloud term", "Resources"].map((c) => h("th", null, c)))),
          h("tbody", null, ...resources.map((r) => h("tr", null, h("td", null, r.component), h("td", null, r.provider_terms), h("td", { class: "mono", style: { fontSize: "12px" } }, r.resource_types.join(", "))))))))));
    document.addEventListener("keydown", esc);
    document.body.append(m);
  }

  const bpCard = (title, ...kids) => h("div", { class: "panel card in in-rise" }, h("h2", { class: "section" }, title), ...kids);

  function renderBlueprint() {
    const d = S.data;
    if (!d) return;
    const states = stageStates(d), cards = [];
    const todo = (d.attention || []).filter((a) => a.kind !== "question");
    if (todo.length) cards.push(bpCard("Needs your attention", ...todo.map((a) => h("div", { class: `todo ${a.severity}` }, h("b", null, `⚠ ${a.title}`), h("div", null, a.detail), h("div", { class: "muted" }, `What to do: ${a.how_to_fix}`)))));
    cards.push(bpCard("Pipeline", h("ol", { class: "pipe" }, ...STAGES.map(([id, label, who], i) => h("li", { class: states[i] }, h("span", { class: "n" }, states[i] === "done" ? "✓" : i + 1), h("span", null, label), h("small", null, who))))));
    if (d.architecture) {
      const a = d.architecture;
      if (a.diagram) cards.push(bpCard("Architecture", window.Diagram.render(a.diagram, { height: 250 }), h("div", { class: "actions", style: { marginTop: "10px" } }, h("button", { class: "btn btn-sm btn-primary", onclick: showArchitecture }, "Open full diagram"))));
      cards.push(bpCard("Cloud", h("dl", { class: "kv" }, h("dt", null, "Provider"), h("dd", { class: "mono" }, a.provider.terraform_source), h("dt", null, "Version"), h("dd", { class: "mono" }, a.provider.version_constraint), h("dt", null, "Region"), h("dd", null, a.region)),
        a.provider.auth_env_vars.length ? h("div", { style: { marginTop: "10px" } }, h("div", { class: "muted", style: { fontSize: "12px", marginBottom: "6px" } }, "Credentials are read from these environment variables (never typed here):"), h("div", { class: "chips" }, ...a.provider.auth_env_vars.map((v) => h("span", { class: "badge" }, v)))) : null));
      cards.push(bpCard("How this cloud names things", h("div", { class: "tblwrap" }, h("table", { class: "tbl" }, h("thead", null, h("tr", null, ...["Component", "Cloud term", "Resources"].map((c) => h("th", null, c)))), h("tbody", null, ...a.mappings.map((m) => h("tr", null, h("td", null, m.component), h("td", null, m.provider_terms), h("td", { class: "mono", style: { fontSize: "12px" } }, m.resource_types.join(", ")))))))));
    }
    if (d.files.length) {
      S.file = Math.min(S.file, d.files.length - 1);
      const pre = h("pre", { class: "code" }, d.files[S.file].content);
      const tabs = h("div", { class: "ftabs", role: "tablist" }, ...d.files.map((f, i) => h("button", { role: "tab", "aria-selected": String(i === S.file), onclick: () => { S.file = i; renderBlueprint(); } }, f.path)));
      cards.push(bpCard("Terraform", tabs, pre, h("div", { class: "actions", style: { marginTop: "10px" } }, h("button", { class: "btn btn-sm", onclick: () => Kit.copy(d.files[S.file].content), html: Kit.icon("copy") + " Copy" }),
        h("button", { class: "btn btn-sm", onclick: download, html: Kit.icon("file") + " Download .zip" }))));
    }
    if (d.review) cards.push(bpCard("Review", h("div", { style: { marginBottom: "8px" } }, h("span", { class: `badge ${d.review.approved_for_plan ? "ok" : "bad"}` }, d.review.approved_for_plan ? "Ready to plan" : "Blocked"), " ", h("span", { class: "muted", style: { fontSize: "13px" } }, d.review.summary)),
      ...d.review.findings.map((f) => h("div", { class: "find" }, h("span", { class: `badge ${f.severity === "blocker" ? "bad" : f.severity === "warning" ? "warn" : "info"}` }, f.severity), h("span", null, h("span", { class: "mono", style: { fontSize: "12px", color: "var(--muted)" } }, f.resource + " "), f.message)))));
    if (d.plan_output) cards.push(bpCard("Plan", h("pre", { class: "code" }, d.plan_output.slice(-2400))));
    if (d.apply_output) cards.push(bpCard("Apply", h("pre", { class: "code" }, d.apply_output.slice(-2000))));
    const act = actions(d);
    if (act) cards.push(act);
    bp.replaceChildren(...cards);
  }

  async function download() {
    const r = await Kit.api(`/iac/sessions/${S.id}/download`, { raw: true });
    if (!r.ok) return Kit.toast("Nothing to download yet", { kind: "bad" });
    const url = URL.createObjectURL(await r.blob());
    const a = h("a", { href: url, download: `infrastructure-${S.id}.zip` }); document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  async function step(path, okMsg) {
    try { S.data = await Kit.api(`/iac/sessions/${S.id}/${path}`, { method: "POST" }); if (okMsg) Kit.toast(okMsg, { kind: "ok" }); render(true); }
    catch (e) {
      Kit.toast(e.message, { kind: "bad" });
      try { S.data = await Kit.api(`/iac/sessions/${S.id}`); render(true); } catch (_) {}
    }
  }
  function confirmApply() {
    const ok = h("input", { type: "checkbox", id: "ok" });
    const go = h("button", { class: "btn btn-primary", disabled: true, onclick: async () => { m.remove(); Kit.mood("thinking"); await step("apply"); if (S.data.status === "applied") Kit.mood("celebrate"); } }, "Apply to my cloud account");
    ok.onchange = () => (go.disabled = !ok.checked);
    const m = h("div", { class: "modal", role: "dialog", "aria-modal": "true" }, h("div", { class: "panel modal-card panel-pad" }, h("h2", { style: { margin: "0 0 8px" } }, "Apply this plan?"),
      h("p", { class: "muted" }, "This creates real resources using the cloud credentials on the machine running the agent. It can cost money. You approved this plan as ", h("b", null, S.data.approved_by || "you"), "."),
      h("label", { class: "check", for: "ok", style: { cursor: "pointer" } }, ok, h("span", null, "I understand and want to continue")), h("div", { class: "actions", style: { marginTop: "16px", justifyContent: "flex-end" } }, h("button", { class: "btn", onclick: () => m.remove() }, "Cancel"), go)));
    document.body.append(m);
  }
  function actions(d) {
    if (d.busy) return null;
    const a = h("div", { class: "actions" });
    const btn = (label, fn, cls = "btn") => a.append(h("button", { class: cls, onclick: async (e) => { e.currentTarget.disabled = true; await fn(); } }, label));
    if (d.status === "ready_for_plan") btn("Run terraform plan", () => step("plan", "Plan complete"), "btn btn-primary");
    if (d.status === "planned") btn("Approve plan", () => step("approve", "Plan approved"), "btn btn-primary");
    if (d.status === "approved") btn("Apply…", async () => confirmApply(), "btn btn-primary");
    if (!a.children.length) return null;
    const note = d.status === "ready_for_plan" ? "Preview exactly what would change. Nothing is created yet." : d.status === "planned" ? "Review the plan, then approve it. You will confirm once more before anything is created." : "One last confirmation before anything is created.";
    return bpCard("Next step", h("p", { class: "muted", style: { margin: "0 0 10px", fontSize: "13px" } }, note), a);
  }

  // ----- boot -----
  try { S.examples = await Kit.api("/iac/examples"); } catch (_) { S.examples = []; }
  welcome();
  loadList();
  input.focus();
})();
