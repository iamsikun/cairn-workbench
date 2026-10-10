# Paper review checklist

Import an owner-selected CSL-JSON export using `cairn bibliography import`. The source
manifest retains the library alias, external item ID, citation key, authors, raw metadata,
and source version/date when available. A year alone is not converted into a full date.

Paper readings follow Finch. After `cairn ingest`, a library reading, or a Finch handoff,
review the proposal against the preserved evidence using Finch's own terms:

- Coverage: metadata, abstract, excerpt, or full text actually inspected, and the version read
- Claim ledger: each central claim with its exact source locator and the conditions and
  scope (population, assumptions, regime, uncertainty) that make it true
- Intellectual status: inherited, modified, newly established, authors' interpretation, or
  assistant's inference; only what the paper itself reports is a `reported_result`
- Four checks: reference existence, passage support, scope fidelity, scientific warrant
- Unknowns: "not reported" kept separate from "not done", with what would resolve each
- Connections to explicitly selected projects, labeled as the assistant's inference
- Conflicts with earlier versions, the supplement, or other sources

Cairn checks locators and exact quotes mechanically. Passage support, scope fidelity and
scientific warrant remain the reviewer's judgment.

Bibliographic abstracts are `abstract_only`; metadata without an abstract is `excerpt`.
Neither is full paper coverage. A plain BibTeX capture remains unparsed bibliography text
in this release. No live bibliography database or remote URL is opened by the adapter.
