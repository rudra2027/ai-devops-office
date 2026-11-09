(() => {
  const CFG = window.OFFICE_CONFIG;
  const floor = document.getElementById("floor");
  const connEl = document.getElementById("conn");
  const desks = new Map(); // "team/member" -> desk record
  const teams = new Map(); // team id -> {el, def, stat}
  const log = []; // every event seen, newest last
  const key = (t, m) => `${t}/${m}`;
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let wires, runners, live = false, filter = null, eventsSeen = 0, activeCalls = 0;

  // ---------- helpers ----------
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const SKIN = ["#f1c9a5", "#e0a981", "#c68863", "#8d5a3c", "#f6d7bd"];
  const HAIR = ["#2b2118", "#6b3f1d", "#c27a2c", "#1a1a1f", "#9a9a9a", "#7a2e2e"];
  const fmt = (ts) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const look = (id) => {
    const h = hash(id);
    return { skin: SKIN[h % SKIN.length], hair: HAIR[(h >> 3) % HAIR.length], long: (h >> 5) % 3 === 0 };
  };
  // Overlays that fake volume on any flat shape (gradients live in index.html).
  const vol = (shape) => `${shape.replace("/>", ' fill="url(#g-shine)"/>')}${shape.replace("/>", ' fill="url(#g-shade-r)"/>')}`;

  // ---------- figures ----------
  function seatedSvg(id, accent) {
    const { skin, hair, long } = look(id);
    return `
<svg class="person" viewBox="0 0 140 112" aria-hidden="true">
  <ellipse cx="70" cy="107" rx="62" ry="5" fill="#000" opacity=".13"/>
  <g class="chair">
    <rect x="43" y="88" width="5" height="15" fill="#2c2f38"/>
    <path d="M26 103 h40" stroke="#2c2f38" stroke-width="4" stroke-linecap="round"/>
    <circle cx="26" cy="105" r="3" fill="#15171c"/><circle cx="66" cy="105" r="3" fill="#15171c"/>
    <rect x="21" y="46" width="30" height="42" rx="13" fill="#3d4352"/>
    <rect x="21" y="46" width="30" height="42" rx="13" fill="url(#g-shade-r)"/>
    <rect x="24" y="52" width="3.5" height="28" rx="2" fill="#fff" opacity=".14"/>
    <rect x="30" y="80" width="40" height="9" rx="4.5" fill="#4a5163"/>
    <rect x="30" y="80" width="40" height="9" rx="4.5" fill="url(#g-shade-b)"/>
  </g>
  <g class="body">
    <path d="M28 84 q-2-30 22-30 q24 0 22 30z" fill="${accent}"/>
    <path d="M28 84 q-2-30 22-30 q24 0 22 30z" fill="url(#g-shine)"/>
    <path d="M28 84 q-2-30 22-30 q24 0 22 30z" fill="url(#g-shade-r)"/>
    <path d="M44 55 l6 11 l6 -11z" fill="#fff" opacity=".92"/>
    <path d="M46 57 l4 21 l4 -21" stroke="#f1c40f" stroke-width="1.6" fill="none"/>
    <g class="head">
      <rect x="45.5" y="44" width="9" height="13" rx="3.5" fill="${skin}"/>
      <rect x="45.5" y="44" width="9" height="13" rx="3.5" fill="url(#g-shade-b)"/>
      ${long ? `<rect x="33" y="19" width="34" height="38" rx="15" fill="${hair}"/><rect x="33" y="19" width="34" height="38" rx="15" fill="url(#g-shade-r)"/>` : ""}
      <ellipse cx="36.5" cy="37" rx="2.6" ry="4.2" fill="${skin}"/>
      <circle cx="50" cy="35" r="14.5" fill="${skin}"/>
      <circle cx="50" cy="35" r="14.5" fill="url(#g-shine)"/>
      <circle cx="50" cy="35" r="14.5" fill="url(#g-shade-r)"/>
      <path d="M35 33 q15-25 30 0 q-3-9-15-9 q-12 0-15 9z" fill="${hair}"/>
      <path d="M40 27 q8-6 17-1" stroke="#fff" stroke-width="2" opacity=".22" fill="none" stroke-linecap="round"/>
      <path d="M42 30.5 q3-2 6 0 M54 30.5 q3-2 6 0" stroke="${hair}" stroke-width="1.3" fill="none" stroke-linecap="round"/>
      <g class="eyes"><ellipse cx="45.5" cy="35" rx="1.8" ry="2.3" fill="#1d1d22"/><ellipse cx="56.5" cy="35" rx="1.8" ry="2.3" fill="#1d1d22"/></g>
      <path d="M50 37 q1.5 3 -.5 4" stroke="#000" stroke-width="1" opacity=".18" fill="none"/>
      <ellipse class="mouth" cx="51" cy="42.5" rx="3" ry="1" fill="#7a3b3b"/>
    </g>
    <g class="arm arm-l"><rect x="56" y="62" width="35" height="9" rx="4.5" fill="${accent}"/><rect x="56" y="62" width="35" height="9" rx="4.5" fill="url(#g-shade-b)"/><circle cx="92" cy="67" r="4.6" fill="${skin}"/></g>
    <g class="arm arm-r"><rect x="58" y="68" width="30" height="9" rx="4.5" fill="${accent}" opacity=".93"/><rect x="58" y="68" width="30" height="9" rx="4.5" fill="url(#g-shade-b)"/><circle cx="89" cy="73" r="4.6" fill="${skin}"/></g>
    <g class="phone">
      <rect x="62" y="26" width="7" height="18" rx="3.5" fill="#222" transform="rotate(18 65 35)"/>
      <path class="wave wave1" d="M73 28 q6 8 0 16" stroke="#555" stroke-width="2" fill="none" stroke-linecap="round"/>
      <path class="wave wave2" d="M78 24 q9 12 0 24" stroke="#555" stroke-width="2" fill="none" stroke-linecap="round"/>
    </g>
  </g>
  <rect x="8" y="76" width="126" height="7" rx="2" fill="url(#g-wood)"/>
  <rect x="8" y="76" width="126" height="1.8" fill="#fff" opacity=".4"/>
  <rect x="14" y="83" width="114" height="21" rx="2" fill="#a67c52"/>
  <rect x="14" y="83" width="114" height="21" rx="2" fill="url(#g-shade-b)"/>
  <rect x="20" y="88" width="42" height="12" rx="1.5" fill="#000" opacity=".1"/>
  <rect x="36" y="93" width="10" height="2.2" rx="1" fill="#e6cf95"/>
  <ellipse class="glow" cx="104" cy="77" rx="26" ry="3.5" fill="#7fd0ff"/>
  <rect x="82" y="38" width="50" height="36" rx="3.5" fill="url(#g-bezel)"/>
  <rect class="screen" x="85" y="41" width="44" height="28" rx="2"/>
  <path d="M85 41 h20 l-12 28 h-8z" fill="#fff" opacity=".1"/>
  <rect x="104" y="74" width="6" height="3" fill="#20232b"/>
  <rect x="70" y="73" width="24" height="3.2" rx="1.2" fill="#e8e4da"/>
  <rect x="62" y="67" width="9" height="9" rx="1.5" fill="#fff" stroke="#c9bfa8"/>
  <path class="steam" d="M65 64 q-2-4 0-7 M69 64 q-2-4 0-7" stroke="#aaa" stroke-width="1.5" fill="none" stroke-linecap="round"/>
</svg>`;
  }

  // A full-body figure. `.walking` on the svg animates the gait; visitors reuse it standing.
  function walkerSvg(accent, id, { carry = false, walking = false } = {}) {
    const { skin, hair, long } = look(id);
    return `
<svg class="walker${walking ? " walking" : ""}" viewBox="0 0 60 100" aria-hidden="true">
  <ellipse cx="30" cy="96" rx="17" ry="4" fill="#000" opacity=".22"/>
  <g class="fig">
    <g class="limb leg-b" style="transform-origin:34px 58px">
      <rect x="30" y="56" width="9" height="33" rx="4.5" fill="#2f3441"/><rect x="30" y="56" width="9" height="33" rx="4.5" fill="url(#g-shade-r)"/>
      <ellipse cx="35" cy="91" rx="7" ry="4" fill="#14161b"/>
    </g>
    <g class="limb leg-a" style="transform-origin:26px 58px">
      <rect x="21" y="56" width="9" height="33" rx="4.5" fill="#3b4150"/><rect x="21" y="56" width="9" height="33" rx="4.5" fill="url(#g-shade-r)"/>
      <ellipse cx="25" cy="91" rx="7" ry="4" fill="#1b1d23"/>
    </g>
    <g class="limb arm-b" style="transform-origin:43px 38px">
      <rect x="39" y="35" width="8" height="26" rx="4" fill="${accent}"/><rect x="39" y="35" width="8" height="26" rx="4" fill="url(#g-shade-r)"/>
      <circle cx="43" cy="63" r="4.2" fill="${skin}"/>
    </g>
    <g class="limb arm-a" style="transform-origin:17px 38px">
      <rect x="13" y="35" width="8" height="26" rx="4" fill="${accent}"/><rect x="13" y="35" width="8" height="26" rx="4" fill="url(#g-shade-b)"/>
      <circle cx="17" cy="63" r="4.2" fill="${skin}"/>
    </g>
    <path d="M15 37 q15-9 30 0 l2 27 q-17 6-34 0z" fill="${accent}"/>
    <path d="M15 37 q15-9 30 0 l2 27 q-17 6-34 0z" fill="url(#g-shine)"/>
    <path d="M15 37 q15-9 30 0 l2 27 q-17 6-34 0z" fill="url(#g-shade-r)"/>
    <path d="M25 36 l5 8 l5 -8z" fill="#fff" opacity=".9"/>
    <rect x="28.8" y="44" width="2.4" height="12" fill="#f1c40f"/>
    ${carry ? `<g transform="rotate(-6 30 56)"><rect x="21" y="50" width="18" height="12" rx="1.5" fill="#fff" stroke="#c9bfa8"/><path d="M21 51 l9 6 l9 -6" stroke="#c9bfa8" fill="none"/></g>` : ""}
    <rect x="27" y="29" width="6" height="8" rx="3" fill="${skin}"/>
    ${long ? `<rect x="18" y="8" width="24" height="30" rx="11" fill="${hair}"/>` : ""}
    <circle cx="30" cy="20" r="11" fill="${skin}"/>
    <circle cx="30" cy="20" r="11" fill="url(#g-shine)"/>
    <circle cx="30" cy="20" r="11" fill="url(#g-shade-r)"/>
    <path d="M19 18 q11-19 22 0 q-3-7-11-7 q-8 0-11 7z" fill="${hair}"/>
    <ellipse cx="26" cy="21" rx="1.3" ry="1.7" fill="#1d1d22"/><ellipse cx="34" cy="21" rx="1.3" ry="1.7" fill="#1d1d22"/>
    <path d="M27 26 q3 2 6 0" stroke="#7a3b3b" stroke-width="1.2" fill="none" stroke-linecap="round"/>
  </g>
</svg>`;
  }

  const plantSvg = (cls) => {
    const s = el("div", `plant ${cls}`);
    s.innerHTML = `<svg viewBox="0 0 44 66" width="100%" height="100%" aria-hidden="true">
      <ellipse cx="22" cy="62" rx="15" ry="3.2" fill="#000" opacity=".22"/>
      <g fill="#3f7d4e"><ellipse cx="22" cy="26" rx="7" ry="18"/><ellipse cx="22" cy="26" rx="7" ry="18" transform="rotate(-38 22 44)" fill="#4a9159"/><ellipse cx="22" cy="26" rx="7" ry="18" transform="rotate(38 22 44)" fill="#357048"/></g>
      <g fill="url(#g-shine)"><ellipse cx="22" cy="26" rx="7" ry="18"/></g>
      <path d="M11 46 h22 l-3 17 h-16z" fill="#ece7dc"/><path d="M11 46 h22 l-3 17 h-16z" fill="url(#g-shade-r)"/>
      <rect x="10" y="44" width="24" height="4" rx="2" fill="#f6f2e8"/></svg>`;
    return s;
  };

  // ---------- reception lobby ----------
  const board = {};
  function buildLobby() {
    const lobby = el("section", "lobby");
    lobby.dataset.room = "lobby";
    const wall = el("div", "logo-wall");
    wall.append(el("h2", null, "AGENT OFFICE"), el("p", null, "Reception · every agent, one floor"));
    const rec = el("div", "reception");
    rec.append(el("div", "counter"));
    const mon = el("div", "monitor");
    mon.append(el("i"));
    rec.append(mon);
    const b = el("div", "board");
    b.append(el("h3", null, "Floor status"));
    const dl = el("dl");
    [["At desks", "desk"], ["On break", "break"], ["On calls", "calls"], ["Events seen", "events"]].forEach(([label, k]) => {
      const dd = el("dd", null, "0");
      board[k] = dd;
      dl.append(el("dt", null, label), dd);
    });
    b.append(dl);
    const seat = el("div", "lounge-seat");
    seat.append(el("div", "sofa"));
    lobby.append(wall, rec, b, seat);
    return lobby;
  }

  function updateBoard() {
    const all = [...desks.values()];
    const away = all.filter((d) => d.mode !== "desk").length;
    board.desk.textContent = all.length - away;
    board.break.textContent = away;
    board.calls.textContent = activeCalls;
    board.events.textContent = eventsSeen;
    teams.forEach((t) => {
      const mine = all.filter((d) => d.team.id === t.def.id);
      const working = mine.filter((d) => d.el.dataset.state === "working").length;
      const gone = mine.filter((d) => d.mode !== "desk").length;
      t.stat.textContent = `${working} working · ${mine.length - working - gone} idle · ${gone} on break`;
    });
  }

  // ---------- build the floor ----------
  function buildTeam(t) {
    const cabin = el("section", "cabin" + (t.built ? "" : " onboarding") + (t.wide ? " wide" : ""));
    cabin.style.setProperty("--accent", t.accent);
    cabin.dataset.room = t.id;
    const head = el("div", "cabin-head");
    const titles = el("div");
    titles.append(el("h2", null, t.name), el("p", null, t.tagline));
    const right = el("div");
    right.style.cssText = "display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end";
    const stat = el("span", "teamstat", "");
    right.append(stat);
    if (!t.built) right.append(el("span", "badge", "onboarding · not built yet"));
    head.append(titles, right);
    cabin.append(head);

    const grid = el("div", "desks");
    t.members.forEach((m) => {
      const d = el("div", "desk");
      d.dataset.state = "idle";
      d.tabIndex = 0;
      d.title = `${m.name}, ${m.role}\n${m.component}\n(click for this colleague's log)`;
      d.insertAdjacentHTML("beforeend", seatedSvg(`${t.id}${m.id}`, t.accent));
      const bubble = el("div", "bubble");
      bubble.append(el("div", "txt"));
      bubble.setAttribute("role", "status");
      const plate = el("div", "nameplate");
      plate.append(el("b", null, m.name), el("span", null, m.role), el("i", "dot"));
      const wrap = el("div");
      wrap.append(plate);
      const sign = el("div", "breaksign");
      d.append(bubble, wrap, sign);
      const open = () => setFilter({ team: t.id, member: m.id, name: m.name });
      d.addEventListener("click", open);
      d.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
      grid.append(d);
      desks.set(key(t.id, m.id), {
        team: t, def: m, el: d, bubble, sign, queue: [], busy: false, timer: null, ringTimer: null,
        // breakout state: desk | leaving | break | returning
        mode: "desk", spot: null, wantBack: false, waiters: [], gate: Promise.resolve(),
        lastActive: Date.now(), idleAfter: 8000 + Math.random() * 22000,
      });
    });
    cabin.append(grid);
    cabin.append(el("div", "cabin-door"), plantSvg("p1"), plantSvg("p2"));
    teams.set(t.id, { el: cabin, def: t, stat });
    if (t.chat_enabled) cabin.append(buildFooter(t));
    return cabin;
  }

  // ---------- speech clouds ----------
  function renderBubble(d, e) {
    const b = d.bubble;
    const wasVisible = b.classList.contains("show");
    b.className = `bubble ${e.kind}` + (wasVisible ? " show" : "");
    const txt = b.firstChild;
    txt.replaceChildren();
    if (e.simulated) txt.append(el("span", "sim", "demo"));
    let text = e.text;
    if (e.kind === "handoff" && e.to_member) {
      const to = desks.get(key(e.to_team || e.team, e.to_member));
      if (to && !text.includes(to.def.name)) text += ` → ${to.def.name}`;
    }
    txt.append(document.createTextNode(text.length > 200 ? text.slice(0, 197) + "…" : text));
    d.el.title = `${d.def.name}: ${e.text}`;
    if (wasVisible) { void b.offsetWidth; b.classList.add("swap"); }
    requestAnimationFrame(() => b.classList.add("show"));
    d.el.classList.toggle("speaking", ["message", "inbound", "handoff", "done"].includes(e.kind));
    d.el.classList.toggle("on-call", e.kind === "tool_call");
  }

  function nextBubble(d) {
    const e = d.queue.shift();
    if (!e) {
      d.busy = false;
      d.bubble.classList.remove("show");
      d.el.classList.remove("speaking", "on-call");
      return;
    }
    d.busy = true;
    renderBubble(d, e);
    // Read time grows with length but shrinks when a backlog builds so the cloud keeps up.
    const base = clamp(1100 + e.text.length * 34, 1800, 8000);
    clearTimeout(d.timer);
    d.timer = setTimeout(() => nextBubble(d), base / (1 + d.queue.length * 0.9));
  }

  function speak(d, e) {
    const q = d.queue;
    if (q.length && q[q.length - 1].kind === "thinking") q.pop(); // a newer line supersedes "thinking"
    q.push(e);
    while (q.length > 6) { const i = q.findIndex((x) => x.kind !== "error"); q.splice(i < 0 ? 0 : i, 1); }
    if (!d.busy) nextBubble(d);
  }

  // ---------- motion ----------
  const relRect = (node) => {
    const fr = floor.getBoundingClientRect(), r = node.getBoundingClientRect();
    return { l: r.left - fr.left, t: r.top - fr.top, r: r.right - fr.left, b: r.bottom - fr.top };
  };
  const deskCenter = (d) => { const q = relRect(d.el.querySelector(".person")); return { x: (q.l + q.r) / 2, y: (q.t + q.b) / 2 }; };
  // the walking lane just below a desk, between desk rows
  const deskStand = (d) => { const q = relRect(d.el); return { x: (q.l + q.r) / 2, y: q.b + 16 }; };
  const spotFeet = (s) => { const q = relRect(s.el); return { x: (q.l + q.r) / 2, y: q.b - 6 }; };

  function ring(d, ms = 2200) {
    d.el.classList.add("ringing");
    clearTimeout(d.ringTimer);
    d.ringTimer = setTimeout(() => d.el.classList.remove("ringing"), ms);
  }

  // ---------- floor plan & path-finding ----------
  // Rooms are walled; the only way in or out is the door onto the corridor. Walkers plan a route over a coarse grid
  // so they follow corridors and lanes instead of cutting through other rooms or desks.
  const CELL = 12;
  let nav = null, navDirty = true, aisles = null;
  const isTwoCol = () => matchMedia("(min-width: 1000px)").matches;
  const inside = (x, y, q, pad = 0) => x >= q.l + pad && x <= q.r - pad && y >= q.t + pad && y <= q.b - pad;

  // Every room's door faces the central spine (or the left-hand corridor on a single column).
  function layoutRooms() {
    const twoCol = isTwoCol();
    const fl = floor.getBoundingClientRect();
    floor.querySelectorAll("[data-room]").forEach((room) => {
      const door = room.querySelector(":scope > .cabin-door");
      if (!door) return;
      const rr = room.getBoundingClientRect();
      const mid = rr.left + rr.width / 2 - fl.left;
      const side = twoCol ? (mid < fl.width / 2 ? "right" : "left") : "left";
      room.classList.remove("door-left", "door-right");
      room.classList.add(`door-${side}`);
      const first = room.querySelector(".desk");
      const y = first ? first.getBoundingClientRect().bottom + 16 - rr.top : rr.height * 0.5;
      door.style.top = `${clamp(y - 44, 40, Math.max(40, rr.height - 100))}px`;
    });
  }

  function layoutAisles() {
    aisles.replaceChildren();
    const fr = floor.getBoundingClientRect();
    const rooms = [...floor.querySelectorAll("[data-room]")].map((n) => ({ id: n.dataset.room, ...relRect(n) }));
    const body = rooms.filter((r) => r.id !== "lobby");
    if (!body.length) return;
    const add = (cls, l, t, w, h) => {
      if (w < 16 || h < 16) return;
      const a = el("div", `aisle ${cls}`);
      a.style.cssText = `left:${l}px;top:${t}px;width:${w}px;height:${h}px`;
      aisles.append(a);
    };
    const rows = [];
    [...rooms].sort((a, b) => a.t - b.t).forEach((r) => {
      const row = rows.find((g) => Math.abs(g.t - r.t) < 24);
      if (row) { row.b = Math.max(row.b, r.b); } else rows.push({ t: r.t, b: r.b });
    });
    for (let i = 0; i + 1 < rows.length; i++) add("h", 0, rows[i].b, fr.width, rows[i + 1].t - rows[i].b);
    const top = Math.min(...body.map((r) => r.t)), bottom = Math.max(...body.map((r) => r.b));
    if (isTwoCol()) {
      const left = body.filter((r) => (r.l + r.r) / 2 < fr.width / 2), right = body.filter((r) => (r.l + r.r) / 2 >= fr.width / 2);
      if (left.length && right.length) {
        const x1 = Math.max(...left.map((r) => r.r)), x2 = Math.min(...right.map((r) => r.l));
        add("v", x1, top - 30, x2 - x1, bottom - top + 60);
      }
    } else {
      add("v", 0, top - 30, Math.min(...body.map((r) => r.l)), bottom - top + 60);
    }
  }

  function buildNav() {
    layoutRooms();
    const fr = floor.getBoundingClientRect();
    const cols = Math.ceil(fr.width / CELL), rows = Math.ceil(fr.height / CELL);
    const rooms = [...floor.querySelectorAll("[data-room]")].map((node) => {
      const d = node.querySelector(":scope > .cabin-door");
      const dq = d ? relRect(d) : null;
      return {
        id: node.dataset.room, rect: relRect(node),
        door: dq ? { l: dq.l - 14, r: dq.r + 14, t: dq.t + 10, b: dq.b - 10 } : null,
        obstacles: [...node.querySelectorAll(".desk, .cabin-head, .cabin-foot, .ochat, .prop:not(.plant)")].map(relRect),
      };
    });
    // kind: 0 corridor/door, -1 blocked, n>0 = interior of room n-1 (walkable only for rooms a trip starts or ends in)
    const kind = new Int16Array(cols * rows);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x = (c + 0.5) * CELL, y = (r + 0.5) * CELL;
        let k = 0;
        if (!rooms.some((R) => R.door && inside(x, y, R.door))) {
          for (let i = 0; i < rooms.length; i++) {
            const R = rooms[i];
            if (!inside(x, y, R.rect)) continue;
            k = !inside(x, y, R.rect, CELL + 2) || R.obstacles.some((o) => inside(x, y, o)) ? -1 : i + 1;
            break;
          }
        }
        kind[r * cols + c] = k;
      }
    }
    nav = { cols, rows, kind, rooms };
    navDirty = false;
  }

  function findPath(a, b) {
    if (!nav || navDirty) buildNav();
    const { cols, rows, kind, rooms } = nav;
    const allowed = new Set([a, b].map((p) => rooms.findIndex((R) => inside(p.x, p.y, R.rect))).filter((i) => i >= 0));
    const ok = (c, r) => {
      if (c < 0 || r < 0 || c >= cols || r >= rows) return false;
      const k = kind[r * cols + c];
      return k === 0 || (k > 0 && allowed.has(k - 1));
    };
    const toCell = (p) => [clamp(Math.floor(p.x / CELL), 0, cols - 1), clamp(Math.floor(p.y / CELL), 0, rows - 1)];
    const snap = ([c, r]) => {
      if (ok(c, r)) return [c, r];
      for (let rad = 1; rad <= 10; rad++)
        for (let dy = -rad; dy <= rad; dy++)
          for (let dx = -rad; dx <= rad; dx++)
            if (Math.max(Math.abs(dx), Math.abs(dy)) === rad && ok(c + dx, r + dy)) return [c + dx, r + dy];
      return null;
    };
    const S = snap(toCell(a)), T = snap(toCell(b));
    if (!S || !T) return [a, b];

    const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]];
    const G = new Float32Array(cols * rows * 5).fill(Infinity);
    const from = new Int32Array(cols * rows * 5).fill(-1);
    const done = new Uint8Array(cols * rows * 5);
    const hf = [], hs = []; // binary min-heap of (f, state)
    const push = (f, st) => {
      let i = hf.length; hf.push(f); hs.push(st);
      while (i > 0) {
        const p = (i - 1) >> 1;
        if (hf[p] <= hf[i]) break;
        [hf[p], hf[i]] = [hf[i], hf[p]]; [hs[p], hs[i]] = [hs[i], hs[p]]; i = p;
      }
    };
    const pop = () => {
      const top = hs[0], lf = hf.pop(), ls = hs.pop();
      if (hf.length) {
        hf[0] = lf; hs[0] = ls;
        let i = 0;
        for (;;) {
          const l = 2 * i + 1, r = l + 1;
          let m = i;
          if (l < hf.length && hf[l] < hf[m]) m = l;
          if (r < hf.length && hf[r] < hf[m]) m = r;
          if (m === i) break;
          [hf[m], hf[i]] = [hf[i], hf[m]]; [hs[m], hs[i]] = [hs[i], hs[m]]; i = m;
        }
      }
      return top;
    };
    const h = (c, r) => Math.abs(c - T[0]) + Math.abs(r - T[1]);
    const s0 = (S[1] * cols + S[0]) * 5 + 4;
    G[s0] = 0;
    push(h(S[0], S[1]), s0);
    let end = -1, guard = 0;
    while (hf.length && guard++ < 600000) {
      const st = pop();
      if (done[st]) continue;
      done[st] = 1;
      const dir = st % 5, idx = (st - dir) / 5, c = idx % cols, r = (idx - c) / cols;
      if (c === T[0] && r === T[1]) { end = st; break; }
      for (let d = 0; d < 4; d++) {
        const nc = c + DIRS[d][0], nr = r + DIRS[d][1];
        if (!ok(nc, nr)) continue;
        // prefer straight runs and the middle of a corridor over hugging walls
        const near = !ok(nc + 1, nr) || !ok(nc - 1, nr) || !ok(nc, nr + 1) || !ok(nc, nr - 1);
        const cost = 1 + (dir !== 4 && dir !== d ? 3 : 0) + (near ? 2 : 0);
        const ns = (nr * cols + nc) * 5 + d, ng = G[st] + cost;
        if (ng < G[ns]) { G[ns] = ng; from[ns] = st; push(ng + h(nc, nr), ns); }
      }
    }
    if (end < 0) return [a, b];
    const cells = [];
    for (let st = end; st >= 0; st = from[st]) {
      const idx = (st - (st % 5)) / 5;
      cells.push({ x: ((idx % cols) + 0.5) * CELL, y: (Math.floor(idx / cols) + 0.5) * CELL });
    }
    cells.reverse();
    const pts = [a];
    for (let i = 0; i < cells.length; i++) {
      const p = cells[i], q = pts[pts.length - 1], n = cells[i + 1];
      const straight = n && ((p.x === q.x && p.x === n.x) || (p.y === q.y && p.y === n.y));
      if (!straight) pts.push(p);
    }
    pts.push(b);
    return pts;
  }

  // A figure walks the planned route at a relaxed pace. Resolves on arrival.
  function travel(a, b, team, idStr, { speed = 0.055, min = 2400, max = 30000, carry = false } = {}) {
    return new Promise((resolve) => {
      if (reduceMotion) return resolve();
      const pts = findPath(a, b);
      const seg = pts.slice(1).map((p, i) => Math.hypot(p.x - pts[i].x, p.y - pts[i].y));
      const total = seg.reduce((x, y) => x + y, 0) || 1;
      const dur = clamp(total / speed, min, max);
      const r = el("div", "runner");
      const flip = el("div", "flip");
      flip.insertAdjacentHTML("beforeend", walkerSvg(team.accent, idStr, { carry, walking: true }));
      r.append(flip);
      runners.append(r);
      const at = (p) => `translate(${p.x - 25}px, ${p.y - 78}px)`;
      let acc = 0;
      const frames = pts.map((p, i) => {
        if (i) acc += seg[i - 1];
        return { transform: at(p), offset: acc / total, opacity: i === 0 || i === pts.length - 1 ? 0 : 1 };
      });
      // fade in/out only at the very ends
      frames.splice(1, 0, { transform: at(pts[0]), offset: 0.0001, opacity: 1 });
      frames.splice(frames.length - 1, 0, { transform: at(pts[pts.length - 1]), offset: 0.9999, opacity: 1 });
      const anim = r.animate(frames, { duration: dur, easing: "linear", fill: "forwards" });
      const finish = () => { r.remove(); resolve(); };
      anim.onfinish = finish;
      anim.oncancel = finish;
    });
  }
  const idOf = (d) => d.team.id + d.def.id;

  // Same team: get up, walk along the lanes to the other desk, talk for a moment, walk back.
  function walk(from, to) {
    from.el.classList.add("away");
    const home = deskStand(from), spot = deskStand(to);
    const dest = { x: spot.x + (home.x <= spot.x ? -44 : 44), y: spot.y };
    const there = travel(home, dest, from.team, idOf(from), { carry: true });
    to.gate = Promise.all([to.gate, there]);
    from.gate = (async () => {
      await there;
      ring(to, 1400);
      await sleep(1100);
      await travel(dest, home, from.team, idOf(from));
      from.el.classList.remove("away");
    })();
  }

  // Different teams: a phone call along a glowing dashed line.
  function phoneCall(from, to) {
    const A = deskCenter(from), B = deskCenter(to);
    const a = { x: A.x, y: A.y - 10 }, b = { x: B.x, y: B.y - 10 };
    const dist = Math.hypot(b.x - a.x, b.y - a.y);
    const cx = (a.x + b.x) / 2, cy = Math.min(a.y, b.y) - 50 - dist * 0.12;
    const d = `M${a.x},${a.y} Q${cx},${cy} ${b.x},${b.y}`;
    const g = document.createElementNS(NS, "g");
    const mk = (cls) => {
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", d);
      p.setAttribute("class", cls);
      p.setAttribute("stroke", from.team.accent);
      return p;
    };
    g.append(mk("wire-glow"), mk("wire"));
    if (!reduceMotion) {
      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("r", "6");
      dot.setAttribute("fill", from.team.accent);
      const m = document.createElementNS(NS, "animateMotion");
      m.setAttribute("dur", "1.4s");
      m.setAttribute("repeatCount", "indefinite");
      m.setAttribute("path", d);
      dot.append(m);
      g.append(dot);
    }
    wires.append(g);
    const chip = el("div", "callchip", `📞 ${from.def.name} → ${to.def.name}`);
    chip.style.left = `${(a.x + 2 * cx + b.x) / 4}px`;
    chip.style.top = `${(a.y + 2 * cy + b.y) / 4}px`;
    chip.style.setProperty("--accent", from.team.accent);
    runners.append(chip);
    from.el.classList.add("on-call");
    ring(to, 3000);
    activeCalls++;
    const cabin = teams.get(to.team.id);
    if (cabin) { cabin.el.classList.remove("ringing-in"); void cabin.el.offsetWidth; cabin.el.classList.add("ringing-in"); }
    setTimeout(() => { g.style.transition = "opacity .4s"; g.style.opacity = 0; chip.classList.add("fade-out"); }, 2800);
    setTimeout(() => { g.remove(); chip.remove(); from.el.classList.remove("on-call"); activeCalls--; }, 3250);
  }

  function connect(from, to) {
    if (reduceMotion) { ring(to, 1500); return; }
    if (from.team.id === to.team.id) walk(from, to); else phoneCall(from, to);
  }

  // ---------- breakout area: café + lounge and play zone ----------
  const spots = []; // {el, kind, group, occupant}
  const BADGE = { coffee: "☕", vending: "🥤", seat: "🍕", pingpong: "🏓", arcade: "🎮", beanbag: "😴", sofa: "💬", read: "📖" };
  const ACT = { coffee: "sip", vending: "sip", seat: "sip", pingpong: "play", arcade: "play", beanbag: "relax", sofa: "relax", read: "sip" };

  function buildBreakout() {
    const card = el("section", "breakout");
    card.dataset.room = "breakout";
    card.append(el("div", "cabin-door"));
    const head = el("div", "cabin-head");
    const titles = el("div");
    titles.append(el("h2", null, "Breakout area"), el("p", null, "Colleagues with nothing to do come here, and head back to their desk when work arrives."));
    const count = el("span", "break-count", "0 on break");
    count.id = "break-count";
    head.append(titles, count);
    card.append(head);

    const zones = el("div", "zones");
    const zone = (cls, title, props, spotDefs) => {
      const z = el("div", `zone ${cls}`);
      z.append(el("h3", null, title));
      props.forEach(([c, x, y, txt]) => {
        const p = el("div", `prop ${c}`, txt || "");
        if (x || y) { p.style.left = `${x}%`; p.style.top = `${y}%`; } // 0,0 = positioned by CSS
        if (c === "pptable") p.append(el("i", "net"), el("i", "ball"));
        z.append(p);
      });
      spotDefs.forEach(([kind, x, y, group]) => {
        const s = el("div", "spot");
        s.style.left = `${x}%`; s.style.top = `${y}%`;
        z.append(s);
        spots.push({ el: s, kind, group, occupant: null });
      });
      return z;
    };
    zones.append(
      zone("cafe", "Café & lounge",
        [["counter", 0, 0, "🍩 🥐 ☕ 🥪"], ["vending", 0, 0], ["table", 18, 74], ["table", 50, 74], ["table", 82, 74], ["plant", 5, 42, "🪴"], ["plant", 96, 92, "🪴"]],
        [["coffee", 52, 40], ["coffee", 66, 40], ["vending", 80, 42],
         ["seat", 8, 76], ["seat", 28, 76], ["seat", 40, 76], ["seat", 60, 76], ["seat", 72, 76], ["seat", 92, 76]]),
      zone("play", "Play zone",
        [["pptable", 0, 0], ["arcade", 70, 36], ["arcade", 86, 36], ["beanbag bb1", 60, 86], ["beanbag bb2", 76, 88], ["beanbag bb3", 91, 86], ["plant", 8, 20, "🎯"]],
        [["pingpong", 10, 62, "pp"], ["pingpong", 46, 62, "pp"], ["arcade", 70, 60], ["arcade", 86, 60],
         ["beanbag", 60, 82], ["beanbag", 76, 84], ["beanbag", 91, 82]]),
      zone("lounge", "Quiet lounge",
        [["shelf", 50, 13], ["sofa2", 28, 46], ["sofa2", 74, 46], ["ctable", 51, 62], ["plant", 6, 30, "🪴"], ["plant", 95, 30, "🪴"]],
        [["read", 38, 27], ["read", 62, 27], ["sofa", 20, 62], ["sofa", 36, 62], ["sofa", 66, 62], ["sofa", 82, 62]])
    );
    card.append(zones);
    return card;
  }

  function updateBreakout() {
    const pp = spots.filter((s) => s.group === "pp");
    const table = document.querySelector(".pptable");
    if (table) table.classList.toggle("playing", pp.length > 0 && pp.every((s) => s.occupant && s.occupant.mode === "break"));
    const n = [...desks.values()].filter((d) => d.mode !== "desk").length;
    const c = document.getElementById("break-count");
    if (c) c.textContent = `${n} on break`;
  }

  function placeVisitor(d, spot) {
    const v = el("div", `visitor ${ACT[spot.kind]}`);
    v.insertAdjacentHTML("beforeend", walkerSvg(d.team.accent, idOf(d)));
    v.append(el("span", "badge-act", BADGE[spot.kind]), el("span", "who", d.def.name));
    spot.el.append(v);
  }

  const BREAK_WALK = { speed: 0.09, min: 2600, max: 30000 };

  async function goOnBreak(d, spot) {
    d.mode = "leaving";
    d.spot = spot;
    spot.occupant = d;
    d.sign.textContent = `${BADGE[spot.kind]} on break`;
    d.el.classList.add("away", "onbreak");
    updateBreakout();
    await travel(deskStand(d), spotFeet(spot), d.team, idOf(d), BREAK_WALK);
    placeVisitor(d, spot);
    d.mode = "break";
    updateBreakout();
    if (d.wantBack) returnToDesk(d);
  }

  async function returnToDesk(d) {
    const spot = d.spot;
    d.mode = "returning";
    spot.el.replaceChildren();
    updateBreakout();
    await travel(spotFeet(spot), deskStand(d), d.team, idOf(d), BREAK_WALK);
    spot.occupant = null;
    d.spot = null;
    d.mode = "desk";
    d.wantBack = false;
    d.lastActive = Date.now();
    d.el.classList.remove("away", "onbreak");
    updateBreakout();
    d.waiters.splice(0).forEach((resolve) => resolve());
  }

  // Resolves once the colleague is sitting at their desk, calling them back if needed.
  function wantDesk(d) {
    if (d.mode === "desk") return Promise.resolve();
    const p = new Promise((resolve) => d.waiters.push(resolve));
    if (d.mode === "break") returnToDesk(d);
    else if (d.mode === "leaving") d.wantBack = true;
    return p;
  }

  // Idle, no recent work, nothing queued: go and enjoy the breakout area. One departure per tick.
  setInterval(() => {
    if (document.hidden || !spots.length) return;
    const now = Date.now();
    const free = spots.filter((s) => !s.occupant);
    if (!free.length) return;
    const ready = [...desks.values()].filter((d) =>
      d.mode === "desk" && d.el.dataset.state === "idle" && !d.busy && !d.queue.length &&
      !d.el.classList.contains("away") && !d.el.classList.contains("ringing") && now - d.lastActive > d.idleAfter);
    if (!ready.length) return;
    goOnBreak(ready[Math.floor(Math.random() * ready.length)], free[Math.floor(Math.random() * free.length)]);
  }, 1500);
  setInterval(() => { if (desks.size) updateBoard(); }, 1000);

  // ---------- events ----------
  function onEvent(e) {
    log.push(e);
    eventsSeen++;
    if (log.length > 600) log.shift();
    const d = desks.get(key(e.team, e.member));
    if (!d) return;
    const state = e.state || (e.kind === "error" ? "error" : e.kind === "done" ? "idle" : null);
    if (state) d.el.dataset.state = state;
    if (live) {
      const to = e.to_member ? desks.get(key(e.to_team || e.team, e.to_member)) : null;
      d.lastActive = Date.now();
      if (to) { to.lastActive = Date.now(); wantDesk(to); } // the callee is called back from break too
      // Whoever speaks must be at their desk, and not mid-walk delivering a message.
      Promise.all([wantDesk(d), d.gate]).then(() => {
        speak(d, e);
        if (to && to !== d) connect(d, to);
      });
    }
    appendRow(e);
  }

  // ---------- activity drawer ----------
  const drawer = document.getElementById("drawer");
  const dList = document.getElementById("drawer-list");
  function rowFor(e) {
    const d = desks.get(key(e.team, e.member));
    const r = el("div", `row ${e.kind}`);
    if (d) r.style.setProperty("--accent", d.team.accent);
    if (e.simulated) r.append(el("span", "sim", "demo"));
    r.append(el("b", null, d ? d.def.name : e.member));
    r.append(document.createTextNode(e.text));
    r.append(el("time", null, fmt(e.ts)));
    return r;
  }
  const matches = (e) => !filter || (e.team === filter.team && e.member === filter.member) ||
    ((e.to_team || e.team) === filter.team && e.to_member === filter.member);
  function renderDrawer() {
    dList.replaceChildren(...log.filter(matches).slice(-300).map(rowFor));
    dList.scrollTop = dList.scrollHeight;
    document.getElementById("drawer-title").textContent = filter ? `Log: ${filter.name}` : "All activity";
    document.getElementById("drawer-clear").hidden = !filter;
  }
  function appendRow(e) {
    if (drawer.hidden || !matches(e)) return;
    const nearBottom = dList.scrollHeight - dList.scrollTop - dList.clientHeight < 60;
    dList.append(rowFor(e));
    if (nearBottom) dList.scrollTop = dList.scrollHeight;
  }
  function setFilter(f) { filter = f; drawer.hidden = false; renderDrawer(); }

  document.getElementById("log-btn").addEventListener("click", () => { drawer.hidden = !drawer.hidden; if (!drawer.hidden) renderDrawer(); });
  document.getElementById("drawer-close").addEventListener("click", () => (drawer.hidden = true));
  document.getElementById("drawer-clear").addEventListener("click", () => { filter = null; renderDrawer(); });

  // ---------- talk to a team ----------
  // Every cabin has a real conversation with its team. Agents ask everything they need up front (answers can be clicked), and anything
  // only the admin can fix shows up as a "Needs you" card here, in the team's own app, and as a colleague speaking on the floor.
  const APPS = Object.assign({ support: "http://localhost:8000", iac: "http://localhost:8100", cicd: "http://localhost:8300", observability: "http://localhost:8400" }, window.AO_APPS || {}, { observability: (window.AO_APPS || {}).perf || "http://localhost:8400" });
  const TEAM_CHAT = {
    iac: { label: "Infrastructure", hint: "Describe what to build, on any cloud…", kind: "session", app: APPS.iac },
    support: { label: "Customer Support", hint: "Try the support bot as a customer would…", kind: "sse", path: "/api/chat", base: APPS.support, app: APPS.support },
    cicd: { label: "CI/CD", hint: "Give Cody a change to review, or ask about pipelines…", kind: "sse", path: "/api/agent/chat", base: APPS.cicd, app: APPS.cicd },
    observability: { label: "Observability", hint: "Ask how things are running, or ask for a dashboard…", kind: "sse", path: "/api/agent/chat", base: APPS.observability, app: APPS.observability },
  };
  const chats = {}; // team id -> state

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const md = (s) => esc(s).replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>").replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\n/g, "<br>");
  // "Which region? [fsn1 * | nbg1 | hel1]" -> question text + options (the * marks the recommended one)
  function parseQuestions(text) {
    const out = [];
    text.split("\n").forEach((line) => {
      const m = line.match(/^\s*(?:[-*\d.]+\s*)?(.*?)\s*\[([^\]]+\|[^\]]+)\]\s*[;.,]?\s*$/);
      if (m && m[1]) out.push({ q: m[1].trim(), opts: m[2].split("|").map((o) => o.trim()).filter(Boolean) });
    });
    return out;
  }
  const stripOpts = (text) => text.split("\n").map((l) => l.replace(/\s*\[[^\]]+\|[^\]]+\]\s*[;.,]?\s*$/, "")).join("\n");

  async function authedJson(url, opts = {}) {
    const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
    const r = await fetch(url, { ...opts, headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...(opts.headers || {}) } });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${r.status})`);
    return body;
  }
  async function streamSse(url, body, onEvent) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(typeof j.detail === "string" ? j.detail : `Request failed (${r.status})`); }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i).split("\n").find((l) => l.startsWith("data:"));
        buf = buf.slice(i + 2);
        if (line) { try { onEvent(JSON.parse(line.slice(5).trim())); } catch (_) {} }
      }
    }
  }

  function buildFooter(t) {
    const cfg = TEAM_CHAT[t.id];
    const st = (chats[t.id] = { msgs: [], history: [], busy: false, convId: null, sessionId: null, session: null, timer: null });
    const wrap = el("div", "ochat");
    const head = el("div", "ochat-head");
    const title = el("b", null, `Talk to the ${cfg.label} team`);
    const open = el("button", "ochat-link", "Open full app ↗");
    open.type = "button";
    open.onclick = () => window.AO_OPEN ? window.AO_OPEN(cfg.app) : window.open(cfg.app, "_blank");
    const status = el("span", "ochat-status", "");
    head.append(title, status, open);
    const thread = el("div", "ochat-thread");
    thread.setAttribute("role", "log");
    thread.setAttribute("aria-live", "polite");
    const attn = el("div", "ochat-attn");
    const form = el("form", "ochat-form");
    const input = el("input");
    input.placeholder = cfg.hint;
    input.setAttribute("aria-label", `Message the ${cfg.label} team`);
    const send = el("button", "btn btn-accent", "Send");
    send.type = "submit";
    const fileChip = el("span", "ochat-file");
    fileChip.hidden = true;
    if (cfg.kind === "session") {
      // the infrastructure team can read an architecture diagram or document and build it on the cloud you name
      const pick = el("input");
      pick.type = "file"; pick.hidden = true;
      pick.accept = ".png,.jpg,.jpeg,.webp,.gif,.pdf,.docx,.txt,.md,.json,.yaml,.yml,.xml,.drawio,.mmd,.puml,.tf,.svg";
      const clip = el("button", "btn btn-ghost ochat-clip", "📎");
      clip.type = "button"; clip.title = "Attach an architecture diagram or document"; clip.setAttribute("aria-label", "Attach a diagram or document");
      const setFile = (f) => {
        st.file = f || null;
        fileChip.hidden = !f;
        fileChip.textContent = f ? `📎 ${f.name} ✕` : "";
        input.placeholder = f ? "Which cloud should I build this on?" : cfg.hint;
      };
      fileChip.onclick = () => setFile(null);
      clip.onclick = () => pick.click();
      pick.onchange = () => { const f = pick.files[0]; pick.value = ""; if (f && f.size > 15 * 1048576) addMsg(t.id, "agent", "Needs you: that file is over 15 MB.", { who: "System" }), paintChat(t.id); else setFile(f); };
      input.addEventListener("paste", (e) => { const f = [...(e.clipboardData?.files || [])][0]; if (f) { e.preventDefault(); setFile(f); } });
      wrap.addEventListener("dragover", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) e.preventDefault(); });
      wrap.addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) { e.preventDefault(); setFile(f); } });
      st.setFile = setFile;
      form.append(clip, pick);
    }
    form.append(input, send);
    const actions = el("div", "ochat-actions");
    wrap.append(head, thread, attn, fileChip, form, actions);
    st.ui = { thread, attn, input, send, status, actions };

    form.addEventListener("submit", (ev) => { ev.preventDefault(); submitChat(t.id); });
    paintChat(t.id);
    return wrap;
  }

  function addMsg(tid, role, text, extra = {}) {
    const st = chats[tid];
    st.msgs.push({ role, text, ...extra });
    if (st.msgs.length > 80) st.msgs.shift();
  }

  function paintChat(tid) {
    const st = chats[tid], cfg = TEAM_CHAT[tid], { thread, attn, input, send, status, actions } = st.ui;
    const nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 60;
    thread.replaceChildren();
    if (!st.msgs.length) thread.append(el("div", "ochat-empty", cfg.hint));
    st.msgs.forEach((m, idx) => {
      const b = el("div", `ochat-msg ${m.role}${/(^|\n)Needs you:/.test(m.text) ? " needs" : ""}`);
      const who = el("span", "who", m.role === "user" ? "You" : (m.who || cfg.label));
      const body = el("div", "txt");
      body.innerHTML = md(m.role === "user" ? m.text : stripOpts(m.text));
      b.append(who, body);
      if (m.role !== "user" && idx === st.msgs.length - 1 && !st.busy) {
        const qs = parseQuestions(m.text);
        if (qs.length) {
          const chips = el("div", "ochat-chips");
          qs.forEach((q) => {
            const row = el("div", "ochat-q");
            row.append(el("span", "ochat-qt", q.q));
            q.opts.forEach((o) => {
              const rec = o.includes("*"), label = o.replace(/\s*\*\s*/g, "").trim();
              const chip = el("button", `ochat-chip${rec ? " rec" : ""}`, label);
              chip.type = "button";
              chip.title = rec ? "Recommended" : "";
              chip.onclick = () => { const stem = q.q.replace(/\?+$/, ""); input.value = (input.value ? input.value + "; " : "") + `${stem}: ${label}`; input.focus(); };
              row.append(chip);
            });
            chips.append(row);
          });
          chips.append(el("div", "ochat-tip", "Click your answers, edit if you like, then press Send once."));
          b.append(chips);
        }
      }
      thread.append(b);
    });
    if (st.busy) thread.append(el("div", "ochat-typing", st.working || "Working…"));
    if (nearBottom || st.busy) thread.scrollTop = thread.scrollHeight;
    send.disabled = st.busy;
    status.textContent = st.busy ? "working…" : (st.session ? st.session.status.replace(/_/g, " ") : "");

    // "Needs you" cards (infrastructure computes them server side)
    attn.replaceChildren();
    const items = ((st.session && st.session.attention) || []).filter((a) => a.kind !== "question");
    items.forEach((a) => {
      const c = el("div", `ochat-need ${a.severity}`);
      c.append(el("b", null, `⚠ ${a.title}`), el("div", null, a.detail || ""), el("div", "fix", a.how_to_fix || ""));
      attn.append(c);
    });
    paintActions(tid);
  }

  function paintActions(tid) {
    const st = chats[tid], d = st.session, box = st.ui.actions;
    box.replaceChildren();
    if (tid !== "iac" || !d || st.busy) return;
    const add = (label, fn, primary) => {
      const b = el("button", `btn btn-sm${primary ? " btn-accent" : ""}`, label);
      b.type = "button";
      b.onclick = async () => { b.disabled = true; try { await fn(); } catch (e) { addMsg("iac", "agent", `Needs you: ${e.message}`, { who: "Ira" }); } paintChat("iac"); };
      box.append(b);
    };
    const post = async (p) => { st.session = await authedJson(`${APPS.iac}/iac/sessions/${st.sessionId}/${p}`, { method: "POST" }); };
    if (d.architecture && d.architecture.diagram) add("Architecture diagram ↗", async () => window.AO_OPEN(APPS.iac), false);
    if (d.status === "ready_for_plan") add("Run plan", async () => { await post("plan"); addMsg("iac", "agent", "Plan complete. Review it, then approve.", { who: "Ira" }); }, true);
    if (d.status === "planned") add("Approve plan", async () => { await post("approve"); addMsg("iac", "agent", "Plan approved. Press Apply when you are ready.", { who: "Ira" }); }, true);
    if (d.status === "approved") add("Apply…", async () => { if (confirm("This creates real infrastructure and may cost money. Apply the approved plan?")) { await post("apply"); addMsg("iac", "agent", st.session.status === "applied" ? "Infrastructure applied." : "Apply finished.", { who: "Ira" }); } }, true);
  }

  async function submitChat(tid) {
    const st = chats[tid], cfg = TEAM_CHAT[tid], text = st.ui.input.value.trim(), file = st.file || null;
    if ((!text && !file) || st.busy) return;
    st.ui.input.value = "";
    if (file && st.setFile) st.setFile(null);
    addMsg(tid, "user", file ? `📎 ${file.name}${text ? " — " + text : ""}` : text);
    st.busy = true; st.working = "Working…";
    paintChat(tid);
    try {
      if (cfg.kind === "session") await sendIacChat(tid, text, file);
      else await sendSseChat(tid, cfg, text);
    } catch (e) {
      addMsg(tid, "agent", `Needs you: ${e.message}`, { who: "System" });
    } finally {
      st.busy = false;
      paintChat(tid);
    }
  }

  async function sendSseChat(tid, cfg, text) {
    const st = chats[tid];
    const msg = { role: "agent", text: "", who: cfg.label };
    st.msgs.push(msg);
    const body = tid === "support" ? { message: text, conversation_id: st.convId, model: "primary" } : { message: text, history: st.history.slice(-20), model: "primary" };
    await streamSse(cfg.base + cfg.path, body, (ev) => {
      if (ev.type === "meta" && ev.conversation_id) st.convId = ev.conversation_id;
      else if (ev.type === "token") { msg.text += ev.text; paintChat(tid); }
      else if (ev.type === "tool_start") { st.working = `Using ${ev.name.replace(/_/g, " ")}…`; paintChat(tid); }
      else if (ev.type === "error") { msg.text = `Needs you: ${ev.message}`; }
      else if (ev.type === "done") { msg.text = msg.text || ev.text || ""; }
    });
    if (!msg.text) msg.text = "(no answer)";
    st.history.push({ role: "user", content: text }, { role: "assistant", content: msg.text });
  }

  async function sendIacChat(tid, text, file) {
    const st = chats[tid];
    if (!st.sessionId) st.sessionId = (await authedJson(`${APPS.iac}/iac/sessions`, { method: "POST", body: JSON.stringify({ model: "primary" }) })).id;
    const seenHistory = st.session ? st.session.history.length : 0;
    if (file) {
      const form = new FormData();
      form.append("file", file); form.append("message", text); form.append("model", "primary");
      st.session = await authedJson(`${APPS.iac}/iac/sessions/${st.sessionId}/attachments`, { method: "POST", body: form });
    } else st.session = await authedJson(`${APPS.iac}/iac/sessions/${st.sessionId}/messages`, { method: "POST", body: JSON.stringify({ content: text, model: "primary" }) });
    // the team works in the background; follow its activity until it answers
    for (let i = 0; i < 400; i++) {
      await new Promise((r) => setTimeout(r, 1200));
      st.session = await authedJson(`${APPS.iac}/iac/sessions/${st.sessionId}`);
      const last = (st.session.activity || []).slice(-1)[0];
      if (last) st.working = `${last.member}: ${last.text}`.slice(0, 90);
      paintChat(tid);
      if (!st.session.busy) break;
    }
    // surface only the agent's NEW replies (the user's own message is already in the thread)
    st.session.history.slice(seenHistory + 1).filter((m) => m.role === "agent").forEach((m) => addMsg(tid, "agent", m.text, { who: "Infrastructure team" }));
  }

  // ---------- boot ----------
  async function boot() {
    const roster = await (await fetch(CFG.OFFICE_API + "/roster")).json();
    aisles = el("div", "aisles");
    floor.append(aisles, buildLobby());
    roster.teams.forEach((t) => floor.append(buildTeam(t)));
    floor.append(buildBreakout());
    wires = document.createElementNS(NS, "svg");
    wires.setAttribute("class", "layer");
    runners = el("div", "layer");
    floor.append(wires, runners);
    roster.members.forEach((s) => {
      const d = desks.get(key(s.team, s.member));
      if (d) d.el.dataset.state = s.state;
    });
    layoutRooms();
    layoutAisles();
    new ResizeObserver(() => { navDirty = true; layoutRooms(); layoutAisles(); }).observe(floor);
    updateBoard();

    const es = new EventSource(CFG.OFFICE_API + "/stream");
    es.onopen = () => {
      connEl.className = "conn conn-on";
      connEl.lastElementChild.textContent = "live";
      setTimeout(() => (live = true), 700); // history replays silently; only fresh events animate
    };
    es.onerror = () => {
      live = false;
      connEl.className = "conn conn-off";
      connEl.lastElementChild.textContent = "reconnecting";
    };
    es.onmessage = (m) => onEvent(JSON.parse(m.data));
  }

  // Handy for checking routes from the browser console: __officeDebug.route('iac/requirements', 0)
  window.__officeDebug = { route: (deskKey, spotIdx) => findPath(deskStand(desks.get(deskKey)), spotFeet(spots[spotIdx])), nav: () => nav };

  const demoBtn = document.getElementById("demo-btn");
  demoBtn.addEventListener("click", async () => {
    demoBtn.disabled = true;
    let secs = 120;
    try {
      const r = await (await fetch(CFG.OFFICE_API + "/demo/start", { method: "POST" })).json();
      if (r.seconds) secs = r.seconds + 12;
    } catch (_) { /* hub unreachable; button re-enables below */ }
    setTimeout(() => (demoBtn.disabled = false), secs * 1000);
  });
  document.getElementById("modal-close").addEventListener("click", () => (document.getElementById("modal").hidden = true));
  document.getElementById("modal").addEventListener("click", (e) => { if (e.target.id === "modal") e.target.hidden = true; });

  boot().catch((err) => floor.append(el("p", null, `Could not load the office: ${err.message}. Is the hub running?`)));
})();
