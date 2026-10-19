# Working on Cairn

Cairn has one job. While the owner reads papers with Finch in Claude Code or Codex, or
brainstorms research ideas, it saves notes automatically and connects them into a network
of topics. Keep it minimal.
Before adding a feature, ask whether that workflow needs it. See README.md for the design.

- The code is five modules in `src/cairn/`:
  - `store.py`: notes, links, search and suggestions.
  - `mcp.py`: the stdio server and the agent instructions.
  - `html.py`: optional offline pages.
  - `cli.py`: the command line.
  - `skills.py`: the pinned skills and `cairn skills`.
- Markdown files are the only state. Indexes, caches and HTML are derived or absent.
- The MCP tools are search, get_note, list_topics, save_reading, save_idea and save_note.
- Cairn never runs a model. The connected agent writes notes and decides links; Cairn
  stores them and suggests candidate topics.
- Finch (reading), Quill (writing) and Aster (scouting) are independent skills in their own
  repositories. They never name Cairn or the workbench (Aster may hand off to Finch and
  Quill); the workbench connects them to the knowledge base. `cairn skills` installs each through its own `install.sh` at the version `PINS` in
  `skills.py` names, with its self-update off; bump a pin only after testing that release.
  How they use the knowledge base lives in the MCP instructions in `mcp.py`.
  Never vendor or edit them from here. Run `cairn skills install` only with `--dry-run`.
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
- `packages/gardener` (`cairn-garden`): daily and weekly gardening and the `kb-gardener`
  skill. Unlike the core, it may launch the user's own `claude` or `codex` CLI to draft
  reports. Its state, logs and note history live in the state folder, never in the
  knowledge base. Keep `bridge/` byte-identical unless a new Zotero extension is intended:
  any change requires reinstalling the extension in Zotero.
- `packages/studio` (`cairn-studio`): a localhost app for browsing the knowledge base. It
  only reads, binds to 127.0.0.1 and answers only localhost requests. Its frontend has no
  build step and no third-party code. Where it is heading is in `packages/studio/ROADMAP.md`.
- The knowledge base holds knowledge, plus the gardener's readable reports in `gardening/`
  beside the collections. Code, views, caches, run state and raw evidence stay out of it. The
  core never reads `gardening/`.
- The gardener's GitHub Actions support is `.github/workflows/garden.yml`, a reusable
  workflow that a private knowledge base calls, plus `cairn-garden ci`. It is not this
  repository's CI.

Develop with `uv` and synthetic data in temporary folders. Never read a real knowledge
base, home directory or credentials. Never change real client settings: run `connect` only
with `--dry-run`. Never push, publish or add remotes.
Run `uv run pytest` and `uv run ruff check . && uv run ruff format --check .` before
committing. Make small commits.
