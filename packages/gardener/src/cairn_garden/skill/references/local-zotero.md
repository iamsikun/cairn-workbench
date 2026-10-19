# Local Zotero writes

Zotero 9's local REST API reads the library; its standard Connector imports into the current
UI selection and cannot generally update existing memberships. The bundled extension exposes
only authenticated `create` and additive `add` operations on the configured personal library.
It uses Zotero's own objects and transactions; it never writes SQLite directly, deletes items,
overwrites existing metadata, downloads attachments, changes UI selection or executes supplied code.
Zotero must be open. Cloud sync, when configured in Zotero, remains Zotero's responsibility.

## Install and verify

1. Set the intended `zotero_user_id` and `zotero_backend = "local"` under `[garden]` in
   `~/.config/cairn-workbench/config.toml`.
2. Build/provision with `cairn-garden zotero-bridge --output /absolute/path/gardener-local.xpi --credentials`.
   It creates `~/.config/kb-gardener/zotero-local.json` with a random local token and mode 600;
   it never prints the token. The extension reads that fixed path, so it stays there whatever
   the cairn-workbench configuration is. Do not commit credentials or put them in notes.
3. Install that XPI using Zotero's Tools → Plugins interface. Obtain any required application
   installation confirmation. A matching extension build is required after bridge source changes.
4. Run `cairn-garden health`. Run both `daily` and `weekly` manually, with real agent reports,
   an actual import and an existing-item collection addition in each. `--zotero-limit N` bounds
   a verification pass. Use externally verified papers already needed by the KB, and verify final
   memberships. Dry runs, no-op passes, mock agents and failed read-backs cannot satisfy this gate.
5. Run `cairn-garden readiness`, then `cairn-garden enable-zotero-writes`. `cairn-garden schedule`
   also checks/enables this gate for an explicit local backend before registering jobs.

Scheduled invocation checks that the stored gate names the configured library. Once enabled, it
stays open across releases: after a change to the write code or configuration, the next scheduled
run that writes re-verifies the gate by read-back, and a failed verification pauses it. With
`zotero_strict_write_gate = true` under `[garden]`, any such change closes it until both
workflows are verified again. Reports can still run with a sync preview while closed. A failed write, missing bridge or closed Zotero in an enabled local workflow
prevents completion, so the 15-minute schedule can retry. Disable scheduled writes immediately by
removing `zotero-writes-enabled.json` from the gardener's workspace state folder; this preserves all library items.

## Integrity and retries

Collections are addressed by key, independently of the selected UI collection. Additions run
inside a serialized Zotero transaction and preserve other memberships. Metadata must resolve
externally to its DOI/arXiv identity before an import. The bridge rejects conflicting keys,
ambiguous identities, trashed matches, wrong accounts, missing collections and unsupported fields.
A durable random item key is reserved before sending an import, and an in-transaction identity
check makes retries safe even across restarts. Python independently reads every resulting item
through the normal local REST API and checks identity, metadata and collection membership.
The daily budget is shared by daily/weekly/standalone passes and reserves uncertain attempts.
Unknown Web API creations must be reconciled before switching their receipts to the local backend.

Endpoint `/kb-gardener/v1` accepts JSON POSTs only, rejects browser origins, and requires a local
Bearer token plus the configured account ID. The client rejects non-loopback hosts, proxies,
redirects, incompatible builds, and broadly readable credential files. The plugin contains no token. Zotero requires an HTTPS update URL even for local extensions. The reserved `.invalid` URL
has no update server; disable automatic updates for this extension after installation. Updates
are installed as reviewed local packages, without weakening Zotero’s update security settings.
Remove/disable “Cairn Gardener Local Zotero” in Zotero's Plugins window to remove the endpoint.
