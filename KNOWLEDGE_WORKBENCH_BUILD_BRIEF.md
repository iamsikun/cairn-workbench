# Knowledge Workbench — Agent Build Brief

Status: proposed implementation specification; this file is not a working application.
Audience: a coding agent implementing a reusable, public-source-code/private-data personal knowledge workbench.
All names, records, accounts, project identifiers, paths, and documents in public examples must be synthetic.

## 1. Objective

Build a small, local-first knowledge workbench that compiles selected sources into a reviewable Markdown wiki. Preserve original evidence and human-authored thinking. Support research, finance, and daily-life domains without giving every agent access to every domain.

The public repository contains software, generic schemas/templates, documentation, and synthetic tests. The user's content, source files, policies, credentials, logs, indexes, context packs, and approvals live outside that repository. The product must function without publishing any user knowledge.

Prefer Python with a src layout, uv, a typed CLI, schema validation, ordinary Markdown/YAML/JSON files, and SQLite FTS5. Use standard library facilities where adequate. Do not build a custom chat UI, agent framework, graph database, hosted service, or vector infrastructure in the first release.

Use existing coding-agent clients as model frontends. Keep durable records independent of any client's hidden conversation state or auto-memory format. A deterministic provider interface and fake model implementation must make the full workflow testable without a paid API.

## 2. Boundaries and defaults

1. Public code and private workspaces must be disjoint after resolving real paths. Reject nested/overlapping roots, path traversal, and unauthorized symlink targets. A .gitignore is defense in depth, not the privacy boundary.
2. Development and CI may see only the public checkout and synthetic fixtures. Never attach a private workspace, a user's home directory, or private credentials to contributor-code execution.
3. Real-data runtime uses a reviewed, pinned installation. Do not automatically run the latest upstream commit against private data.
4. Sources and human-authored notes are read-only to the model. The model produces proposals, not direct edits to canonical files. Policy, approval, publication, deletion, and financial actions are outside model authority.
5. An owner-controlled apply process is the only canonical writer. An actor label or a prompt saying 'human approved' is not authorization. Document and implement a sandbox/permissions profile that prevents a model with shell access from bypassing this separation.
6. Default all data to private and local-only. Public source material is not automatically safe to send with a private question. Cloud processing requires an explicit, separately configured grant.
7. Local-only applies to extraction, embeddings, query expansion, reranking, generation, traces, and error reporting. There must be no silent cloud fallback. Missing local capability produces a clear blocked status.
8. Retrieval permissions apply before search, and also to indexes, titles, snippets, counts, backlinks, graph traversal, caches, and context packs. A domain filter chosen by the model is not an access-control boundary.
9. Imported documents and tool output are untrusted data. They cannot authorize tool calls, edits to instructions, arbitrary code execution, outbound network requests, or access to another domain.
10. No trading, payments, tax filing, message sending, or calendar writes in the knowledge-maintenance toolset. A review date is metadata, not a scheduled reminder.

## 3. Layout

Public checkout:

```text
knowledge-workbench/
  README.md
  AGENTS.md
  pyproject.toml
  uv.lock
  src/knowledge_workbench/
    cli/
    records/
    storage/
    ingest/
    retrieval/
    proposals/
    policies/
    adapters/
  schemas/
  templates/
  examples/synthetic-vault/
  tests/
  docs/
    architecture.md
    threat-model.md
    privacy.md
    recovery.md
    agent-integration.md
  .github/workflows/
```

A separately configured private workspace:

```text
knowledge-private/
  vault/
    inbox/
    sources/
    notes/
    decisions/
    wiki/
      research/
      finance/
      life/
      shared/
    index.md
  blobs/
  policy/
  proposals/
  receipts/
  cache/
```

The vault is readable with any Markdown editor. An Obsidian-specific configuration may be optional, never required for core functionality. Source manifests reference blobs or stable external library identifiers; do not duplicate a bibliography manager's live database.

Version text, manifests, policy, and receipts locally. Keep large blobs in separately backed-up storage and disposable caches out of version history. No Git remote is configured automatically. A machine-local configuration locates all private paths; the public repo ships only an example configuration.

## 4. Durable record model

Give every durable object a stable ID independent of its title/path. Support schema migrations. Start with six useful record types: source, concept, project, decision, entity, and playbook. Human captures can be simple timestamped Markdown without requiring all fields immediately.

Common validated fields:

```yaml
schema_version: 1
id: concept_demo_001
type: concept
title: Example concept
domain: research
classification: private
processing: local_only
status: draft
created_at: 2026-01-01T12:00:00Z
updated_at: 2026-01-01T12:00:00Z
sources:
  - id: source_demo_001
    locator: "section 2, paragraph 3"
```

Source manifests additionally record origin, source type, capture timestamp, source date/version when known, content hash, extraction method/version, and coverage (full text, excerpt, abstract only, or failed). Missing metadata remains unknown; never invent dates or authors.

For material claims, decisions, numbers, and high-stakes records, preserve:

- Assertion kind: reported result, inference, hypothesis, or owner decision.
- Evidence references with page/section/table/line locators and source version/hash.
- Verification state: unreviewed, reviewed, disputed, or superseded. 'Reviewed' does not mean proven true.
- Applicable period and date recorded, when time matters. Support as_of, valid_from/valid_until, tax_year, jurisdiction, statement period, and owner/account alias as applicable, not as mandatory noise on every note.
- Supersedes/disputes links and rationale. A newer document does not automatically override an older source.

A source may be wrong. An AI synthesis is not a new independent source. Citation checks establish that quoted text exists, not that it entails a conclusion. Preserve this distinction in the UI and tests.

Protect human thinking from silent rewriting. Import conversations with roles intact: a user statement, an assistant proposal, a question, and an approved decision are different records. Never infer adoption merely because an assistant recommended something.

## 5. Ingestion and compilation

Implement the following explicit state machine:

```text
captured -> extracted -> proposed -> validated -> approved -> applied -> indexed
```

Failures leave the original capture and a retryable status. They never promote incomplete or unsupported summaries into accepted knowledge.

Ingestion sequence:

1. Capture a source under a stable ID and checksum. Record provenance before invoking a model.
2. Classify scope and allowed processing route. Unknown classification stays restricted.
3. Extract evidence with source locators. Preserve raw files. For image/table-heavy material, record whether those components were inspected; do not claim full coverage from text-only extraction.
4. Retrieve only authorized relevant pages. Propose a source note and a small bounded set of related updates. Do not create a new concept page for every noun.
5. Stage a proposal containing base hashes, proposed files/diffs, citations, affected IDs, route/model identifiers, and rationale.
6. Validate schemas, IDs, references, quote matches, privacy-label propagation, allowed paths, and unchanged source/human files. Require additional owner review for interpretation, conflicting evidence, decisions, and sensitive records.
7. Apply through a single-writer transaction with optimistic concurrency checks, a recoverable journal, and a durable receipt. Reject stale proposals without silently overwriting intervening human edits.
8. Update disposable indexes after successful application. An indexing failure must not corrupt durable files.

Deduplicate by source identity/version/content hash with explicit rules for genuinely revised sources. Re-running the same import should not multiply pages or create meaningless edit churn.

## 6. Query and agent context

Query is read-only by default. Search both evidence and synthesis, label which is which, and retrieve originals for exact wording, numbers, or high-stakes interpretations. Answers should expose sources, relevant date/version, conflicts, and missing evidence. Do not silently replace an unsupported answer with a plausible one.

Start with metadata filters, aliases, keyword search, and SQLite FTS5. Include multilingual titles and English/Chinese cross-language test cases. A hybrid retrieval adapter may be added after a private evaluation demonstrates a material benefit; it must obey the same scope and processing rules.

Define a compact project context pack containing question, objective, constraints, current decisions, relevant literature, failed approaches, open issues, next action, source IDs, and bound repository commit/run IDs. It must not include the global private index or unrelated domains. If code has changed, flag stale context rather than asserting it is current.

At session end, agents return structured receipts: what was tried, what evidence was produced, run/commit IDs, proposed decisions, failures, and unresolved questions. Receipt ingestion creates reviewable proposals. Project code, datasets, checkpoints, and manuscripts stay in their existing project repositories/storage.

Implement CLI commands first. Treat these names as the intended interface, not existing commands:

```text
kw init --workspace PATH
kw capture FILE --domain DOMAIN
kw ingest SOURCE_ID
kw proposal show PROPOSAL_ID
kw validate PROPOSAL_ID
kw apply PROPOSAL_ID
kw search QUERY --scope SCOPE
kw context PROJECT_ID --budget TOKENS
kw lint --scope SCOPE
kw rebuild-index
kw doctor
```

Later, expose read/search/context/propose through a local stdio MCP adapter. Do not expose owner approval/apply, public export, policy mutation, or arbitrary file/shell access through that adapter. A remote server is a separate feature requiring authentication and per-request authorization.

Implemented as `cairn mcp` (see `docs/agent-integration.md`). Its tools return scoped material to the owner's agent, so each call requires an explicit cloud grant for that agent's provider and destination; packet tools export only the sealed, granted request and record an export receipt.

## 7. Domain templates

Research project: research question, claimed contribution, closest literature, assumptions and identification, conjectures versus proven results, data/experiment manifests, negative results, decisions, unresolved issues, and next test.

Paper: stable bibliography-manager ID, citation key, bibliographic metadata, precise claims, assumptions, methods, supporting locators, limitations, connections, and relevance to selected projects. Prefer a read-only bibliography import initially.

Finance: distinguish general educational knowledge, dated official rules/terms, private account/statement snapshots, and owner decisions. Store amounts as structured decimal values with units, currency, as-of dates, and source references. Deterministic tested code performs calculations. No LLM-invented holdings or balances; no wiki text as the accounting ledger. Keep account owners distinct. Preserve investment theses as originally recorded instead of rewriting them after the outcome.

Life: entity-centered hubs for a home, vehicle, pet, or device, with authoritative documents, dated service history, warranty/renewal information, procedures, and decisions. External calendar/task systems remain authoritative for actual reminders and actions.

## 8. Acceptance tests and evaluation

Hard gates before real sensitive-data use:

- Public/private root overlap, traversal, and unauthorized symlink access are rejected.
- The dev/CI profile cannot read the private workspace.
- Source and human-note hashes remain unchanged after model compilation.
- A stale proposal cannot overwrite a newer owner edit.
- Failure halfway through apply recovers without presenting a half-applied bundle as complete.
- Re-ingestion is idempotent and revised sources preserve lineage.
- Fabricated quotes, missing references, invalid schemas, and denied-scope reads are rejected.
- A prompt-injected source cannot mutate policy, approve itself, access another domain, or invoke execution tools.
- Restricted information cannot leak through titles, backlinks, caches, or context packs.
- Local-only runs make no remote requests, including through fallback or telemetry paths.
- Cache deletion and rebuild preserve durable knowledge.
- Backup restore reconstructs both text and referenced evidence blobs.
- The system does not treat an assistant suggestion as an approved user decision.

Build a small synthetic gold set covering exact-source questions, multi-source synthesis, contradictions, outdated rules, absent evidence, multilingual retrieval, and project context. Keep the owner's real evaluation set private. Measure citation support, useful answer quality, unauthorized disclosure, write correctness, review burden, latency, and model cost. Do not claim that passing deterministic tests proves semantic truth or complete security.

## 9. Delivery milestones

M0: public/private separation, schemas, Markdown storage, synthetic demo, no-network fake-model tests, and security defaults.

M1: one complete capture-to-approval ingestion path, source-aware query, local history, crash recovery, and rebuildable search. Demonstrate failure and recovery, not only the happy path.

M2: read-only bibliography adapter and project context/receipt workflow. Validate that another agent session actually uses a recorded decision and avoids a previously failed approach.

M3: dated finance/life templates, processing-route enforcement, restore test, and user-facing source/conflict review.

M4: optional MCP, hybrid search, and multi-device capture only after the core is reliable. Retain a single canonical apply writer. Do not sync live index databases across machines.

Implement milestones in isolated commits, run their acceptance tests, and continue automatically when gates pass. Do not require a generic 'what next?' interaction after every stage. Stop before any unauthorized external write, publication, destructive operation, or privacy-boundary change. Report unimplemented controls and failing tests explicitly; never describe a scaffold or mocked adapter as production-ready.
