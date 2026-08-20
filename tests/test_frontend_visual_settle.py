from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "zz" / "web" / "static" / "app.js").read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    start = APP_SOURCE.index(f"function {name}(")
    end = APP_SOURCE.find("\nfunction ", start + 1)
    return APP_SOURCE[start:] if end < 0 else APP_SOURCE[start:end]


def test_destroy_and_heal_settle_held_visual_state() -> None:
    settles = _function_source("animationEventSettlesVisualState")
    finished = _function_source("settleFinishedAnimationEvent")
    destroy = _function_source("settleDestroyVisualState")
    heal = _function_source("settleHealVisualState")
    show_next = _function_source("showNextAnimationEvent")

    assert '"destroy"' in settles
    assert '"heal"' in settles
    assert '"refresh"' in settles
    assert "settleDestroyVisualState(event)" in finished
    assert "settleHealVisualState(event)" in finished
    assert "isRefreshVisualEvent(event)" in finished
    assert "found.rested = false" in _function_source("settleRefreshVisualState")
    layer = _function_source("animationEventLayerMode")
    assert 'event.type === "refresh") return "none"' in layer
    assert 'event.phase === "refresh" ? "overlay"' in layer
    assert "removeVisualCardFromArea(player, \"field\", card.iid)" in destroy
    assert "player.life" in heal
    assert "rememberDestroySource(activeAnimationEvent)" in show_next


def test_update_notice_downloads_installer_instead_of_opening_a_page() -> None:
    notice = _function_source("renderApplicationUpdateNotice")
    opener = _function_source("openApplicationRelease")
    assert "downloadAndInstallUpdate" in opener
    assert "updateDownloading" in notice
    assert "viewRelease" in notice



def test_refresh_banner_is_language_neutral_and_effect_text_follows_ui_language() -> None:
    label = _function_source("animationEventLabel")
    overlay = _function_source("renderEffectTriggerOverlay")
    assert 'return "refresh"' in label
    assert "t(\"phaseRefresh\")" not in label
    assert "localizedTriggeredEffectText(event, card)" in overlay
    picker = _function_source("localizedTriggeredEffectText")
    assert "event.effectTextZh" in picker
    assert "event.effectTextEn" in picker
    assert "currentLanguage()" in picker
