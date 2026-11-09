/* Agent Office UI kit: shell, auth, streaming, generative-UI renderer, charts, speech. No dependencies. */
(() => {
  const Kit = (window.Kit = {});
  const LS = {
    get: (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (_) { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} },
    del: (k) => { try { localStorage.removeItem(k); } catch (_) {} },
  };
  Kit.apps = Object.assign({ support: "http://localhost:8000", iac: "http://localhost:8100", cicd: "http://localhost:8300", perf: "http://localhost:8400", office: "http://localhost:8200" }, window.AO_APPS || {});
  Kit.rm = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- tiny DOM helper ----------
  const h = (tag, props, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === false || v == null) continue;
      if (k === "class") n.className = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "style" && typeof v === "object") Object.assign(n.style, v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    kids.flat().forEach((c) => c != null && c !== false && n.append(c.nodeType ? c : document.createTextNode(String(c))));
    return n;
  };
  Kit.h = h;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  Kit.esc = esc;
  const pick = (a) => a[Math.floor(Math.random() * a.length)];

  // ---------- icons (stroke style) ----------
  const P = {
    chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
    cloud: '<path d="M7 18a4.5 4.5 0 0 1-.5-9A6 6 0 0 1 18 9.5 4 4 0 0 1 17.5 18z"/>',
    rocket: '<path d="M5 15c-1 1-1.5 3.5-1.5 5 1.5 0 4-.5 5-1.5M14 4c3.5-.5 6 0 6 0s.5 2.5 0 6l-6 6-4-4zM9 12l-3-1 2-3 3 .5M12 15l1 3 3-2-.5-3"/><circle cx="15.5" cy="8.5" r="1.3"/>',
    gauge: '<path d="M4 17a8 8 0 1 1 16 0"/><path d="m12 17 4-6"/><circle cx="12" cy="17" r="1.2"/>',
    building: '<path d="M4 21V5l8-2v18M12 8l8 2v11M3 21h18M8 8h1M8 12h1M8 16h1M16 13h1M16 17h1"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    send: '<path d="M5 12h13M13 6l6 6-6 6"/>', stop: '<rect x="6" y="6" width="12" height="12" rx="2.5"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>', trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    logout: '<path d="M10 4H5v16h5M15 8l4 4-4 4M19 12H9"/>', spark: '<path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z"/>',
    volume: '<path d="M4 9v6h4l5 4V5L8 9zM16.5 8.5a5 5 0 0 1 0 7"/>', mute: '<path d="M4 9v6h4l5 4V5L8 9zM17 9l4 6M21 9l-4 6"/>',
    play: '<path d="M7 4l13 8-13 8z"/>', refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    check: '<path d="m5 12 5 5 9-10"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>', copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    zap: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>', shield: '<path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6z"/>', file: '<path d="M7 3h7l5 5v13H7zM14 3v5h5"/>',
  };
  Kit.icon = (n, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n] || ""}</svg>`;
  Kit.checkIcon = (size = 56, color = "var(--ok)") => `<svg class="ico-check" width="${size}" height="${size}" viewBox="0 0 56 56" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><circle cx="28" cy="28" r="25"/><path d="m17 29 8 8 14-17"/></svg>`;
  Kit.dots = () => h("span", { class: "dots-loader", "aria-label": "Working" }, h("i"), h("i"), h("i"));

  // ---------- ripple + press feedback ----------
  document.addEventListener("pointerdown", (e) => {
    const t = e.target.closest && e.target.closest(".btn, .chip, .rail-item");
    if (!t || t.disabled || Kit.rm) return;
    const r = t.getBoundingClientRect(), size = Math.max(r.width, r.height);
    const s = h("span", { class: "ripple", style: { width: size + "px", height: size + "px", left: e.clientX - r.left - size / 2 + "px", top: e.clientY - r.top - size / 2 + "px" } });
    t.append(s);
    setTimeout(() => s.remove(), 750);
  });

  // ---------- toasts ----------
  Kit.toast = (msg, { kind = "", ms = 4200 } = {}) => {
    let box = document.querySelector(".toasts");
    if (!box) document.body.append((box = h("div", { class: "toasts", role: "status", "aria-live": "polite" })));
    const t = h("div", { class: `toast ${kind}` }, msg, h("div", { class: "bar", style: { animationDuration: ms + "ms" } }));
    box.append(t);
    setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 300); }, ms);
  };

  // ---------- theme + mood ----------
  Kit.setTheme = (t) => { document.documentElement.dataset.theme = t; LS.set("ao.theme", t); };
  Kit.setTheme(LS.get("ao.theme", matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  Kit.mood = (m = "calm") => {
    document.documentElement.dataset.mood = m;
    if (m === "celebrate") Kit.confetti();
  };
  Kit.confetti = (n = 70) => {
    if (Kit.rm) return;
    const cols = ["#7c5cff", "#22d3b6", "#ff7ab6", "#ffb347", "#60a5fa"];
    for (let i = 0; i < n; i++) {
      const c = h("i", { class: "confetti", style: {
        left: Math.random() * 100 + "vw", background: pick(cols), borderRadius: Math.random() > 0.5 ? "50%" : "2px",
        animationDuration: 1.6 + Math.random() * 1.6 + "s", animationDelay: Math.random() * 0.4 + "s",
      } });
      c.style.setProperty("--dx", (Math.random() * 240 - 120) + "px");
      c.style.setProperty("--rot", Math.random() * 900 - 450 + "deg");
      document.body.append(c);
      setTimeout(() => c.remove(), 3800);
    }
  };

  // ---------- number helpers ----------
  Kit.fmt = {
    n: (v, d = 0) => (v == null || isNaN(v) ? "–" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })),
    ms: (v) => (v == null ? "–" : v >= 1000 ? (v / 1000).toFixed(2) + " s" : Math.round(v) + " ms"),
    usd: (v) => (v == null ? "–" : "$" + (v < 1 ? v.toFixed(4) : v.toFixed(2))),
    pct: (v, d = 1) => (v == null ? "–" : (v * 100).toFixed(d) + "%"),
    ago: (iso) => { const s = (Date.now() - new Date(iso)) / 1000; return s < 60 ? Math.round(s) + "s ago" : s < 3600 ? Math.round(s / 60) + "m ago" : s < 86400 ? Math.round(s / 3600) + "h ago" : Math.round(s / 86400) + "d ago"; },
  };
  // sliding-digit counter
  Kit.odo = (text) => {
    const row = h("span", { style: { display: "inline-flex", alignItems: "flex-start", lineHeight: "1.25em", height: "1.25em" } });
    Kit.setOdo(row, String(text));
    return row;
  };
  Kit.setOdo = (row, text) => {
    if (row.dataset.text === text) return;
    row.dataset.text = text;
    const rebuild = row.children.length !== text.length;
    if (rebuild) row.replaceChildren();
    [...text].forEach((ch, i) => {
      if (/\d/.test(ch)) {
        let col = rebuild ? null : row.children[i];
        if (!col || !col.classList.contains("odo")) {
          const inner = h("span", null, ...[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((d) => h("b", null, d)));
          col = h("span", { class: "odo" }, inner);
          rebuild ? row.append(col) : row.children[i].replaceWith(col);
        }
        const inner = col.firstChild;
        requestAnimationFrame(() => requestAnimationFrame(() => (inner.style.transform = `translateY(${-Number(ch) * 1.25}em)`)));
      } else if (rebuild) row.append(h("span", null, ch));
      else row.children[i].replaceWith(h("span", null, ch));
    });
  };

  // ---------- safe markdown ----------
  Kit.md = (src) => {
    const blocks = [];
    let s = esc((src || "").replace(/\s+$/, "")).replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => { blocks.push(`<pre class="code">${code.replace(/\n$/, "")}</pre>`); return `\u0000${blocks.length - 1}\u0000`; });
    s = s.replace(/`([^`\n]+)`/g, '<code class="mono" style="background:var(--surface-2);padding:1px 6px;border-radius:6px">$1</code>')
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" style="color:var(--a2)">$1</a>');
    const out = [];
    let list = null;
    s.split("\n").forEach((line) => {
      const li = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
      if (li) { if (!list) { list = []; } list.push(`<li>${li[1]}</li>`); return; }
      if (list) { out.push(`<ul style="margin:6px 0;padding-left:20px">${list.join("")}</ul>`); list = null; }
      out.push(line.trim() === "" ? "<br>" : `<p style="margin:0 0 6px">${line}</p>`);
    });
    if (list) out.push(`<ul style="margin:6px 0;padding-left:20px">${list.join("")}</ul>`);
    return out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[i]);
  };

  // ---------- config + auth (Supabase) ----------
  Kit.config = null;
  Kit.loadConfig = async () => (Kit.config = await (await fetch("/api/config")).json());
  const SKEY = "ao.session";
  if (location.hash.startsWith("#s=")) {
    try { LS.set(SKEY, JSON.stringify(JSON.parse(atob(decodeURIComponent(location.hash.slice(3)))))); } catch (_) {}
    history.replaceState(null, "", location.pathname + location.search);
  }
  const sess = () => { try { return JSON.parse(LS.get(SKEY, "null")); } catch (_) { return null; } };
  const sb = async (path, body, token) => {
    const c = Kit.config;
    const r = await fetch(`${c.supabase_url}/auth/v1/${path}`, {
      method: "POST", headers: { "Content-Type": "application/json", apikey: c.supabase_key, ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(body || {}),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.msg || j.error_description || j.message || `Auth error ${r.status}`);
    return j;
  };
  const saveSession = (j) => { const s = { access_token: j.access_token, refresh_token: j.refresh_token, expires_at: Date.now() + (j.expires_in || 3600) * 1000, user: j.user }; LS.set(SKEY, JSON.stringify(s)); return s; };
  Kit.user = () => (sess() || {}).user || null;
  Kit.token = async () => {
    let s = sess();
    if (!s) return null;
    if (s.access_token.startsWith("dev:")) return s.access_token;
    if (s.expires_at - Date.now() < 60000) {
      try { s = saveSession(await sb("token?grant_type=refresh_token", { refresh_token: s.refresh_token })); } catch (_) { Kit.signOutLocal(); return null; }
    }
    return s.access_token;
  };
  Kit.signOutLocal = () => LS.del(SKEY);
  Kit.signOut = async () => {
    const s = sess();
    if (s && !s.access_token.startsWith("dev:")) { try { await sb("logout", {}, s.access_token); } catch (_) {} }
    Kit.signOutLocal();
    location.reload();
  };

  Kit.requireAuth = () => new Promise((resolve) => {
    if (sess()) return resolve(sess());
    let mode = "in";
    const msg = h("div", { class: "auth-msg", hidden: true });
    const title = h("h1", null), sub = h("p", { class: "muted", style: { margin: 0 } });
    const name = h("input", { class: "input", placeholder: "Your name", autocomplete: "name" });
    const email = h("input", { class: "input", type: "email", placeholder: "you@company.com", required: true, autocomplete: "email" });
    const pass = h("input", { class: "input", type: "password", placeholder: "Password (min 6 characters)", required: true, minlength: 6, autocomplete: "current-password" });
    const nameField = h("label", { class: "field" }, "Name", name), submit = h("button", { class: "btn btn-primary", type: "submit" });
    const swap = h("button", { class: "swap", type: "button" });
    const forgot = h("button", { class: "swap", type: "button", style: { fontWeight: 500 } }, "Forgot password?");
    const say = (text, kind = "") => { msg.hidden = !text; msg.textContent = text || ""; msg.className = `auth-msg ${kind}`; };
    const paint = () => {
      title.innerHTML = mode === "in" ? 'Welcome <span class="grad-text">back</span>' : 'Create your <span class="grad-text">account</span>';
      sub.textContent = mode === "in" ? "Sign in to continue to your agents." : "One account for every agent in the office.";
      nameField.hidden = mode === "in"; submit.textContent = mode === "in" ? "Sign in" : "Create account"; forgot.hidden = mode !== "in";
      swap.textContent = mode === "in" ? "No account? Create one" : "Have an account? Sign in"; say("");
    };
    const form = h("form", { onsubmit: async (e) => {
      e.preventDefault(); submit.disabled = true; say("");
      try {
        if (mode === "in") {
          const s = saveSession(await sb("token?grant_type=password", { email: email.value.trim(), password: pass.value }));
          card.remove(); wrap.remove(); resolve(s);
        } else {
          const j = await sb("signup", { email: email.value.trim(), password: pass.value, data: { display_name: name.value.trim() || undefined } });
          if (j.access_token) { const s = saveSession(j); wrap.remove(); resolve(s); }
          else say("Almost there. Check your inbox and confirm your email, then sign in.", "ok");
        }
      } catch (err) { say(err.message, "bad"); } finally { submit.disabled = false; }
    } }, nameField, h("label", { class: "field" }, "Email", email), h("label", { class: "field" }, "Password", pass), msg, submit,
      h("div", { style: { display: "flex", justifyContent: "space-between" } }, swap, forgot));
    swap.onclick = () => { mode = mode === "in" ? "up" : "in"; paint(); };
    forgot.onclick = async () => { if (!email.value) return say("Enter your email first.", "bad"); try { await sb("recover", { email: email.value.trim() }); say("Password reset email sent.", "ok"); } catch (err) { say(err.message, "bad"); } };
    const dev = (email) => () => { LS.set(SKEY, JSON.stringify({ access_token: "dev:" + email, expires_at: Date.now() + 864e5, user: { id: "dev", email } })); wrap.remove(); resolve(sess()); };
    const devBtn = Kit.config && Kit.config.auth_mode === "dev" ? h("div", { style: { display: "grid", gap: "8px", marginTop: "14px" } },
      Kit.config.dev_admin_email ? h("button", { class: "btn", type: "button", onclick: dev(Kit.config.dev_admin_email) }, "Continue as admin (dev mode)") : null,
      h("button", { class: "btn", type: "button", onclick: dev("customer@example.com") }, "Continue as a customer (dev mode)")) : null;
    const card = h("div", { class: "panel auth-card" }, h("div", { class: "logo", style: { width: "48px", height: "48px", borderRadius: "15px", background: "var(--grad)", display: "grid", placeItems: "center", color: "#fff" }, html: Kit.icon("spark", "sparkle") }), title, sub, form, devBtn);
    const wrap = h("div", { class: "auth", role: "dialog", "aria-modal": "true", "aria-label": "Sign in" }, card);
    document.body.append(wrap);
    paint();
    setTimeout(() => email.focus(), 300);
  });

  // ---------- roles ----------
  Kit.go = (id) => { const s = sess(); location.href = Kit.apps[id] + (s ? "#s=" + encodeURIComponent(btoa(JSON.stringify(s))) : ""); };
  Kit.deniedScreen = () => {
    document.body.replaceChildren(h("div", { class: "aurora", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
      h("div", { class: "auth", style: { zIndex: 1 } }, h("div", { class: "panel auth-card" },
        h("h1", null, "Admins ", h("span", { class: "grad-text" }, "only")), h("p", { class: "muted" }, "This area is for the administrator. Customers can use the support chat."),
        h("div", { style: { display: "grid", gap: "10px", marginTop: "20px" } }, h("button", { class: "btn btn-primary", onclick: () => Kit.go("support") }, "Open the support chat"), h("button", { class: "btn", onclick: Kit.signOut }, "Sign out")))));
  };
  // Loads config, signs the user in, learns their role. `admin: true` shuts everyone else out of the page.
  Kit.boot = async ({ admin = false } = {}) => {
    await Kit.loadConfig();
    await Kit.requireAuth();
    const me = await Kit.api("/api/me");
    Kit.me = me; Kit.isAdmin = !!me.is_admin;
    if (admin && !Kit.isAdmin) { Kit.deniedScreen(); return null; }
    return me;
  };

  // ---------- API + SSE ----------
  Kit.api = async (path, { method = "GET", body, form, raw } = {}) => {
    const token = await Kit.token();
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const r = await fetch(path, { method, headers, body: form || (body !== undefined ? JSON.stringify(body) : undefined) });
    if (r.status === 401) { Kit.signOutLocal(); location.reload(); throw new Error("Session expired"); }
    if (raw) return r;
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || j.message || `Request failed (${r.status})`);
    return j;
  };
  Kit.stream = async (path, body, onEvent, signal) => {
    const r = await Kit.api(path, { method: "POST", body, raw: true });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || `Request failed (${r.status})`); }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      if (signal && signal.aborted) { reader.cancel(); break; }
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data:"));
        if (line) { try { onEvent(JSON.parse(line.slice(5).trim())); } catch (_) {} }
      }
    }
  };

  // ---------- app shell (rail + topbar) ----------
  Kit.shell = ({ active, title, subtitle }) => {
    const items = [["office", "Agent Office (home)", "building"], ["perf", "Observability", "gauge"], ["iac", "Infrastructure agent", "cloud"], ["cicd", "CI/CD agent", "rocket"], ["support", "Support chat (customer view)", "chat"]];
    const aurora = h("div", { class: "aurora", "aria-hidden": "true" }, h("i"), h("i"), h("i"));
    const themeBtn = h("button", { class: "btn btn-icon", title: "Toggle theme", "aria-label": "Toggle theme", onclick: () => { Kit.setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"); themeBtn.innerHTML = Kit.icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon"); } });
    themeBtn.innerHTML = Kit.icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon");
    const rail = h("nav", { class: "rail", "aria-label": "Admin console" },
      h("div", { class: "logo", html: Kit.icon("spark", "sparkle") }),
      ...items.map(([id, label, ic]) => h("a", { class: "rail-item", href: Kit.apps[id], onclick: (e) => { if (id !== active) { e.preventDefault(); Kit.go(id); } else e.preventDefault(); }, "aria-label": label, ...(id === active ? { "aria-current": "page" } : {}), html: Kit.icon(ic) + `<span class="tip">${label}</span>` })),
      h("div", { class: "spacer" }));
    const right = h("div", { class: "right" });
    const u = Kit.user();
    if (u) {
      const out = h("button", { class: "btn btn-icon", title: `Sign out ${u.email || ""}`, "aria-label": "Sign out", onclick: Kit.signOut, html: Kit.icon("logout") });
      right.append(h("span", { class: "badge", title: u.email }, (u.email || "user").split("@")[0]), themeBtn, out);
    } else right.append(themeBtn);
    const page = h("main", { class: "page", id: "page" });
    const solo = !Kit.isAdmin; // customers see just their app: no console, no links to internal tools
    const brand = solo ? h("span", { class: "brand-mini", html: Kit.icon("spark", "sparkle") }) : null;
    const top = h("header", { class: "topbar" }, h("div", { style: { display: "flex", alignItems: "center", gap: "12px" } }, brand, h("div", null, h("h1", null, title), subtitle ? h("p", null, subtitle) : null)), right);
    document.body.replaceChildren(aurora, h("div", { class: `shell${solo ? " solo" : ""}` }, solo ? null : rail, h("div", { class: "main" }, top, page)));
    return { page, right, top };
  };

  Kit.tabs = (items, onChange, initial = 0) => {
    const ind = h("span", { class: "ind" });
    const el = h("div", { class: "tabs", role: "tablist" }, ind);
    const btns = items.map((label, i) => h("button", { role: "tab", onclick: () => select(i) }, label));
    el.append(...btns);
    const select = (i) => {
      btns.forEach((b, j) => b.setAttribute("aria-selected", String(i === j)));
      ind.style.left = btns[i].offsetLeft + "px"; ind.style.width = btns[i].offsetWidth + "px";
      onChange && onChange(i, items[i]);
    };
    requestAnimationFrame(() => select(initial));
    el.select = select;
    return el;
  };

  // ---------- charts (SVG, animated) ----------
  const COLORS = ["var(--a1)", "var(--a2)", "var(--a3)", "var(--info)"];
  Kit.charts = {
    colors: COLORS,
    bar(labels, series, { height = 180 } = {}) {
      const W = 360, H = height, pad = { l: 34, r: 8, t: 10, b: 24 };
      const max = Math.max(1, ...series.flatMap((s) => s.values)) * 1.1, bw = (W - pad.l - pad.r) / labels.length;
      let g = "";
      for (let t = 0; t <= 4; t++) { const y = pad.t + ((H - pad.t - pad.b) * t) / 4; g += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" stroke="var(--border)" stroke-dasharray="3 4"/><text x="${pad.l - 6}" y="${y + 4}" text-anchor="end">${Kit.fmt.n(max * (1 - t / 4), max < 10 ? 1 : 0)}</text>`; }
      series.forEach((s, si) => s.values.forEach((v, i) => {
        const w = (bw * 0.72) / series.length, x = pad.l + i * bw + bw * 0.14 + si * w, hh = ((H - pad.t - pad.b) * v) / max;
        g += `<rect class="bar" style="--i:${i}" x="${x}" y="${H - pad.b - hh}" width="${w - 2}" height="${hh}" rx="4" fill="${COLORS[si % 4]}"><title>${esc(s.name)} · ${esc(labels[i])}: ${v}</title></rect>`;
      }));
      const lstep = Math.ceil(labels.length / 6);
      labels.forEach((l, i) => i % lstep === 0 && (g += `<text x="${pad.l + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${esc(String(l).slice(0, 8))}</text>`));
      return Kit.charts._wrap(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`, series);
    },
    line(labels, series, { height = 180, area = true } = {}) {
      const W = 360, H = height, pad = { l: 34, r: 10, t: 10, b: 24 };
      const max = Math.max(1, ...series.flatMap((s) => s.values)) * 1.1, n = Math.max(1, labels.length - 1);
      const X = (i) => pad.l + ((W - pad.l - pad.r) * i) / n, Y = (v) => H - pad.b - ((H - pad.t - pad.b) * v) / max;
      let g = "";
      for (let t = 0; t <= 4; t++) { const y = pad.t + ((H - pad.t - pad.b) * t) / 4; g += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" stroke="var(--border)" stroke-dasharray="3 4"/><text x="${pad.l - 6}" y="${y + 4}" text-anchor="end">${Kit.fmt.n(max * (1 - t / 4), max < 10 ? 1 : 0)}</text>`; }
      series.forEach((s, si) => {
        const pts = s.values.map((v, i) => `${X(i)},${Y(v)}`), d = "M" + pts.join(" L");
        if (area && s.values.length > 1) g += `<path class="area" d="${d} L${X(s.values.length - 1)},${H - pad.b} L${X(0)},${H - pad.b}Z" fill="${COLORS[si % 4]}" opacity=".12"/>`;
        g += `<path class="line" style="--len:2000" d="${d}" fill="none" stroke="${COLORS[si % 4]}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;
        s.values.length < 40 && s.values.forEach((v, i) => (g += `<circle cx="${X(i)}" cy="${Y(v)}" r="3" fill="${COLORS[si % 4]}"><title>${esc(s.name)} · ${esc(labels[i])}: ${v}</title></circle>`));
      });
      const step = Math.ceil(labels.length / 6);
      labels.forEach((l, i) => i % step === 0 && (g += `<text x="${X(i)}" y="${H - 6}" text-anchor="middle">${esc(String(l).slice(0, 8))}</text>`));
      return Kit.charts._wrap(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`, series);
    },
    donut(labels, series) {
      const vals = series[0].values, total = vals.reduce((a, b) => a + b, 0) || 1, R = 62, C = 2 * Math.PI * R;
      let off = 0, g = "";
      vals.forEach((v, i) => {
        const len = (v / total) * C;
        g += `<circle cx="90" cy="90" r="${R}" fill="none" stroke="${COLORS[i % 4]}" stroke-width="22" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 90 90)" style="transition: stroke-dasharray 1s var(--ease)"><title>${esc(labels[i])}: ${v}</title></circle>`;
        off += len;
      });
      g += `<text x="90" y="96" text-anchor="middle" style="font-size:20px;font-weight:700;fill:var(--text)">${Kit.fmt.n(total, total < 10 ? 1 : 0)}</text>`;
      const el = h("div", null, h("div", { html: `<svg class="chart" viewBox="0 0 180 180" style="max-width:200px;display:block;margin:auto" role="img">${g}</svg>` }));
      el.append(h("div", { class: "legend", style: { justifyContent: "center" }, html: labels.map((l, i) => `<span><i style="background:${COLORS[i % 4]}"></i>${esc(l)}</span>`).join("") }));
      return el;
    },
    spark(values, { w = 120, h: hh = 32, color = "var(--a2)" } = {}) {
      const max = Math.max(...values, 1), min = Math.min(...values, 0), n = Math.max(1, values.length - 1);
      const pts = values.map((v, i) => `${(w * i) / n},${hh - 3 - ((hh - 6) * (v - min)) / (max - min || 1)}`);
      return h("span", { html: `<svg width="${w}" height="${hh}" viewBox="0 0 ${w} ${hh}"><path class="line" style="--len:400;stroke-dasharray:400;stroke-dashoffset:400;animation:draw 1s var(--ease) forwards" d="M${pts.join(" L")}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round"/></svg>` });
    },
    _wrap(svg, series) {
      const el = h("div", { html: svg });
      if (series.length > 1 || (series[0] && series[0].name)) el.append(h("div", { class: "legend", html: series.map((s, i) => `<span><i style="background:${COLORS[i % 4]}"></i>${esc(s.name)}</span>`).join("") }));
      return el;
    },
  };

  // ---------- generative UI renderer ----------
  const VARIANTS = ["rise", "blur", "slide", "flip", "zoom", "fan"];
  Kit.blocks = {
    render(payload, { onAction } = {}) {
      const wrap = h("div", { class: "blocks" });
      (payload.blocks || []).forEach((b, i) => {
        const node = (Kit.blocks[b.type] || (() => null))(b, { onAction });
        if (!node) return;
        node.classList.add("in", "in-" + pick(VARIANTS));
        node.style.setProperty("--i", i);
        wrap.append(node);
      });
      return wrap;
    },
    card(b, { onAction }) {
      const acts = (b.actions || []).map((a) => h("button", { class: "btn btn-sm", onclick: () => onAction && onAction(a.prompt || a.label) }, a.label));
      return h("div", { class: `blk blk-card ${b.tone || "info"}` },
        h("div", { class: "t" }, h("span", { class: "ic" }, b.icon || "✨"), b.title),
        b.body ? h("div", { class: "muted", html: Kit.md(b.body) }) : null, acts.length ? h("div", { class: "acts" }, acts) : null);
    },
    steps(b) {
      return h("div", { class: "blk" }, b.title ? h("div", { class: "t" }, b.title) : null,
        h("ol", { class: "steps" }, ...b.steps.map((s, i) => h("li", { class: s.status }, h("span", { class: "n" }, s.status === "done" ? "✓" : i + 1), h("div", null, h("div", null, s.label), s.detail ? h("div", { class: "d" }, s.detail) : null)))));
    },
    table(b) {
      return h("div", { class: "blk" }, b.title ? h("div", { class: "t" }, b.title) : null,
        h("div", { class: "tblwrap" }, h("table", { class: "tbl" }, h("thead", null, h("tr", null, ...b.columns.map((c) => h("th", null, c)))), h("tbody", null, ...b.rows.map((r) => h("tr", null, ...r.map((c) => h("td", null, c))))))));
    },
    chart(b) {
      const f = Kit.charts[b.kind] || Kit.charts.bar;
      return h("div", { class: "blk" }, b.title ? h("div", { class: "t" }, b.title) : null, f(b.labels, b.series));
    },
    stats(b) {
      return h("div", { class: "blk" }, h("div", { class: "stats" }, ...b.items.map((s) => h("div", { class: "stat" }, h("div", { class: "l" }, s.label), h("div", { class: "v" }, Kit.odo(s.value)), s.delta ? h("div", { class: `dl ${s.tone === "success" ? "ok" : s.tone === "danger" ? "bad" : s.tone === "warning" ? "warn" : ""}` }, s.delta) : null))));
    },
    code(b) {
      const pre = h("pre", { class: "code" }, b.code);
      const copy = h("button", { onclick: async () => { try { await navigator.clipboard.writeText(b.code); copy.textContent = "Copied"; setTimeout(() => (copy.textContent = "Copy"), 1400); } catch (_) {} } }, "Copy");
      return h("div", { class: "blk" }, h("div", { class: "codebar" }, h("span", null, b.filename || b.language || "code"), copy), pre);
    },
    checklist(b) {
      return h("div", { class: "blk" }, b.title ? h("div", { class: "t" }, b.title) : null, ...b.items.map((it) => h("div", { class: `check ${it.done ? "done" : ""}` }, h("span", { class: "bx", html: it.done ? Kit.icon("check") : "" }), h("span", null, it.text))));
    },
  };

  // ---------- speech: browser (Edge) voices out, Gemini-powered speech-to-text in ----------
  Kit.tts = {
    enabled: LS.get("ao.tts", "1") !== "0",
    set(on) { this.enabled = on; LS.set("ao.tts", on ? "1" : "0"); if (!on) this.stop(); },
    voice() {
      const v = (window.speechSynthesis && speechSynthesis.getVoices()) || [];
      const en = v.filter((x) => /^en/i.test(x.lang));
      return en.find((x) => /Microsoft.*(Online|Natural)/i.test(x.name)) || en.find((x) => /Microsoft/i.test(x.name)) || en.find((x) => /Google|Samantha|Aria|Jenny/i.test(x.name)) || en[0] || null;
    },
    speak(text) {
      if (!this.enabled || !("speechSynthesis" in window)) return;
      this.stop();
      const clean = String(text).replace(/```[\s\S]*?```/g, " code block ").replace(/[*_`#>]/g, "").replace(/\s+/g, " ").trim();
      if (!clean) return;
      const u = new SpeechSynthesisUtterance(clean.slice(0, 900));
      const v = this.voice(); if (v) u.voice = v; u.rate = 1.02;
      speechSynthesis.speak(u);
    },
    stop() { if ("speechSynthesis" in window) speechSynthesis.cancel(); },
  };
  Kit.stt = {
    rec: null, chunks: [], stream: null,
    supported: () => !!(navigator.mediaDevices && window.MediaRecorder),
    async start() {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
      this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
      this.chunks = [];
      this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
      this.rec.start();
    },
    // MediaRecorder gives webm/opus; Gemini is most reliable with plain WAV, so decode and re-encode 16 kHz mono PCM here.
    async toWav(blob) {
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      const buf = await ac.decodeAudioData(await blob.arrayBuffer());
      ac.close();
      const rate = 16000, len = Math.ceil(buf.duration * rate);
      const off = new OfflineAudioContext(1, len, rate), src = off.createBufferSource();
      src.buffer = buf; src.connect(off.destination); src.start();
      const pcm = (await off.startRendering()).getChannelData(0);
      const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
      const w = (o, s) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
      w(0, "RIFF"); out.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVEfmt "); out.setUint32(16, 16, true); out.setUint16(20, 1, true);
      out.setUint16(22, 1, true); out.setUint32(24, rate, true); out.setUint32(28, rate * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
      w(36, "data"); out.setUint32(40, pcm.length * 2, true);
      pcm.forEach((v, i) => out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true));
      return new Blob([out], { type: "audio/wav" });
    },
    stop() {
      return new Promise((resolve, reject) => {
        if (!this.rec) return reject(new Error("Not recording"));
        this.rec.onstop = async () => {
          this.stream.getTracks().forEach((t) => t.stop());
          try {
            const wav = await this.toWav(new Blob(this.chunks, { type: this.rec.mimeType || "audio/webm" }));
            const form = new FormData();
            form.append("audio", wav, "speech.wav");
            resolve((await Kit.api("/api/stt", { method: "POST", form })).text || "");
          } catch (e) { reject(e); }
        };
        this.rec.stop();
      });
    },
  };

  Kit.copy = async (t) => { try { await navigator.clipboard.writeText(t); Kit.toast("Copied", { kind: "ok", ms: 1600 }); } catch (_) {} };
})();
