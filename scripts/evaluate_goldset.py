"""Execute the public synthetic baseline in the native synthetic environment.

The report distinguishes exact mechanical checks from semantic model evaluation.
No owner data, real model, external client, network access, or subagent is used.
"""

import argparse
import json
import platform
import sqlite3
import statistics
import tempfile
import time
from collections import Counter
from datetime import date
from pathlib import Path

from cairn.adapters.fake import FakeProvider
from cairn.errors import Denied
from cairn.ingest.projects import create_project
from cairn.ingest.receipts import adopt_decision, import_receipt
from cairn.ingest.service import capture_bytes, extract, load_extraction
from cairn.proposals.service import approve, prepare_job, stage_result
from cairn.records.continuity import ReceiptEntry, ReceiptMessage, SessionReceipt
from cairn.records.models import EvidenceRef, Period, canonical, digest
from cairn.retrieval.context import context_pack
from cairn.retrieval.search import backlinks, query, search
from cairn.storage.backup import durable_contents
from cairn.storage.markdown import decode
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply


def evaluate(corpus_path: Path) -> dict:
    corpus = json.loads(corpus_path.read_bytes())
    assert corpus["schema_version"] == 1 and corpus["synthetic"] is True
    started = time.perf_counter()
    reviews, cases, checks = [], [], []
    citations_checked = citations_supported = 0

    def check(name: str, passed: bool) -> None:
        checks.append({"check": name, "passed": bool(passed)})

    with tempfile.TemporaryDirectory(prefix="cairn-synthetic-goldset-") as directory:
        root = Path(directory)
        code = root / "public-code"
        code.mkdir()
        ws = Workspace.init(root / "workspace", code_roots=[code], synthetic=True)
        ws.fs.write("vault/notes/owner.md", b"Synthetic owner hypothesis; do not rewrite.\n")
        original_policy = ws.policy_hash

        def accept(proposal, label: str) -> None:
            protected = ws.protected_hashes()
            before = {
                path: raw for path, raw in durable_contents(ws).items() if path.startswith("vault/")
            }
            approve(
                ws,
                proposal.id,
                acknowledgements=proposal.review_flags,
                statement="Synthetic evaluation fixture review, not a real owner decision.",
            )
            receipt = apply(ws, proposal.id)
            expected = {change.path: change.content_hash for change in proposal.changes}
            check(f"{label}:protected_bytes", ws.protected_hashes() == protected)
            check(
                f"{label}:exact_write",
                receipt.files == expected
                and all(
                    digest(ws.fs.read(path)) == checksum for path, checksum in expected.items()
                ),
            )
            after = {
                path: raw for path, raw in durable_contents(ws).items() if path.startswith("vault/")
            }
            changed = {
                path for path in before.keys() | after.keys() if before.get(path) != after.get(path)
            }
            check(f"{label}:only_approved_pages", changed == set(expected))
            reviews.append(
                {
                    "label": label,
                    "pages_changed": len(expected),
                    "review_flags": sorted(proposal.review_flags),
                    "diff_lines": sum(len(change.diff.splitlines()) for change in proposal.changes),
                    "human_edits": None,
                    "review_seconds": None,
                }
            )

        aliases, summaries, source_expectations = {}, {}, {}
        for item in corpus["sources"]:
            source = capture_bytes(
                ws,
                item["text"].encode(),
                origin=item["alias"] + ".txt",
                title=item["title"],
                identity=item.get("identity", item["alias"]),
                domain=item["domain"],
                source_type="text",
                version=item["version"],
                source_date=date.fromisoformat(item["date"]) if item["date"] else None,
            )
            aliases[item["alias"]] = source.id
            source_expectations[source.id] = item
            extract(ws, source.id, scope_name=item["domain"], inline_synthetic=True)
            related = [summaries[item["disputes"]]] if "disputes" in item else []
            job = prepare_job(ws, source.id, scope_name=item["domain"], related_ids=related).job
            result = FakeProvider().generate(job)
            candidate = result.candidates[0].record
            if item["domain"] == "finance":
                candidate.period = Period(
                    as_of=date.fromisoformat(item["date"]), jurisdiction="Example"
                )
                candidate.finance_category = "official_rule"
            if "disputes" in item:
                # Explicit fixture annotation, not an automatic contradiction detector.
                assertion = candidate.assertions[0]
                assertion.rationale = "Synthetic estimates disagree; preserve both for review."
                assertion.disputes = related
                assertion.verification = "disputed"
            proposal = stage_result(ws, result)
            assert proposal is not None
            accept(proposal, item["alias"])
            summaries[item["alias"]] = proposal.changes[0].id

        def supported(ref: EvidenceRef, scope: str) -> bool:
            _, source, _ = ws.record(ref.id, ws.policy.scope(scope))
            extraction, artifact_hash = load_extraction(ws, source)
            assert source.source
            raw = ws.fs.read(source.source.blob)
            segments = [part for part in extraction.segments if part.locator == ref.locator]
            return bool(segments) and (
                digest(raw) == ref.source_hash == source.source.content_hash
                and artifact_hash == ref.evidence_hash
                and (ref.quote is None or any(ref.quote in part.text for part in segments))
            )

        # A denied record must not perturb authorized hit counts, ordering, or scores.
        before_denied = canonical(search(ws, "Orchid", scope_name="research"))
        secret = corpus["denied_source"]
        denied = capture_bytes(
            ws,
            secret["text"].encode(),
            origin="restricted.txt",
            title=secret["title"],
            identity="denied-fixture",
            domain="finance",
            classification="restricted",
            source_type="text",
        )
        extract(ws, denied.id, scope_name="owner", inline_synthetic=True)
        after_denied = canonical(search(ws, "Orchid", scope_name="research"))
        check("scope:authorized_ranking_unchanged", before_denied == after_denied)
        denial = query(ws, secret["title"], scope_name="research")
        check("scope:denied_title_absent", not denial["hits"])
        try:
            backlinks(ws, denied.id, scope_name="research")
            denied_backlink = False
        except Denied:
            denied_backlink = True
        check("scope:denied_backlink", denied_backlink)

        id_alias = {value: key for key, value in aliases.items()}
        query_durable_before = durable_contents(ws)
        for case in corpus["queries"]:
            latencies, answer = [], None
            for _ in range(3):
                tick = time.perf_counter()
                answer = query(ws, case["question"], scope_name=case["scope"])
                latencies.append(round((time.perf_counter() - tick) * 1000, 3))
            assert answer is not None
            evidence = [hit for hit in answer["hits"] if hit["kind"] == "evidence"]
            retrieved = {id_alias[hit["id"]] for hit in evidence}
            expected = set(case["expected_sources"])
            case_citations = [
                EvidenceRef.model_validate(ref) for hit in answer["hits"] for ref in hit["sources"]
            ]
            supported_count = sum(supported(ref, case["scope"]) for ref in case_citations)
            citations_checked += len(case_citations)
            citations_supported += supported_count
            observed_dates = {hit["source_date"] for hit in evidence if hit["source_date"]}
            predicates = {
                "all_expected_sources": expected <= retrieved,
                "no_unexpected_evidence_sources": retrieved <= expected,
                "expected_status": answer["status"] == case["expected_status"],
                "expected_wording": all(text in answer["answer"] for text in case["expected_text"]),
                "dates_retained": set(case["dates"]) <= observed_dates,
                "conflict_retained": bool(answer["conflicts"]) == case["conflict"],
                "citations_supported": supported_count == len(case_citations),
                "no_denied_content": secret["title"] not in canonical(answer).decode(),
                "no_synthesis_claim": answer["mode"] == "extractive",
                "original_segments": all(
                    hit["text"].strip() == source_expectations[hit["id"]]["text"].strip()
                    for hit in evidence
                ),
            }
            for name, passed in predicates.items():
                check(f"{case['id']}:{name}", passed)
            cases.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "scope": case["scope"],
                    "expected_sources": sorted(expected),
                    "retrieved_sources": sorted(retrieved),
                    "source_recall": len(expected & retrieved) / len(expected)
                    if expected
                    else None,
                    "source_precision": len(expected & retrieved) / len(retrieved)
                    if retrieved
                    else None,
                    "evidence_hits": len(evidence),
                    "synthesis_hits": len(answer["hits"]) - len(evidence),
                    "citations_checked": len(case_citations),
                    "citations_supported": supported_count,
                    "dates": sorted(observed_dates),
                    "conflict_count": len(answer["conflicts"]),
                    "latency_ms": {"samples": latencies, "median": statistics.median(latencies)},
                    "checks": predicates,
                    "mechanical_rubric_passed": all(predicates.values()),
                    "model_synthesis": "not_performed",
                    "semantic_answer_quality": "not_evaluated",
                }
            )
        check("query:durable_read_only", durable_contents(ws) == query_durable_before)
        check("source_injection:policy_unchanged", ws.policy_hash == original_policy)
        check(
            "source_injection:no_adoption",
            not any(record.type == "decision" for _, record, _ in ws.records()),
        )

        # Execute role preservation and explicit adoption through the real owner workflow.
        framed = create_project(
            ws,
            title="Synthetic continuity fixture",
            question="Can a later session retain provenance?",
            objective="Preserve decisions and failures.",
            constraints="Synthetic data only; no network.",
            scope_name="research",
            inline_synthetic=True,
        )
        accept(framed, "project_framing")
        project_id = framed.changes[0].id
        continuity = corpus["continuity"]
        receipt = SessionReceipt(
            session_id="session_gold_alpha",
            project_id=project_id,
            messages=[
                ReceiptMessage(role="user", content="Keep original locators."),
                ReceiptMessage(role="assistant", content=continuity["proposed_decision"]),
            ],
            failures=[ReceiptEntry(text=continuity["failed_approach"])],
            proposed_decisions=[ReceiptEntry(text=continuity["proposed_decision"])],
            unresolved=[ReceiptEntry(text=continuity["open_issue"])],
            next_action=ReceiptEntry(text=continuity["next_action"]),
        )
        receipt_path = root / "session.json"
        receipt_path.write_bytes(canonical(receipt))
        proposed = import_receipt(ws, receipt_path, scope_name="research", inline_synthetic=True)
        assert proposed is not None
        accept(proposed, "session_receipt")
        decision_id = next(
            change.id for change in proposed.changes if change.id.startswith("decision_")
        )
        project_change = next(change for change in proposed.changes if change.id == project_id)
        record, _ = decode(project_change.content.encode())
        receipt_source_id = record.assertions[-1].sources[0].id
        _, receipt_source, _ = ws.record(receipt_source_id)
        receipt_extraction, _ = load_extraction(ws, receipt_source)
        roles = [segment.role for segment in receipt_extraction.segments if segment.role]
        check("roles:preserved_order", roles[:2] == ["user", "assistant"])
        before_adoption = context_pack(
            ws, project_id, question="What next?", budget=20000, scope_name="research"
        )
        check("roles:suggestion_not_adopted", not before_adoption.sections["current_decisions"])
        adopted = adopt_decision(
            ws,
            decision_id,
            scope_name="research",
            statement="Adopt exact provenance for the synthetic fixture.",
        )
        assert adopted is not None
        accept(adopted, "owner_adoption")
        tick = time.perf_counter()
        pack = context_pack(
            ws, project_id, question="What next?", budget=20000, scope_name="research"
        )
        context_latency = round((time.perf_counter() - tick) * 1000, 3)
        check(
            "context:decision_retained",
            any(
                continuity["proposed_decision"] in item.text
                for item in pack.sections["current_decisions"]
            ),
        )
        check(
            "context:failure_retained",
            any(
                continuity["failed_approach"] in item.text
                for item in pack.sections["failed_approaches"]
            ),
        )
        check(
            "context:denied_domain_absent",
            secret["title"] not in canonical(pack).decode() and denied.id not in pack.input_hashes,
        )
        check("context:budget", pack.estimated_tokens <= pack.budget)
        context_refs = [
            ref for section in pack.sections.values() for item in section for ref in item.sources
        ]
        check(
            "context:citations",
            bool(context_refs) and all(supported(ref, "research") for ref in context_refs),
        )

    base = Path(__file__).resolve().parents[1]
    source_hashes = {
        str(path.relative_to(base)): digest(path.read_bytes())
        for path in sorted((base / "src").rglob("*.py"))
    }
    return {
        "schema_version": 1,
        "synthetic": True,
        "baseline": "fts5 plus fake-v1 extractive workflow",
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
        "provenance": {
            "corpus_sha256": digest(corpus_path.read_bytes()),
            "script_sha256": digest(Path(__file__).read_bytes()),
            "source_tree_sha256": digest(canonical(source_hashes)),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.system() + "-" + platform.machine(),
        },
        "checks": checks,
        "query_cases": cases,
        "metrics": {
            "checks_passed": sum(item["passed"] for item in checks),
            "checks_total": len(checks),
            "mechanical_query_rubric_passes": sum(
                case["mechanical_rubric_passed"] for case in cases
            ),
            "query_cases": len(cases),
            "citation_support": {
                "supported": citations_supported,
                "checked": citations_checked,
                "meaning": "hash/locator/quote existence; not entailment",
            },
            "unauthorized_disclosures_observed": sum(
                not item["passed"]
                for item in checks
                if item["check"].startswith("scope:") or "denied_" in item["check"]
            ),
            "write_violations_observed": sum(
                not item["passed"]
                for item in checks
                if item["check"].endswith(
                    (
                        ":protected_bytes",
                        ":exact_write",
                        ":only_approved_pages",
                        ":durable_read_only",
                        ":policy_unchanged",
                        ":no_adoption",
                    )
                )
            ),
            "review_burden": {
                "proposals": len(reviews),
                "page_changes": sum(r["pages_changed"] for r in reviews),
                "flag_occurrences": dict(
                    sorted(Counter(flag for r in reviews for flag in r["review_flags"]).items())
                ),
                "human_edits": None,
                "human_review_seconds": None,
                "observations": reviews,
            },
            "context_latency_ms": context_latency,
            "context_estimated_tokens": pack.estimated_tokens,
            "total_elapsed_seconds": round(time.perf_counter() - started, 3),
            "model_calls": 0,
            "model_tokens": 0,
            "model_cost_usd": "0.00",
        },
        "continuity": {
            "roles_observed": roles[:2],
            "protocol": "evaluated",
            "second_agent_session": "pending_manual_session",
            "semantic_usefulness": "not_evaluated",
        },
        "limitations": [
            "This is the measured mechanical baseline, not a general answer-quality score.",
            "Multiple-source retrieval is measured; model synthesis is not evaluated.",
            "The Cedar dispute is a fixture annotation, not automatic conflict detection.",
            "Dated Maple revisions stay visible together; applicability is not inferred.",
            "Human review time and edits are unmeasured; synthetic approval is not acceptance.",
            "Zero observed violations covers only these defined cases, not universal security.",
            "Native process budgets do not establish a network or filesystem sandbox.",
            "Manual usefulness and private evaluation remain separate; no model ran.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("examples/goldset/corpus.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "goldset": report["status"],
                "checks": report["metrics"]["checks_total"],
                "passed": report["metrics"]["checks_passed"],
                "manual_continuity": "pending",
            }
        )
    )
    raise SystemExit(0 if report["status"] == "passed" else 1)
