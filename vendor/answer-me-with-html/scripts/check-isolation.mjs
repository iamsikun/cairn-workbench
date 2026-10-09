// A readiness gate for the documented Linux development container, never a skip.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { networkInterfaces } from 'node:os';
assert.equal(process.platform, 'linux', 'run contributor checks in the development container');
assert.notEqual(process.getuid(), 0, 'processing must use an unprivileged uid');
assert.equal(existsSync('/var/run/docker.sock'), false, 'no Docker socket');
const status = readFileSync('/proc/self/status', 'utf8');
assert.match(status, /^CapEff:\s+0+$/m); assert.match(status, /^NoNewPrivs:\s+1$/m);
const interfaces = Object.keys(networkInterfaces()); assert.deepEqual(interfaces, ['lo'], 'only container loopback is allowed');
const mounts = readFileSync('/proc/mounts', 'utf8');
assert.match(mounts, /^\S+ \/ \S+ ro[, ]/m, 'read-only root');
assert.doesNotMatch(mounts, /\s\/(?:Users|home|root|var\/run\/docker.sock)(?:\/|\s)/, 'no private filesystem mounts');
assert.ok(!Object.keys(process.env).some((k) => /^(?:OPENAI_API_KEY|ANTHROPIC_API_KEY|ELEVENLABS_API_KEY|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|GITHUB_TOKEN|GH_TOKEN)$/.test(k)), 'no credentials');
console.log(JSON.stringify({isolated:true,uid:process.getuid(),interfaces,rootReadOnly:true,capabilities:'none',noNewPrivileges:true,dockerSocket:false,credentialVariables:false}));
