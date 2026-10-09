// Run inside the renderer development image after extracting the portable ZIP.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {cpSync, mkdtempSync, mkdirSync, readFileSync, writeFileSync, readdirSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync, spawnSync} from 'node:child_process';
const normalize=v=>Array.isArray(v)?v.map(normalize):v!==null&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,normalize(v[k])])):v;
const checksum=v=>createHash('sha256').update(JSON.stringify(normalize(v))+'\n').digest('hex');
const source = process.argv[2];
const results = [];
for (const version of [20,22,24]) for (const name of ['skill', 'Skill Folder 日本語']) {
  const work = mkdtempSync(join(tmpdir(),'cairn-portable-'));
  try {
    const installed=join(work,name); cpSync(source,installed,{recursive:true});
    const input=join(work,'Approved packet 中文.json'),output=join(work,'Answer 日本語.html');
    const doc={version:1,title:'Synthetic portable view',bundle_id:'view_synthetic',bundle_hash:'a'.repeat(64),subtitle:'Synthetic snapshot',sections:[{title:'Finding',blocks:[{title:'Bounded finding',text:'42 under condition C. <script>hostile()</script>',kind:'text',labels:['Unreviewed'],citations:[],nodes:[]}]}],evidence:[],targets:[],assets:[],feedback:false};
    const job={bundle:{id:doc.bundle_id}};doc.bundle_hash=checksum(job.bundle);
    const packet=()=>JSON.stringify({job,input_hash:checksum(job),document:doc,document_hash:checksum(doc)});
    writeFileSync(input,packet());
    const node=`/opt/node${version}/bin/node`,cli=join(installed,'scripts/render.mjs');
    const run=()=>execFileSync(node,[cli,'--input',input,'--output',output],{env:{PATH:'/usr/bin:/bin'},encoding:'utf8'});
    run(); const first=readFileSync(output);run();assert.deepEqual(readFileSync(output),first);
    assert.equal(readdirSync(work).filter(p=>p.endsWith('.html')).length,1);
    assert.match(first.toString(),/&lt;script&gt;hostile/);
    doc.sections[0].blocks[0].url='javascript:alert(1)';writeFileSync(input,packet());
    assert.notEqual(spawnSync(node,[cli,'--input',input,'--output',output],{env:{PATH:'/usr/bin:/bin'}}).status,0);
    assert.deepEqual(readFileSync(output),first);
    results.push({runtime:execFileSync(node,['--version'],{encoding:'utf8'}).trim(),installPath:name,retry:'passed',failedRenderPreserved:'passed',agentEnvironmentVariables:'none'});
  } finally {rmSync(work,{recursive:true,force:true});}
}
console.log(JSON.stringify(results,null,2));
