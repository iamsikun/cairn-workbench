"""Recoverable direct writer. Callers hold Book.lock; no approval machinery."""

import os

from cairn.errors import Conflict, Denied
from cairn.records.models import canonical, digest
from cairn.saving.models import SaveReceipt, SaveTransaction
from cairn.saving.workspace import Book, decode


def crash(book: Book, point: str) -> None:
    if book.config.synthetic and os.environ.get("CAIRN_SAVE_CRASH_AT") == point:
        os._exit(77)


def complete(book: Book, tx: SaveTransaction) -> SaveReceipt:
    book.collection(tx.collection)
    if tx.id != tx.receipt.id or tx.collection != tx.receipt.collection:
        raise Denied("invalid transaction identity")
    paths = set()
    for entry in tx.entries:
        if entry.path in paths or not entry.path.startswith(f"vault/collections/{tx.collection}/"):
            raise Denied("invalid transaction destination")
        paths.add(entry.path)
        record, _ = decode(entry.after.encode())
        if record.collection != tx.collection or entry.path.rsplit("/", 1)[-1] != record.id + ".md":
            raise Denied("transaction path and record disagree")
        raw = book.fs.read(entry.path).decode() if book.fs.exists(entry.path) else None
        if raw not in (entry.before, entry.after):
            raise Conflict("recovery conflicts with an external edit; bytes preserved")
    planned = {entry.path: digest(entry.after.encode()) for entry in tx.entries}
    for note in tx.receipt.notes:
        if not note.path.startswith(f"vault/collections/{tx.collection}/"):
            raise Denied("receipt target is outside the transaction collection")
        revision = planned.get(note.path)
        if revision is None:
            revision = book.revision(note.path)
        if revision != note.revision:
            raise Conflict("receipt target changed before transaction completion")
    for index, entry in enumerate(tx.entries):
        book.fs.write(entry.path, entry.after.encode())
        crash(book, f"write:{index}")
    for note in tx.receipt.notes:
        if (
            not note.path.startswith(f"vault/collections/{tx.collection}/")
            or book.revision(note.path) != note.revision
        ):
            raise Conflict("receipt does not match committed bytes")
    receipt_path = f"revisions/{tx.collection}/{tx.receipt.operation_hash}.json"
    raw_receipt = canonical(tx.receipt)
    if book.fs.exists(receipt_path) and book.fs.read(receipt_path) != raw_receipt:
        raise Conflict("operation receipt changed")
    book.fs.write(receipt_path, raw_receipt)
    crash(book, "receipt")
    tx.status = "committed"
    book.fs.write(f"journal/saves/{tx.id}.json", canonical(tx))
    crash(book, "committed")
    return tx.receipt


def commit(book: Book, tx: SaveTransaction) -> SaveReceipt:
    for entry in tx.entries:
        current = book.fs.read(entry.path).decode() if book.fs.exists(entry.path) else None
        if current != entry.before:
            raise Conflict("target changed before preparation")
    book.fs.write(f"journal/saves/{tx.id}.json", canonical(tx), exclusive=True)
    crash(book, "prepared")
    return complete(book, tx)


def recover(book: Book) -> list[str]:
    recovered = []
    with book.lock(recovery=True):
        for path in book.fs.files("journal/saves"):
            tx = SaveTransaction.model_validate_json(book.fs.read(path))
            if tx.status == "prepared":
                complete(book, tx)
                recovered.append(tx.id)
        from cairn.saving.retrieval import rebuild

        for collection in book.config.collections:
            rebuild(book, collection)
    return recovered


def operation_hash(collection: str, key: str) -> str:
    return digest(canonical([collection, key]))
