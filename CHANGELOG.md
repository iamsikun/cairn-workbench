# Changelog

Cairn uses semantic versioning. The version lives in `pyproject.toml` and
`src/cairn/__init__.py`, which must agree; managed installs adopt `stable` only when it
increases.

- **Major** releases need owner attention: a changed workspace or record format, a removed
  command, or a changed approval boundary.
- **Minor** releases add commands, workflows or guidance.
- **Patch** releases fix defects without changing behavior otherwise.

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
