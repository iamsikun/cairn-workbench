# Agent integration

You use Cairn from inside an agent you already run: Claude Code, Codex, Cursor or
another MCP host. The agent calls Cairn; Cairn never launches an agent. The agent
reads scoped material through Cairn's tools and submits its work in one call; Cairn
validates the answer as untrusted input and stages a proposal. Approval and apply stay
with you.

Cairn does not install, edit, vendor or update agent skills. If your agent has Finch or
Quill, it uses them for *how* to read or write. *What* Cairn needs back, and what the
agent may not do, is Cairn's own contract, carried in each `propose_*` tool's
description (`src/cairn/reading/contract.md`, `src/cairn/presentation/contract.md`,
`src/cairn/proposals/contract.md`).

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
   `operations`, `valid_until` and `owner_consent` (equal to the statement). `query` and
   `context` cover read tools; `generation` and `client_export` cover `propose_*`.
   Only records labelled `cloud_eligible` can leave; local-only material is withheld
   from search and refused by every other tool.

2. **Print the registration and sandbox settings.** Cairn prints them; it never edits
   agent settings.

   ```sh
   cairn mcp --print-config --workspace ~/cairn --scope research \
     --provider claude-code --destination https://api.anthropic.com
   ```

   The output contains `claude mcp add cairn -- ...` and `codex mcp add cairn -- ...`
   commands, a Cursor `mcp.json` entry, Claude Code settings for
   `~/.claude/settings.json`, and Codex sandbox guidance.

3. **Optional file capture.** `--capture-root DIR --capture-labels labels.json` lets
   the agent capture files under `DIR` (outside the knowledge base) with labels you
   chose; files elsewhere are refused.

4. **Optional HTML.** `--html-root /srv/synthetic-reports` permits explicit requests
   through `view(record_id=..., format="html")`. The agent chooses a record, not a
   filesystem destination. `query` and `client_export` grants cover the rendered
   material. Outputs are tracked and refresh after accepted Markdown changes.

The launch arguments fix the workspace, scope, provider and destination for the
session. Tools cannot change or widen them.

## Tools

| Tool | What it does |
| --- | --- |
| `search`, `evidence`, `page`, `context` | Scoped reads; `evidence` gives the locators and hashes to cite, `page` gives a page's `base_hash` |
| `view`, `feedback` | Saved view content; explicitly requested canonical HTML; imported feedback |
| `capture` | Capture a file from the capture root and return its evidence |
| `pending`, `proposal_show` | Proposals awaiting your review in this scope, and their details |
| `propose_reading` | Propose an evolving paper note and bounded companion notebook changes together |
| `propose_page` | Propose a new page, a revision (with `base_hash`) or a feedback revision |
| `propose_changes` | Propose pages drafted from one source |
| `propose_explanation` | Keep an unreviewed explanation of a saved view; render it with `cairn view explanation JOB OUTPUT.html` |

Each read writes a receipt under `receipts/agent/` with the hash of what left. Each
`propose_*` call checks the grant for the complete request, seals its inputs (source,
related pages, target version, contract) with an `ExportReceipt`, and validates the
answer in the same step. A retry with the same answer returns the same receipt; a
different answer is a new attempt and a new proposal.

Every answer is untrusted: unknown fields, citations to locators or quotes that do not
exist, owner decisions, reviewed verification and approval, actor or status fields are
rejected. A revision whose `base_hash` no longer matches the page is refused, so an
agent never overwrites a newer version. Changed evidence, human notes or policy and
revoked or expired grants block later acceptance. Backup and restore validate these
bindings; a restore does not restore permission to export.

There is no tool for approval, accept, apply, recovery, policy, backup, restore,
schema, update or editing human notes, and no CLI command for agent packets.

## Paper to notebook

Capture a paper or read its `evidence`. Default identity follows its bytes: renaming
an identical file deduplicates, while unrelated same-named files stay separate.
For revised documents, supply an explicit `identity` and `version` to `capture`;
existing captures retain their historical identity. A capture in a single-project
session inherits that project; multi-project sessions require explicit `project_ids`.

`evidence.paper_notes` gives authorized existing notes and base hashes, including
notes bound to another explicit version of that source. Read the note with `page`,
use `search` for topics, and inspect authorized links/backlinks. A follow-up sends
the existing target and current base hash. Multiple candidate notes require a
target selection; an explicit historical target can become the evolving note.

`propose_reading` preserves each exchange as immutable evidence and stages one
proposal. Its summary retains earlier useful content and answers the current
question. Optional `pages` contain notebook drafts (concept pages), their `key`,
full `body_markdown`, claims, and either a new title or existing target/base hash.
Use `related: ["@topic"]` on the paper and `related: ["@paper", "@broader"]` on a
topic draft. Cairn assigns durable IDs. The default budget is four changed pages.
Companion claims can cite other authorized papers. Topic selection comes from the
host agent; privacy labels stay owner-controlled. There is no classifier service.

The owner sees diffs, evidence and review flags and confirms the combined proposal
once. Accepted Markdown becomes searchable immediately. HTML is generated only when
requested, then maintained as a derivative; see [HTML views](html-views.md).

## Keeping the agent's shell out of owner operations

MCP limits what the agent can do *through Cairn*. An agent that also has a shell runs
as you and could otherwise run owner commands or write the knowledge base directly.
Two layers close that:

- **The agent's sandbox (the real barrier).** Claude Code runs MCP servers outside its
  shell sandbox, so `cairn mcp` keeps working while the agent's shell is confined. The
  printed `claude_code_settings` enable the sandbox, deny writes to the knowledge base
  and Cairn's data directory, and deny `Edit(...)` there plus `cairn` owner commands.
  For Codex, use `sandbox_mode = "workspace-write"` and keep those directories outside
  the workspace and out of `writable_roots`; Codex documents no per-path deny inside a
  writable root, and does not document whether MCP servers run inside its sandbox.
- **Owner terminal confirmation.** `approve`, `accept`, `apply`, policy changes, schema
  apply and `update enable|disable` ask you to type the action at your terminal
  (`/dev/tty`). Agent shells such as Claude Code's have no controlling terminal, so
  they are refused. A determined agent could allocate a terminal; that is why the
  sandbox matters. There is no `--yes`. Synthetic workspaces accept
  `CAIRN_SYNTHETIC_OWNER=1` for tests; a real knowledge base ignores it.

## What this does not establish

An `ExportReceipt` records intent and route; it does not prove where or how a model
processed the material. Mechanical checks confirm locators, quotes and bindings, not
that a claim follows from its evidence. The tests drive the MCP server with a synthetic
stdio client and deterministic answers; no real agent or model was exercised, and the
sandbox settings are printed from the agents' documentation, not tested here.

The pinned worker container is unrelated to agents: it extracts text, renders HTML
views, inspects PDF metadata and runs isolation probes, with no network or mounts.
Plain `cairn ingest --inline-synthetic` remains a deterministic test shortcut.
