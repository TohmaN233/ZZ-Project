from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Mapping

from zz.effects import EffectSpec
from zz.model import (
    Action,
    AttackTarget,
    Card,
    CardInstance,
    Context,
    ForceInstance,
    Player,
    Trigger,
)


def _callable_name(value: Any) -> str:
    module = getattr(value, "__module__", "")
    qualname = getattr(value, "__qualname__", getattr(value, "__name__", ""))
    if not qualname:
        raise TypeError(f"cannot identify callable {value!r}")
    return f"{module}.{qualname}" if module else str(qualname)


def _enum_value(value: Enum) -> Any:
    raw = value.value
    return raw if isinstance(raw, (str, int, float, bool)) or raw is None else value.name


def _force_ref(force: ForceInstance) -> dict[str, str]:
    return {"ownerSide": force.owner.side.name, "forceId": force.force.id}


def _runtime_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _enum_value(value)
    if isinstance(value, Player):
        return {"$player": value.side.name}
    if isinstance(value, CardInstance):
        return {"$card": value.iid}
    if isinstance(value, ForceInstance):
        return {"$force": _force_ref(value)}
    if isinstance(value, Card):
        return {"$cardDefinition": value.id}
    if isinstance(value, EffectSpec):
        return {
            "$effect": {
                "timing": _runtime_value(value.timing),
                "callback": _callable_name(value.fn),
                "preTargetCallback": None if value.pre_target_fn is None else _callable_name(value.pre_target_fn),
                "condition": None if value.condition is None else _callable_name(value.condition),
                "targetKind": value.target_kind,
                "minTargets": value.min_targets,
                "maxTargets": value.max_targets,
                "optional": value.optional,
                "templateId": value.template_id,
                "params": _runtime_value(value.params),
                "activeAreas": _runtime_value(value.active_areas),
            }
        }
    if isinstance(value, Trigger):
        return {
            "$trigger": {
                "when": _runtime_value(value.when),
                "callback": _callable_name(value.fn),
                "condition": None if value.condition is None else _callable_name(value.condition),
            }
        }
    if isinstance(value, Action):
        return {"kind": value.kind, "payload": _runtime_value(value.payload)}
    if isinstance(value, AttackTarget):
        return {"kind": _runtime_value(value.kind), "ref": _runtime_value(value.ref)}
    if isinstance(value, Context):
        return {
            "controller": _runtime_value(value.controller),
            "source": _runtime_value(value.source),
            "target": _runtime_value(value.target),
        }
    if isinstance(value, Mapping):
        return {
            str(_runtime_value(key)): _runtime_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_runtime_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_runtime_value(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=True))
    if callable(value):
        return {"$callable": _callable_name(value)}
    if is_dataclass(value):
        return {
            item.name: _runtime_value(getattr(value, item.name))
            for item in fields(value)
        }
    raise TypeError(f"unsupported authoritative state value: {type(value).__name__}")


def _card_state(card: CardInstance) -> dict[str, Any]:
    return {
        "iid": card.iid,
        "cardId": card.card.id,
        "ownerSide": card.owner.side.name,
        "area": card.area.value,
        "bpMod": card.bp_mod,
        "dpMod": card.dp_mod,
        "permanentBpMod": card.permanent_bp_mod,
        "permanentDpMod": card.permanent_dp_mod,
        "extraKeywords": sorted(keyword.value for keyword in card.extra_keywords),
        "rested": card.rested,
        "summoningSickness": card.summoning_sickness,
        "flags": sorted(card.flags),
        "manaColorOverride": None if card.mana_color_override is None else card.mana_color_override.value,
        "blessings": [_card_state(mana) for mana in card.blessings],
    }


def _player_state(player: Player) -> dict[str, Any]:
    return {
        "name": player.name,
        "side": player.side.name,
        "isFirstPlayer": player.is_first_player,
        "life": player.life,
        "deck": [_card_state(card) for card in player.deck],
        "hand": [_card_state(card) for card in player.hand],
        "base": [_card_state(card) for card in player.base],
        "field": [_card_state(card) for card in player.field],
        "trash": [_card_state(card) for card in player.trash],
        "removed": [_card_state(card) for card in player.removed],
        "forces": [
            {
                **_force_ref(force),
                "life": force.life,
                "destroyed": force.destroyed,
                "rested": force.rested,
            }
            for force in player.forces
        ],
        "movementRightCount": player.movement_right_count,
        "movementRightTotal": player.movement_right_total,
        "mulliganDone": player.mulligan_done,
        "colorlessOnlyStreak": player.colorless_only_streak,
        "flags": sorted(player.flags),
    }


def _identity_refs(session: Any) -> dict[int, Any]:
    refs: dict[int, Any] = {}
    for player in session.engine.state.players:
        refs[id(player)] = {"$player": player.side.name}
        for force in player.forces:
            refs[id(force)] = {"$force": _force_ref(force)}
    return refs


def _identity_map(values: Mapping[int, Any], refs: Mapping[int, Any]) -> list[dict[str, Any]]:
    rows = []
    for object_id, value in values.items():
        ref = refs.get(object_id)
        if ref is None:
            raise RuntimeError(f"authoritative identity map contains unknown object id {object_id}")
        rows.append({"ref": ref, "value": _runtime_value(value)})
    return sorted(rows, key=lambda row: json.dumps(row["ref"], sort_keys=True))


def _identity_set(values: set[int], refs: Mapping[int, Any]) -> list[Any]:
    out = []
    for object_id in values:
        ref = refs.get(object_id)
        if ref is None:
            raise RuntimeError(f"authoritative identity set contains unknown object id {object_id}")
        out.append(ref)
    return sorted(out, key=lambda item: json.dumps(item, sort_keys=True))


def canonical_authoritative_state(
    session: Any,
    *,
    revision: int,
    initial_match: Mapping[str, Any],
) -> dict[str, Any]:
    engine = session.engine
    state = engine.state
    refs = _identity_refs(session)
    passive_modifiers = []
    for kind, callback in engine._passive_modifiers:
        force_ref = refs.get(getattr(callback, "_force_iid", None))
        passive_modifiers.append({
            "kind": kind,
            "callback": _callable_name(callback),
            "force": force_ref,
        })
    delayed_effects = [
        {"player": _runtime_value(player), "callback": _callable_name(callback)}
        for player, callback in engine._delayed_turn_end_effects
    ]
    return {
        "revision": revision,
        "initialMatch": _runtime_value(initial_match),
        "rngState": _runtime_value(session.rng.getstate()),
        "gameState": {
            "turn": state.turn,
            "activeIndex": state.active_idx,
            "phase": state.phase.value,
            "step": state.step.value,
            "nextInstanceId": state.next_instance_id,
            "presentAtTurnStart": sorted(state.present_at_turn_start),
            "summonedThisTurn": [card.iid for card in state.summoned_this_turn],
            "players": [_player_state(player) for player in state.players],
        },
        "engineRuntime": {
            "pendingForceBaseChoices": _runtime_value(engine.pending_force_base_choices),
            "pendingBlessingReturns": _runtime_value(engine.pending_blessing_returns),
            "triggerQueue": _runtime_value(list(engine.triggers._queue)),
            "ignoreHandCap": engine.ignore_hand_cap,
            "passiveModifiers": passive_modifiers,
            "playerDamageReduction": _identity_map(engine._player_damage_reduction, refs),
            "playerDamageReductionBlocked": _identity_set(engine._player_damage_reduction_blocked, refs),
            "forceDamageReduction": _identity_map(engine._force_damage_reduction, refs),
            "forceDamageReductionBlocked": _identity_set(engine._force_damage_reduction_blocked, refs),
            "playerHealingBlocked": _identity_set(engine._player_healing_blocked, refs),
            "forceHealingBlocked": _identity_set(engine._force_healing_blocked, refs),
            "effectResolutionDepth": engine._effect_resolution_depth,
            "pendingDestroyEvents": _runtime_value(engine._pending_destroy_events),
            "flushingDestroyEvents": engine._flushing_destroy_events,
            "resolvingStateBasedActions": engine._resolving_state_based_actions,
            "delayedTurnEndEffects": delayed_effects,
            "turnStatModifiers": _runtime_value(engine._turn_stat_modifiers),
            "observedActionProfiles": _runtime_value(engine.observed_action_profile_by_player_side),
            "flashContext": _runtime_value(getattr(engine, "_flash_ctx", None)),
        },
        "decisionRuntime": {
            "promptCounter": session._prompt_counter,
            "prompt": _runtime_value(session.prompt),
            "options": _runtime_value(session._options),
            "pendingMulligans": {
                side: {
                    "prompt": _runtime_value(record["prompt"]),
                    "options": _runtime_value(record["options"]),
                }
                for side, record in sorted(getattr(session, "_pending_mulligans", {}).items())
            },
            "attack": _runtime_value(session._attack),
            "pendingEffect": _runtime_value(session._pending_effect),
            "promptedTriggerResolution": _runtime_value(session._prompted_trigger_resolution),
            "promptedSourceEffectResolution": _runtime_value(session._prompted_source_effect_resolution),
            "humanPolicyTargets": _runtime_value(session.human_policy._targets),
            "gameOver": _runtime_value(session._game_over),
        },
    }


def hash_authoritative_state(
    session: Any,
    *,
    revision: int,
    initial_match: Mapping[str, Any],
) -> str:
    canonical = canonical_authoritative_state(
        session,
        revision=revision,
        initial_match=initial_match,
    )
    encoded = json.dumps(
        canonical,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
