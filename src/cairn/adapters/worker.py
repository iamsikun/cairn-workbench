"""Unprivileged worker: one JSON job in, one JSON result out; no owner APIs."""

import sys

from cairn.adapters.fake import FakeProvider
from cairn.adapters.protocol import Job
from cairn.records.models import canonical


def main() -> None:
    raw = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
    try:
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("job too large")
        job = Job.model_validate_json(raw)
        if job.provider != "fake-v1" or job.route != "local":
            raise ValueError("unsupported local provider")
        sys.stdout.buffer.write(canonical(FakeProvider().generate(job)))
    except Exception:
        # Never send untrusted/private exception text into generic diagnostics.
        sys.stderr.write("worker rejected job\n")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
