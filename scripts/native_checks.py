"""Native synthetic acceptance. Dependency acquisition is a separate, explicit phase.

Checks inherit executable paths, not credentials or owner configuration. This runner
is not an OS sandbox. A rejecting Docker sentinel verifies that no check uses Docker.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT / ".venv/bin/python")


def run(args: list[str | Path], env: dict[str, str], *, cwd: Path = ROOT,
        output: Path | None = None) -> None:
    command = [str(arg) for arg in args]
    print("Checking: " + " ".join(command[:4]), file=sys.stderr, flush=True)
    if output is None:
        subprocess.run(command, env=env, cwd=cwd, check=True, timeout=1800)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as stream:
            subprocess.run(command, env=env, cwd=cwd, check=True, stdout=stream, timeout=1800)


def environment(scratch: Path) -> dict[str, str]:
    env = {key: os.environ[key] for key in (
        "PATH", "LANG", "LC_ALL", "AM_CHROME", "CAIRN_NODE20", "CAIRN_NODE22", "CAIRN_NODE24",
    ) if key in os.environ}
    env.update({
        "PATH": str(ROOT / ".venv/bin") + os.pathsep + env.get("PATH", os.defpath),
        "TMPDIR": str(scratch), "CAIRN_HOME": str(scratch / "cairn-state"),
        "XDG_CONFIG_HOME": str(scratch / "config"), "XDG_CACHE_HOME": str(scratch / "cache"),
        "XDG_DATA_HOME": str(scratch / "data"), "AM_HOME": str(scratch / "renderer-state"),
        "AM_NO_OPEN": "1", "AM_NO_UPDATE_CHECK": "1", "CAIRN_NO_AUTO_UPDATE": "1",
        "CAIRN_SYNTHETIC_OWNER": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "UV_NO_CONFIG": "1", "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never",
        "UV_CACHE_DIR": str(ROOT / ".cache/uv"),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "NPM_CONFIG_USERCONFIG": os.devnull,
    })
    tools = scratch / "tools"
    tools.mkdir()
    sentinel = tools / "docker"
    sentinel.write_text('#!/bin/sh\nprintf "Docker execution is retired\\n" >&2\n'
                        f'touch "{scratch / "docker-used"}"\nexit 99\n')
    sentinel.chmod(0o755)
    env["PATH"] = str(tools) + os.pathsep + env["PATH"]
    return env


def code(env: dict[str, str], scratch: Path) -> None:
    run([PYTHON, "-m", "pytest", "-q"], env)
    run([PYTHON, "-m", "ruff", "check", "src", "tests", "scripts"], env)
    run([PYTHON, "-m", "mypy"], env)
    run([PYTHON, "scripts/prepare_continuity.py", "--output", scratch / "continuity"], env)
    run([PYTHON, "scripts/evaluate_goldset.py", "--output", ROOT / "dist/native-goldset.json"], env)
    run([PYTHON, "scripts/library_backup_trial.py"], env,
        output=ROOT / "dist/native-library-backup.json")


def html(env: dict[str, str], scratch: Path) -> None:
    node = shutil.which("node", path=env["PATH"])
    if not node or subprocess.check_output([node, "--version"], env=env).split(b".")[0] != b"v24":
        raise SystemExit("HTML checks require Node 24 on PATH; acquire it before checking.")
    for program in ("ffmpeg", "ffprobe", "say" if sys.platform == "darwin" else "espeak-ng"):
        if not shutil.which(program, path=env["PATH"]):
            raise SystemExit(f"Acquire {program} before the full renderer regression suite.")
    for version in (20, 22, 24):
        key = f"CAIRN_NODE{version}"
        executable = env.get(key) or (node if version == 24 else shutil.which(f"node{version}"))
        if not executable or not Path(executable).is_file():
            raise SystemExit(f"Set {key} to a Node {version} executable before HTML checks.")
        if subprocess.check_output([executable, "--version"], env=env).split(b".")[0] != (
            f"v{version}".encode()
        ):
            raise SystemExit(f"{key} must select Node {version}.")
        env[key] = str(Path(executable).resolve())
    vendor = ROOT / "vendor/answer-me-with-html"
    if not (vendor / "node_modules/esbuild").is_dir():
        raise SystemExit("Acquire renderer dependencies: cd vendor/answer-me-with-html && "
                         "npm ci --ignore-scripts")
    work = scratch / "renderer"
    shutil.copytree(vendor, work, ignore=shutil.ignore_patterns("node_modules", "dist", ".git"))
    (work / "node_modules").symlink_to(
        (vendor / "node_modules").resolve(), target_is_directory=True
    )
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    for name in ("first", "second"):
        run([node, "scripts/build-application.mjs", scratch / f"{name}.mjs"], env, cwd=work)
    generated = (scratch / "first.mjs").read_bytes()
    assert generated == (scratch / "second.mjs").read_bytes()
    assert generated == (ROOT / "src/cairn/presentation/resources/application.mjs").read_bytes()
    run([node, "scripts/build.mjs"], env, cwd=work)
    generic = (work / "skills/answer-me-with-html/scripts/am.mjs").read_bytes()
    run([node, "scripts/build.mjs"], env, cwd=work)
    assert generic == (work / "skills/answer-me-with-html/scripts/am.mjs").read_bytes()
    assert generic == (vendor / "skills/answer-me-with-html/scripts/am.mjs").read_bytes()
    env.update(AM_E2E="1", AM_BROWSER_OUTPUT=str(out / "browser-html"))
    tests = sorted((work / "test").glob("*.test.js"))
    run([node, "--test", "--test-concurrency=2", "--test-timeout=180000", *tests], env,
        cwd=work, output=out / "renderer-tests.log")
    run([node, "scripts/smoke-portable.mjs"], env, cwd=work,
        output=out / "generic-node-smoke.json")
    for name in ("cairn-html.zip", "cairn-html-repeat.zip"):
        run([PYTHON, "scripts/package_html.py", "--output", out / name], env)
    assert (out / "cairn-html.zip").read_bytes() == (out / "cairn-html-repeat.zip").read_bytes()
    installed = scratch / "installed"
    with zipfile.ZipFile(out / "cairn-html.zip") as archive:
        archive.extractall(installed)
    run([node, "scripts/html_smoke.mjs", installed / "cairn-html"], env,
        output=out / "html-node-smoke.json")
    run([PYTHON, "scripts/notebook_demo.py", "--output", out / "notebook-demo"], env)
    run([node, "scripts/notebook_browser.mjs", out / "notebook-demo"], env)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cairn-native-check-") as directory:
        scratch = Path(directory).resolve()
        env = environment(scratch)
        mode = sys.argv[1]
        if mode == "code":
            code(env, scratch)
        elif mode == "html":
            html(env, scratch)
        elif mode == "acquire-release":
            env.pop("UV_OFFLINE")
            run([PYTHON, "scripts/build_release.py", "--output", sys.argv[2],
                 "--revision", sys.argv[3]], env)
        elif mode == "release":
            bundle = Path(sys.argv[2])
            run([PYTHON, "scripts/release_trial.py", bundle], env, output=bundle / "trial.json")
        else:
            raise SystemExit(f"Unknown check mode: {mode}")
        assert not (scratch / "docker-used").exists(), "a check attempted Docker execution"
        print(json.dumps({"native_check": mode, "status": "passed", "docker": "unused"}))


if __name__ == "__main__":
    main()
