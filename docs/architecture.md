# Architecture

Cairn's new runtime connects an existing agent to one collection. Finch and Quill provide
reading and writing methods. Six tools share the CLI's save/retrieval services.
Markdown records and versioned visual resources are canonical. Original source blobs
and attributed contributions are preserved. Stable IDs connect papers, topics, projects
and questions. Explained relationships preserve direction, provenance and corrections.
SQLite search is disposable and collection-specific. Graph neighbors are resolved from
the selected collection's canonical records.

The writer validates a bounded change set under a workspace lock, journals before/after
bytes, and commits content plus revision receipts. Readers refuse prepared transactions.
Recovery preserves unexpected third-party bytes. Operation keys make retries safe;
undo is compensating. Hashes detect ordinary editor changes, but editors ignoring the
lock do not participate in Cairn's multi-file transactions.

Persistence, semantic enrichment, indexing and rendering have separate states. Only the
connected agent performs semantic enrichment. Native extraction/rendering have resource
limits, not a claimed host sandbox. HTML is requested, tracks inputs, and preserves
snapshots. Client metadata does not grant permissions or verify claims.

Legacy formats and validations remain only for compatibility/migration. Historical
architecture is in legacy/architecture-v3.md. Migration is explicit and backed up;
software installation does not implicitly convert data.
