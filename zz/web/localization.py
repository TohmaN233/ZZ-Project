from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from zz.card_identity import explicit_card_equivalence_pairs


TRANSLATION_ROOT = Path(__file__).resolve().parent / "translations"
CARD_TRANSLATIONS_TSV = TRANSLATION_ROOT / "zz_card_pool_zh.tsv"
FORCE_TRANSLATIONS_TSV = TRANSLATION_ROOT / "zz_force_pool_zh.tsv"
CARD_SOURCE_TSV = Path(__file__).resolve().parents[2] / "data/cards_bilingual_v4.tsv"


def _clean(value: object) -> str:
    return str(value or "").replace("\\n", "\n").strip()


def _read_tsv_by_id(path: Path, id_column: str) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            item_id = _clean(row.get(id_column))
            if not item_id:
                continue
            rows[item_id] = {str(key): _clean(value) for key, value in row.items() if key is not None}
    return rows


@lru_cache(maxsize=1)
def card_translations() -> dict[str, dict[str, str]]:
    return _read_tsv_by_id(CARD_TRANSLATIONS_TSV, "card_id")


@lru_cache(maxsize=1)
def force_translations() -> dict[str, dict[str, str]]:
    return _read_tsv_by_id(FORCE_TRANSLATIONS_TSV, "force_id")


def card_translation(card_id: str) -> dict[str, str]:
    translation = card_translations().get(card_id, {})
    english = _equivalent_english_abilities()
    if card_id in english:
        return {**translation, "ability_en": english[card_id]}
    return translation


@lru_cache(maxsize=1)
def _equivalent_english_abilities() -> dict[str, str]:
    """Display EX02 English rules on paired SAO faces without inventing a print."""
    with CARD_SOURCE_TSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["image_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    pairs = explicit_card_equivalence_pairs()
    names = {_clean(rows[a]["name_en"]): _clean(rows[b]["name_jp"]) for a, b in pairs}
    if not all(names) or not all(names.values()):
        raise ValueError("Equivalent English effects require both printed card names")
    pattern = re.compile("|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)))
    abilities = {}
    for original, variant in pairs:
        text = _clean(rows[original]["ability_en"])
        if not text and _clean(rows[original]["ability_jp"]):
            raise ValueError(f"Missing EX02 English effect for SAO counterpart: {original} / {variant}")
        abilities[variant] = pattern.sub(lambda match: names[match.group()], text)
    return abilities


@lru_cache(maxsize=1)
def card_japanese_abilities() -> dict[str, str]:
    """Required canonical Japanese text, shared by catalog and live details."""
    with CARD_SOURCE_TSV.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not {"image_id", "ability_jp"}.issubset(reader.fieldnames or ()):
            raise ValueError("Japanese card source is missing required columns")
        rows: dict[str, str] = {}
        for row in reader:
            card_id = row["image_id"]
            if not card_id or card_id in rows:
                raise ValueError(f"invalid or duplicate Japanese card identity: {card_id}")
            rows[card_id] = _clean(row["ability_jp"])
        return rows


def card_japanese_ability(card) -> str:
    sources = card_japanese_abilities()
    # Generated cards have their own text and no official source-table record.
    return sources[card.id] if card.id in sources else card.ability_jp


def force_translation(force_id: str) -> dict[str, str]:
    return force_translations().get(force_id, {})
