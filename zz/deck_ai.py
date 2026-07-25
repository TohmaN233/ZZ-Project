from __future__ import annotations

import argparse
import json
import random
import traceback
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from typing import Iterable

from zz.ai_deck_analysis import DeckSpec, card_primary_color, load_saved_decks
from zz.cards import CARD_REGISTRY
from zz.decks import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
    deck_card_max_copies,
    is_user_deck_card_id,
    validate_forces,
    validate_user_deck_recipe,
)
from zz.enums import CardType, Color
from zz.greedy_ai import GreedyLegalPolicy
from zz.model import Card
from zz.sim import play_one_game
from zz.web.deck_store import DeckStore


CHIMERA_FORCE_ID = "force_kon"

GENERAL_FORCE_PAIR_PRIORITY: tuple[tuple[str, str], ...] = (
    ("force_e", "force_rin"),
    ("force_so2", "force_rin"),
    ("force_kai", "force_rin"),
    ("force_chi", "force_rin"),
    ("force_e", "force_so2"),
    ("force_kai", "force_chi"),
)

CHIMERA_FORCE_PAIR_PRIORITY: tuple[tuple[str, str], ...] = (
    ("force_kon", "force_e"),
    ("force_kon", "force_rin"),
    ("force_kon", "force_so2"),
)

COLOR_FORCE_PAIR_PRIORITY: dict[Color, tuple[tuple[str, str], ...]] = {
    Color.BLUE: (
        ("force_e", "force_rin"),
        ("force_kai", "force_rin"),
        ("force_chi", "force_rin"),
    ),
    Color.GREEN: (
        ("force_so2", "force_rin"),
        ("force_e", "force_rin"),
    ),
    Color.PURPLE: (
        ("force_so2", "force_rin"),
        ("force_e", "force_rin"),
    ),
}

COLOR_ALIASES = {
    "red": Color.RED,
    "yellow": Color.YELLOW,
    "white": Color.WHITE,
    "green": Color.GREEN,
    "blue": Color.BLUE,
    "purple": Color.PURPLE,
}

DEFAULT_TOP_SEARCH_COLOR_SETS: tuple[tuple[str, ...], ...] = (
    ("red",),
    ("yellow",),
    ("white",),
    ("green",),
    ("blue",),
    ("purple",),
    ("red", "green"),
    ("red", "yellow"),
    ("red", "white"),
    ("blue", "green"),
)


def parse_colors(values: Iterable[str]) -> tuple[Color, ...]:
    colors: list[Color] = []
    for value in values:
        key = str(value).strip().lower()
        try:
            color = COLOR_ALIASES[key] if key in COLOR_ALIASES else Color[key.upper()]
        except KeyError as exc:
            raise ValueError(f"unknown deck color: {value}") from exc
        if color is Color.COLORLESS:
            continue
        if color not in colors:
            colors.append(color)
    if not colors:
        raise ValueError("at least one non-colorless color is required")
    return tuple(colors)


def _unique_force_pairs(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    unique: list[tuple[str, str]] = []
    seen: set[frozenset[str]] = set()
    for pair in pairs:
        if len(pair) != 2:
            continue
        validate_forces(list(pair))
        key = frozenset(pair)
        if key in seen:
            continue
        seen.add(key)
        unique.append(pair)
    return unique


def candidate_force_pairs(
    colors: Iterable[str],
    *,
    include_chimera: bool = True,
    max_pairs: int | None = None,
) -> list[tuple[str, str]]:
    parsed_colors = parse_colors(colors)
    primary = parsed_colors[0]
    pairs: list[tuple[str, str]] = []
    if include_chimera and len(parsed_colors) > 1:
        pairs.extend(CHIMERA_FORCE_PAIR_PRIORITY)
    pairs.extend(COLOR_FORCE_PAIR_PRIORITY.get(primary, ()))
    pairs.extend(GENERAL_FORCE_PAIR_PRIORITY)
    if include_chimera and len(parsed_colors) == 1:
        pairs.extend(CHIMERA_FORCE_PAIR_PRIORITY)
    unique = _unique_force_pairs(pairs)
    if max_pairs is not None:
        return unique[: max(1, int(max_pairs))]
    return unique


@dataclass(frozen=True)
class DeckBuildConstraints:
    colors: tuple[Color, ...]
    forces: tuple[str, str]
    allow_multicolor: bool
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_inputs(cls, colors: Iterable[str], forces: Iterable[str]) -> "DeckBuildConstraints":
        parsed_forces = tuple(str(force_id) for force_id in forces)
        validate_forces(list(parsed_forces))
        parsed_colors = parse_colors(colors)
        allow_multicolor = CHIMERA_FORCE_ID in parsed_forces
        warnings: list[str] = []
        if not allow_multicolor and len(parsed_colors) > 1:
            parsed_colors = (parsed_colors[0],)
            warnings.append(f"Chimera is not selected; using only the first color: {parsed_colors[0].name}")
        return cls(
            colors=parsed_colors,
            forces=parsed_forces,
            allow_multicolor=allow_multicolor,
            warnings=warnings,
        )


def legal_candidate_cards(constraints: DeckBuildConstraints) -> list[Card]:
    allowed_colors = set(constraints.colors) | {Color.COLORLESS}
    return [
        card
        for card_id, card in CARD_REGISTRY.items()
        if is_user_deck_card_id(card_id) and card_primary_color(card) in allowed_colors
    ]


def card_total_cost(card: Card) -> int:
    return sum(card.cost.values())


def recipe_slots(recipe: dict[str, int]) -> list[Card]:
    slots: list[Card] = []
    for card_id, count in recipe.items():
        if card_id in CARD_REGISTRY:
            slots.extend([CARD_REGISTRY[card_id]] * count)
    return slots


def _can_add(recipe: dict[str, int], card: Card) -> bool:
    return recipe.get(card.id, 0) < deck_card_max_copies(card.id)


def _available_cards(candidates: list[Card], recipe: dict[str, int]) -> list[Card]:
    return [card for card in candidates if _can_add(recipe, card)]


def _add_card(recipe: dict[str, int], card: Card) -> bool:
    if not _can_add(recipe, card):
        return False
    recipe[card.id] = recipe.get(card.id, 0) + 1
    return True


def _choose_card(
    candidates: list[Card],
    recipe: dict[str, int],
    rng: random.Random,
    *,
    card_type: CardType | None = None,
    costs: set[int] | None = None,
) -> Card:
    available = _available_cards(candidates, recipe)
    pools = []
    if card_type is not None and costs is not None:
        pools.append([card for card in available if card.type is card_type and card_total_cost(card) in costs])
    if costs is not None:
        pools.append([card for card in available if card_total_cost(card) in costs])
    if card_type is not None:
        pools.append([card for card in available if card.type is card_type])
    pools.append(available)
    for pool in pools:
        if pool:
            return rng.choice(pool)
    raise ValueError("not enough legal cards to build a deck")


def _choose_humanlike_card(
    candidates: list[Card],
    recipe: dict[str, int],
    rng: random.Random,
    constraints: DeckBuildConstraints,
    *,
    card_type: CardType | None = None,
    costs: set[int] | None = None,
) -> Card:
    available = _available_cards(candidates, recipe)
    if not available:
        raise ValueError("not enough legal cards to build a deck")
    singletons = _singleton_count(recipe)
    colored_cards = sum(
        count
        for card_id, count in recipe.items()
        if CARD_REGISTRY.get(card_id) is not None and card_primary_color(CARD_REGISTRY[card_id]) in set(constraints.colors)
    )
    weights: list[float] = []
    for card in available:
        existing = recipe.get(card.id, 0)
        color = card_primary_color(card)
        weight = 1.0
        if card_type is not None:
            weight = weight + 7.0 if card.type is card_type else weight * 0.25
        if costs is not None:
            weight = weight + 5.0 if card_total_cost(card) in costs else weight * 0.45
        if existing == 1:
            weight += 9.0
        elif existing >= 2:
            weight += 4.0
        elif singletons >= 12:
            weight *= 0.18
        if color in constraints.colors:
            weight += 2.5
            if colored_cards < 16:
                weight += 5.0
        elif color is Color.COLORLESS and colored_cards < 16:
            weight *= 0.20
        weights.append(weight)
    return _weighted_choice(available, weights, rng)


def _weighted_choice(items: list[Any], weights: list[float], rng: random.Random) -> Any:
    total = sum(max(0.0, weight) for weight in weights)
    if total <= 0.0:
        return rng.choice(items)
    cursor = rng.random() * total
    for item, weight in zip(items, weights):
        cursor -= max(0.0, weight)
        if cursor <= 0.0:
            return item
    return items[-1]


def remove_cost_weighted_half_recipe(
    recipe: dict[str, int],
    *,
    seed: int,
    remaining_cards: int = 20,
) -> tuple[dict[str, int], dict[str, int]]:
    current = {str(card_id): int(count) for card_id, count in recipe.items() if int(count) > 0}
    target_remaining = max(0, min(sum(current.values()), int(remaining_cards)))
    removed: dict[str, int] = {}
    rng = random.Random(seed)
    while sum(current.values()) > target_remaining:
        slots = [card_id for card_id, count in current.items() for _ in range(count)]
        weights = [
            1.0 + max(0, card_total_cost(CARD_REGISTRY[card_id])) * 0.35
            for card_id in slots
            if card_id in CARD_REGISTRY
        ]
        weighted_slots = [card_id for card_id in slots if card_id in CARD_REGISTRY]
        if not weighted_slots:
            raise ValueError("recipe contains no known cards")
        card_id = _weighted_choice(weighted_slots, weights, rng)
        current[card_id] -= 1
        if current[card_id] <= 0:
            del current[card_id]
        removed[card_id] = removed.get(card_id, 0) + 1
    return dict(sorted(current.items())), dict(sorted(removed.items()))


def _recipe_cost_targets(reference_recipe: dict[str, int] | None, partial_recipe: dict[str, int]) -> list[int]:
    if reference_recipe is None:
        return [1, 2, 2, 3, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9]
    reference = Counter(
        card_total_cost(CARD_REGISTRY[card_id])
        for card_id, count in reference_recipe.items()
        if card_id in CARD_REGISTRY
        for _ in range(count)
    )
    partial = Counter(
        card_total_cost(CARD_REGISTRY[card_id])
        for card_id, count in partial_recipe.items()
        if card_id in CARD_REGISTRY
        for _ in range(count)
    )
    targets: list[int] = []
    for cost, target in sorted(reference.items()):
        targets.extend([cost] * max(0, target - partial.get(cost, 0)))
    return targets or [1, 2, 2, 3, 3, 4, 5, 6]


def _recipe_type_targets(reference_recipe: dict[str, int] | None, partial_recipe: dict[str, int]) -> list[CardType]:
    if reference_recipe is None:
        return [
            CardType.F_MINION,
            CardType.F_MINION,
            CardType.F_MINION,
            CardType.MAGIC,
            CardType.F_MINION,
        ]
    reference = Counter(
        CARD_REGISTRY[card_id].type
        for card_id, count in reference_recipe.items()
        if card_id in CARD_REGISTRY
        for _ in range(count)
    )
    partial = Counter(
        CARD_REGISTRY[card_id].type
        for card_id, count in partial_recipe.items()
        if card_id in CARD_REGISTRY
        for _ in range(count)
    )
    targets: list[CardType] = []
    for card_type, target in reference.items():
        targets.extend([card_type] * max(0, target - partial.get(card_type, 0)))
    return targets or [CardType.F_MINION, CardType.F_MINION, CardType.MAGIC]


def _singleton_count(recipe: dict[str, int]) -> int:
    return sum(
        1
        for card_id, count in recipe.items()
        if count == 1 and deck_card_max_copies(card_id) > 1
    )


def generate_completion_recipe(
    partial_recipe: dict[str, int],
    constraints: DeckBuildConstraints,
    *,
    seed: int,
    reference_recipe: dict[str, int] | None = None,
) -> dict[str, int]:
    rng = random.Random(seed)
    candidates = legal_candidate_cards(constraints)
    if not candidates:
        raise ValueError("no legal cards for selected colors")
    recipe = {str(card_id): int(count) for card_id, count in partial_recipe.items() if int(count) > 0}
    if sum(recipe.values()) > 40:
        raise ValueError("partial recipe cannot contain more than 40 cards")
    for card_id, count in recipe.items():
        if card_id not in CARD_REGISTRY:
            raise ValueError(f"unknown card id: {card_id}")
        max_copies = deck_card_max_copies(card_id)
        if count > max_copies:
            raise ValueError(f"{card_id} allows at most {max_copies} copies (got {count})")

    cost_targets = _recipe_cost_targets(reference_recipe, recipe)
    type_targets = _recipe_type_targets(reference_recipe, recipe)
    start_size = sum(recipe.values())
    while sum(recipe.values()) < 40:
        available = _available_cards(candidates, recipe)
        if not available:
            raise ValueError("not enough legal cards to complete deck")
        fill_index = sum(recipe.values()) - start_size
        wanted_cost = cost_targets[fill_index % len(cost_targets)]
        wanted_type = type_targets[fill_index % len(type_targets)]
        singletons = _singleton_count(recipe)
        b_minions = sum(
            count
            for card_id, count in recipe.items()
            if CARD_REGISTRY[card_id].type is CardType.B_MINION
        )
        weights = []
        for card in available:
            existing = recipe.get(card.id, 0)
            weight = 1.0
            if card_total_cost(card) == wanted_cost:
                weight += 6.0
            if card.type is wanted_type:
                weight += 3.0
            if existing == 1:
                weight += 5.0
            elif existing >= 2:
                weight += 3.0
            elif singletons >= 10:
                weight *= 0.35
            if reference_recipe is not None and card.id in reference_recipe:
                weight += 2.0 + min(3, int(reference_recipe[card.id]))
            if card.type is CardType.B_MINION and b_minions < 8:
                weight += 2.0
            weights.append(weight)
        _add_card(recipe, _weighted_choice(available, weights, rng))

    validate_user_deck_recipe(recipe)
    return dict(sorted(recipe.items()))


def generate_candidate_recipe(constraints: DeckBuildConstraints, *, seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    candidates = legal_candidate_cards(constraints)
    if not candidates:
        raise ValueError("no legal cards for selected colors")
    recipe: dict[str, int] = {}
    b_minions = [card for card in candidates if card.type is CardType.B_MINION]
    low_cards = [
        card
        for card in candidates
        if card.type is not CardType.B_MINION and card_total_cost(card) in {1, 2}
    ]

    target_b_minions = min(8, max(0, sum(deck_card_max_copies(card.id) for card in b_minions)))
    while sum(recipe.values()) < target_b_minions and b_minions:
        _add_card(recipe, _choose_humanlike_card(b_minions, recipe, rng, constraints, card_type=CardType.B_MINION, costs={0}))

    def low_count() -> int:
        return sum(
            count
            for card_id, count in recipe.items()
            if card_total_cost(CARD_REGISTRY[card_id]) in {1, 2}
        )

    while sum(recipe.values()) < 40 and low_count() < 10 and low_cards:
        _add_card(recipe, _choose_humanlike_card(low_cards, recipe, rng, constraints, costs={1, 2}))

    curve_costs = [1, 2, 2, 3, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9]
    type_curve = [
        CardType.F_MINION,
        CardType.F_MINION,
        CardType.F_MINION,
        CardType.MAGIC,
        CardType.F_MINION,
        CardType.F_MINION,
        CardType.MAGIC,
    ]
    while sum(recipe.values()) < 40:
        wanted_cost = rng.choice(curve_costs)
        wanted_type = rng.choice(type_curve)
        card = _choose_humanlike_card(candidates, recipe, rng, constraints, card_type=wanted_type, costs={wanted_cost})
        _add_card(recipe, card)

    validate_user_deck_recipe(recipe)
    return dict(sorted(recipe.items()))


def recipe_distribution(recipe: dict[str, int]) -> dict[str, object]:
    cost_counter: Counter[int] = Counter()
    type_counter: Counter[str] = Counter()
    color_counter: Counter[str] = Counter()
    total = 0
    for card_id, count in recipe.items():
        card = CARD_REGISTRY[card_id]
        total += count
        cost_counter[card_total_cost(card)] += count
        type_counter[card.type.value] += count
        color_counter[card_primary_color(card).name] += count
    return {
        "total_cards": total,
        "cost": dict(sorted(cost_counter.items())),
        "type": dict(sorted(type_counter.items())),
        "color": dict(sorted(color_counter.items())),
    }


def _closeness(value: int, target: int, width: int, points: float) -> float:
    return max(0.0, points - abs(value - target) * (points / max(1, width)))


def deck_score(recipe: dict[str, int], constraints: DeckBuildConstraints) -> dict[str, float]:
    slots = recipe_slots(recipe)
    total_cards = len(slots)
    costs = Counter(card_total_cost(card) for card in slots)
    types = Counter(card.type for card in slots)
    low = costs[1] + costs[2]
    mid = costs[3] + costs[4] + costs[5]
    high = sum(count for cost, count in costs.items() if cost >= 6)
    b_minions = types[CardType.B_MINION]
    f_minions = types[CardType.F_MINION]
    magic = types[CardType.MAGIC]

    size = _closeness(total_cards, 40, 40, 10.0)
    curve = _closeness(low, 10, 10, 18.0) + _closeness(mid, 18, 18, 8.0) + _closeness(high, 8, 12, 4.0)
    mana = _closeness(b_minions, 8, 8, 18.0)
    if b_minions < 6:
        mana -= (6 - b_minions) * 4.0
    type_mix = _closeness(f_minions, 25, 25, 10.0) + _closeness(magic, 7, 10, 6.0)
    stats = 0.0
    effects = 0.0
    for card in slots:
        cost = max(1, card_total_cost(card))
        stats += min(2.0, ((card.bp / 100) + (card.dp * 2)) / (cost + 1))
        if card.effects or card.triggers or card.keywords or card.aura or card.flash_ability:
            effects += 0.5
        if card.flash_timing_ok:
            effects += 0.25
    stats = min(12.0, stats / max(1, total_cards) * 8.0)
    effects = min(12.0, effects)

    force_synergy = 0.0
    forces = set(constraints.forces)
    if "force_chi" in forces:
        force_synergy += min(6.0, magic * 0.7)
    if "force_so" in forces:
        force_synergy += min(6.0, high * 0.8)
    if "force_rin" in forces:
        force_synergy += min(6.0, f_minions * 0.2)
    if "force_so2" in forces:
        force_synergy += min(6.0, (mid + high) * 0.18)
    if "force_e" in forces:
        force_synergy += min(6.0, (f_minions + low) * 0.16)
    if CHIMERA_FORCE_ID in forces and len(constraints.colors) > 1:
        force_synergy += 4.0

    singletons = _singleton_count(recipe)
    copy_consistency = max(-12.0, 6.0 - max(0, singletons - 6) * 1.5)

    total = size + curve + mana + type_mix + stats + effects + force_synergy + copy_consistency
    return {
        "total": round(total, 3),
        "size": round(size, 3),
        "curve": round(curve, 3),
        "mana": round(mana, 3),
        "type_mix": round(type_mix, 3),
        "stats": round(stats, 3),
        "effects": round(effects, 3),
        "force_synergy": round(force_synergy, 3),
        "copy_consistency": round(copy_consistency, 3),
        "singletons": float(singletons),
    }


def load_benchmark_decks(deck_root: str | Path | None = None) -> list[DeckSpec]:
    benchmarks = [
        DeckSpec(
            id="template-kanatana-yellow",
            name="Template Kanatana Yellow",
            recipe=dict(KANATANA_YELLOW_RECIPE),
            forces=list(DECKCODE0_YELLOW_FORCES),
        ),
        DeckSpec(
            id="template-demete-green",
            name="Template Demete Green",
            recipe=dict(DEMETE_GREEN_RECIPE),
            forces=list(DECKCODE0_GREEN_FORCES),
        ),
    ]
    seen = {deck.id for deck in benchmarks}
    for deck in load_saved_decks(deck_root):
        if deck.id not in seen:
            benchmarks.append(deck)
            seen.add(deck.id)
    return benchmarks


def load_top_suite_decks(path: str | Path = "data/ai_training/top_deck_suite_v2_latest.json") -> list[DeckSpec]:
    report_path = Path(path)
    if not report_path.exists():
        return []
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    decks: list[DeckSpec] = []
    for index, raw in enumerate(data.get("top10") or [], start=1):
        try:
            recipe = {str(card_id): int(count) for card_id, count in (raw.get("recipe") or {}).items()}
            forces = [str(force_id) for force_id in raw.get("forces") or []]
            validate_user_deck_recipe(recipe)
            validate_forces(forces)
        except (TypeError, ValueError):
            continue
        decks.append(DeckSpec(
            id=f"top-suite-v2-{index:02d}",
            name=f"Top Suite v2 #{index}: {raw.get('name') or raw.get('id') or 'Deck'}",
            recipe=recipe,
            forces=forces,
        ))
    return decks


def load_mixed_benchmark_decks(
    *,
    top_suite_path: str | Path = "data/ai_training/top_deck_suite_v2_latest.json",
    deck_root: str | Path | None = None,
    include_templates: bool = False,
    max_ai_decks: int = 10,
    max_saved_decks: int = 10,
) -> list[DeckSpec]:
    decks: list[DeckSpec] = []
    seen: set[tuple[tuple[tuple[str, int], ...], tuple[str, ...]]] = set()

    def add(deck: DeckSpec) -> None:
        key = (tuple(sorted(deck.recipe.items())), tuple(deck.forces))
        if key not in seen:
            decks.append(deck)
            seen.add(key)

    for deck in load_top_suite_decks(top_suite_path)[: max(0, int(max_ai_decks))]:
        add(deck)
    saved = load_benchmark_decks(deck_root) if include_templates else load_saved_decks(deck_root)
    for deck in saved[: max(0, int(max_saved_decks))]:
        add(deck)
    return decks


def _play_matchup(
    *,
    seed: int,
    left_recipe: dict[str, int],
    left_forces: tuple[str, str] | list[str],
    right_recipe: dict[str, int],
    right_forces: tuple[str, str] | list[str],
) -> dict[str, Any]:
    try:
        winner, turns = play_one_game(
            seed,
            p1_recipe=left_recipe,
            p2_recipe=right_recipe,
            p1_forces=list(left_forces),
            p2_forces=list(right_forces),
            p1_policy=GreedyLegalPolicy(random.Random(seed + 11)),
            p2_policy=GreedyLegalPolicy(random.Random(seed + 29)),
        )
        return {"winner": winner, "turns": turns, "error": None}
    except Exception as exc:  # pragma: no cover - diagnostic report path
        return {
            "winner": "error",
            "turns": None,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=6),
            },
        }


def evaluate_candidate(
    recipe: dict[str, int],
    constraints: DeckBuildConstraints,
    benchmarks: list[DeckSpec],
    *,
    bench_games: int,
    seed: int,
) -> dict[str, Any]:
    wins = 0
    losses = 0
    ties = 0
    errors: list[dict[str, Any]] = []
    turns_total = 0
    played = 0
    cursor = seed
    for benchmark in benchmarks:
        for side in ("candidate_first", "benchmark_first"):
            for _ in range(bench_games):
                if side == "candidate_first":
                    result = _play_matchup(
                        seed=cursor,
                        left_recipe=recipe,
                        left_forces=constraints.forces,
                        right_recipe=benchmark.recipe,
                        right_forces=benchmark.forces,
                    )
                    candidate_winner = "P1"
                else:
                    result = _play_matchup(
                        seed=cursor,
                        left_recipe=benchmark.recipe,
                        left_forces=benchmark.forces,
                        right_recipe=recipe,
                        right_forces=constraints.forces,
                    )
                    candidate_winner = "P2"
                if result["error"] is not None:
                    errors.append({"seed": cursor, "benchmark": benchmark.id, "error": result["error"]})
                else:
                    played += 1
                    turns_total += int(result["turns"])
                    if result["winner"] == "tie":
                        ties += 1
                    elif result["winner"] == candidate_winner:
                        wins += 1
                    else:
                        losses += 1
                cursor += 1
    games = max(1, played)
    return {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "errors": errors,
        "games": played,
        "winRate": wins / games,
        "avgTurns": turns_total / games if played else None,
    }


def _candidate_record(
    candidate_id: str,
    recipe: dict[str, int],
    constraints: DeckBuildConstraints,
    benchmarks: list[DeckSpec],
    *,
    bench_games: int,
    seed: int,
) -> dict[str, Any]:
    heuristic = deck_score(recipe, constraints)
    benchmark = evaluate_candidate(
        recipe,
        constraints,
        benchmarks,
        bench_games=bench_games,
        seed=seed,
    )
    final_score = heuristic["total"] + benchmark["winRate"] * 100 - len(benchmark["errors"]) * 25
    return {
        "id": candidate_id,
        "recipe": recipe,
        "cards": sum(recipe.values()),
        "forces": list(constraints.forces),
        "distribution": recipe_distribution(recipe),
        "heuristic": heuristic,
        "benchmark": benchmark,
        "playoff": {"wins": 0, "losses": 0, "ties": 0, "games": 0, "winRate": 0.0},
        "finalScore": round(final_score, 3),
    }


def _run_playoff(candidates: list[dict[str, Any]], constraints: DeckBuildConstraints, *, games: int, seed: int) -> None:
    if len(candidates) < 2 or games <= 0:
        return
    cursor = seed
    by_id = {candidate["id"]: candidate for candidate in candidates}
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1:]:
            for _ in range(games):
                result = _play_matchup(
                    seed=cursor,
                    left_recipe=left["recipe"],
                    left_forces=constraints.forces,
                    right_recipe=right["recipe"],
                    right_forces=constraints.forces,
                )
                cursor += 1
                if result["error"] is not None:
                    continue
                left_stats = by_id[left["id"]]["playoff"]
                right_stats = by_id[right["id"]]["playoff"]
                left_stats["games"] += 1
                right_stats["games"] += 1
                if result["winner"] == "tie":
                    left_stats["ties"] += 1
                    right_stats["ties"] += 1
                elif result["winner"] == "P1":
                    left_stats["wins"] += 1
                    right_stats["losses"] += 1
                else:
                    right_stats["wins"] += 1
                    left_stats["losses"] += 1
    for candidate in candidates:
        playoff = candidate["playoff"]
        games_played = max(1, int(playoff["games"]))
        playoff["winRate"] = playoff["wins"] / games_played
        candidate["finalScore"] = round(candidate["finalScore"] + playoff["winRate"] * 40, 3)


def run_training(
    *,
    colors: Iterable[str],
    forces: Iterable[str],
    population: int = 32,
    generations: int = 3,
    bench_games: int = 4,
    playoff_games: int = 4,
    seed: int = 20260523,
    deck_root: str | Path | None = None,
    json_out: str | Path | None = None,
    save_deck_name: str | None = None,
) -> dict[str, Any]:
    constraints = DeckBuildConstraints.from_inputs(colors, forces)
    benchmarks = load_benchmark_decks(deck_root)
    all_candidates: list[dict[str, Any]] = []
    generation_rows: list[dict[str, Any]] = []
    cursor = seed
    per_generation = max(1, population)
    for generation in range(max(1, generations)):
        records: list[dict[str, Any]] = []
        for index in range(per_generation):
            candidate_seed = cursor + index
            recipe = generate_candidate_recipe(constraints, seed=candidate_seed)
            record = _candidate_record(
                f"g{generation + 1:02d}-{index + 1:03d}",
                recipe,
                constraints,
                benchmarks,
                bench_games=bench_games,
                seed=seed + 10_000 + generation * 1_000 + index * 100,
            )
            records.append(record)
        records.sort(key=lambda row: row["finalScore"], reverse=True)
        generation_rows.append(
            {
                "generation": generation + 1,
                "bestScore": records[0]["finalScore"],
                "bestId": records[0]["id"],
                "candidates": len(records),
            }
        )
        all_candidates.extend(records[: max(1, min(12, len(records)))])
        cursor += per_generation
    all_candidates.sort(key=lambda row: row["finalScore"], reverse=True)
    top_candidates = all_candidates[: max(1, min(8, len(all_candidates)))]
    _run_playoff(top_candidates, constraints, games=playoff_games, seed=seed + 80_000)
    top_candidates.sort(key=lambda row: row["finalScore"], reverse=True)
    winner = top_candidates[0]
    report = {
        "seed": seed,
        "config": {
            "colors": [color.name for color in constraints.colors],
            "forces": list(constraints.forces),
            "population": population,
            "generations": generations,
            "benchGames": bench_games,
            "playoffGames": playoff_games,
        },
        "warnings": list(constraints.warnings),
        "benchmarks": [
            {"id": deck.id, "name": deck.name, "cards": sum(deck.recipe.values()), "forces": list(deck.forces)}
            for deck in benchmarks
        ],
        "generations": generation_rows,
        "topCandidates": top_candidates,
        "winner": {
            "id": winner["id"],
            "recipe": winner["recipe"],
            "cards": winner["cards"],
            "forces": winner["forces"],
            "finalScore": winner["finalScore"],
            "heuristic": winner["heuristic"],
            "benchmark": winner["benchmark"],
            "playoff": winner["playoff"],
        },
        "errors": [
            error
            for candidate in top_candidates
            for error in candidate["benchmark"]["errors"]
        ],
    }
    if save_deck_name:
        DeckStore(deck_root).save_deck(
            {
                "name": save_deck_name,
                "recipe": winner["recipe"],
                "forces": winner["forces"],
            }
        )
    if json_out is not None:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def run_rl_candidate_search(
    *,
    colors: Iterable[str],
    forces: Iterable[str],
    model_path: str | Path,
    population: int = 32,
    validation_top: int = 8,
    stage1_games: int = 1,
    validation_games: int = 5,
    seed: int = 20260523,
    deck_root: str | Path | None = None,
    json_out: str | Path | None = None,
    save_deck_name: str | None = None,
) -> dict[str, Any]:
    from zz.rl_training import run_deck_matrix_evaluation

    constraints = DeckBuildConstraints.from_inputs(colors, forces)
    benchmarks = load_benchmark_decks(deck_root)
    candidates = [
        DeckSpec(
            id=f"rl-candidate-{index + 1:03d}",
            name=f"RL Candidate {index + 1:03d}",
            recipe=generate_candidate_recipe(constraints, seed=seed + index),
            forces=list(constraints.forces),
        )
        for index in range(max(1, population))
    ]
    stage1 = run_deck_matrix_evaluation(
        model_path=model_path,
        learner_decks=candidates,
        opponent_decks=benchmarks,
        episodes=max(1, stage1_games),
        seed=seed + 10_000,
        seed_count=1,
        opponent="greedy",
    )
    stage1_rows = _rank_rl_candidate_rows(candidates, constraints, stage1)
    stage1_rows.sort(
        key=lambda row: (row["rlEvaluation"]["stage1WinRate"], row["rlEvaluation"]["stage1MinRow"], row["heuristic"]["total"]),
        reverse=True,
    )
    top_rows = stage1_rows[: max(1, min(validation_top, len(stage1_rows)))]
    top_decks = [
        DeckSpec(id=row["id"], name=row["name"], recipe=row["recipe"], forces=row["forces"])
        for row in top_rows
    ]
    validation = run_deck_matrix_evaluation(
        model_path=model_path,
        learner_decks=top_decks,
        opponent_decks=benchmarks,
        episodes=max(1, validation_games),
        seed=seed + 20_000,
        seed_count=2,
        opponent="greedy",
    )
    validated_by_id = _rl_matrix_stats_by_deck(validation)
    for row in top_rows:
        stats = validated_by_id[row["id"]]
        row["rlEvaluation"].update({
            "validationWinRate": stats["wins"] / max(1, stats["games"]),
            "validationMinRow": min(stats["mins"]),
            "validationMeanRow": sum(stats["means"]) / max(1, len(stats["means"])),
            "validationGames": stats["games"],
        })
        row["finalScore"] = round(
            row["heuristic"]["total"] + row["rlEvaluation"]["validationWinRate"] * 100,
            3,
        )
    top_rows.sort(
        key=lambda row: (row["rlEvaluation"]["validationWinRate"], row["rlEvaluation"]["validationMinRow"], row["finalScore"]),
        reverse=True,
    )
    winner = top_rows[0]
    report = {
        "seed": seed,
        "config": {
            "colors": [color.name for color in constraints.colors],
            "forces": list(constraints.forces),
            "population": population,
            "validationTop": validation_top,
            "stage1Games": stage1_games,
            "validationGames": validation_games,
            "rlModelPath": str(model_path),
        },
        "warnings": list(constraints.warnings),
        "benchmarks": [
            {"id": deck.id, "name": deck.name, "cards": sum(deck.recipe.values()), "forces": list(deck.forces)}
            for deck in benchmarks
        ],
        "topCandidates": top_rows,
        "winner": {
            "id": winner["id"],
            "name": winner["name"],
            "recipe": winner["recipe"],
            "cards": winner["cards"],
            "forces": winner["forces"],
            "distribution": winner["distribution"],
            "heuristic": winner["heuristic"],
            "rlEvaluation": winner["rlEvaluation"],
            "finalScore": winner["finalScore"],
        },
    }
    if save_deck_name:
        DeckStore(deck_root).save_deck(
            {
                "name": save_deck_name,
                "recipe": winner["recipe"],
                "forces": winner["forces"],
            }
        )
    if json_out is not None:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _focus_gate_stats(report: dict[str, Any]) -> dict[str, Any]:
    rows = list(report.get("rows") or [])
    row_rates = [float(row.get("winRate", 0.0)) for row in rows]
    games = int(report.get("games", 0))
    wins = int(report.get("wins", 0))
    if games <= 0:
        games = sum(
            int((row.get("results") or {}).get("model", 0))
            + int((row.get("results") or {}).get("opponent", 0))
            + int((row.get("results") or {}).get("tie", 0))
            for row in rows
        )
        wins = sum(int((row.get("results") or {}).get("model", 0)) for row in rows)
    return {
        "wins": wins,
        "games": games,
        "winRate": wins / max(1, games),
        "minRow": min(row_rates, default=0.0),
        "meanRow": sum(row_rates) / max(1, len(row_rates)),
        "limitedGames": int(report.get("limitedGames", 0)),
    }


def run_focus_candidate_search(
    *,
    colors: Iterable[str],
    forces: Iterable[str],
    normal_model_path: str | Path,
    opponent_decks: Iterable[DeckSpec],
    model_side: str = "P2",
    model_kind: str = "normal",
    opponent_kind: str = "normal",
    deep_model_path: str | Path | None = None,
    data_root: str | Path | None = None,
    population: int = 32,
    validation_top: int = 8,
    stage1_games: int = 1,
    validation_games: int = 3,
    stage1_opponent_count: int | None = None,
    max_turns: int = 30,
    max_actions: int = 500,
    seed: int = 20260523,
    json_out: str | Path | None = None,
) -> dict[str, Any]:
    from zz.ai_league import run_difficulty_focus_evaluation

    constraints = DeckBuildConstraints.from_inputs(colors, forces)
    opponents = list(opponent_decks)
    if not opponents:
        raise ValueError("at least one opponent deck is required")
    stage1_count = len(opponents) if stage1_opponent_count is None else max(1, int(stage1_opponent_count))
    stage1_opponents = opponents[: min(len(opponents), stage1_count)]
    candidates = [
        DeckSpec(
            id=f"focus-candidate-{index + 1:03d}",
            name=f"Focus Candidate {index + 1:03d}",
            recipe=generate_candidate_recipe(constraints, seed=seed + index),
            forces=list(constraints.forces),
        )
        for index in range(max(1, int(population)))
    ]
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        gate = run_difficulty_focus_evaluation(
            episodes=max(1, int(stage1_games)),
            seed=seed + 10_000 + index * 997,
            model_kind=model_kind,
            opponent_kind=opponent_kind,
            model_side=model_side,
            model_deck=candidate,
            opponent_decks=stage1_opponents,
            normal_model_path=normal_model_path,
            deep_model_path=deep_model_path,
            data_root=data_root,
            max_turns=max_turns,
            max_actions=max_actions,
        )
        stats = _focus_gate_stats(gate)
        rows.append({
            "id": candidate.id,
            "name": candidate.name,
            "recipe": candidate.recipe,
            "cards": sum(candidate.recipe.values()),
            "forces": list(candidate.forces),
            "distribution": recipe_distribution(candidate.recipe),
            "heuristic": deck_score(candidate.recipe, constraints),
            "rlEvaluation": {
                "stage1WinRate": stats["winRate"],
                "stage1MinRow": stats["minRow"],
                "stage1MeanRow": stats["meanRow"],
                "stage1Wins": stats["wins"],
                "stage1Games": stats["games"],
                "stage1LimitedGames": stats["limitedGames"],
            },
        })
    rows.sort(
        key=lambda row: (
            row["rlEvaluation"]["stage1WinRate"],
            row["rlEvaluation"]["stage1MinRow"],
            row["heuristic"]["total"],
        ),
        reverse=True,
    )
    top_rows = rows[: max(1, min(int(validation_top), len(rows)))]
    for index, row in enumerate(top_rows):
        candidate = candidate_by_id[row["id"]]
        gate = run_difficulty_focus_evaluation(
            episodes=max(1, int(validation_games)),
            seed=seed + 20_000 + index * 997,
            model_kind=model_kind,
            opponent_kind=opponent_kind,
            model_side=model_side,
            model_deck=candidate,
            opponent_decks=opponents,
            normal_model_path=normal_model_path,
            deep_model_path=deep_model_path,
            data_root=data_root,
            max_turns=max_turns,
            max_actions=max_actions,
        )
        stats = _focus_gate_stats(gate)
        row["rlEvaluation"].update({
            "validationWinRate": stats["winRate"],
            "validationMinRow": stats["minRow"],
            "validationMeanRow": stats["meanRow"],
            "validationWins": stats["wins"],
            "validationGames": stats["games"],
            "validationLimitedGames": stats["limitedGames"],
        })
        row["finalScore"] = round(
            row["heuristic"]["total"]
            + stats["winRate"] * 100.0
            + stats["minRow"] * 10.0,
            3,
        )
    top_rows.sort(
        key=lambda row: (
            row["rlEvaluation"].get("validationWinRate", 0.0),
            row["rlEvaluation"].get("validationMinRow", 0.0),
            row.get("finalScore", 0.0),
        ),
        reverse=True,
    )
    winner = top_rows[0]
    report = {
        "kind": "rl_focus_candidate_search",
        "seed": seed,
        "config": {
            "colors": [color.name for color in constraints.colors],
            "forces": list(constraints.forces),
            "modelSide": model_side,
            "modelKind": model_kind,
            "opponentKind": opponent_kind,
            "normalModelPath": str(normal_model_path),
            "deepModelPath": str(deep_model_path) if deep_model_path is not None else None,
            "population": int(population),
            "validationTop": int(validation_top),
            "stage1Games": int(stage1_games),
            "validationGames": int(validation_games),
            "stage1OpponentCount": len(stage1_opponents),
            "opponentDeckCount": len(opponents),
            "maxTurns": int(max_turns),
            "maxActions": int(max_actions),
        },
        "warnings": list(constraints.warnings),
        "benchmarks": [
            {"id": deck.id, "name": deck.name, "cards": sum(deck.recipe.values()), "forces": list(deck.forces)}
            for deck in opponents
        ],
        "topCandidates": top_rows,
        "winner": {
            "id": winner["id"],
            "name": winner["name"],
            "recipe": winner["recipe"],
            "cards": winner["cards"],
            "forces": winner["forces"],
            "distribution": winner["distribution"],
            "heuristic": winner["heuristic"],
            "rlEvaluation": winner["rlEvaluation"],
            "finalScore": winner["finalScore"],
        },
    }
    if json_out is not None:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _color_inputs_from_recipe(recipe: dict[str, int]) -> list[str]:
    colors: list[str] = []
    seen: set[Color] = set()
    for card_id in recipe:
        card = CARD_REGISTRY.get(card_id)
        if card is None:
            continue
        color = card_primary_color(card)
        if color is Color.COLORLESS or color in seen:
            continue
        colors.append(color.name.lower())
        seen.add(color)
    return colors or ["red"]


def _completion_candidate_record(
    *,
    deck: DeckSpec,
    source: DeckSpec,
    partial_recipe: dict[str, int],
    removed_recipe: dict[str, int],
    constraints: DeckBuildConstraints,
    stats: dict[str, Any],
    baseline_stats: dict[str, Any],
) -> dict[str, Any]:
    heuristic = deck_score(deck.recipe, constraints)
    improvement = float(stats["winRate"]) - float(baseline_stats["winRate"])
    improvement_reward = max(0.0, improvement) * 100.0
    final_score = round(
        heuristic["total"]
        + float(stats["winRate"]) * 100.0
        + float(stats["minRow"]) * 10.0
        + improvement_reward,
        3,
    )
    return {
        "id": deck.id,
        "name": deck.name,
        "sourceDeckId": source.id,
        "sourceDeckName": source.name,
        "recipe": deck.recipe,
        "partialRecipe": partial_recipe,
        "removedRecipe": removed_recipe,
        "cards": sum(deck.recipe.values()),
        "forces": list(deck.forces),
        "distribution": recipe_distribution(deck.recipe),
        "heuristic": heuristic,
        "rlEvaluation": {
            "validationWinRate": stats["winRate"],
            "validationMinRow": stats["minRow"],
            "validationMeanRow": stats["meanRow"],
            "validationWins": stats["wins"],
            "validationGames": stats["games"],
            "validationLimitedGames": stats["limitedGames"],
            "baselineWinRate": baseline_stats["winRate"],
            "baselineMinRow": baseline_stats["minRow"],
            "baselineWins": baseline_stats["wins"],
            "baselineGames": baseline_stats["games"],
            "improvement": improvement,
            "improvementReward": improvement_reward,
        },
        "finalScore": final_score,
    }


def run_completion_candidate_search(
    *,
    source_decks: Iterable[DeckSpec],
    benchmark_decks: Iterable[DeckSpec],
    normal_model_path: str | Path,
    model_side: str = "random",
    model_kind: str = "normal",
    opponent_kind: str = "normal",
    deep_model_path: str | Path | None = None,
    data_root: str | Path | None = None,
    completions_per_source: int = 8,
    validation_games: int = 2,
    remaining_cards: int = 20,
    max_turns: int = 30,
    max_actions: int = 500,
    seed: int = 20260523,
    json_out: str | Path | None = None,
) -> dict[str, Any]:
    from zz.ai_league import run_difficulty_focus_evaluation

    sources = list(source_decks)
    benchmarks = list(benchmark_decks)
    if not sources:
        raise ValueError("at least one source deck is required")
    if not benchmarks:
        raise ValueError("at least one benchmark deck is required")

    rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    for source_index, source in enumerate(sources):
        constraints = DeckBuildConstraints.from_inputs(_color_inputs_from_recipe(source.recipe), source.forces)
        partial, removed = remove_cost_weighted_half_recipe(
            source.recipe,
            seed=seed + source_index * 10_000,
            remaining_cards=remaining_cards,
        )
        baseline_gate = run_difficulty_focus_evaluation(
            episodes=max(1, int(validation_games)),
            seed=seed + 100_000 + source_index * 10_000,
            model_kind=model_kind,
            opponent_kind=opponent_kind,
            model_side=model_side,
            model_deck=source,
            opponent_decks=benchmarks,
            normal_model_path=normal_model_path,
            deep_model_path=deep_model_path,
            data_root=data_root,
            max_turns=max_turns,
            max_actions=max_actions,
        )
        baseline_stats = _focus_gate_stats(baseline_gate)
        baseline_rows.append({
            "sourceDeckId": source.id,
            "sourceDeckName": source.name,
            "winRate": baseline_stats["winRate"],
            "minRow": baseline_stats["minRow"],
            "wins": baseline_stats["wins"],
            "games": baseline_stats["games"],
            "limitedGames": baseline_stats["limitedGames"],
        })
        for completion_index in range(max(1, int(completions_per_source))):
            recipe = generate_completion_recipe(
                partial,
                constraints,
                seed=seed + source_index * 10_000 + completion_index + 1,
                reference_recipe=source.recipe,
            )
            deck = DeckSpec(
                id=f"completion-{source.id}-{completion_index + 1:03d}",
                name=f"{source.name} Completion {completion_index + 1:03d}",
                recipe=recipe,
                forces=list(source.forces),
            )
            gate = run_difficulty_focus_evaluation(
                episodes=max(1, int(validation_games)),
                seed=seed + 200_000 + source_index * 10_000 + completion_index * 997,
                model_kind=model_kind,
                opponent_kind=opponent_kind,
                model_side=model_side,
                model_deck=deck,
                opponent_decks=benchmarks,
                normal_model_path=normal_model_path,
                deep_model_path=deep_model_path,
                data_root=data_root,
                max_turns=max_turns,
                max_actions=max_actions,
            )
            stats = _focus_gate_stats(gate)
            rows.append(_completion_candidate_record(
                deck=deck,
                source=source,
                partial_recipe=partial,
                removed_recipe=removed,
                constraints=constraints,
                stats=stats,
                baseline_stats=baseline_stats,
            ))

    rows.sort(
        key=lambda row: (
            row["rlEvaluation"]["improvementReward"],
            row["finalScore"],
            row["rlEvaluation"]["validationWinRate"],
            row["rlEvaluation"]["validationMinRow"],
        ),
        reverse=True,
    )
    winner = rows[0]
    raw_winner = max(
        rows,
        key=lambda row: (
            row["rlEvaluation"]["validationWinRate"],
            row["rlEvaluation"]["validationMinRow"],
            row["finalScore"],
        ),
    )
    report = {
        "kind": "rl_completion_candidate_search",
        "seed": seed,
        "config": {
            "sourceDeckCount": len(sources),
            "benchmarkDeckCount": len(benchmarks),
            "normalModelPath": str(normal_model_path),
            "deepModelPath": str(deep_model_path) if deep_model_path is not None else None,
            "modelSide": model_side,
            "modelKind": model_kind,
            "opponentKind": opponent_kind,
            "completionsPerSource": int(completions_per_source),
            "validationGames": int(validation_games),
            "remainingCards": int(remaining_cards),
            "maxTurns": int(max_turns),
            "maxActions": int(max_actions),
        },
        "baselineRows": baseline_rows,
        "benchmarks": [
            {"id": deck.id, "name": deck.name, "cards": sum(deck.recipe.values()), "forces": list(deck.forces)}
            for deck in benchmarks
        ],
        "topCandidates": rows,
        "winner": {
            "id": winner["id"],
            "name": winner["name"],
            "sourceDeckId": winner["sourceDeckId"],
            "sourceDeckName": winner["sourceDeckName"],
            "recipe": winner["recipe"],
            "partialRecipe": winner["partialRecipe"],
            "removedRecipe": winner["removedRecipe"],
            "cards": winner["cards"],
            "forces": winner["forces"],
            "distribution": winner["distribution"],
            "heuristic": winner["heuristic"],
            "rlEvaluation": winner["rlEvaluation"],
            "finalScore": winner["finalScore"],
        },
        "bestRawCandidate": {
            "id": raw_winner["id"],
            "name": raw_winner["name"],
            "sourceDeckId": raw_winner["sourceDeckId"],
            "sourceDeckName": raw_winner["sourceDeckName"],
            "recipe": raw_winner["recipe"],
            "partialRecipe": raw_winner["partialRecipe"],
            "removedRecipe": raw_winner["removedRecipe"],
            "cards": raw_winner["cards"],
            "forces": raw_winner["forces"],
            "distribution": raw_winner["distribution"],
            "heuristic": raw_winner["heuristic"],
            "rlEvaluation": raw_winner["rlEvaluation"],
            "finalScore": raw_winner["finalScore"],
        },
    }
    if json_out is not None:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def run_auto_force_rl_candidate_search(
    *,
    colors: Iterable[str],
    model_path: str | Path,
    force_pairs: Iterable[tuple[str, str]] | None = None,
    max_force_pairs: int | None = None,
    population: int = 32,
    validation_top: int = 8,
    stage1_games: int = 1,
    validation_games: int = 5,
    seed: int = 20260523,
    deck_root: str | Path | None = None,
    json_out: str | Path | None = None,
    save_deck_name: str | None = None,
) -> dict[str, Any]:
    parsed_colors = parse_colors(colors)
    pairs = (
        _unique_force_pairs(force_pairs)
        if force_pairs is not None
        else candidate_force_pairs([color.name.lower() for color in parsed_colors], max_pairs=max_force_pairs)
    )
    if not pairs:
        raise ValueError("at least one force pair is required")
    force_candidates: list[dict[str, Any]] = []
    flattened: list[dict[str, Any]] = []
    benchmark_rows: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        sub_report = run_rl_candidate_search(
            colors=[color.name.lower() for color in parsed_colors],
            forces=pair,
            model_path=model_path,
            population=population,
            validation_top=validation_top,
            stage1_games=stage1_games,
            validation_games=validation_games,
            seed=seed + index * 100_000,
            deck_root=deck_root,
        )
        if not benchmark_rows:
            benchmark_rows = list(sub_report["benchmarks"])
        winner = sub_report["winner"]
        force_candidate = {
            "forcePair": list(pair),
            "searchOrder": index + 1,
            "colors": sub_report["config"]["colors"],
            "warnings": sub_report["warnings"],
            "winner": winner,
            "topCandidates": sub_report["topCandidates"],
            "bestWinRate": winner["rlEvaluation"]["validationWinRate"],
            "bestMinRow": winner["rlEvaluation"]["validationMinRow"],
        }
        force_candidates.append(force_candidate)
        for row in sub_report["topCandidates"]:
            flattened.append({
                **row,
                "forcePair": list(pair),
                "forceSearchColors": sub_report["config"]["colors"],
                "forceWarnings": sub_report["warnings"],
                "forceSearchRank": index + 1,
            })
    force_candidates.sort(
        key=lambda row: (
            row["bestWinRate"],
            row["bestMinRow"],
            row["winner"]["finalScore"],
        ),
        reverse=True,
    )
    flattened.sort(
        key=lambda row: (
            row["rlEvaluation"]["validationWinRate"],
            row["rlEvaluation"]["validationMinRow"],
            row["finalScore"],
        ),
        reverse=True,
    )
    winner = flattened[0]
    report = {
        "kind": "rl_auto_force_candidate_search",
        "seed": seed,
        "config": {
            "colors": [color.name for color in parsed_colors],
            "searchedForcePairs": [list(pair) for pair in pairs],
            "forcePairs": [candidate["forcePair"] for candidate in force_candidates],
            "populationPerForce": population,
            "validationTopPerForce": validation_top,
            "stage1Games": stage1_games,
            "validationGames": validation_games,
            "rlModelPath": str(model_path),
        },
        "benchmarks": benchmark_rows,
        "forceCandidates": force_candidates,
        "topCandidates": flattened,
        "winner": {
            "id": winner["id"],
            "name": winner["name"],
            "recipe": winner["recipe"],
            "cards": winner["cards"],
            "forces": winner["forces"],
            "forcePair": winner["forcePair"],
            "forceSearchColors": winner["forceSearchColors"],
            "forceWarnings": winner["forceWarnings"],
            "distribution": winner["distribution"],
            "heuristic": winner["heuristic"],
            "rlEvaluation": winner["rlEvaluation"],
            "finalScore": winner["finalScore"],
        },
    }
    if save_deck_name:
        DeckStore(deck_root).save_deck(
            {
                "name": save_deck_name,
                "recipe": report["winner"]["recipe"],
                "forces": report["winner"]["forces"],
            }
        )
    if json_out is not None:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def run_top_deck_search_suite(
    *,
    model_path: str | Path,
    color_sets: Iterable[Iterable[str]] | None = None,
    top_n: int = 10,
    passing_win_rate: float = 0.70,
    max_force_pairs: int | None = None,
    population: int = 32,
    validation_top: int = 8,
    stage1_games: int = 1,
    validation_games: int = 5,
    seed: int = 20260523,
    deck_root: str | Path | None = None,
    json_out: str | Path | None = None,
) -> dict[str, Any]:
    selected_color_sets = [
        tuple(str(color).strip().lower() for color in colors if str(color).strip())
        for colors in (color_sets or DEFAULT_TOP_SEARCH_COLOR_SETS)
    ]
    selected_color_sets = [colors for colors in selected_color_sets if colors]
    if not selected_color_sets:
        raise ValueError("at least one color set is required")

    search_reports: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for index, colors in enumerate(selected_color_sets):
        sub_report = run_auto_force_rl_candidate_search(
            colors=colors,
            model_path=model_path,
            max_force_pairs=max_force_pairs,
            population=population,
            validation_top=validation_top,
            stage1_games=stage1_games,
            validation_games=validation_games,
            seed=seed + index * 100_000,
            deck_root=deck_root,
        )
        search_reports.append({
            "colors": list(sub_report.get("config", {}).get("colors") or [color.upper() for color in colors]),
            "candidateCount": len(sub_report.get("topCandidates") or []),
            "winnerId": (sub_report.get("winner") or {}).get("id"),
            "winnerForces": list((sub_report.get("winner") or {}).get("forces") or []),
        })
        for candidate in sub_report.get("topCandidates") or []:
            record = _suite_candidate_record(candidate, sub_report=sub_report, source_index=index)
            candidates.append(record)

    candidates.sort(key=_suite_candidate_sort_key, reverse=True)
    passing = [
        candidate
        for candidate in candidates
        if float(candidate["rlEvaluation"].get("validationWinRate", 0.0)) >= float(passing_win_rate)
    ]
    top_decks = passing[:max(1, int(top_n))]
    preference_source = passing if passing else candidates
    report = {
        "kind": "rl_top_deck_search_suite",
        "seed": seed,
        "modelPath": str(model_path),
        "acceptance": f"validationWinRate >= {float(passing_win_rate):.2f} vs greedy benchmark deck pool",
        "passingThreshold": float(passing_win_rate),
        "passingCount": len(passing),
        "searchedColorSets": [list(colors) for colors in selected_color_sets],
        "searchReports": search_reports,
        "forcePreference": _force_preference_from_candidates(preference_source),
        "top10": top_decks,
        "candidateCount": len(candidates),
    }
    if json_out is not None:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def run_ai_deckbuilder_vs_human_suite(
    *,
    deep_model_path: str | Path,
    normal_model_path: str | Path | None = None,
    data_root: str | Path | None = None,
    human_decks: Iterable[DeckSpec] | None = None,
    deck_root: str | Path | None = None,
    color_sets: Iterable[Iterable[str]] | None = None,
    force_pairs: Iterable[tuple[str, str]] | None = None,
    model_kind: str = "deep",
    opponent_kind: str | None = None,
    top_n: int = 10,
    comparison_pass_threshold: float = 0.50,
    max_human_decks: int | None = None,
    max_force_pairs: int | None = None,
    population: int = 12,
    validation_top: int = 3,
    stage1_games: int = 1,
    stage1_opponent_count: int | None = None,
    validation_games: int = 1,
    comparison_games: int = 2,
    comparison_model_side: str = "random",
    max_turns: int = 30,
    max_actions: int = 500,
    seed: int = 20260523,
    json_out: str | Path | None = None,
) -> dict[str, Any]:
    from zz.ai_league import run_deck_set_comparison_gate

    selected_human_decks = list(human_decks) if human_decks is not None else load_saved_decks(deck_root)
    if not selected_human_decks:
        selected_human_decks = load_benchmark_decks(deck_root)
    if max_human_decks is not None:
        selected_human_decks = selected_human_decks[: max(1, int(max_human_decks))]
    if not selected_human_decks:
        raise ValueError("AI deckbuilder suite requires at least one human/reference deck")

    resolved_opponent_kind = opponent_kind or model_kind
    selected_color_sets = [
        tuple(str(color).strip().lower() for color in colors if str(color).strip())
        for colors in (color_sets or DEFAULT_TOP_SEARCH_COLOR_SETS)
    ]
    selected_color_sets = [colors for colors in selected_color_sets if colors]
    if not selected_color_sets:
        raise ValueError("AI deckbuilder suite requires at least one color set")

    explicit_force_pairs = _unique_force_pairs(force_pairs) if force_pairs is not None else None
    search_reports: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    search_index = 0
    for color_index, colors in enumerate(selected_color_sets):
        pairs = explicit_force_pairs or candidate_force_pairs(colors, max_pairs=max_force_pairs)
        for pair_index, pair in enumerate(pairs):
            search_index += 1
            sub_report = run_focus_candidate_search(
                colors=colors,
                forces=pair,
                normal_model_path=normal_model_path,
                deep_model_path=deep_model_path,
                data_root=data_root,
                opponent_decks=selected_human_decks,
                model_side=comparison_model_side,
                model_kind=model_kind,
                opponent_kind=resolved_opponent_kind,
                population=population,
                validation_top=validation_top,
                stage1_games=stage1_games,
                stage1_opponent_count=stage1_opponent_count,
                validation_games=validation_games,
                max_turns=max_turns,
                max_actions=max_actions,
                seed=seed + color_index * 100_000 + pair_index * 10_000,
            )
            search_reports.append({
                "searchIndex": search_index,
                "colors": list(sub_report.get("config", {}).get("colors") or [color.upper() for color in colors]),
                "forcePair": list(pair),
                "winnerId": (sub_report.get("winner") or {}).get("id"),
                "winnerWinRate": ((sub_report.get("winner") or {}).get("rlEvaluation") or {}).get("validationWinRate"),
                "candidateCount": len(sub_report.get("topCandidates") or []),
            })
            for rank, candidate in enumerate(sub_report.get("topCandidates") or [], start=1):
                record = _suite_candidate_record(candidate, sub_report=sub_report, source_index=search_index - 1)
                source_id = record["id"]
                record["id"] = f"ai-suite-{search_index:02d}-{rank:03d}"
                record["name"] = f"AI Suite {search_index:02d}-{rank:03d}: {record['name']}"
                record["sourceCandidateId"] = source_id
                record["sourceColors"] = list(colors)
                candidates.append(record)

    candidates.sort(key=_suite_candidate_sort_key, reverse=True)
    top_candidates = candidates[: max(1, int(top_n))]
    candidate_decks = [
        DeckSpec(
            id=row["id"],
            name=row["name"],
            recipe=dict(row["recipe"]),
            forces=list(row["forces"]),
        )
        for row in top_candidates
    ]
    comparison_gate = run_deck_set_comparison_gate(
        episodes=max(1, int(comparison_games)),
        seed=seed + 700_000,
        model_kind=model_kind,
        opponent_kind=resolved_opponent_kind,
        model_side=comparison_model_side,
        pass_threshold=comparison_pass_threshold,
        normal_model_path=normal_model_path,
        deep_model_path=deep_model_path,
        data_root=data_root,
        candidate_decks=candidate_decks,
        reference_decks=selected_human_decks,
        max_turns=max_turns,
        max_actions=max_actions,
    )
    comparison_by_id = {
        row["candidateDeckId"]: row
        for row in (comparison_gate.get("gate") or {}).get("perCandidateDeck", [])
    }
    for row in top_candidates:
        comparison = comparison_by_id.get(row["id"], {})
        row["comparison"] = {
            "wins": int(comparison.get("wins", 0)),
            "games": int(comparison.get("games", 0)),
            "winRate": float(comparison.get("winRate", 0.0)),
        }
    top_candidates.sort(
        key=lambda row: (
            row["comparison"]["winRate"],
            float(row["rlEvaluation"].get("validationWinRate", 0.0)),
            float(row["rlEvaluation"].get("validationMinRow", 0.0)),
            row["finalScore"],
        ),
        reverse=True,
    )
    winner = top_candidates[0]
    report = {
        "kind": "ai_deckbuilder_vs_human_suite",
        "seed": seed,
        "config": {
            "modelKind": model_kind,
            "opponentKind": resolved_opponent_kind,
            "deepModelPath": str(deep_model_path),
            "normalModelPath": str(normal_model_path) if normal_model_path is not None else None,
            "searchedColorSets": [list(colors) for colors in selected_color_sets],
            "forcePairs": [list(pair) for pair in explicit_force_pairs] if explicit_force_pairs is not None else None,
            "topN": int(top_n),
            "comparisonPassThreshold": float(comparison_pass_threshold),
            "humanDeckCount": len(selected_human_decks),
            "population": int(population),
            "validationTop": int(validation_top),
            "stage1Games": int(stage1_games),
            "stage1OpponentCount": stage1_opponent_count,
            "validationGames": int(validation_games),
            "comparisonGames": int(comparison_games),
            "comparisonModelSide": comparison_model_side,
            "maxTurns": int(max_turns),
            "maxActions": int(max_actions),
        },
        "humanDecks": [
            {"id": deck.id, "name": deck.name, "cards": sum(deck.recipe.values()), "forces": list(deck.forces)}
            for deck in selected_human_decks
        ],
        "searchReports": search_reports,
        "topCandidates": top_candidates,
        "comparisonGate": comparison_gate,
        "winner": {
            "id": winner["id"],
            "name": winner["name"],
            "sourceCandidateId": winner["sourceCandidateId"],
            "recipe": winner["recipe"],
            "cards": winner["cards"],
            "forces": winner["forces"],
            "colors": winner["colors"],
            "distribution": winner["distribution"],
            "heuristic": winner["heuristic"],
            "rlEvaluation": winner["rlEvaluation"],
            "comparison": winner["comparison"],
            "finalScore": winner["finalScore"],
        },
    }
    if json_out is not None:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _suite_candidate_record(candidate: dict[str, Any], *, sub_report: dict[str, Any], source_index: int) -> dict[str, Any]:
    colors = list(sub_report.get("config", {}).get("colors") or candidate.get("forceSearchColors") or [])
    force_pair = list(candidate.get("forcePair") or candidate.get("forces") or [])
    return {
        "id": str(candidate.get("id") or f"suite-candidate-{source_index}"),
        "name": str(candidate.get("name") or candidate.get("id") or "Suite Candidate"),
        "recipe": dict(candidate.get("recipe") or {}),
        "cards": int(candidate.get("cards") or sum((candidate.get("recipe") or {}).values())),
        "forces": list(candidate.get("forces") or force_pair),
        "forcePair": force_pair,
        "colors": [str(color) for color in colors],
        "distribution": dict(candidate.get("distribution") or {}),
        "heuristic": dict(candidate.get("heuristic") or {}),
        "rlEvaluation": dict(candidate.get("rlEvaluation") or {}),
        "finalScore": float(candidate.get("finalScore", 0.0)),
        "sourceSearchIndex": source_index + 1,
    }


def _suite_candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float]:
    evaluation = candidate.get("rlEvaluation") or {}
    return (
        float(evaluation.get("validationWinRate", 0.0)),
        float(evaluation.get("validationMinRow", 0.0)),
        float(candidate.get("finalScore", 0.0)),
    )


def _force_preference_from_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats: dict[tuple[str, ...], dict[str, Any]] = {}
    for candidate in candidates:
        force_pair = tuple(str(force_id) for force_id in candidate.get("forcePair") or candidate.get("forces") or [])
        if not force_pair:
            continue
        evaluation = candidate.get("rlEvaluation") or {}
        entry = stats.setdefault(force_pair, {"count": 0, "winRateSum": 0.0, "minRowSum": 0.0, "bestWinRate": 0.0})
        win_rate = float(evaluation.get("validationWinRate", 0.0))
        min_row = float(evaluation.get("validationMinRow", 0.0))
        entry["count"] += 1
        entry["winRateSum"] += win_rate
        entry["minRowSum"] += min_row
        entry["bestWinRate"] = max(float(entry["bestWinRate"]), win_rate)
    rows = [
        {
            "forcePair": list(force_pair),
            "count": int(entry["count"]),
            "averageWinRate": float(entry["winRateSum"]) / max(1, int(entry["count"])),
            "averageMinRow": float(entry["minRowSum"]) / max(1, int(entry["count"])),
            "bestWinRate": float(entry["bestWinRate"]),
        }
        for force_pair, entry in stats.items()
    ]
    rows.sort(key=lambda row: (row["averageWinRate"], row["averageMinRow"], row["count"]), reverse=True)
    return rows


def _rl_matrix_stats_by_deck(matrix_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stats_by_id: dict[str, dict[str, Any]] = {}
    for row in matrix_report["rows"]:
        stats = stats_by_id.setdefault(row["learnerDeckId"], {"wins": 0, "games": 0, "mins": [], "means": []})
        stats["wins"] += row["results"][row["learnerSide"]]
        stats["games"] += row["results"]["P1"] + row["results"]["P2"] + row["results"]["tie"]
        stats["mins"].append(row["minWinRate"])
        stats["means"].append(row["meanWinRate"])
    return stats_by_id


def _rank_rl_candidate_rows(
    candidates: list[DeckSpec],
    constraints: DeckBuildConstraints,
    matrix_report: dict[str, Any],
) -> list[dict[str, Any]]:
    matrix_stats = _rl_matrix_stats_by_deck(matrix_report)
    rows = []
    for deck in candidates:
        stats = matrix_stats[deck.id]
        rows.append({
            "id": deck.id,
            "name": deck.name,
            "recipe": deck.recipe,
            "cards": sum(deck.recipe.values()),
            "forces": list(deck.forces),
            "distribution": recipe_distribution(deck.recipe),
            "heuristic": deck_score(deck.recipe, constraints),
            "rlEvaluation": {
                "stage1WinRate": stats["wins"] / max(1, stats["games"]),
                "stage1MinRow": min(stats["mins"]),
                "stage1Games": stats["games"],
            },
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and evaluate automatic Zenonzard deck candidates.")
    parser.add_argument("--colors", nargs="+", required=True)
    parser.add_argument("--forces", nargs=2)
    parser.add_argument("--auto-forces", action="store_true")
    parser.add_argument("--top-suite", action="store_true")
    parser.add_argument("--suite-color-set", nargs="+", action="append")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--passing-win-rate", type=float, default=0.70)
    parser.add_argument("--max-force-pairs", type=int)
    parser.add_argument("--population", type=int, default=32)
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--bench-games", type=int, default=4)
    parser.add_argument("--playoff-games", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260523)
    parser.add_argument("--deck-root", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--save-deck-name")
    parser.add_argument("--rl-model-path", type=Path)
    parser.add_argument("--rl-validation-top", type=int, default=8)
    parser.add_argument("--rl-stage1-games", type=int, default=1)
    parser.add_argument("--rl-validation-games", type=int, default=5)
    args = parser.parse_args(argv)
    if args.top_suite:
        if args.rl_model_path is None:
            parser.error("--top-suite requires --rl-model-path")
        color_sets = args.suite_color_set or [(color,) for color in args.colors]
        report = run_top_deck_search_suite(
            color_sets=color_sets,
            model_path=args.rl_model_path,
            top_n=args.top_n,
            passing_win_rate=args.passing_win_rate,
            max_force_pairs=args.max_force_pairs,
            population=args.population,
            validation_top=args.rl_validation_top,
            stage1_games=args.rl_stage1_games,
            validation_games=args.rl_validation_games,
            seed=args.seed,
            deck_root=args.deck_root,
            json_out=args.json_out,
        )
    elif args.auto_forces:
        if args.rl_model_path is None:
            parser.error("--auto-forces requires --rl-model-path")
        report = run_auto_force_rl_candidate_search(
            colors=args.colors,
            model_path=args.rl_model_path,
            max_force_pairs=args.max_force_pairs,
            population=args.population,
            validation_top=args.rl_validation_top,
            stage1_games=args.rl_stage1_games,
            validation_games=args.rl_validation_games,
            seed=args.seed,
            deck_root=args.deck_root,
            json_out=args.json_out,
            save_deck_name=args.save_deck_name,
        )
    elif args.forces is None:
        parser.error("--forces is required unless --auto-forces is set")
    elif args.rl_model_path is not None:
        report = run_rl_candidate_search(
            colors=args.colors,
            forces=args.forces,
            model_path=args.rl_model_path,
            population=args.population,
            validation_top=args.rl_validation_top,
            stage1_games=args.rl_stage1_games,
            validation_games=args.rl_validation_games,
            seed=args.seed,
            deck_root=args.deck_root,
            json_out=args.json_out,
            save_deck_name=args.save_deck_name,
        )
    else:
        report = run_training(
            colors=args.colors,
            forces=args.forces,
            population=args.population,
            generations=args.generations,
            bench_games=args.bench_games,
            playoff_games=args.playoff_games,
            seed=args.seed,
            deck_root=args.deck_root,
            json_out=args.json_out,
            save_deck_name=args.save_deck_name,
        )
    if args.top_suite:
        print(
            f"Top suite: passing={report['passingCount']} "
            f"top={len(report['top10'])} threshold={report['passingThreshold']:.2f}"
        )
    elif args.rl_model_path is not None:
        winner = report["winner"]
        print(
            f"Winner {winner['id']}: score={winner['finalScore']:.3f} "
            f"rlWinRate={winner['rlEvaluation']['validationWinRate']:.3f}"
        )
    else:
        winner = report["winner"]
        print(
            f"Winner {winner['id']}: score={winner['finalScore']:.3f} "
            f"benchmark={winner['benchmark']['wins']}-{winner['benchmark']['losses']}-"
            f"{winner['benchmark']['ties']}"
        )
    if args.json_out is not None:
        print(f"Wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
