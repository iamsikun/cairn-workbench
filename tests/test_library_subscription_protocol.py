import json

import pytest
from test_library_reader import response, setup
from test_library_verification_feed import configured

from cairn.errors import Blocked, Denied
from cairn.library import subscriptions, verification
from cairn.library.reader import enqueue, run
from cairn.library.verification_models import VerificationResult
from cairn.proposals.service import approve
from cairn.records.models import canonical, digest


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_structured_official_client_results_are_packet_bound(ws, tmp_path, monkeypatch, provider):
    _, state = configured(ws, tmp_path)
    packet = verification.packet(ws, state)
    checksum = digest(canonical(packet))
    monkeypatch.setattr(subscriptions, "checked_subscription", lambda *args: None)
    calls = []

    def client(command, raw, **kwargs):
        calls.append((command, raw))
        value = VerificationResult(packet_hash=checksum, verdict="supported")
        if provider == "claude":
            return 0, canonical({"subtype": "success", "structured_output": value})
        return 0, canonical(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": canonical(value).decode()},
            }
        )

    monkeypatch.setattr(subscriptions, "bounded_process", client)
    assert subscriptions.verify(provider, "synthetic-model", packet).packet_hash == checksum
    assert len(calls) == 1
    if provider == "claude":
        assert json.loads(calls[0][1])["message"]["role"] == "user"
    else:
        assert "--ignore-user-config" in calls[0][0]


def test_unexpected_codex_tool_call_and_allowance_failure_stop(ws, tmp_path, monkeypatch):
    _, state = configured(ws, tmp_path)
    packet = verification.packet(ws, state)
    monkeypatch.setattr(subscriptions, "checked_subscription", lambda *args: None)
    monkeypatch.setattr(
        subscriptions,
        "bounded_process",
        lambda *args, **kwargs: (
            0,
            canonical({"type": "item.completed", "item": {"type": "command_execution"}}),
        ),
    )
    with pytest.raises(Denied, match="tool operation"):
        subscriptions.verify("codex", "synthetic-model", packet)
    monkeypatch.setattr(subscriptions, "bounded_process", lambda *args, **kwargs: (1, b""))
    with pytest.raises(Blocked, match="allowance"):
        subscriptions.verify("claude", "synthetic-model", packet)


def test_pending_checks_and_missing_export_consent_do_not_approve(ws, tmp_path):
    paper_id, device = setup(ws, tmp_path)
    state = run(ws, enqueue(ws, paper_id, device.id).job.id, transport=response)
    calls = []
    values = verification.verify(ws, client=lambda *args: calls.append(args))
    assert all(value.status == "blocked" for value in values) and not calls
    with pytest.raises(Blocked, match="pending"):
        approve(
            ws,
            state.proposal_id,
            acknowledgements={"evidence_and_interpretation"},
            statement="Synthetic attempted early acceptance",
        )
