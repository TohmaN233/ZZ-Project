from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from zz.enums import Step
from zz.model import Action, Player
from zz.rl_action_vocab import decision_kind_for_action, normalise_decision_kind
from zz.rl_tensor_schema import ActionSetTensor, encode_action_set


TRAINING_FAST_PATH_VERSION = "training_fast_path_v1"
TRAINING_FAST_PATH_ACTION_SET_VERSION = "training_fast_path_action_set_v1"
TRAINING_FAST_PATH_ROW_VERSION = "training_fast_path_row_v1"


@dataclass(frozen=True)
class CompactForceFrame:
    forceId: str
    life: int
    destroyed: bool
    rested: bool


@dataclass(frozen=True)
class CompactPlayerFrame:
    role: str
    trueTurnOrder: str
    life: int
    handCount: int
    baseCount: int
    fieldCount: int
    trashCount: int
    removedCount: int
    movementRightCount: int
    movementRightTotal: int
    colorlessOnlyStreak: int
    forceFrames: tuple[CompactForceFrame, ...]
    handCardIds: tuple[str, ...]
    baseCardIds: tuple[str, ...]
    fieldCardIds: tuple[str, ...]
    fieldBp: tuple[int, ...]
    fieldDp: tuple[int, ...]
    fieldRested: tuple[bool, ...]


@dataclass(frozen=True)
class TrainingDecisionFrame:
    version: str
    turn: int
    phase: str
    step: str
    activeRole: str
    decisionKind: str
    legalCount: int
    mask: tuple[int, ...]
    self_: CompactPlayerFrame
    opponent: CompactPlayerFrame
    actions: tuple[dict[str, Any], ...]
    stateKey: str
    actionKeys: tuple[str, ...]


@dataclass(frozen=True)
class TrainingActionSetFrame:
    version: str
    decisionFrame: TrainingDecisionFrame
    tensor: ActionSetTensor
    actionRecords: tuple[dict[str, Any], ...]


def build_training_decision_frame(
    engine: Any,
    player: Player,
    actions: list[Action] | tuple[Action, ...],
    *,
    decision_kind: str | None = None,
    max_actions: int | None = None,
) -> TrainingDecisionFrame:
    action_list = list(actions)
    action_cap = len(action_list) if max_actions is None else int(max_actions)
    if action_cap <= 0:
        raise ValueError("max_actions must be positive when provided")
    if len(action_list) > action_cap:
        raise ValueError("actions exceed max_actions")

    state = getattr(engine, "state", None)
    opponent = _opponent_for(state, player)
    decision_kind_value = _decision_kind_value(state, action_list, decision_kind)
    action_records = tuple(
        _relative_action_record(engine, player, action)
        for action in action_list
    )
    mask = tuple(1 if index < len(action_list) else 0 for index in range(action_cap))
    self_frame = _player_frame(player, role="self")
    opponent_frame = _player_frame(opponent, role="opponent")
    state_payload = {
        "turn": int(getattr(state, "turn", 0) or 0),
        "phase": _enum_value(getattr(state, "phase", None)),
        "step": _enum_value(getattr(state, "step", None)),
        "activeRole": "self" if getattr(state, "active", None) is player else "opponent",
        "decisionKind": decision_kind_value,
        "self": _json_dataclass(self_frame),
        "opponent": _json_dataclass(opponent_frame),
        "mask": mask,
    }
    action_keys = tuple(_stable_key(record) for record in action_records)
    return TrainingDecisionFrame(
        version=TRAINING_FAST_PATH_VERSION,
        turn=int(state_payload["turn"]),
        phase=str(state_payload["phase"]),
        step=str(state_payload["step"]),
        activeRole=str(state_payload["activeRole"]),
        decisionKind=decision_kind_value,
        legalCount=len(action_list),
        mask=mask,
        self_=self_frame,
        opponent=opponent_frame,
        actions=action_records,
        stateKey=_stable_key(state_payload),
        actionKeys=action_keys,
    )


def build_training_action_set_frame(
    engine: Any,
    player: Player,
    actions: list[Action] | tuple[Action, ...],
    *,
    decision_kind: str | None = None,
    max_actions: int,
    history_context: Mapping[str, Any] | None = None,
) -> TrainingActionSetFrame:
    action_list = list(actions)
    decision_frame = build_training_decision_frame(
        engine,
        player,
        action_list,
        decision_kind=decision_kind,
        max_actions=max_actions,
    )
    tensor = encode_action_set(
        engine,
        player,
        action_list,
        max_actions=max_actions,
        decision_kind=decision_kind,
        history_context=history_context,
    )
    return TrainingActionSetFrame(
        version=TRAINING_FAST_PATH_ACTION_SET_VERSION,
        decisionFrame=decision_frame,
        tensor=tensor,
        actionRecords=decision_frame.actions,
    )


def fast_path_row_metadata_from_frame(
    frame: TrainingActionSetFrame,
    *,
    max_actions: int | None = None,
) -> dict[str, Any]:
    action_cap = int(max_actions) if max_actions is not None else len(frame.decisionFrame.mask)
    action_keys = list(frame.decisionFrame.actionKeys)
    if len(action_keys) > action_cap:
        raise ValueError("action keys exceed max_actions")
    return {
        "fastPathVersion": TRAINING_FAST_PATH_ROW_VERSION,
        "fastPathFrameVersion": frame.decisionFrame.version,
        "fastPathActionSetVersion": frame.version,
        "fastPathStateKeySource": "engine_frame",
        "fastPathDecisionKind": frame.decisionFrame.decisionKind,
        "stateKey": frame.decisionFrame.stateKey,
        "actionKeys": action_keys + [None] * (action_cap - len(action_keys)),
        "legalMask": list(frame.decisionFrame.mask),
    }


def fast_path_row_metadata_from_serialized_action_set_row(row: Mapping[str, Any]) -> dict[str, Any]:
    decision_kind = normalise_decision_kind(str(row.get("decisionKind") or "unknown"))
    legal_count = int(_optional_int(row.get("legalCount")) or 0)
    mask = _serialized_mask(row, legal_count=legal_count)
    actions = _serialized_actions(row, legal_count=legal_count)
    action_keys = [_stable_key(action) for action in actions]
    state_payload = {
        "source": "serialized_action_set_row",
        "decisionKind": decision_kind,
        "globalFeatureNames": _json_value(row.get("globalFeatureNames") or []),
        "global": _json_value(row.get("global_") or []),
        "legalMask": mask,
        "legalCount": legal_count,
    }
    return {
        "fastPathVersion": TRAINING_FAST_PATH_ROW_VERSION,
        "fastPathFrameVersion": TRAINING_FAST_PATH_VERSION,
        "fastPathActionSetVersion": TRAINING_FAST_PATH_ACTION_SET_VERSION,
        "fastPathStateKeySource": "serialized_action_set_row",
        "fastPathDecisionKind": decision_kind,
        "stateKey": _stable_key(state_payload),
        "actionKeys": action_keys + [None] * max(0, len(mask) - len(action_keys)),
        "legalMask": mask,
    }


def attach_fast_path_row_metadata(
    row: Mapping[str, Any],
    *,
    source: str = "serialized_action_set_row",
) -> dict[str, Any]:
    copied = dict(row)
    if source != "serialized_action_set_row":
        raise ValueError(f"unsupported fast-path metadata source: {source}")
    copied.update(fast_path_row_metadata_from_serialized_action_set_row(copied))
    return copied


def _player_frame(player: Any, *, role: str) -> CompactPlayerFrame:
    return CompactPlayerFrame(
        role=role,
        trueTurnOrder="first" if bool(getattr(player, "is_first_player", False)) else "second",
        life=int(getattr(player, "life", 0) or 0),
        handCount=_safe_len(getattr(player, "hand", [])),
        baseCount=_safe_len(getattr(player, "base", [])),
        fieldCount=_safe_len(getattr(player, "field", [])),
        trashCount=_safe_len(getattr(player, "trash", [])),
        removedCount=_safe_len(getattr(player, "removed", [])),
        movementRightCount=int(getattr(player, "movement_right_count", 0) or 0),
        movementRightTotal=int(getattr(player, "movement_right_total", 0) or 0),
        colorlessOnlyStreak=int(getattr(player, "colorless_only_streak", 0) or 0),
        forceFrames=tuple(_force_frame(force) for force in list(getattr(player, "forces", []) or [])),
        handCardIds=_card_ids(getattr(player, "hand", [])),
        baseCardIds=_card_ids(getattr(player, "base", [])),
        fieldCardIds=_card_ids(getattr(player, "field", [])),
        fieldBp=tuple(int(getattr(card, "bp", 0) or 0) for card in list(getattr(player, "field", []) or [])),
        fieldDp=tuple(int(getattr(card, "dp", 0) or 0) for card in list(getattr(player, "field", []) or [])),
        fieldRested=tuple(bool(getattr(card, "rested", False)) for card in list(getattr(player, "field", []) or [])),
    )


def _force_frame(force: Any) -> CompactForceFrame:
    force_template = getattr(force, "force", force)
    return CompactForceFrame(
        forceId=str(getattr(force_template, "id", getattr(force_template, "name", "unknown"))),
        life=int(getattr(force, "life", 0) or 0),
        destroyed=bool(getattr(force, "destroyed", False)),
        rested=bool(getattr(force, "rested", False)),
    )


def _relative_action_record(engine: Any, player: Player, action: Action) -> dict[str, Any]:
    payload = _json_mapping(getattr(action, "payload", {}) or {})
    semantic_payload = {
        str(key): _relative_payload_value(engine, player, key=str(key), value=value)
        for key, value in payload.items()
    }
    return {
        "kind": str(getattr(action, "kind", "")),
        "payload": semantic_payload,
        "signature": {
            "kind": str(getattr(action, "kind", "")),
            "payload": semantic_payload,
        },
    }


def _relative_payload_value(engine: Any, player: Player, *, key: str, value: Any) -> Any:
    if key == "iid" or key.endswith("_iid"):
        try:
            return _relative_iid_ref(engine, player, int(value))
        except (TypeError, ValueError):
            return _json_value(value)
    return _json_value(value)


def _relative_iid_ref(engine: Any, player: Player, iid: int) -> dict[str, Any]:
    state = getattr(engine, "state", None)
    players = [player]
    for candidate in list(getattr(state, "players", []) or []):
        if candidate is not player:
            players.append(candidate)
    for owner in players:
        owner_role = "self" if owner is player else "opponent"
        for zone_name in ("hand", "base", "field", "trash", "removed"):
            zone = list(getattr(owner, zone_name, []) or [])
            for zone_index, card_instance in enumerate(zone):
                if int(getattr(card_instance, "iid", -1) or -1) != iid:
                    continue
                card_id = _card_id(card_instance)
                same_card_index = sum(1 for earlier in zone[:zone_index] if _card_id(earlier) == card_id)
                return {
                    "owner": owner_role,
                    "zone": zone_name,
                    "cardId": card_id,
                    "zoneIndex": int(zone_index),
                    "sameCardIndex": int(same_card_index),
                }
    return {"iid": int(iid)}


def _opponent_for(state: Any, player: Player) -> Any:
    for candidate in list(getattr(state, "players", []) or []):
        if candidate is not player:
            return candidate
    return None


def _card_ids(zone: Any) -> tuple[str, ...]:
    return tuple(_card_id(card_instance) for card_instance in list(zone or []))


def _card_id(card_instance: Any) -> str:
    card = getattr(card_instance, "card", card_instance)
    return str(getattr(card, "id", getattr(card, "name_en", "unknown")))


def _decision_kind_value(state: Any, actions: list[Action], decision_kind: str | None) -> str:
    explicit = normalise_decision_kind(decision_kind)
    inferred = {decision_kind_for_action(action) for action in actions}
    if explicit != "unknown":
        if explicit == "main" and len(inferred) == 1:
            inferred_kind = next(iter(inferred))
            if inferred_kind not in {"unknown", "main"}:
                return inferred_kind
        return explicit

    step = getattr(state, "step", None)
    if step is Step.MANA or getattr(step, "value", None) == "mana":
        return "mana"
    if step is Step.FLASH or getattr(step, "value", None) == "flash":
        return "flash"
    if step is Step.MAIN or getattr(step, "value", None) == "main":
        return "main"

    if len(inferred) == 1:
        return next(iter(inferred))
    return "unknown"


def _serialized_mask(row: Mapping[str, Any], *, legal_count: int) -> list[int]:
    raw_mask = row.get("mask_")
    if isinstance(raw_mask, list | tuple):
        return [1 if bool(value) else 0 for value in raw_mask]
    return [1 for _ in range(max(0, legal_count))]


def _serialized_actions(row: Mapping[str, Any], *, legal_count: int) -> list[Any]:
    raw_actions = row.get("actions")
    if not isinstance(raw_actions, list | tuple):
        return []
    return [_json_value(action) for action in list(raw_actions)[:max(0, legal_count)]]


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _enum_value(value: Any) -> str:
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    if value is None:
        return "unknown"
    return str(value).lower()


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except TypeError:
        return 0


def _json_dataclass(value: Any) -> Any:
    if isinstance(value, CompactPlayerFrame):
        return {
            "role": value.role,
            "trueTurnOrder": value.trueTurnOrder,
            "life": value.life,
            "handCount": value.handCount,
            "baseCount": value.baseCount,
            "fieldCount": value.fieldCount,
            "trashCount": value.trashCount,
            "removedCount": value.removedCount,
            "movementRightCount": value.movementRightCount,
            "movementRightTotal": value.movementRightTotal,
            "colorlessOnlyStreak": value.colorlessOnlyStreak,
            "forceFrames": [_json_dataclass(force) for force in value.forceFrames],
            "handCardIds": list(value.handCardIds),
            "baseCardIds": list(value.baseCardIds),
            "fieldCardIds": list(value.fieldCardIds),
            "fieldBp": list(value.fieldBp),
            "fieldDp": list(value.fieldDp),
            "fieldRested": list(value.fieldRested),
        }
    if isinstance(value, CompactForceFrame):
        return {
            "forceId": value.forceId,
            "life": value.life,
            "destroyed": value.destroyed,
            "rested": value.rested,
        }
    return _json_value(value)


def _json_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in mapping.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    enum_name = getattr(value, "name", None)
    if isinstance(enum_name, str):
        return enum_name
    return str(value)


def _stable_key(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
