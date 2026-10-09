import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { renderDoc } from '../src/render.js';
import { devtoolsUrl, findChrome } from '../src/video/export.js';
const skip = process.env.AM_E2E !== '1' ? 'requires AM_E2E=1 and Chromium' : !findChrome() ? 'Chromium unavailable' : typeof WebSocket === 'undefined' ? 'needs Node 22+' : false;

// Dedicated CDP observer records every page request, including failed attempts.
async function browser(url) {
  const ws = new WebSocket(url), pending = new Map(), events = []; let next = 0;
  ws.addEventListener('message', ({ data }) => {
    const value = JSON.parse(data);
    if (value.id) { const p = pending.get(value.id); pending.delete(value.id); if (p) { clearTimeout(p.timer); value.error ? p.reject(new Error(value.error.message)) : p.resolve(value.result); } }
    else events.push(value);
  });
  await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, { once: true }); ws.addEventListener('error', reject, { once: true }); });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => { const id = ++next; const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000); pending.set(id, { resolve, reject, timer }); ws.send(JSON.stringify({ id, method, params, sessionId })); });
  return { send, events, close: () => ws.close() };
}
const draft = '---\ntitle: Synthetic review\nlang: en\n---\n## A Evidence\nObserved result. [Source](https://example.org/report)\n\n## B Flow\n```flow LR\nReader -> Review: evidence\nReview -> Answer: conclusion\n```\n## C Decision\n```ask\nWhich detail helps?\n* Examples\n- More theory\n```';

test('Chromium: offline requests, clipping, themes, focus, controls, replies, print, and reduced motion', { skip, timeout: 90000 }, async (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'portable-browser-'));
  const file = join(dir, 'answer.html'); writeFileSync(file, renderDoc(draft).html);
  const chrome = spawn(findChrome(), ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${join(dir,'profile')}`, '--no-first-run', 'about:blank'], { stdio: ['ignore','ignore','pipe'] });
  let cdp;
  t.after(async () => { cdp?.close(); if (chrome.exitCode === null) await new Promise((done) => { const timer = setTimeout(done, 3000); chrome.once('exit',()=>{clearTimeout(timer);done();}); chrome.kill(); }); await rm(dir,{recursive:true,force:true,maxRetries:10,retryDelay:200}); });
  cdp = await browser(await devtoolsUrl(chrome));
  const { targetId } = await cdp.send('Target.createTarget',{url:'about:blank'});
  const { sessionId } = await cdp.send('Target.attachToTarget',{targetId,flatten:true});
  const send = (method,params) => cdp.send(method,params,sessionId);
  const evaluate = async (expression) => { const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true}); if(r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text); return r.result.value; };
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:pathToFileURL(file).href});
  for(let i=0;i<100;i++) { if(await evaluate('document.readyState === "complete" && !!document.querySelector(".am-diagram-expand")')) break; await new Promise((r)=>setTimeout(r,50)); }
  await evaluate('document.fonts.ready');
  const out = process.env.AM_BROWSER_OUTPUT;
  if(out) mkdirSync(out,{recursive:true});
  for(const width of [1440,390]) for(const mode of ['light','dark']) {
    await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
    await evaluate(`document.documentElement.setAttribute('data-mode','${mode}')`);
    await new Promise((r)=>setTimeout(r,220));
    const metrics = await evaluate(`({ overflow: document.documentElement.scrollWidth - innerWidth, panels: [...document.querySelectorAll('.am-panel')].map(el => ({ x:el.getBoundingClientRect().left, right:el.getBoundingClientRect().right, height:el.clientHeight, scroll:el.scrollHeight })), background:getComputedStyle(document.body).backgroundColor })`);
    assert.ok(metrics.overflow <= 1,JSON.stringify({width,mode,metrics}));
    assert.ok(metrics.panels.every(p=>p.x>=0 && p.right<=width+1 && p.height>=p.scroll-1),JSON.stringify(metrics));
    if(out) writeFileSync(join(out,`${width}-${mode}.png`),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true})).data,'base64'));
  }
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9}); await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  assert.ok(await evaluate('document.activeElement !== document.body'));
  assert.ok(await evaluate('document.activeElement.matches(":focus-visible")'));
  await evaluate('document.querySelector(".am-diagram-expand").click()');
  assert.equal(await evaluate('document.activeElement.classList.contains("am-lightbox-close")'),true);
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  assert.equal(await evaluate('document.querySelector(".am-lightbox").hidden'),true);
  await evaluate('document.querySelector("[data-am=reply]").click()');
  assert.equal(await evaluate('document.querySelector("dialog.am-reply").open'),true);
  assert.match(await evaluate('document.querySelector("dialog.am-reply textarea").value'),/Re:|Synthetic review/);
  await evaluate('document.querySelector("dialog.am-reply").close()');
  await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  assert.equal(await evaluate('matchMedia("(prefers-reduced-motion: reduce)").matches'),true);
  assert.ok(await evaluate('parseFloat(getComputedStyle(document.querySelector(".am-diagram-expand")).transitionDuration) <= 0.001'));
  await send('Emulation.setEmulatedMedia',{media:'print'});
  assert.equal(await evaluate('getComputedStyle(document.querySelector(".am-toolbar")).display'),'none');
  const pdf=await send('Page.printToPDF',{printBackground:true}); assert.ok(Buffer.from(pdf.data,'base64').length>1000); if(out) writeFileSync(join(out,'print.pdf'),Buffer.from(pdf.data,'base64'));
  const requests=cdp.events.filter(e=>e.sessionId===sessionId&&e.method==='Network.requestWillBeSent').map(e=>e.params.request.url);
  assert.deepEqual(requests.filter(url=>/^https?:/i.test(url)),[],'no page network requests, including attempted loads');
  const exceptions=cdp.events.filter(e=>e.sessionId===sessionId&&e.method==='Runtime.exceptionThrown'); assert.deepEqual(exceptions,[]);
  // Trusted script execution is opt-in, but still cannot fetch resources in offline mode.
  const trusted='## A\n```html\n<script>window.violations=[]; document.addEventListener("securitypolicyviolation", e => window.violations.push({directive:e.effectiveDirective, uri:e.blockedURI})); window.rawRan=true; fetch("https://example.org/blocked").catch(()=>{window.blocked=true})</script>\n```';
  writeFileSync(file,renderDoc(trusted,{}, {},{policy:{allowRawHtml:true}}).html);
  await send('Page.navigate',{url:pathToFileURL(file).href});
  for(let i=0;i<100;i++){if(await evaluate('window.blocked === true && window.violations?.length > 0'))break; await new Promise(r=>setTimeout(r,30));}
  assert.equal(await evaluate('window.rawRan && window.blocked'),true);
  const blocked=await evaluate('window.violations'); assert.ok(blocked.some(e=>e.directive==='connect-src' && e.uri.startsWith('https://example.org')),JSON.stringify(blocked));
  if(out) writeFileSync(join(out,'network-check.json'),JSON.stringify({defaultPageRequests:requests,defaultPageExceptions:exceptions.length,cspBlockedRequests:blocked.length},null,2));
});
