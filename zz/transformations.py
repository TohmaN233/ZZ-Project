"""Verified transformation identities across packs, independent of OCR wrapping.

The table is curated from named Japanese transformation clauses and their
transformed faces. It includes truncated OCR clauses cross-checked against the
opposing face and the existing PC02R callbacks; IDs are never guessed by suffix.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def transformation_graph() -> dict[str, tuple[str, ...]]:
    root = Path(__file__).resolve().parents[1]
    with (root / "data/cards_bilingual_v4.tsv").open(encoding="utf-8-sig", newline="") as handle:
        known_ids = {row["image_id"] for row in csv.DictReader(handle, delimiter="\t")}
    edges: dict[str, list[str]] = {}
    with (root / "data/card_transformations.tsv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            source, target = row["source_id"], row["target_id"]
            if source not in known_ids or target not in known_ids or source == target:
                raise ValueError(f"invalid transformation identity: {source} -> {target}")
            targets = edges.setdefault(source, [])
            if target in targets:
                raise ValueError(f"duplicate transformation identity: {source} -> {target}")
            targets.append(target)
    return {source: tuple(targets) for source, targets in edges.items()}


def is_transformed_card_id(card_id: str) -> bool:
    return any(card_id in targets for targets in transformation_graph().values())


def transformation_target_id(source_id: str, equivalent_target_id: str) -> str:
    """Resolve a shared transformation rule to this printed face's declared edge."""
    from zz.card_identity import explicitly_equivalent_card_ids

    matches = [
        target for target in transformation_graph().get(source_id, ())
        if target == equivalent_target_id or explicitly_equivalent_card_ids(target, equivalent_target_id)
    ]
    if len(matches) != 1:
        raise ValueError(f"No unique declared transformation: {source_id} -> {equivalent_target_id}")
    return matches[0]


def apply_transformation_metadata(card) -> None:
    card.transformation_ids = transformation_graph().get(card.id, card.transformation_ids)
    if is_transformed_card_id(card.id):
        card.deck_buildable = False
