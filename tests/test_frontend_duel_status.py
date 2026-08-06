from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DuelStatusLayoutTests(unittest.TestCase):
    def test_duel_header_keeps_only_mode_and_turn_in_one_stable_row(self) -> None:
        source = (PROJECT_ROOT / "zz" / "web" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        start = source.index("function renderDuelBrand()")
        end = source.index("function renderAvatar", start)
        render = source[start:end]

        self.assertIn('<div class="meta duel-status-meta">', render)
        self.assertIn("localizedMode(state.mode)", render)
        self.assertIn('t("turn")', render)
        self.assertEqual(render.count("<span>"), 2)
        self.assertNotIn("activeSide", render)
        self.assertNotIn("renderDuelPhaseMeta", render)

        styles = (PROJECT_ROOT / "zz" / "web" / "static" / "styles.css").read_text(
            encoding="utf-8"
        )
        start = styles.index(".duel-status-meta {")
        end = styles.index("}", start)
        status_styles = styles[start:end]
        self.assertIn("min-height: 18px", status_styles)
        self.assertIn("flex-wrap: nowrap", status_styles)
        self.assertIn("white-space: nowrap", status_styles)


if __name__ == "__main__":
    unittest.main()
