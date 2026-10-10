import { renderApplication } from '../src/application.js';
// Decode once after collecting bytes: per-chunk decoding splits multi-byte characters.
const chunks = [];
let size = 0;
try {
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 32 * 1024 * 1024) throw Error('Input budget exceeded');
    chunks.push(chunk);
  }
  const document = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  process.stdout.write(renderApplication(document));
} catch { process.stderr.write('Application renderer rejected input\n'); process.exitCode = 2; }
