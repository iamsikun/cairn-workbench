# Acceptance evidence

Implementation is in progress. A checked item requires an executed test or inspected
artifact, not just code presence. Private activation and M4 are outside this goal.

| Stage | Status | Remaining |
| --- | --- | --- |
| M0 | Passed reference acceptance | 24 tests, lint, strict typing, 13 isolation checks |
| M1 | Passed reference acceptance | 48 tests, installed worker protocols, both isolation profiles |
| M2 | Pending | Bibliography, context, receipts, continuity demonstration |
| M3 | Pending | Domain workflows, restore, installed release, complete audit |

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
container security, or private-runtime readiness. M1–M3 remain required.

M1 core evidence: **44 cumulative tests passed**, Ruff passed, strict mypy passed
(29 source files), using the isolated development profile with public source mounted.
The updated installed image still needs its full acceptance run before closing M1.

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

Next work: implement M2 bibliography,
project context and receipt workflows; implement M3 domain templates/calculations, grant
audits, full restore/release packaging, all required documentation, and a full requirement
audit. Private activation remains separate and is currently explicitly denied.
