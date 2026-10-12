"""PC:02R registry, assembled from independently authored card modules."""

from __future__ import annotations

import csv
from importlib import import_module
from pathlib import Path

from zz.cards import CARD_REGISTRY, register

_CARD_TSV = Path(__file__).with_name("pc02r_data.tsv")

_MODULES = (
    ('red_00_01_02r_00', 'zz.pc02r_cards.red_00_01_02r_00'),
    ('red_00_01_02r_01', 'zz.pc02r_cards.red_00_01_02r_01'),
    ('red_02_02_02r_00', 'zz.pc02r_cards.red_02_02_02r_00'),
    ('red_02_02_02r_01', 'zz.pc02r_cards.red_02_02_02r_01'),
    ('red_02_03_02r_00', 'zz.pc02r_cards.red_02_03_02r_00'),
    ('red_02_03_02r_01', 'zz.pc02r_cards.red_02_03_02r_01'),
    ('red_04_02_02r_00', 'zz.pc02r_cards.red_04_02_02r_00'),
    ('red_04_02_02r_01', 'zz.pc02r_cards.red_04_02_02r_01'),
    ('red_05_02_02r_00', 'zz.pc02r_cards.red_05_02_02r_00'),
    ('red_06_02_02r_00', 'zz.pc02r_cards.red_06_02_02r_00'),
    ('red_07_02_02r_00', 'zz.pc02r_cards.red_07_02_02r_00'),
    ('red_07_02_02r_01', 'zz.pc02r_cards.red_07_02_02r_01'),
    ('red_07_02_02r_02', 'zz.pc02r_cards.red_07_02_02r_02'),
    ('red_08_02_02r_00', 'zz.pc02r_cards.red_08_02_02r_00'),
    ('yellow_00_01_02r_00', 'zz.pc02r_cards.yellow_00_01_02r_00'),
    ('yellow_00_01_02r_01', 'zz.pc02r_cards.yellow_00_01_02r_01'),
    ('yellow_01_03_02r_00', 'zz.pc02r_cards.yellow_01_03_02r_00'),
    ('yellow_02_02_02r_00', 'zz.pc02r_cards.yellow_02_02_02r_00'),
    ('yellow_02_02_02r_01', 'zz.pc02r_cards.yellow_02_02_02r_01'),
    ('yellow_03_02_02r_00', 'zz.pc02r_cards.yellow_03_02_02r_00'),
    ('yellow_04_02_02r_00', 'zz.pc02r_cards.yellow_04_02_02r_00'),
    ('yellow_04_02_02r_01', 'zz.pc02r_cards.yellow_04_02_02r_01'),
    ('yellow_04_02_02r_02', 'zz.pc02r_cards.yellow_04_02_02r_02'),
    ('yellow_05_03_02r_00', 'zz.pc02r_cards.yellow_05_03_02r_00'),
    ('yellow_06_02_02r_00', 'zz.pc02r_cards.yellow_06_02_02r_00'),
    ('yellow_07_02_02r_00', 'zz.pc02r_cards.yellow_07_02_02r_00'),
    ('yellow_07_02_02r_01', 'zz.pc02r_cards.yellow_07_02_02r_01'),
    ('yellow_08_02_02r_00', 'zz.pc02r_cards.yellow_08_02_02r_00'),
    ('purple_00_01_02r_00', 'zz.pc02r_cards.purple_00_01_02r_00'),
    ('purple_00_01_02r_01', 'zz.pc02r_cards.purple_00_01_02r_01'),
    ('purple_02_02_02r_00', 'zz.pc02r_cards.purple_02_02_02r_00'),
    ('purple_03_02_02r_00', 'zz.pc02r_cards.purple_03_02_02r_00'),
    ('purple_03_02_02r_01', 'zz.pc02r_cards.purple_03_02_02r_01'),
    ('purple_03_03_02r_00', 'zz.pc02r_cards.purple_03_03_02r_00'),
    ('purple_04_02_02r_00', 'zz.pc02r_cards.purple_04_02_02r_00'),
    ('purple_04_02_02r_01', 'zz.pc02r_cards.purple_04_02_02r_01'),
    ('purple_04_03_02r_00', 'zz.pc02r_cards.purple_04_03_02r_00'),
    ('purple_05_02_02r_00', 'zz.pc02r_cards.purple_05_02_02r_00'),
    ('purple_06_02_02r_01', 'zz.pc02r_cards.purple_06_02_02r_01'),
    ('purple_06_02_02r_00', 'zz.pc02r_cards.purple_06_02_02r_00'),
    ('purple_07_02_02r_00', 'zz.pc02r_cards.purple_07_02_02r_00'),
    ('purple_07_02_02r_01', 'zz.pc02r_cards.purple_07_02_02r_01'),
    ('green_00_01_02r_00', 'zz.pc02r_cards.green_00_01_02r_00'),
    ('green_00_01_02r_01', 'zz.pc02r_cards.green_00_01_02r_01'),
    ('green_01_03_02r_00', 'zz.pc02r_cards.green_01_03_02r_00'),
    ('green_02_02_02r_00', 'zz.pc02r_cards.green_02_02_02r_00'),
    ('green_02_03_02r_00', 'zz.pc02r_cards.green_02_03_02r_00'),
    ('green_03_02_02r_00', 'zz.pc02r_cards.green_03_02_02r_00'),
    ('green_04_02_02r_00', 'zz.pc02r_cards.green_04_02_02r_00'),
    ('green_04_02_02r_01', 'zz.pc02r_cards.green_04_02_02r_01'),
    ('green_05_02_02r_00', 'zz.pc02r_cards.green_05_02_02r_00'),
    ('green_06_02_02r_00', 'zz.pc02r_cards.green_06_02_02r_00'),
    ('green_06_02_02r_01', 'zz.pc02r_cards.green_06_02_02r_01'),
    ('green_07_02_02r_00', 'zz.pc02r_cards.green_07_02_02r_00'),
    ('green_07_02_02r_01', 'zz.pc02r_cards.green_07_02_02r_01'),
    ('green_08_02_02r_00', 'zz.pc02r_cards.green_08_02_02r_00'),
    ('blue_00_01_02r_00', 'zz.pc02r_cards.blue_00_01_02r_00'),
    ('blue_00_01_02r_01', 'zz.pc02r_cards.blue_00_01_02r_01'),
    ('blue_01_03_02r_00', 'zz.pc02r_cards.blue_01_03_02r_00'),
    ('blue_02_02_02r_00', 'zz.pc02r_cards.blue_02_02_02r_00'),
    ('blue_03_02_02r_00', 'zz.pc02r_cards.blue_03_02_02r_00'),
    ('blue_04_02_02r_00', 'zz.pc02r_cards.blue_04_02_02r_00'),
    ('blue_04_02_02r_01', 'zz.pc02r_cards.blue_04_02_02r_01'),
    ('blue_04_02_02r_02', 'zz.pc02r_cards.blue_04_02_02r_02'),
    ('blue_04_03_02r_00', 'zz.pc02r_cards.blue_04_03_02r_00'),
    ('blue_05_02_02r_00', 'zz.pc02r_cards.blue_05_02_02r_00'),
    ('blue_06_02_02r_00', 'zz.pc02r_cards.blue_06_02_02r_00'),
    ('blue_06_02_02r_01', 'zz.pc02r_cards.blue_06_02_02r_01'),
    ('blue_07_02_02r_00', 'zz.pc02r_cards.blue_07_02_02r_00'),
    ('blue_07_02_02r_01', 'zz.pc02r_cards.blue_07_02_02r_01'),
    ('white_00_01_02r_00', 'zz.pc02r_cards.white_00_01_02r_00'),
    ('white_00_01_02r_01', 'zz.pc02r_cards.white_00_01_02r_01'),
    ('white_02_02_02r_00', 'zz.pc02r_cards.white_02_02_02r_00'),
    ('white_02_03_02r_00', 'zz.pc02r_cards.white_02_03_02r_00'),
    ('white_03_02_02r_00', 'zz.pc02r_cards.white_03_02_02r_00'),
    ('white_04_02_02r_00', 'zz.pc02r_cards.white_04_02_02r_00'),
    ('white_04_02_02r_01', 'zz.pc02r_cards.white_04_02_02r_01'),
    ('white_04_02_02r_02', 'zz.pc02r_cards.white_04_02_02r_02'),
    ('white_05_02_02r_00', 'zz.pc02r_cards.white_05_02_02r_00'),
    ('white_05_03_02r_00', 'zz.pc02r_cards.white_05_03_02r_00'),
    ('white_06_02_02r_00', 'zz.pc02r_cards.white_06_02_02r_00'),
    ('white_06_02_02r_01', 'zz.pc02r_cards.white_06_02_02r_01'),
    ('white_07_02_02r_00', 'zz.pc02r_cards.white_07_02_02r_00'),
    ('white_07_02_02r_01', 'zz.pc02r_cards.white_07_02_02r_01'),
    ('colorless_00_02_02r_00', 'zz.pc02r_cards.colorless_00_02_02r_00'),
    ('colorless_00_01_02r_00', 'zz.pc02r_cards.colorless_00_01_02r_00'),
    ('colorless_01_02_02r_00', 'zz.pc02r_cards.colorless_01_02_02r_00'),
    ('colorless_02_02_02r_00', 'zz.pc02r_cards.colorless_02_02_02r_00'),
    ('colorless_02_02_02r_01', 'zz.pc02r_cards.colorless_02_02_02r_01'),
    ('colorless_03_02_02r_00', 'zz.pc02r_cards.colorless_03_02_02r_00'),
    ('colorless_03_02_02r_01', 'zz.pc02r_cards.colorless_03_02_02r_01'),
    ('colorless_03_02_02r_02', 'zz.pc02r_cards.colorless_03_02_02r_02'),
    ('colorless_04_02_02r_01', 'zz.pc02r_cards.colorless_04_02_02r_01'),
    ('colorless_03_02_02r_03', 'zz.pc02r_cards.colorless_03_02_02r_03'),
    ('colorless_04_02_02r_00', 'zz.pc02r_cards.colorless_04_02_02r_00'),
    ('colorless_04_02_02r_02', 'zz.pc02r_cards.colorless_04_02_02r_02'),
    ('colorless_04_02_02r_03', 'zz.pc02r_cards.colorless_04_02_02r_03'),
    ('colorless_05_02_02r_00', 'zz.pc02r_cards.colorless_05_02_02r_00'),
    ('colorless_05_02_02r_01', 'zz.pc02r_cards.colorless_05_02_02r_01'),
    ('colorless_06_02_02r_00', 'zz.pc02r_cards.colorless_06_02_02r_00'),
    ('colorless_06_02_02r_01', 'zz.pc02r_cards.colorless_06_02_02r_01'),
    ('colorless_07_02_02r_00', 'zz.pc02r_cards.colorless_07_02_02r_00'),
    ('colorless_07_02_02r_01', 'zz.pc02r_cards.colorless_07_02_02r_01'),
    ('colorless_08_02_02r_00', 'zz.pc02r_cards.colorless_08_02_02r_00'),
    ('colorless_09_02_02r_00', 'zz.pc02r_cards.colorless_09_02_02r_00'),
    ('colorless_010_02_02r_00', 'zz.pc02r_cards.colorless_010_02_02r_00'),
)
PC02R_CARD_IDS = tuple(card_id for card_id, _ in _MODULES)


def _register_transformation_metadata() -> None:
    from zz.transformations import transformation_graph
    # Reuse the exact identities consumed by the card callbacks, never infer
    # transformed faces from their names, printed keywords, or ID suffixes.
    anju = import_module("zz.pc02r_cards.colorless_04_02_02r_01")
    anju_forms = tuple(anju._ANJU_FORMS.values())
    relationships = {anju.CARD_ID: anju_forms}
    for form_id in anju_forms:
        module = import_module(f"zz.pc02r_cards.{form_id}")
        if set(module._ANJU_FORMS.values()) != set(anju_forms):
            raise RuntimeError(f"PC:02R Anju transformation identity mismatch: {form_id}")
        relationships[form_id] = tuple(target for target in anju_forms if target != form_id)
    for module_name, target_attribute in (
        ("red_07_02_02r_00", "_TRANSFORMED_FORM_ID"),
        ("blue_07_02_02r_00", "TRANSFORMED_CARD_ID"),
        ("green_07_02_02r_00", "TRANSFORMED_CARD_ID"),
        ("white_07_02_02r_00", "TRANSFORMED_CARD_ID"),
        ("yellow_07_02_02r_00", "_TRANSFORMED_CARD_ID"),
        ("purple_07_02_02r_00", "_TRANSFORMED_FORM_ID"),
    ):
        module = import_module(f"zz.pc02r_cards.{module_name}")
        relationships[module.CARD_ID] = (getattr(module, target_attribute),)
    for source_id, targets in relationships.items():
        if transformation_graph().get(source_id) != targets:
            raise RuntimeError(f"PC:02R transformation table disagrees with card rules: {source_id}")
        for card_id in (source_id, *targets):
            if card_id not in CARD_REGISTRY:
                raise RuntimeError(f"PC:02R transformation card is not registered: {source_id} -> {card_id}")
    for source_id, targets in relationships.items():
        CARD_REGISTRY[source_id].transformation_ids = targets
        for target_id in targets:
            CARD_REGISTRY[target_id].deck_buildable = False


def register_pc02r_cards():
    with _CARD_TSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["image_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    for card_id, module_name in _MODULES:
        if card_id not in rows:
            raise RuntimeError(f"missing PC:02R source row: {card_id}")
        if card_id in CARD_REGISTRY:
            raise RuntimeError(f"PC:02R card already registered: {card_id}")
        module = import_module(module_name)
        if module.CARD_ID != card_id:
            raise RuntimeError(f"PC:02R module identity mismatch: {module_name}")
        card = module.build_card(rows[card_id])
        if card.id != card_id or card_id in CARD_REGISTRY:
            raise RuntimeError(f"PC:02R build_card contract failed: {card_id}")
        register(card)
    _register_transformation_metadata()
    return list(PC02R_CARD_IDS)


register_pc02r_cards()
