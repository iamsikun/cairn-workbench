# Journal library

The library is an owner-maintained catalog over a read-only journal-folder archive.
Catalog entries are research `entity` records. Their `cairn_library_v1` section is
validated by the exported Journal/Paper schemas; this additive representation leaves
existing record serialization and sealed proposal hashes unchanged. Source snapshots
and PDFs use existing `source` records. Model proposals cannot create, overwrite, or
strip library metadata. Personal reading state is an owner operation.

Configure explicitly using the reviewed installed runtime, never a development checkout:

```sh
cairn library configure /srv/source-library --workspace /srv/cairn
cairn library scan --workspace /srv/cairn --json
cairn library journals --workspace /srv/cairn
cairn library papers --workspace /srv/cairn --reading unread
cairn library mark entity_example read --workspace /srv/cairn
cairn library export --workspace /srv/cairn --output /srv/reports/library.html
```

Configuration is an explicit additive catalog migration. It is idempotent for the same
route and refuses a changed root: relocation must not silently rewrite provenance.
The first successful scan establishes the baseline and does not enqueue old papers for
reading. Unknown metadata stays unknown; filenames are provisional titles. PDF title
and author fields are observed metadata, not verified bibliographic truth. DOI extraction
refuses ambiguous first-page matches. Files over the bounded PDF processing limit,
encrypted files, symlinks, and unsupported archives are reported rather than silently
counted as fully processed. `--rehash` verifies bytes even when file size/time match.

Missing paths are marked only after a complete scan. Offline roots do not erase records.
Reading state and owner-corrected fields survive rescans. Owners can submit an explicit
JSON correction with `library correct PAPER FILE`. Shared bytes deduplicate a paper;
contradictory DOI/hash identities are reported for review.

All catalog writes use the workspace lock and bounded recoverable owner transactions.
Interrupted transactions block readers until `cairn recover`. No model actor label is
authority to run this writer. Scope-filtered SQLite catalog indexes are disposable.
The HTML export escapes imported text and has no active scripts or network resources.

The remaining interfaces are `library discover`, `library capture`, `library update`, and
`feed latest/history/export/acknowledge`. `library update` scans, checks configured
journals for new publications, records feed events and saves a digest. Filenames never
supply personal reading status.

Cairn no longer reads papers itself. The offline GPU reader, owner-device enrollment
and subscription verifiers were retired: to read a paper, capture it with
`library capture PAPER` and read it from your agent through a reading packet (see
[agent integration](agent-integration.md)). The result enters the normal proposal
queue. Receipts left by the retired reader stay in the knowledge base but are no longer
interpreted, and saved views that showed reader state must be regenerated.
