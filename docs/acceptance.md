# Acceptance evidence

## Native Docker removal (2026-10-11; implementation in progress)

Docker execution, worker activation and managed updater installation/enabling are retired.
Historical worker profiles remain data for approval validation. Native adapters enforce
process deadlines and stream budgets and clean up their owned process groups; they do
not establish network or filesystem isolation. Linux PDF extraction retains its address-
space limit; macOS uses CPU/input/output/deadline budgets without that memory limit.

Executed milestone checks on macOS arm64, Python 3.12.12:

- 90 release/schema/updater/upgrade-chain/installation-transition tests passed.
- 30 activation/archive, discovery/catalog, presentation and release tests passed.
- 12 legacy draft/cached-extraction tests passed after preserving the cached read path.
- 9 native process/retired-worker tests passed, including descendant cleanup after the
  leader exits. The restricted shell denied `ps`; the complete targeted rerun passed
  outside that shell, inspecting only synthetic child PIDs.
- 3 configured/missing-Node and failed-parser preservation tests passed.
- Ruff and strict mypy passed (125 source files).
- Native Chromium's application acceptance test passed with its sandbox enabled and a
  temporary profile. The restricted-shell browser attempt did not pass.

The complete `bash scripts/check.sh` native gate then passed: **400 tests**, Ruff,
strict mypy across **125 source files**, **129/129 gold-set checks**, synthetic
continuity preparation, and a **272,631,034-byte / 65-blob** backup/restore trial.
The rejecting Docker sentinel was never invoked. Outputs are retained locally in
`dist/native-goldset.json` and `dist/native-library-backup.json`.

Full renderer and installed-package results will be recorded below after execution.
All inputs/settings are synthetic; no owner workspace, real schedule, installed skill,
Docker installation/images, or client configuration was changed. Historical evidence below
is retained unchanged and does not establish native acceptance.


## Direct-save restructuring (2026-10-11; automated gates passed, not released)

Historical evidence below applies to the previous requirements. It is not a passing
gate for the direct-save release. Only synthetic data is used in this implementation.

| Gate | Evidence | Status |
| --- | --- | --- |
| R1 requirements and legacy fixtures | Revised baseline; 3 fixture-reader tests passed in offline development container | Passed |
| R2 saves, recovery, undo | 14 direct-save tests: retries, no-op, external/stale edits, two concurrent processes, four crash points, recovery conflict, index failure, selective undo | Passed |
| R3 notebooks, graph, scope | Paper follow-up identity and duplicate rejection, aliases/questions, retained observations, explained backlinks, rejected-link memory, scoped reads and located quotes | Passed with synthetic inputs |
| R4 CLI/MCP/connections/extraction | Six synthetic integration tests: CLI init, six-tool stdio, retry/resumption, two client settings formats, interrupted registration, unavailable/actual PDF parsing | Adapter checks passed; actual clients unverified |
| R5 HTML and scenarios | Four presentation tests plus mandatory Chromium: desktop/narrow, themes, print, reduced motion, offline requests, deterministic temporary controls | Passed, including installed package |
| R6 migration/install transition | Eleven migration/backup tests, five retirement adapter tests; verified inventories, real interrupted conversion, proposal/library retention, updater lock/process races, orphaned loaded jobs | Passed, including installed package; real owner-machine transition unverified |
| Actual Claude Code/Codex behavior | Separate real-client synthetic trial | Unverified |
| Semantic quality | Human assessment of real model explanations | Unverified |

No private workspace, home, credentials, real client settings, or schedules were used.

Final implementation and package revision: `a67a0993d1ccc0842279fffa1de727cc0bb5d39d`,
on local branch `codex/direct-save-workbench`, version **0.4.0**. The following evidence
commit changes documentation only. All R1–R6 implementation milestones are complete;
the actual-client and semantic-quality gates remain open.

- `bash scripts/check.sh` passed: **421 tests**, schema export parity, Ruff and strict
  mypy across **124 source files**; both development/worker **13-check isolation**
  probes, extraction and HTML round trips, **129/129 gold-set checks**, and real-engine
  worker/hostile-child cleanup. No required isolation check was skipped.
- `bash scripts/check_html.sh` passed. The vendored renderer reported **787 passed,
  2 skipped, 0 failed** out of 789 tests. The skips concern a foreign-user PID fixture
  (PID 1 is signalable by the container user) and an optional prebuilt static-site
  check; neither establishes a passing required gate. Required Chromium, container
  isolation, reproducible bundle/portable builds and [Node 20/22/24 trials](evidence/direct-save-node-smoke.json)
  passed. The native-renderer separation was followed by a successful rerun of the
  [notebook/scenario browser checks](evidence/direct-save-browser.json).
- `bash scripts/release_check.sh` passed sequentially after the final check run.
  The [offline installed trial](evidence/direct-save-release.json) verified 15
  distributions and 952 package files. Its new-format trial exercises installed
  CLI initialization, documented legacy migration, synthetic Claude/Codex settings,
  six-tool stdio saving/retry, search, native HTML, backup/restore and undo. The final
  pinned-worker [13-check probe](evidence/direct-save-worker-profile.json) passed.
  Retained legacy trial fields describe compatibility, not new save requirements.
- The [scripted two-paper demonstration](evidence/direct-save-demo.json) retains an
  observation, connects recommendation and decoder notebooks, refreshes requested
  HTML, preserves a snapshot and undoes a change without removing an unrelated
  question. It uses synthetic adapter requests, not actual clients or model calls.
  Generated pages, screenshots and print PDFs are under `dist/notebook-demo/`.

Earlier final-check attempts with overlapping Docker image tags and an outdated
schema-1 package fixture failed and were not counted as passes. The fixture was
corrected without weakening legacy validation; the complete checks above were
rerun sequentially. The installed package and wheelhouse remain local under
`dist/release-a67a0993d1ccc0842279fffa1de727cc0bb5d39d/`; nothing was published.

No automated result establishes Finch/Quill explanation quality, actual Claude Code
or Codex behavior, or a real managed-installation transition. Those trials remain
unverified. The native extraction/rendering resource limits are not claimed to be
equivalent to the contributor container's isolation boundary.

R2/R3 checkpoint: 85 tests passed in the offline development container (direct-save,
legacy fixtures and schema parity). Strict mypy passed for 13 new/changed source modules;
the persistence modules pass Ruff. Source and record storage use schema 4 / record schema 2.
These checks do not establish semantic correctness of generated links or learning prose.

Integration checkpoint: 35 direct-save/integration/presentation/transition tests passed.
The scripted two-paper demo preserves an observation, connects recommendation and decoder
notebooks, refreshes HTML, preserves a snapshot, and undoes a change while retaining an
unrelated question. It uses synthetic adapter requests, not actual Claude Code/Codex or
Finch/Quill model execution. The browser gate used required Chromium, two widths (1440/390),
two themes, print output, reduced motion, offline requests and deterministic temporary
scenario controls. Desktop notebook and narrow scenario screenshots were visually inspected;
evidence placement and scenario-control placement were corrected and rechecked.

## Repository code source and workspace schema 3 (2026-10-11; software checks passed, not released)

A knowledge base can name Cairn's code by repository URL, by local checkout paths,
or by both (workspace schema 3). Checkout paths keep the disjointness guard; the
`.git`-ancestor rejection applies whatever the code source. `workspace_v2_to_v3` is a
supported owner migration, and `cairn code-source set` is an owner-writer command.

`bash scripts/check.sh` passed on the working tree: **377 tests**, including 11 new
cases in `tests/test_code_source.py`, schema parity, Ruff, strict mypy across 104
source files, all required isolation probes (13/13 checks), worker extraction and
HTML round trips, **129/129 gold-set checks**, and real-engine worker/child cleanup.
No isolation check was skipped. The new tests cover repository-only init, the
managed `updater.json` default (synthetic `CAIRN_HOME`), the `.git` guard without a
code root, schema 2 staying valid and migrating to 3, owner change with receipts and
backup/restore round trip, rejection of a new checkout that overlaps the workspace or
a configured library root, restore keeping or replacing the code source, and the
owner-terminal requirement. The automatic-update test now migrates schema 1 to 3 in
two backed-up steps. Schema 1 and 2 JSON exports are byte-identical.

Not run: `scripts/release_check.sh` (it needs a clean commit and produces release
artifacts) and the installed-release trial, so installed-wheel behavior of the new
options is unverified. No real workspace, home directory or remote was used.

## 0.3.0 release verification (2026-10-10)

After the owner requested publication, the package, module and lockfile versions
were advanced together to 0.3.0. Release notes clarify that paper notes and topic
notes are Markdown pages, and HTML is an optional generated view.

The release candidate `d4156d2c8676070bed064a2333a2e2d2991efdf5` passed
`bash scripts/check.sh`: **364 tests**, schema parity, Ruff, strict mypy across
102 source files, all required isolation probes, worker extraction and HTML
round trips, **129/129 gold-set checks**, and real-engine worker/child cleanup.
No isolation check was skipped. The initial sandboxed build could not write
Docker builder metadata; the authorized rerun completed successfully.

`bash scripts/release_check.sh` then passed sequentially on that clean commit.
The [offline installed trial](evidence/release-0.3.0.json) verified 15 distributions
and 929 files, including the evolving paper-note/topic-note workflow and HTML
refresh. Tampered package, renderer and contract rejection passed, along with the
final pinned-worker [13-check isolation probe](evidence/release-0.3.0-worker-profile.json).
The following evidence commit changes documentation only. The renderer source and
bundle are unchanged from the browser, portable-runtime and reproducibility checks
recorded below; those checks were not repeated for the version bump.

All evidence remains synthetic. Real-host agent validation is unperformed, and no
private workspace, installed skill or agent configuration was changed.

## Paper notes, connected notebooks and synchronized HTML — final verification (2026-10-10)

Implementation and installed-release revision: `1847e686c4e0ae46a0b6304c5e710a9ec638901a`
on local branch `codex/paper-notebooks`. No publication, private workspace activation,
installed-skill changes or agent-configuration changes were performed.

- `bash scripts/check.sh`: **364 passed**, schema parity, Ruff and strict mypy
  (102 source files); all **13 isolation checks** in both development and worker
  images; no-mount extraction and HTML/Markdown round trips; bibliography, receipt,
  finance and life extraction; **129/129 gold-set checks**; real-engine lifecycle
  and worker/child removal. No isolation check was skipped.
- `bash scripts/check_html.sh`: **787 passed, 2 skipped, 0 failed** out of 789
  renderer tests. The skips are the generic CLI's other-user PID case (PID 1 is
  signalable in this container) and the generic website check (no prebuilt site).
  Neither is the mandatory Cairn browser or isolation check. Repeated application
  builds and portable ZIPs matched. The application checksum also matches the
  independent Docker build. [Node trials](evidence/paper-notebooks-node-smoke.json)
  passed on 20.19.0, 22.14.0 and 24.0.0 with ordinary and space/non-ASCII paths.
- Mandatory Chromium checks passed for Markdown tables/code, escaped HTML, blocked
  image loads/executable links, evidence, keyboard focus, themes, narrow/desktop
  layout, feedback and print. [Browser evidence](evidence/paper-notebooks-browser.json)
  records **zero external requests and zero script exceptions**. Application light
  and dark screenshots were visually inspected; generated artifacts are under
  `dist/browser-html/application/` in this checkout.
- `bash scripts/release_check.sh`: [offline installed trial](evidence/paper-notebooks-release.json)
  passed with 15 distributions and 929 verified files. It uses the installed MCP
  server to capture, propose a paper and topic together, restore, accept, render,
  revise the same note and verify the notebook HTML refresh. Tampered package,
  renderer and contract checks passed, as did the final pinned-worker
  [13-check isolation probe](evidence/paper-notebooks-worker-profile.json).
  An earlier installed trial passed but its final probe lost an image reference
  when build scripts shared Docker tags. It was not counted as a passing gate;
  the complete release check was rerun sequentially and passed.
- The repository HTML skill passed the skill-creator frontmatter validator inside
  the isolated development container. Installed skills were not edited.

Behavioral coverage is in `test_notebook_workflow.py`, `test_live_html.py` and the
existing MCP/Finch/Quill suites: six original failures, current grants and narrowed
scopes, source versions and identity collisions, project capture/revisions,
two-paper integration, stale/ambiguous targets, immutable exchanges, fresh-session
retrieval after rebuilding indexes, requested HTML only, accepted/editor updates,
changed/unrelated dependencies, failed rendering, first and later interrupted
replacement, output tampering, and inactive registrations after both restore paths.

**Real-host workflow validation remains separate and unperformed.** No actual host
agent or remote model was connected, no private corpus was read, and no semantic
quality claim follows from deterministic answers. The trial exercised the installed
software through a subprocess MCP client on synthetic data. Owner approval remains
required; topic classification is the host agent's proposed choice, and Markdown
remains canonical. There is no background agent, classifier service or watcher.

## Connected paper notes and opt-in HTML — implementation milestone (2026-10-10)

The new synthetic notebook and HTML regressions passed **17 tests** in the documented
offline development container. They exercise two-paper integration and a fresh MCP
client after index rebuild; stable notes across follow-ups and explicit source versions;
ambiguous targets and stale companion drafts; scope/grant changes; HTML opt-in,
accepted and editor updates, changed dependencies, unrelated changes, output tampering,
renderer failure/retry, process termination after replacement and both restore paths.
Schema exports were regenerated; Ruff and strict mypy passed (102 source files).
Full-suite, browser and installed-release evidence is recorded separately below when run.
These tests use deterministic synthetic agent answers, not a real model or private workspace.

The first full container run found a renderer reproducibility failure (361 tests
passed, one checksum check failed). Markdown's bundled dependency introduced
build-path comments. The application build now removes those comments through
esbuild's whitespace minification, and carries Marked's license. A follow-up
authorization regression suite passed **18 tests**, including a related page changed
to local-only before pending, review or a cached reading retry. Browser checks passed;
the full post-fix results are recorded in the final verification entry.

## Paper notebooks — six regression fixes (2026-10-10)

The targeted synthetic container suite passed **57 tests** covering MCP, capture/apply,
context, page writing and six added regression scenarios. The new checks reproduce
large-source citation writing, same-name captures and explicit revisions, project body
and concept context, project-scoped revisions, filtering before ranking, and pending
grant enforcement. No private workspace or real model was used. Full release and HTML
checks will follow the notebook and rendering milestones; this is not release readiness.

## One-call agent tools, owner terminal, removed compatibility flags (2026-10-10; software checks passed; no real agent exercised)

The owner asked whether packets were still needed when using skills, then asked to
simplify accordingly, fix stale packets, close the shell gap and remove the
compatibility flags, all at once (sole user). The owner chose sandbox guidance plus a
terminal check for the shell gap, and moving the HTML explanation/feedback flows to
MCP. Signed approvals were considered and rejected: a same-user agent outside a
sandbox could replace the key or write files directly.

- **No agent-facing packets.** MCP read tools (`search`, `evidence`, `page`, `context`,
  `view`, `feedback`, `capture`, `pending`, `proposal_show`) and one-call
  `propose_reading`, `propose_page`, `propose_changes`, `propose_explanation`. Each
  `propose_*` seals inputs with an `ExportReceipt` and validates the answer in the same
  call (`reading.workflow.submit`, `quill.submit`, `draft.submit`,
  `writing.submit_explanation`). Reads leave receipts in `receipts/agent/`. Contracts
  travel in tool descriptions. `cairn finch`, `cairn write`, `cairn draft` and
  `--packets-dir` are removed; `cairn view explanation` renders kept explanations.
- **Retries and attempts.** A retried reading returns its first receipt (submission
  record, validated on restore). Different page or draft answers seal a new packet
  (`QuillPacket.attempt`, omitted when unset so stored packet identities hold; draft job
  IDs salted by the answer) instead of conflicting. Page revisions require the
  `base_hash` the agent read.
- **Stale packets.** Guidance is no longer rechecked when a staged proposal is approved,
  so contract edits never strand proposals (`test_contract_changes_never_strand_staged_proposals`).
- **Shell gap.** Owner commands (approve, accept, apply, policy changes, schema apply,
  update enable/disable) require the action typed at `/dev/tty`; `accept --yes` is gone.
  `CAIRN_SYNTHETIC_OWNER=1` works only for synthetic workspaces. `--print-config` prints
  Claude Code sandbox and deny settings and Codex sandbox guidance, taken from the
  agents' documentation (Claude Code runs MCP servers outside its shell sandbox; Codex
  documents no per-path deny and does not say where MCP servers run).
- **Flags.** `init --no-quill/--no-finch` removed; `docs/updates.md` explains running the
  new updater once from a checkout after release.

| Area | Tests |
|---|---|
| Tool surface, protocol errors, contract in descriptions | `test_protocol_and_tool_surface_exclude_owner_operations` |
| Read-then-propose for reading, page (stale base refused), changes (reviewed verification refused), explanation; pending; review; backup validation | `test_read_then_propose_reading_page_changes_and_explanation` |
| Feedback revision via tools | `test_feedback_revision_through_tools` |
| Grants on reads and proposals; local-only withheld | `test_grants_bound_every_tool` |
| Forged fields and quotes rejected without side effects | `test_untrusted_answers_are_rejected_without_side_effects` |
| Capture root and labels | `test_file_capture_needs_owner_root_and_labels` |
| Launch validation, sandbox settings | `test_launch_validation_and_print_config` |
| Submit idempotency and new attempts | `test_submit_seals_and_stages_one_reading`, `test_submit_seals_and_stages_in_one_step`, `test_submit_maps_citations_and_refuses_stale_or_foreign_evidence`, `test_submit_explanation_keeps_it_for_owner_rendering` |
| Owner terminal: refused without a terminal, wrong word declined, typed word accepted, override ignored for real knowledge bases | `test_cli_accept_requires_confirmation`, `test_owner_terminal_is_required_for_real_knowledge_bases`, `test_cli_enable_registers_and_disable_unregisters` |
| Removed commands and flags | `test_plain_ingest_is_blocked_and_packet_commands_are_gone`, `test_setup_and_restore_never_install_or_edit_skills` |

`bash scripts/check.sh` passed in the development container: **341 tests**, Ruff,
strict mypy (99 files), all 13 isolation checks in both images, worker probe and
extraction/HTML round trips, gold set 129/129, and the real-engine lifecycle.

Manual run from this session's Claude Code shell (no controlling terminal) on a
synthetic scratch workspace: `cairn policy set-grant` and `cairn accept` were refused
as owner commands; `accept --yes` is a usage error; the installed `cairn mcp` captured
a file, staged a reading with `propose_reading` and listed it in `pending`.

Not established: no real agent or model was connected; the printed sandbox settings
were not applied to a real Claude Code or Codex configuration; the owner terminal check
was exercised with a pseudo-terminal and an agent shell, not an adversarial agent.
`scripts/release_trial.py` was rewritten (MCP reading section) but not executed.
The section below describes the earlier begin/finish packet tools, now superseded.

## Host-agent model: MCP server, draft packets, no managed skills (2026-10-10; superseded by the section above)

The owner always uses Cairn from inside an agent (Claude Code, Codex, Cursor) and did
not want Cairn launching Claude Code. The owner chose: the agent calls Cairn through a
hand-written local stdio MCP server; packets carry Cairn-owned contracts instead of
vendored Finch/Quill; Cairn stops installing, editing or updating skills; the docker
client route and the offline library reader are retired; ingest becomes a begin/finish
draft packet. No version bump, release, tag or push was made, and Finch and Quill were
not touched.

- **Retired reader** (`a0dd3d4`). Library reader, device runner, subscription
  verifiers, their CLI commands, schemas and tests are removed. Feed entries, catalog
  items and view bundles keep their fields so stored data still parses; legacy reader
  receipts are ignored by backup validation; views carrying reader state must be
  regenerated (`load_view` raises a conflict).
- **Contracts, not skills** (`48d5eb3`). `reading/contract.md` and
  `presentation/contract.md` are the packet guidance, hash-bound as before. Vendored
  Finch (snapshot and installer) and Quill are deleted; `finch install|status`,
  `quill install`, init/restore skill setup and updater skill refresh are removed.
  `init` still accepts hidden `--no-quill/--no-finch` because a 0.1.x updater
  smoke-tests a new runtime with them.
- **Draft packets** (`1d79beb`). `cairn draft begin|finish` (`proposals/draft.py`)
  seals a cloud-route ingest job, records an `ExportReceipt`, and stages the agent's
  `Result` through `stage_result`/`validate`; drafts cannot adopt decisions or mark
  evidence reviewed. `ClientPacketProvider`, `cairn client run` and the worker's
  `fake-v1` branch are removed; `check.sh`'s lifecycle step now uses an extraction
  request.
- **MCP server** (`d3bcddd`). `cairn mcp` (`src/cairn/mcp.py`): JSON-RPC 2.0 over
  stdio, no new dependency. Launch arguments fix workspace, scope, provider,
  destination and packets directory. Read tools are authorized against the cloud
  grant (`query`/`context`) and withhold local-only records. File capture only under
  an owner-chosen root with owner-chosen labels. `--print-config` prints `claude mcp
  add`/`codex mcp add` commands (syntax checked against the installed CLIs' `--help`),
  a Cursor entry and deny rules; Cairn writes no agent configuration.

| Area | Tests |
|---|---|
| Draft round trip, idempotent retry, conflicting retry, inbox, backup validation, owner approve/apply | `test_draft_roundtrip_is_idempotent_reviewable_and_owner_applied` |
| Missing/partial grant, local-only input | `test_draft_begin_requires_a_grant_and_cloud_eligible_inputs` |
| Revoked grant blocks finish | `test_revoked_grant_blocks_finish` |
| Forged provider/hash, owner decision, reviewed verification, active decision, source record | `test_untrusted_draft_cannot_claim_owner_authority` |
| Malformed draft, plain `ingest` blocked, `client run` gone | `test_malformed_draft_is_rejected_without_side_effects`, `test_cli_draft_begin_finish_and_blocked_plain_ingest` |
| Protocol (initialize, notifications, ping, -32700/-32600/-32601/-32602), tool surface excludes owner operations | `test_protocol_and_tool_surface_exclude_owner_operations` |
| Reading, writing and drafting over stdio; pending; proposal review; search; evidence | `test_reading_writing_and_drafting_round_trips` |
| Grants bound every tool; local-only withheld | `test_grants_bound_every_tool` |
| Untrusted responses rejected | `test_untrusted_responses_are_rejected_without_side_effects` |
| Capture root and labels | `test_file_capture_needs_owner_root_and_labels` |
| Launch validation, print-config | `test_launch_validation_and_print_config` |
| Setup/restore never touch skills; retired commands gone | `test_setup_and_restore_never_install_or_edit_skills` |
| Packets carry the contract | `test_finch.py` CLI round trip, `test_quill_write.py` |

`bash scripts/check.sh` passed in the development container: **333 tests**, Ruff,
strict mypy (101 files), all 13 isolation checks in both images, the worker probe,
extraction (text, bibliography, receipt, finance, life) and HTML round trips, gold set
129/129, and the real-engine create/start/remove lifecycle using an extraction request.

A manual smoke run on a synthetic scratch workspace drove the installed `cairn mcp`
CLI with a JSON-RPC script: grant, file capture under the capture root,
`reading_begin`, a hand-written `FinchResponse` to `reading_finish` (proposal staged),
a forged `approved` field rejected, `pending` listing the proposal, then owner `cairn
inbox` and `cairn accept --yes` applying it. The synthetic `HOME` stayed empty.

Not established: no real agent (Claude Code, Codex, Cursor) or model was connected;
all agent responses are hand-written or produced by the deterministic fake. The MCP
server was tested with a synthetic client against the protocol subset Cairn
implements, not against every host's behavior. `scripts/release_check.sh` and
`scripts/release_trial.py` were not rerun; the release trial was edited (Finch install
lifecycle removed, contract tamper check added) without being executed.

Superseded evidence: `docs/evidence/finch-install-release-trial.json`,
`finch-release-trial.json` (Finch snapshot and installer) and the library reader,
device and subscription-verification entries in the sections below describe retired
components. They are kept as history.

## Automatic updates and managed skills (2026-10-10; software checks passed, live update pending)

The owner asked that a knowledge base update automatically whenever the workbench is
updated, like a self-updating terminal application, and that knowledge-base skills
follow their upstream. Previously a private workspace was bound to one release with no
upgrade path. The owner first chose SSH-signed release tags, then asked to follow Finch
and Quill instead: a release is the `stable` branch with a higher version number, and no
signing setup is required. Schema migrations run automatically with backups.

- **Rebind.** `storage/upgrade.py` rebinds a workspace under a standing
  `UpdateAuthorization` stored in that workspace. The new runtime verifies itself, then
  checks that the release commit is on the branch named in that authorization and that
  both version declarations (`pyproject.toml`, `src/cairn/__init__.py`) agree on the
  expected version. It also checks that the manifest's revision and source hash match
  that tree. It refuses downgrades,
  runs a fresh worker probe, and backs up before replacing `workspace.json`. Upgrade
  approvals chain back to an acknowledged `init`/`restore` and are checked on every open
  and in backups.
- **Updater.** It adopts the `stable` head only when its version increases and it
  fast-forwards the installed commit. `cairn update setup|run|status|enable|disable|schedule`, a launchd/cron
  job, a background check when `cairn` starts, a one-time notice, and serving a
  workspace from the runtime it is still bound to. A failed build, verification or
  smoke run keeps the previous runtime.
- **Managed Quill.** The knowledge-base copy is generated from a pristine clone of
  Quill's `stable` branch plus the Cairn handoff. It is refreshed only while it matches
  its marker, so owner edits and unmanaged copies are kept. Finch's own updater is
  invoked when present.

Tests (synthetic only; local repositories, synthetic `CAIRN_HOME` and `FINCH_HOME`):

| Area | Tests |
|---|---|
| Channel rebind, chain, backup, restore of upgraded archive | `test_channel_release_rebinds_with_backup_chain_and_history` |
| Missing/revoked authorization | `test_rebind_requires_active_owner_authorization` |
| Wrong version, disagreeing declarations, off-channel commit | `test_rebind_requires_a_channel_commit_declaring_the_release` |
| Manifest/source binding, no downgrade | `test_rebind_binds_manifest_to_channel_source_and_never_downgrades` |
| Probe failure before backup; interruption before commit | `test_failed_worker_probe_blocks_before_backup`, `test_interrupted_rebind_leaves_previous_binding_valid` |
| Forged authorization reference detected on open | `test_upgrade_chain_is_checked_on_every_open` |
| Automatic legacy migration with second backup | `test_upgrade_migrates_legacy_format_automatically_with_backup` |
| Version-bump selection, rewritten history refused, cycle ordering, failure keeps runtime, busy, GC | `tests/test_updater.py` |
| Bound-runtime re-exec, notice, background check, schedules, shim | `tests/test_updater.py` |
| Managed Quill install, refresh, local edits, offline fallback | `tests/test_managed_skills.py` |

After switching to version-based releases, `bash scripts/check.sh` passed: **365
tests**, Ruff, strict mypy, all 13 isolation checks, worker and installed round trips,
gold set 129/129, and the real-engine lifecycle. The temporary `openssh-client`
addition to the development image was removed with the signing code; the worker image
was never changed.

Not executed: build, install and verification steps are simulated by a fake runner.
No live `cairn update setup`/`run` was run on a real macOS host, so the native host
build (`uv run ... build_release.py`, local `docker build`, offline install and the new
runtime's `check-runtime`) is unverified. The repository has no `stable` branch yet. `scripts/release_check.sh` was not rerun. Live launchd/cron
registration, Quill's upstream over the network, and the owner's first activation
remain owner deployment checks.

## Review fixes: macOS history, recovery, reader evidence, renderer (2026-10-10)

A code review found five defects; each fix has a regression test.

- **macOS local history.** `git init --bare` on default APFS writes `ignorecase` and
  `precomposeunicode`. The strict history profile rejected them, so after the first apply
  history stayed pending and backup, migration and library snapshots failed. Exactly these
  two keys with value `true` are now allowed. Test:
  `test_history_accepts_case_insensitive_filesystem_profile`. The keys were observed with
  Apple git on APFS. The test injects them into Linux containers; it does not run on a
  native APFS volume.
- **Migration recovery with library journals.** `schema recover` parsed library journals
  as apply transactions and crashed. Test:
  `test_migration_recovery_ignores_committed_library_journal`.
- **Edit between validation and journaling.** Apply journaled the validated base hash, not
  the bytes it read. A lock-ignoring editor could leave a prepared journal that could never
  be recovered. Observed bytes are now checked before any journal write. Test:
  `test_edit_after_validation_is_rejected_before_journaling`.
- **Owner-device reader evidence.** Device page text became evidence after binding checks
  alone. The owner now runs deterministic extraction (the isolated worker for PDFs) and
  requires each page segment to match it. Understated page counts are rejected. Tests:
  `test_device_text_must_match_owner_extraction`, `test_device_cannot_understate_page_count`.
  The earlier synthetic fixture was a blank PDF paired with invented device text, so it
  had passed only because of this defect.
- **Renderer UTF-8 decoding.** Per-chunk decoding corrupted multi-byte characters past
  64 KiB. Test: `test_large_non_ascii_view_is_not_corrupted`. It fails against the
  previous bundle. The bundle was rebuilt twice in the offline renderer image and was
  byte-identical; provenance was regenerated.

Executed on revision `0ef37e3`:

- `bash scripts/check.sh`: **290 passed**, ruff and strict mypy clean, both 13-check
  isolation probes passed, installed worker trials passed, gold set 129/129.
- `bash scripts/release_check.sh`: offline installation of 15 distributions passed.
  Release manifest SHA256
  `f4f9209d4028e58e4ad8a93079c237580cb4fea9fdefad80375d99534410665b`. Installed worker
  image `sha256:0849d7f9c00250eab05792524ab6f1c5f866094f00bf3361e3d2c0cd06819961`
  passed all 13 checks.
- `bash scripts/check_html.sh`: passed. Renderer suite 0 failed; the 2 skips are the
  known upstream cases. The repeat portable ZIP matched; `cairn-html.zip` SHA256
  `6283611fde9177cc397856746d3a10726557fb5871308295048ba018b25e26b0`. Browser
  screenshots were regenerated but not manually re-inspected in this pass.

**Not addressed here:** macOS `F_FULLFSYNC` durability, the streaming-restore digest race,
and lower-severity review findings. No private workspace, live device or deployment was
used. (The first two were fixed in the follow-up below.)

### Medium-severity follow-up (2026-10-10)

- **Durability flush.** All flushes now use `F_FULLFSYNC` where the platform provides it,
  falling back to `fsync` where a filesystem rejects it. Test:
  `test_sync_uses_full_flush_where_available`. It simulates the macOS call because tests
  run on Linux. Power-loss ordering was not tested physically.
- **Proposal checks.** Structured amounts must match preserved observations in every
  domain. Empty quotes are rejected. Model-supplied `reviewed`/`superseded` verification
  now needs a `verification_change` acknowledgement (documented in `docs/review.md`).
  Tests: `test_structured_amounts_outside_finance_must_be_observed`,
  `test_empty_quote_cannot_support_a_citation`,
  `test_model_supplied_verification_requires_acknowledgement`.
- **Source lineage.** An unversioned revert (A, then B, then A again) records a new
  lineage head; reordered project IDs no longer duplicate a source. Tests:
  `test_unversioned_revert_records_a_new_lineage_head`,
  `test_project_order_does_not_duplicate_sources`.
- **Bibliography import.** Impossible dates name the item. Digit-string date parts are
  accepted. Version conflicts are checked before anything is captured. Year-only dates
  still stay unknown as `source_date` by design; the raw item keeps them. Tests:
  `test_bibliography_invalid_date_names_item_and_writes_nothing`,
  `test_bibliography_version_conflict_imports_nothing`.
- **Export guard.** Feed and JSON catalog exports use the guarded owner output writer.
  Test: `test_catalog_json_export_refuses_symlinked_workspace_target`.
- **Weekly update.** Reading errors are handled per job and recorded as digest issues,
  so a failing reading no longer stalls later updates. Test:
  `test_failing_reading_does_not_hold_update_in_read_phase`.
- **Streaming restore.** The archive is copied once into an owner-only temporary file
  while it is hashed, and restore reads only that copy. Test:
  `test_streaming_restore_uses_the_digest_checked_bytes`. Restore now needs free space
  for one extra copy of the archive next to the destination.

Executed on revision `ee6e3b7`:

- `bash scripts/check.sh`: **301 passed**, ruff and strict mypy clean, isolation
  probes passed, gold set 129/129.
- `bash scripts/release_check.sh`: passed. Release manifest SHA256
  `7ad552171569db52c5f8ea73b914a1858ba8aad96bf09e3891affbd91ddb1bf1`. Installed worker
  image `sha256:def2f5116f2544891c4c5bde5e6c3d5ba5d0f6543650d2ff687a16c99815bf3b`
  passed all 13 checks.
- `check_html.sh` was not rerun: no renderer or presentation resources changed.

## Simplified writing: Quill writer, owner notes, one-step accept (2026-10-10; software checks passed)

A review found that writing took too many owner steps. The reviewer also reported
no quick capture, inbox or batch review, and that notes were unsearchable until
captured. This branch keeps the invariants and shortens the path:

- **Notes.** `cairn note` (stdin with `-`) writes a new inbox file. Notes in
  `vault/notes` and `vault/inbox` are searchable at once from `cairn search`. Labels
  come from front matter or the folder; unlabelled notes default to shared/restricted.
  Notes never reach views, context or model packets.
- **Capture and triage.** `cairn capture -` captures stdin text as a source.
  `cairn inbox` lists notes, pending proposals and unanswered packets.
- **Writing.** `cairn write begin` tells Quill what to write and where, with keyed
  scoped evidence. `cairn write finish` checks the `QuillResponse`, formats the record
  itself and stages a validated proposal. It replaces the explanation and
  feedback-revision packet commands.
- **Acceptance.** `cairn accept` validates, approves and applies proposals after one
  confirmation. It is batchable, and each proposal keeps its own sealed approval and
  journaled transaction. Batch selection skips stale, sensitive, decision and
  adoption proposals.

Sources and notes stay immutable to models, and acceptance stays an owner command.

`check.sh` passed **306 tests**, Ruff and strict mypy across **105 source files**.
That includes 9 acceptance, 5 note and 8 Quill writing tests, with the 2 retired
feedback-revision tests removed. Both processing profiles passed all **13 isolation
checks**. The installed worker, extraction and HTML trials, **129 gold checks** and
the real Docker lifecycle check also passed.

The run used a copy of `scripts/check.sh` whose only change was branch-unique image
tags. The unmodified script built correctly, then failed with "No such image" when
another checkout's concurrent build retagged `cairn-dev:local` mid-run. That was an
environment collision, not a code result.

A manual synthetic CLI run in the development container covered:

1. stdin note, then search hit;
2. `write begin`, after which the inbox shows a Quill packet;
3. a hand-written response, then `write finish`, after which the inbox shows the
   Quill proposal;
4. `accept --all` refused without `--yes`, then applied with it;
5. search finds the new page, and source/note hashes are unchanged.

A copy of `scripts/release_check.sh`, again changed only to use branch-unique image
tags, passed the offline installed release trial at revision
`8a1cdbb3fa4c250dcac6a0c6d6ab635b48351bf5`. It covered **15 distributions** and
**940 verified files**. The installed Finch, HTML, library, markdown-review and
capture/approval/apply/query/restore workflows passed, along with all **13 checks**
on the released worker. Modified packages, resources and renderers, editable
installs and unreviewed `.pth` files were rejected. Manifest SHA-256:
`0492cbad247e86884e264dd8d13b3ecf4d4eaa3e407bd2f3cda18391453c23bd`.

Limits:

- The Quill responses were hand-written synthetic fixtures. They prove the mechanical
  handoff, citation and authority checks, not Quill's writing quality.
- Setup now installs Quill for the knowledge base unless `quill/SKILL.md` exists in
  a machine-wide skill directory. Five setup tests cover install, machine-wide use
  (the copy is left untouched), location override and opt-out, blocked installs, and
  restore. After this change `check.sh` passed **311 tests** and every profile, gold
  and lifecycle check. The tests point the machine-wide lookup at a synthetic
  directory; no real home directory was inspected.
- The CLI `capture` command does not expose processing labels. The cloud-eligible
  source in the manual run was captured through the Python API.
- Editing an existing note still marks pending proposals stale, because notes are
  protected inputs.

## Finch installed by its own updater (2026-10-10; software checks passed, upstream release pending)

The owner asked that a first private setup install Finch for whichever agent uses the
knowledge base, keep it updated, and replace Cairn's own reading guidance. Finch's
upstream installer already links the skill into detected agents and schedules a daily
fast-forward update that skips a clone with local edits. The previous Cairn installer
appended a hook to `SKILL.md`, which would have dirtied that clone and stopped its
updates. Finch 0.3.0 therefore ships the Cairn handoff as `references/cairn.md`, and
Cairn no longer edits an installed Finch. `cairn init` for a private workspace runs the
checksummed packaged installer only when no Finch is available; failure leaves the
workspace usable and reports `pending`. The offline reader prompt keeps only the
worker's evidence contract (now `finch-paper-reader-v2`), and the paper review checklist
uses Finch's terms.

In the development container, **287 tests**, Ruff and strict mypy (**101 source files**)
passed. The prompt and checklist commit was also tested by itself (**284 tests**). Five
installer tests use a synthetic home and a local synthetic git remote: the packaged
installer links Finch into the detected Claude Code and shared agent directories as a
clean clone. An existing Finch is preserved byte-for-byte without running the
installer. A tampered installer is rejected. A failed clone reports pending with no
links. Synthetic `init` installs only with `--finch`. Scheduled updates were disabled in
tests, and no real home, launchd or cron was touched.

The fresh offline installed release trial passed at revision
`b43ae00b895b42ecb03ecb8f13d5f85342106084`: **15 distributions**, **936 verified files**,
offline `finch install` reported pending without links, an existing synthetic Finch was
preserved, and the existing Finch packet, HTML, library and restore workflows passed. See
the [installed trial](evidence/finch-install-release-trial.json). Manifest SHA-256:
`b7ec109f5f48a3384f483292864b40cf478babb0d9905507d680262748559402`. The 13 isolation
checks and the released-worker probe (`scripts/check.sh`, `scripts/release_check.sh`)
were not rerun for this change.

Pending: the bundled snapshot is upstream commit `4de3695` on an unreleased Finch branch.
Release Finch 0.3.0 to `stable`, then re-record provenance. A real install against a
live agent home, the scheduled update, and Claude Code plugin installs (not detected)
remain owner deployment checks.

## Automatic Finch reading (2026-10-10; software checks passed, activation pending)

The owner requested automatic Finch use for paper reading and automatic Cairn workflow
handoffs on each Finch invocation. The package includes a checksummed MIT Finch 0.2.0
snapshot. Library jobs bind the guidance and use it in the offline worker. The host-skill
installer handles missing Finch, preserves existing guidance, and attaches the lifecycle.
Owner-prepared agent packets and returned responses automatically capture conversations,
stage concept-note proposals, and validate them. Approval/apply and read status remain
owner operations; sources and human notes are immutable to these proposals.

`bash scripts/check.sh` passed **284 tests**, Ruff and strict mypy across **100 source
files**. Both processing profiles passed all **13 isolation checks**, installed worker
packet/extraction/HTML/domain trials, **129 gold checks**, and real Docker lifecycle and
hostile-child cleanup checks. All tests used synthetic inputs; no private workspace or
home directory was mounted. The first full run found an outdated PDF trial fixture
without the new guidance hash; it was corrected and the complete check rerun passed.

The 24 Finch tests cover packaged guidance use, installation/retry/preservation and
conflicting hooks/symlinks; cloud grants and full-request labels; immutable raw response
capture and proposal-only handoff; typed claims, citations and rejected authority fields;
changed source/human notes/policy, revocation, interrupted and concurrent retries;
selected project inheritance, denied context, durable bindings and CLI round trips.
Schemas are regenerated from the typed models. Unrelated protected workspace paths
remain in owner-only guards rather than exported packets.

The fresh offline installed release trial passed at revision
`86dd9696df8fcf0d757e56ec477c167c13166765`: **15 distributions**, **934 verified files**,
Finch installation/capture/proposal/validation/retry/restore, existing installed CLI
workflows, and all **13 checks** on the exact released worker. Modified Finch resources,
packages/renderer, editable installs, unreviewed `.pth` files and activation without
a live engine were rejected. The first installed trial correctly rejected an older HTML
view after the trial added an export grant; the corrected trial expects this rejection
and regenerates the view before backup/restore. See the
[installed trial](evidence/finch-release-trial.json) and
[released worker profile](evidence/finch-worker-profile.json). Manifest SHA-256:
`caed04dfc439ba50ef2eac71665528db684927bf2483ca769213eeabe901b1b0`.

The installed trial targets Linux-aarch64, not a native macOS owner runtime. Live
reading quality, private runtime activation and host skill/launcher configuration remain
separate owner deployment gates. This instruction-based lifecycle does not monitor
unconfigured chats. Missing packets/launchers report `cairn_handoff_pending`; no real
discussion has been ingested or accepted by these development tests.

## Journal library extension (2026-09-30, software validated; deployment pending)

Catalog hardening preserves bibliographic observations as source snapshots, resolves
pre-existing journal identities in place, supports folder aliases/publication series,
and treats an empty previously populated route as uncertain. The catalog/discovery
boundary tests use synthetic journals and PDFs. No private library was used by tests.

The final `scripts/check.sh` run at code revision
`653aba4f1011d0c058b7014be6266908c154c50b` passed **227 tests**, Ruff and strict mypy
across 77 source files. Both development and installed processing profiles passed all
13 isolation checks. Installed extraction and packet trials, 129 gold checks, and real
Docker create/start/remove plus hostile-child cleanup passed. The new PDF page trial
uses actual PDFium rendering with synthetic model responses; it does not test semantic
reading quality.

The same revision passed the offline installed release trial: 15 distributions,
899 verified files, library scan/mark/feed/streaming restore, schema migration with backup,
and capture/approval/apply/query/restore. Modified packages, unreviewed `.pth` files,
editable installations, and activation without a live engine were rejected. See the
[installed trial](evidence/library-release-trial.json) and
[exact released worker profile](evidence/library-worker-profile.json). Release manifest
SHA-256: `8feceae826e915d29fa2b31598de44b48681e999003018b63a383570f5571a0f`.

A separate physical **260MiB of source payload** streaming trial restored all 65
synthetic blobs and checked the archive digest; [the report](evidence/library-backup-trial.json)
records 272,630,931 total payload bytes. This exceeds the legacy total-size limit without
claiming a one-terabyte capacity trial.

Implemented interfaces cover catalog/filter/export, publication backfill, explicit
owner-device enrollment, resumable/cancellable reading proposals, bounded subscription
verification, saved Markdown/HTML/Atom digests, delivery acknowledgements, and streaming
backup/restore. Pending or failed verification is visible; selected pending checks and
failed checks block owner acceptance. Local older papers are inventoried and preserved;
weekly baseline scans do not read the archive. The reader is Qwen/llama.cpp code, not a
claim that a live Qwen model has run. The Monday 09:00 America/Chicago heartbeat has been
prepared in a paused state. No private library or private workspace was used for these
tests, and no private runtime was upgraded.

Deployment remains pending: the workstation SSH connection still times out; its GPU,
WSL2/container configuration, pinned Qwen build, memory use and reading quality remain
unverified. The release trial is Linux-aarch64, not a native macOS owner installation.
A compatible pinned Mac installation with reviewed owner SSH/client transport, live
subscription adapter capability checks, and a small owner-reviewed pilot are required
before full cataloging and weekly activation. Subscription login status and synthetic
protocol tests do not establish live tool disabling, billing behavior, or output quality.
See [deployment gates](library-deployment.md). No skipped or synthetic check is counted
as passing a live deployment gate.

M0–M3 reference acceptance is complete. A checked item requires an executed test or
inspected artifact, not just code presence. Entries below retain the earlier M0–M3
chronological evidence and scope statements; the authorized journal extension and its
remaining deployment gates are described above.

| Stage | Status | Evidence and limits |
| --- | --- | --- |
| M0 | Passed reference acceptance | 24 tests, lint, strict typing, 13 isolation checks |
| M1 | Passed reference acceptance | 48 tests, installed worker protocols, both isolation profiles |
| M2 | Passed narrow manual continuity review | Owner-supplied real-client design uses the decision and avoids the failure; owner verdict remains unclear; receipt normalized separately |
| M3 | Passed reference acceptance | 175 tests, 129 gold checks, full requirements matrix, final installed release trial; actual activation separate |

The brief's hard gates are mapped to implementation and named evidence in
[the requirements matrix](requirements.md).

M0 evidence collected by `bash scripts/check.sh` in the reference Linux container on
the macOS Docker host: **24 tests passed**, Ruff passed, strict mypy passed (16 files),
and **13 process-level isolation checks passed**.

- `test_foundations.py`: record round trips, deterministic sets, traversal, symlink and
  hard-link access, special files, case/Unicode collisions, root overlap, unsafe YAML,
  scope widening, confidentiality/processing inheritance, and cloud denial.
- `test_provider.py`: deterministic extractive fake; injected source remains data;
  job/result serialization; pinned, no-mount worker command; subprocess wire protocol.
- `test_schema_exports.py`: generated schema parity.
- `scripts/isolation_probe.py`: all 13 checks passed with a real unmounted synthetic
  host canary. Canonical/policy/approval writes, outbound TCP, DNS, and hostile child
  operations were denied. No Docker socket, host home, or forwarded credentials existed.

These checks cover a defined threat corpus. They do not prove semantic truth, universal
container security, or private-runtime readiness.

M1 core evidence: **44 cumulative tests passed**, Ruff passed, strict mypy passed
(29 source files), using the isolated development profile with public source mounted.
The later installed M1 acceptance run below supersedes this initial core run.

| Requirement | Current named evidence |
| --- | --- |
| Preserve source/human bytes; no duplicate import churn | `test_capture_extract_apply_preserve_and_deduplicate` |
| Revised-source lineage and version conflicts | `test_revisions_and_declared_version_conflicts` |
| Retryable extraction failures preserve original capture | `test_failed_extraction_preserves_capture` |
| Assistant recommendations do not authorize adoption | `test_conversation_roles_remain_data` |
| Fabricated quote and denied-scope rejection | `test_quotes_scope_and_source_hash_are_validated` |
| Exact approval binding and intervening owner edits | `test_approval_tamper_and_owner_edits_are_rejected` |
| Real termination halfway through a two-file bundle | `test_real_process_crash_recovery` (six boundaries) |
| Recovery preserves unexpected owner bytes | `test_recovery_preserves_unexpected_owner_bytes` |
| Scoped titles, counts/ranking, and backlinks | `test_scoped_search_no_counts_titles_or_ranking_leaks`, `test_restricted_backlinks_are_omitted` |
| Two-character Chinese and bilingual aliases; cache deletion | `test_bilingual_short_query_and_cache_rebuild` |
| Text and evidence-blob restore; hostile archives | `test_restore_text_blobs_and_evidence`, `test_archive_traversal_and_hash_tamper_rejected` |
| CLI capture through review/apply/search | `test_cli_full_owner_workflow` |
| Source summary plus bounded project update | `test_two_file_update_is_reviewable` |

Installed M1 evidence from `bash scripts/check.sh`: **48 tests passed**, Ruff passed,
strict mypy passed (30 source files), both development and installed worker profiles
passed all 13 isolation probes, and installed extraction/client-packet round trips passed.
The staged owner editor, PDF page/coverage behavior, and backup/restore CLI are present.
`test_stale_wiki_update_cannot_overwrite_owner_edit` and
`test_index_failure_leaves_durable_apply_and_retries` cover the final concurrency and
post-commit maintenance boundaries. Private-runtime readiness remains unproven until M3.

The user selected a **manual agent session** for M2's separate-agent continuity check.
Prepare its synthetic pack and verification procedure; do not spawn a subagent or claim
that deterministic tests satisfy that semantic gate.

M2 installed reference evidence from `bash scripts/check.sh`: **64 cumulative tests
passed**, Ruff passed, strict mypy passed (38 files), and both processing profiles passed
all 13 isolation probes. Installed packet, text-extraction, bibliography-extraction, and
receipt-extraction trials passed. The synthetic manual-handoff generator also completed
inside the installed development image. The new workflow covers:

| Requirement | Named evidence |
| --- | --- |
| Stable library IDs/citation keys; unknown dates; item-level deduplication | `test_bibliography_ids_dates_coverage_and_item_dedup` |
| Ambiguous or malformed import produces no capture | `test_bibliography_invalid_export_writes_nothing` (three cases) |
| Receipt approval preserves draft status; explicit adoption needs exact owner apply | `test_session_receipt_requires_explicit_adoption_and_context_preserves_evidence` |
| Roles preserved; fabricated citations and claimed authority rejected | `test_receipt_roles_fabricated_reference_and_claimed_authority` |
| No denied-domain titles/IDs/content or unsupported derived conclusion | `test_context_scope_filters_titles_ids_and_denied_evidence` |
| Bounded packs omit whole items, retaining evidence locators | `test_context_budget_omits_whole_items_and_keeps_locators` |
| Current, stale, and unverified repository states | `test_repository_binding_flags_changed_or_unverifiable_context` |
| Review diff matches exact candidate bytes | `test_review_diff_tamper_is_rejected` |
| CLI scoped context and explicit save | `test_cli_research_context_and_save` |

`scripts/prepare_continuity.py` executed the synthetic capture/proposal/approval/apply/
adoption/context sequence and generated `examples/continuity/context.json`, source evidence,
and a verification manifest. The second-agent semantic result is explicitly **not evaluated**.
Follow `docs/research-continuity.md` for the owner-selected manual test. No subagent was spawned.

M3 domain implementation adds exact structured financial observations and Decimal
calculations, dated financial categories, life dossier/history imports, and the owner
`evidence` command. The new tests cover decimal fidelity; distinct owner/account/date/
unit/currency; float rejection; fabricated amounts, metadata, prose and snapshot bodies;
preserved life history; denied-evidence summary leakage; and decision supersession.
Installed M3 domain-increment evidence from `bash scripts/check.sh`: **86 tests passed**,
Ruff passed, strict mypy passed (42 source files), both profiles passed 13 isolation probes
each, and six installed-worker trials passed (packet, text, bibliography, receipt,
financial snapshot, and life dossier). The manual-handoff generator also completed.

- `tests/test_domains.py` contains 15 executed cases, including six hostile snapshot
  mutations and five distinct prohibited arithmetic mixtures.
- `test_denied_evidence_withholds_derived_text_and_ranking` verifies that stripped citations
  cannot leave a restricted conclusion in search or its cache.
- `test_superseded_adopted_decision_is_not_presented_as_current` preserves the original
  decision and presents only its adopted successor as current.
- `test_missing_conflict_reference_is_rejected` and `test_cli_evidence_exact_locator_and_coverage`
  cover conflict-reference integrity and explicit source inspection.

Next work: complete release packaging, schema migration support,
the synthetic evaluation report, and a full requirement audit. Independent work may
continue while the external manual gate remains named and pending. Private activation
remains separate and is currently explicitly denied.

M3 restore/worker-hardening evidence from `bash scripts/check.sh`: **110 tests passed**,
Ruff passed, strict mypy passed (43 files), both profiles passed 13 isolation probes each,
and all six installed-worker trials passed. A real-engine create/start packet round trip
and forced removal of a running worker plus child also passed. No contributor Python
received a Docker socket or host/private mount.

- `tests/test_restore_hardening.py`: 12 executed cases cover complete namespace preflight,
  special files, missing manifest, invalid records, expected archive digest, copy failure,
  executable Git configuration, a ZIP above the old 32 MiB ceiling, backup of a real
  process-terminated two-file apply, and refusal to open incomplete restore staging.
- `tests/test_worker_lifecycle.py`: 11 cases use real subprocess pipes with a synthetic
  Docker control process to verify stdout/stderr limits, timeouts, closed pipes, packet
  success/failure, actual exit-state checks, exact owned-container cleanup, cleanup failure,
  remote endpoint denial, and image-volume rejection before input transmission.

The synthetic engine verifies launcher behavior, while the separate host script verifies
the actual Docker lifecycle and worker isolation. Neither is claimed to prove a complete
private installation or universal container security.

M3 policy-audit evidence from `bash scripts/check.sh`: **127 tests passed**, Ruff passed,
strict mypy passed (45 files), both profiles passed 13 isolation probes each, all six
installed-worker trials passed, and the real Docker create/start/removal trials passed.

`tests/test_policy_audit.py` executes 12 cases: all five processing operations; missing,
expired, wrong-provider/destination/scope/operation grants; question and metadata labels;
unknown labels; public evidence paired with a private question; denied input audit
redaction; local-client cloud-job rejection; exact policy history with interrupted
replacement; stale proposals after policy changes; scope replacement revoking grants;
restore of policy history; and the owner policy CLI. Five new schema parity cases cover
the audit/request/scope/grant models. A full-run context regression was fixed and rerun:
question labels constrain the output pack without widening access to stored records.

Cloud grants describe consent only. There is no cloud adapter, and an otherwise matching
cloud request is explicitly blocked without transmission. Release installation, version
inspection/migration, and the gold-set report remain required independent work. The
owner-selected manual continuity session is still pending.

Release preparation now has a typed manifest, locked wheel acquisition, bundle inventory
checks, and installed-runtime verification. The initial 31 focused schema/release/CLI
tests passed. The subsequent offline trial at revision
`58f03a6574b56ec9221659d05786cf25d7baa867` passed with **15 distributions and 871 verified
files**, imported from the new environment's site-packages. Synthetic capture, approval,
apply, query, backup, and restore passed through the installed CLI with network disabled.
The trial rejected modified package bytes, an unreviewed `.pth`, and editable metadata.
See `docs/evidence/release-trial.json` and `docs/installation.md` for the exact manifest
digest and target. This is a `linux-aarch64` reference bundle, not a macOS installation.

The final `bash scripts/check.sh` run after release-code changes passed **131 tests**,
Ruff, strict mypy (49 files), both sets of 13 isolation probes, six installed-worker
trials, the manual-fixture generator, and real-engine lifecycle checks. CI now also runs
the separate offline installation trial. Private activation/restore gates, version
inspection/migration, the gold-set evaluation, and the final requirement matrix remain.
The manual second-session continuity test remains pending by owner choice.

Activation/restore increment: **146 tests passed**, Ruff passed, and strict mypy passed
(52 source files) in `bash scripts/check.sh`. Both independent isolation profiles passed
13 checks each, the installed worker's new nonce-bound probe passed all 13 checks on the
real engine, all six installed-worker trials passed, and the lifecycle checks passed.

`tests/test_activation.py` covers ten cases: required review and installed-runtime gates
before creation; missing, failed, replayed, or unavailable probes; changed host canaries;
release/image binding; private inline-bypass rejection; rechecks before operations;
private-mode restore preserving source/policy bytes with a new runtime approval; staging
failure; and doctor reporting unchecked or blocked workers. These lifecycle tests use
synthetic data with explicitly stubbed installation/worker verification. They do not prove
successful activation on a real owner machine. Five exported-schema checks were added.

The clean-revision offline trial at `330ce6b6be116e8e8eaa9e79fbb99f3a5737da2d` passed:
15 distributions and 874 files verified; installed CLI workflow through restore passed;
tampered installation, unreviewed `.pth`, and editable metadata were rejected. The
installed CLI blocked activation with no live engine and created no workspace. Separately,
the exact manifest-bound worker image passed all 13 real-engine probe checks with 64 MiB
scratch and an unmounted synthetic canary. Reports are retained in
`docs/evidence/activation-release-trial.json` and `activation-worker-profile.json`.
Actual owner activation, the manual continuity check, and release review remain separate.

Schema migration increment: **169 cumulative tests passed**, Ruff passed, and strict
mypy passed (55 source files) in `bash scripts/check.sh`. Both isolation profiles and the
installed worker probe passed all 13 checks each; all six worker trials, the manual-fixture
generator, and the real-engine lifecycle checks passed. `tests/test_migration.py`
contributes 18 cases, plus five
new schema-export parity cases. Legacy workspace v1 stays readable without writes;
new v2 explicitly requires record schema 1. Unknown versions and a missing v2 record
contract are rejected. The owner command previews exact bytes and all durable input
hashes, makes an independently hashed backup, and requires an exact preview digest and
statement before journaled configuration/policy replacement.

Executed tests cover stale preview and stale workspace handles; occupied backup targets;
unknown record versions; nine real process-termination boundaries (backup, authorization,
policy intent, prepared journal, both replacements, receipt, commit marker, and history);
read blocking while prepared; unexpected owner bytes; an altered configuration target in
the journal; source/record/adoption-chain preservation; invalidation of pending approvals;
restoring pre- and post-migration archives; invalid migration receipts; retryable history;
and the owner CLI. The private-mode fixture checks release binding and re-verification
with synthetic installation stubs; it is not an actual private deployment.

The migration deliberately changes workspace format only. It does not install or approve
a different runtime, migrate Markdown record schema 1, or permit backing up a prepared
schema transaction. Recover locally or use the mandatory pre-migration archive. These
limits and the separate `schema recover` procedure are in `docs/schema-migrations.md`.
The clean-revision offline trial at `1b72f1b7b276dfe3cf019895e2ea90249d56b230` passed
with **15 distributions and 877 verified files**. The freshly installed CLI opened a
synthetic legacy workspace without rewriting it, migrated it after preview/backup,
retained its query result, and backed up/restored the migrated workspace. Installation
tamper checks and activation denial without an engine also passed. The manifest-bound
worker passed all 13 real-engine isolation checks. Evidence is retained in
`docs/evidence/migration-release-trial.json` and `migration-worker-profile.json`.
The manifest SHA256 is `af540becc04763a2dac6b459dd798ffbe97de4b6f040df7cfe1471724c221bfd`.
This remains a Linux-aarch64 reference trial, not owner-machine activation or semantic
acceptance. Gold-set reporting, the final requirements audit, and the manual M2 gate remain.

Synthetic evaluation increment: `bash scripts/check.sh` again passed **169 tests**, Ruff,
strict mypy (55 files), both sets of 13 isolation checks, the installed worker probe,
all six worker trials, fixture generation, and real-engine lifecycle checks. The newly
integrated gold-set evaluator passed **129/129 checks** in the installed development
image. The retained public report binds its source tree, corpus, and script hashes.

Eight query cases retained all expected sources and exact wording, dates, and explicit
conflicts. All 36 citation occurrences passed hash/locator/quote checks; the defined
scope and write checks observed zero violations. The fixture generated 12 proposals and
13 page changes. It records latency samples, review flags, and zero model calls/cost;
human edits/time and semantic quality are explicitly unmeasured. Conversation roles,
unadopted suggestions, and the adopted decision/failure context workflow were exercised.
See `docs/evaluation.md` and `docs/evidence/goldset.json`. This does not satisfy the
owner-selected manual second-agent gate or establish entailment or complete security.

Source-review/final-audit increment: **175 tests passed**, Ruff passed, strict mypy passed
(56 files), both sets of 13 isolation checks and the installed worker probe passed, all
six worker trials passed, gold-set checks remained **129/129**, and the real-engine
lifecycle checks passed. Six new review tests cover local source/artifact links, dates,
coverage, explicit conflicts, read-only behavior, recomputed stale/tampered diffs, revoked
scope denial, symlink refusal, and rendering hostile HTML/links/fences without activation.
An earlier acceptance invocation stopped at a test-formatting lint error; the corrected
complete invocation passed all stages.

`docs/requirements.md` now maps every brief boundary, ingestion step, hard gate, named
artifact, interface, domain template, evaluation measure, and additional plan requirement
to inspected implementation and named evidence. The audit identified and closed the
missing Markdown source-review report and added a validated synthetic configuration
example. The updated offline installed-release trial remains the final revision-specific
check for this increment; the manual M2 semantic gate remains pending by owner choice.

Final installed trial at `6bcad55cd9c71ea154dab2d4e6e34b65e80d1929`: **15 distributions,
878 files verified**. The fresh offline CLI passed Markdown source review, capture through
approval/apply/query, explicit legacy schema migration with backup, and restore. Modified
package files, an unreviewed `.pth`, and editable metadata were rejected. Activation with
no live engine remained blocked without creating a workspace. The exact manifest-bound
worker image passed all 13 real-engine isolation checks. Retained reports are
`docs/evidence/final-release-trial.json` and `final-worker-profile.json`; manifest SHA256
is `b4c9def89d6d673afe6b650adce49714e471902d31541497d3756802af73a9ae`.

The final matrix closes the independent public implementation/evaluation/audit work.
M0/M1/M3 have reference acceptance; M2 mechanics pass but the required separate manual
agent session still has no semantic result. The goal must remain incomplete until that
gate has evidence. Actual private activation, real-data evaluation, and M4 remain outside
this goal. All test workspaces were synthetic; no private directory was accessed.

The saved manual handoff pack was also rechecked: its SHA256 matches
`examples/continuity/verification.json`, all 11 citation occurrences resolve against the
saved source/extraction evidence, and the adopted decision and failed approach are
present. This verifies the input artifact, not a second agent's use of it. Follow
[the manual separate-session procedure](research-continuity.md#manual-separate-session-acceptance)
to supply the remaining result.

Manual M2 evidence received from the owner: reported model **GPT 6 Astra Light**, reported
generation time **7 seconds**, cost/tokens unknown, owner verdict **unclear** because the
context was unfamiliar. That verdict is preserved, not promoted to owner approval.
The supplied response explicitly uses the adopted provenance requirement in a concrete
three-source/four-case design, avoids title-only retrieval, and separates its design from
unrun experiments. It cites the matching context ID and named decision/failure sections.
The implementation assistant therefore records a **design-level semantic continuity pass**.

The original receipt is not Cairn-schema compatible (missing session/project IDs, an
unstructured next action, and extra fields). The initial test prompt did not supply that
schema. The raw receipt is retained, and a separately labeled reviewer normalization
validates as `SessionReceipt`. Its added evidence references come from the saved pack,
not the second agent. No approval, adoption, canonical import, or experiment was performed.
The context hash and all 11 input citation occurrences were reverified in the no-network
development container. External client isolation, input bytes, and network behavior are
not independently verified; this is an owner-supplied manual observation.

See [the recorded review](research-continuity.md#recorded-manual-result) and
[`manual-evaluation.json`](../examples/continuity/manual-evaluation.json) for artifact
hashes, criterion-specific evidence, validation errors, and limits. This closes the last
M0–M3 gate at its specified scope. The runtime code and earlier executed release checks
are unchanged. Actual private deployment and general model-quality evaluation remain
outside this acceptance.

Final evidence validation is retained in `docs/evidence/manual-review-check.json`:
67 checks passed, including 37 local documentation links, original-receipt rejection,
normalized-receipt validation, artifact hashes, and current source/corpus/evaluator
bindings to the passing 129-check gold report. A Git comparison against the installed
trial's `6bcad55` revision confirmed no changes to runtime, tests, schemas, build scripts,
dependencies, container configuration, CI, or templates. This documentation/evidence-only
increment did not rerun or change the previously passing 175-test release validation.

Repository naming update: the software repository is `cairn-workbench`; the separately
configured private knowledge base is `cairn`. Documentation and the synthetic example
configuration use those names. Runtime code, Python package, CLI, and schemas are
unchanged; this documentation/configuration-only change passes `git diff --check`.
# Journal catalog follow-on — implementation evidence

The journal catalog extension is under development. Synthetic tests run in the documented
network-disabled development container (public checkout mount only). The targeted catalog,
existing ingestion/apply, backup, schema-export, and CLI suite passed **65 tests**.
Three additional publication-discovery tests passed: cursor resumption/idempotence,
unresolved journals/feed-only coverage, and failed-page watermark preservation.
These are mechanical tests, not paper-reading quality evidence. Workstation SSH timed out;
GPU inference, subscription verification, release activation, and private-library deployment
are not yet verified. No real paper or private workspace has been used by contributor code.

## Cairn HTML follow-on — foundation evidence (2026-10-09)

The application renderer is built from maintained source, with a complete licensed
source snapshot and lockfile in `vendor/answer-me-with-html`. The generic CLI and both
installed skills remain unchanged. The standalone renderer source is synchronized at
`0a13bfcaaa5081b87e6cd191537426261da8c1df`; its upstream base is
`19b2b5b07676d3e65c83ca9a7b6621f300b54c92` (0.5.0). Quill resources are pinned at
`d6bc7de15d1779c58286cbdec1a54eec52bdef22` (0.3.0, MIT). Resource hashes are recorded in
`src/cairn/presentation/resources/provenance.json`.

Executed in the isolated renderer development container with synthetic inputs:

- Full renderer suite: **788 tests, 786 passed, zero failed, two skipped**.
- Mandatory Chromium application checks passed: 1440/390 widths, light/dark, keyboard
  focus, evidence disclosures, diagram controls/Escape, filtering, feedback JSON
  download, no persistent storage, reduced motion, print and JavaScript-disabled
  readability. Request monitoring recorded zero HTTP(S) requests. Screenshots were
  inspected; the narrow diagram was changed to wrap rather than require scrolling.
- Actual container probe passed: non-root, read-only root, no network interface beyond
  loopback, no credentials, capabilities or Docker socket. Browser coverage was not
  skipped or counted as passing by absence.
- Node 20.19.0, 22.14.0 and 24.0.0 exercised generic rendering/patches/captions and the
  Cairn package from ordinary and space/non-ASCII install paths with no agent variables.
- Application rebuilds matched each other and the committed runtime byte for byte.
  Generic CLI rebuilds matched in its documented original build-directory layout.

Failed checks during development, resolved: an interrupted-write test initially
expected raw OSError rather than the writer's existing Denied wrapper; it was corrected
and rerun. A generic CLI checksum comparison from a deeper scratch directory differed
only in 230 esbuild dependency-path comment lines. Repeating the documented original
layout matched exactly; no generated file was hand-edited. Lint issues were fixed
before the passing suite.

Skipped upstream checks: reused foreign-owner PID detection (PID 1 is signalable by
the container UID) and the separate marketing-site build test (site/dist not built).
Neither is a Cairn isolation or browser gate. Live agent-product compatibility, private
workspace deployment, cloud narration and GPU inference are not established here.

### Knowledge-view and review milestone

The seven typed views and shared terminal/Markdown/HTML proposal review model passed
their targeted synthetic tests. Fresh diffs, exact proposal hashes, assertion kinds,
verification, owner adoption and personal reading are displayed separately. Added
regressions cover denied-scope leakage in serialized bundles and HTML, markup injection,
render failure, stale records/library status/approval state, revoked scope, interrupted
replacement and retries leaving one deliverable. Retrieval of a historical saved view
still rechecks authorization. Viewing emits no approval or validation event.

The full development/container check at this milestone passed **255 tests**, Ruff,
strict mypy, schema parity, worker canary/network/credential probes, hostile subprocess
containment, real worker lifecycle cleanup, and a no-mount HTML JSON roundtrip. A final
release trial follows the complete packet/feedback milestone; this result alone is
not private deployment approval.

### Writing and feedback milestone

A synthetic Quill packet was prepared by `scripts/html_packet_trial.py`, exported,
read and answered by **Codex in this development chat**, then imported/rendered after
restoring the synthetic backup. Canonical records and approvals were unchanged.
Manual comparison retained 12 simulated datasets, condition C, errors 12% versus
15%, the −3 percentage-point difference and 95% interval [−7, +1]. It distinguished
a point estimate from a clear superiority/equivalence claim and missing excerpt
coverage from an assertion that other conditions were never studied. This is one
manually inspected synthetic case, not a semantic-quality benchmark or a verified
local-execution attestation. No other agent product was exercised live.

The packet/feedback tests exercise grants for both generation and client export,
private-question defaults, local-only blocking, job/input identity, exact quotations,
missing/foreign citations, forged approval/status fields, revoked policy, response
idempotency, immutable source/catalog targets and comments awaiting action. A synthetic
feedback revision stages through normal proposals, remains unapplied without owner
approval, applies after explicit test-owner approval, and rejects stale replay. Saved
view/writing/feedback receipts participate in backup validation; modified excerpt bytes
are rejected even if a forged bundle ID is recomputed.

Skill review covered explicit HTML (render supplied document), ordinary questions
(no page), maintenance (edit skill only), presentation edits (same packet/output),
knowledge changes (new bundle), explanations (structured Quill response), feedback
(selected-target proposal) and video requests (outside this skill's scope; no implicit
cloud call). The entry point and relative references use the Agent Skills format.
The existing generic HTML and Quill installations were not changed.

The first synthetic trial preparation failed because its consent text differed from
its owner statement. The fixture was corrected to identical explicit text and rerun;
the authorization check was retained. An earlier writer interruption test and build
path comparison are recorded above rather than counted as passing attempts.

### Final release evidence

The complete source implementation is commit
`5428abeade70a48ae3e0a619ed6d246bedeb816f`. The final acceptance commit changes only
this record and the documented validation entry point; it does not claim a different
runtime was exercised.

**Executed and passed:**

- `bash scripts/check.sh`: **255 passed**, zero skipped/failed; Ruff passed; strict
  mypy passed for 89 source files; generated-schema parity passed. Actual dev/worker
  isolation probes, hostile subprocess containment, lifecycle removal and renderer
  JSON roundtrip all passed. Goldset control-flow checks passed 129/129; fake-provider
  outputs remain control-flow evidence rather than semantic-quality evidence.
- `bash scripts/check_html.sh`: complete renderer suite **786 passed, zero failed,
  two upstream skips** out of 788; required Chromium and isolation gates passed.
  Both generic and Cairn packaged CLIs passed all six Node/install-path combinations.
  Application rebuilds matched the checked-in bytes. Two independently generated
  portable ZIPs matched byte for byte. The actual exported synthetic Quill packet
  also rendered through the packaged CLI after its request/document checksum checks.
- Chromium **154.0.8037.92**, Linux ARM64: desktop/narrow light/dark screenshots were
  reviewed; controls, JavaScript-disabled content, print and zero unintended requests
  passed. The accepted synthetic explanation was additionally rendered and inspected.
- Skill frontmatter/reference review and the installed skill-creator validator passed.
  Existing generic renderer bytes still match their prior pinned checksum; installed
  Quill guidance still matches its pinned copy. Neither installation was replaced.
- `bash scripts/release_check.sh`: fresh offline installation of 15 distributions,
  **919 verified installed files**, HTML render/retry/saved-view backup/restore, existing
  Markdown review, capture/approval/apply/query, library/feed and migration trials
  passed. Modified renderer/package bytes, unreviewed .pth files and editable installs
  were rejected. Activation without the required owner engine remained blocked.
- Release manifest SHA256:
  `51c5fe3e7ba4faf79b598c9e6c47f5ec601fbb8c25d2580c2d38943c7e75e652`.
  Its worker image is
  `sha256:4de955dfdb10666e154403c14a7ded2f93a9e69f87f0e90926def1668e901fa7`.
  That exact image passed all 13 installed-worker isolation checks and an additional
  no-mount HTML render roundtrip. The pinned production Node runtime is **24.21.0**;
  compatibility smoke runtimes were **20.19.0, 22.14.0 and 24.0.0**.
- Portable `cairn-html.zip` SHA256:
  `fb5b7a1934661b231e963a125b9e20b9187c4fc365813ee3b72f3bd94d392a06`.
  Source/runtime/license hashes and the maintained renderer commit are in the packaged
  provenance. Public-code review found only source, licensed vendor resources,
  documentation and synthetic tests; no real workspace, credentials or owner paths
  were added. The first-party diff passed `git diff --check`.

**Failed checks:** none unresolved. Earlier failed attempts and their corrections are
recorded above. Docker initially needed permission to update host build metadata;
it was rerun with that permission, without broadening processing-container access.

**Skipped checks:** only the two identified upstream PID/marketing-site cases.
No required isolation or browser check was skipped or substituted with a fake result.
Native Windows/macOS rendering and other agent products were not exercised.

**Live deployment:** not performed. No private inputs, subscription transports, local
writing model, GPU reader, scheduled jobs or installation changes were activated.
Manual packet responses do not attest local execution; local-only writing remains
blocked without a reviewed adapter. The semantic review covers one synthetic Codex
response. Owner release acceptance and any private deployment remain separate.
