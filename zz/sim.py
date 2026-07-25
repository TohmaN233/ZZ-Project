from __future__ import annotations
import argparse, random

from zz.ai import RandomLegalPolicy
from zz.decks import (
    AGUMA_FORCES,
    AGUMA_RED_RECIPE,
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
    build_deck,
)
from zz.engine import Engine, GameOver, MAX_TURNS_SAFETY
from zz.enums import Side
from zz.forces import ALL_FORCES
from zz.model import ForceInstance, GameState, Player


def play_one_game(
    seed: int,
    *,
    p1_recipe: dict[str, int] | None = None,
    p2_recipe: dict[str, int] | None = None,
    p1_forces: list[str] | None = None,
    p2_forces: list[str] | None = None,
    p1_policy=None,
    p2_policy=None,
) -> tuple[str, int]:
    rng = random.Random(seed)
    p1 = Player(name="P1", side=Side.P1, is_first_player=True)
    p2 = Player(name="P2", side=Side.P2, is_first_player=False)
    s = GameState(players=[p1, p2])
    eng = Engine(s, rng=rng)
    s.engine = eng
    eng.set_policies(
        p1_policy or RandomLegalPolicy(random.Random(seed + 1)),
        p2_policy or RandomLegalPolicy(random.Random(seed + 2)),
    )
    p1_recipe = p1_recipe or KANATANA_YELLOW_RECIPE
    p2_recipe = p2_recipe or DEMETE_GREEN_RECIPE
    p1_forces = p1_forces or DECKCODE0_YELLOW_FORCES
    p2_forces = p2_forces or DECKCODE0_GREEN_FORCES
    p1.deck = build_deck(p1_recipe, owner=p1, iid_factory=s.allocate_iid)
    p2.deck = build_deck(p2_recipe, owner=p2, iid_factory=s.allocate_iid)
    rng.shuffle(p1.deck); rng.shuffle(p2.deck)
    for p in (p1, p2):
        eng.deal_opening_hand(p)
        force_ids = p1_forces if p is p1 else p2_forces
        eng.install_forces(p, [
            ForceInstance(force=ALL_FORCES[fid], owner=p,
                          life=ALL_FORCES[fid].initial_life)
            for fid in force_ids
        ])
    for p in (p1, p2):
        redraw = eng.policy_for(p).choose_mulligan(eng, p)
        eng.mulligan(p, redraw=redraw)
    try:
        eng.begin_turn()
        while True:
            action = eng.policy_for(eng.state.active).choose(eng)
            eng.apply(action)
    except GameOver as g:
        return ((g.winner.name if g.winner else "tie"), eng.state.turn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100)
    args = ap.parse_args()
    results = {"P1": 0, "P2": 0, "tie": 0}
    turns_total = 0
    for seed in range(args.games):
        winner, turns = play_one_game(seed)
        results[winner] = results.get(winner, 0) + 1
        turns_total += turns
    print(f"Played {args.games} games. Avg turns: {turns_total / args.games:.1f}")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
