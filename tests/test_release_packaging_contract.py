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

        manifest = json.loads(
            (PROJECT_ROOT / "PUBLIC_RELEASE_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["runtimeRootFiles"][0]["path"], "image.png")


if __name__ == "__main__":
    unittest.main()
