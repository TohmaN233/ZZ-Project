from __future__ import annotations

import json
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
        windows_builder = (PROJECT_ROOT / "packaging" / "build_windows_package.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('add_data("image.png", ".")', windows_builder)
        self.assertNotIn('add_data("data", "data")', windows_builder)
        self.assertIn("data/ai_training/deep_p2_specialist_v1_latest/best_greedy.pt", windows_builder)
        self.assertNotIn('add_data("data/decks", "data/decks")', windows_builder)
        self.assertNotIn('add_data("local_ai_training/retained_mainline_20260630", "local_ai_training/retained_mainline_20260630")', windows_builder)

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
