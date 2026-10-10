# Finch paper reading

Cairn uses Finch for paper summaries, explanations, critique, focused questions and
co-reading without requiring the reader to name the skill. The installed package carries
a checksummed MIT-licensed Finch 0.3.0 snapshot, its four contribution guides, its Cairn
handoff guide and Finch's installer. The offline reader uses this snapshot directly;
processing does not download or install software. The provenance manifest records file
hashes and the upstream commit. Cairn makes no changes to the snapshot.

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

Initializing a private workspace installs Finch for the owner's agents when it is missing:

```sh
cairn init --workspace /srv/cairn --code-root /srv/cairn-runtime ...  # --no-finch to skip
cairn finch status                     # agent-facing Finch and bundled reader version
cairn finch install                    # retry; --no-auto-update skips the daily update
```

Finch is available if its installer clone (`$FINCH_HOME`, default
`~/.local/share/finch`) or a `finch/SKILL.md` exists in a known agent skill directory
(`~/.claude/skills`, `~/.agents/skills`, `~/.copilot/skills`,
`~/.config/opencode/skills`). An available Finch is never reinstalled or edited. Otherwise
Cairn runs Finch's own installer from the checksummed packaged copy. It clones the
`stable` release, links it into each detected agent, adds the `finch` command and, unless
disabled, schedules Finch's daily fast-forward update (launchd or cron). This setup step
uses the network; offline or failed installation leaves the workspace usable and reports
`pending` with the retry command. Synthetic workspaces skip installation unless `--finch`
is given. A Finch installed as a Claude Code plugin is not detected; use `--no-finch` to
avoid a second copy. Skill hosts may need to reload their catalog after installation.

Finch ships the Cairn lifecycle as `references/cairn.md`. It applies only when a Cairn
packet is supplied or the reader asks to read inside the knowledge base, before reading
and before returning the answer, including follow-up questions. Because Cairn no longer
edits Finch, the installed clone stays clean and Finch's own update keeps working. Each
packet also carries the bundled handoff guide, so an older installed Finch still receives
it. The agent-facing Finch can be newer than the bundled offline-reader snapshot;
`cairn finch status` reports both versions.

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
background watcher of arbitrary chats. A Finch invocation inside the knowledge base
without a prepared packet or available launcher reports `cairn_handoff_pending` and the
missing configuration; Finch used outside Cairn is unaffected. It may still read otherwise authorized public evidence, but
must not claim that the discussion was saved. A failed handoff reports pending/blocked;
it never reports a fabricated receipt or silently approves a proposal.

Development uses synthetic fixtures and the documented offline container. Private
activation requires a reviewed non-editable runtime and worker deployment, launcher
configuration, and the existing installation/consent gates. Only the owner's private
`cairn init` or `cairn finch install` looks for agent skill directories under the
owner's home; development tests use a synthetic home and a local synthetic remote, and
never discover, inspect or modify a real home, runtime or skill directory. Software boundary checks do not establish live reading quality or
private deployment readiness.
