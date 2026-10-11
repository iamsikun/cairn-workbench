// Native portability checks; CAIRN_NODE20/22/24 select acquired executable paths.
import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, writeFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
const results = [];
for (const version of [20, 22, 24]) for (const name of ['plain', 'Skill Folder 日本語']) { // lang-ok: synthetic non-ASCII install/output path
  const work = mkdtempSync(join(tmpdir(), 'portable-smoke-'));
  try {
    const installed = join(work, name); cpSync(join(root, 'skills/answer-me-with-html'), installed, { recursive: true });
    const node = process.env[`CAIRN_NODE${version}`], cli = join(installed, 'scripts/am.mjs');
    const env = { PATH: '/usr/bin:/bin', TMPDIR: work, AM_HOME: join(work, 'synthetic-state') };
    const run = (...args) => execFileSync(node, [cli, ...args], { cwd: work, env, encoding: 'utf8' });
    writeFileSync(join(work, 'draft with spaces.md'), '---\nlang: en\n---\n## A Finding\n[Source](https://example.org/report)\n## B Diagram\n```flow\nReader -> Answer\n```');
    run('render', 'draft with spaces.md', '-o', 'answer 日本語.html', '--no-open'); // lang-ok: synthetic non-ASCII install/output path
    writeFileSync(join(work, 'replacement.md'), 'An observed finding, with uncertainty.');
    run('patch', 'answer 日本語.html', '--panel', 'A', '--from', 'replacement.md', '--no-open'); // lang-ok: synthetic non-ASCII install/output path
    run('render', 'draft with spaces.md', '-o', 'answer 日本語.html', '--mode', 'dark', '--no-open'); // lang-ok: synthetic non-ASCII install/output path
    const html = readFileSync(join(work, 'answer 日本語.html'), 'utf8'); // lang-ok: synthetic non-ASCII install/output path
    assert.match(html, /Content-Security-Policy/); assert.match(html, /class="am-node /); assert.match(html, /data-mode="dark"/);
    assert.equal(readdirSync(work).filter((p) => p.endsWith('.html')).length, 1);
    writeFileSync(join(work, 'video.md'), '## A Scene\nA picture.\n> Captions only.');
    run('video', 'video.md', '-o', 'video.html', '--voice', 'off', '--no-open');
    const config = run('config', 'get', 'update_check').trim(); assert.equal(config, 'off');
    results.push({ runtime: execFileSync(node, ['--version'], { env, encoding: 'utf8' }).trim(), installPath: name, render: 'pass', patch: 'pass', retry: 'pass', captions: 'pass', agentEnvironmentVariables: 'none' });
  } finally { rmSync(work, { recursive: true, force: true }); }
}
console.log(JSON.stringify(results, null, 2));
