# Architecture

Cairn stores durable records as validated Markdown/YAML, original evidence as hashed
blobs, and immutable extraction/locator artifacts as JSON. SQLite FTS5 indexes are
disposable and built only from records authorized by the effective scope.

The owner CLI is the trusted writer. Capture records provenance before extraction.
Extraction and generation can run in a pinned local worker image using JSON over
stdin/stdout. The model receives a bounded job rather than a vault mount. Its result
becomes an untrusted proposal; it cannot choose canonical paths, weaken labels, grant
access, or approve itself.

The successful workflow is `captured → extracted → proposed → validated → approved →
applied → indexed`. Durable events track failures without advancing the successful
stage. Approving also records a fresh successful validation. Source versions and proposal
attempts retain separate identities. Index/history failures remain pending maintenance.

Proposal approvals bind workspace, content, policy, inputs, and review flags. Apply
revalidates under a single writer lock, journals before/after bytes, replaces files,
records a durable receipt, then maintains indexes and local Git history. Readers refuse
an incomplete bundle until recovery. The history repository is local and has no remote.

Workspace schemas 1 and 2 are readable without implicit rewriting. Explicit owner schema
migration uses the same writer lock, a mandatory backup, a digest-bound preview, and a
separate recoverable maintenance journal. It cannot accept worker-supplied configuration
edits. The initial migration declares the record schema without rewriting record bytes
and advances policy revision to invalidate pending approvals. See
[schema migrations](schema-migrations.md) for version and recovery limits.

Scope, classification, processing permission, and domain are separate concepts. Derived
records retain the strongest classification and local-only restriction of their inputs,
plus all access compartments. `shared` does not mean public. Owner CLI scope selection
is trusted configuration; model workers have no CLI access to the owner workspace.

The synthetic inline provider is a test facility and cannot be enabled for a private
workspace. `FakeProvider` only quotes evidence and connects a selected project; it is
not a model. Query currently returns labeled evidence excerpts and related synthesis,
with dates, versions, coverage, and explicit insufficient-evidence status.

Research adapters preserve selected bibliography exports and role-attributed session
receipts as evidence. Receipt import stages observations and draft decisions. A separate
owner-adoption proposal followed by exact approval/apply establishes current decisions;
context generation verifies that chain against the canonical decision bytes. A source
or assistant-supplied authority flag has no effect.

Context generation is local and read-only unless the owner explicitly saves the pack.
It checks every retained citation against the selected scope and exact evidence, includes
only project-bound material, propagates labels including the question, and trims complete
items with their citations intact. A repository fingerprint is verified only against an
explicitly selected root and never executes project code. Saved packs represent their
generation instant and may become stale after any subsequent change.
