# Writing

Owner notes, Quill drafts and acceptance take a few commands. The invariants still
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

## Asking Quill to write

```text
cairn write begin --new concept --title "Result C" --from SOURCE_ID \
  --instructions "Write a short concept page on the main result" \
  --provider chosen-agent --destination approved-client --shareable --output packet.json
# Quill, using the packet, returns response.json
cairn write finish response.json
```

`--target PAGE_ID` revises an existing page instead. `--feedback FEEDBACK_ID` turns
imported view comments into instructions for their target. `--view VIEW_ID` writes an
unreviewed explanation of a saved view.

- **Packet contents.** The packet holds the instructions, the target or new-record
  slot, keyed evidence from `--from` sources, context pages and the Quill guidance.
- **Instruction labels.** Instructions default to restricted. `--shareable` marks them
  private and cloud-eligible. Export needs the usual `generation` and `client_export`
  grants for the provider and destination.
- **What Quill returns.** Quill sends back a body, an optional title, claims with
  evidence keys and exact quotes, and limitations.
- **What `finish` does.** It checks the response and preserves it as a source. Cairn
  then formats the record itself: status, labels and existing assertions are kept,
  and new claims stay unreviewed. Finally it stages a validated proposal.
- **Installing Quill.** Run `cairn quill install --skills-dir DIR` to install Quill
  with the Cairn writing workflow. An existing Quill skill is preserved.

## Triage and acceptance

```text
cairn inbox
cairn accept PROPOSAL_ID
cairn accept --all
```

`cairn inbox` lists inbox notes, proposals awaiting acceptance and packets without a
response.

`cairn accept` runs these steps for each proposal:

1. It prints each proposal's titles, paths and review flags.
2. It asks for one confirmation for the whole batch. Without a terminal it needs
   `--yes`.
3. It validates, approves (acknowledging the shown flags with your statement, by
   default `Owner accepted via cairn accept`) and applies each proposal in order.

Each proposal keeps its own sealed approval and journaled transaction. The batch stops
at the first failure, and earlier proposals stay applied. `cairn recover` finishes an
interrupted apply.

`--all` skips stale proposals. It also skips proposals flagged `sensitive_record`,
`decision_review` or `owner_adoption`; name those explicitly.

`approve` and `apply` remain available for scripted, step-by-step review.
