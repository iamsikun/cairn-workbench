// Run after rebuilding, inside the development container. No agent integration required.
import { readFileSync, writeFileSync, copyFileSync, readdirSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
const skill = join(root, 'skills/answer-me-with-html');
copyFileSync(join(root, 'LICENSE'), join(skill, 'LICENSE'));
const dependencies = ['@dagrejs/dagre', '@dagrejs/graphlib', 'marked', 'parse5', 'entities', 'css-tree'];
let licenses = '# Bundled dependency licenses\n\nThe generated CLI includes the following dependencies.\n';
for (const name of dependencies) {
  const folder = join(root, 'node_modules', name);
  const meta = JSON.parse(readFileSync(join(folder, 'package.json'), 'utf8'));
  const file = readdirSync(folder).find((name) => /^licen[sc]e(?:\.|$)/i.test(name));
  if (!file) throw new Error(`License missing: ${name}`);
  licenses += `\n## ${name} ${meta.version}\n\n${readFileSync(join(folder, file), 'utf8')}\n`;
}
writeFileSync(join(skill, 'THIRD_PARTY_LICENSES.md'), licenses);
const sha256 = (file) => createHash('sha256').update(readFileSync(file)).digest('hex');
const provenance = {
  upstream: { repository: 'https://github.com/QingYunA/answer-me-with-html', version: '0.5.0', commit: '19b2b5b07676d3e65c83ca9a7b6621f300b54c92', license: 'MIT' },
  portableRevision: 1,
  generatedBundle: { path: 'scripts/am.mjs', sha256: sha256(join(skill, 'scripts/am.mjs')), build: 'node scripts/build.mjs (maintained source project)' },
  dependencyLockSha256: sha256(join(root, 'package-lock.json')),
  sourceChanges: ['explicit HTML routing and agent-neutral paths', 'canonical code-file containment', 'URL/resource policy and invocation-only exceptions', 'offline CSP and opt-in update checks', 'stable per-panel snapshots and explicit refresh', 'atomic writes', 'local speech or captions for auto', 'reduced-motion page controls'],
  maintenance: 'references/settings.md',
  compatibility: 'Core requires file access and Node.js 20+. Browser checks optional. See the source acceptance record for exercised platforms; this is not a claim of live testing in every agent product.',
};
writeFileSync(join(skill, 'PROVENANCE.json'), JSON.stringify(provenance, null, 2) + '\n');
console.log(JSON.stringify(provenance.generatedBundle));
