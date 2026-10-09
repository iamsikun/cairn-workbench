import { test } from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {renderApplication} from '../src/application.js';
const block = {title:'Synthetic result', text:'42 under condition C', kind:'text', labels:['inference'], citations:[], nodes:[], url:null};
export const fixture = () => ({version:1,title:'Synthetic 中文 research',bundle_id:'view_synthetic',bundle_hash:'a'.repeat(64),subtitle:'Private snapshot; not current knowledge',sections:[{title:'Findings',blocks:[{...block}]}],evidence:[],targets:['concept_example'],feedback:true,assets:[]});
test('application treats source markup and component fences as text',()=>{
 const doc=fixture();doc.sections[0].blocks[0].text='<script>INJECT()</script>\n```code src="/etc/passwd"\n```';
 const html=renderApplication(doc);
 assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>INJECT'));
 assert.ok(!html.includes('localStorage'));assert.ok(!html.includes('am-source'));
 assert.ok(html.includes("script-src 'sha256-"));assert.ok(html.includes("connect-src 'none'"));
 assert.ok(!renderApplication(doc,{interactions:false}).includes('<script>'));
});
test('application rejects executable navigation and unavailable citations',()=>{
 for(const value of ['javascript:alert(1)','JaVaScRiPt:alert(1)','data:text/html,test','file:///tmp/private','vbscript:x','https://user:pass@example.org']) {
  const doc=fixture();doc.sections[0].blocks[0].url=value;assert.throws(()=>renderApplication(doc));
 }
 const doc=fixture();doc.sections[0].blocks[0].citations=['evidence_denied'];assert.throws(()=>renderApplication(doc));
});
test('application accepts supplied verified image bytes without filesystem reads',()=>{
 const doc=fixture(),bytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aEuoAAAAASUVORK5CYII=','base64');
 doc.assets=[{id:'asset_pixel',mime:'image/png',data:bytes.toString('base64'),sha256:createHash('sha256').update(bytes).digest('hex')}];
 doc.sections[0].blocks[0].asset_id='asset_pixel';assert.ok(renderApplication(doc).includes('src="data:image/png;'));
 doc.assets[0].sha256='0'.repeat(64);assert.throws(()=>renderApplication(doc));
});
