from __future__ import annotations

import random

from zz.ai import PassOnlyPolicy
from zz.engine import BASE_CAP, Engine
from zz.enums import AreaType, CardType, Color, Side, Step
from zz.model import Card, CardInstance, GameState, Player
from zz.web.serialize import serialize_card
from zz.web.session import GameSession


class _QueuedTargetPolicy(PassOnlyPolicy):
    def __init__(self, targets: list[object] | None = None):
        self.asked: list[tuple[str, str]] = []
        self.targets = list(targets or [])

    def choose_target(self, engine, kind, min_n, max_n, eligible):
        owner_side = eligible[0].owner.side.name if eligible else ""
        self.asked.append((kind, owner_side))
        selected = [target for target in self.targets if target in eligible][:max_n]
        self.targets = [target for target in self.targets if target not in selected]
        if len(selected) >= min_n:
            return selected
        return eligible[:max_n]


def _token(owner: Player, iid: int, *, rested: bool = False, color: Color | None = None) -> CardInstance:
    token = CardInstance(
        card=Card(id="mana_token", name_jp="無色マナ", name_en="Mana", type=CardType.MANA_TOKEN),
        owner=owner,
        iid=iid,
        area=AreaType.BASE,
        rested=rested,
    )
    if color is not None:
        token.mana_color_override = color
    return token


def _minion(owner: Player, iid: int, *, area: AreaType = AreaType.FIELD) -> CardInstance:
    return CardInstance(
        card=Card(id="blue_bounce", name_jp="青", name_en="Blue", type=CardType.F_MINION, cost={Color.BLUE: 3}),
        owner=owner,
        iid=iid,
        area=area,
    )


def test_effect_target_meta_reuses_serialize_card_mana_urls() -> None:
    session = GameSession(seed=3, mode="god")
    owner = session.engine.state.players[0]
    ready = _token(owner, session.engine.state.allocate_iid(), rested=False)
    tired = _token(owner, session.engine.state.allocate_iid(), rested=True, color=Color.BLUE)
    owner.base = [ready, tired]

    ready_meta = session._effect_target_meta(ready)
    tired_meta = session._effect_target_meta(tired)
    ready_card = serialize_card(session.engine, ready, session.asset_index)
    tired_card = serialize_card(session.engine, tired, session.asset_index)

    assert ready_meta["assetUrl"] == ready_card["assetUrl"]
    assert ready_meta["assetUrlEn"] == ready_card["assetUrlEn"]
    assert ready_meta["manaColor"] == ready_card["manaColor"] == "COLORLESS"
    assert ready_meta["rested"] is False
    assert ready_meta["area"] == "base"
    assert tired_meta["assetUrl"] == tired_card["assetUrl"]
    assert tired_meta["assetUrlEn"] == tired_card["assetUrlEn"]
    assert tired_meta["rested"] is True
    assert tired_meta["manaColor"] == tired_card["manaColor"] == "BLUE"
    if ready_card["assetUrl"]:
        assert ready_card["assetUrl"] == "/assets/mana%3ACOLORLESS"
    if tired_card["assetUrl"]:
        assert tired_card["assetUrl"] == "/assets/mana%3ABLUE"


def test_move_to_base_asks_card_owner_for_full_base_replacement() -> None:
    p1 = Player(name="P1", side=Side.P1, is_first_player=True, life=10)
    p2 = Player(name="P2", side=Side.P2, life=10)
    state = GameState(players=[p1, p2], step=Step.MAIN, turn=2)
    engine = Engine(state, random.Random(11))
    victim = _minion(p2, 21)
    replacement = _token(p2, 1)
    p2.field = [victim]
    p2.base = [replacement] + [_token(p2, index + 2) for index in range(BASE_CAP - 1)]
    p1_policy = _QueuedTargetPolicy()
    p2_policy = _QueuedTargetPolicy([replacement])
    engine.set_policies(p1_policy, p2_policy)

    assert engine.move_target_to_base_asking_owner(victim, rested=True, source=_minion(p1, 99)) is True
    assert p1_policy.asked == []
    assert p2_policy.asked == [("ally_base", "P2")]
    assert victim in p2.base
    assert replacement not in p2.base
    assert victim.rested is True
