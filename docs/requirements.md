# M0–M3 requirements and evidence

This matrix follows the original build brief and Cairn build plan, including the plan's
additional installation, writer, migration, and review requirements. It does not redefine
the scope around passing tests. “Reference verified” means executed synthetic checks and
inspected implementation under the documented container profile. It does not mean real
owner data was tested or that a host/engine compromise is prevented.

The full goal is **not complete** while the owner-selected manual M2 continuity trial
has no result. The private directory has not been initialized or used. M4, publication,
real-data evaluation, and actual owner deployment are outside this goal. Current source
review and evaluation evidence are described below; the final acceptance log records
which committed revisions and installed bundles were executed.

## Brief §2: all ten boundaries

| Requirement | Authoritative implementation and executed evidence | Result and limit |
| --- | --- | --- |
| B1. Disjoint public/private roots; traversal and symlink rejection | `storage/files.py`, `storage/workspace.py:check_roots`; `test_roots_must_be_disjoint_and_not_git`, `test_traversal_rejected`, `test_links_special_files_and_collisions` | Reference verified for equal/nested roots, aliases, traversal, links, hard links, special files, case/Unicode ambiguity |
| B2. Dev/CI cannot read private workspaces, home, or credentials | Allowlisted `.dockerignore`, `Dockerfile`, `scripts/check.sh`; real unmounted synthetic canaries in both dev and worker isolation profiles | Reference verified for the executed profile; no real private files were probed |
| B3. Reviewed pinned runtime, not unchecked source | `records/release.py`, `storage/release.py`, `storage/activation.py`; offline installed trials; `test_activation_consent_and_installation_gate_precede_destination` | Reference verified on Linux-aarch64/CPython 3.13.11. No native macOS bundle or automatic release upgrade is claimed |
| B4. Sources/human notes immutable to models; proposals only | `proposals/service.py:target_path`, protected/input hashes; `test_capture_extract_apply_preserve_and_deduplicate`; gold-set exact-write checks | Source summaries are synthesis, not new evidence. Trusted capture/extraction may append source provenance |
| B5. Exclusive owner apply; actor labels are not authority | No owner mounts or endpoints in `adapters/worker.py`; exact approvals and journal in `transactions/apply.py`; real canonical/policy/approval write-denial probes; approval tamper tests | Reference verified for isolated workers. A host agent with owner/daemon access is outside this boundary |
| B6. Private/local-only default; separate explicit cloud consent | `records/models.py:Labels`, `policies/models.py`, `policies/audit.py`; `test_public_evidence_does_not_authorize_private_question`, `test_public_source_and_private_question_stay_local` | Reference verified. Owner capture uses the explicit private default; unknown request-part labels are restricted/local-only and unsupported classifications are rejected |
| B7. All local processing stages; no fallback, telemetry, or implicit downloads | Worker profile, route audit boundaries, blocked missing extraction/model capability; all five operation tests; real egress/DNS/subprocess probes | Reference verified for implemented stages. Embeddings, expansion, reranking, translation, and cloud generation are unavailable, not silent fallbacks |
| B8. Authorization before indexes, metadata, ranking, backlinks, context | `retrieval/search.py:_corpus`, policy/corpus cache keys, `retrieval/context.py`; scoped search/ranking/cache/backlink/context tests; gold scope checks | Reference verified. No graph traversal API or global model-visible database is exposed |
| B9. Documents/tool output cannot grant authority or execute | Strict worker protocol and typed candidate models; injected-source/wire-protocol tests; safe YAML tests; real worker probes; `test_markdown_cannot_activate_imported_html_links_or_fences` | Reference verified for defined attacks. Imported instructions are content, not executable tools |
| B10. No financial/external actions or scheduling | Inspected CLI/worker registrations; finance Decimal and life-dossier tests; no trading/payment/tax/message/calendar adapters | Implemented toolset has only knowledge operations; review dates are stored metadata |

## Brief §§3–4: artifacts and durable knowledge

| Requirement/artifact | Evidence | Result and limit |
| --- | --- | --- |
| Python src layout, uv, typed CLI, Markdown/YAML/JSON, SQLite FTS5 | `pyproject.toml`, `uv.lock`, `src/cairn/`, generated `schemas/`; schema parity, CLI and FTS tests | Reference verified; standard-library storage/calculation/index components, no ORM or agent framework |
| Named public artifacts and documentation | `README.md`, `AGENTS.md`, `templates/`, `examples/synthetic-vault/`, `tests/`, `.github/workflows/ci.yml`, architecture/threat/privacy/recovery/agent docs | Present; all examples synthetic. Public project uses the requested name Cairn |
| Separate private layout and machine-local path configuration | `Workspace.init`, `DIRECTORIES`, `workspace.json`, `CAIRN_WORKSPACE`, `examples/workspace.example.json`; initialization and restore tests | Reference verified in synthetic roots. The actual chosen owner root remains untouched |
| Local version history; no blob/cache versioning or automatic remote | `storage/history.py` explicit path list and hardened bare Git config; history execution/filter tests; installed apply trials | Evidence metadata is durable; original blobs are separately included in backups. No remote is configured |
| Stable IDs; six types; simple human Markdown captures | `records/models.py:RecordType`, type-prefixed IDs, `storage/markdown.py`, `vault/notes`/`inbox`; round-trip and preservation tests | Source, concept, project, decision, entity, playbook; titles are not identity |
| Common metadata, source provenance, unknown dates/authors | Typed records and source metadata; capture lineage; bibliography unknown-date test; gold unknown dates | Missing bibliographic dates remain unknown; year-only data is not invented as a full date |
| Assertions, exact locators/hashes, verification and dated applicability | `Assertion`, `EvidenceRef`, `Period`, `Money`; schema/quote/domain tests; dated/conflict gold cases | “Reviewed” and quote presence are not entailment or truth |
| Disputes/supersession preserve older evidence and decisions | Revised-source tests, superseded-adopted-decision test, gold Cedar/Maple cases | Relations are explicit. Automatic contradiction detection or date-based legal applicability is not implemented |
| Conversation roles and adoption separation | Conversation and receipt extraction tests; session adoption tests; gold role/context checks | A receipt or assistant recommendation never supplies owner approval |
| Explicit schema migration with backup and preview | `storage/migration.py`, `schema` CLI, `tests/test_migration.py`, installed migration trial | Workspace v1→v2 supported; record schema remains v1. No implicit rewriting, relabeling, or old pending-approval reuse. Release replacement is separate and unsupported |

## Brief §5 and plan writer requirements

| Requirement | Executed evidence | Result and limit |
| --- | --- | --- |
| I1. Capture identity/checksum/provenance before processing | Capture/extract workflow tests; installed CLI trial; `capture_bytes` writes raw blob, manifest, and event first | Reference verified |
| I2. Classify scope/route before extraction or generation | Sealed job/scope/input hashes; policy tests for all operations and complete request parts | Owner selects domain/scope and default privacy; no automatic classifier is claimed |
| I3. Preserve raw evidence, locators, extractor version and coverage | Text/PDF/conversation/bibliography/receipt/domain extractors; `test_pdf_extraction_preserves_page_and_partial_coverage`; installed extraction trials | PDF text is excerpt coverage with tables/images uninspected. Missing OCR/local capability is blocked |
| I4. Authorized retrieval and bounded source/related updates | `prepare_job`, `Job.max_changes`, scope-specific search; `test_two_file_update_is_reviewable`, worker packet round trip | Owner policy defaults to at most four changes, related inputs bounded; fake provider updates selected project links |
| I5. Stage bases, bytes, computed paths/diffs, evidence, rationale, provider/route | `stage_result`; diff-tamper test; new review-report tests | Model-authored shell patches and canonical target paths are not executed |
| I6. Validate all bindings, schemas, IDs, references, privacy inheritance and review flags | Foundations, ingest/apply, research-continuity and domain tests; `validate_unlocked` inspection | Invalid quotes/IDs/conflict targets, unsupported financial values, changed inputs and narrowed scopes fail closed |
| I7. Single writer, optimistic concurrency, durable approval/receipt, crash recovery | Six real apply-crash boundaries; stale wiki/owner-byte tests; policy/approval tamper tests; restored pending-transaction test | All application readers use the lock; arbitrary external editors must cooperate for multi-file consistency |
| I8. Post-commit disposable index/history maintenance | `test_index_failure_leaves_durable_apply_and_retries`, cache rebuild test, local history checks | Maintenance failure is retryable and does not roll back accepted data |
| Required captured→extracted→proposed→validated→approved→applied→indexed sequence | Durable `Event` model and workflow; duplicate import reaches indexed; failed extraction remains captured | Attempt/source IDs and retryable failure/block events are retained outside caches |
| Idempotence and revised lineage | Repeated capture/import tests, bibliography item dedup, source revisions | Re-ingestion produces no duplicate canonical pages; changed declared-version bytes are conflicts |
| Staged owner edit command | `transactions/edit.py`, `test_owner_edit_is_staged_and_checks_base` | Uses the same review/apply writer; imported content never selects the editor command |
| Preserve data on unexpected recovery edits | Apply and schema migration owner-byte tests | Recovery stops instead of overwriting unknown bytes |
| No model deletion or reclassification | Inspected proposal target/type checks and worker API | Retention/deletion and owner reclassification are outside model operations |

## Brief §6: reading, context, and interfaces

| Requirement | Evidence | Result and limit |
| --- | --- | --- |
| Read-only answers from both evidence and synthesis, exact original wording/numbers | `query`, labeled `Hit`, gold exact-source/multiple-source/absent cases; `query:durable_read_only` | Read-only means no durable knowledge writes; scoped caches may be built. Answers are labeled excerpts, not model synthesis |
| Dates, versions, coverage, conflicts and missing evidence | Gold dated/contradiction/unknown cases; `evidence` CLI and review report tests | Explicit conflicts retained; unsupported answers are not fabricated |
| Metadata/aliases/keywords, English and Chinese | FTS5 + trigram + short Chinese fallback; two-character/alias tests and gold cases | Cross-language matching is limited to available aliases; no semantic translation or vector retrieval |
| Compact project question/objective/constraints/decisions/literature/failures/issues/action/citations | `ContextPack`, budget/role/scope tests; gold project context | Whole retained items keep citations; UTF-8 byte estimate is conservative, not a model tokenizer |
| Commit/run bindings and stale/unverified handling | `RepositoryBinding`, `inspect_repository`; current/stale/unverified repository test | Selected repository is read-only; ignored datasets/submodules require separate manifests |
| Structured session receipts become reviewed proposals | `SessionReceipt`, `import_receipt`, explicit `adopt_decision`; receipt tests and installed receipt extraction | Code/data/checkpoints/manuscripts remain in their repositories; no hidden-client-memory dependency |
| Another agent actually uses a decision and avoids the failed approach | `examples/continuity/context.json`, owner evidence and verification; `docs/research-continuity.md` manual rubric | **Pending manual session by owner choice. Protocol tests and gold results do not prove this requirement** |
| Existing-client job/result integration, deterministic offline fake | `FakeProvider`, `ClientPacketProvider`, strict protocol, sealed jobs and real installed packet round trip | A concrete real model frontend is not bundled. Manual/unverified client output is not claimed local. Missing capability is blocked |
| Intended CLI surface | `init`, `capture`, `ingest`, `proposal show`, `validate`, `apply`, `search`, `context`, `lint`, `rebuild-index`, `doctor`; CLI integration tests | All original names available under `cairn`; owner approval, edit, recover, backup/restore, policy/release/schema and domain commands added |
| Stable JSON, distinct error statuses, honest doctor | CLI guarded errors; activation doctor tests; full owner CLI tests; worker diagnostics redaction | JSON preserves structured contracts; doctor does not install models, change permissions, or grant routes |
| Human source/conflict review with local Markdown links | `proposals/review.py`, `proposal show --markdown`, `tests/test_review.py`, `docs/review.md` | Dates/coverage/conflicts are visible; current diffs recomputed; imported active content escaped; revoked scopes denied |
| Later stdio MCP and remote server restrictions | No MCP/server endpoint exists; plan explicitly assigns these to M4 | Deferred as specified. No approval/apply/public export/policy/shell endpoint exposed to models |

## Brief §7: all domain templates

| Requirement | Evidence | Result and limit |
| --- | --- | --- |
| Research framing, contribution/literature, assumptions, conjectures/results, experiments, failures, decisions, next test | `templates/research-project.md`; `project create`, structured assertions/sections, receipts and repository bindings | Framing is captured as evidence and applied by owner; additional sections use staged edits |
| Paper/library IDs, citation keys, metadata, claims, methods/limits/locators and project relevance | `templates/paper.md`; read-only CSL-JSON adapter and dedup/date/coverage tests | Abstract-only coverage remains explicit; no live bibliography database copy/write; raw BibTeX is an unparsed excerpt |
| Finance educational/rules/snapshots/decisions separation and dates | `templates/finance.md`, finance CLI/model constraints, dated rule test and gold Maple cases | Applicability metadata required for official rules; original theses remain separate preserved decisions |
| Decimal values, units/currencies, dates, source references and owner/account separation | Financial snapshot/amount models; Decimal exactness, incompatible operand and fabricated-value tests | Calculations read structured preserved sources; no inferred holdings/balances, live account access, or wiki-ledger authority |
| Life entity documents/service/warranty/renewal/procedures/decisions | `templates/life-entity.md`; `LifeDossier`, life import and revision test | Dated history is appended, prior events preserved; review date never schedules an action |

## Brief §8: every hard gate and evaluation measure

| Hard gate | Direct evidence |
| --- | --- |
| H1. Root overlap, traversal, unauthorized symlinks | B1 tests and restore namespace/special-file tests |
| H2. Dev/CI cannot read private workspace | Actual dev/worker profiles denied an unmounted synthetic host canary; B2 profile inspection |
| H3. Source/human hashes unchanged after compilation | Capture/apply preservation test and all gold proposal `protected_bytes` checks |
| H4. Stale proposal cannot overwrite owner edit | `test_stale_wiki_update_cannot_overwrite_owner_edit`, staged editor test |
| H5. Half-apply recovers without appearing complete | Real termination at prepared, both file writes, receipt, commit, history; pending read refusal and exact recovery hashes |
| H6. Idempotent re-ingest; revised lineage | Capture/version/bibliography/receipt dedup tests |
| H7. Reject fabricated quotes, missing refs, invalid schemas and denied reads | Quote/scope test, missing-conflict-reference test, financial fabrication tests, schema/YAML tests |
| H8. Injected source cannot mutate policy/approve/read another domain/execute tools | Strict worker result/job schema, injection test, gold policy/adoption checks, no-mount no-network hostile-process probes |
| H9. No restricted titles/backlinks/caches/context | Scoped ranking/cache/backlink/derived-citation tests; context scope test; gold scope and review-revocation checks |
| H10. No remote requests/fallback/telemetry for local-only | Exact manifest worker image probes and local profile checks, five-operation route tests, inspection of networking code (build acquisition and explicit probes only) |
| H11. Cache deletion/rebuild preserves knowledge | `test_bilingual_short_query_and_cache_rebuild` verifies durable bytes and identical results |
| H12. Backup restore reconstructs text and evidence blobs | Text/blob/evidence round trip, >32 MiB archive, namespace/hash attacks, copy failure and interrupted transaction restore; fresh installed CLI trials |
| H13. Assistant suggestion is not an owner decision | Conversation/receipt/adoption chain tests; gold roles and pre-adoption empty decision section |

| Evaluation requirement | Retained measurement |
| --- | --- |
| Exact-source, multiple-source, contradiction, outdated-rule, absent-evidence, bilingual, role and project cases | `examples/goldset/corpus.json`, `scripts/evaluate_goldset.py`, `docs/evidence/goldset.json`; 129 checks and eight query cases |
| Citation support and source coverage | 36 citation occurrences checked; expected source recall/precision per query; locators/hashes/quotes inspected |
| Useful answer quality | Exact-source wording/date/conflict/status rubric per case. General semantic/model quality explicitly unmeasured; multiple-source retrieval is not synthesis |
| Unauthorized disclosure and write correctness | Zero observed violations in the defined scope/write corpus; exact affected-page hashes and durable-read-only checks |
| Review burden | 12 fixture proposals, 13 page changes, per-proposal flags and diff-line counts; actual human edits/time unmeasured |
| Latency and model cost | Three samples/median per query, context and workload time; zero model calls/tokens and USD 0.00 model cost |
| Honest fake/real distinction, private real evaluation | `docs/evaluation.md` limits; manual continuity pending; no private corpus or logs copied into development |

## Plan-specific release and remaining gates

The following evidence extends the brief rather than replacing its requirements:

| Plan requirement | Evidence/status |
| --- | --- |
| Separate acquisition from no-network processing; exact wheelhouse/lock/runtime/worker/adapters | `scripts/build_release.py`, release manifests and strict verifier; offline installed trials; no private build inputs |
| Complete request audit covers question, instructions, metadata, output handling and traces | `tests/test_policy_audit.py` all five operations, mismatched/expired grants, public evidence plus private question, redacted denied requests |
| Shared writer and explicit schema preview/backup/migration | Nine process crash boundaries; unknown-version rejection; source/adoption preservation and pending-approval invalidation; installed migration trial |
| Safe backup path namespace, evidence bindings, history config, staged publication | `tests/test_restore_hardening.py`; incomplete restore marker refusal; exact hashes before publication |
| Bounded worker streams/deadlines and owned cleanup | `tests/test_worker_lifecycle.py`; real Docker create/start/remove and hostile child removal; remote daemon/implicit volume denial |
| Actual-machine activation requires separate owner acceptance and fresh probe | Synthetic lifecycle stand-ins plus actual installed negative activation; no private activation occurred. Manual review is still pending |
| Named limitations and release review | `docs/installation.md`, `docs/privacy.md`, `docs/recovery.md`, `docs/agent-integration.md`, `docs/schema-migrations.md`, `docs/review.md` |

M0/M1 have reference acceptance evidence. M2 has implementation and mechanical evidence,
but its explicit semantic exit gate is pending. M3 has domain, policy, restoration,
installation, migration, review, and evaluation evidence. The final installed trial at
`6bcad55cd9c71ea154dab2d4e6e34b65e80d1929` passed with 15 distributions/878 verified files,
Markdown source review, migration/restore, tamper rejection, and all 13 checks for the exact
worker image. See `docs/evidence/final-release-trial.json` and `final-worker-profile.json`.
Nothing in this matrix authorizes real deployment, new cloud consent, publication, or M4.
