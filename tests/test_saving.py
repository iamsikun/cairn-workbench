import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cairn.errors import Conflict, Denied, RecoveryRequired
from cairn.saving.models import (
    NoteChange,
    Observation,
    Relationship,
    SaveNote,
    SaveReading,
    SourceInput,
)
from cairn.saving.retrieval import get_note, list_topics, search
from cairn.saving.service import recent, save, undo
from cairn.saving.workspace import Book
from cairn.transactions.writer import recover


@pytest.fixture
def book(tmp_path: Path) -> Book:
    return Book.init(tmp_path / "book", synthetic=True)


def request(key: str = "one", **fields) -> SaveNote:
    return SaveNote(
        operation_key=key,
        note=NoteChange(title="Synthetic topic", markdown="evidence 证据", **fields),
    )


def test_save_retry_noop_observations_and_external_edit(book: Book) -> None:
    req = request(observations=[Observation(id="observation_one", text="My question")])
    first = save(book, "research", req)
    assert save(book, "research", req)["id"] == first["id"]
    note = first["notes"][0]
    reread = get_note(book, "research", note["id"])
    second = request("two", id=note["id"], expected_revision=note["revision"])
    assert save(book, "research", second)["status"] == "unchanged"
    assert get_note(book, "research", note["id"])["observations"] == reread["observations"]
    book.fs.write(note["path"], book.fs.read(note["path"]) + b"\nexternal edit")
    with pytest.raises(Conflict):
        save(book, "research", request("three", id=note["id"], expected_revision=note["revision"]))
    assert book.fs.files("recovery/research")


def test_changed_key_conflicts(book: Book) -> None:
    save(book, "research", request())
    with pytest.raises(Conflict):
        save(
            book,
            "research",
            SaveNote(operation_key="one", note=NoteChange(title="Changed", markdown="new")),
        )


def test_paper_followup_topics_scope_and_rejections(book: Book) -> None:
    topic = save(book, "research", request(kind="topic"))["notes"][0]
    private = save(book, "finance", request("private"))["notes"][0]
    reading = SaveReading(
        operation_key="read",
        paper=SourceInput(
            identity="https://doi.org/10.123/demo", title="Example paper", coverage="abstract_only"
        ),
        note=NoteChange(
            title="Reading",
            markdown="A partial explanation",
            relationships=[
                Relationship(target=topic["id"], kind="studies", explanation="Examines this topic")
            ],
        ),
    )
    result = save(book, "research", reading)
    paper = next(n for n in result["notes"] if n["id"].startswith("concept_"))
    assert get_note(book, "research", topic["id"])["backlinks"][0]["id"] == paper["id"]
    follow = reading.model_copy(deep=True)
    follow.operation_key = "follow"
    follow.paper.identity = "doi:10.123/demo"
    follow.note.expected_revision = paper["revision"]
    follow.note.markdown += "\nMore understanding"
    assert save(book, "research", follow)["notes"][0]["id"] == paper["id"]
    assert len(list_topics(book, "research")) == 1
    with pytest.raises(Denied):
        get_note(book, "research", private["id"])
    with pytest.raises(Denied):
        save(
            book,
            "research",
            request(
                "badlink", relationships=[Relationship(target=private["id"], explanation="Hidden")]
            ),
        )
    assert all(x["id"] != private["id"] for x in search(book, "research", "evidence"))
    reject = request(
        "reject",
        id=paper["id"],
        expected_revision=get_note(book, "research", paper["id"])["revision"],
        relationships=[
            Relationship(
                target=topic["id"], explanation="Not relevant", state="rejected", kind="studies"
            )
        ],
    )
    rejected = save(book, "research", reject)["notes"][0]
    with pytest.raises(Conflict):
        save(
            book,
            "research",
            request(
                "reinstate",
                id=paper["id"],
                expected_revision=rejected["revision"],
                relationships=[
                    Relationship(target=topic["id"], explanation="Recreated", kind="studies")
                ],
            ),
        )


def test_bundle_conflict_and_selective_undo(book: Book) -> None:
    first = save(book, "research", request())
    unrelated = save(book, "research", request("other"))
    result = undo(book, "research", first["id"], "undo-one")
    assert undo(book, "research", first["id"], "undo-one")["id"] == result["id"]
    with pytest.raises(Denied):
        get_note(book, "research", first["notes"][0]["id"])
    assert get_note(book, "research", unrelated["notes"][0]["id"])
    assert len(recent(book, "research")) == 3


@pytest.mark.parametrize("point", ["prepared", "write:0", "receipt", "committed"])
def test_real_process_crash_recovery(book: Book, point: str) -> None:
    program = """
import sys
from pathlib import Path
from cairn.saving.workspace import Book
from cairn.saving.models import SaveNote, NoteChange
from cairn.saving.service import save
save(Book(Path(sys.argv[1])), 'research', SaveNote(operation_key='crash',
    note=NoteChange(title='Crash', markdown='Recover me')))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(book.root)],
        env={**os.environ, "CAIRN_SAVE_CRASH_AT": point},
        check=False,
    )
    assert result.returncode == 77
    if point != "committed":
        with pytest.raises(RecoveryRequired):
            search(book, "research", "Recover")
    recover(book)
    assert len(search(book, "research", "Recover")) == 1
    assert len(recent(book, "research")) == 1


def test_recovery_preserves_unexpected_bytes(book: Book, monkeypatch) -> None:
    from cairn.transactions import writer

    def stop(_book, point):
        if point == "prepared":
            raise RuntimeError("crash")

    monkeypatch.setattr(writer, "crash", stop)
    with pytest.raises(RuntimeError):
        save(book, "research", request())
    tx = json.loads(book.fs.read(book.fs.files("journal/saves")[0]))
    book.fs.write(tx["entries"][0]["path"], b"unexpected user content")
    with pytest.raises(Conflict):
        recover(book)
    assert book.fs.read(tx["entries"][0]["path"]) == b"unexpected user content"


def test_index_failure_does_not_lose_save(book: Book, monkeypatch) -> None:
    from cairn.saving import retrieval

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(retrieval, "rebuild", fail)
    result = save(book, "research", request())
    assert result["index"] == "pending"
    assert len(search(book, "research", "证据")) == 1


def test_stale_topic_aborts_entire_reading(book: Book) -> None:
    topic = save(book, "research", request())["notes"][0]
    before = {p: book.fs.read(p) for p in book.fs.files("vault")}
    reading = SaveReading(
        operation_key="stale-topic",
        paper=SourceInput(identity="doi:10.999/a", title="A"),
        note=NoteChange(title="New paper", markdown="Partial reading"),
        topics=[
            NoteChange(
                id=topic["id"], expected_revision="0" * 64, title="Topic", markdown="Stale summary"
            )
        ],
    )
    with pytest.raises(Conflict):
        save(book, "research", reading)
    assert before == {p: book.fs.read(p) for p in book.fs.files("vault")}


def test_two_clients_serialize_and_only_one_revision_wins(book: Book) -> None:
    note = save(book, "research", request())["notes"][0]
    program = """
import sys
from pathlib import Path
from cairn.saving.workspace import Book
from cairn.saving.models import SaveNote, NoteChange
from cairn.saving.service import save
from cairn.errors import Conflict
try:
 save(Book(Path(sys.argv[1])), 'research', SaveNote(operation_key=sys.argv[4],
    note=NoteChange(id=sys.argv[2], expected_revision=sys.argv[3],
        title='Race', markdown=sys.argv[4])))
except Conflict:
 sys.exit(3)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", program, str(book.root), note["id"], note["revision"], key]
        )
        for key in ("client-a", "client-b")
    ]
    assert sorted(p.wait(timeout=30) for p in processes) == [0, 3]
    assert len(recent(book, "research")) == 2


def test_source_versions_aliases_questions_and_quotes(book: Book) -> None:
    from cairn.saving.models import Capture, Citation

    source = SourceInput(
        identity="doi:10.999/paper",
        title="Paper",
        text="Evidence line\nSecond line",
        version="v1",
        coverage="excerpt",
    )
    captured = save(book, "research", Capture(operation_key="capture", source=source))["notes"][0]
    first = save(
        book,
        "research",
        request(
            "question",
            kind="question",
            aliases=["architecture"],
            citations=[Citation(id=captured["id"], quote="Second line", locator="line 2")],
        ),
    )
    assert search(book, "research", "architecture")[0]["id"] == first["notes"][0]["id"]
    with pytest.raises(Denied):
        save(
            book,
            "research",
            request(
                "bad-quote",
                citations=[Citation(id=captured["id"], quote="Second line", locator="line 1")],
            ),
        )
    revised = source.model_copy(update={"version": "v2", "text": "New version"})
    second = save(book, "research", Capture(operation_key="v2", source=revised))["notes"][0]
    assert captured["id"] != second["id"]
    assert get_note(book, "research", captured["id"])["source"]["text"] == source.text


def test_explicit_target_cannot_duplicate_a_paper_identity(book: Book) -> None:
    paper = SourceInput(identity="doi:10.9999/unique", title="Unique synthetic paper")
    first = SaveReading(
        operation_key="first",
        paper=paper,
        note=NoteChange(title=paper.title, markdown="First reading"),
    )
    saved = save(book, "research", first)
    duplicate = SaveReading(
        operation_key="duplicate",
        paper=paper,
        note=NoteChange(id="concept_duplicate", title=paper.title, markdown="Second copy"),
    )
    with pytest.raises(Conflict, match="already has a note"):
        save(book, "research", duplicate)
    assert len([r for _, r, _ in book.records("research").values() if r.paper_identity]) == 1
    assert len(recent(book, "research")) == 1 and saved["status"] == "saved"
