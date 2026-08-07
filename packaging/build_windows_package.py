from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
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


def add_data_path(source: Path, destination: str) -> str:
    return f"{source}{__import__('os').pathsep}{destination}"


def export_deep_runtime_model(source: Path, destination: Path) -> None:
    import numpy as np
    import torch

    payload = torch.load(source, map_location="cpu", weights_only=False)
    if payload.get("kind") != "torch_action_value":
        raise ValueError(f"unsupported deep model kind: {payload.get('kind')!r}")
    if payload.get("multitaskHeads") is not None or payload.get("publicDeepV2Architecture") is not None:
        raise ValueError("the current inference-only exporter does not support auxiliary deep heads")
    state_dict = payload.get("stateDict")
    required_keys = {"0.weight", "0.bias", "2.weight", "2.bias"}
    if not isinstance(state_dict, dict) or set(state_dict) != required_keys:
        raise ValueError("deep model state dictionary does not match the supported runtime architecture")
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        format_version=np.asarray(1, dtype=np.int64),
        vectorizer_size=np.asarray(int(payload["vectorizerSize"]), dtype=np.int64),
        hidden_size=np.asarray(int(payload["hiddenSize"]), dtype=np.int64),
        input_weight=state_dict["0.weight"].detach().cpu().numpy().astype(np.float32),
        input_bias=state_dict["0.bias"].detach().cpu().numpy().astype(np.float32),
        output_weight=state_dict["2.weight"].detach().cpu().numpy().astype(np.float32),
        output_bias=state_dict["2.bias"].detach().cpu().numpy().astype(np.float32),
        metadata_json=np.asarray(json.dumps(payload.get("metadata") or {}, ensure_ascii=True)),
    )


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
        # Keep user decks and Codeman memory/training data outside the frozen
        # executable. Only public read-only runtime inputs belong here.
        "--add-data",
        add_data("data/cards_bilingual_v4.tsv", "data"),
        "--add-data",
        add_data("data/forces.tsv", "data"),
        "--add-data",
        add_data("data/official_cardlist.tsv", "data"),
        "--add-data",
        add_data("data/official_filters.tsv", "data"),
        "--add-data",
        add_data("data/ai_training/quality_tactical_latest/best_league.json", "data/ai_training/quality_tactical_latest"),
        "--add-data",
        add_data("image.png", "."),
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
    with tempfile.TemporaryDirectory(prefix="zz-deep-runtime-") as runtime_dir:
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
    ])
    installers = sorted(WINDOWS_DIST.glob("*.exe"))
    if not installers:
        raise FileNotFoundError(f"No Windows installer found in {WINDOWS_DIST}")
    for installer in installers:
        print(f"PACKAGED_INSTALLER={installer} bytes={installer.stat().st_size}")


if __name__ == "__main__":
    main()
