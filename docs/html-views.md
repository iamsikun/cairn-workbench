# HTML knowledge views and writing packets

Cairn can produce offline HTML when the owner explicitly requests it. A page is a
snapshot of authorized records, not another canonical record type. Source, concept,
project, decision, entity and playbook remain the six record types. Viewing and
writing explanations create no approval and change no canonical knowledge.

## Owner commands

Use a reviewed installation for private work. These examples use synthetic paths;
`--inline-synthetic` is available only for synthetic development workspaces. In an
owner installation the renderer runs in the reviewed, network-disabled worker.

```text
cairn context PROJECT_ID --workspace /srv/cairn --scope research --question "What should be tested next?" --format html --output "/srv/reports/project brief.html" --save
cairn query "retrieval coverage" --workspace /srv/cairn --scope research --format html --output /srv/reports/query.html --save-view
cairn evidence SOURCE_ID --workspace /srv/cairn --scope research --format html --output /srv/reports/evidence.html
cairn proposal show PROPOSAL_ID --workspace /srv/cairn --format html --output /srv/reports/review.html
cairn library show PAPER_ID --workspace /srv/cairn --format html --output /srv/reports/paper.html
cairn library export --output /srv/reports/catalog.html --workspace /srv/cairn --format html
cairn feed export /srv/reports/feed.html --workspace /srv/cairn --format html
cairn view save VIEW_ID --workspace /srv/cairn
cairn view render VIEW_ID /srv/reports/revised-presentation.html --workspace /srv/cairn
```

Existing text, JSON, Markdown and Atom interfaces remain available. A destination
alone does not request HTML. Commands return the artifact path, bundle identity and
checksum without opening a browser. Destinations must be outside canonical storage
and public code, with no symlinks. Replacement uses a same-directory temporary file,
private permissions and the existing recoverable file writer. A failed render,
stale input or interrupted replacement preserves the previous deliverable.

A question is part of the protected request. Unlabelled free text defaults to
restricted/local-only. Owners can supply `--question-labels labels.json` on context
or query using Cairn's Labels schema. That explicit classification is an owner
operation, not an instruction from a draft or agent.

## What a view preserves

Project briefs retain the context pack's decisions, failures, next actions,
repository state, coverage and omissions. Queries remain extractive. Evidence uses
stable internal anchors, source IDs, dates, versions, exact locators and expandable
excerpts. Paper views retain inspected-page coverage and separate machine analysis,
verification concerns and personal reading state. Catalog and journal feeds use the
same presentation layer. A feed remains its saved digest, not a live update.

Proposal terminal, Markdown and HTML output consume one review model. It recomputes
the current diff, checks scope and citations, reports exact proposal hashes and
current invalid-for-apply reasons, and distinguishes recorded stage from present
validity. Viewing creates no validation or approval event.

Assembly uses existing scoped readers under their owner locks, with a locked
consistency check around the sequence. The bundle binds question, labels, effective
scope, policy, record/evidence hashes, relevant library/review state, timestamp and
renderer/template identity. The owner renders outside the lock and rechecks relevant
inputs and authorization before delivery. Knowledge changes require new assembly.
Presentation retries reuse the bundle; HTML patching is not version tracking.

Transient bundles and HTML live under private `cache/presentation`. Explicit saving
moves the bundle into durable `receipts/presentation/views`; backup/restore validates
it with related writing and feedback receipts. HTML remains rebuildable. Managed
retrieval rechecks current authorization. `view show --historical` permits changed
inputs but still requires current scope and matching policy; its timestamp describes
a historical snapshot. It never restores a revoked grant. Detached HTML cannot
enforce later revocation and says so on the page.

The worker receives a bounded presentation document, no vault mount, credentials,
Docker socket or network. Templates escape all imported text, including renderer
commands. The Cairn profile does not read user configuration or source files, load
remote assets, check updates, open browsers, or use persistent browser storage.
Only supplied raster bytes with matching hashes and signatures can become assets.
Publication links are navigation, not fetches. The CSP permits only the bundled
script hash, inline styles and embedded raster images; native disclosures and print
styles preserve readability without JavaScript.

## Quill explanation packets

Quill 0.3.0 core and references are packaged from MIT-licensed revision
`d6bc7de15d1779c58286cbdec1a54eec52bdef22`. Jobs embed drafting or editing guidance;
technical guidance is optional. The personal author profile is not applied.

```text
cairn explanation prepare VIEW_ID --workspace /srv/cairn --route cloud --provider chosen-agent --destination approved-client
cairn explanation export WRITING_ID /srv/reports/packet.json --workspace /srv/cairn
cairn explanation import /srv/reports/response.json --workspace /srv/cairn --output /srv/reports/explanation.html
```

Preparation binds the entire request, labels, view, evidence, Quill guidance and
response schema. A custom `--request` defaults to restricted/local-only unless the
owner supplies `--request-labels`. Export requires current `generation` and
`client_export` grants for the provider, destination and complete request. Consent
for paper verification is not reused. Neither preparation nor export calls a model
or activates a subscription. No private export was activated by this implementation.

The agent returns structured prose, permitted kinds, supplied evidence keys and
optional exact quotations. Import checks job identity, hashes, field/size limits,
reference membership, quotation presence and current authorization. These mechanical
checks do not establish entailment or semantic accuracy. Accepted prose is displayed
as **generated, unreviewed interpretation**. A manual packet records unverified
execution; it cannot establish local-only processing. No reviewed local writing
adapter is installed, so that route remains blocked without a cloud fallback.

## Feedback to proposal

Add `--feedback` to an HTML view to offer a bounded JSON download form. It stores
nothing persistently in the browser and sends no request. The owner can then use:

```text
cairn feedback import /srv/reports/cairn-feedback.json --workspace /srv/cairn
cairn feedback prepare FEEDBACK_ID --workspace /srv/cairn --route cloud --provider chosen-agent --destination approved-client
cairn explanation export WRITING_ID /srv/reports/revision.json --workspace /srv/cairn
cairn feedback stage /srv/reports/revision-response.json --workspace /srv/cairn
```

Import preserves feedback as immutable attributed source evidence. Authorship and
approval are explicitly unverified. Repeated imports are idempotent. Comments without
suggested text await action. Preparation selects only authorized managed targets
and binds their base hashes. Source records, human notes and owner catalog metadata
cannot be targets. Returned revisions cannot expand the selected set or citations,
change authoritative status, bypass label inheritance or exceed the change budget.

Staging uses the existing proposal machinery. Stale revisions fail. Nothing becomes
adopted merely because a comment suggests it. The owner must still validate, review,
approve and apply the exact proposal using the established recoverable workflow.

## Portable skill

`skills/cairn-html` follows the [Agent Skills format](https://agentskills.io/specification).
Build `dist/cairn-html.zip` with `python scripts/package_html.py` in the development
container. The ZIP includes the Node renderer, licenses, hashes and pinned Quill
resources. Its core works with any agent that can read packets, write files and run
Node 20+. The owner-exported packet includes a presentation document for portable
rendering; writing responses return to the owner import boundary. Receiving a packet
never grants workspace access. Existing HTML and Quill installations stay unchanged.

Only the actually exercised runtime/agent cases in `acceptance.md` are compatibility
evidence. The package does not claim live validation in every agent product.
