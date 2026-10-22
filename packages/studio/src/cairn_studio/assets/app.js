// Cairn Studio: a hash-routed app over the read-only JSON API.
// Server-rendered note HTML has raw HTML escaped; every other string goes in as text.

import { NetworkMap } from "./map.js";

const STATUSES = ["seed", "exploring", "testing", "parked", "developed"];
const STATUS_HINTS = {
  seed: "Noted, not yet worked on",
  exploring: "Reading and reasoning",
  testing: "Checking it against data",
  parked: "Set aside, with a reason",
  developed: "Done or grown into a project",
};
const KINDS = { topic: "Topic", paper: "Paper", idea: "Idea", note: "Note" };
const PLURAL = { topic: "topics", paper: "papers", idea: "ideas", note: "notes" };

const view = document.getElementById("view");
const picker = document.getElementById("collection");
const state = { collection: null, route: null, map: null, events: null, render: null };

// Helpers

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "html") el.innerHTML = value; // only server-rendered Markdown
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function remember(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch {
    return null;
  }
}

async function api(name, params = {}) {
  const query = new URLSearchParams({ c: state.collection || "", ...params });
  const response = await fetch(`/api/${name}?${query}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function noteHref(slug) {
  return `#/note/${encodeURIComponent(slug)}`;
}

function ago(value) {
  if (!value) return "";
  const then = new Date(`${value}T12:00:00`);
  if (Number.isNaN(then.getTime())) return value;
  const days = Math.round((Date.now() - then.getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.round(days / 7)} weeks ago`;
  return then.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function dayLabel(value) {
  const text = ago(value);
  return text ? text[0].toUpperCase() + text.slice(1) : "Undated";
}

function kindBadge(kind) {
  return h("span", { class: `kind ${kind}` }, KINDS[kind] || kind);
}

function topicChips(topics, limit = 4) {
  if (!topics || !topics.length) return null;
  const shown = topics.slice(0, limit).map((t) => h("a", { class: "chip topic", href: noteHref(t.slug) }, t.title));
  if (topics.length > limit) shown.push(h("span", { class: "chip" }, `+${topics.length - limit}`));
  return h("div", { class: "chips" }, shown);
}

function toast(text) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 1800);
}

function noteRow(note, extra) {
  return h(
    "li",
    {},
    h(
      "a",
      { class: "row", href: noteHref(note.slug) },
      kindBadge(note.kind),
      h("span", { class: "title" }, note.title),
      h(
        "span",
        { class: "meta" },
        note.kind === "idea" && note.status ? h("span", { class: `pill ${note.status}` }, note.status) : null,
        note.topics && note.topics.length ? note.topics.map((t) => t.title).join(" · ") : null,
        note.updated ? h("span", {}, `updated ${ago(note.updated)}`) : null,
      ),
      extra,
    ),
  );
}

function ideaCard(idea) {
  return h(
    "a",
    { class: `card idea-card ${idea.status}`, href: noteHref(idea.slug) },
    h("span", { class: "title" }, idea.title),
    idea.next_action ? h("p", { class: "next" }, h("b", {}, "Next: "), idea.next_action) : null,
    h(
      "span",
      { class: "when" },
      h("span", { class: `pill ${idea.status}` }, idea.status),
      idea.last_discussed ? h("span", {}, `discussed ${ago(idea.last_discussed)}`) : null,
      idea.stale ? h("span", { class: "stale" }, `quiet for ${idea.days_since} days`) : null,
    ),
    idea.topics && idea.topics.length
      ? h("span", { class: "chips" }, idea.topics.slice(0, 3).map((t) => h("span", { class: "chip topic" }, t.title)))
      : null,
  );
}

// Views

async function recentView() {
  const [recent, board] = await Promise.all([api("recent"), api("ideas")]);
  const counts = recent.counts;
  const moving = board.columns
    .filter((c) => ["exploring", "testing", "seed"].includes(c.status))
    .flatMap((c) => c.ideas)
    .sort((a, b) => (b.last_discussed || b.updated || "").localeCompare(a.last_discussed || a.updated || ""))
    .slice(0, 6);
  const groups = new Map();
  for (const note of recent.notes) {
    const key = dayLabel(note.updated);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(note);
  }
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total) {
    return h(
      "section",
      {},
      h("h1", {}, "Nothing here yet"),
      h("p", { class: "lede" }, "Read a paper or develop an idea with your agent; its notes appear here as they are saved."),
    );
  }
  return h(
    "section",
    {},
    h("h1", {}, "Recent"),
    h(
      "div",
      { class: "stats" },
      ["paper", "topic", "idea", "note"]
        .filter((k) => counts[k])
        .map((k) => h("a", { class: "card stat", href: k === "topic" ? "#/map" : k === "idea" ? "#/ideas" : `#/search?kind=${k}` }, h("b", {}, counts[k]), h("span", {}, PLURAL[k]))),
    ),
    moving.length ? [h("h2", {}, "Ideas in motion"), h("div", { class: "moving" }, moving.map(ideaCard))] : null,
    [...groups].map(([label, notes]) => [h("h2", {}, label), h("ul", { class: "rows card" }, notes.map((n) => noteRow(n)))]),
  );
}

async function ideasView() {
  const board = await api("ideas");
  const total = board.columns.reduce((n, c) => n + c.ideas.length, 0);
  return h(
    "section",
    {},
    h("h1", {}, "Ideas"),
    h("p", { class: "lede" }, total ? `${total} research idea${total === 1 ? "" : "s"}, by status. Status changes only on your decision.` : "No ideas yet. Brainstorm with your agent and they appear here."),
    h(
      "div",
      { class: "board" },
      board.columns.map((column) =>
        h(
          "div",
          { class: `column ${column.status}` },
          h(
            "header",
            {},
            h("span", { class: `pill ${column.status}` }, column.status),
            h("span", { class: "count" }, column.ideas.length),
            h("p", {}, STATUS_HINTS[column.status] || ""),
          ),
          column.ideas.length ? column.ideas.map(ideaCard) : h("div", { class: "none" }, "None"),
        ),
      ),
    ),
  );
}

function sourceLink(source) {
  const text = String(source);
  if (text.startsWith("doi:")) return h("a", { href: `https://doi.org/${text.slice(4)}`, target: "_blank", rel: "noopener" }, text);
  if (text.startsWith("arxiv:")) return h("a", { href: `https://arxiv.org/abs/${text.slice(6)}`, target: "_blank", rel: "noopener" }, text);
  if (/^https?:\/\//.test(text)) return h("a", { href: text, target: "_blank", rel: "noopener" }, text);
  return text;
}

function fieldList(fields, catalog) {
  const parts = [];
  const add = (label, value) => value && parts.push(h("span", {}, h("b", {}, label), value));
  const authors = fields.authors;
  add("Authors", Array.isArray(authors) ? authors.join(", ") : authors);
  add("Year", fields.year);
  add("Venue", fields.venue);
  if (fields.source) add("Source", sourceLink(fields.source));
  if (fields.url && fields.url !== fields.source) add("Link", sourceLink(fields.url));
  if (fields.doi && !String(fields.source || "").includes(String(fields.doi))) add("DOI", sourceLink(`doi:${fields.doi}`));
  // A paper note when the catalog is installed: its catalog paper, or none (conference, arXiv).
  if (catalog !== undefined)
    add("Catalog", catalog ? h("a", { href: `/catalog/catalog.html?paper=${encodeURIComponent(catalog)}` }, "In the journal catalog") : "Not in the journal catalog");
  add("Created", fields.created);
  add("Updated", fields.updated);
  return parts.length ? h("div", { class: "fields" }, parts) : null;
}

function statusTrack(status) {
  // Parked sits outside the path from seed to developed.
  if (status === "parked") return h("div", { class: "status-track parked" }, h("span", { class: "now" }, "parked"));
  const steps = STATUSES.filter((s) => s !== "parked");
  const reached = steps.indexOf(status);
  const items = steps.map((step, i) => [i ? h("i") : null, h("span", { class: i === reached ? "now" : i < reached ? "done" : "" }, step)]);
  return h("div", { class: `status-track ${status}` }, items);
}

function minutesTimeline(days) {
  if (!days || !days.length) return h("p", { class: "empty" }, "No minutes yet.");
  const who = { user: "User", agent: "Agent", source: "Source", note: "" };
  return [
    h(
      "div",
      { class: "legend" },
      h("span", { class: "user" }, "User"),
      h("span", { class: "agent" }, "Agent suggestion"),
      h("span", { class: "source" }, "Source"),
      h("span", { class: "status" }, "Status change"),
    ),
    h(
      "div",
      { class: "timeline" },
      [...days].reverse().map((day) =>
        h(
          "div",
          { class: `day${day.label === "review" ? " review" : ""}` },
          h("time", { datetime: day.date }, new Date(`${day.date}T12:00:00`).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })),
          day.label ? h("span", { class: "label" }, day.label) : null,
          h(
            "div",
            { class: "items" },
            day.items.map((item) =>
              item.who === "status"
                ? h("div", { class: "item status" }, h("span", { class: "who" }, "Status"), h("span", { class: `pill ${item.from}` }, item.from), "→", h("span", { class: `pill ${item.to}` }, item.to))
                : h(
                    "div",
                    { class: `item ${item.who}` },
                    item.label || who[item.who] ? h("span", { class: "who" }, item.label || who[item.who]) : null,
                    h("div", { class: "prose", html: item.html }),
                  ),
            ),
          ),
        ),
      ),
    ),
  ];
}

function groupedNotes(notes, emptyText) {
  if (!notes.length) return emptyText ? h("p", { class: "lede" }, emptyText) : null;
  const order = ["paper", "idea", "note", "topic"];
  const sorted = [...notes].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind) || a.title.localeCompare(b.title));
  return h("ul", { class: "rows card" }, sorted.map((n) => noteRow(n)));
}

function refList(refs) {
  const known = refs.filter((r) => !r.missing);
  if (!known.length) return null;
  return h("ul", { class: "rows card" }, known.map((r) => h("li", {}, h("a", { class: "row", href: noteHref(r.slug) }, kindBadge(r.kind), h("span", { class: "title" }, r.title)))));
}

async function noteView(slug) {
  const note = await api("note", { slug });
  document.title = `${note.title} · Cairn Studio`;
  const head = h(
    "div",
    { class: "note-head" },
    kindBadge(note.kind),
    h("h1", {}, note.title),
    note.aliases.length ? h("p", { class: "aliases" }, `Also: ${note.aliases.join("; ")}`) : null,
    note.trails.length
      ? h(
          "div",
          { class: "trails" },
          note.trails.map((trail) =>
            h("div", { class: "trail" }, trail.map((t, i) => [i ? h("span", { class: "sep" }, "›") : null, h("a", { href: noteHref(t.slug) }, t.title)])),
          ),
        )
      : null,
    fieldList(note.fields, note.catalog),
    note.kind === "idea" ? statusTrack(note.fields.status) : null,
    note.kind === "idea" && note.fields.next_action
      ? h("div", { class: "card next-action" }, h("b", {}, "Next action"), note.fields.next_action)
      : null,
    h(
      "div",
      { class: "actions" },
      h("a", { class: "button", href: `#/map?focus=${encodeURIComponent(note.slug)}` }, mapIcon(), "Show on map"),
    ),
  );
  const body = note.html.trim() ? h("div", { class: "prose", html: note.html }) : h("p", { class: "lede" }, note.kind === "topic" ? "No explanation yet." : "This note is empty.");
  const backlinks = note.backlinks.filter((b) => !(note.kind === "topic" && b.via === "topics"));
  const side = h(
    "aside",
    { class: "side" },
    note.kind !== "topic" && note.related.length ? [h("h2", {}, "Shares topics with"), groupedNotes(note.related)] : null,
    backlinks.length ? [h("h2", {}, "Linked from"), refList(backlinks)] : null,
    note.links.some((l) => !l.missing) ? [h("h2", {}, "Links to"), refList(note.links)] : null,
  );

  if (note.kind === "idea") {
    const account = h("div", { class: "pane" }, h("h2", {}, "Current account"), body, side);
    const minutes = h("div", { class: "pane" }, h("h2", {}, `Minutes`), minutesTimeline(note.minutes));
    const entries = note.minutes.length;
    const which = state.ideaPane || "account";
    account.hidden = which !== "account";
    minutes.hidden = which !== "minutes";
    const buttons = [
      ["account", "Account"],
      ["minutes", `Minutes (${entries})`],
    ].map(([key, label]) =>
      h("button", {
        type: "button",
        "aria-pressed": String(which === key),
        onclick: (event) => {
          state.ideaPane = key;
          account.hidden = key !== "account";
          minutes.hidden = key !== "minutes";
          event.currentTarget.parentElement.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === event.currentTarget)));
        },
      }, label),
    );
    return h("article", {}, head, h("div", { class: "segmented pane-switch" }, buttons), h("div", { class: "layout idea" }, account, minutes));
  }

  if (note.kind === "topic") {
    return h(
      "article",
      {},
      head,
      h(
        "div",
        { class: "layout" },
        h(
          "div",
          {},
          body,
          note.narrower.length ? [h("h2", {}, "Narrower topics"), h("div", { class: "chips" }, note.narrower.map((t) => h("a", { class: "chip topic", href: noteHref(t.slug) }, t.title)))] : null,
          h("h2", {}, "Filed here"),
          groupedNotes(note.members, "Nothing filed under this topic yet."),
        ),
        side,
      ),
    );
  }
  return h("article", {}, head, h("div", { class: "layout" }, body, side));
}

function mapIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.innerHTML = '<circle cx="6" cy="7" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="17" r="2.5"/><path d="M8.2 8.2l2.6 6.6M15.9 7.6l-2.7 7.1M8.5 6.8l7-.6"/>';
  return svg;
}

async function searchView(params) {
  const query = params.get("q") || "";
  const kind = params.get("kind") || "";
  const input = h("input", { type: "search", placeholder: "Search titles and notes", value: query, "aria-label": "Search", autocomplete: "off" });
  const results = h("div", {});
  const kinds = h(
    "div",
    { class: "segmented" },
    [["", "All"], ["paper", "Papers"], ["idea", "Ideas"], ["topic", "Topics"], ["note", "Notes"]].map(([key, label]) =>
      h("button", { type: "button", "aria-pressed": String(key === kind), "data-kind": key }, label),
    ),
  );
  let current = kind;
  let timer;
  const run = async () => {
    const q = input.value.trim();
    const next = new URLSearchParams();
    if (q) next.set("q", q);
    if (current) next.set("kind", current);
    const hash = `#/search${next.toString() ? `?${next}` : ""}`;
    if (location.hash !== hash) history.replaceState(null, "", hash);
    const data = await api("search", { q, kind: current });
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    results.replaceChildren(
      data.results.length
        ? h("ul", { class: "rows card" }, data.results.map((r) => noteRow(r, r.snippet && q ? h("span", { class: "snippet" }, highlight(r.snippet, terms)) : null)))
        : h("p", { class: "empty" }, q ? `Nothing matches “${q}”.` : "No notes of this kind yet."),
    );
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(run, 180);
  });
  kinds.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    current = button.dataset.kind;
    kinds.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    run();
  });
  await run();
  requestAnimationFrame(() => input.focus({ preventScroll: true }));
  state.refresh = run;
  return h("section", {}, h("h1", {}, "Search"), h("div", { class: "search-box" }, input, kinds), results);
}

function highlight(text, terms) {
  if (!terms.length) return text;
  const pattern = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(pattern).map((part, i) => (i % 2 ? h("mark", {}, part) : part));
}

async function mapView(params) {
  const data = await api("graph");
  const wrap = h("div", { class: "map-wrap" });
  if (!state.map || state.map.collection !== state.collection) {
    state.map?.destroy();
    state.map = new NetworkMap({ open: (slug) => (location.hash = noteHref(slug)) });
    state.map.collection = state.collection;
  }
  state.map.mount(wrap);
  state.map.setData(data);
  const focus = params.get("focus");
  if (focus) requestAnimationFrame(() => state.map.focus(focus));
  state.refresh = async () => state.map.setData(await api("graph"));
  return wrap;
}

// Routing

const ROUTES = [
  [/^\/?$/, "recent", () => recentView()],
  [/^\/map$/, "map", (_, params) => mapView(params)],
  [/^\/ideas$/, "ideas", () => ideasView()],
  [/^\/search$/, "search", (_, params) => searchView(params)],
  [/^\/note\/(.+)$/, null, (match) => noteView(decodeURIComponent(match[1]))],
];

async function route({ keepScroll = false } = {}) {
  const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query);
  for (const [pattern, tab, make] of ROUTES) {
    const match = path.match(pattern);
    if (!match) continue;
    document.querySelectorAll(".tabs a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    view.classList.toggle("map", tab === "map");
    if (tab) document.title = `${{ recent: "Recent", map: "Map", ideas: "Ideas", search: "Search" }[tab]} · Cairn Studio`;
    const scroll = window.scrollY;
    state.refresh = null;
    const ticket = (state.ticket = Symbol());
    let content;
    try {
      content = await make(match, params);
    } catch (error) {
      content = h("section", {}, h("h1", {}, "Not found"), h("p", { class: "lede error" }, error.message), h("a", { class: "button", href: "#/" }, "Back to recent"));
    }
    if (ticket !== state.ticket) return; // a later navigation won
    if (tab !== "map") state.map?.unmount();
    view.replaceChildren(content);
    if (!state.refresh) state.refresh = () => route({ keepScroll: true });
    window.scrollTo(0, keepScroll ? scroll : 0);
    if (!keepScroll && tab !== "search") view.focus({ preventScroll: true });
    return;
  }
  location.hash = "#/";
}

function listen() {
  state.events?.close();
  const events = new EventSource(`/api/events?c=${encodeURIComponent(state.collection)}`);
  events.addEventListener("change", async () => {
    if (state.refresh) {
      await state.refresh();
      toast("Updated");
    }
  });
  state.events = events;
}

async function start() {
  const { collections, default: fallback, catalog } = await fetch("/api/collections").then((r) => r.json());
  document.querySelector('[data-tab="catalog"]').hidden = !catalog;
  const saved = remember("cairn-studio:collection");
  state.collection = collections.includes(saved) ? saved : fallback;
  picker.replaceChildren(...collections.map((c) => h("option", { value: c, selected: c === state.collection }, c)));
  picker.closest("label").hidden = collections.length < 2;
  picker.addEventListener("change", () => {
    state.collection = picker.value;
    remember("cairn-studio:collection", picker.value);
    listen();
    route();
  });
  window.addEventListener("hashchange", () => route());
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) {
      event.preventDefault();
      location.hash = "#/search";
    }
  });
  listen();
  route();
}

start();
