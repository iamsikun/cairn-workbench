# Remaining M3 release audit

M0/M1 reference gates pass. M2 mechanics pass; its second-agent semantic trial is manual
and pending by owner choice. M3 domain mechanics pass 86 cumulative tests plus installed
worker and isolation trials. These results do not close the full M0–M3 implementation goal.

Before release review, finish the following public, synthetic-only work:

1. Audit every processing path against the complete request, including question and
   derived labels. Provide owner-facing route/grant inspection and audit receipts;
   reject missing, expired, destination-mismatched, or scope-mismatched grants. Keep cloud
   execution unavailable until a concrete compliant adapter exists, with no fallback.
2. Harden and retest full backup/restore: archive-wide case/Unicode/parent collisions,
   missing manifests, malformed canonical records, referenced blob/evidence integrity,
   pending transactions, and the mismatch between the 256 MiB archive budget and the
   current 32 MiB `RootFS.write` default. Validate everything possible before writes.
3. Bound worker stdout/stderr during execution, rather than only after `subprocess.run`.
   Ensure a timeout terminates the owned container, not merely its Docker client process.
   Test failure cleanup without mounting private state or a Docker socket in a worker.
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
