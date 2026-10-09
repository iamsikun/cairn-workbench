import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
await build({
  entryPoints: [fileURLToPath(new URL('../bin/application.js', import.meta.url))],
  outfile: process.argv[2] || 'application.mjs', bundle: true, platform: 'node',
  format: 'esm', target: 'node20', legalComments: 'eof',
  banner: {js: '// Generated application profile. MIT; see THIRD_PARTY_LICENSES. Do not edit.'},
});
