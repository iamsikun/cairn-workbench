# Writing

Owner notes, agent drafts and acceptance take a few commands. The invariants still
hold: sources and notes are immutable to models, every canonical change is a
proposal, and only the owner accepts it through the recoverable writer.

## Your own notes

```text
cairn note "Try the lattice estimator on panel B" --domain research
pbpaste | cairn note - --title "Reading list"
cairn search lattice --scope research
```

A note is a new Markdown file in `vault/inbox/`. Notes you keep in `vault/notes/` work
the same way. Both are searchable immediately with no capture, proposal or approval.
Labels come from front matter (`domain`, `classification`, `processing`,
`compartments`) or the folder (`vault/notes/research/...`). Unlabelled notes outside a
domain folder are `shared`/`restricted`, so only the owner scope sees them.

Notes are not source evidence. They appear only in owner search (`--no-notes` hides
them). They never go into views, context packs or model packets. To cite a note as
evidence, capture it: `cairn capture vault/inbox/NOTE.md --domain research`.
`cairn capture -` captures stdin text as a source.

Editing an existing note still marks pending proposals stale, because notes are
protected inputs. Adding a new note does not.

## Asking your agent to write

In your agent, ask for the page. With Cairn connected over MCP, the agent reads what
it needs (`evidence`, `page`, `context`), writes with its own method (Quill, if
installed) and calls `propose_page` (see [agent integration](agent-integration.md)).

- **New page or revision.** A new page names its type and title. A revision names the
  target and the `base_hash` the agent read; if the page changed since, the proposal
  is refused rather than overwriting the newer version.
- **Feedback.** After `cairn feedback import`, the agent can read the comments with
  `feedback` and revise their target with `propose_page --feedback_id`.
- **Citations.** Each claim cites a source ID and locator; quotes must be exact.
  Cairn maps them to sealed evidence and refuses anything outside the cited sources.
- **What Cairn does.** It preserves the response as a source, formats the record
  itself (status, labels and existing assertions are kept; new claims stay
  unreviewed) and stages a validated proposal.

Cairn does not install or configure Quill. Earlier releases set it up during `init`
and `restore`; those copies are left in place and no longer updated.

## Triage and acceptance

```text
cairn inbox
cairn accept PROPOSAL_ID
cairn accept --all
```

`cairn inbox` lists inbox notes and proposals awaiting acceptance.

`cairn accept` runs these steps for each proposal:

1. It prints each proposal's titles, paths, compact diffs, evidence and review flags.
2. It asks you to type `accept` at your terminal, once for the whole batch. There is
   no `--yes`: an agent's shell has no terminal and cannot accept for you.
3. It validates, approves (acknowledging the shown flags with your statement, by
   default `Owner accepted via cairn accept`) and applies each proposal in order.

Each proposal keeps its own sealed approval and journaled transaction. The batch stops
at the first failure, and earlier proposals stay applied. `cairn recover` finishes an
interrupted apply.

`--all` skips stale proposals. It also skips proposals flagged `sensitive_record`,
`decision_review` or `owner_adoption`; name those explicitly.

`approve` and `apply` remain available for step-by-step review; they also ask for
confirmation at your terminal.
