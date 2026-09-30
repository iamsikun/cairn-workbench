# Acceptance evidence

Implementation is in progress. A checked item requires an executed test or inspected
artifact, not just code presence. Private activation and M4 are outside this goal.

| Stage | Status | Remaining |
| --- | --- | --- |
| M0 | Passed reference acceptance | 24 tests, lint, strict typing, 13 isolation checks |
| M1 | Passed reference acceptance | 48 tests, installed worker protocols, both isolation profiles |
| M2 | Mechanics implemented; manual semantic gate pending | Separate-session continuity evaluation chosen by owner |
| M3 | In progress | Domains, restore, and route audit pass; release/migration/evaluation audit remains |

The brief's hard gates will be mapped to named tests as implementation proceeds.

M0 evidence collected by `bash scripts/check.sh` in the reference Linux container on
the macOS Docker host: **24 tests passed**, Ruff passed, strict mypy passed (16 files),
and **13 process-level isolation checks passed**.

- `test_foundations.py`: record round trips, deterministic sets, traversal, symlink and
  hard-link access, special files, case/Unicode collisions, root overlap, unsafe YAML,
  scope widening, confidentiality/processing inheritance, and cloud denial.
- `test_provider.py`: deterministic extractive fake; injected source remains data;
  job/result serialization; pinned, no-mount worker command; subprocess wire protocol.
- `test_schema_exports.py`: generated schema parity.
- `scripts/isolation_probe.py`: all 13 checks passed with a real unmounted synthetic
  host canary. Canonical/policy/approval writes, outbound TCP, DNS, and hostile child
  operations were denied. No Docker socket, host home, or forwarded credentials existed.

These checks cover a defined threat corpus. They do not prove semantic truth, universal
container security, or private-runtime readiness.

M1 core evidence: **44 cumulative tests passed**, Ruff passed, strict mypy passed
(29 source files), using the isolated development profile with public source mounted.
The later installed M1 acceptance run below supersedes this initial core run.

| Requirement | Current named evidence |
| --- | --- |
| Preserve source/human bytes; no duplicate import churn | `test_capture_extract_apply_preserve_and_deduplicate` |
| Revised-source lineage and version conflicts | `test_revisions_and_declared_version_conflicts` |
| Retryable extraction failures preserve original capture | `test_failed_extraction_preserves_capture` |
| Assistant recommendations do not authorize adoption | `test_conversation_roles_remain_data` |
| Fabricated quote and denied-scope rejection | `test_quotes_scope_and_source_hash_are_validated` |
| Exact approval binding and intervening owner edits | `test_approval_tamper_and_owner_edits_are_rejected` |
| Real termination halfway through a two-file bundle | `test_real_process_crash_recovery` (six boundaries) |
| Recovery preserves unexpected owner bytes | `test_recovery_preserves_unexpected_owner_bytes` |
| Scoped titles, counts/ranking, and backlinks | `test_scoped_search_no_counts_titles_or_ranking_leaks`, `test_restricted_backlinks_are_omitted` |
| Two-character Chinese and bilingual aliases; cache deletion | `test_bilingual_short_query_and_cache_rebuild` |
| Text and evidence-blob restore; hostile archives | `test_restore_text_blobs_and_evidence`, `test_archive_traversal_and_hash_tamper_rejected` |
| CLI capture through review/apply/search | `test_cli_full_owner_workflow` |
| Source summary plus bounded project update | `test_two_file_update_is_reviewable` |

Installed M1 evidence from `bash scripts/check.sh`: **48 tests passed**, Ruff passed,
strict mypy passed (30 source files), both development and installed worker profiles
passed all 13 isolation probes, and installed extraction/client-packet round trips passed.
The staged owner editor, PDF page/coverage behavior, and backup/restore CLI are present.
`test_stale_wiki_update_cannot_overwrite_owner_edit` and
`test_index_failure_leaves_durable_apply_and_retries` cover the final concurrency and
post-commit maintenance boundaries. Private-runtime readiness remains unproven until M3.

The user selected a **manual agent session** for M2's separate-agent continuity check.
Prepare its synthetic pack and verification procedure; do not spawn a subagent or claim
that deterministic tests satisfy that semantic gate.

M2 installed reference evidence from `bash scripts/check.sh`: **64 cumulative tests
passed**, Ruff passed, strict mypy passed (38 files), and both processing profiles passed
all 13 isolation probes. Installed packet, text-extraction, bibliography-extraction, and
receipt-extraction trials passed. The synthetic manual-handoff generator also completed
inside the installed development image. The new workflow covers:

| Requirement | Named evidence |
| --- | --- |
| Stable library IDs/citation keys; unknown dates; item-level deduplication | `test_bibliography_ids_dates_coverage_and_item_dedup` |
| Ambiguous or malformed import produces no capture | `test_bibliography_invalid_export_writes_nothing` (three cases) |
| Receipt approval preserves draft status; explicit adoption needs exact owner apply | `test_session_receipt_requires_explicit_adoption_and_context_preserves_evidence` |
| Roles preserved; fabricated citations and claimed authority rejected | `test_receipt_roles_fabricated_reference_and_claimed_authority` |
| No denied-domain titles/IDs/content or unsupported derived conclusion | `test_context_scope_filters_titles_ids_and_denied_evidence` |
| Bounded packs omit whole items, retaining evidence locators | `test_context_budget_omits_whole_items_and_keeps_locators` |
| Current, stale, and unverified repository states | `test_repository_binding_flags_changed_or_unverifiable_context` |
| Review diff matches exact candidate bytes | `test_review_diff_tamper_is_rejected` |
| CLI scoped context and explicit save | `test_cli_research_context_and_save` |

`scripts/prepare_continuity.py` executed the synthetic capture/proposal/approval/apply/
adoption/context sequence and generated `examples/continuity/context.json`, source evidence,
and a verification manifest. The second-agent semantic result is explicitly **not evaluated**.
Follow `docs/research-continuity.md` for the owner-selected manual test. No subagent was spawned.

M3 domain implementation adds exact structured financial observations and Decimal
calculations, dated financial categories, life dossier/history imports, and the owner
`evidence` command. The new tests cover decimal fidelity; distinct owner/account/date/
unit/currency; float rejection; fabricated amounts, metadata, prose and snapshot bodies;
preserved life history; denied-evidence summary leakage; and decision supersession.
Installed M3 domain-increment evidence from `bash scripts/check.sh`: **86 tests passed**,
Ruff passed, strict mypy passed (42 source files), both profiles passed 13 isolation probes
each, and six installed-worker trials passed (packet, text, bibliography, receipt,
financial snapshot, and life dossier). The manual-handoff generator also completed.

- `tests/test_domains.py` contains 15 executed cases, including six hostile snapshot
  mutations and five distinct prohibited arithmetic mixtures.
- `test_denied_evidence_withholds_derived_text_and_ranking` verifies that stripped citations
  cannot leave a restricted conclusion in search or its cache.
- `test_superseded_adopted_decision_is_not_presented_as_current` preserves the original
  decision and presents only its adopted successor as current.
- `test_missing_conflict_reference_is_rejected` and `test_cli_evidence_exact_locator_and_coverage`
  cover conflict-reference integrity and explicit source inspection.

Next work: complete release packaging, schema migration support,
the synthetic evaluation report, and a full requirement audit. Independent work may
continue while the external manual gate remains named and pending. Private activation
remains separate and is currently explicitly denied.

M3 restore/worker-hardening evidence from `bash scripts/check.sh`: **110 tests passed**,
Ruff passed, strict mypy passed (43 files), both profiles passed 13 isolation probes each,
and all six installed-worker trials passed. A real-engine create/start packet round trip
and forced removal of a running worker plus child also passed. No contributor Python
received a Docker socket or host/private mount.

- `tests/test_restore_hardening.py`: 12 executed cases cover complete namespace preflight,
  special files, missing manifest, invalid records, expected archive digest, copy failure,
  executable Git configuration, a ZIP above the old 32 MiB ceiling, backup of a real
  process-terminated two-file apply, and refusal to open incomplete restore staging.
- `tests/test_worker_lifecycle.py`: 11 cases use real subprocess pipes with a synthetic
  Docker control process to verify stdout/stderr limits, timeouts, closed pipes, packet
  success/failure, actual exit-state checks, exact owned-container cleanup, cleanup failure,
  remote endpoint denial, and image-volume rejection before input transmission.

The synthetic engine verifies launcher behavior, while the separate host script verifies
the actual Docker lifecycle and worker isolation. Neither is claimed to prove a complete
private installation or universal container security.

M3 policy-audit evidence from `bash scripts/check.sh`: **127 tests passed**, Ruff passed,
strict mypy passed (45 files), both profiles passed 13 isolation probes each, all six
installed-worker trials passed, and the real Docker create/start/removal trials passed.

`tests/test_policy_audit.py` executes 12 cases: all five processing operations; missing,
expired, wrong-provider/destination/scope/operation grants; question and metadata labels;
unknown labels; public evidence paired with a private question; denied input audit
redaction; local-client cloud-job rejection; exact policy history with interrupted
replacement; stale proposals after policy changes; scope replacement revoking grants;
restore of policy history; and the owner policy CLI. Five new schema parity cases cover
the audit/request/scope/grant models. A full-run context regression was fixed and rerun:
question labels constrain the output pack without widening access to stored records.

Cloud grants describe consent only. There is no cloud adapter, and an otherwise matching
cloud request is explicitly blocked without transmission. Release installation, version
inspection/migration, and the gold-set report remain required independent work. The
owner-selected manual continuity session is still pending.

Release preparation now has a typed manifest, locked wheel acquisition, bundle inventory
checks, and installed-runtime verification. Its 31 focused schema/release/CLI tests and
strict typing pass. The offline installed-wheel trial is pending execution at this
commit; it must pass before release packaging is recorded as verified. Private activation
is still denied.
