# Acceptance evidence

## Automatic Finch reading (2026-10-10; software checks passed, activation pending)

The owner requested automatic Finch use for paper reading and automatic Cairn workflow
handoffs on each Finch invocation. The package includes a checksummed MIT Finch 0.2.0
snapshot. Library jobs bind the guidance and use it in the offline worker. The host-skill
installer handles missing Finch, preserves existing guidance, and attaches the lifecycle.
Owner-prepared agent packets and returned responses automatically capture conversations,
stage concept-note proposals, and validate them. Approval/apply and read status remain
owner operations; sources and human notes are immutable to these proposals.

`bash scripts/check.sh` passed **284 tests**, Ruff and strict mypy across **100 source
files**. Both processing profiles passed all **13 isolation checks**, installed worker
packet/extraction/HTML/domain trials, **129 gold checks**, and real Docker lifecycle and
hostile-child cleanup checks. All tests used synthetic inputs; no private workspace or
home directory was mounted. The first full run found an outdated PDF trial fixture
without the new guidance hash; it was corrected and the complete check rerun passed.

The 24 Finch tests cover packaged guidance use, installation/retry/preservation and
conflicting hooks/symlinks; cloud grants and full-request labels; immutable raw response
capture and proposal-only handoff; typed claims, citations and rejected authority fields;
changed source/human notes/policy, revocation, interrupted and concurrent retries;
selected project inheritance, denied context, durable bindings and CLI round trips.
Schemas are regenerated from the typed models. Unrelated protected workspace paths
remain in owner-only guards rather than exported packets.

Fresh installed-release validation is pending at this implementation milestone. Its
first run completed the installed Finch handoff but correctly rejected the older HTML
view after the trial added an export grant. The trial now expects that stale-view rejection
and regenerates the view before backup/restore; a complete rerun is required. Live
reading quality, private runtime activation and host skill/launcher configuration remain
separate owner deployment gates. This instruction-based lifecycle does not monitor
unconfigured chats. Missing packets/launchers report `cairn_handoff_pending`; no real
discussion has been ingested or accepted by these development tests.

## Journal library extension (2026-09-30, software validated; deployment pending)

Catalog hardening preserves bibliographic observations as source snapshots, resolves
pre-existing journal identities in place, supports folder aliases/publication series,
and treats an empty previously populated route as uncertain. The catalog/discovery
boundary tests use synthetic journals and PDFs. No private library was used by tests.

The final `scripts/check.sh` run at code revision
`653aba4f1011d0c058b7014be6266908c154c50b` passed **227 tests**, Ruff and strict mypy
across 77 source files. Both development and installed processing profiles passed all
13 isolation checks. Installed extraction and packet trials, 129 gold checks, and real
Docker create/start/remove plus hostile-child cleanup passed. The new PDF page trial
uses actual PDFium rendering with synthetic model responses; it does not test semantic
reading quality.

The same revision passed the offline installed release trial: 15 distributions,
899 verified files, library scan/mark/feed/streaming restore, schema migration with backup,
and capture/approval/apply/query/restore. Modified packages, unreviewed `.pth` files,
editable installations, and activation without a live engine were rejected. See the
[installed trial](evidence/library-release-trial.json) and
[exact released worker profile](evidence/library-worker-profile.json). Release manifest
SHA-256: `8feceae826e915d29fa2b31598de44b48681e999003018b63a383570f5571a0f`.

A separate physical **260MiB of source payload** streaming trial restored all 65
synthetic blobs and checked the archive digest; [the report](evidence/library-backup-trial.json)
records 272,630,931 total payload bytes. This exceeds the legacy total-size limit without
claiming a one-terabyte capacity trial.

Implemented interfaces cover catalog/filter/export, publication backfill, explicit
owner-device enrollment, resumable/cancellable reading proposals, bounded subscription
verification, saved Markdown/HTML/Atom digests, delivery acknowledgements, and streaming
backup/restore. Pending or failed verification is visible; selected pending checks and
failed checks block owner acceptance. Local older papers are inventoried and preserved;
weekly baseline scans do not read the archive. The reader is Qwen/llama.cpp code, not a
claim that a live Qwen model has run. The Monday 09:00 America/Chicago heartbeat has been
prepared in a paused state. No private library or private workspace was used for these
tests, and no private runtime was upgraded.

Deployment remains pending: the workstation SSH connection still times out; its GPU,
WSL2/container configuration, pinned Qwen build, memory use and reading quality remain
unverified. The release trial is Linux-aarch64, not a native macOS owner installation.
A compatible pinned Mac installation with reviewed owner SSH/client transport, live
subscription adapter capability checks, and a small owner-reviewed pilot are required
before full cataloging and weekly activation. Subscription login status and synthetic
protocol tests do not establish live tool disabling, billing behavior, or output quality.
See [deployment gates](library-deployment.md). No skipped or synthetic check is counted
as passing a live deployment gate.

M0–M3 reference acceptance is complete. A checked item requires an executed test or
inspected artifact, not just code presence. Entries below retain the earlier M0–M3
chronological evidence and scope statements; the authorized journal extension and its
remaining deployment gates are described above.

| Stage | Status | Evidence and limits |
| --- | --- | --- |
| M0 | Passed reference acceptance | 24 tests, lint, strict typing, 13 isolation checks |
| M1 | Passed reference acceptance | 48 tests, installed worker protocols, both isolation profiles |
| M2 | Passed narrow manual continuity review | Owner-supplied real-client design uses the decision and avoids the failure; owner verdict remains unclear; receipt normalized separately |
| M3 | Passed reference acceptance | 175 tests, 129 gold checks, full requirements matrix, final installed release trial; actual activation separate |

The brief's hard gates are mapped to implementation and named evidence in
[the requirements matrix](requirements.md).

M0 evidence collected by `bash scripts/check.sh` in the reference Linux container on
the macOS Docker host: **24 tests passed**, Ruff passed, strict mypy passed (16 files),
and **13 process-level isolation checks passed**.

- `test_foundations.py`: record round trips, deterministic sets, traversal, symlink and
  hard-link access, special files, case/Unicode collisions, root overlap, unsafe YAML,
  scope widening, confidentiality/processing inheritance, and cloud denial.
- `test_provider.py`: deterministic extractive fake; injected source remains data;
  job/result serialization; pinned, no-mount worker command; subprocess wire protocol.
- `test_schema_exports.py`: generated schema parity.
- `scripts/isolation_probe.py`: all 13 checks passed with a real unmounted synthetic
  host canary. Canonical/policy/approval writes, outbound TCP, DNS, and hostile child
  operations were denied. No Docker socket, host home, or forwarded credentials existed.

These checks cover a defined threat corpus. They do not prove semantic truth, universal
container security, or private-runtime readiness.

M1 core evidence: **44 cumulative tests passed**, Ruff passed, strict mypy passed
(29 source files), using the isolated development profile with public source mounted.
The later installed M1 acceptance run below supersedes this initial core run.

| Requirement | Current named evidence |
| --- | --- |
| Preserve source/human bytes; no duplicate import churn | `test_capture_extract_apply_preserve_and_deduplicate` |
| Revised-source lineage and version conflicts | `test_revisions_and_declared_version_conflicts` |
| Retryable extraction failures preserve original capture | `test_failed_extraction_preserves_capture` |
| Assistant recommendations do not authorize adoption | `test_conversation_roles_remain_data` |
| Fabricated quote and denied-scope rejection | `test_quotes_scope_and_source_hash_are_validated` |
| Exact approval binding and intervening owner edits | `test_approval_tamper_and_owner_edits_are_rejected` |
| Real termination halfway through a two-file bundle | `test_real_process_crash_recovery` (six boundaries) |
| Recovery preserves unexpected owner bytes | `test_recovery_preserves_unexpected_owner_bytes` |
| Scoped titles, counts/ranking, and backlinks | `test_scoped_search_no_counts_titles_or_ranking_leaks`, `test_restricted_backlinks_are_omitted` |
| Two-character Chinese and bilingual aliases; cache deletion | `test_bilingual_short_query_and_cache_rebuild` |
| Text and evidence-blob restore; hostile archives | `test_restore_text_blobs_and_evidence`, `test_archive_traversal_and_hash_tamper_rejected` |
| CLI capture through review/apply/search | `test_cli_full_owner_workflow` |
| Source summary plus bounded project update | `test_two_file_update_is_reviewable` |

Installed M1 evidence from `bash scripts/check.sh`: **48 tests passed**, Ruff passed,
strict mypy passed (30 source files), both development and installed worker profiles
passed all 13 isolation probes, and installed extraction/client-packet round trips passed.
The staged owner editor, PDF page/coverage behavior, and backup/restore CLI are present.
`test_stale_wiki_update_cannot_overwrite_owner_edit` and
`test_index_failure_leaves_durable_apply_and_retries` cover the final concurrency and
post-commit maintenance boundaries. Private-runtime readiness remains unproven until M3.

The user selected a **manual agent session** for M2's separate-agent continuity check.
Prepare its synthetic pack and verification procedure; do not spawn a subagent or claim
that deterministic tests satisfy that semantic gate.

M2 installed reference evidence from `bash scripts/check.sh`: **64 cumulative tests
passed**, Ruff passed, strict mypy passed (38 files), and both processing profiles passed
all 13 isolation probes. Installed packet, text-extraction, bibliography-extraction, and
receipt-extraction trials passed. The synthetic manual-handoff generator also completed
inside the installed development image. The new workflow covers:

| Requirement | Named evidence |
| --- | --- |
| Stable library IDs/citation keys; unknown dates; item-level deduplication | `test_bibliography_ids_dates_coverage_and_item_dedup` |
| Ambiguous or malformed import produces no capture | `test_bibliography_invalid_export_writes_nothing` (three cases) |
| Receipt approval preserves draft status; explicit adoption needs exact owner apply | `test_session_receipt_requires_explicit_adoption_and_context_preserves_evidence` |
| Roles preserved; fabricated citations and claimed authority rejected | `test_receipt_roles_fabricated_reference_and_claimed_authority` |
| No denied-domain titles/IDs/content or unsupported derived conclusion | `test_context_scope_filters_titles_ids_and_denied_evidence` |
| Bounded packs omit whole items, retaining evidence locators | `test_context_budget_omits_whole_items_and_keeps_locators` |
| Current, stale, and unverified repository states | `test_repository_binding_flags_changed_or_unverifiable_context` |
| Review diff matches exact candidate bytes | `test_review_diff_tamper_is_rejected` |
| CLI scoped context and explicit save | `test_cli_research_context_and_save` |

`scripts/prepare_continuity.py` executed the synthetic capture/proposal/approval/apply/
adoption/context sequence and generated `examples/continuity/context.json`, source evidence,
and a verification manifest. The second-agent semantic result is explicitly **not evaluated**.
Follow `docs/research-continuity.md` for the owner-selected manual test. No subagent was spawned.

M3 domain implementation adds exact structured financial observations and Decimal
calculations, dated financial categories, life dossier/history imports, and the owner
`evidence` command. The new tests cover decimal fidelity; distinct owner/account/date/
unit/currency; float rejection; fabricated amounts, metadata, prose and snapshot bodies;
preserved life history; denied-evidence summary leakage; and decision supersession.
Installed M3 domain-increment evidence from `bash scripts/check.sh`: **86 tests passed**,
Ruff passed, strict mypy passed (42 source files), both profiles passed 13 isolation probes
each, and six installed-worker trials passed (packet, text, bibliography, receipt,
financial snapshot, and life dossier). The manual-handoff generator also completed.

- `tests/test_domains.py` contains 15 executed cases, including six hostile snapshot
  mutations and five distinct prohibited arithmetic mixtures.
- `test_denied_evidence_withholds_derived_text_and_ranking` verifies that stripped citations
  cannot leave a restricted conclusion in search or its cache.
- `test_superseded_adopted_decision_is_not_presented_as_current` preserves the original
  decision and presents only its adopted successor as current.
- `test_missing_conflict_reference_is_rejected` and `test_cli_evidence_exact_locator_and_coverage`
  cover conflict-reference integrity and explicit source inspection.

Next work: complete release packaging, schema migration support,
the synthetic evaluation report, and a full requirement audit. Independent work may
continue while the external manual gate remains named and pending. Private activation
remains separate and is currently explicitly denied.

M3 restore/worker-hardening evidence from `bash scripts/check.sh`: **110 tests passed**,
Ruff passed, strict mypy passed (43 files), both profiles passed 13 isolation probes each,
and all six installed-worker trials passed. A real-engine create/start packet round trip
and forced removal of a running worker plus child also passed. No contributor Python
received a Docker socket or host/private mount.

- `tests/test_restore_hardening.py`: 12 executed cases cover complete namespace preflight,
  special files, missing manifest, invalid records, expected archive digest, copy failure,
  executable Git configuration, a ZIP above the old 32 MiB ceiling, backup of a real
  process-terminated two-file apply, and refusal to open incomplete restore staging.
- `tests/test_worker_lifecycle.py`: 11 cases use real subprocess pipes with a synthetic
  Docker control process to verify stdout/stderr limits, timeouts, closed pipes, packet
  success/failure, actual exit-state checks, exact owned-container cleanup, cleanup failure,
  remote endpoint denial, and image-volume rejection before input transmission.

The synthetic engine verifies launcher behavior, while the separate host script verifies
the actual Docker lifecycle and worker isolation. Neither is claimed to prove a complete
private installation or universal container security.

M3 policy-audit evidence from `bash scripts/check.sh`: **127 tests passed**, Ruff passed,
strict mypy passed (45 files), both profiles passed 13 isolation probes each, all six
installed-worker trials passed, and the real Docker create/start/removal trials passed.

`tests/test_policy_audit.py` executes 12 cases: all five processing operations; missing,
expired, wrong-provider/destination/scope/operation grants; question and metadata labels;
unknown labels; public evidence paired with a private question; denied input audit
redaction; local-client cloud-job rejection; exact policy history with interrupted
replacement; stale proposals after policy changes; scope replacement revoking grants;
restore of policy history; and the owner policy CLI. Five new schema parity cases cover
the audit/request/scope/grant models. A full-run context regression was fixed and rerun:
question labels constrain the output pack without widening access to stored records.

Cloud grants describe consent only. There is no cloud adapter, and an otherwise matching
cloud request is explicitly blocked without transmission. Release installation, version
inspection/migration, and the gold-set report remain required independent work. The
owner-selected manual continuity session is still pending.

Release preparation now has a typed manifest, locked wheel acquisition, bundle inventory
checks, and installed-runtime verification. The initial 31 focused schema/release/CLI
tests passed. The subsequent offline trial at revision
`58f03a6574b56ec9221659d05786cf25d7baa867` passed with **15 distributions and 871 verified
files**, imported from the new environment's site-packages. Synthetic capture, approval,
apply, query, backup, and restore passed through the installed CLI with network disabled.
The trial rejected modified package bytes, an unreviewed `.pth`, and editable metadata.
See `docs/evidence/release-trial.json` and `docs/installation.md` for the exact manifest
digest and target. This is a `linux-aarch64` reference bundle, not a macOS installation.

The final `bash scripts/check.sh` run after release-code changes passed **131 tests**,
Ruff, strict mypy (49 files), both sets of 13 isolation probes, six installed-worker
trials, the manual-fixture generator, and real-engine lifecycle checks. CI now also runs
the separate offline installation trial. Private activation/restore gates, version
inspection/migration, the gold-set evaluation, and the final requirement matrix remain.
The manual second-session continuity test remains pending by owner choice.

Activation/restore increment: **146 tests passed**, Ruff passed, and strict mypy passed
(52 source files) in `bash scripts/check.sh`. Both independent isolation profiles passed
13 checks each, the installed worker's new nonce-bound probe passed all 13 checks on the
real engine, all six installed-worker trials passed, and the lifecycle checks passed.

`tests/test_activation.py` covers ten cases: required review and installed-runtime gates
before creation; missing, failed, replayed, or unavailable probes; changed host canaries;
release/image binding; private inline-bypass rejection; rechecks before operations;
private-mode restore preserving source/policy bytes with a new runtime approval; staging
failure; and doctor reporting unchecked or blocked workers. These lifecycle tests use
synthetic data with explicitly stubbed installation/worker verification. They do not prove
successful activation on a real owner machine. Five exported-schema checks were added.

The clean-revision offline trial at `330ce6b6be116e8e8eaa9e79fbb99f3a5737da2d` passed:
15 distributions and 874 files verified; installed CLI workflow through restore passed;
tampered installation, unreviewed `.pth`, and editable metadata were rejected. The
installed CLI blocked activation with no live engine and created no workspace. Separately,
the exact manifest-bound worker image passed all 13 real-engine probe checks with 64 MiB
scratch and an unmounted synthetic canary. Reports are retained in
`docs/evidence/activation-release-trial.json` and `activation-worker-profile.json`.
Actual owner activation, the manual continuity check, and release review remain separate.

Schema migration increment: **169 cumulative tests passed**, Ruff passed, and strict
mypy passed (55 source files) in `bash scripts/check.sh`. Both isolation profiles and the
installed worker probe passed all 13 checks each; all six worker trials, the manual-fixture
generator, and the real-engine lifecycle checks passed. `tests/test_migration.py`
contributes 18 cases, plus five
new schema-export parity cases. Legacy workspace v1 stays readable without writes;
new v2 explicitly requires record schema 1. Unknown versions and a missing v2 record
contract are rejected. The owner command previews exact bytes and all durable input
hashes, makes an independently hashed backup, and requires an exact preview digest and
statement before journaled configuration/policy replacement.

Executed tests cover stale preview and stale workspace handles; occupied backup targets;
unknown record versions; nine real process-termination boundaries (backup, authorization,
policy intent, prepared journal, both replacements, receipt, commit marker, and history);
read blocking while prepared; unexpected owner bytes; an altered configuration target in
the journal; source/record/adoption-chain preservation; invalidation of pending approvals;
restoring pre- and post-migration archives; invalid migration receipts; retryable history;
and the owner CLI. The private-mode fixture checks release binding and re-verification
with synthetic installation stubs; it is not an actual private deployment.

The migration deliberately changes workspace format only. It does not install or approve
a different runtime, migrate Markdown record schema 1, or permit backing up a prepared
schema transaction. Recover locally or use the mandatory pre-migration archive. These
limits and the separate `schema recover` procedure are in `docs/schema-migrations.md`.
The clean-revision offline trial at `1b72f1b7b276dfe3cf019895e2ea90249d56b230` passed
with **15 distributions and 877 verified files**. The freshly installed CLI opened a
synthetic legacy workspace without rewriting it, migrated it after preview/backup,
retained its query result, and backed up/restored the migrated workspace. Installation
tamper checks and activation denial without an engine also passed. The manifest-bound
worker passed all 13 real-engine isolation checks. Evidence is retained in
`docs/evidence/migration-release-trial.json` and `migration-worker-profile.json`.
The manifest SHA256 is `af540becc04763a2dac6b459dd798ffbe97de4b6f040df7cfe1471724c221bfd`.
This remains a Linux-aarch64 reference trial, not owner-machine activation or semantic
acceptance. Gold-set reporting, the final requirements audit, and the manual M2 gate remain.

Synthetic evaluation increment: `bash scripts/check.sh` again passed **169 tests**, Ruff,
strict mypy (55 files), both sets of 13 isolation checks, the installed worker probe,
all six worker trials, fixture generation, and real-engine lifecycle checks. The newly
integrated gold-set evaluator passed **129/129 checks** in the installed development
image. The retained public report binds its source tree, corpus, and script hashes.

Eight query cases retained all expected sources and exact wording, dates, and explicit
conflicts. All 36 citation occurrences passed hash/locator/quote checks; the defined
scope and write checks observed zero violations. The fixture generated 12 proposals and
13 page changes. It records latency samples, review flags, and zero model calls/cost;
human edits/time and semantic quality are explicitly unmeasured. Conversation roles,
unadopted suggestions, and the adopted decision/failure context workflow were exercised.
See `docs/evaluation.md` and `docs/evidence/goldset.json`. This does not satisfy the
owner-selected manual second-agent gate or establish entailment or complete security.

Source-review/final-audit increment: **175 tests passed**, Ruff passed, strict mypy passed
(56 files), both sets of 13 isolation checks and the installed worker probe passed, all
six worker trials passed, gold-set checks remained **129/129**, and the real-engine
lifecycle checks passed. Six new review tests cover local source/artifact links, dates,
coverage, explicit conflicts, read-only behavior, recomputed stale/tampered diffs, revoked
scope denial, symlink refusal, and rendering hostile HTML/links/fences without activation.
An earlier acceptance invocation stopped at a test-formatting lint error; the corrected
complete invocation passed all stages.

`docs/requirements.md` now maps every brief boundary, ingestion step, hard gate, named
artifact, interface, domain template, evaluation measure, and additional plan requirement
to inspected implementation and named evidence. The audit identified and closed the
missing Markdown source-review report and added a validated synthetic configuration
example. The updated offline installed-release trial remains the final revision-specific
check for this increment; the manual M2 semantic gate remains pending by owner choice.

Final installed trial at `6bcad55cd9c71ea154dab2d4e6e34b65e80d1929`: **15 distributions,
878 files verified**. The fresh offline CLI passed Markdown source review, capture through
approval/apply/query, explicit legacy schema migration with backup, and restore. Modified
package files, an unreviewed `.pth`, and editable metadata were rejected. Activation with
no live engine remained blocked without creating a workspace. The exact manifest-bound
worker image passed all 13 real-engine isolation checks. Retained reports are
`docs/evidence/final-release-trial.json` and `final-worker-profile.json`; manifest SHA256
is `b4c9def89d6d673afe6b650adce49714e471902d31541497d3756802af73a9ae`.

The final matrix closes the independent public implementation/evaluation/audit work.
M0/M1/M3 have reference acceptance; M2 mechanics pass but the required separate manual
agent session still has no semantic result. The goal must remain incomplete until that
gate has evidence. Actual private activation, real-data evaluation, and M4 remain outside
this goal. All test workspaces were synthetic; no private directory was accessed.

The saved manual handoff pack was also rechecked: its SHA256 matches
`examples/continuity/verification.json`, all 11 citation occurrences resolve against the
saved source/extraction evidence, and the adopted decision and failed approach are
present. This verifies the input artifact, not a second agent's use of it. Follow
[the manual separate-session procedure](research-continuity.md#manual-separate-session-acceptance)
to supply the remaining result.

Manual M2 evidence received from the owner: reported model **GPT 6 Astra Light**, reported
generation time **7 seconds**, cost/tokens unknown, owner verdict **unclear** because the
context was unfamiliar. That verdict is preserved, not promoted to owner approval.
The supplied response explicitly uses the adopted provenance requirement in a concrete
three-source/four-case design, avoids title-only retrieval, and separates its design from
unrun experiments. It cites the matching context ID and named decision/failure sections.
The implementation assistant therefore records a **design-level semantic continuity pass**.

The original receipt is not Cairn-schema compatible (missing session/project IDs, an
unstructured next action, and extra fields). The initial test prompt did not supply that
schema. The raw receipt is retained, and a separately labeled reviewer normalization
validates as `SessionReceipt`. Its added evidence references come from the saved pack,
not the second agent. No approval, adoption, canonical import, or experiment was performed.
The context hash and all 11 input citation occurrences were reverified in the no-network
development container. External client isolation, input bytes, and network behavior are
not independently verified; this is an owner-supplied manual observation.

See [the recorded review](research-continuity.md#recorded-manual-result) and
[`manual-evaluation.json`](../examples/continuity/manual-evaluation.json) for artifact
hashes, criterion-specific evidence, validation errors, and limits. This closes the last
M0–M3 gate at its specified scope. The runtime code and earlier executed release checks
are unchanged. Actual private deployment and general model-quality evaluation remain
outside this acceptance.

Final evidence validation is retained in `docs/evidence/manual-review-check.json`:
67 checks passed, including 37 local documentation links, original-receipt rejection,
normalized-receipt validation, artifact hashes, and current source/corpus/evaluator
bindings to the passing 129-check gold report. A Git comparison against the installed
trial's `6bcad55` revision confirmed no changes to runtime, tests, schemas, build scripts,
dependencies, container configuration, CI, or templates. This documentation/evidence-only
increment did not rerun or change the previously passing 175-test release validation.

Repository naming update: the software repository is `cairn-workbench`; the separately
configured private knowledge base is `cairn`. Documentation and the synthetic example
configuration use those names. Runtime code, Python package, CLI, and schemas are
unchanged; this documentation/configuration-only change passes `git diff --check`.
# Journal catalog follow-on — implementation evidence

The journal catalog extension is under development. Synthetic tests run in the documented
network-disabled development container (public checkout mount only). The targeted catalog,
existing ingestion/apply, backup, schema-export, and CLI suite passed **65 tests**.
Three additional publication-discovery tests passed: cursor resumption/idempotence,
unresolved journals/feed-only coverage, and failed-page watermark preservation.
These are mechanical tests, not paper-reading quality evidence. Workstation SSH timed out;
GPU inference, subscription verification, release activation, and private-library deployment
are not yet verified. No real paper or private workspace has been used by contributor code.

## Cairn HTML follow-on — foundation evidence (2026-10-09)

The application renderer is built from maintained source, with a complete licensed
source snapshot and lockfile in `vendor/answer-me-with-html`. The generic CLI and both
installed skills remain unchanged. The standalone renderer source is synchronized at
`0a13bfcaaa5081b87e6cd191537426261da8c1df`; its upstream base is
`19b2b5b07676d3e65c83ca9a7b6621f300b54c92` (0.5.0). Quill resources are pinned at
`d6bc7de15d1779c58286cbdec1a54eec52bdef22` (0.3.0, MIT). Resource hashes are recorded in
`src/cairn/presentation/resources/provenance.json`.

Executed in the isolated renderer development container with synthetic inputs:

- Full renderer suite: **788 tests, 786 passed, zero failed, two skipped**.
- Mandatory Chromium application checks passed: 1440/390 widths, light/dark, keyboard
  focus, evidence disclosures, diagram controls/Escape, filtering, feedback JSON
  download, no persistent storage, reduced motion, print and JavaScript-disabled
  readability. Request monitoring recorded zero HTTP(S) requests. Screenshots were
  inspected; the narrow diagram was changed to wrap rather than require scrolling.
- Actual container probe passed: non-root, read-only root, no network interface beyond
  loopback, no credentials, capabilities or Docker socket. Browser coverage was not
  skipped or counted as passing by absence.
- Node 20.19.0, 22.14.0 and 24.0.0 exercised generic rendering/patches/captions and the
  Cairn package from ordinary and space/non-ASCII install paths with no agent variables.
- Application rebuilds matched each other and the committed runtime byte for byte.
  Generic CLI rebuilds matched in its documented original build-directory layout.

Failed checks during development, resolved: an interrupted-write test initially
expected raw OSError rather than the writer's existing Denied wrapper; it was corrected
and rerun. A generic CLI checksum comparison from a deeper scratch directory differed
only in 230 esbuild dependency-path comment lines. Repeating the documented original
layout matched exactly; no generated file was hand-edited. Lint issues were fixed
before the passing suite.

Skipped upstream checks: reused foreign-owner PID detection (PID 1 is signalable by
the container UID) and the separate marketing-site build test (site/dist not built).
Neither is a Cairn isolation or browser gate. Live agent-product compatibility, private
workspace deployment, cloud narration and GPU inference are not established here.

### Knowledge-view and review milestone

The seven typed views and shared terminal/Markdown/HTML proposal review model passed
their targeted synthetic tests. Fresh diffs, exact proposal hashes, assertion kinds,
verification, owner adoption and personal reading are displayed separately. Added
regressions cover denied-scope leakage in serialized bundles and HTML, markup injection,
render failure, stale records/library status/approval state, revoked scope, interrupted
replacement and retries leaving one deliverable. Retrieval of a historical saved view
still rechecks authorization. Viewing emits no approval or validation event.

The full development/container check at this milestone passed **255 tests**, Ruff,
strict mypy, schema parity, worker canary/network/credential probes, hostile subprocess
containment, real worker lifecycle cleanup, and a no-mount HTML JSON roundtrip. A final
release trial follows the complete packet/feedback milestone; this result alone is
not private deployment approval.

### Writing and feedback milestone

A synthetic Quill packet was prepared by `scripts/html_packet_trial.py`, exported,
read and answered by **Codex in this development chat**, then imported/rendered after
restoring the synthetic backup. Canonical records and approvals were unchanged.
Manual comparison retained 12 simulated datasets, condition C, errors 12% versus
15%, the −3 percentage-point difference and 95% interval [−7, +1]. It distinguished
a point estimate from a clear superiority/equivalence claim and missing excerpt
coverage from an assertion that other conditions were never studied. This is one
manually inspected synthetic case, not a semantic-quality benchmark or a verified
local-execution attestation. No other agent product was exercised live.

The packet/feedback tests exercise grants for both generation and client export,
private-question defaults, local-only blocking, job/input identity, exact quotations,
missing/foreign citations, forged approval/status fields, revoked policy, response
idempotency, immutable source/catalog targets and comments awaiting action. A synthetic
feedback revision stages through normal proposals, remains unapplied without owner
approval, applies after explicit test-owner approval, and rejects stale replay. Saved
view/writing/feedback receipts participate in backup validation; modified excerpt bytes
are rejected even if a forged bundle ID is recomputed.

Skill review covered explicit HTML (render supplied document), ordinary questions
(no page), maintenance (edit skill only), presentation edits (same packet/output),
knowledge changes (new bundle), explanations (structured Quill response), feedback
(selected-target proposal) and video requests (outside this skill's scope; no implicit
cloud call). The entry point and relative references use the Agent Skills format.
The existing generic HTML and Quill installations were not changed.

The first synthetic trial preparation failed because its consent text differed from
its owner statement. The fixture was corrected to identical explicit text and rerun;
the authorization check was retained. An earlier writer interruption test and build
path comparison are recorded above rather than counted as passing attempts.

### Final release evidence

The complete source implementation is commit
`5428abeade70a48ae3e0a619ed6d246bedeb816f`. The final acceptance commit changes only
this record and the documented validation entry point; it does not claim a different
runtime was exercised.

**Executed and passed:**

- `bash scripts/check.sh`: **255 passed**, zero skipped/failed; Ruff passed; strict
  mypy passed for 89 source files; generated-schema parity passed. Actual dev/worker
  isolation probes, hostile subprocess containment, lifecycle removal and renderer
  JSON roundtrip all passed. Goldset control-flow checks passed 129/129; fake-provider
  outputs remain control-flow evidence rather than semantic-quality evidence.
- `bash scripts/check_html.sh`: complete renderer suite **786 passed, zero failed,
  two upstream skips** out of 788; required Chromium and isolation gates passed.
  Both generic and Cairn packaged CLIs passed all six Node/install-path combinations.
  Application rebuilds matched the checked-in bytes. Two independently generated
  portable ZIPs matched byte for byte. The actual exported synthetic Quill packet
  also rendered through the packaged CLI after its request/document checksum checks.
- Chromium **154.0.8037.92**, Linux ARM64: desktop/narrow light/dark screenshots were
  reviewed; controls, JavaScript-disabled content, print and zero unintended requests
  passed. The accepted synthetic explanation was additionally rendered and inspected.
- Skill frontmatter/reference review and the installed skill-creator validator passed.
  Existing generic renderer bytes still match their prior pinned checksum; installed
  Quill guidance still matches its pinned copy. Neither installation was replaced.
- `bash scripts/release_check.sh`: fresh offline installation of 15 distributions,
  **919 verified installed files**, HTML render/retry/saved-view backup/restore, existing
  Markdown review, capture/approval/apply/query, library/feed and migration trials
  passed. Modified renderer/package bytes, unreviewed .pth files and editable installs
  were rejected. Activation without the required owner engine remained blocked.
- Release manifest SHA256:
  `51c5fe3e7ba4faf79b598c9e6c47f5ec601fbb8c25d2580c2d38943c7e75e652`.
  Its worker image is
  `sha256:4de955dfdb10666e154403c14a7ded2f93a9e69f87f0e90926def1668e901fa7`.
  That exact image passed all 13 installed-worker isolation checks and an additional
  no-mount HTML render roundtrip. The pinned production Node runtime is **24.21.0**;
  compatibility smoke runtimes were **20.19.0, 22.14.0 and 24.0.0**.
- Portable `cairn-html.zip` SHA256:
  `fb5b7a1934661b231e963a125b9e20b9187c4fc365813ee3b72f3bd94d392a06`.
  Source/runtime/license hashes and the maintained renderer commit are in the packaged
  provenance. Public-code review found only source, licensed vendor resources,
  documentation and synthetic tests; no real workspace, credentials or owner paths
  were added. The first-party diff passed `git diff --check`.

**Failed checks:** none unresolved. Earlier failed attempts and their corrections are
recorded above. Docker initially needed permission to update host build metadata;
it was rerun with that permission, without broadening processing-container access.

**Skipped checks:** only the two identified upstream PID/marketing-site cases.
No required isolation or browser check was skipped or substituted with a fake result.
Native Windows/macOS rendering and other agent products were not exercised.

**Live deployment:** not performed. No private inputs, subscription transports, local
writing model, GPU reader, scheduled jobs or installation changes were activated.
Manual packet responses do not attest local execution; local-only writing remains
blocked without a reviewed adapter. The semantic review covers one synthetic Codex
response. Owner release acceptance and any private deployment remain separate.
