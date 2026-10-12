from __future__ import annotations

import random

import pytest

from zz.engine import Engine
from zz.enums import AreaType, CardType, Keyword, Side
from zz.model import Card, CardInstance, Context, GameState, Player
from zz.pc02r_cards.blue_02_02_02r_00 import _grant_sneaking
from zz.pc02r_cards.red_08_02_02r_00 import _reduce_all_opponent_minions
from zz.pc02r_cards.white_07_02_02r_01 import _grant_charge


def _card(owner: Player, card_id: str, *, bp: int = 500) -> CardInstance:
    return CardInstance(
        card=Card(card_id, card_id, card_id, CardType.F_MINION, bp=bp),
        owner=owner,
        area=AreaType.FIELD,
    )


@pytest.fixture
def game() -> tuple[Engine, Player, Player]:
    owner = Player(name="P1", side=Side.P1, is_first_player=True)
    opponent = Player(name="P2", side=Side.P2)
    state = GameState(players=[owner, opponent])
    return Engine(state, random.Random(1)), owner, opponent


def test_pc02r_keyword_grants_survive_turn_end_and_clear_on_zone_exit(game) -> None:
    engine, owner, opponent = game
    sneaking_target = _card(owner, "blue_02_02_02r_00")
    charge_source = _card(owner, "white_07_02_02r_01")
    owner.field.extend([sneaking_target, charge_source])
    opponent.deck.append(_card(opponent, "draw-card"))

    _grant_sneaking(sneaking_target, engine.state, Context(controller=owner, source=sneaking_target))
    _grant_charge(charge_source, engine.state, Context(controller=owner, source=charge_source))

    assert Keyword.SNEAKING in sneaking_target.keywords
    assert Keyword.REAWAKEN in charge_source.keywords
    assert charge_source.bp == 600

    engine.end_turn()

    assert Keyword.SNEAKING in sneaking_target.keywords
    assert Keyword.REAWAKEN in charge_source.keywords
    assert charge_source.bp == 600

    engine.return_to_hand(sneaking_target)
    engine.return_to_hand(charge_source)

    assert Keyword.SNEAKING not in sneaking_target.keywords
    assert Keyword.REAWAKEN not in charge_source.keywords
    assert charge_source.bp == 500

    owner.hand.remove(sneaking_target)
    sneaking_target.area = AreaType.FIELD
    owner.field.append(sneaking_target)
    engine.add_keyword(sneaking_target, Keyword.SNEAKING)
    engine.move_target_to_base(sneaking_target)

    assert Keyword.SNEAKING not in sneaking_target.keywords


def test_pc02r_attack_bp_reduction_survives_turn_end_and_clears_on_zone_exit(game) -> None:
    engine, owner, opponent = game
    source = _card(owner, "red_08_02_02r_00", bp=800)
    target = _card(opponent, "opponent", bp=500)
    owner.field.append(source)
    opponent.field.append(target)
    opponent.deck.append(_card(opponent, "draw-card"))

    _reduce_all_opponent_minions(source, engine.state, Context(controller=owner, source=source))

    assert target.bp == 400
    engine.end_turn()
    assert target.bp == 400

    engine.return_to_hand(target)
    assert target.bp == 500


def test_add_keyword_rejects_unknown_duration(game) -> None:
    engine, owner, _opponent = game
    target = _card(owner, "target")

    with pytest.raises(ValueError, match="unsupported keyword duration"):
        engine.add_keyword(target, Keyword.SNEAKING, duration="forever")


def test_turn_keyword_is_the_explicit_exception_to_zone_persistent_grants(game) -> None:
    engine, owner, opponent = game
    target = _card(owner, "target")
    owner.field.append(target)
    opponent.deck.append(_card(opponent, "draw-card"))

    engine.add_keyword(target, Keyword.SNEAKING, duration="turn")
    assert Keyword.SNEAKING in target.keywords

    engine.end_turn()

    assert Keyword.SNEAKING not in target.keywords
