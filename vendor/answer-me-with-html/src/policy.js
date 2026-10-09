// Invocation policy is supplied by the caller, never by a draft or an existing page.
import { parse, parseFragment } from 'parse5';
import parseCss from 'css-tree/parser';
import walkCss from 'css-tree/walker';
import { esc } from './svg/text.js';

export class PolicyError extends Error {
  constructor(message) { super(message); this.name = 'PolicyError'; }
}

export function elements(node, visit) {
  if (node.tagName) visit(node);
  for (const child of node.childNodes ?? []) elements(child, visit);
  if (node.content) elements(node.content, visit);
}

export function normalizedUrl(value) {
  // HTML entities and URI escapes can hide a scheme; inspect a conservative decoded form.
  const fragment = parseFragment(`<a href="${String(value).replace(/"/g, '&quot;').replace(/</g, '&lt;')}"></a>`);
  let text = fragment.childNodes[0]?.attrs?.find((a) => a.name === 'href')?.value ?? String(value);
  for (let i = 0; i < 4; i++) {
    try { const decoded = decodeURIComponent(text); if (decoded === text) break; text = decoded; } catch { break; }
  }
  return text.replace(/[\u0000-\u0020\u007f-\u009f]/g, '').replace(/\\/g, '/');
}

export function checkUrl(value, { resource = false, allowNetworkAssets = false, allowLocal = false, image = false } = {}) {
  const url = normalizedUrl(value);
  const scheme = /^([a-z][a-z\d+.-]*):/i.exec(url)?.[1].toLowerCase();
  // A Windows drive is a local path, not an arbitrary URI handler.
  const drive = /^[a-z]:\//i.test(url);
  if (scheme && !drive && !['http', 'https', 'mailto', 'file', 'data', 'blob'].includes(scheme)) {
    throw new PolicyError(`Unsafe URL scheme: ${scheme}`);
  }
  if (!resource) {
    if (scheme === 'data' || scheme === 'blob') throw new PolicyError('Data and blob navigation links are not allowed');
    return;
  }
  if (/^https?:/i.test(url) || url.startsWith('//')) {
    if (!allowNetworkAssets) throw new PolicyError('External assets require --allow-network-assets');
    return;
  }
  if (url.startsWith('#')) return;
  if (scheme === 'data') {
    const permitted = image ? /^data:image\/(png|jpeg|gif|webp|avif|svg\+xml)[;,]/i : /^data:(image\/(png|jpeg|gif|webp|avif|svg\+xml)|audio\/[\w.+-]+|video\/[\w.+-]+|font\/[\w.+-]+|application\/font-[\w.+-]+)[;,]/i;
    if (!permitted.test(url)) throw new PolicyError('Unsupported data resource type');
    return;
  }
  if (scheme === 'blob' && !image) return;
  if (allowLocal && (!scheme || drive || scheme === 'file')) return;
  throw new PolicyError('Resources must be embedded; local references and unsupported resource schemes are not allowed');
}

const decodeCss = (s) => String(s).replace(/\\([0-9a-f]{1,6})\s?|\\([^\r\n])/gi, (_, hex, char) => hex ? String.fromCodePoint(Math.min(parseInt(hex, 16), 0x10ffff) || 0xfffd) : char);

function checkCss(source, policy, context = 'stylesheet') {
  let ast;
  try { ast = parseCss(source, { context, parseCustomProperty: true }); }
  catch { throw new PolicyError('Cannot validate malformed CSS'); }
  walkCss(ast, (node) => {
    if (node.type === 'Url') checkUrl(decodeCss(node.value), { ...policy, resource: true });
    // A selector or content string is quoted text, not a URL. These image
    // functions are the CSS positions where a bare string is a resource.
    if (node.type === 'Function' && ['image', 'image-set', '-webkit-image-set', 'src'].includes(decodeCss(node.name).toLowerCase())) {
      node.children.forEach((child) => {
        if (child.type === 'String') checkUrl(decodeCss(child.value), { ...policy, resource: true });
        if (child.type === 'Function' && decodeCss(child.name).toLowerCase() === 'var') throw new PolicyError('Cannot validate a dynamic CSS image resource; use an explicit embedded URL');
      });
    }
    if (node.type === 'Atrule' && decodeCss(node.name).toLowerCase() === 'import') {
      if (!policy.allowNetworkAssets) throw new PolicyError('CSS imports require --allow-network-assets');
      // Strings in @import are URLs too, including relative paths.
      node.prelude?.children?.forEach((child) => {
        if (child.type === 'String') checkUrl(decodeCss(child.value), { ...policy, resource: true });
      });
    }
    if (node.type === 'Raw' && /url|image|import|\\|expression|binding|behavior/i.test(node.value)) throw new PolicyError('Cannot validate an opaque CSS resource expression');
  });
}

// Validate browser-parsed attributes, not regular-expression approximations of HTML.
// Navigation links are distinct from resources that load automatically.
export function secureDocument(html, policy = {}) {
  const doc = parse(html);
  elements(doc, (node) => {
    const attrs = Object.fromEntries(node.attrs.map((a) => [a.prefix ? `${a.prefix}:${a.name}` : a.name, a.value]));
    const tag = node.tagName.toLowerCase();
    if (['base', 'iframe', 'frame', 'object', 'embed', 'set', 'animate'].includes(tag)) throw new PolicyError(`Embedded ${tag} documents are not supported`);
    if (tag === 'meta' && /^(refresh|content-security-policy)$/i.test(attrs['http-equiv'] ?? '')) throw new PolicyError('Drafts cannot set redirects or content security policy');
    for (const [name, value] of Object.entries(attrs)) {
      if (/^on/i.test(name) && !policy.allowRawHtml) throw new PolicyError('Event handlers require --allow-raw-html');
      if (['srcdoc', 'ping', 'action', 'formaction', 'manifest', 'codebase', 'archive'].includes(name)) throw new PolicyError(`Automatic action attribute ${name} is not supported`);
      if (name === 'style') checkCss(value, policy, 'declarationList');
      if (name === 'srcset' || name === 'imagesrcset') throw new PolicyError('Use a single embedded image instead of srcset');
      if (['href', 'xlink:href', 'src', 'poster', 'background', 'cite', 'data'].includes(name)) {
        // data on arbitrary elements is not an asset; object is rejected above.
        if (name === 'data') continue;
        checkUrl(value, { ...policy, resource: !(name === 'cite' || tag === 'a' && /href$/.test(name)), image: tag === 'img' });
      }
    }
    if (tag === 'style') checkCss(node.childNodes.map((n) => n.value ?? '').join(''), policy);
  });
  const network = policy.allowNetworkAssets ? ' https: http:' : '';
  const csp = `default-src 'none'; script-src 'unsafe-inline'${network}; style-src 'unsafe-inline'${network}; img-src data: blob:${network}; font-src data:${network}; media-src data: blob:${network}; connect-src ${network.trim() || "'none'"}; worker-src blob:; object-src 'none'; base-uri 'none'; form-action 'none'`;
  return html.replace(/<head>/i, `<head>\n<meta http-equiv="Content-Security-Policy" content="${esc(csp)}">`);
}
