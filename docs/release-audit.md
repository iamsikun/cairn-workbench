# Remaining M3 release audit

M0/M1 reference gates pass. M2 mechanics pass; its second-agent semantic trial is manual
and pending by owner choice. M3 now passes 131 cumulative tests plus installed worker,
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
   runbook. Still supply the reviewed-installation activation/restore gate and make doctor
   report actual gates. The bundle is not a macOS installation; target compatibility must
   remain explicit. Exercise remaining work with synthetic files only.
5. Add versioned schema inspection/migration support with backups and rejection of unknown
   versions. Existing durable version-one additions must remain readable; no silent
   destructive rewriting, relabeling, or approval reuse after a migration.
6. Run and retain the synthetic gold-set report for exact source, multiple sources,
   contradictions, outdated rules, absent evidence, roles, Chinese/English retrieval, and
   project continuity. Record observed citation support, write correctness, unauthorized
   disclosures, pages/review flags, latency, and honest model-cost/semantic limitations.
7. Map every brief hard gate to an executed test, manual gate, or named unsupported
   capability. Finish installation, privacy, recovery, and agent-integration documentation.

The private directory remains untouched. Actual private activation, owner real-data
evaluation, real cloud grants, publication, and M4 are outside the current goal. No public
test result is a substitute for the selected manual continuity session or release review.
