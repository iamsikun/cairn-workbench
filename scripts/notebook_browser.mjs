// Mandatory direct-save browser checks, only inside the isolated renderer container.
import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import {devtoolsUrl, findChrome} from '../vendor/answer-me-with-html/src/video/export.js';

const directory = process.argv[2];
assert.ok(findChrome(), 'Chromium is required; skipping does not pass this gate');
const scratch = mkdtempSync(join(tmpdir(), 'notebook-browser-'));
const chrome = spawn(findChrome(), ['--headless=new', '--remote-debugging-port=0',
  `--user-data-dir=${scratch}`, '--no-first-run', 'about:blank'], {stdio: ['ignore', 'ignore', 'pipe']});
let socket;
try {
  socket = new WebSocket(await devtoolsUrl(chrome));
  const pending = new Map(), events = []; let sequence = 0;
  socket.addEventListener('message', ({data}) => {
    const value = JSON.parse(data);
    if (!value.id) return events.push(value);
    const item = pending.get(value.id); if (!item) return;
    clearTimeout(item.timer); pending.delete(value.id);
    value.error ? item.reject(Error(value.error.message)) : item.resolve(value.result);
  });
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, {once: true});
    socket.addEventListener('error', reject, {once: true});
  });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++sequence, timer = setTimeout(() => reject(Error(method)), 15000);
    pending.set(id, {resolve, reject, timer}); socket.send(JSON.stringify({id, method, params, sessionId}));
  });
  const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
  const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
  const page = (method, params) => send(method, params, sessionId);
  const evaluate = async expression => {
    const result = await page('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  await page('Page.enable'); await page('Runtime.enable'); await page('Network.enable');
  const out = join(directory, 'browser'); mkdirSync(out, {recursive: true});
  for (const file of ['notebook', 'scenario']) {
    await page('Page.navigate', {url: pathToFileURL(join(directory, `${file}.html`)).href});
    for (let i = 0; i < 100; i++) {
      if (await evaluate('document.readyState === "complete" && !!document.querySelector("#filter")')) break;
      await new Promise(resolve => setTimeout(resolve, 40));
    }
    for (const width of [1440, 390]) for (const mode of ['light', 'dark']) {
      await page('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
      await evaluate(`document.documentElement.dataset.mode='${mode}'`);
      assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'));
      writeFileSync(join(out, `${file}-${width}-${mode}.png`), Buffer.from(
        (await page('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true})).data, 'base64'));
    }
    if (file === 'notebook') {
      assert.ok(await evaluate('document.querySelectorAll("table").length > 0'));
      assert.ok(await evaluate('document.body.textContent.includes("p(t₁…tₖ | u)")'));
      assert.ok(await evaluate('!document.body.textContent.includes("USD")'));
      assert.ok(await evaluate('[...document.querySelectorAll("#feedback option")].some(o=>o.value.startsWith("asset_"))'));
    } else {
      assert.equal(await evaluate('document.querySelector("output").textContent'), '142.00 USD');
      await evaluate('const input=document.querySelector("[data-cairn-scenario] input"); input.value="200"; input.dispatchEvent(new Event("input"))');
      assert.equal(await evaluate('document.querySelector("output").textContent'), '263.00 USD');
      assert.equal(await evaluate('localStorage.length'), 0);
    }
    await page('Emulation.setEmulatedMedia', {features: [{name: 'prefers-reduced-motion', value: 'reduce'}]});
    assert.equal(await evaluate('getComputedStyle(document.querySelector("button")).animationName'), 'none');
    await page('Emulation.setEmulatedMedia', {media: 'print'});
    assert.equal(await evaluate('getComputedStyle(document.querySelector("#feedback")).display'), 'none');
    writeFileSync(join(out, `${file}-print.pdf`), Buffer.from((await page('Page.printToPDF', {printBackground: true})).data, 'base64'));
    await page('Emulation.setEmulatedMedia', {media: ''});
  }
  const requests = events.filter(e => e.method === 'Network.requestWillBeSent').map(e => e.params.request.url);
  assert.deepEqual(requests.filter(url => /^https?:/i.test(url)), []);
  const errors = events.filter(e => e.method === 'Runtime.exceptionThrown'); assert.deepEqual(errors, []);
  writeFileSync(join(out, 'checks.json'), JSON.stringify({offline: true, widths: [1440, 390], themes: ['light', 'dark'],
    print: true, reducedMotion: true, scopedContent: true, deterministicControls: true, requests,
    chromium: await send('Browser.getVersion')}, null, 2));
  console.log('Notebook and scenario browser checks passed');
} finally {
  socket?.close(); chrome.kill();
}
