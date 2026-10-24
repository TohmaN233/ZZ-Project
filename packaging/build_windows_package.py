from __future__ import annotations

import shutil
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGING_ROOT = ROOT / "packaging"
SERVER_BUILD = PACKAGING_ROOT / "server-build"
SERVER_DIST = PACKAGING_ROOT / "server-dist"
VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
WINDOWS_DIST = ROOT / "dist" / "windows" / f"v{VERSION}"
RELEASE_DIST = ROOT / "dist" / "releases" / f"v{VERSION}"


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def add_data(source: str, destination: str) -> str:
    return f"{ROOT / source}{__import__('os').pathsep}{destination}"


def add_data_path(source: Path, destination: str) -> str:
    return f"{source}{__import__('os').pathsep}{destination}"


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows packaging must run on Windows.")
    for path in (SERVER_BUILD, SERVER_DIST, WINDOWS_DIST):
        resolved = path.resolve()
        if not resolved.is_relative_to(ROOT.resolve()) or resolved == ROOT.resolve():
            raise ValueError(f"Unsafe packaging cleanup path: {resolved}")
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
        "--collect-submodules",
        "zz.pc02r_cards",
        "--collect-submodules",
        "zz.ex02c_cards",
        "--add-data",
        add_data("zz/pc02r_data.tsv", "zz"),
        "--add-data",
        add_data("zz/web/static", "zz/web/static"),
        "--add-data",
        add_data("zz/web/translations", "zz/web/translations"),
        "--add-data",
        add_data("zz/multiplayer/compatibility.json", "zz/multiplayer"),
        "--add-data",
        add_data("docs/rules", "docs/rules"),
        # Keep user decks and Codeman memory/training data outside the frozen
        # executable. Only public read-only runtime inputs belong here.
        "--add-data",
        add_data("data/ai_training/quality_tactical_latest/best_league.json", "data/ai_training/quality_tactical_latest"),
        "--add-data",
        add_data("image.png", "."),
    ]
    from release_files import PUBLIC_TSVS

    for filename in PUBLIC_TSVS:
        source = ROOT / "data" / filename
        if not source.is_file():
            raise FileNotFoundError(source)
        pyinstaller_command.extend(["--add-data", add_data_path(source, "data")])
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
    with tempfile.TemporaryDirectory(prefix="zz-deep-runtime-") as runtime_dir:
        if str(PACKAGING_ROOT) not in sys.path:
            sys.path.insert(0, str(PACKAGING_ROOT))
        from runtime_model_export import export_deep_runtime_model

        runtime_model_path = Path(runtime_dir) / "best_greedy.runtime.npz"
        export_deep_runtime_model(
            ROOT / "data/ai_training/deep_p2_specialist_v1_latest/best_greedy.pt",
            runtime_model_path,
        )
        pyinstaller_command.extend([
            "--add-data",
            add_data_path(runtime_model_path, "data/ai_training/deep_p2_specialist_v1_latest"),
        ])
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
        f"--config.directories.output={WINDOWS_DIST}",
    ])
    installers = sorted(WINDOWS_DIST.glob("*.exe"))
    if not installers:
        raise FileNotFoundError(f"No Windows installer found in {WINDOWS_DIST}")
    for installer in installers:
        RELEASE_DIST.mkdir(parents=True, exist_ok=True)
        destination = RELEASE_DIST / installer.name
        shutil.copy2(installer, destination)
        print(f"PACKAGED_INSTALLER={destination} bytes={destination.stat().st_size}")


if __name__ == "__main__":
    main()
