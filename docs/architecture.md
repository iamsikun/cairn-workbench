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

Scope, classification, processing permission, and domain are separate concepts. Derived
records retain the strongest classification and local-only restriction of their inputs,
plus all access compartments. `shared` does not mean public. Owner CLI scope selection
is trusted configuration; model workers have no CLI access to the owner workspace.

The synthetic inline provider is a test facility and cannot be enabled for a private
workspace. `FakeProvider` only quotes evidence and connects a selected project; it is
not a model. Query currently returns labeled evidence excerpts and related synthesis,
with dates, versions, coverage, and explicit insufficient-evidence status.
