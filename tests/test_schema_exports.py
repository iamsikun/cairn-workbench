import json
from pathlib import Path

import pytest

from cairn.adapters.protocol import Job, Result
from cairn.ingest.bibliography import BibliographyImport
from cairn.library.device_runner import RunnerConfig
from cairn.library.discovery import DiscoveryReport, Publication
from cairn.library.feed import FeedDigest, FeedEntry, FeedEvent
from cairn.library.models import Journal, LibraryConfig, Paper, ScanReport
from cairn.library.reader_models import (
    DeviceConfig,
    DeviceProbe,
    PaperSummary,
    ReaderJob,
    ReaderResult,
    ReadState,
)
from cairn.library.store import LibraryTransaction
from cairn.library.verification_models import (
    VerificationConfig,
    VerificationPacket,
    VerificationResult,
    VerificationState,
)
from cairn.policies.audit import PolicyChange, RouteAudit, RouteRequest
from cairn.policies.models import Policy, RouteGrant, Scope
from cairn.proposals.models import Approval, Proposal
from cairn.records.continuity import ContextPack, SessionReceipt
from cairn.records.domains import Calculation, FinancialSnapshot, LifeDossier
from cairn.records.migration import (
    MigrationAuthorization,
    MigrationPlan,
    MigrationReceipt,
    MigrationTransaction,
)
from cairn.records.models import Event, Extraction, Record
from cairn.records.release import ReleaseManifest
from cairn.records.runtime import ProbeRequest, ProbeResult, RuntimeApproval, WorkerProfile
from cairn.storage.backup import BackupManifest
from cairn.storage.workspace import WorkspaceConfig, WorkspaceConfigV2


@pytest.mark.parametrize(
    "model",
    [
        DeviceConfig,
        DeviceProbe,
        PaperSummary,
        ReaderJob,
        ReaderResult,
        ReadState,
        VerificationConfig,
        VerificationPacket,
        VerificationResult,
        VerificationState,
        FeedDigest,
        FeedEntry,
        FeedEvent,
        RunnerConfig,
        Publication,
        DiscoveryReport,
        Journal,
        LibraryConfig,
        Paper,
        ScanReport,
        LibraryTransaction,
        Record,
        Extraction,
        Event,
        Policy,
        PolicyChange,
        RouteAudit,
        RouteRequest,
        RouteGrant,
        Scope,
        Job,
        Result,
        ContextPack,
        SessionReceipt,
        BibliographyImport,
        Approval,
        Proposal,
        FinancialSnapshot,
        Calculation,
        LifeDossier,
        BackupManifest,
        ReleaseManifest,
        ProbeRequest,
        ProbeResult,
        WorkerProfile,
        RuntimeApproval,
        WorkspaceConfig,
        WorkspaceConfigV2,
        MigrationAuthorization,
        MigrationPlan,
        MigrationReceipt,
        MigrationTransaction,
    ],
)
def test_export_matches_model(model: type[Record]) -> None:
    version = model.model_fields.get("schema_version")
    number = version.default if version else 1
    name = "workspaceconfig" if model is WorkspaceConfigV2 else model.__name__.lower()
    path = Path(__file__).parents[1] / "schemas" / f"{name}-v{number}.json"
    assert json.loads(path.read_text()) == model.model_json_schema()
