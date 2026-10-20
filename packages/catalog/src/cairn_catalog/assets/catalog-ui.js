/* Shared interface; each destination owns its URL and form state. */
(() => {
  const $ = id => document.getElementById(id), config = window.CAIRN_CONFIG;
  const page = document.body.dataset.page, entityPage = ['author', 'institution'].includes(page);
  const size = 30, num = n => Number(n).toLocaleString(), esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const read = () => Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
  const url = (file, args) => file + '#' + new URLSearchParams(Object.entries(args).filter(([, v]) => v !== '' && v != null));
  let version = 0, detailVersion = 0, issueVersion = 0;
  const stored = (key, value) => { try { if (value !== undefined) localStorage.setItem(key, value); else return localStorage.getItem(key); } catch {} };
  const storedJson = (key, fallback) => { try { return JSON.parse(stored(key) || 'null') ?? fallback; } catch { return fallback; } };
  // Fields, tiers and "For you" come from fields.json and the optional catalog-personal.js.
  let personal = window.CAIRN_PERSONAL || null;
  const fieldList = config.meta.fields || [];
  const journalById = new Map(config.meta.journals.map(j => [j.id, j])), fieldById = new Map(fieldList.map(f => [f.id, f]));
  const fieldOf = p => journalById.get(p.journal_id)?.field;
  const tierOf = field => personal?.tiers?.[field] || fieldById.get(field)?.tier || 'core';
  const paperTier = p => personal?.journal_tiers?.[p.journal_id] || tierOf(fieldOf(p));
  const abbr = id => journalById.get(id)?.abbreviation || journalById.get(id)?.title || id;
  const compact = () => (stored('cairn-density') || 'compact') === 'compact';
  // Unread state: the snapshot each field was last caught up to. A first visit starts caught up.
  function seenDates() {
    const seen = storedJson('cairn-seen', {}), snapshot = config.meta.snapshot_date;
    let changed = false;
    for (const f of fieldList) if (typeof seen[f.id] !== 'string' || seen[f.id].length !== 10) { seen[f.id] = snapshot; changed = true; }
    if (changed) stored('cairn-seen', JSON.stringify(seen));
    return seen;
  }
  const isNew = (p, seen = seenDates()) => !!p.first_seen && p.first_seen > (seen[fieldOf(p)] || '9999');
  function markSeen(fields) {
    const seen = seenDates();
    for (const f of fields) seen[f] = config.meta.snapshot_date;
    stored('cairn-seen', JSON.stringify(seen));
  }
  const reasonText = r => ({person: 'Following ', institution: 'Institution: ', topic: 'Topic: ', keyword: 'Keyword: '}[r.type] || '') + r.label + (r.unverified ? ' (name match, unverified)' : '');
  // Single-series bar strip: one accent hue, 2px gaps, a faint baseline for empty bins, a tooltip per bar.
  function bars(values, labels, label, width = 76, height = 18) {
    const max = Math.max(1, ...values), w = width / values.length;
    return `<svg class="spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}">${values.map((v, i) => {
      const h = v ? Math.max(2, v / max * height) : 1;
      return `<rect class="${v ? '' : 'zero'}" x="${(i * w + 1).toFixed(1)}" y="${(height - h).toFixed(1)}" width="${Math.max(1, w - 2).toFixed(1)}" height="${h.toFixed(1)}" rx="1"><title>${esc(labels[i])}: ${num(v)}</title></rect>`;
    }).join('')}</svg>`;
  }
  function rememberNavigation(args) {
    try {
      const saved = {...args}; delete saved.paper;
      if (page === 'home') for (const key of Object.keys(saved)) if (['field', 'section', 'foryou'].includes(key) || key.startsWith('offset_')) delete saved[key];
      // The Authors and Institutions tabs always lead back to their landing page, not the last profile or search.
      if (entityPage) for (const key of Object.keys(saved)) if (!['ins_field', 'ins_period'].includes(key)) delete saved[key];
      sessionStorage.setItem('cairn-nav-' + page, new URLSearchParams(saved).toString());
      document.querySelectorAll('[data-nav]').forEach(a => {
        const hash = sessionStorage.getItem('cairn-nav-' + a.dataset.nav);
        if (hash) a.href = a.getAttribute('href').split('#')[0] + '#' + hash;
      });
    } catch {}
  }
  const dateLabel = (value, precision) => {
    if (!value) return 'Date unavailable';
    if (['provider_day_unverified', 'provider_date_unverified', 'range'].includes(precision)) return value.slice(0, 4) + ' · date uncertain';
    if (value.length === 4) return value + ' · year only';
    const full = value.length === 7 ? value + '-01' : value;
    return new Intl.DateTimeFormat('en-US', {timeZone: 'UTC', year: 'numeric', month: 'short', ...(value.length > 7 ? {day: 'numeric'} : {})}).format(new Date(full + 'T00:00:00Z')) + (value.length === 7 ? ' · day unspecified' : '');
  };
  // Pages read the prebuilt offline bundles, also through the catalog app; only explore.html queries SQLite.
  const sqliteEdition = location.protocol !== 'file:' && location.pathname.endsWith('/explore.html');
  async function api(path, args = {}) {
    if (!sqliteEdition) return window.cairnOfflineApi(path, args);
    const response = await fetch('api/' + path + '?' + new URLSearchParams({...args, version: config.version}));
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'The catalog could not be loaded.');
    return result;
  }
  function fail(error) { $('error').textContent = error.message; }
  // Inside Cairn Studio (under /catalog/), papers already in the knowledge base link to their notes.
  const studio = location.protocol !== 'file:' && location.pathname.startsWith('/catalog/');
  let inKb = {};
  async function loadInKb() {
    if (!studio) return;
    const response = await fetch('in-kb.json?' + new URLSearchParams({c: stored('cairn-studio:collection') || ''}));
    if (response.ok) inKb = (await response.json()).papers || {};
  }
  const noteUrl = p => '/#/note/' + encodeURIComponent(inKb[p.id].slug);
  const kbChip = p => inKb[p.id] ? `<a class="chip in-kb" href="${esc(noteUrl(p))}" title="${esc('In your knowledge base: ' + inKb[p.id].title)}">In KB</a>` : '';
  // Follows, keywords, topics and field tiers are saved to the preferences file through the catalog app
  // (cairn-catalog serve), which then regenerates catalog-personal.js. A file:// page cannot write files.
  const editable = location.protocol !== 'file:';
  const appUrl = () => 'http://127.0.0.1:8766/' + location.pathname.split('/').pop() + location.hash;
  const appHint = () => `To change this from the page, open the catalog through the catalog app: run <code>cairn-catalog serve --open</code>. If it is already running, <a href="${esc(appUrl())}">open this page in the app</a>.`;
  const saveAttr = (change, done = 'Saved to your preferences') => `data-save="${esc(JSON.stringify(change))}" data-done="${esc(done)}"${editable ? '' : ' disabled'}`;
  let statusTimer;
  function showStatus(text, failed = false, ms = 0) {
    const node = $('saveStatus'); clearTimeout(statusTimer);
    node.hidden = false; node.textContent = text; node.classList.toggle('failed', failed);
    if (ms) statusTimer = setTimeout(() => node.hidden = true, ms);
  }
  // Changes are saved one at a time, in the order they were made.
  let saveQueue = Promise.resolve(), pendingSaves = 0;
  function savePreference(change, done) {
    if (!editable) return;
    pendingSaves++;
    showStatus(pendingSaves > 1 ? `Saving ${pendingSaves} changes to your preferences…` : 'Saving to your preferences and updating matches…');
    saveQueue = saveQueue.then(async () => {
      try {
        const response = await fetch('api/preferences', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(change)});
        const result = await response.json();
        if (!response.ok) throw Error(result.error || 'Could not save preferences.');
        personal = window.CAIRN_PERSONAL = result.personal;
        homeCache = null; homeDrawKey = null; if (page === 'home') $('homeLayout').dataset.layout = '';
        // Ambiguous or missing follows are explained in place; keyword syntax problems are not shown elsewhere.
        const problems = (result.warnings || []).filter(w => w.startsWith('Could not use keyword'));
        if (--pendingSaves) showStatus(`Saving ${pendingSaves} more ${pendingSaves === 1 ? 'change' : 'changes'}…`);
        else showStatus(problems.length ? `${done || 'Saved'}. ${problems.join(' ')}` : done || 'Saved to your preferences', false, problems.length ? 10000 : 2500);
      } catch (error) { pendingSaves--; showStatus(error.message, true, 8000); }
      await render().catch(fail);
    });
  }
  function go(args, replace = false, keepScroll = false, focusId = '') {
    history.replaceState({...history.state, scrollY: window.scrollY}, '', location.href);
    const next = {scrollY: keepScroll ? window.scrollY : 0, detailOpen: !!args.paper && !read().paper};
    history[replace ? 'replaceState' : 'pushState'](next, '', url(location.pathname, args));
    const destination = location.href;
    render().then(() => {
      if (location.href !== destination) return;
      if (focusId) $(focusId)?.focus({preventScroll: true});
      if (focusId && !keepScroll && $(focusId)) $(focusId).scrollIntoView({block: 'start', behavior: 'instant'});
      else window.scrollTo(0, next.scrollY);
      trackJournal();
    }).catch(fail);
  }
  function pager(id, total, offset, field, args, count = size) {
    const node = $(id); node.replaceChildren();
    if (!total || total <= count) return;
    for (const [label, value, disabled] of [['Previous', Math.max(0, offset - count), offset === 0], ['Next', offset + count, offset + count >= total]]) {
      const button = document.createElement('button'); button.textContent = label; button.disabled = disabled;
      button.onclick = () => go({...args, [field]: value, paper: ''}); node.append(button);
    }
    const span = document.createElement('span'); span.textContent = `${num(offset + 1)}–${num(Math.min(total, offset + count))} of ${num(total)}`; node.append(span);
  }
  function byline(p) {
    const ids = new Map((p.author_entities || []).map(a => [a.position, a.author_id]));
    const authors = (p.authors || []).slice(0, 10);
    const names = authors.map((name, i) => `<a href="${esc(url('authors.html', ids.has(i + 1) ? {entity: ids.get(i + 1)} : {query: name}))}">${esc(name)}</a>`);
    const more = Math.max(0, (p.author_count ?? (p.authors || []).length) - authors.length);
    if (more) names.push(`and ${num(more)} more`);
    return names.join(' · ') || 'Authors unavailable';
  }
  function stage(p) {
    return p.publication_status === 'issue_assigned' ? `<span>${p.volume_series ? esc(p.volume_series) + ' series · ' : ''}Vol. ${esc(p.volume)}${p.issue ? ' · Issue ' + esc(p.issue) : ''}${p.article_number ? ' · Article ' + esc(p.article_number) : ''}</span>` : `<span class="badge" title="${esc(p.publication_status_evidence)}">${p.publication_status === 'online_first' ? 'Online first' : 'Issue details unavailable'}</span>`;
  }
  function forYouChip(p) {
    const score = personal?.scores?.[p.id];
    return score ? `<span class="chip for-you-chip" title="${esc(score.reasons.map(reasonText).join('; '))}">For you</span>` : '';
  }
  function cardHtml(p, args) {
    const fresh = page === 'home' && isNew(p);
    return `<article class="paper${fresh ? ' is-new' : ''}">${fresh ? '<span class="new-dot" title="New since your last visit"></span>' : ''}<a class="paper-title" data-paper="${esc(p.id)}" href="${esc(url(location.pathname, {...args, paper: p.id}))}">${esc(p.title)}</a><div class="byline">${byline(p)}</div><div class="paper-meta"><a class="journal-name" href="${esc(url('search.html', {journal: p.journal_id}))}">${esc(p.journal)}</a><span title="${esc(p.first_source || '')}">${esc(dateLabel(p.publication_date, p.date_precision))}</span>${stage(p)}${p.period_membership === 'uncertain' ? '<span class="badge uncertain">Period uncertain</span>' : ''}${!['article', 'article_or_other'].includes(p.entry_type) ? `<span>${esc(p.entry_type?.replaceAll('_', ' '))}</span>` : ''}${forYouChip(p)}${kbChip(p)}</div></article>`;
  }
  function shortByline(p) {
    const ids = new Map((p.author_entities || []).map(a => [a.position, a.author_id])), authors = (p.authors || []).slice(0, 3);
    const names = authors.map((name, i) => `<a href="${esc(url('authors.html', ids.has(i + 1) ? {entity: ids.get(i + 1)} : {query: name}))}">${esc(name)}</a>`);
    const more = (p.author_count ?? (p.authors || []).length) - authors.length;
    return (names.join(', ') || 'Authors unavailable') + (more > 0 ? ` +${num(more)}` : '');
  }
  function shortDate(value, precision) {
    if (!value || value.length < 10 || ['provider_day_unverified', 'provider_date_unverified', 'range'].includes(precision)) return dateLabel(value, precision);
    const sameYear = value.slice(0, 4) === config.meta.snapshot_date.slice(0, 4);
    return new Intl.DateTimeFormat('en-US', {timeZone: 'UTC', month: 'short', day: 'numeric', ...(sameYear ? {} : {year: 'numeric'})}).format(new Date(value + 'T00:00:00Z'));
  }
  // One line per paper: title, then first authors · journal · date, with unread and "For you" marks.
  function rowHtml(p, args, {journal = true, reasons = false} = {}) {
    const fresh = isNew(p), score = personal?.scores?.[p.id];
    const why = reasons && score ? score.reasons.slice(0, 3).map(r => `<span class="chip reason ${esc(r.type)}">${esc(reasonText(r))}</span>`).join('') : forYouChip(p);
    return `<article class="row${fresh ? ' is-new' : ''}">${fresh ? '<span class="new-dot" title="New since your last visit"></span>' : ''}<a class="paper-title" data-paper="${esc(p.id)}" href="${esc(url(location.pathname, {...args, paper: p.id}))}">${esc(p.title)}</a><div class="row-meta"><span class="byline">${shortByline(p)}</span>${journal ? `<span class="abbr" title="${esc(p.journal)}">${esc(abbr(p.journal_id))}</span>` : ''}<span>${esc(shortDate(p.publication_date, p.date_precision))}</span>${why}${kbChip(p)}</div></article>`;
  }
  const stageHeading = p => p.publication_status === 'issue_assigned' ? `${p.volume_series ? p.volume_series + ' series · ' : ''}Vol. ${p.volume}${p.issue ? ' · Issue ' + p.issue : ''}` : p.publication_status === 'online_first' ? 'Online first' : 'Issue details unavailable';
  function bindPapers(node) {
    node.querySelectorAll('[data-paper]').forEach(a => a.onclick = event => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); go({...read(), paper: a.dataset.paper}, false, true); });
  }
  function papers(id, items, args, {issues = false} = {}) {
    const node = $(id); node.classList.remove('empty');
    if (!items.length) { node.innerHTML = '<div class="empty">No entries in this selection. Try a wider period or different search.</div>'; return; }
    const rows = page === 'home' && compact();
    let previous;
    node.innerHTML = items.map(p => {
      // Within a journal, consecutive papers from one issue sit under a single heading.
      const heading = issues ? stageHeading(p) : null, head = heading && heading !== previous ? `<h3 class="sub-head">${esc(heading)}</h3>` : '';
      previous = heading;
      return head + (rows ? rowHtml(p, args, {journal: !issues}) : cardHtml(p, args));
    }).join('');
    bindPapers(node);
  }
  function dateControls(id) {
    const root = $(id);
    root.innerHTML = `<label>Publication period<select data-period><option value="all">All years</option><option value="custom">Custom dates</option><option value="quarter">Previous calendar quarter</option><option value="year">This year</option><option value="rolling">Rolling window</option><option value="calendar">Calendar window</option></select></label><label data-calendar hidden>Starting year<input data-year type="number" min="100" max="9998" value="${CairnPeriods.today().slice(0, 4)}"></label><label data-calendar hidden>Starting quarter<select data-quarter><option>1</option><option>2</option><option>3</option><option>4</option></select></label><label data-window hidden>Length<input data-length type="number" min="1" max="1000" value="1"></label><label data-window hidden>Unit<select data-unit><option value="year">Years</option><option value="quarter">Quarters</option></select></label><label data-through hidden>Through<input data-anchor type="date" value="${CairnPeriods.today()}"></label><label>From<input name="start_date" type="date"></label><label>Through<input name="end_date" type="date"></label>`;
    const get = selector => root.querySelector(selector);
    function mode() {
      const value = get('[data-period]').value;
      root.querySelectorAll('[data-calendar]').forEach(e => e.hidden = value !== 'calendar');
      root.querySelectorAll('[data-window]').forEach(e => e.hidden = !['calendar', 'rolling'].includes(value));
      get('[data-through]').hidden = value !== 'rolling';
      let range;
      if (value === 'all') range = {start_date: '', end_date: ''};
      if (value === 'quarter') range = CairnPeriods.lastQuarter();
      if (value === 'year') range = CairnPeriods.calendar(CairnPeriods.today().slice(0, 4), 'year');
      if (value === 'calendar') range = CairnPeriods.calendar(get('[data-year]').value, get('[data-unit]').value, get('[data-length]').value, get('[data-quarter]').value);
      if (value === 'rolling') range = CairnPeriods.rolling(get('[data-length]').value, get('[data-unit]').value, get('[data-anchor]').value);
      if (range) for (const field of ['start_date', 'end_date']) get(`[name=${field}]`).value = range[field];
    }
    root.querySelectorAll('[data-period], [data-year], [data-quarter], [data-length], [data-unit], [data-anchor]').forEach(e => e.onchange = () => { try { mode(); } catch (e) { fail(e); } });
    root.querySelectorAll('input[name]').forEach(e => e.onchange = () => { get('[data-period]').value = 'custom'; mode(); });
  }
  function restoreForm(id, args) {
    const form = $(id);
    form.querySelectorAll('[name]').forEach(e => {
      if (e.type === 'checkbox') e.checked = args[e.name] === '1';
      else e.value = args[e.name] || (e.name === 'basis' ? 'issue' : e.name === 'stage' ? 'all' : '');
    });
    form.querySelectorAll('[data-period]').forEach(e => e.value = args.start_date || args.end_date ? 'custom' : 'all');
    form.querySelectorAll('[data-calendar], [data-window], [data-through]').forEach(e => e.hidden = true);
  }
  function formArgs(id) {
    const args = Object.fromEntries(new FormData($(id)));
    CairnPeriods.range(args.start_date, args.end_date);
    return args;
  }
  async function issues(args, v) {
    const request = ++issueVersion;
    const node = $('issue');
    if (!args.journal || ['online_first', 'pending', 'unassigned'].includes(args.stage)) {
      node.innerHTML = '<option value="">' + (!args.journal ? 'Choose a journal first' : 'No complete issue assignment') + '</option>'; node.disabled = true; return;
    }
    node.disabled = false;
    const year = args.start_date && args.end_date && args.start_date.slice(0, 4) === args.end_date.slice(0, 4) ? args.start_date.slice(0, 4) : '';
    const result = await api('issues', {journal: args.journal, year});
    if (v !== version || request !== issueVersion) return;
    node.innerHTML = '<option value="">All volumes / issues</option>' + result.items.map(i => `<option value="${esc(i.id)}">${esc(i.date || i.year || '')} · ${i.volume_series ? esc(i.volume_series) + ' series · ' : ''}${esc(i.volume)}${i.issue ? '(' + esc(i.issue) + ')' : ''} · ${num(i.entry_count)} entries</option>`).join('');
    node.value = args.issue || '';
  }
  function homeRange(args) {
    const window = args.window || stored('cairn-home-window') || '3', today = CairnPeriods.today();
    let range;
    if (window === 'custom') {
      const start = args.start_date || stored('cairn-home-start'), end = args.end_date || stored('cairn-home-end');
      range = start && end ? CairnPeriods.range(start, end) : CairnPeriods.rolling(1, 'quarter');
    } else if (window === 'quarter') range = CairnPeriods.lastQuarter();
    else range = CairnPeriods.range(CairnPeriods.addDays(CairnPeriods.shift(today, -Number(['1', '3', '6', '12'].includes(window) ? window : '3')), 1), today);
    return {window, ...range};
  }
  const desktopJournals = matchMedia('(min-width: 1000px)');
  let homeCache, homeDrawKey, journalFrame, controlsHeight = 0, journalNavigationHeight = 0;
  function updateStickyLayout() {
    if (page !== 'home') return;
    controlsHeight = Math.ceil($('catalogChrome').getBoundingClientRect().height);
    journalNavigationHeight = !desktopJournals.matches && !$('journalIndex').hidden ? Math.ceil($('journalSummary').getBoundingClientRect().height) + 2 : 0;
    document.documentElement.style.setProperty('--catalog-controls-height', controlsHeight + 'px');
    document.documentElement.style.setProperty('--journal-navigation-height', journalNavigationHeight + 'px');
    trackJournal();
  }
  function refreshHomeLinks() {
    const args = read();
    $('journalNav').querySelectorAll('[data-journal-link]').forEach(a => a.href = url(location.pathname, {...args, paper: '', section: a.dataset.journalLink}));
    $('homeList').querySelectorAll('[data-paper]').forEach(a => a.href = url(location.pathname, {...args, paper: a.dataset.paper}));
  }
  function trackJournal() {
    if (page !== 'home' || journalFrame) return;
    journalFrame = requestAnimationFrame(() => {
      journalFrame = null;
      const sections = [...$('homeList').querySelectorAll('[data-journal-section]')];
      if (!sections.length) return;
      let current = sections[0].dataset.journalSection;
      for (const section of sections) {
        if (section.getBoundingClientRect().top > controlsHeight + journalNavigationHeight + 40) break;
        current = section.dataset.journalSection;
      }
      $('journalNav').querySelectorAll('[data-journal-link]').forEach(a => {
        if (a.dataset.journalLink === current) a.setAttribute('aria-current', 'location');
        else a.removeAttribute('aria-current');
      });
    });
  }
  function journalTarget(id) {
    return config.meta.journals.some(j => j.id === id) ? $('journal-' + id) : null;
  }
  function jumpToJournal(id) {
    const heading = journalTarget(id);
    if (!heading) return;
    history.replaceState({...history.state, scrollY: window.scrollY}, '', location.href);
    const args = {...read(), section: id};
    history.pushState({sectionNavigation: true}, '', url(location.pathname, args));
    if (!desktopJournals.matches) $('journalDisclosure').open = false;
    updateStickyLayout();
    rememberNavigation(args); refreshHomeLinks();
    heading.focus({preventScroll: true});
    heading.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    trackJournal();
  }
  function restorePosition() {
    updateStickyLayout();
    const heading = page === 'home' ? journalTarget(read().section) : null;
    if (heading && !read().paper && (history.state?.sectionNavigation || history.state?.scrollY == null)) heading.focus({preventScroll: true});
    if (history.state?.scrollY != null) window.scrollTo(0, history.state.scrollY);
    else if (heading) heading.scrollIntoView({block: 'start', behavior: 'instant'});
    else window.scrollTo(0, 0);
    trackJournal();
  }
  function journalSections(groups, args, rebuild) {
    if (rebuild) {
      const issueLink = i => `<a href="${esc(url('search.html', {journal: i.journal_id, issue: i.issue_id}))}">${i.volume_series ? esc(i.volume_series) + ' · ' : ''}${esc(i.volume)}${i.issue ? '(' + esc(i.issue) + ')' : ''} · ${num(i.total)}</a>`;
      $('homeList').innerHTML = groups.map(g => `<section class="journal-section" data-journal-section="${esc(g.journal_id)}" aria-labelledby="journal-${esc(g.journal_id)}"><div class="journal-heading"><h2 id="journal-${esc(g.journal_id)}" tabindex="-1">${esc(g.journal)}</h2><p>${num(g.total)} publications${g.new_total ? ` · <span class="new-count">${num(g.new_total)} new</span>` : ''}</p>${g.issues?.length ? `<p class="issue-chips"><span>Issues in this window</span>${g.issues.slice(0, 6).map(issueLink).join('')}</p>` : ''}</div><div id="journal-list-${esc(g.journal_id)}"></div><div id="journal-pager-${esc(g.journal_id)}" class="pager" role="group" aria-label="${esc(g.journal)} pagination"></div></section>`).join('');
      $('journalSummary').textContent = `Journals (${groups.length})`;
      $('journalDisclosure').open = desktopJournals.matches;
      $('journalNav').innerHTML = groups.map(g => `<a data-journal-link="${esc(g.journal_id)}"><span>${esc(g.journal)}${g.new_total ? ' <span class="new-dot inline" title="New since your last visit"></span>' : ''}</span><span class="journal-count" aria-label="${num(g.total)} publications">${num(g.total)}</span></a>`).join('');
      $('journalNav').querySelectorAll('a').forEach(a => a.onclick = event => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault(); jumpToJournal(a.dataset.journalLink);
      });
    }
    for (const g of groups) {
      const id = g.journal_id, list = $('journal-list-' + id);
      if (!rebuild && list.dataset.offset === String(g.offset)) continue;
      papers(list.id, g.items, args, {issues: true}); list.dataset.offset = g.offset;
      const node = $('journal-pager-' + id); node.replaceChildren();
      if (g.total <= 10) continue;
      for (const [label, offset, disabled] of [['Previous', Math.max(0, g.offset - 10), !g.offset], ['Next', g.offset + 10, g.offset + 10 >= g.total]]) {
        const button = document.createElement('button'); button.textContent = label; button.disabled = disabled;
        button.id = `journal-${id}-${label.toLowerCase()}`;
        button.onclick = () => go({...read(), ['offset_' + id]: offset || '', paper: ''}, false, true, offset === 0 || offset + 10 >= g.total ? 'journal-' + id : button.id);
        node.append(button);
      }
      const count = document.createElement('span'); count.setAttribute('role', 'status');
      count.textContent = `${num(g.offset + 1)}–${num(Math.min(g.total, g.offset + 10))} of ${num(g.total)}`; node.append(count);
    }
  }
  // The front page links into a field; a journal section implies its field.
  const homeField = args => fieldById.has(args.field) ? args.field : journalById.get(args.section)?.field || '';
  const homeBase = args => ({window: args.window, ...(args.window === 'custom' ? {start_date: args.start_date, end_date: args.end_date} : {}), new: args.new});
  function forYouRows(range, args, field) {
    if (!personal) return [];
    const seen = seenDates();
    return personal.for_you.map(id => personal.papers[id]).filter(p => p && p.first_lower >= range.start_date && p.first_upper <= range.end_date
      && paperTier(p) !== 'mute' && (!field || fieldOf(p) === field) && (args.new !== '1' || isNew(p, seen)));
  }
  function personalNotices() {
    if (!personal) return `<p class="notice">Set up this list by running <code>cairn-catalog personalize</code>, then reload. Your Cairn topics are included automatically; keywords, people and institutions can then be added here and on the Authors and Institutions pages through the catalog app.</p>`;
    const notes = [];
    if (personal.snapshot !== config.meta.snapshot_date) notes.push(`Matches were computed for the ${esc(dateLabel(personal.snapshot))} snapshot; run <code>cairn-catalog personalize</code> to refresh them.`);
    if (!personal.preferences) notes.push('Run <code>cairn-catalog personalize</code> once to enable editing keywords and topics here.');
    const choose = [...personal.people, ...personal.institutions].filter(f => ['needs_choice', 'not_found'].includes(f.status));
    if (choose.length) notes.push(`${choose.map(f => esc(f.label)).join(', ')} ${choose.length === 1 ? 'needs' : 'need'} attention: <a href="authors.html">see Following on the Authors page</a>.`);
    return notes.map(n => `<p class="notice">${n}</p>`).join('');
  }
  // The topics and keywords behind "For you", editable in place through the catalog app.
  let settingsOpen = false;
  function forYouSettings() {
    if (!personal?.preferences) return '';
    const topics = personal.topics.filter(t => t && typeof t === 'object'), used = topics.filter(t => t.status === 'used').length;
    const keywords = personal.preferences.keywords, matches = new Map(personal.terms.filter(t => t.type === 'keyword').map(t => [t.label, t.matches]));
    const status = {used: 'In use', excluded: 'Excluded', broad: 'Broad topic: has narrower topics, so skipped', off: 'Cairn topics are turned off'};
    const keywordHtml = keywords.length ? `<div class="keyword-list">${keywords.map(k => `<span class="chip">${esc(k)} <span title="Papers matched in the past 12 months">${num(matches.get(k) ?? 0)}</span><button type="button" class="link" aria-label="Remove keyword ${esc(k)}" title="Remove" ${saveAttr({action: 'keyword_remove', text: k}, `Removed “${k}”`)}>×</button></span>`).join('')}</div>` : '<p class="muted">No keywords yet.</p>';
    const addKeyword = `<form class="add-form" data-save-form="${esc(JSON.stringify({action: 'keyword_add'}))}" data-key="text"><label>Add a keyword or phrase<input name="value" required maxlength="200" placeholder="e.g. causal inference" ${editable ? '' : 'disabled'}></label><button ${editable ? '' : 'disabled'}>Add</button></form>`;
    const rows = topics.map(t => `<tr class="${t.status === 'used' ? '' : 'off'}"><td><strong>${esc(t.title)}</strong>${t.broader.length ? `<div class="aliases">Under ${esc(t.broader.map(b => topics.find(x => x.slug === b)?.title || b).join(', '))}</div>` : ''}</td><td class="aliases">${esc(t.aliases.join(', ') || '—')}</td><td class="n">${num(t.matches)}</td><td>${esc(status[t.status] || t.status)}</td><td><label class="check" title="Use this topic in For you"><input type="checkbox" ${t.status === 'used' ? 'checked' : ''} ${personal.preferences.cairn_topics ? '' : 'disabled'} data-toggle="${esc(JSON.stringify({action: 'topic', slug: t.slug}))}" data-key="include" ${editable ? '' : 'disabled'} aria-label="Use ${esc(t.title)} in For you"></label></td></tr>`).join('');
    const topicsHtml = `<label class="check"><input type="checkbox" ${personal.preferences.cairn_topics ? 'checked' : ''} data-toggle="${esc(JSON.stringify({action: 'cairn_topics'}))}" data-key="value" ${editable ? '' : 'disabled'}>Use my Cairn topics (titles and aliases of the notes in <code>research/topics</code>)</label>${topics.length ? `<table class="topics-table"><thead><tr><th>Topic</th><th>Also matches</th><th class="n">Papers, past 12 months</th><th>Status</th><th>Use</th></tr></thead><tbody>${rows}</tbody></table><p class="edit-hint">Matches count papers whose title or abstract contains the topic name or an alias of four or more characters; excluded and broad topics show what they would add.</p>` : '<p class="muted">No Cairn topic notes found.</p>'}`;
    return `<details class="settings" id="forYouSettings" ${settingsOpen ? 'open' : ''}><summary>Keywords &amp; topics · ${num(keywords.length)} ${keywords.length === 1 ? 'keyword' : 'keywords'} · ${num(used)} of ${num(topics.length)} Cairn topics in use</summary>${editable ? '' : `<p class="notice">${appHint()}</p>`}<h3>Keywords</h3>${keywordHtml}${addKeyword}<h3>Cairn topics (${num(topics.length)})</h3>${topicsHtml}</details>`;
  }
  function frontPage(result, args, range) {
    const base = homeBase(args), fieldUrl = (field, section) => url(location.pathname, {...base, field, section});
    const mine = forYouRows(range, args), shown = args.foryou === 'all' ? mine : mine.slice(0, 8);
    const sources = personal ? [...new Set(personal.terms.filter(t => t.matches).map(t => t.label))] : [];
    $('forYou').innerHTML = `<div class="lane-head"><h2 id="forYouTitle">For you</h2><p class="muted">${personal ? `${num(mine.length)} ${mine.length === 1 ? 'match' : 'matches'} in this window${sources.length ? ' · ' + esc(sources.slice(0, 6).join(', ')) + (sources.length > 6 ? '…' : '') : ''}${personal.people.length || personal.institutions.length ? ' · followed people and institutions' : ''}` : ''}</p></div>${shown.length ? `<div class="rows">${shown.map(p => rowHtml(p, args, {reasons: true})).join('')}</div>` : personal ? '<p class="muted">Nothing in this window matches your topics, keywords or follows.</p>' : ''}${mine.length > 8 ? `<p><a id="forYouMore" href="${esc(url(location.pathname, {...read(), foryou: args.foryou === 'all' ? '' : 'all', paper: ''}))}">${args.foryou === 'all' ? 'Show fewer' : `Show all ${num(mine.length)}`}</a></p>` : ''}${personalNotices()}${forYouSettings()}`;
    const tile = f => {
      const tier = tierOf(f.field), core = tier === 'core', seen = new Set();
      const items = [...forYouRows(range, args, f.field).slice(0, core ? 2 : 1), ...f.items].filter(p => !seen.has(p.id) && seen.add(p.id)).slice(0, core ? 5 : 2);
      const issues = f.issues.slice(0, core ? 4 : 2).map(i => `<a href="${esc(fieldUrl(f.field, i.journal_id))}">${esc(abbr(i.journal_id))} ${i.volume_series ? esc(i.volume_series) + ' · ' : ''}${esc(i.volume)}${i.issue ? '(' + esc(i.issue) + ')' : ''} · ${num(i.total)}</a>`).join('');
      return `<section class="tile ${tier}" aria-labelledby="tile-${esc(f.field)}"><header><h2 id="tile-${esc(f.field)}"><a href="${esc(fieldUrl(f.field))}">${esc(f.label)}</a></h2><p class="tile-stats"><strong>${num(f.total)}</strong> ${f.total === 1 ? 'paper' : 'papers'}${f.new_total ? ` · <span class="new-count">${num(f.new_total)} new</span>` : ''}</p></header>${issues ? `<p class="issue-chips"><span>New issues</span>${issues}</p>` : ''}${items.length ? `<div class="rows">${items.map(p => rowHtml(p, args)).join('')}</div>` : '<p class="muted">Nothing in this window.</p>'}<footer class="tile-journals">${f.journals.map(j => `<a href="${esc(fieldUrl(f.field, j.journal_id))}" title="${esc(j.journal)}">${esc(j.abbreviation || j.journal)} <span>${num(j.total)}</span>${j.new_total ? '<span class="new-dot inline" title="New since your last visit"></span>' : ''}</a>`).join('')}</footer></section>`;
    };
    const byTier = tier => result.fields.filter(f => tierOf(f.field) === tier);
    $('coreTiles').innerHTML = byTier('core').map(tile).join('');
    $('skimTiles').innerHTML = byTier('skim').length ? `<h2 class="tier-title">Skim</h2><div class="tiles-grid">${byTier('skim').map(tile).join('')}</div>` : '';
    const muted = byTier('mute');
    $('mutedFields').innerHTML = muted.length ? `Muted in your preferences: ${muted.map(f => `<a href="${esc(fieldUrl(f.field))}">${esc(f.label)} (${num(f.total)})</a>`).join(', ')}` : '';
    for (const id of ['forYou', 'coreTiles', 'skimTiles']) bindPapers($(id));
  }
  async function risingTerms(field, range, v) {
    const node = $('risingTerms'); if (!node) return;
    const insights = await api('insights'); if (v !== version) return;
    const months = (new Date(range.end_date) - new Date(range.start_date)) / 2629746000, key = months <= 4 ? '3m' : '12m';
    const terms = insights.fields[field]?.[key]?.rising_terms || [], period = insights.periods[key];
    node.innerHTML = terms.length ? `<span class="terms-label" title="Title words and phrases over-represented in ${esc(dateLabel(period.start))} – ${esc(dateLabel(period.end))} compared with the twelve months before">Rising in titles, past ${key === '3m' ? '3 months' : 'year'}</span>${terms.map(t => `<a class="chip" href="${esc(url('search.html', {query: '"' + t.term + '"', start_date: period.start, end_date: period.end, basis: 'first'}))}" title="${num(t.count)} papers now; ${num(t.baseline)} in the twelve months before">${esc(t.term)} <span>${num(t.count)}</span></a>`).join('')}` : '';
  }
  async function home(args, v) {
    const range = homeRange(args); $('homeWindow').value = range.window;
    $('homeDates').hidden = range.window !== 'custom'; $('homeStart').value = range.start_date; $('homeEnd').value = range.end_date;
    $('homeRange').textContent = `${dateLabel(range.start_date)} – ${dateLabel(range.end_date)}`;
    const age = (new Date(CairnPeriods.today()) - new Date(config.meta.snapshot_date)) / 86400000;
    $('snapshot').textContent = `Metadata updated ${dateLabel(config.meta.snapshot_date)}${age > 7 ? ' · This snapshot is more than a week old; newer publications may be missing.' : ''}`;
    $('snapshot').classList.toggle('stale', age > 7);
    const field = homeField(args), label = fieldById.get(field)?.label, seen = seenDates();
    $('frontPage').hidden = !!field; $('fieldPage').hidden = !field; $('crumbs').hidden = !field;
    $('allFields').href = url(location.pathname, homeBase(args));
    $('homeTitle').textContent = field ? label : 'What’s New';
    $('newOnly').setAttribute('aria-pressed', String(args.new === '1'));
    $('density').setAttribute('aria-pressed', String(compact()));
    $('markSeen').textContent = field ? `Mark ${label} caught up` : 'Mark all caught up';
    updateStickyLayout();
    let uncertain = 0;
    const common = {...range, seen: JSON.stringify(seen), new_only: args.new === '1' ? '1' : ''};
    if (!field) {
      const result = await api('recent', {...common, group_by: 'field'});
      if (v !== version) return;
      homeDrawKey = null; $('homeLayout').dataset.layout = ''; uncertain = result.uncertain_count;
      const fresh = result.fields.reduce((n, f) => n + (tierOf(f.field) === 'mute' ? 0 : f.new_total), 0);
      $('homeCount').textContent = args.new === '1' ? `${num(result.total)} new since your last visit` : `${num(result.total)} recent publications${fresh ? ` · ${num(fresh)} new since your last visit` : ''}`;
      frontPage(result, args, range);
    } else {
      const offsets = {};
      for (const j of config.meta.journals) {
        const offset = Number(args['offset_' + j.id]);
        if (Number.isSafeInteger(offset) && offset > 0) offsets[j.id] = offset;
      }
      const request = {...common, group_by: 'journal', field, journal_offsets: JSON.stringify(offsets)};
      const key = JSON.stringify([request, compact()]);
      const result = homeCache?.key === key ? homeCache.result : await api('recent', request);
      if (v !== version) return;
      homeCache = {key, result}; uncertain = result.uncertain_count;
      const fresh = result.groups.reduce((n, g) => n + g.new_total, 0);
      $('homeCount').textContent = `${num(result.total)} ${label} publications${fresh && args.new !== '1' ? ` · ${num(fresh)} new since your last visit` : args.new === '1' ? ' new since your last visit' : ''}`;
      if (homeDrawKey !== key) {
        const layoutKey = JSON.stringify([range.start_date, range.end_date, field, args.new, compact()]);
        const rebuild = $('homeLayout').dataset.layout !== layoutKey;
        if (rebuild) $('fieldHead').innerHTML = `<p class="muted">${num(result.groups.length)} ${result.groups.length === 1 ? 'journal' : 'journals'} · ${editable ? `<label class="tier-select">Show as<select data-tier="${esc(field)}">${['core', 'skim', 'mute'].map(t => `<option value="${t}" ${tierOf(field) === t ? 'selected' : ''}>${{core: 'Core field', skim: 'Skim field', mute: 'Muted field'}[t]}</option>`).join('')}</select></label>` : `${esc(tierOf(field) === 'core' ? 'Core field' : tierOf(field) === 'skim' ? 'Skim field' : 'Muted field')} (set in your preferences)`}</p><div id="risingTerms" class="terms"></div>`;
        $('homeLayout').dataset.layout = layoutKey;
        $('homeLayout').classList.toggle('has-journals', result.total > 0);
        $('journalIndex').hidden = !result.total;
        if (result.total) journalSections(result.groups, args, rebuild);
        else papers('homeList', [], args);
        homeDrawKey = key;
        if (rebuild) risingTerms(field, range, v).catch(() => {});
      }
    }
    refreshHomeLinks(); updateStickyLayout();
    $('uncertainLink').innerHTML = uncertain ? `${num(uncertain)} additional entries have dates that overlap this window but cannot be placed confidently. <a href="${esc(url('search.html', {...range, window: '', basis: 'first', entry_type: 'article_or_other', include_uncertain: '1'}))}">Explore uncertain dates</a>` : '';
    $('noticesLink').href = url('search.html', {...range, window: '', basis: 'first', entry_type: 'correction_or_retraction'});
  }
  function hasSearch(args) { return !!(args.query?.trim() || args.journal || args.issue || args.start_date || args.end_date || args.entry_type || args.stage && args.stage !== 'all'); }
  async function search(args, v) {
    restoreForm('searchForm', args);
    $('searchAdvanced').open = !!(args.basis && args.basis !== 'issue' || args.stage && args.stage !== 'all' || args.entry_type || args.include_uncertain);
    await issues(args, v);
    if (v !== version) return;
    if (!hasSearch(args)) {
      $('searchList').classList.remove('empty');
      $('searchCount').textContent = ''; $('searchSort').textContent = ''; $('searchPager').replaceChildren();
      $('searchList').innerHTML = '<div class="empty">Search for a paper, or choose a journal or publication period.</div>'; return;
    }
    $('searchCount').textContent = 'Searching…';
    $('searchList').classList.remove('empty');
    $('searchList').innerHTML = '<p class="muted">Loading matching entries…</p>';
    const offset = Math.max(0, Number(args.offset) || 0), result = await api('papers', {...args, period: args.start_date || args.end_date ? 'range' : 'all', offset, limit: size});
    if (v !== version) return;
    if (offset && offset >= result.total) { go({...args, offset: 0}, true); return; }
    $('searchCount').textContent = `${num(result.total)} matching entries`; $('searchSort').textContent = 'Newest first';
    papers('searchList', result.items, args); pager('searchPager', result.total, offset, 'offset', args);
  }
  // Landing for Authors and Institutions: who you follow, then who is active in a field.
  const localFollows = () => storedJson('cairn-follow-local', []).filter(f => f && typeof f.id === 'string');
  const yamlFollow = f => `- name: ${f.name}\n  ids: [${f.id}]`;
  function followBlock(f, args) {
    const link = id => url(location.pathname, {entity: id});
    const rows = [...new Set([...f.papers, ...f.name_only])].map(id => personal.papers[id]).filter(Boolean)
      .sort((a, b) => (b.publication_date || '').localeCompare(a.publication_date || ''));
    const choose = c => editable ? ` <button type="button" class="small" ${saveAttr({action: 'choose', kind: page, label: f.label, id: c.id}, `Following ${c.name}`)}>Follow this one</button>` : '';
    let body = '';
    if (f.status === 'needs_choice') body = `<p class="notice uncertain">Several catalog identities share this name, so none is followed yet. Open each to check, then ${editable ? 'choose the right one (you can choose more than one)' : 'list the right one(s) in your preferences as <code>ids: [...]</code>'}.</p><ul class="candidates">${f.candidates.map(c => `<li><a href="${esc(link(c.id))}">${esc(c.name)}</a> · ${num(c.papers)} catalog entries${c.latest_journal ? ` · latest in ${esc(c.latest_journal)}${c.latest_date ? ' ' + esc(c.latest_date.slice(0, 4)) : ''}` : ''} · <code>${esc(c.id)}</code>${choose(c)}</li>`).join('')}</ul>`;
    else if (f.status === 'not_found') body = `<p class="notice uncertain">Not found in the catalog${f.missing_ids ? ` (${esc(f.missing_ids.join(', '))})` : ''}.${f.suggestions?.length ? ' Similar names:' : ''}</p>${f.suggestions?.length ? `<ul class="candidates">${f.suggestions.map(c => `<li><a href="${esc(link(c.id))}">${esc(c.name)}</a> · ${num(c.papers)} catalog entries${choose(c)}</li>`).join('')}</ul>` : ''}`;
    else body = `<p class="muted">${num(rows.length)} ${rows.length === 1 ? 'paper' : 'papers'} in the past 12 months${f.name_only.length ? ` · ${num(f.name_only.length)} matched by name only (unverified)` : ''}</p>${rows.length ? `<div class="rows">${rows.slice(0, 5).map(p => rowHtml(p, args)).join('')}</div>` : ''}${rows.length > 5 && f.ids.length ? `<p><a href="${esc(link(f.ids[0]))}">All publications</a></p>` : ''}`;
    const title = f.ids.length === 1 ? `<a href="${esc(link(f.ids[0]))}">${esc(f.label)}</a>` : esc(f.label);
    const remove = editable ? `<button type="button" class="small" ${saveAttr({action: 'unfollow', kind: page, label: f.label}, `Unfollowed ${f.label}`)}>Unfollow</button>` : '';
    return `<article class="follow"><h3>${title}${remove}</h3>${body}</article>`;
  }
  function insightControls(args, field, period) {
    const tabs = fieldList.filter(f => tierOf(f.id) !== 'mute').sort((a, b) => (tierOf(a.id) === 'core' ? 0 : 1) - (tierOf(b.id) === 'core' ? 0 : 1));
    const link = extra => url(location.pathname, {...args, ...extra, paper: ''});
    return `<div class="tabs" role="group" aria-label="Field">${tabs.map(f => `<a href="${esc(link({ins_field: f.id}))}" ${f.id === field ? 'aria-current="true"' : ''}>${esc(f.label)}</a>`).join('')}</div><div class="tabs period" role="group" aria-label="Period">${[['3m', 'Past 3 months'], ['12m', 'Past year']].map(([k, label]) => `<a href="${esc(link({ins_period: k}))}" ${k === period ? 'aria-current="true"' : ''}>${label}</a>`).join('')}</div>`;
  }
  function insightPanel(insights, args) {
    const field = fieldById.has(args.ins_field) ? args.ins_field : (fieldList.find(f => tierOf(f.id) === 'core') || fieldList[0]).id;
    const period = args.ins_period === '12m' ? '12m' : '3m', data = insights.fields[field]?.[period], range = insights.periods[period];
    const paper = id => { const p = insights.papers[id]; return p ? `<a data-paper="${esc(id)}" href="${esc(url(location.pathname, {...args, paper: id}))}">${esc(p.title)}</a> <span class="abbr">${esc(abbr(p.journal_id))}</span>` : ''; };
    const entity = (id, name) => `<a href="${esc(url(location.pathname, {entity: id}))}">${esc(name)}</a>`;
    const head = `<p class="muted">${esc(fieldById.get(field).label)} · ${esc(dateLabel(range.start))} – ${esc(dateLabel(range.end))} · ${num(data.papers)} papers (${num(data.previous_papers)} in the period before)</p>`;
    if (page === 'author') {
      const quarters = Array.from({length: 8}, (_, i) => { const end = CairnPeriods.shift(insights.as_of, -3 * (7 - i)); return `${dateLabel(CairnPeriods.addDays(CairnPeriods.shift(end, -3), 1))} – ${dateLabel(end)}`; });
      const active = data.active_authors.length ? `<table class="board"><thead><tr><th>Author</th><th class="n">Papers</th><th>Last 2 years</th><th>Journals</th><th>Latest</th></tr></thead><tbody>${data.active_authors.map(a => `<tr><td>${entity(a.id, a.name)}</td><td class="n">${num(a.count)}</td><td>${bars(a.spark, quarters, `${a.name}: papers per quarter over two years`)}</td><td>${a.journals.map(([j, n]) => `<span class="abbr">${esc(abbr(j))}${n > 1 ? ' ×' + n : ''}</span>`).join(' ')}</td><td class="latest">${paper(a.latest)}</td></tr>`).join('')}</tbody></table>` : '<p class="muted">No identified author has two or more papers in this field and period.</p>';
      const fresh = data.new_authors.length ? `<ul class="newcomers">${data.new_authors.map(a => `<li>${entity(a.id, a.name)} <span class="muted">· ${esc(dateLabel(a.first))}${a.papers > 1 ? ` · ${num(a.papers)} papers` : ''}${a.coauthors ? ` · with ${num(a.coauthors)} coauthor${a.coauthors === 1 ? '' : 's'}` : ' · solo'}</span><br>${paper(a.paper)}</li>`).join('')}</ul>` : '<p class="muted">No first appearances in this period.</p>';
      return `${head}<h3>Most active</h3>${active}<h3>New names</h3><p class="notice">First paper in these catalog journals during the period (source-identified authors; a split identity can make an established author look new).</p>${fresh}`;
    }
    const change = i => i.previous ? (i.count - i.previous > 0 ? `<span class="up">+${num(i.count - i.previous)}</span>` : i.count === i.previous ? '<span class="muted">±0</span>' : `<span class="down">−${num(i.previous - i.count)}</span>`) : '<span class="up">new</span>';
    const board = data.institutions.length ? `<table class="board"><thead><tr><th>Institution</th><th class="n">Papers</th><th class="n">vs. before</th></tr></thead><tbody>${data.institutions.map(i => `<tr><td>${entity(i.id, i.name)}</td><td class="n">${num(i.count)}</td><td class="n">${change(i)}</td></tr>`).join('')}</tbody></table>` : '<p class="muted">No identified affiliations in this field and period.</p>';
    return `${head}<h3>Most papers</h3>${board}<p class="notice">Counts papers with at least one author affiliated with the institution, as recorded on the paper. Affiliations are recorded for ${data.affiliation_coverage == null ? 'none' : Math.round(data.affiliation_coverage * 100) + '%'} of this field's papers in the period.</p>`;
  }
  async function entityLanding(args, v) {
    const node = $('entityLanding'), follows = (page === 'author' ? personal?.people : personal?.institutions) || [], local = page === 'author' ? localFollows() : [];
    const configured = new Set(follows.flatMap(f => f.ids)), extra = local.filter(f => !configured.has(f.id));
    const kindLabel = page === 'author' ? 'people' : 'institutions';
    const localHtml = f => `<article class="follow" data-local="${esc(f.id)}"><h3><a href="${esc(url(location.pathname, {entity: f.id}))}">${esc(f.name)}</a>${editable ? `<button type="button" class="small primary" ${saveAttr({action: 'follow', kind: 'author', name: f.name, id: f.id}, `Following ${f.name}`)}>Save to your preferences</button>` : ''} <button type="button" class="small" data-unfollow="${esc(f.id)}">Unfollow</button></h3><p class="notice">Followed in this browser only${editable ? '; save it to include in For you.' : `. Add to <code>people:</code> in your preferences to include in For you:</p><pre>${esc(yamlFollow(f))}</pre><p class="notice">`}</p><div class="rows" data-local-rows></div></article>`;
    const followHtml = follows.length || extra.length ? follows.map(f => followBlock(f, args)).join('') + extra.map(localHtml).join('')
      : `<p class="muted">You are not following any ${kindLabel} yet.</p>`;
    const add = editable ? `<form class="add-form" data-save-form="${esc(JSON.stringify({action: 'follow', kind: page}))}" data-key="name"><label>Follow ${page === 'author' ? 'a person' : 'an institution'} by name<input name="value" required maxlength="200" placeholder="${page === 'author' ? 'e.g. Daron Acemoglu' : 'e.g. Washington University in St. Louis'}"></label><button>Follow</button></form><p class="edit-hint">If several catalog identities share the name, you will be asked to choose. You can also open any ${page === 'author' ? 'author' : 'institution'} and press Follow. Changes are saved to your preferences.</p>`
      : `<p class="notice">${appHint()}${page === 'author' ? ' Without the app, Follow on an author’s page remembers them in this browser only.' : ''}</p>`;
    node.innerHTML = `<section class="following" aria-labelledby="followingTitle"><h2 id="followingTitle">Following${follows.length + extra.length ? ` <span class="muted">(${num(follows.length + extra.length)})</span>` : ''}</h2>${followHtml}${add}</section><section class="insights" aria-labelledby="insightsTitle"><h2 id="insightsTitle">${page === 'author' ? 'Who’s active' : 'Institutions by field'}</h2><div id="insightsPanel"><p class="muted">Loading…</p></div></section>`;
    node.querySelectorAll('[data-unfollow]').forEach(b => b.onclick = () => { stored('cairn-follow-local', JSON.stringify(localFollows().filter(f => f.id !== b.dataset.unfollow))); render().catch(fail); });
    bindPapers(node);
    const end = config.meta.snapshot_date, start = CairnPeriods.addDays(CairnPeriods.shift(end, -12), 1);
    await Promise.all(extra.map(async f => {
      const pubs = await api('publications', {kind: 'author', entity: f.id, period: 'range', start_date: start, end_date: end, basis: 'issue', limit: 5});
      if (v !== version) return;
      const target = node.querySelector(`[data-local="${CSS.escape(f.id)}"] [data-local-rows]`);
      if (target) { target.innerHTML = pubs.items.length ? pubs.items.map(p => rowHtml(p, args)).join('') : '<p class="muted">No papers in the past 12 months.</p>'; bindPapers(target); }
    }).map(job => job.catch(() => {})));
    const insights = await api('insights'); if (v !== version) return;
    $('insightsPanel').innerHTML = insightControls(args, fieldById.has(args.ins_field) ? args.ins_field : (fieldList.find(f => tierOf(f.id) === 'core') || fieldList[0]).id, args.ins_period === '12m' ? '12m' : '3m') + insightPanel(insights, args);
    bindPapers($('insightsPanel'));
  }
  function profileSummary(e, profile) {
    const last = Number(config.meta.snapshot_date.slice(0, 4)), known = Object.keys(profile.years).map(Number);
    const first = Math.max(Math.min(last, ...known), last - 24), years = Array.from({length: last - first + 1}, (_, i) => first + i);
    const perYear = years.map(y => profile.years[y] || 0), total = profile.journals.reduce((n, [, c]) => n + c, 0);
    const fields = new Map();
    for (const [j, n] of profile.journals) { const f = journalById.get(j)?.field; fields.set(f, (fields.get(f) || 0) + n); }
    const blocks = [`<div><h3>Papers per year</h3>${bars(perYear, years.map(String), `${e.display_name}: catalog papers per year, ${first}–${last}`, Math.min(300, years.length * 12), 32)}<p class="muted">${first}–${last}${known.some(y => y < first) ? ' (earlier years omitted)' : ''}</p></div>`,
      `<div><h3>Journals</h3><p>${profile.journals.slice(0, 6).map(([j, n]) => `<span class="abbr" title="${esc(journalById.get(j)?.title || j)}">${esc(abbr(j))}</span> ${num(n)}`).join(' · ')}${profile.journals.length > 6 ? ' · …' : ''}</p>${page === 'institution' ? `<p class="muted">${[...fields].sort((a, b) => b[1] - a[1]).map(([f, n]) => `${esc(fieldById.get(f)?.label || f)} ${Math.round(n / Math.max(1, total) * 100)}%`).join(' · ')}</p>` : ''}</div>`];
    if (profile.coauthors.length) blocks.push(`<div><h3>Frequent coauthors</h3><p>${profile.coauthors.map(c => `<a href="${esc(url(location.pathname, {entity: c.id}))}">${esc(c.name)}</a> <span class="muted">${num(c.papers)}</span>`).join(' · ')}</p></div>`);
    return blocks.join('');
  }
  function followControl(e) {
    if (e.identity_status === 'unresolved_credit') return '';
    const followed = (page === 'author' ? personal?.people : personal?.institutions)?.find(f => f.ids.includes(e.id));
    if (editable) return `<p class="follow-control">${followed ? `<button type="button" aria-pressed="true" ${saveAttr({action: 'unfollow', kind: page, id: e.id, label: followed.label}, `Unfollowed ${e.display_name}`)}>Following · Unfollow</button>` : `<button type="button" class="primary" aria-pressed="false" ${saveAttr({action: 'follow', kind: page, name: e.display_name, id: e.id}, `Following ${e.display_name}`)}>Follow</button>`} <span class="muted">Saved in your preferences; followed ${page === 'author' ? 'people' : 'institutions'} appear in For you.</span></p>`;
    if (followed) return '<p class="muted">Following (your preferences)</p>';
    if (page !== 'author') return '';
    const local = localFollows().some(f => f.id === e.id);
    return `<p class="follow-control"><button type="button" id="followButton" aria-pressed="${local}">${local ? 'Following' : 'Follow'}</button>${local ? ' <span class="muted">In this browser. To include in For you, add to <code>people:</code> in your preferences:</span>' : ''}</p>${local ? `<pre>${esc(yamlFollow({id: e.id, name: e.display_name}))}</pre>` : ''}`;
  }
  async function entities(args, v) {
    $('entitySearch').value = args.query || '';
    // One column: the landing (following, who's active), search results, or a profile.
    const searching = !!args.query?.trim() && !args.entity, landing = !args.entity && !searching;
    $('entityResults').hidden = !searching;
    if (searching) {
      const offset = Math.max(0, Number(args.entity_offset) || 0);
      const result = await api('entities', {kind: page, query: args.query, offset, limit: 24});
      if (v !== version) return;
      $('entityCount').textContent = `${num(result.total)} matching ${page === 'author' ? 'identities' : 'institution identities / labels'}`;
      $('entityList').innerHTML = result.items.length ? result.items.map(e => `<a class="entity" data-entity="${esc(e.id)}" href="${esc(url(location.pathname, {query: args.query, entity: e.id}))}"><strong>${esc(e.display_name)}</strong><small>${num(e.publication_count)} catalog entries · ${esc(e.identity_status.replaceAll('_', ' '))}</small><small>${esc(e.id)}</small></a>`).join('') : '<p class="empty">No matching identities.</p>';
      pager('entityPager', result.total, offset, 'entity_offset', args, 24);
    }
    $('publicationForm').hidden = !args.entity;
    $('entityLanding').hidden = !landing; $('entityHead').hidden = !args.entity; $('entitySummary').hidden = true;
    if (!args.entity) {
      $('entityHead').className = 'empty'; $('entityHead').textContent = `Choose ${page === 'author' ? 'an author' : 'an institution'} to see publications.`;
      for (const id of ['publicationList', 'publicationCount', 'publicationPager']) $(id).replaceChildren();
      if (landing) await entityLanding(args, v);
      return;
    }
    restoreForm('publicationForm', args);
    $('entityHead').className = 'empty'; $('entityHead').textContent = 'Loading publications…';
    $('publicationCount').textContent = ''; $('publicationList').replaceChildren(); $('publicationPager').replaceChildren();
    const pubOffset = Math.max(0, Number(args.pub_offset) || 0), pubs = await api('publications', {...args, kind: page, period: args.start_date || args.end_date ? 'range' : 'all', offset: pubOffset, limit: size});
    if (v !== version) return;
    if (pubOffset && pubOffset >= pubs.total) { go({...args, pub_offset: 0}, true); return; }
    const e = pubs.entity;
    $('entityHead').className = 'entity-head';
    $('entityHead').innerHTML = `<h2>${esc(e.display_name)}</h2>${followControl(e)}<details class="identity"><summary>Identity &amp; period</summary><p class="identifier">${esc(e.id)}</p><p class="muted">${esc(pubs.period)}</p></details>${e.identity_status !== 'source_identified' ? '<p class="notice uncertain">Unresolved source identity; this is not a verified complete bibliography.</p>' : ''}${pubs.affiliation_note ? `<p class="notice">${esc(pubs.affiliation_note)}</p>` : ''}`;
    if ($('followButton')) $('followButton').onclick = () => {
      const list = localFollows(), following = list.some(f => f.id === e.id);
      stored('cairn-follow-local', JSON.stringify(following ? list.filter(f => f.id !== e.id) : [...list, {id: e.id, name: e.display_name}])); render().catch(fail);
    };
    if (pubs.profile) { $('entitySummary').innerHTML = profileSummary(e, pubs.profile); $('entitySummary').hidden = false; }
    $('publicationAdvanced').open = !!(args.basis && args.basis !== 'issue' || args.stage && args.stage !== 'all' || args.include_uncertain === '1');
    $('publicationCount').textContent = `${num(pubs.total)} displayed entries${pubs.uncertain_count ? ` · ${num(pubs.uncertain_count)} overlap this period with uncertain dates` : ''}${pubs.undated_publications_all_years ? ` · ${num(pubs.undated_publications_all_years)} entries have no date on this basis` : ''}`;
    papers('publicationList', pubs.items, args); pager('publicationPager', pubs.total, pubOffset, 'pub_offset', args);
  }
  async function detail(id) {
    const request = ++detailVersion;
    if (!id) { if ($('detail').open) $('detail').close(); return; }
    $('detailBody').innerHTML = '<h2 id="detailTitle">Loading paper…</h2>';
    if (!$('detail').open) $('detail').showModal();
    const p = await api('paper', {id}); if (request !== detailVersion) return;
    const membership = p.journal_membership;
    $('detailBody').innerHTML = `<p class="eyebrow">${esc(p.journal)}</p><h2 id="detailTitle">${esc(p.title)}</h2><div class="byline">${byline(p)}</div><p class="paper-meta">${stage(p)}</p><p class="muted">Online: ${esc(dateLabel(p.published_online))}<br>Print: ${esc(dateLabel(p.published_print))}<br>Publication (print preferred): ${esc(dateLabel(p.date, p.date_precision))}</p><div class="detail-links">${p.doi ? `<a href="https://doi.org/${encodeURIComponent(p.doi)}" target="_blank" rel="noopener">Publisher / DOI ↗</a>` : ''}${inKb[p.id] ? `<a href="${esc(noteUrl(p))}">Your note in the knowledge base</a>` : ''}<a href="cairn-library/research/papers/${encodeURIComponent(p.cairn_slug)}.md">Cairn paper note</a>${p.issue_id ? `<a href="${esc(url('search.html', {journal: p.journal_id, issue: p.issue_id}))}">Issue contents</a>` : ''}</div><h3>Abstract</h3><div class="abstract">${esc(p.abstract || 'No abstract is available in the harvested public sources.')}</div><p class="notice">Abstract source: ${esc(p.field_sources?.abstract || 'Unavailable')}</p>${p.institution_entities?.length ? `<h3>Institutions</h3><div class="detail-links">${p.institution_entities.map(i => `<a href="${esc(url('institutions.html', {entity: i.id}))}">${esc(i.display_name)}</a>`).join('')}</div><p class="notice">Affiliations recorded on this paper, not necessarily current employers.</p>` : ''}<details><summary>Publication dates &amp; source evidence</summary><p class="notice">${esc(p.publication_status_evidence)}<br>Publication date source: ${esc(p.field_sources?.date || 'Unavailable')}. Dates retain their source precision and are separate from metadata retrieval.</p><p class="notice">${esc(membership?.explanation || 'Journal membership has not been checked.')}<br>${membership?.archive_status === 'confirmed' ? `<a href="${esc(membership.archive_url)}" target="_blank" rel="noopener">Record confirmed in publisher archive</a>` : 'This paper’s individual publisher archive listing has not been checked.'}</p></details>`;
  }
  async function render() {
    const v = ++version, args = read(); $('error').textContent = '';
    rememberNavigation(args);
    if (!args.paper) await detail(null);
    try {
      if (page === 'home') await home(args, v);
      else if (page === 'search') await search(args, v);
      else await entities(args, v);
      if (v === version && args.paper) await detail(args.paper);
    } catch (error) { if (v === version) fail(error); }
  }
  function closeDetail() {
    if (history.state?.detailOpen) { history.back(); return; }
    const args = read(); delete args.paper; go(args, true, true);
  }
  $('closeDetail').onclick = closeDetail;
  // Same-page links (field tiles, tabs, profiles) render in place instead of reloading.
  document.addEventListener('click', event => {
    const a = event.target.closest?.('a[href]');
    if (!a || event.defaultPrevented || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (a.protocol !== location.protocol || a.pathname !== location.pathname || !a.hash) return;
    const args = Object.fromEntries(new URLSearchParams(a.hash.slice(1)));
    event.preventDefault(); go(args, false, false, page === 'home' && args.section ? 'journal-' + args.section : '');
  });
  // Preference edits: buttons carry their change; forms and checkboxes fill in one value.
  document.addEventListener('click', event => {
    const button = event.target.closest?.('button[data-save]');
    if (!button || button.disabled) return;
    event.preventDefault(); savePreference(JSON.parse(button.dataset.save), button.dataset.done);
  });
  document.addEventListener('submit', event => {
    const form = event.target.closest?.('form[data-save-form]');
    if (!form) return;
    event.preventDefault();
    const value = form.elements.value.value.trim();
    if (value) savePreference({...JSON.parse(form.dataset.saveForm), [form.dataset.key]: value}, `Saved “${value}” to your preferences`);
  });
  document.addEventListener('change', event => {
    const input = event.target;
    if (input.matches?.('input[data-toggle]')) savePreference({...JSON.parse(input.dataset.toggle), [input.dataset.key]: input.checked});
    else if (input.matches?.('select[data-tier]')) savePreference({action: 'tier', field: input.dataset.tier, tier: input.value}, `${fieldById.get(input.dataset.tier)?.label} is now ${input.value === 'mute' ? 'muted' : 'a ' + input.value + ' field'}`);
  });
  document.addEventListener('toggle', event => { if (event.target.id === 'forYouSettings') settingsOpen = event.target.open; }, true);
  document.querySelector('.skip').onclick = event => {
    event.preventDefault(); $('main').focus({preventScroll: true});
    $('main').scrollIntoView({block: 'start', behavior: 'instant'});
  };
  $('detail').addEventListener('cancel', e => { e.preventDefault(); closeDetail(); });
  history.scrollRestoration = 'manual';
  window.addEventListener('popstate', () => render().then(restorePosition));
  window.addEventListener('pagehide', () => history.replaceState({...history.state, scrollY: window.scrollY}, '', location.href));
  // Preserve legacy author/institution links into the previous single-page catalog.
  const legacy = read();
  if (page === 'home' && (legacy.author || legacy.institution || legacy['author-query'])) {
    const kind = legacy.institution ? 'institution' : 'author';
    location.replace(url(kind + 's.html', legacy['author-query'] ? {query: legacy['author-query']} : {entity: legacy[kind]})); return;
  }
  const names = {home: 'What’s New', search: 'Search', author: 'Authors', institution: 'Institutions'};
  document.title = names[page] + ' · Cairn catalog';
  document.querySelector(`[data-nav=${page}]`).setAttribute('aria-current', 'page');
  $('footerMeta').textContent = `${num(config.meta.papers)} catalog entries · ${num(config.meta.issues)} issues · Snapshot ${config.meta.snapshot_date} · ${sqliteEdition ? 'Local SQLite edition' : location.protocol === 'file:' ? 'Offline edition' : (studio ? 'Cairn Studio' : 'Catalog app') + ' · edits save to your preferences'}`;
  if (studio) document.querySelector('.masthead nav').insertAdjacentHTML('afterbegin', '<a href="/">← Studio</a>');
  if (page === 'home') {
    const stickyObserver = new ResizeObserver(updateStickyLayout);
    stickyObserver.observe($('catalogChrome')); stickyObserver.observe($('journalIndex'));
    desktopJournals.addEventListener('change', () => { $('journalDisclosure').open = desktopJournals.matches; updateStickyLayout(); });
    window.addEventListener('scroll', trackJournal, {passive: true});
    window.addEventListener('resize', updateStickyLayout, {passive: true});
    $('homeWindow').onchange = () => {
      const window = $('homeWindow').value;
      if (window === 'custom') { $('homeDates').hidden = false; updateStickyLayout(); return; }
      stored('cairn-home-window', window); go({window, field: homeField(read()), new: read().new});
    };
    $('homeDates').onsubmit = e => { e.preventDefault(); try {
      const range = CairnPeriods.range($('homeStart').value, $('homeEnd').value);
      stored('cairn-home-window', 'custom'); stored('cairn-home-start', range.start_date); stored('cairn-home-end', range.end_date); go({window: 'custom', ...range, field: homeField(read()), new: read().new});
    } catch (error) { fail(error); } };
    const redraw = () => { homeCache = null; homeDrawKey = null; $('homeLayout').dataset.layout = ''; render().catch(fail); };
    $('newOnly').onclick = () => { const a = read(); go({...a, new: a.new === '1' ? '' : '1', foryou: '', paper: ''}); };
    $('density').onclick = () => { stored('cairn-density', compact() ? 'cards' : 'compact'); redraw(); };
    $('markSeen').onclick = () => { const field = homeField(read()); markSeen(field ? [field] : fieldList.map(f => f.id)); redraw(); };
    const args = read(); delete args.group; delete args.offset;
    if (!args.field && homeField(args)) args.field = homeField(args);
    const range = homeRange(args);
    history.replaceState(history.state, '', url(location.pathname, {...args, window: range.window, ...(range.window === 'custom' ? range : {})}));
  } else if (page === 'search') {
    dateControls('searchDates');
    $('journal').innerHTML += config.meta.journals.map(j => `<option value="${esc(j.id)}">${esc(j.title)}</option>`).join('');
    $('journal').onchange = () => issues({...formArgs('searchForm'), issue: ''}, version).catch(fail);
    $('searchForm').onsubmit = e => { e.preventDefault(); try { go(formArgs('searchForm')); } catch (error) { fail(error); } };
    $('resetSearch').onclick = () => go({});
  } else if (entityPage) {
    $('entityTitle').textContent = names[page];
    $('entityIntro').textContent = page === 'author' ? 'Find an author by name or source identity, then explore their publications.' : 'Explore research through the affiliations recorded on each paper.';
    $('entityLabel').firstChild.textContent = page === 'author' ? 'Find an author' : 'Find an institution';
    $('entitySearch').placeholder = page === 'author' ? 'Name, ORCID or OpenAlex ID' : 'Name, ROR or OpenAlex ID';
    dateControls('publicationDates');
    $('entityForm').onsubmit = e => { e.preventDefault(); go({query: $('entitySearch').value.trim()}); };
    $('publicationForm').onsubmit = e => { e.preventDefault(); try { go({...read(), ...formArgs('publicationForm'), pub_offset: 0, paper: ''}); } catch (error) { fail(error); } };
  }
  loadInKb().catch(() => {}).finally(() => render().then(restorePosition).catch(fail));
})();
