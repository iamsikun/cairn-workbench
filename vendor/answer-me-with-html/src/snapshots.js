import { parse, serialize } from 'parse5';
import { readEmbeddedCode } from './code.js';
import { readEmbeddedImages } from './images.js';
import { parseDoc } from './parse.js';
import { findPanel } from './patch.js';

// Old pages already carry per-panel containers and embedded assets. No new authority
// fields are read from them. Missing snapshots are errors when an include is rendered.
export function patchSnapshots(html, source, query, { refresh = false } = {}) {
  if (refresh) return undefined;
  const draft = parseDoc(source, { choices: { theme: undefined } });
  const target = draft.panels.indexOf(findPanel(draft, query));
  const hasClass = (node, name) => (node?.attrs?.find((a) => a.name === 'class')?.value ?? '').split(/\s+/).includes(name);
  const child = (node, name) => node?.childNodes?.find((n) => hasClass(n, name));
  const document = parse(html);
  const body = document.childNodes.find((n) => n.tagName === 'html')?.childNodes.find((n) => n.tagName === 'body');
  // Follow the renderer's envelope, not matching class names inside custom markup.
  const main = body?.childNodes.find((n) => n.tagName === 'main' && (hasClass(n, 'am-sheet') || hasClass(n, 'am-doc')));
  const camera = child(child(child(body, 'amv-viewport'), 'amv-stage'), 'amv-camera');
  const container = main ? child(child(main, 'am-frame'), 'am-grid') ?? child(child(main, 'am-doc-layout'), 'am-doc-body') : camera;
  const panels = container?.childNodes?.filter((n) => hasClass(n, main ? 'am-panel' : 'amv-scene') && !hasClass(n, 'amv-scene--title')) ?? [];
  const introNode = main ? child(child(main, 'am-head'), 'am-intro') : child(child(child(camera, 'amv-scene--title'), 'amv-title-wrap'), 'amv-intro');
  const intro = introNode ? serialize(introNode) : '';
  const found = panels.map((node) => serialize(node));
  const snapshot = (fragment = '') => ({ code: readEmbeddedCode(fragment), images: readEmbeddedImages(fragment) });
  return { intro: snapshot(intro), panels: draft.panels.map((_, i) => i === target ? undefined : snapshot(found[i])) };
}

export function scopedContext(ctx, snapshot) {
  if (!snapshot) return ctx;
  // Keep the shared diagram ID counter while changing the include lookup for this section.
  const local = Object.create(ctx);
  Object.defineProperty(local, 'seq', { get: () => ctx.seq, set: (value) => { ctx.seq = value; } });
  local.code = { ...ctx.code, known: snapshot.code, snapshotOnly: true };
  local.images = { ...ctx.images, known: snapshot.images, snapshotOnly: true };
  return local;
}
