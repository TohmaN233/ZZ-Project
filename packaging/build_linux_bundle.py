from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "linux"
STAGING = OUTPUT / "staging"
EXCLUDED_ROOTS = {".git", "asserts", "dist", "node_modules", "__pycache__"}
EXCLUDED_FILES = {"PUBLIC_RELEASE_MANIFEST.json", "RELEASE_NOTES.md"}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        relative
        for item in result.stdout.decode("utf-8").split("\0")
        if item
        for relative in [Path(item)]
        if relative.parts and relative.parts[0] not in EXCLUDED_ROOTS
        and relative.as_posix() not in EXCLUDED_FILES
    ]


def copy_release_tree(destination: Path) -> None:
    for relative in tracked_files():
        source = ROOT / relative
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    if info.name.endswith("/launch-electron.sh"):
        info.mode = 0o755
    return info


def main() -> None:
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    archive_name = f"ZZ-Project-v{version}-Linux.tar.gz"
    archive_path = OUTPUT / archive_name
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    STAGING.mkdir(parents=True)
    bundle_root = STAGING / f"ZZ-Project-v{version}"
    bundle_root.mkdir()
    copy_release_tree(bundle_root)
    launcher = bundle_root / "launch-electron.sh"
    if not launcher.is_file():
        raise FileNotFoundError(launcher)
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(bundle_root, arcname=bundle_root.name, filter=archive_filter)
    shutil.rmtree(STAGING)
    print(f"LINUX_BUNDLE={archive_path} bytes={archive_path.stat().st_size}")


if __name__ == "__main__":
    main()
