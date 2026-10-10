# Working on Cairn

Read `KNOWLEDGE_WORKBENCH_BUILD_BRIEF.md` and `CAIRN_BUILD_PLAN.md` before changing boundaries.
Develop and test with synthetic data only. Do not inspect, mount, or ingest a real private
workspace, a home directory, or private credentials. Public fixtures and documentation
must use synthetic names and paths. Never add a remote or publish automatically.

Run contributor code through the documented development container. The worker image
must have no network, owner filesystem, credentials, or Docker socket at processing time.
Do not turn a skipped isolation check into a passing readiness gate.

Keep source bytes and human notes immutable to model proposals. Approval and canonical
apply remain owner operations. A model-supplied actor or approval field is not authority.
Preserve the six record types, explicit state machine, source locators, scoped retrieval,
and recoverable writer. Keep schema exports synchronized with the typed models.

Use small milestone commits and maintain `docs/acceptance.md` with honest evidence.
Run meaningful tests for changed boundaries and failure modes; do not claim that fake
provider results prove semantic quality or production readiness.

## Updates

The updater (`cairn update`) is an owner-machine operation outside the processing
boundary. A release is the `stable` branch with a higher version number (see
`CHANGELOG.md` and `docs/updates.md`); the new runtime checks it against the knowledge
base's own `UpdateAuthorization`, verifies itself, takes a backup and records an
`upgrade` approval chained to an owner-acknowledged activation. Never weaken the
channel, fast-forward, source-hash or downgrade checks, and never run `setup`, `run` or the scheduler
against a real home from contributor code. Tests use a synthetic `CAIRN_HOME`, local
synthetic remotes and throwaway keys.

## Agents, reading and writing

The owner uses Cairn from inside their own agent (Claude Code, Codex, Cursor); Cairn
never launches an agent. The interface is the local stdio MCP server
(`cairn mcp`, `src/cairn/mcp.py`). Keep its tool set to scoped reads and one-call
`propose_*` tools; never expose approval, accept, apply, recovery, policy, backup,
restore, schema or update. Owner commands require confirmation at the owner's terminal;
never add a non-interactive bypass that works on a real knowledge base. Launch arguments fix the scope and granted route; tools must not widen
them. Anything a tool returns reaches the agent's provider, so it needs a cloud grant.

Cairn does not vendor, install, edit or update Finch, Quill or any other skill. Packets
carry Cairn's own contracts (`reading/contract.md`, `presentation/contract.md`,
`proposals/contract.md`); skills only supply method. Every response is untrusted and
goes through `finish` validation; a model-supplied approval, actor or status field is
not authority.

When you read a paper or write a page for the owner inside a Cairn knowledge base, use
the Cairn tools, follow the contract in the `propose_*` tool description, and report
the source/proposal IDs or an explicit pending/blocked reason. Never run `cairn accept`,
`approve` or `apply`; acceptance is the owner's step. Do not inspect private
configuration or use contributor code against a private workspace; missing owner
configuration does not authorize a guessed route. Tests use synthetic workspaces, a
synthetic home and a subprocess MCP client, never a real agent or home directory.
