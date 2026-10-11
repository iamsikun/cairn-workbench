# Requested HTML companions

Markdown holds the learning explanation and conclusions. Resources in the same record's
front matter hold diagram steps, tables, figures and deterministic scenario definitions.
They change through the same revision/undo mechanism as the notebook. Math and notation
are preserved as authored Markdown/text; no external typesetting service is called.

Request `get_note` with `format: html`, `cairn get-note ID --html --workspace PATH`, or
`cairn presentation render ID --workspace PATH`. The optional bounded Node adapter reuses
the packaged renderer. It produces self-contained offline HTML, escaped source markup,
embedded figures, captions, readable tables, print styles, narrow layouts and reduced-motion
behavior. Network fetches and source-supplied scripts are not allowed.

Every rendered input is revision-bound. Deterministic companions refresh after saves.
Resources that depend on semantic synthesis declare `synthesis_inputs` (note ID to revision)
and/or `synthesis_markdown_hash` (SHA256 of their notebook body). Changed inputs mark the
view `needs_synthesis`; an agent must revise the visual source before a new render. Failed
refreshes keep the prior HTML and manifest. Content-addressed outputs preserve old bytes.
`--snapshot` creates a view that is not automatically refreshed.

Figure resources use JSON with `mime` and base64 `data`. Diagram resources use a JSON list
of labeled steps. Table resources use Markdown. Scenario resources use JSON with initial
amount, annual contribution, annual rate as a decimal, years and unit. The example model
compounds annually with contributions at year end; it is illustrative, not a forecast.
Controls are temporary. Saving a changed scenario requires an explicit resource save.

Export feedback from the view and import it with
`cairn presentation feedback FILE.json --workspace PATH`. Notebook and figure/diagram
anchors route comments to attributed observations on their originating notebook. Suggested
text remains a suggestion for the connected agent to reconcile. Old view manifests remain
available to bind feedback to the version that was viewed. Reimporting identical feedback
is idempotent.
