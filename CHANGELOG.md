# Changelog

## 0.4.0 — local restructuring build; unpublished

- Direct versioned saves, revision checks, recoverable transactions, checkpoints and undo.
- Connected paper notes, topic learning notebooks, attributed observations and explained links.
- Six scoped MCP tools, native optional extraction, and Claude Code/Codex registration.
- Explicit HTML companions with dependency freshness, snapshots, feedback and scenarios.
- Backed-up schema 1–3 migration to schema 4 and managed-installation retirement.
- Ordinary saves no longer require proposals, grants, activation or release rebinding.
  Historical validators and provenance remain available for legacy data.

Cairn uses semantic versioning. The version lives in `pyproject.toml` and
`src/cairn/__init__.py`, which must agree; managed installs adopt `stable` only when it
increases.

- **Major** releases need owner attention: a changed workspace or record format, a removed
  command, or a changed approval boundary.
- **Minor** releases add commands, workflows or guidance.
- **Patch** releases fix defects without changing behavior otherwise.

## Unreleased

This changes the workspace format, which the versioning policy above treats as a
major change. The version number is not yet advanced.

- **A knowledge base can name Cairn's code by repository.** Workspace schema 3 adds
  an optional `code_repository` and makes the local `code_roots` optional; at least
  one is required. `cairn init` accepts `--repository URL`, and `--code-root` is
  optional. A managed install defaults the repository to `updater.json`'s, so it
  needs no checkout. Configured checkout paths stay guarded against the workspace,
  backups, HTML outputs and the library root, and a workspace under any `.git`
  ancestor is still rejected.
- **Owner command `cairn code-source set`** changes the checkout paths or repository
  of an existing knowledge base under the owner writer lock, with a receipt under
  `receipts/code-source/`. It is not exposed to agents.
- **Supported migration `workspace_v2_to_v3`.** Schema 1 and 2 workspaces stay valid
  and are not rewritten when read. `cairn schema apply` (or an automatic update)
  migrates them one version at a time, each with a backup. Existing code roots are
  kept.
- `cairn restore` keeps the archived code source unless `--code-root` or
  `--repository` is given.

## 0.3.0 — 2026-10-10

- **Evolving paper notes and connected topics.** Follow-up readings revise the same
  paper note, with each exchange preserved as immutable provenance. Topic notes
  (notebooks) are ordinary Markdown concept pages. Agents can propose a paper note
  and related topic updates together, with stale-update checks and one owner
  acceptance. Evidence and page tools expose authorized existing notes and links.
- **Requested HTML stays synchronized.** Markdown is the source of truth. Explicit
  chat requests use an owner-configured `--html-root`; owners can also run
  `cairn view page RECORD_ID --format html --output PATH`. Views include directly
  linked paper notes and refresh after accepted Markdown changes. `cairn view sync`
  incorporates editor changes and retries failures. Output conflicts preserve the
  existing file; restored registrations stay inactive until rebound by the owner.
- **Reliable capture and writing.** Large papers support bounded citation selections
  without truncating evidence. Content-based capture identity deduplicates renamed
  files while separating filename collisions; explicit identity/version supports
  revisions. Context includes project Markdown and attached concept content, and
  project membership carries through capture, new notes and revisions.
- **Current authorization at retrieval.** Search filters the corpus before ranking.
  Pending proposals and review recheck current scope and route grants, including
  linked records, and record export receipts without exposing inaccessible counts.
- Existing records, proposals, receipts and snapshot views remain readable. The
  six record types and owner approval boundary are unchanged. HTML remains optional;
  there is no background agent, classifier service or filesystem watcher. Validation
  used synthetic data only; see [acceptance evidence](docs/acceptance.md).

## 0.2.0 — 2026-10-10

This release removes commands and changes the agent boundary; read it before
upgrading. Upgrading from 0.1.x needs one manual step: run `uv run cairn update run`
from an up-to-date checkout (see `docs/updates.md`).

- **Agent interface.** New `cairn mcp`: a local stdio MCP server for Claude Code, Codex
  or Cursor. Read tools (search, evidence, page, context, view, feedback, capture,
  pending, proposal_show) and one-call `propose_reading`, `propose_page`,
  `propose_changes` and `propose_explanation`, which seal their inputs and validate the
  answer in the same step. Each read leaves a receipt. No owner operations are exposed.
  `cairn mcp --print-config` prints registration commands and sandbox settings.
- **Owner commands need your terminal.** `approve`, `accept`, `apply`, policy changes,
  `schema apply` and `update enable|disable` ask you to type the action at your
  terminal; `accept --yes` is removed. Agent shells have no terminal and are refused.
- **Contracts, not skills.** Cairn's contracts travel with the `propose_*` tools.
  Cairn no longer vendors, installs, edits or updates Finch or Quill: `cairn finch`,
  `cairn quill install` and `cairn write` are removed, `init`/`restore` no longer set up
  skills, and `cairn update` no longer refreshes them. Existing skill copies are left in
  place. Proposals staged before this change stay approvable; the contract is checked
  when an answer arrives, not again at approval.
- **Drafting.** Turning a source into pages is the agent's `propose_changes`. Plain
  `cairn ingest` is now only the synthetic `--inline-synthetic` shortcut.
- **Explanations.** Agents keep view explanations with `propose_explanation`; render
  them with `cairn view explanation JOB OUTPUT`.
- **Compatibility flags removed.** `init --no-quill/--no-finch` are gone. A 0.1.x
  updater passes them when smoke-testing a new runtime, so after this release run the
  new updater once from the checkout (`uv run cairn update run`).
- **Retired.** The docker client route (`cairn client run`), the offline library reader
  (`library read|jobs|retry|cancel|worker|verify|verification-configure`), owner devices
  and subscription verifiers. Library scan, discovery, catalog and feeds remain. Old
  reader receipts are kept but no longer interpreted.

## 0.1.1 — 2026-10-10

- Documentation: rewrite the README for clarity and add the MIT license. No change in
  behavior.

## 0.1.0 — 2026-10-10

- First release on the `stable` channel: M0–M3 workflows, Finch reading, Quill writing,
  HTML views, journal library, and automatic updates of the managed runtime and the
  knowledge-base Quill.
