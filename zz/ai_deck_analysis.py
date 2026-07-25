from __future__ import annotations

import argparse
import json
import random
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.decks import deck_card_max_copies, is_user_deck_card_id, validate_user_deck_recipe
from zz.enums import CardType, Color
from zz.forces import ALL_FORCES
from zz.model import Card
from zz.sim import play_one_game
from zz.web.deck_store import DeckStore


NO_EFFECT_TEXTS = {"", "効果なし", "（効果なし）", "(効果なし)"}


@dataclass(frozen=True)
class DeckSpec:
    id: str
    name: str
    recipe: dict[str, int]
    forces: list[str]


def load_saved_decks(root: str | Path | None = None) -> list[DeckSpec]:
    decks = []
    for deck in DeckStore(root).list_decks():
        recipe = {str(card_id): int(count) for card_id, count in deck["recipe"].items()}
        forces = [str(force_id) for force_id in deck["forces"]]
        decks.append(
            DeckSpec(
                id=str(deck["id"]),
                name=str(deck["name"]),
                recipe=recipe,
                forces=forces,
            )
        )
    return decks


def card_primary_color(card: Card) -> Color:
    if card.mana_color is not None:
        return card.mana_color
    for color in card.cost:
        if color is not Color.COLORLESS:
            return color
    return Color.COLORLESS


def card_total_cost(card: Card) -> int:
    return sum(card.cost.values())


def recipe_card_slots(recipe: dict[str, int]) -> list[Card]:
    slots: list[Card] = []
    for card_id, count in recipe.items():
        slots.extend([CARD_REGISTRY[card_id]] * count)
    return slots


def deck_distribution(decks: list[DeckSpec]) -> dict[str, Any]:
    cost_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()
    color_counter: Counter[str] = Counter()
    total = 0
    for deck in decks:
        for card in recipe_card_slots(deck.recipe):
            total += 1
            cost_counter[str(card_total_cost(card))] += 1
            type_counter[card.type.value] += 1
            color_counter[card_primary_color(card).name.lower()] += 1
    return {
        "total_cards": total,
        "cost": dict(sorted(cost_counter.items(), key=lambda item: int(item[0]))),
        "type": dict(sorted(type_counter.items())),
        "color": dict(sorted(color_counter.items())),
    }


def effectless_cards_in_decks(decks: list[DeckSpec]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for deck in decks:
        for card_id in deck.recipe:
            if card_id in seen:
                continue
            seen.add(card_id)
            card = CARD_REGISTRY[card_id]
            ability = (card.ability_jp or "").strip()
            if ability in NO_EFFECT_TEXTS:
                continue
            if card.effects or card.triggers or card.keywords or card.aura or card.flash_ability:
                continue
            rows.append(
                {
                    "card_id": card_id,
                    "name": card.name_jp,
                    "type": card.type.value,
                    "color": card_primary_color(card).name.lower(),
                    "ability_jp": ability,
                }
            )
    return rows


def _sample_color(source_decks: list[DeckSpec], rng: random.Random) -> Color:
    colors = deck_buildable_colors()
    if not colors:
        colors = [
            card_primary_color(card)
            for deck in source_decks
            for card in recipe_card_slots(deck.recipe)
            if card_primary_color(card) is not Color.COLORLESS
        ]
    if not colors:
        colors = [color for color in Color if color is not Color.COLORLESS]
    return rng.choice(colors)


def deck_buildable_colors() -> list[Color]:
    return sorted(
        {
            card_primary_color(card)
            for card_id, card in CARD_REGISTRY.items()
            if is_user_deck_card_id(card_id) and card_primary_color(card) is not Color.COLORLESS
        },
        key=lambda color: color.value,
    )


def _source_shape_slots(source_decks: list[DeckSpec]) -> list[tuple[CardType, int]]:
    slots = [
        (card.type, card_total_cost(card))
        for deck in source_decks
        for card in recipe_card_slots(deck.recipe)
    ]
    if not slots:
        raise ValueError("at least one source deck is required")
    return slots


def _candidate_pool(color: Color) -> list[Card]:
    allowed = {color, Color.COLORLESS}
    return [
        card
        for card_id, card in CARD_REGISTRY.items()
        if is_user_deck_card_id(card_id) and card_primary_color(card) in allowed
    ]


def _choose_card_for_slot(
    candidates: list[Card],
    rng: random.Random,
    recipe: dict[str, int],
    wanted_type: CardType,
    wanted_cost: int,
) -> Card:
    def available(card: Card) -> bool:
        return recipe.get(card.id, 0) < deck_card_max_copies(card.id)

    pools = [
        [
            card
            for card in candidates
            if available(card) and card.type is wanted_type and card_total_cost(card) == wanted_cost
        ],
        [card for card in candidates if available(card) and card.type is wanted_type],
        [card for card in candidates if available(card)],
    ]
    for pool in pools:
        if pool:
            return rng.choice(pool)
    raise ValueError("not enough legal cards to build a 40-card random deck")


def generate_random_recipe(
    source_decks: list[DeckSpec],
    *,
    rng: random.Random,
    color: Color | None = None,
) -> dict[str, int]:
    chosen_color = color or _sample_color(source_decks, rng)
    shape_slots = _source_shape_slots(source_decks)
    candidates = _candidate_pool(chosen_color)
    if not candidates:
        raise ValueError(f"no deck-buildable candidates for color {chosen_color.name}")
    recipe: dict[str, int] = {}
    while sum(recipe.values()) < 40:
        wanted_type, wanted_cost = rng.choice(shape_slots)
        card = _choose_card_for_slot(candidates, rng, recipe, wanted_type, wanted_cost)
        recipe[card.id] = recipe.get(card.id, 0) + 1
    validate_user_deck_recipe(recipe)
    return recipe


def generate_random_decks(
    source_decks: list[DeckSpec],
    *,
    count: int,
    rng: random.Random,
) -> list[DeckSpec]:
    observed_forces = sorted({force_id for deck in source_decks for force_id in deck.forces})
    force_pool = observed_forces if len(observed_forces) >= 2 else sorted(ALL_FORCES)
    random_decks: list[DeckSpec] = []
    for index in range(count):
        color = _sample_color(source_decks, rng)
        recipe = generate_random_recipe(source_decks, rng=rng, color=color)
        random_decks.append(
            DeckSpec(
                id=f"random-{index + 1:02d}-{color.name.lower()}",
                name=f"Random {index + 1:02d} {color.name.title()}",
                recipe=recipe,
                forces=rng.sample(force_pool, 2),
            )
        )
    return random_decks


def _play_safe(seed: int, p1: DeckSpec, p2: DeckSpec) -> dict[str, Any]:
    try:
        winner, turns = play_one_game(
            seed,
            p1_recipe=p1.recipe,
            p2_recipe=p2.recipe,
            p1_forces=p1.forces,
            p2_forces=p2.forces,
        )
        return {"winner": winner, "turns": turns, "error": None}
    except Exception as exc:  # pragma: no cover - diagnostic path for live simulations
        return {
            "winner": "error",
            "turns": None,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=8),
            },
        }


def run_round_robin(
    decks: list[DeckSpec],
    *,
    games_per_side: int,
    seed: int,
) -> dict[str, Any]:
    standings: dict[str, Counter[str]] = defaultdict(Counter)
    matchup_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seed_cursor = seed
    for left_index, left in enumerate(decks):
        for right in decks[left_index + 1 :]:
            row = {
                "left_id": left.id,
                "left_name": left.name,
                "right_id": right.id,
                "right_name": right.name,
                "left_wins": 0,
                "right_wins": 0,
                "ties": 0,
                "errors": 0,
                "games": games_per_side * 2,
                "turns_total": 0,
            }
            pairings = ((left, right, "left", "right"), (right, left, "right", "left"))
            for p1, p2, p1_key, p2_key in pairings:
                for _ in range(games_per_side):
                    result = _play_safe(seed_cursor, p1, p2)
                    current_seed = seed_cursor
                    seed_cursor += 1
                    if result["error"] is not None:
                        row["errors"] += 1
                        errors.append(
                            {
                                "seed": current_seed,
                                "p1": p1.name,
                                "p2": p2.name,
                                "error": result["error"],
                            }
                        )
                        continue
                    row["turns_total"] += int(result["turns"])
                    if result["winner"] == "tie":
                        row["ties"] += 1
                    elif result["winner"] == "P1":
                        row[f"{p1_key}_wins"] += 1
                    elif result["winner"] == "P2":
                        row[f"{p2_key}_wins"] += 1
            played = row["games"] - row["errors"]
            if played:
                row["avg_turns"] = row["turns_total"] / played
            else:
                row["avg_turns"] = None
            for deck, wins_key, losses_key in ((left, "left_wins", "right_wins"), (right, "right_wins", "left_wins")):
                standings[deck.id]["wins"] += row[wins_key]
                standings[deck.id]["losses"] += row[losses_key]
                standings[deck.id]["ties"] += row["ties"]
                standings[deck.id]["errors"] += row["errors"]
                standings[deck.id]["games"] += played
            matchup_rows.append(row)
    standings_rows = []
    for deck in decks:
        stats = standings[deck.id]
        games = max(1, stats["games"])
        standings_rows.append(
            {
                "id": deck.id,
                "name": deck.name,
                "wins": stats["wins"],
                "losses": stats["losses"],
                "ties": stats["ties"],
                "errors": stats["errors"],
                "games": stats["games"],
                "win_rate": stats["wins"] / games,
            }
        )
    standings_rows.sort(key=lambda row: (row["win_rate"], row["wins"]), reverse=True)
    return {"standings": standings_rows, "matchups": matchup_rows, "errors": errors}


def run_random_stress(
    source_decks: list[DeckSpec],
    *,
    random_deck_count: int,
    games: int,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    random_decks = generate_random_decks(source_decks, count=random_deck_count, rng=rng)
    errors: list[dict[str, Any]] = []
    wins: Counter[str] = Counter()
    turns_total = 0
    played = 0
    for index in range(games):
        p1, p2 = rng.sample(random_decks, 2)
        game_seed = seed + 100_000 + index
        result = _play_safe(game_seed, p1, p2)
        if result["error"] is not None:
            errors.append({"seed": game_seed, "p1": p1.name, "p2": p2.name, "error": result["error"]})
            continue
        played += 1
        turns_total += int(result["turns"])
        wins[result["winner"]] += 1
    return {
        "generated_decks": [
            {
                "id": deck.id,
                "name": deck.name,
                "forces": deck.forces,
                "distribution": deck_distribution([deck]),
            }
            for deck in random_decks
        ],
        "effectless_cards": effectless_cards_in_decks(random_decks),
        "games_requested": games,
        "games_played": played,
        "wins": dict(wins),
        "avg_turns": (turns_total / played) if played else None,
        "errors": errors,
    }


def build_report(
    *,
    decks: list[DeckSpec],
    games_per_side: int,
    random_decks: int,
    random_games: int,
    seed: int,
) -> dict[str, Any]:
    return {
        "seed": seed,
        "decks": [
            {"id": deck.id, "name": deck.name, "cards": sum(deck.recipe.values()), "forces": deck.forces}
            for deck in decks
        ],
        "source_distribution": deck_distribution(decks),
        "effectless_cards": effectless_cards_in_decks(decks),
        "round_robin": run_round_robin(decks, games_per_side=games_per_side, seed=seed),
        "random_stress": run_random_stress(
            decks,
            random_deck_count=random_decks,
            games=random_games,
            seed=seed + 50_000,
        ),
    }


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def print_report(report: dict[str, Any]) -> None:
    print(f"Decks: {len(report['decks'])}")
    for deck in report["decks"]:
        print(f"  {deck['name']} ({deck['id']}): {deck['cards']} cards, forces={deck['forces']}")
    print("\nSource distribution:")
    print(json.dumps(report["source_distribution"], ensure_ascii=False, sort_keys=True))
    missing = report["effectless_cards"]
    print(f"\nCards with rules text but no behavior binding: {len(missing)}")
    for row in missing[:20]:
        print(f"  {row['card_id']} {row['name']} [{row['type']}]")
    if len(missing) > 20:
        print(f"  ... {len(missing) - 20} more")
    print("\nRound-robin standings:")
    for row in report["round_robin"]["standings"]:
        print(
            f"  {row['name']}: {row['wins']}-{row['losses']}-{row['ties']} "
            f"({ _format_percent(row['win_rate']) }) errors={row['errors']}"
        )
    rr_errors = report["round_robin"]["errors"]
    print(f"Round-robin errors: {len(rr_errors)}")
    print("\nRandom stress:")
    stress = report["random_stress"]
    avg_turns = stress["avg_turns"]
    avg_turns_text = f"{avg_turns:.1f}" if avg_turns is not None else "n/a"
    print(
        f"  games={stress['games_played']}/{stress['games_requested']} "
        f"avg_turns={avg_turns_text} "
        f"errors={len(stress['errors'])}"
    )
    print(f"  generated cards with rules text but no behavior binding: {len(stress['effectless_cards'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AI simulations for saved Zenonzard decks.")
    parser.add_argument("--deck-root", type=Path)
    parser.add_argument("--games-per-side", type=int, default=10)
    parser.add_argument("--random-decks", type=int, default=20)
    parser.add_argument("--random-games", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260518)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    decks = load_saved_decks(args.deck_root)
    if len(decks) < 2:
        raise SystemExit("Need at least two saved decks to analyze.")
    report = build_report(
        decks=decks,
        games_per_side=args.games_per_side,
        random_decks=args.random_decks,
        random_games=args.random_games,
        seed=args.seed,
    )
    print_report(report)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
