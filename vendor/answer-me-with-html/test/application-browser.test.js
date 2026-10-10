import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,mkdirSync,readFileSync,readdirSync} from 'node:fs';
import {rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import {renderApplication} from '../src/application.js';
import {devtoolsUrl,findChrome} from '../src/video/export.js';

async function connect(url) {
 const socket=new WebSocket(url),pending=new Map(),events=[];let sequence=0;
 socket.addEventListener('message',({data})=>{const value=JSON.parse(data);if(value.id){const p=pending.get(value.id);if(p){clearTimeout(p.timer);pending.delete(value.id);value.error?p.reject(Error(value.error.message)):p.resolve(value.result);}}else events.push(value);});
 await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
 return {events,close:()=>socket.close(),send:(method,params={},sessionId)=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>reject(Error(`CDP timeout ${method}`)),15000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params,sessionId}));})};
}

test('application Chromium mandatory: evidence, themes, narrow layout, feedback, print, requests', {timeout:90000},async t=>{
 assert.ok(findChrome(),'Chromium is required for this acceptance gate');
 const dir=mkdtempSync(join(tmpdir(),'cairn-browser-'));
 const doc={version:1,title:'Synthetic research brief · 研究',bundle_id:'view_synthetic',bundle_hash:'a'.repeat(64),subtitle:'Snapshot: 2026-01-01 · public synthetic evidence',sections:[{title:'Finding and qualification',blocks:[{title:'Reported result',text:'The reported value is 42 under condition C. This does not establish the result for other conditions. <img src="https://synthetic.invalid/tracker">',kind:'text',labels:['Reported result','Unreviewed'],citations:['evidence_example'],nodes:[],url:'https://example.org/publication'},{title:'Review workflow',text:'Describes the workflow, not the current proposal status.',kind:'diagram',labels:[],citations:[],nodes:['Evidence','Proposal','Owner review','Apply'],url:null}]}],evidence:[{key:'evidence_example',reference:{id:'source_example',locator:'page 2',source_hash:'b'.repeat(64),evidence_hash:'c'.repeat(64)},title:'Synthetic source',text:'42 under condition C.',source_date:null,version:'v1',coverage:'excerpt',tables_inspected:false,images_inspected:false,support:'Quote presence does not establish entailment.'}],targets:['concept_example'],feedback:true,assets:[]};
 doc.sections[0].blocks.push({title:'Markdown notebook',text:'# Topic\n\n- A paper\n\n| Model | Result |\n|---|---|\n| Synthetic | 42 |\n\n```python\nprint(42)\n```\n<script>INJECT()</script>\n![tracker](https://synthetic.invalid/tracker)\n[unsafe](javascript:alert%281%29)',kind:'markdown',anchor:'concept_example',labels:[],citations:[],nodes:[],url:null});
 const file=join(dir,'brief.html');writeFileSync(file,renderApplication(doc));
 const chrome=spawn(findChrome(),['--headless=new','--remote-debugging-port=0',`--user-data-dir=${join(dir,'profile')}`,'--no-first-run','about:blank'],{stdio:['ignore','ignore','pipe']});
 let cdp;
 t.after(async()=>{cdp?.close();if(chrome.exitCode===null)await new Promise(resolve=>{const timer=setTimeout(resolve,3000);chrome.once('exit',()=>{clearTimeout(timer);resolve();});chrome.kill();});await rm(dir,{recursive:true,force:true,maxRetries:10,retryDelay:200});});
 cdp=await connect(await devtoolsUrl(chrome));const {targetId}=await cdp.send('Target.createTarget',{url:'about:blank'});const{sessionId}=await cdp.send('Target.attachToTarget',{targetId,flatten:true});const send=(m,p)=>cdp.send(m,p,sessionId);
 const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
 await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
 await send('Page.navigate',{url:pathToFileURL(file).href});
 for(let i=0;i<100;i++){if(await evaluate('document.readyState==="complete" && !!document.querySelector("#filter")'))break;await new Promise(r=>setTimeout(r,40));}
 assert.equal(await evaluate('document.querySelectorAll("#concept_example table").length'),1);
 assert.equal(await evaluate('document.querySelectorAll("#concept_example img, #concept_example script, #concept_example [href^=javascript]").length'),0);
 const output=process.env.AM_BROWSER_OUTPUT?join(process.env.AM_BROWSER_OUTPUT,'application'):null;if(output)mkdirSync(output,{recursive:true});
 for(const width of [1440,390])for(const mode of ['light','dark']){
  await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});await evaluate(`document.documentElement.dataset.mode='${mode}'`);
  assert.ok(await evaluate('document.documentElement.scrollWidth<=innerWidth+1'));
  assert.ok(await evaluate('[...document.querySelectorAll("article,details,.diagram")].every(x=>x.scrollWidth<=x.clientWidth+1)'));
  if(output)writeFileSync(join(output,`${width}-${mode}.png`),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true})).data,'base64'));
 }
 await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});assert.ok(await evaluate('document.activeElement.matches(":focus-visible")'));
 await evaluate('document.querySelector("summary").click()');assert.equal(await evaluate('document.querySelector("details").open'),true);
 await evaluate('document.querySelector(".diagram button").click()');assert.equal(await evaluate('!!document.querySelector(".diagram.expanded")'),true);
 await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});assert.equal(await evaluate('!!document.querySelector(".diagram.expanded")'),false);
 await evaluate('document.querySelector("#filter").value="no-match";document.querySelector("#filter").dispatchEvent(new Event("input"))');assert.equal(await evaluate('document.querySelectorAll("article:not([hidden])").length'),0);
 await evaluate('document.querySelector("#filter").value="";document.querySelector("#filter").dispatchEvent(new Event("input"))');
 await cdp.send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:dir});
 await evaluate('document.querySelector("[name=comment]").value="Keep the condition.";document.querySelector("#feedback").requestSubmit()');
 for(let i=0;i<100&&!readdirSync(dir).includes('cairn-feedback.json');i++)await new Promise(r=>setTimeout(r,40));
 const feedback=JSON.parse(readFileSync(join(dir,'cairn-feedback.json'),'utf8'));assert.equal(feedback.bundle_id,doc.bundle_id);assert.equal(feedback.entries[0].target_id,'concept_example');assert.equal(await evaluate('localStorage.length'),0);
 await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});assert.equal(await evaluate('getComputedStyle(document.querySelector("button")).animationName'),'none');
 await send('Emulation.setEmulatedMedia',{media:'print'});assert.equal(await evaluate('getComputedStyle(document.querySelector("#feedback")).display'),'none');
 await evaluate('document.querySelector("details").open=false');assert.equal(await evaluate('getComputedStyle(document.querySelector("details"),"::details-content").contentVisibility'),'visible');
 const pdf=await send('Page.printToPDF',{printBackground:true});assert.ok(Buffer.from(pdf.data,'base64').length>1000);if(output)writeFileSync(join(output,'print.pdf'),Buffer.from(pdf.data,'base64'));
 await send('Emulation.setScriptExecutionDisabled',{value:true});await send('Page.reload');
 await new Promise(r=>setTimeout(r,200));assert.ok(await evaluate('document.body.textContent.includes("42 under condition C")'));
 const requests=cdp.events.filter(e=>e.sessionId===sessionId&&e.method==='Network.requestWillBeSent').map(e=>e.params.request.url);assert.deepEqual(requests.filter(u=>/^https?:/i.test(u)),[]);
 const exceptions=cdp.events.filter(e=>e.sessionId===sessionId&&e.method==='Runtime.exceptionThrown');assert.deepEqual(exceptions,[]);
 if(output)writeFileSync(join(output,'checks.json'),JSON.stringify({requests,exceptions:exceptions.length,feedback,chromium:await cdp.send('Browser.getVersion')},null,2));
});
