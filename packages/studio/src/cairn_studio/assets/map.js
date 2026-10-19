// The network map: topics, papers, ideas and notes on a canvas, laid out by a small force
// simulation. Positions survive live refreshes, so a newly saved note settles into place.

const KINDS = ["topic", "paper", "idea", "note"];
const LABELS = { topic: "Topics", paper: "Papers", idea: "Ideas", note: "Notes" };
const STATUSES = ["seed", "exploring", "testing", "parked", "developed"];
const REPEL_RANGE = 420; // pairs further apart than this do not push each other

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  node.append(...children.filter((c) => c !== null && c !== undefined));
  return node;
}

function icon(paths) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = paths;
  return svg;
}

export class NetworkMap {
  constructor({ open }) {
    this.open = open;
    this.nodes = [];
    this.bySlug = new Map();
    this.edges = [];
    this.view = { x: 0, y: 0, k: 1 };
    this.shown = new Set(KINDS);
    this.status = "";
    this.query = "";
    this.selected = null;
    this.hover = null;
    this.alpha = 0;
    this.frame = 0;
    this.pointers = new Map();
    this.fitted = false;
    this.build();
  }

  // Elements

  build() {
    this.canvas = el("canvas", { role: "img", "aria-label": "Network of topics, papers and ideas" });
    this.ctx = this.canvas.getContext("2d");
    this.search = el("input", { type: "search", placeholder: "Find on map", "aria-label": "Find on map", autocomplete: "off" });
    this.search.addEventListener("input", () => {
      this.query = this.search.value.trim().toLowerCase();
      this.draw();
    });
    this.search.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const hit = this.matches()[0];
      if (hit) this.focus(hit.slug);
    });
    const filters = el(
      "div",
      { class: "filters" },
      ...KINDS.map((kind) =>
        el(
          "button",
          { type: "button", "aria-pressed": "true", "data-kind": kind, onclick: (event) => this.toggle(kind, event.currentTarget) },
          el("span", { class: `kind ${kind}` }, LABELS[kind]),
        ),
      ),
    );
    this.statusPicker = el(
      "select",
      { "aria-label": "Idea status", class: "chip" },
      el("option", { value: "" }, "Any status"),
      ...STATUSES.map((s) => el("option", { value: s }, s[0].toUpperCase() + s.slice(1))),
    );
    this.statusPicker.addEventListener("change", () => {
      this.status = this.statusPicker.value;
      this.draw();
    });
    filters.append(this.statusPicker);
    this.tools = el("div", { class: "map-tools" }, this.search, filters);
    const zoomButton = (label, paths, action) => el("button", { type: "button", "aria-label": label, title: label, onclick: action }, icon(paths));
    this.zoom = el(
      "div",
      { class: "map-zoom" },
      zoomButton("Zoom in", '<path d="M12 6v12M6 12h12"/>', () => this.zoomBy(1.4)),
      zoomButton("Zoom out", '<path d="M6 12h12"/>', () => this.zoomBy(1 / 1.4)),
      zoomButton("Fit", '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>', () => this.fit(true)),
    );
    this.preview = el("div", { class: "card preview" });
    this.preview.hidden = true;
    this.hint = el("div", { class: "map-hint" }, "Tap a note to see it; drag to move, pinch or scroll to zoom");

    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => this.down(e));
    c.addEventListener("pointermove", (e) => this.move(e));
    c.addEventListener("pointerup", (e) => this.up(e));
    c.addEventListener("pointercancel", (e) => this.up(e, true));
    c.addEventListener("pointerleave", () => {
      if (!this.pointers.size && this.hover) {
        this.hover = null;
        this.draw();
      }
    });
    c.addEventListener("wheel", (e) => this.wheel(e), { passive: false });
    c.addEventListener("dblclick", (e) => {
      const hit = this.hit(e.offsetX, e.offsetY);
      if (hit) this.open(hit.slug);
    });
    this.onKey = (e) => {
      if (e.key === "Escape" && this.selected) this.select(null);
    };
    this.scheme = window.matchMedia("(prefers-color-scheme: dark)");
    this.onScheme = () => {
      this.readTheme();
      this.draw();
    };
  }

  mount(wrap) {
    this.unmount();
    wrap.append(this.canvas, this.tools, this.zoom, this.preview, this.hint);
    this.wrap = wrap;
    this.resizer = new ResizeObserver(() => this.resize());
    this.resizer.observe(wrap);
    document.addEventListener("keydown", this.onKey);
    this.scheme.addEventListener("change", this.onScheme);
    this.readTheme();
  }

  unmount() {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.resizer?.disconnect();
    document.removeEventListener("keydown", this.onKey);
    this.scheme.removeEventListener("change", this.onScheme);
  }

  destroy() {
    this.unmount();
    clearTimeout(this.newTimer);
  }

  readTheme() {
    const css = getComputedStyle(document.documentElement);
    const v = (name) => css.getPropertyValue(name).trim();
    this.theme = {
      bg: v("--bg"),
      text: v("--text"),
      muted: v("--muted"),
      line: v("--line"),
      faint: v("--faint"),
      accent: v("--accent"),
      topic: v("--topic"),
      paper: v("--paper"),
      idea: v("--idea"),
      note: v("--note"),
    };
  }

  resize() {
    const box = this.wrap.getBoundingClientRect();
    this.width = box.width;
    this.height = box.height;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(box.width * dpr);
    this.canvas.height = Math.round(box.height * dpr);
    this.dpr = dpr;
    if (!this.fitted && this.nodes.length) {
      this.fit(false);
      this.fitted = true;
    }
    if (this.pending && this.width) {
      const slug = this.pending;
      this.pending = null;
      this.focus(slug);
    }
    this.draw();
  }

  // Data

  setData({ nodes, edges }) {
    const old = this.bySlug;
    const fresh = !this.nodes.length;
    this.bySlug = new Map();
    this.nodes = nodes.map((n) => {
      const before = old.get(n.slug);
      const node = { ...n, x: before?.x, y: before?.y, vx: 0, vy: 0, neighbors: new Set(), isNew: !before && !fresh };
      node.r = n.kind === "topic" ? 6 + 2.2 * Math.sqrt(n.degree) : n.kind === "idea" ? 6.5 : n.kind === "paper" ? 5 : 4.2;
      this.bySlug.set(n.slug, node);
      return node;
    });
    this.edges = edges
      .map((e) => ({ ...e, a: this.bySlug.get(e.source), b: this.bySlug.get(e.target) }))
      .filter((e) => e.a && e.b);
    for (const e of this.edges) {
      e.a.neighbors.add(e.b);
      e.b.neighbors.add(e.a);
    }
    this.place();
    if (this.selected) this.selected = this.bySlug.get(this.selected.slug) || null;
    if (fresh) {
      this.alpha = 1;
      for (let i = 0; i < 240 && this.alpha > 0.02; i++) this.tick();
      this.fitted = false;
      if (this.width) {
        this.fit(false);
        this.fitted = true;
      }
    } else {
      this.alpha = Math.max(this.alpha, 0.35);
    }
    this.renderPreview();
    this.run();
    clearTimeout(this.newTimer);
    this.newTimer = setTimeout(() => {
      for (const n of this.nodes) n.isNew = false;
      this.draw();
    }, 8000);
  }

  place() {
    // Topics on a ring, everything else beside a placed neighbour, so the layout starts tidy.
    const topics = this.nodes.filter((n) => n.kind === "topic" && n.x === undefined);
    const ring = 60 + 18 * Math.sqrt(this.nodes.length);
    topics.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(topics.length, 1);
      n.x = ring * Math.cos(angle) + Math.random();
      n.y = ring * Math.sin(angle) + Math.random();
    });
    for (const n of this.nodes) {
      if (n.x !== undefined) continue;
      const anchor = [...n.neighbors].find((m) => m.x !== undefined);
      const spread = 40;
      n.x = (anchor ? anchor.x : 0) + (Math.random() - 0.5) * spread;
      n.y = (anchor ? anchor.y : 0) + (Math.random() - 0.5) * spread;
    }
  }

  visible(n) {
    if (!this.shown.has(n.kind)) return false;
    if (this.status && n.kind === "idea" && n.status !== this.status) return false;
    return true;
  }

  matches() {
    if (!this.query) return [];
    return this.nodes.filter((n) => this.visible(n) && n.title.toLowerCase().includes(this.query)).sort((a, b) => b.degree - a.degree);
  }

  toggle(kind, button) {
    if (this.shown.has(kind)) this.shown.delete(kind);
    else this.shown.add(kind);
    button.setAttribute("aria-pressed", String(this.shown.has(kind)));
    if (this.selected && !this.visible(this.selected)) this.select(null);
    this.draw();
  }

  // Simulation

  tick() {
    const nodes = this.nodes;
    const alpha = this.alpha;
    const range2 = REPEL_RANGE * REPEL_RANGE;
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 > range2) continue;
        if (d2 < 1) {
          dx = Math.random() - 0.5;
          dy = Math.random() - 0.5;
          d2 = 1;
        }
        const strength = (a.kind === "topic" ? 2 : 1) * (b.kind === "topic" ? 2 : 1);
        const f = (380 * strength * alpha) / d2;
        a.vx += dx * f * 0.5;
        a.vy += dy * f * 0.5;
        b.vx -= dx * f * 0.5;
        b.vy -= dy * f * 0.5;
      }
    }
    for (const e of this.edges) {
      const between = e.a.kind === "topic" && e.b.kind === "topic";
      const rest = between ? 110 : e.kind === "topic" ? 46 + e.b.r * 2 : 90;
      const k = e.kind === "topic" ? 0.08 : 0.025;
      const dx = e.b.x - e.a.x;
      const dy = e.b.y - e.a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = ((d - rest) / d) * k * alpha;
      // The lighter end moves more, so topics stay put and their notes gather round them.
      const wa = e.b.degree + 1;
      const wb = e.a.degree + 1;
      const share = wa / (wa + wb);
      e.a.vx += dx * f * share;
      e.a.vy += dy * f * share;
      e.b.vx -= dx * f * (1 - share);
      e.b.vy -= dy * f * (1 - share);
    }
    for (const n of nodes) {
      n.vx -= n.x * 0.004 * alpha;
      n.vy -= n.y * 0.004 * alpha;
      if (n.fixed) {
        n.vx = n.vy = 0;
        continue;
      }
      n.vx *= 0.62;
      n.vy *= 0.62;
      n.x += n.vx;
      n.y += n.vy;
    }
    this.alpha *= 0.985;
  }

  run() {
    if (this.frame || !this.wrap) return;
    const step = () => {
      this.frame = 0;
      if (this.alpha > 0.01) {
        const ticks = this.nodes.length > 600 ? 1 : 2;
        for (let i = 0; i < ticks; i++) this.tick();
        this.frame = requestAnimationFrame(step);
      }
      this.draw();
    };
    this.frame = requestAnimationFrame(step);
  }

  // View

  toScreen(n) {
    return [n.x * this.view.k + this.width / 2 + this.view.x, n.y * this.view.k + this.height / 2 + this.view.y];
  }

  toWorld(sx, sy) {
    return [(sx - this.width / 2 - this.view.x) / this.view.k, (sy - this.height / 2 - this.view.y) / this.view.k];
  }

  fit(animate) {
    const shown = this.nodes.filter((n) => this.visible(n));
    if (!shown.length || !this.width) return;
    let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
    for (const n of shown) {
      x0 = Math.min(x0, n.x - n.r);
      y0 = Math.min(y0, n.y - n.r);
      x1 = Math.max(x1, n.x + n.r);
      y1 = Math.max(y1, n.y + n.r);
    }
    const pad = Math.min(80, this.width * 0.1);
    const k = Math.min(2.2, Math.max(0.15, Math.min((this.width - pad) / (x1 - x0 || 1), (this.height - pad * 1.6) / (y1 - y0 || 1))));
    this.animateTo({ k, x: -((x0 + x1) / 2) * k, y: -((y0 + y1) / 2) * k + 18 }, animate);
  }

  zoomBy(factor, sx = this.width / 2, sy = this.height / 2) {
    const k = Math.min(6, Math.max(0.1, this.view.k * factor));
    const [wx, wy] = this.toWorld(sx, sy);
    this.view.k = k;
    this.view.x = sx - this.width / 2 - wx * k;
    this.view.y = sy - this.height / 2 - wy * k;
    this.draw();
  }

  animateTo(target, animate = true) {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!animate || reduce) {
      Object.assign(this.view, target);
      return this.draw();
    }
    const start = { ...this.view };
    const began = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - began) / 380);
      const ease = 1 - Math.pow(1 - t, 3);
      for (const key of ["x", "y", "k"]) this.view[key] = start[key] + (target[key] - start[key]) * ease;
      this.draw();
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  focus(slug) {
    const node = this.bySlug.get(slug);
    if (!node) return;
    if (!this.width) return (this.pending = slug); // resize() focuses once the canvas has a size
    if (!this.visible(node)) {
      this.shown.add(node.kind);
      this.tools.querySelector(`[data-kind="${node.kind}"]`)?.setAttribute("aria-pressed", "true");
      if (node.kind === "idea") this.statusPicker.value = this.status = "";
    }
    this.select(node);
    const k = Math.max(this.view.k, 1.5);
    this.animateTo({ k, x: -node.x * k, y: -node.y * k - this.height * 0.12 });
  }

  select(node) {
    this.selected = node;
    this.renderPreview();
    this.draw();
  }

  renderPreview() {
    const n = this.selected;
    this.preview.hidden = !n;
    this.hint.hidden = Boolean(n) || this.hintDismissed;
    if (!n) return;
    const neighbors = [...n.neighbors];
    const count = (kind) => neighbors.filter((m) => m.kind === kind).length;
    let meta;
    if (n.kind === "topic") {
      const parts = [["paper", "paper"], ["idea", "idea"], ["topic", "connected topic"]]
        .map(([kind, word]) => [count(kind), word])
        .filter(([c]) => c)
        .map(([c, word]) => `${c} ${word}${c === 1 ? "" : "s"}`);
      meta = parts.join(" · ") || "Nothing filed yet";
    } else {
      const topics = n.topics.map((s) => this.bySlug.get(s)?.title).filter(Boolean);
      meta = [n.kind === "idea" && n.status ? n.status[0].toUpperCase() + n.status.slice(1) : null, topics.join(", ") || "No topics yet"].filter(Boolean).join(" · ");
    }
    const open = el("a", { class: "button primary", href: `#/note/${encodeURIComponent(n.slug)}` }, "Open");
    const close = el("button", { type: "button", class: "button", onclick: () => this.select(null) }, "Close");
    const parts = [
      el("span", { class: `kind ${n.kind}` }, n.kind[0].toUpperCase() + n.kind.slice(1)),
      el("span", { class: "title" }, n.title),
      el("div", { class: "meta" }, meta),
      n.next_action ? el("div", { class: "meta" }, `Next: ${n.next_action}`) : null,
      el("div", { class: "actions" }, open, close),
    ];
    this.preview.replaceChildren(...parts.filter(Boolean));
  }

  // Input

  hit(sx, sy) {
    const [wx, wy] = this.toWorld(sx, sy);
    const slack = 8 / this.view.k; // a finger is wider than a dot
    let best = null;
    let bestD = Infinity;
    for (const n of this.nodes) {
      if (!this.visible(n)) continue;
      const d = Math.hypot(n.x - wx, n.y - wy) - n.r;
      if (d < slack && d < bestD) {
        best = n;
        bestD = d;
      }
    }
    return best;
  }

  down(e) {
    this.canvas.setPointerCapture(e.pointerId);
    this.pointers.set(e.pointerId, { x: e.offsetX, y: e.offsetY, sx: e.offsetX, sy: e.offsetY });
    if (this.pointers.size === 1) {
      this.dragNode = this.hit(e.offsetX, e.offsetY);
      this.moved = 0;
    } else if (this.pointers.size === 2) {
      if (this.dragNode) this.dragNode.fixed = false;
      this.dragNode = null;
      const [a, b] = [...this.pointers.values()];
      this.pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), k: this.view.k };
    }
    this.hintDismissed = true;
    this.hint.hidden = true;
  }

  move(e) {
    const p = this.pointers.get(e.pointerId);
    if (!p) {
      const hit = this.hit(e.offsetX, e.offsetY);
      if (hit !== this.hover) {
        this.hover = hit;
        this.canvas.classList.toggle("over", Boolean(hit));
        this.draw();
      }
      return;
    }
    const dx = e.offsetX - p.x;
    const dy = e.offsetY - p.y;
    p.x = e.offsetX;
    p.y = e.offsetY;
    this.moved += Math.abs(dx) + Math.abs(dy);
    if (this.pointers.size === 2 && this.pinch) {
      const [a, b] = [...this.pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      const factor = (this.pinch.k * (d / (this.pinch.d || 1))) / this.view.k;
      this.zoomBy(factor, (a.x + b.x) / 2, (a.y + b.y) / 2);
      this.view.x += dx / 2;
      this.view.y += dy / 2;
      return;
    }
    if (this.moved < 4) return;
    this.canvas.classList.add("dragging");
    if (this.dragNode) {
      const [wx, wy] = this.toWorld(e.offsetX, e.offsetY);
      Object.assign(this.dragNode, { x: wx, y: wy, fixed: true });
      this.alpha = Math.max(this.alpha, 0.25);
      this.run();
    } else {
      this.view.x += dx;
      this.view.y += dy;
    }
    this.draw();
  }

  up(e, cancelled = false) {
    const p = this.pointers.get(e.pointerId);
    this.pointers.delete(e.pointerId);
    if (this.pointers.size < 2) this.pinch = null;
    this.canvas.classList.remove("dragging");
    if (this.dragNode) this.dragNode.fixed = false;
    if (!p || cancelled || this.pointers.size) return (this.dragNode = null);
    if (this.moved < 6) {
      this.select(this.hit(e.offsetX, e.offsetY));
    }
    this.dragNode = null;
  }

  wheel(e) {
    e.preventDefault();
    const scale = e.deltaMode === 1 ? 32 : 1;
    if (e.ctrlKey || e.deltaMode || Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      this.zoomBy(Math.exp((-e.deltaY * scale) / (e.ctrlKey ? 120 : 600)), e.offsetX, e.offsetY);
    } else {
      this.view.x -= e.deltaX;
      this.view.y -= e.deltaY;
      this.draw();
    }
  }

  // Drawing

  draw() {
    const ctx = this.ctx;
    if (!this.width || !this.theme) return;
    const t = this.theme;
    const { k } = this.view;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.setTransform(this.dpr * k, 0, 0, this.dpr * k, this.dpr * (this.width / 2 + this.view.x), this.dpr * (this.height / 2 + this.view.y));

    const focus = this.selected || this.hover;
    const found = new Set(this.matches());
    const lit = (n) => {
      if (found.size) return found.has(n);
      if (!focus) return true;
      return n === focus || focus.neighbors.has(n);
    };

    for (const e of this.edges) {
      if (!this.visible(e.a) || !this.visible(e.b)) continue;
      const on = focus ? e.a === focus || e.b === focus : !found.size;
      ctx.globalAlpha = on ? (focus ? 0.9 : 0.55) : 0.12;
      ctx.strokeStyle = on && focus ? t.muted : t.faint;
      ctx.lineWidth = (e.kind === "topic" ? 1.1 : 0.9) / Math.sqrt(k);
      ctx.setLineDash(e.kind === "link" ? [4 / k, 3 / k] : []);
      ctx.beginPath();
      ctx.moveTo(e.a.x, e.a.y);
      ctx.lineTo(e.b.x, e.b.y);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    const order = this.nodes.filter((n) => this.visible(n)).sort((a, b) => lit(a) - lit(b) || a.r - b.r);
    for (const n of order) {
      ctx.globalAlpha = lit(n) ? 1 : 0.18;
      this.shape(n);
      ctx.fillStyle = t[n.kind] || t.note;
      ctx.fill();
      ctx.lineWidth = 1.5 / k;
      ctx.strokeStyle = t.bg;
      ctx.stroke();
      if (n === this.selected || found.has(n) || n.isNew) {
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r + 4 / k, 0, 2 * Math.PI);
        ctx.lineWidth = 2 / k;
        ctx.strokeStyle = n.isNew ? t.idea : t.text;
        ctx.stroke();
      }
    }

    this.labels(order, lit, focus, found);
    ctx.globalAlpha = 1;
  }

  shape(n) {
    const ctx = this.ctx;
    const r = n.r;
    ctx.beginPath();
    if (n.kind === "idea") {
      ctx.moveTo(n.x, n.y - r * 1.15);
      ctx.lineTo(n.x + r * 1.15, n.y);
      ctx.lineTo(n.x, n.y + r * 1.15);
      ctx.lineTo(n.x - r * 1.15, n.y);
      ctx.closePath();
    } else if (n.kind === "note") {
      ctx.rect(n.x - r, n.y - r, 2 * r, 2 * r);
    } else {
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
    }
  }

  labels(order, lit, focus, found) {
    const ctx = this.ctx;
    const t = this.theme;
    const { k } = this.view;
    const placed = [];
    const want = (n) => {
      if (found.size) return found.has(n);
      if (focus) return lit(n);
      if (n.kind === "topic") return true; // overlapping labels are skipped below
      return k > 1.7;
    };
    const candidates = order.filter(want).sort((a, b) => (b === this.selected) - (a === this.selected) || (b.kind === "topic") - (a.kind === "topic") || b.degree - a.degree);
    ctx.textBaseline = "middle";
    ctx.lineJoin = "round";
    for (const n of candidates) {
      const size = n.kind === "topic" ? 13 : 12;
      ctx.font = `${n.kind === "topic" ? 650 : 500} ${size / k}px ui-sans-serif, system-ui, -apple-system, sans-serif`;
      const text = n.title.length > 46 ? `${n.title.slice(0, 44)}…` : n.title;
      const width = ctx.measureText(text).width * k;
      const [sx, sy] = this.toScreen(n);
      const box = [sx + n.r * k + 5, sy - size * 0.7, sx + n.r * k + 5 + width, sy + size * 0.7];
      if (box[2] < 0 || box[0] > this.width || box[3] < 0 || box[1] > this.height) continue;
      if (placed.some((p) => box[0] < p[2] && box[2] > p[0] && box[1] < p[3] && box[3] > p[1])) continue;
      placed.push(box);
      const x = n.x + n.r + 5 / k;
      ctx.globalAlpha = 1;
      ctx.lineWidth = 3.5 / k;
      ctx.strokeStyle = t.bg;
      ctx.strokeText(text, x, n.y);
      ctx.fillStyle = n.kind === "topic" ? t.text : t.muted;
      ctx.fillText(text, x, n.y);
    }
  }
}
