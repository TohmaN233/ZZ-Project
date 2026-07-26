from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from zz.cards import CARD_REGISTRY
from zz.decks import is_user_deck_card_id
from zz.forces import ALL_FORCES
from zz.web.assets import BATTLE_SFX_AUDIO_NAMES, AssetIndex
from zz.web.profiles import character_catalog, home_guide_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = Path(os.environ.get("ZZ_RELEASE_ASSET_ROOT", PROJECT_ROOT / "asserts")).resolve()
HAS_CLEAN_LAYOUT = (ASSET_ROOT / "images" / "clean_graph" / "ui").is_dir()


@unittest.skipUnless(HAS_CLEAN_LAYOUT, "clean release asset pack is not installed")
class CleanReleaseAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = AssetIndex(ASSET_ROOT)

    def test_asset_tree_is_ascii_only_and_has_no_unowned_top_level_content(self) -> None:
        self.assertEqual(
            {path.name for path in ASSET_ROOT.iterdir()},
            {"audio", "card_back", "images", "video", "ZENONZARD_CARDLIST"},
        )
        non_ascii = [
            str(path.relative_to(ASSET_ROOT))
            for path in ASSET_ROOT.rglob("*")
            if not str(path.relative_to(ASSET_ROOT)).isascii()
        ]
        self.assertEqual(non_ascii, [])

    def test_card_force_token_and_audio_closure_matches_runtime(self) -> None:
        expected_cards = {
            card.id
            for card in CARD_REGISTRY.values()
            if is_user_deck_card_id(card.id)
        }
        card_root = ASSET_ROOT / "ZENONZARD_CARDLIST"
        card_files = {
            path.stem
            for color in ("RED", "YELLOW", "WHITE", "GREEN", "BLUE", "PURPLE", "COLORLESS")
            for path in (card_root / color).glob("*.png")
        }
        self.assertEqual(card_files, expected_cards)
        self.assertTrue(all(self.index.resolve_asset_id(card_id) for card_id in expected_cards))

        self.assertEqual(
            {path.stem for path in (card_root / "FORCE").glob("*.png")},
            set(ALL_FORCES),
        )
        self.assertEqual(
            {path.name for path in (card_root / "tokens").glob("*.png")},
            {"red_01_04_00_00.png", "blue_02_04_00_00.png", "colorless_01_04_00_00.png"},
        )
        self.assertTrue(self.index.resolve_asset_id("card_back"))
        self.assertTrue(self.index.resolve_asset_id("s_golem_token"))
        self.assertTrue(self.index.resolve_asset_id("merfolk_token"))
        self.assertTrue(self.index.resolve_asset_id("slime_block_token"))

        expected_audio_ids = {f"bgm_{index:02d}" for index in range(1, 21)} | set(BATTLE_SFX_AUDIO_NAMES)
        self.assertTrue(all(self.index.resolve_audio_id(audio_id) for audio_id in expected_audio_ids))

    def test_ui_playmat_and_character_manifests_are_complete(self) -> None:
        ui_root = ASSET_ROOT / "images" / "clean_graph" / "ui"
        ui_manifest = json.loads((ui_root / "ui_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {path.name for path in ui_root.iterdir()},
            {"ui_manifest.json", *ui_manifest["assets"].values()},
        )
        self.assertEqual(ui_manifest["assets"]["logo_zzicon"], "logo_zzicon.png")
        self.assertEqual(set(self.index.ui_asset_catalog()), set(ui_manifest["assets"]))

        playmat_root = ASSET_ROOT / "images" / "clean_graph" / "playmats"
        playmat_manifest = json.loads((playmat_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(playmat_manifest), 185)
        self.assertEqual(len(self.index.playmat_catalog()), 185)
        self.assertEqual(
            {path.name for path in playmat_root.iterdir()},
            {"manifest.json", *(entry["file"] for entry in playmat_manifest)},
        )

        characters = character_catalog(self.index)
        self.assertEqual(len(characters), 19)
        self.assertTrue(all(character["portraitUrl"] for character in characters))
        self.assertIsNotNone(home_guide_catalog(self.index))


if __name__ == "__main__":
    unittest.main()
