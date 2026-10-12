#!/usr/bin/env python3
"""Execute one card semantic scenario through the real GameSession boundary.

The card-writing workflow stores scenarios as a small, public-action DSL.  This
runner calls the same debug fixtures and ``GameSession.choose`` method used by
the browser API. Explicit ``/fixture/`` preparation operations use real engine
transformation events and zone transitions for existing instances. It never
mutates a result to satisfy an assertion. A failed selector, setup call, or
assertion is therefore a real semantic failure and exits non-zero.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Iterable, Mapping


class ScenarioError(RuntimeError):
    """A scenario cannot be executed or did not satisfy its contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScenarioError(f"{label} must be an object")
    return dict(value)


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ScenarioError(f"{label} must be an array")
    return list(value)


def _parse_path(path: str) -> list[str | int]:
    if not isinstance(path, str) or not path:
        raise ScenarioError("state path must be a non-empty string")
    tokens: list[str | int] = []
    for part in path.split("."):
        if not part:
            raise ScenarioError(f"invalid empty path segment in {path!r}")
        match = re.fullmatch(r"([^\[\]]+)((?:\[\d+\])*)", part)
        if match is None:
            raise ScenarioError(f"invalid state path segment {part!r}")
        tokens.append(match.group(1))
        for index in re.findall(r"\[(\d+)\]", match.group(2)):
            tokens.append(int(index))
    return tokens


def _path_get(root: Any, path: str) -> Any:
    current = root
    for token in _parse_path(path):
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise ScenarioError(f"path {path!r} has no list index {token}")
            current = current[token]
            continue
        if isinstance(current, Mapping) and token in current:
            current = current[token]
            continue
        raise ScenarioError(f"path {path!r} has no key {token!r}")
    return current


def _resolve_refs(value: Any, captures: Mapping[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        name = value[1:]
        if not name or name not in captures:
            raise ScenarioError(f"unknown scenario capture {value!r}")
        return _json_copy(captures[name])
    if isinstance(value, list):
        return [_resolve_refs(item, captures) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _resolve_refs(item, captures) for key, item in value.items()}
    return value


def _coerce_predicate(value: str) -> Any:
    text = value.strip()
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if text.lower() == "null":
        return None
    try:
        return int(text)
    except ValueError:
        return text


def _parse_where(where: Any) -> dict[str, Any]:
    if isinstance(where, Mapping):
        return dict(where)
    if isinstance(where, str):
        match = re.fullmatch(r"@\{([^=]+)=(.*)\}", where.strip())
        if match is None:
            raise ScenarioError(f"unsupported capture where expression {where!r}")
        return {match.group(1).strip(): _coerce_predicate(match.group(2))}
    raise ScenarioError("capture where must be an object or @{field=value} expression")


def _matches_where(value: Any, where: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping):
        return False
    for key, expected in where.items():
        actual = value.get(key)
        if isinstance(expected, Mapping):
            if "contains" in expected:
                required = expected["contains"]
                if not isinstance(actual, list) or not isinstance(required, list):
                    return False
                if not all(
                    any(
                        _matches_where(candidate, requirement)
                        if isinstance(requirement, Mapping)
                        else candidate == requirement
                        for candidate in actual
                    )
                    for requirement in required
                ):
                    return False
                continue
            if "none" in expected:
                forbidden = expected["none"]
                if not isinstance(actual, list) or not isinstance(forbidden, list):
                    return False
                if any(
                    any(
                        _matches_where(candidate, requirement)
                        if isinstance(requirement, Mapping)
                        else candidate == requirement
                        for candidate in actual
                    )
                    for requirement in forbidden
                ):
                    return False
                continue
            if "exact" in expected:
                if actual != expected["exact"]:
                    return False
                continue
            if not _matches_where(actual, expected):
                return False
        elif isinstance(expected, list):
            if actual != expected:
                return False
        elif actual != expected:
            return False
    return True


def _capture_value(response: Mapping[str, Any], spec: Mapping[str, Any]) -> Any:
    path = spec.get("path")
    value = _path_get(response, str(path))
    if "where" in spec:
        where = _parse_where(spec["where"])
        if not isinstance(value, list):
            raise ScenarioError(f"capture path {path!r} is not a list")
        matches = [item for item in value if _matches_where(item, where)]
        if len(matches) != 1:
            raise ScenarioError(
                f"capture path {path!r} expected one match for {where!r}, got {len(matches)}"
            )
        value = matches[0]
    if "field" in spec:
        field = spec["field"]
        if not isinstance(value, Mapping) or field not in value:
            raise ScenarioError(f"capture field {field!r} is absent at {path!r}")
        value = value[field]
    return _json_copy(value)


def _card_id_for_iid(session: Any, iid: Any) -> str | None:
    if isinstance(iid, bool):
        return None
    try:
        wanted = int(iid)
    except (TypeError, ValueError):
        return None
    for card in _iter_instances(session):
        if int(card.iid) == wanted:
            return card.card.id
    return None


def _iter_instances(session: Any) -> Iterable[Any]:
    for player in session.engine.state.players:
        for zone in (
            player.deck,
            player.hand,
            player.base,
            player.field,
            player.trash,
            player.removed,
        ):
            yield from zone
            for card in zone:
                yield from getattr(card, "blessings", ())


def _option_action(session: Any, option: Mapping[str, Any]) -> Any:
    option_id = option.get("id")
    if not isinstance(option_id, str) or option_id not in session._options:
        raise ScenarioError(f"prompt option has no authoritative action: {option_id!r}")
    return session._options[option_id]


def _option_value(session: Any, option: Mapping[str, Any], key: str) -> Any:
    if key in option:
        return option[key]
    action = _option_action(session, option)
    payload = getattr(action, "payload", {}) or {}
    aliases = {
        "iid": ("iid", "attacker_iid", "mana_iid"),
        "cardIid": ("cardIid", "iid", "attacker_iid", "mana_iid"),
        "target_iid": ("target_iid", "targetIid"),
        "direction": ("direction",),
        "forceId": ("forceId", "force_id"),
    }
    for candidate in aliases.get(key, (key,)):
        if candidate in payload:
            return payload[candidate]
    return None


def _option_matches(session: Any, option: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    action = _option_action(session, option)
    payload = getattr(action, "payload", {}) or {}
    action_kind = getattr(action, "kind", None)
    for key, expected in selector.items():
        if key == "kind":
            option_kind = option.get("kind")
            target_kind = option.get("targetKind")
            if expected not in {action_kind, option_kind, target_kind}:
                return False
            continue
        if key == "cardId":
            actual = option.get("cardId")
            if actual is None:
                for candidate in (
                    option.get("iid"),
                    option.get("cardIid"),
                    payload.get("iid"),
                    payload.get("attacker_iid"),
                    payload.get("mana_iid"),
                ):
                    actual = _card_id_for_iid(session, candidate)
                    if actual is not None:
                        break
            if actual != expected:
                return False
            continue
        if key == "cardIid":
            actual = _option_value(session, option, key)
            if actual != expected:
                return False
            continue
        if key == "iid":
            actual = _option_value(session, option, key)
            if actual != expected:
                return False
            continue
        if key == "target_iid":
            actual = _option_value(session, option, key)
            if actual != expected:
                return False
            continue
        actual = _option_value(session, option, key)
        if actual is None and key in option:
            actual = option[key]
        if actual != expected:
            return False
    return True


def _select_option_ids(session: Any, action: Mapping[str, Any]) -> list[str]:
    if not isinstance(session.prompt, Mapping):
        raise ScenarioError(f"action {action.get('name', '<unnamed>')!r} has no prompt")
    prompt_kind = action.get("prompt_kind")
    actual_kind = session.prompt.get("kind")
    if prompt_kind != actual_kind:
        raise ScenarioError(
            f"action {action.get('name', '<unnamed>')!r} expected prompt {prompt_kind!r}, got {actual_kind!r}"
        )
    options = _require_list(session.prompt.get("options"), "prompt.options")
    if "select_many" in action:
        selectors = _require_list(action["select_many"], "action.select_many")
        selected: list[str] = []
        for selector in selectors:
            selector_map = _require_mapping(selector, "action.select_many item")
            matches = [
                option
                for option in options
                if _option_matches(session, option, selector_map)
            ]
            if len(matches) != 1:
                raise ScenarioError(
                    f"action {action.get('name', '<unnamed>')!r} selector {selector_map!r} matched {len(matches)} options"
                )
            option_id = matches[0].get("id")
            if not isinstance(option_id, str) or option_id in selected:
                raise ScenarioError("select_many produced duplicate or invalid option IDs")
            selected.append(option_id)
        if not selected:
            raise ScenarioError("select_many must contain at least one selector")
        return selected
    selector = action.get("select")
    if selector is None:
        raise ScenarioError(f"action {action.get('name', '<unnamed>')!r} is missing select/select_many")
    selector_map = _require_mapping(selector, "action.select")
    matches = [
        option
        for option in options
        if _option_matches(session, option, selector_map)
    ]
    if len(matches) != 1:
        raise ScenarioError(
            f"action {action.get('name', '<unnamed>')!r} selector {selector_map!r} matched {len(matches)} options"
        )
    option_id = matches[0].get("id")
    if not isinstance(option_id, str):
        raise ScenarioError("selected prompt option has no string ID")
    return [option_id]


def _state_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a compact diagnostic alongside the full evidence snapshots."""
    players = state.get("players") if isinstance(state, Mapping) else None
    summary: dict[str, Any] = {
        "turn": state.get("turn"),
        "phase": state.get("phase"),
        "step": state.get("step"),
        "activeSide": state.get("activeSide"),
        "promptKind": (state.get("prompt") or {}).get("kind") if isinstance(state.get("prompt"), Mapping) else None,
    }
    if isinstance(players, Mapping):
        summary["players"] = {
            side: {
                key: players.get(side, {}).get(key)
                for key in ("life", "handCount", "field", "base", "trashCount", "movementRightCount")
                if isinstance(players.get(side), Mapping)
            }
            for side in ("human", "opponent")
        }
    return summary


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ScenarioError(f"{label}: expected {expected!r}, got {actual!r}")


def _assertion_count(items: Any, where: Mapping[str, Any], expected: int, label: str) -> int:
    if not isinstance(items, list):
        raise ScenarioError(f"{label}: count_where path is not a list")
    count = sum(1 for item in items if _matches_where(item, where))
    _assert_equal(count, expected, label)
    return count


def _run_assertion(state: Mapping[str, Any], assertion: Mapping[str, Any]) -> dict[str, Any]:
    name = str(assertion.get("name") or assertion.get("claim") or "assertion")
    path = assertion.get("path")
    if not isinstance(path, str) or not path.startswith("state."):
        raise ScenarioError(f"{name}: assertion path must start with state.")
    actual = _path_get({"state": state}, path)
    op = assertion.get("op")
    expected = assertion.get("value")
    if op == "eq":
        _assert_equal(actual, expected, name)
        detail = {"op": op, "actual": actual, "expected": expected}
    elif op == "gt":
        if not isinstance(actual, (int, float)) or not actual > expected:
            raise ScenarioError(f"{name}: expected {actual!r} > {expected!r}")
        detail = {"op": op, "actual": actual, "expected": expected}
    elif op in {"count_where", "none_where", "any_where"}:
        where = assertion.get("where")
        if not isinstance(where, Mapping):
            raise ScenarioError(f"{name}: {op} requires an object where clause")
        if not isinstance(actual, list):
            raise ScenarioError(f"{name}: {op} path is not a list")
        count = sum(1 for item in actual if _matches_where(item, where))
        if op == "count_where":
            _assert_equal(count, expected, name)
        elif op == "none_where":
            _assert_equal(count, 0, name)
        elif count == 0:
            raise ScenarioError(f"{name}: expected at least one match for {where!r}")
        detail = {"op": op, "count": count, "expected": expected, "where": _json_copy(where)}
    elif op == "length_eq":
        if not isinstance(actual, (list, dict, str)):
            raise ScenarioError(f"{name}: length_eq path is not sized")
        count = len(actual)
        _assert_equal(count, expected, name)
        detail = {"op": op, "actual": count, "expected": expected}
    else:
        raise ScenarioError(f"{name}: unsupported assertion operation {op!r}")
    return {"name": name, "path": path, **detail}


class ScenarioRunner:
    def __init__(self, spec_path: Path, project_root: Path) -> None:
        self.spec_path = spec_path.resolve()
        self.project_root = project_root.resolve()
        try:
            self.spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScenarioError(f"cannot load scenario {self.spec_path}: {exc}") from exc
        if not isinstance(self.spec, Mapping):
            raise ScenarioError("scenario root must be an object")
        self._validate_spec_header()
        self.captures: dict[str, Any] = {}
        self.session: Any | None = None
        self.state: dict[str, Any] | None = None
        self.setup_records: list[dict[str, Any]] = []
        self.action_records: list[dict[str, Any]] = []
        self.assertion_records: list[dict[str, Any]] = []

    def _validate_spec_header(self) -> None:
        required = ("schema_version", "scenario_id", "card_id", "scenario_kind", "official_rule", "setup", "actions", "assertions")
        missing = [key for key in required if key not in self.spec]
        if missing:
            raise ScenarioError(f"scenario missing required fields: {', '.join(missing)}")
        if self.spec.get("schema_version") != 1:
            raise ScenarioError(f"unsupported scenario schema {self.spec.get('schema_version')!r}")
        if self.spec.get("scenario_kind") not in {"positive", "boundary"}:
            raise ScenarioError(f"unsupported scenario kind {self.spec.get('scenario_kind')!r}")
        if not str(self.spec.get("official_rule") or "").strip():
            raise ScenarioError("official_rule must not be empty")
        if not str(self.spec.get("card_id") or "").strip():
            raise ScenarioError("card_id must not be empty")
        if "placeholder" in str(self.spec.get("official_rule") or "").lower():
            raise ScenarioError("placeholder rule text is not allowed")

    def _imports(self) -> tuple[Any, ...]:
        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))
        try:
            from zz.web.debug_tools import (
                add_debug_card_to_zone,
                move_debug_card,
                set_debug_card_state,
                set_debug_control,
                set_debug_force_state,
                set_debug_life,
                setup_debug_fixed_board,
                setup_debug_lab,
            )
            from zz.web.server import ServerState
        except Exception as exc:  # pragma: no cover - diagnostic includes import traceback
            raise ScenarioError(f"cannot import project runtime from {self.project_root}: {exc}") from exc
        return (
            ServerState,
            add_debug_card_to_zone,
            move_debug_card,
            set_debug_card_state,
            set_debug_control,
            set_debug_force_state,
            set_debug_life,
            setup_debug_fixed_board,
            setup_debug_lab,
        )

    def _envelope(self, state: dict[str, Any], debug: Mapping[str, Any] | None = None) -> dict[str, Any]:
        state = _json_copy(state)
        state["devMode"] = True
        out: dict[str, Any] = {"ok": state.get("error") is None, "state": state}
        if state.get("error") is not None:
            out["error"] = _json_copy(state["error"])
        if debug is not None:
            out["debug"] = _json_copy(debug)
        return out

    def _state_response(self, debug: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if self.session is None:
            raise ScenarioError("runtime session has not been initialized")
        return self._envelope(self.session.state_dto(), debug)

    def _transform_fixture(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Transform an existing legal face, including its real transform event.

        This explicit test operation is not a debug add endpoint: scenarios must
        first create a deck-buildable source and name a verified source/target
        edge. No transformed CardInstance is constructed by the runner.
        """
        from zz.cards import CARD_REGISTRY
        from zz.transformations import transformation_graph
        from zz.web.debug_tools import _debug_refresh_session

        source_id, target_id = str(payload["sourceId"]), str(payload["targetId"])
        if target_id not in transformation_graph().get(source_id, ()):
            raise ScenarioError(f"unverified fixture transformation: {source_id} -> {target_id}")
        matches = [card for card in _iter_instances(self.session) if card.iid == int(payload["iid"])]
        if len(matches) != 1 or matches[0].card.id != source_id:
            raise ScenarioError(f"fixture transformation source does not match iid {payload['iid']}: {source_id}")
        source = matches[0]
        if self.session._pending_effect is not None or self.session._attack is not None:
            raise ScenarioError("fixture transformation requires all previous choices to be resolved")
        # An outstanding main-action prompt pauses TriggerRegistry.resolve_all.
        # Release it just as GameSession.choose does before executing an action.
        self.session._clear_prompt()
        self.session.engine.transform_card(source, copy.copy(CARD_REGISTRY[target_id]))
        if source.card.id != target_id:
            raise ScenarioError(f"fixture transformation did not produce {target_id}")
        if self.session._pending_effect is not None or self.session.engine.triggers.has_pending():
            raise ScenarioError("fixture transformation requires an explicit rule choice; use scenario actions")
        _debug_refresh_session(self.session)
        return {"transformed": {"iid": source.iid, "sourceId": source_id, "cardId": target_id}}

    def _return_fixture_to_hand(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from zz.web.debug_tools import _debug_refresh_session

        matches = [card for card in _iter_instances(self.session) if card.iid == int(payload["iid"])]
        if len(matches) != 1:
            raise ScenarioError(f"fixture return source does not match iid {payload['iid']}")
        source = matches[0]
        if not self.session.engine.return_to_hand(source):
            raise ScenarioError(f"fixture card {source.iid} cannot return to hand")
        _debug_refresh_session(self.session)
        return {"returned": {"iid": source.iid, "cardId": source.card.id, "zone": "hand"}}

    def _apply_setup(self, call: Mapping[str, Any]) -> dict[str, Any]:
        path = call.get("path")
        payload = _resolve_refs(_require_mapping(call.get("payload", {}), "setup.payload"), self.captures)
        (
            ServerState,
            add_debug_card_to_zone,
            move_debug_card,
            set_debug_card_state,
            set_debug_control,
            set_debug_force_state,
            set_debug_life,
            setup_debug_fixed_board,
            setup_debug_lab,
        ) = self._imports()
        if path == "/api/debug/setup":
            app = ServerState()
            new_payload = {
                "mode": "debug-card-lab",
                "seed": payload.get("seed"),
                "firstPlayer": "human",
                "playerProfile": payload.get("playerProfile"),
                "opponentProfile": payload.get("opponentProfile"),
            }
            self.session = app.new_session(new_payload)
            debug = setup_debug_lab(
                self.session,
                str(payload.get("cardId") or ""),
                zone=str(payload.get("zone") or "hand"),
                player_forces=payload.get("playerForces"),
                opponent_forces=payload.get("opponentForces"),
                compact_board=bool(payload.get("compactBoard", False)),
                non_minion_mana_only=bool(payload.get("nonMinionManaOnly", False)),
            )
        else:
            if self.session is None:
                raise ScenarioError(f"setup path {path!r} requires /api/debug/setup first")
            if path == "/api/debug/add-card":
                debug = add_debug_card_to_zone(
                    self.session,
                    str(payload.get("cardId") or ""),
                    side=str(payload.get("side") or "P1"),
                    zone=str(payload.get("zone") or "hand"),
                    rested=bool(payload.get("rested", False)),
                )
            elif path == "/api/debug/move-card":
                debug = move_debug_card(
                    self.session,
                    int(payload["iid"]),
                    zone=str(payload.get("zone") or "hand"),
                    rested=payload.get("rested") if "rested" in payload else None,
                )
            elif path == "/api/debug/card-state":
                debug = set_debug_card_state(
                    self.session,
                    int(payload["iid"]),
                    rested=payload.get("rested") if "rested" in payload else None,
                    permanent_bp_modifier=(
                        None if "permanentBpModifier" not in payload else int(payload["permanentBpModifier"])
                    ),
                    permanent_dp_modifier=(
                        None if "permanentDpModifier" not in payload else int(payload["permanentDpModifier"])
                    ),
                )
            elif path == "/api/debug/control":
                debug = set_debug_control(self.session, bool(payload.get("controlBoth", False)))
            elif path == "/api/debug/life":
                debug = set_debug_life(
                    self.session,
                    side=str(payload.get("side") or "P1"),
                    life=int(payload["life"]),
                    force_index=int(payload["forceIndex"]) if "forceIndex" in payload else None,
                )
            elif path == "/api/debug/force-state":
                debug = set_debug_force_state(
                    self.session,
                    side=str(payload.get("side") or "P1"),
                    force_index=int(payload["forceIndex"]),
                    destroyed=bool(payload.get("destroyed", False)),
                    rested=payload.get("rested") if "rested" in payload else None,
                )
            elif path == "/api/debug/fixed-board":
                debug = setup_debug_fixed_board(
                    self.session,
                    active_side=str(payload.get("activeSide") or "P1"),
                    control_both=bool(payload.get("controlBoth", True)),
                    preserve_board=bool(payload.get("preserveBoard", False)),
                    step=str(payload.get("step") or "main"),
                )
            elif path == "/fixture/transform-card":
                debug = self._transform_fixture(payload)
            elif path == "/fixture/return-to-hand":
                debug = self._return_fixture_to_hand(payload)
            else:
                raise ScenarioError(f"unsupported semantic setup path {path!r}")
        response = self._state_response(debug)
        self.state = response["state"]
        return response

    def _run_action(self, action: Mapping[str, Any]) -> dict[str, Any]:
        if self.session is None or self.state is None:
            raise ScenarioError("action cannot run before setup")
        action = _require_mapping(_resolve_refs(action, self.captures), "action")
        option_ids = _select_option_ids(self.session, action)
        prompt = _json_copy(self.state.get("prompt"))
        options_by_id = {
            option.get("id"): option
            for option in (prompt.get("options") or [])
            if isinstance(option, Mapping)
        }
        selected_options = [options_by_id[option_id] for option_id in option_ids]
        payload: dict[str, Any] = {
            "promptId": str(self.session.prompt["id"]),
            "optionId": option_ids[0],
        }
        if len(option_ids) > 1:
            payload["selectedOptionIds"] = option_ids
        before_state = _json_copy(self.state)
        try:
            state = self.session.choose(payload["promptId"], payload["optionId"], payload)
        except Exception as exc:
            raise ScenarioError(
                f"action {action.get('name', '<unnamed>')!r} raised {type(exc).__name__}: {exc}"
            ) from exc
        response = self._envelope(state)
        if not response["ok"]:
            raise ScenarioError(
                f"action {action.get('name', '<unnamed>')!r} returned error {response.get('error')!r}"
            )
        self.state = response["state"]
        self.action_records.append({
            "index": len(self.action_records),
            "name": str(action.get("name") or ""),
            "path": "/api/choose",
            "prompt": prompt,
            "selected_options": _json_copy(selected_options),
            "payload": payload,
            "status": 200,
            "ok": True,
            "before_state": before_state,
            "after_state": _json_copy(self.state),
        })
        return response

    def _apply_captures(self, response: Mapping[str, Any], call: Mapping[str, Any]) -> None:
        captures = call.get("capture")
        if captures is None:
            return
        captures_map = _require_mapping(captures, "capture")
        for name, raw_spec in captures_map.items():
            spec = _require_mapping(raw_spec, f"capture.{name}")
            self.captures[str(name)] = _capture_value(response, spec)

    def _run_assertions(self) -> None:
        if self.state is None:
            raise ScenarioError("scenario has no final state")
        assertions = _require_list(self.spec.get("assertions"), "assertions")
        if not assertions:
            raise ScenarioError("scenario must contain at least one assertion")
        for assertion_raw in assertions:
            assertion = _require_mapping(
                _resolve_refs(assertion_raw, self.captures),
                "assertion",
            )
            result = _run_assertion(self.state, assertion)
            self.assertion_records.append(result)

    def run(self) -> dict[str, Any]:
        setup = _require_list(self.spec.get("setup"), "setup")
        actions = _require_list(self.spec.get("actions"), "actions")
        if not setup:
            raise ScenarioError("scenario must contain at least one setup call")
        if not actions:
            raise ScenarioError("scenario must contain at least one action")
        for index, call_raw in enumerate(setup):
            call = _require_mapping(call_raw, f"setup[{index}]")
            response = self._apply_setup(call)
            self._apply_captures(response, call)
            self.setup_records.append({
                "index": index,
                "path": call.get("path"),
                "payload": _resolve_refs(_json_copy(call.get("payload", {})), self.captures),
                "status": 200,
                "ok": bool(response.get("ok")),
            })
            if not response.get("ok"):
                raise ScenarioError(f"setup[{index}] returned {response.get('error')!r}")
        for index, action_raw in enumerate(actions):
            action = _require_mapping(action_raw, f"actions[{index}]")
            self._run_action(action)
        self._run_assertions()
        return {
            "schema_version": 1,
            "scenario_id": self.spec["scenario_id"],
            "card_id": self.spec["card_id"],
            "scenario_kind": self.spec["scenario_kind"],
            "official_rule": self.spec["official_rule"],
            "seed": self.spec.get("seed"),
            "spec_sha256": _sha256(self.spec_path),
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "result": "passed",
            "setup_calls": self.setup_records,
            "public_actions": self.action_records,
            "assertions": self.assertion_records,
            "captures": _json_copy(self.captures),
            "final_state_summary": _state_summary(self.state or {}),
        }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = ScenarioRunner(args.scenario, args.project_root).run()
    except Exception as exc:
        error = {
            "schema_version": 1,
            "scenario": str(args.scenario.resolve()),
            "result": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        try:
            _write_json(args.evidence.resolve(), error)
        except OSError as write_exc:
            print(f"semantic runner could not write failure evidence: {write_exc}", file=sys.stderr)
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        if not isinstance(exc, ScenarioError):
            traceback.print_exc(file=sys.stderr)
        return 1
    _write_json(args.evidence.resolve(), result)
    print(json.dumps({
        "result": "passed",
        "scenario_id": result["scenario_id"],
        "assertions": len(result["assertions"]),
        "actions": len(result["public_actions"]),
        "evidence": str(args.evidence.resolve()),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
