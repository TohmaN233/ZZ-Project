"""EX02C registry, assembled from independently authored card modules."""

from __future__ import annotations

import csv
from importlib import import_module
from pathlib import Path

from zz.cards import CARD_REGISTRY, register

_CARD_TSV = Path(__file__).with_name("ex02c_data.tsv")

_MODULES = (
    ('red_00_01_02c_00', 'zz.ex02c_cards.red_00_01_02c_00'),
    ('red_00_01_02c_01', 'zz.ex02c_cards.red_00_01_02c_01'),
    ('red_00_01_02c_02', 'zz.ex02c_cards.red_00_01_02c_02'),
    ('red_02_02_02c_00', 'zz.ex02c_cards.red_02_02_02c_00'),
    ('red_02_02_02c_01', 'zz.ex02c_cards.red_02_02_02c_01'),
    ('red_02_03_02c_00', 'zz.ex02c_cards.red_02_03_02c_00'),
    ('red_02_03_02c_01', 'zz.ex02c_cards.red_02_03_02c_01'),
    ('red_03_02_02c_00', 'zz.ex02c_cards.red_03_02_02c_00'),
    ('red_04_02_02c_00', 'zz.ex02c_cards.red_04_02_02c_00'),
    ('red_06_02_02c_00', 'zz.ex02c_cards.red_06_02_02c_00'),
    ('red_06_02_02c_01', 'zz.ex02c_cards.red_06_02_02c_01'),
    ('red_07_02_02c_02', 'zz.ex02c_cards.red_07_02_02c_02'),
    ('red_07_02_02c_00', 'zz.ex02c_cards.red_07_02_02c_00'),
    ('yellow_00_01_02c_00', 'zz.ex02c_cards.yellow_00_01_02c_00'),
    ('yellow_00_01_02c_01', 'zz.ex02c_cards.yellow_00_01_02c_01'),
    ('yellow_00_01_02c_03', 'zz.ex02c_cards.yellow_00_01_02c_03'),
    ('yellow_02_02_02c_00', 'zz.ex02c_cards.yellow_02_02_02c_00'),
    ('yellow_03_02_02c_00', 'zz.ex02c_cards.yellow_03_02_02c_00'),
    ('yellow_03_03_02c_00', 'zz.ex02c_cards.yellow_03_03_02c_00'),
    ('yellow_04_02_02c_00', 'zz.ex02c_cards.yellow_04_02_02c_00'),
    ('yellow_05_02_02c_00', 'zz.ex02c_cards.yellow_05_02_02c_00'),
    ('yellow_06_02_02c_00', 'zz.ex02c_cards.yellow_06_02_02c_00'),
    ('yellow_07_02_02c_00', 'zz.ex02c_cards.yellow_07_02_02c_00'),
    ('yellow_07_02_02c_1', 'zz.ex02c_cards.yellow_07_02_02c_1'),
    ('yellow_08_02_02c_00', 'zz.ex02c_cards.yellow_08_02_02c_00'),
    ('yellow_011_03_02c_00', 'zz.ex02c_cards.yellow_011_03_02c_00'),
    ('green_00_01_02c_00', 'zz.ex02c_cards.green_00_01_02c_00'),
    ('green_00_01_02c_01', 'zz.ex02c_cards.green_00_01_02c_01'),
    ('green_00_01_02c_02', 'zz.ex02c_cards.green_00_01_02c_02'),
    ('green_02_02_02c_03', 'zz.ex02c_cards.green_02_02_02c_03'),
    ('green_02_02_02c_00', 'zz.ex02c_cards.green_02_02_02c_00'),
    ('green_02_03_02c_00', 'zz.ex02c_cards.green_02_03_02c_00'),
    ('green_03_02_02c_00', 'zz.ex02c_cards.green_03_02_02c_00'),
    ('green_03_03_02c_00', 'zz.ex02c_cards.green_03_03_02c_00'),
    ('green_04_02_02c_00', 'zz.ex02c_cards.green_04_02_02c_00'),
    ('green_05_02_02c_00', 'zz.ex02c_cards.green_05_02_02c_00'),
    ('green_06_02_02c_00', 'zz.ex02c_cards.green_06_02_02c_00'),
    ('green_08_02_02c_00', 'zz.ex02c_cards.green_08_02_02c_00'),
    ('green_08_02_02c_01', 'zz.ex02c_cards.green_08_02_02c_01'),
    ('colorless_00_01_02c_00', 'zz.ex02c_cards.colorless_00_01_02c_00'),
    ('colorless_01_02_02c_00', 'zz.ex02c_cards.colorless_01_02_02c_00'),
    ('colorless_01_02_02c_01', 'zz.ex02c_cards.colorless_01_02_02c_01'),
    ('colorless_01_02_02c_02', 'zz.ex02c_cards.colorless_01_02_02c_02'),
    ('colorless_01_02_02c_03', 'zz.ex02c_cards.colorless_01_02_02c_03'),
    ('colorless_02_02_02c_04', 'zz.ex02c_cards.colorless_02_02_02c_04'),
    ('colorless_02_02_02c_05', 'zz.ex02c_cards.colorless_02_02_02c_05'),
    ('colorless_02_02_02c_00', 'zz.ex02c_cards.colorless_02_02_02c_00'),
    ('colorless_03_02_02c_01', 'zz.ex02c_cards.colorless_03_02_02c_01'),
    ('colorless_03_02_02c_02', 'zz.ex02c_cards.colorless_03_02_02c_02'),
    ('colorless_03_02_02c_03', 'zz.ex02c_cards.colorless_03_02_02c_03'),
    ('colorless_03_02_02c_00', 'zz.ex02c_cards.colorless_03_02_02c_00'),
    ('colorless_04_02_02c_00', 'zz.ex02c_cards.colorless_04_02_02c_00'),
    ('colorless_04_02_02c_01', 'zz.ex02c_cards.colorless_04_02_02c_01'),
    ('colorless_04_02_02c_02', 'zz.ex02c_cards.colorless_04_02_02c_02'),
    ('colorless_04_02_02c_03', 'zz.ex02c_cards.colorless_04_02_02c_03'),
    ('colorless_05_02_02c_00', 'zz.ex02c_cards.colorless_05_02_02c_00'),
    ('colorless_05_02_02c_01', 'zz.ex02c_cards.colorless_05_02_02c_01'),
    ('colorless_05_02_02c_02', 'zz.ex02c_cards.colorless_05_02_02c_02'),
    ('colorless_05_02_02c_03', 'zz.ex02c_cards.colorless_05_02_02c_03'),
    ('colorless_05_02_cp_00', 'zz.ex02c_cards.colorless_05_02_cp_00'),
    ('colorless_06_02_02c_00', 'zz.ex02c_cards.colorless_06_02_02c_00'),
    ('colorless_06_02_cp_00', 'zz.ex02c_cards.colorless_06_02_cp_00'),
    ('colorless_07_02_02c_00', 'zz.ex02c_cards.colorless_07_02_02c_00'),
    ('colorless_07_02_02c_01', 'zz.ex02c_cards.colorless_07_02_02c_01'),
    ('colorless_07_02_02c_02', 'zz.ex02c_cards.colorless_07_02_02c_02'),
    ('colorless_08_02_02c_00', 'zz.ex02c_cards.colorless_08_02_02c_00'),
    ('colorless_08_02_02c_01', 'zz.ex02c_cards.colorless_08_02_02c_01'),
    ('colorless_09_02_02c_00', 'zz.ex02c_cards.colorless_09_02_02c_00'),
    ('colorless_09_02_02c_01', 'zz.ex02c_cards.colorless_09_02_02c_01'),
    ('colorless_010_02_02c_00', 'zz.ex02c_cards.colorless_010_02_02c_00'),
)
EX02C_CARD_IDS = tuple(card_id for card_id, _ in _MODULES)


def register_ex02c_cards():
    with _CARD_TSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["image_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    for card_id, module_name in _MODULES:
        if card_id not in rows:
            raise RuntimeError(f"missing EX02C source row: {card_id}")
        if card_id in CARD_REGISTRY:
            raise RuntimeError(f"EX02C card already registered: {card_id}")
        module = import_module(module_name)
        if module.CARD_ID != card_id:
            raise RuntimeError(f"EX02C module identity mismatch: {module_name}")
        card = module.build_card(rows[card_id])
        if card.id != card_id or card_id in CARD_REGISTRY:
            raise RuntimeError(f"EX02C build_card contract failed: {card_id}")
        register(card)
    return list(EX02C_CARD_IDS)


register_ex02c_cards()
