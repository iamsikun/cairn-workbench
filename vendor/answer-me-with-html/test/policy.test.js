import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, symlinkSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { Readable, Writable } from 'node:stream';
import { renderDoc } from '../src/render.js';
import { renderVideo } from '../src/video/render.js';
import { readEmbeddedCode } from '../src/code.js';
import { readEmbeddedImages } from '../src/images.js';
import { main } from '../src/cli.js';
import { atomicWrite } from '../src/atomic-write.js';
import { pickProvider } from '../src/video/tts.js';

const raw = (text) => `## A\n\`\`\`html\n${text}\n\`\`\``;
const allowed = { allowRawHtml: true, allowNetworkAssets: true };
const render = (source, policy = {}) => renderDoc(source, {}, {}, { policy });
const fixture = (t) => { const dir = mkdtempSync(join(tmpdir(), 'portable-')); t.after(() => rmSync(dir, { recursive: true, force: true })); return dir; };
async function cli(dir, args, source = '') {
  let out = '', err = '';
  const stream = (cb) => new Writable({ write(c, _, done) { cb(String(c)); done(); } });
  const code = await main(args, { cwd: dir, env: { AM_HOME: join(dir, 'state'), AM_NO_OPEN: '1', AM_NO_UPDATE_CHECK: '1' }, stdin: Readable.from([source]), stdout: stream((s) => out += s), stderr: stream((s) => err += s) });
  return { code, out, err };
}
const include = (ref) => `\`\`\`js src="${ref}"\n\`\`\``;
const image = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="red"/></svg>');

test('code containment uses resolved roots and rejects traversal, symlink escapes and sensitive aliases', (t) => {
  const dir = fixture(t), root = join(dir, 'work'); mkdirSync(root);
  writeFileSync(join(dir, 'outside.js'), 'outside'); writeFileSync(join(root, 'good.js'), 'safe');
  writeFileSync(join(root, '.env'), 'SYNTHETIC_SETTING=sample'); mkdirSync(join(root, '.ssh')); writeFileSync(join(root, '.ssh', 'config'), 'synthetic');
  symlinkSync(join(dir, 'outside.js'), join(root, 'file.js'));
  symlinkSync(dir, join(root, 'directory'));
  symlinkSync('.env', join(root, 'alias.js')); symlinkSync('.ssh', join(root, 'keys'));
  symlinkSync(root, join(dir, 'root-link'));
  for (const ref of ['../outside.js', 'file.js', 'directory/outside.js', '.env', 'alias.js', 'keys/config']) {
    assert.throws(() => renderDoc(`## A\n${include(ref)}`, {}, {}, { codeDir: root }), /outside|password|keys/, ref);
  }
  assert.match(renderDoc(`## A\n${include('good.js')}`, {}, {}, { codeDir: join(dir, 'root-link') }).html, />safe<\/span>/);
  assert.match(renderDoc(`## A\n${include(join(root, 'good.js'))}`, {}, {}, { codeDir: join(dir, 'root-link') }).html, />safe<\/span>/);
  writeFileSync(join(dir, 'explicit.svg'), image);
  assert.match(renderDoc(`## A\n![explicit](${join(dir, 'explicit.svg')})`, {}, {}, { codeDir: root }).html, /src="data:image\/svg/);
});

for (const url of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'java&#x09;script:alert(1)', '&#106;avascript:alert(1)', 'javascript%3Aalert(1)', 'java%73cript:alert(1)', 'vbscript:x', 'DATA:text/html,hi', 'ftp://example.org/x']) {
  test(`unsafe URL is rejected in all modes: ${url}`, () => {
    for (const policy of [{}, allowed]) {
      assert.throws(() => render(`## A\n[link](<${url}>)`, policy), /scheme|navigation/);
      assert.throws(() => render(`## A\n![image](<${url}>)`, policy), /scheme|resource/);
    }
    assert.throws(() => render(raw(`<a href="${url}">link</a>`), allowed), /scheme|navigation/);
  });
}

test('remote images need an invocation flag, citations do not', () => {
  for (const url of ['https://example.org/a.png', 'HtTpS://example.org/a.png', '//example.org/a.png', 'https%3A%2F%2Fexample.org/a.png']) {
    assert.throws(() => render(`## A\n![picture](${url})`), /network-assets/);
  }
  assert.match(render('## A\n[Source](https://example.org/report)').html, /href="https:\/\/example.org\/report"/);
  assert.match(render('## A\n![picture](https://example.org/a.png)', { allowNetworkAssets: true }).html, /src="https:\/\/example.org\/a.png"/);
  assert.match(render('## A\nanswer').html, /Content-Security-Policy/);
});

test('raw fences need a separate flag; static, CSS and SVG dependencies follow network policy', () => {
  const local = '<svg><circle r="5"/></svg><script>window.example = 1</script>';
  assert.throws(() => render(raw(local)), /allow-raw-html/);
  assert.throws(() => render(raw(local), { allowNetworkAssets: true }), /allow-raw-html/);
  assert.match(render(raw(local), { allowRawHtml: true }).html, /window.example = 1/);
  for (const asset of ['<img src=https://example.org/a.png>', "<img src='https://example.org/a.png'>", '<script src="https://example.org/a.js"></script>', '<link rel="stylesheet" href="https://example.org/a.css">', '<style>div { background:url(https://example.org/a.png) }</style>', '<style>@import "https://example.org/a.css";</style>', '<svg><image href="https://example.org/a.svg"/></svg>']) {
    assert.throws(() => render(raw(asset), { allowRawHtml: true }), /network-assets/);
    assert.doesNotThrow(() => render(raw(asset), allowed));
  }
  assert.throws(() => render(raw('<style>div{background:u\\72l(javascript:x)}</style>'), allowed), /scheme|opaque/);
  assert.doesNotThrow(() => render(raw('<style>.am-grid[style*="display: flex"] {max-width:900px} p::after {content:"quoted: text"}</style>'), { allowRawHtml: true }));
  assert.throws(() => render(raw('<style>p {background:image-set("https://example.org/a.png" 1x)}</style>'), { allowRawHtml: true }), /network-assets/);
});

test('drafts and saved page metadata cannot grant either exception', async (t) => {
  const dir = fixture(t);
  assert.equal((await cli(dir, ['render','-','-o','one.html'], `---\nallow-raw-html: true\nallow-network-assets: true\n---\n${raw('<script>1</script>')}`)).code, 1);
  const draft = raw('<img src="https://example.org/a.png">') + '\n## B\nkeep';
  assert.equal((await cli(dir, ['render','-','-o','one.html','--allow-raw-html','--allow-network-assets'], draft)).code, 0);
  const before = readFileSync(join(dir, 'one.html'),'utf8');
  for (const flags of [[], ['--allow-raw-html'], ['--allow-network-assets']]) {
    assert.equal((await cli(dir, ['patch','one.html','--panel','B',...flags], 'new')).code, 1);
    assert.equal(readFileSync(join(dir, 'one.html'),'utf8'), before);
  }
});

test('patch preserves unchanged per-panel and intro snapshots, replacement alone re-reads; refresh is deliberate', async (t) => {
  const dir = fixture(t); writeFileSync(join(dir,'code.js'),'old'); writeFileSync(join(dir,'pic.svg'),image);
  const source = `${include('code.js')}\n\n## A\n${include('code.js')}\n![plot](pic.svg)\n## B\n${include('code.js')}\n![plot](pic.svg)`;
  assert.equal((await cli(dir,['render','-','-o','answer.html'],source)).code,0);
  writeFileSync(join(dir,'code.js'),'new'); writeFileSync(join(dir,'pic.svg'), Buffer.from(image.toString().replace('red','blue')));
  const replacement = `${include('code.js')}\n![plot](pic.svg)`;
  assert.equal((await cli(dir,['patch','answer.html','--panel','B'],replacement)).code,0);
  let html = readFileSync(join(dir,'answer.html'),'utf8');
  assert.equal((html.match(/>old<\/span>/g)||[]).length,2);
  assert.equal((html.match(/>new<\/span>/g)||[]).length,1);
  assert.ok(html.includes(image.toString('base64')));
  assert.equal((await cli(dir,['patch','answer.html','--panel','B','--refresh-sources'],replacement)).code,0);
  html=readFileSync(join(dir,'answer.html'),'utf8'); assert.ok(!html.includes('>old</span>')); assert.equal((html.match(/>new<\/span>/g)||[]).length,3);
});

test('legacy pages recover snapshots; missing snapshots fail without changing the page', async (t) => {
  const dir=fixture(t); writeFileSync(join(dir,'code.js'),'old');
  await cli(dir,['render','-','-o','answer.html'],`## A\n${include('code.js')}\n## B\ntext`);
  const file=join(dir,'answer.html'); let legacy=readFileSync(file,'utf8').replace(/<meta http-equiv="Content-Security-Policy"[^>]*>/,'');
  writeFileSync(file,legacy); rmSync(join(dir,'code.js'));
  assert.equal((await cli(dir,['patch','answer.html','--panel','B'],'changed')).code,0);
  const broken=readFileSync(file,'utf8').replace('data-am-src="code.js"','data-lost-src="code.js"'); writeFileSync(file,broken);
  const missing=await cli(dir,['patch','answer.html','--panel','B'],'again'); assert.equal(missing.code,1); assert.match(missing.err,/refresh-sources/); assert.equal(readFileSync(file,'utf8'),broken);
  writeFileSync(join(dir,'code.js'),'refreshed'); assert.equal((await cli(dir,['patch','answer.html','--panel','B','--refresh-sources'],'again')).code,0);
});

test('selection failures and retries preserve one chosen deliverable', async (t) => {
  const dir=fixture(t); const args=['render','-','-o','answer.html','--no-open'];
  await cli(dir,args,'## A Same\na\n## B Same\nb'); const file=join(dir,'answer.html'), before=readFileSync(file,'utf8');
  for (const selection of [[], ['--panel','absent'], ['--panel','Same']]) {
    assert.notEqual((await cli(dir,['patch','answer.html',...selection],'changed')).code,0); assert.equal(readFileSync(file,'utf8'),before);
  }
  assert.equal((await cli(dir,args,raw('<script>1</script>'))).code,1); assert.equal(readFileSync(file,'utf8'),before);
  assert.equal((await cli(dir,args,'## A Fixed\ncomplete')).code,0);
  assert.deepEqual(readdirSync(dir).filter((name)=>name.endsWith('.html')),['answer.html']);
});

test('failed atomic replacement preserves bytes, removes temp files, rejects symlink outputs', (t) => {
  const dir=fixture(t), file=join(dir,'answer.html'); writeFileSync(file,'original');
  assert.throws(()=>atomicWrite(file,'replacement',{rename(){throw new Error('simulated rename failure');}}),/simulated/);
  assert.equal(readFileSync(file,'utf8'),'original'); assert.deepEqual(readdirSync(dir),['answer.html']);
  symlinkSync(file,join(dir,'link.html')); assert.throws(()=>atomicWrite(join(dir,'link.html'),'oops'),/symlink/); assert.equal(readFileSync(file,'utf8'),'original');
});

test('automatic narration ignores cloud credentials; invalid markup is rejected before provider calls', async () => {
  assert.equal(pickProvider('auto',{ELEVENLABS_API_KEY:'synthetic',AM_TTS_URL:'https://example.org'},{platform:'linux',which:()=>false}),null);
  let calls=0;
  await assert.rejects(()=>renderVideo(raw('<script>1</script>')+'\n> hello',{provider:{name:'synthetic',id:'synthetic',concurrency:1,synth:async()=>{calls++; return new Int16Array(100);}}}),/allow-raw-html/);
  assert.equal(calls,0);
});


test('missing unchanged image snapshots fail instead of rereading existing files', async (t) => {
  const dir=fixture(t); writeFileSync(join(dir,'pic.svg'),image);
  await cli(dir,['render','-','-o','answer.html'],'## A\n![plot](pic.svg)\n## B\ntext');
  const file=join(dir,'answer.html');
  const broken=readFileSync(file,'utf8').replace('data-am-src="pic.svg"','data-lost-src="pic.svg"'); writeFileSync(file,broken);
  const result=await cli(dir,['patch','answer.html','--panel','B'],'changed');
  assert.equal(result.code,1); assert.match(result.err,/Missing embedded snapshot.*refresh-sources/);
  assert.equal(readFileSync(file,'utf8'),broken);
  assert.equal((await cli(dir,['patch','answer.html','--panel','B','--refresh-sources'],'changed')).code,0);
});


test('custom markup with renderer-like classes cannot shift unchanged panel snapshots', async (t) => {
  const dir=fixture(t); writeFileSync(join(dir,'code.js'),'original');
  const source=raw('<div class="am-grid"><section class="am-panel">quoted layout example</section></div>')+`\n## B\n${include('code.js')}\n## C\ntext`;
  assert.equal((await cli(dir,['render','-','-o','answer.html','--allow-raw-html'],source)).code,0);
  writeFileSync(join(dir,'code.js'),'modified');
  assert.equal((await cli(dir,['patch','answer.html','--panel','C','--allow-raw-html'],'changed')).code,0);
  assert.match(readFileSync(join(dir,'answer.html'),'utf8'),/>original<\/span>/);
});
