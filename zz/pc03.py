"""PC03 registry, assembled from independently authored card modules."""

from __future__ import annotations

import csv
from importlib import import_module
from pathlib import Path

from zz.cards import CARD_REGISTRY, register

_CARD_TSV = Path(__file__).with_name("pc03_data.tsv")

_MODULES = (
    ('blue_00_00_03_00', 'zz.pc03_cards.blue_00_00_03_00'),
    ('blue_00_00_03_01', 'zz.pc03_cards.blue_00_00_03_01'),
    ('blue_00_00_03_02', 'zz.pc03_cards.blue_00_00_03_02'),
    ('blue_00_00_03_03', 'zz.pc03_cards.blue_00_00_03_03'),
    ('blue_00_00_03_04', 'zz.pc03_cards.blue_00_00_03_04'),
    ('blue_00_00_03_05', 'zz.pc03_cards.blue_00_00_03_05'),
    ('blue_01_01_03_00', 'zz.pc03_cards.blue_01_01_03_00'),
    ('blue_02_01_03_00', 'zz.pc03_cards.blue_02_01_03_00'),
    ('blue_02_01_03_01', 'zz.pc03_cards.blue_02_01_03_01'),
    ('blue_02_01_03_02', 'zz.pc03_cards.blue_02_01_03_02'),
    ('blue_02_01_03_03', 'zz.pc03_cards.blue_02_01_03_03'),
    ('blue_03_01_03_00', 'zz.pc03_cards.blue_03_01_03_00'),
    ('blue_03_01_03_01', 'zz.pc03_cards.blue_03_01_03_01'),
    ('blue_03_01_03_02', 'zz.pc03_cards.blue_03_01_03_02'),
    ('blue_03_01_03_03', 'zz.pc03_cards.blue_03_01_03_03'),
    ('blue_03_02_03_00', 'zz.pc03_cards.blue_03_02_03_00'),
    ('blue_04_01_03_00', 'zz.pc03_cards.blue_04_01_03_00'),
    ('blue_05_01_03_00', 'zz.pc03_cards.blue_05_01_03_00'),
    ('blue_05_01_03_01', 'zz.pc03_cards.blue_05_01_03_01'),
    ('blue_05_01_03_02', 'zz.pc03_cards.blue_05_01_03_02'),
    ('blue_05_02_03_00', 'zz.pc03_cards.blue_05_02_03_00'),
    ('blue_06_01_03_00', 'zz.pc03_cards.blue_06_01_03_00'),
    ('blue_06_01_03_01', 'zz.pc03_cards.blue_06_01_03_01'),
    ('blue_06_01_03_02', 'zz.pc03_cards.blue_06_01_03_02'),
    ('blue_06_02_03_00', 'zz.pc03_cards.blue_06_02_03_00'),
    ('colorless_00_00_03_00', 'zz.pc03_cards.colorless_00_00_03_00'),
    ('colorless_00_00_03_01', 'zz.pc03_cards.colorless_00_00_03_01'),
    ('colorless_00_00_03_02', 'zz.pc03_cards.colorless_00_00_03_02'),
    ('colorless_02_01_03_00', 'zz.pc03_cards.colorless_02_01_03_00'),
    ('colorless_02_01_03_01', 'zz.pc03_cards.colorless_02_01_03_01'),
    ('colorless_03_01_03_00', 'zz.pc03_cards.colorless_03_01_03_00'),
    ('colorless_03_01_03_01', 'zz.pc03_cards.colorless_03_01_03_01'),
    ('colorless_03_01_03_02', 'zz.pc03_cards.colorless_03_01_03_02'),
    ('colorless_03_01_03_03', 'zz.pc03_cards.colorless_03_01_03_03'),
    ('colorless_04_01_03_00', 'zz.pc03_cards.colorless_04_01_03_00'),
    ('colorless_04_01_03_01', 'zz.pc03_cards.colorless_04_01_03_01'),
    ('colorless_04_01_03_02', 'zz.pc03_cards.colorless_04_01_03_02'),
    ('colorless_06_01_03_00', 'zz.pc03_cards.colorless_06_01_03_00'),
    ('colorless_06_01_03_01', 'zz.pc03_cards.colorless_06_01_03_01'),
    ('colorless_06_01_03_02', 'zz.pc03_cards.colorless_06_01_03_02'),
    ('colorless_07_01_03_00', 'zz.pc03_cards.colorless_07_01_03_00'),
    ('colorless_07_01_03_01', 'zz.pc03_cards.colorless_07_01_03_01'),
    ('colorless_07_01_03_02', 'zz.pc03_cards.colorless_07_01_03_02'),
    ('colorless_09_01_03_00', 'zz.pc03_cards.colorless_09_01_03_00'),
    ('colorless_10_01_03_00', 'zz.pc03_cards.colorless_10_01_03_00'),
    ('colorless_10_01_03_01', 'zz.pc03_cards.colorless_10_01_03_01'),
    ('green_00_00_03_00', 'zz.pc03_cards.green_00_00_03_00'),
    ('green_00_00_03_01', 'zz.pc03_cards.green_00_00_03_01'),
    ('green_00_00_03_02', 'zz.pc03_cards.green_00_00_03_02'),
    ('green_00_00_03_03', 'zz.pc03_cards.green_00_00_03_03'),
    ('green_00_00_03_04', 'zz.pc03_cards.green_00_00_03_04'),
    ('green_00_00_03_05', 'zz.pc03_cards.green_00_00_03_05'),
    ('green_01_01_03_00', 'zz.pc03_cards.green_01_01_03_00'),
    ('green_01_02_03_00', 'zz.pc03_cards.green_01_02_03_00'),
    ('green_02_01_03_00', 'zz.pc03_cards.green_02_01_03_00'),
    ('green_03_01_03_00', 'zz.pc03_cards.green_03_01_03_00'),
    ('green_03_01_03_01', 'zz.pc03_cards.green_03_01_03_01'),
    ('green_03_01_03_02', 'zz.pc03_cards.green_03_01_03_02'),
    ('green_03_01_03_03', 'zz.pc03_cards.green_03_01_03_03'),
    ('green_03_01_03_04', 'zz.pc03_cards.green_03_01_03_04'),
    ('green_04_01_03_00', 'zz.pc03_cards.green_04_01_03_00'),
    ('green_04_01_03_01', 'zz.pc03_cards.green_04_01_03_01'),
    ('green_04_02_03_00', 'zz.pc03_cards.green_04_02_03_00'),
    ('green_05_01_03_00', 'zz.pc03_cards.green_05_01_03_00'),
    ('green_05_01_03_01', 'zz.pc03_cards.green_05_01_03_01'),
    ('green_05_01_03_02', 'zz.pc03_cards.green_05_01_03_02'),
    ('green_05_02_03_00', 'zz.pc03_cards.green_05_02_03_00'),
    ('green_06_01_03_00', 'zz.pc03_cards.green_06_01_03_00'),
    ('green_06_01_03_01', 'zz.pc03_cards.green_06_01_03_01'),
    ('green_06_01_03_02', 'zz.pc03_cards.green_06_01_03_02'),
    ('green_10_01_03_00', 'zz.pc03_cards.green_10_01_03_00'),
    ('purple_00_00_03_00', 'zz.pc03_cards.purple_00_00_03_00'),
    ('purple_00_00_03_01', 'zz.pc03_cards.purple_00_00_03_01'),
    ('purple_00_00_03_02', 'zz.pc03_cards.purple_00_00_03_02'),
    ('purple_00_00_03_03', 'zz.pc03_cards.purple_00_00_03_03'),
    ('purple_00_00_03_04', 'zz.pc03_cards.purple_00_00_03_04'),
    ('purple_00_00_03_05', 'zz.pc03_cards.purple_00_00_03_05'),
    ('purple_01_01_03_00', 'zz.pc03_cards.purple_01_01_03_00'),
    ('purple_01_02_03_00', 'zz.pc03_cards.purple_01_02_03_00'),
    ('purple_02_01_03_00', 'zz.pc03_cards.purple_02_01_03_00'),
    ('purple_02_02_03_00', 'zz.pc03_cards.purple_02_02_03_00'),
    ('purple_03_01_03_00', 'zz.pc03_cards.purple_03_01_03_00'),
    ('purple_03_01_03_01', 'zz.pc03_cards.purple_03_01_03_01'),
    ('purple_04_01_03_00', 'zz.pc03_cards.purple_04_01_03_00'),
    ('purple_04_01_03_01', 'zz.pc03_cards.purple_04_01_03_01'),
    ('purple_04_01_03_02', 'zz.pc03_cards.purple_04_01_03_02'),
    ('purple_04_01_03_03', 'zz.pc03_cards.purple_04_01_03_03'),
    ('purple_04_01_03_04', 'zz.pc03_cards.purple_04_01_03_04'),
    ('purple_04_02_03_00', 'zz.pc03_cards.purple_04_02_03_00'),
    ('purple_05_01_03_00', 'zz.pc03_cards.purple_05_01_03_00'),
    ('purple_05_01_03_01', 'zz.pc03_cards.purple_05_01_03_01'),
    ('purple_05_01_03_02', 'zz.pc03_cards.purple_05_01_03_02'),
    ('purple_05_01_03_03', 'zz.pc03_cards.purple_05_01_03_03'),
    ('purple_05_01_03_04', 'zz.pc03_cards.purple_05_01_03_04'),
    ('purple_06_01_03_00', 'zz.pc03_cards.purple_06_01_03_00'),
    ('purple_08_01_03_00', 'zz.pc03_cards.purple_08_01_03_00'),
    ('red_00_00_03_00', 'zz.pc03_cards.red_00_00_03_00'),
    ('red_00_00_03_01', 'zz.pc03_cards.red_00_00_03_01'),
    ('red_00_00_03_02', 'zz.pc03_cards.red_00_00_03_02'),
    ('red_00_00_03_03', 'zz.pc03_cards.red_00_00_03_03'),
    ('red_00_00_03_04', 'zz.pc03_cards.red_00_00_03_04'),
    ('red_00_00_03_05', 'zz.pc03_cards.red_00_00_03_05'),
    ('red_01_01_03_00', 'zz.pc03_cards.red_01_01_03_00'),
    ('red_01_02_03_00', 'zz.pc03_cards.red_01_02_03_00'),
    ('red_02_01_03_00', 'zz.pc03_cards.red_02_01_03_00'),
    ('red_02_01_03_01', 'zz.pc03_cards.red_02_01_03_01'),
    ('red_02_01_03_02', 'zz.pc03_cards.red_02_01_03_02'),
    ('red_02_01_03_03', 'zz.pc03_cards.red_02_01_03_03'),
    ('red_03_01_03_00', 'zz.pc03_cards.red_03_01_03_00'),
    ('red_03_01_03_01', 'zz.pc03_cards.red_03_01_03_01'),
    ('red_04_01_03_00', 'zz.pc03_cards.red_04_01_03_00'),
    ('red_04_01_03_02', 'zz.pc03_cards.red_04_01_03_02'),
    ('red_04_01_03_03', 'zz.pc03_cards.red_04_01_03_03'),
    ('red_05_01_03_00', 'zz.pc03_cards.red_05_01_03_00'),
    ('red_05_01_03_01', 'zz.pc03_cards.red_05_01_03_01'),
    ('red_05_01_03_02', 'zz.pc03_cards.red_05_01_03_02'),
    ('red_05_01_03_03', 'zz.pc03_cards.red_05_01_03_03'),
    ('red_06_01_03_00', 'zz.pc03_cards.red_06_01_03_00'),
    ('red_06_02_03_00', 'zz.pc03_cards.red_06_02_03_00'),
    ('red_07_01_03_00', 'zz.pc03_cards.red_07_01_03_00'),
    ('red_07_02_03_00', 'zz.pc03_cards.red_07_02_03_00'),
    ('white_00_00_03_00', 'zz.pc03_cards.white_00_00_03_00'),
    ('white_00_00_03_01', 'zz.pc03_cards.white_00_00_03_01'),
    ('white_00_00_03_02', 'zz.pc03_cards.white_00_00_03_02'),
    ('white_00_00_03_03', 'zz.pc03_cards.white_00_00_03_03'),
    ('white_00_00_03_04', 'zz.pc03_cards.white_00_00_03_04'),
    ('white_00_00_03_05', 'zz.pc03_cards.white_00_00_03_05'),
    ('white_01_01_03_00', 'zz.pc03_cards.white_01_01_03_00'),
    ('white_02_01_03_00', 'zz.pc03_cards.white_02_01_03_00'),
    ('white_03_01_03_00', 'zz.pc03_cards.white_03_01_03_00'),
    ('white_03_01_03_01', 'zz.pc03_cards.white_03_01_03_01'),
    ('white_03_01_03_02', 'zz.pc03_cards.white_03_01_03_02'),
    ('white_03_02_03_00', 'zz.pc03_cards.white_03_02_03_00'),
    ('white_03_02_03_01', 'zz.pc03_cards.white_03_02_03_01'),
    ('white_04_01_03_00', 'zz.pc03_cards.white_04_01_03_00'),
    ('white_04_01_03_02', 'zz.pc03_cards.white_04_01_03_02'),
    ('white_04_01_03_03', 'zz.pc03_cards.white_04_01_03_03'),
    ('white_05_01_03_00', 'zz.pc03_cards.white_05_01_03_00'),
    ('white_05_01_03_01', 'zz.pc03_cards.white_05_01_03_01'),
    ('white_06_01_03_00', 'zz.pc03_cards.white_06_01_03_00'),
    ('white_06_01_03_02', 'zz.pc03_cards.white_06_01_03_02'),
    ('white_07_01_03_00', 'zz.pc03_cards.white_07_01_03_00'),
    ('white_07_01_03_01', 'zz.pc03_cards.white_07_01_03_01'),
    ('white_07_01_03_02', 'zz.pc03_cards.white_07_01_03_02'),
    ('white_07_02_03_00', 'zz.pc03_cards.white_07_02_03_00'),
    ('white_09_01_03_00', 'zz.pc03_cards.white_09_01_03_00'),
    ('yellow_00_00_03_00', 'zz.pc03_cards.yellow_00_00_03_00'),
    ('yellow_00_00_03_01', 'zz.pc03_cards.yellow_00_00_03_01'),
    ('yellow_00_00_03_02', 'zz.pc03_cards.yellow_00_00_03_02'),
    ('yellow_00_00_03_03', 'zz.pc03_cards.yellow_00_00_03_03'),
    ('yellow_00_00_03_04', 'zz.pc03_cards.yellow_00_00_03_04'),
    ('yellow_00_00_03_05', 'zz.pc03_cards.yellow_00_00_03_05'),
    ('yellow_01_01_03_00', 'zz.pc03_cards.yellow_01_01_03_00'),
    ('yellow_01_02_03_00', 'zz.pc03_cards.yellow_01_02_03_00'),
    ('yellow_02_01_03_00', 'zz.pc03_cards.yellow_02_01_03_00'),
    ('yellow_02_01_03_01', 'zz.pc03_cards.yellow_02_01_03_01'),
    ('yellow_03_01_03_00', 'zz.pc03_cards.yellow_03_01_03_00'),
    ('yellow_03_01_03_02', 'zz.pc03_cards.yellow_03_01_03_02'),
    ('yellow_03_01_03_03', 'zz.pc03_cards.yellow_03_01_03_03'),
    ('yellow_03_01_03_04', 'zz.pc03_cards.yellow_03_01_03_04'),
    ('yellow_03_01_03_05', 'zz.pc03_cards.yellow_03_01_03_05'),
    ('yellow_03_02_03_00', 'zz.pc03_cards.yellow_03_02_03_00'),
    ('yellow_04_01_03_00', 'zz.pc03_cards.yellow_04_01_03_00'),
    ('yellow_05_01_03_00', 'zz.pc03_cards.yellow_05_01_03_00'),
    ('yellow_05_01_03_01', 'zz.pc03_cards.yellow_05_01_03_01'),
    ('yellow_05_02_03_00', 'zz.pc03_cards.yellow_05_02_03_00'),
    ('yellow_06_01_03_00', 'zz.pc03_cards.yellow_06_01_03_00'),
    ('yellow_06_01_03_01', 'zz.pc03_cards.yellow_06_01_03_01'),
    ('yellow_06_01_03_02', 'zz.pc03_cards.yellow_06_01_03_02'),
    ('yellow_06_01_03_03', 'zz.pc03_cards.yellow_06_01_03_03'),
    ('yellow_08_01_03_00', 'zz.pc03_cards.yellow_08_01_03_00'),
)
PC03_CARD_IDS = tuple(card_id for card_id, _ in _MODULES)


def register_pc03_cards():
    with _CARD_TSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["image_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    outside_ids = set()
    for card_id, module_name in _MODULES:
        if card_id not in rows:
            raise RuntimeError(f"missing PC03 source row: {card_id}")
        if card_id in CARD_REGISTRY:
            raise RuntimeError(f"PC03 card already registered: {card_id}")
        module = import_module(module_name)
        if module.CARD_ID != card_id:
            raise RuntimeError(f"PC03 module identity mismatch: {module_name}")
        beast_id = getattr(module, "SUMMON_BEAST_CARD_ID", None)
        if beast_id:
            outside_ids.add(beast_id)
        for attribute in ("EVOLUTION_PAIRS", "LAHRS_UPGRADES"):
            outside_ids.update(target for _, target in getattr(module, attribute, ()))
        card = module.build_card(rows[card_id])
        if beast_id:
            card.cannot_move = True
        if card.id != card_id or card_id in CARD_REGISTRY:
            raise RuntimeError(f"PC03 build_card contract failed: {card_id}")
        register(card)
    for card_id in outside_ids:
        CARD_REGISTRY[card_id].deck_buildable = False
    return list(PC03_CARD_IDS)


register_pc03_cards()
