"""Synthetic no-mount renderer roundtrip, used by check.sh."""

import base64
import json
import sys

from cairn.presentation.models import RenderJob, ViewBlock, ViewDocument, ViewSection
from cairn.presentation.render import validate_html
from cairn.presentation.service import renderer_identity
from cairn.records.models import canonical, digest


def request() -> RenderJob:
    return RenderJob(
        document=ViewDocument(
            title="Synthetic worker view",
            bundle_id="view_worker",
            bundle_hash="a" * 64,
            subtitle="Synthetic snapshot",
            sections=[
                ViewSection(
                    title="Evidence",
                    blocks=[
                        ViewBlock(text="Value 42 under condition C. <script>hostile()</script>")
                    ],
                )
            ],
            evidence=[],
            targets=[],
        )
    )


if sys.argv[1] == "make":
    sys.stdout.buffer.write(canonical(request()))
else:
    result = json.load(sys.stdin)
    assert result["renderer"] == renderer_identity()
    assert result["document_hash"] == digest(canonical(request().document))
    html = base64.b64decode(result["html"], validate=True)
    validate_html(html, request().document)
    assert b"&lt;script&gt;hostile()&lt;/script&gt;" in html
    print('{"no_mount_html_worker": "passed"}')
