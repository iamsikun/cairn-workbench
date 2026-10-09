"""Prepare/import a real agent's synthetic Quill response in an offline container.

This script never creates the agent response. Read the exported packet and provide
response.json separately, then run import. No private workspace is involved.
"""

import argparse
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from cairn.ingest.service import capture_bytes, extract
from cairn.policies.audit import set_grant
from cairn.policies.models import RouteGrant
from cairn.presentation.service import assemble, remember
from cairn.presentation.writing import (
    explanation_html,
    export_packet,
    import_explanation,
    prepare,
)
from cairn.records.models import Labels, canonical, digest, now
from cairn.storage.backup import backup, durable_contents, restore
from cairn.storage.workspace import Workspace


def run(mode: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cairn-quill-trial-") as scratch:
        root = Path(scratch) / "synthetic-workspace"
        if mode == "prepare":
            ws = Workspace.init(root, code_roots=[Path("/opt/cairn")], synthetic=True)
            set_grant(
                ws,
                RouteGrant(
                    id="grant_quill_trial",
                    scope="research",
                    provider="codex-agent-packet",
                    destination="synthetic-manual-review",
                    operations={"generation", "client_export"},
                    valid_until=now() + timedelta(days=7),
                    owner_consent="Synthetic packet evaluation only; no private data.",
                ),
                base_hash=ws.policy_hash,
                statement="Synthetic packet evaluation only; no private data.",
            )
            source = capture_bytes(
                ws,
                (
                    b"Synthetic Aster study: in 12 simulated datasets with condition C, "
                    b"method A had mean error 12%, compared with 15% for method B.\n"
                    b"Across those simulations, the estimated difference was -3 percentage points "
                    b"with a 95% interval from -7 to +1 percentage points.\n"
                    b"The supplied excerpt reports no results for conditions other than C. "
                    b"It does not state whether such conditions were studied elsewhere.\n"
                ),
                origin="synthetic-aster.txt",
                domain="research",
                title="Synthetic Aster study",
                identity="quill-trial",
                source_type="text",
                classification="public",
                processing="cloud_eligible",
            )
            extract(ws, source.id, scope_name="research", inline_synthetic=True)
            view = assemble(ws, "evidence", scope="research", object_id=source.id)
            remember(ws, view)
            job = prepare(
                ws,
                view.id,
                provider="codex-agent-packet",
                route="cloud",
                destination="synthetic-manual-review",
                request="Explain what the Aster comparison supports for a researcher, "
                "keeping numerical uncertainty and scope explicit.",
                request_labels=Labels(
                    domain="research", classification="public", processing="cloud_eligible"
                ),
            )
            export_packet(ws, job.id, output / "packet.json")
            result = backup(ws, output / "state.zip")
            (output / "state.sha256").write_text(str(result["sha256"]) + "\n")
            print(
                canonical(
                    {
                        "job_id": job.id,
                        "bundle_id": view.id,
                        "status": "prepared; agent response required",
                    }
                ).decode()
            )
        else:
            ws = restore(
                output / "state.zip",
                root,
                code_roots=[Path("/opt/cairn")],
                expected_sha256=(output / "state.sha256").read_text().strip(),
                synthetic=True,
            )
            before = {
                p: digest(b)
                for p, b in durable_contents(ws).items()
                if p.startswith(("vault/", "approvals/"))
            }
            response = import_explanation(ws, output / "response.json")
            export_packet(ws, response.job_id, output / "reexported.json")
            rendered = explanation_html(
                ws, response, output / "explanation.html", inline_synthetic=True
            )
            assert before == {
                p: digest(b)
                for p, b in durable_contents(ws).items()
                if p.startswith(("vault/", "approvals/"))
            }
            result = {
                "agent": "Codex (this development chat)",
                "input": "synthetic only",
                "mechanical_import": "passed",
                "canonical_unchanged": True,
                "execution_attestation": "not established by a manual packet",
                "semantic_review": "manual, one case; not a quality benchmark",
                **rendered,
            }
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "import"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.mode, args.output)
