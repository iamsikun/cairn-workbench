# Daily run

Run `cairn-garden daily` for a complete verified pass. The runner records pre-change history,
syncs Zotero, repairs unambiguous links, discovers papers, records metrics, asks the configured
agent to draft the report, validates and saves it, and records post-change history. Only then
are the selected discoveries marked delivered and the daily completion receipt written.

When drafting from `facts.json`, the mechanical work has already happened. Do not rerun it.
Use the snapshot for topics and reading positions. Prefer newly added Zotero items, then catalog,
Aster and arXiv papers that extend an existing reading chain. A paper found by several sources
appears in each block under the same identity; recommend it once. Select up to 5–10 useful papers, skip
`already_in_kb`, and use only papers supplied in the evidence. For each, give a source link and a
specific reason tied to an existing topic. Return `selected` as the exact discovery identities
for the papers recommended. If none are useful, return an empty list and say why.

Include a compact account of confirmed changes, unresolved links, source outages/incomplete
pagination, and pending Zotero writes. If a scheduled write gate is closed, report pending changes rather than claiming synchronization.
Local write failures prevent workflow completion. Put larger organizational questions under “For the weekly review.”
Preserve annotations, attribution, versioned citations and reading positions.

The runner owns persistence in `gardening/daily/garden-digest-YYYY-MM-DD.md` and records the run
in `gardening/index.md`. A rerun appends an update and
preserves previous observations. Discovery and delivery are separate: failed reports do not lose
papers, and undelivered candidates remain in the queue. The weekly window includes daily picks.
