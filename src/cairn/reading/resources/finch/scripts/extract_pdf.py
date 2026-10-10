#!/usr/bin/env python3
"""Extract a local PDF with stable page anchors; requires Python 3.9+ and Poppler.

Usage: python3 extract_pdf.py paper.pdf paper.txt
No network access, OCR, Python packages, or automatic dependency installation.
"""

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys


def extract(source: Path) -> list[str]:
    executable = shutil.which("pdftotext")
    if not executable:
        raise ValueError("pdftotext is unavailable; use a host PDF reader or install Poppler")
    with source.open("rb") as stream:
        if b"%PDF-" not in stream.read(1024):
            raise ValueError("input has no PDF header; it may be an HTML download/error page")
    result = subprocess.run(
        [executable, "-layout", "-enc", "UTF-8", str(source.resolve()), "-"],
        capture_output=True, timeout=120,
    )
    if result.returncode:
        raise ValueError("pdftotext failed: " + result.stderr.decode("utf-8", "replace").strip())
    if result.stderr:
        print(result.stderr.decode("utf-8", "replace").strip(), file=sys.stderr)
    text = result.stdout.decode("utf-8")
    if not text.endswith("\f"):
        raise ValueError("extractor returned no final page boundary; use the host PDF reader")
    # Remove only the final delimiter. Empty pages inside the PDF retain their index.
    return text[:-1].split("\f")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, help="new UTF-8 text file (never overwrites)")
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("output already exists; choose a new path")
        pages = extract(args.source)
        digest = hashlib.sha256(args.source.read_bytes()).hexdigest()
        sparse = [i for i, page in enumerate(pages, 1)
                  if sum(not char.isspace() for char in page) < 40]
        header = (
            f"Source: {args.source.resolve()}\nSHA-256: {digest}\n"
            f"PDF pages: {len(pages)} (1-based file order, not printed page numbers)\n"
            "Extraction: pdftotext -layout; verify equations, figures, and tables visually.\n"
            f"Sparse pages (<40 non-whitespace characters): {sparse or 'none'}\n"
            "Sparse text can mean scans, figures, or blank pages; it is not an OCR diagnosis.\n"
        )
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(header)
            for i, page in enumerate(pages, 1):
                stream.write(f"\n===== PDF page {i} =====\n{page.rstrip()}\n")
        print(f"Extracted {len(pages)} pages to {args.output}; sparse pages: {sparse or 'none'}")
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"extract_pdf: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
