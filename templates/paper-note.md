# Paper review checklist

Import an owner-selected CSL-JSON export using `cairn bibliography import`. The source
manifest retains the library alias, external item ID, citation key, authors, raw metadata,
and source version/date when available. A year alone is not converted into a full date.

After `cairn ingest`, review the proposal against the preserved evidence:

- Coverage: metadata, abstract, excerpt, or full text actually inspected
- Precise claims and reported results, with exact source locators
- Assumptions, methods, and limitations
- Inferences and hypotheses separated from the author's claims
- Connections and relevance to explicitly selected projects
- Conflicts with earlier versions or other sources

Bibliographic abstracts are `abstract_only`; metadata without an abstract is `excerpt`.
Neither is full paper coverage. A plain BibTeX capture remains unparsed bibliography text
in this release. No live bibliography database or remote URL is opened by the adapter.
