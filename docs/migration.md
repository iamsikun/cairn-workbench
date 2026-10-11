# Explicit migration to workspace schema 4

Install and check the new package separately. Migration is never a package-install or
startup side effect. For a managed installation, first complete the retirement procedure
in [updates](updates.md). Resolve pending legacy transactions with the compatible legacy
runtime; do not accept pending proposals merely to migrate.

```sh
cairn migrate --workspace /synthetic/legacy --backup /synthetic/pre-migration.zip
# If an unlabeled legacy note needs a collection:
cairn migrate --workspace /synthetic/legacy --backup /synthetic/pre-migration.zip \
  --mapping /synthetic/collections.json
```

`collections.json` maps exact legacy relative note paths to research/finance/life/shared.
Unclear notes require explicit mapping. Typed records keep their existing collections.
Schema 1, 2 and 3 inputs are validated with their existing validators before conversion.

The migration creates a verified archive and a recoverable `migration.pending` journal.
It inventories every retained source, blob, note, proposal, approval, receipt, library record
and history file. Existing files remain byte-for-byte; only `workspace.json` switches format,
and its original is retained under `legacy/`. IDs remain stable. Human notes become searchable
records with separately attributed observations and a hash-bound original. Legacy decisions
retain their original provenance; migrated or newly saved content is not automatically
verified or adopted. Pending proposals remain legacy material, outside ordinary retrieval.

New records live under `vault/collections/COLLECTION/`. Old cross-collection links stay in
original records and are flagged for reconciliation without exposing their endpoints to
a different collection. Reading an old record or backup never rewrites it automatically.

After interruption, rerun the same command with the same backup path. The converter verifies
backup and original hashes before resuming. External edits cause a recoverable conflict.
Configuration switches last; an old executable rejects schema 4. No implicit downgrade or
runtime rebinding occurs.

Rollback means restoring the pre-conversion archive into a separate new directory and using
a compatible historical executable there. Keep the migrated workspace and any newer saves;
never point the old executable at schema 4 or overwrite it with an older archive.
