"""Build a synthetic, owner-approved context pack for a later manual agent session.

Run in the native synthetic environment with synthetic inputs only. This
script demonstrates the protocol, not a real second agent or model capability.
"""

import argparse
import json
import tempfile
from pathlib import Path

from cairn.ingest.projects import create_project
from cairn.ingest.receipts import adopt_decision, import_receipt
from cairn.proposals.models import Proposal
from cairn.proposals.service import approve
from cairn.records.continuity import ReceiptEntry, ReceiptMessage, SessionReceipt
from cairn.records.models import canonical, digest
from cairn.retrieval.context import context_pack
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply


def prepare(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cairn-synthetic-continuity-") as directory:
        root = Path(directory)
        code = root / "code"
        code.mkdir()
        ws = Workspace.init(root / "workspace", code_roots=[code], synthetic=True)

        def accept(proposal: Proposal) -> None:
            approve(
                ws,
                proposal.id,
                acknowledgements=proposal.review_flags,
                statement="Synthetic owner accepts these exact fixture changes.",
            )
            apply(ws, proposal.id)

        framed = create_project(
            ws,
            title="Synthetic bilingual retrieval study",
            question="Can scoped retrieval preserve exact provenance for Chinese and English?",
            objective="Design a reproducible, local-only retrieval baseline.",
            constraints="Synthetic evidence only. No network. Report unknown results as unknown.",
            scope_name="research",
            inline_synthetic=True,
        )
        accept(framed)
        project_id = framed.changes[0].id
        receipt = SessionReceipt(
            session_id="session_synthetic_alpha",
            project_id=project_id,
            messages=[
                ReceiptMessage(role="user", content="Keep the baseline scoped and auditable."),
                ReceiptMessage(role="assistant", content="I suggest preserving exact locators."),
            ],
            tried=[
                ReceiptEntry(text="A title-only lookup could not disambiguate source revisions.")
            ],
            failures=[
                ReceiptEntry(
                    text="Title-only retrieval lost source locators and version identity; "
                    "do not repeat it as the evidence representation."
                )
            ],
            proposed_decisions=[
                ReceiptEntry(
                    text="Every retrieved claim must retain a stable source ID, "
                    "source version/hash, and exact evidence locator."
                )
            ],
            unresolved=[
                ReceiptEntry(text="Two-character Chinese queries still need a baseline test.")
            ],
            next_action=ReceiptEntry(
                text="Design a tiny bilingual test with two-character Chinese queries, "
                "exact English matches, and an absent-evidence case."
            ),
        )
        file = root / "session-alpha.json"
        file.write_bytes(canonical(receipt))
        imported = import_receipt(ws, file, scope_name="research", inline_synthetic=True)
        assert imported is not None
        accept(imported)
        decision_id = next(
            change.id for change in imported.changes if change.id.startswith("decision_")
        )
        adopted = adopt_decision(
            ws,
            decision_id,
            scope_name="research",
            statement="Adopt exact provenance for this synthetic baseline.",
        )
        assert adopted is not None
        accept(adopted)
        pack = context_pack(
            ws,
            project_id,
            question="Continue the study with the next useful step.",
            budget=12000,
            scope_name="research",
        )
        assert pack.sections["current_decisions"] and pack.sections["failed_approaches"]
        data = canonical(pack)
        (output / "context.json").write_bytes(data)
        (output / "session-alpha.json").write_bytes(canonical(receipt))
        # Owner review evidence is separate from the single artifact sent to session beta.
        source_evidence = []
        for source_id in pack.source_ids:
            _, source, _ = ws.record(source_id)
            assert source.source and source.source.extraction
            source_evidence.append(
                {
                    "record": source,
                    "source_bytes_utf8": ws.fs.read(source.source.blob).decode(),
                    "extraction": json.loads(
                        ws.fs.read(f"evidence/{source.source.extraction.evidence_hash}.json")
                    ),
                }
            )
        (output / "owner-evidence.json").write_bytes(canonical(source_evidence))
        (output / "verification.json").write_bytes(
            canonical(
                {
                    "synthetic": True,
                    "context_sha256": digest(data),
                    "protocol": "capture/extract/propose/approve/apply/adopt/context executed",
                    "second_agent_session": "pending_manual_session",
                    "semantic_continuity": "not_evaluated",
                    "network_used": False,
                    "estimated_tokens": pack.estimated_tokens,
                    "actual_model_tokens": None,
                    "model_cost": None,
                }
            )
        )
        print(json.dumps({"synthetic_context_prepared": True, "manual_session": "pending"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    prepare(parser.parse_args().output)
