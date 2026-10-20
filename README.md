# Cairn

A Markdown research knowledge base that your agent writes while you read.

Read a paper with the Finch skill in Claude Code or Codex. As the discussion progresses,
the agent saves a note for the paper and files it under topics, such as
*Generative recommendation* or *Large recommendation models*. Those topics nest under
broader ones like *Recommendation systems*. Over many sessions and both clients, the notes
grow into a connected network.

Brainstorming works the same way. When you develop a research idea with the agent, it
saves an idea note, files it under topics and links it to papers. Later sessions resume
it, and its dated minutes record how the idea developed.

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
unregisters it.

### Skills

Cairn is used with three independent skills, each in its own repository:
[Finch](https://github.com/iamsikun/finch) reads papers,
[Quill](https://github.com/iamsikun/quill) drafts and revises them, and
[Aster](https://github.com/iamsikun/aster) scouts what is new and hands picked items to
Finch. None of them knows about Cairn; its MCP instructions connect them to your notes: a
scouted item is checked against them, a reading is saved, and Quill drafts from them.

```sh
cairn skills install          # Finch, Quill and Aster at the versions this release pins, plus kb-gardener
cairn skills                  # installed and pinned versions, and each agent's link
cairn skills remove aster     # uninstall one; `install` again after upgrading Cairn
```

`install` runs each skill's own installer (`curl … | bash` the first time) with its daily
self-update off, so upgrading Cairn moves all of them to tested versions together. It also
runs `cairn-garden skill` when the gardener is installed. `--dry-run` prints the commands.

## How it works

The knowledge base is a folder of Markdown files, and it opens as an Obsidian vault:

```text
~/knowledge/research/papers/tiger-recommender-systems-with-generative-retrieval.md
~/knowledge/research/topics/generative-recommendation.md
~/knowledge/research/topics/recommendation-systems.md
~/knowledge/research/ideation/semantic-ids-for-cold-start-ads.md
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

- **Notes.** A note's file name is its slug. One DOI or arXiv id always maps to the same
  note. Renaming a note keeps its slug and adds the old title to `aliases`, so links still
  work.
- **Links.** `topics:` puts a paper in a topic, and a topic in its broader topics. A topic
  may have several broader topics. `[[slug]]` in a body links any two notes. Backlinks and
  the topic tree are computed from these links.
- **Saving and linking.** The connected agent calls Cairn's MCP tools. Cairn runs no model
  of its own:
  - `search`, `get_note` and `list_topics` read the knowledge base.
  - `save_reading` saves a paper note and its topics.
  - `save_idea` saves a research idea and adds an entry to its minutes.
  - `save_note` saves a topic or a free-standing note.
- **Topics.** Naming a topic that does not exist creates it. Each save returns
  `suggested_topics`: existing topics whose names appear in the note but are not linked
  yet. The server's instructions tell the agent to save after each substantive step, reuse
  existing topics, add broader topics, and link the suggestions that are real.
- **Ideas.** An idea note has two parts. Above `## Minutes` is its current account, which
  the agent revises: question, hypothesis, related work, evidence and open questions.
  Below it are dated minutes. Cairn only ever appends to these, and an entry that is
  already there is not added twice. Each line is attributed to the user, the agent or a
  source. `status` is one of `seed`, `exploring`, `testing`, `parked` and `developed`, and
  a change records its reason in the minutes. `next_action` names the next useful step.
  `last_discussed` and `last_review` are dated by Cairn. A save marked as a review, such
  as a maintenance pass, cannot change the status.

  ```markdown
  ---
  title: Semantic IDs for cold-start ads
  kind: idea
  status: exploring
  next_action: Find an ads dataset with cold-start items
  last_discussed: '2026-10-13'
  topics:
  - '[[generative-recommendation]]'
  ---
  **Question:** do semantic IDs help cold-start ads? Builds on [[tiger-recommender-systems-with-generative-retrieval]].

  ## Minutes

  ### 2026-10-13

  Status: seed → exploring.

  **User:** cold-start ads might benefit most; worth a pilot.
  ```
- **Safe updates.** Updating a note requires the revision returned by `get_note`. Edits you
  make in an editor, or that another session makes, are never silently overwritten.
- **Collections.** `research` is the default. `finance` and `life` are separate folders.
  Pass `--collection` to `connect` to expose one of them under its own server name. Each
  server reads and writes only its own collection.
- **HTML.** `get_note(html=true)` or `cairn html` writes offline pages to
  `html/<collection>/`. These include a topic-tree index and backlinks. The pages are
  generated from the Markdown and can be deleted at any time.

From the terminal: `cairn search [QUERY] [--kind idea] [--status testing]`, `cairn show NAME`, `cairn topics` and `cairn html`.
These take `-w PATH` or read `$CAIRN_WORKSPACE`.

## Optional tools

`packages/` holds optional tools that work on a knowledge base without changing the core:

- [`cairn-catalog`](packages/catalog/README.md): a local catalog of public journal
  metadata with an offline browser. Import selected papers into the knowledge base.
- [`cairn-garden`](packages/gardener/README.md): daily digests and weekly reviews of the
  knowledge base, drafted by your own agent, with proposals you approve. It runs on your Mac
  or, for a knowledge base kept in a private GitHub repository, on GitHub Actions.
- [`cairn-studio`](packages/studio/README.md): a local, read-only app for browsing the
  knowledge base: a map of topics, papers and ideas, note pages, an idea board and each
  idea's minutes as a timeline, refreshed live while an agent saves. With `cairn-catalog`
  installed it also serves the journal catalog, marking papers already in the knowledge base.
  Its [roadmap](packages/studio/ROADMAP.md) leads to a phone app.

Their data, state and settings live outside the knowledge base, configured in
`~/.config/cairn-workbench/config.toml`. The one exception is the gardener's readable
reports, in the knowledge base's `gardening/` folder beside the collections. Cairn's own
tools never read that folder.

If GitHub Actions gardens your private KB, add local Git sync during setup:

```sh
cairn-garden sync setup --dry-run       # preview the existing repo/remote and the job
cairn-garden sync setup                 # 07:15 and 13:15, around the cloud daily run
cairn-garden sync status
```

This optional macOS job commits local edits, merges cloud changes and pushes, with
conflicts left for review. It catches up after sleep and runs without Codex open.
See [local sync setup and controls](packages/gardener/docs/local-sync.md).

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
