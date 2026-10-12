from __future__ import annotations

import tarfile
from pathlib import Path

from release_files import (
    DEEP_RUNTIME_RELATIVE,
    DEEP_SOURCE_RELATIVE,
    archive_filter,
    copy_release_tree,
    prepare_embedded_manifest,
    release_files,
    release_staging,
)
from runtime_model_export import export_deep_runtime_model


ROOT = Path(__file__).resolve().parents[1]


def build_linux_bundle(root: Path = ROOT) -> Path:
    files = release_files(root, "linux")
    with release_staging(root, "linux") as (staging, output, version):
        bundle_root = staging / f"ZZ-Project-v{version}"
        copy_release_tree(root, bundle_root, files)
        prepare_embedded_manifest(bundle_root)
        # best_greedy.pt remains a build input; only best_greedy.runtime.npz is
        # shipped to Linux so inference does not require Torch.
        export_deep_runtime_model(root / DEEP_SOURCE_RELATIVE, bundle_root / DEEP_RUNTIME_RELATIVE)
        archive_path = output / f"ZZ-Project-v{version}-Linux.tar.gz"
        temporary_archive = staging / archive_path.name
        with tarfile.open(temporary_archive, "w:gz") as archive:
            archive.add(bundle_root, arcname=bundle_root.name, filter=archive_filter)
        temporary_archive.replace(archive_path)
    return archive_path


def main() -> None:
    archive_path = build_linux_bundle()
    print(f"LINUX_BUNDLE={archive_path} bytes={archive_path.stat().st_size}")


if __name__ == "__main__":
    main()
