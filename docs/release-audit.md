# M0–M3 release audit

M0/M1 reference gates pass. M2 mechanics and the narrow review of the owner-supplied
second-session response pass; its original receipt needs the separately recorded
normalization. M3 passes 175 cumulative tests plus installed worker, isolation, and
real-engine lifecycle trials. The evidence below closes M0–M3 reference acceptance.

The following public, synthetic-only work is now complete:

1. Completed reference policy audit: owner scope/grant commands require explicit consent
   and the current policy hash; changes have an atomic, verifiable history. Complete
   request checks cover all five operations and deny missing/mismatched/expired grants or
   incompatible labels. Cloud execution remains unavailable, with no fallback. Local
   processing receipts bind packet hashes; read-only query/context retain local provenance.
2. Completed reference hardening: backup/restore now preflights paths, canonical metadata,
   evidence/quotes, history configuration, and journals. Staged publication avoids partial
   destinations; a >32 MiB ZIP and interrupted apply restore pass. Private restore still
   depends on the reviewed-runtime gate in item 4.
3. Completed reference hardening: worker streams/deadlines are bounded, remote Docker
   endpoints and implicit volumes are rejected, and owned-container cleanup is required.
   Real-engine create/start/removal and synthetic launcher failure tests pass. Full private
   installation verification remains separate; no daemon socket was mounted in a worker.
4. Offline packaging and installation verification now pass for the reference
   `linux-aarch64`/CPython 3.13.11 target: 15 pinned wheels and 871 installed file hashes;
   installed CLI capture through restore; modified packages, extra `.pth` files, and
   editable metadata rejected. The manifest binds revision `58f03a6`, lock/byte hashes,
   interpreter and worker image. See `docs/evidence/release-trial.json` and the installation
   runbook. Activation/restore gates are now implemented: explicit review, installed-file
   checks, a fresh worker probe, and durable release/profile binding. Doctor distinguishes
   unchecked, blocked, and passed probes. Lifecycle tests use synthetic verification
   stand-ins. The updated offline negative-activation and exact-image trial passed at
   revision `330ce6b` (15 distributions, 874 file hashes, 13 real worker probe checks).
   The bundle is not a macOS installation; target compatibility remains explicit. Actual
   owner activation is outside this goal and still requires separate owner release review.
5. Completed reference schema inspection/migration: legacy workspace v1 remains readable;
   new v2 declares record schema 1. Explicit owner preview, mandatory backup, exact plan
   approval, policy-revision invalidation, and a recoverable maintenance journal preserve
   record/evidence bytes and adopted decisions. Nine process-termination boundaries,
   changed inputs/authorization, failed backups/history, runtime rechecks, and migration
   archive validation pass. Unknown versions are rejected. See `docs/schema-migrations.md`
   for the separate recovery command, pending-backup restriction, and explicit limitation:
   this migrates data within an approved runtime, not a private software-release upgrade.
   The offline installed CLI migration/restore trial at `1b72f1b` passed (15 distributions,
   877 verified files), with all 13 exact-image isolation checks. Its reports are in
   `docs/evidence/migration-release-trial.json` and `migration-worker-profile.json`.
6. Completed synthetic gold-set report: 129 mechanical checks, eight query cases, 36
   supported citation occurrences, zero observed disclosure/write violations, and 12
   fixture proposals changing 13 pages. Latencies, flags, and zero model calls/cost are
   retained in `docs/evidence/goldset.json`; human review duration/edits and semantic
   usefulness remain explicitly unmeasured by the gold set. See `docs/evaluation.md`.
   Actual second-session continuity is assessed separately in the manual M2 review;
   this mechanical report does not satisfy it.
7. The full requirement mapping is in `docs/requirements.md`, with inspected source,
   named tests, retained reports, limits, and the explicit manual gate. The audit closed
   the missing Markdown review report: current diffs, dates/coverage/conflicts, local
   evidence links, scope revocation, and active-content escaping now have six tests.
   Installation, privacy, recovery, agent-integration, evaluation, migration, and review
   procedures are documented. The final offline installed trial at `6bcad55` passed:
   Markdown source review, the complete synthetic workflow, migration, restore, package
   tamper rejection, and activation denial without an engine. It verified 15 distributions
   and 878 files; the exact worker image passed all 13 checks. Retained evidence is in
   `docs/evidence/final-release-trial.json` and `final-worker-profile.json`.

The owner supplied the manual M2 response, reporting GPT 6 Astra Light and seven seconds.
It uses the saved provenance decision in a concrete bilingual test design, avoids
title-only retrieval, cites the relevant context sections, and does not invent execution
or approval. The reviewer records a narrow continuity pass, with the owner's original
unclear verdict retained. The original receipt fails the Cairn schema; a labeled reviewer
normalization passes and does not invent experimental results or second-agent citations.
See `examples/continuity/manual-evaluation.json` and the recorded manual review in
`docs/research-continuity.md`. External session isolation/network were not independently
observed. No in-scope milestone gate remains unevaluated; actual deployment is separate.

The private directory remains untouched. Actual private activation, owner real-data
evaluation, real cloud grants, publication, and M4 are outside the current goal. No public
test result substitutes for owner release acceptance; the limited manual observation
also does not establish general semantic quality.
