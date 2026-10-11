# Revisions, conflicts, and recovery

A saved receipt is separate from enrichment, search and HTML freshness. Saving persists
Markdown and ready relationships before maintaining derived outputs. A missing renderer
or failed index does not undo a reading. Search rebuilds from canonical records, with a
current, scoped text fallback when index writing fails. Pending semantic enrichment is
returned in notes and left for the connected agent to resume.

Reusing an operation key with identical input returns the original receipt. Changed input
under that key conflicts. An unchanged save makes no new content revision. All ready bundle
targets are checked before any note is written. Revision hashes detect external Markdown
edits. Attempted stale content is retained under `recovery/COLLECTION/` for reconciliation.

A process crash can leave a prepared transaction. Normal operations then report recovery
required. Run `cairn recover --workspace PATH`; recovery accepts each target only at its
recorded before/after bytes. Unexpected external edits remain untouched and require explicit
reconciliation. Do not delete a journal to make an integrity conflict disappear. Cooperating
clients serialize on a workspace lock; an independent text editor does not honor that lock.

`cairn recent --workspace PATH` lists saved checkpoints in the selected collection.
`cairn undo REVISION OPERATION_KEY --workspace PATH` writes a compensating revision. It
preserves captured source bytes, original observations and unrelated later work. Reversing
a record changed by later work, or hiding a newly created note referenced by later work,
conflicts rather than overwriting it.

`cairn backup DESTINATION.zip --workspace PATH` writes and verifies a checksummed archive.
`cairn restore ARCHIVE.zip NEW_DESTINATION` validates before writing and only restores to a
new location. It cannot silently replace newer saves. Legacy archive payloads retain their
version-specific validation. Indexes are rebuilt, not trusted from archives. Archive size
is bounded; a rejected or interrupted backup is not a verified recovery point.
