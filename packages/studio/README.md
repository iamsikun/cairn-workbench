# Cairn Studio

A local app for browsing a Cairn knowledge base: a map of topics, papers and ideas, a page
for every note, an idea board, and the history of each idea. It reads the Markdown notes
through `cairn.store` and never writes them. Views refresh while an agent saves, so a
reading session with Finch can be watched as it fills in.

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

The layout is built for a phone first: the tabs sit at the bottom of a narrow screen and in
the top bar of a wide one.

## Design

- One standard-library HTTP server with a read-only JSON API (`server.py`) over views
  computed from the notes on every request (`views.py`). Note shapes follow the MCP tools.
- Server-sent events on `/api/events` report a change when any note file changes.
- The app is plain JavaScript modules with no build step or third-party code; the map is a
  canvas with a small force layout.
- Markdown is rendered on the server with raw HTML escaped. Pages run under a strict Content
  Security Policy, the server binds to 127.0.0.1, and it answers only requests addressed to
  `127.0.0.1` or `localhost`, so other sites in the browser cannot read the notes.

Where this is heading, up to a phone app you can talk to, is in [ROADMAP.md](ROADMAP.md).
