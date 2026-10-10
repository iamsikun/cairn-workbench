import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
// Whitespace minification removes esbuild's machine-dependent source-path comments.
await build({
  entryPoints: [fileURLToPath(new URL('../bin/application.js', import.meta.url))],
  outfile: process.argv[2] || 'application.mjs', bundle: true, platform: 'node',
  format: 'esm', target: 'node20', legalComments: 'eof', minifyWhitespace: true,
  banner: {js: '// Generated application profile. MIT; see THIRD_PARTY_LICENSES. Do not edit.'},
});
