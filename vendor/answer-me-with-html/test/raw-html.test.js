import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseFragment } from 'parse5';
import { md, mdInline, collectHtmlNotes } from '../src/markdown.js';
import { elements } from '../src/policy.js';
import { renderDoc } from '../src/render.js';
import { renderVideo } from '../src/video/render.js';

// Ordinary quoted source never becomes executable markup, even when apparently benign.
const quotes = [
  '<b>x</b>', '<kbd>Ctrl</kbd>', '<div class="a">\n<script>x()</script>\n</div>',
  '<span onclick="x()">s</span>', '<a href="JaVaScRiPt:x()">x</a>',
  '<img src="https://example.org/a.png" onerror="x()">', '<pre>code <b>x</b></pre>',
  '<style>p{background:url(https://example.org/a)}</style>', '<textarea>\nx',
  '<details>\n<summary>more</summary>\n\ntext\n</details>',
  '<picture><source srcset="a.webp"><img src="a.png"></picture>',
  '<div title="a>b" class="x\n', 'Array<string> and <host>', '<svg onload=x()>hi</svg>',
  '<iframe srcdoc="<script>x()</script>"></iframe>', '<?php echo 1 ?>', '<![CDATA[x]]>',
];
for (const quote of quotes) test(`source HTML stays inert: ${quote.slice(0, 60)}`, () => {
  for (const source of [quote, `See ${quote}`, `- ${quote}`, `> ${quote}`, `| a |\n|---|\n| ${quote.replaceAll('\n', ' ')} |`]) {
    const found = [];
    elements(parseFragment(md(source)), (el) => {
      if (['script', 'style', 'iframe', 'img', 'svg', 'b', 'span', 'kbd', 'textarea', 'details', 'source'].includes(el.tagName)) found.push(el.tagName);
      assert.ok(!el.attrs.some((a) => /^on/i.test(a.name)), source);
    });
    assert.deepEqual(found, [], source);
  }
});

test('source placeholders, unclosed comments, and script lines do not swallow following Markdown', () => {
  for (const raw of ['<script> x', '<style> x', '<textarea>x', '<!-- unfinished', '<host>']) {
    assert.match(md(`${raw}\n\n## Next\n**kept**`), /<h2>Next<\/h2>/);
    assert.match(md(`${raw}\n\n## Next\n**kept**`), /<strong>kept<\/strong>/);
  }
});

test('Markdown formatting, code, and autolinks still work', () => {
  assert.match(md('**bold** _em_ `<script>` <https://example.org>'), /<strong>bold<\/strong>/);
  assert.match(md('`<script>`'), /<code>&lt;script&gt;<\/code>/);
  assert.match(md('<https://example.org>'), /href="https:\/\/example.org"/);
  assert.equal(mdInline('<b>quoted</b>'), '&lt;b&gt;quoted&lt;/b&gt;');
  assert.match(md('```text\n<script>x()</script>\n```'), /&lt;script&gt;x\(\)&lt;\/script&gt;/);
});

test('components escape source HTML in their labels and prose', () => {
  const source = '## A\n```kv\nKey: <b>value</b>\n```\n```tree\nRoot\n  <kbd>child</kbd>\n```\n```callout warn\n<script>x()</script>\n```';
  const { html } = renderDoc(source);
  assert.match(html, /&lt;b&gt;value&lt;\/b&gt;/);
  assert.match(html, /&lt;kbd&gt;child&lt;\/kbd&gt;/);
  assert.ok(!html.includes('<script>x()</script>'));
});

test('source notes have draft line numbers and collectors do not leak', async () => {
  const { stats } = renderDoc('## A\nConnect to <host>.\n');
  assert.equal(stats.htmlWarnings[0].line, 2);
  const outer = collectHtmlNotes(() => { md('a <host>'); collectHtmlNotes(() => md('b <pid>')); md('c <dir>'); });
  assert.deepEqual(outer.notes.map((n) => n.at), ['<host>', '<dir>']);
  assert.throws(() => collectHtmlNotes(() => { throw new Error('x'); }), /x/);
  assert.deepEqual(collectHtmlNotes(() => md('**normal**')).notes, []);
  const video = await renderVideo('## A\nConnect to <host>.\n> Narration.');
  assert.equal(video.stats.htmlWarnings.length, 1);
});
