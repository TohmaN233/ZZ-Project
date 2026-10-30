from __future__ import annotations

import json
import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingContractTests(unittest.TestCase):
    def test_home_background_is_present_and_packaged(self) -> None:
        home_image = PROJECT_ROOT / "image.png"
        self.assertTrue(home_image.is_file())
        self.assertGreater(home_image.stat().st_size, 0)

        package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("image.png", package["build"]["files"])
        self.assertIn("!asserts{,/**/*}", package["build"]["files"])
        self.assertTrue(package["build"]["nsis"]["perMachine"])
        self.assertNotIn("data/**/*", package["build"]["files"])
        self.assertIn({"from": "data/decks", "to": "data/decks"}, package["build"]["extraFiles"])
        self.assertNotIn("local_ai_training/retained_mainline_20260630/**/*", package["build"]["files"])
        self.assertTrue(all("codeman_ai" not in pattern and "ai_challenges" not in pattern
                            for pattern in package["build"]["files"]))
        self.assertTrue(
            all("asserts" not in pattern or pattern == "!asserts{,/**/*}"
                for pattern in package["build"]["files"])
        )
        main = (PROJECT_ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        self.assertIn('path.join(path.dirname(process.execPath), "asserts")', main)
        self.assertIn('path.join(primary, "asserts")', main)
        self.assertIn("configuredCandidates", main)
        self.assertIn('"server.log"', main)
        windows_builder = (PROJECT_ROOT / "packaging" / "build_windows_package.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('add_data("image.png", ".")', windows_builder)
        self.assertIn('add_data("zz/ex02c_data.tsv", "zz")', windows_builder)
        self.assertNotIn('add_data("data", "data")', windows_builder)
        self.assertIn("data/ai_training/deep_p2_specialist_v1_latest/best_greedy.pt", windows_builder)
        self.assertIn("best_greedy.runtime.npz", windows_builder)
        self.assertNotIn('add_data("data/decks", "data/decks")', windows_builder)
        self.assertNotIn('add_data("local_ai_training/retained_mainline_20260630", "local_ai_training/retained_mainline_20260630")', windows_builder)

        linux_builder = (PROJECT_ROOT / "packaging" / "build_linux_bundle.py").read_text(
            encoding="utf-8"
        )
        selector_spec = importlib.util.spec_from_file_location(
            "release_files_contract", PROJECT_ROOT / "packaging" / "release_files.py"
        )
        self.assertIsNotNone(selector_spec)
        self.assertIsNotNone(selector_spec.loader)
        selector = importlib.util.module_from_spec(selector_spec)
        selector_spec.loader.exec_module(selector)
        linux_files = selector.release_files(PROJECT_ROOT, "linux")
        multiplayer_files = selector.release_files(PROJECT_ROOT, "multiplayer")
        self.assertIn(Path("zz/ex02c.py"), linux_files)
        self.assertIn(Path("zz/ex02.py"), linux_files)
        self.assertIn(Path("zz/card_identity.py"), linux_files)
        self.assertIn(Path("zz/ex02c_cards/colorless_08_02_02c_00.py"), linux_files)
        self.assertIn(Path("zz/ex02c_data.tsv"), linux_files)
        self.assertIn(Path("data/ex02_ex02c_equivalences.tsv"), linux_files)
        self.assertIn(Path("zz/ex02c.py"), multiplayer_files)
        self.assertIn(Path("zz/ex02.py"), multiplayer_files)
        self.assertIn(Path("zz/ex02c_cards/colorless_08_02_02c_00.py"), multiplayer_files)
        self.assertIn(Path("zz/ex02c_data.tsv"), multiplayer_files)
        self.assertNotIn(selector.DEEP_SOURCE_RELATIVE, linux_files)
        self.assertEqual(selector.DEEP_RUNTIME_RELATIVE.name, "best_greedy.runtime.npz")
        self.assertIn(selector.NORMAL_MODEL_RELATIVE, linux_files)
        self.assertFalse(any(path.parts[0] in {"local_ai_training", "ai_training"}
                             for path in linux_files))
        self.assertFalse(any("codeman_ai" in path.parts for path in linux_files))
        self.assertIn("export_deep_runtime_model", linux_builder)

        installer = (PROJECT_ROOT / "build" / "installer.nsh").read_text(encoding="utf-8")
        self.assertIn("!macro customCheckAppRunning", installer)
        self.assertIn("Get-CimInstance -ClassName Win32_Process", installer)
        self.assertIn("Stop-Process -Id $$_.ProcessId -Force", installer)
        self.assertIn('taskkill.exe" /F /T /IM "ZZ-Project.exe"', installer)
        self.assertIn('taskkill.exe" /F /T /IM "zz-server.exe"', installer)
        self.assertIn('DeleteRegKey HKCU "${UNINSTALL_REGISTRY_KEY}"', installer)
        self.assertIn('DeleteRegKey HKLM "${UNINSTALL_REGISTRY_KEY}"', installer)
        self.assertIn('FileExists} "$INSTDIR\\${APP_EXECUTABLE_FILENAME}"', installer)
        self.assertIn("!macro customRemoveFiles", installer)
        self.assertIn("${If} ${isUpdated}", installer)
        self.assertIn("Keeping existing installation files during update.", installer)

        server = (PROJECT_ROOT / "zz" / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--bundled-deck-root", default=None)', server)
        self.assertIn('self._send_file(self.app.theme_video_path())', server)
        self.assertIn('asset_root / "video" / "OP02.mp4"', server)

        manifest = json.loads(
            (PROJECT_ROOT / "PUBLIC_RELEASE_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["runtimeRootFiles"][0]["path"], "image.png")


if __name__ == "__main__":
    unittest.main()
