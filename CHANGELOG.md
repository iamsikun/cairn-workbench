# Changelog

Cairn uses semantic versioning. The version lives in `pyproject.toml` and
`src/cairn/__init__.py`, which must agree; managed installs adopt `stable` only when it
increases.

- **Major** releases need owner attention: a changed workspace or record format, a removed
  command, or a changed approval boundary.
- **Minor** releases add commands, workflows or guidance.
- **Patch** releases fix defects without changing behavior otherwise.

## Unreleased

This is a major change (removed commands, changed agent boundary); it is not yet
released or versioned.

- **Agent interface.** New `cairn mcp`: a local stdio MCP server for Claude Code, Codex
  or Cursor with scoped search/evidence/context, the pending queue, proposal review and
  begin/finish tools for reading, writing and drafting. No owner operations are exposed.
  `cairn mcp --print-config` prints registration commands and suggested deny rules.
- **Drafting.** New `cairn draft begin|finish` seals an ingest job for the owner's agent
  under a grant and stages its validated result. Plain `cairn ingest` is now only the
  synthetic `--inline-synthetic` shortcut.
- **Contracts, not skills.** Reading and writing packets carry Cairn-owned contracts.
  Cairn no longer vendors, installs, edits or updates Finch or Quill: `cairn finch
  install|status` and `cairn quill install` are removed, `init`/`restore` no longer set
  up skills, and `cairn update` no longer refreshes them. Existing skill copies are left
  in place. Packets and pending Finch/Quill proposals prepared before this change fail
  with "guidance changed" and must be prepared again.
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
