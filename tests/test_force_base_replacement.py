import random

import pytest

from zz.engine import BASE_CAP, Engine, IllegalActionError
from zz.enums import AreaType, CardType, Side
from zz.forces import F_OUROBOROS
from zz.model import Card, CardInstance, ForceInstance, GameState, Player
from zz.multiplayer.views import build_player_view
from zz.web.session import GameSession


def _token(owner: Player, iid: int) -> CardInstance:
    return CardInstance(
        card=Card(id="mana_token", name_jp="無色マナ", name_en="Mana", type=CardType.MANA_TOKEN),
        owner=owner,
        iid=iid,
        area=AreaType.BASE,
    )


def _bminion(owner: Player, iid: int, card_id: str = "force_bminion") -> CardInstance:
    return CardInstance(
        card=Card(id=card_id, name_jp="ベース", name_en="Base", type=CardType.B_MINION),
        owner=owner,
        iid=iid,
        area=AreaType.DECK,
    )


def test_force_base_choice_uses_shared_base_space_and_does_not_auto_eject() -> None:
    owner = Player(name="P1", side=Side.P1, is_first_player=True)
    opponent = Player(name="P2", side=Side.P2)
    state = GameState(players=[owner, opponent])
    engine = Engine(state, rng=random.Random(1))
    owner.base = [_token(owner, index + 1) for index in range(BASE_CAP)]
    chosen = _bminion(owner, 21)
    owner.deck = [chosen]
    victim = owner.base[4]
    force = ForceInstance(force=F_OUROBOROS, owner=owner, life=F_OUROBOROS.initial_life)

    with pytest.raises(IllegalActionError, match="choose a replacement"):
        engine.resolve_force_base_choice(force, chosen.iid)

    engine.resolve_force_base_choice(force, chosen.iid, victim.iid)

    assert chosen in owner.base
    assert victim not in owner.base
    assert len(owner.base) == BASE_CAP
    assert chosen.area is AreaType.BASE


def test_user_force_destroy_on_full_base_prompts_ally_base_replacement() -> None:
    session = GameSession(seed=11, mode="god")
    owner = session.engine.state.players[0]
    owner.base = [_token(owner, session.engine.state.allocate_iid()) for _ in range(BASE_CAP)]
    chosen = _bminion(owner, session.engine.state.allocate_iid())
    owner.deck = [chosen]
    force = ForceInstance(force=F_OUROBOROS, owner=owner, life=F_OUROBOROS.initial_life)
    owner.forces = [force]

    session._clear_prompt()
    session.engine.handle_force_destroy_base_search(force)
    assert session._drain_or_prompt_force_base_choices() is True
    assert session.prompt["kind"] == "force_base_choice"
    assert all("replaceBaseIid" not in option for option in session.prompt["options"])

    first = session.choose(session.prompt["id"], session.prompt["options"][0]["id"])
    assert first["error"] is None
    assert session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "ally_base"

    victim_option = next(
        option for option in session.prompt["options"]
        if option.get("cardIid") == owner.base[2].iid
    )
    victim_iid = victim_option["cardIid"]
    session.choose(session.prompt["id"], victim_option["id"])

    assert chosen in owner.base
    assert all(card.iid != victim_iid for card in owner.base)
    assert len(owner.base) == BASE_CAP


def test_force_search_candidates_are_private_and_selected_by_the_force_owner() -> None:
    session = GameSession(seed=12, mode="god")
    owner = session.engine.state.players[1]
    owner.base = []
    choices = [_bminion(owner, session.engine.state.allocate_iid(), f"base_{i}") for i in range(2)]
    other = CardInstance(Card("field", "field", "field", CardType.F_MINION), owner,
                         iid=session.engine.state.allocate_iid(), area=AreaType.DECK)
    owner.deck = [*choices, other]
    force = ForceInstance(force=F_OUROBOROS, owner=owner, life=F_OUROBOROS.initial_life)
    owner.forces = [force]
    session._clear_prompt()
    session.engine.handle_force_destroy_base_search(force)
    assert session._drain_or_prompt_force_base_choices()
    owner_view = build_player_view(session, player_id="player_2", revision=1, state_hash="test")
    opponent_view = build_player_view(session, player_id="player_1", revision=1, state_hash="test")
    prompt = owner_view["prompt"]
    assert prompt["kind"] == "force_base_choice" and prompt["playerSide"] == "P2"
    assert {option["cardIid"] for option in prompt["options"]} == {card.iid for card in choices}
    assert opponent_view["prompt"] is None
    invalid = session.choose(prompt["id"], "illegal")
    assert invalid["error"]["code"] == "illegal_choice" and not owner.base
    option = next(option for option in prompt["options"] if option["cardIid"] == choices[1].iid)
    result = session.choose(prompt["id"], option["id"])
    assert result["error"] is None
    assert owner.base == [choices[1]] and choices[1].area is AreaType.BASE
