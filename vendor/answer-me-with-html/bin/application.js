import { renderApplication } from '../src/application.js';
let data = '';
try {
  for await (const chunk of process.stdin) {
    data += chunk;
    if (Buffer.byteLength(data) > 32 * 1024 * 1024) throw Error('Input budget exceeded');
  }
  const document = JSON.parse(data);
  process.stdout.write(renderApplication(document));
} catch { process.stderr.write('Application renderer rejected input\n'); process.exitCode = 2; }
