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
archive paths blindly. It preflights directory/file and case/Unicode collisions, durable
schemas, source/evidence bindings, quote locators, and journal before/after hashes. Git
history settings must match the local bare-repository profile; executable filters and
external object directories are rejected. Backup destinations must be outside code and
workspace roots.

Restore copies into an owner-only temporary sibling directory, verifies the copied hashes,
then renames the complete directory into the empty destination. A copy error leaves the
requested destination unpublished. An abrupt process termination may leave a staging
directory with `restore.pending`; Cairn refuses to open it. Retry from the intact archive
into the intended empty destination and inspect/remove abandoned staging as owner
maintenance. The archive is never deleted by restore.

The ZIP format supports up to 256 MiB of durable payload, 32 MiB per source/durable file,
and fewer than 10,000 payload files. ZIP metadata has a separate 16 MiB allowance. Larger
workspaces require an owner-controlled filesystem snapshot of the same durable directories
while no writer runs; preserve text, blobs, evidence, approvals, receipts, journals, and
history together. Such external backups are outside the built-in ZIP verifier.

Ordinary backup refuses an unresolved transaction. `cairn backup ... --include-pending`
explicitly preserves its journal and authorization for recovery elsewhere. After restore,
normal readers still refuse that pending bundle until `cairn recover` succeeds.

Backup hashes detect corruption; they do not authenticate an untrusted backup supplier.
Keep the independently recorded archive digest and store backups with owner-controlled
access. Supply that digest with `cairn restore ... --expected-sha256 DIGEST` to verify it
before parsing or writing. Private restore and the installed-release runbook remain M3 work.
