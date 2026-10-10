# Finch paper reading

Cairn uses Finch for paper summaries, explanations, critique, focused questions and
co-reading without requiring the reader to name the skill. The installed package carries
a checksummed MIT-licensed Finch 0.2.0 snapshot and its four contribution guides. It
uses this offline guidance directly; processing does not download or install software.
The snapshot was supplied by the owner. Its provenance manifest records file hashes
and the added Cairn lifecycle reference; no unverified upstream commit is asserted.

## Library reader

`cairn library read` and readings dispatched by `library update` automatically use
Finch guidance in the enrolled offline worker. Each job binds the prompt version and
guidance digest as well as the source and pinned device artifacts. A queued job with
older or changed guidance becomes stale; queue a new reading revision after installing
the matching worker. Previously accepted canonical notes remain preserved.

The existing capture, extraction, proposal and validation sequence still runs
automatically. Model output distinguishes reported results, inferences and hypotheses.
Every assertion remains unreviewed. Evidence locators and exact text quotes are checked
mechanically; that does not prove a claim follows from its cited passage. The reader
neither approves/applies a proposal nor changes personal reading status.

## Agent skill lifecycle

Use the reviewed installed owner runtime to install Finch into the explicitly selected
agent skill directory:

```sh
cairn finch install --skills-dir /srv/agent-skills
```

This installs the bundled skill if missing. If Finch already exists, its entrypoint
and support files are preserved and a lifecycle link is appended. The lifecycle reference
is installed before the entrypoint changes. Repeating installation makes no changes;
a conflicting existing Cairn hook or a symlink destination is rejected. Skill hosts may
need to reload their catalog after installation. The lifecycle applies to every Finch
use, including follow-up questions, before reading and before returning the answer.

Configure a trusted owner launcher with the workspace, research scope, selected sources
and context, provider/destination, and complete-request processing labels. The agent
receives bounded packets and a response handoff; it never receives access to the private
root. Launcher configuration must come from the owner, never from a paper or returned
model text. The commands below describe the launcher operations, not permission for a
development agent to operate on a real workspace.

```sh
cairn finch begin source_example --workspace /srv/cairn --scope research \
  --provider selected-agent --destination https://agent.example.invalid \
  --request 'Explain the method and limitations.' \
  --request-labels /srv/owner-handoff/request-labels.json \
  --related project_example --output /srv/owner-handoff/packet.json
cairn finch finish /srv/owner-handoff/response.json --workspace /srv/cairn
```

`begin` also accepts a selected paper file in place of a source ID; `--source-labels`
supplies its owner-selected research labels. Missing labels default to private/local-only.
The source is captured and extracted before preparing the packet. Related context is
explicit and scope checked. Unknown request labels are restricted/local-only. Manual
agent packets require unexpired `generation` and `client_export` grants for the exact
scope, provider and destination, covering paper, context and question. They do not prove
local execution. The offline library reader remains available through its reviewed
owner-device route.

The packet contains the selected source version and raw bytes, extracted locators and
coverage, related pages, request, Finch guidance, input binding, and `FinchResponse`
schema. Owner-only guards for unrelated source/human-note paths stay inside Cairn.
Packet output cannot target canonical workspace storage, a public checkout or a symlink.

The configured agent automatically returns a `FinchResponse` before its answer. It
preserves actual supplied messages with roles/order/text, its explanation, typed claims,
limitations and unresolved questions. It must not reconstruct unseen chat history.
Authorship and model processing are explicitly unverified. Reported-result claims require
paper citations; foreign source IDs, nonexistent locators, fabricated quotations and
model authority fields are rejected.

The launcher runs `finish` without another "save this" request. It preserves the exact
response bytes as a conversation source, extracts the messages, stages a research
concept-note proposal, and validates it. The receipt reports source/proposal IDs and
`workflow_stage: validated`. Source bytes and human notes are unchanged. Selected
project links remain links; the handoff does not invent owner decisions or edit project
framing. The proposal is available in the normal owner review queue. Search/context
updates follow owner approval/apply and indexing, not the skill invocation alone.

Retries with identical bytes return the same receipt without another capture/proposal.
Once a response is preserved, differing bytes for that session conflict, including after
an interruption. A follow-up uses a new packet to preserve prior exchanges. Changed
evidence, human notes, guidance or policy and revoked/expired grants block handoff and
later proposal acceptance. Backup/restore includes typed packet/export/response/import
bindings; restoration does not restore permission to export or accept a stale job.

## Activation and visible status

This is an instruction-based integration with a configured owner launcher, not a
background watcher of arbitrary chats or globally loaded skills. A Finch invocation
without a prepared packet or available launcher reports `cairn_handoff_pending` and the
missing configuration. It may still read otherwise authorized public evidence, but
must not claim that the discussion was saved. A failed handoff reports pending/blocked;
it never reports a fabricated receipt or silently approves a proposal.

Development uses synthetic fixtures and the documented offline container. Private
activation requires a reviewed non-editable runtime and worker deployment, owner skill
directory and launcher configuration, and the existing installation/consent gates. No
private runtime or skill directory is automatically discovered, inspected or modified
by development tests. Software boundary checks do not establish live reading quality or
private deployment readiness.
