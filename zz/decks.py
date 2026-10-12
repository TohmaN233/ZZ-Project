import csv
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re
from typing import Callable
import unicodedata

from zz.cards import CARD_REGISTRY
from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
import zz.pc01  # noqa: F401 - registers PC:01 cards not already hand-authored
import zz.basic  # noqa: F401 - registers Basic non-token cards not already hand-authored
import zz.ex01  # noqa: F401 - registers EX:01 cards
import zz.pc01r  # noqa: F401 - registers PC:01R cards
import zz.pc02  # noqa: F401 - registers PC:02 cards
import zz.pc02r  # noqa: F401 - registers PC:02R DIVINE cards
from zz.forces import ALL_FORCES
from zz.enums import CardType
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


@lru_cache(maxsize=1)
def _deck_copy_sources() -> dict[str, tuple[str, str]]:
    """Authoritative Japanese name and complete effect text for printed cards."""
    data_root = Path(__file__).resolve().parents[1] / "data"
    with (data_root / "official_cardlist.tsv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not {"image_id", "official_name_jp"}.issubset(reader.fieldnames or ()):
            raise ValueError("official card source is missing copy-identity columns")
        names = {row["image_id"]: row["official_name_jp"] for row in reader}
    with (data_root / "cards_bilingual_v4.tsv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not {"image_id", "name_jp", "ability_jp"}.issubset(reader.fieldnames or ()):
            raise ValueError("Japanese card source is missing copy-identity columns")
        sources = {}
        for row in reader:
            card_id = row["image_id"]
            if not card_id or card_id in sources:
                raise ValueError(f"invalid or duplicate Japanese card identity: {card_id}")
            name = names.get(card_id) or row["name_jp"]
            if not name.strip():
                raise ValueError(f"Japanese card name is missing: {card_id}")
            sources[card_id] = (name, row["ability_jp"])
        return sources


@lru_cache(maxsize=4096)
def _normalize_copy_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text.replace("\\n", "\n"))
    text = re.sub(r"\s+", "", text)
    # A turn-qualified timing appears as either one label or adjacent labels.
    return re.sub(r"【(自分のターン|相手のターン):([^【】]+)】", r"【\1】【\2】", text)


def _deck_card_japanese_source(card_id: str) -> tuple[str, str]:
    if card_id not in CARD_REGISTRY:
        raise ValueError(f"unknown card id: {card_id}")
    card = CARD_REGISTRY[card_id]
    sources = _deck_copy_sources()
    # Generated/test cards have no printed source-table record.
    return sources[card_id] if card_id in sources else (card.name_jp, card.ability_jp or "")


def deck_card_copy_identity(card_id: str) -> str:
    name, ability = _deck_card_japanese_source(card_id)
    identity = f"{_normalize_copy_text(name)}\0{_normalize_copy_text(ability)}"
    return "jp:" + sha256(identity.encode("utf-8")).hexdigest()


def deck_card_copy_count(recipe: dict[str, int], card_id: str) -> int:
    identity = deck_card_copy_identity(card_id)
    return sum(count for cid, count in recipe.items() if deck_card_copy_identity(cid) == identity)


def is_catalog_card_id(card_id: str) -> bool:
    """Official non-token cards, including faces obtainable by transformation."""
    card = CARD_REGISTRY.get(card_id)
    return bool(
        card
        and card_id.startswith(OFFICIAL_CARD_ID_PREFIXES)
        and not card.is_token
        and card.type is not CardType.MANA_TOKEN
    )


def is_user_deck_card_id(card_id: str) -> bool:
    return is_catalog_card_id(card_id) and CARD_REGISTRY[card_id].deck_buildable


def card_allows_unlimited_copies(card_id: str) -> bool:
    card = CARD_REGISTRY.get(card_id)
    return bool(card and UNLIMITED_COPIES_TEXT in _normalize_copy_text(_deck_card_japanese_source(card_id)[1]))


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
        card = CARD_REGISTRY[cid]
        if card.is_token or card.type is CardType.MANA_TOKEN or not card.deck_buildable:
            raise ValueError(f"card is not deck-buildable: {cid}")


def validate_user_deck_recipe(recipe: dict[str, int]) -> None:
    validate_recipe(recipe)
    copy_groups: dict[str, list[str]] = {}
    for cid in recipe:
        if not is_user_deck_card_id(cid):
            raise ValueError(f"legacy placeholder card is not deck-buildable: {cid}")
        copy_groups.setdefault(deck_card_copy_identity(cid), []).append(cid)
    for card_ids in copy_groups.values():
        count = sum(recipe[cid] for cid in card_ids)
        max_copies = deck_card_max_copies(card_ids[0])
        if count > max_copies:
            raise ValueError(f"{' / '.join(card_ids)} allows at most {max_copies} copies combined (got {count})")


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
