/* Exercise the actual UI controller's URL/focus logic without a browser or network. */
const assert = require('node:assert/strict'), vm = require('node:vm');
module.exports = async function verifyHomeNavigation(source, config, periods, recentApi) {
  const settle = () => new Promise(resolve => setImmediate(resolve));
  for (const reducedMotion of [false, true]) {
    const elements = new Map(), events = new Map(), scrolls = [], frames = [], properties = new Map(), requests = [];
    let focused;
    const makeElement = id => ({
      id, dataset: {}, open: false, value: '', textContent: '', innerHTML: '', children: [],
      classList: {remove() {}, toggle() {}},
      setAttribute(name, value) { this[name] = value; },
      getAttribute(name) { return this[name]; },
      removeAttribute(name) { delete this[name]; },
      querySelectorAll() { return []; },
      replaceChildren() { this.children = []; },
      append(child) { this.children.push(child); },
      focus(options) { focused = {id, options}; },
      scrollIntoView(options) { scrolls.push({id, ...options}); },
      addEventListener() {},
      getBoundingClientRect() { return {height: id === 'catalogChrome' ? 160 : id === 'journalSummary' ? 48 : 0, top: 0}; },
    });
    const get = id => { if (!elements.has(id)) elements.set(id, makeElement(id)); return elements.get(id); };
    const location = {protocol: 'file:', pathname: '/catalog.html', hash: reducedMotion ? '#window=3&group=date&offset=30&offset_mnsc=10&section=mnsc' : '#window=3&offset_mnsc=10&section=mnsc'};
    Object.defineProperty(location, 'href', {get: () => location.pathname + location.hash});
    const history = {
      state: null,
      replaceState(state, _, url) { this.state = state; location.hash = url.slice(url.indexOf('#')); },
      pushState(state, _, url) { this.replaceState(state, _, url); },
    };
    const links = config.meta.journals.map(j => ({...makeElement('link-' + j.id), dataset: {journalLink: j.id}}));
    get('journalNav').querySelectorAll = selector => selector === '#unused' ? [] : links;
    const saved = new Map(), storage = {getItem() { return null; }, setItem(key, value) { saved.set(key, value); }};
    const context = vm.createContext({
      window: {CAIRN_CONFIG: config, cairnOfflineApi(path, args) { const job = recentApi(path, args); requests.push({path, args, job}); return job; }, scrollY: 0,
        scrollTo(x, y) { scrolls.push({x, y}); }, addEventListener(name, handler) { events.set(name, handler); }},
      document: {body: {...makeElement('body'), dataset: {page: 'home'}}, documentElement: {style: {setProperty(name, value) { properties.set(name, value); }}}, getElementById: get,
        querySelector: selector => get(selector), querySelectorAll: () => [], createElement: () => makeElement(''), addEventListener() {}},
      location, history, localStorage: storage, sessionStorage: storage,
      CairnPeriods: {...periods, today: () => '2026-10-12'}, URLSearchParams, Intl, Date,
      requestAnimationFrame(callback) { frames.push(callback); return frames.length; },
      matchMedia(query) { return {matches: query.includes('reduced-motion') && reducedMotion, addEventListener() {}}; },
      ResizeObserver: class { observe() {} },
    });
    vm.runInContext(source, context);
    // The initial deep link must focus and scroll its target after async results render.
    await settle(); await Promise.all(requests.map(r => r.job)); await settle();
    assert.equal(get('error').textContent, '');
    assert.equal(focused.id, 'journal-mnsc');
    assert.equal(focused.options.preventScroll, true);
    assert.equal(scrolls.at(-1).id, 'journal-mnsc');
    assert(location.hash.includes('offset_mnsc=10'));
    assert.equal(properties.get('--catalog-controls-height'), '160px');
    assert.equal(properties.get('--journal-navigation-height'), '50px');
    assert(!location.hash.includes('group='));
    assert(requests.every(r => r.path !== 'recent' || r.args.group_by === 'journal' && r.args.field === 'business'));
    // A table-of-contents click keeps pagination, closes the mobile index and uses the motion preference.
    get('journalDisclosure').open = true;
    links.find(a => a.dataset.journalLink === 'msom').onclick({preventDefault() {}});
    assert.equal(focused.id, 'journal-msom');
    assert.equal(get('journalDisclosure').open, false);
    assert.equal(scrolls.at(-1).behavior, reducedMotion ? 'instant' : 'smooth');
    assert(location.hash.includes('offset_mnsc=10') && location.hash.includes('section=msom'));
    const beforeSkip = location.hash;
    get('.skip').onclick({preventDefault() {}});
    assert.equal(location.hash, beforeSkip);
    assert.equal(focused.id, 'main');
    // A journal deep link opens its field; window changes keep the field but clear the target and journal pages.
    assert(location.hash.includes('field=business'));
    // The "What's New" nav link always leads back to the front page, never into the last field.
    assert(!/field=|section=|offset_/.test(saved.get('cairn-nav-home')), saved.get('cairn-nav-home'));
    get('homeWindow').value = '1'; get('homeWindow').onchange(); await settle();
    assert.equal(location.hash, '#window=1&field=business');
    // Leaving the field shows the front page, which asks for the per-field overview.
    location.hash = '#window=3'; await events.get('popstate')(); await settle(); await Promise.all(requests.map(r => r.job)); await settle();
    assert.equal(get('error').textContent, '');
    assert.equal(get('frontPage').hidden, false); assert.equal(get('fieldPage').hidden, true);
    assert(requests.some(r => r.path === 'recent' && r.args.group_by === 'field' && JSON.parse(r.args.seen).business === config.meta.snapshot_date));
    assert(get('coreTiles').innerHTML.includes('tile core') && get('skimTiles').innerHTML.includes('tile skim'));
  }
  return {field_front_page: true, deep_link_focus: true, reduced_motion: true, window_reset: true, sticky_header_offsets: true, journal_only_home: true, skip_preserves_state: true};
};
