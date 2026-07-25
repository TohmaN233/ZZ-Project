from __future__ import annotations

import csv
from pathlib import Path

from zz.cards import CARD_REGISTRY, register
from zz.pc01 import DEFAULT_CARD_TSV, _card_from_row


BASIC_PACK_JP = "ベーシック"


def _basic_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            dict(row)
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("pack_jp_official") == BASIC_PACK_JP
            and row.get("card_type") != "token_minion"
        ]
    rows.sort(key=lambda row: int(row.get("official_order") or 999999))
    return rows


def register_basic_cards(path: Path = DEFAULT_CARD_TSV) -> list[str]:
    registered_ids: list[str] = []
    for row in _basic_rows(path):
        card_id = row["image_id"].strip()
        if card_id not in CARD_REGISTRY:
            register(_card_from_row(row))
        registered_ids.append(card_id)
    return registered_ids


register_basic_cards()

