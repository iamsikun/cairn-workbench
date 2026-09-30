from datetime import timedelta
from pathlib import Path

import pytest
from test_library_reader import response, setup

from cairn.errors import Blocked, Denied
from cairn.library import feed, verification
from cairn.library.reader import enqueue, run
from cairn.library.subscriptions import client_env, command
from cairn.library.verification_models import (
    VerificationConfig,
    VerificationFinding,
    VerificationResult,
)
from cairn.proposals.service import validate
from cairn.records.models import canonical, digest, now
from cairn.storage.workspace import Workspace


def configured(ws: Workspace, tmp_path: Path):
    from cairn.library.catalog import get_paper

    paper_id, device = setup(ws, tmp_path)
    with ws.lock():
        journals = get_paper(ws, paper_id, "research")[1].journal_ids
    verification.configure(
        ws,
        VerificationConfig(
            journal_ids=journals,
            valid_until=now() + timedelta(days=30),
            owner_statement="Synthetic packet export consent",
        ),
    )
    state = run(ws, enqueue(ws, paper_id, device.id).job.id, transport=response)
    assert state.status == "completed", state.reason
    return paper_id, state


def test_calibration_failure_and_feed_are_conspicuous(ws: Workspace, tmp_path: Path) -> None:
    paper_id, state = configured(ws, tmp_path)

    def concern(provider, model, packet):
        return VerificationResult(
            packet_hash=digest(canonical(packet)),
            verdict="concerns",
            findings=[
                VerificationFinding(
                    severity="serious",
                    kind="numerical",
                    explanation="Synthetic number mismatch",
                    page=1,
                )
            ],
        )

    checks = verification.verify(ws, client=concern)
    assert {v.provider for v in checks} == {"codex", "claude"}
    assert all(v.status == "completed" for v in checks)
    with pytest.raises(Denied, match="concerns"):
        validate(ws, state.proposal_id)
    event = feed.FeedEvent(id="feed_example", paper_id=paper_id, kind="box_addition", at=now())
    digest_value = feed.save(ws, [event], [], "research")
    assert digest_value and "CHECK FAILED" in digest_value.entries[0].review_state
    assert digest_value.entries[0].reading_status == "unknown"
    assert "CHECK FAILED" in feed.render(digest_value, "atom")
    assert feed.save(ws, [event], [], "research") is None
    feed.acknowledge(ws, digest_value.id, "research")
    assert feed.history(ws, "research")[0].notification == "acknowledged"
    assert feed.history(ws, "finance") == []


def test_exhaustion_queued_without_other_route(ws: Workspace, tmp_path: Path) -> None:
    _, state = configured(ws, tmp_path)
    calls = []

    def exhausted(provider, model, packet):
        calls.append(provider)
        raise Blocked("subscription_allowance_exhausted")

    checks = verification.verify(ws, client=exhausted)
    assert calls == ["codex", "claude"]
    assert all(v.status == "blocked" for v in checks)
    assert state.proposal_id


def test_subscription_tools_and_api_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-not-exported")
    with pytest.raises(Blocked, match="api_environment"):
        client_env()
    monkeypatch.delenv("OPENAI_API_KEY")
    codex = command("codex", "synthetic-model", tmp_path)
    claude = command("claude", "synthetic-model", tmp_path)
    assert "--ignore-user-config" in codex and 'forced_login_method="chatgpt"' in codex
    assert "--safe-mode" in claude and claude[claude.index("--tools") + 1] == ""
    assert "--fallback-model" not in claude and "--bare" not in claude


def test_feed_escapes_untrusted_markup() -> None:
    event = feed.FeedEvent(id="feed_test", paper_id="entity_test", kind="new_publication", at=now())
    value = feed.FeedDigest(
        id="digest_test",
        scope="research",
        at=now(),
        entries=[
            feed.FeedEntry(
                event=event,
                title="<script>attack()</script>",
                citation="[x](javascript:attack)",
                journal_ids=["entity_journal"],
                journals=["<script>"],
                availability="Metadata only",
            )
        ],
    )
    assert "<script>" not in feed.render(value, "html")
    assert "<script>" not in feed.render(value, "atom")
    assert "[x](javascript" not in feed.render(value, "md")
