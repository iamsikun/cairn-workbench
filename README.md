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

The current release is 0.1.1 on the `stable` channel. Reference acceptance for
milestones M0–M3 is complete and recorded in [acceptance tracking](docs/acceptance.md),
measured against the [build plan](CAIRN_BUILD_PLAN.md). All of that evidence comes from
synthetic data; see also the [evaluation report](docs/evaluation.md) and
[requirements audit](docs/requirements.md). Passing it does not approve any private deployment, and the
fake provider used in tests does not show that a real model produces useful content.
Cloud processing is not available; no network access is enabled by default.

Do not use this development checkout with private data.

## How it works

Every change to the knowledge base follows one explicit path:

```text
captured → extracted → proposed → validated → approved → applied → indexed
```

- **Sources are evidence.** Captured files are stored as hashed blobs with recorded
  provenance and source locators, so every claim can point back to the exact text.
- **Models propose, the owner decides.** Extraction and drafting run in a pinned,
  offline worker container that receives a bounded job, not your files. Its output is an
  untrusted proposal. It cannot choose where it is written, relax access labels, or
  approve itself; an actor or approval field written by a model carries no authority.
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
- **Read papers with Finch.** Paper reading uses [Finch](docs/finch-reading.md)
  automatically. In a configured agent session inside a knowledge base, each Finch
  answer also saves the discussion and stages a concept-note proposal for your review.
  If Finch is missing, `cairn init` for a private knowledge base runs Finch's installer.
- **Write pages with Quill.** `cairn write begin` prepares a packet for Quill, and
  `cairn write finish` turns the draft into a proposal. `cairn note` makes your own notes
  searchable at once, `cairn inbox` lists what awaits you, and `cairn accept` validates,
  approves and applies proposals in one confirmed step. See [Writing](docs/writing.md).
- **Maintain a journal library.** Catalog a read-only folder of journal PDFs, track what
  is new, and queue readings. See the [journal library](docs/library.md).
- **Track finances and daily life.** Import structured financial snapshots, run exact
  decimal calculations, and keep dated notes and sourced life hubs, with owner, account,
  date, unit and currency kept separate. See [personal domains](docs/personal-domains.md).
- **Export offline HTML views** of project context, queries, evidence, readings,
  proposals, catalogs and journal feeds. See [HTML views](docs/html-views.md).

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
backup and any needed schema migration. It also keeps the knowledge base's Quill copy on
Quill's stable release. Opt in with `cairn init --auto-update` or `cairn update enable`.
See [automatic updates](docs/updates.md) and the [changelog](CHANGELOG.md).

## License

Cairn is released under the [MIT License](LICENSE). The bundled Finch snapshot and the
vendored `answer-me-with-html` keep their own MIT licenses.
