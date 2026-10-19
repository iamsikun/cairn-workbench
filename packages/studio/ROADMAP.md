# Roadmap: from Studio to a phone app

## The goal

A phone app (iOS and Android) for the knowledge base that you can **examine** and **talk
to**:

- **Examine.** See the network of topics, papers and ideas as a picture, open any note,
  follow its links, and see how each research idea developed over time.
- **Talk.** Ask about what you have read, resume an idea, or think something through on the
  go. The agent searches the notes and saves new ones and new minutes, just as it does in
  Claude Code or Codex today.

Everything below are steps toward that app. Each step is useful by itself.

## Principles

These follow from Cairn's design and do not change along the way:

- **Markdown is the only state.** Every view is computed from the notes. Nothing the app
  shows is stored anywhere else, and the knowledge base still opens in Obsidian.
- **Cairn runs no model.** Talking is done by a connected agent (the Claude app, Claude
  Code, Codex), which uses Cairn's tools. Cairn stores and suggests; the agent writes.
- **The core stays minimal.** Interfaces are optional packages that use the core through
  `cairn.store` and never change it.
- **Private by default.** The notes are private research. Anything reachable beyond
  localhost needs real authentication and is a deliberate step, not a side effect.
- **Phone-first.** Every view is designed for a phone screen first and widened for a
  desktop, so the same code serves both.
- **Read first, write carefully.** Agents and editors stay the writers until a write path
  exists that keeps the guarantees: the current revision, append-only minutes, and the
  user's decisions attributed to the user.

## Core functionality

| Area | What it does | First step |
| --- | --- | --- |
| Map | The topic hierarchy and links as an interactive network; focus a note's neighbourhood; filter by kind and idea status | 1 |
| Paper pages | The rendered note, its topics as trails up the hierarchy, backlinks, papers that share its topics | 1 |
| Topic pages | Explanation, broader and narrower topics, papers and ideas filed under it | 1 |
| Idea board | Ideas by status (seed → developed), next action, last discussed, flags stale ideas | 1 |
| Idea history | The current account beside a timeline of the minutes, coloured by attribution (user, agent, source), with status changes marked | 1 |
| Recent | What was read, filed or discussed most recently | 1 |
| Search | Keyword search across notes, the same ranking as the `search` tool | 1 |
| Live updates | Views refresh as an agent saves, so a reading session can be watched as it fills in | 1 |
| Catalog | The journal catalog inside the app, with papers already in the knowledge base marked | 2 |
| Talk | Conversation with an agent that uses Cairn's tools, from the phone | 3 |
| Anywhere | The app on the phone without the Mac, working offline from the private repo | 4 |
| Store app | Installable iOS and Android builds, notifications for the gardener's digests | 5 |
| Edits from the app | A few deliberate changes, such as an idea's status or next action | 6 |

## Steps

### 1. Studio v1: a local, read-only app

`packages/studio` (`cairn-studio`). `cairn-studio serve --open` starts a localhost server
that reads the knowledge base through `cairn.store` and serves a single-page app.

- Views: Recent, Map, Ideas, Search, and a page for every note (paper, topic, idea, note).
- A JSON API whose answers mirror the MCP tools (`search`, `get_note`, `list_topics`) plus
  the derived views (graph, idea board, parsed minutes). Later clients use the same shapes.
- Server-sent events when a note changes on disk, so views refresh while an agent saves.
- No build step and no third-party frontend code: plain JS modules, the map drawn on a
  canvas with a small force layout. Markdown is rendered on the server with raw HTML
  escaped, and the page runs under a strict Content Security Policy.
- Bound to 127.0.0.1, with requests for any other host name refused. It never writes.

**Done when** a knowledge base with a few hundred notes is pleasant to browse on a desktop
and in a phone-sized window, and a note saved by an agent shows up without a reload.

### 2. The catalog inside the Studio

If `cairn-catalog` is installed, the Studio serves the catalog's browser and API under
`/catalog`, so one app covers both and `cairn-catalog serve` is no longer needed day to
day. Catalog papers already in the knowledge base are marked "in KB", matched by DOI or
arXiv id. The catalog's data stays in its own folder, outside the knowledge base.

### 3. Talk from the phone: a remote Cairn server

A separate package exposes Cairn's six tools and the same agent instructions over MCP's HTTP
transport, with authentication. Added as a custom connector in Claude, it lets the Claude
app on iOS and Android search the notes, resume ideas and save minutes. No app of our own
is needed to start talking.

- Decision needed: where the always-on part runs. A small cloud host works while the Mac
  sleeps; the Mac behind a tunnel keeps the notes at home but must stay on.
- Writes from two places (the phone's agent and the Mac) go through the same revision check;
  if the knowledge base is synced by git, the remote server commits and pushes each save and
  refuses one that would overwrite a newer note.
- To check: how much of Finch's reading behaviour the Claude mobile app supports. The MCP
  instructions already carry the saving rules.

### 4. The Studio on the phone

The Studio becomes an installable web app (home-screen icon, full screen, offline cache).
It reads the notes from the private GitHub repository through the GitHub API with a
read-only token, or from the remote server of step 3, and keeps a local copy for offline
reading. The views and the API shapes from step 1 carry over unchanged.

### 5. Store apps

The same web code wrapped with Capacitor into iOS and Android builds: an icon in the store,
secure storage for the token, share-sheet import of a paper link, and push notifications
for the gardener's daily digest and weekly review.

### 6. Edits and conversation inside the app (only where steps 3–5 leave gaps)

- A few edits from the app, such as an idea's status or next action, saved with the note's
  current revision and recorded as a minute attributed to **User:**.
- A "resume in Claude" action that opens a conversation about the note on screen.
- A conversation built into the app (the app calls a model with Cairn's tools) only if the
  Claude app with the connector proves too limited. It would need its own API key and would
  repeat the reading and saving behaviour the skills and MCP instructions already provide.

## Open decisions

- Where the always-on part runs (step 3).
- Whether phone access reads from GitHub directly, from the remote server, or both (step 4).
- Which edits, if any, the app should make itself (step 6).
