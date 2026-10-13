/* Local classic-script bundles work from file:// as well as localhost. */
window.CairnBundles = (() => {
  const config = window.CAIRN_CONFIG, pending = new Map(), loaded = new Map();
  async function register(version, name, encoded) {
    const job = pending.get(name);
    if (!job) return;
    job.registered = true;
    try {
      if (version !== config.version) throw Error('Catalog editions differ. Reopen the catalog after the refresh.');
      // A per-character callback is ~25x slower than this on multi-megabyte bundles.
      let bytes;
      if (Uint8Array.fromBase64) bytes = Uint8Array.fromBase64(encoded);
      else {
        const binary = atob(encoded);
        bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      }
      let data = JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text());
      if (data && data.columns) data = decodeRows(data);
      loaded.set(name, data);
      job.resolve(data);
    } catch (error) { pending.delete(name); job.reject(error); }
  }
  // Columnar bundles: one array per field, with repeated strings stored once.
  function decodeRows({columns, dicts}) {
    const fields = Object.keys(columns), n = fields.length ? columns[fields[0]].length : 0, rows = new Array(n);
    for (let i = 0; i < n; i++) {
      const row = {};
      for (const field of fields) { const value = columns[field][i]; row[field] = dicts[field] && value != null ? dicts[field][value] : value; }
      if (row.author_ids) {
        row.author_entities = row.author_ids.map((author_id, k) => ({position: row.author_pos ? row.author_pos[k] : k + 1, author_id}));
        delete row.author_ids; delete row.author_pos;
      }
      rows[i] = row;
    }
    return rows;
  }
  function load(name) {
    if (loaded.has(name)) return Promise.resolve(loaded.get(name));
    if (pending.has(name)) return pending.get(name).promise;
    const job = {};
    job.promise = new Promise((resolve, reject) => { job.resolve = resolve; job.reject = reject; });
    pending.set(name, job);
    const script = document.createElement('script');
    script.src = config.assets + name + '.js';
    const fail = () => {
      pending.delete(name); script.remove();
      job.reject(Error('A catalog data file could not be opened. Keep the catalog HTML files and their catalog-assets folder together, then reload.'));
    };
    script.onerror = fail;
    script.onload = () => { if (!job.registered) fail(); else script.remove(); };
    document.head.append(script);
    return job.promise;
  }
  return {register, load, loaded, decodeRows};
})();
window.cairnOfflineApi = (() => {
  const load = window.CairnBundles.load;
  const fold = s => String(s || '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
  const tokens = s => fold(s).match(/[\p{L}\p{N}]+/gu) || [];
  const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const identity = s => String(s || '').replace(/^https?:\/\/(?:www\.)?orcid.org\//, 'orcid:').replace(/^https?:\/\/openalex.org\//, 'openalex:').replace(/^https?:\/\/ror.org\//, 'ror:');
  const bucket = value => { let h = 0; for (const c of value) h = (Math.imul(h, 31) + c.codePointAt(0)) >>> 0; return (h % 256).toString(16).padStart(2, '0'); };
  const order = (a, b) => cmp(b.publication_date || '', a.publication_date || '') || cmp(a.title, b.title) || cmp(a.id, b.id);
  const pubOrder = (a, b) => cmp(CairnPeriods.bounds(b.publication_date, b.date_precision)?.[0] || '', CairnPeriods.bounds(a.publication_date, a.date_precision)?.[0] || '') || cmp(a.title, b.title) || cmp(a.id, b.id);
  function stageMatches(p, stage) {
    if (!stage || stage === 'all') return true;
    if (stage === 'pending') return p.publication_status !== 'issue_assigned';
    if (!['issue_assigned', 'online_first', 'unassigned'].includes(stage)) throw Error('Invalid publication stage');
    return p.publication_status === stage;
  }
  function dated(p, basis = 'issue') {
    if (!['first', 'issue', 'online', 'print'].includes(basis)) throw Error('Invalid date basis');
    const value = basis === 'first' ? p.first_date : basis === 'online' ? p.published_online : basis === 'print' ? p.published_print : p.date;
    const precision = basis === 'first' ? p.first_precision : basis === 'issue' ? p.date_precision : !value ? null : value.length === 4 ? 'year' : value.length === 7 ? 'month' : 'day';
    return {...p, publication_date: value, date_precision: precision};
  }
  function bounds(p, basis) { return basis === 'first' ? p.first_lower && [p.first_lower, p.first_upper] : CairnPeriods.bounds(p.publication_date, p.date_precision); }
  function select(p, args) {
    if (!stageMatches(p, args.stage) || args.entry_type && p.entry_type !== args.entry_type) return null;
    const r = dated(p, args.basis), b = bounds(r, args.basis);
    if (!args.start_date && !args.end_date) return {...r, period_membership: 'certain'};
    const lo = args.start_date || '0001-01-01', hi = args.end_date || '9999-12-31';
    if (!b || b[0] > hi || b[1] < lo) return null;
    r.period_membership = b[0] >= lo && b[1] <= hi ? 'certain' : 'uncertain';
    return r.period_membership === 'certain' || args.include_uncertain === '1' ? r : null;
  }
  const config = window.CAIRN_CONFIG, pad = n => String(n).padStart(4, '0');
  // Each journal belongs to one field; unread state compares when a paper entered the catalog.
  const journalInfo = new Map(config.meta.journals.map(j => [j.id, j])), fieldIds = new Set((config.meta.fields || []).map(f => f.id));
  const fieldOf = id => journalInfo.get(id)?.field ?? null;
  const isNew = (p, field, seen) => Object.hasOwn(seen, field) && (p.first_seen || '') > seen[field];
  function parseSeen(value) {
    let seen;
    try { seen = JSON.parse(value || '{}'); } catch { throw Error('Invalid seen dates'); }
    if (!seen || Array.isArray(seen) || typeof seen !== 'object' || Object.values(seen).some(v => typeof v !== 'string' || v.length !== 10)) throw Error('Invalid seen dates');
    return seen;
  }
  function issueSummaries(rows) {
    const issues = new Map();
    for (const p of rows) {
      if (p.publication_status !== 'issue_assigned' || !p.issue_id) continue;
      if (!issues.has(p.issue_id)) issues.set(p.issue_id, {issue_id: p.issue_id, journal_id: p.journal_id, volume: p.volume ?? null, issue: p.issue ?? null, volume_series: p.volume_series ?? null, total: 0, date: ''});
      const entry = issues.get(p.issue_id); entry.total++;
      if ((p.first_date || '') > entry.date) entry.date = p.first_date || '';
    }
    return [...issues.values()].sort((a, b) => cmp(b.date, a.date) || cmp(a.issue_id, b.issue_id));
  }
  const hex = key => [...key].map(c => c.codePointAt(0).toString(16)).join('-');
  // Summary chunks never span journals and carry year-widened date bounds.
  const chunks = config.summary_chunks.map(([name, start, count, journal, lo, hi]) => ({name, start, count, journal, lo, hi}));
  function chunkAt(index) {
    let a = 0, b = chunks.length - 1;
    while (a < b) { const m = (a + b + 1) >> 1; if (chunks[m].start <= index) a = m; else b = m - 1; }
    return chunks[a];
  }
  async function summaryRows(list) {
    const data = await Promise.all(list.map(c => load(c.name)));
    return list.map((c, i) => [c, data[i]]);
  }
  async function rowsAt(indices) {
    const rows = new Map(await summaryRows([...new Set([...indices].map(chunkAt))]));
    return i => { const c = chunkAt(i); return rows.get(c)[i - c.start]; };
  }
  function entityConfig(kind) {
    if (!['author', 'institution'].includes(kind)) throw Error('Invalid entity kind');
    return config.entities[kind];
  }
  // Entity ordinals follow directory order; chunks hold consecutive ordinals.
  async function entitiesAt(kind, ordinals) {
    const size = entityConfig(kind).chunk, name = o => kind + 's-' + pad(Math.floor(o / size) + 1);
    const names = [...new Set(ordinals.map(name))], data = await Promise.all(names.map(load));
    const byName = new Map(names.map((n, i) => [n, data[i]]));
    return ordinals.map(o => byName.get(name(o))[o % size]);
  }
  async function entityById(kind, id) {
    const ordinal = (await load(`${kind}-ids-${bucket(id)}`))[id];
    return ordinal === undefined ? null : (await entitiesAt(kind, [ordinal]))[0];
  }
  // Postings encode ordinal * slots + name slot, so every word must match the same name.
  async function nameMatches(kind, terms) {
    const {slots} = entityConfig(kind), files = await load(kind + '-name-shards');
    let matches = null;
    for (const term of [...terms].sort((a, b) => b.length - a.length)) {
      const chars = [...term];
      const wanted = chars.length > 1 ? [files[chars.slice(0, 2).join('')]].filter(Boolean)
        : [...new Set(Object.entries(files).filter(([key]) => [...key][0] === term).map(([, file]) => file))];
      const found = new Set();
      for (const shard of await Promise.all(wanted.map(file => load(`${kind}-names-${file}`)))) {
        for (const word in shard) {
          if (!word.startsWith(term)) continue;
          let value = 0;
          for (const gap of shard[word]) { value += gap; if (!matches || matches.has(value)) found.add(value); }
        }
      }
      matches = found;
      if (!matches.size) break;
    }
    return [...new Set([...matches].map(v => Math.floor(v / slots)))].sort((a, b) => a - b);
  }
  // Whole-catalog overview for a profile: papers per year, journals and frequent coauthors.
  function profile(kind, e, papers) {
    const years = {}, journals = new Map(), coauthors = new Map(), own = new Set([e.id, ...(e.identifiers || [])]);
    for (const p of papers) {
      if (p.year != null) years[p.year] = (years[p.year] || 0) + 1;
      journals.set(p.journal_id, (journals.get(p.journal_id) || 0) + 1);
      if (kind !== 'author') continue;
      for (const a of p.author_entities || []) {
        if (own.has(a.author_id) || a.author_id.startsWith('unresolved-') || a.position > 10) continue;
        const entry = coauthors.get(a.author_id) || {id: a.author_id, name: p.authors[a.position - 1] || a.author_id, papers: 0};
        entry.papers++; coauthors.set(a.author_id, entry);
      }
    }
    return {years, journals: [...journals].sort((a, b) => b[1] - a[1] || cmp(a[0], b[0])),
      coauthors: [...coauthors.values()].sort((a, b) => b.papers - a.papers || cmp(a.name, b.name)).slice(0, 8)};
  }
  function publicEntity(e) { const {names, aliases, identifiers, paper_indices, ...rest} = e; return rest; }
  async function queryIndices(query) {
    const doi = query.trim().replace(/^https?:\/\/(?:dx\.)?doi.org\//i, '').replace(/^doi:\s*/i, '').toLowerCase();
    if (/^10\.\d{4,9}\//.test(doi)) return new Set((await load('dois-' + bucket(doi)))[doi] || []);
    const terms = [...new Set(tokens(query))];
    if (!terms.length) return new Set();
    const lists = await Promise.all(terms.map(async t => (await load('search-' + bucket(t)))[t] || []));
    lists.sort((a, b) => a.length - b.length);
    let ids = new Set(lists[0]);
    for (const list of lists.slice(1)) { const next = new Set(list); ids = new Set([...ids].filter(i => next.has(i))); }
    return ids;
  }
  return async function api(path, args = {}) {
    const limit = Math.max(1, Math.min(200, Number(args.limit) || 30)), offset = Math.max(0, Number(args.offset) || 0);
    CairnPeriods.range(args.start_date, args.end_date);
    if (path === 'meta') return window.CAIRN_CONFIG.meta;
    if (path === 'insights') return load('insights');
    if (path === 'recent') {
      if (!['', 'date', 'journal', 'field'].includes(args.group_by || '')) throw Error('Invalid recent-publications grouping');
      if (args.field && !fieldIds.has(args.field)) throw Error('Unknown field');
      const seen = parseSeen(args.seen);
      const lo = args.start_date, hi = args.end_date;
      if (!lo || !hi) throw Error('Choose both dates for What’s New.');
      const periods = config.recent_periods, names = new Set(), start = new Date(lo + 'T00:00:00Z'), end = new Date(hi + 'T00:00:00Z');
      for (let year = start.getUTCFullYear(); year <= end.getUTCFullYear(); year++) {
        const record = periods[String(year)];
        if (!record) continue;
        for (let month = 0; month < 12; month++) {
          const key = `${year}-${String(month + 1).padStart(2, '0')}`;
          if (key >= lo.slice(0, 7) && key <= hi.slice(0, 7) && record.months.includes(key.slice(5, 7))) names.add('recent-' + key);
        }
        if (record.uncertain) names.add('recent-' + year + '-uncertain');
      }
      const bundles = [...names];
      const all = [...new Map((await Promise.all(bundles.map(load))).flat().map(p => [p.id, p])).values()];
      let uncertain = 0;
      const rows = [];
      for (const p of all) {
        if (p.first_lower > hi || p.first_upper < lo) continue;
        if (p.first_lower < lo || p.first_upper > hi) { uncertain++; continue; }
        rows.push({...dated(p, 'first'), period_membership: 'certain'});
      }
      const filtered = rows.filter(p => (!args.field || fieldOf(p.journal_id) === args.field) && (args.new_only !== '1' || isNew(p, fieldOf(p.journal_id), seen)));
      rows.length = 0; rows.push(...filtered);
      rows.sort(order);
      if (args.group_by === 'field') {
        const fields = config.meta.fields.map(f => {
          const papers = rows.filter(p => fieldOf(p.journal_id) === f.id), journals = new Map();
          for (const p of papers) {
            if (!journals.has(p.journal_id)) journals.set(p.journal_id, {journal_id: p.journal_id, journal: p.journal, abbreviation: journalInfo.get(p.journal_id).abbreviation, total: 0, new_total: 0});
            const j = journals.get(p.journal_id); j.total++; j.new_total += isNew(p, f.id, seen) ? 1 : 0;
          }
          const list = [...journals.values()].sort((a, b) => b.total - a.total || cmp(a.journal, b.journal) || cmp(a.journal_id, b.journal_id));
          return {field: f.id, label: f.label, total: papers.length, new_total: list.reduce((n, j) => n + j.new_total, 0), journals: list, issues: issueSummaries(papers).slice(0, 8), items: papers.slice(0, 5)};
        });
        return {total: rows.length, uncertain_count: uncertain, fields};
      }
      if (args.group_by === 'journal') {
        let offsets;
        try { offsets = JSON.parse(args.journal_offsets || '{}'); } catch { throw Error('Invalid journal offsets'); }
        if (!offsets || Array.isArray(offsets) || typeof offsets !== 'object' || Object.values(offsets).some(v => !Number.isSafeInteger(v) || v < 0)) throw Error('Invalid journal offsets');
        const journals = new Map();
        for (const paper of rows) {
          if (!journals.has(paper.journal_id)) journals.set(paper.journal_id, []);
          journals.get(paper.journal_id).push(paper);
        }
        const groups = [...window.CAIRN_CONFIG.meta.journals].sort((a, b) => cmp(a.title, b.title) || cmp(a.id, b.id)).flatMap(j => {
          const items = journals.get(j.id);
          if (!items?.length) return [];
          const start = Math.min(Math.floor((offsets[j.id] || 0) / 10), Math.floor((items.length - 1) / 10)) * 10;
          const field = fieldOf(j.id);
          return [{journal_id: j.id, journal: j.title, total: items.length, offset: start, items: items.slice(start, start + 10), field, abbreviation: j.abbreviation ?? null, new_total: items.filter(p => isNew(p, field, seen)).length, issues: issueSummaries(items)}];
        });
        return {total: rows.length, uncertain_count: uncertain, groups};
      }
      return {total: rows.length, uncertain_count: uncertain, items: rows.slice(offset, offset + limit)};
    }
    if (path === 'entities') {
      const kind = args.kind || 'author', {count} = entityConfig(kind), id = identity(args.query || ''), terms = [...new Set(tokens(args.query))];
      let ordinals;
      if (/^(orcid:|openalex:|ror:|unresolved-)/.test(id)) {
        const ordinal = (await load(`${kind}-ids-${bucket(id)}`))[id];
        ordinals = ordinal === undefined ? [] : [ordinal];
      } else if (terms.length) ordinals = await nameMatches(kind, terms);
      else {
        const page = Array.from({length: Math.max(0, Math.min(limit, count - offset))}, (_, i) => offset + i);
        return {total: count, items: (await entitiesAt(kind, page)).map(publicEntity)};
      }
      return {total: ordinals.length, items: (await entitiesAt(kind, ordinals.slice(offset, offset + limit))).map(publicEntity)};
    }
    if (path === 'paper') {
      const p = (await load('details-' + bucket(args.id)))[args.id];
      if (!p) throw Error('Paper not found');
      return p;
    }
    if (path === 'issues') return {items: (await load('issues')).filter(i => (!args.journal || i.journal_id === args.journal) && (!args.year || i.year == args.year)).sort((a, b) => cmp(b.date || '', a.date || ''))};
    if (path === 'papers') {
      const matches = args.query?.trim() ? await queryIndices(args.query) : null;
      let journal = args.journal;
      if (args.issue && !journal) journal = (await load('issues')).find(i => i.id === args.issue)?.journal_id || '\0';
      // Load only chunks that can hold a match: same journal, overlapping dates, matched indices.
      const lo = args.start_date || '0001-01-01', hi = args.end_date || '9999-12-31', bounded = args.start_date || args.end_date;
      const hit = matches && new Set([...matches].map(chunkAt));
      const list = chunks.filter(c => (!journal || c.journal === journal) && (!bounded || c.lo && c.lo <= hi && c.hi >= lo) && (!hit || hit.has(c)));
      const rows = [];
      for (const [c, papers] of await summaryRows(list)) papers.forEach((p, k) => {
        if (matches && !matches.has(c.start + k) || args.journal && p.journal_id !== args.journal || args.issue && p.issue_id !== args.issue || args.year && p.year != args.year) return;
        const row = select(p, args); if (row) rows.push(row);
      });
      rows.sort(order);
      return {total: rows.length, items: rows.slice(offset, offset + limit)};
    }
    if (path === 'publications') {
      const kind = args.kind || 'author'; entityConfig(kind);
      const e = await entityById(kind, identity(args.entity));
      if (!e) throw Error('Choose an explicit author or institution identity.');
      const paperAt = await rowsAt(e.paper_indices), rows = [];
      let certain = 0, uncertain = 0, undated = 0;
      for (const idx of e.paper_indices) {
        const p = paperAt(idx); if (!stageMatches(p, args.stage)) continue;
        const datedPaper = dated(p, args.basis); if (!bounds(datedPaper, args.basis)) undated++;
        const r = select(p, {...args, include_uncertain: '1'});
        if (!r) continue;
        if (r.period_membership === 'certain') certain++; else uncertain++;
        if (r.period_membership === 'certain' || args.include_uncertain === '1') rows.push(r);
      }
      rows.sort(pubOrder);
      const all = !args.start_date && !args.end_date;
      return {entity: publicEntity(e), profile: profile(kind, e, e.paper_indices.map(paperAt)), period: all ? 'All available dates' : `${args.start_date || 'Beginning'} to ${args.end_date || 'Present'}`, period_mode: all ? 'all' : 'range', certain_count: certain, uncertain_count: uncertain, undated_publications_all_years: undated, total: rows.length, items: rows.slice(offset, offset + limit), affiliation_note: kind === 'institution' ? 'Paper-level source affiliations; not current employer.' : null};
    }
    throw Error('Unknown catalog request');
  };
})();
