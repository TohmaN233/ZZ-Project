from __future__ import annotations

import importlib.util
import json
import shutil
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("zz_release_files", ROOT / "packaging/release_files.py")
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.mark.parametrize("kind", ["linux", "source", "multiplayer"])
def test_current_product_inventory_includes_untracked_pc02r_rules_and_public_sources(kind):
    files = {path.as_posix() for path in release.release_files(ROOT, kind)}
    cards = {path for path in files if path.startswith("zz/pc02r_cards/") and path != "zz/pc02r_cards/__init__.py"}
    assert len(cards) == 106
    assert {"zz/pc02r_data.tsv", "data/card_transformations.tsv", "data/cards_bilingual_v4.tsv",
            "data/official_cardlist.tsv", "zz/multiplayer/compatibility.json"} <= files
    assert not any(release.FORBIDDEN_PARTS.intersection(Path(path).parts) for path in files)
    assert "新建 文本文档.txt" not in files
    assert "data/settings/settings.json" not in files
    assert "seiso.toml" not in files
    if kind != "multiplayer":
        assert {"electron/asset-bootstrap.js", "electron/asset-setup.html", "electron/asset-source.json",
                "zz/web/static/duel-layout.js", "image.png", "package-lock.json"} <= files
    else:
        assert not any(path.startswith(("electron/", "docs/assets/", "data/ai_training/", "zz/web/static/")) for path in files)
        assert "zz/ai_registry.py" not in files
    if kind == "source":
        assert "tools/run_semantic_scenario.py" in files
        assert "tools/card_translation_exchange.py" in files
        assert "ai_training/codeman_training.py" in files
        assert release.DEEP_SOURCE_RELATIVE.as_posix() in files
        assert len([path for path in files if path.startswith("tests/semantic_scenarios/pc02r/")]) == 212
        assert len([path for path in files if path.startswith("tests/semantic_scenarios/ex02c/")]) == 141
        assert {"tests/test_ex02c_cards.py", "tools/build_ex02c_correspondence.py"} <= files
    else:
        assert release.DEEP_SOURCE_RELATIVE.as_posix() not in files


def fixture_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "product"
    for relative in release.release_files(ROOT, "source"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.as_posix() in {"zz/pc02r.py", "zz/ex02c.py"} or relative.as_posix().startswith("zz/web/static/fx/"):
            shutil.copyfile(ROOT / relative, target)
        else:
            target.write_text("fixture", encoding="utf-8")
    return root


def test_inventory_rejects_missing_required_new_product_file(tmp_path):
    root = fixture_workspace(tmp_path)
    (root / "electron/asset-bootstrap.js").unlink()
    with pytest.raises(FileNotFoundError, match="asset-bootstrap"):
        release.release_files(root, "linux")


def test_inventory_does_not_admit_unrelated_files_in_product_directories(tmp_path):
    root = fixture_workspace(tmp_path)
    unrelated = ("data/private.tsv", "electron/probe.js", "zz/probe.py", "tests/test_private_audit.py",
                 "zz/web/static/fx/unselected.efkefc")
    for name in unrelated:
        (root / name).write_text("must not ship", encoding="utf-8")
    files = {path.as_posix() for path in release.release_files(root, "source")}
    assert files.isdisjoint(unrelated)


def test_copy_fails_if_source_changes_during_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "input.py").write_text("before", encoding="utf-8")
    original_copy = shutil.copy2

    def mutate_after_copy(source, target):
        original_copy(source, target)
        source.write_text("after", encoding="utf-8")

    monkeypatch.setattr(release.shutil, "copy2", mutate_after_copy)
    with pytest.raises(RuntimeError, match="input.py"):
        release.copy_release_tree(root, tmp_path / "snapshot", [Path("input.py")])


def test_staging_cleanup_preserves_existing_versions_and_same_version_artifacts(tmp_path):
    (tmp_path / "package.json").write_text('{"version":"0.4.0"}', encoding="utf-8")
    previous = tmp_path / "dist/releases/v0.3.2/prior.zip"
    same = tmp_path / "dist/releases/v0.4.0/Windows.exe"
    for path in (previous, same):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"existing")
    with release.release_staging(tmp_path, "linux") as (staging, output, version):
        assert version == "0.4.0"
        assert staging.resolve().is_relative_to(output.resolve())
        (staging / "owned").write_bytes(b"temporary")
    assert not staging.exists()
    assert previous.read_bytes() == same.read_bytes() == b"existing"


def test_launcher_has_unix_executable_permissions_in_tar():
    info = tarfile.TarInfo("ZZ-Project-v0.4.0/launch-electron.sh")
    assert release.archive_filter(info).mode == 0o755
    assert release.archive_filter(tarfile.TarInfo("ZZ-Project-v0.4.0/README.md")).mode == 0o644


def test_embedded_manifest_excludes_self_referential_artifact_hashes_only(tmp_path):
    artifact_keys = ("windowsInstaller", "linuxBundle", "sourcePackage", "multiplayerServer")
    manifest = {key: {"filename": f"{key}.zip", "bytes": 12, "sha256": "artifact-hash"} for key in artifact_keys}
    manifest["runtimeRootFiles"] = [{"path": "image.png", "bytes": 12, "sha256": "content-hash"}]
    manifest["runtimeModels"] = [{"path": "model.npz", "bytes": 13, "sha256": "model-hash"}]
    path = tmp_path / "PUBLIC_RELEASE_MANIFEST.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    release.prepare_embedded_manifest(tmp_path)
    actual = json.loads(path.read_text(encoding="utf-8"))
    for key in artifact_keys:
        assert actual[key] == {"filename": f"{key}.zip"}
    assert actual["runtimeRootFiles"] == manifest["runtimeRootFiles"]
    assert actual["runtimeModels"] == manifest["runtimeModels"]
    assert actual["artifactIntegrity"]["checksumFile"] == "SHA256SUMS-PC02.txt"
