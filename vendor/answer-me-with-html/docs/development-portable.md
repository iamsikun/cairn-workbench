# Native portable development

This licensed source snapshot is maintained by Cairn. Use Node 24 with `npm ci
--ignore-scripts`, a synthetic staging copy, and acquired Node 20/22/24 executables
selected by `CAIRN_NODE20`, `CAIRN_NODE22`, and `CAIRN_NODE24`. No Docker is used.

Run `bash scripts/check_html.sh` from the Cairn repository root for reproducible
application/generic builds, regressions, required Chromium checks, and portable ZIP
trials. See Cairn's `docs/development.md` for acquisition and native prerequisites.
Chromium must retain its sandbox and use a temporary profile. Native processing is
not a network or filesystem sandbox. No owner data, credentials, installed skills,
remotes, or publication belong in contributor verification.

To run this snapshot independently after acquisition, set `AM_E2E=1`, optionally
`AM_CHROME`, and synthetic `AM_HOME`, then run `sh scripts/check-portable.sh`.
Both builds remove machine-dependent dependency path comments. Record runtime
versions and executed checks; historical container passes are not native evidence.
