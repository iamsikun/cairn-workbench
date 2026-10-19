"""The skills Cairn is used with: Finch for reading, Quill for writing, Aster for scouting.

Each skill is independent and installs itself; Cairn runs its own `install.sh` at the version
this release was tested with, with the skill's daily self-update off, so a workbench release
moves all of them together. The gardener's kb-gardener skill is linked by `cairn-garden skill`.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path

PINS = {"finch": "v0.2.2", "quill": "v0.6.0", "aster": "v0.2.1"}
GARDENER = "kb-gardener"
INSTALLER = "https://raw.githubusercontent.com/iamsikun/{name}/{ref}/install.sh"
# Claude Code; the shared folder of Codex, Gemini CLI and Cursor; Copilot; opencode.
AGENT_DIRS = (".claude/skills", ".agents/skills", ".copilot/skills", ".config/opencode/skills")


def clone(name: str) -> Path:
    """Where the skill's installer keeps its clone ($FINCH_HOME and so on)."""
    default = Path.home() / ".local/share" / name
    return Path(os.environ.get(f"{name.upper()}_HOME") or default)


def version(skill_dir: Path) -> str | None:
    try:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    found = re.search(r'^\s+version:\s*"?([^"\s]+)"?\s*$', text, re.M)
    return found.group(1) if found else None


def links(name: str) -> dict[str, str]:
    """Each agent's entry for the skill: its target, or why it is not a working link."""
    found = {}
    for folder in AGENT_DIRS:
        path = Path.home() / folder / name
        if path.is_symlink():
            target = os.readlink(path)
            found[str(path)] = target if path.exists() else f"broken: {target}"
        elif path.exists():
            found[str(path)] = "a folder, not managed by an installer"
    return found


def status() -> list[dict]:
    rows = []
    for name, ref in PINS.items():
        installed = version(clone(name) / "skills" / name)
        entries = links(name)
        rows.append(
            {
                "skill": name,
                "pinned": ref.removeprefix("v"),
                "installed": installed,
                "links": entries,
                "ok": installed == ref.removeprefix("v")
                and bool(entries)
                and not any(v.startswith("broken") for v in entries.values()),
            }
        )
    entries = links(GARDENER)
    working = [Path(p) for p, v in entries.items() if not v.startswith("broken")]
    rows.append(
        {
            "skill": GARDENER,
            "pinned": None,
            "installed": version(working[0].resolve()) if working else None,
            "links": entries,
            "ok": bool(working) and len(working) == len(entries),
        }
    )
    return rows


def plan(names: list[str], remove: bool) -> list[tuple[str, list[str], dict[str, str]]]:
    """(skill, command, extra environment) for each step; a missing installer is downloaded."""
    steps = []
    for name in names:
        if name == GARDENER:
            steps.append((name, ["cairn-garden", "skill", *(["--remove"] if remove else [])], {}))
            continue
        script = clone(name) / "install.sh"
        if remove:
            steps.append((name, ["bash", str(script), "uninstall"], {}))
            continue
        ref = PINS[name]
        source = str(script) if script.exists() else INSTALLER.format(name=name, ref=ref)
        steps.append(
            (name, ["bash", source, "install", "--no-auto-update"], {f"{name.upper()}_REF": ref})
        )
    return steps


def run(names: list[str], remove: bool, dry_run: bool, call) -> int:
    failed = 0
    for name, cmd, env in plan(names, remove):
        assign = [f"{k}={v}" for k, v in env.items()]
        if cmd[1].startswith("https://"):
            shown = ["curl -fsSL", cmd[1], "|", *assign, "bash -s --", *cmd[2:]]
        else:
            shown = [*assign, *cmd]
        print(" ".join(shown), flush=True)
        if dry_run:
            continue
        if name == GARDENER and not shutil.which("cairn-garden"):
            print("cairn: cairn-garden is not installed; skipped kb-gardener")
            continue
        if remove and name != GARDENER and not Path(cmd[1]).exists():
            print(f"cairn: {name} is not installed")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            if cmd[1].startswith("https://"):
                downloaded = Path(tmp) / "install.sh"
                with urllib.request.urlopen(cmd[1], timeout=60) as response:
                    downloaded.write_bytes(response.read())
                cmd = [cmd[0], str(downloaded), *cmd[2:]]
            failed += call(cmd, env={**os.environ, **env}) != 0
    return 1 if failed else 0
