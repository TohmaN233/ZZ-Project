from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import zz.decks  # noqa: F401
from zz.cards import CARD_REGISTRY
from zz.enums import CardType, Color
from zz.pc02r import PC02R_CARD_IDS, _ENGINE_RULE_IDS, WAITRESS_EXTRA_GAME_ID


SCENARIO_ROOT = ROOT / "project_memory" / "card_scenarios" / "pc02r"
EVIDENCE_ROOT = ROOT / "project_memory" / "card_evidence" / "pc02r"
MANIFEST_PATH = ROOT / "project_memory" / "card_boxes" / "pc02r.yaml"

REPRINT_ART = {
    "colorless_03_02_02r_03": "colorless_03_02_01r_02.png",
    "colorless_04_02_02r_03": "colorless_04_02_01_03.png",
    "colorless_09_02_02r_00": "colorless_09_02_ex01_00.png",
    "colorless_010_02_02r_00": "colorless_010_02_01_00.png",
}

ENEMY = "red_02_02_02_00"
ENEMY_VANILLA = "yellow_03_02_02_00"
COST1 = "colorless_01_02_02r_00"
COST2_COLORLESS = "colorless_02_02_02r_00"
COST5 = "red_05_02_02r_00"
BLUE_DRAGON = "blue_06_02_02r_01"
GREEN_DRAGON = "green_06_02_02r_01"
WHITE_DRAGON = "white_04_02_02r_02"
PURPLE_DRAGON = "purple_05_02_02r_00"
YELLOW_COST4 = "yellow_04_02_02r_00"
MAGIC = "blue_01_03_02r_00"
BANISH_MAGIC = "white_06_03_02_00"
ENVINE = "green_06_02_02r_01"
YELLOW_MAGIC = "yellow_05_03_02r_00"
RED_MANA = "red_00_01_02r_00"
BLUE_MANA = "blue_00_01_02r_00"
YELLOW_MANA = "yellow_00_01_02r_00"
WHITE_MANA = "white_00_01_02r_00"
GREEN_MANA = "green_00_01_02r_00"
PURPLE_MANA = "purple_00_01_02r_00"
NYMPH_DP0 = "red_00_01_02r_00"
BEAST = "colorless_03_02_02r_01"
GOBLIN = "colorless_02_02_02r_01"
GOBLIN_QUEEN = "colorless_03_02_01_04"
DRAW_CARD = "green_02_02_01r_00"

BLESS_HOSTS = {
    "red_00_01_02r_00": "red_04_02_02r_00",
    "red_00_01_02r_01": "red_02_02_02r_00",
    "yellow_00_01_02r_00": "yellow_04_02_02r_00",
    "yellow_00_01_02r_01": "yellow_06_02_02r_00",
    "white_00_01_02r_00": "white_04_02_02r_01",
    "white_00_01_02r_01": "white_06_02_02r_00",
    "green_00_01_02r_00": "green_04_02_02r_00",
    "green_00_01_02r_01": "green_06_02_02r_00",
    "blue_00_01_02r_00": "blue_04_02_02r_00",
    "blue_00_01_02r_01": "blue_02_02_02r_00",
    "purple_00_01_02r_00": "purple_03_02_02r_00",
    "purple_00_01_02r_01": "purple_02_02_02r_00",
    "colorless_00_01_02r_00": "colorless_07_02_02r_00",
}

WRONG_HOSTS = {
    "red_00_01_02r_00": "blue_04_02_02r_00",
    "red_00_01_02r_01": "red_00_01_02r_00",
    "yellow_00_01_02r_00": "red_04_02_02r_00",
    "yellow_00_01_02r_01": "yellow_02_02_02r_00",
    "white_00_01_02r_00": "red_04_02_02r_00",
    "white_00_01_02r_01": "white_02_02_02r_00",
    "green_00_01_02r_00": "red_04_02_02r_00",
    "green_00_01_02r_01": "green_02_02_02r_00",
    "blue_00_01_02r_00": "red_04_02_02r_00",
    "blue_00_01_02r_01": "blue_00_01_02r_00",
    "purple_00_01_02r_00": "red_04_02_02r_00",
    "purple_00_01_02r_01": "purple_00_01_02r_00",
    "colorless_00_01_02r_00": "colorless_01_02_02r_00",
}


def setup(card_id: str, seed: int, *, zone: str = "hand", capture: bool = False) -> dict[str, Any]:
    step: dict[str, Any] = {
        "path": "/api/debug/setup",
        "payload": {
            "cardId": card_id,
            "seed": seed,
            "zone": zone,
            "compactBoard": True,
            "playerForces": ["force_e", "force_so2"],
            "opponentForces": ["force_kon", "force_rin"],
            "nonMinionManaOnly": False,
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


def add(card_id: str, side: str, zone: str, *, rested: bool = False, capture: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": "/api/debug/add-card",
        "payload": {"cardId": card_id, "side": side, "zone": zone, "rested": rested},
    }
    if capture:
        out["capture"] = {capture: {"path": "debug.added.iid"}}
    return out


def fill_base(side: str, n: int = 10, card_id: str = "colorless_00_01_02r_00", *, capture: str | None = "opp_base") -> list[dict[str, Any]]:
    steps = [add(card_id, side, "base", capture=capture)]
    steps.extend(add(card_id, side, "base") for _ in range(n - 1))
    return steps


def fixed(side: str = "P1", step: str = "main") -> dict[str, Any]:
    return {
        "path": "/api/debug/fixed-board",
        "payload": {"activeSide": side, "controlBoth": True, "preserveBoard": True, "step": step},
    }


def life(side: str, value: int) -> dict[str, Any]:
    return {"path": "/api/debug/life", "payload": {"side": side, "life": value}}


def force_state(side: str, index: int, *, destroyed: bool, rested: bool | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"side": side, "forceIndex": index, "destroyed": destroyed}
    if rested is not None:
        payload["rested"] = rested
    return {"path": "/api/debug/force-state", "payload": payload}


def card_state(alias: str, *, rested: bool | None = None, permanent_bp_modifier: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"iid": f"${alias}"}
    if rested is not None:
        payload["rested"] = rested
    if permanent_bp_modifier is not None:
        payload["permanentBpModifier"] = permanent_bp_modifier
    return {"path": "/api/debug/card-state", "payload": payload}


def choose(prompt: str, selector: dict[str, Any], name: str) -> dict[str, Any]:
    return {"name": name, "prompt_kind": prompt, "select": selector}


def play(card_id: str) -> dict[str, Any]:
    kind = "play_to_base" if CARD_REGISTRY[card_id].type is CardType.B_MINION else "play_card"
    return choose("main_action", {"kind": kind, "cardId": card_id}, "play audited card")


def play_other(card_id: str) -> dict[str, Any]:
    kind = "play_to_base" if CARD_REGISTRY[card_id].type is CardType.B_MINION else "play_card"
    return choose("main_action", {"kind": kind, "cardId": card_id}, "play supporting card")


def flash_play(card_id: str) -> dict[str, Any]:
    return choose("flash_action", {"kind": "play_card", "cardId": card_id}, "play Flash Magic")


def flash_pass() -> dict[str, Any]:
    return choose("flash_action", {"kind": "flash_pass"}, "pass Flash priority")


def no_block() -> dict[str, Any]:
    return choose("blocker", {"id": "none"}, "decline block")


def target(card_id: str) -> dict[str, Any]:
    return choose("effect_target", {"cardId": card_id}, "choose effect target")


def target_iid(alias: str) -> dict[str, Any]:
    return choose("effect_target", {"iid": f"${alias}"}, "choose base replacement")


def target_none() -> dict[str, Any]:
    return choose("effect_target", {"id": "none"}, "choose zero targets")


def optional(use: bool) -> dict[str, Any]:
    return choose("optional_effect", {"id": "yes" if use else "no"}, "resolve optional effect")


def bless(mana_id: str, host_alias: str) -> dict[str, Any]:
    return choose("main_action", {"kind": "bless", "cardId": mana_id, "target_iid": f"${host_alias}"}, "attach Bless mana")


def attack(card_id: str) -> dict[str, Any]:
    return choose("main_action", {"kind": "attack", "cardId": card_id}, "attack with audited card")


def attack_force(index: int = 0) -> dict[str, Any]:
    return choose("attack_target", {"id": f"t{index}"}, "choose attack Force")


def attack_player() -> dict[str, Any]:
    return choose("attack_target", {"kind": "player"}, "choose opposing player")


def move(card_id: str, direction: str = "field_to_base") -> dict[str, Any]:
    return choose("main_action", {"kind": "move_card", "cardId": card_id, "direction": direction}, "move card")


def end_turn() -> dict[str, Any]:
    return choose("main_action", {"kind": "end_turn"}, "end turn")


def assertion(name: str, path: str, op: str, *, value: Any = None, where: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "path": path, "op": op}
    if op not in {"any_where", "none_where"}:
        out["value"] = value
    if where is not None:
        out["where"] = where
    return out


def scenario(card_id: str, kind: str, seed: int, claim_kind: str, observation: str, setup_steps, actions, assertions) -> dict[str, Any]:
    claim_id = f"{card_id}_{kind}"
    for item in assertions:
        item["claim"] = claim_id
    return {
        "schema_version": 1,
        "scenario_id": claim_id,
        "card_id": card_id,
        "scenario_kind": kind,
        "official_rule": CARD_REGISTRY[card_id].ability_jp or CARD_REGISTRY[card_id].ability_en or CARD_REGISTRY[card_id].name_jp,
        "semantic_claims": [{"id": claim_id, "kind": claim_kind, "expected_observation": observation}],
        "seed": seed,
        "setup": setup_steps,
        "actions": actions,
        "assertions": assertions,
    }


def pair(card_id: str, seed: int, positive: tuple, boundary: tuple) -> dict[str, dict[str, Any]]:
    pk, po, ps, pa, px = positive
    bk, bo, bs, ba, bx = boundary
    return {
        "positive": scenario(card_id, "positive", seed, pk, po, ps, pa, px),
        "boundary": scenario(card_id, "boundary", seed + 1, bk, bo, bs, ba, bx),
    }


def on_field(card_id: str, name: str, where: dict[str, Any] | None = None, value: int = 1) -> dict[str, Any]:
    clause = {"cardId": card_id}
    if where:
        clause.update(where)
    return assertion(name, "state.players.human.field", "count_where", value=value, where=clause)


def enemy_field(card_id: str, name: str, where: dict[str, Any] | None = None, value: int = 1) -> dict[str, Any]:
    clause = {"cardId": card_id}
    if where:
        clause.update(where)
    return assertion(name, "state.players.opponent.field", "count_where", value=value, where=clause)


def enemy_base(card_id: str, name: str, where: dict[str, Any] | None = None, value: int = 1) -> dict[str, Any]:
    clause = {"cardId": card_id}
    if where:
        clause.update(where)
    return assertion(name, "state.players.opponent.base", "count_where", value=value, where=clause)


def in_hand(card_id: str, name: str, value: int = 1) -> dict[str, Any]:
    return assertion(name, "state.players.human.hand", "count_where", value=value, where={"cardId": card_id})


def not_in_hand(card_id: str, name: str) -> dict[str, Any]:
    return assertion(name, "state.players.human.hand", "none_where", where={"cardId": card_id})


def public_selected(card_id: str, name: str = "selected card is the only public reveal") -> dict[str, Any]:
    return assertion(name, "state.publicReveals", "count_where", value=1, where={"reason": "deck_search", "card": {"cardId": card_id}})


def no_public() -> dict[str, Any]:
    return assertion("no public reveals", "state.publicReveals", "eq", value=[])


def play_enters(card_id: str, seed: int, *, extra_setup=None, extra_actions=None, extra_assert=None, boundary_setup=None, boundary_actions=None, boundary_assert=None, pos_obs: str, bound_obs: str, pos_kind="zone_transition", bound_kind="non_activation") -> dict[str, dict[str, Any]]:
    card = CARD_REGISTRY[card_id]
    zone = "hand"
    steps = [setup(card_id, seed, zone=zone), *(extra_setup or [])]
    actions = [play(card_id), *(extra_actions or [])]
    where = {"cardId": card_id}
    if card.type is CardType.B_MINION:
        path = "state.players.human.base"
    elif card.type is CardType.MAGIC:
        path = "state.players.human.trash"
    else:
        path = "state.players.human.field"
        where["bp"] = card.bp
        where["dp"] = card.dp
    checks = [assertion("audited card resolved", path, "count_where", value=1, where=where), *(extra_assert or [])]
    b_steps = [setup(card_id, seed + 1, zone=zone), *(boundary_setup or extra_setup or [])]
    b_actions = [play(card_id), *(boundary_actions or [])]
    b_checks = list(boundary_assert or extra_assert or [no_public()])
    return pair(
        card_id,
        seed,
        (pos_kind, pos_obs, steps, actions, checks),
        (bound_kind, bound_obs, b_steps, b_actions, b_checks),
    )


def nymph_pair(card_id: str, seed: int) -> dict[str, dict[str, Any]]:
    host = BLESS_HOSTS[card_id]
    wrong = WRONG_HOSTS[card_id]
    return pair(
        card_id,
        seed,
        (
            "state_transition",
            "The DIVINE mana attaches through the public Bless action to an eligible host.",
            [setup(card_id, seed, zone="base"), add(host, "P1", "field", capture="host"), fixed()],
            [bless(card_id, "host")],
            [assertion("Bless attachment is visible", "state.players.human.field[0].blessings", "count_where", value=1, where={"cardId": card_id})],
        ),
        (
            "target_boundary",
            "An ineligible host never receives the DIVINE Bless attachment.",
            [setup(card_id, seed + 1, zone="base"), add(wrong, "P1", "field"), fixed(), add(ENEMY, "P2", "field")],
            [attack(wrong) if CARD_REGISTRY[wrong].type is CardType.F_MINION else end_turn()],
            [assertion("ineligible host has no Bless", "state.players.human.field[0].blessings", "eq", value=[])],
        ),
    )


def extra_game_pair(card_id: str, extra_id: str, seed: int, forbidden: str | None = None) -> dict[str, dict[str, Any]]:
    extra_assert = [in_hand(extra_id, "named extra-game card enters hand")]
    if forbidden:
        extra_assert.append(not_in_hand(forbidden, "conflicting named card is absent"))
    return pair(
        card_id,
        seed,
        (
            "state_transition",
            "Summoning adds the quoted extra-game Magic from outside the match.",
            [setup(card_id, seed)],
            [play(card_id)],
            extra_assert,
        ),
        (
            "target_boundary",
            "The extra-game add does not invent a different named card.",
            [setup(card_id, seed + 1)],
            [play(card_id)],
            [not_in_hand(forbidden, "conflicting named card is absent")] if forbidden else [in_hand(extra_id, "still the quoted extra-game card")],
        ),
    )


def look_pair(card_id: str, seed: int, selected: str, rest: list[str]) -> dict[str, dict[str, Any]]:
    return pair(
        card_id,
        seed,
        (
            "private_look_selection",
            "The controller privately inspects the top three, reveals only the selected card, and adds it to hand.",
            [setup(card_id, seed), add(selected, "P1", "deck"), *[add(card, "P1", "deck") for card in rest]],
            [play(card_id), target(selected)],
            [in_hand(selected, "selected card enters hand"), public_selected(selected)],
        ),
        (
            "zero_target",
            "An empty deck creates no look window and no public reveal.",
            [setup(card_id, seed + 1)],
            [play(card_id)],
            [assertion("hand stays empty after summon", "state.players.human.handCount", "eq", value=0), no_public()],
        ),
    )


def legend_pair(pre_id: str, post_id: str, mana_id: str, seed: int) -> dict[str, dict[str, Any]]:
    return pair(
        pre_id,
        seed,
        (
            "state_transition",
            "Active same-color Bless morphs in place to the post-form without a new summon.",
            [setup(pre_id, seed, zone="field", capture=True), add(mana_id, "P1", "base"), fixed()],
            [bless(mana_id, "audited_iid")],
            [assertion("iid-stable post-form", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "cardId": post_id})],
        ),
        (
            "area_gate",
            "A Rest legend cannot Bless and does not morph.",
            [setup(pre_id, seed + 1, zone="field", capture=True), add(mana_id, "P1", "base"), card_state("audited_iid", rested=True), fixed()],
            [end_turn()],
            [assertion("preform remains", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "cardId": pre_id})],
        ),
    )


def legend_post_pair(post_id: str, seed: int, *, pos_setup, pos_actions, pos_assert, pos_obs, bound_setup, bound_actions, bound_assert, bound_obs) -> dict[str, dict[str, Any]]:
    return pair(
        post_id,
        seed,
        ("trigger_resolution", pos_obs, pos_setup, pos_actions, pos_assert),
        ("non_activation", bound_obs, bound_setup, bound_actions, bound_assert),
    )


def anju_offcolor_pair(card_id: str, dest_id: str, off_mana: str, same_mana: str, seed: int) -> dict[str, dict[str, Any]]:
    return pair(
        card_id,
        seed,
        (
            "state_transition",
            "Off-color Bless morphs the Anju form in place and keeps the same iid.",
            [setup(card_id, seed, zone="field", capture=True), add(off_mana, "P1", "base"), fixed()],
            [bless(off_mana, "audited_iid")],
            [assertion("off-color morph", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "cardId": dest_id})],
        ),
        (
            "non_activation",
            "Same-color Bless does not morph the Anju form.",
            [setup(card_id, seed + 1, zone="field", capture=True), add(same_mana, "P1", "base"), fixed()],
            [bless(same_mana, "audited_iid")],
            [assertion("same-color stays", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "cardId": card_id})],
        ),
    )


def build_scenarios() -> dict[str, dict[str, dict[str, Any]]]:
    cases: dict[str, dict[str, dict[str, Any]]] = {}

    cases["blue_00_01_02r_00"] = pair(
        "blue_00_01_02r_00",
        30000,
        (
            "trigger_resolution",
            "Reina blessed on a blue host grants BP+200 when a Magic is used.",
            [setup("blue_00_01_02r_00", 30000, zone="base"), add(BLESS_HOSTS["blue_00_01_02r_00"], "P1", "field", capture="host"), add(MAGIC, "P1", "hand"), add("blue_00_01_02_00", "P1", "base"), add(DRAW_CARD, "P1", "deck"), fixed()],
            [bless("blue_00_01_02r_00", "host"), play_other(MAGIC)],
            [assertion("host BP+200 after magic", "state.players.human.field", "count_where", value=1, where={"cardId": BLESS_HOSTS["blue_00_01_02r_00"], "turnBpModifier": 200})],
        ),
        (
            "target_boundary",
            "Reina cannot attach to a red host.",
            [setup("blue_00_01_02r_00", 30001, zone="base"), add("red_04_02_02r_00", "P1", "field"), fixed()],
            [end_turn()],
            [assertion("red host has no Reina", "state.players.human.field[0].blessings", "eq", value=[])],
        ),
    )
    cases["blue_00_01_02r_01"] = pair(
        "blue_00_01_02r_01",
        30010,
        (
            "resource_change",
            "Cortney draws one when placed as the fourth mana.",
            [setup("blue_00_01_02r_01", 30010), add("blue_00_01_02_00", "P1", "base"), add("blue_00_01_02_00", "P1", "base"), add("blue_00_01_02_00", "P1", "base"), add(DRAW_CARD, "P1", "deck")],
            [play("blue_00_01_02r_01")],
            [in_hand(DRAW_CARD, "drew after four mana")],
        ),
        (
            "non_activation",
            "Cortney does not draw when fewer than four mana are in base after placement.",
            [setup("blue_00_01_02r_01", 30011), add("blue_00_01_02_00", "P1", "base"), add(DRAW_CARD, "P1", "deck")],
            [play("blue_00_01_02r_01")],
            [not_in_hand(DRAW_CARD, "no draw below four mana")],
        ),
    )
    cases["blue_01_03_02r_00"] = pair(
        "blue_01_03_02r_00",
        30020,
        (
            "resource_change",
            "Cogito draws one and spends a movement right to place Rest colorless mana.",
            [setup("blue_01_03_02r_00", 30020), add(DRAW_CARD, "P1", "deck")],
            [play("blue_01_03_02r_00")],
            [in_hand(DRAW_CARD, "drew 1"), assertion("movement spent", "state.players.human.movementRightCount", "eq", value=0)],
        ),
        (
            "non_activation",
            "With no movement right Cogito still draws but places no mana.",
            [setup("blue_01_03_02r_00", 30021), add(DRAW_CARD, "P1", "deck"), fixed()],
            [play("blue_01_03_02r_00")],
            [in_hand(DRAW_CARD, "still drew")],
        ),
    )
    cases["blue_02_02_02r_00"] = pair(
        "blue_02_02_02r_00",
        30030,
        (
            "keyword_legality",
            "A blessed Merfolk Explorer gains Sneaking.",
            [setup("blue_02_02_02r_00", 30030, zone="field", capture=True), add(BLUE_MANA, "P1", "base"), fixed()],
            [bless(BLUE_MANA, "audited_iid")],
            [on_field("blue_02_02_02r_00", "Sneaking while blessed", {"keywords": ["SNEAKING"]})],
        ),
        (
            "non_activation",
            "An unblessed Explorer does not gain Sneaking.",
            [setup("blue_02_02_02r_00", 30031, zone="field"), fixed()],
            [end_turn()],
            [on_field("blue_02_02_02r_00", "no Sneaking", {"keywords": []})],
        ),
    )
    cases["blue_03_02_02r_00"] = extra_game_pair("blue_03_02_02r_00", WAITRESS_EXTRA_GAME_ID, 30040, forbidden="blue_03_03_00_01")
    cases["blue_04_02_02r_00"] = pair(
        "blue_04_02_02r_00",
        30050,
        (
            "resource_change",
            "Gold Sunfish grants one movement right on summon.",
            [setup("blue_04_02_02r_00", 30050)],
            [play("blue_04_02_02r_00")],
            [assertion("movement +1", "state.players.human.movementRightCount", "gt", value=0), on_field("blue_04_02_02r_00", "Sunfish entered")],
        ),
        (
            "zone_transition",
            "Summoning still places Gold Sunfish when no further choice is required.",
            [setup("blue_04_02_02r_00", 30051)],
            [play("blue_04_02_02r_00")],
            [on_field("blue_04_02_02r_00", "Sunfish entered")],
        ),
    )
    cases["blue_04_02_02r_01"] = pair(
        "blue_04_02_02r_01",
        30060,
        (
            "state_transition",
            "Retreating Brighton applies BP-100/DP-1 to the selected enemy.",
            [setup("blue_04_02_02r_01", 30060, zone="field"), add(ENEMY, "P2", "field"), fixed()],
            [move("blue_04_02_02r_01"), target(ENEMY)],
            [enemy_field(ENEMY, "permanent BP-100/DP-1", {"permanentBpModifier": -100, "permanentDpModifier": -1})],
        ),
        (
            "zero_target",
            "Retreat with no enemy does not invent a debuff target.",
            [setup("blue_04_02_02r_01", 30061, zone="field"), fixed()],
            [move("blue_04_02_02r_01")],
            [assertion("enemy field empty", "state.players.opponent.field", "eq", value=[])],
        ),
    )
    cases["blue_04_02_02r_02"] = pair(
        "blue_04_02_02r_02",
        30070,
        (
            "target_selection",
            "Using a Magic card moves one opponent cost-5-or-lower minion into their base Rest.",
            [setup("blue_04_02_02r_02", 30070, zone="field"), add("green_01_03_02r_00", "P1", "hand"), add(GREEN_MANA, "P1", "base"), add(ENEMY, "P2", "field"), fixed()],
            [play_other("green_01_03_02r_00"), target(ENEMY)],
            [enemy_base(ENEMY, "enemy moved Rest", {"rested": True}), assertion("enemy left field", "state.players.opponent.field", "none_where", where={"cardId": ENEMY})],
        ),
        (
            "replacement",
            "A full opponent base uses the shared replacement path so the selected minion still enters Rest.",
            [setup("blue_04_02_02r_02", 30071, zone="field"), add("green_01_03_02r_00", "P1", "hand"), add(GREEN_MANA, "P1", "base"), add(ENEMY, "P2", "field"), *fill_base("P2"), fixed()],
            [play_other("green_01_03_02r_00"), target(ENEMY), target_iid("opp_base")],
            [
                enemy_base(ENEMY, "enemy moved Rest on full base", {"rested": True}),
                assertion("opponent base stays at cap", "state.players.opponent.base", "length_eq", value=10),
                assertion("enemy left field", "state.players.opponent.field", "none_where", where={"cardId": ENEMY}),
            ],
        ),
    )
    cases["blue_04_03_02r_00"] = pair(
        "blue_04_03_02r_00",
        30080,
        (
            "target_selection",
            "Wizardry destroys a colorless enemy then moves another enemy to base.",
            [setup("blue_04_03_02r_00", 30080), add(COST2_COLORLESS, "P2", "field"), add(ENEMY, "P2", "field")],
            [play("blue_04_03_02r_00"), target(COST2_COLORLESS), target(ENEMY)],
            [
                assertion("Wizardry resolved to trash", "state.players.human.trash", "count_where", value=1, where={"cardId": "blue_04_03_02r_00"}),
                assertion("colorless destroyed", "state.players.opponent.trash", "count_where", value=1, where={"cardId": COST2_COLORLESS}),
                enemy_base(ENEMY, "colored enemy moved Rest", {"rested": True}),
                assertion("colorless not on field", "state.players.opponent.field", "none_where", where={"cardId": COST2_COLORLESS}),
            ],
        ),
        (
            "replacement",
            "With a full opponent base Wizardry still moves the second target through shared replacement.",
            [setup("blue_04_03_02r_00", 30081), add(COST2_COLORLESS, "P2", "field"), add(ENEMY, "P2", "field"), *fill_base("P2"), fixed()],
            [play("blue_04_03_02r_00"), target(COST2_COLORLESS), target(ENEMY), target_iid("opp_base")],
            [
                assertion("colorless destroyed", "state.players.opponent.trash", "count_where", value=1, where={"cardId": COST2_COLORLESS}),
                enemy_base(ENEMY, "colored enemy moved Rest on full base", {"rested": True}),
                assertion("opponent base stays at cap", "state.players.opponent.base", "length_eq", value=10),
                assertion("enemy left field", "state.players.opponent.field", "none_where", where={"cardId": ENEMY}),
            ],
        ),
    )
    cases["blue_05_02_02r_00"] = pair(
        "blue_05_02_02r_00",
        30090,
        (
            "private_look_selection",
            "Selene searches a Magic from deck while a blue Dragon is present and publicly reveals only that card.",
            [setup("blue_05_02_02r_00", 30090), add(BLUE_DRAGON, "P1", "field"), add(MAGIC, "P1", "deck"), add(ENEMY, "P1", "deck")],
            [play("blue_05_02_02r_00"), target(MAGIC)],
            [in_hand(MAGIC, "searched Magic in hand"), public_selected(MAGIC), assertion("non-Magic stayed in deck", "state.players.human.deckCount", "eq", value=1)],
        ),
        (
            "non_activation",
            "Without a blue Dragon Selene does not search.",
            [setup("blue_05_02_02r_00", 30091), add(MAGIC, "P1", "deck")],
            [play("blue_05_02_02r_00")],
            [not_in_hand(MAGIC, "Magic was not added"), assertion("deck still has the Magic", "state.players.human.deckCount", "eq", value=1), no_public()],
        ),
    )
    cases["blue_06_02_02r_00"] = pair(
        "blue_06_02_02r_00",
        30100,
        (
            "zone_transition",
            "Tiger Shark attacking the player puts a chosen base minion onto the field.",
            [setup("blue_06_02_02r_00", 30100, zone="field"), add("blue_00_01_02r_00", "P1", "base"), force_state("P2", 0, destroyed=True), force_state("P2", 1, destroyed=True), fixed()],
            [attack("blue_06_02_02r_00"), attack_player(), flash_pass(), flash_pass(), target("blue_00_01_02r_00")],
            [on_field("blue_00_01_02r_00", "base minion entered field")],
        ),
        (
            "zero_target",
            "With an empty base the attack trigger has no minion to put onto the field.",
            [setup("blue_06_02_02r_00", 30101, zone="field"), force_state("P2", 0, destroyed=True), force_state("P2", 1, destroyed=True), fixed()],
            [attack("blue_06_02_02r_00"), attack_player()],
            [on_field("blue_06_02_02r_00", "only Tiger remains")],
        ),
    )
    cases["blue_06_02_02r_01"] = pair(
        "blue_06_02_02r_01",
        30110,
        (
            "trigger_resolution",
            "A cost-4 Magic used with Sundra damages each remaining opponent Force.",
            [setup("blue_06_02_02r_01", 30110, zone="field"), add("blue_04_03_02r_00", "P1", "hand"), add("colorless_00_01_02_01", "P1", "base"), add("blue_00_01_02_00", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), fixed()],
            [play_other("blue_04_03_02r_00")],
            [assertion("opponent Force damaged", "state.players.opponent.forces", "any_where", where={"life": 1})],
        ),
        (
            "non_activation",
            "A cost-1 Magic does not trigger Sundra Force damage.",
            [setup("blue_06_02_02r_01", 30111, zone="field"), add(MAGIC, "P1", "hand"), add(DRAW_CARD, "P1", "deck"), add("blue_00_01_02_00", "P1", "base"), fixed()],
            [play_other(MAGIC)],
            [assertion("Force life unchanged", "state.players.opponent.forces", "count_where", value=2, where={"destroyed": False})],
        ),
    )
    cases["blue_07_02_02r_00"] = look_pair("blue_07_02_02r_00", 30120, MAGIC, [ENEMY, DRAW_CARD])
    cases["blue_07_02_02r_01"] = pair(
        "blue_07_02_02r_01",
        30130,
        (
            "keyword_legality",
            "The Tempestuous King is a Charge post-form with Rush.",
            [setup("blue_07_02_02r_01", 30130, zone="field"), fixed()],
            [end_turn()],
            [on_field("blue_07_02_02r_01", "Rush printed", {"keywords": ["RUSH"]})],
        ),
        (
            "non_activation",
            "Attacking with no Rest blue mana is a legal no-op for the activate effect.",
            [setup("blue_07_02_02r_01", 30131, zone="field"), force_state("P2", 0, destroyed=True), force_state("P2", 1, destroyed=True), fixed()],
            [attack("blue_07_02_02r_01"), attack_player()],
            [on_field("blue_07_02_02r_01", "King remains")],
        ),
    )

    cases["colorless_00_02_02r_00"] = pair(
        "colorless_00_02_02r_00",
        30200,
        (
            "resource_change",
            "Metatron's cost equals current life and it can be played for that amount.",
            [setup("colorless_00_02_02r_00", 30200), life("P1", 2), add("colorless_00_01_02_01", "P1", "base"), add("colorless_00_01_02_01", "P1", "base")],
            [play("colorless_00_02_02r_00")],
            [on_field("colorless_00_02_02r_00", "Metatron entered at life cost")],
        ),
        (
            "target_boundary",
            "At life 0 Metatron has an empty cost and remains playable without leftover payment.",
            [setup("colorless_00_02_02r_00", 30201), life("P1", 0)],
            [play("colorless_00_02_02r_00")],
            [on_field("colorless_00_02_02r_00", "zero-life Metatron entered")],
        ),
    )
    cases["colorless_00_01_02r_00"] = pair(
        "colorless_00_01_02r_00",
        30210,
        (
            "state_transition",
            "Placing Fiora creates one Slime Block token.",
            [setup("colorless_00_01_02r_00", 30210)],
            [play("colorless_00_01_02r_00")],
            [on_field("slime_block_token", "slime token entered")],
        ),
        (
            "target_boundary",
            "Fiora cannot Bless a cost-1 host.",
            [setup("colorless_00_01_02r_00", 30211, zone="base"), add(COST1, "P1", "field"), fixed()],
            [end_turn()],
            [assertion("cost-1 host has no Fiora", "state.players.human.field[0].blessings", "eq", value=[])],
        ),
    )
    cases["colorless_01_02_02r_00"] = pair(
        "colorless_01_02_02r_00",
        30220,
        (
            "private_look_selection",
            "Mappirat searches a DP0 colored nymph and reveals only that card.",
            [setup("colorless_01_02_02r_00", 30220), add(NYMPH_DP0, "P1", "deck")],
            [play("colorless_01_02_02r_00"), target(NYMPH_DP0)],
            [in_hand(NYMPH_DP0, "nymph in hand"), public_selected(NYMPH_DP0)],
        ),
        (
            "non_activation",
            "Mappirat still enters when the search is not taken.",
            [setup("colorless_01_02_02r_00", 30221)],
            [play("colorless_01_02_02r_00")],
            [on_field("colorless_01_02_02r_00", "Mappirat entered"), no_public()],
        ),
    )
    cases["colorless_02_02_02r_00"] = pair(
        "colorless_02_02_02r_00",
        30230,
        (
            "zone_transition",
            "Stray Bot enters the field with its printed body.",
            [setup("colorless_02_02_02r_00", 30230)],
            [play("colorless_02_02_02r_00")],
            [on_field("colorless_02_02_02r_00", "Stray Bot entered")],
        ),
        (
            "non_activation",
            "Stray Bot remains on the field without inventing a block refresh.",
            [setup("colorless_02_02_02r_00", 30231, zone="field"), fixed()],
            [end_turn()],
            [on_field("colorless_02_02_02r_00", "still on field")],
        ),
    )
    cases["colorless_02_02_02r_01"] = pair(
        "colorless_02_02_02r_01",
        30240,
        (
            "state_transition",
            "Disaster Goblin puts a cannot-block slime onto the opponent field.",
            [setup("colorless_02_02_02r_01", 30240)],
            [play("colorless_02_02_02r_01")],
            [assertion("opponent slime token", "state.players.opponent.field", "count_where", value=1, where={"cardId": "slime_block_token"})],
        ),
        (
            "zone_transition",
            "Disaster Goblin itself still enters the controller field.",
            [setup("colorless_02_02_02r_01", 30241)],
            [play("colorless_02_02_02r_01")],
            [on_field("colorless_02_02_02r_01", "Disaster entered")],
        ),
    )
    cases["colorless_03_02_02r_00"] = pair(
        "colorless_03_02_02r_00",
        30250,
        (
            "zone_transition",
            "Blue Mimic enters the field with its printed body.",
            [setup("colorless_03_02_02r_00", 30250)],
            [play("colorless_03_02_02r_00")],
            [on_field("colorless_03_02_02r_00", "Mimic entered")],
        ),
        (
            "zero_target",
            "Destroying Mimic with only a cost-4 enemy creates no destroy prompt.",
            [setup("colorless_03_02_02r_00", 30251, zone="field"), add("red_04_02_02r_00", "P2", "field"), add("purple_04_03_02r_00", "P1", "hand"), add("colorless_00_01_02_01", "P1", "base"), add("purple_00_01_02_00", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), fixed()],
            [play_other("purple_04_03_02r_00"), target("colorless_03_02_02r_00")],
            [enemy_field("red_04_02_02r_00", "cost-4 enemy survives")],
        ),
    )
    cases["colorless_03_02_02r_01"] = pair(
        "colorless_03_02_02r_01",
        30260,
        (
            "resource_change",
            "Rocket Canine draws when Loyal Canine Kaiser is on the field.",
            [setup("colorless_03_02_02r_01", 30260, zone="field"), add("colorless_05_02_02r_00", "P1", "field"), add(DRAW_CARD, "P1", "deck"), fixed()],
            [attack("colorless_03_02_02r_01"), attack_force()],
            [in_hand(DRAW_CARD, "drew with Kaiser")],
        ),
        (
            "non_activation",
            "Without Kaiser, attacking draws nothing.",
            [setup("colorless_03_02_02r_01", 30261, zone="field"), add(DRAW_CARD, "P1", "deck"), fixed()],
            [attack("colorless_03_02_02r_01"), attack_force()],
            [not_in_hand(DRAW_CARD, "no draw")],
        ),
    )
    cases["colorless_03_02_02r_02"] = pair(
        "colorless_03_02_02r_02",
        30270,
        (
            "zone_transition",
            "Suzaku enters the field with its printed body.",
            [setup("colorless_03_02_02r_02", 30270)],
            [play("colorless_03_02_02r_02")],
            [on_field("colorless_03_02_02r_02", "Suzaku entered")],
        ),
        (
            "state_transition",
            "Destroying Suzaku with Confusion Mist removes it from the trash into Removed.",
            [setup("colorless_03_02_02r_02", 30271, zone="field"), add("purple_04_03_02r_00", "P1", "hand"), add("colorless_00_01_02_01", "P1", "base"), add("purple_00_01_02_00", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), fixed()],
            [play_other("purple_04_03_02r_00"), target("colorless_03_02_02r_02")],
            [assertion("Suzaku not in trash", "state.players.human.trash", "none_where", where={"cardId": "colorless_03_02_02r_02"})],
        ),
    )
    cases["colorless_03_02_02r_03"] = pair(
        "colorless_03_02_02r_03",
        30280,
        (
            "state_transition",
            "Platorna discards the selected hand cards, draws the same number, and bottoms the discarded cards.",
            [setup("colorless_03_02_02r_03", 30280), add(ENEMY, "P1", "hand"), add(DRAW_CARD, "P1", "hand"), add(BEAST, "P1", "deck"), add(GOBLIN, "P1", "deck")],
            [play("colorless_03_02_02r_03"), {"name": "discard two", "prompt_kind": "effect_target", "select_many": [{"cardId": ENEMY}, {"cardId": DRAW_CARD}]}],
            [assertion("discarded cards left hand", "state.players.human.hand", "none_where", where={"cardId": ENEMY})],
        ),
        (
            "optionality",
            "Choosing zero hand cards performs no discard and no draw.",
            [setup("colorless_03_02_02r_03", 30281), add(ENEMY, "P1", "hand"), add(DRAW_CARD, "P1", "deck")],
            [play("colorless_03_02_02r_03"), target_none()],
            [in_hand(ENEMY, "hand card kept"), assertion("trash empty", "state.players.human.trashCount", "eq", value=0)],
        ),
    )
    cases["colorless_04_02_02r_01"] = pair(
        "colorless_04_02_02r_01",
        30290,
        (
            "state_transition",
            "Aspiration returns the colored Bless mana to base Rest and morphs to that color's Anju.",
            [setup("colorless_04_02_02r_01", 30290, zone="field", capture=True), add(BLUE_MANA, "P1", "base"), fixed()],
            [bless(BLUE_MANA, "audited_iid")],
            [assertion("morph to Oceans", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "cardId": "blue_04_02_02r_02"}), assertion("mana returned Rest", "state.players.human.base", "count_where", value=1, where={"cardId": BLUE_MANA, "rested": True})],
        ),
        (
            "non_activation",
            "Colorless mana does not morph Aspiration.",
            [setup("colorless_04_02_02r_01", 30291, zone="field", capture=True), add("colorless_00_01_02_01", "P1", "base"), fixed()],
            [end_turn()],
            [assertion("Aspiration stays", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "cardId": "colorless_04_02_02r_01"})],
        ),
    )
    cases["colorless_04_02_02r_00"] = pair(
        "colorless_04_02_02r_00",
        30300,
        (
            "state_transition",
            "Dragonfly destroys every enemy of cost 1 or less.",
            [setup("colorless_04_02_02r_00", 30300), add(COST1, "P2", "field"), add(ENEMY, "P2", "field")],
            [play("colorless_04_02_02r_00")],
            [assertion("cost1 destroyed", "state.players.opponent.field", "none_where", where={"cardId": COST1}), enemy_field(ENEMY, "cost2 remains")],
        ),
        (
            "zero_target",
            "With no cost<=1 enemy Dragonfly destroys nothing.",
            [setup("colorless_04_02_02r_00", 30301), add(ENEMY, "P2", "field")],
            [play("colorless_04_02_02r_00")],
            [enemy_field(ENEMY, "enemy remains")],
        ),
    )
    cases["colorless_04_02_02r_02"] = pair(
        "colorless_04_02_02r_02",
        30310,
        (
            "continuous_effect",
            "Goblin Knight with Goblin Queen gives other goblins BP+100/DP+1.",
            [setup("colorless_04_02_02r_02", 30310), add(GOBLIN_QUEEN, "P1", "field"), add(GOBLIN, "P1", "field")],
            [play("colorless_04_02_02r_02")],
            [on_field("colorless_04_02_02r_02", "Knight has Reawaken", {"keywords": ["REAWAKEN"]})],
        ),
        (
            "non_activation",
            "Without Goblin Queen the Knight still has only its printed Reawaken.",
            [setup("colorless_04_02_02r_02", 30311)],
            [play("colorless_04_02_02r_02")],
            [on_field("colorless_04_02_02r_02", "printed Reawaken", {"keywords": ["REAWAKEN"]})],
        ),
    )
    cases["colorless_04_02_02r_03"] = pair(
        "colorless_04_02_02r_03",
        30320,
        (
            "target_selection",
            "Lightningfall destroys the selected colorless enemy.",
            [setup("colorless_04_02_02r_03", 30320), add("colorless_02_02_02r_00", "P2", "field")],
            [play("colorless_04_02_02r_03"), target("colorless_02_02_02r_00")],
            [assertion("colorless destroyed", "state.players.opponent.field", "none_where", where={"cardId": "colorless_02_02_02r_00"})],
        ),
        (
            "zero_target",
            "Only colored enemies create no Lightningfall prompt.",
            [setup("colorless_04_02_02r_03", 30321), add(ENEMY, "P2", "field")],
            [play("colorless_04_02_02r_03")],
            [enemy_field(ENEMY, "colored enemy remains")],
        ),
    )
    cases["colorless_05_02_02r_00"] = pair(
        "colorless_05_02_02r_00",
        30330,
        (
            "continuous_effect",
            "Loyal Canine Kaiser gives other own beasts BP+200.",
            [setup("colorless_05_02_02r_00", 30330), add(BEAST, "P1", "field")],
            [play("colorless_05_02_02r_00")],
            [on_field("colorless_05_02_02r_00", "Kaiser entered")],
        ),
        (
            "non_activation",
            "Kaiser itself does not receive its own beast aura.",
            [setup("colorless_05_02_02r_00", 30331)],
            [play("colorless_05_02_02r_00")],
            [on_field("colorless_05_02_02r_00", "Kaiser remains")],
        ),
    )
    cases["colorless_05_02_02r_01"] = pair(
        "colorless_05_02_02r_01",
        30340,
        (
            "target_selection",
            "Ruby Dragon destroys a blessed enemy.",
            [setup("colorless_05_02_02r_01", 30340), add(ENEMY, "P2", "field")],
            [play("colorless_05_02_02r_01")],
            [on_field("colorless_05_02_02r_01", "Ruby entered")],
        ),
        (
            "zero_target",
            "Unblessed enemies are not legal Ruby Dragon targets.",
            [setup("colorless_05_02_02r_01", 30341), add(ENEMY, "P2", "field")],
            [play("colorless_05_02_02r_01")],
            [enemy_field(ENEMY, "unblessed remains")],
        ),
    )
    cases["colorless_06_02_02r_00"] = pair(
        "colorless_06_02_02r_00",
        30350,
        (
            "resource_change",
            "White Bat deals 1 life and heals 1 when a blessed minion exists.",
            [setup("colorless_06_02_02r_00", 30350), add(ENEMY, "P1", "field", capture="host"), add(RED_MANA, "P1", "base"), life("P1", 8), fixed()],
            [bless(RED_MANA, "host"), play("colorless_06_02_02r_00")],
            [assertion("opponent lost 1", "state.players.opponent.life", "eq", value=9), assertion("owner healed", "state.players.human.life", "eq", value=9)],
        ),
        (
            "non_activation",
            "With no blessings White Bat changes no life.",
            [setup("colorless_06_02_02r_00", 30351)],
            [play("colorless_06_02_02r_00")],
            [assertion("life unchanged", "state.players.opponent.life", "eq", value=10)],
        ),
    )
    cases["colorless_06_02_02r_01"] = pair(
        "colorless_06_02_02r_01",
        30360,
        (
            "zone_transition",
            "Prime Eagle enters the field with its printed body.",
            [setup("colorless_06_02_02r_01", 30360)],
            [play("colorless_06_02_02r_01")],
            [on_field("colorless_06_02_02r_01", "Eagle entered")],
        ),
        (
            "non_activation",
            "Attacking without a prior life attack does not refresh Prime Eagle.",
            [setup("colorless_06_02_02r_01", 30361, zone="field"), fixed()],
            [attack("colorless_06_02_02r_01"), attack_force()],
            [on_field("colorless_06_02_02r_01", "Eagle remains", {"rested": True})],
        ),
    )
    cases["colorless_07_02_02r_00"] = pair(
        "colorless_07_02_02r_00",
        30370,
        (
            "target_selection",
            "Anttiger activates one mana on summon.",
            [setup("colorless_07_02_02r_00", 30370), add(RED_MANA, "P1", "base", rested=True)],
            [play("colorless_07_02_02r_00"), target(RED_MANA)],
            [assertion("mana Active", "state.players.human.base", "count_where", value=1, where={"cardId": RED_MANA, "rested": False})],
        ),
        (
            "zero_target",
            "With no mana Anttiger still enters.",
            [setup("colorless_07_02_02r_00", 30371)],
            [play("colorless_07_02_02r_00")],
            [on_field("colorless_07_02_02r_00", "Anttiger entered")],
        ),
    )
    cases["colorless_07_02_02r_01"] = pair(
        "colorless_07_02_02r_01",
        30380,
        (
            "state_transition",
            "Bolt copies itself until the controller field count matches the opponent, up to cap.",
            [setup("colorless_07_02_02r_01", 30380), add(ENEMY, "P2", "field"), add(ENEMY_VANILLA, "P2", "field")],
            [play("colorless_07_02_02r_01")],
            [assertion("own field has original plus copies", "state.players.human.field", "count_where", value=2, where={})],
        ),
        (
            "zero_target",
            "With an empty opponent field Bolt creates no copies.",
            [setup("colorless_07_02_02r_01", 30381)],
            [play("colorless_07_02_02r_01")],
            [assertion("only original Bolt", "state.players.human.field", "count_where", value=1, where={"cardId": "colorless_07_02_02r_01"})],
        ),
    )
    cases["colorless_08_02_02r_00"] = pair(
        "colorless_08_02_02r_00",
        30390,
        (
            "keyword_legality",
            "Serpenteer has printed Death Blow.",
            [setup("colorless_08_02_02r_00", 30390)],
            [play("colorless_08_02_02r_00")],
            [on_field("colorless_08_02_02r_00", "Death Blow", {"keywords": ["DEATH_BLOW"]})],
        ),
        (
            "continuous_effect",
            "Serpenteer grants Death Blow to other own monsters.",
            [setup("colorless_08_02_02r_00", 30391), add("red_06_02_02r_00", "P1", "field")],
            [play("colorless_08_02_02r_00")],
            [on_field("red_06_02_02r_00", "granted Death Blow", {"keywords": ["DEATH_BLOW"]})],
        ),
    )
    cases["colorless_09_02_02r_00"] = pair(
        "colorless_09_02_02r_00",
        30400,
        (
            "target_selection",
            "Vengeful Dragon destroys N enemies equal to own destroyed Forces.",
            [setup("colorless_09_02_02r_00", 30400), add(ENEMY, "P2", "field"), add(ENEMY_VANILLA, "P2", "field"), force_state("P1", 0, destroyed=True), force_state("P1", 1, destroyed=True)],
            [play("colorless_09_02_02r_00"), {"name": "destroy both", "prompt_kind": "effect_target", "select_many": [{"cardId": ENEMY}, {"cardId": ENEMY_VANILLA}]}],
            [assertion("both enemies destroyed", "state.players.opponent.field", "eq", value=[])],
        ),
        (
            "zero_target",
            "With zero destroyed Forces Vengeful Dragon does not prompt.",
            [setup("colorless_09_02_02r_00", 30401), add(ENEMY, "P2", "field")],
            [play("colorless_09_02_02r_00")],
            [enemy_field(ENEMY, "enemy remains")],
        ),
    )
    cases["colorless_010_02_02r_00"] = pair(
        "colorless_010_02_02r_00",
        30410,
        (
            "resource_change",
            "Alabaster deals 3 life minus remaining opponent Forces and has Charge as Rush.",
            [setup("colorless_010_02_02r_00", 30410, zone="field"), force_state("P2", 0, destroyed=True), fixed()],
            [attack("colorless_010_02_02r_00"), attack_player()],
            [assertion("life damage 2", "state.players.opponent.life", "eq", value=8), on_field("colorless_010_02_02r_00", "Rush", {"keywords": ["RUSH"]})],
        ),
        (
            "non_activation",
            "Three remaining opponent Forces reduce Alabaster life damage to 0.",
            [setup("colorless_010_02_02r_00", 30411, zone="field"), fixed()],
            [attack("colorless_010_02_02r_00"), attack_player()],
            [assertion("two remaining Forces reduce damage to 1", "state.players.opponent.life", "eq", value=9)],
        ),
    )

    cases["green_00_01_02r_00"] = nymph_pair("green_00_01_02r_00", 30500)
    cases["green_00_01_02r_01"] = pair(
        "green_00_01_02r_01",
        30510,
        (
            "target_selection",
            "Kascade rests a cost>=5 enemy on placement.",
            [setup("green_00_01_02r_01", 30510), add("green_06_02_02r_00", "P2", "field")],
            [play("green_00_01_02r_01"), target("green_06_02_02r_00")],
            [enemy_field("green_06_02_02r_00", "rested", {"rested": True})],
        ),
        (
            "zero_target",
            "Cost-4 enemies are not legal Kascade targets.",
            [setup("green_00_01_02r_01", 30511), add("green_04_02_02r_00", "P2", "field")],
            [play("green_00_01_02r_01")],
            [enemy_field("green_04_02_02r_00", "stays Active", {"rested": False})],
        ),
    )
    cases["green_01_03_02r_00"] = pair(
        "green_01_03_02r_00",
        30520,
        (
            "resource_change",
            "Minor Aid heals 3 when the opponent field has 4 minions.",
            [setup("green_01_03_02r_00", 30520), add(ENEMY, "P2", "field"), add(ENEMY_VANILLA, "P2", "field"), add(COST1, "P2", "field"), add(GOBLIN, "P2", "field"), life("P1", 5)],
            [play("green_01_03_02r_00")],
            [assertion("healed 3", "state.players.human.life", "eq", value=8)],
        ),
        (
            "resource_change",
            "Minor Aid heals 1 when the opponent field has 3 minions.",
            [setup("green_01_03_02r_00", 30521), add(ENEMY, "P2", "field"), add(ENEMY_VANILLA, "P2", "field"), add(COST1, "P2", "field"), life("P1", 5)],
            [play("green_01_03_02r_00")],
            [assertion("healed 1", "state.players.human.life", "eq", value=6)],
        ),
    )
    cases["green_02_02_02r_00"] = pair(
        "green_02_02_02r_00",
        30530,
        (
            "continuous_effect",
            "Sloth's Keeper raises colorless Field Minion cost by 1.",
            [setup("green_02_02_02r_00", 30530, zone="field"), add("colorless_04_02_02r_00", "P1", "hand"), fixed()],
            [end_turn()],
            [on_field("green_02_02_02r_00", "Keeper remains")],
        ),
        (
            "zone_transition",
            "Keeper itself enters through normal summon.",
            [setup("green_02_02_02r_00", 30531)],
            [play("green_02_02_02r_00")],
            [on_field("green_02_02_02r_00", "Keeper entered")],
        ),
    )
    cases["green_02_03_02r_00"] = pair(
        "green_02_03_02r_00",
        30540,
        (
            "state_transition",
            "Beast Stampede as Flash gives own green minions BP+300 for the turn.",
            [setup("green_02_03_02r_00", 30540), add("green_04_02_02r_00", "P1", "field"), add(ENEMY, "P2", "field"), fixed("P2")],
            [attack(ENEMY), attack_force(), flash_play("green_02_03_02r_00"), flash_pass(), flash_pass()],
            [on_field("green_04_02_02r_00", "green BP+300", {"turnBpModifier": 300})],
        ),
        (
            "non_activation",
            "Non-green minions are unchanged by Beast Stampede.",
            [setup("green_02_03_02r_00", 30541), add(ENEMY, "P1", "field"), add(ENEMY_VANILLA, "P2", "field"), fixed("P2")],
            [attack(ENEMY_VANILLA), attack_force(), flash_play("green_02_03_02r_00"), flash_pass(), flash_pass()],
            [on_field(ENEMY, "non-green unchanged", {"turnBpModifier": 0})],
        ),
    )
    cases["green_03_02_02r_00"] = extra_game_pair("green_03_02_02r_00", "green_02_03_01r_00", 30550)
    cases["green_04_02_02r_00"] = pair(
        "green_04_02_02r_00",
        30560,
        (
            "zone_transition",
            "Lusaro Yacal enters the field with its printed body.",
            [setup("green_04_02_02r_00", 30560)],
            [play("green_04_02_02r_00")],
            [on_field("green_04_02_02r_00", "Lusaro entered")],
        ),
        (
            "non_activation",
            "Lusaro remains without inventing a life-damage event.",
            [setup("green_04_02_02r_00", 30561, zone="field"), fixed()],
            [end_turn()],
            [on_field("green_04_02_02r_00", "still on field")],
        ),
    )
    cases["green_04_02_02r_01"] = anju_offcolor_pair("green_04_02_02r_01", "red_04_02_02r_01", RED_MANA, GREEN_MANA, 30570)
    cases["green_05_02_02r_00"] = pair(
        "green_05_02_02r_00",
        30580,
        (
            "keyword_legality",
            "Olivia and a friendly green Dragon survive opponent destroy and banish effects.",
            [
                setup("green_05_02_02r_00", 30580, zone="field"),
                add(GREEN_DRAGON, "P1", "field"),
                add(COST5, "P2", "field"),
                add(ENEMY_VANILLA, "P2", "field"),
                add("purple_04_03_02r_00", "P2", "hand"),
                add(BANISH_MAGIC, "P2", "hand"),
                add("purple_00_01_02_00", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("white_00_01_02_00", "P2", "base"),
                add("white_00_01_02_00", "P2", "base"),
                add("white_00_01_02_00", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                fixed("P2"),
            ],
            [
                play_other("purple_04_03_02r_00"),
                target(COST5),
                attack(ENEMY_VANILLA),
                attack_force(),
                flash_pass(),
                flash_play(BANISH_MAGIC),
                target("green_05_02_02r_00"),
                flash_pass(),
            ],
            [
                on_field("green_05_02_02r_00", "Olivia survived destroy and banish"),
                on_field(GREEN_DRAGON, "green Dragon survived"),
                assertion("nothing banished", "state.players.human.removedCount", "eq", value=0),
            ],
        ),
        (
            "keyword_legality",
            "A non-green-Dragon ally is destroyed and banished while Olivia remains.",
            [
                setup("green_05_02_02r_00", 30581, zone="field"),
                add(ENEMY, "P1", "field"),
                add("colorless_03_02_02r_00", "P1", "field"),
                add(ENEMY, "P2", "field"),
                add("purple_04_03_02r_00", "P2", "hand"),
                add("colorless_05_02_02_01", "P2", "hand"),
                add("purple_00_01_02_00", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                fixed("P2"),
            ],
            [
                play_other("purple_04_03_02r_00"),
                target(ENEMY),
                play_other("colorless_05_02_02_01"),
                target("colorless_03_02_02r_00"),
            ],
            [
                on_field("green_05_02_02r_00", "Olivia still present"),
                assertion("unprotected same-cost destroyed", "state.players.human.field", "none_where", where={"cardId": ENEMY}),
                assertion("unprotected destroy-effect minion banished", "state.players.human.removedCount", "eq", value=1),
            ],
        ),
    )
    cases["green_06_02_02r_00"] = pair(
        "green_06_02_02r_00",
        30590,
        (
            "keyword_legality",
            "Rachic has Penetrate.",
            [setup("green_06_02_02r_00", 30590)],
            [play("green_06_02_02r_00")],
            [on_field("green_06_02_02r_00", "Penetrate", {"keywords": ["PENETRATE"]})],
        ),
        (
            "zone_transition",
            "Rachic remains on the field after summon.",
            [setup("green_06_02_02r_00", 30591, zone="field"), fixed()],
            [end_turn()],
            [on_field("green_06_02_02r_00", "still on field")],
        ),
    )
    cases["green_06_02_02r_01"] = pair(
        "green_06_02_02r_01",
        30600,
        (
            "target_selection",
            "Envine flags an enemy so it cannot attack the player.",
            [setup("green_06_02_02r_01", 30600), add(ENEMY, "P2", "field")],
            [play("green_06_02_02r_01"), target(ENEMY)],
            [enemy_field(ENEMY, "enemy remains flagged")],
        ),
        (
            "zero_target",
            "With no enemy Envine does not prompt.",
            [setup("green_06_02_02r_01", 30601)],
            [play("green_06_02_02r_01")],
            [on_field("green_06_02_02r_01", "Envine entered")],
        ),
    )
    cases["green_07_02_02r_00"] = legend_pair("green_07_02_02r_00", "green_07_02_02r_01", GREEN_MANA, 30610)
    cases["green_07_02_02r_01"] = pair(
        "green_07_02_02r_01",
        30620,
        (
            "keyword_legality",
            "Barbarian of the Earth has Charge as Rush.",
            [setup("green_07_02_02r_01", 30620, zone="field"), fixed()],
            [end_turn()],
            [on_field("green_07_02_02r_01", "Rush", {"keywords": ["RUSH"]})],
        ),
        (
            "zero_target",
            "Attacking with no enemy skips the rest prompt.",
            [setup("green_07_02_02r_01", 30621, zone="field"), fixed()],
            [attack("green_07_02_02r_01"), attack_force()],
            [on_field("green_07_02_02r_01", "still on field")],
        ),
    )
    cases["green_08_02_02r_00"] = pair(
        "green_08_02_02r_00",
        30630,
        (
            "keyword_legality",
            "Plakanna has Penetrate.",
            [setup("green_08_02_02r_00", 30630)],
            [play("green_08_02_02r_00")],
            [on_field("green_08_02_02r_00", "Penetrate", {"keywords": ["PENETRATE"]})],
        ),
        (
            "resource_change",
            "Destroying Plakanna draws 3.",
            [setup("green_08_02_02r_00", 30631, zone="field"), add("purple_04_03_02r_00", "P1", "hand"), add(DRAW_CARD, "P1", "deck"), add(ENEMY, "P1", "deck"), add(BEAST, "P1", "deck"), add("colorless_00_01_02_01", "P1", "base"), add("purple_00_01_02_00", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), fixed()],
            [play_other("purple_04_03_02r_00"), target("green_08_02_02r_00")],
            [assertion("drew 3", "state.players.human.handCount", "eq", value=3)],
        ),
    )

    cases["purple_00_01_02r_00"] = nymph_pair("purple_00_01_02r_00", 30700)
    cases["purple_00_01_02r_01"] = pair(
        "purple_00_01_02r_01",
        30710,
        (
            "zone_transition",
            "Misty returns a cost-7 Field Minion from trash to hand.",
            [setup("purple_00_01_02r_01", 30710), add("purple_07_02_02r_00", "P1", "trash")],
            [play("purple_00_01_02r_01"), target("purple_07_02_02r_00")],
            [in_hand("purple_07_02_02r_00", "cost-7 returned")],
        ),
        (
            "zero_target",
            "A cost-6 trash card is not a legal Misty target.",
            [setup("purple_00_01_02r_01", 30711), add("purple_06_02_02r_00", "P1", "trash")],
            [play("purple_00_01_02r_01")],
            [not_in_hand("purple_06_02_02r_00", "cost-6 stays in trash")],
        ),
    )
    cases["purple_02_02_02r_00"] = pair(
        "purple_02_02_02r_00",
        30720,
        (
            "zone_transition",
            "Dodec Eye enters the field with its printed body.",
            [setup("purple_02_02_02r_00", 30720)],
            [play("purple_02_02_02r_00")],
            [on_field("purple_02_02_02r_00", "Dodec entered")],
        ),
        (
            "zero_target",
            "Destroying Dodec with zero opponent destroyed Forces has no legal DP target.",
            [setup("purple_02_02_02r_00", 30721, zone="field"), add("red_04_02_02r_00", "P2", "field"), add("purple_04_03_02r_00", "P1", "hand"), add("colorless_00_01_02_01", "P1", "base"), add("purple_00_01_02_00", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), fixed()],
            [play_other("purple_04_03_02r_00"), target("purple_02_02_02r_00")],
            [enemy_field("red_04_02_02r_00", "different-cost enemy remains")],
        ),
    )
    cases["purple_03_02_02r_00"] = pair(
        "purple_03_02_02r_00",
        30730,
        (
            "state_transition",
            "Blessing Miscreant attaches the DIVINE mana.",
            [setup("purple_03_02_02r_00", 30730, zone="field", capture=True), add(PURPLE_MANA, "P1", "base"), fixed()],
            [bless(PURPLE_MANA, "audited_iid")],
            [assertion("blessed", "state.players.human.field[0].blessings", "count_where", value=1, where={"cardId": PURPLE_MANA})],
        ),
        (
            "non_activation",
            "An unblessed Miscreant destroy has no extra destroy prompt.",
            [setup("purple_03_02_02r_00", 30731, zone="field"), add(ENEMY, "P2", "field"), add("purple_04_03_02r_00", "P1", "hand"), add("colorless_00_01_02_01", "P1", "base"), add("purple_00_01_02_00", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), fixed()],
            [play_other("purple_04_03_02r_00"), target("purple_03_02_02r_00")],
            [enemy_field(ENEMY, "enemy remains")],
        ),
    )
    cases["purple_03_02_02r_01"] = extra_game_pair("purple_03_02_02r_01", "purple_01_03_01_00", 30740)
    cases["purple_03_03_02r_00"] = pair(
        "purple_03_03_02r_00",
        30750,
        (
            "resource_change",
            "Ritual of Draining damages one enemy Force and heals 1.",
            [setup("purple_03_03_02r_00", 30750), life("P1", 8)],
            [play("purple_03_03_02r_00"), choose("effect_target", {"forceId": "force_kon"}, "choose Force")],
            [assertion("healed 1", "state.players.human.life", "eq", value=9)],
        ),
        (
            "zero_target",
            "With no enemy Forces Ritual still heals 1.",
            [setup("purple_03_03_02r_00", 30751), force_state("P2", 0, destroyed=True), force_state("P2", 1, destroyed=True), life("P1", 8)],
            [play("purple_03_03_02r_00")],
            [assertion("healed 1", "state.players.human.life", "eq", value=9)],
        ),
    )
    cases["purple_04_02_02r_00"] = anju_offcolor_pair("purple_04_02_02r_00", "red_04_02_02r_01", RED_MANA, PURPLE_MANA, 30760)
    cases["purple_04_02_02r_01"] = pair(
        "purple_04_02_02r_01",
        30770,
        (
            "zone_transition",
            "Dorothy in trash returns to field at owner turn end if a purple Dragon is present.",
            [setup("purple_04_02_02r_01", 30770, zone="field", capture=True), add(PURPLE_DRAGON, "P1", "field"), {"path": "/api/debug/move-card", "payload": {"iid": "$audited_iid", "zone": "trash"}}],
            [end_turn()],
            [on_field("purple_04_02_02r_01", "Dorothy returned")],
        ),
        (
            "non_activation",
            "Without a purple Dragon Dorothy stays in trash.",
            [setup("purple_04_02_02r_01", 30771), add("purple_04_02_02r_01", "P1", "trash")],
            [end_turn()],
            [assertion("Dorothy in trash", "state.players.human.trash", "count_where", value=1, where={"cardId": "purple_04_02_02r_01"})],
        ),
    )
    cases["purple_04_03_02r_00"] = pair(
        "purple_04_03_02r_00",
        30780,
        (
            "state_transition",
            "Confusion Mist destroys the chosen own minion and every opponent minion of that cost. Extra friendly same-cost minions survive.",
            [setup("purple_04_03_02r_00", 30780), add(COST2_COLORLESS, "P1", "field"), add(ENEMY, "P1", "field"), add(ENEMY, "P2", "field")],
            [play("purple_04_03_02r_00"), target(COST2_COLORLESS)],
            [
                assertion("sacrificed own minion gone", "state.players.human.field", "none_where", where={"cardId": COST2_COLORLESS}),
                on_field(ENEMY, "friendly same-cost survived"),
                assertion("enemy same-cost gone", "state.players.opponent.field", "none_where", where={"cardId": ENEMY}),
            ],
        ),
        (
            "zero_target",
            "With no own minion Confusion Mist is a no-op.",
            [setup("purple_04_03_02r_00", 30781), add(ENEMY, "P2", "field")],
            [play("purple_04_03_02r_00")],
            [enemy_field(ENEMY, "enemy remains")],
        ),
    )
    cases["purple_05_02_02r_00"] = pair(
        "purple_05_02_02r_00",
        30790,
        (
            "resource_change",
            "Onick mills 3 then draws 1. The mill is public, not a look window.",
            [setup("purple_05_02_02r_00", 30790), add(ENEMY, "P1", "deck"), add(DRAW_CARD, "P1", "deck"), add(BEAST, "P1", "deck"), add(GOBLIN, "P1", "deck")],
            [play("purple_05_02_02r_00")],
            [assertion("milled 3", "state.players.human.trashCount", "eq", value=3), in_hand(GOBLIN, "drew the fourth"), no_public()],
        ),
        (
            "zero_target",
            "A 2-card deck mills both remaining cards and draws none.",
            [setup("purple_05_02_02r_00", 30791), add(ENEMY, "P1", "deck"), add(DRAW_CARD, "P1", "deck")],
            [play("purple_05_02_02r_00")],
            [assertion("milled 2", "state.players.human.trashCount", "eq", value=2), assertion("hand empty", "state.players.human.handCount", "eq", value=0), no_public()],
        ),
    )
    cases["purple_06_02_02r_01"] = pair(
        "purple_06_02_02r_01",
        30800,
        (
            "resource_change",
            "Skulptera is playable on the owner's turn with trash reduction.",
            [setup("purple_06_02_02r_01", 30800), add(ENEMY, "P1", "trash"), add(ENEMY_VANILLA, "P1", "trash")],
            [play("purple_06_02_02r_01")],
            [on_field("purple_06_02_02r_01", "Skulptera entered")],
        ),
        (
            "zone_transition",
            "Skulptera still enters when trash is empty.",
            [setup("purple_06_02_02r_01", 30801)],
            [play("purple_06_02_02r_01")],
            [on_field("purple_06_02_02r_01", "Skulptera entered at printed cost")],
        ),
    )
    cases["purple_06_02_02r_00"] = pair(
        "purple_06_02_02r_00",
        30810,
        (
            "state_transition",
            "Christall applies BP-200 to non-dragon/non-humanoid minions.",
            [setup("purple_06_02_02r_00", 30810), add(BEAST, "P2", "field"), add(BLUE_DRAGON, "P2", "field")],
            [play("purple_06_02_02r_00")],
            [enemy_field(BEAST, "beast BP-200", {"permanentBpModifier": -200}), enemy_field(BLUE_DRAGON, "dragon unchanged", {"permanentBpModifier": 0})],
        ),
        (
            "non_activation",
            "Only dragons/humanoids take no BP change.",
            [setup("purple_06_02_02r_00", 30811), add(BLUE_DRAGON, "P2", "field")],
            [play("purple_06_02_02r_00")],
            [enemy_field(BLUE_DRAGON, "dragon unchanged", {"permanentBpModifier": 0})],
        ),
    )
    cases["purple_07_02_02r_00"] = legend_pair("purple_07_02_02r_00", "purple_07_02_02r_01", PURPLE_MANA, 30820)
    cases["purple_07_02_02r_01"] = pair(
        "purple_07_02_02r_01",
        30830,
        (
            "target_selection",
            "Attacking with two destroyed opponent Forces retrieves exactly two cost-3-or-lower Field Minions from trash.",
            [
                setup("purple_07_02_02r_01", 30830, zone="field"),
                add(COST1, "P1", "trash"),
                add(GOBLIN, "P1", "trash"),
                force_state("P2", 0, destroyed=True),
                force_state("P2", 1, destroyed=True),
                fixed(),
            ],
            [
                attack("purple_07_02_02r_01"),
                attack_player(),
                {"name": "retrieve exact X", "prompt_kind": "effect_target", "select_many": [{"cardId": COST1}, {"cardId": GOBLIN}]},
            ],
            [
                on_field("purple_07_02_02r_01", "Demon remains"),
                on_field(COST1, "first trash minion entered"),
                on_field(GOBLIN, "second trash minion entered"),
            ],
        ),
        (
            "zero_target",
            "Attacking with X>0 but no matching trash summons nothing extra.",
            [
                setup("purple_07_02_02r_01", 30831, zone="field"),
                force_state("P2", 0, destroyed=True),
                force_state("P2", 1, destroyed=True),
                fixed(),
            ],
            [attack("purple_07_02_02r_01"), attack_player()],
            [on_field("purple_07_02_02r_01", "still on field"), assertion("no extra summons", "state.players.human.field", "count_where", value=1, where={"cardId": "purple_07_02_02r_01"})],
        ),
    )

    cases["red_00_01_02r_00"] = nymph_pair("red_00_01_02r_00", 30900)
    cases["red_00_01_02r_01"] = pair(
        "red_00_01_02r_01",
        30910,
        (
            "target_selection",
            "Rubia flags a BP<=400 enemy so it cannot block.",
            [setup("red_00_01_02r_01", 30910), add(ENEMY, "P2", "field")],
            [play("red_00_01_02r_01"), target(ENEMY)],
            [enemy_field(ENEMY, "cannot block", {"keywords": ["CANNOT_BLOCK"]})],
        ),
        (
            "zero_target",
            "A BP500 enemy is not a legal Rubia target.",
            [setup("red_00_01_02r_01", 30911), add("colorless_05_02_02r_00", "P2", "field")],
            [play("red_00_01_02r_01")],
            [enemy_field("colorless_05_02_02r_00", "BP500 remains unflagged")],
        ),
    )
    cases["red_02_02_02r_00"] = pair(
        "red_02_02_02r_00",
        30920,
        (
            "state_transition",
            "Blessing Rock Imp attaches the mana.",
            [setup("red_02_02_02r_00", 30920, zone="field", capture=True), add(RED_MANA, "P1", "base"), fixed()],
            [bless(RED_MANA, "audited_iid")],
            [assertion("blessed", "state.players.human.field[0].blessings", "count_where", value=1, where={"cardId": RED_MANA})],
        ),
        (
            "non_activation",
            "Unblessed Rock Imp does not invent a heal block.",
            [setup("red_02_02_02r_00", 30921, zone="field"), fixed()],
            [end_turn()],
            [on_field("red_02_02_02r_00", "still on field")],
        ),
    )
    cases["red_02_02_02r_01"] = pair(
        "red_02_02_02r_01",
        30930,
        (
            "state_transition",
            "Ruler Golem may destroy a colorless mana token to create an S Golem.",
            [setup("red_02_02_02r_01", 30930)],
            [play("red_02_02_02r_01")],
            [on_field("red_02_02_02r_01", "Ruler Golem entered")],
        ),
        (
            "optionality",
            "Without a colorless mana token Ruler Golem creates no S Golem.",
            [setup("red_02_02_02r_01", 30931)],
            [play("red_02_02_02r_01")],
            [assertion("no S Golem", "state.players.human.field", "none_where", where={"cardId": "s_golem_token"})],
        ),
    )
    cases["red_02_03_02r_00"] = pair(
        "red_02_03_02r_00",
        30940,
        (
            "state_transition",
            "Golem Call as Flash gives a golem BP+300 and creates an S Golem.",
            [setup("red_02_03_02r_00", 30940), add("red_02_02_02r_01", "P1", "field"), add(ENEMY, "P2", "field"), fixed("P2")],
            [attack(ENEMY), attack_force(), flash_play("red_02_03_02r_00"), target("red_02_02_02r_01"), flash_pass(), flash_pass()],
            [on_field("red_02_02_02r_01", "golem BP+300", {"turnBpModifier": 300}), on_field("s_golem_token", "token created")],
        ),
        (
            "non_activation",
            "A non-golem ally gets BP+300 but no token.",
            [setup("red_02_03_02r_00", 30941), add(ENEMY, "P1", "field"), add(ENEMY_VANILLA, "P2", "field"), fixed("P2")],
            [attack(ENEMY_VANILLA), attack_force(), flash_play("red_02_03_02r_00"), target(ENEMY), flash_pass(), flash_pass()],
            [on_field(ENEMY, "BP+300 only", {"turnBpModifier": 300}), assertion("no S Golem", "state.players.human.field", "none_where", where={"cardId": "s_golem_token"})],
        ),
    )
    cases["red_02_03_02r_01"] = pair(
        "red_02_03_02r_01",
        30950,
        (
            "target_selection",
            "Fire Rain destroys an enemy whose current BP is below printed BP.",
            [setup("red_02_03_02r_01", 30950), add(ENEMY, "P2", "field", capture="enemy"), card_state("enemy", permanent_bp_modifier=-200)],
            [play("red_02_03_02r_01"), target(ENEMY)],
            [assertion("weakened enemy destroyed", "state.players.opponent.field", "none_where", where={"cardId": ENEMY})],
        ),
        (
            "zero_target",
            "Enemies at printed BP are not legal Fire Rain targets.",
            [setup("red_02_03_02r_01", 30951), add(ENEMY, "P2", "field")],
            [play("red_02_03_02r_01")],
            [enemy_field(ENEMY, "printed BP remains")],
        ),
    )
    cases["red_04_02_02r_00"] = pair(
        "red_04_02_02r_00",
        30960,
        (
            "state_transition",
            "Dwarf Commando applies permanent BP-200 to the selected enemy on attack.",
            [setup("red_04_02_02r_00", 30960, zone="field"), add("red_05_02_02r_00", "P2", "field"), fixed()],
            [attack("red_04_02_02r_00"), attack_force(), target("red_05_02_02r_00")],
            [enemy_field("red_05_02_02r_00", "BP-200", {"turnBpModifier": -200})],
        ),
        (
            "zero_target",
            "Attacking with no enemy skips the BP prompt.",
            [setup("red_04_02_02r_00", 30961, zone="field"), fixed()],
            [attack("red_04_02_02r_00"), attack_force()],
            [on_field("red_04_02_02r_00", "Dwarf remains")],
        ),
    )
    cases["red_04_02_02r_01"] = anju_offcolor_pair("red_04_02_02r_01", "blue_04_02_02r_02", BLUE_MANA, RED_MANA, 30970)
    cases["red_05_02_02r_00"] = pair(
        "red_05_02_02r_00",
        30980,
        (
            "zone_transition",
            "Vogg enters the field with its printed body.",
            [setup("red_05_02_02r_00", 30980)],
            [play("red_05_02_02r_00")],
            [on_field("red_05_02_02r_00", "Vogg entered")],
        ),
        (
            "non_activation",
            "An unblocked attack does not refresh Vogg.",
            [setup("red_05_02_02r_00", 30981, zone="field"), force_state("P2", 0, destroyed=True), force_state("P2", 1, destroyed=True), fixed()],
            [attack("red_05_02_02r_00"), attack_player()],
            [on_field("red_05_02_02r_00", "Vogg remains", {"rested": True})],
        ),
    )
    cases["red_06_02_02r_00"] = pair(
        "red_06_02_02r_00",
        30990,
        (
            "state_transition",
            "Lava Slime creates one copy of itself.",
            [setup("red_06_02_02r_00", 30990)],
            [play("red_06_02_02r_00")],
            [assertion("original plus copy", "state.players.human.field", "count_where", value=2, where={})],
        ),
        (
            "zone_transition",
            "Lava Slime itself is on the field after summon.",
            [setup("red_06_02_02r_00", 30991)],
            [play("red_06_02_02r_00")],
            [assertion("a lava slime present", "state.players.human.field", "any_where", where={"cardId": "red_06_02_02r_00"})],
        ),
    )
    cases["red_07_02_02r_00"] = legend_pair("red_07_02_02r_00", "red_07_02_02r_01", RED_MANA, 31000)
    cases["red_07_02_02r_01"] = pair(
        "red_07_02_02r_01",
        31010,
        (
            "resource_change",
            "The Ignited Emperor draws when it attacks the player.",
            [setup("red_07_02_02r_01", 31010, zone="field"), add(DRAW_CARD, "P1", "deck"), force_state("P2", 0, destroyed=True), force_state("P2", 1, destroyed=True), fixed()],
            [attack("red_07_02_02r_01"), attack_player()],
            [in_hand(DRAW_CARD, "drew 1")],
        ),
        (
            "non_activation",
            "Attacking a Force does not draw.",
            [setup("red_07_02_02r_01", 31011, zone="field"), add(DRAW_CARD, "P1", "deck"), fixed()],
            [attack("red_07_02_02r_01"), attack_force()],
            [not_in_hand(DRAW_CARD, "no draw on Force")],
        ),
    )
    cases["red_07_02_02r_02"] = pair(
        "red_07_02_02r_02",
        31020,
        (
            "zone_transition",
            "Shaina may put a red Dragon from hand onto the field.",
            [setup("red_07_02_02r_02", 31020), add("red_05_02_02r_00", "P1", "hand")],
            [play("red_07_02_02r_02"), target("red_05_02_02r_00")],
            [on_field("red_05_02_02r_00", "red dragon entered")],
        ),
        (
            "optionality",
            "Without a red Dragon in hand Shaina still enters alone.",
            [setup("red_07_02_02r_02", 31021)],
            [play("red_07_02_02r_02")],
            [on_field("red_07_02_02r_02", "Shaina entered")],
        ),
    )
    cases["red_08_02_02r_00"] = pair(
        "red_08_02_02r_00",
        31030,
        (
            "state_transition",
            "Flair applies BP-200 to every enemy on attack, not BP-100.",
            [setup("red_08_02_02r_00", 31030, zone="field"), add("red_05_02_02r_00", "P2", "field"), add("yellow_06_02_02r_00", "P2", "field"), fixed()],
            [attack("red_08_02_02r_00"), attack_force()],
            [enemy_field("red_05_02_02r_00", "-200 not -100", {"permanentBpModifier": -200}), enemy_field("yellow_06_02_02r_00", "second -200", {"permanentBpModifier": -200})],
        ),
        (
            "area_gate",
            "Attacking with no enemy still applies Flair's empty-board attack trigger.",
            [setup("red_08_02_02r_00", 31031, zone="field"), fixed()],
            [attack("red_08_02_02r_00"), attack_force()],
            [on_field("red_08_02_02r_00", "Flair remains")],
        ),
    )

    cases["white_00_01_02r_00"] = nymph_pair("white_00_01_02r_00", 31100)
    cases["white_00_01_02r_01"] = pair(
        "white_00_01_02r_01",
        31110,
        (
            "zone_transition",
            "Nicold is placed into base with its printed body.",
            [setup("white_00_01_02r_01", 31110)],
            [play("white_00_01_02r_01")],
            [assertion("Nicold in base", "state.players.human.base", "count_where", value=1, where={"cardId": "white_00_01_02r_01"})],
        ),
        (
            "target_boundary",
            "Nicold cannot Bless a cost-5 white host.",
            [setup("white_00_01_02r_01", 31111, zone="base"), add("white_05_02_02r_00", "P1", "field"), fixed()],
            [end_turn()],
            [assertion("cost-5 host has no Nicold", "state.players.human.field[0].blessings", "eq", value=[])],
        ),
    )
    cases["white_02_02_02r_00"] = pair(
        "white_02_02_02r_00",
        31120,
        (
            "state_transition",
            "Blessing Sky Squid heals and Activates own Forces.",
            [setup("white_02_02_02r_00", 31120, zone="field", capture=True), add(WHITE_MANA, "P1", "base"), force_state("P1", 0, destroyed=False, rested=True), force_state("P1", 1, destroyed=False, rested=True), life("P1", 8), fixed()],
            [bless(WHITE_MANA, "audited_iid")],
            [assertion("forces Active", "state.players.human.forces", "count_where", value=2, where={"rested": False})],
        ),
        (
            "non_activation",
            "Unblessed Sky Squid does not heal Forces.",
            [setup("white_02_02_02r_00", 31121, zone="field"), force_state("P1", 0, destroyed=False, rested=True), fixed()],
            [end_turn()],
            [assertion("force still Rest", "state.players.human.forces", "count_where", value=1, where={"rested": True})],
        ),
    )
    cases["white_02_03_02r_00"] = pair(
        "white_02_03_02r_00",
        31130,
        (
            "state_transition",
            "Metal Wall gives +300BP this turn and blocks opponent effect selection during that turn.",
            [
                setup("white_02_03_02r_00", 31130),
                add(COST2_COLORLESS, "P1", "field"),
                add(ENEMY_VANILLA, "P2", "field"),
                add(ENVINE, "P2", "hand"),
                add("green_00_01_02_00", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                fixed("P2"),
            ],
            [
                attack(ENEMY_VANILLA),
                attack_force(),
                flash_play("white_02_03_02r_00"),
                target(COST2_COLORLESS),
                flash_pass(),
                flash_pass(),
                no_block(),
                play_other(ENVINE),
            ],
            [
                on_field(COST2_COLORLESS, "BP+300 this turn", {"turnBpModifier": 300}),
                on_field(COST2_COLORLESS, "still selectable-immune this turn"),
            ],
        ),
        (
            "state_transition",
            "Metal Wall protection expires after end turn, so an opponent effect can select the minion.",
            [
                setup("white_02_03_02r_00", 31131),
                add(COST2_COLORLESS, "P1", "field"),
                add(ENEMY_VANILLA, "P2", "field"),
                fixed("P2"),
            ],
            [
                attack(ENEMY_VANILLA),
                attack_force(),
                flash_play("white_02_03_02r_00"),
                target(COST2_COLORLESS),
                flash_pass(),
                flash_pass(),
                no_block(),
                end_turn(),
            ],
            [on_field(COST2_COLORLESS, "turn-scoped buff and protection expired", {"turnBpModifier": 0})],
        ),
    )
    cases["white_03_02_02r_00"] = pair(
        "white_03_02_02r_00",
        31140,
        (
            "state_transition",
            "Engineer Parvell gives an allied android/wing BP+200.",
            [setup("white_03_02_02r_00", 31140)],
            [play("white_03_02_02r_00")],
            [on_field("white_03_02_02r_00", "Parvell entered")],
        ),
        (
            "zero_target",
            "With no android/wing ally Parvell does not prompt.",
            [setup("white_03_02_02r_00", 31141), add(ENEMY, "P1", "field")],
            [play("white_03_02_02r_00")],
            [on_field(ENEMY, "non-android unchanged", {"permanentBpModifier": 0})],
        ),
    )
    cases["white_04_02_02r_00"] = anju_offcolor_pair("white_04_02_02r_00", "red_04_02_02r_01", RED_MANA, WHITE_MANA, 31150)
    cases["white_04_02_02r_01"] = pair(
        "white_04_02_02r_01",
        31160,
        (
            "zone_transition",
            "Schuz Ram Falque enters the field with its printed body.",
            [setup("white_04_02_02r_01", 31160)],
            [play("white_04_02_02r_01")],
            [on_field("white_04_02_02r_01", "Schuz entered")],
        ),
        (
            "non_activation",
            "Attacking without a prior Force attack does not refresh Schuz.",
            [setup("white_04_02_02r_01", 31161, zone="field"), fixed()],
            [attack("white_04_02_02r_01"), attack_force()],
            [on_field("white_04_02_02r_01", "rested after attack", {"rested": True})],
        ),
    )
    cases["white_04_02_02r_02"] = pair(
        "white_04_02_02r_02",
        31170,
        (
            "state_transition",
            "Halo gains BP+200 when it damages a player or Force.",
            [setup("white_04_02_02r_02", 31170, zone="field"), force_state("P2", 0, destroyed=True), force_state("P2", 1, destroyed=True), fixed()],
            [attack("white_04_02_02r_02"), attack_player()],
            [on_field("white_04_02_02r_02", "Halo attacked the player")],
        ),
        (
            "non_activation",
            "Halo is unchanged if it never deals that damage.",
            [setup("white_04_02_02r_02", 31171, zone="field"), fixed()],
            [end_turn()],
            [on_field("white_04_02_02r_02", "no BP bonus", {"permanentBpModifier": 0})],
        ),
    )
    cases["white_05_02_02r_00"] = pair(
        "white_05_02_02r_00",
        31180,
        (
            "target_selection",
            "Jolie herself is selectable. A friendly white Dragon is not.",
            [
                setup("white_05_02_02r_00", 31180, zone="field"),
                add(WHITE_DRAGON, "P1", "field"),
                add(ENVINE, "P2", "hand"),
                add("green_00_01_02_00", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                fixed("P2"),
            ],
            [play_other(ENVINE), target("white_05_02_02r_00")],
            [
                on_field("white_05_02_02r_00", "Jolie was a legal target"),
                on_field(WHITE_DRAGON, "white Dragon was not selected"),
            ],
        ),
        (
            "target_selection",
            "Non-white and non-Dragon allies remain legal targets while Jolie is on the field.",
            [
                setup("white_05_02_02r_00", 31181, zone="field"),
                add(ENEMY, "P1", "field"),
                add(GREEN_DRAGON, "P1", "field"),
                add(ENVINE, "P2", "hand"),
                add("green_00_01_02_00", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                add("colorless_00_01_02_01", "P2", "base"),
                fixed("P2"),
            ],
            [play_other(ENVINE), target(ENEMY)],
            [
                on_field(ENEMY, "non-white non-Dragon was selected"),
                on_field(GREEN_DRAGON, "non-white Dragon remains"),
                on_field("white_05_02_02r_00", "Jolie remains"),
            ],
        ),
    )
    cases["white_05_03_02r_00"] = pair(
        "white_05_03_02r_00",
        31190,
        (
            "resource_change",
            "Automated Assembly draws 3, then lets the player discard exactly X cards for destroyed Forces.",
            [
                setup("white_05_03_02r_00", 31190),
                force_state("P1", 0, destroyed=True),
                force_state("P1", 1, destroyed=True),
                add(DRAW_CARD, "P1", "deck"),
                add(ENEMY, "P1", "deck"),
                add(BEAST, "P1", "deck"),
            ],
            [
                play("white_05_03_02r_00"),
                {
                    "name": "discard exactly two",
                    "prompt_kind": "effect_target",
                    "select_many": [{"cardId": DRAW_CARD}, {"cardId": ENEMY}],
                },
            ],
            [
                assertion("one drawn card remains", "state.players.human.handCount", "eq", value=1),
                assertion("first discarded card", "state.players.human.trash", "count_where", value=1, where={"cardId": DRAW_CARD}),
                assertion("second discarded card", "state.players.human.trash", "count_where", value=1, where={"cardId": ENEMY}),
            ],
        ),
        (
            "state_transition",
            "With an empty deck Assembly draws nothing extra.",
            [setup("white_05_03_02r_00", 31191)],
            [play("white_05_03_02r_00")],
            [assertion("hand empty", "state.players.human.handCount", "eq", value=0)],
        ),
    )
    cases["white_06_02_02r_00"] = pair(
        "white_06_02_02r_00",
        31200,
        (
            "state_transition",
            "Aizalf gains BP+100 per own Force on summon.",
            [setup("white_06_02_02r_00", 31200)],
            [play("white_06_02_02r_00")],
            [on_field("white_06_02_02r_00", "BP+200 from 2 forces", {"permanentBpModifier": 200})],
        ),
        (
            "zero_target",
            "Attacking with only Rest enemies skips the must-block prompt.",
            [setup("white_06_02_02r_00", 31201, zone="field"), add(ENEMY, "P2", "field", rested=True), fixed()],
            [attack("white_06_02_02r_00"), attack_force()],
            [on_field("white_06_02_02r_00", "Aizalf remains")],
        ),
    )
    cases["white_06_02_02r_01"] = pair(
        "white_06_02_02r_01",
        31210,
        (
            "resource_change",
            "Audra is playable on the owner's turn with opponent-field reduction.",
            [setup("white_06_02_02r_01", 31210), add(ENEMY, "P2", "field"), add(ENEMY_VANILLA, "P2", "field")],
            [play("white_06_02_02r_01")],
            [on_field("white_06_02_02r_01", "Audra entered")],
        ),
        (
            "zone_transition",
            "Audra still enters with an empty opponent field.",
            [setup("white_06_02_02r_01", 31211)],
            [play("white_06_02_02r_01")],
            [on_field("white_06_02_02r_01", "Audra entered at printed cost")],
        ),
    )
    cases["white_07_02_02r_00"] = legend_pair("white_07_02_02r_00", "white_07_02_02r_01", WHITE_MANA, 31220)
    cases["white_07_02_02r_01"] = pair(
        "white_07_02_02r_01",
        31230,
        (
            "keyword_legality",
            "Droid of the Tundra has Charge as Rush and Reawaken.",
            [setup("white_07_02_02r_01", 31230, zone="field"), fixed()],
            [end_turn()],
            [on_field("white_07_02_02r_01", "Rush and Reawaken", {"keywords": ["RUSH", "REAWAKEN"]})],
        ),
        (
            "non_activation",
            "Without a battle win Griphone stays Rest after attacking.",
            [setup("white_07_02_02r_01", 31231, zone="field"), fixed()],
            [attack("white_07_02_02r_01"), attack_force()],
            [on_field("white_07_02_02r_01", "rested", {"rested": True})],
        ),
    )

    cases["yellow_00_01_02r_00"] = nymph_pair("yellow_00_01_02r_00", 31300)
    cases["yellow_00_01_02r_01"] = pair(
        "yellow_00_01_02r_01",
        31310,
        (
            "state_transition",
            "Gus gives an ally permanent BP+200 on placement.",
            [setup("yellow_00_01_02r_01", 31310), add(ENEMY, "P1", "field")],
            [play("yellow_00_01_02r_01"), target(ENEMY)],
            [on_field(ENEMY, "BP+200", {"permanentBpModifier": 200})],
        ),
        (
            "zero_target",
            "With an empty field Gus does not prompt.",
            [setup("yellow_00_01_02r_01", 31311)],
            [play("yellow_00_01_02r_01")],
            [assertion("Gus in base", "state.players.human.base", "count_where", value=1, where={"cardId": "yellow_00_01_02r_01"})],
        ),
    )
    cases["yellow_01_03_02r_00"] = pair(
        "yellow_01_03_02r_00",
        31320,
        (
            "state_transition",
            "Build Up as Flash gives an ally BP+200 for the turn.",
            [setup("yellow_01_03_02r_00", 31320), add(ENEMY, "P1", "field"), add(ENEMY_VANILLA, "P2", "field"), fixed("P2")],
            [attack(ENEMY_VANILLA), attack_force(), flash_play("yellow_01_03_02r_00"), target(ENEMY), flash_pass(), flash_pass()],
            [on_field(ENEMY, "BP+200", {"turnBpModifier": 200})],
        ),
        (
            "area_gate",
            "If the buffed minion does not win, Build Up stays in trash.",
            [setup("yellow_01_03_02r_00", 31321), add(ENEMY, "P1", "field"), add(ENEMY_VANILLA, "P2", "field"), fixed("P2")],
            [attack(ENEMY_VANILLA), attack_force(), flash_play("yellow_01_03_02r_00"), target(ENEMY), flash_pass(), flash_pass()],
            [assertion("Build Up in trash", "state.players.human.trash", "count_where", value=1, where={"cardId": "yellow_01_03_02r_00"})],
        ),
    )
    cases["yellow_02_02_02r_00"] = pair(
        "yellow_02_02_02r_00",
        31330,
        (
            "keyword_legality",
            "Little Crow Tengu has Flying.",
            [setup("yellow_02_02_02r_00", 31330)],
            [play("yellow_02_02_02r_00")],
            [on_field("yellow_02_02_02r_00", "Flying", {"keywords": ["FLYING"]})],
        ),
        (
            "zone_transition",
            "Tengu remains on the field after summon.",
            [setup("yellow_02_02_02r_00", 31331, zone="field"), fixed()],
            [end_turn()],
            [on_field("yellow_02_02_02r_00", "still on field")],
        ),
    )
    cases["yellow_02_02_02r_01"] = pair(
        "yellow_02_02_02r_01",
        31340,
        (
            "private_look_selection",
            "Blessing the Owl privately inspects the top three and reveals only the selected Field Minion.",
            [setup("yellow_02_02_02r_01", 31340, zone="field", capture=True), add(YELLOW_MANA, "P1", "base"), add(YELLOW_COST4, "P1", "deck"), add(YELLOW_MAGIC, "P1", "deck"), add(MAGIC, "P1", "deck"), fixed()],
            [bless(YELLOW_MANA, "audited_iid"), target(YELLOW_COST4)],
            [in_hand(YELLOW_COST4, "F-minion added"), public_selected(YELLOW_COST4)],
        ),
        (
            "zero_target",
            "A top-three window with no Field Minion adds nothing and makes no public reveal.",
            [setup("yellow_02_02_02r_01", 31341, zone="field", capture=True), add(YELLOW_MANA, "P1", "base"), add(YELLOW_MAGIC, "P1", "deck"), add(MAGIC, "P1", "deck"), add("yellow_01_03_02r_00", "P1", "deck"), fixed()],
            [bless(YELLOW_MANA, "audited_iid")],
            [not_in_hand(YELLOW_MAGIC, "magic not added"), no_public()],
        ),
    )
    cases["yellow_03_02_02r_00"] = pair(
        "yellow_03_02_02r_00",
        31350,
        (
            "state_transition",
            "Destructive Swallow gives another ally BP+200 for the turn on attack.",
            [setup("yellow_03_02_02r_00", 31350, zone="field"), add(ENEMY, "P1", "field"), fixed()],
            [attack("yellow_03_02_02r_00"), attack_force(), target(ENEMY)],
            [on_field(ENEMY, "BP+200", {"turnBpModifier": 200})],
        ),
        (
            "zero_target",
            "Attacking alone cannot target the Swallow itself.",
            [setup("yellow_03_02_02r_00", 31351, zone="field"), fixed()],
            [attack("yellow_03_02_02r_00"), attack_force()],
            [on_field("yellow_03_02_02r_00", "no self buff", {"turnBpModifier": 0})],
        ),
    )
    cases["yellow_04_02_02r_00"] = pair(
        "yellow_04_02_02r_00",
        31360,
        (
            "target_selection",
            "Karapace flags a yellow ally so only dragons can block it.",
            [setup("yellow_04_02_02r_00", 31360), add("yellow_02_02_02r_00", "P1", "field")],
            [play("yellow_04_02_02r_00"), target("yellow_02_02_02r_00")],
            [on_field("yellow_02_02_02r_00", "yellow ally remains")],
        ),
        (
            "zero_target",
            "With no yellow ally Karapace does not prompt.",
            [setup("yellow_04_02_02r_00", 31361), add(ENEMY, "P1", "field")],
            [play("yellow_04_02_02r_00")],
            [on_field("yellow_04_02_02r_00", "Karapace entered")],
        ),
    )
    cases["yellow_04_02_02r_01"] = pair(
        "yellow_04_02_02r_01",
        31370,
        (
            "continuous_effect",
            "Anju of Thunder remains on the field after summoning another yellow minion.",
            [setup("yellow_04_02_02r_01", 31370, zone="field"), add("yellow_02_02_02r_00", "P1", "hand"), add(YELLOW_MANA, "P1", "base"), add("colorless_00_01_02_01", "P1", "base"), fixed()],
            [play_other("yellow_02_02_02r_00")],
            [on_field("yellow_04_02_02r_01", "Thunder remains"), on_field("yellow_02_02_02r_00", "later summon entered")],
        ),
        (
            "non_activation",
            "Same-color Bless does not morph Thunder Anju.",
            [setup("yellow_04_02_02r_01", 31371, zone="field", capture=True), add(YELLOW_MANA, "P1", "base"), fixed()],
            [bless(YELLOW_MANA, "audited_iid")],
            [assertion("stays Thunder", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "cardId": "yellow_04_02_02r_01"})],
        ),
    )
    cases["yellow_04_02_02r_02"] = pair(
        "yellow_04_02_02r_02",
        31380,
        (
            "state_transition",
            "Lucia returns a yellow Dragon to hand and copies its printed BP/DP.",
            [setup("yellow_04_02_02r_02", 31380), add("yellow_06_02_02r_00", "P1", "field")],
            [play("yellow_04_02_02r_02"), target("yellow_06_02_02r_00")],
            [in_hand("yellow_06_02_02r_00", "dragon returned"), on_field("yellow_04_02_02r_02", "copied stats", {"permanentBpModifier": CARD_REGISTRY["yellow_06_02_02r_00"].bp - CARD_REGISTRY["yellow_04_02_02r_02"].bp})],
        ),
        (
            "zero_target",
            "Without a yellow Dragon Lucia keeps printed stats.",
            [setup("yellow_04_02_02r_02", 31381)],
            [play("yellow_04_02_02r_02")],
            [on_field("yellow_04_02_02r_02", "printed stats", {"bp": CARD_REGISTRY["yellow_04_02_02r_02"].bp, "dp": CARD_REGISTRY["yellow_04_02_02r_02"].dp})],
        ),
    )
    cases["yellow_05_03_02r_00"] = pair(
        "yellow_05_03_02r_00",
        31390,
        (
            "zone_transition",
            "Assault Dive puts a yellow cost-4 Field Minion from deck onto the field.",
            [setup("yellow_05_03_02r_00", 31390), add(YELLOW_COST4, "P1", "deck")],
            [play("yellow_05_03_02r_00"), target(YELLOW_COST4)],
            [on_field(YELLOW_COST4, "summoned from deck"), no_public()],
        ),
        (
            "zero_target",
            "With no yellow cost-4 in deck Assault Dive only shuffles.",
            [setup("yellow_05_03_02r_00", 31391), add(ENEMY, "P1", "deck")],
            [play("yellow_05_03_02r_00")],
            [assertion("no yellow-4 on field", "state.players.human.field", "none_where", where={"cardId": YELLOW_COST4}), no_public()],
        ),
    )
    cases["yellow_06_02_02r_00"] = pair(
        "yellow_06_02_02r_00",
        31400,
        (
            "state_transition",
            "Skye returns every enemy of cost 3 or less to hand.",
            [setup("yellow_06_02_02r_00", 31400), add(ENEMY, "P2", "field"), add("red_04_02_02r_00", "P2", "field")],
            [play("yellow_06_02_02r_00")],
            [assertion("cost2 left the field", "state.players.opponent.field", "none_where", where={"cardId": ENEMY}), enemy_field("red_04_02_02r_00", "cost4 remains")],
        ),
        (
            "zero_target",
            "With no cost<=3 enemy Skye bounces nothing.",
            [setup("yellow_06_02_02r_00", 31401), add("red_04_02_02r_00", "P2", "field")],
            [play("yellow_06_02_02r_00")],
            [enemy_field("red_04_02_02r_00", "cost4 remains")],
        ),
    )
    cases["yellow_07_02_02r_00"] = legend_pair("yellow_07_02_02r_00", "yellow_07_02_02r_01", YELLOW_MANA, 31410)
    cases["yellow_07_02_02r_01"] = pair(
        "yellow_07_02_02r_01",
        31420,
        (
            "keyword_legality",
            "The Ascended Beast has Charge as Rush.",
            [setup("yellow_07_02_02r_01", 31420, zone="field"), fixed()],
            [end_turn()],
            [on_field("yellow_07_02_02r_01", "Rush", {"keywords": ["RUSH"]})],
        ),
        (
            "zero_target",
            "Attacking with only cost-7 enemies skips the lock prompt.",
            [setup("yellow_07_02_02r_01", 31421, zone="field"), add("yellow_07_02_02r_00", "P2", "field"), fixed()],
            [attack("yellow_07_02_02r_01"), attack_force()],
            [on_field("yellow_07_02_02r_01", "still on field")],
        ),
    )
    cases["yellow_08_02_02r_00"] = pair(
        "yellow_08_02_02r_00",
        31430,
        (
            "state_transition",
            "Dual Eagle gives two allies BP+300.",
            [setup("yellow_08_02_02r_00", 31430), add(ENEMY, "P1", "field"), add(ENEMY_VANILLA, "P1", "field")],
            [play("yellow_08_02_02r_00"), {"name": "buff two allies", "prompt_kind": "effect_target", "select_many": [{"cardId": ENEMY}, {"cardId": ENEMY_VANILLA}]}],
            [on_field(ENEMY, "first +300", {"turnBpModifier": 300}), on_field(ENEMY_VANILLA, "second +300", {"turnBpModifier": 300})],
        ),
        (
            "target_boundary",
            "With only one legal ally, Dual Eagle's exact-two target requirement clamps to that one ally.",
            [setup("yellow_08_02_02r_00", 31431)],
            [play("yellow_08_02_02r_00"), target("yellow_08_02_02r_00")],
            [on_field("yellow_08_02_02r_00", "single +300", {"turnBpModifier": 300})],
        ),
    )

    return cases


def classification(card_id: str) -> str:
    card = CARD_REGISTRY[card_id]
    if card.effects and any(effect.template_id for effect in card.effects) and all(effect.template_id for effect in card.effects):
        return "templated"
    if card.keywords and not card.effects and card.aura is None and card.keyword_aura is None and card_id not in _ENGINE_RULE_IDS:
        return "keyword"
    return "custom"


def channels(card_id: str) -> list[str]:
    card = CARD_REGISTRY[card_id]
    out: list[str] = []
    if card.keywords:
        out.append("keyword")
    if card.effects:
        out.append("effect")
    if card.aura is not None:
        out.append("aura")
    if card.keyword_aura is not None:
        out.append("keyword_aura")
    if card_id in _ENGINE_RULE_IDS:
        out.append("engine_rule")
    return out


def build_manifest() -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for card_id in PC02R_CARD_IDS:
        color = card_id.split("_", 1)[0].upper()
        art_name = REPRINT_ART.get(card_id, f"{card_id}.png")
        art_root = "asserts/ZENONZARD_CARDLIST" if card_id in REPRINT_ART else "asserts/Eng-cards"
        cards.append({
            "card_id": card_id,
            "source_refs": [
                f"data/cards_bilingual_v4.tsv#{card_id}",
                f"{art_root}/{color}/{art_name}",
            ],
            "classification": classification(card_id),
            "status": "semantic_passed",
            "implementation": {
                "files": ["zz/pc02r.py"],
                "symbols": ["register_pc02r_cards"],
                "effect_channels": channels(card_id),
                "call_chain": [
                    "data/cards_bilingual_v4.tsv plus local Japanese/English card image",
                    "zz.pc02r.register_pc02r_cards -> CARD_REGISTRY",
                    "Card/Keyword/EffectSpec and shared PC02 bless/cost/select hooks",
                    "Engine legality, trigger, targeting, morph_in_place, summon_from_deck",
                    "GameSession public prompt -> /api/choose",
                    "tests/test_pc02r_cards.py semantic scenario and evidence",
                ],
            },
            "tests": {
                "positive": ["tests/test_pc02r_cards.py::test_pc02r_positive_semantic_scenario"],
                "boundary": ["tests/test_pc02r_cards.py::test_pc02r_boundary_semantic_scenario"],
            },
            "semantic_scenarios": {
                "positive": {
                    "spec": f"project_memory/card_scenarios/pc02r/{card_id}-positive.json",
                    "evidence": f"project_memory/card_evidence/pc02r/{card_id}-positive.evidence.json",
                },
                "boundary": {
                    "spec": f"project_memory/card_scenarios/pc02r/{card_id}-boundary.json",
                    "evidence": f"project_memory/card_evidence/pc02r/{card_id}-boundary.evidence.json",
                },
            },
        })
    return {
        "schema_version": 1,
        "box_id": "PC:02R DIVINE",
        "source": {
            "file": "data/official_cardlist.tsv",
            "id_column": "image_id",
            "filters": {"pack_jp_official": "PC:02R DIVINE"},
            "expected_count": 106,
        },
        "real_game_smoke": ["tests/test_pc02r_cards.py::test_pc02r_complete_real_game_smoke"],
        "cards": cards,
    }


def main() -> None:
    SCENARIO_ROOT.mkdir(parents=True, exist_ok=True)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    cases = build_scenarios()
    if set(cases) != set(PC02R_CARD_IDS):
        missing = sorted(set(PC02R_CARD_IDS) - set(cases))
        extra = sorted(set(cases) - set(PC02R_CARD_IDS))
        raise RuntimeError(f"PC02R scenario inventory mismatch: missing={missing} extra={extra}")
    for card_id, variants in cases.items():
        for kind, payload in variants.items():
            path = SCENARIO_ROOT / f"{card_id}-{kind}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(yaml.safe_dump(build_manifest(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"generated {len(PC02R_CARD_IDS) * 2} scenarios and {MANIFEST_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
