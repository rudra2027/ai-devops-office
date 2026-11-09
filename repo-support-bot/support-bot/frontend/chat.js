(async () => {
  const { h } = Kit;
  const me = await Kit.boot();
  if (!me) return;
  const { page, right } = Kit.shell({ active: "support", title: "Aria", subtitle: Kit.isAdmin ? "Customer support agent · admin view" : "Ask anything about your orders" });

  const state = { conv: null, convs: [], model: "primary", streaming: false, abort: null, recording: false };
  const modelSel = h("select", { class: "select", "aria-label": "Model", onchange: (e) => (state.model = e.target.value) },
    ...Kit.config.models.map((m) => h("option", { value: m.alias }, m.label)));
  const ttsBtn = h("button", { class: "btn btn-icon", "aria-label": "Speak replies", title: "Speak replies (browser voice)", onclick: () => { Kit.tts.set(!Kit.tts.enabled); paintTts(); } });
  const paintTts = () => { ttsBtn.innerHTML = Kit.icon(Kit.tts.enabled ? "volume" : "mute"); ttsBtn.setAttribute("aria-pressed", String(Kit.tts.enabled)); };
  paintTts();
  // Only the admin sees model choice and the ticket inbox; customers get a clean chat.
  const ticketsBtn = h("button", { class: "btn btn-sm", onclick: showTickets, html: Kit.icon("file") + " Tickets" });
  async function showTickets() {
    let rows = [];
    try { rows = await Kit.api("/api/admin/tickets"); } catch (e) { return Kit.toast(e.message, { kind: "bad" }); }
    const m = h("div", { class: "modal", role: "dialog", "aria-modal": "true", onclick: (e) => e.target === m && m.remove() },
      h("div", { class: "panel modal-card panel-pad" }, h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" } }, h("h2", { style: { margin: 0 } }, "Customer tickets"), h("button", { class: "btn btn-sm", onclick: () => m.remove() }, "Close")),
        rows.length ? h("div", { class: "tblwrap" }, h("table", { class: "tbl" }, h("thead", null, h("tr", null, ...["Opened", "Priority", "Subject", "Details"].map((c) => h("th", null, c)))),
          h("tbody", null, ...rows.map((r) => h("tr", null, h("td", null, Kit.fmt.ago(r.created_at)), h("td", null, h("span", { class: `badge ${r.priority === "high" ? "bad" : ""}` }, r.priority)), h("td", null, r.subject), h("td", { class: "muted" }, r.details || "")))))) : h("div", { class: "empty" }, "No tickets yet.")));
    document.body.append(m);
  }
  right.prepend(...(Kit.isAdmin ? [ticketsBtn, modelSel, ttsBtn] : [ttsBtn]));

  // ----- layout -----
  const list = h("div", { class: "list", role: "list" });
  const newBtn = h("button", { class: "btn btn-primary", onclick: () => newChat(), html: Kit.icon("plus") + " New chat" });
  const side = h("aside", { class: "side", "aria-label": "Conversations" }, newBtn, h("h2", { class: "section", style: { margin: "4px 4px 0" } }, "History"), list);
  const col = h("div", { class: "col" });
  const scroll = h("div", { class: "scroll", id: "scroll" }, col);
  const toBottom = h("button", { class: "btn btn-icon to-bottom", "aria-label": "Scroll to latest", onclick: () => scroll.scrollTo({ top: scroll.scrollHeight }), html: Kit.icon("send").replace("<svg", '<svg style="transform:rotate(90deg)"') });
  const input = h("textarea", { rows: 1, placeholder: "Message Aria…", "aria-label": "Message", maxlength: 4000 });
  const wave = h("div", { class: "wave", "aria-hidden": "true" }, ...Array.from({ length: 28 }, () => h("i")));
  const send = h("button", { class: "send", "aria-label": "Send message", title: "Send (Enter)", html: Kit.icon("send") });
  const mic = h("button", { class: "btn mic", "aria-label": "Record voice message", title: "Voice message (Gemini speech-to-text)", html: Kit.icon("mic") });
  const composer = h("form", { class: "panel composer beam", onsubmit: (e) => { e.preventDefault(); submit(); } },
    h("div", null, input, wave), h("div", { class: "acts" }, mic, send),
    h("div", { class: "tools-row" }, h("span", { class: "hint" }, "Enter to send · Shift+Enter for a new line")));
  const stage = h("section", { class: "stage" }, scroll, toBottom, h("div", { class: "composer-wrap" }, composer));
  page.append(h("div", { class: "chat" }, side, stage));

  // ----- helpers -----
  const atBottom = () => scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 90;
  const stick = () => { if (state.stick) scroll.scrollTop = scroll.scrollHeight; };
  scroll.addEventListener("scroll", () => { state.stick = atBottom(); toBottom.classList.toggle("show", !state.stick); });
  state.stick = true;
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
  document.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); newChat(); } });

  const GREET = [
    (n, p) => `${p}, ${n}.`, (n) => `Hi ${n}, what's on your mind?`, (n) => `Hello ${n}. How can I help?`, (n, p) => `${p}! Let's sort it out, ${n}.`,
  ];
  const SUBS = ["Ask about an order, delivery, or anything else. I can also open a ticket for you.", "I can check order status in seconds. Try an order number like 4412.", "Tell me what's wrong and I'll find the fastest fix."];
  const POOL = ["Where is my order 4412?", "Is order 9001 delayed?", "What's the status of order 5120?", "I want to return a USB-C hub (order 7788)", "I need a human agent", "Open a ticket about a damaged item", "What can you help me with?", "Compare my shipped and delayed orders (5120, 9001)"];
  const shuffle = (a) => a.map((v) => [Math.random(), v]).sort((x, y) => x[0] - y[0]).map((x) => x[1]);

  function welcome() {
    Kit.mood("calm");
    const name = (Kit.user()?.email || "there").split("@")[0];
    const hr = new Date().getHours(), part = hr < 5 ? "Burning the midnight oil" : hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
    const g = GREET[Math.floor(Math.random() * GREET.length)](name, part);
    const el = h("div", { class: "welcome" }, h("div", { class: "orb in in-zoom" }), h("h2", { class: "in in-blur", style: { "--i": 1 } }, ...g.split(" ").map((w, i) => h("span", { class: i % 3 === 1 ? "grad-text" : "" }, w + " "))),
      h("p", { class: "in in-rise", style: { "--i": 2 } }, SUBS[Math.floor(Math.random() * SUBS.length)]),
      h("div", { class: "suggest" }, ...shuffle(POOL).slice(0, 4).map((t, i) => h("button", { class: "chip in in-rise", style: { "--i": 3 + i }, onclick: () => submit(t) }, t))));
    col.replaceChildren(el);
  }

  // ----- conversations -----
  async function loadConvs() {
    try { state.convs = await Kit.api("/api/conversations"); } catch (e) { return Kit.toast(e.message, { kind: "bad" }); }
    list.replaceChildren(...(state.convs.length ? state.convs.map((c) => {
      const del = h("button", { class: "btn btn-icon del", "aria-label": "Delete conversation", html: Kit.icon("trash"), onclick: async (ev) => { ev.stopPropagation(); await Kit.api(`/api/conversations/${c.id}`, { method: "DELETE" }); if (state.conv === c.id) newChat(); loadConvs(); } });
      return h("div", { class: `conv ${state.conv === c.id ? "active" : ""}`, role: "listitem", tabindex: 0, onclick: () => openConv(c.id), onkeydown: (e) => e.key === "Enter" && openConv(c.id) },
        h("div", { class: "ti" }, c.title, h("small", null, Kit.fmt.ago(c.updated_at))), del);
    }) : [h("div", { class: "empty muted" }, "No conversations yet")]));
  }
  function newChat() { if (state.streaming) return; state.conv = null; welcome(); loadConvs(); input.focus(); }
  async function openConv(id) {
    if (state.streaming) return;
    const j = await Kit.api(`/api/conversations/${id}`);
    state.conv = id; col.replaceChildren();
    let lastUi = null;
    j.messages.forEach((m) => { if (m.role === "user") userBubble(m.content); else { lastUi = m.ui; assistantStatic(m); } });
    Kit.mood(lastUi?.mood && lastUi.mood !== "celebrate" ? lastUi.mood : "calm");
    state.stick = true; stick(); loadConvs();
  }

  // ----- rendering messages -----
  const userBubble = (text) => { const m = h("div", { class: "msg user in in-rise" }, h("div", { class: "bub" }, text)); col.append(m); stick(); return m; };
  function qrRow(ui) {
    if (!ui?.quick_replies?.length) return null;
    return h("div", { class: "qr" }, ...ui.quick_replies.map((q, i) => h("button", { class: "chip in in-rise", style: { "--i": i }, onclick: () => submit(q) }, q)));
  }
  function metaRow(text, meta) {
    const bits = [];
    if (Kit.isAdmin && meta?.model) bits.push((Kit.config.models.find((m) => m.id === meta.model) || {}).label || meta.model);
    if (Kit.isAdmin && meta?.total_ms) bits.push(Kit.fmt.ms(meta.total_ms));
    if (Kit.isAdmin && meta?.usage?.output_tokens) bits.push(`${meta.usage.output_tokens} tokens`);
    return h("div", { class: "meta" }, ...bits.map((b) => h("span", null, b)),
      h("button", { title: "Copy", "aria-label": "Copy reply", onclick: () => Kit.copy(text), html: Kit.icon("copy") }),
      h("button", { title: "Read aloud", "aria-label": "Read aloud", onclick: () => { const was = Kit.tts.enabled; Kit.tts.enabled = true; Kit.tts.speak(text); Kit.tts.enabled = was; }, html: Kit.icon("volume") }));
  }
  function assistantStatic(m) {
    const body = h("div", { class: "body" }, h("div", { class: "text", html: Kit.md(m.content) }));
    if (m.ui?.blocks?.length) body.append(Kit.blocks.render(m.ui, { onAction: submit }));
    body.append(metaRow(m.content, m.meta));
    col.append(h("div", { class: "msg assistant" }, h("div", { class: "orb sm" }), body));
  }

  // ----- sending -----
  async function submit(text) {
    text = (text ?? input.value).trim();
    if (!text || state.streaming) return;
    input.value = ""; input.style.height = "auto";
    if (col.querySelector(".welcome")) col.replaceChildren();
    Kit.tts.stop();
    userBubble(text);
    setStreaming(true);

    const orb = h("div", { class: "orb sm busy" });
    const tools = h("div", { class: "tools" });
    const textEl = h("div", { class: "text caret" });
    const uiBox = h("div");
    const thinking = h("div", { class: "thinking" }, Kit.dots(), h("span", { class: "shimmer" }, "Thinking…"));
    const body = h("div", { class: "body" }, tools, thinking, textEl, uiBox);
    col.append(h("div", { class: "msg assistant in in-rise" }, orb, body));
    state.stick = true; stick();

    let raw = "", pending = false, final = null, errored = false;
    const paint = () => { pending = false; textEl.innerHTML = Kit.md(raw); stick(); };
    const pills = {};
    state.abort = new AbortController();
    try {
      await Kit.stream("/api/chat", { message: text, conversation_id: state.conv, model: state.model }, (ev) => {
        if (ev.type === "meta") { state.conv = ev.conversation_id; }
        else if (ev.type === "token") { thinking.remove(); raw += ev.text; if (!pending) { pending = true; requestAnimationFrame(paint); } }
        else if (ev.type === "tool_start") {
          thinking.remove();
          const labels = { lookup_order_status: "Checking your order", create_support_ticket: "Opening a ticket", current_time: "Checking the time" };
          const p = h("span", { class: "pill" }, h("span", { class: "spin" }), labels[ev.name] || "Working");
          pills[ev.name] = p; tools.append(p); stick();
        } else if (ev.type === "tool_end") {
          const p = pills[ev.name]; if (p) { p.classList.add("done"); p.innerHTML = Kit.icon("check") + " " + (p.textContent || "Done"); }
        } else if (ev.type === "ui") {
          Kit.mood(ev.ui.mood);
          uiBox.append(Kit.blocks.render(ev.ui, { onAction: submit }));
          const q = qrRow(ev.ui); if (q) uiBox.append(q);
          stick();
        } else if (ev.type === "done") { final = ev; }
        else if (ev.type === "error") { errored = true; thinking.remove(); body.append(h("div", { class: "err" }, ev.message, h("button", { class: "btn btn-sm", onclick: () => submit(text) }, "Try again"))); }
      }, state.abort.signal);
    } catch (e) {
      errored = true; thinking.remove();
      body.append(h("div", { class: "err" }, e.message || "Something went wrong.", h("button", { class: "btn btn-sm", onclick: () => submit(text) }, "Try again")));
      Kit.toast(e.message, { kind: "bad" });
    }
    textEl.classList.remove("caret"); orb.classList.remove("busy");
    if (raw) paint();
    if (final && !errored) {
      body.append(metaRow(final.text, { model: Kit.config.models.find((m) => m.alias === state.model)?.id, total_ms: final.total_ms, usage: final.usage }));
      Kit.tts.speak(final.text);
    }
    setStreaming(false);
    loadConvs();
  }

  function setStreaming(on) {
    state.streaming = on;
    send.classList.toggle("stop", on);
    send.innerHTML = Kit.icon(on ? "stop" : "send");
    send.setAttribute("aria-label", on ? "Stop generating" : "Send message");
    send.type = on ? "button" : "submit";
    send.onclick = on ? () => state.abort && state.abort.abort() : null;
    modelSel.disabled = on;
  }

  // ----- voice in -----
  mic.addEventListener("click", async () => {
    if (state.streaming) return;
    if (!Kit.stt.supported()) return Kit.toast("Voice input isn't supported in this browser.", { kind: "bad" });
    if (!state.recording) {
      try { await Kit.stt.start(); } catch (_) { return Kit.toast("Microphone access was blocked.", { kind: "bad" }); }
      state.recording = true; mic.classList.add("rec"); composer.classList.add("rec", "on"); Kit.tts.stop();
    } else {
      state.recording = false; mic.classList.remove("rec"); composer.classList.remove("rec", "on");
      mic.disabled = true; input.placeholder = "Transcribing…";
      try {
        const t = (await Kit.stt.stop()).trim();
        if (t) { input.value = t; input.dispatchEvent(new Event("input")); input.focus(); } else Kit.toast("I couldn't hear anything. Try again.");
      } catch (e) { Kit.toast(e.message, { kind: "bad" }); }
      mic.disabled = false; input.placeholder = "Message Aria…";
    }
  });

  setStreaming(false);
  welcome();
  loadConvs();
  input.focus();
})();
