/* Verify columnar decoding and that queries open only the chunks that can match. */
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const os = require('node:os'), path = require('node:path'), zlib = require('node:zlib');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cairn-bundle-parts-'));
const assets = path.join(root, 'assets'); fs.mkdirSync(assets);
const bucket = value => { let h = 0; for (const c of value) h = (Math.imul(h, 31) + c.codePointAt(0)) >>> 0; return (h % 256).toString(16).padStart(2, '0'); };
const hex = key => [...key].map(c => c.codePointAt(0).toString(16)).join('-');
const tokens = s => String(s || '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
function columnar(rows, dictFields = []) {
  const columns = {}, dicts = {};
  for (const field of Object.keys(rows[0])) {
    columns[field] = rows.map(r => r[field] ?? null);
    if (dictFields.includes(field)) { dicts[field] = [...new Set(columns[field])]; columns[field] = columns[field].map(v => dicts[field].indexOf(v)); }
  }
  return {columns, dicts};
}
function write(name, value) {
  const encoded = zlib.gzipSync(Buffer.from(JSON.stringify(value))).toString('base64');
  fs.writeFileSync(path.join(assets, name + '.js'), `window.CairnBundles.register("test-version","${name}","${encoded}");\n`);
}
const paper = (id, journal_id, date, title) => ({id, title, journal_id, journal: journal_id.toUpperCase(), authors: ['A'], author_count: 1, author_ids: ['author-' + id], author_pos: null,
  date, date_precision: 'day', published_print: date, published_online: null, year: Number(date.slice(0, 4)), entry_type: 'article', publication_status: 'issue_assigned', first_date: date,
  first_precision: 'day', first_lower: date, first_upper: date, issue_id: null});
write('summaries-a-0001', columnar([paper('p0', 'a', '2020-05-01', 'Old model')], ['journal_id', 'journal']));
write('summaries-a-0002', columnar([paper('p1', 'a', '2026-05-01', 'New model')], ['journal_id', 'journal']));
write('summaries-b-0001', columnar([paper('p2', 'b', '2026-06-01', 'Another model')], ['journal_id', 'journal']));
write('search-' + bucket('model'), {model: [0, 1, 2]});

// Ordinals 0..2 in directory order; slots=2 names per entity.
const people = [
  {id: 'orcid:0', display_name: 'Ann Smith', aliases: [], identifiers: [], paper_indices: [0], identity_status: 'source_identified', publication_count: 1},
  {id: 'orcid:1', display_name: 'John Smith', aliases: ['J. Smith'], identifiers: [], paper_indices: [2], identity_status: 'source_identified', publication_count: 1},
  {id: 'orcid:2', display_name: 'John Doe', aliases: ['Jane Smith'], identifiers: [], paper_indices: [1], identity_status: 'source_identified', publication_count: 1},
];
write('authors-0001', columnar(people.slice(0, 2), ['identity_status']));
write('authors-0002', columnar(people.slice(2), ['identity_status']));
const ids = {}, shards = {}, files = {};
people.forEach((e, ordinal) => {
  (ids[bucket(e.id)] ||= {})[e.id] = ordinal;
  [...new Set([e.display_name, ...e.aliases])].forEach((name, slot) => new Set(tokens(name)).forEach(word => {
    const key = [...word].slice(0, 2).join(''), file = files[key] = hex([...word][0]) + '-s';
    ((shards[file] ||= {})[word] ||= []).push(ordinal * 2 + slot);
  }));
});
for (let n = 0; n < 256; n++) { const key = n.toString(16).padStart(2, '0'); write('author-ids-' + key, ids[key] || {}); }
for (const [file, words] of Object.entries(shards)) write('author-names-' + file, Object.fromEntries(Object.entries(words).map(([w, v]) => [w, v.map((x, i) => i ? x - v[i - 1] : x)])));
write('author-name-shards', files);

const config = {
  version: 'test-version', assets: 'assets/', meta: {journals: []}, recent_periods: {},
  summary_chunks: [['summaries-a-0001', 0, 1, 'a', '2020-01-01', '2020-12-31'], ['summaries-a-0002', 1, 1, 'a', '2026-01-01', '2026-12-31'], ['summaries-b-0001', 2, 1, 'b', '2026-01-01', '2026-12-31']],
  entities: {author: {count: 3, chunk: 2, slots: 2}, institution: {count: 0, chunk: 2, slots: 1}},
};
let requested = [];
let context;
const document = {
  createElement() { return {remove() {}}; },
  head: {append(script) {
    requested.push(path.basename(script.src, '.js'));
    try { vm.runInContext(fs.readFileSync(path.join(root, script.src), 'utf8'), context); script.onload(); }
    catch (error) { script.onerror(error); }
  }},
};
context = vm.createContext({window: {CAIRN_CONFIG: config}, document, Blob, Response, DecompressionStream, Uint8Array, atob, Intl, Date});
for (const name of ['periods.js', 'offline-runtime.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'src', 'cairn_catalog', 'assets', name), 'utf8'), context);
  if (name === 'periods.js') context.CairnPeriods = context.window.CairnPeriods;
}
const api = context.window.cairnOfflineApi;
const take = async (path, args) => { requested = []; const result = await api(path, args); return [result, [...requested].sort()]; };
(async () => {
  let [result, files] = await take('papers', {journal: 'b'});
  assert.deepEqual(Array.from(result.items, p => p.id), ['p2']);
  assert.deepEqual(files, ['summaries-b-0001'], 'A journal filter opens only that journal');
  assert.equal(result.items[0].journal, 'B', 'Dictionary columns decode');
  assert.deepEqual(JSON.parse(JSON.stringify(result.items[0].author_entities)), [{position: 1, author_id: 'author-p2'}]);
  [result, files] = await take('papers', {start_date: '2026-01-01', end_date: '2026-12-31'});
  assert.deepEqual(Array.from(result.items, p => p.id), ['p2', 'p1']);
  assert.deepEqual(files, ['summaries-a-0002'], 'A period skips chunks outside it (b-0001 already cached)');
  [result, files] = await take('papers', {query: 'model', journal: 'a'});
  assert.equal(result.total, 2);
  assert.deepEqual(files, ['search-' + bucket('model'), 'summaries-a-0001']);
  [result, files] = await take('entities', {kind: 'author', query: '', limit: 1, offset: 2});
  assert.equal(result.total, 3);
  assert.deepEqual(Array.from(result.items, e => e.id), ['orcid:2']);
  assert.deepEqual(files, ['authors-0002'], 'A directory page opens only its chunk');
  [result] = await take('entities', {kind: 'author', query: 'john smith'});
  assert.deepEqual(Array.from(result.items, e => e.id), ['orcid:1'], 'All words must match one name');
  [result] = await take('entities', {kind: 'author', query: 'j smith'});
  assert.deepEqual(Array.from(result.items, e => e.id), ['orcid:1', 'orcid:2'], 'One-letter words use every shard for that letter');
  [result, files] = await take('publications', {kind: 'author', entity: 'orcid:2'});
  assert.deepEqual(Array.from(result.items, p => p.id), ['p1']);
  assert.equal((await api('entities', {kind: 'author', query: 'orcid:9'})).total, 0);
  fs.rmSync(root, {recursive: true, force: true});
  console.log(JSON.stringify({chunk_selection: true, columnar: true, entity_names: true}));
})().catch(error => { console.error(error); process.exitCode = 1; });
