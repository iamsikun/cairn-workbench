/* Exercise the actual generated offline bundles with network access disabled. */
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), path = require('node:path');
const root = process.argv[3] || __dirname, html = fs.readFileSync(path.join(root, 'catalog.html'), 'utf8');
const config = JSON.parse(html.match(/window.CAIRN_CONFIG=(.*?);<\/script>/s)[1]);
// A fresh runtime has an empty bundle cache, so its requests measure one action's payload.
function runtime() {
  const requested = [];
  let context;
  const document = {
    createElement() { return {remove() {}}; },
    head: {append(script) {
      requested.push(path.basename(script.src));
      try { vm.runInContext(fs.readFileSync(path.join(root, script.src), 'utf8'), context); script.onload(); }
      catch (error) { script.onerror(error); }
    }},
  };
  context = vm.createContext({window: {CAIRN_CONFIG: config}, document, Blob, Response, DecompressionStream, Uint8Array, atob, Intl, Date, console, fetch() { throw Error('Network disabled'); }});
  for (const name of ['periods.js', 'offline-runtime.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, config.assets, name), 'utf8'), context);
    if (name === 'periods.js') context.CairnPeriods = context.window.CairnPeriods;
  }
  return {api: context.window.cairnOfflineApi, requested, P: context.CairnPeriods};
}
async function payload(route, args) {
  const {api, requested} = runtime(), result = await api(route, args), files = [...new Set(requested)];
  return {result, files, bytes: files.reduce((n, name) => n + fs.statSync(path.join(root, config.assets, name)).size, 0)};
}
new vm.Script(fs.readFileSync(path.join(root, config.assets, 'catalog-ui.js'), 'utf8'));
const {api, requested, P} = runtime();
assert.equal(P.rolling(5, 'year', '2024-02-29').start_date, '2019-03-01');
assert.equal(P.lastQuarter('2026-01-03').start_date, '2025-10-01');
assert.equal(P.calendar(2025, 'quarter', 7, 3).end_date, '2027-03-31');
assert.throws(() => P.range('2026-02-30', '2026-10-11'));
assert.throws(() => P.range('2026-10-12', '2026-10-11'));
(async () => {
  const meta = await api('meta');
  assert.equal(requested.length, 0, 'Metadata must not load the catalog');
  const recent = await api('recent', {start_date: '2026-07-13', end_date: '2026-10-12', limit: 30});
  assert(recent.total > 0);
  if (config.recent_periods) assert(recent.items.every(p => p.author_count >= p.authors.length && p.authors.length <= 10 && p.author_entities.length <= 10));
  const expectedRecent = [];
  if (config.recent_periods) {
    for (const month of ['07', '08', '09', '10']) if (config.recent_periods['2026']?.months.includes(month)) expectedRecent.push(`recent-2026-${month}.js`);
    if (config.recent_periods['2026']?.uncertain) expectedRecent.push('recent-2026-uncertain.js');
  } else expectedRecent.push('recent-2026.js');
  assert.deepEqual([...new Set(requested)].sort(), expectedRecent.sort(), 'Recent loads only selected month bundles and matching uncertain-date shards');
  assert(recent.items.every(p => !('abstract' in p) && p.period_membership === 'certain'));
  const grouped = await api('recent', {start_date: '2026-07-13', end_date: '2026-10-12', group_by: 'journal'});
  assert.equal(grouped.total, recent.total);
  assert.equal(grouped.groups.reduce((n, g) => n + g.total, 0), recent.total);
  assert(grouped.groups.every(g => g.items.length <= 10 && g.items.every(p => !('abstract' in p))));
  assert.deepEqual([...new Set(requested)].sort(), expectedRecent.sort(), 'Journal view must reuse the selected recent shards');
  const paged = await api('recent', {start_date: '2026-07-13', end_date: '2026-10-12', group_by: 'journal', journal_offsets: '{"mnsc":10}'});
  assert.deepEqual(paged.groups.filter(g => g.journal_id !== 'mnsc'), grouped.groups.filter(g => g.journal_id !== 'mnsc'));
  for (const journal_offsets of ['null', '[]', '1', '{', '{"mnsc":-1}', '{"mnsc":1.5}', '{"mnsc":true}', '{"mnsc":"10"}', '{"mnsc":9007199254740992}']) {
    await assert.rejects(api('recent', {start_date: '2026-07-13', end_date: '2026-10-12', group_by: 'journal', journal_offsets}), /Invalid journal offsets/);
  }
  const overview = await api('recent', {start_date: '2026-07-13', end_date: '2026-10-12', group_by: 'field', seen: '{}'});
  assert.equal(overview.total, recent.total);
  assert.equal(overview.fields.reduce((n, f) => n + f.total, 0), recent.total);
  assert(overview.fields.every(f => f.items.length <= 5 && f.issues.length <= 8));
  assert.deepEqual([...new Set(requested)].sort(), expectedRecent.sort(), 'The field overview must reuse the selected recent shards');
  for (const seen of ['[]', 'null', '{"economics":5}', '{"economics":"2026"}', '{']) await assert.rejects(api('recent', {start_date: '2026-07-13', end_date: '2026-10-12', group_by: 'field', seen}), /Invalid seen dates/);
  await assert.rejects(api('recent', {start_date: '2026-07-13', end_date: '2026-10-12', group_by: 'journal', field: 'nonsense'}), /Unknown field/);
  const homeShards = expectedRecent;
  const initialBytes = Buffer.byteLength(html) + ['catalog.css', 'catalog-ui.js', 'periods.js', 'offline-runtime.js'].reduce((n, p) => n + fs.statSync(path.join(root, config.assets, p)).size, 0) + homeShards.reduce((n, name) => n + fs.statSync(path.join(root, config.assets, name)).size, 0);
  assert(initialBytes < 1000000, `Home exceeded 1 MB: ${initialBytes}`);
  const detail = await api('paper', {id: recent.items[0].id});
  assert(detail.journal_membership && Array.isArray(detail.author_entities) && Array.isArray(detail.institution_entities));
  assert.equal(detail.authors.length, detail.author_entities.length, 'Paper details keep complete author bylines and identities');
  assert(requested.every(p => /(?:recent-2026-(?:\d{2}|uncertain)|recent-2026|details-[a-f0-9]{2})\.js$/.test(p)), 'Opening a paper must not initialize search or entity directories');
  const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  // Objects from the sandbox have another realm's prototypes; compare their JSON.
  const plain = value => JSON.parse(JSON.stringify(value));
  for (const c of cases) {
    const result = await api(c.path, c.args);
    if (c.insights) { assert.deepEqual(plain(result), c.insights, 'insights bundle matches SQLite'); continue; }
    assert.equal(result.total, c.total, JSON.stringify(c.args));
    if (c.certain_count !== undefined) assert.equal(result.certain_count, c.certain_count, JSON.stringify(c.args));
    if (c.uncertain_count !== undefined) assert.equal(result.uncertain_count, c.uncertain_count, JSON.stringify(c.args));
    if (c.groups) {
      const groups = plain(Array.from(result.groups, ({items, ...g}) => ({...g, ids: Array.from(items, p => p.id), author_ids: Array.from(items, p => Array.from(p.author_entities, a => a.author_id))})));
      assert.deepEqual(groups, c.groups, JSON.stringify(c.args));
    } else if (c.fields) {
      assert.deepEqual(plain(Array.from(result.fields, ({items, ...f}) => ({...f, ids: Array.from(items, p => p.id)}))), c.fields, JSON.stringify(c.args));
    } else assert.deepEqual(Array.from(result.items, p => p.id), c.ids, JSON.stringify(c.args));
    if (c.author_ids) assert.deepEqual(Array.from(result.items, p => Array.from(p.author_entities, a => a.author_id)), c.author_ids);
  }
  const navigation = await require('./home_navigation.js')(fs.readFileSync(path.join(root, config.assets, 'catalog-ui.js'), 'utf8'), config, P, api);
  await assert.rejects(api('paper', {id: 'https://openalex.org/W2994574218'}), /Paper not found/);
  assert.equal((await api('entities', {kind: 'author', query: 'openalex:A5096567628'})).total, 0);
  const all = await api('papers', {period: 'all', limit: 1}); assert.equal(all.total, meta.papers);
  // Ordinary actions must open only the chunks that can answer them.
  const budgets = {};
  const check = async (label, route, args, maxBytes, test = () => true) => {
    const {result, files, bytes} = await payload(route, args);
    assert(bytes <= maxBytes, `${label} loaded ${bytes} bytes (${files.length} files)`);
    assert(test(result, files), label);
    budgets[label] = {bytes, files: files.length};
    return result;
  };
  await check('journal_search_aer', 'papers', {journal: 'aer', period: 'all', limit: 30}, 15e6, (r, files) => r.total > 0 && files.every(f => f.startsWith('summaries-aer-')));
  await check('doi_lookup', 'papers', {query: 'https://doi.org/10.1257/aer.20191569', period: 'all', limit: 30}, 3e6, (r, files) => files.filter(f => f.startsWith('dois-')).length === 1);
  await check('recent_quarter_all_journals', 'papers', {start_date: '2026-07-01', end_date: '2026-09-30', period: 'range', limit: 30}, 30e6, r => r.total > 0);
  await check('author_directory_first_page', 'entities', {kind: 'author', query: '', limit: 20}, 2e6, (r, files) => r.total > 1e6 && files.length === 1);
  await check('author_name_search', 'entities', {kind: 'author', query: 'John', limit: 20}, 25e6, r => r.total > 0);
  await check('institution_profile', 'publications', {kind: 'institution', entity: 'ror:024mw5h28', period: 'all', limit: 30}, 40e6, r => r.total > 0);
  for (const filename of ['catalog.html', 'search.html', 'authors.html', 'institutions.html', 'explore.html']) {
    const page = fs.readFileSync(path.join(root, filename), 'utf8');
    assert(page.includes(config.version), 'All entrypoints must share one immutable asset edition');
    assert(!page.includes('id="cairn-data"'), 'No whole-catalog payload in HTML');
    assert(!page.includes('id="homeView"') && !page.includes('id="homePager"'), 'Home must have only the journal view');
    const activeSource = page + fs.readFileSync(path.join(root, config.assets, 'catalog-ui.js'), 'utf8');
    for (const removed of ['Recently published research across the catalog’s ten journals.', 'inclusive dates', 'Source dates may be incomplete.']) assert(!activeSource.includes(removed), `Removed wording remains: ${removed}`);
  }
  console.log(JSON.stringify({network_disabled: true, parity_queries: cases.length, papers: meta.papers, home_initial_bytes: initialBytes, detail_loaded_on_demand: true, navigation, budgets}));
})().catch(error => {console.error(error); process.exitCode = 1;});
