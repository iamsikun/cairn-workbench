# Research continuity

Paper reading happens in the owner's agent. With Cairn connected over MCP, a reading
preserves the supplied discussion and stages a validated concept-note proposal before
returning, without a separate save request. [Agent integration](agent-integration.md)
explains the packet boundary, project links and explicit pending status. Owner
approval/apply and adoption of suggestions remain separate operations.

All examples here are synthetic. The owner selects a scope for every research operation.
The worker never receives workspace paths, the global index, or approval/apply authority.

1. `cairn project create TITLE --question TEXT --objective TEXT --constraints TEXT --scope research`
   stages one project and preserves its framing as a source. Review, approve, and apply it.
2. `cairn bibliography import selected.json --library-alias library_demo --project PROJECT_ID --scope research`
   captures an exact export plus independently hashed items. Import is read-only against
   the selected file. Use a stable library alias and stable export IDs. Reimporting an
   unchanged item keeps its source ID even when another item in the export changes.
3. `cairn draft begin SOURCE_ID --scope research --related PROJECT_ID ...` seals a
   drafting packet for the owner's agent; `cairn draft finish` stages its note and
   bounded related updates (the MCP `draft_*` tools do the same). On a synthetic
   workspace, `cairn ingest SOURCE_ID --inline-synthetic` uses the deterministic fake.
4. `cairn receipt import session.json --scope research` preserves the structured session
   receipt and stages project observations plus draft decisions. Its schema is
   `schemas/sessionreceipt-v1.json`. Reported failures are attributed observations, not
   independently proven results. Approval of a receipt does not adopt its suggestions.
5. `cairn decision adopt DECISION_ID --scope research --statement TEXT` stages explicit
   owner adoption. The normal owner approval and apply steps remain required. A context
   pack presents a current decision only while its exact bytes have an intact adoption
   and apply receipt; a direct editor change makes that proof unavailable.
6. `cairn context PROJECT_ID --scope research --question TEXT --budget 12000 --json`
   returns a bounded JSON pack. `--save` stores it under private receipts. The pack includes
   provenance and hashes, a conservative UTF-8 byte estimate, and omitted-item counts.
   Whole items are removed when trimming; retained items keep their references. Project
   framing cannot be silently truncated. Unknown question labels are restricted/local-only.

Every command above also needs `--workspace /path/to/selected-workspace`, or the
owner-controlled `CAIRN_WORKSPACE` variable. `--inline-synthetic` on project creation,
receipt import, and ingestion is only valid for a synthetic workspace; installed private
extraction requires the pinned worker. Drafting with the owner's agent is cloud
processing and needs an explicit grant.

The bibliography adapter reads the `id`, `citation-key`, `author`, `issued`, `abstract`,
and `version` fields of [CSL-JSON input data](https://github.com/citation-style-language/schema/blob/master/schemas/input/csl-data.json).
It retains other JSON metadata without interpreting it, rather than claiming complete
CSL validation. IDs must be nonempty strings or integers. Dates with year/month precision
remain in their original metadata. BibTeX parsing and live-library integration are deferred.

`cairn repository inspect ROOT --alias repo_demo --run-id RUN_ID` reads an explicitly
selected Git checkout and emits a binding to include in a session receipt. The fingerprint
covers the index and tracked/non-ignored untracked regular files, including deletions.
Ignored datasets and submodules require separate owner run/manifest identifiers; they
are not claimed to be verified. Symlinks, oversized files, or unsupported entries make
verification unavailable. No project code, external diff, text conversion, hook, or filter
is run. Use `cairn context ... --repository-root ROOT` to compare a recorded binding.
A match describes the scan instant; a later code change can still make a saved pack stale.

## Manual separate-session acceptance

The owner chose a manual agent session for the M2 semantic check. No second agent has
been run automatically, and the deterministic tests do not satisfy that check.

The checked-in `examples/continuity/context.json` is generated from a real synthetic
capture/propose/approve/apply sequence, with one explicitly adopted decision and a
recorded failed approach. `owner-evidence.json` and `verification.json` let the owner
inspect the provenance and verify the artifact hash; they are not additional agent context.
For a new trial, generate a separate pack using
`python scripts/prepare_continuity.py --output /tmp/new-manual-handoff` inside the
documented development container. Do not overwrite the retained pack: the recorded
manual response and evaluation are bound to its exact IDs and hash.

For the manual trial:

1. Open a fresh agent session with no prior project history or repository access. Give it
   only `context.json` and this request: “Continue the study with the next useful step.
   Explain the evidence behind your choice and return a structured session receipt.
   Do not claim an experiment ran unless you actually ran it.”
2. Record the client/model, exact input hash, response, latency, and actual reported cost
   if available. Keep the rubric outside the agent's initial context.
3. Inspect whether the agent uses the saved requirement for source IDs, versions/hashes,
   and locators in its proposed artifact; avoids repeating title-only evidence retrieval;
   carries citations to the prior decision/failure; and distinguishes suggested work from
   measured results and owner decisions. Mere keyword mentions are insufficient.
4. Save an owner evaluation with pass/fail/unclear and concrete examples. Import the new
   receipt only after inspection through the normal review path. Report the manual gate
   as pending until that evidence exists. The public fixture uses only synthetic data.

The current protocol tests exercise receipt roles, draft/adopted separation, changed
decision bytes, stale repository bindings, denied-scope citations, strict JSON inputs,
and whole-item budget trimming. They establish those mechanics only.

## Recorded manual result

The owner supplied a response from **GPT 6 Astra Light**, with **7 seconds** reported
generation time, and an **unclear** verdict because the context was unfamiliar. The
implementation assistant assessed the response as a **pass for the brief's narrow M2
continuity requirement**. The owner's verdict remains unchanged and is not approval
to adopt the proposed baseline or activate a private workspace.

| Criterion | Observation |
| --- | --- |
| Uses the recorded decision | Specifies three stable fixture IDs, version 1, exact UTF-8 bodies, SHA-256 computation, matching quotes, and code-point offsets as its output contract. Hashes are explicitly uncomputed. |
| Avoids the failed approach | Searches scoped source bodies and returns exact evidence/provenance instead of title-only results. The explanation connects this choice to the saved failure. |
| Cites decision/failure | Links the context pack, gives its matching context ID, and names `current_decisions` and `failed_approaches`. These are resolvable section-level citations, not full durable evidence references. |
| Separates design, results and authority | Marks execution pending, experiments empty, results unknown, and new decisions empty. Does not claim independent reproduction or owner adoption. |

The [supplied response](../examples/continuity/session-beta-response.md) retains the
prose, table formatting, and JSON, with only the host-specific link destination replaced
by a relative link for public-fixture privacy. The
[reported receipt](../examples/continuity/session-beta-reported-receipt.json) is valid
JSON but **fails Cairn's receipt schema**. The test asked for a structured receipt without
supplying that schema; this is an integration-format limitation, not failed continuity.

The [normalized receipt](../examples/continuity/session-beta-normalized.json) is a separate
reviewer-authored derivative. It preserves the response as an assistant message, maps
design/limitations into the schema, and resolves references from the named pack sections.
Those added IDs/references are not credited to the second agent. It passes schema
validation; no canonical import/apply or decision adoption was performed.

The [machine-readable review](../examples/continuity/manual-evaluation.json) records the
owner and assessor verdicts separately, all artifact hashes, original schema errors,
and verification of the input pack's 11 citation occurrences. Cost/tokens are unknown.
Client/model and time are owner-reported; external input bytes, session isolation, and
network activity were not independently observed. One synthetic design response proves
the observed continuity behavior only; it does not establish general model quality,
retrieval performance, or private-runtime readiness.
