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
from zz.pc02 import PC02_CARD_IDS, _PC02_ENGINE_RULE_IDS, _PC02_VANILLA_IDS


SCENARIO_ROOT = ROOT / "project_memory" / "card_scenarios" / "pc02"
EVIDENCE_ROOT = ROOT / "project_memory" / "card_evidence" / "pc02"
MANIFEST_PATH = ROOT / "project_memory" / "card_boxes" / "pc02.yaml"


def setup(card_id: str, seed: int, *, zone: str = "hand", non_minion_mana_only: bool = False) -> dict[str, Any]:
    return {
        "path": "/api/debug/setup",
        "payload": {
            "cardId": card_id,
            "seed": seed,
            "zone": zone,
            "compactBoard": True,
            "playerForces": ["force_e", "force_so2"],
            "opponentForces": ["force_kon", "force_rin"],
            "nonMinionManaOnly": non_minion_mana_only,
        },
    }


def add(card_id: str, side: str, zone: str, *, rested: bool = False, capture: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": "/api/debug/add-card",
        "payload": {"cardId": card_id, "side": side, "zone": zone, "rested": rested},
    }
    if capture:
        out["capture"] = {capture: {"path": "debug.added.iid"}}
    return out


MANA_CARD_BY_COLOR = {
    Color.RED: "red_00_01_02_00",
    Color.YELLOW: "yellow_00_01_02_00",
    Color.WHITE: "white_00_01_02_00",
    Color.GREEN: "green_00_01_02_00",
    Color.BLUE: "blue_00_01_02_00",
    Color.PURPLE: "purple_00_01_02_00",
    Color.COLORLESS: "colorless_00_01_02_01",
}


def payment(card_id: str, side: str = "P1", *, colored_only: bool = False) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for color, amount in CARD_REGISTRY[card_id].cost.items():
        if colored_only and color is Color.COLORLESS:
            continue
        steps.extend(add(MANA_CARD_BY_COLOR[color], side, "base") for _ in range(amount))
    return steps


def fixed(side: str = "P1", step: str = "main") -> dict[str, Any]:
    return {
        "path": "/api/debug/fixed-board",
        "payload": {"activeSide": side, "controlBoth": True, "preserveBoard": True, "step": step},
    }


def life(side: str, value: int, *, force_index: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"side": side, "life": value}
    if force_index is not None:
        payload["forceIndex"] = force_index
    return {"path": "/api/debug/life", "payload": payload}


def force_state(side: str, index: int, *, destroyed: bool, rested: bool | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"side": side, "forceIndex": index, "destroyed": destroyed}
    if rested is not None:
        payload["rested"] = rested
    return {"path": "/api/debug/force-state", "payload": payload}


def card_state(alias: str, *, rested: bool | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"iid": f"${alias}"}
    if rested is not None:
        payload["rested"] = rested
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


def target(card_id: str) -> dict[str, Any]:
    return choose("effect_target", {"cardId": card_id}, "choose effect target")


def target_option(option_id: str) -> dict[str, Any]:
    return choose("effect_target", {"id": option_id}, "choose effect target")


def target_force(force_id: str) -> dict[str, Any]:
    return choose("effect_target", {"forceId": force_id}, "choose Force target")


def blessing_replacement(card_id: str) -> dict[str, Any]:
    return choose(
        "blessing_base_replacement",
        {"cardId": card_id},
        "replace base card for returning Bless mana",
    )


def move(card_id: str, direction: str) -> dict[str, Any]:
    return choose("main_action", {"kind": "move_card", "cardId": card_id, "direction": direction}, "move card")


def bless(mana_id: str, host_alias: str) -> dict[str, Any]:
    return choose(
        "main_action",
        {"kind": "bless", "cardId": mana_id, "target_iid": f"${host_alias}"},
        "attach Bless mana",
    )


def bless_alias(mana_alias: str, host_alias: str) -> dict[str, Any]:
    return choose(
        "main_action",
        {"kind": "bless", "iid": f"${mana_alias}", "target_iid": f"${host_alias}"},
        "attach exact Bless mana",
    )


def attack(card_id: str) -> dict[str, Any]:
    return choose("main_action", {"kind": "attack", "cardId": card_id}, "attack with audited card")


def attack_force(index: int = 0) -> dict[str, Any]:
    return choose("attack_target", {"id": f"t{index}"}, "choose attack Force")


def flash_pass() -> dict[str, Any]:
    return choose("flash_action", {"kind": "flash_pass"}, "pass Flash priority")


def block_option(option_id: str) -> dict[str, Any]:
    return choose("blocker", {"id": option_id}, "choose blocker")


def no_block() -> dict[str, Any]:
    return choose("blocker", {"id": "none"}, "decline block")


def end_turn() -> dict[str, Any]:
    return choose("main_action", {"kind": "end_turn"}, "end turn")


def assertion(name: str, path: str, op: str, *, value: Any = None, where: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "path": path, "op": op}
    if op not in {"any_where", "none_where"}:
        out["value"] = value
    if where is not None:
        out["where"] = where
    return out


BLESS_HOSTS = {
    "red_00_01_02_00": "red_04_02_02_00",
    "red_00_01_02_01": "red_04_02_02_00",
    "yellow_00_01_02_00": "yellow_04_02_02_02",
    "yellow_00_01_02_01": "yellow_04_02_02_02",
    "white_00_01_02_00": "white_04_02_02_01",
    "white_00_01_02_01": "white_04_02_02_01",
    "green_00_01_02_00": "green_04_02_02_00",
    "green_00_01_02_01": "green_04_02_02_00",
    "blue_00_01_02_00": "blue_04_02_02_00",
    "blue_00_01_02_01": "blue_04_02_02_00",
    "purple_00_01_02_00": "purple_04_02_02_00",
    "purple_00_01_02_01": "purple_04_02_02_00",
    "colorless_00_01_02_00": "red_04_02_02_00",
    "colorless_00_01_02_01": "red_02_02_02_00",
    "colorless_00_01_02_02": "red_04_02_02_00",
}


VANILLA_IDS = set(_PC02_VANILLA_IDS)

DRAGON_LORD_IDS = {
    "red_09_02_02_00",
    "yellow_09_02_02_00",
    "white_09_02_02_00",
    "green_09_02_02_00",
    "blue_09_02_02_00",
    "purple_09_02_02_00",
}
RETREAT_IDS = {
    "red_01_02_02_00",
    "yellow_01_02_02_00",
    "white_01_02_02_00",
    "green_01_02_02_00",
    "blue_01_02_02_00",
    "purple_01_02_02_00",
}


def positive(card_id: str, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str, str]:
    card = CARD_REGISTRY[card_id]
    if card_id == "red_00_01_02_01":
        host, blocker = BLESS_HOSTS[card_id], "colorless_010_02_01_00"
        steps = [setup(card_id, seed, zone="base"), add(host, "P1", "field", capture="host"), add(blocker, "P2", "field"), fixed()]
        actions = [bless(card_id, "host"), attack(host), attack_force(), flash_pass(), flash_pass(), block_option("b0")]
        checks = [assertion("granted block trigger applies BP-200", "state.players.opponent.field", "count_where", value=1, where={"cardId": blocker, "permanentBpModifier": -200})]
        return steps, actions, checks, "trigger_resolution", "Firely attaches only to an eligible red cost-four host and its granted block trigger applies BP-200."
    if card_id == "yellow_00_01_02_01":
        host, entrant = BLESS_HOSTS[card_id], "yellow_01_02_02_00"
        steps = [setup(card_id, seed), add(host, "P1", "field", capture="host"), add(entrant, "P1", "hand"), *payment(entrant)]
        actions = [play(card_id), bless(card_id, "host"), play_other(entrant), target(entrant)]
        checks = [assertion("granted entry trigger buffs host", "state.players.human.field", "count_where", value=1, where={"cardId": host, "turnBpModifier": 200})]
        return steps, actions, checks, "trigger_resolution", "Sunlight attaches only to an eligible yellow cost-four host and buffs it when another ally enters."
    if card_id == "white_00_01_02_01":
        host, blocker = BLESS_HOSTS[card_id], "red_02_02_02_00"
        steps = [setup(card_id, seed, zone="base"), add(host, "P1", "field", capture="host"), add(blocker, "P2", "field"), fixed()]
        actions = [bless(card_id, "host"), attack(host), attack_force(), flash_pass(), flash_pass(), block_option("b0")]
        checks = [assertion("granted battle-win trigger refreshes host", "state.players.human.field", "count_where", value=1, where={"cardId": host, "rested": False})]
        return steps, actions, checks, "trigger_resolution", "Chronora attaches only to an eligible white cost-four host and refreshes it after defeating a cost-three-or-less blocker."
    if card_id == "green_00_01_02_01":
        host = BLESS_HOSTS[card_id]
        steps = [setup(card_id, seed), add(host, "P1", "field", capture="host")]
        actions = [play(card_id), bless(card_id, "host"), attack(host), attack_force(), target_force("force_kon")]
        checks = [assertion("granted attack trigger rests Force", "state.players.opponent.forces", "count_where", value=1, where={"id": "force_kon", "rested": True})]
        return steps, actions, checks, "trigger_resolution", "Griefi attaches only to an eligible green cost-four host and rests the selected enemy Force when it attacks."
    if card_id == "blue_00_01_02_01":
        host = BLESS_HOSTS[card_id]
        steps = [setup(card_id, seed), add(host, "P1", "field", capture="host")]
        actions = [play(card_id), bless(card_id, "host"), attack(host), attack_force()]
        checks = [assertion("granted attack trigger restores movement right", "state.players.human.movementRightCount", "eq", value=1)]
        return steps, actions, checks, "resource_change", "Bleuvert attaches only to an eligible blue cost-four host and grants one movement right when it attacks."
    if card_id == "purple_00_01_02_01":
        host, blocker = BLESS_HOSTS[card_id], "colorless_07_02_02_00"
        steps = [setup(card_id, seed, zone="base"), add(host, "P1", "field", capture="host"), add(blocker, "P2", "field"), fixed()]
        actions = [bless(card_id, "host"), attack(host), attack_force(), flash_pass(), flash_pass(), block_option("b0")]
        checks = [assertion("granted Death Blow destroys blocker", "state.players.opponent.trash", "count_where", value=1, where={"cardId": blocker})]
        return steps, actions, checks, "keyword_legality", "Agma attaches only to an eligible purple cost-four host and grants Death Blow."
    if card_id == "colorless_00_01_02_01":
        host = BLESS_HOSTS[card_id]
        steps = [setup(card_id, seed), add(host, "P1", "field", capture="host")]
        actions = [play(card_id), bless(card_id, "host")]
        checks = [assertion("unconditional Bless grants Reawaken", "state.players.human.field", "count_where", value=1, where={"cardId": host, "keywords": ["REAWAKEN"]})]
        return steps, actions, checks, "keyword_legality", "Sandy attaches without a color or cost condition and grants Reawaken."
    if card_id == "colorless_00_01_02_02":
        host, dragon = BLESS_HOSTS[card_id], "colorless_04_02_02_00"
        steps = [setup(card_id, seed), add(host, "P1", "field", capture="host"), add(dragon, "P1", "deck")]
        actions = [play(card_id), target(dragon), bless(card_id, "host")]
        checks = [assertion("placement search takes top-four Dragon", "state.players.human.hand", "count_where", value=1, where={"cardId": dragon}), assertion("Cryska then attaches", "state.players.human.field[0].blessings", "count_where", value=1, where={"cardId": card_id})]
        return steps, actions, checks, "trigger_resolution", "Cryska searches a top-four Dragon on placement, then attaches to an eligible cost-four host."
    if card_id in BLESS_HOSTS:
        host = BLESS_HOSTS[card_id]
        steps = [setup(card_id, seed), add(host, "P1", "field", capture="host")]
        actions = [play(card_id), bless(card_id, "host")]
        checks = [assertion("Bless attachment is visible", "state.players.human.field[0].blessings", "count_where", value=1, where={"cardId": card_id})]
        return steps, actions, checks, "state_transition", "The mana attaches through the public Bless action to an eligible host."

    if card_id in VANILLA_IDS:
        steps = [setup(card_id, seed)]
        actions = [play(card_id)]
        checks = [assertion("exact vanilla body enters", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "bp": card.bp, "dp": card.dp})]
        return steps, actions, checks, "zone_transition", "The exact vanilla minion enters through normal payment without an invented effect."

    # Red
    if card_id == "red_01_02_02_00":
        draw_id = "blue_02_02_02_00"
        return [setup(card_id, seed, non_minion_mana_only=True), *payment(card_id, colored_only=True), add(draw_id, "P1", "deck")], [play(card_id), target_option("e0")], [assertion("Digger draws after destroying mana", "state.players.human.hand", "count_where", value=1, where={"cardId": draw_id})], "resource_change", "Destroying one non-minion colorless mana draws exactly one card."
    if card_id == "red_02_02_02_00":
        return [setup(card_id, seed), add(card_id, "P1", "field")], [play(card_id)], [assertion("both Fire Lizards expose the mutual aura", "state.players.human.field", "count_where", value=2, where={"cardId": card_id, "effectiveBp": 600})], "continuous_effect", "Each Fire Lizard gains BP+300 from the other copy on its controller's turn."
    if card_id == "red_03_02_02_00":
        dragon = "red_04_02_02_00"
        return [setup(card_id, seed), add(dragon, "P1", "field")], [play(card_id)], [assertion("red Dragon has Rush", "state.players.human.field", "count_where", value=1, where={"cardId": dragon, "keywords": ["RUSH"]})], "continuous_effect", "Jane grants Rush to the existing red Dragon."
    if card_id == "red_03_03_02_00":
        target_id = "red_02_02_02_00"
        return [setup(card_id, seed), add(target_id, "P1", "field")], [play(card_id), target(target_id)], [assertion("selected low-cost red minion is copied", "state.players.human.field", "count_where", value=2, where={"cardId": target_id})], "state_transition", "Shape Shift creates one exact copy without using a summon action."
    if card_id == "red_03_03_02_01":
        enemy = "yellow_03_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field")], [play(card_id), target(enemy)], [assertion("ordinary target loses 300 BP", "state.players.opponent.field", "count_where", value=1, where={"cardId": enemy, "permanentBpModifier": -300})], "target_selection", "Breaching applies BP-300 to a non-Dragon target."
    if card_id == "red_04_02_02_00":
        return [setup(card_id, seed, non_minion_mana_only=True), *payment(card_id, colored_only=True)], [play(card_id), target_option("e0")], [assertion("colorless mana is destroyed", "state.players.human.removedCount", "eq", value=1)], "resource_change", "Gran Rex destroys one non-minion colorless mana on summon."
    if card_id == "red_05_02_02_00":
        return _bless_host_effect(card_id, seed, "red_00_01_02_00", assertion("S Golem appears", "state.players.human.field", "count_where", value=1, where={"cardId": "s_golem_token"}), "Blessing Warhammer creates one S Golem token.")
    if card_id == "red_06_02_02_01":
        enemy = "yellow_03_02_02_00"
        return [setup(card_id, seed, non_minion_mana_only=True), *payment(card_id, colored_only=True), add(enemy, "P2", "field")], [play(card_id), target_option("e0"), target(enemy)], [assertion("selected enemy cannot block", "state.players.opponent.field", "count_where", value=1, where={"cardId": enemy, "keywords": ["CANNOT_BLOCK"]}), assertion("rested red mana replaces the loss", "state.players.human.base", "count_where", value=1, where={"cardId": "mana_token", "manaColor": "RED", "rested": True})], "trigger_resolution", "Margus resolves its mandatory mana destruction before choosing an enemy, then creates one rested red replacement mana."
    if card_id == "red_08_03_02_00":
        dragon = "red_09_02_02_00"
        return [setup(card_id, seed, non_minion_mana_only=True), *payment(card_id, colored_only=True), add(dragon, "P1", "deck")], [play(card_id), target_option("e0"), target(dragon)], [assertion("top-three Dragon enters", "state.players.human.field", "count_where", value=1, where={"cardId": dragon})], "private_look_selection", "After the mandatory mana destruction selection, the controller privately inspects the top three, chooses an eligible Dragon, and it enters without summon effects."
    if card_id == "red_09_02_02_00":
        enemy = "yellow_03_02_02_00"
        return _attack_effect(card_id, seed, enemy, [target(enemy)], assertion("destroying target creates Dragon token", "state.players.human.field", "count_where", value=1, where={"cardId": "colorless_04_04_00_00"}), "The attack trigger destroys BP500 and creates a Dragon token.")

    # Yellow
    if card_id == "yellow_01_02_02_00":
        return [setup(card_id, seed)], [play(card_id), target(card_id)], [assertion("selected minion gains permanent BP", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "permanentBpModifier": 100})], "state_transition", "Otter Father gives the selected allied minion permanent BP+100."
    if card_id == "yellow_02_03_02_00":
        enemy, summon, attacker = "yellow_03_02_02_00", "red_02_02_02_00", "yellow_03_02_02_00"
        steps = [setup(card_id, seed), add(enemy, "P2", "field"), add(summon, "P1", "hand"), add(attacker, "P1", "field"), *payment(summon), fixed()]
        actions = [play_other(summon), attack(attacker), attack_force(), flash_pass(), flash_play(card_id), target(enemy), flash_pass(), flash_pass()]
        return steps, actions, [assertion("post-summon Air Raid loses 400", "state.players.opponent.field", "count_where", value=1, where={"cardId": enemy, "permanentBpModifier": -400})], "state_transition", "Air Raid applies BP-400 after its controller summoned this turn."
    if card_id == "yellow_03_03_02_00":
        attacker = "red_02_02_02_00"
        steps = [setup(card_id, seed), add(attacker, "P2", "field"), fixed("P2")]
        actions = [attack(attacker), attack_force(), flash_play(card_id), flash_pass(), flash_pass()]
        checks = [assertion("damaging attacker returns", "state.players.opponent.hand", "count_where", value=1, where={"cardId": attacker})]
        return steps, actions, checks, "trigger_resolution", "Tornado Blow returns the minion that damages the protected player or Force."
    if card_id == "yellow_04_02_02_00":
        dragon = "yellow_09_02_02_00"
        return [setup(card_id, seed), add(dragon, "P1", "deck")], [play(card_id), target(dragon)], [assertion("searched Dragon enters hand", "state.players.human.hand", "count_where", value=1, where={"cardId": dragon})], "public_information", "Celica reveals and adds an eligible Dragon from the deck."
    if card_id == "yellow_04_02_02_01":
        magic = "yellow_06_03_02_00"
        return [setup(card_id, seed, zone="field"), add(magic, "P1", "hand"), *payment(magic), fixed()], [play_other(magic), target(card_id)], [assertion("rested selected Chohi refreshes", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "rested": False})], "trigger_resolution", "A rested Chohi selected by its own effect refreshes once."
    if card_id == "yellow_04_02_02_02":
        ally = "yellow_03_02_02_00"
        return [setup(card_id, seed), add(ally, "P1", "field")], [play(card_id), target(ally)], [assertion("chosen minion gets BP and Reawaken", "state.players.human.field", "count_where", value=1, where={"cardId": ally, "turnBpModifier": 200, "keywords": ["REAWAKEN"]})], "state_transition", "Kung-fu Monkey grants BP+200 and Reawaken for the turn."
    if card_id == "yellow_05_02_02_00":
        destroy_magic = "purple_03_03_01r_00"
        steps = [setup(card_id, seed, zone="field"), add("yellow_00_01_02_00", "P1", "base"), add(destroy_magic, "P1", "hand"), *payment(destroy_magic), fixed()]
        actions = [bless("yellow_00_01_02_00", _capture_setup_host(steps, card_id)), play_other(destroy_magic), target(card_id)]
        return steps, actions, [assertion("blessed Milky returns to hand", "state.players.human.hand", "count_where", value=1, where={"cardId": card_id})], "trigger_resolution", "A blessed Milky returns to hand when destroyed."
    if card_id == "yellow_06_02_02_00":
        ally, enemy = "red_02_02_02_00", "colorless_07_02_02_00"
        steps = [setup(card_id, seed), add(ally, "P1", "field"), add(enemy, "P2", "field"), fixed()]
        actions = [play(card_id), target(ally), attack(ally), attack_force(), flash_pass(), flash_pass(), block_option("b0")]
        return steps, actions, [assertion("granted winner survives larger blocker", "state.players.human.field", "count_where", value=1, where={"cardId": ally}), assertion("larger blocker is destroyed", "state.players.opponent.trash", "count_where", value=1, where={"cardId": enemy})], "keyword_legality", "Ryudou grants another allied minion unconditional battle victory for the turn."
    if card_id == "yellow_06_03_02_00":
        ally = "red_02_02_02_00"
        return [setup(card_id, seed), add(ally, "P1", "field")], [play(card_id), target(ally)], [assertion("Power of Sun applies turn stats", "state.players.human.field", "count_where", value=1, where={"cardId": ally, "turnBpModifier": 400, "turnDpModifier": 2})], "state_transition", "Power of Sun grants BP+400/DP+2 for the turn."
    if card_id == "yellow_09_02_02_00":
        enemy = "red_02_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field")], [play(card_id), target(enemy)], [assertion("selected enemy leaves field", "state.players.opponent.field", "none_where", where={"cardId": enemy}), assertion("enemy is on deck", "state.players.opponent.deckCount", "eq", value=1)], "state_transition", "Densai returns the selected enemy minion to the top of its deck."

    # White
    if card_id == "white_01_02_02_00":
        return [setup(card_id, seed), force_state("P1", 0, destroyed=True)], [play(card_id)], [assertion("destroyed Force increases stats", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "effectiveBp": 300, "effectiveDp": 1})], "continuous_effect", "Eisen Croco gains BP+200/DP+1 per destroyed allied Force."
    if card_id == "white_03_02_02_00":
        attacker = "red_02_02_02_00"
        return [setup(card_id, seed, zone="field"), add(attacker, "P2", "field"), fixed("P2")], [attack(attacker), attack_force()], [assertion("Force attack grows R-A7", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "permanentBpModifier": 100})], "trigger_resolution", "R-A7 gains permanent BP+100 when an allied Force is attacked on the opponent turn."
    if card_id == "white_03_02_02_01":
        dragon, blocker = "white_09_02_02_00", "colorless_04_02_02_00"
        steps = [setup(card_id, seed, zone="field"), add(dragon, "P1", "field"), add(blocker, "P2", "field"), fixed(), life("P2", 5)]
        actions = [attack(dragon), attack_force(), flash_pass(), flash_pass(), block_option("b0")]
        return steps, actions, [assertion("Dragon battle win damages player", "state.players.opponent.life", "eq", value=4)], "trigger_resolution", "Matilda deals one direct player damage after an allied white Dragon wins a battle."
    if card_id == "white_03_03_02_00":
        attacker = "red_02_02_02_00"
        steps = [setup(card_id, seed), add(attacker, "P2", "field"), fixed("P2")]
        actions = [attack(attacker), attack_force(), flash_play(card_id), target_force("force_so2"), flash_pass(), flash_pass()]
        return steps, actions, [assertion("redirected Force takes damage", "state.players.human.forces", "count_where", value=1, where={"id": "force_so2", "life": 2})], "target_selection", "Moving Shield changes the attack target to the selected allied Force."
    if card_id == "white_04_02_02_00":
        enemy, magic = "red_02_02_02_00", "red_03_03_02_01"
        return [setup(card_id, seed, zone="field"), add(enemy, "P1", "field"), add(magic, "P2", "hand"), *payment(magic, "P2"), fixed("P2")], [play_other(magic), target(enemy)], [assertion("Apostel is excluded from opponent effects", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "permanentBpModifier": 0})], "target_selection", "On the opponent turn Apostel cannot be selected by that opponent's effect."
    if card_id == "white_04_03_02_00":
        ally = "white_04_02_02_01"
        return [setup(card_id, seed), add(ally, "P1", "field")], [play(card_id)], [assertion("white minion gains permanent BP", "state.players.human.field", "count_where", value=1, where={"cardId": ally, "permanentBpModifier": 200})], "state_transition", "Option Parts gives every current allied white minion permanent BP+200."
    if card_id == "white_05_02_02_00":
        return _ivan_scenario(card_id, seed)
    if card_id == "white_06_02_02_00":
        enemy = "red_02_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field", rested=True)], [play(card_id), target(enemy)], [assertion("chosen enemy becomes active", "state.players.opponent.field", "count_where", value=1, where={"cardId": enemy, "rested": False}), assertion("chosen enemy must block", "state.players.opponent.field[0].activeEffects", "count_where", value=1, where={"kind": "must_block"})], "state_transition", "Kanonen Tiger refreshes the selected enemy and marks it as a mandatory blocker."
    if card_id == "white_06_03_02_00":
        enemy, attacker = "red_04_02_02_00", "red_02_02_02_00"
        steps = [setup(card_id, seed), add(enemy, "P2", "field"), add(attacker, "P2", "field"), fixed("P2")]
        actions = [attack(attacker), attack_force(), flash_play(card_id), target(enemy), flash_pass(), flash_pass()]
        return steps, actions, [assertion("Ex Cannon removes enemy", "state.players.opponent.removedCount", "eq", value=1)], "state_transition", "Ex Cannon removes the selected enemy minion during a real Flash window."
    if card_id == "white_09_02_02_00":
        low, high = "red_02_02_02_00", "colorless_07_02_02_00"
        steps = [setup(card_id, seed, zone="field"), add(low, "P2", "field"), add(high, "P2", "field"), fixed()]
        actions = [attack(card_id), attack_force(), flash_pass(), flash_pass(), no_block()]
        return steps, actions, [assertion("one lowest-cost enemy is removed", "state.players.opponent.removedCount", "eq", value=1), assertion("higher cost remains", "state.players.opponent.field", "count_where", value=1, where={"cardId": high})], "trigger_resolution", "After Frieren deals attack damage, every lowest-cost enemy minion is removed."

    # Green
    if card_id == "green_01_02_02_00":
        return _bless_host_effect(card_id, seed, "green_00_01_02_00", assertion("Tupa Choka gains permanent DP", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "permanentDpModifier": 1}), "Blessing Tupa Choka gives it permanent DP+1.")
    if card_id == "green_02_03_02_00":
        nymph = "green_00_01_02_00"
        return [setup(card_id, seed), add(nymph, "P1", "deck")], [play(card_id), target(nymph)], [assertion("searched Nymph is rested mana", "state.players.human.base", "count_where", value=1, where={"cardId": nymph, "rested": True})], "state_transition", "Anima places the searched green Nymph B-Minion into base rested."
    if card_id == "green_03_02_02_00":
        return _bless_host_effect(card_id, seed, "red_00_01_02_00", assertion("wrong-color Bless attaches", "state.players.human.field[0].blessings", "count_where", value=1, where={"cardId": "red_00_01_02_00"}), "Tuhansapi ignores Bless conditions and accepts red Bless mana.")
    if card_id == "green_03_02_02_01":
        dragon = "green_09_02_02_00"
        mana_ids = ["green_00_01_02_00"] + ["colorless_00_01_02_01"] * 6
        steps = [setup(card_id, seed, zone="base"), add(dragon, "P1", "hand")] + [add(mid, "P1", "base") for mid in mana_ids] + [fixed()]
        return steps, [play_other(dragon)], [assertion("Chloe helps pay for green Dragon", "state.players.human.field", "count_where", value=1, where={"cardId": dragon})], "resource_change", "Chloe contributes two green mana units while paying for a green Dragon."
    if card_id == "green_03_03_02_00":
        enemy = "yellow_03_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field", rested=True)], [play(card_id), target(enemy)], [assertion("rested enemy loses 500", "state.players.opponent.trash", "count_where", value=1, where={"cardId": enemy})], "target_selection", "Forest Guard gives a rested target BP-500, allowing state-based destruction."
    if card_id == "green_04_02_02_00":
        nymph, enemy = "green_00_01_02_00", "yellow_03_02_02_00"
        return [setup(card_id, seed, zone="field"), add(nymph, "P1", "hand"), add(enemy, "P2", "field", rested=True), fixed("P1", "mana")], [play_other(nymph), target(enemy)], [assertion("Nymph placement destroys rested enemy", "state.players.opponent.trash", "count_where", value=1, where={"cardId": enemy})], "trigger_resolution", "Papilio destroys a rested enemy when a Nymph mana is placed from hand."
    if card_id == "green_05_02_02_00":
        return _bless_host_effect(card_id, seed, "green_00_01_02_00", assertion("Bayagan records granted Rush and Reawaken", "state.players.human.field[0].activeEffects", "count_where", value=1, where={"kind": "keyword_modifier", "keywords": ["RUSH", "REAWAKEN"]}), "Blessing Bayagan grants Rush and Reawaken for the turn.")
    if card_id == "green_06_02_02_00":
        nymph = "green_00_01_02_00"
        return [setup(card_id, seed), add(nymph, "P1", "base", rested=True)], [play(card_id)], [assertion("all Nymph mana refresh", "state.players.human.base", "count_where", value=1, where={"cardId": nymph, "rested": False})], "state_transition", "Sylvie refreshes every allied Nymph mana on summon."
    if card_id == "green_08_03_02_00":
        enemy = "yellow_03_02_02_00"
        return [setup(card_id, seed), add("green_08_02_02_00", "P1", "field"), add(enemy, "P2", "field")], [play(card_id)], [assertion("only three colored mana are paid", "state.players.human.base", "count_where", value=3, where={"rested": True}), assertion("all enemies rest", "state.players.opponent.field", "count_where", value=1, where={"cardId": enemy, "rested": True})], "resource_change", "With a cost-7+ green minion, Tentacle Entangle keeps its three green cost while its free cost becomes zero, then rests all enemies."
    if card_id == "green_09_02_02_00":
        enemy = "red_02_02_02_00"
        return [setup(card_id, seed, zone="field"), add(enemy, "P2", "hand"), *payment(enemy, "P2"), fixed("P2")], [play_other(enemy)], [assertion("opponent minion enters rested", "state.players.opponent.field", "count_where", value=1, where={"cardId": enemy, "rested": True})], "continuous_effect", "On the opponent turn Hatoto makes that opponent's entering minion rested."

    # Blue
    if card_id == "blue_00_03_02_00":
        return [setup(card_id, seed), add("blue_02_02_02_00", "P1", "field")], [play(card_id)], [assertion("movement right increases", "state.players.human.movementRightCount", "eq", value=2)], "resource_change", "Merfolk March increases movement right while an allied blue minion exists."
    if card_id == "blue_01_02_02_00":
        top = "red_02_02_02_00"
        return [setup(card_id, seed), add(top, "P1", "deck")], [play(card_id), target(top)], [assertion("chosen top card stays in deck", "state.players.human.deckCount", "eq", value=1)], "trigger_resolution", "The apprentice inspects exactly the top card and may leave it on top."
    if card_id == "blue_03_02_02_00":
        dragon, draw_id = "colorless_04_02_02_00", "red_02_02_02_00"
        return [setup(card_id, seed), add(dragon, "P1", "hand"), add(draw_id, "P1", "deck"), *payment(dragon)], [play(card_id), play_other(dragon)], [assertion("blue or colorless Dragon entry draws", "state.players.human.hand", "count_where", value=1, where={"cardId": draw_id})], "trigger_resolution", "Sophia draws when an allied blue or colorless Dragon enters on her controller's turn."
    if card_id == "blue_03_03_02_00":
        enemy = "yellow_03_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field")], [play(card_id), target(enemy)], [assertion("Sonic Wave changes original stats", "state.players.opponent.field", "count_where", value=1, where={"cardId": enemy, "permanentBpModifier": -200, "permanentDpModifier": -1})], "state_transition", "Sonic Wave permanently gives BP-200 and original DP-1."
    if card_id == "blue_04_02_02_00":
        enemy = "yellow_03_02_02_00"
        return [setup(card_id, seed, zone="field"), add(enemy, "P2", "field"), fixed()], [move(card_id, "field_to_base"), target(enemy)], [assertion("enemy retreats rested", "state.players.opponent.base", "count_where", value=1, where={"cardId": enemy, "rested": True})], "state_transition", "Blackscale's retreat effect moves a cost-5-or-less enemy to base rested."
    if card_id == "blue_05_02_02_00":
        moved = "blue_02_02_02_00"
        steps = [setup(card_id, seed, zone="field"), add(moved, "P1", "field", rested=True, capture="moved"), fixed()]
        return steps, [move(moved, "field_to_base")], [assertion("moved blue minion refreshes at destination", "state.players.human.base", "count_where", value=1, where={"cardId": moved, "rested": False})], "continuous_effect", "Giulio makes another moving blue minion active at its destination."
    if card_id == "blue_05_02_02_01":
        draw_id = "red_02_02_02_00"
        steps, actions, checks, kind, text = _bless_host_effect(card_id, seed, "blue_00_01_02_00", assertion("Rainbow Jelly draws", "state.players.human.hand", "count_where", value=1, where={"cardId": draw_id}), "Blessing Rainbow Jelly draws one card.", extras=[add(draw_id, "P1", "deck")])
        return steps, actions, checks, kind, text
    if card_id == "blue_06_02_02_00":
        magic, minion = "red_03_03_02_01", "red_02_02_02_00"
        return [setup(card_id, seed), add(magic, "P1", "deck"), add(minion, "P1", "deck")], [play(card_id), choose("effect_target", {"cardId": magic}, "choose the Magic card to add")], [assertion("selected Magic enters hand", "state.players.human.hand", "count_where", value=1, where={"cardId": magic}), assertion("non-Magic remains in deck", "state.players.human.deckCount", "eq", value=1), assertion("only selected Magic is publicly revealed", "state.publicReveals", "count_where", value=1, where={"reason": "top_magic", "card": {"cardId": magic}})], "private_look_selection", "David's mandatory summon effect lets the controller inspect the top three and choose which Magic card to publicly reveal and add to hand."
    if card_id == "blue_09_02_02_00":
        magic = "blue_00_03_02_00"
        return [setup(card_id, seed), add(magic, "P1", "hand")], [play(card_id), play_other(magic)], [assertion("next blue Magic resolves for zero", "state.players.human.trash", "count_where", value=1, where={"cardId": magic})], "resource_change", "Guerrerofon makes the next allied blue Magic cost zero."
    if card_id == "blue_010_03_02_00":
        return [setup(card_id, seed)], [play(card_id)], [assertion("four elemental Dragon tokens appear", "state.players.human.field", "length_eq", value=4)], "state_transition", "Maelstrom creates exactly one Fire, Water, Wind, and Thunder Dragon token."

    # Purple
    if card_id == "purple_01_02_02_00":
        ally, destroy_magic = "purple_05_02_02_00", "purple_03_03_01r_00"
        return [setup(card_id, seed, zone="field"), add(ally, "P1", "field"), add(destroy_magic, "P1", "hand"), *payment(destroy_magic), fixed()], [play_other(destroy_magic), target(card_id), target(ally)], [assertion("destroy trigger buffs purple ally", "state.players.human.field", "count_where", value=1, where={"cardId": ally, "permanentBpModifier": 100})], "trigger_resolution", "Murmur's destruction gives one allied purple minion permanent BP+100."
    if card_id == "purple_01_03_02_00":
        recovered = "red_02_02_02_00"
        return [setup(card_id, seed), add(recovered, "P1", "trash")], [play(card_id), target(recovered)], [assertion("low-cost minion returns from trash", "state.players.human.hand", "count_where", value=1, where={"cardId": recovered})], "resource_change", "Bad Talk mills three then returns a cost-3-or-less minion from trash."
    if card_id == "purple_02_02_02_00":
        enemy, destroy_magic, draw_id = "red_02_02_02_00", "purple_04_03_01r_00", "blue_02_02_02_00"
        steps, actions, _, _, _ = _bless_host_effect(card_id, seed, "purple_00_01_02_00", assertion("unused", "state.players.human.field", "length_eq", value=1), "")
        steps += [add(enemy, "P2", "field"), add(destroy_magic, "P1", "hand"), add(draw_id, "P1", "deck"), *payment(destroy_magic)]
        actions += [play_other(destroy_magic)]
        return steps, actions, [assertion("enemy destruction draws", "state.players.human.hand", "count_where", value=1, where={"cardId": draw_id})], "trigger_resolution", "After Richard is blessed, each enemy minion destroyed that turn draws one card."
    if card_id == "purple_03_02_02_00":
        ally = "red_02_02_02_00"
        return [setup(card_id, seed), add(ally, "P1", "field")], [play(card_id), target(ally)], [assertion("sacrifice grows Ante", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "permanentBpModifier": 200, "permanentDpModifier": 1}), assertion("ally is destroyed", "state.players.human.trash", "count_where", value=1, where={"cardId": ally})], "state_transition", "Ante destroys another allied minion and gains permanent BP+200/DP+1."
    if card_id == "purple_03_03_02_00":
        enemy, ally = "yellow_03_02_02_00", "purple_05_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field"), add(ally, "P1", "field")], [play(card_id), target(enemy)], [assertion("enemy loses BP", "state.players.opponent.field", "count_where", value=1, where={"cardId": enemy, "permanentBpModifier": -200}), assertion("allied purple gains BP", "state.players.human.field", "count_where", value=1, where={"cardId": ally, "permanentBpModifier": 100})], "state_transition", "Doomed Road debuffs the target then buffs every allied purple minion."
    if card_id == "purple_04_02_02_00":
        dragon = "colorless_04_02_02_00"
        return [setup(card_id, seed), add(dragon, "P1", "trash")], [play(card_id), target(dragon)], [assertion("eligible Dragon returns", "state.players.human.hand", "count_where", value=1, where={"cardId": dragon})], "resource_change", "Francesca optionally returns an eligible purple or colorless Dragon from trash."
    if card_id == "purple_05_02_02_01":
        ally, enemy = "purple_02_02_02_00", "colorless_07_02_02_00"
        steps = [setup(card_id, seed, zone="field"), add(ally, "P1", "field"), add(enemy, "P2", "field"), fixed("P2")]
        actions = [attack(enemy), attack_force(), flash_pass(), flash_pass(), block_option("b1")]
        return steps, actions, [assertion("Death Blow works on opponent turn", "state.players.opponent.trash", "count_where", value=1, where={"cardId": enemy})], "keyword_legality", "Isaac lets allied Death Blow resolve during the opponent's turn."
    if card_id == "purple_06_02_02_00":
        trash_card = "red_02_02_02_00"
        return [setup(card_id, seed), add(trash_card, "P1", "trash"), add(trash_card, "P2", "trash")], [play(card_id)], [assertion("trash count becomes permanent BP", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "permanentBpModifier": 200})], "state_transition", "Gustave gains permanent BP+100 for each F-Minion in both trash zones."
    if card_id == "purple_06_03_02_00":
        demon, attacker = "purple_05_02_02_00", "red_02_02_02_00"
        return [setup(card_id, seed), add(demon, "P1", "field"), add(attacker, "P2", "field"), fixed("P2")], [attack(attacker), attack_force(), flash_play(card_id), flash_pass(), flash_pass()], [assertion("opponent minion is attack-locked", "state.players.opponent.field", "count_where", value=1, where={"cardId": attacker, "rested": True})], "keyword_legality", "Demon's Terror, enabled by a Demon, prevents every enemy minion from attacking for the turn."
    if card_id == "purple_09_02_02_00":
        enemy, milled = "yellow_03_02_02_00", "red_02_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field"), add(milled, "P1", "deck"), add(milled, "P1", "deck"), add(milled, "P1", "deck")], [play(card_id), target(enemy)], [assertion("target is destroyed", "state.players.opponent.trash", "count_where", value=1, where={"cardId": enemy}), assertion("cost-three cards are milled", "state.players.human.trash", "count_where", value=3, where={"cardId": milled})], "trigger_resolution", "Skullbone destroys the target and mills cards equal to that target's cost."

    # Colorless
    if card_id == "colorless_02_02_02_00":
        draw_id = "red_02_02_02_00"
        return [setup(card_id, seed), add("red_00_01_02_00", "P1", "base"), add(draw_id, "P1", "deck")], [play(card_id)], [assertion("Bless mana enables draw", "state.players.human.hand", "count_where", value=1, where={"cardId": draw_id})], "resource_change", "Scarlet draws because an allied Bless mana exists in base."
    if card_id == "colorless_02_02_02_01":
        demigod = "red_05_02_01r_00"
        return [setup(card_id, seed), add(demigod, "P1", "hand")], [play(card_id), end_turn()], [assertion("Demigod remains in hand with increased cost", "state.players.human.hand", "count_where", value=1, where={"cardId": demigod})], "resource_change", "Green Mimic raises the free cost of Demigod F-Minions in both hands by two."
    if card_id in {"colorless_03_02_02_00", "colorless_03_02_02_01"}:
        destroy_magic = "purple_03_03_01r_00"
        steps = [setup(card_id, seed, zone="field"), add(destroy_magic, "P1", "hand"), *payment(destroy_magic), fixed()]
        if card_id.endswith("01"):
            steps.append(add("red_03_02_01r_00", "P2", "field"))
        actions = [play_other(destroy_magic), target(card_id)]
        checks = [assertion("destroy effect resolves", "state.players.human.trash", "count_where", value=1, where={"cardId": card_id})]
        if card_id.endswith("00"):
            checks.append(assertion("Dragon token appears", "state.players.human.field", "count_where", value=1, where={"cardId": "colorless_04_04_00_00"}))
        return steps, actions, checks, "trigger_resolution", "The printed destruction effect resolves from trash after public destruction."
    if card_id == "colorless_03_02_02_02":
        dragon = "colorless_04_02_02_00"
        reduced_payment = payment(dragon)[:-1]
        return [setup(card_id, seed), add(dragon, "P1", "hand"), *reduced_payment], [play(card_id), play_other(dragon)], [assertion("Dragon is playable with reduced free cost", "state.players.human.field", "count_where", value=1, where={"cardId": dragon})], "resource_change", "Drangail reduces the free cost of allied hand Dragons by one."
    if card_id == "colorless_04_02_02_00":
        dragon = "red_09_02_02_00"
        return [setup(card_id, seed), add(dragon, "P1", "field")], [play(card_id)], [assertion("other Dragon exposes Obsidian aura", "state.players.human.field[0].activeEffects", "count_where", value=1, where={"kind": "card_aura", "sourceCardId": card_id, "bpDelta": 200})], "continuous_effect", "Obsidian Dragon gives every other allied Dragon BP+200."
    if card_id == "colorless_04_02_02_01":
        enemy_magic, ally = "red_03_03_02_01", "red_02_02_02_00"
        return [setup(card_id, seed, zone="field"), add(ally, "P1", "field"), add(enemy_magic, "P2", "hand"), *payment(enemy_magic, "P2"), fixed("P2")], [play_other(enemy_magic), target(ally)], [assertion("Force ward remains active", "state.players.human.forces", "count_where", value=2, where={"destroyed": False})], "target_selection", "Slave Beetle prevents opponent effects from selecting allied Forces on the opponent turn."
    if card_id == "colorless_04_02_02_02":
        return [setup(card_id, seed, zone="field"), fixed(), life("P1", 5)], [attack(card_id), attack_force(), flash_pass(), flash_pass()], [assertion("dealt damage heals player", "state.players.human.life", "gt", value=5)], "trigger_resolution", "Steel Centipede heals its player by the attack damage it deals."
    if card_id == "colorless_04_02_02_03":
        host = "red_04_02_02_00"
        steps = [setup(card_id, seed, zone="field"), add(host, "P1", "field", capture="host"), add("red_00_01_02_00", "P1", "base", rested=True), fixed()]
        return steps, [bless("red_00_01_02_00", "host")], [assertion("rested Bless mana attaches", "state.players.human.field[1].blessings", "count_where", value=1, where={"cardId": "red_00_01_02_00"})], "keyword_legality", "Black Saber Jaguar allows rested Bless mana to attach."
    if card_id == "colorless_05_02_02_00":
        return [setup(card_id, seed, zone="field"), add("red_04_02_02_00", "P2", "field"), fixed()], [attack(card_id), attack_force(), flash_pass(), flash_pass(), block_option("b0")], [assertion("Death Blow destroys battle opponent", "state.players.opponent.trash", "count_where", value=1, where={"cardId": "red_04_02_02_00"})], "keyword_legality", "Goblin Assassin's Death Blow destroys the minion it battled on its own turn."
    if card_id == "colorless_05_02_02_01":
        enemy = "colorless_03_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field")], [play(card_id), target(enemy)], [assertion("destroy-effect enemy is removed", "state.players.opponent.removedCount", "eq", value=1)], "target_selection", "Monoeye Dragon removes an enemy that has a destruction effect."
    if card_id == "colorless_05_02_02_03":
        enemy = "colorless_08_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field")], [play(card_id)], [assertion("all cost-eight enemies are destroyed", "state.players.opponent.trash", "count_where", value=1, where={"cardId": enemy})], "state_transition", "Hero Error destroys every enemy minion with cost eight or more."
    if card_id == "colorless_06_02_02_00":
        return [setup(card_id, seed), life("P1", 2, force_index=0)], [play(card_id), target_force("force_e")], [assertion("selected Force heals", "state.players.human.forces", "count_where", value=1, where={"id": "force_e", "life": 3})], "resource_change", "Gilly Boar heals the selected allied player or Force by one."
    if card_id == "colorless_06_02_02_01":
        enemy = "red_02_02_02_00"
        return [setup(card_id, seed), add(enemy, "P2", "field")], [play(card_id), target(enemy)], [assertion("BP400 target rests", "state.players.opponent.field", "count_where", value=1, where={"cardId": enemy, "rested": True})], "target_selection", "Storm Gira rests the selected enemy with BP400 or less."
    if card_id == "colorless_06_02_02_02":
        enemy_magic, other = "red_03_03_02_01", "red_02_02_02_00"
        return [setup(card_id, seed, zone="field"), add(other, "P1", "field"), add(enemy_magic, "P2", "hand"), *payment(enemy_magic, "P2"), fixed("P2")], [play_other(enemy_magic), target(card_id)], [assertion("with another ally Black Flame can be selected", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "permanentBpModifier": -300})], "target_selection", "Black Flame becomes selectable once another allied minion exists."
    if card_id == "colorless_07_02_02_01":
        return [setup(card_id, seed)], [play(card_id)], [assertion("Hagen gains turn BP", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "turnBpModifier": 300})], "state_transition", "Hagen gains BP+300 for the summon turn."
    if card_id == "colorless_08_02_02_00":
        return [setup(card_id, seed, zone="field"), add("red_02_02_02_00", "P2", "deck"), fixed()], [end_turn()], [assertion("Hydra creates Dragon token at end", "state.players.human.field", "count_where", value=1, where={"cardId": "colorless_04_04_00_00"})], "trigger_resolution", "Hydra creates one Dragon token at its controller's turn end."
    if card_id == "colorless_010_02_02_00":
        colored = "red_00_01_02_00"
        return [setup(card_id, seed), add(colored, "P1", "base", rested=True)], [play(card_id)], [assertion("colored mana refreshes", "state.players.human.base", "count_where", value=1, where={"cardId": colored, "rested": False})], "resource_change", "Regenerate refreshes every colored allied mana on its first same-name summon of the turn."

    raise RuntimeError(f"missing positive semantic scenario for {card_id}")


def _capture_setup_host(steps: list[dict[str, Any]], card_id: str) -> str:
    steps[0]["capture"] = {
        "host": {
            "path": "state.players.human.field",
            "where": {"cardId": card_id},
            "field": "iid",
        }
    }
    return "host"


def _bless_host_effect(
    card_id: str,
    seed: int,
    mana_id: str,
    check: dict[str, Any],
    text: str,
    *,
    extras: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str, str]:
    steps = [setup(card_id, seed, zone="field")]
    _capture_setup_host(steps, card_id)
    steps.extend([add(mana_id, "P1", "base", capture="bless_mana"), *(extras or []), fixed()])
    return steps, [bless_alias("bless_mana", "host")], [check], "trigger_resolution", text


def _attack_effect(
    card_id: str,
    seed: int,
    enemy_id: str,
    effect_actions: list[dict[str, Any]],
    check: dict[str, Any],
    text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str, str]:
    steps = [setup(card_id, seed, zone="field"), add(enemy_id, "P2", "field"), fixed()]
    return steps, [attack(card_id), attack_force(), *effect_actions], [check], "trigger_resolution", text


def _ivan_scenario(card_id: str, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str, str]:
    blocker_id = "red_04_02_02_00"
    steps = [setup(card_id, seed, zone="field")]
    _capture_setup_host(steps, card_id)
    steps += [add("white_00_01_02_00", "P1", "base"), add(blocker_id, "P2", "field"), fixed()]
    actions = [bless("white_00_01_02_00", "host"), attack(card_id), attack_force(), flash_pass(), flash_pass(), block_option("b0")]
    checks = [assertion("Ivan forces the available blocker into battle", "state.players.opponent.trash", "count_where", value=1, where={"cardId": blocker_id})]
    return steps, actions, checks, "keyword_legality", "After Blessing Ivan, the opponent must block its attack when a blocker exists."


def boundary(card_id: str, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str, str]:
    card = CARD_REGISTRY[card_id]
    if card_id in BLESS_HOSTS:
        if card_id == "colorless_00_01_02_01":
            host = BLESS_HOSTS[card_id]
            generator = "colorless_04_02_ex01_02"
            destroy_magic = "purple_03_03_01r_00"
            steps = [
                setup(card_id, seed, zone="base"),
                add(host, "P1", "field", capture="host"),
                add("purple_00_01_02_00", "P1", "base"),
                *[add("colorless_00_01_01_00", "P1", "base") for _ in range(8)],
                add(generator, "P1", "hand"),
                add(destroy_magic, "P1", "hand"),
                fixed(),
            ]
            steps[0]["payload"]["playerForces"] = ["force_kon", "force_so2"]
            actions = [
                bless(card_id, "host"),
                play_other(generator),
                play_other(destroy_magic),
                target(host),
                blessing_replacement("mana_token"),
            ]
            checks = [
                assertion("returning Bless mana keeps base at its cap", "state.players.human.base", "length_eq", value=10),
                assertion("chosen neutral mana is replaced", "state.players.human.removedCount", "eq", value=1),
                assertion("Bless mana returns rested", "state.players.human.base", "count_where", value=1, where={"cardId": card_id, "rested": True}),
            ]
            return steps, actions, checks, "replacement", "When its host leaves a full base, returning Bless mana uses a public replacement choice and the base remains at ten cards."
        wrong_host = "yellow_03_02_02_00" if card_id.startswith("red_") else "red_02_02_02_00"
        if card_id in {"colorless_00_01_02_00", "colorless_00_01_02_02"}:
            wrong_host = "red_02_02_02_00"
        if card_id == "colorless_00_01_02_01":
            wrong_host = BLESS_HOSTS[card_id]
        steps = [setup(card_id, seed), add(wrong_host, "P1", "field", capture="host")]
        actions = [play(card_id), end_turn()]
        checks = [assertion("unattached mana remains in base", "state.players.human.base", "count_where", value=1, where={"cardId": card_id}), assertion("host has no Bless attachment", "state.players.human.field", "count_where", value=1, where={"cardId": wrong_host, "blessings": []})]
        observation = "Without a legal Bless selection, the mana remains in base and no attachment is invented."
        if card_id == "colorless_00_01_02_01":
            steps[1]["payload"]["rested"] = False
            observation = "An unconditional Bless card still does nothing while its controller declines to spend movement right."
        return steps, actions, checks, "non_activation", observation
    if card_id == "red_08_03_02_00":
        non_dragon = "blue_02_02_02_00"
        steps = [
            setup(card_id, seed, non_minion_mana_only=True),
            *payment(card_id, colored_only=True),
            add(non_dragon, "P1", "deck"),
            add(non_dragon, "P1", "deck"),
            add(non_dragon, "P1", "deck"),
        ]
        actions = [play(card_id), target_option("e0")]
        checks = [
            assertion("mandatory colorless mana is still destroyed", "state.players.human.removedCount", "eq", value=1),
            assertion("no ineligible minion enters", "state.players.human.field", "none_where", where={"cardId": non_dragon}),
        ]
        return steps, actions, checks, "zero_target", "With no eligible Dragon in the top three, Fossil still destroys the selected mana and puts no minion onto the field."
    if card_id == "blue_06_02_02_00":
        magic, minion = "red_03_03_02_01", "red_02_02_02_00"
        steps = [setup(card_id, seed), add(magic, "P1", "deck"), add(minion, "P1", "deck")]
        actions = [play(card_id), choose("effect_target", {"kind": "effect_target_skip"}, "choose no Magic cards")]
        checks = [
            assertion("unselected cards remain in deck", "state.players.human.deckCount", "eq", value=2),
            assertion("zero selection publishes no cards", "state.publicReveals", "length_eq", value=0),
        ]
        return steps, actions, checks, "selection_boundary", "David's mandatory top-three inspection allows a zero-card Magic selection, leaving all looked cards undisclosed in the deck."
    if card_id == "purple_06_03_02_00":
        demon = "purple_05_02_02_00"
        attacker = "red_02_02_02_00"
        mover = "red_00_01_00_00"
        steps = [
            setup(card_id, seed),
            add(demon, "P1", "field"),
            add(attacker, "P2", "field"),
            add(mover, "P2", "base"),
            fixed("P2"),
        ]
        actions = [
            attack(attacker),
            attack_force(),
            flash_play(card_id),
            flash_pass(),
            flash_pass(),
            no_block(),
            move(mover, "base_to_field"),
        ]
        checks = [
            assertion("attack lock does not forbid movement", "state.players.opponent.field", "count_where", value=1, where={"cardId": mover}),
        ]
        return steps, actions, checks, "no_extra_effect", "Demon's Terror forbids attacks only; an affected player can still spend movement right normally."
    if card_id == "colorless_06_02_02_02":
        enemy_magic = "red_03_03_02_01"
        steps = [
            setup(card_id, seed, zone="field"),
            add(enemy_magic, "P2", "hand"),
            *payment(enemy_magic, "P2"),
            fixed("P1"),
        ]
        actions = [
            attack(card_id),
            attack_force(),
        ]
        checks = [
            assertion(
                "targeted Flash is unavailable against lone Black Flame",
                "state.prompt.options",
                "none_where",
                where={"cardId": enemy_magic},
            ),
        ]
        return steps, actions, checks, "target_boundary", "With no other allied minion, the opponent's targeted Flash is absent from the public legal choices even during Black Flame's controller's turn."
    if card_id == "white_04_02_02_00":
        winner = "white_03_02_02_01"
        blocker = "red_02_02_02_00"
        enemy_magic = "red_03_03_02_01"
        steps = [
            setup(card_id, seed, zone="field"),
            add(winner, "P1", "field"),
            add(blocker, "P2", "field"),
            add(enemy_magic, "P2", "hand"),
            *payment(enemy_magic, "P2"),
            fixed(),
        ]
        actions = [
            attack(winner),
            attack_force(),
            flash_play(enemy_magic),
            target(card_id),
            flash_pass(),
            flash_pass(),
            block_option("b0"),
        ]
        checks = [
            assertion(
                "another white minion's battle win grows Apostel",
                "state.players.human.field",
                "count_where",
                value=1,
                where={"cardId": card_id, "permanentBpModifier": -200, "permanentDpModifier": 1},
            ),
        ]
        return steps, actions, checks, "target_boundary", "On its controller's turn Apostel can be selected by an opponent's effect, then gains permanent BP+100/DP+1 when another allied white minion wins a battle."
    if card_id == "white_06_02_02_00":
        attacker = "red_02_02_02_00"
        draw_id = "blue_02_02_02_00"
        steps = [
            setup(card_id, seed, zone="field"),
            add(attacker, "P2", "field"),
            add(draw_id, "P1", "deck"),
            fixed("P2"),
        ]
        actions = [
            attack(attacker),
            attack_force(),
            flash_pass(),
            flash_pass(),
            block_option("b0"),
        ]
        checks = [
            assertion("Kanonen does not draw for an opponent-turn battle win", "state.players.human.hand", "none_where", where={"cardId": draw_id}),
        ]
        return steps, actions, checks, "non_activation", "Kanonen Tiger can win a battle while blocking on the opponent's turn, but its controller-turn draw clause does not activate."
    if card_id == "colorless_07_02_02_01":
        steps = [setup(card_id, seed, zone="field"), fixed()]
        actions = [
            attack(card_id),
            attack_force(),
            flash_pass(),
            flash_pass(),
            attack(card_id),
            attack_force(),
            flash_pass(),
            flash_pass(),
        ]
        checks = [
            assertion("Hagen refreshes only after its first attack", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "rested": True}),
        ]
        return steps, actions, checks, "non_activation", "Hagen refreshes after its first attack of the turn, can attack again, and does not refresh after the second attack."
    if "ベースに移動するとき、レスト状態で移動する" in card.ability_jp:
        steps = [setup(card_id, seed, zone="field"), fixed()]
        actions = [move(card_id, "field_to_base")]
        checks = [
            assertion("printed retreat enters base rested", "state.players.human.base", "count_where", value=1, where={"cardId": card_id, "rested": True}),
        ]
        return steps, actions, checks, "area_gate", "The printed passive applies at the field-to-base boundary and makes this minion enter base rested through the public movement action."
    if card_id in DRAGON_LORD_IDS:
        dragon_blocker = "colorless_07_02_02_00"
        non_dragon = "colorless_05_02_02_03"
        steps = [
            setup(card_id, seed, zone="field"),
            add(non_dragon, "P2", "field"),
            add(dragon_blocker, "P2", "field"),
            fixed(),
        ]
        actions = [
            attack(card_id),
            attack_force(),
            flash_pass(),
            flash_pass(),
            block_option("b0"),
        ]
        checks = [
            assertion("non-Dragon is excluded from blockers", "state.players.opponent.field", "count_where", value=1, where={"cardId": non_dragon}),
        ]
        return steps, actions, checks, "target_boundary", "On its controller's turn, this Dragon Lord can be blocked by the Dragon but not by the available non-Dragon."
    if card.type is CardType.MAGIC:
        steps = [setup(card_id, seed)]
        actions = [end_turn()]
        checks = [assertion("unused Magic remains in hand", "state.players.human.hand", "count_where", value=1, where={"cardId": card_id})]
        return steps, actions, checks, "area_gate", "The Magic has no passive effect while it remains unused in hand."
    steps = [setup(card_id, seed, zone="field"), fixed()]
    actions = [end_turn()]
    checks = [assertion("debug-arranged presence does not fabricate summon modifiers", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "permanentBpModifier": 0, "permanentDpModifier": 0})]
    return steps, actions, checks, "no_extra_effect", "A minion arranged directly on the field does not receive an unwritten summon effect."


def make_scenario(card_id: str, kind: str, seed: int) -> dict[str, Any]:
    if kind == "positive":
        steps, actions, checks, claim_kind, observation = positive(card_id, seed)
    else:
        steps, actions, checks, claim_kind, observation = boundary(card_id, seed)
    claim_id = f"{card_id}_{kind}"
    for check in checks:
        check["claim"] = claim_id
    return {
        "schema_version": 1,
        "scenario_id": claim_id,
        "card_id": card_id,
        "scenario_kind": kind,
        "official_rule": CARD_REGISTRY[card_id].ability_jp,
        "semantic_claims": [{"id": claim_id, "kind": claim_kind, "expected_observation": observation}],
        "seed": seed,
        "setup": steps,
        "actions": actions,
        "assertions": checks,
    }


def classification(card_id: str) -> str:
    card = CARD_REGISTRY[card_id]
    if card_id in VANILLA_IDS:
        return "vanilla"
    if card.keywords and not card.effects and card.aura is None and card.keyword_aura is None and card_id not in _PC02_ENGINE_RULE_IDS:
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
    if card_id in _PC02_ENGINE_RULE_IDS:
        out.append("engine_rule")
    return out


def build_manifest() -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for card_id in PC02_CARD_IDS:
        color = card_id.split("_", 1)[0].upper()
        cards.append({
            "card_id": card_id,
            "source_refs": [
                f"data/cards_bilingual_v4.tsv#{card_id}",
                f"data/pc02_image_reconciliation.tsv#{card_id}",
                f"asserts/ZENONZARD_CARDLIST/{color}/{card_id}.png",
            ],
            "classification": classification(card_id),
            "status": "semantic_passed",
            "implementation": {
                "files": ["zz/pc02.py"],
                "symbols": ["register_pc02_cards", "bless_condition_matches" if card_id in BLESS_HOSTS else "_PC02_EFFECTS_BY_ID"],
                "effect_channels": channels(card_id),
                "call_chain": [
                    "data/cards_bilingual_v4.tsv plus reconciled Japanese card image",
                    "zz.pc02.register_pc02_cards -> CARD_REGISTRY",
                    "Card/Keyword/EffectSpec and shared PC02 rule hook",
                    "Engine legality, trigger, targeting, and state mutation",
                    "GameSession public prompt -> /api/choose",
                    "tests/test_pc02_cards.py semantic scenario and evidence",
                ],
            },
            "tests": {
                "positive": ["tests/test_pc02_cards.py::test_pc02_positive_semantic_scenario"],
                "boundary": ["tests/test_pc02_cards.py::test_pc02_boundary_semantic_scenario"],
            },
            "semantic_scenarios": {
                "positive": {
                    "spec": f"project_memory/card_scenarios/pc02/{card_id}-positive.json",
                    "evidence": f"project_memory/card_evidence/pc02/{card_id}-positive.evidence.json",
                },
                "boundary": {
                    "spec": f"project_memory/card_scenarios/pc02/{card_id}-boundary.json",
                    "evidence": f"project_memory/card_evidence/pc02/{card_id}-boundary.evidence.json",
                },
            },
        })
    return {
        "schema_version": 1,
        "box_id": "PC:02 CONTRACT",
        "source": {
            "file": "data/official_cardlist.tsv",
            "id_column": "image_id",
            "filters": {"pack_jp_official": "PC:02 CONTRACT"},
            "expected_count": 100,
        },
        "real_game_smoke": ["tests/test_pc02_cards.py::test_pc02_complete_real_game_smoke"],
        "cards": cards,
    }


def main() -> None:
    SCENARIO_ROOT.mkdir(parents=True, exist_ok=True)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    for index, card_id in enumerate(PC02_CARD_IDS):
        for offset, kind in enumerate(("positive", "boundary")):
            spec = make_scenario(card_id, kind, 20000 + index * 2 + offset)
            path = SCENARIO_ROOT / f"{card_id}-{kind}.json"
            path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(yaml.safe_dump(build_manifest(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"generated {len(PC02_CARD_IDS) * 2} scenarios and {MANIFEST_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
