"""Emit versioned public schemas; run inside the development container."""

import json
from pathlib import Path

from cairn.adapters.protocol import Job, Result
from cairn.ingest.bibliography import BibliographyImport
from cairn.policies.models import Policy
from cairn.proposals.models import Approval, Proposal
from cairn.records.continuity import ContextPack, SessionReceipt
from cairn.records.models import Event, Extraction, Record

if __name__ == "__main__":
    destination = Path("schemas")
    destination.mkdir(exist_ok=True)
    for model in (
        Record,
        Extraction,
        Event,
        Policy,
        Job,
        Result,
        ContextPack,
        SessionReceipt,
        BibliographyImport,
        Approval,
        Proposal,
    ):
        (destination / f"{model.__name__.lower()}-v1.json").write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        )
