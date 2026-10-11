"""Bounded native subprocesses on macOS/Linux; this is not an OS sandbox."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from pathlib import Path

from cairn.errors import Blocked, CairnError

ERROR_LIMIT = 64 * 1024


def bounded_process(
    command: list[str],
    raw: bytes,
    *,
    timeout: float,
    stdout_limit: int,
    stderr_limit: int = ERROR_LIMIT,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[int, bytes]:
    """Drain both pipes without unbounded buffering; never return child diagnostics."""
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
            start_new_session=True,
            bufsize=0,
        )
    except OSError as exc:
        raise Blocked("process_unavailable") from exc
    output = bytearray()
    errors = 0
    offset = 0
    assert process.stdin and process.stdout and process.stderr
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            if raw:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE)
            else:
                process.stdin.close()
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Blocked("process_timeout")
                for key, _ in selector.select(min(remaining, 0.25)):
                    if key.fileobj is process.stdin:
                        try:
                            offset += os.write(key.fd, memoryview(raw)[offset : offset + 65536])
                        except BrokenPipeError:
                            offset = len(raw)
                        if offset == len(raw):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        data = os.read(key.fd, 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                        elif key.fileobj is process.stdout:
                            if len(output) + len(data) > stdout_limit:
                                raise CairnError("process stdout exceeds output budget")
                            output.extend(data)
                        else:
                            errors += len(data)
                            if errors > stderr_limit:
                                raise CairnError("process stderr exceeds diagnostic budget")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Blocked("process_timeout")
            return process.wait(timeout=remaining), bytes(output)
    except subprocess.TimeoutExpired as exc:
        raise Blocked("process_timeout") from exc
    finally:
        # The session belongs to this invocation. Kill descendants even when the
        # leader exited or closed its pipes; never signal the caller's group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
