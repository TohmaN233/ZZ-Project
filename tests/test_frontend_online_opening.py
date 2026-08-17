from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "zz" / "web" / "static" / "app.js").read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    start = APP_SOURCE.index(f"function {name}(")
    end = APP_SOURCE.find("\nfunction ", start + 1)
    return APP_SOURCE[start:] if end < 0 else APP_SOURCE[start:end]


def test_ready_room_does_not_host_rps_picker() -> None:
    source = _function_source("renderOnlineRoom")
    assert "data-online-opening-choice" not in source
    assert "choosingFirstPlayer" not in source


def test_opening_choice_happens_on_duel_view() -> None:
    apply_source = _function_source("applyMultiplayerSnapshot")
    render_source = _function_source("render")
    opening_source = _function_source("renderOnlineOpeningDuelView")

    assert 'multiplayerUi.status === "MATCH_STARTING"' in apply_source
    assert 'appView = "duel"' in apply_source
    assert "isOnlineOpeningChoice()" in render_source
    assert "data-online-opening-choice" in opening_source


def test_rps_result_overlay_shows_first_and_second_seats() -> None:
    source = _function_source("renderRockPaperScissorsOverlay")
    assert 'uiAssetUrl("turn_first")' in source
    assert 'uiAssetUrl("turn_second")' in source
    assert "dice-seat-row" in source


def test_online_display_name_is_remembered() -> None:
    apply_source = _function_source("applyMultiplayerSnapshot")
    connect_source = _function_source("connectOnlineServer")
    create_source = _function_source("createOnlineRoom")
    persist_source = _function_source("persistOnlineDisplayName")

    assert "previousDisplayName" in apply_source
    assert "displayName: previousDisplayName" in apply_source
    assert "persistOnlineDisplayName" in connect_source
    assert "persistOnlineDisplayName" in create_source
    assert "localStorage.setItem" in persist_source
    assert "zz_online_display_name" in APP_SOURCE
    assert 'closest("[data-online-name]")' in APP_SOURCE


def test_online_duel_keeps_first_second_badge_off_offline_dice() -> None:
    badge = _function_source("onlineTurnOrderBadge")
    avatar = _function_source("renderAvatar")
    pilot = _function_source("renderPilotIdentity")
    dice = _function_source("renderDiceRollOverlay")

    assert "isOnlineDuel()" in badge
    assert "onlineTurnOrderBadge" in avatar
    assert "onlineTurnOrderBadge" in pilot
    assert "onlineTurnOrderBadge" not in dice
    assert 'uiAssetUrl("turn_first")' in dice


def test_home_hides_stale_reconnect_errors() -> None:
    apply_source = _function_source("applyMultiplayerSnapshot")
    assert "hideRecoveryNoise" in apply_source
    assert '"RECONNECTING", "OFFLINE", "ERROR"' in apply_source


def test_reconnecting_keeps_the_duel_instead_of_returning_to_lobby() -> None:
    apply_source = _function_source("applyMultiplayerSnapshot")
    assert "const reconnecting = multiplayerUi.status === \"RECONNECTING\"" in apply_source
    assert "previousOnlineDuel && !matchVisible && !reconnecting" in apply_source


def test_multiplayer_last_error_is_not_sticky_across_snapshots() -> None:
    apply_source = _function_source("applyMultiplayerSnapshot")
    assert "lastError: snapshot.lastError || null" in apply_source
    assert "snapshot.lastError || multiplayerUi.lastError" not in apply_source
    assert "stageDuelState(multiplayerUi.view, null)" in apply_source



def test_opening_snapshot_does_not_rerender_when_only_the_opponent_submits() -> None:
    apply_source = _function_source("applyMultiplayerSnapshot")
    assert "previousChoiceSubmitted" in apply_source
    assert "previousOpeningTie" in apply_source
    assert "rerender = false" in apply_source


def test_card_and_force_art_use_the_same_localized_url_helpers() -> None:
    card_source = _function_source("localizedCardAssetUrl")
    force_source = _function_source("localizedForceAssetUrl")
    hydrate_source = _function_source("hydrateMultiplayerViewAssets")
    assert "currentLanguage() === \"en\" && card.assetUrlEn" in card_source
    assert "card.assetUrl ? card.assetUrl : null" in card_source
    assert "mana_token" not in card_source
    assert "currentLanguage() === \"en\" && force.assetUrlEn" in force_source
    assert "catalog.manaAssets" in hydrate_source
    assert "card.assetUrlEn = manaUrl" in hydrate_source


def test_online_game_over_waits_for_return_before_leaving_the_duel() -> None:
    apply_source = _function_source("applyMultiplayerSnapshot")
    return_source = _function_source("returnToOnlineRoom")
    prompt_source = _function_source("renderPrompt")
    assert "multiplayerUi.view && multiplayerUi.view.gameOver" in apply_source
    assert "dismissMatchResult" in return_source
    assert "data-online-return-room" in prompt_source
