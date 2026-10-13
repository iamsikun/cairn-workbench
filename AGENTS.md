# Working on Cairn

Cairn has one job. While the owner reads papers with Finch in Claude Code or Codex, or
brainstorms research ideas, it saves notes automatically and connects them into a network
of topics. Keep it minimal.
Before adding a feature, ask whether that workflow needs it. See README.md for the design.

- The code is four modules in `src/cairn/`:
  - `store.py`: notes, links, search and suggestions.
  - `mcp.py`: the stdio server and the agent instructions.
  - `html.py`: optional offline pages.
  - `cli.py`: the command line.
- Markdown files are the only state. Indexes, caches and HTML are derived or absent.
- The MCP tools are search, get_note, list_topics, save_reading, save_idea and save_note.
- Cairn never runs a model. The connected agent writes notes and decides links; Cairn
  stores them and suggests candidate topics.
- Finch is an independent skill. Do not install, vendor or edit it.
- Idea minutes are append-only. Never rewrite or drop earlier entries.
- Never overwrite a note without its current revision. Writes are atomic and stay inside
  the selected collection.
- `cairn connect` delegates to `claude mcp add` / `codex mcp add`. It never edits client
  settings files itself.

Optional tools live in `packages/` as separate packages of one uv workspace. They use the
core through `cairn.store` and never change it; the core never imports them. The rules
above are the core's.

- `packages/catalog` (`cairn-catalog`): the public journal catalog and its offline
  browser. Its data, preferences and generated pages live outside the knowledge base and
  outside this repository; `paths.py` resolves them from the config file or environment.
- The knowledge base holds knowledge only. Code, views, caches, run state and raw evidence
  stay out of it.

Develop with `uv` and synthetic data in temporary folders. Never read a real knowledge
base, home directory or credentials. Never change real client settings: run `connect` only
with `--dry-run`. Never push, publish or add remotes.
Run `uv run pytest` and `uv run ruff check . && uv run ruff format --check .` before
committing. Make small commits.
