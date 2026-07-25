from typing import Callable

from zz.cards import CARD_REGISTRY
from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
import zz.pc01  # noqa: F401 - registers PC:01 cards not already hand-authored
import zz.basic  # noqa: F401 - registers Basic non-token cards not already hand-authored
from zz.forces import ALL_FORCES
from zz.model import CardInstance, Player


OFFICIAL_CARD_ID_PREFIXES = (
    "red_",
    "yellow_",
    "white_",
    "green_",
    "blue_",
    "purple_",
    "colorless_",
)

STANDARD_MAX_COPIES = 3
DECK_SIZE = 40
UNLIMITED_COPIES_TEXT = "何枚でもデッキに入れられる"


def is_user_deck_card_id(card_id: str) -> bool:
    return card_id in CARD_REGISTRY and card_id.startswith(OFFICIAL_CARD_ID_PREFIXES)


def card_allows_unlimited_copies(card_id: str) -> bool:
    card = CARD_REGISTRY.get(card_id)
    return bool(card and UNLIMITED_COPIES_TEXT in (card.ability_jp or ""))


def deck_card_max_copies(card_id: str) -> int:
    return DECK_SIZE if card_allows_unlimited_copies(card_id) else STANDARD_MAX_COPIES


AGUMA_RED_RECIPE: dict[str, int] = {
    "red_00_01_00_00": 16,
    "red_00_01_01_00": 3,
    "red_01_02_01_00": 3,
    "red_02_02_00_00": 3,
    "red_02_02_00_01": 3,
    "red_02_02_01_00": 3,
    "red_03_02_00_00": 3,
    "red_03_02_01_01": 3,
    "red_04_02_01_00": 3,
}


AGUMA_FORCES: list[str] = ["force_e", "force_kon"]   # Cyclops + Chimera


def validate_recipe(recipe: dict[str, int]) -> None:
    """40 cards total, max 3 copies — but starter packs historically allowed 4 of basics.
    For MVP we accept any per-card count; just enforce 40 total."""
    total = sum(recipe.values())
    if total != DECK_SIZE:
        raise ValueError(f"deck must be exactly {DECK_SIZE} cards (got {total})")
    for cid in recipe:
        if cid not in CARD_REGISTRY:
            raise ValueError(f"unknown card id: {cid}")


def validate_user_deck_recipe(recipe: dict[str, int]) -> None:
    validate_recipe(recipe)
    for cid, count in recipe.items():
        if not is_user_deck_card_id(cid):
            raise ValueError(f"legacy placeholder card is not deck-buildable: {cid}")
        max_copies = deck_card_max_copies(cid)
        if count > max_copies:
            raise ValueError(f"{cid} allows at most {max_copies} copies (got {count})")


def validate_forces(force_ids: list[str]) -> None:
    if len(force_ids) != 2:
        raise ValueError(f"exactly 2 Forces required (got {len(force_ids)})")
    if force_ids[0] == force_ids[1]:
        raise ValueError("the 2 Forces must be different")
    for fid in force_ids:
        if fid not in ALL_FORCES:
            raise ValueError(f"unknown force id: {fid}")


def build_deck(
        recipe: dict[str, int],
        owner: Player,
        iid_factory: Callable[[], int] | None = None,
) -> list[CardInstance]:
    validate_recipe(recipe)
    out: list[CardInstance] = []
    for card_id, count in recipe.items():
        card = CARD_REGISTRY[card_id]
        for _ in range(count):
            if iid_factory is None:
                out.append(CardInstance(card=card, owner=owner))
            else:
                out.append(CardInstance(card=card, owner=owner, iid=iid_factory()))
    return out
