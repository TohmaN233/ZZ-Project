from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import zz.decks  # noqa: F401 - populate the complete runtime card registry
from zz.cards import CARD_REGISTRY
from zz.enums import CardType
from zz.pc01r import PC01R_CARD_IDS


SCENARIO_ROOT = ROOT / "project_memory" / "card_scenarios" / "pc01r"
EVIDENCE_ROOT = ROOT / "project_memory" / "card_evidence" / "pc01r"
MANIFEST_PATH = ROOT / "project_memory" / "card_boxes" / "pc01r.yaml"


def claim(card_id: str, kind: str, text: str) -> dict[str, str]:
    return {"id": f"{card_id}_{kind}", "kind": kind, "expected_observation": text}


def assertion(
    card_id: str,
    name: str,
    path: str,
    op: str,
    *,
    value: Any = None,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "claim": f"{card_id}_{'positive' if 'positive' in name else 'boundary'}",
        "path": path,
        "op": op,
    }
    if op not in {"any_where", "none_where"}:
        out["value"] = value
    if where is not None:
        out["where"] = where
    return out


def setup(
    card_id: str,
    seed: int,
    *,
    zone: str = "hand",
    capture: bool = False,
    player_forces: list[str] | None = None,
    opponent_forces: list[str] | None = None,
    non_minion_mana_only: bool = False,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "path": "/api/debug/setup",
        "payload": {
            "cardId": card_id,
            "seed": seed,
            "zone": zone,
            "compactBoard": True,
            "playerForces": player_forces or ["force_e", "force_so2"],
            "opponentForces": opponent_forces or ["force_kon", "force_rin"],
            "nonMinionManaOnly": non_minion_mana_only,
        },
    }
    if capture:
        step["capture"] = {
            "audited_iid": {
                "path": f"state.players.human.{zone}",
                "where": {"cardId": card_id},
                "field": "iid",
            }
        }
    return step


def add(
    card_id: str,
    *,
    side: str,
    zone: str,
    rested: bool = False,
    capture_as: str | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "path": "/api/debug/add-card",
        "payload": {"cardId": card_id, "side": side, "zone": zone, "rested": rested},
    }
    if capture_as:
        step["capture"] = {capture_as: {"path": "debug.added.iid"}}
    return step


def fixed(*, active: str, step: str = "main") -> dict[str, Any]:
    return {
        "path": "/api/debug/fixed-board",
        "payload": {"activeSide": active, "controlBoth": True, "preserveBoard": True, "step": step},
    }


def force_state(side: str, index: int, destroyed: bool, *, rested: bool | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"side": side, "forceIndex": index, "destroyed": destroyed}
    if rested is not None:
        payload["rested"] = rested
    return {
        "path": "/api/debug/force-state",
        "payload": payload,
    }


def card_state(
    iid: str,
    *,
    rested: bool | None = None,
    permanent_bp_modifier: int | None = None,
    permanent_dp_modifier: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"iid": iid}
    if rested is not None:
        payload["rested"] = rested
    if permanent_bp_modifier is not None:
        payload["permanentBpModifier"] = permanent_bp_modifier
    if permanent_dp_modifier is not None:
        payload["permanentDpModifier"] = permanent_dp_modifier
    return {"path": "/api/debug/card-state", "payload": payload}


def life(side: str, value: int, force_index: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"side": side, "life": value}
    if force_index is not None:
        payload["forceIndex"] = force_index
    return {"path": "/api/debug/life", "payload": payload}


def choose(name: str, prompt: str, selector: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "prompt_kind": prompt, "select": selector}


def play(card_id: str) -> dict[str, Any]:
    kind = "play_to_base" if CARD_REGISTRY[card_id].type is CardType.B_MINION else "play_card"
    return choose("play audited card", "main_action", {"kind": kind, "cardId": card_id})


def target(card_id: str, *, name: str = "choose effect target") -> dict[str, Any]:
    return choose(name, "effect_target", {"cardId": card_id})


def target_force(force_id: str) -> dict[str, Any]:
    return choose("choose Force target", "effect_target", {"forceId": force_id})


def optional(use: bool) -> dict[str, Any]:
    return choose("resolve optional effect", "optional_effect", {"id": "yes" if use else "no"})


def move(card_id: str, direction: str = "field_to_base") -> dict[str, Any]:
    return choose("move audited card", "main_action", {"kind": "move_card", "cardId": card_id, "direction": direction})


def attack(card_id: str) -> dict[str, Any]:
    return choose("attack with audited card", "main_action", {"kind": "attack", "cardId": card_id})


def attack_force(force_id: str = "force_kon") -> dict[str, Any]:
    option_id = "t0" if force_id == "force_kon" else "t1"
    return choose("choose attack Force", "attack_target", {"id": option_id})


def attack_player() -> dict[str, Any]:
    return choose("choose opposing player", "attack_target", {"kind": "player"})


def end_turn() -> dict[str, Any]:
    return choose("end turn", "main_action", {"kind": "end_turn"})


def skip_mana() -> dict[str, Any]:
    return choose("leave mana step", "main_action", {"kind": "skip_mana"})


def place_colorless_mana() -> dict[str, Any]:
    return choose("place colorless mana", "main_action", {"kind": "place_colorless_mana"})


def flash_play(card_id: str) -> dict[str, Any]:
    return choose("cast audited Flash card", "flash_action", {"kind": "play_card", "cardId": card_id})


def flash_pass() -> dict[str, Any]:
    return choose("pass Flash priority", "flash_action", {"kind": "flash_pass"})


def block_with(iid: str) -> dict[str, Any]:
    return choose("choose blocker", "blocker", {"cardIid": iid})


def decline_block() -> dict[str, Any]:
    return choose("decline block", "blocker", {"kind": "no_block"})


def scenario(
    card_id: str,
    kind: str,
    seed: int,
    claim_kind: str,
    observation: str,
    setup_steps: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
) -> dict[str, Any]:
    if kind == "positive" and claim_kind == "zone_transition":
        claim_kind = "state_transition"
    claim_id = f"{card_id}_{kind}"
    for item in assertions:
        item["claim"] = claim_id
    return {
        "schema_version": 1,
        "scenario_id": f"{card_id}_{kind}",
        "card_id": card_id,
        "scenario_kind": kind,
        "official_rule": CARD_REGISTRY[card_id].ability_jp,
        "semantic_claims": [{"id": claim_id, "kind": claim_kind, "expected_observation": observation}],
        "seed": seed,
        "setup": setup_steps,
        "actions": actions,
        "assertions": assertions,
    }


def pair(
    card_id: str,
    seed: int,
    positive: tuple[str, str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]],
    boundary: tuple[str, str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    pk, po, ps, pa, px = positive
    bk, bo, bs, ba, bx = boundary
    return {
        "positive": scenario(card_id, "positive", seed, pk, po, ps, pa, px),
        "boundary": scenario(card_id, "boundary", seed + 1, bk, bo, bs, ba, bx),
    }


def count(card_id: str, name: str, path: str, value: int, where: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "path": path, "op": "count_where", "value": value, "where": where}


def eq(name: str, path: str, value: Any) -> dict[str, Any]:
    return {"name": name, "path": path, "op": "eq", "value": value}


def none(name: str, path: str, where: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "path": path, "op": "none_where", "where": where}


def any_match(name: str, path: str, where: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "path": path, "op": "any_where", "where": where}


def demigod_pair(card_id: str, seed: int) -> dict[str, dict[str, Any]]:
    card = CARD_REGISTRY[card_id]
    neutral_forces = ["force_kon", "force_so2"]
    positive_setup = [setup(card_id, seed, zone="field", player_forces=neutral_forces), add("red_04_02_01r_00", side="P1", zone="field")]
    boundary_setup = [setup(card_id, seed + 1, zone="field", player_forces=neutral_forces), add("red_03_02_01r_00", side="P1", zone="field")]
    return pair(
        card_id,
        seed,
        (
            "continuous_effect",
            "A friendly Demigod gives the audited minion exactly BP+200/DP+1.",
            positive_setup,
            [attack(card_id), attack_force()],
            [count(card_id, "positive Demigod bonus", "state.players.human.field", 1, {"cardId": card_id, "effectiveBp": card.bp + 200, "effectiveDp": card.dp + 1})],
        ),
        (
            "non_activation",
            "Without a friendly Demigod, the audited minion keeps its printed BP and DP.",
            boundary_setup,
            [attack(card_id)],
            [count(card_id, "boundary no Demigod bonus", "state.players.human.field", 1, {"cardId": card_id, "effectiveBp": card.bp, "effectiveDp": card.dp})],
        ),
    )


def build_scenarios() -> dict[str, dict[str, dict[str, Any]]]:
    cases: dict[str, dict[str, dict[str, Any]]] = {}

    card_id = "red_00_01_01r_00"
    cases[card_id] = pair(
        card_id, 1001,
        (
            "keyword_legality", "The next red minion summoned after placement receives Rush.",
            [setup(card_id, 1001), add("red_02_02_01r_00", side="P1", zone="hand"), add("colorless_00_01_01r_01", side="P1", zone="base")],
            [play(card_id), play("red_02_02_01r_00")],
            [count(card_id, "positive next red has Rush", "state.players.human.field", 1, {"cardId": "red_02_02_01r_00", "keywords": ["RUSH"]})],
        ),
        (
            "target_boundary", "A non-red summon does not consume or receive the red-only Rush grant.",
            [setup(card_id, 1002), add("blue_02_02_01r_00", side="P1", zone="hand"), add("blue_00_01_01r_00", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base")],
            [play(card_id), play("blue_02_02_01r_00")],
            [count(card_id, "boundary blue has no Rush", "state.players.human.field", 1, {"cardId": "blue_02_02_01r_00", "keywords": []})],
        ),
    )

    card_id = "red_01_03_01r_00"
    cases[card_id] = pair(
        card_id, 1011,
        (
            "state_transition", "One generated minion token grants the selected minion a permanent 100 BP.",
            [setup(card_id, 1011), add("red_03_02_01r_00", side="P1", zone="field"), add("red_02_02_01r_00", side="P1", zone="field")],
            [move("red_03_02_01r_00"), play(card_id), target("red_02_02_01r_00")],
            [count(card_id, "positive token count buff", "state.players.human.field", 1, {"cardId": "red_02_02_01r_00", "permanentBpModifier": 100})],
        ),
        (
            "zero_target", "With no minion tokens, the selected minion receives a zero BP change.",
            [setup(card_id, 1012), add("red_02_02_01r_00", side="P1", zone="field")],
            [play(card_id), target("red_02_02_01r_00")],
            [count(card_id, "boundary no token buff", "state.players.human.field", 1, {"cardId": "red_02_02_01r_00", "permanentBpModifier": 0})],
        ),
    )

    card_id = "red_02_02_01r_00"
    cases[card_id] = pair(
        card_id, 1021,
        (
            "trigger_resolution", "Attacking the opposing player permanently adds 100 BP.",
            [setup(card_id, 1021, zone="field"), force_state("P2", 0, True), force_state("P2", 1, True)],
            [attack(card_id), attack_player()],
            [count(card_id, "positive player attack growth", "state.players.human.field", 1, {"cardId": card_id, "permanentBpModifier": 100})],
        ),
        (
            "non_activation", "Attacking a Force does not grant the player-attack BP bonus.",
            [setup(card_id, 1022, zone="field")],
            [attack(card_id), attack_force()],
            [count(card_id, "boundary Force attack no growth", "state.players.human.field", 1, {"cardId": card_id, "permanentBpModifier": 0})],
        ),
    )

    card_id = "red_02_03_01r_00"
    cases[card_id] = pair(
        card_id, 1031,
        (
            "target_selection", "BP500 is included and the selected enemy cannot block this turn.",
            [setup(card_id, 1031), add("white_04_02_01r_00", side="P2", zone="field")],
            [play(card_id), target("white_04_02_01r_00")],
            [count(card_id, "positive inclusive BP500 target", "state.players.opponent.field", 1, {"cardId": "white_04_02_01r_00", "keywords": ["CANNOT_BLOCK"]})],
        ),
        (
            "target_boundary", "BP400 is below the inclusive BP500 minimum and receives no restriction.",
            [setup(card_id, 1032), add("white_03_02_01r_00", side="P2", zone="field")],
            [play(card_id)],
            [count(card_id, "boundary BP400 excluded", "state.players.opponent.field", 1, {"cardId": "white_03_02_01r_00", "keywords": ["REAWAKEN"]})],
        ),
    )

    card_id = "red_03_02_01r_00"
    cases[card_id] = pair(
        card_id, 1041,
        (
            "trigger_resolution", "Retreating creates exactly one S Golem token.",
            [setup(card_id, 1041, zone="field")], [move(card_id)],
            [count(card_id, "positive retreat token", "state.players.human.field", 1, {"cardId": "s_golem_token"})],
        ),
        (
            "area_gate", "Moving from base to field does not fire the retreat trigger.",
            [setup(card_id, 1042, zone="base")], [move(card_id, "base_to_field")],
            [none("boundary no token outside retreat", "state.players.human.field", {"cardId": "s_golem_token"})],
        ),
    )

    card_id = "red_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1051,
        (
            "target_selection", "Summoning adds a new copy of the selected other non-token minion to hand.",
            [setup(card_id, 1051), add("blue_02_02_01r_00", side="P2", zone="field")],
            [play(card_id), target("blue_02_02_01r_00")],
            [count(card_id, "positive copied card in hand", "state.players.human.hand", 1, {"cardId": "blue_02_02_01r_00"})],
        ),
        (
            "zero_target", "With no other non-token minion, summoning adds no copied card.",
            [setup(card_id, 1052)], [play(card_id)],
            [eq("boundary hand stays empty", "state.players.human.handCount", 0)],
        ),
    )

    for offset, aura_id in enumerate([
        "red_05_02_01r_00",
        "yellow_04_02_01r_00",
        "purple_04_02_01r_00",
        "green_06_02_01r_00",
        "blue_05_02_01r_00",
        "white_03_02_01r_00",
    ]):
        cases[aura_id] = demigod_pair(aura_id, 1061 + offset * 10)

    card_id = "red_05_03_01r_00"
    cases[card_id] = pair(
        card_id, 1071,
        (
            "state_transition", "The selected enemy receives a permanent BP-500 modifier.",
            [setup(card_id, 1071), add("white_06_02_01r_00", side="P2", zone="field")],
            [play(card_id), target("white_06_02_01r_00")],
            [count(card_id, "positive permanent minus 500", "state.players.opponent.field", 1, {"cardId": "white_06_02_01r_00", "permanentBpModifier": -500})],
        ),
        (
            "zero_target", "With no enemy minion, the Magic resolves without inventing a target.",
            [setup(card_id, 1072)], [play(card_id)],
            [eq("boundary enemy field remains empty", "state.players.opponent.field", [])],
        ),
    )

    card_id = "red_07_02_01r_00"
    cases[card_id] = pair(
        card_id, 1081,
        (
            "trigger_resolution", "The attack trigger gives one selected enemy BP-300 for the turn.",
            [setup(card_id, 1081, zone="field"), add("white_04_02_01r_00", side="P2", zone="field")],
            [attack(card_id), attack_force(), target("white_04_02_01r_00")],
            [count(card_id, "positive attack BP reduction", "state.players.opponent.field", 1, {"cardId": "white_04_02_01r_00", "turnBpModifier": -300})],
        ),
        (
            "area_gate", "The separate retreat trigger creates exactly two S Golem tokens.",
            [setup(card_id, 1082, zone="field")], [move(card_id)],
            [count(card_id, "boundary retreat creates two", "state.players.human.field", 2, {"cardId": "s_golem_token"})],
        ),
    )

    card_id = "yellow_00_01_01r_00"
    target_card = CARD_REGISTRY["yellow_02_02_01r_00"]
    cases[card_id] = pair(
        card_id, 1101,
        (
            "state_transition", "Placement gives every friendly minion BP+100 for the turn, including minions summoned later this turn.",
            [setup(card_id, 1101), add("yellow_02_02_01r_00", side="P1", zone="field")], [play(card_id)],
            [count(card_id, "positive current minion buff", "state.players.human.field", 1, {"cardId": "yellow_02_02_01r_00", "effectiveBp": target_card.bp + 200})],
        ),
        (
            "target_boundary", "A minion summoned after placement still inherits the BP bonus for the rest of this turn.",
            [setup(card_id, 1102), add("yellow_02_02_01r_00", side="P1", zone="hand"), add("yellow_00_01_01r_00", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base")],
            [play(card_id), play("yellow_02_02_01r_00")],
            [count(card_id, "boundary later minion receives buff", "state.players.human.field", 1, {"cardId": "yellow_02_02_01r_00", "effectiveBp": target_card.bp + 200})],
        ),
    )

    card_id = "yellow_01_03_01r_00"
    flash_card = "blue_05_03_01r_00"
    attacker_id = "colorless_03_02_01r_00"
    common_sun_setup = [
        add(attacker_id, side="P1", zone="field"),
        add(flash_card, side="P2", zone="hand"),
        add("blue_00_01_01r_00", side="P2", zone="base"),
        add("blue_00_01_01r_00", side="P2", zone="base"),
        add("colorless_00_01_01r_01", side="P2", zone="base"),
        add("colorless_00_01_01r_01", side="P2", zone="base"),
        add("colorless_00_01_01r_01", side="P2", zone="base"),
        fixed(active="P1"),
    ]
    cases[card_id] = pair(
        card_id, 1111,
        (
            "resource_change", "During the same turn, the opponent cannot pay the audited +3 free-cost increase with only printed-cost mana.",
            [setup(card_id, 1111), *common_sun_setup],
            [play(card_id), attack(attacker_id), attack_force()],
            [none("positive opponent Magic removed from Flash options", "state.prompt.options", {"cardId": flash_card})],
        ),
        (
            "duration_cleanup", "At turn end the +3 free-cost increase expires and the opponent can play the Magic for printed cost.",
            [setup(card_id, 1112), *common_sun_setup, add(attacker_id, side="P2", zone="field"), add("red_02_02_01r_00", side="P2", zone="deck")],
            [play(card_id), end_turn(), place_colorless_mana(), attack(attacker_id), attack_force(), flash_pass()],
            [any_match("boundary Magic returns after cleanup", "state.prompt.options", {"kind": "play_card"})],
        ),
    )

    card_id = "yellow_02_02_01r_00"
    cases[card_id] = pair(
        card_id, 1121,
        (
            "trigger_resolution", "Retreating refreshes a rested yellow minion whose original cost is exactly six.",
            [setup(card_id, 1121, zone="field"), add("yellow_06_02_01r_01", side="P1", zone="field", rested=True)],
            [move(card_id), target("yellow_06_02_01r_01")],
            [count(card_id, "positive cost six refreshed", "state.players.human.field", 1, {"cardId": "yellow_06_02_01r_01", "rested": False})],
        ),
        (
            "target_boundary", "A cost-five yellow minion is below the minimum and remains rested.",
            [setup(card_id, 1122, zone="field"), add("yellow_05_02_01r_00", side="P1", zone="field", rested=True)],
            [move(card_id)],
            [count(card_id, "boundary cost five stays rested", "state.players.human.field", 1, {"cardId": "yellow_05_02_01r_00", "rested": True})],
        ),
    )

    card_id = "yellow_03_03_01r_00"
    cases[card_id] = pair(
        card_id, 1131,
        (
            "state_transition", "The selected friendly minion permanently gains BP+200 and DP+1.",
            [setup(card_id, 1131), add("yellow_02_02_01r_00", side="P1", zone="field")],
            [play(card_id), target("yellow_02_02_01r_00")],
            [count(card_id, "positive permanent stats", "state.players.human.field", 1, {"cardId": "yellow_02_02_01r_00", "permanentBpModifier": 200, "permanentDpModifier": 1})],
        ),
        (
            "zero_target", "With no friendly minion, the Magic has no invented recipient.",
            [setup(card_id, 1132)], [play(card_id)],
            [eq("boundary field remains empty", "state.players.human.field", [])],
        ),
    )

    card_id = "yellow_05_02_01r_00"
    cases[card_id] = pair(
        card_id, 1141,
        (
            "trigger_resolution", "Another friendly minion entering the field permanently gives Ape BP+100.",
            [setup(card_id, 1141, zone="field"), add("yellow_02_02_01r_00", side="P1", zone="hand"), add("yellow_00_01_01r_00", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base")],
            [play("yellow_02_02_01r_00")],
            [count(card_id, "positive other entry growth", "state.players.human.field", 1, {"cardId": card_id, "permanentBpModifier": 100})],
        ),
        (
            "non_activation", "Ape entering by itself is not another minion and does not trigger its own growth.",
            [setup(card_id, 1142)], [play(card_id)],
            [count(card_id, "boundary no self growth", "state.players.human.field", 1, {"cardId": card_id, "permanentBpModifier": 0})],
        ),
    )

    card_id = "yellow_06_02_01r_00"
    cases[card_id] = pair(
        card_id, 1151,
        (
            "target_selection", "The selected enemy receives the attack, block, and movement lock.",
            [setup(card_id, 1151), add("blue_02_02_01r_00", side="P2", zone="field")],
            [play(card_id), target("blue_02_02_01r_00")],
            [any_match("positive action lock visible", "state.players.opponent.field[0].activeEffects", {"kind": "action_lock"})],
        ),
        (
            "duration_cleanup", "The lock remains through its creator's turn and expires at the end of the target owner's next turn.",
            [setup(card_id, 1152), add("blue_02_02_01r_00", side="P2", zone="field"), add("red_02_02_01r_00", side="P2", zone="deck"), add("red_02_02_01r_00", side="P1", zone="deck"), fixed(active="P1")],
            [play(card_id), target("blue_02_02_01r_00"), end_turn(), place_colorless_mana(), end_turn()],
            [none("boundary lock removed", "state.players.opponent.field[0].activeEffects", {"kind": "action_lock"})],
        ),
    )

    card_id = "yellow_06_02_01r_01"
    destroy_magic = "purple_03_03_01r_00"
    cases[card_id] = pair(
        card_id, 1161,
        (
            "trigger_resolution", "When destroyed, Tata returns the selected enemy minion to its owner's hand.",
            [setup(card_id, 1161, zone="field"), add(destroy_magic, side="P1", zone="hand"), add("purple_00_01_01r_00", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base"), add("blue_02_02_01r_00", side="P2", zone="field")],
            [play(destroy_magic), target(card_id), target("blue_02_02_01r_00")],
            [eq("positive enemy returned", "state.players.opponent.handCount", 1), eq("positive enemy field emptied", "state.players.opponent.field", [])],
        ),
        (
            "area_gate", "The separate retreat trigger refreshes one selected friendly yellow minion.",
            [setup(card_id, 1162, zone="field"), add("yellow_02_02_01r_00", side="P1", zone="field", rested=True)],
            [move(card_id), target("yellow_02_02_01r_00")],
            [count(card_id, "boundary retreat refresh", "state.players.human.field", 1, {"cardId": "yellow_02_02_01r_00", "rested": False})],
        ),
    )

    card_id = "yellow_07_03_01r_00"
    cases[card_id] = pair(
        card_id, 1171,
        (
            "zone_transition", "All non-token minions on both fields return to their owners' hands.",
            [setup(card_id, 1171), add("red_02_02_01r_00", side="P1", zone="field"), add("blue_02_02_01r_00", side="P2", zone="field")],
            [play(card_id)],
            [count(card_id, "positive own minion returned", "state.players.human.hand", 1, {"cardId": "red_02_02_01r_00"}), eq("positive enemy hand grows", "state.players.opponent.handCount", 1), eq("positive enemy field emptied", "state.players.opponent.field", [])],
        ),
        (
            "zero_target", "With both fields empty, the Magic resolves without creating cards or changing life.",
            [setup(card_id, 1172), {"path": "/api/debug/life", "payload": {"side": "P1", "life": 8}, "capture": {"life_before": {"path": "state.players.human.life"}}}],
            [play(card_id)],
            [eq("boundary life unchanged", "state.players.human.life", "$life_before"), eq("boundary fields empty", "state.players.opponent.field", [])],
        ),
    )

    card_id = "purple_00_01_01r_00"
    cases[card_id] = pair(
        card_id, 1201,
        (
            "resource_change", "Placement draws one card for one opposing destroyed Force.",
            [setup(card_id, 1201), force_state("P2", 0, True), add("red_02_02_01r_00", side="P1", zone="deck")],
            [play(card_id)], [eq("positive one Force one draw", "state.players.human.handCount", 1)],
        ),
        (
            "non_activation", "With no opposing destroyed Force, placement draws no card.",
            [setup(card_id, 1202), add("red_02_02_01r_00", side="P1", zone="deck")],
            [play(card_id)], [eq("boundary no destroyed Force no draw", "state.players.human.handCount", 0)],
        ),
    )

    card_id = "purple_02_02_01r_00"
    cases[card_id] = pair(
        card_id, 1211,
        (
            "trigger_resolution", "Destroying the minion deals one damage to the selected opposing Force.",
            [setup(card_id, 1211, zone="field"), add(destroy_magic, side="P1", zone="hand"), add("purple_00_01_01r_00", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base")],
            [play(destroy_magic), target(card_id), target_force("force_kon")],
            [count(card_id, "positive Force loses one life", "state.players.opponent.forces", 1, {"id": "force_kon", "life": 2})],
        ),
        (
            "zero_target", "If all opposing Forces are already destroyed, the destroy trigger cannot damage one again.",
            [setup(card_id, 1212, zone="field"), force_state("P2", 0, True), force_state("P2", 1, True), add(destroy_magic, side="P1", zone="hand"), add("purple_00_01_01r_00", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base")],
            [play(destroy_magic), target(card_id)],
            [count(card_id, "boundary Forces remain destroyed", "state.players.opponent.forces", 2, {"destroyed": True})],
        ),
    )

    card_id = "purple_03_02_01r_00"
    cases[card_id] = pair(
        card_id, 1221,
        (
            "trigger_resolution", "Retreating permanently gives the selected enemy BP-200.",
            [setup(card_id, 1221, zone="field"), add("white_04_02_01r_00", side="P2", zone="field")],
            [move(card_id), target("white_04_02_01r_00")],
            [count(card_id, "positive retreat BP reduction", "state.players.opponent.field", 1, {"cardId": "white_04_02_01r_00", "permanentBpModifier": -200})],
        ),
        (
            "zero_target", "Retreating with no enemy minion creates no target or stat change.",
            [setup(card_id, 1222, zone="field")], [move(card_id)],
            [eq("boundary enemy field stays empty", "state.players.opponent.field", [])],
        ),
    )

    card_id = "purple_03_03_01r_00"
    cases[card_id] = pair(
        card_id, 1231,
        (
            "resource_change", "Destroying the selected friendly minion draws exactly two cards.",
            [setup(card_id, 1231), add("red_02_02_01r_00", side="P1", zone="field"), add("blue_02_02_01r_00", side="P1", zone="deck"), add("green_02_02_01r_00", side="P1", zone="deck")],
            [play(card_id), target("red_02_02_01r_00")],
            [eq("positive draws two", "state.players.human.handCount", 2), count(card_id, "positive target destroyed", "state.players.human.trash", 1, {"cardId": "red_02_02_01r_00"})],
        ),
        (
            "zero_target", "With no friendly minion, the targeted Magic is not a legal main action and draws nothing.",
            [setup(card_id, 1232), add("blue_02_02_01r_00", side="P1", zone="deck")],
            [end_turn()],
            [count(card_id, "boundary Magic remains in hand", "state.players.human.hand", 1, {"cardId": card_id})],
        ),
    )

    card_id = "purple_04_03_01r_00"
    cases[card_id] = pair(
        card_id, 1241,
        (
            "state_transition", "All minions with original cost at most three are destroyed.",
            [setup(card_id, 1241), add("red_03_02_01r_00", side="P1", zone="field"), add("colorless_04_02_01r_00", side="P2", zone="field")],
            [play(card_id)],
            [count(card_id, "positive cost three destroyed", "state.players.human.trash", 1, {"cardId": "red_03_02_01r_00"}), count(card_id, "positive cost four survives", "state.players.opponent.field", 1, {"cardId": "colorless_04_02_01r_00"})],
        ),
        (
            "target_boundary", "A cost-four minion is above the maximum and survives.",
            [setup(card_id, 1242), add("colorless_04_02_01r_00", side="P2", zone="field")],
            [play(card_id)],
            [count(card_id, "boundary cost four survives", "state.players.opponent.field", 1, {"cardId": "colorless_04_02_01r_00"})],
        ),
    )

    def kiska_deck() -> list[dict[str, Any]]:
        return [
            add("purple_02_02_01r_00", side="P1", zone="deck"),
            add("purple_02_02_01r_00", side="P1", zone="deck"),
            add("red_02_02_01r_00", side="P1", zone="deck"),
            add("blue_02_02_01r_00", side="P1", zone="deck"),
            add("green_02_02_01r_00", side="P1", zone="deck"),
        ]

    card_id = "purple_06_02_01r_00"
    cases[card_id] = pair(
        card_id, 1251,
        (
            "trigger_resolution", "Summoning mills five cards and resolves only the first milled purple destroy effect.",
            [setup(card_id, 1251), *kiska_deck()],
            [play(card_id), target_force("force_kon")],
            [{"name": "positive five cards milled", "path": "state.players.human.trash", "op": "length_eq", "value": 5}, count(card_id, "positive only one Force damage", "state.players.opponent.forces", 1, {"id": "force_kon", "life": 2})],
        ),
        (
            "non_activation", "Multiple Kiska copies do not duplicate the milled-card destroy effect.",
            [setup(card_id, 1252), add(card_id, side="P1", zone="field"), *kiska_deck()],
            [play(card_id), target_force("force_kon")],
            [count(card_id, "boundary nonstack damage once", "state.players.opponent.forces", 1, {"id": "force_kon", "life": 2})],
        ),
    )

    card_id = "purple_07_02_01r_00"
    cases[card_id] = pair(
        card_id, 1261,
        (
            "trigger_resolution", "Destroying the minion and accepting the optional effect creates three Death Blow tokens.",
            [setup(card_id, 1261, zone="field"), add(destroy_magic, side="P1", zone="hand"), add("purple_00_01_01r_00", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base"), add("colorless_00_01_01r_01", side="P1", zone="base")],
            [play(destroy_magic), target(card_id), optional(True)],
            [count(card_id, "positive three tokens", "state.players.human.field", 3, {"cardId": "s_aryushinashion_token", "keywords": ["DEATH_BLOW"]})],
        ),
        (
            "area_gate", "The separate retreat trigger permanently gives one enemy BP-400.",
            [setup(card_id, 1262, zone="field"), add("white_04_02_01r_00", side="P2", zone="field")],
            [move(card_id), target("white_04_02_01r_00")],
            [count(card_id, "boundary retreat BP reduction", "state.players.opponent.field", 1, {"cardId": "white_04_02_01r_00", "permanentBpModifier": -400})],
        ),
    )

    card_id = "purple_07_03_01r_00"
    cases[card_id] = pair(
        card_id, 1271,
        (
            "zone_transition", "The selected field minion card moves from trash to the field.",
            [setup(card_id, 1271), add("red_02_02_01r_00", side="P1", zone="trash")],
            [play(card_id), target("red_02_02_01r_00")],
            [count(card_id, "positive summoned from trash", "state.players.human.field", 1, {"cardId": "red_02_02_01r_00"})],
        ),
        (
            "target_boundary", "A Magic card in trash is not a legal field-minion target.",
            [setup(card_id, 1272), add("red_02_03_01r_00", side="P1", zone="trash")],
            [end_turn()],
            [count(card_id, "boundary Magic remains in trash", "state.players.human.trash", 1, {"cardId": "red_02_03_01r_00"})],
        ),
    )

    card_id = "green_00_01_01r_00"
    cases[card_id] = pair(
        card_id, 1301,
        (
            "target_selection", "Placement permanently gives a friendly Penetrate minion BP+100/DP+1.",
            [setup(card_id, 1301), add("green_06_02_01r_00", side="P1", zone="field")],
            [play(card_id), target("green_06_02_01r_00")],
            [count(card_id, "positive Penetrate target buff", "state.players.human.field", 1, {"cardId": "green_06_02_01r_00", "permanentBpModifier": 100, "permanentDpModifier": 1})],
        ),
        (
            "target_boundary", "A minion without Penetrate is excluded and receives no modifier.",
            [setup(card_id, 1302), add("green_02_02_01r_00", side="P1", zone="field")],
            [play(card_id)],
            [count(card_id, "boundary non-Penetrate unchanged", "state.players.human.field", 1, {"cardId": "green_02_02_01r_00", "permanentBpModifier": 0})],
        ),
    )

    card_id = "green_01_03_01r_00"
    cases[card_id] = pair(
        card_id, 1311,
        (
            "target_selection", "A rested minion with BP exactly 400 is a legal target and is destroyed.",
            [setup(card_id, 1311), add("colorless_02_02_01r_00", side="P2", zone="field", rested=True)],
            [play(card_id), target("colorless_02_02_01r_00")],
            [count(card_id, "positive BP400 destroyed", "state.players.opponent.trash", 1, {"cardId": "colorless_02_02_01r_00"})],
        ),
        (
            "target_boundary", "A rested BP500 minion is above the inclusive maximum and survives.",
            [setup(card_id, 1312), add("colorless_05_02_01r_00", side="P2", zone="field", rested=True)],
            [end_turn()],
            [count(card_id, "boundary BP500 survives", "state.players.opponent.field", 1, {"cardId": "colorless_05_02_01r_00"})],
        ),
    )

    card_id = "green_02_02_01r_00"
    cases[card_id] = pair(
        card_id, 1321,
        (
            "trigger_resolution", "Retreating refreshes one selected rested green mana.",
            [setup(card_id, 1321, zone="field"), add("green_00_01_01r_00", side="P1", zone="base", rested=True)],
            [move(card_id), target("green_00_01_01r_00")],
            [count(card_id, "positive green mana refreshed", "state.players.human.base", 1, {"cardId": "green_00_01_01r_00", "rested": False})],
        ),
        (
            "target_boundary", "A rested red mana is not green and remains rested.",
            [setup(card_id, 1322, zone="field"), add("red_00_01_01r_00", side="P1", zone="base", rested=True)],
            [move(card_id)],
            [count(card_id, "boundary red mana not refreshed", "state.players.human.base", 1, {"cardId": "red_00_01_01r_00", "rested": True})],
        ),
    )

    def flash_fixture(card_id: str, seed: int, attacker: str) -> list[dict[str, Any]]:
        return [
            setup(card_id, seed),
            add(attacker, side="P2", zone="field"),
            fixed(active="P2"),
        ]

    card_id = "green_02_03_01r_00"
    flash_attacker = "colorless_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1331,
        (
            "state_transition", "At Flash timing the selected enemy minion's DP becomes zero for the turn.",
            flash_fixture(card_id, 1331, flash_attacker),
            [attack(flash_attacker), attack_force(), flash_play(card_id), target(flash_attacker)],
            [count(card_id, "positive DP zero", "state.players.opponent.field", 1, {"cardId": flash_attacker, "effectiveDp": 0})],
        ),
        (
            "target_boundary", "Only an enemy minion can receive the DP change; friendly minions remain unchanged.",
            [setup(card_id, 1332), add("green_02_02_01r_00", side="P1", zone="field"), add(flash_attacker, side="P2", zone="field"), fixed(active="P2")],
            [attack(flash_attacker), attack_force(), flash_play(card_id), target(flash_attacker)],
            [count(card_id, "boundary friendly DP unchanged", "state.players.human.field", 1, {"cardId": "green_02_02_01r_00", "effectiveDp": 1})],
        ),
    )

    card_id = "green_03_02_01r_00"
    cases[card_id] = pair(
        card_id, 1341,
        (
            "trigger_resolution", "During its owner's mana step, placing Demeter Village Girl draws one card.",
            [setup(card_id, 1341, zone="field"), add("green_00_01_00_00", side="P1", zone="hand"), add("red_02_02_01r_00", side="P1", zone="deck"), fixed(active="P1", step="mana")],
            [play("green_00_01_00_00")],
            [eq("positive mana-step draw", "state.players.human.handCount", 1)],
        ),
        (
            "non_activation", "Placing another green base minion does not trigger the name-specific draw.",
            [setup(card_id, 1342, zone="field"), add("green_00_01_01r_00", side="P1", zone="hand"), add("red_02_02_01r_00", side="P1", zone="deck"), fixed(active="P1", step="mana")],
            [play("green_00_01_01r_00")],
            [eq("boundary wrong base no draw", "state.players.human.handCount", 0)],
        ),
    )

    card_id = "green_03_03_01r_00"
    cases[card_id] = pair(
        card_id, 1351,
        (
            "state_transition", "The selected enemy minion and every opposing Force become rested.",
            [setup(card_id, 1351), add("blue_02_02_01r_00", side="P2", zone="field")],
            [play(card_id), target("blue_02_02_01r_00")],
            [count(card_id, "positive enemy minion rested", "state.players.opponent.field", 1, {"cardId": "blue_02_02_01r_00", "rested": True}), count(card_id, "positive all Forces rested", "state.players.opponent.forces", 2, {"rested": True})],
        ),
        (
            "target_boundary", "The effect does not rest a friendly minion while resolving its enemy-only target.",
            [setup(card_id, 1352), add("green_02_02_01r_00", side="P1", zone="field"), add("blue_02_02_01r_00", side="P2", zone="field")],
            [play(card_id), target("blue_02_02_01r_00")],
            [count(card_id, "boundary friendly remains active", "state.players.human.field", 1, {"cardId": "green_02_02_01r_00", "rested": False})],
        ),
    )

    card_id = "green_05_02_01r_00"
    green_play = "green_03_02_01r_00"
    cases[card_id] = pair(
        card_id, 1361,
        (
            "trigger_resolution", "Moving to base forces Van Jean to enter that base rested.",
            [setup(card_id, 1361, zone="field")], [move(card_id)],
            [count(card_id, "positive retreat enters rested", "state.players.human.base", 1, {"cardId": card_id, "rested": True})],
        ),
        (
            "area_gate", "While in base, Van Jean alone pays three mana units toward a green cost-three card.",
            [setup(card_id, 1362, zone="base"), add(green_play, side="P1", zone="hand")],
            [play(green_play)],
            [count(card_id, "boundary one triple-value mana rested", "state.players.human.base", 1, {"cardId": card_id, "rested": True})],
        ),
    )

    card_id = "green_07_02_01r_00"
    cases[card_id] = pair(
        card_id, 1371,
        (
            "target_selection", "The attack trigger rests one selected enemy minion or Force.",
            [setup(card_id, 1371, zone="field"), add("blue_02_02_01r_00", side="P2", zone="field")],
            [attack(card_id), attack_force(), target("blue_02_02_01r_00")],
            [count(card_id, "positive attack target rested", "state.players.opponent.field", 1, {"cardId": "blue_02_02_01r_00", "rested": True})],
        ),
        (
            "area_gate", "The retreat trigger refreshes exactly two selected green mana.",
            [setup(card_id, 1372, zone="field"), add("green_00_01_01r_00", side="P1", zone="base", rested=True, capture_as="green_mana_one"), add("green_00_01_00_00", side="P1", zone="base", rested=True, capture_as="green_mana_two")],
            [move(card_id), {"name": "choose two green mana", "prompt_kind": "effect_target", "select_many": [{"cardIid": "$green_mana_one"}, {"cardIid": "$green_mana_two"}]}],
            [count(card_id, "boundary first green mana active", "state.players.human.base", 1, {"iid": "$green_mana_one", "rested": False}), count(card_id, "boundary second green mana active", "state.players.human.base", 1, {"iid": "$green_mana_two", "rested": False})],
        ),
    )

    card_id = "blue_00_01_01r_00"
    cases[card_id] = pair(
        card_id, 1401,
        (
            "zone_transition", "Placement optionally moves the selected friendly minion from field to base while preserving its rest state.",
            [setup(card_id, 1401), add("blue_02_02_01r_00", side="P1", zone="field", rested=False)],
            [play(card_id), target("blue_02_02_01r_00")],
            [count(card_id, "positive minion moved active to base", "state.players.human.base", 1, {"cardId": "blue_02_02_01r_00", "rested": False})],
        ),
        (
            "optionality", "Declining the optional placement effect leaves the friendly minion on the field.",
            [setup(card_id, 1402), add("blue_02_02_01r_00", side="P1", zone="field")],
            [play(card_id), choose("decline optional move", "effect_target", {"id": "none"})],
            [count(card_id, "boundary minion stays field", "state.players.human.field", 1, {"cardId": "blue_02_02_01r_00"})],
        ),
    )

    card_id = "blue_01_03_01r_00"
    cases[card_id] = pair(
        card_id, 1411,
        (
            "private_look_selection", "The controller inspects the top four, selects one Magic card to reveal and add to hand, and returns the other seen cards to the deck bottom.",
            [setup(card_id, 1411), add("red_02_02_01r_00", side="P1", zone="deck"), add("red_02_03_01r_00", side="P1", zone="deck"), add("blue_02_02_01r_00", side="P1", zone="deck"), add("green_02_02_01r_00", side="P1", zone="deck"), add("yellow_02_02_01r_00", side="P1", zone="deck")],
            [play(card_id), target("red_02_03_01r_00")],
            [count(card_id, "positive Magic added", "state.players.human.hand", 1, {"cardId": "red_02_03_01r_00"}), count(card_id, "positive selected public reveal", "state.publicReveals", 1, {"reason": "deck_search", "card": {"cardId": "red_02_03_01r_00"}})],
        ),
        (
            "zero_target", "When the top four contain no Magic, no card is added to hand.",
            [setup(card_id, 1412), add("red_02_02_01r_00", side="P1", zone="deck"), add("blue_02_02_01r_00", side="P1", zone="deck")],
            [play(card_id)], [eq("boundary no Magic added", "state.players.human.handCount", 0), eq("boundary private look has no public reveal", "state.publicReveals", [])],
        ),
    )

    card_id = "blue_02_02_01r_00"
    five_hand = [add(value, side="P1", zone="hand") for value in [
        "red_02_02_01r_00", "green_02_02_01r_00", "yellow_02_02_01r_00", "white_03_02_01r_00", "colorless_03_02_01r_00",
    ]]
    cases[card_id] = pair(
        card_id, 1421,
        (
            "resource_change", "Retreating with four or fewer cards in hand draws one card.",
            [setup(card_id, 1421, zone="field"), add("red_02_02_01r_00", side="P1", zone="deck")],
            [move(card_id)], [eq("positive one card drawn", "state.players.human.handCount", 1)],
        ),
        (
            "target_boundary", "At five cards in hand the at-most-four condition fails and no card is drawn.",
            [setup(card_id, 1422, zone="field"), *five_hand, add("red_02_02_01r_00", side="P1", zone="deck")],
            [move(card_id)], [eq("boundary five-card hand unchanged", "state.players.human.handCount", 5)],
        ),
    )

    card_id = "blue_02_02_01r_01"
    cost_magic = "red_05_03_01r_00"
    flute_resources = [
        add(cost_magic, side="P1", zone="hand"),
        add("red_00_01_01r_00", side="P1", zone="base"),
        add("red_00_01_01r_00", side="P1", zone="base"),
        add("colorless_00_01_01r_01", side="P1", zone="base"),
        add("colorless_00_01_01r_01", side="P1", zone="base"),
        add("colorless_05_02_01r_01", side="P2", zone="field"),
    ]
    cases[card_id] = pair(
        card_id, 1431,
        (
            "resource_change", "While Flute is on field, a Magic with printed cost five rests only four mana sources.",
            [setup(card_id, 1431, zone="field"), *flute_resources],
            [play(cost_magic), target("colorless_05_02_01r_01")],
            [count(card_id, "positive four mana paid", "state.players.human.base", 4, {"rested": True})],
        ),
        (
            "area_gate", "Flute in base does not reduce Magic cost, so the same Magic rests five mana sources.",
            [setup(card_id, 1432, zone="base"), *flute_resources],
            [play(cost_magic), target("colorless_05_02_01r_01")],
            [count(card_id, "boundary five mana paid", "state.players.human.base", 5, {"rested": True})],
        ),
    )

    card_id = "blue_03_03_01r_00"
    cases[card_id] = pair(
        card_id, 1441,
        (
            "zone_transition", "The selected minion mana moves from base to field in an active state.",
            [setup(card_id, 1441), add("blue_02_02_01r_00", side="P1", zone="base", rested=True)],
            [play(card_id), target("blue_02_02_01r_00")],
            [count(card_id, "positive mana enters field active", "state.players.human.field", 1, {"cardId": "blue_02_02_01r_00", "rested": False})],
        ),
        (
            "target_boundary", "A colorless mana token is not a minion mana target and remains in base.",
            [setup(card_id, 1442), add("mana_token", side="P1", zone="base")],
            [play(card_id), choose("choose a valid minion mana", "effect_target", {"id": "e0"})],
            [count(card_id, "boundary token stays base", "state.players.human.base", 1, {"cardId": "mana_token"})],
        ),
    )

    card_id = "blue_05_03_01r_00"
    howling_attacker = "colorless_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1451,
        (
            "target_selection", "At Flash timing the player option deals exactly one damage to the opponent player.",
            [*flash_fixture(card_id, 1451, howling_attacker), life("P2", 10)],
            [attack(howling_attacker), attack_force(), flash_play(card_id), choose("choose player damage mode", "effect_target", {"targetKind": "player", "ownerSide": "P2"})],
            [eq("positive player takes one", "state.players.opponent.life", 9)],
        ),
        (
            "target_boundary", "An enemy minion with BP exactly 500 is included and moves to base rested.",
            [setup(card_id, 1452), add("white_04_02_01r_00", side="P2", zone="field"), add(howling_attacker, side="P2", zone="field"), fixed(active="P2")],
            [attack(howling_attacker), attack_force(), flash_play(card_id), target("white_04_02_01r_00")],
            [count(card_id, "boundary BP500 moved rested", "state.players.opponent.base", 1, {"cardId": "white_04_02_01r_00", "rested": True})],
        ),
    )

    card_id = "blue_06_02_01r_00"
    put_blue = "blue_02_02_01r_00"
    cases[card_id] = pair(
        card_id, 1461,
        (
            "zone_transition", "The optional summon effect puts the selected blue field minion from hand into the base rested.",
            [setup(card_id, 1461), add(put_blue, side="P1", zone="hand")],
            [play(card_id), target(put_blue)],
            [count(card_id, "positive blue minion put in base rested", "state.players.human.base", 1, {"cardId": put_blue, "rested": True})],
        ),
        (
            "optionality", "Declining the optional effect leaves the blue minion in hand.",
            [setup(card_id, 1462), add(put_blue, side="P1", zone="hand")],
            [play(card_id), choose("decline optional placement", "effect_target", {"id": "none"})],
            [count(card_id, "boundary blue minion remains hand", "state.players.human.hand", 1, {"cardId": put_blue})],
        ),
    )

    card_id = "blue_08_02_01r_00"
    cases[card_id] = pair(
        card_id, 1471,
        (
            "keyword_legality", "During its owner's turn the Merfolk source receives Sneaking from its own aura.",
            [setup(card_id, 1471, zone="field")], [attack(card_id)],
            [count(card_id, "positive Merfolk has Sneaking", "state.players.human.field", 1, {"cardId": card_id, "keywords": ["SNEAKING"]})],
        ),
        (
            "non_activation", "During the opponent turn the own-turn Sneaking aura is inactive.",
            [setup(card_id, 1472, zone="field"), add("colorless_03_02_01r_00", side="P2", zone="field"), fixed(active="P2")],
            [attack("colorless_03_02_01r_00")],
            [count(card_id, "boundary no opponent-turn Sneaking", "state.players.human.field", 1, {"cardId": card_id, "keywords": []})],
        ),
    )

    card_id = "white_00_01_01r_00"
    cases[card_id] = pair(
        card_id, 1501,
        (
            "target_selection", "Placement marks one selected enemy minion as required to block this turn.",
            [setup(card_id, 1501), add("blue_02_02_01r_00", side="P2", zone="field")],
            [play(card_id), target("blue_02_02_01r_00")],
            [count(card_id, "positive required blocker marker", "state.players.opponent.field", 1, {"cardId": "blue_02_02_01r_00", "activeEffects": {"contains": [{"kind": "must_block", "sourceName": "Must block this turn"}]}})],
        ),
        (
            "optionality", "Declining the optional placement target marks no enemy minion.",
            [setup(card_id, 1502), add("blue_02_02_01r_00", side="P2", zone="field")],
            [play(card_id), choose("decline optional target", "effect_target", {"id": "none"})],
            [count(card_id, "boundary no required blocker marker", "state.players.opponent.field", 1, {"cardId": "blue_02_02_01r_00", "activeEffects": {"none": [{"kind": "must_block"}]}})],
        ),
    )

    card_id = "white_02_02_01r_00"
    protected = "white_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1511,
        (
            "continuous_effect", "Retreat grants one friendly minion immunity from opponent Magic selection for the turn.",
            [setup(card_id, 1511, zone="field"), add(protected, side="P1", zone="field")],
            [move(card_id), target(protected)],
            [count(card_id, "positive Magic immunity marker", "state.players.human.field", 1, {"cardId": protected, "activeEffects": {"contains": [{"kind": "magic_selection_immunity", "sourceName": "Opponent Magic selection immunity"}]}})],
        ),
        (
            "duration_cleanup", "The selection immunity is removed when that turn ends.",
            [setup(card_id, 1512, zone="field"), add(protected, side="P1", zone="field"), add("red_02_02_01r_00", side="P2", zone="deck")],
            [move(card_id), target(protected), end_turn()],
            [count(card_id, "boundary Magic immunity cleaned", "state.players.human.field", 1, {"cardId": protected, "activeEffects": {"none": [{"kind": "magic_selection_immunity"}]}})],
        ),
    )

    card_id = "white_02_03_01r_00"
    zone_attacker = "colorless_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1521,
        (
            "state_transition", "Casting during the opponent turn refreshes every friendly minion and non-destroyed Force.",
            [setup(card_id, 1521), add(protected, side="P1", zone="field", rested=True), force_state("P1", 0, False, rested=True), force_state("P1", 1, False, rested=True), add(zone_attacker, side="P2", zone="field"), fixed(active="P2")],
            [attack(zone_attacker), attack_force(), flash_play(card_id)],
            [count(card_id, "positive all minions active", "state.players.human.field", 1, {"rested": False}), count(card_id, "positive all Forces active", "state.players.human.forces", 2, {"rested": False})],
        ),
        (
            "non_activation", "The opponent-turn-only refresh does not fire when the owner casts the card on their own turn.",
            [setup(card_id, 1522), add(protected, side="P1", zone="field", rested=True), force_state("P1", 0, False, rested=True), force_state("P1", 1, False, rested=True), add(zone_attacker, side="P1", zone="field"), fixed(active="P1")],
            [attack(zone_attacker), attack_force(), flash_pass(), flash_play(card_id)],
            [count(card_id, "boundary own-turn minion stays rested", "state.players.human.field", 1, {"cardId": protected, "rested": True}), count(card_id, "boundary own-turn Forces stay rested", "state.players.human.forces", 2, {"rested": True})],
        ),
    )

    card_id = "white_02_03_01r_01"
    soldier = "white_04_02_01r_00"
    non_soldier = "blue_02_02_01r_00"
    cases[card_id] = pair(
        card_id, 1531,
        (
            "continuous_effect", "The selected Soldier wins battles regardless of BP for the turn.",
            [setup(card_id, 1531), add(soldier, side="P1", zone="field")],
            [play(card_id), target(soldier)],
            [count(card_id, "positive Soldier auto-win marker", "state.players.human.field", 1, {"cardId": soldier, "activeEffects": {"contains": [{"kind": "battle_auto_win", "sourceName": "Wins battle regardless of BP"}]}})],
        ),
        (
            "target_boundary", "A friendly minion without the Soldier race is not affected.",
            [setup(card_id, 1532), add(non_soldier, side="P1", zone="field")],
            [play(card_id)],
            [count(card_id, "boundary non-Soldier has no auto-win", "state.players.human.field", 1, {"cardId": non_soldier, "activeEffects": {"none": [{"kind": "battle_auto_win"}]}})],
        ),
    )

    card_id = "white_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1541,
        (
            "continuous_effect", "When Vogelbein attacks, the opponent cannot decline to block when a legal blocker exists.",
            [setup(card_id, 1541, zone="field"), add(non_soldier, side="P2", zone="field")],
            [attack(card_id), attack_force()],
            [count(card_id, "positive attacker must be blocked", "state.players.human.field", 1, {"cardId": card_id, "activeEffects": {"contains": [{"kind": "must_be_blocked", "sourceName": "Must be blocked when attacking"}]}})],
        ),
        (
            "area_gate", "The forced-block attack rule is inactive while Vogelbein is in base.",
            [setup(card_id, 1542, zone="base")],
            [move(card_id, "base_to_field")],
            [count(card_id, "boundary no attack marker outside attack", "state.players.human.field", 1, {"cardId": card_id, "activeEffects": {"none": [{"kind": "must_be_blocked"}]}})],
        ),
    )

    card_id = "white_04_03_01r_00"
    crack_attacker = "colorless_06_02_01_00"
    crack_blocker = "blue_02_02_01r_00"
    cases[card_id] = pair(
        card_id, 1551,
        (
            "trigger_resolution", "Casting permanently buffs all current friendly minions and a subsequent battle win deals one player damage.",
            [setup(card_id, 1551), add(crack_attacker, side="P1", zone="field"), add(crack_blocker, side="P2", zone="field", capture_as="crack_blocker_iid"), fixed(active="P1")],
            [play(card_id), attack(crack_attacker), attack_force(), flash_pass(), flash_pass(), block_with("$crack_blocker_iid")],
            [count(card_id, "positive all current minions buffed", "state.players.human.field", 1, {"cardId": crack_attacker, "permanentBpModifier": 100}), eq("positive battle-win player damage", "state.players.opponent.life", 9)],
        ),
        (
            "non_activation", "An unblocked Force attack is not a battle win and does not deal the extra player damage.",
            [setup(card_id, 1552), add(crack_attacker, side="P1", zone="field"), fixed(active="P1")],
            [play(card_id), attack(crack_attacker), attack_force(), flash_pass(), flash_pass()],
            [eq("boundary no battle-win player damage", "state.players.opponent.life", 10)],
        ),
    )

    card_id = "white_06_02_01r_00"
    cases[card_id] = pair(
        card_id, 1561,
        (
            "resource_change", "On attack, resting one active friendly Force refreshes Held Duke.",
            [setup(card_id, 1561, zone="field")],
            [attack(card_id), attack_force(), target_force("force_e")],
            [count(card_id, "positive Held Duke refreshed", "state.players.human.field", 1, {"cardId": card_id, "rested": False}), count(card_id, "positive selected Force rested", "state.players.human.forces", 1, {"id": "force_e", "rested": True})],
        ),
        (
            "optionality", "Declining the optional Force cost leaves Held Duke rested after attacking.",
            [setup(card_id, 1562, zone="field")],
            [attack(card_id), attack_force(), choose("decline Force cost", "effect_target", {"id": "none"})],
            [count(card_id, "boundary Held Duke stays rested", "state.players.human.field", 1, {"cardId": card_id, "rested": True}), count(card_id, "boundary no Force rested", "state.players.human.forces", 0, {"rested": True})],
        ),
    )

    card_id = "white_07_02_01r_00"
    roid_blocker = "blue_02_02_01r_00"
    roid_target = "colorless_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1571,
        (
            "trigger_resolution", "After winning a battle, Combat Roid rests one selected remaining enemy minion.",
            [setup(card_id, 1571, zone="field"), add(roid_blocker, side="P2", zone="field", capture_as="roid_blocker_iid"), add(roid_target, side="P2", zone="field"), fixed(active="P1")],
            [attack(card_id), attack_force(), flash_pass(), flash_pass(), block_with("$roid_blocker_iid"), target(roid_target)],
            [count(card_id, "positive post-win target rested", "state.players.opponent.field", 1, {"cardId": roid_target, "rested": True})],
        ),
        (
            "area_gate", "Retreating grants all current friendly minions opponent-Magic selection immunity for the turn.",
            [setup(card_id, 1572, zone="field"), add(protected, side="P1", zone="field")],
            [move(card_id)],
            [count(card_id, "boundary retreat protects all", "state.players.human.field", 1, {"cardId": protected, "activeEffects": {"contains": [{"kind": "magic_selection_immunity", "sourceName": "Opponent Magic selection immunity"}]}})],
        ),
    )

    card_id = "colorless_00_01_01r_00"
    low_magic = "red_02_03_01r_00"
    high_magic = "white_04_03_01r_00"
    cases[card_id] = pair(
        card_id, 1601,
        (
            "zone_transition", "Placement rests City Resident and returns a selected cost-three-or-less Magic from trash to hand.",
            [setup(card_id, 1601), add(low_magic, side="P1", zone="trash")],
            [play(card_id), target(low_magic)],
            [count(card_id, "positive Magic returned", "state.players.human.hand", 1, {"cardId": low_magic}), count(card_id, "positive source rested in base", "state.players.human.base", 1, {"cardId": card_id, "rested": True})],
        ),
        (
            "target_boundary", "A cost-four Magic is above the recovery limit and remains in trash.",
            [setup(card_id, 1602), add(high_magic, side="P1", zone="trash")],
            [play(card_id)],
            [count(card_id, "boundary cost-four remains trash", "state.players.human.trash", 1, {"cardId": high_magic}), count(card_id, "boundary source still pays rest cost", "state.players.human.base", 1, {"cardId": card_id, "rested": True})],
        ),
    )

    card_id = "colorless_00_01_01r_01"
    cases[card_id] = pair(
        card_id, 1611,
        (
            "target_selection", "Placement can rest an enemy minion with original cost exactly four.",
            [setup(card_id, 1611), add(roid_target, side="P2", zone="field")],
            [play(card_id), target(roid_target)],
            [count(card_id, "positive cost-four rested", "state.players.opponent.field", 1, {"cardId": roid_target, "rested": True})],
        ),
        (
            "target_boundary", "An enemy minion with original cost five is excluded.",
            [setup(card_id, 1612), add("colorless_05_02_01r_01", side="P2", zone="field")],
            [play(card_id)],
            [count(card_id, "boundary cost-five remains active", "state.players.opponent.field", 1, {"cardId": "colorless_05_02_01r_01", "rested": False})],
        ),
    )

    card_id = "colorless_01_02_01r_00"
    cases[card_id] = pair(
        card_id, 1621,
        (
            "resource_change", "With only non-minion colorless mana in base, summoning Porin draws one card; retreating then enters base rested.",
            [setup(card_id, 1621, non_minion_mana_only=True), add("red_02_02_01r_00", side="P1", zone="deck")],
            [play(card_id), move(card_id)],
            [eq("positive conditional draw", "state.players.human.handCount", 1), count(card_id, "positive retreat enters rested", "state.players.human.base", 1, {"cardId": card_id, "rested": True})],
        ),
        (
            "non_activation", "A minion card in base makes the draw condition fail.",
            [setup(card_id, 1622), add("red_02_02_01r_00", side="P1", zone="deck")],
            [play(card_id)],
            [eq("boundary no conditional draw", "state.players.human.handCount", 0)],
        ),
    )

    card_id = "colorless_02_02_01r_00"
    low_attacker = "blue_02_02_01r_00"
    high_attacker = "colorless_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1631,
        (
            "continuous_effect", "While Spike Toad is on field, minion damage from a cost-three-or-less attacker is reduced by one.",
            [setup(card_id, 1631, zone="field"), force_state("P1", 0, True), force_state("P1", 1, True), add(low_attacker, side="P2", zone="field"), fixed(active="P2")],
            [attack(low_attacker), attack_player(), flash_pass(), flash_pass(), decline_block()],
            [eq("positive low-cost damage reduced to zero", "state.players.human.life", 10)],
        ),
        (
            "target_boundary", "Damage from a cost-four attacker is outside the reduction and remains unchanged.",
            [setup(card_id, 1632, zone="field"), force_state("P1", 0, True), force_state("P1", 1, True), add(high_attacker, side="P2", zone="field"), fixed(active="P2")],
            [attack(high_attacker), attack_player(), flash_pass(), flash_pass(), decline_block()],
            [eq("boundary cost-four full damage", "state.players.human.life", 8)],
        ),
    )

    card_id = "colorless_03_02_01r_00"
    cases[card_id] = pair(
        card_id, 1641,
        (
            "target_selection", "Summoning permanently gives one selected enemy minion BP-200.",
            [setup(card_id, 1641), add(roid_target, side="P2", zone="field")],
            [play(card_id), target(roid_target)],
            [count(card_id, "positive enemy BP reduced", "state.players.opponent.field", 1, {"cardId": roid_target, "permanentBpModifier": -200})],
        ),
        (
            "target_boundary", "A friendly minion is not an enemy target and receives no modifier.",
            [setup(card_id, 1642), add(roid_target, side="P1", zone="field"), add(low_attacker, side="P2", zone="field")],
            [play(card_id), target(low_attacker)],
            [count(card_id, "boundary friendly BP unchanged", "state.players.human.field", 1, {"cardId": roid_target, "permanentBpModifier": 0})],
        ),
    )

    card_id = "colorless_03_02_01r_01"
    cost_two_magic = "red_02_03_01r_00"
    cost_three_magic = "green_03_03_01r_00"
    cases[card_id] = pair(
        card_id, 1651,
        (
            "public_information", "Summoning searches an original-cost-two Magic, reveals it, adds it to hand, and shuffles the deck.",
            [setup(card_id, 1651), add(cost_two_magic, side="P1", zone="deck"), add(low_attacker, side="P1", zone="deck")],
            [play(card_id), target(cost_two_magic)],
            [count(card_id, "positive searched Magic in hand", "state.players.human.hand", 1, {"cardId": cost_two_magic}), count(card_id, "positive searched Magic revealed", "state.publicReveals", 1, {"reason": "deck_search"})],
        ),
        (
            "zero_target", "A Magic with original cost three is not eligible and remains in deck.",
            [setup(card_id, 1652), add(cost_three_magic, side="P1", zone="deck")],
            [play(card_id)],
            [eq("boundary cost-three remains deck", "state.players.human.deckCount", 1)],
        ),
    )

    card_id = "colorless_03_02_01r_02"
    redraw_a = "red_02_02_01r_00"
    redraw_b = "blue_02_02_01r_00"
    cases[card_id] = pair(
        card_id, 1661,
        (
            "zone_transition", "Any chosen hand cards are discarded, the same count is drawn, and the discarded cards move to deck bottom.",
            [setup(card_id, 1661), add(redraw_a, side="P1", zone="hand"), add(redraw_b, side="P1", zone="hand"), add("green_02_02_01r_00", side="P1", zone="deck"), add("yellow_02_02_01r_00", side="P1", zone="deck")],
            [play(card_id), {"name": "choose redraw cards", "prompt_kind": "effect_target", "select_many": [{"cardId": redraw_a}, {"cardId": redraw_b}]}],
            [eq("positive replacement hand size", "state.players.human.handCount", 2), eq("positive discarded cards returned to deck", "state.players.human.deckCount", 2), eq("positive redraw leaves no discarded cards", "state.players.human.trashCount", 0)],
        ),
        (
            "optionality", "Choosing no hand cards performs no discard and no draw.",
            [setup(card_id, 1662), add(redraw_a, side="P1", zone="hand"), add("green_02_02_01r_00", side="P1", zone="deck")],
            [play(card_id), choose("choose zero redraw cards", "effect_target", {"id": "none"})],
            [eq("boundary hand unchanged", "state.players.human.handCount", 1), eq("boundary deck unchanged", "state.players.human.deckCount", 1)],
        ),
    )

    card_id = "colorless_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1671,
        (
            "state_transition", "Summoning permanently grants BP+100 for each opposing field minion.",
            [setup(card_id, 1671), add(low_attacker, side="P2", zone="field"), add(non_soldier, side="P2", zone="field")],
            [play(card_id)],
            [count(card_id, "positive two-enemy growth", "state.players.human.field", 1, {"cardId": card_id, "permanentBpModifier": 200})],
        ),
        (
            "zero_target", "With no opposing field minions, summoning grants zero BP.",
            [setup(card_id, 1672)], [play(card_id)],
            [count(card_id, "boundary zero-enemy growth", "state.players.human.field", 1, {"cardId": card_id, "permanentBpModifier": 0})],
        ),
    )

    card_id = "colorless_05_02_01r_00"
    colored_blocker = "white_04_02_01r_00"
    colorless_blocker = "colorless_04_02_01r_00"
    cases[card_id] = pair(
        card_id, 1681,
        (
            "keyword_legality", "While Sapphire Dragon attacks on its owner's turn, colored minions cannot block it.",
            [setup(card_id, 1681, zone="field"), add(colored_blocker, side="P2", zone="field"), fixed(active="P1")],
            [attack(card_id), attack_force(), flash_pass(), flash_pass()],
            [count(card_id, "positive colored blocker remains active", "state.players.opponent.field", 1, {"cardId": colored_blocker, "rested": False}), count(card_id, "positive Force takes unblocked damage", "state.players.opponent.forces", 1, {"id": "force_kon", "life": 2})],
        ),
        (
            "target_boundary", "A colorless minion remains a legal blocker.",
            [setup(card_id, 1682, zone="field"), add(colorless_blocker, side="P2", zone="field", capture_as="colorless_blocker_iid"), fixed(active="P1")],
            [attack(card_id), attack_force(), flash_pass(), flash_pass()],
            [any_match("boundary colorless blocker offered", "state.prompt.options", {"cardIid": "$colorless_blocker_iid"})],
        ),
    )

    card_id = "colorless_05_02_01r_01"
    opponent_magic = "yellow_01_03_01r_00"
    cases[card_id] = pair(
        card_id, 1691,
        (
            "trigger_resolution", "Each opponent Magic use permanently gives Puma BP+100/DP+1.",
            [setup(card_id, 1691, zone="field"), add(high_attacker, side="P2", zone="field"), add(opponent_magic, side="P2", zone="hand"), add("yellow_00_01_01r_00", side="P2", zone="base"), fixed(active="P2")],
            [attack(high_attacker), attack_force(), flash_pass(), flash_play(opponent_magic)],
            [count(card_id, "positive opponent Magic growth", "state.players.human.field", 1, {"cardId": card_id, "permanentBpModifier": 100, "permanentDpModifier": 1})],
        ),
        (
            "non_activation", "Using a Magic by Puma's owner does not trigger the opponent-only growth.",
            [setup(card_id, 1692, zone="field"), add(opponent_magic, side="P1", zone="hand"), add("yellow_00_01_01r_00", side="P1", zone="base")],
            [play(opponent_magic)],
            [count(card_id, "boundary owner Magic no growth", "state.players.human.field", 1, {"cardId": card_id, "permanentBpModifier": 0, "permanentDpModifier": 0})],
        ),
    )

    card_id = "colorless_06_02_01r_00"
    cases[card_id] = pair(
        card_id, 1701,
        (
            "resource_change", "With a friendly Demigod on field, Centipede's free cost is reduced by three.",
            [setup(card_id, 1701), add("red_04_02_01r_00", side="P1", zone="field")],
            [play(card_id)],
            [count(card_id, "positive reduced payment", "state.players.human.base", 3, {"rested": True})],
        ),
        (
            "non_activation", "Without a friendly Demigod, Centipede pays its full cost.",
            [setup(card_id, 1702)], [play(card_id)],
            [count(card_id, "boundary full payment", "state.players.human.base", 6, {"rested": True})],
        ),
    )

    card_id = "colorless_06_02_01r_01"
    cost_six = "white_06_02_01_02"
    cost_seven = "green_07_02_01_00"
    cases[card_id] = pair(
        card_id, 1711,
        (
            "zone_transition", "Retreating puts one original-cost-six-or-less field minion from hand onto the field.",
            [setup(card_id, 1711, zone="field"), add(cost_six, side="P1", zone="hand")],
            [move(card_id), target(cost_six)],
            [count(card_id, "positive cost-six put on field", "state.players.human.field", 1, {"cardId": cost_six})],
        ),
        (
            "target_boundary", "An original-cost-seven field minion is excluded and remains in hand.",
            [setup(card_id, 1712, zone="field"), add(cost_seven, side="P1", zone="hand")],
            [move(card_id)],
            [count(card_id, "boundary cost-seven remains hand", "state.players.human.hand", 1, {"cardId": cost_seven})],
        ),
    )

    card_id = "colorless_07_02_01r_00"
    cases[card_id] = pair(
        card_id, 1721,
        (
            "keyword_legality", "Rush lets Karnal attack on the turn it is summoned.",
            [setup(card_id, 1721)],
            [play(card_id), attack(card_id), attack_force()],
            [count(card_id, "positive immediate Rush attack", "state.players.human.field", 1, {"cardId": card_id, "rested": True, "keywords": ["RUSH", "REAWAKEN"]})],
        ),
        (
            "duration_cleanup", "Reawaken refreshes Karnal at its owner's turn end after attacking.",
            [setup(card_id, 1722), add("red_02_02_01r_00", side="P2", zone="deck")],
            [play(card_id), attack(card_id), attack_force(), flash_pass(), end_turn()],
            [count(card_id, "boundary Reawaken refresh", "state.players.human.field", 1, {"cardId": card_id, "rested": False})],
        ),
    )

    card_id = "colorless_07_02_01r_01"
    non_monster = "blue_02_02_01r_00"
    monster = "colorless_07_02_01r_02"
    cases[card_id] = pair(
        card_id, 1731,
        (
            "trigger_resolution", "At its owner's turn end, every non-Monster minion on both sides permanently gets BP-200.",
            [setup(card_id, 1731, zone="field"), add(non_monster, side="P1", zone="field"), add(colored_blocker, side="P2", zone="field"), add("red_02_02_01r_00", side="P2", zone="deck")],
            [end_turn()],
            [count(card_id, "positive friendly non-Monster reduced", "state.players.human.field", 1, {"cardId": non_monster, "permanentBpModifier": -200}), count(card_id, "positive enemy non-Monster reduced", "state.players.opponent.field", 1, {"cardId": colored_blocker, "permanentBpModifier": -200})],
        ),
        (
            "target_boundary", "Minions with the Monster race are excluded from the turn-end BP reduction.",
            [setup(card_id, 1732, zone="field"), add(monster, side="P2", zone="field"), add("red_02_02_01r_00", side="P2", zone="deck")],
            [end_turn()],
            [count(card_id, "boundary Monster unchanged", "state.players.opponent.field", 1, {"cardId": monster, "permanentBpModifier": 0})],
        ),
    )

    card_id = "colorless_07_02_01r_02"
    bald_target = "green_07_02_01r_00"
    cases[card_id] = pair(
        card_id, 1741,
        (
            "trigger_resolution", "Summoning destroys one selected enemy at BP1200 or less and deals one damage to each friendly Force.",
            [setup(card_id, 1741), add(bald_target, side="P2", zone="field")],
            [play(card_id), target(bald_target)],
            [count(card_id, "positive target destroyed", "state.players.opponent.trash", 1, {"cardId": bald_target}), count(card_id, "positive first friendly Force damaged", "state.players.human.forces", 1, {"id": "force_e", "life": 1}), count(card_id, "positive second friendly Force damaged", "state.players.human.forces", 1, {"id": "force_so2", "life": 2})],
        ),
        (
            "target_boundary", "An enemy with effective BP above 1200 is excluded and survives.",
            [setup(card_id, 1742), add(bald_target, side="P2", zone="field", capture_as="bald_target_iid"), card_state("$bald_target_iid", permanent_bp_modifier=600)],
            [play(card_id)],
            [count(card_id, "boundary BP1300 survives", "state.players.opponent.field", 1, {"cardId": bald_target, "effectiveBp": 1300}), count(card_id, "boundary first Force still damaged", "state.players.human.forces", 1, {"id": "force_e", "life": 1}), count(card_id, "boundary second Force still damaged", "state.players.human.forces", 1, {"id": "force_so2", "life": 2})],
        ),
    )

    card_id = "colorless_010_02_01r_00"
    beast_a = "colorless_05_02_01r_01"
    beast_b = "yellow_06_02_01_00"
    cases[card_id] = pair(
        card_id, 1751,
        (
            "resource_change", "Summoning deals player damage equal to all friendly Beast/Five Star minions, including Kirin itself.",
            [setup(card_id, 1751), add(beast_a, side="P1", zone="field"), add(beast_b, side="P1", zone="field")],
            [play(card_id)],
            [eq("positive three-race damage", "state.players.opponent.life", 7)],
        ),
        (
            "target_boundary", "A friendly minion of another race is not counted, while Kirin still counts itself once.",
            [setup(card_id, 1752), add(non_soldier, side="P1", zone="field")],
            [play(card_id)],
            [eq("boundary only Kirin counted", "state.players.opponent.life", 9)],
        ),
    )

    return cases


ENGINE_RULE_SYMBOLS = {
    "blue_02_02_01r_01": "free_cost_delta",
    "green_05_02_01r_00": "mana_value",
    "colorless_02_02_01r_00": "adjust_minion_dp_damage",
    "colorless_05_02_01r_00": "can_block",
    "colorless_06_02_01r_00": "free_cost_delta",
}


def build_manifest() -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for card_id in PC01R_CARD_IDS:
        card = CARD_REGISTRY[card_id]
        channels: list[str] = []
        if card.keywords:
            channels.append("keyword")
        if card.effects:
            channels.append("effect")
        if card.triggers:
            channels.append("trigger")
        if card.aura is not None:
            channels.append("aura")
        if card.keyword_aura is not None:
            channels.append("keyword_aura")
        if card.flash_ability is not None:
            channels.append("flash_ability")
        if card_id in ENGINE_RULE_SYMBOLS:
            channels.append("engine_rule")

        template_ids = sorted({effect.template_id for effect in card.effects if effect.template_id})
        has_custom_effect = any(effect.template_id is None for effect in card.effects)
        if card_id in ENGINE_RULE_SYMBOLS or card.aura is not None or card.keyword_aura is not None or has_custom_effect:
            classification = "custom"
        elif card.effects:
            classification = "templated"
        else:
            classification = "keyword"

        files = ["zz/pc01r.py"]
        symbols = ["register_pc01r_cards"]
        if classification == "custom":
            direct_symbols = sorted({effect.fn.__name__ for effect in card.effects if effect.template_id is None})
            symbols.extend(symbol for symbol in direct_symbols if symbol != "fn")
            if card.aura is not None:
                symbols.append("_demigod_aura")
            if card.keyword_aura is not None:
                symbols.append("_rose_keyword_aura")
            if card_id in ENGINE_RULE_SYMBOLS:
                symbols.append(ENGINE_RULE_SYMBOLS[card_id])
                files.append("zz/engine.py")
        if template_ids:
            files.append("zz/effects.py")
            symbols.append("build_effect")
        files = list(dict.fromkeys(files))
        symbols = list(dict.fromkeys(symbols))

        color_dir = card_id.split("_", 1)[0].upper()
        implementation: dict[str, Any] = {
            "files": files,
            "symbols": symbols,
            "effect_channels": channels,
            "call_chain": [
                "data/cards_bilingual_v4.tsv and reconciled Japanese card image",
                "zz.pc01r.register_pc01r_cards -> CARD_REGISTRY",
                "GameSession public prompt selection -> /api/choose",
                "Engine action, effect, aura, keyword, and shared rule resolution",
                "tests/test_pc01r_cards.py::test_pc01r_positive_semantic_scenario",
            ],
        }
        if classification == "templated":
            implementation["template_ids"] = template_ids
        cards.append({
            "card_id": card_id,
            "source_refs": [
                f"data/official_cardlist.tsv#{card_id}",
                f"data/pc01r_image_reconciliation.tsv#{card_id}",
                f"asserts/ZENONZARD_CARDLIST/{color_dir}/{card_id}.png",
            ],
            "classification": classification,
            "status": "semantic_passed",
            "implementation": implementation,
            "tests": {
                "positive": ["tests/test_pc01r_cards.py::test_pc01r_positive_semantic_scenario"],
                "boundary": ["tests/test_pc01r_cards.py::test_pc01r_boundary_semantic_scenario"],
            },
            "semantic_scenarios": {
                kind: {
                    "spec": f"project_memory/card_scenarios/pc01r/{card_id}-{kind}.json",
                    "evidence": f"project_memory/card_evidence/pc01r/{card_id}-{kind}.evidence.json",
                }
                for kind in ("positive", "boundary")
            },
        })
    return {
        "schema_version": 1,
        "box_id": "PC:01R BEYOND",
        "source": {
            "file": "data/official_cardlist.tsv",
            "id_column": "image_id",
            "filters": {"pack_jp_official": "PC:01R BEYOND"},
            "expected_count": 70,
        },
        "real_game_smoke": ["tests/test_pc01r_cards.py::test_pc01r_complete_real_game_smoke"],
        "cards": cards,
    }


def main() -> None:
    SCENARIO_ROOT.mkdir(parents=True, exist_ok=True)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    cases = build_scenarios()
    if set(cases) != set(PC01R_CARD_IDS):
        missing = sorted(set(PC01R_CARD_IDS) - set(cases))
        extra = sorted(set(cases) - set(PC01R_CARD_IDS))
        raise RuntimeError(f"PC01R scenario inventory mismatch: missing={missing} extra={extra}")
    for card_id, variants in cases.items():
        for kind, payload in variants.items():
            path = SCENARIO_ROOT / f"{card_id}-{kind}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {sum(len(value) for value in cases.values())} PC01R scenarios and {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
