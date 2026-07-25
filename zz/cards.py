from __future__ import annotations
from zz.model import Card


CARD_REGISTRY: dict[str, Card] = {}


def register(card: Card) -> Card:
    CARD_REGISTRY[card.id] = card
    return card
