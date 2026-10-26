"""A runner can disappear between phases without advancing the published edition."""

import json
import shutil

import pytest
from cairn_catalog import cli, publisher_archives
from cairn_catalog import update_catalog as updater


@pytest.fixture
def phased(tmp_path, monkeypatch):
    root = tmp_path / "runner-1" / "catalog"
    root.mkdir(parents=True)
    (root / "raw").mkdir()
    (root / "raw/baseline.json").write_text('"old"')
    (root / "journals.json").write_text("[]")
    (root / "coverage.json").write_text('{"as_of":"2026-10-14","total_entries":1}')
    (root / "update-state.json").write_text('{"crossref_until":"2026-10-14"}')
    (root / "catalog.html").write_text("previous verified edition")
    calls = []

    def fetch(service, stage, *args):
        calls.append(service)
        (stage / "raw" / f"{service}.json").write_text('"new metadata"')
        return [{"provider": service, "added": 1, "changed": 0}]

    def build(_):
        calls.append("build")
        stage = updater.catalog.ROOT
        assert not (stage / "partial.sqlite").exists()
        assert (stage / "raw/openalex.json").exists()
        updater.catalog.atomic_json(
            stage / "coverage.json", {"total_entries": 3, "journal_membership": {}}
        )
        (stage / "catalog.sqlite").write_text("built database")

    def browser(stage, **kwargs):
        calls.append("browser")
        (stage / "catalog.html").write_text("new verified edition")
        return {"assets": "catalog-assets-fixture"}

    def verify(stage):
        calls.append("verify")
        assert (stage / "catalog.sqlite").read_text() == "built database"
        return 37

    monkeypatch.setattr(updater, "refresh_service", fetch)
    monkeypatch.setattr(updater.catalog, "harvest_repec", lambda _: None)
    monkeypatch.setattr(updater.catalog, "harvest_publisher", lambda _: None)
    monkeypatch.setattr(publisher_archives, "harvest_jmlr", lambda _: None)
    monkeypatch.setattr(updater.catalog, "build", build)
    monkeypatch.setattr(updater.catalog, "validate", lambda _: None)
    monkeypatch.setattr(updater.build_browser, "build", browser)
    monkeypatch.setattr(updater.build_browser, "prune_assets", lambda *args: [])
    monkeypatch.setattr(updater.verify_offline, "verify", verify)
    monkeypatch.setattr(updater.personalize, "run", lambda _: {})
    return root, calls


def test_phases_resume_on_another_runner_and_only_publish_after_verification(phased, tmp_path):
    root, calls = phased
    updater.refresh(root, phase="sources", notes=False)
    assert sorted(calls) == ["crossref", "openalex"]
    assert (root / "catalog.html").read_text() == "previous verified edition"
    assert "last_success_at" not in json.loads((root / "update-state.json").read_text())

    # Cache extraction relocates the tree and changes its timestamps.
    restored = tmp_path / "runner-2/catalog"
    shutil.copytree(root, restored, copy_function=shutil.copy)
    updater.refresh(restored, phase="sources", notes=False)
    updater.refresh(restored, phase="build", notes=False)
    assert len(calls) == 4  # two providers, catalog build, browser build
    assert (restored / "catalog.html").read_text() == "previous verified edition"
    assert "verify" not in calls

    final = tmp_path / "runner-3/catalog"
    shutil.copytree(restored, final, copy_function=shutil.copy)
    updater.refresh(final, phase="sources", notes=False)
    updater.refresh(final, phase="build", notes=False)
    result = updater.refresh(final, phase="publish", notes=False)
    assert result["status"] == "success"
    assert calls.count("crossref") == calls.count("openalex") == calls.count("build") == 1
    assert calls.count("verify") == 1
    assert (final / "catalog.html").read_text() == "new verified edition"
    assert json.loads((final / "update-state.json").read_text())["last_success_at"]
    assert not (final / ".refresh-checkpoint/checkpoint.json").exists()


def test_failed_build_reuses_sources_and_discards_partial_outputs(phased, monkeypatch):
    root, calls = phased
    updater.refresh(root, phase="sources", notes=False)
    build = updater.catalog.build

    def fail(_):
        (updater.catalog.ROOT / "partial.sqlite").write_text("interrupted")
        raise RuntimeError("runner interrupted")

    monkeypatch.setattr(updater.catalog, "build", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        updater.refresh(root, phase="build", notes=False)
    checkpoint = json.loads((root / ".refresh-checkpoint/checkpoint.json").read_text())
    assert checkpoint["phase"] == "sources"
    assert (root / "catalog.html").read_text() == "previous verified edition"
    monkeypatch.setattr(updater.catalog, "build", build)
    updater.refresh(root, phase="sources", notes=False)
    updater.refresh(root, phase="build", notes=False)
    assert calls.count("openalex") == calls.count("crossref") == 1


def test_failed_verification_keeps_build_checkpoint_and_old_edition(phased, monkeypatch):
    root, calls = phased
    updater.refresh(root, phase="sources", notes=False)
    updater.refresh(root, phase="build", notes=False)
    verify = updater.verify_offline.verify

    def fail(_):
        raise RuntimeError("query mismatch")

    monkeypatch.setattr(updater.verify_offline, "verify", fail)
    with pytest.raises(RuntimeError, match="query mismatch"):
        updater.refresh(root, phase="publish", notes=False)
    assert (root / "catalog.html").read_text() == "previous verified edition"
    assert "last_success_at" not in json.loads((root / "update-state.json").read_text())
    monkeypatch.setattr(updater.verify_offline, "verify", verify)
    updater.refresh(root, phase="build", notes=False)
    updater.refresh(root, phase="publish", notes=False)
    assert calls.count("build") == 1


def test_delayed_resume_preserves_the_source_collection_time(phased):
    root, _ = phased
    updater.refresh(root, phase="sources", notes=False)
    path = root / ".refresh-checkpoint/checkpoint.json"
    checkpoint = json.loads(path.read_text())
    checkpoint["report"]["sources_completed_at"] = "2026-10-14T12:00:00+00:00"
    path.write_text(json.dumps(checkpoint))
    updater.refresh(root, phase="build", notes=False)
    updater.refresh(root, phase="publish", notes=False)
    state = json.loads((root / "update-state.json").read_text())
    assert state["last_success_at"] == "2026-10-14T12:00:00+00:00"


@pytest.mark.parametrize("change", ["source", "registry", "published"])
def test_checkpoint_from_a_different_baseline_is_refused(phased, change):
    root, calls = phased
    updater.refresh(root, phase="sources", notes=False)
    target, content = {
        "source": ("raw/baseline.json", '"new"'),  # same size, different evidence
        "registry": ("journals.json", '[{"id":"fixture"}]'),
        "published": ("update-state.json", '{"crossref_until":"2026-10-25"}'),
    }[change]
    (root / target).write_text(content)
    with pytest.raises(RuntimeError, match="No compatible source checkpoint"):
        updater.refresh(root, phase="build", notes=False)
    updater.refresh(root, phase="sources", notes=False)
    assert calls.count("crossref") == 2


def test_out_of_order_phase_and_incompatible_cli_flags_are_refused(phased):
    root, _ = phased
    with pytest.raises(RuntimeError, match="No compatible source checkpoint"):
        updater.refresh(root, phase="publish", notes=False)
    updater.refresh(root, phase="sources", notes=False)
    with pytest.raises(RuntimeError, match="No completed build checkpoint"):
        updater.refresh(root, phase="publish", notes=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["update", "--phase", "sources", "--rebuild-only"])
    assert exc.value.code == 2


def test_resuming_completed_phase_does_not_request_duplicate_cache_save(
    phased, tmp_path, monkeypatch
):
    root, _ = phased
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    updater.refresh(root, phase="sources", notes=False)
    assert output.read_text() == "checkpoint=sources\n"
    updater.refresh(root, phase="sources", notes=False)
    assert output.read_text() == "checkpoint=sources\n"
    updater.refresh(root, phase="build", notes=False)
    assert output.read_text().endswith("checkpoint=build\n")
