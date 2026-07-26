from __future__ import annotations

import random

from zz.engine import Engine
from zz.enums import AreaType, CardType, Side
from zz.forces import F_CYCLOPS
from zz.model import Card, CardInstance, ForceInstance, GameState, Player


def _card(card_id: str, card_type: CardType, owner: Player) -> CardInstance:
    return CardInstance(
        card=Card(
            id=card_id,
            name_jp=card_id,
            name_en=card_id,
            type=card_type,
            bp=300,
            dp=1,
        ),
        owner=owner,
        area=AreaType.FIELD,
    )


def test_cyclops_grants_exactly_100_bp_to_all_friendly_minions() -> None:
    owner = Player(name="Owner", side=Side.P1)
    opponent = Player(name="Opponent", side=Side.P2)
    engine = Engine(GameState(players=[owner, opponent]), rng=random.Random(0))
    force = ForceInstance(force=F_CYCLOPS, owner=owner, life=F_CYCLOPS.initial_life)
    engine.install_forces(owner, [force])

    field_minion = _card("friendly-field", CardType.F_MINION, owner)
    base_minion = _card("friendly-base", CardType.B_MINION, owner)
    enemy_minion = _card("enemy-field", CardType.F_MINION, opponent)
    magic = _card("friendly-magic", CardType.MAGIC, owner)

    assert engine.effective_bp(field_minion) == 400
    assert engine.effective_bp(base_minion) == 400
    assert engine.effective_bp(enemy_minion) == 300
    assert engine.effective_bp(magic) == 300

    force.destroyed = True
    assert engine.effective_bp(field_minion) == 300
