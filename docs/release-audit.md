# Remaining M3 release audit

M0/M1 reference gates pass. M2 mechanics pass; its second-agent semantic trial is manual
and pending by owner choice. M3 now passes 110 cumulative tests plus installed worker,
isolation, and real-engine lifecycle trials. These results do not close the full goal.

Before release review, finish the following public, synthetic-only work:

1. Audit every processing path against the complete request, including question and
   derived labels. Provide owner-facing route/grant inspection and audit receipts;
   reject missing, expired, destination-mismatched, or scope-mismatched grants. Keep cloud
   execution unavailable until a concrete compliant adapter exists, with no fallback.
2. Completed reference hardening: backup/restore now preflights paths, canonical metadata,
   evidence/quotes, history configuration, and journals. Staged publication avoids partial
   destinations; a >32 MiB ZIP and interrupted apply restore pass. Private restore still
   depends on the reviewed-runtime gate in item 4.
3. Completed reference hardening: worker streams/deadlines are bounded, remote Docker
   endpoints and implicit volumes are rejected, and owned-container cleanup is required.
   Real-engine create/start/removal and synthetic launcher failure tests pass. Full private
   installation verification remains separate; no daemon socket was mounted in a worker.
4. Deliver an offline installed-wheel trial and release manifest containing the reviewed
   code commit, wheel/dependency hashes, lock hash, versions, and pinned worker images.
   Verify installed imports rather than editable-checkout imports. Supply an explicit
   reviewed-installation activation/restore procedure and make doctor report actual gates.
   Exercise it with synthetic files only; do not create the real private workspace.
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
