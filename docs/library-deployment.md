# Library deployment and evidence gates

Development uses synthetic data only. Do not run contributor code against an owner
workspace or source archive. Build and activate a pinned release before owner-side work.
The local catalog does not require a GPU, but automatic reading remains queued until
the enrolled owner device passes isolation and an owner-reviewed quality/memory pilot.

## Workstation preparation

The runner targets a dedicated Linux WSL2 distribution named `Cairn`, with NVIDIA GPU
container support and a local Unix-socket Docker engine. Use an owner-controlled account
and install the reviewed wheel in `/opt/cairn-device`. Its entry point is fixed:
`/opt/cairn-device/bin/cairn-device serve`. The Windows SSH route invokes that entry point
through `wsl.exe --distribution Cairn --exec`. No job-supplied shell command is accepted.

The public acquisition script `scripts/prepare_reader_models.sh NEW_DIRECTORY` downloads
Qwen/Qwen3.5-9B revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, converts its model and
vision projector, and creates Q8_0 model weights using llama.cpp revision
`feb9a3d6debb3a8544052b04c84fa1f445fd77f5`. It records artifact SHA-256 values. Acquisition
has network access and must finish before processing; the processing image never downloads.
The converter's Python dependencies follow the pinned upstream requirements. Keep its
environment lock and build log with the owner-side artifact provenance.

Build `containers/reader.Dockerfile` on the workstation with its pinned CUDA base and
llama.cpp source. Pin the resulting local image ID. This CUDA build has **not** been tested
on the target GPU by the contributor tests. Place reviewed artifacts in the dedicated
`/opt/cairn-models/model.gguf` and `/opt/cairn-models/mmproj.gguf` files. Create an owner-only
`/var/lib/cairn-device` directory for the one-job GPU lock. Configure `/etc/cairn-device.json`
using `runnerconfig-v1.json` and protect the config, installed code and model directory
from modification by the container user. Ensure the owner runner can execute `nvidia-smi`.

Create a dedicated SSH known-hosts file from an independently checked workstation host
key. Do not populate it by blindly trusting a network scan. `deviceconfig-v1.json` binds
that file's hash, the SSH alias, route type, image, model and projector hashes, source
revisions, and research scope. `library worker enroll FILE` runs a fresh nonce-bound
isolation probe through the fixed runner. Revocation clears enrollment and invalidates
pending proposal inputs. Changed host keys, artifacts, scope or policy fail closed.

Run synthetic papers covering scans, tables, equations, long documents, misleading
instructions and unsupported evidence. Save the exact result packets and memory
measurements. Review their accuracy before supplying `quality_review` in the enrollment
file: it binds the trial digest, image and model hashes, peak VRAM, date and owner statement.
An isolation-only probe does not authorize private readings. The first real pilot must
remain small; quality acceptance belongs to the owner and is never inferred from a fake
provider, a successful container launch, or a model's confidence.

## Subscription verification

Use `library verification-configure FILE` with explicit journal IDs, research scope,
future expiry and an owner statement. This is a distinct owner export action: only the
short summary, at most twelve supporting page passages, at most four page images, and
source/version identifiers are copied into an immutable cloud-eligible evidence packet.
The original PDF, catalog entry and human notes retain their original labels. Both
provider-specific `client_export` grants are recorded in the existing policy audit chain.
Configure consent before queuing readings because policy changes invalidate sealed jobs.

The official installed Codex and Claude clients use their own subscription login. The
adapter does not copy or inspect credentials. API keys/provider overrides cause a blocked
check; no automatic paid fallback exists. Reviewed client profiles currently pin Codex
CLI 0.153.4 and Claude Code 2.1.285. A changed version requires reviewing the flags and
tool surface again. Codex uses a tool-free model catalog, disabled feature tools, ignored
user config/rules, empty MCP config and a temporary working directory. Claude uses safe
and restricted modes, an empty built-in tool list, strict empty MCP config and disabled
hooks. Managed administrative policy still applies; a conflicting policy must block the
pilot rather than be bypassed. A real subscription capability trial is required before
activation; synthetic command construction tests do not prove service behavior.

The first ten completed readings go to both providers. Later readings have one stable,
hash-selected position in every cohort of ten per journal and text/vision mode. Complete
cohorts therefore sample 10%; incomplete cohorts have zero or one selected reading.
Providers alternate by cohort with a stable per-stratum offset. Flagged evidence goes
to both; concerns escalate routine single-provider checks to the other provider. Checks
bind exact packet/source/summary hashes. Pending selected checks prevent acceptance;
failed checks require a revised reading. Use `library read ... --revision 2` for an explicit
new reading attempt. No model check changes personal reading status or supplies approval.

## Weekly operation and delivery

After release activation and the small pilot, use `library update --device DEVICE_ID`.
The first run establishes the archive baseline. Later runs distinguish new publications,
historical discoveries and new/revised Box files. Reading budgets defer excess work and
outages retain queued jobs. Persistent checkpoints resume interrupted stages. Only one
update process runs per workspace. Original PDFs are read-only; full-paper downloads are
not implemented. Unresolved journal identities remain listed with discovery blocked.

The saved digest includes citations, summaries, evidence coverage, availability, personal
reading, analysis/review and verification states. `feed latest --json`, `feed history
--limit 20`, and `feed export --format atom` provide bounded feed access for Dot or other
local consumers. Markdown, HTML and Atom presentations are regenerated from durable feed
records. HTML escapes all imported markup and loads no remote resources. Feed snapshots
contain at most 500 events; the catalog retains the complete paper inventory.

Schedule a Codex heartbeat in the delivery chat for Monday 09:00 America/Chicago **after
activation**. It should run only the pinned owner launcher, inspect pending digest IDs,
report meaningful additions, completion or failures, and stay quiet when unchanged.
After delivering a digest it should call `feed acknowledge DIGEST_ID`. Exact-once chat
delivery cannot be transactional with the local filesystem: use the stable digest ID to
check the chat for a prior delivery before retrying an unacknowledged notification.

Streaming ZIP64 `backup`/`restore` reads at most one bounded source file at a time and
keeps hashes/metadata in memory. It retains the existing 32MiB per-file processing bound,
with a one-terabyte total and one-million member safety budget. The 256MiB legacy archive
cap is no longer the CLI's library limit. Independently record the archive digest; private
restore still requires the original reviewed release. Preserve private backups outside
the public checkout.
