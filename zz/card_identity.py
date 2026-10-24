"""Shared printed-card identity rules for EX02 and EX02C reprints."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _explicit_equivalences() -> dict[str, str]:
    path = Path(__file__).resolve().parents[1] / "data" / "ex02_ex02c_equivalences.tsv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"canonical_card_id", "variant_card_id"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError(f"EX02 equivalence table is missing columns: {sorted(required)}")
        equivalences: dict[str, str] = {}
        variants: set[str] = set()
        for row in reader:
            canonical = (row.get("canonical_card_id") or "").strip()
            variant = (row.get("variant_card_id") or "").strip()
            if not canonical or not variant:
                raise ValueError("EX02 equivalence table contains an empty card id")
            if canonical in equivalences or canonical in variants:
                raise ValueError(f"EX02 equivalence table has ambiguous card id: {canonical}")
            if variant in equivalences or variant in variants:
                raise ValueError(f"EX02 equivalence table has ambiguous card id: {variant}")
            equivalences[canonical] = canonical
            equivalences[variant] = canonical
            variants.add(variant)
        return equivalences


def explicit_deck_copy_identity(card_id: str) -> str | None:
    """Return a stable shared identity only for an explicitly mapped pair."""
    if not isinstance(card_id, str) or not card_id:
        raise ValueError(f"invalid card id for deck-copy identity: {card_id!r}")
    canonical = _explicit_equivalences().get(card_id)
    return f"ex02-equivalent:{canonical}" if canonical else None


def explicitly_equivalent_card_ids(left: str, right: str) -> bool:
    """Whether two IDs are paired by the project-confirmed equivalence table."""
    left_identity = explicit_deck_copy_identity(left)
    return left_identity is not None and left_identity == explicit_deck_copy_identity(right)


def explicit_card_equivalence_pairs() -> tuple[tuple[str, str], ...]:
    """Return each declared original/variant pair once, in source-table order."""
    return tuple(
        (canonical, card_id)
        for card_id, canonical in _explicit_equivalences().items()
        if card_id != canonical
    )
