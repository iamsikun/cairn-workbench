// File-based portable entry point. The owner exports/authorizes the packet first.
import {readFileSync, lstatSync, openSync, writeFileSync, fsyncSync, closeSync, renameSync, unlinkSync, constants} from 'node:fs';
import {resolve, dirname, basename, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash, randomUUID} from 'node:crypto';
import {spawnSync} from 'node:child_process';

function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (value !== null && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k=>[k,normalize(value[k])]));
  return value;
}
const checksum = value => createHash('sha256').update(JSON.stringify(normalize(value))+'\n').digest('hex');
let temporary;
try {
  const args = process.argv.slice(2);
  if (args.length !== 4 || args[0] !== '--input' || args[2] !== '--output') throw Error('Usage: render.mjs --input packet.json --output answer.html');
  const input = resolve(args[1]), output = resolve(args[3]);
  if (input === output) throw Error('Output must differ from the packet');
  const info = lstatSync(input);
  if (!info.isFile() || info.size > 32000000) throw Error('Packet must be a bounded regular file');
  const packet = JSON.parse(readFileSync(input, 'utf8'));
  if (!packet.job || !packet.input_hash || !packet.document || packet.document.bundle_id !== packet.job.bundle.id) throw Error('Owner-exported presentation packet required');
  if (checksum(packet.job) !== packet.input_hash || checksum(packet.document) !== packet.document_hash || checksum(packet.job.bundle) !== packet.document.bundle_hash) throw Error('Packet checksum mismatch; ask the owner to export it again');
  // No options from the draft or packet can change the application profile.
  const result = spawnSync(process.execPath, [fileURLToPath(new URL('../runtime/application.mjs', import.meta.url))], {
    input: JSON.stringify(packet.document), encoding: 'utf8', timeout: 60000,
    maxBuffer: 32000000, env: {LANG:'C.UTF-8'}, windowsHide: true,
  });
  if (result.error || result.status !== 0 || !result.stdout.startsWith('<!doctype html>')) throw Error('Renderer failed; original output preserved');
  // Existing directory required. Reject links before creating a same-directory temp.
  for (let p = dirname(output);; p = dirname(p)) {
    if (lstatSync(p).isSymbolicLink()) throw Error('Output ancestors must not be symlinks');
    if (p === dirname(p)) break;
  }
  try { const s=lstatSync(output); if (!s.isFile() || s.nlink !== 1) throw Error('Output must be a regular, unlinked file'); }
  catch (e) { if (e.code !== 'ENOENT') throw e; }
  temporary = join(dirname(output), `.${basename(output)}.${randomUUID()}.tmp`);
  const fd = openSync(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL, 0o600);
  try { writeFileSync(fd, result.stdout); fsyncSync(fd); } finally { closeSync(fd); }
  renameSync(temporary, output); temporary = undefined;
  process.stdout.write(JSON.stringify({path: output, bundle_id:packet.document.bundle_id})+'\n');
} catch (e) {
  if (temporary) { try { unlinkSync(temporary); } catch {} }
  process.stderr.write(`${e.message}\n`); process.exitCode=1;
}
