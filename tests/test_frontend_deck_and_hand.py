from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "zz" / "web" / "static" / "app.js").read_text(encoding="utf-8")
STYLE_SOURCE = (ROOT / "zz" / "web" / "static" / "styles.css").read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    start = APP_SOURCE.index(f"function {name}(")
    end = APP_SOURCE.find("\nfunction ", start + 1)
    return APP_SOURCE[start:] if end < 0 else APP_SOURCE[start:end]


def test_home_exposes_deck_builder_through_existing_route() -> None:
    home = _function_source("renderHome")

    assert 'data-view="deckbuilder"' in home
    assert 't("deckBuilder")' in home
    assert 'else if (view === "deckbuilder") startDeckBuilder();' in APP_SOURCE


def test_new_game_keeps_selected_decks_when_payload_is_partial_or_empty() -> None:
    start_new = _function_source("startNew")

    assert "...selectedBattlePayload()," in start_new
    assert "...(launchPayload || {})," in start_new
    assert "activeMatchPayload = cloneLaunchPayload(payload);" in start_new
    assert 'startNew(newGame.dataset.new, activeMatchPayload);' in APP_SOURCE


def test_player_hand_uses_a_fixed_fan_with_real_hit_areas() -> None:
    hand = _function_source("renderHandFan")

    assert 'class="hand-slot"' in hand
    assert '"hand-card"' in hand
    assert '"opponent-hand-card"' in hand
    assert "--n:${handCount}" in hand
    assert "--hand-count:${Math.max(2, handCount)}" in hand

    assert "--hand-w: clamp(72px, 6vw, 104px);" in STYLE_SOURCE
    assert ".hand-fan.bottom .hand-cards" in STYLE_SOURCE
    assert "overflow: visible;" in STYLE_SOURCE
    assert "--hand-overlap: clamp(" in STYLE_SOURCE
    assert "margin-left: calc(-1 * var(--hand-overlap));" in STYLE_SOURCE
    assert "transform: rotate(var(--fan-angle, 0deg));" in STYLE_SOURCE
    assert "translateY(-10px) rotate(0deg)" in STYLE_SOURCE
    assert "scroll-snap-type: x proximity;" not in STYLE_SOURCE
    assert "transform: scale(1.8);" not in STYLE_SOURCE


def test_floating_pass_gets_a_dedicated_command_row() -> None:
    assert ".cockpit-command-row:has(.prompt.has-floating-actions)" in STYLE_SOURCE
    assert ".cockpit-command-row .prompt.has-floating-actions" in STYLE_SOURCE
    assert "min-height: clamp(88px, 7.2vw, 110px);" in STYLE_SOURCE
    assert "bottom: 0;" in STYLE_SOURCE

def test_catalog_card_detail_keeps_deck_builder_scroll() -> None:
    opener = _function_source("openCatalogCardDetail")
    closer = _function_source("closeCatalogCardDetail")

    assert "renderPreservingDeckBuilderScroll()" in opener
    assert "render();" not in opener
    assert "renderPreservingDeckBuilderScroll()" in closer
    assert "if (rerender) render();" not in closer

