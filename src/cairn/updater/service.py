"""Check, build, verify, install and adopt Cairn releases on the owner's machine.

One cycle: refresh the channel mirror; take the channel head if it declares a higher
release number and builds on the current runtime's commit; export that exact tree;
build the worker image and a release bundle for this machine; install it offline into
a new runtime; verify it with its own `release check-runtime`/`check-worker` and a
synthetic smoke run; ask that runtime to rebind each registered knowledge base (backup,
channel re-check, migration); switch `current`; and refresh managed skills. Any failure
leaves `current` and every unchanged knowledge base on the previous runtime. Models
and workers take no part.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from cairn.errors import Blocked, CairnError, Conflict, Denied
from cairn.records.json import read_json
from cairn.records.models import canonical, digest, now
from cairn.records.release import ReleaseManifest
from cairn.records.runtime import tag_version
from cairn.storage.release import verify_bundle
from cairn.updater.home import Busy, Home, RuntimeInfo, UpdaterConfig, bound_release
from cairn.updater.source import ChannelRelease, channel_head, fetch, git, has_commit, is_ancestor

type Runner = Callable[..., subprocess.CompletedProcess[bytes]]
BUILD_TIMEOUT = 3600
KEEP_RUNTIMES = 2


def run_command(
    runner: Runner,
    command: Sequence[str | Path],
    *,
    env: Mapping[str, str],
    cwd: Path | None = None,
    timeout: int = BUILD_TIMEOUT,
) -> bytes:
    try:
        completed = runner(
            [str(item) for item in command],
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked(f"update step unavailable: {Path(str(command[0])).name}") from exc
    if completed.returncode != 0:
        tail = completed.stderr.decode(errors="replace").strip().splitlines()[-3:]
        raise Blocked(f"update step failed: {' '.join(map(str, command[:3]))}: {' | '.join(tail)}")
    return completed.stdout


def environment(config: UpdaterConfig) -> dict[str, str]:
    keep = ("HOME", "TMPDIR", "LANG", "LC_ALL", "DOCKER_HOST", "DOCKER_CONFIG", "CAIRN_HOME")
    env = {key: value for key, value in os.environ.items() if key in keep}
    return env | {"PATH": config.path, "UV_NO_PROGRESS": "1", "CAIRN_NO_AUTO_UPDATE": "1"}


def newest_release(home: Home, config: UpdaterConfig) -> ChannelRelease | None:
    """The channel head, if it is a newer release that fast-forwards the current one."""
    fetch(home.mirror, config.repository, config.ref)
    current = home.current_runtime()
    head = channel_head(home.mirror, config.ref)
    if current is None:
        return head
    if tag_version(head.tag) <= tag_version(current.release_tag):
        return None
    if has_commit(home.mirror, current.commit) and not is_ancestor(
        home.mirror, current.commit, head.commit
    ):
        raise Denied("the update channel was rewritten; stable must only fast-forward")
    return head


def export_tree(home: Home, commit: str, destination: Path) -> None:
    archive = git(home.mirror, "archive", "--format=tar", commit)
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination, filter="data")


def install(
    home: Home, release: ChannelRelease, config: UpdaterConfig, runner: Runner
) -> RuntimeInfo:
    env = environment(config)
    home.runtimes.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".build-", dir=home.runtimes) as temporary:
        source = Path(temporary) / "source"
        export_tree(home, release.commit, source)
        image_tag = f"cairn-worker:{release.tag}"
        build: list[str | Path] = ["docker", "build", "--target", "base", "-t", image_tag, source]
        run_command(runner, build, env=env)
        image = (
            run_command(
                runner, ["docker", "image", "inspect", image_tag, "--format", "{{.Id}}"], env=env
            )
            .decode()
            .strip()
        )
        bundle = Path(temporary) / "bundle"
        run_command(
            runner,
            [
                "uv",
                "run",
                "--frozen",
                "--project",
                source,
                "python",
                "scripts/build_release.py",
                "--output",
                bundle,
                "--revision",
                release.commit,
                "--worker-image",
                image,
            ],
            env=env,
            cwd=source,
        )
        raw = (bundle / "release.json").read_bytes()
        sha = digest(raw)
        manifest = ReleaseManifest.model_validate(read_json(raw))
        if manifest.code_revision != release.commit or manifest.source_hash != release.source_hash:
            raise Conflict("built release does not match the channel source")
        verify_bundle(bundle, expected_sha256=sha)
        interpreter = (source / ".venv" / "bin" / "python").resolve()
        if existing := home.installed(sha):
            return existing
        target = home.runtime(sha)
        if target.exists():
            shutil.rmtree(target)  # An interrupted earlier install; runtime.json was absent.
        target.mkdir(mode=0o700)
        try:
            shutil.move(bundle, target / "bundle")
            venv = target / "venv"
            run_command(
                runner,
                [
                    "uv",
                    "venv",
                    "--no-python-downloads",
                    "--python",
                    interpreter,
                    venv,
                ],
                env=env,
            )
            run_command(
                runner,
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    venv / "bin" / "python",
                    "--offline",
                    "--no-index",
                    "--find-links",
                    target / "bundle" / "wheels",
                    "--only-binary",
                    ":all:",
                    "--require-hashes",
                    "-r",
                    target / "bundle" / "requirements.txt",
                ],
                env=env | {"UV_COMPILE_BYTECODE": "0"},
            )
            python: list[str | Path] = [venv / "bin" / "python", "-I", "-B", "-m", "cairn"]
            manifest_path = target / "bundle" / "release.json"
            checks: list[str | Path] = [
                "release",
                "check-runtime",
                manifest_path,
                "--sha256",
                sha,
                "--json",
            ]
            run_command(runner, [*python, *checks], env=env)
            run_command(runner, [*python, "release", "check-worker", image, "--json"], env=env)
            smoke = Path(temporary) / "smoke"
            run_command(
                runner,
                [
                    *python,
                    "init",
                    "--synthetic",
                    "--no-quill",
                    "--no-finch",
                    "--workspace",
                    smoke / "workspace",
                    "--code-root",
                    source,
                ],
                env=env,
            )
            info = RuntimeInfo(
                release_tag=release.tag,
                commit=release.commit,
                release_sha256=sha,
                worker_image=image,
                installed_at=now(),
            )
            (target / "runtime.json").write_bytes(canonical(info))
            return info
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise


def rebind_all(
    home: Home, info: RuntimeInfo, config: UpdaterConfig, runner: Runner
) -> dict[str, Any]:
    """Ask the new runtime to rebind each registered knowledge base; report each result."""
    results: dict[str, Any] = {}
    python = home.python(info.release_sha256)
    for workspace in config.workspaces:
        if bound_release(Path(workspace)) == info.release_sha256:
            results[workspace] = {"status": "current"}
            continue
        try:
            output = run_command(
                runner,
                [
                    python,
                    "-I",
                    "-B",
                    "-m",
                    "cairn",
                    "update",
                    "rebind",
                    "--workspace",
                    workspace,
                    "--release",
                    home.runtime(info.release_sha256) / "bundle" / "release.json",
                    "--release-sha256",
                    info.release_sha256,
                    "--mirror",
                    home.mirror,
                    "--tag",
                    info.release_tag,
                    "--backup-dir",
                    home.backups,
                ],
                env=environment(config),
            )
            results[workspace] = json.loads(output)
        except (CairnError, ValueError) as exc:
            results[workspace] = {"status": "failed", "reason": str(exc)}
    return results


def collect(home: Home, config: UpdaterConfig, keep: set[str]) -> list[str]:
    """Remove old runtimes no registered knowledge base is still bound to."""
    if not home.runtimes.is_dir():
        return []
    bound = {bound_release(Path(path)) for path in config.workspaces}
    installed = sorted(
        (info for path in home.runtimes.iterdir() if (info := home.installed(path.name))),
        key=lambda info: tag_version(info.release_tag),
        reverse=True,
    )
    retained = {info.release_sha256 for info in installed[:KEEP_RUNTIMES]} | keep | bound
    removed = []
    for info in installed:
        if info.release_sha256 not in retained:
            shutil.rmtree(home.runtime(info.release_sha256))
            removed.append(info.release_tag)
    return removed


def run(
    home: Home,
    *,
    if_due: bool = False,
    runner: Runner = subprocess.run,
    refresh_skills: Callable[[Home, UpdaterConfig], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config = home.config()
    if config is None:
        raise Denied("automatic updates are not set up; run `cairn update setup`")
    state = home.state()
    if not config.enabled:
        return {"status": "disabled"}
    if if_due and not home.due(config, state):
        return {"status": "not_due", "last_check": state.last_check}
    if refresh_skills is None:
        from cairn.updater.skills import refresh

        refresh_skills = refresh
    try:
        with home.lock():
            try:
                result = _cycle(home, config, runner)
            except CairnError as exc:
                result = {"status": "failed", "reason": str(exc)}
            # Skills follow their own upstream even when a Cairn release cannot be built.
            try:
                result["skills"] = refresh_skills(home, config)
            except CairnError as exc:
                result["skills"] = {"status": "failed", "reason": str(exc)}
    except Busy:
        return {"status": "busy"}
    state = home.state()
    state.last_check = now()
    state.last_result = str(result["status"])
    state.errors = [str(result["reason"])] if "reason" in result else []
    if result.get("status") == "updated":
        state.notice = f"Cairn updated to {result['release_tag']} (was {result['previous']})."
        state.notice_shown = False
    home.save_state(state)
    return result


def _cycle(home: Home, config: UpdaterConfig, runner: Runner) -> dict[str, Any]:
    previous = home.current_runtime()
    release = newest_release(home, config)
    if release is None:
        result: dict[str, Any] = {
            "status": "up_to_date",
            "release_tag": previous.release_tag if previous else None,
        }
        if previous:
            # Retry any knowledge base still bound to an older runtime.
            result["workspaces"] = rebind_all(home, previous, config, runner)
        return result
    info = install(home, release, config, runner)
    workspaces = rebind_all(home, info, config, runner)
    home.set_current(info.release_sha256)
    removed = collect(
        home, config, {info.release_sha256} | ({previous.release_sha256} if previous else set())
    )
    return {
        "status": "updated",
        "release_tag": info.release_tag,
        "previous": previous.release_tag if previous else None,
        "workspaces": workspaces,
        "removed_runtimes": removed,
    }
