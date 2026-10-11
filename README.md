# Cairn

A Markdown research knowledge base that your agent writes while you read.

Read a paper with the Finch skill in Claude Code or Codex. As the discussion progresses,
the agent saves a note for the paper and files it under topics, such as
*Generative recommendation* or *Large recommendation models*. Those topics nest under
broader ones like *Recommendation systems*. Over many sessions and both clients, the notes
grow into a connected network.

```text
Recommendation systems
├── Generative recommendation
│   └── TIGER: Recommender Systems with Generative Retrieval
└── Large recommendation models
    └── Actions Speak Louder than Words: HSTU
```

## Setup

```sh
uv tool install .                       # from this checkout; provides `cairn`
cairn init ~/knowledge                  # create the knowledge base
cairn connect claude -w ~/knowledge     # runs `claude mcp add --scope user cairn ...`
cairn connect codex  -w ~/knowledge     # runs `codex mcp add cairn ...`
```

Keep the knowledge base private and outside this repository. `cairn` refuses a folder
inside any git checkout, though the knowledge base may be its own private git repo.
`--dry-run` prints the registration command without running it, and `--remove`
unregisters it. Finch is installed separately; Cairn does not install or modify it.

## How it works

The knowledge base is a folder of Markdown files, and it opens as an Obsidian vault:

```text
~/knowledge/research/papers/tiger-recommender-systems-with-generative-retrieval.md
~/knowledge/research/topics/generative-recommendation.md
~/knowledge/research/topics/recommendation-systems.md
```

```markdown
---
title: 'TIGER: Recommender Systems with Generative Retrieval'
kind: paper
source: arxiv:2305.05065
topics:
- '[[generative-recommendation]]'
created: '2026-10-11'
updated: '2026-10-11'
---
## Main idea
...
```

- **Notes.** A paper's file name is its slug. One DOI or arXiv id always maps to the same note.
- **Links.** `topics:` puts a paper in a topic, and a topic in its broader topics. A topic
  may have several broader topics. `[[slug]]` in a body links any two notes. Backlinks and
  the topic tree are computed from these links.
- **Saving and linking.** The connected agent calls Cairn's MCP tools. Cairn runs no model
  of its own:
  - `search`, `get_note` and `list_topics` read the knowledge base.
  - `save_reading` saves a paper note and its topics.
  - `save_note` saves a topic or a free-standing note.
- **Topics.** Naming a topic that does not exist creates it. Each save returns
  `suggested_topics`: existing topics whose names appear in the note but are not linked
  yet. The server's instructions tell the agent to save after each substantive step, reuse
  existing topics, add broader topics, and link the suggestions that are real.
- **Safe updates.** Updating a note requires the revision returned by `get_note`. Edits you
  make in an editor, or that another session makes, are never silently overwritten.
- **Collections.** `research` is the default. `finance` and `life` are separate folders.
  Pass `--collection` to `connect` to expose one of them under its own server name. Each
  server reads and writes only its own collection.
- **HTML.** `get_note(html=true)` or `cairn html` writes offline pages to
  `html/<collection>/`. These include a topic-tree index and backlinks. The pages are
  generated from the Markdown and can be deleted at any time.

From the terminal: `cairn search QUERY`, `cairn show NAME`, `cairn topics` and `cairn html`.
These take `-w PATH` or read `$CAIRN_WORKSPACE`.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Tests use temporary folders. Don't point development commands at a real knowledge base,
and don't run `cairn connect` without `--dry-run` during development.

## License

MIT.
