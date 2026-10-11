"""Native process budgets and retired legacy entrypoints, using synthetic children."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cairn.adapters.isolation import invoke_worker
from cairn.adapters.process import bounded_process
from cairn.errors import Blocked, CairnError
from cairn.library.fetcher import fetch_isolated
from cairn.storage.activation import check_worker, prepare_activation


@pytest.mark.parametrize("mode", ["echo", "timeout", "stdout", "stderr", "closed"])
def test_native_bounded_streams_and_deadline(mode):
    code = {
        "echo": "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
        "timeout": "import time; time.sleep(300)",
        "stdout": "import os; os.write(1,b'PRIVATE-DIAGNOSTIC'*10000)",
        "stderr": "import os; os.write(2,b'PRIVATE-DIAGNOSTIC'*10000)",
        "closed": "import os,time; os.close(1); os.close(2); time.sleep(300)",
    }[mode]
    def run():
        return bounded_process(
            [sys.executable, "-c", code], b"synthetic input", timeout=0.5,
            stdout_limit=1024, stderr_limit=1024,
        )
    if mode == "echo":
        assert run() == (0, b"synthetic input")
    else:
        with pytest.raises(CairnError) as failure:
            run()
        assert "PRIVATE-DIAGNOSTIC" not in str(failure.value)


@pytest.mark.parametrize("parent_exits", [False, True])
def test_owned_descendants_are_killed_even_after_leader_exits(tmp_path: Path, parent_exits):
    pidfile = tmp_path / "child.pid"
    code = (
        "import os,subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "open(sys.argv[1],'w').write(str(p.pid)); "
        + ("sys.exit(0)" if parent_exits else "os.close(1); os.close(2); time.sleep(300)")
    )
    args = ([sys.executable, "-c", code, str(pidfile)], b"")
    if parent_exits:
        assert bounded_process(*args, timeout=2, stdout_limit=100) == (0, b"")
    else:
        with pytest.raises(Blocked, match="process_timeout"):
            bounded_process(*args, timeout=0.5, stdout_limit=100)
    pid = int(pidfile.read_text())
    try:
        for _ in range(100):
            state = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, check=False,
            ).stdout.strip()
            if not state or state.startswith(b"Z"):
                break
            time.sleep(0.02)
        else:
            pytest.fail("owned child survived process cleanup")
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def test_unavailable_program_has_content_free_error(tmp_path):
    with pytest.raises(Blocked, match="^process_unavailable$"):
        bounded_process([str(tmp_path / "missing")], b"secret", timeout=1, stdout_limit=10)


def test_retired_workers_never_launch_or_read(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("retired operation launched a process")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for action in (
        lambda: invoke_worker("unused", b"source bytes"),
        lambda: fetch_isolated(None, "https://example.invalid", set()),
        lambda: check_worker("unused"),
        lambda: prepare_activation(
            tmp_path / "absent", expected_sha256=None, statement=None, acknowledgements=None,
        ),
    ):
        with pytest.raises(Blocked, match="retired"):
            action()
    assert list(tmp_path.iterdir()) == []
