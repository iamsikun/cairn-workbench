# Schema inspection and owner migration

New workspaces use workspace schema 2, which explicitly declares record schema 1.
The six Markdown record types and their evidence format remain version 1. Existing
workspace schema 1 files, including files without the optional runtime fields introduced
during development, remain readable. Opening or querying them never migrates them.
Unknown workspace/record versions fail validation; missing private runtime approval is
still denied, even for a valid legacy schema.

The first supported migration is `workspace_v1_to_v2`. It changes only `workspace.json`
and the policy revision/audit pointer. It preserves identity, roots, runtime approval,
labels, scope membership, grants, source bytes, human notes, accepted record bytes,
evidence, and historical approvals. Advancing the policy revision invalidates pending
jobs, proposals, and approvals. Regenerate those from their preserved sources after
migration. Previously applied decisions retain their exact adoption chain.

Run these owner commands from the approved installed runtime, with no concurrent plain
editor writes. Example paths are synthetic:

```sh
/srv/cairn-runtime/bin/python -I -B -m cairn schema inspect --workspace /srv/cairn-private
/srv/cairn-runtime/bin/python -I -B -m cairn schema preview --workspace /srv/cairn-private
/srv/cairn-runtime/bin/python -I -B -m cairn schema apply --workspace /srv/cairn-private \
  --plan-sha256 REVIEWED_PREVIEW_DIGEST --backup /srv/backups/before-schema-v2.zip \
  --statement "I reviewed this format change and the pending-approval invalidation."
```

Inspection validates the durable snapshot using the backup preflight checks. Preview
shows a JSON field diff and a digest binding the exact before/after bytes and complete
durable input hashes; `--json` includes those bytes and hashes. Neither command writes
durable knowledge. These checks share the built-in backup limits: 256 MiB total, 32 MiB
per file, fewer than 10,000 files. No arbitrary migration code, scripts from records, or
model-selected target paths are accepted.

Apply recomputes the preview while holding the owner writer lock. A stale digest or
failed backup prevents migration. The backup must be outside the workspace and public
code, and its destination must not already exist. Keep the printed `backup_sha256`
independently with the archive. Authorizations, exact plans, journal status, and commit
receipts live under `migrations/`; policy history records the revision change. Local Git
history is updated after commit. A history failure is retryable and does not undo the
committed migration; status lives under `receipts/maintenance/`.

After an interruption:

```sh
/srv/cairn-runtime/bin/python -I -B -m cairn schema recover --workspace /srv/cairn-private
```

Normal readers refuse a prepared schema migration. Recovery checks the supported
transformation, owner authorization, policy audit, and all original inputs before
completing either configuration replacement. Unexpected owner bytes stop recovery and
are preserved. Re-running recovery also retries history maintenance. An interruption
before the prepared journal can leave an unused authorization/audit intent and a valid
backup; configuration is unchanged, so review a fresh preview and use a new backup path.

New backups and restore reject a prepared schema migration, including with
`backup --include-pending`. Recover it locally first, or restore the mandatory archive
from before migration into an empty destination and review a new migration there. The
existing `--include-pending` option remains available for synthesis transactions.
Completed migration authorizations and receipts are validated and preserved by backup
and restore. Do not remove journals to bypass a recovery error.

This command migrates a data format within a runtime that already supports both versions.
It does not install software, replace a release approval, weaken a route grant, or migrate
record schema 1 to an invented new record version. Replacing a private installation with
a different release remains a separate unsupported upgrade operation; a workspace bound
to an earlier release must not be opened by unchecked newer code. A future release
upgrade needs its own explicit verification and reauthorization path. Current private
operation still checks the approved installation before inspection, migration, or recovery.
