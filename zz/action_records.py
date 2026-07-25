from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zz.model import Action


ACTION_RECORD_VERSION = "action_record_v1"


def canonical_action_record(value: Any) -> dict[str, Any]:
    action = json_mapping(value)
    kind = str(action.get("kind") or "").strip()
    if not kind:
        return {}
    record: dict[str, Any] = {
        "kind": kind,
        "payload": json_mapping(action.get("payload")),
    }
    signature = json_mapping(action.get("signature"))
    if signature:
        record["signature"] = signature
    key = action.get("key", action.get("actionKey"))
    if key is not None:
        record["key"] = str(key)
    return record


def action_record_from_action(action: Action, *, engine: Any = None, player: Any = None) -> dict[str, Any]:
    record = {"kind": str(action.kind), "payload": json_mapping(action.payload)}
    if engine is not None and player is not None:
        record["signature"] = action_signature(engine, player, action)
    return record


def action_record_from_row_slot(row: Mapping[str, Any], slot: int | None) -> dict[str, Any] | None:
    if slot is None:
        return None
    actions = row.get("actions")
    if not isinstance(actions, list | tuple):
        return None
    try:
        index = int(slot)
    except (TypeError, ValueError):
        return None
    if index < 0 or index >= len(actions):
        return None
    record = canonical_action_record(actions[index])
    return record or None


def action_from_record(record: Any) -> Action:
    action_record = canonical_action_record(record)
    payload = json_mapping(action_record.get("payload"))
    signature = json_mapping(action_record.get("signature"))
    if signature:
        payload = dict(payload)
        payload["signature"] = signature
    return Action(str(action_record.get("kind") or "unknown"), payload)


def action_signature(engine: Any, player: Any, action: Action) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in sorted(action.payload.items()):
        if key == "iid" or key.endswith("_iid"):
            try:
                payload[key] = semantic_iid_ref(engine, player, int(value))
            except (TypeError, ValueError):
                payload[key] = json_scalar(value)
        else:
            payload[key] = json_scalar(value)
    return {"kind": str(action.kind), "payload": payload}


def find_recorded_action(engine: Any, player: Any, recorded: Any, legal_actions: list[Action]) -> Action | None:
    record = canonical_action_record(recorded)
    if not record:
        return None
    exact = Action(str(record["kind"]), json_mapping(record.get("payload")))
    if exact in legal_actions:
        return exact
    signature = json_mapping(record.get("signature"))
    if signature:
        for action in legal_actions:
            if action_signature(engine, player, action) == signature:
                return action
    return _fallback_recorded_action(engine, player, record, legal_actions)


def action_records_match(expected: Any, actual: Any) -> bool:
    expected_record = canonical_action_record(expected)
    actual_record = canonical_action_record(actual)
    if not expected_record:
        return True
    if not actual_record:
        return False
    if str(expected_record.get("kind") or "") != str(actual_record.get("kind") or ""):
        return False

    expected_key = expected_record.get("key")
    actual_key = actual_record.get("key")
    if expected_key is not None and actual_key is not None and str(expected_key) == str(actual_key):
        return True

    if _semantic_signature_conflicts(expected_record, actual_record):
        return False

    expected_payload = json_mapping(expected_record.get("payload"))
    actual_payload = json_mapping(actual_record.get("payload"))
    if expected_payload and expected_payload == actual_payload:
        return True

    expected_signature = json_mapping(expected_record.get("signature"))
    actual_signature = json_mapping(actual_record.get("signature"))
    if expected_signature and actual_signature and expected_signature == actual_signature:
        return True

    if _payloads_match_without_volatile_iids(expected_record, actual_record):
        return True

    expected_ref = semantic_ref_from_action_record(expected_record)
    actual_ref = semantic_ref_from_action_record(actual_record)
    if expected_ref and actual_ref:
        return semantic_refs_match(expected_ref, actual_ref)

    if not expected_payload and not expected_signature and expected_key is None:
        return True
    return False


def semantic_ref_from_action_record(record: Any) -> dict[str, Any]:
    action_record = canonical_action_record(record)
    signature = json_mapping(action_record.get("signature"))
    signature_payload = json_mapping(signature.get("payload"))
    ref = semantic_ref_from_payload(signature_payload)
    if ref:
        return ref
    return semantic_ref_from_payload(json_mapping(action_record.get("payload")))


def action_record_has_semantic_identity(record: Any) -> bool:
    action_record = canonical_action_record(record)
    if not action_record:
        return False
    if json_mapping(action_record.get("signature")):
        return True
    return bool(semantic_ref_from_action_record(action_record))


def semantic_ref_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    source = json_mapping(payload)
    for key, value in source.items():
        if key == "iid" or key.endswith("_iid"):
            nested = json_mapping(value)
            if nested:
                return _normalise_semantic_ref(nested)
    return _direct_semantic_ref(source)


def semantic_refs_match(expected_ref: Mapping[str, Any], actual_ref: Mapping[str, Any]) -> bool:
    expected_card = str(expected_ref.get("cardId") or expected_ref.get("card_id") or "")
    actual_card = str(actual_ref.get("cardId") or actual_ref.get("card_id") or "")
    if not expected_card or expected_card != actual_card:
        return False
    for key in ("owner", "zone", "sameCardIndex"):
        expected_value = expected_ref.get(key)
        actual_value = actual_ref.get(key)
        if expected_value is not None and actual_value is not None and expected_value != actual_value:
            return False
    expected_same_card_index = expected_ref.get("sameCardIndex")
    actual_same_card_index = actual_ref.get("sameCardIndex")
    if (
        expected_same_card_index is not None
        and actual_same_card_index is not None
        and expected_same_card_index == actual_same_card_index
    ):
        return True
    expected_zone_index = expected_ref.get("zoneIndex")
    actual_zone_index = actual_ref.get("zoneIndex")
    if expected_zone_index is not None and actual_zone_index is not None and expected_zone_index != actual_zone_index:
        return False
    return True


def payload_context_free_key(payload: Mapping[str, Any]) -> dict[str, Any]:
    key = json_mapping(payload)
    key.pop("attacker", None)
    return key


def json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): json_value(item) for key, item in value.items()}


def json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return json_mapping(value)
    if isinstance(value, list | tuple):
        return [json_value(item) for item in value]
    return json_scalar(value)


def json_scalar(value: Any) -> Any:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str | int | float | bool):
        return enum_value
    enum_name = getattr(value, "name", None)
    if isinstance(enum_name, str):
        return enum_name
    return str(value)


def semantic_iid_ref(engine: Any, preferred_player: Any, iid: int) -> dict[str, Any]:
    state = getattr(engine, "state", None)
    players = [preferred_player]
    for candidate in getattr(state, "players", []) or []:
        if candidate is not preferred_player:
            players.append(candidate)
    for owner in players:
        for zone_name in ("hand", "base", "field", "trash", "removed"):
            zone = list(getattr(owner, zone_name, []) or [])
            for index, card_instance in enumerate(zone):
                if getattr(card_instance, "iid", None) != iid:
                    continue
                card = getattr(card_instance, "card", card_instance)
                card_id = str(getattr(card, "id", getattr(card, "name_en", "unknown")))
                same_card_index = sum(
                    1
                    for earlier in zone[:index]
                    if str(
                        getattr(
                            getattr(earlier, "card", earlier),
                            "id",
                            getattr(getattr(earlier, "card", earlier), "name_en", "unknown"),
                        )
                    )
                    == card_id
                )
                return {
                    "owner": _player_label(owner),
                    "zone": zone_name,
                    "cardId": card_id,
                    "zoneIndex": index,
                    "sameCardIndex": same_card_index,
                }
    return {"iid": iid}


def _fallback_recorded_action(
    engine: Any,
    player: Any,
    recorded: Mapping[str, Any],
    legal_actions: list[Action],
) -> Action | None:
    payload = json_mapping(recorded.get("payload"))
    kind = str(recorded.get("kind") or "")
    if kind in {"play_card", "play_to_base", "activate_flash_ability"}:
        recorded_iid = payload.get("iid")
        for action in legal_actions:
            if action.kind == kind and action.payload.get("iid") == recorded_iid:
                return action
        return _semantic_recorded_action(engine, player, recorded, legal_actions)
    if kind == "attack":
        recorded_attacker_iid = payload.get("attacker_iid")
        for action in legal_actions:
            if action.kind == "attack" and action.payload.get("attacker_iid") == recorded_attacker_iid:
                return action
        return _semantic_recorded_action(engine, player, recorded, legal_actions)
    if kind == "move_card":
        direction = str(payload.get("direction") or "")
        direction_matches = [
            action
            for action in legal_actions
            if action.kind == "move_card" and str(action.payload.get("direction") or "") == direction
        ]
        semantic_match = _semantic_recorded_action(engine, player, recorded, direction_matches)
        if semantic_match is not None:
            return semantic_match
        if direction == "field_to_base":
            return direction_matches[0] if direction_matches else None
        return None

    context_free_match = _context_free_recorded_action(engine, player, recorded, legal_actions)
    if context_free_match is not None:
        return context_free_match
    return _semantic_recorded_action(engine, player, recorded, legal_actions)


def _context_free_recorded_action(
    engine: Any,
    player: Any,
    recorded: Mapping[str, Any],
    legal_actions: list[Action],
) -> Action | None:
    recorded_kind = str(recorded.get("kind") or "")
    recorded_keys = [
        payload_context_free_key(payload)
        for payload in _record_payloads(recorded)
    ]
    recorded_keys = [key for key in recorded_keys if key]
    if not recorded_keys:
        return None
    for action in legal_actions:
        if str(action.kind) != recorded_kind:
            continue
        for candidate_payload in _candidate_payloads(engine, player, action):
            candidate_key = payload_context_free_key(candidate_payload)
            if candidate_key and candidate_key in recorded_keys:
                return action
    return None


def _semantic_recorded_action(
    engine: Any,
    player: Any,
    recorded: Mapping[str, Any],
    legal_actions: list[Action],
) -> Action | None:
    recorded_ref = semantic_ref_from_action_record(recorded)
    if not recorded_ref:
        return None
    kind = str(recorded.get("kind") or "")
    matches: list[Action] = []
    for action in legal_actions:
        if action.kind != kind:
            continue
        candidate_ref = semantic_ref_from_action_record(action_record_from_action(action, engine=engine, player=player))
        if semantic_refs_match(recorded_ref, candidate_ref):
            matches.append(action)
    if not matches:
        return None
    same_card_index = recorded_ref.get("sameCardIndex")
    if same_card_index is not None:
        indexed_matches = [
            action
            for action in matches
            if semantic_ref_from_action_record(
                action_record_from_action(action, engine=engine, player=player)
            ).get("sameCardIndex")
            == same_card_index
        ]
        if indexed_matches:
            matches = indexed_matches
    return matches[0] if len(matches) == 1 or kind in {"play_card", "play_to_base"} else None


def _record_payloads(recorded: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    payloads: list[Mapping[str, Any]] = []
    recorded_kind = str(recorded.get("kind") or "")
    signature = recorded.get("signature")
    if isinstance(signature, Mapping) and str(signature.get("kind") or "") == recorded_kind:
        signature_payload = signature.get("payload")
        if isinstance(signature_payload, Mapping):
            payloads.append(signature_payload)
    payload = recorded.get("payload")
    if isinstance(payload, Mapping):
        payloads.append(payload)
    return payloads


def _candidate_payloads(engine: Any, player: Any, action: Action) -> list[Mapping[str, Any]]:
    payloads: list[Mapping[str, Any]] = []
    try:
        signature_payload = action_signature(engine, player, action).get("payload")
        if isinstance(signature_payload, Mapping):
            payloads.append(signature_payload)
    except Exception:
        pass
    payloads.append(action.payload)
    return payloads


def _semantic_signature_conflicts(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    expected_signature = json_mapping(expected.get("signature"))
    actual_signature = json_mapping(actual.get("signature"))
    if not expected_signature or not actual_signature:
        return False
    if str(expected_signature.get("kind") or "") != str(actual_signature.get("kind") or ""):
        return False
    expected_ref = semantic_ref_from_action_record(expected)
    actual_ref = semantic_ref_from_action_record(actual)
    return bool(expected_ref and actual_ref and not semantic_refs_match(expected_ref, actual_ref))


def _payloads_match_without_volatile_iids(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    expected_payloads = [
        _drop_volatile_iids_from_payload(payload)
        for payload in _record_payloads(expected)
    ]
    actual_payloads = [
        _drop_volatile_iids_from_payload(payload)
        for payload in _record_payloads(actual)
    ]
    expected_payloads = [payload for payload in expected_payloads if payload]
    actual_payloads = [payload for payload in actual_payloads if payload]
    if not expected_payloads or not actual_payloads:
        return False
    return any(expected_payload == actual_payload for expected_payload in expected_payloads for actual_payload in actual_payloads)


def _drop_volatile_iids_from_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        mapped = json_mapping(value)
        out: dict[str, Any] = {}
        stable_card_identity = _has_stable_card_identity(mapped)
        for key, item in mapped.items():
            if key == "iid" and stable_card_identity:
                continue
            out[key] = _drop_volatile_iids_from_payload(item)
        return out
    if isinstance(value, list | tuple):
        return [_drop_volatile_iids_from_payload(item) for item in value]
    return json_scalar(value)


def _has_stable_card_identity(payload: Mapping[str, Any]) -> bool:
    return bool(payload.get("cardId") or payload.get("card_id")) and (
        payload.get("owner") is not None
        or payload.get("zone") is not None
        or payload.get("sameCardIndex") is not None
    )


def _normalise_semantic_ref(value: Mapping[str, Any]) -> dict[str, Any]:
    card_id = str(value.get("cardId") or value.get("card_id") or "")
    if not card_id:
        return {}
    out: dict[str, Any] = {"cardId": card_id}
    for key in ("owner", "zone", "zoneIndex", "sameCardIndex"):
        if key in value:
            out[key] = value[key]
    return out


def _direct_semantic_ref(payload: Mapping[str, Any]) -> dict[str, Any]:
    card_id = str(payload.get("cardId") or payload.get("card_id") or "")
    if not card_id:
        return {}
    out: dict[str, Any] = {"cardId": card_id}
    for key in ("owner", "zone", "zoneIndex", "sameCardIndex"):
        if key in payload:
            out[key] = payload[key]
    return out


def _player_label(player: Any) -> str:
    side = getattr(player, "side", None)
    if side is not None:
        return str(getattr(side, "name", side))
    return str(getattr(player, "name", "unknown"))
