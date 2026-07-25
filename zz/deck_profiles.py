from __future__ import annotations

from dataclasses import asdict, dataclass

import zz.pc01  # noqa: F401 - register PC01 cards as a side effect.
from zz.ai_deck_analysis import DeckSpec
from zz.card_profiles import CardProfile, build_card_profile
from zz.cards import CARD_REGISTRY


DECK_PROFILE_VERSION = "deck_profile_v1"


@dataclass
class DeckProfile:
    version: str
    deck_id: str
    name: str
    forces: tuple[str, ...]
    colors: tuple[str, ...]
    archetype_scores: dict[str, float]
    core_cards: tuple[str, ...]
    safe_base_cards: tuple[str, ...]
    protect_in_base_cards: tuple[str, ...]
    field_blocker_cards: tuple[str, ...]
    combo_routes: tuple[str, ...]
    preferred_early_plan: tuple[str, ...]
    preferred_midgame_plan: tuple[str, ...]
    preferred_endgame_plan: tuple[str, ...]
    resource_sensitive: bool

    def to_dict(self) -> dict:
        return asdict(self)


def build_deck_profile(deck: DeckSpec) -> DeckProfile:
    profiles = _recipe_profiles(deck)
    profile_by_id = {card_id: profile for card_id, _count, profile in profiles}
    colors = tuple(sorted({
        profile.identity.color
        for _card_id, _count, profile in profiles
        if profile.identity.color and profile.identity.color != "colorless"
    }))

    archetype_scores = _archetype_scores(deck, profiles)
    combo_routes = _combo_routes(deck, profiles)
    resource_sensitive = _resource_sensitive(deck, profiles, archetype_scores)

    early_plan = ["base_growth"]
    if resource_sensitive or archetype_scores["control"] >= archetype_scores["aggro"]:
        early_plan.append("hold_defense")
    if archetype_scores["aggro"] > archetype_scores["control"]:
        early_plan.append("pressure")
    if archetype_scores["combo"] > 0:
        early_plan.append("draw_search_setup")

    midgame_plan = ["stabilize"]
    if archetype_scores["combo"] > 0:
        midgame_plan.append("protect_combo_piece")
    if archetype_scores["control"] >= archetype_scores["aggro"]:
        midgame_plan.append("remove_threat")

    endgame_plan = ["lethal_push"]
    if "life_exchange" in combo_routes:
        endgame_plan.append("force_life_exchange")

    return DeckProfile(
        version=DECK_PROFILE_VERSION,
        deck_id=deck.id,
        name=deck.name,
        forces=tuple(deck.forces),
        colors=colors,
        archetype_scores=archetype_scores,
        core_cards=tuple(sorted(
            card_id
            for card_id, count in deck.recipe.items()
            if count >= 3 or (card_id in profile_by_id and profile_by_id[card_id].zone_value.protect_in_base)
        )),
        safe_base_cards=_zone_cards(profiles, "good_mana_card"),
        protect_in_base_cards=_zone_cards(profiles, "protect_in_base"),
        field_blocker_cards=_zone_cards(profiles, "stay_field_as_blocker"),
        combo_routes=combo_routes,
        preferred_early_plan=tuple(early_plan),
        preferred_midgame_plan=tuple(midgame_plan),
        preferred_endgame_plan=tuple(endgame_plan),
        resource_sensitive=resource_sensitive,
    )


def _recipe_profiles(deck: DeckSpec) -> list[tuple[str, int, CardProfile]]:
    profiles = []
    for card_id, count in deck.recipe.items():
        card = CARD_REGISTRY.get(card_id)
        if card is None:
            continue
        profiles.append((card_id, count, build_card_profile(card)))
    return profiles


def _archetype_scores(deck: DeckSpec, profiles: list[tuple[str, int, CardProfile]]) -> dict[str, float]:
    aggro = 0.0
    control = 0.0
    combo = 0.0
    ramp = 0.0
    midrange = 0.4
    stall = 0.0
    force_break = 0.0
    life_exchange = 0.0
    total_cards = sum(count for _card_id, count, _profile in profiles)

    force_ids = set(deck.forces)
    if {"force_kai", "force_chi"} & force_ids:
        control += 2.0
    if {"force_kon", "force_sei"} & force_ids:
        combo += 2.0
        life_exchange += 1.0
    if "aice" in deck.name.lower() or deck.id == "aice":
        combo += 2.0
        life_exchange += 1.0

    for _card_id, count, profile in profiles:
        roles = set(profile.roles)
        cost = profile.identity.cost_total
        if profile.identity.card_type == "f_minion" and cost <= 2:
            aggro += count
        if "finisher" in roles or "buff" in roles:
            aggro += 1.5 * count
            force_break += 0.5 * count
        if "removal" in roles or "draw" in roles or profile.identity.color == "blue":
            control += count
        if profile.zone_value.good_mana_card:
            ramp += count
        if profile.identity.card_type == "f_minion" and 3 <= cost <= 5:
            midrange += count
        if profile.zone_value.stay_field_as_blocker:
            stall += count
        if "combo_piece" in roles:
            combo += 2.0 * count
        if "life_exchange" in roles:
            life_exchange += 2.0 * count
            combo += count

    if total_cards:
        ramp = ramp / total_cards
    stall += control * 0.25

    return {
        "aggro": float(aggro),
        "control": float(control),
        "combo": float(combo),
        "ramp": float(ramp),
        "midrange": float(midrange),
        "stall": float(stall),
        "force_break": float(force_break),
        "life_exchange": float(life_exchange),
    }


def _combo_routes(deck: DeckSpec, profiles: list[tuple[str, int, CardProfile]]) -> tuple[str, ...]:
    routes = {
        role
        for _card_id, _count, profile in profiles
        for role in profile.roles
        if role in {"life_exchange", "trash_recursion"}
    }
    if deck.id == "aice" or {"force_kon", "force_sei"} <= set(deck.forces):
        routes.add("life_exchange")
    return tuple(sorted(routes))


def _resource_sensitive(
    deck: DeckSpec,
    profiles: list[tuple[str, int, CardProfile]],
    archetype_scores: dict[str, float],
) -> bool:
    colors = {
        profile.identity.color
        for _card_id, _count, profile in profiles
        if profile.identity.color and profile.identity.color != "colorless"
    }
    return (
        len(colors) > 1
        or archetype_scores["control"] >= archetype_scores["aggro"]
        or bool({"force_kai", "force_chi"} & set(deck.forces))
    )


def _zone_cards(profiles: list[tuple[str, int, CardProfile]], field_name: str) -> tuple[str, ...]:
    return tuple(sorted(
        card_id
        for card_id, _count, profile in profiles
        if getattr(profile.zone_value, field_name)
    ))
