import csv
from pathlib import Path

import pytest

from tools.normalize_japanese_card_text import (
    ROOT, SOURCE, VERIFIED, PC02R, integrity_findings, normalize_text, read_rows,
)
from zz.cards import CARD_REGISTRY
from zz.pc02r import PC02R_CARD_IDS
from zz.web.assets import AssetIndex
from zz.web.catalog import catalog_dto


OLIVIA = "green_05_02_02r_00"
OLIVIA_TEXT = (
    "【常時】\\n"
    "このミニオンと自分の種族「ドラゴン」を持つ緑のミニオン全ては"
    "相手の効果で破壊または除外されない。"
)


def by_id(path):
    return {row["image_id"]: row for row in read_rows(path)[1]}


def test_pc02r_all_106_have_verified_complete_japanese_faces():
    verified, source, registry_source = by_id(VERIFIED), by_id(SOURCE), by_id(PC02R)
    assert len(PC02R_CARD_IDS) == len(registry_source) == 106
    for card_id in PC02R_CARD_IDS:
        row = verified[card_id]
        assert row["source"] == "local_official_japanese_face_manual_2026-10-11"
        assert row["face_text_status"] == "text"
        text = normalize_text(row["ability_jp"])
        assert not integrity_findings(text), (card_id, text)
        assert source[card_id]["ability_jp"] == registry_source[card_id]["ability_jp"] == text
        assert CARD_REGISTRY[card_id].ability_jp == text.replace("\\n", "\n")
        image = ROOT / "asserts/ZENONZARD_CARDLIST" / source[card_id]["color"].upper() / f"{card_id}.png"
        assert image.is_file(), image


def test_olivia_condition_and_protection_are_not_truncated():
    assert by_id(SOURCE)[OLIVIA]["ability_jp"] == OLIVIA_TEXT
    assert by_id(PC02R)[OLIVIA]["ability_jp"] == OLIVIA_TEXT


def test_pc02r_original_face_conditions_and_numbers():
    rows = by_id(SOURCE)
    assert "自分の青の種族「ドラゴン」" in rows["blue_05_02_02r_00"]["ability_jp"]
    assert "BP-100" in rows["red_08_02_02r_00"]["ability_jp"]
    assert "BP-200" not in rows["red_08_02_02r_00"]["ability_jp"]
    assert "DP-1" in rows["blue_04_02_02r_01"]["ability_jp"]
    assert "［加護］は付与されない。" in rows["green_07_02_02r_00"]["ability_jp"]
    assert "自分の「ゴブリンズ・クイーン」がいる場合" in rows["colorless_04_02_02r_02"]["ability_jp"]
    assert "加護：黄＋コスト6以上" in rows["yellow_00_01_02r_01"]["ability_jp"]


def test_catalog_uses_the_same_complete_japanese_source_and_preserves_chinese():
    catalog = {row["id"]: row for row in catalog_dto(AssetIndex(None))["cards"]}
    source = by_id(SOURCE)
    with (ROOT / "zz/web/translations/zz_card_pool_zh.tsv").open(encoding="utf-8-sig", newline="") as handle:
        chinese = {row["card_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    for card_id in PC02R_CARD_IDS:
        row = catalog[card_id]
        assert row["abilityJp"].replace("\n", "\\n") == source[card_id]["ability_jp"]
        assert row["nameZh"] == chinese[card_id]["name_zh"]
        assert row["abilityZh"] == chinese[card_id]["ability_zh"]


def test_reflow_keeps_granted_abilities_and_timing_references_in_the_sentence():
    text = "【加護時】\\nこのミ二オンに「【アタック時】相手のBP400以\\n下のミニオン1体を破壊する。」を付与する。"
    assert normalize_text(text) == "【加護時】\\nこのミニオンに「【アタック時】相手のBP400以下のミニオン1体を破壊する。」を付与する。"
    reference = "【自分のターン】\\nそのフォースの【破壊時】効\\n果は発揮しない。"
    assert normalize_text(reference) == "【自分のターン】\\nそのフォースの【破壊時】効果は発揮しない。"
    assert normalize_text("【メイン】/【フラッシュ】\\n自分はカードを1枚引く。\\nＬEGEND") == "【メイン】/【フラッシュ】\\n自分はカードを1枚引く。"
    evolution = "進化：手札から「ドワーフ」が召喚されたとき\\n「召喚獣」をLv3にする。"
    assert normalize_text(evolution) == evolution


@pytest.mark.parametrize("text", [
    "【常時】\\nこのミニオンは除外され", "【自分の夕\\nカードを引く。",
    "【加護時】\\nこのミニオンに[加護を与える。",
])
def test_unresolved_ocr_is_reported_and_never_reconstructed(text):
    assert integrity_findings(normalize_text(text))
    assert not normalize_text(text).endswith("ない。")


def test_source_reflow_is_idempotent_for_all_packs():
    _, rows = read_rows(SOURCE)
    assert len(rows) == 1439
    for row in rows:
        assert normalize_text(row["ability_jp"]) == row["ability_jp"], row["image_id"]


def test_all_source_rows_pass_the_japanese_text_integrity_scan():
    findings = {row["image_id"]: integrity_findings(row["ability_jp"])
                for row in read_rows(SOURCE)[1] if integrity_findings(row["ability_jp"])}
    assert not findings, findings


def test_all_verified_transcriptions_are_installed_without_card_face_layout_garbage():
    source = by_id(SOURCE)
    for row in read_rows(VERIFIED)[1]:
        text = normalize_text(row["ability_jp"])
        assert source[row["image_id"]]["ability_jp"] == text
        assert not integrity_findings(text), (row["image_id"], text)
