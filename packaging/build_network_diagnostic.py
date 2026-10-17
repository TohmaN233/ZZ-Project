"""Build a small diagnostic package without importing the game runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/multiplayer_network_diagnostic.py"
MANIFEST = ROOT / "zz/multiplayer/compatibility.json"
GUIDE = ROOT / "docs/multiplayer/network-diagnostics.md"
EXECUTABLE_NAME = "ZZ-Network-Diagnostic"

LAUNCHER = """@echo off
setlocal
cd /d "%~dp0"
echo ZZ network diagnostic - approximately 60 seconds.
echo Run with your proxy OFF to collect the direct-connection baseline.
echo This tool ignores application proxies; a VPN/TUN can still affect its route.
"ZZ-Network-Diagnostic.exe" %*
set "ZZ_DIAGNOSTIC_EXIT=%ERRORLEVEL%"
echo.
echo Keep the generated JSON report beside this launcher.
pause
exit /b %ZZ_DIAGNOSTIC_EXIT%
"""


def _zip_directory(source: Path, destination: Path) -> None:
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(source.iterdir()):
            if not path.is_file():
                raise ValueError(f"unexpected package directory: {path.name}")
            archive.write(path, path.name)


def build(output_dir: Path) -> list[Path]:
    if sys.platform != "win32":
        raise RuntimeError("Build the Windows executable on Windows.")
    for source in (SCRIPT, MANIFEST, GUIDE):
        if not source.is_file():
            raise FileNotFoundError(source)
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["applicationVersion"]
    # A fresh destination prevents replacing an earlier evidence/package bundle.
    output_dir.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="zz-network-build-") as scratch:
        scratch_path = Path(scratch)
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                "--onefile", "--console", "--name", EXECUTABLE_NAME,
                "--distpath", str(scratch_path / "dist"),
                "--workpath", str(scratch_path / "work"),
                "--specpath", str(scratch_path),
                "--add-data", f"{MANIFEST};.",
                str(SCRIPT),
            ],
            cwd=ROOT,
            check=True,
        )
        windows = output_dir / "windows"
        windows.mkdir()
        executable = windows / f"{EXECUTABLE_NAME}.exe"
        shutil.copy2(scratch_path / "dist" / executable.name, executable)
        (windows / "Start-Diagnostic.cmd").write_bytes(
            LAUNCHER.replace("\n", "\r\n").encode("ascii")
        )
        shutil.copy2(GUIDE, windows / "README.md")
        source = scratch_path / "source"
        source.mkdir()
        shutil.copy2(SCRIPT, source / SCRIPT.name)
        shutil.copy2(MANIFEST, source / "compatibility.json")
        shutil.copy2(GUIDE, source / "README.md")
        (source / "requirements.txt").write_text("websockets>=16,<17\n", encoding="ascii")
        windows_zip = output_dir / f"ZZ-Network-Diagnostic-v{version}-Windows.zip"
        source_zip = output_dir / f"ZZ-Network-Diagnostic-v{version}-Source.zip"
        _zip_directory(windows, windows_zip)
        _zip_directory(source, source_zip)
    checksums = output_dir / "SHA256SUMS.txt"
    checksums.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (windows_zip, source_zip)
        ),
        encoding="ascii",
    )
    return [windows_zip, source_zip, checksums]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for artifact in build(args.output_dir.resolve()):
        print(artifact)


if __name__ == "__main__":
    main()
