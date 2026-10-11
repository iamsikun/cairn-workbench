"""Bounded native renderer, without workspace policies or proposal execution."""

from pathlib import Path

from cairn.adapters.isolation import bounded_process
from cairn.errors import CairnError, Denied
from cairn.presentation.document import ViewDocument
from cairn.records.models import canonical

RESOURCE = Path(__file__).parent / "resources"


def run_renderer(doc: ViewDocument) -> bytes:
    status, html = bounded_process(
        ["node", str(RESOURCE / "application.mjs")],
        canonical(doc),
        timeout=60,
        stdout_limit=32 * 1024 * 1024,
        env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    if status:
        raise CairnError("application renderer rejected document")
    validate_html(html, doc)
    return html


def validate_html(html: bytes, doc: ViewDocument) -> None:
    # Output is bound to a pinned executable and then checked again by the owner.
    # Browser/DOM policy tests exercise the complete generated document.
    from html.parser import HTMLParser

    class Check(HTMLParser):
        csp = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = dict(attrs)
            if tag in {"iframe", "object", "embed", "base"}:
                raise Denied("renderer returned an embedded document")
            if any(k.startswith("on") or k in {"srcdoc", "action", "formaction"} for k in values):
                raise Denied("renderer returned active attributes")
            if tag == "meta" and values.get("http-equiv") == "Content-Security-Policy":
                content = values.get("content") or ""
                self.csp = "connect-src 'none'" in content and "default-src 'none'" in content
            if values.get("src") and not str(values["src"]).startswith("data:image/"):
                raise Denied("renderer returned a resource dependency")

    check = Check()
    check.feed(html.decode())
    if (
        not check.csp
        or doc.bundle_hash.encode() not in html
        or not html.startswith(b"<!doctype html>")
    ):
        raise Denied("invalid renderer envelope")
