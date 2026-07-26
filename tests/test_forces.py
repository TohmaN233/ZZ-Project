import random

from zz.engine import Engine
from zz.enums import AreaType, CardType, Side
from zz.forces import F_OUROBOROS
from zz.model import Card, CardInstance, ForceInstance, GameState, Player


def test_ouroboros_activates_non_token_minions_only() -> None:
    owner = Player(name="P1", side=Side.P1, is_first_player=True)
    opponent = Player(name="P2", side=Side.P2)
    state = GameState(players=[owner, opponent])
    engine = Engine(state, rng=random.Random(1))

    normal = CardInstance(
        card=Card(
            id="normal_minion",
            name_jp="通常ミニオン",
            name_en="Normal Minion",
            type=CardType.F_MINION,
        ),
        owner=owner,
        area=AreaType.FIELD,
        rested=True,
    )
    token = CardInstance(
        card=Card(
            id="token_minion",
            name_jp="トークン",
            name_en="Token",
            type=CardType.F_MINION,
            is_token=True,
        ),
        owner=owner,
        area=AreaType.FIELD,
        rested=True,
    )
    owner.field = [normal, token]
    engine.install_forces(owner, [
        ForceInstance(
            force=F_OUROBOROS,
            owner=owner,
            life=F_OUROBOROS.initial_life,
        )
    ])

    engine._fire_turn_end_hooks()

    assert normal.rested is False
    assert token.rested is True
