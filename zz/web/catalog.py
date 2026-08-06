from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.decks import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
    card_allows_unlimited_copies,
    deck_card_max_copies,
    is_user_deck_card_id,
)
from zz.effects import (
    effect_template_catalog,
    official_condition_tags_for_card,
    official_effect_tags_for_card,
    official_timing_tags_for_card,
)
from zz.engine import LIFE_CAP
from zz.forces import ALL_FORCES
from zz.web.assets import AssetIndex, DEFAULT_OFFICIAL_CARDLIST
from zz.web.filter_localization import filter_group_labels, filter_option_labels
from zz.web.localization import card_translation, force_translation
from zz.web.profiles import character_catalog, home_guide_catalog


DEFAULT_OFFICIAL_FILTERS = DEFAULT_OFFICIAL_CARDLIST.with_name("official_filters.tsv")
DEFAULT_BILINGUAL_CARDLIST = DEFAULT_OFFICIAL_CARDLIST.with_name("cards_bilingual_v4.tsv")

FILTER_GROUP_ORDER = [
    "cardtype",
    "attribute",
    "cost",
    "series",
    "race",
    "reality",
    "dp",
    "effect",
    "effect_timing",
    "conditions",
]

TYPE_JP_BY_VALUE = {
    "b_minion": "ベース・ミニオン",
    "f_minion": "フィールド・ミニオン",
    "magic": "マジック",
    "mana_token": "ミニオン・トークン",
}

ATTRIBUTE_JP_BY_COLOR = {
    "RED": "赤",
    "YELLOW": "黄",
    "WHITE": "白",
    "GREEN": "緑",
    "BLUE": "青",
    "PURPLE": "紫",
    "COLORLESS": "無色",
}


def _cost_dict(card) -> dict[str, int]:
    return {color.name: amount for color, amount in card.cost.items()}


def _read_tsv_by_id(path: Path, id_column: str = "image_id") -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return {
            str(row.get(id_column, "")).strip(): dict(row)
            for row in reader
            if str(row.get(id_column, "")).strip()
        }


def _read_filter_groups(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            group = (row.get("group") or "").strip()
            value = (row.get("value") or "").strip()
            if not group or not value:
                continue
            labels = filter_option_labels(group, value, (row.get("label") or value).strip())
            option = {
                "value": value,
                "label": labels["labelJp"],
                **labels,
                "order": _int_or_none(row.get("order")),
            }
            pack_order = _int_or_none(row.get("pack_order"))
            if pack_order is not None:
                option["packOrder"] = pack_order
            groups.setdefault(group, []).append(option)
    result = []
    for group in FILTER_GROUP_ORDER:
        if group not in groups:
            continue
        labels = filter_group_labels(group)
        result.append({
            "id": group,
            "label": labels["labelJp"],
            **labels,
            "options": sorted(groups[group], key=lambda item: (item.get("order") or 9999, item["labelJp"])),
        })
    return result


def _int_or_none(value: Any) -> int | None:
    try:
        text = str(value or "").strip()
        return int(text) if text else None
    except ValueError:
        return None


def _split_values(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split("|") if part.strip()]


def _first(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _total_cost_label(card, official: dict[str, str], bilingual: dict[str, str]) -> str:
    label = _first(official.get("cost_official"), bilingual.get("cost"))
    if label:
        return label
    total = sum(card.cost.values())
    return str(total) if total else ""


def _card_filter_values(card, official: dict[str, str], bilingual: dict[str, str]) -> dict[str, list[str]]:
    card_type = _first(official.get("card_type_jp"), TYPE_JP_BY_VALUE.get(card.type.value))
    attribute = _split_values(_first(official.get("attribute_jp")))
    if not attribute and card.mana_color is not None:
        attribute = [ATTRIBUTE_JP_BY_COLOR.get(card.mana_color.name, card.mana_color.name)]
    cost = _total_cost_label(card, official, bilingual)
    race = _split_values(official.get("race_jp"))
    effect_tags = _split_values(official.get("effect_tags_jp")) or official_effect_tags_for_card(card)
    timing_tags = _split_values(official.get("effect_timing_jp")) or official_timing_tags_for_card(card)
    condition_tags = _split_values(official.get("condition_tags_jp")) or official_condition_tags_for_card(card)
    return {
        "cardtype": [card_type] if card_type else [],
        "attribute": attribute,
        "cost": [cost] if cost else [],
        "series": [_first(official.get("pack_jp_official"), bilingual.get("pack_jp"))],
        "race": race,
        "reality": [_first(official.get("rarity_official"), bilingual.get("rarity_en"))],
        "dp": [_first(official.get("dp_official"), card.dp if card.dp is not None else "")],
        "effect": effect_tags,
        "effect_timing": timing_tags,
        "conditions": condition_tags,
    }


def _effect_spec_summary(card) -> list[dict[str, Any]]:
    return [
        {
            "templateId": spec.template_id,
            "timing": spec.timing.value,
            "officialTiming": spec.official_timing,
            "targetKind": spec.target_kind,
            "minTargets": spec.min_targets,
            "maxTargets": spec.max_targets,
            "optional": spec.optional,
            "params": dict(spec.params or {}),
            "officialEffect": spec.official_effect,
            "officialCondition": spec.official_condition,
            "activeAreas": [area.value for area in spec.active_areas or ()],
        }
        for spec in card.effects
    ]


def catalog_dto(asset_index: AssetIndex) -> dict[str, Any]:
    official_by_id = _read_tsv_by_id(DEFAULT_OFFICIAL_CARDLIST)
    bilingual_by_id = _read_tsv_by_id(DEFAULT_BILINGUAL_CARDLIST)
    cards = []
    for card in CARD_REGISTRY.values():
        if not is_user_deck_card_id(card.id):
            continue
        official = official_by_id.get(card.id, {})
        bilingual = bilingual_by_id.get(card.id, {})
        filter_values = _card_filter_values(card, official, bilingual)
        ability_jp = _first(bilingual.get("ability_jp"), card.ability_jp)
        ability_en = _first(bilingual.get("ability_en"), card.ability_en)
        name_jp = _first(official.get("official_name_jp"), bilingual.get("name_jp"), card.name_jp)
        name_en = _first(bilingual.get("name_en"), card.name_en)
        translation = card_translation(card.id)
        name_zh = _first(translation.get("name_zh"))
        ability_zh = _first(translation.get("ability_zh"))
        pack_jp = _first(official.get("pack_jp_official"), bilingual.get("pack_jp"))
        pack_order = _int_or_none(official.get("pack_order"))
        official_cost = _total_cost_label(card, official, bilingual)
        cards.append({
            "id": card.id,
            "nameJp": name_jp,
            "nameEn": name_en,
            "nameZh": name_zh,
            "abilityJp": ability_jp,
            "abilityEn": ability_en,
            "abilityZh": ability_zh,
            "type": card.type.value,
            "cardTypeJp": _first(official.get("card_type_jp"), TYPE_JP_BY_VALUE.get(card.type.value)),
            "officialCardType": _first(official.get("card_type")),
            "attribute": _first(official.get("attribute"), bilingual.get("color")),
            "attributeJp": "|".join(filter_values["attribute"]),
            "cost": _cost_dict(card),
            "totalCost": sum(card.cost.values()),
            "officialCost": official_cost,
            "bp": card.bp,
            "dp": card.dp,
            "manaColor": None if card.mana_color is None else card.mana_color.name,
            "keywords": [keyword.name for keyword in card.keywords],
            "unlimitedCopies": card_allows_unlimited_copies(card.id),
            "maxCopies": deck_card_max_copies(card.id),
            "packJp": pack_jp,
            "packOrder": pack_order,
            "raceJp": filter_values["race"],
            "rarity": _first(official.get("rarity_official"), bilingual.get("rarity_en")),
            "officialOrder": _int_or_none(official.get("official_order")),
            "effectTagsJp": filter_values["effect"],
            "effectTimingJp": filter_values["effect_timing"],
            "conditionTagsJp": filter_values["conditions"],
            "effectSpecs": _effect_spec_summary(card),
            "filterValues": {key: [value for value in values if value] for key, values in filter_values.items()},
            "assetUrl": asset_index.asset_url(card.id),
            "assetUrlEn": asset_index.asset_url_en(card.id),
        })
    cards.sort(key=lambda item: (
        item["packOrder"] or 9999,
        item["officialOrder"] if item["officialOrder"] is not None else 999999,
        item["type"],
        item["totalCost"],
        item["nameJp"],
        item["id"],
    ))

    forces = []
    for force in ALL_FORCES.values():
        translation = force_translation(force.id)
        forces.append({
            "id": force.id,
            "nameJp": force.name_jp,
            "nameZh": _first(translation.get("name_zh")),
            "nameEn": _first(translation.get("name_en")),
            "initialLife": force.initial_life,
            "maxLife": LIFE_CAP,
            "abilityJp": force.ability_jp,
            "abilityEn": force.ability_en,
            "abilityZh": _first(translation.get("ability_zh")),
            "assetUrl": asset_index.asset_url(force.id),
            "assetUrlEn": asset_index.asset_url_en(force.id),
        })
    forces.sort(key=lambda item: item["nameJp"])

    return {
        "ok": True,
        "cards": cards,
        "forces": forces,
        "characters": character_catalog(asset_index),
        "homeGuide": home_guide_catalog(asset_index),
        "playmats": asset_index.playmat_catalog(),
        "uiAssets": asset_index.ui_asset_catalog(),
        "filters": _read_filter_groups(DEFAULT_OFFICIAL_FILTERS),
        "effectTemplates": effect_template_catalog(),
        "defaultDecks": [
            {
                "id": "kanatana_yellow",
                "name": "Kanatana Yellow",
                "recipe": dict(KANATANA_YELLOW_RECIPE),
                "forces": list(DECKCODE0_YELLOW_FORCES),
            },
            {
                "id": "demete_green",
                "name": "Demete Green",
                "recipe": dict(DEMETE_GREEN_RECIPE),
                "forces": list(DECKCODE0_GREEN_FORCES),
            },
        ],
    }
