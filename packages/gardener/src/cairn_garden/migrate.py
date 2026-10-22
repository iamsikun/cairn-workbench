"""Move a kb-gardener installation and an in-workspace catalog to the cairn-workbench layout.

`cairn-garden migrate --dry-run` prints the plan. Without it, every step is journaled before it
runs, so `cairn-garden migrate --rollback JOURNAL` can undo a complete or interrupted migration.
Moves are renames on one filesystem: nothing is copied, and nothing is deleted.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import json
import os
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path

from cairn_catalog import paths as catalog_paths

from . import engine as g
from . import workflow

# Settings of kb-gardener 0.4 that no longer exist.
REMOVED = {"workbench_repo", "workbench_label", "publish_upstream", "upstream_sources"}
# Catalog source files that lived beside its data; the package replaces them.
CATALOG_SOURCE = (
    "*.py",
    "test_*.js",
    "Open catalog app.command",
    "browser-template.html",
    "catalog-ui.js",
    "catalog.css",
    "offline-runtime.js",
    "periods.js",
    "fields.json",
    "__pycache__",
)


def old_config_file() -> Path:
    return Path(
        os.environ.get("KB_GARDENER_CONFIG") or Path.home() / ".config/kb-gardener/config.toml"
    )


def old_home() -> Path:
    return Path(os.environ.get("KB_GARDENER_HOME") or Path.home() / ".local/share/kb-gardener")


def toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(f"{json.dumps(str(k))} = {toml_value(v)}" for k, v in value.items())
            + " }"
        )
    raise ValueError(f"cannot write {type(value).__name__} to the config file")


def new_config(old: dict, data_dir: Path, preferences: Path) -> str:
    lines = [
        "# cairn-workbench settings, converted from kb-gardener's config by `cairn-garden migrate`.",
        f"workspace = {toml_value(old.get('workspace', '~/cairn'))}",
        f"collection = {toml_value(old.get('collection', 'research'))}",
        "",
        "[garden]",
    ]
    lines += [
        f"{key} = {toml_value(value)}"
        for key, value in old.items()
        if key not in REMOVED | {"workspace", "collection"}
    ]
    lines += [
        "",
        "[catalog]",
        f"data_dir = {toml_value(str(data_dir))}",
        f"preferences = {toml_value(str(preferences))}",
        "",
    ]
    return "\n".join(lines)


def same_filesystem(source: Path, target: Path) -> bool:
    parent = target
    while not parent.exists():
        parent = parent.parent
    return source.stat().st_dev == parent.stat().st_dev


def plan(workspace: Path | None = None, resources_to: Path | None = None) -> dict:
    """Every step, in order, with the problems that prevent running it."""
    old = tomllib.loads(old_config_file().read_text()) if old_config_file().exists() else {}
    if workspace:
        old["workspace"] = str(workspace)
    steps, problems, notes = [], [], []
    target_config = g.CONFIG_FILE
    # Without a config file these are the defaults (or environment overrides) that it will record.
    data_dir, preferences = catalog_paths.data_dir(), catalog_paths.preferences_file()
    if target_config.exists():
        notes.append(f"{target_config} exists and is kept as it is")
        cfg = g.config()
    else:
        steps.append(
            {
                "op": "write",
                "path": str(target_config),
                "content": new_config(old, data_dir, preferences),
            }
        )
        cfg = {**g.DEFAULTS, **old}
    if not cfg.get("workspace"):
        problems.append("no workspace: pass --workspace or keep kb-gardener's config in place")
        return {"steps": [], "problems": problems, "notes": notes}
    root = Path(cfg["workspace"]).expanduser()
    collection = root / cfg.get("collection", "research")

    def move(source: Path, target: Path, required_empty=True):
        if not source.exists():
            return
        if target.exists() and (
            required_empty and any(target.iterdir()) if target.is_dir() else True
        ):
            problems.append(f"{target} already exists")
        elif not same_filesystem(source, target):
            problems.append(f"{source} and {target} are on different filesystems; move it yourself")
        steps.append({"op": "move", "from": str(source), "to": str(target)})

    agents = Path.home() / "Library/LaunchAgents"
    for plist in sorted(agents.glob("*.kb-gardener.*.plist")):
        steps.append(
            {
                "op": "unload",
                "label": plist.stem,
                "plist": str(plist),
                "content": base64.b64encode(plist.read_bytes()).decode(),
            }
        )
    move(root / ".gardener", g.workspace_state({**cfg, "workspace": str(root)}))
    # The Web API key, if any, is moved unread; the Zotero extension's credential stays in place.
    move(old_config_file().parent / "zotero.key", target_config.parent / "zotero.key")
    # Nothing reads the old settings after this; renamed, they no longer look current.
    move(old_config_file(), old_config_file().with_name(old_config_file().name + ".migrated"))
    for name in ("history", "logs"):
        move(old_home() / name, g.HOME / name)
    catalog = collection / "catalog"
    if catalog.exists():
        if (catalog / "update-pending.json").exists():
            problems.append(
                "the catalog has an interrupted publication; run `cairn-catalog update` first"
            )
        move(catalog, data_dir)
        for name in ("preferences.yaml", "preferences.yaml.bak"):
            if (catalog / name).exists():
                target = (
                    preferences
                    if name == "preferences.yaml"
                    else preferences.with_name(preferences.name + ".bak")
                )
                if target.exists():
                    problems.append(f"{target} already exists")
                elif not same_filesystem(catalog, target):
                    problems.append(
                        f"{catalog} and {target} are on different filesystems; move it yourself"
                    )
                steps.append({"op": "move", "from": str(data_dir / name), "to": str(target)})
        for pattern in CATALOG_SOURCE:
            for path in sorted(catalog.glob(pattern)):
                steps.append(
                    {
                        "op": "move",
                        "from": str(data_dir / path.name),
                        "to": str(data_dir / "legacy-source" / path.name),
                    }
                )
        prefix = str(catalog) + "/"
        mentions = (
            [
                n.slug
                for n in g.cairn().KB(root, cfg.get("collection", "research")).notes().values()
                if prefix in n.path.read_text("utf-8")
            ]
            if (root / ".cairn").exists()
            else []
        )
        if mentions:
            steps.append(
                {"op": "rewrite", "from": prefix, "to": str(data_dir) + "/", "notes": mentions}
            )
    resources = collection / "resources"
    if resources.exists():
        if resources_to:
            move(resources, Path(resources_to).expanduser())
        else:
            notes.append(f"{resources} stays in place: pass --resources-to to move it out")
    for home in (".claude", ".agents"):
        link = Path.home() / home / "skills" / "kb-gardener"
        if link.is_symlink() and Path(os.readlink(link)).is_relative_to(old_home()):
            steps.append(
                {
                    "op": "link",
                    "path": str(link),
                    "to": str(workflow.SKILL),
                    "previous": os.readlink(link),
                }
            )
    return {"steps": steps, "problems": problems, "notes": notes}


@contextlib.contextmanager
def quiet(paths):
    """Hold the gardener's and the catalog's locks, so no run or refresh starts meanwhile."""
    handles = []
    try:
        for path in paths:
            if path.exists():
                handle = path.open("a")
                handles.append(handle)
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError(
                        f"{path} is held: wait for the running workflow or refresh"
                    ) from None
        yield
    finally:
        for handle in handles:
            handle.close()


def perform(step: dict, reverse: bool = False) -> None:
    op = step["op"]
    domain = f"gui/{os.getuid()}"
    if op == "write":
        path = Path(step["path"])
        if reverse:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(step["content"])
    elif op == "move":
        source, target = (
            (Path(step["to"]), Path(step["from"]))
            if reverse
            else (Path(step["from"]), Path(step["to"]))
        )
        if not source.exists():
            return
        if target.is_dir() and not any(target.iterdir()):
            target.rmdir()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError(f"{target} appeared during the migration")
        source.rename(target)
        if reverse and source.parent.is_dir() and not any(source.parent.iterdir()):
            source.parent.rmdir()  # a folder the migration created, such as legacy-source
    elif op == "unload":
        plist = Path(step["plist"])
        if reverse:
            plist.write_bytes(base64.b64decode(step["content"]))
            subprocess.run(["launchctl", "bootstrap", domain, str(plist)], capture_output=True)
        else:
            subprocess.run(
                ["launchctl", "bootout", f"{domain}/{step['label']}"], capture_output=True
            )
            plist.unlink(missing_ok=True)
    elif op == "link":
        link = Path(step["path"])
        link.unlink(missing_ok=True)
        link.symlink_to(step["previous"] if reverse else step["to"], target_is_directory=True)
    elif op == "rewrite":
        cfg = g.config()
        kb = g.kb_open(cfg)
        old, new = (step["to"], step["from"]) if reverse else (step["from"], step["to"])
        for slug in step["notes"]:
            note = kb.resolve(slug)
            if note is not None and old in note.body:
                g.save_note(kb, note, note.body.replace(old, new))


def run(workspace=None, resources_to=None) -> dict:
    proposal = plan(workspace, resources_to)
    if proposal["problems"]:
        return {"migrated": False, **proposal}
    journal = g.HOME / f"migration-{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    record = {"steps": proposal["steps"], "done": 0, "notes": proposal["notes"]}
    g.atomic_json(journal, record)
    cfg_workspace = next(
        (
            Path(tomllib.loads(s["content"])["workspace"]).expanduser()
            for s in proposal["steps"]
            if s["op"] == "write"
        ),
        None,
    )
    root = cfg_workspace or g.workspace(g.config())
    catalog = next(
        (
            Path(s["from"])
            for s in proposal["steps"]
            if s["op"] == "move" and Path(s["from"]).name == "catalog"
        ),
        None,
    )
    locks = [root / ".gardener" / "run.lock", root / ".gardener" / "engine.lock"]
    locks += [catalog / "update.lock"] if catalog else []
    with quiet(locks):
        for step in proposal["steps"]:
            perform(step)
            record["done"] += 1
            g.atomic_json(journal, record)
    return {
        "migrated": True,
        "journal": str(journal),
        "steps": len(proposal["steps"]),
        "notes": proposal["notes"],
        "next": [
            "cairn-garden health",
            "cairn-garden daily",
            "cairn-garden weekly",
            "cairn-garden readiness",
            "cairn-garden schedule --catalog",
        ],
    }


def rollback(journal: Path) -> dict:
    record = json.loads(Path(journal).read_text())
    undone = 0
    for step in reversed(record["steps"][: record["done"]]):
        perform(step, reverse=True)
        undone += 1
        record["done"] -= 1
        g.atomic_json(Path(journal), record)
    return {"rolled_back": undone, "journal": str(journal)}
