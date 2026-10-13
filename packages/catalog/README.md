# cairn-catalog

A local catalog of public journal metadata, with an offline browser, that feeds a Cairn
knowledge base. It harvests Crossref, OpenAlex and selected publisher archives for the
journals in [`journals.json`](src/cairn_catalog/assets/journals.json), builds SQLite,
JSONL and a native Cairn library, and lets you import selected papers into your
knowledge base for reading. It is optional; the Cairn core does not need it.

## Setup

```sh
uv tool install ./packages/catalog      # from the workbench checkout; provides `cairn-catalog`
```

The catalog keeps its data outside the knowledge base. Configure the locations in
`~/.config/cairn-workbench/config.toml` (environment variables take precedence):

```toml
workspace = "~/knowledge"        # $CAIRN_WORKSPACE: the knowledge base papers are imported into
collection = "research"          # $CAIRN_COLLECTION
[catalog]
data_dir = "~/.local/share/cairn-workbench/catalog"            # $CAIRN_CATALOG_DIR (default)
preferences = "~/.config/cairn-workbench/catalog-preferences.yaml"  # $CAIRN_CATALOG_PREFERENCES (default)
```

`cairn-catalog paths` prints the locations in use. Build a new catalog with
`cairn-catalog harvest` then `cairn-catalog build`; afterwards `cairn-catalog update`
refreshes it incrementally.

Open `catalog.html` in the data folder in a current Safari, Chrome, Edge or Firefox browser. The homepage is What’s New: a configurable recent-publication feed. The catalog works offline without a server, loading companion data files only as needed. Keep `catalog.html`, `search.html`, `authors.html`, `institutions.html`, `catalog-personal.js`, the referenced `catalog-assets-*` folder, and `cairn-library/` together. Copy the folder rather than a single HTML file. Reopen it after an update to load the new snapshot.

To edit your follows, keywords, topics and field tiers from the pages, open the catalog through the **catalog app**: run `cairn-catalog serve --open`, which opens `http://127.0.0.1:8766/catalog.html`. The pages read the same offline data files; the app only adds saving to the preferences file. Stop it with Ctrl-C.

SQLite remains the efficient query store for scripts and larger searches. The app also serves a paginated SQLite browser at `http://127.0.0.1:8766/explore.html`; opening the saved HTML does not require it.

The build retrieves public historical metadata without a publication-year cutoff. Crossref result sets are fully traversed. OpenAlex supplements the metadata; traversals that exceed its free daily budget are explicitly marked incomplete in `COVERAGE.md`. Verified fetched pages remain usable as supplementary evidence, and later refreshes resume missing historical work. AER also uses publisher-supplied RePEc contents and the public AEA issue index. JMLR uses its official volume TOCs and article metadata pages, retaining the original HTML. This is **not a certified complete historical census**.

## Data folder

Everything below is generated in the data folder. The package source is in
`src/cairn_catalog/`; browser source files are in `src/cairn_catalog/assets/`.

| Path | Purpose |
|---|---|
| `catalog.sqlite` | Relational metadata, ordered authors, DOI aliases, and full-text search |
| `papers.jsonl` | One normalized, deduplicated entry per line, with complete field provenance |
| `issues.jsonl` | One publication unit per line: an issue, or an annual/continuous volume where appropriate |
| `journals.json` | Snapshot of the packaged registry used for this edition: names, aliases, ISSNs, publisher admission rules, start years, source IDs and public archives |
| `cairn-library/` | A complete native Cairn workspace with `.cairn` and `research/{papers,topics,notes}` |
| `coverage.json` | Field coverage, source traversal checkpoints and known gaps |
| `validation.json` | Results of database, native-format and link verification |
| `raw/` | Compressed selected API responses and public RePEc contents, with retrieval timestamps |
| `raw/repec/abstract-supplements.jsonl` | AER abstract metadata parsed from cataloged RePEc detail pages |
| `raw/semantic_scholar/abstracts.jsonl` | DOI-backed supplemental abstracts from Semantic Scholar |
| `raw/linked_pages/abstract-supplements.jsonl` | Reviewed abstracts parsed from other cataloged public URLs |
| `raw/{linked_pages,repec,semantic_scholar}/*recovery-report.json` | Retrieval counts, matching rules and skipped records |
| `catalog.html` | What’s New front page: For you, one tile per field, and a drill-down per field; rolling three-month window by default |
| `catalog-personal.js` | Your preferences as the small script the pages read; `cairn-catalog personalize` and the app regenerate it |
| `insights` bundle | Per-field active authors, new names, institution counts and rising title terms (lazily loaded) |
| `first-seen.jsonl` | Persistent ledger of the snapshot in which each paper first entered the catalog (drives “new since last visit”) |
| `search.html` | Historical paper and issue search; no unrestricted initial listing |
| `authors.html`, `institutions.html` | Independent directories and publication filters |
| `catalog-assets-*` | Immutable edition of summary, search, detail and entity bundles |
| `explore.html` | With `cairn-catalog serve`, the catalog app: serves the pages, saves preferences (`POST /api/preferences`, same-origin only) and a paginated browser on a read-only SQLite API |
| `author-*.jsonl`, `authorships.jsonl` | Portable author identities, source identifiers, aliases and ordered paper credits |
| `institution-*.jsonl`, `affiliations.jsonl` | Portable organization identities, aliases and paper-level affiliation evidence |
| `publication-events.jsonl` | Separate print-preferred publication, online and print dates with conservative precision bounds |
| `entity-coverage.json` | Author/institution coverage, conflicts and evidence matching statistics |

The preferences file (outside the data folder) holds field/journal tiers, For you keywords, Cairn topic use, followed people and institutions. The catalog app edits it from the pages, keeping comments and the previous version with a `.bak` suffix. Fields and their default tiers come from the packaged `fields.json`.

## Front page, fields and For you

The What’s New front page groups the 38 journals into seven fields (`fields.json`). Each field has a tier:

- **core** fields (Economics, Business, Statistics & ML, Probability by default) get a full tile with counts, new issues and up to five headlines;
- **skim** fields get a compact tile;
- **mute** fields are listed in one line and left out of For you.

Click a tile to open that field: its journals, the issues represented in the window, and papers grouped under each issue or “Online first”. Rows are compact by default (title, first authors, journal, date); **Compact rows** switches to the full cards. Each field also shows title terms that are rising compared with the previous twelve months.

**New since last visit.** A dot marks papers that entered the catalog after you last caught up with that field. Your first visit starts caught up. Use **Mark caught up** (one field, or all fields on the front page) when you have read through. **New since last visit** filters the page to those papers. The state lives in this browser’s storage; it is based on `first-seen.jsonl`, not on publication dates, so papers that arrive late with an older online date still count as new.

**For you** lists papers from the past twelve months that match your keywords, your Cairn topics (`<collection>/topics/*.md`, titles and aliases; broad parent topics and aliases under four characters are skipped), followed people, or followed institutions. A followed person scores 3, an institution 2, each keyword or topic 1; skim fields count half, and name-only matches on unlinked bylines count half and are marked unverified.

**Keywords & topics**, below the For you list, shows your keywords and every Cairn topic with its aliases, its matches over the past twelve months and whether it is used (broad topics and excluded topics show what they would add). In the catalog app you can add or remove keywords and switch topics on or off there; a field page has a **Show as** menu for its tier. Each change is saved to the preferences file and the matches update in about a second; the first change after starting the app takes a few seconds.

Without the app, edit the preferences file, then run:

```sh
cairn-catalog personalize
```

and reload the page. No catalog rebuild is needed. The script reports match counts and any names that need attention. A name shared by several catalog identities is not pooled: the Authors page lists the candidates to choose from (or add the right one(s) as `ids: [...]`). The weekly updater reruns personalization; a broken preferences file is reported as a warning and does not block the refresh.

**Authors** and **Institutions** open on a landing page; their tab always returns to it. Searching lists the matching identities, and opening one shows its profile. *Following* shows your followed people or institutions with their papers from the past twelve months; in the catalog app you can follow by name, choose among namesakes, and unfollow there. Below it, *Who’s active* ranks source-identified authors by papers in a field (past 3 months or past year), with an eight-quarter bar strip and their latest paper, and lists *New names*: authors whose first paper in these journals falls in the period. *Institutions by field* ranks identified institutions by papers with an affiliated author, with the change from the previous period and the field’s affiliation coverage. Author and institution profiles have a **Follow** button that saves to the preferences file in the catalog app; in the offline edition it remembers an author in this browser and shows the line to add to the preferences file. Profiles open with papers per year, journals and frequent coauthors; date basis, stage and uncertain-date filters are under *More filters*.

## Cairn compatibility

Every exported entry is a normal Cairn paper note: Markdown with a YAML header containing `title`, `kind: paper`, normalized `source: doi:...` (or the source URL when no DOI is available), `authors`, `year`, `url`, `topics`, `aliases`, `created` and `updated`. Additional bibliographic fields are retained. Abstracts appear in the body. Journal topics and issue notes are connected with Cairn `[[wikilinks]]`.

The full catalog is a separate native workspace because the installed Cairn implementation reads every note when searching or resolving links. Keeping the full historical collection outside the active collection avoids slowing ordinary reading-note operations. The active research collection has a `journal-catalog` entry point. Any selected paper can be brought into the active collection with the command below; existing reading notes and unrelated metadata are preserved.

Do not point the active MCP configuration at the full historical library without considering the cost of scanning all its notes. Use the SQLite index for broad discovery and then import selected papers for reading.

## Search and import

Import commands write into the configured workspace and collection:

```sh
cairn-catalog search '"causal inference"' --journal mnsc --limit 10
cairn-catalog search --journal aer --year 2026
cairn-catalog search --journal jpe --missing-abstract --limit 10
cairn-catalog import-paper 10.1287/mnsc.22.7.788
```

Search expressions use SQLite FTS5 syntax. The import command accepts a DOI, DOI URL, catalog ID or exported paper slug, and uses Cairn's native save implementation with revision checks.

## Authors, institutions and publication periods

`COVERAGE.md` and `entity-coverage.json` report how many authors, institutions and authorships are source-identified, and how many credits and labels remain unresolved or conflicting. Unresolved entries are visible but do not constitute verified complete bibliographies.

```sh
cairn-catalog entities search author 'John List'
cairn-catalog entities search institution 'University of Chicago'
cairn-catalog entities publications author orcid:0000-0002-1740-3848 --period 2026-Q3
cairn-catalog entities publications institution ror:024mw5h28 --period last-quarter --as-of 2026-10-11
cairn-catalog entities publications institution ror:024mw5h28 --period 2026-Q3 --basis online --include-uncertain
cairn-catalog entities import author orcid:0000-0002-1740-3848
cairn-catalog entities import institution ror:024mw5h28
```

Use the search results to choose an explicit entity ID. A name that resolves to multiple identities requires selection, rather than silently pooling people. Author identity uses ORCID/OpenAlex IDs linked by source evidence on the same paper. Source author lists are aligned to catalog credits using exact names or compatible names within the same paper. Different ORCIDs are not merged; conflicting credits are isolated and retained in `identity_conflicts`. OpenAlex's own identity assignments can contain errors, and an identifier does not certify a personal bibliography. Institution identity prefers ROR, then OpenAlex; an unstructured label maps to an identified entity only when its normalized full name matches a unique known entity. Department/address variants remain separate unless a source provides an identifier. No fuzzy institution assignment is applied.

**Institution queries use each paper's affiliations**, not an author's current employer. One paper counts once per institution even if several coauthors share it. Results cover the catalog journals, not publications elsewhere. Missing or unresolved affiliations can undercount institutional results. Entries include non-article journal material, and the conservative entry classification is not a verified research-paper classification.

The UI stores a publication period as inclusive **From / Through** dates. Both are editable, including open-ended ranges. The range helper can fill them using a calendar window (starting year, quarter and any positive number of years or quarters) or a rolling window (length, unit and ending date). Quick buttons fill last quarter, this year, past five years or past ten years; they do not restrict which dates can be searched. A calendar five-year span beginning in 2020 is 2020-01-01 through 2024-12-31. A rolling five-year window ending 2026-10-11 is 2021-10-12 through 2026-10-11. The same filter applies to papers, author publications and institution publications.

The CLI accepts `all`, `YYYY-Q1` through `YYYY-Q4`, `YYYY`, `YYYY:YYYY`, `last-N-years`, `last-N-quarters`, and explicit date bounds:

```sh
cairn-catalog entities publications institution ror:024mw5h28 --period 2026
cairn-catalog entities publications author orcid:0000-0002-1740-3848 --period 2020:2024
cairn-catalog entities publications institution ror:024mw5h28 --period last-10-years
cairn-catalog entities publications institution ror:024mw5h28 --start-date 2023-04-17 --end-date 2026-08-03
```

`last-quarter` is the previous completed calendar quarter in America/Chicago time unless `--as-of` supplies an anchor. `--basis issue` uses the selected publication date, preferring print but falling back to another source publication date; it is not always a verified issue release date. `online` and `print` query their separately recorded dates without fallback.

Partial dates are intervals. A month or year is certain when the whole interval fits inside the chosen range. Provider-inferred dates are conservatively represented by their known year. Overlapping intervals that extend beyond the range are counted as uncertain and excluded unless `--include-uncertain` is enabled. Entries without the selected date basis cannot be assigned to a bounded period; their all-year count is reported separately.

The all-year view and imported bibliography include every linked paper, including undated entries. There is no quarter-membership test for this view; the selected date basis controls the displayed dates and ordering.

Profiles import as normal Cairn `kind: note` files with the entity ID, identity status, Research catalogs topic and links to native paper notes. Repeated imports preserve existing personal notes. For questions in Cairn, follow `[[author-institution-catalog]]` and query the SQLite-backed CLI/API. JSONL exports and affiliation evidence retain the graph independently of the browser.

The localhost API supports `/api/entities`, `/api/publications`, `/api/papers`, `/api/issues` and `/api/paper`. Entity and paper result sets are paginated with `limit` and `offset`; abstracts are requested separately. API responses and the saved browser are snapshots rebuilt by the weekly metadata updater.

## Author navigation and alphabetical browsing

Every author name in paper result bylines opens the source-linked author profile. The same links are available in author and institution publication lists. Navigation uses the ordered authorship ID, so namesakes remain separate. The generic “article or other” label is hidden in the HTML; informative review, correction and front/back-matter labels remain.

Author search results sort by surname A–Z (the full directory is no longer listed on the page), with given names and identity ID breaking ties. Recorded family names in paper metadata take precedence, including compound surnames. Older records without a structured family name use a display-name inference that handles comma notation, common surname particles and suffixes. Inferred sort names do not merge or certify identities. Paper bylines keep their published author order.

`author_directory` is a derived SQLite table with an index on its surname sort key; `author-directory.jsonl` retains the family/given names, sort keys and provenance. It is rebuilt automatically with the author graph during weekly updates. To refresh only this derived index, run `cairn-catalog author-directory`; then rebuild the saved HTML with `cairn-catalog browser`. The native paper files and source authorship ordering are unaffected by display changes.

## Forthcoming and issue assignment

Use the **Publication stage** filter in Search → Advanced filters, or Stage on an author/institution profile. It applies to papers and to author/institution publication lists, alongside journal and date filters:

- **Assigned to a volume or issue:** both volume and issue are recorded, or a volume is recorded for a journal whose publication unit is a volume. JMLR, Acta Numerica and Publications Mathématiques de l'IHÉS use volume-level indexing without fabricated issue numbers.
- **Forthcoming / online first:** an online publication date is recorded, with no print date and no complete volume/issue assignment. This is an inference from source metadata, not a verified live publisher status.
- **All awaiting issue assignment:** every entry lacking complete volume/issue information, including online-first entries and other metadata gaps.
- **Other missing issue details:** incomplete bibliography without enough evidence for the online-first category. Historical records are not called forthcoming merely because their issue details are missing.

Lists and paper details display the stage and its evidence instead of `Vol. ? · Issue ?`. A volume already known for an unassigned paper is still shown. Online-first papers retain their actual online publication date; no anticipated print date or issue is invented. A bounded print-date search will omit them when no print date is recorded; choose online dates to search their online publication period.

`publication_status` and `publication_status_evidence` are retained in normalized JSONL, SQLite and native Cairn Markdown. The weekly updater derives stage again from the latest accumulated source records. When volume and issue appear, the same DOI-backed entry is assigned to that issue, disappears from the awaiting/online-first filters and retains its catalog ID, Cairn link and original online date. This lifecycle is covered by a test using before/after provider records.

```sh
cairn-catalog entities publications institution ror:024mw5h28 --period all --stage online_first
```

The stage filter accepts `all`, `issue_assigned`, `online_first`, `pending` and `unassigned` in the CLI and local API. Metadata can lag publisher assignment; [INFORMS describes its Articles in Advance lifecycle](https://pubsonline.informs.org/authorportal/articles-in-advance).

## Database schema

`journals` contains canonical journal identities; `issues` contains volume/issue/date and coverage status; `papers` contains title, journal, issue, authors JSON, publication dates and their precision, DOI, abstract, abstract source and the full normalized JSON record. `authors` preserves author order and available ORCID/affiliation information. `paper_dois` retains alternate registrations. `paper_search` indexes titles, authors, abstracts and journal names.

`author_entities`, `author_identifiers`, `author_aliases` and `authorships` form the author graph. `institution_entities`, `institution_aliases` and `affiliations` form the institution graph, with each affiliation attached to an ordered authorship and its source evidence. `publication_events` stores each date basis and bounds. `entity_names` is a derived FTS5 name index. Indexes support DOI, paper-date, author-to-paper and institution-to-paper lookups. SQL is the operational query store; JSONL is the portable exchange layer; Markdown is the Cairn reading layer; HTML is a view.

Example issue contents:

```sql
SELECT p.title, p.date, p.doi, p.authors_json, p.abstract
FROM papers AS p
WHERE p.issue_id = 'aer:v116:i10'
ORDER BY CAST(p.pages AS INTEGER), p.title;
```

Example full-text discovery:

```sql
SELECT p.title, p.year, p.doi
FROM paper_search AS s
JOIN papers AS p ON p.id = s.paper_id
WHERE paper_search MATCH '"causal inference"';
```

## Journal identity and quarantine

OpenAlex journal/source buckets can mix journals with the same name, book chapters, repository versions and working papers. A bucket assignment is never sufficient membership evidence. Before deduplication, `journal_membership.py` checks the actual Crossref record's ISSNs and publisher/archival registrar against the target journal. AER also accepts the exact publisher-supplied RePEc series. JMLR accepts records parsed from its explicitly configured public archive, retaining the original HTML. OpenAlex records can enrich a confirmed paper through its DOI or an exact title + volume + issue + first-page citation; a working-paper or book DOI cannot become a journal DOI alias. Unsupported source records remain in `quarantine.jsonl` and the raw cache, outside the main paper, issue, author and institution indexes. Removed generated Markdown is retained under `retired/` and in the previous refresh edition.

`journal_membership` travels with each normalized record and native Markdown header. **Publisher/archival deposit confirmation is separate from individual publisher archive verification.** Exact DOI checks in public publisher TOCs/article pages, and directly parsed JMLR publisher archive records, receive `archive_status: confirmed`; the checked URL and date are saved in `raw/membership/archive-evidence.json`. The paper dialog states when an archive listing has not been checked. `journal-membership-report.json` reports admission, quarantine and archive-check coverage. The historical archive has not been exhaustively audited. An inaccessible or missing page is an unresolved verification problem, not proof of non-membership. Title language is never a membership filter.

The Russian-language 2016 record `https://openalex.org/W2994574218` was confirmed to belong to the Financial University's *Управленческие науки / Management Science*, not INFORMS. Its publisher-supplied [RePEc citation](https://ideas.repec.org/a/scn/mngsci/y2016i4p53-61.html) and the [INFORMS April 2016 TOC](https://pubsonline.informs.org/toc/mnsc/62/4) document the correction.

## Metadata conventions

- Schema version is `1.0`; JSONL is UTF-8 with one JSON object per line. Missing scalars are `null`; missing lists are empty arrays.
- Primary identity is the normalized DOI, or the OpenAlex/RePEc source identifier when no DOI exists. DOI aliases are kept, with publisher registrations preferred to `10.2307` registrations when matching bibliography confirms duplication.
- Issue identity is `journal_id:vVOLUME:iISSUE`. Volume-based publications use `journal_id:vVOLUME`. Annals of Mathematics adds `:sfirst` or `:ssecond` before the volume because its numbering restarted in 1899. Unassigned entries remain searchable with `issue_id: null`.
- `date` favors print publication for issue indexing. Crossref year-only and month-only dates remain partial ISO dates; no fictitious day is added. `published_print` and `published_online` are separate. OpenAlex-only dates are flagged `provider_day_unverified` because the provider may infer components.
- `abstract_status` distinguishes source-provided abstracts from unavailable ones. Abstracts are source text, never generated summaries. Crossref and OpenAlex are the primary harvests; cataloged AER/RePEc detail pages, reviewed public linked pages, and DOI-backed Semantic Scholar records fill selected gaps only when titles match exactly. `field_sources` and `sources` explain where fields came from; raw responses and recovery reports permit auditing.
- Counts include catalog entries such as articles, reviews, corrections and front/back matter. Conservative labels are not a verified classification of research papers.

The UI calls `date` **Publication date (print preferred)**. It selects Crossref `published-print`, then `published`, `issued`, or `published-online`; other providers fill gaps. It is not the date this catalog collected the record. The snapshot and each source's `retrieved_at` remain separate. OpenAlex dates marked `provider_day_unverified` display only the publication year, with month/day unverified, and queries treat them as a full-year interval rather than January 1.

## What’s New and navigation

What’s New defaults to the past three calendar months through today in America/Chicago, inclusive (13 July–12 October on 12 October 2026). The window selector also offers one/six/twelve months, the previous completed calendar quarter, and custom dates. The remembered choice and URL parameters preserve context; Search and each entity destination have separate filters. The homepage groups matching journals alphabetically by display name, with total counts and ten newest papers per journal. Each journal pages independently. Title and stable identity break date ties. A month-only date follows known days within that month; year-only and unverified provider dates do not invent a day or month.

The catalog navigation, publication window, custom-date controls, date range, snapshot date and result count stay visible in a compact sticky header. The journal index is a 240 px sticky sidebar at widths of 1,000 px and above, and a sticky, collapsed **Journals (N)** disclosure on smaller screens. Links focus the section heading below the controls, retain all results and pagination, and respect reduced-motion preferences; the index highlights the section in view while scrolling. Scroll offsets and the sidebar height adapt to the header's measured height, including custom-date forms and narrow or short viewports.

Hash parameters preserve this context: `offset_mnsc=10` (and equivalent stable journal IDs) and `section=mnsc`. Home always uses journal grouping; old `group` and global `offset` parameters are removed when reopening the homepage. Changing the publication window clears pages and the section target. Reload, Back and paper details retain the per-journal pages. The recent API accepts `group_by=journal` and a JSON `journal_offsets` object, grouping the complete eligible feed before independently slicing each journal. Offline and SQLite editions use the same eligibility and ordering rules.

The feed uses the earliest known publication event across recorded online, print and fallback publication metadata. Earliest-event lower and upper bounds are the minima across those source intervals. Issue assignment alone does not reset an online-first paper’s recency, and later digitization does not promote an old print paper. Only dates wholly inside the selected window enter the feed. A link opens Search with overlapping uncertain dates included. Known front/back matter, book reviews and correction/retraction notices are omitted from the main feed; notices have a separate Search link. `article_or_other` remains a conservative source classification, not a certification of original research.

The snapshot date is separate from publication dates. A snapshot older than a week shows a freshness notice. Search begins without results until text or a substantive filter is supplied. It supports journal/issue browsing, dates, stages, entry types and exact primary/alternate DOI lookup. Advanced date bases include earliest known, print-preferred, online and print. Author/institution profiles retain independent date and stage filters, ordered by the selected publication basis.

The browser build writes a small shell and immutable, versioned companion files. Recent summaries are partitioned by month, with separate yearly shards for uncertain dates; abstracts and provenance by a hash of stable paper identity; full-text postings by token hash. List bylines show the first ten authors and a remaining-author count; paper details keep the complete ordered byline. List summaries are columnar (one array per field, repeated strings stored once) and split into chunks of at most 5,000 papers that never span journals, ordered by date and labelled with their date span. A search opens only the chunks that can match: the selected journal, an overlapping publication period, or the papers found by the token index or a DOI shard. An author or institution profile opens only the chunks holding its papers. Author and institution directories are stored in display order in chunks of 2,000 identities; a directory page opens one chunk, identifier lookups open one hashed shard, and name searches open the word-prefix shards for the typed words. Abstract text is loaded only when a paper is opened. Classic script bundles allow local-file loading without fetch requests. No external fonts, scripts or network connection are needed by the offline edition.

Edit the source template, stylesheet and UI/runtime scripts in `src/cairn_catalog/assets/`, and `discovery.py`; regenerate entrypoints with `cairn-catalog browser`. Do not edit generated HTML or versioned assets. Each build, and each published weekly refresh, deletes superseded `catalog-assets-*` editions and the retired `catalog-data.js` export. A tab left open on the previous edition must be reopened, and HTML kept in `.refreshes/<run>/previous/` no longer has its asset folder.

## Weekly refresh and validation

Run the updater weekly, for example from a scheduler before the gardener's weekly review, or manually at any time:

```sh
cairn-catalog update
```

The updater retrieves Crossref records indexed since the last successful refresh with a fourteen-day overlap, capturing new records and corrections regardless of publication year. It revisits the last two publication years in completed OpenAlex baselines for recent author, affiliation and abstract metadata. Incomplete historical baselines resume first and remain explicitly incomplete until the full traversal succeeds; provider cooldowns retain the checkpoint. OpenAlex's updated-date filter requires premium access; this public-source workflow does **not** claim to refresh all historical OpenAlex-only corrections. An existing `OPENALEX_API_KEY` environment variable can be used; it is never written to cached requests. AER's RePEc contents are refreshed, and the AEA issue index is revisited; an unavailable AEA index is retained with a warning. JMLR's archive index and homepage are checked for new volumes; the latest two volume TOCs are refreshed and previously captured article pages are reused.

Provider records are replaced by source ID; unchanged records keep their previous retrieval dates. Deletions from provider feeds are not inferred. Public-source coverage remains incomplete. Each run stages the accumulated raw metadata, rebuilds normalized JSONL, SQLite and the author/institution graph, regenerates native Cairn paper/issue/topic notes, validates Cairn parsing and links, and builds and checks the saved HTML. Only a completed build is published. Immutable browser assets publish before all five HTML entrypoints, with `catalog.html` last. Previous asset directories are retained for already-open offline pages. Local API requests carry an edition ID and ask the user to reload after a refresh instead of mixing editions. Failed fetches or validation preserve the previous edition and checkpoint. An interrupted publication is rolled back at the beginning of the next run. A lock prevents overlapping refreshes.

`update-state.json` records the last successful checkpoint; `update-report.json` records results and warnings. Recovery editions remain in `.refreshes/<run>/previous/`; these retained snapshots consume disk space and are not automatically pruned. Existing generated note creation dates are preserved. Only the marked status blocks in the two active catalog entrypoints are updated. Personal reading notes and imported author/institution profiles retain their bodies; the generated historical library is metadata-only.

Rebuild from cached sources or run the verification tools:

```sh
cairn-catalog update --rebuild-only
cairn-catalog verify
uv run pytest packages/catalog/tests       # from the workbench checkout
```

The offline verification runs the generated script-bundle loader with network access disabled and compares 37 queries with SQLite, covering the recent feed, journal counts and independent pagination, first-publication dates, DOI lookup, publication stages, quarter/year/custom ranges, rolling five/ten-year windows, online/print dates, uncertainty, ordering and abstract detail access. It checks that Home loads only recent summaries, opening a paper loads only a detail bundle, and the default homepage stays under a 1 MB initial asset budget. Fresh-cache checks also bound the bytes opened by a journal search, a DOI lookup, an all-journal quarter search, the first author-directory page, an author name search and an institution profile, and `tests/test_bundle_parts.js` checks chunk selection on a small fixture. Browser UI checks cover the localhost edition; the automated browser tool does not permit direct `file://` previews. Node.js is needed for this verification; opening the HTML only needs a current browser. `cairn-catalog validate` parses all generated paper and issue notes with the installed Cairn runtime, checks internal links and database integrity. Snapshot dates are set automatically in America/Chicago time. Full historical reharvest commands (`cairn-catalog harvest --refresh`) remain available when a complete provider reconciliation is needed.

## Public sources

- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [OpenAlex API](https://help.openalex.org/api/)
- [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/api-docs/)
- [OpenAlex authorships and paper-level affiliations](https://help.openalex.org/data/authorships/)
- [ROR organization identifiers](https://ror.org/registry/)
- [AER publisher issue archive](https://www.aeaweb.org/journals/aer/issues)
- [Publisher-supplied AER RePEc contents](https://ideas.repec.org/s/aea/aecrev.html)

Public metadata access does not imply public-domain article full text. Source-specific abstract and metadata rights remain with their respective owners; available Crossref license records and original provenance are retained. This catalog contains bibliographic metadata and available abstracts, without article full texts.
