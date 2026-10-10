# Reviewing a proposal

`cairn proposal show PROPOSAL_ID --workspace PATH` shows the affected pages, proposal
digest, provider/route, required acknowledgements, current validation result, and diffs
against the current canonical bytes. It also lists cited source dates/versions, declared
extraction coverage, table/image inspection flags, exact locators, and quote checks.
Explicit disputes and supersession links appear with their rationale. Missing dates are
shown as unknown. A quote match proves presence, not entailment or truth.

Add `--markdown` for a Markdown report on stdout. Its evidence entries link to the local
source manifest, original blob, and extraction artifact containing the named locator.
The owner may save that output inside private storage for review; Cairn does not publish
it. Imported titles, HTML, links, terminal controls, and backtick fences are escaped or
kept inside code blocks. The renderer constructs only local links from validated paths
and never fetches a source URL. Retain the report privately because its diff and quotes
can contain the workspace's content.

`--json` retains the original structured proposal format, including its stored diff;
it cannot be combined with `--markdown`. Human-readable reports recompute their diff
from current files so a stale or modified stored diff cannot claim there are no changes.
Changed inputs or a modified diff produce a visible invalid-for-apply status; the proposal
must be regenerated or repaired through the normal workflow. Viewing never grants
approval or records a validation event. A revoked scope blocks the entire report before
revealing titles or text. Unsupported source/locator checks remain visibly unsupported.

After reviewing source support, applicability, conflicts, and any decision or sensitive
interpretation, use the normal `validate`, `approve --statement ... --acknowledge ...`,
and `apply` commands. Approval binds the exact proposal and policy; later changes require
fresh review. A saved report is a snapshot and cannot override later edits or revocation.

A proposal that sets an assertion to `reviewed` or `superseded`, where the current record
does not already hold that state, carries the `verification_change` acknowledgement. A
proposed verification state is the proposer's claim, not an owner review; acknowledge it
only after checking the cited evidence. Owner adoption and receipt next-action updates
use this flag too.
