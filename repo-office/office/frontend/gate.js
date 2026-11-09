/*
 * Admin gate for the Agent Office. Loaded before office.js and does not touch the office's own code or styles:
 *  - asks the admin to sign in (Supabase) and refuses everyone else,
 *  - adds the session token to same-origin fetch() calls and to the live event stream,
 *  - adds a small "Admin console" menu to jump to the other apps (Performance, Infrastructure, CI/CD, Support),
 *  - then loads office.js.
 * Everything here is namespaced "ao-" so it cannot collide with the office.
 */
(() => {
  const KEY = "ao.session";
  const APPS = Object.assign({ perf: "http://localhost:8400", iac: "http://localhost:8100", cicd: "http://localhost:8300", support: "http://localhost:8000" }, window.AO_APPS || {});
  const store = {
    get: () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (_) { return null; } },
    set: (v) => { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (_) {} },
    clear: () => { try { localStorage.removeItem(KEY); } catch (_) {} },
  };
  let cfg = null;

  // ---- one-time hand-off from another app (session arrives in the URL fragment, then is removed) ----
  if (location.hash.startsWith("#s=")) {
    try { store.set(JSON.parse(atob(decodeURIComponent(location.hash.slice(3))))); } catch (_) {}
    history.replaceState(null, "", location.pathname + location.search);
  }

  const css = `
  .ao-gate{position:fixed;inset:0;z-index:9999;display:grid;place-items:center;padding:20px;background:#0a0c16;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:#eef0ff}
  .ao-card{width:min(420px,100%);padding:30px;border-radius:18px;background:#141830;border:1px solid rgba(255,255,255,.12);box-shadow:0 30px 80px -20px #000}
  .ao-card h1{margin:12px 0 4px;font-size:24px}.ao-card p{margin:0 0 18px;color:#9ba2c4}
  .ao-logo{width:46px;height:46px;border-radius:14px;background:linear-gradient(135deg,#7c5cff,#22d3b6)}
  .ao-card label{display:grid;gap:6px;font-size:13px;color:#9ba2c4;margin-bottom:12px}
  .ao-card input{padding:11px 14px;border-radius:12px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.06);color:#eef0ff;font:inherit}
  .ao-card input:focus{outline:2px solid #22d3b6;outline-offset:-1px}
  .ao-btn{width:100%;padding:11px;border-radius:12px;border:0;font:inherit;font-weight:600;cursor:pointer;color:#fff;background:linear-gradient(135deg,#7c5cff,#22d3b6)}
  .ao-btn.ghost{background:transparent;border:1px solid rgba(255,255,255,.18);margin-top:10px}.ao-btn:disabled{opacity:.5}
  .ao-msg{margin:0 0 12px;padding:9px 12px;border-radius:10px;font-size:13.5px;background:rgba(251,113,133,.12);color:#fb7185}
  .ao-menu{position:fixed;left:14px;bottom:14px;z-index:9000;font:13px system-ui,sans-serif}
  .ao-menu button.ao-pill{display:flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;border:1px solid rgba(255,255,255,.2);background:rgba(20,24,48,.92);color:#eef0ff;cursor:pointer;backdrop-filter:blur(10px);box-shadow:0 8px 24px rgba(0,0,0,.35)}
  .ao-menu .ao-list{position:absolute;left:0;bottom:44px;min-width:230px;padding:8px;border-radius:14px;background:rgba(20,24,48,.97);border:1px solid rgba(255,255,255,.14);box-shadow:0 18px 40px rgba(0,0,0,.45);display:none}
  .ao-menu.open .ao-list{display:grid;gap:2px}
  .ao-menu a,.ao-menu .ao-out{display:block;padding:8px 10px;border-radius:9px;color:#eef0ff;text-decoration:none;background:none;border:0;text-align:left;font:inherit;cursor:pointer}
  .ao-menu a:hover,.ao-menu .ao-out:hover{background:rgba(255,255,255,.09)}
  .ao-menu small{display:block;color:#9ba2c4;padding:4px 10px 6px}
  `;
  document.head.append(Object.assign(document.createElement("style"), { textContent: css }));
  const el = (t, props, ...kids) => { const n = Object.assign(document.createElement(t), props || {}); kids.forEach((k) => n.append(k)); return n; };

  async function sb(path, body) {
    const r = await fetch(`${cfg.supabase_url}/auth/v1/${path}`, { method: "POST", headers: { "Content-Type": "application/json", apikey: cfg.supabase_key }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.msg || j.error_description || j.message || `Sign-in failed (${r.status})`);
    return j;
  }
  const saveSb = (j) => { const s = { access_token: j.access_token, refresh_token: j.refresh_token, expires_at: Date.now() + (j.expires_in || 3600) * 1000, user: j.user }; store.set(s); return s; };

  const nativeFetch = window.fetch.bind(window);
  async function token() {
    let s = store.get();
    if (!s) return null;
    if (!s.access_token.startsWith("dev:") && s.expires_at - Date.now() < 60000) {
      try { s = saveSb(await sb("token?grant_type=refresh_token", { refresh_token: s.refresh_token })); } catch (_) { store.clear(); return null; }
    }
    return s.access_token;
  }
  const tokenSync = () => (store.get() || {}).access_token;

  async function me() {
    const t = await token();
    if (!t) return null;
    const r = await nativeFetch("/api/me", { headers: { Authorization: `Bearer ${t}` } });
    return r.ok ? r.json() : null;
  }

  function overlay(message) {
    return new Promise((resolve) => {
      const msg = el("div", { className: "ao-msg", hidden: !message, textContent: message || "" });
      const email = el("input", { type: "email", required: true, placeholder: "admin@company.com", autocomplete: "email" });
      const pass = el("input", { type: "password", required: true, placeholder: "Password", autocomplete: "current-password" });
      const go = el("button", { className: "ao-btn", type: "submit", textContent: "Sign in" });
      const form = el("form", {}, msg, el("label", { textContent: "Email" }, email), el("label", { textContent: "Password" }, pass), go);
      form.onsubmit = async (e) => {
        e.preventDefault(); go.disabled = true; msg.hidden = true;
        try { saveSb(await sb("token?grant_type=password", { email: email.value.trim(), password: pass.value })); wrap.remove(); resolve(); }
        catch (err) { msg.textContent = err.message; msg.hidden = false; } finally { go.disabled = false; }
      };
      const card = el("div", { className: "ao-card" }, el("div", { className: "ao-logo" }), el("h1", { textContent: "Agent Office" }), el("p", { textContent: "Admin console. Sign in to see your agents at work." }), form);
      if (cfg.auth_mode === "dev" && cfg.dev_admin_email) {
        card.append(el("button", { className: "ao-btn ghost", type: "button", textContent: "Continue as admin (dev mode)", onclick: () => { store.set({ access_token: `dev:${cfg.dev_admin_email}`, expires_at: Date.now() + 864e5, user: { id: "dev", email: cfg.dev_admin_email } }); wrap.remove(); resolve(); } }));
      }
      const wrap = el("div", { className: "ao-gate", role: "dialog", "aria-modal": "true", "aria-label": "Admin sign in" }, card);
      document.body.append(wrap);
      email.focus();
    });
  }

  function denied(who) {
    const wrap = el("div", { className: "ao-gate" }, el("div", { className: "ao-card" }, el("div", { className: "ao-logo" }), el("h1", { textContent: "Admins only" }),
      el("p", { textContent: `${who || "This account"} is not an administrator. Customers can use the support chat instead.` }),
      el("button", { className: "ao-btn", textContent: "Open the support chat", onclick: () => (location.href = APPS.support) }),
      el("button", { className: "ao-btn ghost", textContent: "Sign out", onclick: () => { store.clear(); location.reload(); } })));
    document.body.append(wrap);
  }

  function installAuth() {
    window.fetch = async (input, init = {}) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.startsWith("/") || url.startsWith(location.origin) || Object.values(APPS).some((a) => url.startsWith(a))) {
        const t = await token();
        init = { ...init, headers: { ...(init.headers || {}), ...(t ? { Authorization: `Bearer ${t}` } : {}) } };
      }
      return nativeFetch(input, init);
    };
    // EventSource cannot set headers: reconnect ourselves with a fresh token and resume from the last event id.
    const Native = window.EventSource;
    window.EventSource = class AuthEventSource {
      constructor(url) {
        this.url = url; this.last = 0; this.closed = false; this.readyState = 0;
        this.connect();
      }
      connect() {
        const sep = this.url.includes("?") ? "&" : "?";
        const es = (this.es = new Native(`${this.url}${sep}access_token=${encodeURIComponent(tokenSync() || "")}&last_event_id=${this.last}`));
        es.onopen = (e) => { this.readyState = 1; this.onopen && this.onopen(e); };
        es.onmessage = (e) => { if (e.lastEventId) this.last = Number(e.lastEventId); this.onmessage && this.onmessage(e); };
        es.onerror = (e) => {
          this.readyState = 0; this.onerror && this.onerror(e);
          es.close();
          if (!this.closed) setTimeout(async () => { await token(); if (!this.closed) this.connect(); }, 2000);
        };
      }
      close() { this.closed = true; this.es && this.es.close(); }
    };
  }

  function menu(user) {
    const wrap = el("div", { className: "ao-menu" });
    const hand = (base) => `${base}#s=${encodeURIComponent(btoa(JSON.stringify(store.get())))}`; // one sign-in for every app
    const link = (label, base, hint) => { const a = el("a", { href: base, textContent: label }); a.onclick = (e) => { e.preventDefault(); location.href = hand(base); }; if (hint) a.title = hint; return a; };
    const list = el("div", { className: "ao-list" }, el("small", { textContent: user.email || "admin" }),
      link("Observability", APPS.perf, "Health, delivery, drift, dashboards, LLM"), link("Infrastructure agent", APPS.iac, "Terraform on any cloud"),
      link("CI/CD agent", APPS.cicd, "Reviews and pipelines"), link("Support chat (customer view)", APPS.support),
      el("button", { className: "ao-out", textContent: "Sign out", onclick: () => { store.clear(); location.reload(); } }));
    const pill = el("button", { className: "ao-pill", textContent: "Admin console ▴" });
    pill.onclick = () => wrap.classList.toggle("open");
    wrap.append(list, pill);
    document.body.append(wrap);
  }

  async function boot() {
    cfg = await (await nativeFetch("/api/config")).json();
    let user = await me();
    if (!user) { await overlay(); user = await me(); }
    if (!user) return location.reload();
    if (!user.is_admin) return denied(user.email);
    installAuth();
    window.AO_OPEN = (base) => window.open(`${base}#s=${encodeURIComponent(btoa(JSON.stringify(store.get())))}`, "_blank", "noopener");
    menu(user);
    document.body.append(el("script", { src: "office.js" }));
  }
  boot().catch((e) => { document.body.append(el("p", { textContent: `Could not start: ${e.message}` })); });
})();
