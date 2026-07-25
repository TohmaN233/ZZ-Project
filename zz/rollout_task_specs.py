from __future__ import annotations

import hashlib
import json
from typing import Any

from zz.ai_deck_analysis import DeckSpec
from zz.rollout_store import deterministic_rollout_task_id


DEFAULT_MODEL_SIDES = ("P1", "P2")


def deck_payload(deck: DeckSpec) -> dict[str, Any]:
    return {
        "deckId": str(deck.id),
        "deckName": str(deck.name),
        "recipe": {str(card_id): int(count) for card_id, count in sorted(deck.recipe.items()) if int(count) > 0},
        "forces": sorted(str(force_id) for force_id in deck.forces),
    }


def build_real_game_task_specs(
    *,
    decks: list[DeckSpec],
    run_id: str,
    suite_id: str,
    policy_id: str,
    opponent_policy_id: str,
    task_count: int,
    seed: int,
    difficulty: str,
) -> list[dict[str, Any]]:
    if not decks:
        raise ValueError("at least one deck is required")
    tasks: list[dict[str, Any]] = []
    count = max(0, int(task_count))
    for index in range(count):
        player_deck = decks[index % len(decks)]
        opponent_deck = decks[(index + 1) % len(decks)] if len(decks) > 1 else decks[0]
        model_side = DEFAULT_MODEL_SIDES[index % len(DEFAULT_MODEL_SIDES)]
        true_turn_order = "first" if model_side == "P1" else "second"
        task_seed = int(seed) + index
        task_id = deterministic_rollout_task_id(
            run_id=run_id,
            player_deck_id=player_deck.id,
            opponent_deck_id=opponent_deck.id,
            model_side=model_side,
            true_turn_order=true_turn_order,
            difficulty=difficulty,
            seed=task_seed,
        )
        p1_deck = player_deck if model_side == "P1" else opponent_deck
        p2_deck = opponent_deck if model_side == "P1" else player_deck
        tasks.append(
            {
                "taskId": task_id,
                "runId": run_id,
                "playerDeckId": player_deck.id,
                "opponentDeckId": opponent_deck.id,
                "modelSide": model_side,
                "trueTurnOrder": true_turn_order,
                "difficulty": difficulty,
                "seed": task_seed,
                "status": "pending",
                "taskSpec": {
                    "games": 1,
                    "suiteId": suite_id,
                    "policyId": policy_id,
                    "opponentPolicyId": opponent_policy_id,
                    "playerDeckName": player_deck.name,
                    "opponentDeckName": opponent_deck.name,
                    "modelSide": model_side,
                    "trueTurnOrder": true_turn_order,
                    "difficulty": difficulty,
                    "seed": task_seed,
                    "taskIndex": index,
                    "p1Deck": deck_payload(p1_deck),
                    "p2Deck": deck_payload(p2_deck),
                },
            }
        )
    return tasks


def task_fingerprint(tasks: list[dict[str, Any]]) -> str:
    payload = [
        {
            "taskId": task["taskId"],
            "seed": int(task["seed"]),
            "playerDeckId": task["playerDeckId"],
            "opponentDeckId": task["opponentDeckId"],
            "modelSide": task["modelSide"],
            "difficulty": task["difficulty"],
        }
        for task in sorted(tasks, key=lambda row: str(row["taskId"]))
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]
