import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';
const root = fileURLToPath(new URL('../skills/answer-me-with-html/', import.meta.url));
test('portable skill frontmatter follows the Agent Skills entry-point fields', () => {
  const source = readFileSync(root + 'SKILL.md', 'utf8');
  const frontmatter = parse(source.split('---')[1]);
  assert.equal(frontmatter.name, 'answer-me-with-html');
  assert.ok(frontmatter.description.length <= 1024);
  for (const key of Object.keys(frontmatter)) assert.ok(['name', 'description', 'license', 'compatibility', 'metadata', 'allowed-tools'].includes(key));
  assert.doesNotMatch(source, /\$ARGUMENTS|CLAUDE_SKILL_DIR|argument-hint|always-on|file:\/\//);
  for (const [, ref] of source.matchAll(/\]\((references\/[^)]+)\)/g)) assert.ok(existsSync(root + ref), ref);
});
