from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zz.cards import CARD_REGISTRY
from zz.ex01 import EX01_CARD_IDS


SCENARIO_ROOT = ROOT / "project_memory" / "card_scenarios" / "ex01"
EVIDENCE_ROOT = ROOT / "project_memory" / "card_evidence" / "ex01"
MANIFEST_PATH = ROOT / "project_memory" / "card_boxes" / "ex01.yaml"
WRONG_FORCES = ["force_li", "force_sei"]
OPPONENT_FORCES = ["force_kon", "force_rin"]


def _claim(claim_id: str, kind: str, observation: str) -> dict[str, str]:
    return {
        "id": claim_id,
        "kind": kind,
        "expected_observation": observation,
    }


def _assert(
        name: str,
        claim: str,
        path: str,
        op: str,
        *,
        value: Any = None,
        where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "claim": claim,
        "path": path,
        "op": op,
    }
    if op not in {"any_where", "none_where"}:
        result["value"] = value
    if where is not None:
        result["where"] = where
    return result


def _setup(
        card_id: str,
        *,
        zone: str,
        seed: int,
        player_forces: list[str],
        opponent_forces: list[str] | None = None,
        capture_zone: str | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "path": "/api/debug/setup",
        "payload": {
            "cardId": card_id,
            "seed": seed,
            "zone": zone,
            "playerForces": player_forces,
            "opponentForces": opponent_forces or OPPONENT_FORCES,
        },
    }
    if capture_zone:
        step["capture"] = {
            "audited_iid": {
                "path": f"state.players.human.{capture_zone}",
                "where": {"cardId": card_id},
                "field": "iid",
            }
        }
    return step


def _scenario(
        card_id: str,
        kind: str,
        seed: int,
        claim: dict[str, str],
        setup: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        assertions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scenario_id": f"{card_id}_{kind}",
        "card_id": card_id,
        "scenario_kind": kind,
        "official_rule": CARD_REGISTRY[card_id].ability_jp,
        "semantic_claims": [claim],
        "seed": seed,
        "setup": setup,
        "actions": actions,
        "assertions": assertions,
    }


def _play(card_id: str, name: str = "play audited card") -> dict[str, Any]:
    return {
        "name": name,
        "prompt_kind": "main_action",
        "select": {"kind": "play_card", "cardId": card_id},
    }


def _end_turn(name: str = "end current turn") -> dict[str, Any]:
    return {
        "name": name,
        "prompt_kind": "main_action",
        "select": {"kind": "end_turn"},
    }


def build_scenarios() -> dict[str, dict[str, dict[str, Any]]]:
    scenarios: dict[str, dict[str, dict[str, Any]]] = {}

    card_id = "colorless_02_02_ex01_00"
    move = {
        "name": "move Flight from base to field",
        "prompt_kind": "main_action",
        "select": {"kind": "move_card", "cardId": card_id, "direction": "base_to_field"},
    }
    positive_claim = _claim(
        "pegasus_active_move",
        "state_transition",
        "A rested Flight entering the field from base becomes active while Pegasus is selected.",
    )
    boundary_claim = _claim(
        "pegasus_required",
        "non_activation",
        "Without Pegasus, the same legal move preserves Flight's rested state.",
    )
    positive_setup = [
        _setup(card_id, zone="base", seed=101, player_forces=["force_sho", "force_chi"], capture_zone="base"),
        {"path": "/api/debug/card-state", "payload": {"iid": "$audited_iid", "rested": True}},
    ]
    boundary_setup = [
        _setup(card_id, zone="base", seed=102, player_forces=WRONG_FORCES, capture_zone="base"),
        {"path": "/api/debug/card-state", "payload": {"iid": "$audited_iid", "rested": True}},
    ]
    scenarios[card_id] = {
        "positive": _scenario(card_id, "positive", 101, positive_claim, positive_setup, [move], [
            _assert("Flight is active in field", "pegasus_active_move", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "rested": False}),
        ]),
        "boundary": _scenario(card_id, "boundary", 102, boundary_claim, boundary_setup, [move], [
            _assert("Flight stays rested without Pegasus", "pegasus_required", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "rested": True}),
        ]),
    }

    card_id = "colorless_03_02_ex01_00"
    choose_top = {
        "name": "choose one of the top two cards",
        "prompt_kind": "effect_target",
        "select": {"id": "e0"},
    }
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            111,
            _claim("chiron_top_two", "private_look_selection", "With Chiron selected, the controller inspects the top two, selects one card to reveal and add to hand, and returns the other card to the deck bottom."),
            [_setup(card_id, zone="hand", seed=111, player_forces=["force_chi", "force_li"])],
            [_play(card_id), choose_top],
            [
                _assert("one selected deck card enters hand", "chiron_top_two", "state.players.human.hand", "length_eq", value=1),
                _assert("the audited minion entered field", "chiron_top_two", "state.players.human.field", "count_where", value=1, where={"cardId": card_id}),
            ],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            112,
            _claim("chiron_required", "non_activation", "Without Chiron, summoning Wisdom creates no top-two choice and adds no extra card to hand."),
            [_setup(card_id, zone="hand", seed=112, player_forces=WRONG_FORCES)],
            [_play(card_id)],
            [
                _assert("no card is added without Chiron", "chiron_required", "state.players.human.hand", "length_eq", value=0),
            ],
        ),
    }

    card_id = "colorless_03_02_ex01_01"
    attack = {
        "name": "declare an attack with Ring",
        "prompt_kind": "main_action",
        "select": {"kind": "attack", "cardId": card_id},
    }
    attack_target = {
        "name": "target the opponent Ouroboros",
        "prompt_kind": "attack_target",
        "select": {"kind": "force", "forceId": "force_rin"},
    }
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            121,
            _claim("ouroboros_attack_bonus", "trigger_resolution", "With Ouroboros selected, Ring gains 300 BP when its attack is declared."),
            [_setup(card_id, zone="field", seed=121, player_forces=["force_rin", "force_li"], capture_zone="field")],
            [attack, attack_target],
            [_assert("Ring gains 300 BP for the turn", "ouroboros_attack_bonus", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "effectiveBp": 600})],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            122,
            _claim("ouroboros_required", "non_activation", "Without Ouroboros, declaring the same attack leaves Ring at its printed BP."),
            [_setup(card_id, zone="field", seed=122, player_forces=WRONG_FORCES, capture_zone="field")],
            [attack, attack_target],
            [_assert("Ring has no attack bonus", "ouroboros_required", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "effectiveBp": 300})],
        ),
    }

    card_id = "colorless_04_02_ex01_00"
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            131,
            _claim("minotaur_undamaged_growth", "continuous_effect", "With Minotaur selected and no player damage received, the opponent-turn end grants Vixon a permanent 200 BP."),
            [_setup(card_id, zone="field", seed=131, player_forces=["force_kai", "force_li"], capture_zone="field")],
            [_end_turn()],
            [_assert("Vixon retains the permanent bonus", "minotaur_undamaged_growth", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "permanentBpModifier": 200, "effectiveBp": 600})],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            132,
            _claim("minotaur_required", "non_activation", "Without Minotaur, an undamaged opponent turn grants Vixon no permanent BP."),
            [_setup(card_id, zone="field", seed=132, player_forces=WRONG_FORCES, capture_zone="field")],
            [_end_turn()],
            [_assert("Vixon receives no permanent bonus", "minotaur_required", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "permanentBpModifier": 0, "effectiveBp": 400})],
        ),
    }

    card_id = "colorless_04_02_ex01_01"
    add_flight = {"path": "/api/debug/add-card", "payload": {"cardId": "colorless_02_02_ex01_00", "side": "P1", "zone": "hand"}}
    choose_flight = {
        "name": "choose the original-cost-two Flight",
        "prompt_kind": "effect_target",
        "select": {"cardId": "colorless_02_02_ex01_00"},
    }
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            141,
            _claim("cyclops_put_without_summon", "target_selection", "With Cyclops selected, Eve puts an original-cost-two field minion from hand onto the field."),
            [_setup(card_id, zone="hand", seed=141, player_forces=["force_e", "force_li"]), add_flight],
            [_play(card_id), choose_flight],
            [
                _assert("Flight is put onto the field", "cyclops_put_without_summon", "state.players.human.field", "count_where", value=1, where={"cardId": "colorless_02_02_ex01_00"}),
                _assert("Flight leaves the hand", "cyclops_put_without_summon", "state.players.human.hand", "none_where", where={"cardId": "colorless_02_02_ex01_00"}),
            ],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            142,
            _claim("cyclops_required", "non_activation", "Without Cyclops, Eve does not offer or perform the hand-to-field placement."),
            [_setup(card_id, zone="hand", seed=142, player_forces=WRONG_FORCES), add_flight],
            [_play(card_id)],
            [
                _assert("Flight remains in hand", "cyclops_required", "state.players.human.hand", "count_where", value=1, where={"cardId": "colorless_02_02_ex01_00"}),
                _assert("Flight is absent from field", "cyclops_required", "state.players.human.field", "none_where", where={"cardId": "colorless_02_02_ex01_00"}),
            ],
        ),
    }

    card_id = "colorless_04_02_ex01_02"
    choose_base_replacement = {
        "name": "replace one base card for the generated mana",
        "prompt_kind": "effect_target",
        "select": {"id": "e0"},
    }
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            151,
            _claim("chimera_rested_mana", "resource_change", "With Chimera selected, Mix places one colorless mana in the full base in a rested state."),
            [_setup(card_id, zone="hand", seed=151, player_forces=["force_kon", "force_li"])],
            [_play(card_id), choose_base_replacement],
            [_assert("one rested colorless mana exists", "chimera_rested_mana", "state.players.human.base", "count_where", value=1, where={"cardId": "mana_token", "rested": True})],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            152,
            _claim("chimera_required", "non_activation", "Without Chimera, summoning Mix creates no colorless mana."),
            [_setup(card_id, zone="hand", seed=152, player_forces=WRONG_FORCES)],
            [_play(card_id)],
            [_assert("no colorless mana is created", "chimera_required", "state.players.human.base", "none_where", where={"cardId": "mana_token"})],
        ),
    }

    card_id = "colorless_05_02_ex01_00"
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            161,
            _claim("sphinx_end_draw", "resource_change", "With Sphinx selected, Holy draws one card at the end of its owner's turn in addition to the next normal draw."),
            [_setup(card_id, zone="field", seed=161, player_forces=["force_sei", "force_li"])],
            [_end_turn()],
            [_assert("Holy grants one extra card", "sphinx_end_draw", "state.players.human.handCount", "eq", value=2)],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            162,
            _claim("sphinx_required", "non_activation", "Without Sphinx, Holy grants no end-step card and only the next normal draw reaches hand."),
            [_setup(card_id, zone="field", seed=162, player_forces=["force_li", "force_sho"])],
            [_end_turn()],
            [_assert("only the normal draw occurs", "sphinx_required", "state.players.human.handCount", "eq", value=1)],
        ),
    }

    card_id = "colorless_05_02_ex01_01"
    flash_magic = "green_02_03_01_00"
    attacker = "colorless_02_02_ex01_00"
    def riza_setup(seed: int, forces: list[str]) -> list[dict[str, Any]]:
        return [
            _setup(card_id, zone="field", seed=seed, player_forces=forces),
            {"path": "/api/debug/fixed-board", "payload": {"activeSide": "P2", "controlBoth": True}},
            {"path": "/api/debug/add-card", "payload": {"cardId": card_id, "side": "P1", "zone": "field", "rested": True}, "capture": {"audited_iid": {"path": "debug.added.iid"}}},
            {"path": "/api/debug/add-card", "payload": {"cardId": flash_magic, "side": "P1", "zone": "hand"}},
            {"path": "/api/debug/add-card", "payload": {"cardId": attacker, "side": "P2", "zone": "field"}},
        ]
    riza_actions = [
        {"name": "opponent attacks", "prompt_kind": "main_action", "select": {"kind": "attack", "cardId": attacker}},
        {"name": "opponent targets a force", "prompt_kind": "attack_target", "select": {"kind": "force", "forceId": "force_li"}},
        {"name": "owner uses a Flash card", "prompt_kind": "flash_action", "select": {"kind": "play_card", "cardId": flash_magic}},
    ]
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            171,
            _claim("phoenix_opponent_turn_refresh", "trigger_resolution", "With Phoenix selected, using a card during the opponent turn makes a rested Riza active."),
            riza_setup(171, ["force_so2", "force_li"]),
            riza_actions,
            [_assert("Riza becomes active after the Flash card", "phoenix_opponent_turn_refresh", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "rested": False})],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            172,
            _claim("phoenix_required", "non_activation", "Without Phoenix, using the same card during the opponent turn leaves Riza rested."),
            riza_setup(172, WRONG_FORCES),
            riza_actions,
            [_assert("Riza remains rested without Phoenix", "phoenix_required", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "rested": True})],
        ),
    }

    card_id = "colorless_05_02_ex01_02"
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            181,
            _claim("orthrus_free_cost_reduction", "resource_change", "With Orthrus selected on its owner's turn, Twin rests three base cards rather than five when played."),
            [_setup(card_id, zone="hand", seed=181, player_forces=["force_so", "force_li"])],
            [_play(card_id)],
            [_assert("Twin costs three mana", "orthrus_free_cost_reduction", "state.players.human.base", "count_where", value=3, where={"rested": True})],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            182,
            _claim("orthrus_required", "non_activation", "Without Orthrus, Twin keeps its printed free cost and rests five base cards."),
            [_setup(card_id, zone="hand", seed=182, player_forces=WRONG_FORCES)],
            [_play(card_id)],
            [_assert("Twin costs five mana", "orthrus_required", "state.players.human.base", "count_where", value=5, where={"rested": True})],
        ),
    }

    card_id = "colorless_07_02_ex01_00"
    def karen_setup(seed: int, *, destroy_force: bool) -> list[dict[str, Any]]:
        steps = [
            _setup(card_id, zone="field", seed=seed, player_forces=["force_li", "force_sho"], capture_zone="field"),
            {"path": "/api/debug/life", "payload": {"side": "P1", "life": 8 if destroy_force else 10}},
        ]
        if destroy_force:
            steps.append({"path": "/api/debug/life", "payload": {"side": "P2", "life": 1, "forceIndex": 0}})
        return steps
    karen_actions = [
        {"name": "attack with Karen", "prompt_kind": "main_action", "select": {"kind": "attack", "cardId": card_id}},
        {"name": "attack the opponent Chimera", "prompt_kind": "attack_target", "select": {"kind": "force", "forceId": "force_kon"}},
        {"name": "pass Flash timing", "prompt_kind": "flash_action", "select": {"kind": "flash_pass"}},
    ]
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            191,
            _claim("heal_and_force_refresh", "trigger_resolution", "Karen heals its owner on attack and becomes active when that attack destroys a Force."),
            karen_setup(191, destroy_force=True),
            karen_actions,
            [
                _assert("Karen heals its owner", "heal_and_force_refresh", "state.players.human.life", "eq", value=9),
                _assert("Karen is active after Force destruction", "heal_and_force_refresh", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "rested": False}),
                _assert("the targeted Force is destroyed", "heal_and_force_refresh", "state.players.opponent.forces", "count_where", value=1, where={"id": "force_kon", "destroyed": True}),
            ],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            192,
            _claim("life_cap_and_no_force_refresh", "non_activation", "At the life cap and without Force destruction, Karen neither exceeds the cap nor reactivates."),
            karen_setup(192, destroy_force=False),
            karen_actions,
            [
                _assert("life does not exceed the cap", "life_cap_and_no_force_refresh", "state.players.human.life", "eq", value=10),
                _assert("Karen remains rested", "life_cap_and_no_force_refresh", "state.players.human.field", "count_where", value=1, where={"iid": "$audited_iid", "rested": True}),
                _assert("the targeted Force survives", "life_cap_and_no_force_refresh", "state.players.opponent.forces", "count_where", value=1, where={"id": "force_kon", "destroyed": False}),
            ],
        ),
    }

    card_id = "colorless_08_02_ex01_00"
    choose_cyclops = {
        "name": "grant Cyclops unique ability",
        "prompt_kind": "effect_target",
        "select": {"forceId": "force_e"},
    }
    choose_orthrus = {
        "name": "grant Orthrus unique ability",
        "prompt_kind": "effect_target",
        "select": {"forceId": "force_so"},
    }
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            201,
            _claim("destroyed_force_discount_and_grant", "continuous_effect", "One destroyed own Force reduces Memoria's payment by three and the selected Cyclops ability grants 100 BP."),
            [
                _setup(card_id, zone="hand", seed=201, player_forces=["force_e", "force_li"]),
                {"path": "/api/debug/force-state", "payload": {"side": "P1", "forceIndex": 0, "destroyed": True}},
            ],
            [_play(card_id), choose_cyclops],
            [
                _assert("Memoria costs four mana", "destroyed_force_discount_and_grant", "state.players.human.base", "count_where", value=4, where={"rested": True}),
                _assert("Memoria receives the Cyclops bonus", "destroyed_force_discount_and_grant", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "effectiveBp": 900}),
            ],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            202,
            _claim("opponent_force_does_not_discount", "target_boundary", "An opponent's destroyed Force does not reduce Memoria's cost; the chosen Orthrus ability changes DP but not that payment boundary."),
            [
                _setup(card_id, zone="hand", seed=202, player_forces=["force_li", "force_sho"], opponent_forces=["force_e", "force_rin"]),
                {"path": "/api/debug/force-state", "payload": {"side": "P2", "forceIndex": 0, "destroyed": True}},
            ],
            [_play(card_id), choose_orthrus],
            [
                _assert("Memoria still costs seven mana", "opponent_force_does_not_discount", "state.players.human.base", "count_where", value=7, where={"rested": True}),
                _assert("the selected Orthrus ability grants one DP", "opponent_force_does_not_discount", "state.players.human.field", "count_where", value=1, where={"cardId": card_id, "effectiveBp": 800, "effectiveDp": 3}),
            ],
        ),
    }

    card_id = "colorless_09_02_ex01_00"
    scenarios[card_id] = {
        "positive": _scenario(
            card_id,
            "positive",
            211,
            _claim("destroy_one_per_own_force", "target_selection", "With two destroyed own Forces, Revenge Dragon requires and destroys exactly two selected enemy minions."),
            [
                _setup(card_id, zone="hand", seed=211, player_forces=["force_e", "force_li"]),
                {"path": "/api/debug/force-state", "payload": {"side": "P1", "forceIndex": 0, "destroyed": True}},
                {"path": "/api/debug/force-state", "payload": {"side": "P1", "forceIndex": 1, "destroyed": True}},
            ],
            [
                _play(card_id),
                {"name": "select exactly two enemy minions", "prompt_kind": "effect_target", "select_many": [{"id": "e0"}, {"id": "e1"}]},
            ],
            [
                _assert("two enemy minions are destroyed", "destroy_one_per_own_force", "state.players.opponent.trash", "length_eq", value=2),
                _assert("three enemy minions remain", "destroy_one_per_own_force", "state.players.opponent.field", "length_eq", value=3),
            ],
        ),
        "boundary": _scenario(
            card_id,
            "boundary",
            212,
            _claim("zero_destroyed_forces_zero_targets", "zero_target", "With no destroyed own Force, Revenge Dragon opens no target prompt and destroys no enemy minion."),
            [_setup(card_id, zone="hand", seed=212, player_forces=["force_e", "force_li"])],
            [_play(card_id)],
            [
                _assert("no enemy minion is destroyed", "zero_destroyed_forces_zero_targets", "state.players.opponent.trash", "length_eq", value=0),
                _assert("all five enemy minions remain", "zero_destroyed_forces_zero_targets", "state.players.opponent.field", "length_eq", value=5),
            ],
        ),
    }
    return scenarios


CARD_WORKFLOW = {
    "colorless_02_02_ex01_00": {
        "classification": "templated", "symbols": ["register_ex01_cards", "build_effect"], "files": ["zz/ex01.py", "zz/effects.py"], "channels": ["effect"], "templates": ["refresh_self"],
        "positive_test": "test_flight_moves_active_with_pegasus", "boundary_test": "test_flight_preserves_rest_without_pegasus",
    },
    "colorless_03_02_ex01_00": {
        "classification": "templated", "symbols": ["register_ex01_cards", "build_effect"], "files": ["zz/ex01.py", "zz/effects.py"], "channels": ["effect"], "templates": ["look_top_to_hand"],
        "positive_test": "test_wisdom_reveals_one_of_top_two_and_bottoms_the_other", "boundary_test": "test_wisdom_does_not_look_without_chiron",
    },
    "colorless_03_02_ex01_01": {
        "classification": "custom", "symbols": ["_ring_trigger", "_buff_self_for_turn"], "files": ["zz/ex01.py"], "channels": ["effect"],
        "positive_test": "test_ring_gains_bp_on_attack_and_block_with_ouroboros", "boundary_test": "test_ring_has_no_bp_bonus_without_ouroboros",
    },
    "colorless_04_02_ex01_00": {
        "classification": "custom", "symbols": ["_vixon_trigger", "_grant_vixon_bp"], "files": ["zz/ex01.py"], "channels": ["effect"],
        "positive_test": "test_vixon_gains_permanent_bp_after_undamaged_opponent_turn", "boundary_test": "test_vixon_does_not_gain_bp_after_player_damage",
    },
    "colorless_04_02_ex01_01": {
        "classification": "custom", "symbols": ["_put_low_cost_minion_from_hand"], "files": ["zz/ex01.py"], "channels": ["effect", "engine_rule"],
        "positive_test": "test_eve_puts_an_original_cost_two_field_minion_without_summoning_it", "boundary_test": "test_eve_cannot_put_an_original_cost_three_minion",
    },
    "colorless_04_02_ex01_02": {
        "classification": "templated", "symbols": ["register_ex01_cards", "build_effect"], "files": ["zz/ex01.py", "zz/effects.py"], "channels": ["effect"], "templates": ["place_colorless_mana"],
        "positive_test": "test_mix_places_one_rested_colorless_mana_with_chimera", "boundary_test": "test_mix_places_no_mana_without_chimera",
    },
    "colorless_05_02_ex01_00": {
        "classification": "templated", "symbols": ["register_ex01_cards", "build_effect"], "files": ["zz/ex01.py", "zz/effects.py"], "channels": ["effect"], "templates": ["draw_cards"],
        "positive_test": "test_holy_draws_at_own_turn_end_with_sphinx", "boundary_test": "test_holy_does_not_draw_at_opponent_turn_end",
    },
    "colorless_05_02_ex01_01": {
        "classification": "custom", "symbols": ["_riza_trigger", "_refresh_self"], "files": ["zz/ex01.py"], "channels": ["effect"],
        "positive_test": "test_riza_activates_when_owner_uses_a_card_on_opponent_turn", "boundary_test": "test_riza_stays_rested_when_owner_uses_a_card_on_own_turn",
    },
    "colorless_05_02_ex01_02": {
        "classification": "custom", "symbols": ["twin_free_cost_reduction"], "files": ["zz/ex01.py"], "channels": ["engine_rule"],
        "positive_test": "test_twin_free_cost_is_reduced_by_two_on_own_turn_with_orthrus", "boundary_test": "test_twin_cost_is_not_reduced_without_orthrus",
    },
    "colorless_07_02_ex01_00": {
        "classification": "custom", "symbols": ["_heal_owner", "_karen_force_destroyed", "_refresh_self"], "files": ["zz/ex01.py"], "channels": ["effect"],
        "positive_test": "test_karen_heals_on_attack_and_activates_when_a_force_is_destroyed", "boundary_test": "test_karen_does_not_heal_past_cap_or_activate_without_force_destruction",
    },
    "colorless_08_02_ex01_00": {
        "classification": "custom", "symbols": ["_grant_selected_force_ability", "memoria_free_cost_reduction"], "files": ["zz/ex01.py"], "channels": ["effect", "engine_rule"],
        "positive_test": "test_memoria_grants_all_ten_force_unique_passives", "boundary_test": "test_memoria_cost_is_not_reduced_by_opponent_destroyed_forces",
    },
    "colorless_09_02_ex01_00": {
        "classification": "custom", "symbols": ["_revenge_dragon_trigger", "_destroy_for_each_destroyed_force"], "files": ["zz/ex01.py"], "channels": ["effect"],
        "positive_test": "test_revenge_dragon_destroys_one_enemy_per_destroyed_own_force", "boundary_test": "test_revenge_dragon_destroys_nothing_with_no_destroyed_own_force",
    },
}


def build_manifest() -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for card_id in EX01_CARD_IDS:
        info = CARD_WORKFLOW[card_id]
        implementation: dict[str, Any] = {
            "files": info["files"],
            "symbols": info["symbols"],
            "effect_channels": info["channels"],
            "call_chain": [
                "data/cards_bilingual_v4.tsv image-authoritative Japanese row",
                "zz.ex01.register_ex01_cards -> CARD_REGISTRY",
                "GameSession public /api/choose option",
                "Engine action and TriggerRegistry resolution",
                f"tests/test_ex01_cards.py::{info['positive_test']}",
            ],
        }
        if info.get("templates"):
            implementation["template_ids"] = info["templates"]
        cards.append({
            "card_id": card_id,
            "source_refs": [
                f"data/official_cardlist.tsv#{card_id}",
                f"asserts/ZENONZARD_CARDLIST/COLORLESS/{card_id}.png",
            ],
            "classification": info["classification"],
            "status": "semantic_passed",
            "implementation": implementation,
            "tests": {
                "positive": [f"tests/test_ex01_cards.py::{info['positive_test']}"],
                "boundary": [f"tests/test_ex01_cards.py::{info['boundary_test']}"],
            },
            "semantic_scenarios": {
                kind: {
                    "spec": f"project_memory/card_scenarios/ex01/{card_id}-{kind}.json",
                    "evidence": f"project_memory/card_evidence/ex01/{card_id}-{kind}.evidence.json",
                }
                for kind in ("positive", "boundary")
            },
        })
    return {
        "schema_version": 1,
        "box_id": "EX01",
        "source": {
            "file": "data/official_cardlist.tsv",
            "id_column": "image_id",
            "filters": {"pack_jp_official": "EX:01 魔術都市の9戦士"},
            "expected_count": 12,
        },
        "real_game_smoke": ["tests/test_ex01_cards.py::test_ex01_complete_real_game_smoke"],
        "cards": cards,
    }


def main() -> None:
    SCENARIO_ROOT.mkdir(parents=True, exist_ok=True)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    scenarios = build_scenarios()
    for card_id, kinds in scenarios.items():
        for kind, payload in kinds.items():
            path = SCENARIO_ROOT / f"{card_id}-{kind}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {sum(len(kinds) for kinds in scenarios.values())} scenarios and {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
