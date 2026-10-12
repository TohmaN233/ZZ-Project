import json

import pytest

from zz.web.settings_store import SettingsStore
from zz.web.server import ServerState
from zz.pc02r import PC02R_CARD_IDS


def test_duel_scale_persists_and_preserves_other_settings(tmp_path):
    store = SettingsStore(tmp_path)
    assert store.load()["duelScale"] == 100
    store.save({"duelScale": 150, "uiLanguage": "ja"})
    assert SettingsStore(tmp_path).load()["duelScale"] == 150
    store.save({"reducedMotion": True})
    assert store.load()["duelScale"] == 150
    assert store.load()["uiLanguage"] == "ja"


@pytest.mark.parametrize("value", [79, 151, 85, True, None, "150", 100.5])
def test_invalid_duel_scale_is_rejected_without_overwriting(tmp_path, value):
    store = SettingsStore(tmp_path)
    store.save({"duelScale": 120})
    with pytest.raises(ValueError, match="invalid duel scale"):
        store.save({"duelScale": value})
    assert store.load()["duelScale"] == 120


def test_catalog_effect_parameters_are_json_serializable():
    payload = ServerState().catalog()
    json.dumps(payload)
    cards = {card["id"]: card for card in payload["cards"]}
    assert set(PC02R_CARD_IDS) <= cards.keys()
