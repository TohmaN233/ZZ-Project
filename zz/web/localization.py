from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path


TRANSLATION_ROOT = Path(__file__).resolve().parent / "translations"
CARD_TRANSLATIONS_TSV = TRANSLATION_ROOT / "zz_card_pool_zh.tsv"
FORCE_TRANSLATIONS_TSV = TRANSLATION_ROOT / "zz_force_pool_zh.tsv"


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
    return card_translations().get(card_id, {})


def force_translation(force_id: str) -> dict[str, str]:
    return force_translations().get(force_id, {})
