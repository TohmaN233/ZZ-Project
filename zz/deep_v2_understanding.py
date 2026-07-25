from __future__ import annotations

from typing import Any, Mapping

import zz.basic  # noqa: F401 - register Basic cards used by legacy tests.
import zz.pc01  # noqa: F401 - register PC:01 cards used by player decks.
from zz.ai_deck_analysis import DeckSpec
from zz.card_profiles import build_card_profile
from zz.cards import CARD_REGISTRY
from zz.deck_profiles import build_deck_profile


DEEP_V2_UNDERSTANDING_ROW_VERSION = "deep_v2_understanding_rows_v1"
UNDERSTANDING_PREFERENCE_VERSION = "public_deep_v2_understanding_preference_v1"


def build_card_understanding_rows(cards: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    source = cards if cards is not None else CARD_REGISTRY
    return [
        card_understanding_row(card)
        for _card_id, card in sorted(source.items(), key=lambda item: str(item[0]))
    ]


def card_understanding_row(card: Any) -> dict[str, Any]:
    profile = build_card_profile(card)
    features: dict[str, float] = {
        "understanding:card": 1.0,
        f"raw_card_type:{profile.identity.card_type}": 1.0,
        f"raw_color:{profile.identity.color or 'none'}": 1.0,
        f"raw_mana_color:{profile.identity.mana_color or 'none'}": 1.0,
        f"raw_cost_bucket:{min(8, int(profile.identity.cost_total))}": 1.0,
        f"raw_bp_bucket:{_bucket(profile.identity.bp, 100)}": 1.0,
        f"raw_dp:{int(profile.identity.dp)}": 1.0,
    }
    for effect in getattr(card, "effects", []) or []:
        template_id = str(getattr(effect, "template_id", "") or "")
        if template_id:
            features[f"raw_effect:{template_id}"] = 1.0
        target_kind = str(getattr(effect, "target_kind", "") or "")
        if target_kind:
            features[f"raw_target_kind:{target_kind}"] = 1.0
        if bool(getattr(effect, "optional", False)) or int(getattr(effect, "min_targets", 1) or 0) == 0:
            features["raw_optional_or_zero_target"] = 1.0
    targets: list[str] = []
    targets.extend(f"card_role:{role}" for role in profile.roles)
    if profile.target_semantics.harmful:
        targets.append("target_semantics:harmful")
    if profile.target_semantics.beneficial:
        targets.append("target_semantics:beneficial")
    if profile.target_semantics.enemy_preferred:
        targets.append("target_semantics:enemy_preferred")
    if profile.target_semantics.own_preferred:
        targets.append("target_semantics:own_preferred")
    if profile.target_semantics.any_target_unsafe_on_own:
        targets.append("target_semantics:any_target_unsafe_on_own")
    if profile.zone_value.good_mana_card:
        targets.append("zone_value:good_mana_card")
    if profile.zone_value.poor_mana_card:
        targets.append("zone_value:poor_mana_card")
    if profile.zone_value.protect_in_base:
        targets.append("zone_value:protect_in_base")
    if profile.zone_value.stay_field_as_blocker:
        targets.append("zone_value:stay_field_as_blocker")
    if profile.zone_value.usually_should_not_attack:
        targets.append("zone_value:usually_should_not_attack")
    if profile.tactical_risks.zero_dp_attacker:
        targets.append("tactical_risk:zero_dp_attacker")
    return {
        "version": DEEP_V2_UNDERSTANDING_ROW_VERSION,
        "kind": "card",
        "id": profile.identity.card_id,
        "features": dict(sorted(features.items())),
        "targets": sorted(set(targets)),
    }


def deck_understanding_row(deck: DeckSpec) -> dict[str, Any]:
    profile = build_deck_profile(deck)
    features: dict[str, float] = {
        "understanding:deck": 1.0,
        f"raw_card_total_bucket:{min(60, int(sum(deck.recipe.values())))}": 1.0,
        f"raw_unique_cards_bucket:{min(40, len(deck.recipe))}": 1.0,
    }
    for force in sorted(deck.forces):
        features[f"raw_force:{force}"] = 1.0
    for color in profile.colors:
        features[f"raw_color:{color}"] = 1.0
    for card_id, count in sorted(deck.recipe.items()):
        card = CARD_REGISTRY.get(card_id)
        if card is None:
            continue
        card_profile = build_card_profile(card)
        features[f"raw_card_color:{card_profile.identity.color or 'none'}"] = (
            features.get(f"raw_card_color:{card_profile.identity.color or 'none'}", 0.0) + float(count)
        )
        features[f"raw_curve:{min(8, int(card_profile.identity.cost_total))}"] = (
            features.get(f"raw_curve:{min(8, int(card_profile.identity.cost_total))}", 0.0) + float(count)
        )
        for role in card_profile.roles:
            features[f"raw_profile_role_count:{role}"] = (
                features.get(f"raw_profile_role_count:{role}", 0.0) + float(count)
            )
    targets: list[str] = []
    targets.extend(
        f"deck_archetype:{archetype}"
        for archetype, score in sorted(profile.archetype_scores.items())
        if float(score) > 0.0
    )
    targets.extend(f"combo_route:{route}" for route in profile.combo_routes)
    targets.extend(f"deck_plan:early:{plan}" for plan in profile.preferred_early_plan)
    targets.extend(f"deck_plan:mid:{plan}" for plan in profile.preferred_midgame_plan)
    targets.extend(f"deck_plan:end:{plan}" for plan in profile.preferred_endgame_plan)
    if profile.resource_sensitive:
        targets.append("deck_trait:resource_sensitive")
    return {
        "version": DEEP_V2_UNDERSTANDING_ROW_VERSION,
        "kind": "deck",
        "id": deck.id,
        "features": dict(sorted(features.items())),
        "targets": sorted(set(targets)),
    }


def understanding_preference_pairs(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        targets = {str(target) for target in row.get("targets", [])}
        kind = str(row.get("kind") or "")
        row_id = str(row.get("id") or "")
        if kind == "card":
            if "target_semantics:harmful" in targets and (
                "target_semantics:enemy_preferred" in targets
                or "card_role:removal" in targets
                or "target_semantics:any_target_unsafe_on_own" in targets
            ):
                pairs.append(_understanding_pair(
                    row_id=row_id,
                    labels=["understandingHarmfulTargetEnemy"],
                    good_action={"kind": "choose_target", "payload": {"target": "enemy_minion"}},
                    bad_action={"kind": "choose_target", "payload": {"target": "own_minion"}},
                    good_features={
                        "decision:generic_target": 1.0,
                        "target_effect_harmful": 1.0,
                        "target_enemy": 1.0,
                        "target_own": 0.0,
                        "semantic_target_intent:harmful": 1.0,
                        "semantic_target_alignment:harmful_enemy": 1.0,
                    },
                    bad_features={
                        "decision:generic_target": 1.0,
                        "target_effect_harmful": 1.0,
                        "target_enemy": 0.0,
                        "target_own": 1.0,
                        "semantic_target_intent:harmful": 1.0,
                        "semantic_target_risk:harmful_own": 1.0,
                    },
                ))
            if "target_semantics:beneficial" in targets and (
                "target_semantics:own_preferred" in targets
                or "card_role:buff" in targets
            ):
                pairs.append(_understanding_pair(
                    row_id=row_id,
                    labels=["understandingBeneficialTargetOwn"],
                    good_action={"kind": "choose_target", "payload": {"target": "own_minion"}},
                    bad_action={"kind": "choose_target", "payload": {"target": "enemy_minion"}},
                    good_features={
                        "decision:generic_target": 1.0,
                        "target_effect_beneficial": 1.0,
                        "target_own": 1.0,
                        "target_enemy": 0.0,
                        "semantic_target_intent:beneficial": 1.0,
                        "semantic_target_alignment:beneficial_own": 1.0,
                    },
                    bad_features={
                        "decision:generic_target": 1.0,
                        "target_effect_beneficial": 1.0,
                        "target_own": 0.0,
                        "target_enemy": 1.0,
                        "semantic_target_intent:beneficial": 1.0,
                        "semantic_target_risk:beneficial_enemy": 1.0,
                    },
                ))
            if (
                "tactical_risk:zero_dp_attacker" in targets
                or "zone_value:usually_should_not_attack" in targets
            ):
                pairs.append(_understanding_pair(
                    row_id=row_id,
                    labels=["understandingZeroDpHold"],
                    good_action={"kind": "end_turn", "payload": {}},
                    bad_action={"kind": "attack", "payload": {"attacker": "zero_dp"}},
                    good_features={
                        "action:end_turn": 1.0,
                        "is_end_or_pass": 1.0,
                        "own_field_count": 0.2,
                    },
                    bad_features={
                        "action:attack": 1.0,
                        "attack_zero_dp": 1.0,
                        "attack_zero_dp_without_attack_payoff": 1.0,
                        "attack_has_lethal_player_target": 0.0,
                        "attack_can_destroy_force": 0.0,
                    },
                ))
            continue
        if kind == "deck" and (
            "deck_trait:resource_sensitive" in targets
            or "deck_plan:early:base_growth" in targets
            or "deck_archetype:combo" in targets
        ):
            deck_context = {
                "turn_normalized": 0.2,
            }
            if "deck_trait:resource_sensitive" in targets:
                deck_context["own_deck_semantic_tag:resource_sensitive"] = 1.0
            if "combo_route:life_exchange" in targets:
                deck_context["own_deck_semantic_combo_route:life_exchange"] = 1.0
            if "deck_archetype:combo" in targets:
                deck_context["own_deck_semantic_archetype:combo"] = 1.0
            if "deck_plan:early:base_growth" in targets:
                deck_context["own_deck_semantic_plan:base_growth"] = 1.0
            if "deck_plan:early:hold_defense" in targets:
                deck_context["own_deck_semantic_plan:hold_defense"] = 1.0
            pairs.append(_understanding_pair(
                row_id=row_id,
                labels=["understandingComboGrowBase"],
                good_action={"kind": "move_card", "payload": {"direction": "field_to_base"}},
                bad_action={"kind": "attack", "payload": {"attacker": "early_minion"}},
                good_features=deck_context | {
                    "action:move_card": 1.0,
                    "is_board_action": 1.0,
                    "move_field_to_base": 1.0,
                    "move_field_to_base_builds_mana": 1.0,
                    "move_field_to_base_under_curve": 1.0,
                    "move_field_to_base_future_play": 1.0,
                    "semantic_action_plan:base_growth": 1.0,
                    "semantic_action_resource:base_development": 1.0,
                    "own_ready_colored_mana_count": 0.1,
                    "own_playable_hand_count": 0.1,
                },
                bad_features=deck_context | {
                    "action:attack": 1.0,
                    "is_attack": 1.0,
                    "attack_has_lethal_player_target": 0.0,
                    "attack_can_destroy_force": 0.0,
                    "attack_nonlethal_with_low_base": 1.0,
                    **(
                        {"semantic_action_risk:breaks_hold_defense": 1.0}
                        if "deck_plan:early:hold_defense" in targets
                        else {}
                    ),
                },
            ))
    return pairs


def _understanding_pair(
    *,
    row_id: str,
    labels: list[str],
    good_action: dict[str, Any],
    bad_action: dict[str, Any],
    good_features: dict[str, float],
    bad_features: dict[str, float],
) -> dict[str, Any]:
    return {
        "decisionIndex": -1,
        "source": UNDERSTANDING_PREFERENCE_VERSION,
        "rowId": row_id,
        "labels": list(labels),
        "goodAction": dict(good_action),
        "badAction": dict(bad_action),
        "goodFeatures": dict(sorted(good_features.items())),
        "badFeatures": dict(sorted(bad_features.items())),
    }


def _bucket(value: int, unit: int) -> int:
    if unit <= 0:
        return int(value)
    return int(value) // unit


def card_aware_action_preference_pairs(
    cards: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate synthetic action preference pairs from CardProfile rules.

    These directly teach the model card-specific behavior without
    requiring player replay data. Generated from deterministic
    CardProfile lookups → sustainable for new cards.
    """
    import zz.basic  # noqa: F401
    import zz.pc01  # noqa: F401
    from zz.card_profiles import build_card_profile
    from zz.cards import CARD_REGISTRY

    source = cards if cards is not None else CARD_REGISTRY
    pairs: list[dict[str, Any]] = []

    for card_id, card in sorted(source.items(), key=lambda item: str(item[0])):
        try:
            profile = build_card_profile(card)
        except Exception:
            continue

        roles = set(profile.roles)
        card_id_key = f"play_card_id:{card_id}"

        # ── Removal cards: target enemy, not own ──────────────────
        if "removal" in roles or profile.target_semantics.harmful:
            pairs.append(_action_pair(
                row_id=f"synthetic:removal_enemy:{card_id}",
                labels=["card_aware:removal_target_enemy"],
                good_kind="play_card", good_extra={
                    card_id_key: 1.0,
                    "target_enemy": 1.0, "target_own": 0.0,
                },
                bad_kind="play_card", bad_extra={
                    card_id_key: 1.0,
                    "target_enemy": 0.0, "target_own": 1.0,
                },
            ))

        # ── Buff cards: target own, not enemy ─────────────────────
        if "buff" in roles or profile.target_semantics.beneficial:
            pairs.append(_action_pair(
                row_id=f"synthetic:buff_own:{card_id}",
                labels=["card_aware:buff_target_own"],
                good_kind="play_card", good_extra={
                    card_id_key: 1.0,
                    "target_enemy": 0.0, "target_own": 1.0,
                },
                bad_kind="play_card", bad_extra={
                    card_id_key: 1.0,
                    "target_enemy": 1.0, "target_own": 0.0,
                },
            ))

        # ── Zero-DP: don't attack unless payoff ───────────────────
        if profile.tactical_risks.zero_dp_attacker:
            attacker_key = f"attacker_id:{card_id}"
            pairs.append(_action_pair(
                row_id=f"synthetic:zero_dp_hold:{card_id}",
                labels=["card_aware:zero_dp_dont_attack"],
                good_kind="end_turn", good_extra={},
                bad_kind="attack", bad_extra={
                    attacker_key: 1.0,
                    "attack_has_lethal_player_target": 0.0,
                    "attack_can_destroy_force": 0.0,
                },
                state={"enemy_field_dp_pressure": 0.3, "own_player_life": 0.4},
            ))

        # ── Protect in base: don't pull finishers ─────────────────
        if profile.zone_value.protect_in_base:
            move_key = f"move_card_id:{card_id}"
            pairs.append(_action_pair(
                row_id=f"synthetic:protect_finisher:{card_id}",
                labels=["card_aware:protect_in_base"],
                good_kind="end_turn", good_extra={},
                bad_kind="move_card", bad_extra={
                    move_key: 1.0, "move_base_to_field": 1.0,
                },
                state={"turn_normalized": 0.3},
            ))

        # ── Stay as blocker: good to put on field ─────────────────
        if profile.zone_value.stay_field_as_blocker:
            move_key = f"move_card_id:{card_id}"
            pairs.append(_action_pair(
                row_id=f"synthetic:blocker_to_field:{card_id}",
                labels=["card_aware:blocker_on_field"],
                good_kind="move_card", good_extra={
                    move_key: 1.0, "move_base_to_field": 1.0,
                },
                bad_kind="end_turn", bad_extra={},
                state={"enemy_field_dp_pressure": 0.4},
            ))

        # ── Defensive flash: hold for opponent turn ───────────────
        if "defensive_flash" in roles:
            pairs.append(_action_pair(
                row_id=f"synthetic:flash_hold:{card_id}",
                labels=["card_aware:hold_defensive_flash"],
                good_kind="end_turn", good_extra={},
                bad_kind="play_card", bad_extra={
                    card_id_key: 1.0,
                },
                state={"turn_normalized": 0.5},
            ))

    return pairs


def _action_pair(
    *,
    row_id: str,
    labels: list[str],
    good_kind: str,
    good_extra: dict[str, float],
    bad_kind: str,
    bad_extra: dict[str, float],
    state: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build a single action preference pair."""
    state_base = dict(state or {})
    good_features = {
        "bias": 1.0,
        f"action:{good_kind}": 1.0,
    } | state_base | good_extra
    bad_features = {
        "bias": 1.0,
        f"action:{bad_kind}": 1.0,
    } | state_base | bad_extra
    return {
        "decisionIndex": -1,
        "source": "card_aware_synthetic_v1",
        "rowId": row_id,
        "labels": list(labels),
        "goodAction": {"kind": good_kind, "payload": {}},
        "badAction": {"kind": bad_kind, "payload": {}},
        "goodFeatures": dict(sorted(good_features.items())),
        "badFeatures": dict(sorted(bad_features.items())),
    }
