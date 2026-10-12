from __future__ import annotations
from zz.model import Card


CARD_REGISTRY: dict[str, Card] = {}


def register(card: Card) -> Card:
    from zz.transformations import apply_transformation_metadata

    apply_transformation_metadata(card)
    CARD_REGISTRY[card.id] = card
    return card
