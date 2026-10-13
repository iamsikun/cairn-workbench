/* Run the shipped bridge in a model of Zotero's API; no HTTP or live library access. */
const assert = require('assert/strict');
const fs = require('fs');
const vm = require('vm');
const items = new Map();
const collections = new Set(['TARGAAAA','TARGBBBB']);
let saves = 0;
class Item {
    constructor(type) { this.data = {itemType: type, collections: []}; this.deleted = false; }
    isRegularItem() { return !['note','attachment'].includes(this.data.itemType); }
    async loadAllData() { this.primaryLoaded = true; }
    async loadPrimaryData() { this.primaryLoaded = true; }
    fromJSON(data) { assert.ok(!this.key || this.primaryLoaded, 'Assigned keys require primary-data initialization'); Object.assign(this.data, JSON.parse(JSON.stringify(data))); }
    toJSON() { return JSON.parse(JSON.stringify({...this.data, key: this.key})); }
    addToCollection(key) { if (!this.data.collections.includes(key)) this.data.collections.push(key); }
    async save() { saves++; items.set(this.key, this); }
}
const context = {Zotero: {
    initializationPromise: Promise.resolve(), version: '9.0.6',
    Libraries: {userLibraryID: 1, get: () => ({editable: true})},
    Users: {getCurrentUserID: () => 123},
    Items: {getByLibraryAndKey: (lib, key) => items.get(key), getAll: async () => [...items.values()]},
    Collections: {getByLibraryAndKey: (lib, key) => collections.has(key) ? {key} : null},
    DB: {executeTransaction: async fn => fn()}, Item, Server: {Endpoints: {}}
}, PathUtils: {join: (...x) => x.join('/')},
    Services: {dirsvc: {get: () => ({path:'/fixture'})}}, Components: {interfaces: {nsIFile: {}}},
    IOUtils: {readJSON: async () => ({token: 'a'.repeat(64), user_id: 123})}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);
const base = {op: 'create', user_id: 123, key: 'PAPERAAA', identity: 'arxiv:1706.03762',
    collections: ['TARGAAAA'], data: {itemType:'preprint',title:'Verified paper',url:'https://arxiv.org/abs/1706.03762'}};
async function call(data, headers = {authorization:'Bearer ' + 'a'.repeat(64)}) {
    const [status, type, body] = await context.handle({headers, data});
    return {status, ...JSON.parse(body)};
}
(async () => {
    await context.startup();
    assert.equal((await call({...base}, {})).status, 401);
    assert.equal((await call({...base}, {authorization:'Bearer ' + 'a'.repeat(64),origin:'https://evil.example'})).status, 403);
    assert.equal((await call({...base,user_id:999})).status, 403);
    assert.equal((await call({...base,collections:['MISSINGA']})).status, 409);
    assert.equal((await call({...base,identity:'arxiv:9999.12345'})).status, 400);
    assert.equal((await call({...base,data:{...base.data,notes:['injected']}})).status, 400);
    assert.equal(items.size, 0);
    const [first,retry] = await Promise.all([call(base),call(base)]);
    assert.equal(first.status, 200); assert.equal(first.created, true);
    assert.equal(retry.created, false); assert.equal(saves, 1); assert.equal(items.size, 1);
    const metadata = items.get('PAPERAAA').toJSON();
    const added = await call({op:'add',user_id:123,key:'PAPERAAA',collections:['TARGBBBB']});
    assert.equal(added.status,200); assert.equal(added.changed,true);
    assert.deepEqual(added.data.collections.sort(), ['TARGAAAA','TARGBBBB']);
    const after = items.get('PAPERAAA').toJSON();
    delete metadata.collections; delete after.collections; assert.deepEqual(after,metadata);
    assert.equal((await call({op:'add',user_id:123,key:'PAPERAAA',collections:['TARGBBBB']})).changed, false);
    const otherKey = await call({...base,key:'PAPERBBB'});
    assert.equal(otherKey.key,'PAPERAAA'); assert.equal(otherKey.created,false); assert.equal(items.size,1);
    assert.equal((await call({...base,identity:'arxiv:1801.00001',data:{...base.data,url:'https://arxiv.org/abs/1801.00001'}})).status,409);
    items.get('PAPERAAA').deleted = true;
    assert.equal((await call(base)).status,409);
    items.get('PAPERAAA').deleted = false;
    const duplicate = new Item('preprint'); duplicate.fromJSON(base.data); duplicate.key='PAPERCCC'; items.set(duplicate.key,duplicate);
    assert.equal((await call({...base,key:'PAPERDDD'})).status,409);
    assert.equal(items.size,2);
    items.clear();
    const legacy = new Item('journalArticle'); 
    legacy.fromJSON({itemType:'journalArticle',title:'Legacy DOI',DOI:'http://dx.doi.org/10.1234%2Fpaper'}); legacy.key='LEGACYAA';
    items.set(legacy.key,legacy);
    const reconciled = await call({...base,key:'NEWKEYAA',identity:'doi:10.1234/paper',
        data:{itemType:'journalArticle',title:'Canonical DOI',DOI:'10.1234/paper'}});
    assert.equal(reconciled.key,'LEGACYAA'); assert.equal(reconciled.created,false); assert.equal(items.size,1);
    context.shutdown(); assert.equal(context.Zotero.Server.Endpoints['/kb-gardener/v1'],undefined);
    console.log('Bridge regressions passed: auth, origin, account, target, metadata, concurrency, idempotence, preservation, conflicts, trash, duplicates, shutdown.');
})().catch(error => {console.error(error);process.exit(1);});
