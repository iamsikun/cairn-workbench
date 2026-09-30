# Cairn build plan

Status: M0–M3 reference acceptance complete. Executed checks and the limited manual M2
assessment are recorded in `docs/acceptance.md` and `docs/release-audit.md`. Private
deployment and owner release acceptance remain separate.

This plan translates `KNOWLEDGE_WORKBENCH_BUILD_BRIEF.md` into an implementation sequence. The brief remains the requirements baseline. Product name, Python import package, and CLI name will be `Cairn`, `cairn`, and `cairn`. Public examples must use synthetic identities, records, and paths.

The software repository is named `cairn-workbench`; the separate private knowledge-base
directory is named `cairn`. These names do not change the Python package or CLI.

## 1. Intended result and scope

### Authorized journal-library follow-on

The follow-on adds an owner-maintained journal/paper catalog, public publication
discovery, bounded inference on an enrolled owner workstation, subscription-based
sample verification, and a weekly saved feed. The canonical writer stays on the owner
Mac. Development uses synthetic inputs only. The local reader targets Qwen3.5-9B with
a pinned CUDA/WSL2 runtime; live hardware, quality, transport, and isolation are separate
activation gates. Public metadata fetchers and subscription-verifier transports are
trusted, separately scoped components; extraction/inference workers remain offline.
Model checks never confer owner approval or mark personal reading as complete.

All older papers are cataloged; reading is selective. Weekly updates cover new
publications and archive additions. Initial calibration checks ten readings with both
verifiers; ongoing sampling is 10% plus flagged results. Digest scheduling defaults to
Monday 09:00 America/Chicago, using a thread heartbeat after reviewed activation.
Detailed operational behavior and actual evidence are recorded in `docs/library.md`
and `docs/acceptance.md`; this authorization is not a claim of deployment readiness.

Implementation now includes all three software stages. The separate
`docs/library-deployment.md` records pinned artifacts, bounded export consent, deterministic
sampling cohorts, saved feeds, and the hardware/quality/installation gates. The owner
transport process needs a compatible reviewed installation with access to the official
host SSH and subscription clients. The reference Linux release does not by itself
provide a native macOS installation or inherit host credentials. Preserve this distinction
during deployment; do not widen an inference container to make a transport work.

Cairn will be a local knowledge compiler with a review queue. It will preserve evidence and human thinking, propose bounded improvements to a Markdown wiki, and supply scoped, source-aware context to existing agent clients.

The first release covers M0–M3 from the brief. Build one reliable research workflow first, then add project continuity and finance/life records. M4 is a separate follow-on: no custom chat interface, hosted service, remote MCP, vector database, or multi-device synchronization is required for the first release.

The first useful demonstration is:

1. Capture a synthetic paper excerpt and a human research note.
2. Extract evidence with stable locators and declared coverage.
3. Propose a source summary and an update to one existing project page.
4. Review the diff, evidence, conflicts, and processing route.
5. Approve and apply the exact proposal.
6. Search both evidence and synthesis; build a project context pack.
7. Import another agent session's receipt as a proposal.
8. Repeat the import without churn, reject a stale proposal, and recover an interrupted apply.

## 2. Physical separation and installation

Keep two independent roots: a public software checkout and an owner-controlled private workspace. The user's intended deployment places the private `cairn` workspace alongside the parent research directory, outside the checkout. Store the actual absolute paths only in machine-local configuration. Documentation examples use `/srv/cairn-workbench` and `/srv/cairn`.

Initialization must resolve both roots and reject equal roots, ancestor/descendant overlap, traversal, and symlink escape. Check configured auxiliary roots too: blobs, temporary files, logs, history, and caches must not bridge the boundary. Reject a private root inside any development checkout even if ignored by Git. Apply containment checks again at file access, rather than trusting initialization alone. Reject proposal-created symlinks, hard links, special files, absolute destinations, and ambiguous case/Unicode path collisions; use descriptor-relative, no-follow operations where supported.

Development uses the source checkout and synthetic fixtures. Private operation uses a reviewed wheel and pinned dependency artifacts installed outside that checkout. Record the code revision, wheel digest, dependency lock digest, runtime version, and adapter versions. An editable installation must fail the private-runtime readiness check. Dependency/model acquisition happens separately from data processing; processing never installs or updates software.

Use `uv` for development and locked build preparation. Build a wheel plus a hashed dependency manifest/wheelhouse for an offline private installation. A virtual environment separates dependencies; it does not isolate filesystem access. [uv documents editable project installs](https://docs.astral.sh/uv/concepts/projects/sync/) and [separate tool environments](https://docs.astral.sh/uv/concepts/tools/); neither substitutes for the execution controls below.

At planning time the checkout contained only the brief and was not a Git repository.
Implementation initialized local Git history. No automatic remote, push, package
publication, or private-workspace initialization is authorized.

## 3. Execution and authority

Use three explicit execution profiles:

| Profile | Inputs | Writable outputs | Authority |
| --- | --- | --- | --- |
| Development/CI | Public checkout, dependencies, synthetic fixtures | Build/test artifacts | No private mounts, home directory, or private credentials |
| Model/extraction worker | A bounded, authorized input bundle; pinned tools | Per-job staging directory | No canonical writes, policy changes, approval, shell tools supplied by Cairn, or default network |
| Owner runtime | Private records and policy | Canonical records, approvals, journal, receipts, derived indexes | Trusted capture/extraction registration and reviewed application |

The owner runtime is a small CLI process, not a continuously running privileged web service. All Cairn-managed durable writes use its shared writer/locking layer. Capture and extraction registration append evidence; proposal application edits managed synthesis. Human-authored notes remain owner-authored and are never an apply target.

Use an isolated Linux container profile as the first enforceable reference profile on macOS and in CI: explicit mounts, non-root worker, read-only root filesystem and inputs, bounded scratch space, no host home, no Docker socket, no credential forwarding, dropped capabilities, and no outbound network. The trusted launcher creates the input bundle; workers never mount the whole vault. The development runner mounts only public material. Build-time downloads use a separate environment with no private inputs. Docker documents [read-only mounts and runtime flags](https://docs.docker.com/engine/containers/run/) and [network isolation using the none driver](https://docs.docker.com/engine/network/drivers/none/).

Container controls are the selected initial implementation approach, not a claim of protection against a compromised host or container engine. Test the actual profile, including hostile subprocesses, rather than only mocking application checks. If that profile is unavailable, report `blocked: isolation_unavailable`; synthetic unit tests may still run, but private operation is not ready. A native sandbox can be added later after equivalent tests pass.

A host coding agent with access to the owner's files or container daemon cannot be made safe by an actor flag, approval prompt, or instructions file. Such a session must not receive the private root. Existing clients interact through scoped packets or a constrained process boundary. Until a client has a verified local processing route, exporting to it requires an explicit cloud-processing grant.

Approval is an owner operation. Add `cairn approve PROPOSAL_ID` to the brief's interface, separate from `validate` and `apply`. The approval binds the workspace ID, complete proposal digest, base hashes, evidence versions, policy revision, approved route, and review acknowledgements. The worker cannot write the approval store or invoke an owner endpoint. Any change invalidates approval. An `approved: true` value inside model output has no authority.

V1 requires owner approval for every canonical synthesis change. Sensitive interpretations, conflicts, and owner decisions receive explicit review flags. Automatic approval is permitted only inside synthetic tests; it must not become a real-data CLI bypass.

## 4. Code and storage layout

Use Python with a `src` layout, `uv`, Typer for the CLI, Pydantic for typed validation and generated JSON Schema, and a safe YAML parser for front matter. Prefer `sqlite3`, `hashlib`, `decimal`, `pathlib`, and other standard-library facilities elsewhere. Pin exact dependency versions during implementation. Do not introduce an ORM, plugin discovery from source documents, or an agent framework.

```text
cairn-workbench/               # public software checkout
  pyproject.toml
  uv.lock
  src/cairn/
    cli/                       # argument parsing and structured output
    records/                   # schemas, assertions, migrations
    storage/                   # safe paths, Markdown, blobs, history
    policies/                  # scopes, labels, processing routes
    ingest/                    # capture, extraction, source lineage
    proposals/                 # manifests, validation, review
    transactions/              # approval, writer lock, journal, recovery
    retrieval/                 # evidence chunks, scoped indexes, ranking
    context/                   # project packs and session receipts
    adapters/                  # fake provider, client packets, bibliography
  schemas/                     # generated and checked against Python models
  templates/
  examples/synthetic-vault/
  tests/
  docs/
  .github/workflows/
```

```text
cairn/                        # private knowledge base; configured separately
  vault/
    inbox/
    sources/                   # source manifests; trusted append/versioning
    notes/                     # human writing; never rewritten by a model
    decisions/                 # owner-approved decision records
    wiki/{research,finance,life,shared}/
    index.md                   # owner-wide navigation; never an agent default
  blobs/                       # original bytes, content addressed
  evidence/                    # immutable extracted text and locator maps
  policy/                      # workspace policy, scopes, route grants
  proposals/
  approvals/
  receipts/                    # durable operation events and apply receipts
  journal/                     # recoverable transaction artifacts
  cache/                       # disposable indexes, working packs, scratch
```

Text, manifests, policy, evidence metadata, approvals, and receipts have local history. Large originals and large extraction artifacts use the separately backed-up content store with a manifest of referenced hashes. No Git remote is configured automatically. Use explicit path allowlists for history operations and disable hooks in application-managed history commands. Secrets are stored separately from versioned policy; policy contains credential references only.

`evidence/` is a deliberate addition to the brief: text and locator maps that justify accepted citations must survive cache deletion. Search chunks can be rebuilt from this evidence. Important context-pack manifests and session receipts are durable records; regenerable pack renderings can be cached. None of these artifacts belongs in the public checkout.

## 5. Records, evidence, and provenance

Start with the six requested record types. Use random, type-prefixed stable IDs; titles and paths may change without changing identity. All structured records carry a schema version. Small human captures can remain loose Markdown until explicitly promoted through a proposal.

Keep three concepts separate:

- A source manifest identifies immutable source bytes or a stable external library record, version, origin, date when known, checksum, and extraction coverage.
- A source summary is managed synthesis referencing that manifest. It lives under `wiki/` and is never represented as a new independent evidence source.
- A claim/assertion is a typed component of a record, with its own ID, assertion kind, evidence locators, verification state, relevant dates, and disputes/supersedes links. It need not become a seventh top-level page type.

Typed assertions support numbers, consequential conclusions, and decisions without requiring a citation for every connecting sentence. Body anchors can refer to assertion IDs. Unknown metadata stays null/absent. A decision cannot acquire `owner_decision` or an approved status from an assistant's recommendation; owner adoption must be explicit in the review record.

Extraction produces immutable evidence segments with raw-source hash, extraction artifact hash, extractor/version, page/section/line locators, and original text. Preserve the normalization rules used for quote matching. Distinguish full text, excerpt, abstract-only, and failed extraction, with independent flags for tables/images inspected. Text-only PDF extraction never implies that figures or tables were reviewed.

Deduplication uses source identity, version, and content hash. Identical bytes can share blob storage while retaining different origins or restricted metadata. Revised bytes preserve the previous version and lineage; an apparent version conflict is surfaced for review. Repeating the same import must not change timestamps, generate duplicate pages, or issue a new non-empty proposal without a substantive difference.

Conversation imports preserve roles, order, timestamps when available, and provenance. Session proposals and adopted owner decisions remain distinct. Schema migrations run through the owner writer with a backup/preview, never implicitly while reading.

## 6. Policy before retrieval or generation

Treat domain, confidentiality, and processing permission as different dimensions. `research`, `finance`, `life`, and `shared` organize content; a directory or model-selected `--scope` does not authorize access. `shared` is still private unless separately granted.

An owner-created scope defines permitted record/project/domain membership, sensitivity limits, and processing routes. The trusted launcher binds a session to that scope. Command arguments may narrow it but cannot widen it. A scope credential/configuration is never taken from an imported document or model output.

Derived records inherit the strictest confidentiality and the intersection of allowed processing routes. For information requiring multiple access compartments, record all required compartments and require all of them for subsequent reads. A destination directory cannot weaken those requirements. Owner-controlled reclassification is a separate audited operation outside model proposals.

Build indexes from authorized records into a scope-specific database or equivalent isolated corpus. Do not expose a global database and filter only returned rows: term statistics, counts, errors, titles, snippets, backlink targets, and ranking can all reveal excluded information. Key indexes, result caches, and context packs by effective access set, policy revision, and source generation. Revoked or stale scopes fail closed and require regeneration.

The processing decision covers the complete request: question, instructions, evidence, retrieved notes, derived metadata, output handling, and traces. Public evidence paired with a private question is still private processing. No cloud grant means no cloud generation, translation, reranking, extraction, telemetry, or error upload. No credential presence or model preference implicitly grants export.

M0 models the route policy and denies cloud processing. M1 enforces it at every existing adapter boundary. M3 completes owner grant configuration and audit coverage; cloud adapters are not required for the first release. A grant, when supported, specifies data scope, operation, destination/provider, validity, and explicit owner consent. Existing-client job export is subject to the same check.

## 7. Capture, proposal, and model interface

Keep the required successful state sequence:

```text
captured -> extracted -> proposed -> validated -> approved -> applied -> indexed
```

Persist operation events outside the cache. Record stage, retryable failure/block reason, attempt ID, and input/output hashes. A failure does not advance the successful state. An index failure leaves an applied transaction with indexing pending. Source versions and proposal runs have separate identities, so revised sources do not erase prior workflow history.

Build capture/extraction for Markdown and plain text first, followed by a pinned local text-PDF extractor and conversation JSON. V1 consumes files; it does not automatically crawl links or fetch arbitrary URLs found in documents. Unsupported scans/OCR and uninspected tables are explicitly partial or blocked. Bibliography import follows in M2.

Define a small provider protocol: an immutable structured job containing only approved inputs, and a validated structured result containing proposed record changes and citations. It has no tools for shell execution, policy, approvals, network requests, or canonical writes. Separate deterministic extraction, retrieval, and validation from model generation.

Implement two provider paths:

1. `FakeProvider`, deterministic and offline, for the complete test/demo workflow, including malformed and adversarial responses.
2. `ClientPacketProvider`, which prepares a bounded job for an existing agent client and accepts its structured response. Bind responses to job ID, input digest, route, and provider metadata. Pending external work has a resumable status. This is a file protocol, not a new chat client.

Real client execution requires a demonstrated processing route and isolation profile. A local client that is not installed or cannot prove its configured route yields a blocked status. Do not label the fake provider or a packet-export scaffold as a working local model. A concrete automated local-client adapter can be added after a synthetic capability trial; it is not necessary to test the application without a paid API.

The initial proposal budget is one source summary plus at most three related-page changes, configurable only by the owner. Prefer updating existing records. Each proposal includes base hashes, candidate bytes, computed diffs, affected IDs, evidence versions, route/provider identifiers, policy revision, rationale, and review flags. The owner runtime computes paths and diffs; it does not execute a model-authored patch or shell fragment.

Validation covers schemas, bounded sizes, duplicate IDs, reference/locator existence, quote matches, assertion structure, label propagation, allowed target classes, and immutable source/human-note hashes. It reports semantic review requirements separately. Quote existence is not entailment, and `reviewed` is not a truth guarantee.

## 8. Apply, concurrency, and recovery

SQLite transactions do not make arbitrary Markdown file writes atomic. Cairn needs its own file transaction protocol; SQLite's documented atomicity applies to its [database transaction machinery](https://www.sqlite.org/atomiccommit.html).

Use a single workspace writer lock and a durable journal:

1. Acquire the lock; finish or block on recovery of any previous incomplete transaction.
2. Revalidate the sealed approval, policy revision, all base hashes, and referenced evidence versions.
3. Stage final bytes and before-images on the same filesystem as their targets. Persist a transaction manifest and prepared status; flush data and metadata.
4. Replace allowed files with atomic per-file replacements, recording enough information to recognize every before/after state after a crash.
5. Verify final hashes; write the durable receipt/commit marker. Repeated application of that proposal returns the same receipt.
6. Record local history and publish updated derived indexes after the durable file commit. A history/index failure remains an explicit retryable maintenance state.

All Cairn readers honor the transaction lock and refuse to serve an unresolved partial transaction as committed knowledge. Recovery compares observed files with journaled before/after hashes and completes or restores deterministically. Unexpected third-party edits cause a recovery conflict with preserved bytes; recovery must not blindly overwrite them. Inject process termination at every meaningful boundary, including between receipt creation and later maintenance.

Ordinary editors can read the vault. Direct owner edits made between operations invalidate affected proposal hashes as expected. For concurrent editing of managed wiki/decision records, provide `cairn edit ID` using a staged editor session and the same writer protocol. No plain multi-file directory can promise atomic visibility or protect simultaneous writes from an arbitrary editor that ignores its lock. Document this limitation explicitly. Human notes are separate files and never application overwrite targets.

Do not implement model-requested deletion in v1. Superseding a record preserves it and its provenance. Retention/deletion and policy migration remain owner maintenance operations.

## 9. Retrieval, answers, and project continuity

Search indexes evidence and synthesis separately and labels each hit. Return IDs, locators, source version/date, coverage, verification state, and conflicts where relevant. Exact wording and numbers lead back to evidence. A read-only `cairn query` can use the provider interface for synthesis, while `cairn search` remains usable without a model. Missing support produces an explicit insufficient-evidence result.

Start with metadata, aliases, and FTS5 lexical ranking. Add deterministic Chinese substring handling and curated bilingual aliases. SQLite's default Unicode tokenizer does not segment Chinese words, and its trigram full-text matching does not cover queries shorter than three characters; include an authorized-corpus short-query fallback. This follows the documented [FTS5 tokenizer behavior](https://www.sqlite.org/fts5.html). Cross-language lexical matching is limited to available aliases; do not claim general semantic translation. The gold set must test both two-character Chinese queries and English/Chinese aliases.

Context packs are bounded, project-specific artifacts with question, objective, constraints, adopted decisions, relevant literature, failed approaches, open issues, next action, source IDs, and repository/run bindings. Keep evidence references when trimming. Report omitted sections and token-budget estimates; use exact model tokenization only when a pinned local tokenizer is available. Never include the global private index.

Record repository commit and working-tree/manifest fingerprints. Changed or unverifiable bindings mark the pack stale or unverified. Repository inspection is read-only and explicitly scoped; project code, data, checkpoints, and manuscripts stay in their existing storage. Session receipts record attempted work, resulting evidence, commit/run IDs, proposed decisions, failures, and unresolved questions. Their ingestion follows the same proposal and approval path.

M2's continuity test uses two isolated sessions: the second receives only the approved context pack and demonstrates use of a recorded decision and avoidance of a documented failed approach. A deterministic fake verifies the protocol; a real-client synthetic trial separately evaluates usefulness. Do not treat a mocked session as semantic proof.

## 10. CLI and operator experience

Preserve the brief's commands with the `cairn` prefix. Add a few commands needed to make omitted steps explicit:

| Workflow | Commands |
| --- | --- |
| Setup and diagnostics | `init`, `doctor` |
| Evidence and synthesis | `capture`, `ingest`, `proposal show`, `validate` |
| Owner control | `approve`, `apply`, `edit`, `recover` |
| Reading | `search`, `query`, `context`, `lint` |
| Maintenance/integration | `rebuild-index`, `receipt import`, `backup`, `restore` |

Provide readable output and a stable `--json` mode with distinct exit statuses for validation failure, denied access/route, conflict, blocked capability, and recovery needed. `doctor` separates synthetic functionality from readiness for private operation. It reports missing controls explicitly and does not silently fix permissions, install models, start services, or grant cloud access.

Review output should show a compact change summary, affected records, before/after diff, clickable local evidence locators, temporal conflicts, and explicit decision/sensitive-review prompts. Use terminal output and Markdown reports. Terminal controls and active content in imported text must be escaped; source links are not automatically fetched.

## 11. Milestones and exit gates

| Stage | Deliverable | Required evidence before proceeding |
| --- | --- | --- |
| M0a: contracts | Initialize public Git/project, docs, schemas, synthetic vault, safe storage, CLI skeleton | Schema round trips; source/human preservation; root/path rejection; no real paths/data in fixtures |
| M0b: execution boundary | Development and worker profiles, scoped jobs, route denial, fake provider | Hostile worker cannot read an unmounted synthetic private canary, alter canonical/policy/approval files, or send remote traffic; test fails closed if profile absent |
| M1a: complete workflow | Text capture/extraction, bounded proposals, validation, explicit approval, journaled apply, local history | End-to-end offline synthetic import; duplicate no-op; revised-source lineage; stale/altered approvals rejected; crash recovery at every commit boundary |
| M1b: useful reading | Evidence/synthesis FTS5 search, Chinese handling, model-optional query, local text-PDF coverage, client packets | Exact-source, conflict, no-evidence and multilingual cases; denied-scope titles/counts/ranking/caches absent; accepted knowledge survives full cache rebuild |
| M2: research continuity | Read-only bibliography file import, paper/project templates, context packs, session receipts | Stable external IDs/citation keys; role/adoption separation; stale repository bindings; two-session continuity demonstration with honest fake/real distinction |
| M3: personal domains and release | Finance/life templates, Decimal calculations, dated evidence, complete route-grant audit, backup/restore, pinned install | Owner/account separation; no invented balances; dated conflicting rules retained; text/blob restore by hash; installed-wheel tests; all hard gates traced to evidence |
| Private activation | Review a specific release and initialize a separate private workspace using that installation | Explicit owner acceptance of release and processing profile; actual-machine isolation and recovery checks; no private content exposed to development |

Build milestones in small isolated commits and maintain a requirements-to-test matrix. Continue automatically through authorized implementation stages when their gates pass. An absent external capability may leave a named gate blocked while independent public work continues; do not silently mark the stage or release ready.

Do not wait until M3 to enforce local-only policy or test backup fundamentals. M0 establishes denial and isolation; M1 enforces route decisions and includes a basic text/blob restore round trip. M3 expands coverage and closes the release checklist.

Research bibliography integration begins with owner-selected exported metadata; no writes to a bibliography manager and no copying its live database. Finance schemas use decimal strings plus units/currency, dates, evidence, and distinct owner/account aliases; deterministic code handles calculations. Life entities collect authoritative documents, history, procedures, and review-date metadata without scheduling reminders or executing external actions.

## 12. Test and evaluation strategy

Use `pytest`, static typing, linting, temporary synthetic workspaces, and a small committed gold corpus. Add property-based testing only where it adds coverage, especially path normalization and transaction state sequences. Test released wheels, not just imports from the source tree.

The required matrix covers every acceptance test in the brief, including malicious source text, malformed provider output, denied scopes, fabricated quotes, missing evidence, scope changes, policy changes after approval, route fallback attempts, stale owner edits, partial writes, interrupted receipts, deduplication, and deletion/rebuild of caches. Test leakage in metadata, diagnostics, logs, backlinks, and cache reuse as well as page content. Public/private hash deduplication must not become an existence oracle.

Network denial needs process-level evidence: attempts from extraction/generation workers and their subprocesses must fail. An application-level socket mock alone is insufficient. Isolation tests use synthetic canaries in an unmounted location; they never probe the owner's real private files or credentials.

Organize the gold set around exact quotes/numbers, multi-source synthesis, contradictory sources, superseded rules, unknown evidence, conversation roles, bilingual retrieval, and context continuity. Security and write-correctness cases require zero observed violations in the defined corpus. Measure citation support, source coverage, retrieval quality, review burden (including pages changed and human edits), latency, and any model cost. Set usefulness targets against a measured baseline; do not invent quality scores before evaluation.

The owner’s real evaluation corpus remains private and runs only against a reviewed installation. Its content, logs, and detailed failure examples do not flow back into public CI. Synthetic deterministic success does not establish semantic truth or complete security.

## 13. Handoff to the next goal

Recommended implementation objective:

> Implement Cairn M0–M3 in the public checkout according to this plan and the original brief. Use synthetic data throughout development, preserve the public/private boundary, and proceed through the ordered milestones with tests and isolated commits. Deliver an offline fake-provider end-to-end demo, scoped existing-client packet workflow, owner-bound approvals, recoverable application, evidence-aware search, project context and receipt workflows, domain templates, and a tested pinned installation/restore procedure. Report every blocked or unimplemented control. Do not activate a private workspace, ingest real data, grant cloud processing, publish/push, or implement M4 as part of this goal.

That goal should end with a concrete release review and private-activation runbook. The owner can then authorize deployment into the chosen private directory without exposing that directory to the development agent. Naming a deployment location in advance does not waive the brief's reviewed-installation and isolation requirements.

Remaining operational selections do not block public implementation: which reviewed local/client runtime to use, whether any cloud route should be granted, the real backup destination, and whether an optional Markdown editor integration is desired. Resolve them against the completed capability report before private activation; use no cloud access as the default.
