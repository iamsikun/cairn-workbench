# Settings and staged maintenance

Resolve `scripts/am.mjs` relative to the loaded skill. Inspect with `node "<skill directory>/scripts/am.mjs" config`. Change only what the user requested with `config set <key> <value>`; `config reset <key>` restores that key's default.

Settings include `open`, `theme`, `mode`, `style`, `voice`, and `update_check`. Update checks default to off. Explicitly stored preferences remain in effect; an offline processing run can set `AM_NO_UPDATE_CHECK=1` without altering them. `--no-open` suppresses opening for one run. Raw HTML and network-resource exceptions are flags, not persistent settings.

The data directory defaults to `.answer-me-with-html` under the operating system's user home; `AM_HOME` can select another directory. Skill replacement must not reset settings or delete pages, videos, themes, or caches. Never infer cleanup permission from a hint. For requested cleanup, inspect `clean --dry-run` and apply the user's stated scope; retain settings and unrelated files.

## Staged updates

This is a maintained portable fork. Do not use generic self-update commands or replace it directly from a moving upstream branch.

1. Read package `PROVENANCE.json` and the maintained project's acceptance record. Acquire a specific public upstream commit into separate staging, preserving licenses. Do not configure a remote or publish unless requested.
2. Compare upstream with the pinned base and local changes. Retain explicit-HTML routing, relative resources, offline defaults, invocation permissions, path containment, stable patches, recoverable writes, and local-only automatic speech selection.
3. Modify source modules; never hand-edit generated `scripts/am.mjs`. Acquire lockfile dependencies separately from contributor execution. Build and run regression, packaging, and available browser checks in isolation with synthetic fixtures and no credentials, private mounts, Docker socket, or external network during processing.
4. Rebuild and compare bundle checksums. Review intended snapshot differences. Record upstream commit, checksum, executed checks, failures, skips, and compatibility limits. Skipped browser coverage is not a passing gate.
5. After validation, back up the existing skill outside discovery directories. Copy maintained package files into the requested existing destination, preserving unrelated files and all user data/settings. Verify installed checksums. Retain backup and rollback instructions. Do not discover or modify other agents' installations automatically.

Other agents receive the same portable package. Registration and delivery are host-specific; only claim live compatibility with products actually exercised.
