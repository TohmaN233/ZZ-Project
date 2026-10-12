from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

from release_files import (
    DEEP_RUNTIME_RELATIVE, DEEP_SOURCE_RELATIVE, archive_filter, copy_release_tree,
    prepare_embedded_manifest, release_files, release_staging,
)
from runtime_model_export import export_deep_runtime_model


ROOT = Path(__file__).resolve().parents[1]


def build_source_archive(root: Path = ROOT) -> Path:
    files = release_files(root, "source")
    with release_staging(root, "source") as (staging, output, version):
        bundle_root = staging / f"ZZ-Project-v{version}"
        copy_release_tree(root, bundle_root, files)
        prepare_embedded_manifest(bundle_root)
        export_deep_runtime_model(root / DEEP_SOURCE_RELATIVE, bundle_root / DEEP_RUNTIME_RELATIVE)
        archive_path = output / f"ZZ-Project-v{version}-source.zip"
        temporary_archive = staging / archive_path.name
        with zipfile.ZipFile(temporary_archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative in sorted([*files, DEEP_RUNTIME_RELATIVE], key=lambda path: path.as_posix()):
                source = bundle_root / relative
                info = zipfile.ZipInfo.from_file(source, arcname=f"{bundle_root.name}/{relative.as_posix()}")
                mode = 0o755 if relative.as_posix() == "launch-electron.sh" else 0o644
                info.create_system = 3
                info.external_attr = (0o100000 | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, source.read_bytes(), compresslevel=9)
        temporary_archive.replace(archive_path)
    return archive_path


def build_multiplayer_archive(root: Path = ROOT) -> Path:
    files = release_files(root, "multiplayer")
    with release_staging(root, "multiplayer") as (staging, output, version):
        bundle_root = staging / f"ZZ-Multiplayer-v{version}"
        copy_release_tree(root, bundle_root, files)
        prepare_embedded_manifest(bundle_root)
        archive_path = output / f"ZZ-Multiplayer-v{version}.tar.gz"
        temporary_archive = staging / archive_path.name
        with tarfile.open(temporary_archive, "w:gz") as archive:
            archive.add(bundle_root, arcname=bundle_root.name, filter=archive_filter)
        temporary_archive.replace(archive_path)
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build curated source and authoritative server release archives")
    parser.add_argument("--kind", choices=("source", "multiplayer", "all"), default="all")
    args = parser.parse_args()
    builders = (build_source_archive, build_multiplayer_archive) if args.kind == "all" else (
        build_source_archive if args.kind == "source" else build_multiplayer_archive,
    )
    for builder in builders:
        archive_path = builder()
        print(f"RELEASE_ARCHIVE={archive_path} bytes={archive_path.stat().st_size}")


if __name__ == "__main__":
    main()
