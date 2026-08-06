from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGING_ROOT = ROOT / "packaging"
SERVER_BUILD = PACKAGING_ROOT / "server-build"
SERVER_DIST = PACKAGING_ROOT / "server-dist"
WINDOWS_DIST = ROOT / "dist" / "windows"


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def add_data(source: str, destination: str) -> str:
    return f"{ROOT / source}{__import__('os').pathsep}{destination}"


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows packaging must run on Windows.")
    for path in (SERVER_BUILD, SERVER_DIST, WINDOWS_DIST):
        if path.exists():
            shutil.rmtree(path)
    SERVER_DIST.mkdir(parents=True, exist_ok=True)
    pyinstaller_command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        "zz-server",
        "--distpath",
        str(SERVER_DIST),
        "--workpath",
        str(SERVER_BUILD),
        "--specpath",
        str(SERVER_BUILD),
        "--paths",
        str(ROOT),
        "--add-data",
        add_data("zz/web/static", "zz/web/static"),
        "--add-data",
        add_data("zz/web/translations", "zz/web/translations"),
        "--add-data",
        add_data("zz/multiplayer/compatibility.json", "zz/multiplayer"),
        "--add-data",
        add_data("docs/rules", "docs/rules"),
        "--add-data",
        add_data("data", "data"),
        "--add-data",
        add_data("local_ai_training/retained_mainline_20260630", "local_ai_training/retained_mainline_20260630"),
    ]
    for module_name in (
        "torch",
        "torchvision",
        "torchaudio",
        "tensorflow",
        "tensorboard",
        "onnxruntime",
        "transformers",
        "scipy",
        "pandas",
        "sklearn",
        "numba",
        "llvmlite",
        "cv2",
        "av",
        "zz.deep_rl",
        "zz.action_q_residual_critic",
        "ai_training",
    ):
        pyinstaller_command.extend(["--exclude-module", module_name])
    pyinstaller_command.append(str(PACKAGING_ROOT / "zz_server_entry.py"))
    run(pyinstaller_command)
    server_executable = SERVER_DIST / "zz-server.exe"
    if not server_executable.is_file():
        raise FileNotFoundError(server_executable)
    run([
        "npx.cmd" if __import__("os").name == "nt" else "npx",
        "electron-builder",
        "--win",
        "nsis",
        "--x64",
        "--publish",
        "never",
    ])
    installers = sorted(WINDOWS_DIST.glob("*.exe"))
    if not installers:
        raise FileNotFoundError(f"No Windows installer found in {WINDOWS_DIST}")
    for installer in installers:
        print(f"PACKAGED_INSTALLER={installer} bytes={installer.stat().st_size}")


if __name__ == "__main__":
    main()
