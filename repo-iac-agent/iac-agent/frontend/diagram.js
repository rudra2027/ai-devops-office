/* Architecture diagram renderer: layered auto-layout, nested boundaries, labelled animated flows, pan / zoom, SVG export. */
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const ICON = {
    internet: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    users: '<circle cx="9" cy="8" r="3.2"/><path d="M3 19a6 6 0 0 1 12 0M16 5a3 3 0 0 1 0 6M18 19a5 5 0 0 0-3-4.5"/>',
    virtual_machine: '<rect x="3" y="4" width="18" height="11" rx="2"/><path d="M8 20h8M12 15v5"/>',
    kubernetes_cluster: '<path d="M12 3l7.5 4v8.5L12 21l-7.5-5.5V7z"/><circle cx="12" cy="12" r="2.2"/>',
    container_service: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12L4 7.5M12 12v9"/>',
    serverless_function: '<path d="M13 3L5 13h6l-1 8 8-10h-6z"/>',
    sql_database: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
    nosql_database: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
    cache: '<path d="M4 12h5l2-6 3 12 2-6h4"/>',
    object_storage: '<path d="M5 8h14l-1.5 11a2 2 0 0 1-2 1.7H8.5a2 2 0 0 1-2-1.7z"/><path d="M4 8c0-2 3.6-3.5 8-3.5S20 6 20 8"/>',
    block_storage: '<rect x="4" y="5" width="16" height="14" rx="2"/><circle cx="12" cy="12" r="3.5"/><circle cx="12" cy="12" r=".8"/>',
    message_queue: '<path d="M4 7h12M4 12h16M4 17h12M17 5l3 2-3 2M17 15l3 2-3 2"/>',
    load_balancer: '<circle cx="5" cy="12" r="2"/><path d="M7 12h4l4-6h4M11 12l4 6h4"/><circle cx="20" cy="6" r="1.2"/><circle cx="20" cy="18" r="1.2"/>',
    cdn: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18"/>',
    dns: '<circle cx="12" cy="12" r="4"/><path d="M16 12v1.5a2.5 2.5 0 0 0 5 0V12a9 9 0 1 0-3.5 7"/>',
    firewall: '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/>',
    secrets: '<circle cx="8" cy="14" r="3.5"/><path d="M11 12l8-8M16 7l2 2M14 9l2 2"/>',
    identity: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    monitoring: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    network: '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/><path d="M12 7v5M12 12L6 16.5M12 12l6 4.5"/>',
    other: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/>',
  };
  const COLOR = { internet: "#60a5fa", users: "#60a5fa", cdn: "#60a5fa", dns: "#60a5fa", load_balancer: "#38bdf8", network: "#60a5fa",
    virtual_machine: "#8b7bff", kubernetes_cluster: "#8b7bff", container_service: "#8b7bff", serverless_function: "#a78bfa",
    sql_database: "#22d3b6", nosql_database: "#22d3b6", cache: "#fbbf24", object_storage: "#34d399", block_storage: "#34d399", message_queue: "#fb923c",
    firewall: "#f472b6", secrets: "#f472b6", identity: "#f472b6", monitoring: "#a3e635", other: "#94a3b8" };
  const GROUP_COLOR = { cloud: "#7c5cff", region: "#22d3b6", network: "#60a5fa", subnet: "#60a5fa", zone: "#fbbf24", other: "#94a3b8" };
  const W = 168, H = 68, GX = 96, GY = 36, PAD = 26;
  const el = (tag, attrs = {}, text) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); if (text != null) n.textContent = text; return n; };
  const css = (v, fb) => (getComputedStyle(document.documentElement).getPropertyValue(v).trim() || fb);

  function layout(d) {
    const nodes = d.nodes.map((n) => ({ ...n, w: W, h: H }));
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const edges = d.edges.filter((e) => byId[e.source] && byId[e.target]);
    const level = Object.fromEntries(nodes.map((n) => [n.id, 0]));
    for (let i = 0; i < nodes.length; i++) {
      let changed = false;
      edges.forEach((e) => { if (level[e.target] < level[e.source] + 1 && level[e.source] + 1 < nodes.length) { level[e.target] = level[e.source] + 1; changed = true; } });
      if (!changed) break;
    }
    const cols = {};
    nodes.forEach((n) => (cols[level[n.id]] ||= []).push(n));
    const order = Object.keys(cols).map(Number).sort((a, b) => a - b);
    // a couple of barycenter passes to cut down edge crossings
    for (let pass = 0; pass < 3; pass++) {
      order.forEach((lv, ci) => {
        if (ci === 0) return;
        const pos = (n) => { const ins = edges.filter((e) => e.target === n.id).map((e) => cols[level[e.source]].indexOf(byId[e.source])); return ins.length ? ins.reduce((a, b) => a + b, 0) / ins.length : 1e9; };
        cols[lv].sort((a, b) => pos(a) - pos(b));
      });
    }
    const tallest = Math.max(...order.map((lv) => cols[lv].length));
    order.forEach((lv, ci) => {
      const col = cols[lv], total = col.length * H + (col.length - 1) * GY, full = tallest * H + (tallest - 1) * GY;
      col.forEach((n, i) => { n.x = 60 + ci * (W + GX); n.y = 70 + (full - total) / 2 + i * (H + GY); });
    });
    // boundaries: bounding box of everything inside, nested groups grow their parents
    const groups = d.groups.map((g) => ({ ...g }));
    const gById = Object.fromEntries(groups.map((g) => [g.id, g]));
    const depth = (g) => { let n = 0; for (let p = g; p && p.parent && gById[p.parent] && n < 8; p = gById[p.parent]) n++; return n; };
    [...groups].sort((a, b) => depth(b) - depth(a)).forEach((g) => {
      const kids = nodes.filter((n) => n.group === g.id).map((n) => ({ x1: n.x, y1: n.y, x2: n.x + n.w, y2: n.y + n.h }))
        .concat(groups.filter((c) => c.parent === g.id && c.box).map((c) => c.box));
      if (!kids.length) return;
      g.box = { x1: Math.min(...kids.map((k) => k.x1)) - PAD, y1: Math.min(...kids.map((k) => k.y1)) - PAD - 18, x2: Math.max(...kids.map((k) => k.x2)) + PAD, y2: Math.max(...kids.map((k) => k.y2)) + PAD };
    });
    const boxes = nodes.map((n) => ({ x1: n.x, y1: n.y, x2: n.x + n.w, y2: n.y + n.h })).concat(groups.filter((g) => g.box).map((g) => g.box));
    const bounds = { x1: Math.min(...boxes.map((b) => b.x1)) - 30, y1: Math.min(...boxes.map((b) => b.y1)) - 30, x2: Math.max(...boxes.map((b) => b.x2)) + 30, y2: Math.max(...boxes.map((b) => b.y2)) + 30 };
    return { nodes, byId, edges, groups: groups.filter((g) => g.box).sort((a, b) => depth(a) - depth(b)), bounds };
  }

  function render(d, { height = 420, title = "" } = {}) {
    const L = layout(d);
    const text = css("--text", "#eef0ff"), muted = css("--muted", "#9ba2c4"), surface = css("--surface-solid", "#141830"), border = css("--border-strong", "rgba(255,255,255,.2)");
    const bw = L.bounds.x2 - L.bounds.x1, bh = L.bounds.y2 - L.bounds.y1;
    const svg = el("svg", { class: "arch", viewBox: `${L.bounds.x1} ${L.bounds.y1} ${bw} ${bh}`, width: "100%", height: String(height), role: "img", "aria-label": `Architecture diagram: ${d.title || title}`, xmlns: NS });
    svg.style.cssText = "display:block;cursor:grab;touch-action:none;font-family:Inter,system-ui,sans-serif";
    const defs = el("defs");
    const marker = el("marker", { id: "arr", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "8", markerHeight: "8", orient: "auto-start-reverse" });
    marker.append(el("path", { d: "M0 0L10 5L0 10z", fill: muted }));
    defs.append(marker);
    svg.append(defs);

    L.groups.forEach((g) => {
      const c = GROUP_COLOR[g.kind] || GROUP_COLOR.other, b = g.box;
      svg.append(el("rect", { x: b.x1, y: b.y1, width: b.x2 - b.x1, height: b.y2 - b.y1, rx: 16, fill: c, "fill-opacity": ".06", stroke: c, "stroke-opacity": ".55", "stroke-dasharray": "7 6" }));
      const label = el("text", { x: b.x1 + 14, y: b.y1 + 17, fill: c, "font-size": 12, "font-weight": 700, "letter-spacing": ".08em" }, `${(g.kind || "").toUpperCase()}  ${g.label}`);
      svg.append(label);
    });

    const edgeEls = [];
    L.edges.forEach((e) => {
      const s = L.byId[e.source], t = L.byId[e.target];
      const back = t.x <= s.x;
      const x1 = back ? s.x + W / 2 : s.x + W, y1 = back ? s.y + H : s.y + H / 2, x2 = back ? t.x + W / 2 : t.x, y2 = back ? t.y + H : t.y + H / 2;
      const dx = Math.max(40, Math.abs(x2 - x1) / 2);
      const path = back ? `M${x1},${y1} C${x1},${y1 + 70} ${x2},${y2 + 70} ${x2},${y2}` : `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
      const g = el("g", { "data-s": e.source, "data-t": e.target });
      g.append(el("path", { d: path, fill: "none", stroke: muted, "stroke-width": 1.6, "stroke-opacity": ".75", "marker-end": "url(#arr)" }));
      const flow = el("path", { d: path, fill: "none", stroke: "#22d3b6", "stroke-width": 2.2, "stroke-linecap": "round", "stroke-dasharray": "2 12", opacity: ".95" });
      flow.append(el("animate", { attributeName: "stroke-dashoffset", from: "28", to: "0", dur: "1.1s", repeatCount: "indefinite" }));
      g.append(flow);
      if (e.label) {
        const mx = back ? (x1 + x2) / 2 : (x1 + x2) / 2, my = back ? Math.max(y1, y2) + 56 : (y1 + y2) / 2 - 8, w = e.label.length * 6.4 + 14;
        g.append(el("rect", { x: mx - w / 2, y: my - 11, width: w, height: 18, rx: 9, fill: surface, stroke: border }), el("text", { x: mx, y: my + 2, "text-anchor": "middle", fill: text, "font-size": 11 }, e.label));
      }
      svg.append(g);
      edgeEls.push(g);
    });

    L.nodes.forEach((n) => {
      const c = COLOR[n.kind] || COLOR.other;
      const g = el("g", { transform: `translate(${n.x},${n.y})`, tabindex: 0, "data-id": n.id });
      g.style.cursor = "pointer";
      g.append(el("title", {}, `${n.label}\n${n.kind.replace(/_/g, " ")}${n.resource_types.length ? "\n" + n.resource_types.join("\n") : ""}${n.note ? "\n" + n.note : ""}`));
      g.append(el("rect", { width: W, height: H, rx: 14, fill: surface, stroke: c, "stroke-width": 1.6 }), el("rect", { width: 6, height: H, rx: 3, fill: c, x: 0 }));
      const ic = el("g", { transform: "translate(18,19) scale(1.1)", fill: "none", stroke: c, "stroke-width": 1.7, "stroke-linecap": "round", "stroke-linejoin": "round" });
      ic.innerHTML = ICON[n.kind] || ICON.other;
      g.append(ic);
      g.append(el("text", { x: 52, y: 29, fill: text, "font-size": 13.5, "font-weight": 650 }, n.label.length > 17 ? n.label.slice(0, 16) + "…" : n.label));
      const sub = n.resource_types[0] || n.kind.replace(/_/g, " ");
      g.append(el("text", { x: 52, y: 47, fill: muted, "font-size": 10.5, "font-family": "JetBrains Mono,ui-monospace,monospace" }, sub.length > 22 ? sub.slice(0, 21) + "…" : sub));
      if (n.note) g.append(el("text", { x: W - 10, y: 15, fill: muted, "font-size": 10, "text-anchor": "end" }, n.note.slice(0, 18)));
      g.addEventListener("mouseenter", () => edgeEls.forEach((eg) => { const on = eg.dataset.s === n.id || eg.dataset.t === n.id; eg.style.opacity = on ? 1 : 0.18; }));
      g.addEventListener("mouseleave", () => edgeEls.forEach((eg) => (eg.style.opacity = 1)));
      svg.append(g);
    });

    // pan + zoom
    let vb = { x: L.bounds.x1, y: L.bounds.y1, w: bw, h: bh };
    const full = { ...vb };
    const apply = () => svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
    const zoom = (f, cx = vb.x + vb.w / 2, cy = vb.y + vb.h / 2) => { const nw = Math.min(full.w * 3, Math.max(full.w / 6, vb.w * f)), k = nw / vb.w; vb = { x: cx - (cx - vb.x) * k, y: cy - (cy - vb.y) * k, w: nw, h: vb.h * k }; apply(); };
    svg.addEventListener("wheel", (e) => { e.preventDefault(); const r = svg.getBoundingClientRect(); zoom(e.deltaY > 0 ? 1.12 : 0.89, vb.x + ((e.clientX - r.left) / r.width) * vb.w, vb.y + ((e.clientY - r.top) / r.height) * vb.h); }, { passive: false });
    let drag = null;
    svg.addEventListener("pointerdown", (e) => { if (e.target.closest("[data-id]")) return; drag = { x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y }; svg.setPointerCapture(e.pointerId); svg.style.cursor = "grabbing"; });
    svg.addEventListener("pointermove", (e) => { if (!drag) return; const r = svg.getBoundingClientRect(); vb.x = drag.vx - ((e.clientX - drag.x) / r.width) * vb.w; vb.y = drag.vy - ((e.clientY - drag.y) / r.height) * vb.h; apply(); });
    svg.addEventListener("pointerup", () => { drag = null; svg.style.cursor = "grab"; });

    const exportSvg = () => {
      const clone = svg.cloneNode(true);
      clone.setAttribute("viewBox", `${full.x} ${full.y} ${full.w} ${full.h}`);
      clone.setAttribute("width", String(full.w)); clone.setAttribute("height", String(full.h));
      const bg = el("rect", { x: full.x, y: full.y, width: full.w, height: full.h, fill: css("--bg", "#0a0c16") });
      clone.insertBefore(bg, clone.firstChild.nextSibling);
      const blob = new Blob(['<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" });
      const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `architecture-${(d.title || "diagram").toLowerCase().replace(/[^a-z0-9]+/g, "-")}.svg` });
      document.body.append(a); a.click(); a.remove();
    };
    const btn = (label, fn, title) => Object.assign(document.createElement("button"), { className: "btn btn-sm", textContent: label, title, type: "button", onclick: fn });
    const bar = Object.assign(document.createElement("div"), { className: "diagram-bar" });
    bar.append(btn("+", () => zoom(0.8), "Zoom in"), btn("−", () => zoom(1.25), "Zoom out"), btn("Fit", () => { vb = { ...full }; apply(); }, "Fit to view"), btn("Download SVG", exportSvg, "Save as an image"));
    const wrap = Object.assign(document.createElement("div"), { className: "diagram" });
    wrap.append(bar, svg);
    return wrap;
  }
  window.Diagram = { render, ICON, COLOR };
})();
