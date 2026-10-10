# Agent integration

Paper reading defaults to Finch. Finch's Cairn handoff guide automatically
hands each supplied reading exchange back for capture, a concept proposal and validation;
it never grants approval/apply authority. The [Finch handoff](finch-reading.md) documents
the exact packet/response schemas, configured launcher and pending status. Agent hosts
without that configured lifecycle are not silently monitored or logged.

`Job` and `Result` schemas define the initial client packet protocol. Jobs bind source
and extraction versions, the scope, policy hash, related pages, provider, route, and a
small change budget. Responses bind `job_id` and the canonical input hash and contain
typed candidate records, bodies, and rationale. Unknown fields (including self-approval
or execution instructions) are rejected.

`ClientPacketProvider` invokes a reviewed image using JSON on stdin/stdout in the same
network-disabled, no-mount profile used by the fake provider. A client image must implement
that protocol at its entry point. Existing frontend-specific automation is an adapter
responsibility; no model CLI or model weights are bundled or downloaded during a run.
The included image implements deterministic extraction and `fake-v1` only.

The owner launcher verifies a local Unix-socket Docker endpoint and rejects remote
SSH/TCP contexts and image-declared persistent volumes before sending a packet. It uses
Docker's separate [create](https://docs.docker.com/reference/cli/docker/container/create/)
and [start](https://docs.docker.com/reference/cli/docker/container/start/) operations so it
knows the owned container ID before streaming input. Processing disables network,
health checks, restarts, and Docker logging. Stdout is limited to 32 MiB, stderr to 64 KiB,
and processing to 90 seconds; diagnostics are not copied into application errors.
The launcher checks the container's exit state and forcibly removes that exact container
and its anonymous volumes on success or failure. Unverified cleanup blocks the result
and reports the container ID for owner inspection. Docker control calls have separate
bounded time/output limits. An engine outage can require manual cleanup; no result is
reported successful while cleanup is unverified.

Lifecycle tests combine real child-process stream/deadline tests with a synthetic engine
process in the development container. The host acceptance script separately verifies
create/start/remove on the real Docker engine, including removal of a running worker and
its child. It does not expose the daemon socket to contributor Python or any worker.

The owner prepares/seals jobs and stages returned results. Clients do not receive the
owner's vault, policy files, approvals, journal, global index, or arbitrary file/shell
tools. Running a host client under the owner's login against the vault is not equivalent
to using this protocol. Manual external results have an unverifiable processing route
and must not be accepted as proof of local execution.

Schema inspection/migration commands are owner maintenance operations, outside the model
packet protocol. A migration advances policy revision, so queued client jobs and pending
proposals must be regenerated; clients cannot reuse earlier approvals. Previously applied
decisions remain available through their original adoption receipts and scoped context.

Cloud transport is not implemented. It must not be enabled by changing a provider string
or supplying credentials. Separately configured owner grants are required before any
future export of a complete request, including the question and derived context.

M2 adds bounded project context packs and session receipts. The protocol's deterministic
tests establish mechanical correctness only; a separate synthetic agent trial is needed
to evaluate whether a later session actually uses approved decisions and failed approaches.

## HTML and Quill packets

The [Cairn HTML workflow](html-views.md) adds a bounded writing packet route. Agents
receive approved evidence and a response schema, never vault mounts or owner apply
authority. `skills/cairn-html` is agent-neutral and explicit about HTML intent. Manual
packets cannot prove local execution; local-only data remains blocked without a reviewed
local adapter. The owner rechecks grants and input hashes on import, and feedback
revisions still enter the existing proposal queue.
