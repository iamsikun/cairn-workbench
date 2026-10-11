import json
from pathlib import Path

import pytest
from test_migration import migrate
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Conflict, Denied
from cairn.records.models import canonical
from cairn.storage.code_source import CHANGES, set_code_source, show
from cairn.storage.migration import inspect, preview
from cairn.storage.streaming_backup import backup, restore
from cairn.storage.workspace import Workspace
from cairn.updater.home import Home, UpdaterConfig

REPOSITORY = "https://example.invalid/synthetic/cairn-workbench.git"


def v2(ws: Workspace) -> Workspace:
    """A workspace written by a runtime that predates schema 3."""
    data = ws.config.model_dump(mode="json")
    data.pop("code_repository")
    data["schema_version"] = 2
    ws.fs.write("workspace.json", canonical(data))
    return Workspace(ws.root)


def test_repository_only_workspace_has_no_checkout_guard(tmp_path: Path) -> None:
    ws = Workspace.init(tmp_path / "private", code_repository=REPOSITORY, synthetic=True)
    assert ws.config.schema_version == 3
    assert ws.config.code_roots == [] and ws.config.code_repository == REPOSITORY
    reopened = Workspace(ws.root)
    assert reopened.config == ws.config
    assert backup(reopened, tmp_path / "anywhere" / "backup.zip")["files"]
    with pytest.raises(Denied, match="repository or a local code root"):
        Workspace.init(tmp_path / "unnamed", synthetic=True)
    assert not (tmp_path / "unnamed").exists()


def test_git_ancestor_check_applies_without_a_code_root(tmp_path: Path) -> None:
    checkout = tmp_path / "some-checkout"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(Denied, match="development checkout"):
        Workspace.init(checkout / "private", code_repository=REPOSITORY, synthetic=True)
    assert not (checkout / "private").exists()


def test_configured_code_root_still_guards_outputs(tmp_path: Path) -> None:
    code = tmp_path / "public-code"
    code.mkdir()
    ws = Workspace.init(
        tmp_path / "private", code_roots=[code], code_repository=REPOSITORY, synthetic=True
    )
    with pytest.raises(Denied, match="public code"):
        backup(ws, code / "backup.zip")
    with pytest.raises(Denied, match="disjoint"):
        Workspace.init(code / "nested", code_repository=REPOSITORY, code_roots=[code])


def test_cli_init_defaults_repository_from_managed_updater(tmp_path: Path) -> None:
    Home.from_env().save_config(UpdaterConfig(repository=REPOSITORY))
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--workspace", str(tmp_path / "private"), "--synthetic"])
    assert result.exit_code == 0, result.output
    config = Workspace(tmp_path / "private").config
    assert config.code_roots == [] and config.code_repository == REPOSITORY
    other = "/synthetic/local-mirror.git"
    result = runner.invoke(
        app,
        ["init", "--workspace", str(tmp_path / "explicit"), "--synthetic", "--repository", other],
    )
    assert result.exit_code == 0, result.output
    assert Workspace(tmp_path / "explicit").config.code_repository == other


def test_cli_init_without_updater_requires_a_code_source(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["init", "--workspace", str(tmp_path / "private"), "--synthetic"]
    )
    assert result.exit_code != 0
    assert "repository or a local code root" in result.output
    assert not (tmp_path / "private").exists()


def test_schema_2_workspace_stays_valid_and_migrates_to_3(ws: Workspace, tmp_path: Path) -> None:
    roots = ws.config.code_roots
    ws = v2(ws)
    assert ws.config.schema_version == 2 and ws.config.code_roots == roots
    assert inspect(ws)["migration_available"] is True
    assert preview(ws).operation == "workspace_v2_to_v3"
    with pytest.raises(Denied, match="schema 3"):
        set_code_source(ws, code_roots=None, repository=REPOSITORY, statement="Synthetic.")
    migrate(ws, tmp_path)
    ws = Workspace(ws.root)
    assert ws.config.schema_version == 3
    assert ws.config.code_roots == roots and ws.config.code_repository is None
    assert inspect(ws)["migration_available"] is False
    backup(ws, tmp_path / "after.zip")
    restored = restore(tmp_path / "after.zip", tmp_path / "restored", synthetic=True)
    assert restored.config.code_roots == roots


def test_owner_replaces_code_source_with_receipt(ws: Workspace, tmp_path: Path) -> None:
    before = ws.fs.read("workspace.json")
    change = set_code_source(
        ws, code_roots=[], repository=REPOSITORY, statement="Checkout removed; use the repo."
    )
    assert show(Workspace(ws.root)) == {
        "workspace_id": ws.config.id,
        "workspace_schema": 3,
        "code_roots": [],
        "code_repository": REPOSITORY,
    }
    assert ws.fs.files(CHANGES) == [f"{CHANGES}/{change.id}.json"]
    assert change.before_code_roots == [str(tmp_path / "public-code")]
    assert change.after_code_roots == [] and change.after_code_repository == REPOSITORY
    assert ws.fs.read("workspace.json") != before
    with pytest.raises(Conflict, match="unchanged"):
        set_code_source(ws, code_roots=None, repository=REPOSITORY, statement="Again.")
    with pytest.raises(Denied, match="repository or a local code root"):
        set_code_source(
            ws, code_roots=None, repository=None, clear_repository=True, statement="None."
        )
    checkout = tmp_path / "new-checkout"
    checkout.mkdir()
    set_code_source(
        ws, code_roots=[checkout], repository=None, clear_repository=True, statement="Local."
    )
    assert ws.config.code_roots == [str(checkout.resolve())]
    assert ws.config.code_repository is None
    with pytest.raises(Denied, match="public code"):
        backup(ws, checkout / "backup.zip")
    backup(ws, tmp_path / "with-receipts.zip")
    restored = restore(tmp_path / "with-receipts.zip", tmp_path / "restored", synthetic=True)
    assert len(restored.fs.files(CHANGES)) == 2


def test_new_code_root_must_stay_disjoint(ws: Workspace, tmp_path: Path) -> None:
    from cairn.library.catalog import configure
    from cairn.library.models import LibraryConfig

    before = ws.fs.read("workspace.json")
    with pytest.raises(Denied, match="disjoint"):
        set_code_source(ws, code_roots=[ws.root.parent], repository=None, statement="Overlap.")
    library = tmp_path / "outer" / "library"
    library.mkdir(parents=True)
    configure(ws, LibraryConfig(root=str(library)))
    with pytest.raises(Denied, match="library or HTML output"):
        set_code_source(
            ws, code_roots=[tmp_path / "outer"], repository=None, statement="Covers library."
        )
    assert ws.fs.read("workspace.json") == before
    assert not ws.fs.files(CHANGES)


def test_backup_rejects_foreign_code_source_receipt(ws: Workspace, tmp_path: Path) -> None:
    change = set_code_source(ws, code_roots=None, repository=REPOSITORY, statement="Repo.")
    path = f"{CHANGES}/{change.id}.json"
    data = json.loads(ws.fs.read(path))
    data["workspace_id"] = "workspace_other"
    ws.fs.write(path, canonical(data))
    with pytest.raises(Conflict, match="code source receipt"):
        backup(ws, tmp_path / "invalid.zip")


def test_restore_keeps_or_replaces_code_source(ws: Workspace, tmp_path: Path) -> None:
    backup(ws, tmp_path / "v3.zip")
    kept = restore(tmp_path / "v3.zip", tmp_path / "kept", synthetic=True)
    assert kept.config.code_roots == ws.config.code_roots
    replaced = restore(
        tmp_path / "v3.zip",
        tmp_path / "replaced",
        code_roots=[],
        code_repository=REPOSITORY,
        synthetic=True,
    )
    assert replaced.config.code_roots == [] and replaced.config.code_repository == REPOSITORY
    with pytest.raises(Denied, match="disjoint"):
        restore(
            tmp_path / "v3.zip",
            tmp_path / "public-code" / "inside",
            synthetic=True,
        )
    legacy = v2(kept)
    backup(legacy, tmp_path / "v2.zip")
    with pytest.raises(Denied, match="schema 3"):
        restore(
            tmp_path / "v2.zip", tmp_path / "v2-repo", code_repository=REPOSITORY, synthetic=True
        )
    with pytest.raises(Denied, match="requires a local code root"):
        restore(tmp_path / "v2.zip", tmp_path / "v2-empty", code_roots=[], synthetic=True)
    assert not (tmp_path / "v2-repo").exists() and not (tmp_path / "v2-empty").exists()
    assert restore(tmp_path / "v2.zip", tmp_path / "v2", synthetic=True).config.schema_version == 2


def test_cli_code_source_is_an_owner_command(
    ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    base = ["code-source", "set", "--workspace", str(ws.root), "--statement", "Synthetic."]
    result = runner.invoke(app, [*base, "--code-root", str(tmp_path), "--no-code-root"])
    assert result.exit_code != 0 and "either" in result.output
    monkeypatch.delenv("CAIRN_SYNTHETIC_OWNER")
    monkeypatch.setattr("cairn.cli.commands._terminal", lambda: (_ for _ in ()).throw(OSError()))
    result = runner.invoke(app, [*base, "--repository", REPOSITORY])
    assert result.exit_code != 0 and "owner command" in result.output
    monkeypatch.setenv("CAIRN_SYNTHETIC_OWNER", "1")
    result = runner.invoke(app, [*base, "--no-code-root", "--repository", REPOSITORY, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["after_code_repository"] == REPOSITORY
    shown = runner.invoke(app, ["code-source", "show", "--workspace", str(ws.root), "--json"])
    assert json.loads(shown.stdout)["code_roots"] == []
