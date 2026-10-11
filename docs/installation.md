# Install and connect

Install the locally built wheel with Python 3.12 or later, for example `uv tool install
/path/to/cairn_workbench-0.4.0-py3-none-any.whl`. Initialization and ordinary saves need
neither Docker nor Node. Node 20 or later is optional and needed only for requested HTML.
Finch and Quill remain independently installed skills in the user's agent.

```sh
cairn init /synthetic/knowledge
cairn connect codex --workspace /synthetic/knowledge
# Or use the same knowledge base from Claude Code:
cairn connect claude --workspace /synthetic/knowledge
cairn connect codex --workspace /synthetic/knowledge --check
```

These are illustrative paths. The knowledge base must be outside a development checkout.
For contributor trials, add `--synthetic` to init and pass a synthetic `--settings-home`
to connect. Never run contributor code against actual settings or a private knowledge base.

Connections register a local stdio server using Codex's `[mcp_servers.NAME]` in
`.codex/config.toml`, or Claude Code's user-scope `mcpServers` in `.claude.json`.
Names include a workspace/collection hash. Only owned entries are replaced or removed;
unrelated settings survive. Launch arguments fix the workspace and collection. Restart
or reconnect the client after changing registration. Use `--repair` after interruption
or deliberate changes to the owned entry, and `--disconnect` to remove it. Ambiguous
or unmarked settings are preserved for manual reconciliation.

`--check` verifies registration against the expected command and arguments. It reports
`client_trial: unverified`; it does not claim that a signed-in client loaded the server.
The MCP initialize response carries Cairn's own persistent reading/writing instructions.
No global skill or agent-instruction file is installed or modified.

Client registration formats were checked against the official
[Codex MCP documentation](https://developers.openai.com/codex/mcp/) and
[Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

# Work from the agent

The six operations are capture, search, get_note, list_topics, save_reading, and save_note.
Start by searching and retrieving existing notes. Finch guides paper reading; Quill guides
substantial notebook prose. The agent saves checkpoints and reports returned IDs/revisions.
If either skill is missing, the instructions say so and retain the same evidence/save
contract. Cairn neither launches a model nor installs or updates skills.

The default collection is research. Register another connection with `--collection finance`
(or life/shared) to select it separately. Collections restrict Cairn tools, including
backlinks and HTML; they cannot restrict an agent's independent filesystem access.

# CLI equivalents

```sh
cairn capture doi:10.9999/synthetic --workspace /synthetic/knowledge
cairn capture /synthetic/paper.pdf --identity doi:10.9999/synthetic --workspace /synthetic/knowledge
cairn save-reading /synthetic/checkpoint.json --workspace /synthetic/knowledge
cairn save-note /synthetic/notebook.json --workspace /synthetic/knowledge
cairn search recommendation --workspace /synthetic/knowledge
cairn list-topics --workspace /synthetic/knowledge
cairn get-note concept_example --workspace /synthetic/knowledge
cairn recent --workspace /synthetic/knowledge
```

Save JSON follows the exported schemas in `schemas/`. `operation_key` identifies the exact
request, and existing targets require `expected_revision` from get_note. Retry an interrupted
request without changing either. A reading can include ready topic changes atomically.
`source_id` can bind an already captured source; paper identity must agree. Supplied PDFs
are retained before optional bounded local extraction. URL/DOI registration does not fetch
remote content. Missing authors, coverage or extraction are not invented.

Markdown front matter stores stable IDs, source versions, explained relationships, aliases,
attributed observations and editable diagram/table/figure/scenario resources. Human
observations are append-only through saves; append a correction instead of replacing them.
A save never makes a scientific claim verified or a decision adopted.

See [recovery](recovery.md), [presentation](notebook-html.md), and
[migration](migration.md). Older reviewed-runtime instructions remain in
[the historical installation guide](legacy/installation-v3.md).
