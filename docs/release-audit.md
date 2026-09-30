# Remaining M3 release audit

M0/M1 reference gates pass. M2 mechanics pass; its second-agent semantic trial is manual
and pending by owner choice. M3 now passes 169 cumulative tests plus installed worker,
isolation, and real-engine lifecycle trials. These results do not close the full goal.

Before release review, finish the following public, synthetic-only work:

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
   owner activation is outside this goal and still requires the pending manual review.
5. Completed reference schema inspection/migration: legacy workspace v1 remains readable;
   new v2 declares record schema 1. Explicit owner preview, mandatory backup, exact plan
   approval, policy-revision invalidation, and a recoverable maintenance journal preserve
   record/evidence bytes and adopted decisions. Nine process-termination boundaries,
   changed inputs/authorization, failed backups/history, runtime rechecks, and migration
   archive validation pass. Unknown versions are rejected. See `docs/schema-migrations.md`
   for the separate recovery command, pending-backup restriction, and explicit limitation:
   this migrates data within an approved runtime, not a private software-release upgrade.
6. Run and retain the synthetic gold-set report for exact source, multiple sources,
   contradictions, outdated rules, absent evidence, roles, Chinese/English retrieval, and
   project continuity. Record observed citation support, write correctness, unauthorized
   disclosures, pages/review flags, latency, and honest model-cost/semantic limitations.
7. Map every brief hard gate to an executed test, manual gate, or named unsupported
   capability. Finish installation, privacy, recovery, and agent-integration documentation.

The private directory remains untouched. Actual private activation, owner real-data
evaluation, real cloud grants, publication, and M4 are outside the current goal. No public
test result is a substitute for the selected manual continuity session or release review.
