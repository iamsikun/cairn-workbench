# Cairn

**A local-first knowledge base that AI agents can propose changes to but never edit.**

Cairn turns the sources you select (papers, PDFs, bibliographies, agent sessions,
financial statements, notes) into a reviewable Markdown wiki, plus scoped context packs
for coding agents. Your original sources and your own notes stay untouched. A model only
proposes changes, and nothing enters the knowledge base until you approve and apply it.

This repository, `cairn-workbench`, contains the software. Your knowledge base is a
separate private directory (by convention named `cairn`) that lives outside this checkout
and is never committed. The Python package and the command are both named `cairn`.

## Status

The current release is 0.2.0 on the `stable` channel. Reference acceptance for
milestones M0–M3 is complete and recorded in [acceptance tracking](docs/acceptance.md),
measured against the [build plan](CAIRN_BUILD_PLAN.md). All of that evidence comes from
synthetic data; see also the [evaluation report](docs/evaluation.md) and
[requirements audit](docs/requirements.md). Passing it does not approve any private deployment, and the
fake provider used in tests does not show that a real model produces useful content.
Cairn opens no network connection itself; models are reached only through your own
agent, under explicit grants.

Do not use this development checkout with private data.

## How it works

Every change to the knowledge base follows one explicit path:

```text
captured → extracted → proposed → validated → approved → applied → indexed
```

- **Sources are evidence.** Captured files are stored as hashed blobs with recorded
  provenance and source locators, so every claim can point back to the exact text.
- **Models propose, the owner decides.** Extraction runs in a pinned, offline worker
  container. Reading, writing and drafting happen in the agent you already use (Claude
  Code, Codex, Cursor), which reads scoped material through Cairn's tools, not your
  files. Its output is an untrusted proposal. It cannot choose where it is written,
  relax access labels, or approve itself; an actor or approval field written by a model
  carries no authority, and owner commands need your own terminal.
- **One recoverable writer.** Applying an approved proposal revalidates it under a lock,
  journals the before and after bytes, and records local Git history, so an interrupted
  write can be recovered.
- **Retrieval is scoped.** Access scope, classification and domain (research, finance,
  daily life) are enforced before search, so an agent working on one project does not see
  another domain's titles, snippets or counts.

Records are ordinary Markdown, YAML and JSON. Search uses SQLite FTS5 indexes that are
rebuilt from the canonical records. The [architecture](docs/architecture.md) and
[threat model](docs/threat-model.md) describe these boundaries in detail.

## What you can do with it

- **Build a research wiki.** Capture text, PDFs and conversations; import CSL-JSON
  bibliographies; review and apply proposals; search evidence and synthesis; back up and
  restore. See the [review procedure](docs/review.md) and [recovery](docs/recovery.md).
- **Keep research continuity across agent sessions.** Create projects, import attributed
  session receipts, adopt decisions explicitly, and generate bounded context packs with
  verified citations and repository-staleness checks. See
  [research continuity](docs/research-continuity.md).
- **Work from your agent.** `cairn mcp` is a local stdio MCP server for Claude Code,
  Codex or Cursor. Your agent searches the knowledge base, reads papers (with Finch, if
  you have it), writes pages (with Quill, if you have it) and drafts pages from sources;
  each result is staged as a proposal for your review. Cairn never edits or installs
  those skills. See [agent integration](docs/agent-integration.md).
- **Connect papers to notebooks.** Follow-up readings revise one paper note while
  preserving each exchange separately. Topic notebooks are ordinary concept pages;
  the agent proposes note and notebook updates together for one owner acceptance.
- **Review and accept.** `cairn note` makes your own notes searchable at once,
  `cairn inbox` lists what awaits you, and `cairn accept` validates, approves and
  applies proposals in one step you confirm at your terminal. See [Writing](docs/writing.md).
- **Maintain a journal library.** Catalog a read-only folder of journal PDFs and track
  what is new. See the [journal library](docs/library.md).
- **Track finances and daily life.** Import structured financial snapshots, run exact
  decimal calculations, and keep dated notes and sourced life hubs, with owner, account,
  date, unit and currency kept separate. See [personal domains](docs/personal-domains.md).
- **Export offline HTML views** of project context, queries, evidence, readings,
  proposals, catalogs and journal feeds. Requested notebook HTML includes linked
  paper notes and refreshes after accepted Markdown updates. Configure `--html-root`
  for chat requests; use `cairn view sync` after direct editor changes. Markdown
  remains the source of truth. See [HTML views](docs/html-views.md).

Run `cairn --help` for the full command list. Most commands take `--workspace` (or
`CAIRN_WORKSPACE`), and `--json` gives structured output.

## Development

Contributors work only with synthetic data, inside the development container. Never
mount a home directory, a private knowledge base, credentials, or the Docker socket.

```sh
bash scripts/check.sh           # build images; run tests, lint, strict typing,
                                # isolation probes and installed-CLI trials
bash scripts/release_check.sh   # on a clean commit: pinned wheelhouse + offline install trial
```

Create development fixtures with `cairn init --synthetic`. See
[synthetic development](docs/development.md) for the container profile and
[AGENTS.md](AGENTS.md) for the rules every change must follow.

## Using Cairn with your own knowledge base

A private knowledge base requires a reviewed, pinned installation, explicit owner
acknowledgements, and a fresh check that the worker is isolated. Follow the
[installation runbook](docs/installation.md), then read the
[processing policy](docs/privacy.md) and [agent protocol](docs/agent-integration.md)
before choosing how models run. Format changes are handled by an explicit, backed-up
[schema migration](docs/schema-migrations.md).

After a one-time `cairn update setup`, Cairn checks its `stable` branch hourly and when
`cairn` starts (at most once a day). When the version number increases, it builds,
verifies and installs the new release, then rebinds each opted-in knowledge base with a
backup and any needed schema migration. Opt in with `cairn init --auto-update` or `cairn update enable`.
See [automatic updates](docs/updates.md) and the [changelog](CHANGELOG.md).

## License

Cairn is released under the [MIT License](LICENSE). The vendored `answer-me-with-html`
renderer keeps its own MIT license.
