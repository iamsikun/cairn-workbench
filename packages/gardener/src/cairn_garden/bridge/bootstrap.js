/* Narrow local write bridge. No deletion, metadata replacement, file access or arbitrary JS endpoint. */
const BUILD = '__BRIDGE_BUILD__';
const ROUTE = '/kb-gardener/v1';
const KEY = /^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$/;
let credentials;
let queue = Promise.resolve();

function identities(data) {
    const ids = new Set();
    let doi = String(data.DOI || '').trim().toLowerCase().replace(/^(https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/, '');
    try { doi = decodeURIComponent(doi).trim(); } catch (_) { /* Preserve malformed evidence. */ }
    if (doi) ids.add('doi:' + doi);
    const text = [data.url, data.archiveID, data.extra, doi.replace('10.48550/arxiv.', 'arxiv:')].join(' ');
    const rx = /(?:arxiv(?:\.org\/(?:abs|pdf)\/|:))([a-z.-]+\/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?/ig;
    for (const match of text.matchAll(rx)) ids.add('arxiv:' + match[1].toLowerCase());
    return ids;
}

function check(condition, message, status = 400) {
    if (!condition) { const error = new Error(message); error.status = status; throw error; }
}

async function mutate(request) {
    const libraryID = Zotero.Libraries.userLibraryID;
    check(Zotero.Libraries.get(libraryID).editable, 'Library is not editable', 403);
    check(request.op === 'create' || request.op === 'add', 'Unsupported operation');
    check(KEY.test(request.key || ''), 'Invalid item key');
    check(Array.isArray(request.collections) && request.collections.length <= 50
        && request.collections.every(key => typeof key === 'string' && KEY.test(key)), 'Invalid collections');
    // Zotero's transaction protects additive updates and deduplication against concurrent writes.
    return Zotero.DB.executeTransaction(async () => {
        for (const key of request.collections) {
            const collection = Zotero.Collections.getByLibraryAndKey(libraryID, key);
            check(collection && !collection.deleted, 'Missing or deleted target collection: ' + key, 409);
        }
        let item = Zotero.Items.getByLibraryAndKey(libraryID, request.key);
        let created = false;
        if (request.op === 'create') {
            const data = request.data;
            const fields = new Set(['itemType', 'title', 'DOI', 'url', 'date', 'creators', 'abstractNote',
                'publicationTitle', 'volume', 'issue', 'pages', 'repository', 'archiveID', 'proceedingsTitle', 'publisher']);
            check(data && typeof data === 'object' && !Array.isArray(data)
                && Object.keys(data).every(field => fields.has(field)), 'Unsupported item fields');
            check(['preprint', 'journalArticle', 'conferencePaper'].includes(data.itemType)
                && typeof data.title === 'string' && data.title.trim(), 'Invalid bibliographic item');
            const ids = identities(data);
            check(typeof request.identity === 'string' && ids.has(request.identity), 'Identity does not match metadata');
            const matches = [];
            // Include trashed records so a deleted paper cannot silently be re-imported.
            for (const candidate of await Zotero.Items.getAll(libraryID, true, true)) {
                if (!candidate.isRegularItem()) continue;
                await candidate.loadAllData();
                if ([...identities(candidate.toJSON())].some(id => ids.has(id))) matches.push(candidate);
            }
            check(matches.length <= 1, 'Ambiguous duplicate identity', 409);
            if (item) {
                await item.loadAllData();
                check(item.isRegularItem() && identities(item.toJSON()).has(request.identity), 'Item key conflict', 409);
                check(!matches.length || matches[0].key === item.key, 'Identity/key conflict', 409);
            } else if (matches.length) item = matches[0];
            if (!item) {
                item = new Zotero.Item(data.itemType);
                item.libraryID = libraryID;
                item.key = request.key;
                // An assigned key marks an object as identified. Load its empty primary state
                // before fromJSON so Zotero can safely create an item with this durable key.
                await item.loadPrimaryData();
                item.fromJSON(data);
                created = true;
            }
        }
        check(item && item.isRegularItem() && !item.deleted, 'Item is absent, trashed or not bibliographic', 409);
        if (!created) await item.loadAllData();
        const before = created ? [] : item.toJSON().collections;
        for (const key of request.collections) item.addToCollection(key);
        const changed = created || request.collections.some(key => !before.includes(key));
        if (changed) await item.save();
        return {key: item.key, created, changed, before_collections: before, data: item.toJSON()};
    });
}

async function handle(request) {
    try {
        check(!request.headers.origin, 'Browser origins are not allowed', 403);
        check(credentials && request.headers.authorization === 'Bearer ' + credentials.token, 'Unauthorized', 401);
        check(request.data && request.data.user_id === credentials.user_id
            && Number(Zotero.Users.getCurrentUserID()) === credentials.user_id, 'Library account mismatch', 403);
        if (request.data.op === 'status') return [200, 'application/json', JSON.stringify({protocol: 1, build: BUILD,
            user_id: credentials.user_id, version: Zotero.version, capabilities: ['create', 'add']})];
        // Serialize requests before opening transactions; a retry can never race an unfinished create.
        const task = queue.then(() => mutate(request.data));
        queue = task.catch(() => {});
        return [200, 'application/json', JSON.stringify(await task)];
    } catch (error) {
        return [error.status || 500, 'application/json', JSON.stringify({error: error.message})];
    }
}

async function startup() {
    await Zotero.initializationPromise;
    const home = Services.dirsvc.get('Home', Components.interfaces.nsIFile).path;
    const file = PathUtils.join(home, '.config', 'kb-gardener', 'zotero-local.json');
    credentials = await IOUtils.readJSON(file);
    check(/^[a-f0-9]{64}$/.test(credentials.token) && Number.isSafeInteger(credentials.user_id), 'Invalid bridge credentials');
    const endpoint = function () {};
    endpoint.prototype = {supportedMethods: ['POST'], supportedDataTypes: ['application/json'], init: handle};
    Zotero.Server.Endpoints[ROUTE] = endpoint;

}
function shutdown() { delete Zotero.Server.Endpoints[ROUTE]; credentials = null; }
function install() {}
function uninstall() {}
