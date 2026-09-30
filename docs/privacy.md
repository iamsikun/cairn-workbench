# Privacy and processing

Keep the private workspace outside all public/development checkouts after realpath
resolution. All vaults, evidence, proposals, approvals, receipts, caches, local history,
and backup artifacts remain private. Public examples and tests use synthetic data only.
Do not attach home directories, private credentials, or private workspaces to CI.

Default labels are private and local-only. A public document does not make a private
question exportable. Policy contains separate scope and destination/operation/time-bound
cloud grants; credentials do not constitute consent. The existing runtime uses local
extraction and local client packets and has no remote fallback or telemetry.

Workers receive bounded authorized inputs. Search databases contain only the authorized
corpus, including ranking statistics. Titles, counts, references, backlinks, snippets,
and cached payloads do not come from a global model-visible index. Policy and corpus
changes alter cache identities; cache deletion loses no durable knowledge.

The owner can always copy data manually, and already exported information cannot be
retracted by revoking a scope. The application must not label an unverifiable client
route local-only. A missing local model is a blocked capability, not a reason to send
data to a cloud model.

## Owner policy changes and audits

`cairn policy show --workspace PATH --json` returns the policy and its SHA-256. Use
`policy set-scope SCOPE.json` or `policy set-grant GRANT.json` with that exact
`--base-hash` and an explicit `--statement`. The versioned public schemas describe
these files. Grant consent must exactly match the statement, with a future timezone-aware
expiry, scope, operation set, provider, and destination. Grant creation does not activate
a cloud adapter. `policy revoke-grant ID` uses the same owner statement/hash checks.

Every change increments the policy revision and writes an immutable before/after audit
under `receipts/policy/` before atomically replacing the policy. `policy history` verifies
the committed chain and distinguishes unapplied intents left by interrupted changes.
The chain preserves the exact initial bytes, including owner formatting. Direct policy
edits after an audited change break verification; use the owner commands. Replacing a
scope revokes its existing grants so consent cannot silently widen with membership.
Policy changes invalidate jobs, approvals, and derived-cache identities.

`policy check-route REQUEST.json` checks a hypothetical complete request and saves a
receipt under `receipts/routes/`. Include record IDs, question labels, and any instructions,
derived metadata, output handling, and trace content. Missing labels remain restricted
and local-only. Cited source labels are included even when only synthesis was selected.
Grants must match every route dimension and all labels. An otherwise eligible cloud
request returns `blocked: cloud_adapter_unavailable`; it transmits nothing. An audit's
`allowed` decision is only a policy decision, never evidence that a model ran. No command
exports packets to an unverified external client or grants authority to source text.

Extraction, generation, and explicit client-packet preparation save route decisions bound
to the complete input packet hash. Receipts contain hashes and policy metadata, without
question or source plaintext. Ordinary search/query and context creation run locally and
do not append durable route receipts; query reports its local extractive processing and
context includes its policy hash and inherited labels. An explicit `check-route` provides
a durable audit when needed. Disposable query caches remain local and scoped.

These owner commands are deliberately absent from the worker protocol. Owning filesystem
access to the policy/approval store is the authority boundary; a user-selected CLI scope
does not confine a coding agent that independently has owner shell access.

Private operation requires the [reviewed activation gate](installation.md). It binds the
installation and worker image to a durable owner review, checks a fresh worker probe,
and rechecks installed files on subsequent access. A development checkout cannot satisfy
the gate. Actual deployment remains separate after manual continuity and release reviews.
