import json
from decimal import Decimal
from pathlib import Path

import pytest

from cairn.errors import CairnError, Denied
from cairn.records.models import digest
from cairn.saving.models import NoteChange, Resource, SaveNote
from cairn.saving.retrieval import get_note
from cairn.saving.service import save
from cairn.saving.views import Scenario, feedback, future_value, render
from cairn.saving.workspace import Book


def create(book, **kwargs):
    result = save(
        book,
        "research",
        SaveNote(
            operation_key="create",
            note=NoteChange(
                title="Synthetic notebook",
                markdown="# Intuition\nA learning explanation.",
                kind="topic",
                **kwargs,
            ),
        ),
    )
    return result["notes"][0]


def test_companion_refresh_snapshot_and_failed_render(tmp_path: Path, monkeypatch):
    from cairn.saving import views

    book = Book.init(tmp_path / "book", synthetic=True)
    note = create(book)
    first = render(book, "research", note["id"])
    snapshot = render(book, "research", note["id"], snapshot=True)
    snapshot_bytes = Path(snapshot["path"]).read_bytes()
    assert b"connect-src 'none'" in Path(first["path"]).read_bytes()
    request = SaveNote(
        operation_key="update",
        note=NoteChange(
            id=note["id"],
            expected_revision=note["revision"],
            title="Renamed notebook",
            markdown="New explanation",
        ),
    )
    result = save(book, "research", request)
    assert result["html"] == "current"
    updated = render(book, "research", note["id"])
    assert updated["html_hash"] != first["html_hash"]
    assert Path(snapshot["path"]).read_bytes() == snapshot_bytes
    assert b"New explanation" in Path(updated["path"]).read_bytes()

    def fail(*args):
        raise CairnError("renderer missing")

    monkeypatch.setattr(views, "run_renderer", fail)
    request.operation_key = "failed-render"
    request.note.expected_revision = result["notes"][0]["revision"]
    request.note.markdown = "Saved despite missing renderer"
    assert save(book, "research", request)["html"] == "pending"
    assert Path(updated["path"]).exists()
    assert get_note(book, "research", note["id"])["markdown"] == request.note.markdown
    with pytest.raises(Denied):
        render(book, "finance", note["id"])


def test_synthesis_dependency_and_deterministic_scenario(tmp_path: Path):
    book = Book.init(tmp_path / "book", synthetic=True)
    model = Scenario(
        initial=Decimal("100"),
        annual_contribution=Decimal("10"),
        annual_rate=Decimal("0.1"),
        years=2,
        unit="USD",
    )
    assert future_value(model) == Decimal("142.00")
    assert future_value(model.model_copy(update={"years": 100, "annual_rate": Decimal("1")})) > 0
    body = "# Intuition\nA learning explanation."
    note = create(
        book,
        resources=[
            Resource(
                key="growth",
                kind="scenario",
                title="Illustrative growth",
                content=model.model_dump_json(),
                description="Units: USD; deterministic scenario, not a forecast.",
                synthesis_markdown_hash=digest(body.encode()),
            )
        ],
    )
    first = render(book, "research", note["id"])
    html = Path(first["path"]).read_text()
    assert 'aria-live="polite"' in html and "Controls are temporary" in html and "142.00" in html
    save(
        book,
        "research",
        SaveNote(
            operation_key="changed",
            note=NoteChange(
                id=note["id"],
                expected_revision=note["revision"],
                title="Changed",
                markdown="Changed assumptions",
            ),
        ),
    )
    assert render(book, "research", note["id"])["freshness"] == "needs_synthesis"
    assert Path(first["path"]).read_text() == html


def test_feedback_is_attributed_and_retry_safe(tmp_path: Path):
    book = Book.init(tmp_path / "book", synthetic=True)
    note = create(
        book,
        resources=[
            Resource(
                key="architecture",
                kind="diagram",
                title="Architecture",
                content=json.dumps(["Input", "Encoder", "Output"]),
                description="Synthetic architecture.",
            )
        ],
    )
    view = render(book, "research", note["id"])
    target = next(k for k in view["feedback_targets"] if k.startswith("asset_"))
    data = {
        "schema_version": 1,
        "bundle_id": view["bundle_id"],
        "bundle_hash": view["bundle_hash"],
        "entries": [
            {"target_id": target, "comment": "Explain the encoder", "suggested_text": None}
        ],
    }
    result = feedback(book, "research", data)
    assert feedback(book, "research", data)[0]["id"] == result[0]["id"]
    current = get_note(book, "research", note["id"])
    assert (
        len(current["observations"]) == 1 and "architecture" in current["observations"][0]["text"]
    )
    assert current["markdown"].startswith("# Intuition")
