import random

from zz.decks import AGUMA_RED_RECIPE, build_deck
from zz.engine import Engine
from zz.enums import CardType, Side, Step
from zz.model import Card, GameState, Player


def _headless_setup(seed: int) -> tuple[GameState, Engine]:
    rng = random.Random(seed)
    p1 = Player(name="P1", side=Side.P1, is_first_player=True)
    p2 = Player(name="P2", side=Side.P2, is_first_player=False)
    state = GameState(players=[p1, p2])
    engine = Engine(state, rng=rng)
    p1.deck = build_deck(AGUMA_RED_RECIPE, owner=p1, iid_factory=state.allocate_iid)
    p2.deck = build_deck(AGUMA_RED_RECIPE, owner=p2, iid_factory=state.allocate_iid)
    rng.shuffle(p1.deck)
    rng.shuffle(p2.deck)
    return state, engine


def _deck_snapshot(state: GameState) -> tuple[tuple[str, int], ...]:
    return tuple(
        (card.card.id, card.iid)
        for player in state.players
        for card in player.deck
    )


def test_same_seed_and_spec_get_same_iids_in_one_process() -> None:
    legacy_owner = Player(name="Legacy", side=Side.P1)
    assert len(build_deck(AGUMA_RED_RECIPE, owner=legacy_owner)) == 40

    first, _ = _headless_setup(1234)
    second, _ = _headless_setup(1234)

    assert _deck_snapshot(first) == _deck_snapshot(second)
    assert {
        card.iid
        for player in first.players
        for card in player.deck
    } == set(range(1, 81))


def test_allocator_position_is_cloned() -> None:
    state, _ = _headless_setup(7)
    clone = state.clone()

    assert state.allocate_iid() == 81
    assert clone.allocate_iid() == 81
    assert state.allocate_iid() == 82
    assert clone.allocate_iid() == 82


def test_engine_created_token_iids_do_not_collide() -> None:
    state, engine = _headless_setup(99)
    player = state.players[0]
    deck_iids = {
        card.iid
        for match_player in state.players
        for card in match_player.deck
    }

    field_token = engine.create_token(
        player,
        Card(
            id="test_token",
            name_jp="Test Token",
            name_en="Test Token",
            type=CardType.B_MINION,
        ),
    )
    generated_mana = engine.place_generated_colorless_mana(player)
    state.step = Step.MANA
    engine.place_colorless_mana()
    placed_mana = player.base[-1]

    runtime_iids = {field_token.iid, generated_mana.iid, placed_mana.iid}
    assert runtime_iids == {81, 82, 83}
    assert runtime_iids.isdisjoint(deck_iids)
