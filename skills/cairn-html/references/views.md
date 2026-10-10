# Views and delivery

For a canonical Markdown page or notebook, use MCP `view(record_id=ID, format="html")`.
The destination is fixed by the owner's `--html-root`, never by a model-selected path.
Only this explicit request registers an output. Future accepted changes to the
notebook or its directly linked paper notes refresh it. Other topics appear as
navigation references, without recursive expansion or separate generated files.
Failures leave earlier HTML intact and mark the registration stale. Modified output
files are conflicts; do not overwrite or delete them to force a refresh.

The packet workflow below remains available for historical snapshots; those outputs
are not registered for synchronization.

Cairn supplies fixed project, query, evidence, paper, proposal, catalog and feed
views. Project views preserve decisions, failed approaches and repository state;
paper/feed views separate coverage, analysis, verification and personal reading.
Queries remain extractive unless the owner prepares an explanation packet.

The portable package includes `scripts/render.mjs` and `runtime/application.mjs`.
Given an owner-approved writing packet containing `document`, render its original
knowledge view with an available Node 20+ runtime:

```text
node "<skill directory>/scripts/render.mjs" --input "/reports/approved packet.json" --output "/reports/knowledge.html"
```

On Windows, quote each complete path, for example `"C:\Reports\approved packet.json"`.
The helper takes file arguments; it needs no Bash heredoc, agent environment variable,
network or installation step. Use the runtime already provided by the host. Never
install a runtime or change global configuration as an implicit prerequisite.

The helper renders the packet's existing document. It does not add returned prose
to a managed view. Send writing responses to the owner for Cairn import. Do not
edit evidence, labels, hashes or snapshot fields to make a different document look
like an authorized view. New knowledge needs a newly assembled bundle. Presentation
retries use the same packet and output; do not patch HTML as source tracking.

If browser tooling is available, inspect narrow and desktop widths, evidence
expansion, focus, print and optional controls. Content must remain readable without
JavaScript. Report unexercised browser behavior. Do not claim compatibility with an
agent product merely because it can read this skill.

Files are snapshots. Managed retrieval rechecks authorization; detached copies
cannot enforce later revocation. Deliver only the requested output through the
host's supported artifact/file mechanism, without automatic opening or upload.
