# Recovery and backups

Apply uses a workspace lock and a durable journal with before/after bytes and hashes.
Readers reject a prepared transaction. After a crash, `cairn recover --workspace PATH`
compares every file against both expected states before completing the approved bundle.
It can recognize replacements that occurred before progress was recorded. A receipt is
written only after every final file hash matches. Re-applying returns the same receipt.

If an owner changed a file during the outage, recovery stops and preserves it. Retain the
journal, receipt, and owner bytes; inspect the approved proposal and reconcile explicitly.
Do not delete the journal to suppress a recovery error. Policy or approval changes during
an incomplete transaction also require owner resolution.

Local history and indexing follow the durable file commit. Their failure does not roll
back accepted files. Maintenance status is in `receipts/maintenance/`; retrying apply or
recovery resumes pending maintenance. Search indexes can always be rebuilt from the vault
and evidence artifacts.

The backup API creates a hash-manifest ZIP containing text, blobs, extraction evidence,
policy, proposals, approvals, receipts, journals, and local history. Caches and lockfiles
are excluded. Restore requires an empty, disjoint root and validates paths, expansion
limits, checksums, and referenced source/evidence bytes before writing. It never extracts
archive paths blindly. Backup destinations must be outside the code and workspace roots.

Backup hashes detect corruption; they do not authenticate an untrusted backup supplier.
Keep the independently recorded archive digest and store backups with owner-controlled
access. Private restore and an installed-release runbook are still required for M3.
