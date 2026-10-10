# Agent integration

You use Cairn from inside an agent you already run: Claude Code, Codex, Cursor or
another MCP host. The agent calls Cairn; Cairn never launches an agent. Cairn hands the
agent sealed packets with a Cairn-owned contract, takes back structured responses,
validates them as untrusted input and stages proposals. Approval and apply stay with
you.

Cairn does not install, edit, vendor or update agent skills. If your agent has Finch or
Quill, it uses them for *how* to read or write; each packet carries Cairn's own short
contract for *what* to return and what the agent may not do. The contracts live in
`src/cairn/reading/contract.md`, `src/cairn/presentation/contract.md` and
`src/cairn/proposals/contract.md`, and each packet binds the contract it carried.

## Connecting an agent

1. **Grant the agent route.** Everything a Cairn tool returns goes to the agent's model
   provider, so it is cloud processing. Grant it once per scope with an explicit
   provider/destination and operations:

   ```sh
   cairn policy show --workspace ~/cairn            # note the current policy hash
   cairn policy set-grant grant.json --workspace ~/cairn \
     --base-hash POLICY_HASH --statement "I consent to ..."
   ```

   `grant.json` is a `RouteGrant`: `id`, `scope`, `provider`, `destination`,
   `operations`, `valid_until` and `owner_consent` (equal to the statement).

   `generation` and `client_export` cover packets; `query` and `context` cover read
   tools. Only records labelled `cloud_eligible` can leave; local-only material is
   withheld from search and refused by every other tool.

2. **Print the registration.** Cairn prints commands; it never edits agent settings.

   ```sh
   cairn mcp --print-config --workspace ~/cairn --scope research \
     --provider claude-code --destination https://api.anthropic.com \
     --packets-dir ~/cairn-packets
   ```

   The output contains a `claude mcp add cairn -- ...` command, a `codex mcp add cairn
   -- ...` command, a Cursor `mcp.json` entry and suggested Claude Code deny rules for
   `cairn approve`, `cairn accept` and `cairn apply`.

3. **Optional file capture.** `--capture-root DIR --capture-labels labels.json` lets the
   agent pass a file path under `DIR` instead of a source ID. Those sources get the
   labels you chose; files elsewhere are refused.

The launch arguments fix the workspace, scope, provider, destination and packets
directory for the session. Tools cannot change or widen them. The packets directory
must be outside the knowledge base and public code.

## Tools

| Tool | What it does |
| --- | --- |
| `search`, `evidence`, `context` | Scoped, read-only retrieval; needs `query`/`context` grants |
| `pending` | IDs of unanswered packets and unaccepted proposals in this scope |
| `proposal_show` | A proposal's diffs, provenance and required owner review |
| `reading_begin` / `reading_finish` | Read a paper; stage a concept note from the `FinchResponse` |
| `writing_begin` / `writing_finish` | Write or revise a page; stage it from the `QuillResponse` |
| `draft_begin` / `draft_finish` | Draft knowledge pages from a source; stage the `Result` |

There is no tool for approval, accept, apply, recovery, policy, backup, restore,
schema, update or editing human notes. The server instructions tell the agent that
acceptance is your step. If your agent also has a shell, add the printed deny rules:
MCP alone cannot stop a shell-capable agent from typing an owner command. See the
[threat model](threat-model.md).

The same flows exist on the CLI for scripts and for agents without MCP:
`cairn finch begin|finish`, `cairn write begin|finish` and `cairn draft begin|finish`.

## Packets and responses

Each `*_begin` call checks the grant for the complete request (source, related pages,
question), records an `ExportReceipt` before any bytes leave, writes the full packet to
the packets directory and returns it inline (without raw source bytes). Re-running
`begin` on unchanged inputs returns the same packet ID.

- **Reading** packets hold the paper version and extraction locators, scoped related
  pages, the request, the reading contract and the `FinchResponse` schema. The response
  preserves the exchange's messages, typed claims (reported result, inference or
  hypothesis) with exact evidence references, limitations and unresolved questions.
  `finish` preserves the response as a conversation source, stages a research
  concept-note proposal and validates it.
- **Writing** packets hold instructions, one target page or new-record slot, keyed
  evidence, context pages and the writing contract. The `QuillResponse` returns a body,
  an optional title, claims with evidence keys and exact quotes, and limitations. Cairn
  formats the record itself; status, labels and existing assertions are kept and new
  claims stay unreviewed.
- **Draft** packets hold one sealed ingest `Job` (source extraction, scoped related
  pages, change budget) and the `Result` schema. Drafts cannot adopt decisions or mark
  evidence reviewed, and every change passes the ordinary proposal checks.

Every `finish` treats the response as untrusted: it must bind the packet ID and input
hash; unknown fields, foreign or fabricated citations, approval, actor and status fields
are rejected. Identical retries return the same receipt; different bytes for a finished
packet conflict. Changed evidence, human notes, contract or policy, and revoked or
expired grants block the handoff and later acceptance. Backup and restore validate the
packet, export, response and receipt bindings; a restore does not restore permission
to export.

## Failure reporting

Tool errors come back as `isError` results with a stable code: `denied` (no grant,
out of scope, local-only, owner-only field), `conflict` (inputs or policy changed,
different retry), `blocked`, or `invalid` (malformed arguments or response). The agent
should report the handoff as pending or blocked with that reason, never claim it was
saved.

## What this does not establish

An `ExportReceipt` records intent and route; it does not prove where or how a model
processed the packet. Mechanical checks confirm locators, quotes and bindings, not that
a claim follows from its evidence. The test suite drives the MCP server with a
synthetic stdio client and deterministic fake responses; it does not exercise a real
agent or model.

The pinned worker container is unrelated to agents: it extracts text, renders HTML
views, inspects PDF metadata and runs isolation probes, with no network or mounts.
Plain `cairn ingest --inline-synthetic` remains a deterministic test shortcut.
