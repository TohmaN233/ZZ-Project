from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from zz.enums import AreaType, CardType, Keyword

if TYPE_CHECKING:
    from zz.model import CardInstance, Player


@dataclass(frozen=True)
class KeywordDefinition:
    keyword: Keyword
    jp_name: str
    en_name: str
    rules_summary: str
    implemented: bool = True
    parameter: str | None = None


OFFICIAL_KEYWORDS: dict[Keyword, KeywordDefinition] = {
    Keyword.REAWAKEN: KeywordDefinition(
        Keyword.REAWAKEN,
        "再起",
        "Reawaken",
        "At the end of your turn, refresh this minion.",
    ),
    Keyword.RUSH: KeywordDefinition(
        Keyword.RUSH,
        "襲撃",
        "Rush",
        "This minion can attack the player on the turn it entered the field.",
    ),
    Keyword.SNEAKING: KeywordDefinition(
        Keyword.SNEAKING,
        "潜入",
        "Infiltrate",
        "This minion can only be blocked by minions with the same cost.",
    ),
    Keyword.FLYING: KeywordDefinition(
        Keyword.FLYING,
        "飛来",
        "Flash Summon",
        "This field minion card can be summoned during flash timing by paying its cost.",
    ),
    Keyword.DEATH_BLOW: KeywordDefinition(
        Keyword.DEATH_BLOW,
        "奪命",
        "Deathblow",
        "During your turn, destroy the minion this minion battled at battle end.",
    ),
    Keyword.PENETRATE: KeywordDefinition(
        Keyword.PENETRATE,
        "貫通",
        "Penetrate",
        "When this minion wins a battle on your turn, deal DP minus 1 damage to the original attack target.",
    ),
    Keyword.COOPERATION: KeywordDefinition(
        Keyword.COOPERATION,
        "連携",
        "Cooperation",
        "If a specified color of your mana was placed this turn when used from hand, draw 1 card.",
        implemented=False,
        parameter="color",
    ),
}


def has_keyword(ci: "CardInstance", keyword: Keyword) -> bool:
    return keyword in ci.keywords


def total_cost(ci: "CardInstance") -> int:
    return sum(ci.card.cost.values())


def enters_without_summoning_sickness(ci: "CardInstance") -> bool:
    return has_keyword(ci, Keyword.RUSH)


def can_attack_player(
    attacker: "CardInstance",
    *,
    no_forces_left: bool,
    present_at_turn_start: bool,
) -> bool:
    if no_forces_left:
        return True
    if has_keyword(attacker, Keyword.RUSH):
        return True
    if attacker.summoning_sickness:
        return False
    return present_at_turn_start


def can_block_attacker(blocker: "CardInstance", attacker: "CardInstance", active: "Player" | None = None) -> bool:
    if blocker.rested:
        return False
    if has_keyword(blocker, Keyword.CANNOT_BLOCK):
        return False
    if has_keyword(attacker, Keyword.UNBLOCKABLE) or "unblockable" in attacker.flags:
        return False
    if "unblockable_by_cost_at_most_3" in attacker.flags and total_cost(blocker) <= 3:
        return False
    if has_keyword(attacker, Keyword.SNEAKING):
        return total_cost(blocker) == total_cost(attacker)
    return True


def is_flash_summonable(ci: "CardInstance") -> bool:
    return ci.card.type is CardType.F_MINION and has_keyword(ci, Keyword.FLYING)


def should_reawaken(ci: "CardInstance", active: "Player") -> bool:
    return (
        ci.owner is active
        and ci.area is AreaType.FIELD
        and has_keyword(ci, Keyword.REAWAKEN)
    )


def has_penetrate(ci: "CardInstance") -> bool:
    return has_keyword(ci, Keyword.PENETRATE)


def should_death_blow_destroy(
    source: "CardInstance",
    opponent: "CardInstance",
    active: "Player",
) -> bool:
    return (
        source.owner is active
        and source.card.type in {CardType.F_MINION, CardType.B_MINION}
        and opponent.card.type in {CardType.F_MINION, CardType.B_MINION}
        and has_keyword(source, Keyword.DEATH_BLOW)
    )
