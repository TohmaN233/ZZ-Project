"""EX02 printed faces sharing the verified rules of their EX02C counterparts."""

from __future__ import annotations

import csv
import re
from copy import deepcopy
from pathlib import Path

from zz.card_identity import explicit_card_equivalence_pairs
from zz.cards import CARD_REGISTRY, register
from zz.ex02c import EX02C_CARD_IDS
from zz.pc01 import _card_from_row


_PAIRS = explicit_card_equivalence_pairs()
EX02_CARD_IDS = tuple(original for original, _variant in _PAIRS)


def register_ex02_cards() -> list[str]:
    if len(_PAIRS) != 70 or {variant for _, variant in _PAIRS} != set(EX02C_CARD_IDS):
        raise ValueError("EX02 registration requires all 70 declared EX02C counterparts")
    path = Path(__file__).resolve().parents[1] / "data/cards_bilingual_v4.tsv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["image_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    if any(original not in rows or variant not in CARD_REGISTRY for original, variant in _PAIRS):
        raise ValueError("EX02 registration is missing a declared source/counterpart")
    printed_cards = {original: _card_from_row(rows[original], infer_effects=False) for original, _ in _PAIRS}
    names = {CARD_REGISTRY[variant].name_jp: printed_cards[original].name_jp for original, variant in _PAIRS}
    if not all(names) or not all(names.values()):
        raise ValueError("EX02 equivalent printed names must not be empty")
    name_pattern = re.compile("|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)))
    for original, variant in _PAIRS:
        if original in CARD_REGISTRY:
            raise ValueError(f"EX02 card already registered: {original}")
        printed = printed_cards[original]
        card = deepcopy(CARD_REGISTRY[variant])
        for field in ("type", "cost", "bp", "dp", "printed_color", "mana_color"):
            if getattr(printed, field) != getattr(card, field):
                raise ValueError(f"EX02 equivalent printed metadata differs: {original} / {field}")
        if set(printed.race_jp.split("|")) != set(card.race_jp.split("|")):
            raise ValueError(f"EX02 equivalent races differ: {original}")
        for field in ("id", "name_jp", "name_en", "ability_jp", "ability_en", "race_jp"):
            setattr(card, field, getattr(printed, field))
        for effect in card.effects:
            for field in ("official_effect", "official_condition", "official_timing"):
                text = getattr(effect, field)
                if text is not None:
                    setattr(effect, field, name_pattern.sub(lambda match: names[match.group()], text))
        # Registration reapplies the original face's verified transformation graph.
        card.transformation_ids = ()
        card.deck_buildable = True
        register(card)
    return list(EX02_CARD_IDS)


register_ex02_cards()
