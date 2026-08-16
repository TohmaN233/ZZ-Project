from __future__ import annotations

import json
import random
from pathlib import Path

from zz.engine import Engine
from zz.enums import Color, Side, Step
from zz.model import GameState, Player
from zz.web.assets import AssetIndex
from zz.web.serialize import serialize_card


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = PROJECT_ROOT / "asserts"
ENGLISH_ROOT = ASSET_ROOT / "Eng-cards"


def test_english_asset_manifest_is_complete() -> None:
    manifest = json.loads((ENGLISH_ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["schemaVersion"] == 1
    assert len(manifest["cards"]) == 1297
    assert len(manifest["forces"]) == 10
    assert set(manifest["mana"]) == {
        "COLORLESS",
        "RED",
        "YELLOW",
        "WHITE",
        "GREEN",
        "BLUE",
        "PURPLE",
    }
    for group in ("cards", "forces", "mana"):
        assert all((ENGLISH_ROOT / relative_path).is_file() for relative_path in manifest[group].values())


def test_asset_index_prefers_local_english_cards_and_forces() -> None:
    manifest = json.loads((ENGLISH_ROOT / "manifest.json").read_text(encoding="utf-8"))
    index = AssetIndex(ASSET_ROOT)
    card_id = next(iter(manifest["cards"]))
    force_id = next(iter(manifest["forces"]))

    assert index.asset_url_en(card_id) == f"/assets/english%3A{card_id}"
    assert index.asset_url_en(force_id) == f"/assets/english%3A{force_id}"


def test_mana_token_art_tracks_its_current_color() -> None:
    player = Player(name="P1", side=Side.P1, is_first_player=True)
    opponent = Player(name="P2", side=Side.P2)
    state = GameState(players=[player, opponent], step=Step.MANA)
    engine = Engine(state, rng=random.Random(7))
    index = AssetIndex(ASSET_ROOT)

    engine.place_colorless_mana()
    token = player.base[-1]
    neutral = serialize_card(engine, token, index)
    assert neutral["manaColor"] == "COLORLESS"
    assert neutral["assetUrl"] == "/assets/mana%3ACOLORLESS"

    token.mana_color_override = Color.RED
    recolored = serialize_card(engine, token, index)
    assert recolored["manaColor"] == "RED"
    assert recolored["assetUrl"] == "/assets/mana%3ARED"
    assert recolored["assetUrlEn"] == recolored["assetUrl"]


def test_asset_index_never_emits_remote_card_urls() -> None:
    index = AssetIndex(ASSET_ROOT)
    card_id = "red_00_01_04_00"
    assert index.asset_url(card_id).startswith("/assets/")
    assert index.asset_url_en(card_id).startswith("/assets/")
    assert "://" not in index.asset_url(card_id)
    assert "://" not in index.asset_url_en(card_id)


def test_offline_serialize_state_still_includes_local_asset_urls() -> None:
    from zz.web.serialize import serialize_state

    player = Player(name="P1", side=Side.P1, is_first_player=True)
    opponent = Player(name="P2", side=Side.P2)
    state = GameState(players=[player, opponent], step=Step.MANA)
    engine = Engine(state, rng=random.Random(7))
    index = AssetIndex(ASSET_ROOT)
    engine.place_colorless_mana()
    view = serialize_state(engine, player, index, prompt=None)
    card = view["players"]["human"]["base"][0]
    assert card["assetUrl"] == "/assets/mana%3ACOLORLESS"
    assert not card["assetUrl"].startswith("http")


def test_catalog_card_urls_are_local_paths() -> None:
    from zz.web.catalog import catalog_dto

    catalog = catalog_dto(AssetIndex(ASSET_ROOT))
    remote = []
    for card in catalog["cards"]:
        for key in ("assetUrl", "assetUrlEn"):
            url = card.get(key)
            if not url or not str(url).startswith("/assets/") or "://" in str(url):
                remote.append((card["id"], key, url))
    assert remote == []
