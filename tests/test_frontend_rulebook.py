from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "zz" / "web" / "static" / "app.js").read_text(encoding="utf-8")
STYLE_SOURCE = (ROOT / "zz" / "web" / "static" / "styles.css").read_text(encoding="utf-8")
RULEBOOK = (ROOT / "docs" / "rules" / "zz_rulebook_zh.md").read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    start = APP_SOURCE.index(f"function {name}(")
    end = APP_SOURCE.find("\nfunction ", start + 1)
    return APP_SOURCE[start:] if end < 0 else APP_SOURCE[start:end]


def test_duel_topbar_opens_an_in_app_rulebook_modal() -> None:
    duel = _function_source("renderDuelView")
    modal = _function_source("renderRulebookModal")
    markdown = _function_source("renderRulebookMarkdown")

    assert "renderTopbarRulebookButton()" in duel
    assert "data-open-rulebook" in _function_source("renderTopbarRulebookButton")
    assert "rulebook-markdown" in modal
    assert "rulebook-table" in markdown
    assert "rulebook-code" in markdown
    assert ".rulebook-modal" in STYLE_SOURCE
    assert "## 5. 回合流程" in RULEBOOK
