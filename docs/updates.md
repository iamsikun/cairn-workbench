# Package updates and managed-installation retirement

New-format Cairn does not update itself at startup, run a scheduler, approve runtimes or
rebind releases. Install package updates deliberately. Updating software never migrates a
knowledge base. Historical managed-update code remains behind `cairn legacy` for compatible
old installations; its authorization, channel, hash and downgrade checks remain intact.

Retiring an existing managed installation is a separate owner operation:

```sh
cairn retire-installation /synthetic/managed /synthetic/bin/cairn /synthetic/new/bin/python \
  --user-home /synthetic/owner
```

Arguments identify the managed home, its exact Cairn-owned launcher and the independently
installed replacement Python. The replacement is checked for schema 4 and the six tools.
The transition records original launcher/configuration/schedule bytes before changes and
preserves all installed runtimes and backups. It disables launch-triggered updates, removes
only the matching launchd or cron job, verifies removal, and replaces only the recognized
Cairn launcher. Unrelated jobs and launchers are preserved.

The updater's lock prevents transition during an active update. A process check also catches
an updater that started before acquiring that lock. Busy or unverifiable states do not pass
retirement; let the running updater finish and retry. If a scheduler or process check fails,
auto-updates remain disabled and the journal supports resumption. Do not migrate until
retirement reports success. Direct manual execution of historical binaries is outside the
new launcher's control.

Rollback artifacts are evidence and recovery material, not an automatic restoration action.
Do not reactivate an old launcher against migrated data. Restore an old backup into a separate
location if historical operation is necessary. See [migration](migration.md).

Contributor acceptance uses synthetic homes and scheduler adapters. It never modifies actual
client settings, launchd, cron, startup entries or update schedules. Actual owner-machine
retirement remains a separate deployment trial. Historical details remain in
[the previous updater guide](legacy/updates-v3.md).
