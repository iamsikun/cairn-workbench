# Personal domain workflows

These workflows use the same scoped sources, isolated extraction, sealed proposal,
owner approval, and recoverable application as research. This implementation is tested
only with synthetic data. Private activation remains a separate release gate.

## Finance

`cairn finance import statement.json --scope finance --workspace WORKSPACE` stages a
dated account snapshot from `schemas/financialsnapshot-v1.json`. The selected JSON export
is preserved exactly. Values use decimal strings, owner/account aliases, an as-of date,
and explicit units/currency. Float inputs and duplicate keys are rejected. The synthetic
`templates/finance-snapshot.json` demonstrates the format. The import does not infer
values from a PDF, model response, or a wiki paragraph.

Snapshot proposals require sensitive-record review. Validation compares every structured
amount, owner/account, date, period, assertion, and snapshot title to preserved source
observations. Free-form snapshot commentary is rejected; put interpretation in a separately
sourced concept or decision. A source match establishes faithful copying, not the truth
or completeness of an external statement. Keep the authoritative statement/export.

`cairn finance calculate SOURCE_ID --key cash_available --key cash_pending --operation sum
--scope finance --workspace WORKSPACE --json` computes an exact result from the structured
source. `difference` uses exactly two operands in their supplied order. Inputs must have
the same owner, account, date, unit, and currency; duplicate source values are rejected.
Calculations fail rather than silently round beyond supported precision. `--save` retains
an auditable receipt containing operands, result, algorithm version, and evidence locators.
The CLI does not read canonical wiki amounts as accounting inputs or execute financial actions.

For selected text sources, `cairn finance note SOURCE_ID --category educational --scope finance`
stages exact source quotations. `--category official_rule` additionally requires `--as-of
YYYY-MM-DD` or `--tax-year YEAR`; include `--jurisdiction TEXT` when applicable. Dates supplied
here are owner metadata and require review. The deterministic renderer is not an adviser
or a model synthesis step. Record conflicting/superseded assertions with explicit links and
rationales; old sources remain intact. The finance note template covers the required fields.

## Life

`cairn life import dossier.json --scope life --workspace WORKSPACE` stages an entity hub
from `schemas/lifedossier-v1.json`. The dossier references already captured and extracted
authoritative documents. All references must be authorized and hash/locator valid. Service
events and terms carry dates and their evidence; revised dossiers preserve previous events,
documents, owner text, and decisions. A stable entity alias identifies the hub independently
of its title. `review_date` is metadata only. No calendar, reminder, messaging, or task API
is called. Restricted or cross-domain supporting sources require corresponding owner labels;
the default importer currently rejects a dossier that would weaken them.

## Evidence review

`cairn evidence SOURCE_ID --locator 'line 1' --scope DOMAIN --workspace WORKSPACE` shows the
exact extracted passage, source/evidence hashes, source version/date, method/version, and
coverage. Omit `--locator` to view the complete available extraction. It does not fetch
remote links or claim to inspect PDF images/tables. `--json` returns structured metadata.

Readable search output includes dates, versions, applicability periods, verification, and
recorded supersession/dispute links. A summary whose cited evidence is unavailable in the
selected scope is withheld, including its title and ranking contribution. Text matching
and reference validation do not establish entailment. Use owner review for interpretations,
conflicts, and high-stakes conclusions.
