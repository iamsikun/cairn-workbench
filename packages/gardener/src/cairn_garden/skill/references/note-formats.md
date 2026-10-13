# Note formats

Both notes are kind `note`, live in `research/notes/`, and list `[[research-catalogs]]` as topic.

## Daily digest

Title `Garden digest YYYY-MM-DD`.

```markdown
# Garden digest 2026-10-14

## New papers for you
1. **Title** (Venue or arXiv, date) — [doi or arXiv](url) · [Zotero](zotero://…) if in Zotero
   Why: one line tied to [[existing-topic]].
…

## Upkeep
- Links fixed: 4 notes (local PDF paths → arXiv + Zotero).
- Open issues: 2 unresolved local references (listed in the weekly review), 0 broken links.

## Pick up where you left off
- [[attention-is-all-you-need]] — reading position: …

## For the weekly review
- (optional) anything larger noticed today
```

## Weekly checklist

Title `Garden weekly YYYY-Www`.

```markdown
# Garden weekly 2026-W42

Tick items to approve them; they are applied at the next run or when you say "apply garden proposals".

## New topics worth reading
- [ ] **N1** Speculative decoding (under [[autoregressive-decoding]]) — why … Seeds: [Title](url) (2023); … <!-- action: {"op":"topic", …} -->

## Links
- [ ] **L1** [[gqa-…]] ↔ [[deepseek-v2-…]] — GQA and MLA both shrink the KV cache … <!-- action: {"op":"link","from":"…","to":"…","reason":"…","both":true} -->

## Topic tree
## Missing papers
## Missing ideas and open questions
## Consolidation and synthesis
## Storage and resources
## HTML views
## Memory
## Health
| metric | week ago | now |
|---|---|---|
```

Keep notes short: one or two lines per item. Order sections by usefulness to the user; new
topics come first.
