# Cairn Studio

A local app for browsing a Cairn knowledge base: a map of topics, papers and ideas, a page
for every note, an idea board, and the history of each idea. It reads the Markdown notes
through `cairn.store` and never writes them. Views refresh while an agent saves, so a
reading session with Finch can be watched as it fills in. If the journal catalog is
installed, the Studio serves it too.

```sh
uv tool install ./packages/studio        # from this checkout; provides `cairn-studio`
cairn-studio serve --open                # http://127.0.0.1:8767/
cairn-studio serve -w ~/knowledge --collection finance --port 8800
```

The knowledge base is `-w`, else `$CAIRN_WORKSPACE`, else `workspace` in
`~/.config/cairn-workbench/config.toml`. The collection works the same way with
`--collection`, `$CAIRN_COLLECTION` and `collection`; collections that hold notes can also
be switched in the app.

## Views

- **Recent.** Counts, the ideas in motion, and the latest notes by day.
- **Map.** Every note as a network. Topics are large circles, papers dots, ideas diamonds
  and free notes squares; solid lines file a note under a topic, dashed lines are `[[links]]`.
  Tap a note to see its neighbourhood, filter by kind or idea status, find a note by name.
  A note saved while the map is open is ringed when it appears.
- **Ideas.** A board by status, from seed to developed, with each idea's next action and when
  it was last discussed. Ideas quiet for more than 30 days are flagged.
- **Note pages.** The rendered note with its topics as trails up the hierarchy, its fields,
  backlinks and the papers and ideas it shares topics with. A topic lists its narrower topics
  and what is filed under it. An idea shows its status, next action and current account beside
  its minutes as a timeline, each entry marked as the user's, an agent's suggestion, a source
  or a status change.
- **Search.** The same ranking as the `search` tool, filtered by kind.
- **Catalog.** Shown when the journal catalog is installed (below).

The layout is built for a phone first: the tabs sit at the bottom of a narrow screen and in
the top bar of a wide one.

## The journal catalog

If [`cairn-catalog`](../catalog/README.md) is installed in the same environment and its pages
are built, the Studio serves them under `/catalog/`, so `cairn-catalog serve` is no longer
needed:

```sh
uv tool install './packages/studio[catalog]'   # or add cairn-catalog to the same environment
```

- What's New, Search, Authors and Institutions work as in the catalog app, and so does the
  SQLite browser (`/catalog/explore.html`). Changes to keywords, topics, follows and field
  tiers are saved to the catalog's preferences file. That is the catalog's only write; the
  Studio never writes notes.
- Catalog papers that already have a paper note in the collection are marked **In KB**,
  matched by DOI or arXiv id (an arXiv DOI such as `10.48550/arXiv.2305.05065` matches
  `arxiv:2305.05065`). A paper without a DOI, such as a JMLR article, matches a note whose
  `source` or `url` is its page on the publisher's site, with either scheme and with or
  without `www.`. The mark links to the note in the Studio. The paper's detail view links to
  the note as well.
- A paper note's page says whether the journal catalog holds its paper, with a link to it
  there, or that it does not: conference and arXiv-only papers are not in the journal
  catalog, so they never show as **In KB**.
- The catalog's data stays in its own folder, outside the knowledge base. Only the pages,
  their edition's bundles, the guides and the library notes are served; the database and raw
  evidence are not.
- The marks need catalog pages built by this version: run `cairn-catalog browser` once, or
  wait for the next `cairn-catalog update`.

## Design

- One standard-library HTTP server with a read-only JSON API (`server.py`) over views
  computed from the notes on every request (`views.py`). Note shapes follow the MCP tools.
- Server-sent events on `/api/events` report a change when any note file changes.
- The app is plain JavaScript modules with no build step or third-party code; the map is a
  canvas with a small force layout.
- Markdown is rendered on the server with raw HTML escaped. Pages run under a strict Content
  Security Policy, the server binds to 127.0.0.1, and it answers only requests addressed to
  `127.0.0.1` or `localhost`, so other sites in the browser cannot read the notes.
- The catalog pages carry their edition's settings in one inline script. Each page is served
  with a policy that allows exactly that script by its hash. Preference changes are accepted
  only from the Studio's own origin (`catalog.py`).

Where this is heading, up to a phone app you can talk to, is in [ROADMAP.md](ROADMAP.md).
