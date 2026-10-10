// Generated application profile. MIT; see THIRD_PARTY_LICENSES. Do not edit.

// src/application.js
import { createHash } from "node:crypto";

// src/svg/text.js
var CJK_RE = /[⺀-鿿가-힯豈-﫿︰-﹏＀-￯　-〿]/;
var NARROW = /* @__PURE__ */ new Set([..."iljtfrI.,:;|!'`()[]{}"]);
var WIDE = /* @__PURE__ */ new Set([..."mwMWOQGD@%&"]);
var HANGUL_SYLLABLE = /[가-힯]/;
var HAN_KANA = new RegExp(CJK_RE.source.replace(HANGUL_SYLLABLE.source.slice(1, -1), ""));
var UNSPACED = [
  ["th", new RegExp("\\p{Script=Thai}", "u")],
  ["lo", new RegExp("\\p{Script=Lao}", "u")],
  ["km", new RegExp("\\p{Script=Khmer}", "u")],
  ["my", new RegExp("\\p{Script=Myanmar}", "u")]
];
var ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function esc(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
}

// src/application.js
var sha = (s) => createHash("sha256").update(s).digest("hex");
var id = (s) => /^[a-z][a-z0-9_]{2,95}$/.test(s);
function text(s, limit = 2e5) {
  if (typeof s !== "string" || s.length > limit) throw Error("Invalid application text");
  return esc(s);
}
function url(s) {
  const u = new URL(s);
  if (!["https:", "http:"].includes(u.protocol) || u.username || u.password) throw Error("Invalid citation URL");
  return esc(u.href);
}
function runtime() {
  const filter = document.querySelector("#filter");
  filter.addEventListener("input", () => {
    const q = filter.value.toLocaleLowerCase();
    document.querySelectorAll("article").forEach((e) => {
      e.hidden = !e.textContent.toLocaleLowerCase().includes(q);
    });
  });
  document.querySelector("#theme").addEventListener("click", () => {
    const dark = getComputedStyle(document.documentElement).colorScheme === "dark";
    document.documentElement.dataset.mode = dark ? "light" : "dark";
  });
  document.querySelectorAll(".diagram button").forEach((b) => b.addEventListener("click", () => {
    const expanded = b.getAttribute("aria-expanded") !== "true";
    b.setAttribute("aria-expanded", String(expanded));
    b.closest("figure").classList.toggle("expanded", expanded);
  }));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") document.querySelectorAll(".diagram.expanded button").forEach((b) => b.click());
  });
  const form = document.querySelector("#feedback");
  if (form) form.addEventListener("submit", (e) => {
    e.preventDefault();
    const comment = form.elements.comment.value.trim();
    if (!comment) return;
    const data = {
      schema_version: 1,
      bundle_id: form.dataset.bundle,
      bundle_hash: form.dataset.hash,
      entries: [{ target_id: form.elements.target.value, comment, suggested_text: form.elements.suggestion.value || null }]
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = "cairn-feedback.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(href), 1e3);
    document.querySelector("#feedback-status").textContent = "Feedback exported for owner import; no knowledge was changed.";
  });
}
var SCRIPT = `(${runtime.toString()})()`;
var CSS = `
:root{color-scheme:light dark;--bg:#f9f8f4;--fg:#202d36;--muted:#52626d;--line:#c3cdd0;--card:#fff;--accent:#145768}
@media(prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#141d24;--fg:#e7edef;--muted:#b3c4cd;--line:#53616b;--card:#1d2a33;--accent:#9edeea}}
:root[data-mode=dark]{color-scheme:dark;--bg:#141d24;--fg:#e7edef;--muted:#b3c4cd;--line:#53616b;--card:#1d2a33;--accent:#9edeea}
:root[data-mode=light]{color-scheme:light;--bg:#f9f8f4;--fg:#202d36;--muted:#52626d;--line:#c3cdd0;--card:#fff;--accent:#145768}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.6 system-ui,sans-serif}main,header,footer{max-width:1080px;margin:auto;padding:1.5rem}h1{font-size:clamp(1.7rem,5vw,2.7rem);line-height:1.2}h2{margin-top:2rem}h3{margin:.2rem 0}a{color:var(--accent);text-underline-offset:.2em}p,li,summary,pre{overflow-wrap:anywhere}article,details{padding:1.1rem;margin:1rem 0;border:1px solid var(--line);border-radius:.5rem;background:var(--card)}.labels,.subtle{color:var(--muted);font-size:.9rem}.labels span{display:inline-block;border:1px solid var(--line);border-radius:.3rem;padding:.1rem .4rem;margin:.2rem .4rem .2rem 0}blockquote{border-left:3px solid var(--accent);margin:1rem 0;padding-left:1rem;white-space:pre-wrap}pre{white-space:pre-wrap;max-width:100%;font:14px/1.5 ui-monospace,monospace}summary{cursor:pointer;font-weight:600}button,input,textarea,select{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:.3rem;padding:.5rem;max-width:100%}button{cursor:pointer}label{display:block;margin:.7rem 0}textarea{display:block;width:100%;min-height:6rem}:focus-visible{outline:3px solid var(--accent);outline-offset:3px}.toolbar{display:flex;gap:1rem;flex-wrap:wrap}.diagram{margin:1rem 0;overflow:auto}.diagram ol{display:flex;flex-wrap:wrap;align-items:center;gap:1.5rem;padding:1rem 2rem}.diagram li{border:1px solid var(--line);padding:1rem;min-width:8rem}.diagram.expanded{position:fixed;inset:1rem;z-index:2;padding:2rem;background:var(--card);border:2px solid var(--accent)}img{max-width:100%;height:auto}.citations{display:flex;gap:1rem;flex-wrap:wrap}[hidden]{display:none!important}
@media(max-width:480px){main,header,footer{padding:1rem}article,details{padding:.8rem}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
@media print{.toolbar,#feedback,.diagram button{display:none}body{background:white;color:black;font-size:11pt}article,details{break-inside:avoid;background:white}details>*{display:block}details::details-content{content-visibility:visible}main,header,footer{max-width:none;padding:.3rem}.diagram.expanded{position:static}.diagram ol{flex-wrap:wrap}a{color:black}.labels,.subtle{color:#333}}
`;
function renderApplication(doc, { interactions = true, embedSource = false, source = "" } = {}) {
  if (!doc || doc.version !== 1 || !id(doc.bundle_id) || !/^[a-f0-9]{64}$/.test(doc.bundle_hash)) throw Error("Invalid application document");
  if (JSON.stringify(doc).length > 16e6) throw Error("Application document too large");
  const refs = new Set(doc.evidence.map((e) => e.key));
  if (refs.size !== doc.evidence.length || [...refs].some((k) => !id(k))) throw Error("Invalid evidence identifiers");
  const assets = /* @__PURE__ */ new Map();
  for (const a of doc.assets || []) {
    if (!id(a.id) || !["image/png", "image/jpeg", "image/webp"].includes(a.mime) || assets.has(a.id)) throw Error("Invalid asset");
    const bytes = Buffer.from(a.data, "base64");
    if (bytes.length > 5e6 || bytes.toString("base64") !== a.data || sha(bytes) !== a.sha256) throw Error("Asset checksum mismatch");
    const valid = a.mime === "image/png" ? bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) : a.mime === "image/jpeg" ? bytes.subarray(0, 3).equals(Buffer.from([255, 216, 255])) : bytes.subarray(0, 4).toString() === "RIFF" && bytes.subarray(8, 12).toString() === "WEBP";
    if (!valid) throw Error("Asset signature mismatch");
    assets.set(a.id, `data:${a.mime};base64,${a.data}`);
  }
  const blocks = doc.sections.map((s) => `<section><h2>${text(s.title)}</h2>${s.blocks.map((b) => {
    if (!["text", "quote", "code", "diagram"].includes(b.kind)) throw Error("Unknown application block");
    const citations = b.citations.map((k) => {
      if (!refs.has(k)) throw Error("Unknown citation");
      return `<a href="#${k}">Evidence ${[...refs].indexOf(k) + 1}</a>`;
    }).join("");
    if (b.asset_id && !assets.has(b.asset_id)) throw Error("Unknown asset");
    const asset = b.asset_id ? `<img alt="${text(b.title)}" src="${assets.get(b.asset_id)}">` : "";
    const body = b.kind === "code" ? `<pre><code>${text(b.text)}</code></pre>` : b.kind === "quote" ? `<blockquote>${text(b.text)}</blockquote>` : `<p style="white-space:pre-wrap">${text(b.text)}</p>`;
    const diagram = b.kind === "diagram" ? `<figure class="diagram">${interactions ? '<button type="button" aria-expanded="false">Expand diagram</button>' : ""}<ol>${b.nodes.map((n) => `<li>${text(n)}</li>`).join("")}</ol><figcaption>${text(b.title)}</figcaption></figure>` : "";
    return `<article><h3>${text(b.title)}</h3><div class="labels">${b.labels.map((l) => `<span>${text(l)}</span>`).join("")}</div>${body}${asset}${diagram}<div class="citations">${citations}${b.url ? `<a rel="noreferrer noopener" href="${url(b.url)}">Publication</a>` : ""}</div></article>`;
  }).join("")}</section>`).join("");
  const evidence = doc.evidence.map((e) => `<details id="${e.key}"><summary>${text(e.title)} \u2014 ${text(e.reference.locator)}</summary><p class="subtle">${text(e.reference.id)} \xB7 Date: ${text(e.source_date || "unknown")} \xB7 Version: ${text(e.version || "unknown")} \xB7 Coverage: ${text(e.coverage)}</p><p>Tables inspected: ${!!e.tables_inspected}; images inspected: ${!!e.images_inspected}</p><blockquote>${text(e.text)}</blockquote><p>${text(e.support)}</p><pre>Source SHA256: ${text(e.reference.source_hash)}
Evidence SHA256: ${text(e.reference.evidence_hash)}</pre></details>`).join("");
  if (doc.targets.some((k) => !id(k))) throw Error("Invalid feedback target");
  const feedback = interactions && doc.feedback && doc.targets.length ? `<form id="feedback" data-bundle="${doc.bundle_id}" data-hash="${doc.bundle_hash}"><h2>Feedback for owner review</h2><p>This exports a file. It does not approve or apply changes.</p><label>Record <select name="target">${doc.targets.map((k) => `<option>${k}</option>`).join("")}</select></label><label>Comment<textarea name="comment" required maxlength="10000"></textarea></label><label>Suggested text (optional)<textarea name="suggestion" maxlength="20000"></textarea></label><button>Export feedback</button><p id="feedback-status" role="status"></p></form>` : "";
  const scriptHash = createHash("sha256").update(SCRIPT).digest("base64");
  const csp = `default-src 'none'; script-src ${interactions ? `'sha256-${scriptHash}'` : "'none'"}; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'`;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><meta name="referrer" content="no-referrer"><title>${text(doc.title)}</title><style>${CSS}</style></head><body><header><p class="subtle">Cairn \xB7 Knowledge snapshot</p><h1>${text(doc.title)}</h1><p>${text(doc.subtitle)}</p>${interactions ? '<div class="toolbar"><label>Filter this view <input id="filter" type="search"></label><button id="theme" type="button">Change theme</button></div>' : ""}</header><main>${blocks}<section><h2>Evidence</h2>${evidence || "<p>No supporting excerpts in this bundle.</p>"}</section>${feedback}</main><footer><p>This snapshot cannot enforce later access revocation. Quote matches establish presence, not truth or entailment.</p><p>${doc.bundle_id} \xB7 ${doc.bundle_hash}</p></footer>${embedSource ? `<textarea hidden readonly>${text(source)}</textarea>` : ""}${interactions ? `<script>${SCRIPT}</script>` : ""}</body></html>`;
}

// bin/application.js
var chunks = [];
var size = 0;
try {
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 32 * 1024 * 1024) throw Error("Input budget exceeded");
    chunks.push(chunk);
  }
  const document2 = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  process.stdout.write(renderApplication(document2));
} catch {
  process.stderr.write("Application renderer rejected input\n");
  process.exitCode = 2;
}
