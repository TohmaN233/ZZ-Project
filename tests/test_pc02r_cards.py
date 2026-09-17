import random
import subprocess
import sys
from pathlib import Path

import pytest

from zz.ai import PassOnlyPolicy, RandomLegalPolicy
from zz.cards import CARD_REGISTRY
from zz.decks import validate_user_deck_recipe
from zz.engine import BASE_CAP, Engine
from zz.effects import EffectTiming
from zz.enums import AreaType, CardType, Color, Keyword, Side, Step
from zz.model import CardInstance, Context, GameState, Player
from zz.pc02 import PC02_CARD_IDS, _remove_target, bless_condition_matches
from zz.pc02r import (
    ANJU_FORMS,
    LEGEND_FORMS,
    PC02R_CARD_IDS,
    WAITRESS_EXTRA_GAME_ID,
    _ENGINE_RULE_IDS,
    _confusion,
    _assembly,
    _dual_eagle_summon,
    _metal_wall,
    _wizardry,
    adjust_effective_cost,
    blocks_effect_destroy,
    can_effect_select,
)
from zz.sim import play_one_game
from zz.web.assets import CARD_IMAGE_NAMES
from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_lab
from zz.web.session import GameSession
from zz.multiplayer.views import build_player_view


ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_RUNNER = ROOT.parent / ".agents" / "skills" / "write-zenonzard-cards" / "scripts" / "run_semantic_scenario.py"
REPRINT_ART = {
    "colorless_03_02_02r_03": "colorless_03_02_01r_02.png",
    "colorless_04_02_02r_03": "colorless_04_02_01_03.png",
    "colorless_09_02_02r_00": "colorless_09_02_ex01_00.png",
    "colorless_010_02_02r_00": "colorless_010_02_01_00.png",
}
CHARGE_RUSH_IDS = (
    "colorless_010_02_02r_00",
    "blue_07_02_02r_01",
    "green_07_02_02r_01",
    "purple_07_02_02r_01",
    "red_07_02_02r_01",
    "white_07_02_02r_01",
    "yellow_07_02_02r_01",
)


class _QueuedTargetPolicy(PassOnlyPolicy):
    def __init__(self, targets: list[object] | None = None):
        self.targets = list(targets or [])

    def choose_target(self, engine, kind, min_n, max_n, eligible):
        selected = [target for target in self.targets if target in eligible][:max_n]
        self.targets = [target for target in self.targets if target not in selected]
        if len(selected) >= min_n:
            return selected
        return eligible[:max_n]


def _engine(*, policy=None) -> tuple[Engine, Player, Player]:
    p1 = Player(name="P1", side=Side.P1, is_first_player=True, life=10)
    p2 = Player(name="P2", side=Side.P2, life=10)
    state = GameState(players=[p1, p2], turn=2)
    state.step = Step.MAIN
    engine = Engine(state, random.Random(202))
    engine.set_policies(policy or PassOnlyPolicy(), PassOnlyPolicy())
    return engine, p1, p2


def _instance(card_id: str, owner: Player, area: AreaType) -> CardInstance:
    return CardInstance(CARD_REGISTRY[card_id], owner, area=area)


def _emit(engine: Engine, timing: EffectTiming, source: CardInstance, *, target=None) -> None:
    engine.triggers.emit(timing, Context(controller=source.owner, source=source, target=target))
    engine.triggers.resolve_all()


def test_pc02r_inventory_and_japanese_faces_are_complete() -> None:
    assert len(PC02R_CARD_IDS) == 106
    assert len(set(PC02R_CARD_IDS)) == 106
    colors = {"red": 0, "yellow": 0, "white": 0, "green": 0, "blue": 0, "purple": 0, "colorless": 0}
    for card_id in PC02R_CARD_IDS:
        assert "_02r_" in card_id
        assert card_id not in PC02_CARD_IDS
        card = CARD_REGISTRY[card_id]
        assert card.name_jp
        assert card.ability_jp or card.ability_en or card.effects or card.keywords or card.aura or card.keyword_aura or card_id in REPRINT_ART
        if card.type is not CardType.MAGIC:
            assert card.bp >= 0
            assert card.dp >= 0
        colors[card_id.split("_", 1)[0]] += 1
    assert colors == {"red": 14, "yellow": 14, "white": 14, "green": 14, "blue": 14, "purple": 14, "colorless": 22}


def test_pc02r_every_rules_card_has_an_executable_channel() -> None:
    for card_id in PC02R_CARD_IDS:
        card = CARD_REGISTRY[card_id]
        channels = bool(card.effects or card.keywords or card.aura or card.keyword_aura)
        assert channels or card_id in _ENGINE_RULE_IDS, card_id


def test_pc02r_charge_is_rush_not_a_new_keyword() -> None:
    for card_id in CHARGE_RUSH_IDS:
        assert Keyword.RUSH in CARD_REGISTRY[card_id].keywords
        assert not hasattr(Keyword, "CHARGE")


def test_pc02r_local_faces_cover_all_106() -> None:
    for card_id in PC02R_CARD_IDS:
        color = card_id.split("_", 1)[0].upper()
        if card_id in REPRINT_ART:
            mapped = REPRINT_ART[card_id]
            assert CARD_IMAGE_NAMES[card_id] == [mapped]
            jp = ROOT / "asserts" / "ZENONZARD_CARDLIST" / color / mapped
            assert jp.is_file(), jp
            continue
        en = ROOT / "asserts" / "Eng-cards" / color / f"{card_id}.png"
        jp = ROOT / "asserts" / "ZENONZARD_CARDLIST" / color / f"{card_id}.png"
        assert en.is_file() or jp.is_file(), card_id


def test_pc02r_complete_real_game_smoke() -> None:
    recipe = {card_id: 1 for card_id in PC02R_CARD_IDS[:40]}
    validate_user_deck_recipe(recipe)
    winner, turns = play_one_game(
        902,
        p1_recipe=recipe,
        p2_recipe=recipe,
        p1_forces=["force_kon", "force_so2"],
        p2_forces=["force_kon", "force_rin"],
    )
    assert winner in {"P1", "P2", "tie"}
    assert turns > 0


def _run_semantic_scenario(card_id: str, kind: str, tmp_path: Path) -> None:
    spec = ROOT / "project_memory" / "card_scenarios" / "pc02r" / f"{card_id}-{kind}.json"
    evidence = tmp_path / f"{card_id}-{kind}.evidence.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SEMANTIC_RUNNER),
            str(spec),
            "--project-root",
            str(ROOT),
            "--evidence",
            str(evidence),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("card_id", PC02R_CARD_IDS, ids=PC02R_CARD_IDS)
def test_pc02r_positive_semantic_scenario(card_id: str, tmp_path: Path) -> None:
    _run_semantic_scenario(card_id, "positive", tmp_path)


@pytest.mark.parametrize("card_id", PC02R_CARD_IDS, ids=PC02R_CARD_IDS)
def test_pc02r_boundary_semantic_scenario(card_id: str, tmp_path: Path) -> None:
    _run_semantic_scenario(card_id, "boundary", tmp_path)


def test_pc02r_flair_attack_applies_minus_200_not_100() -> None:
    engine, owner, opponent = _engine()
    flair = _instance("red_08_02_02r_00", owner, AreaType.FIELD)
    first = _instance("red_05_02_02r_00", opponent, AreaType.FIELD)
    second = _instance("yellow_06_02_02r_00", opponent, AreaType.FIELD)
    owner.field = [flair]
    opponent.field = [first, second]
    engine._resolve_source_effects(flair, EffectTiming.ON_ATTACK, Context(controller=owner, source=flair))
    assert first.permanent_bp_mod == -200
    assert second.permanent_bp_mod == -200
    assert engine.effective_bp(first) == first.card.bp - 200
    assert engine.effective_bp(second) == second.card.bp - 200


def test_pc02r_flair_returns_to_hand_only_on_own_turn() -> None:
    engine, owner, opponent = _engine()
    flair = _instance("red_08_02_02r_00", owner, AreaType.FIELD)
    owner.field = [flair]
    engine.destroy_target(flair, flair)
    assert flair in owner.hand
    assert flair not in owner.trash

    engine.state.active_idx = 1
    other = _instance("red_08_02_02r_00", owner, AreaType.FIELD)
    owner.field = [other]
    engine.destroy_target(other, other)
    assert other in owner.trash
    assert other not in owner.hand


def test_pc02r_waitress_adds_violent_stream_not_tidal_wave() -> None:
    engine, owner, _ = _engine()
    waitress = _instance("blue_03_02_02r_00", owner, AreaType.HAND)
    owner.hand = [waitress]
    owner.base = [
        _instance("blue_00_01_02_00", owner, AreaType.BASE),
        _instance("colorless_00_01_02_01", owner, AreaType.BASE),
        _instance("colorless_00_01_02_01", owner, AreaType.BASE),
    ]
    engine.play_card(waitress)
    assert any(card.card.id == WAITRESS_EXTRA_GAME_ID for card in owner.hand)
    assert all(card.card.id != "blue_03_03_00_01" for card in owner.hand)
    assert WAITRESS_EXTRA_GAME_ID == "blue_02_03_01_01"


def test_pc02r_legend_rest_cannot_bless() -> None:
    engine, owner, _ = _engine()
    orka = _instance("blue_07_02_02r_00", owner, AreaType.FIELD)
    mana = _instance("blue_00_01_02r_00", owner, AreaType.BASE)
    orka.rested = True
    owner.field = [orka]
    owner.base = [mana]
    owner.movement_right_count = 1
    assert bless_condition_matches(mana, orka) is False
    assert engine.can_bless(mana, orka) is False


def test_pc02r_anju_same_color_stays_and_off_color_morphs() -> None:
    engine, owner, _ = _engine()
    oceans = _instance("blue_04_02_02r_02", owner, AreaType.FIELD)
    blue = _instance("blue_00_01_02r_00", owner, AreaType.BASE)
    owner.field = [oceans]
    owner.base = [blue]
    owner.movement_right_count = 1
    iid = oceans.iid
    engine.bless(blue, oceans)
    assert oceans.iid == iid
    assert oceans.card.id == "blue_04_02_02r_02"

    engine2, owner2, _ = _engine()
    oceans2 = _instance("blue_04_02_02r_02", owner2, AreaType.FIELD)
    red = _instance("red_00_01_02r_00", owner2, AreaType.BASE)
    owner2.field = [oceans2]
    owner2.base = [red]
    owner2.movement_right_count = 1
    iid2 = oceans2.iid
    engine2.bless(red, oceans2)
    assert oceans2.iid == iid2
    assert oceans2.card.id == ANJU_FORMS[Color.RED]
    assert not any(
        event[0] is oceans2 and getattr(event[1], "timing", None) is EffectTiming.ON_SUMMON
        for event in engine2.effect_events
    )


def test_pc02r_aspiration_returns_mana_then_morphs() -> None:
    engine, owner, _ = _engine()
    aspiration = _instance("colorless_04_02_02r_01", owner, AreaType.FIELD)
    blue = _instance("blue_00_01_02r_00", owner, AreaType.BASE)
    owner.field = [aspiration]
    owner.base = [blue]
    owner.movement_right_count = 1
    iid = aspiration.iid
    engine.bless(blue, aspiration)
    assert aspiration.iid == iid
    assert aspiration.card.id == ANJU_FORMS[Color.BLUE]
    assert blue in owner.base
    assert blue.rested is True
    assert blue not in owner.removed


def test_pc02r_legend_morph_keeps_iid_and_does_not_summon() -> None:
    engine, owner, _ = _engine()
    pre = _instance("blue_07_02_02r_00", owner, AreaType.FIELD)
    mana = _instance("blue_00_01_02r_00", owner, AreaType.BASE)
    owner.field = [pre]
    owner.base = [mana]
    owner.movement_right_count = 1
    iid = pre.iid
    engine.bless(mana, pre)
    dest, _ = LEGEND_FORMS["blue_07_02_02r_00"]
    assert pre.iid == iid
    assert pre.card.id == dest
    assert Keyword.RUSH in pre.card.keywords
    assert pre.summoning_sickness is False
    assert not any(
        event[0] is pre and getattr(event[1], "timing", None) is EffectTiming.ON_SUMMON
        for event in engine.effect_events
    )
    assert any(
        event[0] is pre and getattr(event[1], "timing", None) is EffectTiming.ON_TRANSFORM
        for event in engine.effect_events
    )


def test_pc02r_assault_dive_summons_yellow_cost_four_from_deck() -> None:
    engine, owner, _ = _engine()
    dive = _instance("yellow_05_03_02r_00", owner, AreaType.HAND)
    target = _instance("yellow_04_02_02r_00", owner, AreaType.DECK)
    owner.hand = [dive]
    owner.deck = [target]
    engine.set_policies(_QueuedTargetPolicy([target]), PassOnlyPolicy())
    engine._resolve_source_effects(dive, EffectTiming.ON_CAST_MAGIC, Context(controller=owner, source=dive))
    assert target in owner.field
    assert target not in owner.deck


def test_pc02r_metatron_cost_equals_current_life() -> None:
    engine, owner, _ = _engine()
    metatron = _instance("colorless_00_02_02r_00", owner, AreaType.HAND)
    owner.hand = [metatron]
    owner.life = 7
    cost = adjust_effective_cost(owner, metatron, engine.state, dict(metatron.card.cost))
    assert cost == {Color.COLORLESS: 7}
    owner.life = 0
    cost = adjust_effective_cost(owner, metatron, engine.state, dict(metatron.card.cost))
    assert cost == {}


def test_pc02r_skulptera_and_audra_and_sloth_cost_hooks() -> None:
    engine, owner, opponent = _engine()
    skulptera = _instance("purple_06_02_02r_01", owner, AreaType.HAND)
    audra = _instance("white_06_02_02r_01", owner, AreaType.HAND)
    keeper = _instance("green_02_02_02r_00", owner, AreaType.FIELD)
    colorless = _instance("colorless_04_02_02r_00", owner, AreaType.HAND)
    owner.hand = [skulptera, audra, colorless]
    owner.field = [keeper]
    owner.trash = [_instance("red_02_02_02_00", owner, AreaType.TRASH) for _ in range(2)]
    opponent.field = [_instance("red_02_02_02_00", opponent, AreaType.FIELD) for _ in range(2)]
    skul_cost = adjust_effective_cost(owner, skulptera, engine.state, dict(skulptera.card.cost))
    assert skul_cost.get(Color.COLORLESS, 0) == max(0, skulptera.card.cost.get(Color.COLORLESS, 0) - 2)
    audra_cost = adjust_effective_cost(owner, audra, engine.state, dict(audra.card.cost))
    assert audra_cost.get(Color.COLORLESS, 0) == max(0, audra.card.cost.get(Color.COLORLESS, 0) - 2)
    sloth_cost = adjust_effective_cost(owner, colorless, engine.state, dict(colorless.card.cost))
    assert sloth_cost.get(Color.COLORLESS, 0) == colorless.card.cost.get(Color.COLORLESS, 0) + 1


def test_pc02r_dorothy_returns_from_trash_only_with_purple_dragon() -> None:
    engine, owner, _ = _engine()
    dorothy = _instance("purple_04_02_02r_01", owner, AreaType.TRASH)
    dragon = _instance("purple_05_02_02r_00", owner, AreaType.FIELD)
    owner.trash = [dorothy]
    owner.field = [dragon]
    _emit(engine, EffectTiming.TURN_END, dorothy)
    assert dorothy in owner.field
    assert dorothy not in owner.trash

    engine2, owner2, _ = _engine()
    stuck = _instance("purple_04_02_02r_01", owner2, AreaType.TRASH)
    owner2.trash = [stuck]
    _emit(engine2, EffectTiming.TURN_END, stuck)
    assert stuck in owner2.trash
    assert stuck not in owner2.field


def test_pc02r_fiora_token_and_disaster_opponent_token() -> None:
    engine, owner, opponent = _engine()
    fiora = _instance("colorless_00_01_02r_00", owner, AreaType.BASE)
    owner.base = [fiora]
    _emit(engine, EffectTiming.ON_PLACE_BASE, fiora)
    assert any(card.card.id == "slime_block_token" for card in owner.field)

    disaster = _instance("colorless_02_02_02r_01", owner, AreaType.FIELD)
    owner.field.append(disaster)
    _emit(engine, EffectTiming.ON_SUMMON, disaster)
    assert any(card.card.id == "slime_block_token" for card in opponent.field)


def test_pc02r_illegal_choice_does_not_clear_prompt() -> None:
    session = GameSession(seed=920, mode="debug-card-lab")
    setup_debug_lab(session, "blue_04_02_02r_00", zone="hand", compact_board=True)
    prompt = session.prompt
    assert prompt is not None
    state = session.choose(prompt["id"], "not-a-real-option")
    assert state["error"]["code"] == "illegal_choice"
    assert session.prompt is not None
    assert session.prompt["id"] == prompt["id"]


def test_pc02r_orka_private_look_reveals_only_the_selected_card() -> None:
    session = GameSession(seed=921, mode="debug-card-lab")
    setup_debug_lab(session, "blue_07_02_02r_00", zone="hand", compact_board=True)
    for card_id in ("red_02_03_01r_00", "red_02_02_02_00", "blue_02_02_02_00"):
        add_debug_card_to_zone(session, card_id, side="P1", zone="deck")
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == "blue_07_02_02r_00")
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    payload = {"paymentBaseIids": play["paymentDefaultIids"]} if play.get("paymentDefaultIids") else None
    result = session.choose(session.prompt["id"], play["id"], payload)
    assert result["prompt"] is not None
    assert [card["cardId"] for card in result["prompt"]["revealedCards"]] == [
        "red_02_03_01r_00",
        "red_02_02_02_00",
        "blue_02_02_02_00",
    ]
    controller_view = build_player_view(session, player_id="player_1", revision=1, state_hash="orka")
    opponent_view = build_player_view(session, player_id="player_2", revision=1, state_hash="orka")
    assert [card["cardId"] for card in controller_view["prompt"]["revealedCards"]] == [
        "red_02_03_01r_00",
        "red_02_02_02_00",
        "blue_02_02_02_00",
    ]
    assert opponent_view["prompt"] is None
    wanted = next(card for card in result["prompt"]["revealedCards"] if card.get("cardId") == "red_02_03_01r_00")
    selected = next(
        option
        for option in result["prompt"]["options"]
        if option.get("cardId") == wanted.get("cardId") or option.get("iid") == wanted.get("iid")
    )
    result = session.choose(result["prompt"]["id"], selected["id"])
    assert result["error"] is None
    assert [(reveal["card"]["cardId"], reveal["reason"]) for reveal in result["publicReveals"]] == [
        ("red_02_03_01r_00", "deck_search"),
    ]
    assert any(card.card.id == "red_02_03_01r_00" for card in player.hand)


def test_pc02r_owl_private_look_on_bless_and_empty_field_minion_window() -> None:
    session = GameSession(seed=922, mode="debug-card-lab")
    setup_debug_lab(session, "yellow_02_02_02r_01", zone="field", compact_board=True)
    add_debug_card_to_zone(session, "yellow_00_01_02r_00", side="P1", zone="base")
    add_debug_card_to_zone(session, "yellow_04_02_02r_00", side="P1", zone="deck")
    add_debug_card_to_zone(session, "yellow_01_03_02r_00", side="P1", zone="deck")
    add_debug_card_to_zone(session, "yellow_05_03_02r_00", side="P1", zone="deck")
    owl = next(card for card in session.engine.state.players[0].field if card.card.id == "yellow_02_02_02r_01")
    mana = next(card for card in session.engine.state.players[0].base if card.card.id == "yellow_00_01_02r_00")
    bless = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "bless" and option.get("iid") == mana.iid and option.get("target_iid") == owl.iid
    )
    result = session.choose(session.prompt["id"], bless["id"])
    assert [card["cardId"] for card in result["prompt"]["revealedCards"]] == [
        "yellow_04_02_02r_00",
        "yellow_01_03_02r_00",
        "yellow_05_03_02r_00",
    ]
    opponent_view = build_player_view(session, player_id="player_2", revision=1, state_hash="owl")
    assert opponent_view["prompt"] is None
    selected = next(option for option in result["prompt"]["options"] if option.get("cardId") == "yellow_04_02_02r_00")
    result = session.choose(result["prompt"]["id"], selected["id"])
    assert [(reveal["card"]["cardId"], reveal["reason"]) for reveal in result["publicReveals"]] == [
        ("yellow_04_02_02r_00", "deck_search"),
    ]

    session = GameSession(seed=923, mode="debug-card-lab")
    setup_debug_lab(session, "yellow_02_02_02r_01", zone="field", compact_board=True)
    add_debug_card_to_zone(session, "yellow_00_01_02r_00", side="P1", zone="base")
    for card_id in ("yellow_01_03_02r_00", "yellow_05_03_02r_00", "blue_01_03_02r_00"):
        add_debug_card_to_zone(session, card_id, side="P1", zone="deck")
    owl = next(card for card in session.engine.state.players[0].field if card.card.id == "yellow_02_02_02r_01")
    mana = next(card for card in session.engine.state.players[0].base if card.card.id == "yellow_00_01_02r_00")
    bless = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "bless" and option.get("iid") == mana.iid and option.get("target_iid") == owl.iid
    )
    result = session.choose(session.prompt["id"], bless["id"])
    assert result["error"] is None
    assert result.get("publicReveals") in (None, [])
    assert all(card.card.id != "yellow_01_03_02r_00" for card in session.engine.state.players[0].hand)


def test_pc02r_confusion_mist_spares_friendly_same_cost() -> None:
    engine, owner, opponent = _engine()
    mist = _instance("purple_04_03_02r_00", owner, AreaType.HAND)
    sacrificed = _instance("colorless_02_02_02r_00", owner, AreaType.FIELD)
    friendly = _instance("red_02_02_02_00", owner, AreaType.FIELD)
    enemy = _instance("red_02_02_02_00", opponent, AreaType.FIELD)
    owner.field = [sacrificed, friendly]
    opponent.field = [enemy]
    engine.set_policies(_QueuedTargetPolicy([sacrificed]), PassOnlyPolicy())
    _confusion(mist, engine.state, Context(controller=owner, source=mist))
    assert sacrificed not in owner.field
    assert friendly in owner.field
    assert enemy not in opponent.field


def test_pc02r_metal_wall_untargetable_clears_at_turn_end() -> None:
    engine, owner, opponent = _engine()
    wall = _instance("white_02_03_02r_00", owner, AreaType.HAND)
    ally = _instance("colorless_02_02_02r_00", owner, AreaType.FIELD)
    enemy_effect = _instance("green_06_02_02r_01", opponent, AreaType.FIELD)
    owner.field = [ally]
    opponent.deck = [_instance("red_02_02_02_00", opponent, AreaType.DECK)]
    opponent.field = [enemy_effect]
    engine.set_policies(_QueuedTargetPolicy([ally]), PassOnlyPolicy())
    _metal_wall(wall, engine.state, Context(controller=owner, source=wall))
    assert "turn:pc02r_effect_untargetable" in ally.flags
    assert can_effect_select(enemy_effect, ally, engine.state) is False
    engine.end_turn()
    assert "turn:pc02r_effect_untargetable" not in ally.flags
    assert can_effect_select(enemy_effect, ally, engine.state) is True


def test_pc02r_olivia_blocks_opponent_effect_destroy_and_banish() -> None:
    engine, owner, opponent = _engine()
    olivia = _instance("green_05_02_02r_00", owner, AreaType.FIELD)
    dragon = _instance("green_06_02_02r_01", owner, AreaType.FIELD)
    unprotected = _instance("red_02_02_02_00", owner, AreaType.FIELD)
    enemy_effect = _instance("purple_04_03_02r_00", opponent, AreaType.HAND)
    owner.field = [olivia, dragon, unprotected]
    engine._enter_effect_resolution()
    try:
        engine.destroy_target(olivia, enemy_effect)
        engine.destroy_target(dragon, enemy_effect)
        engine.destroy_target(unprotected, enemy_effect)
        _remove_target(engine, olivia, enemy_effect)
        _remove_target(engine, dragon, enemy_effect)
    finally:
        engine._leave_effect_resolution()
    assert olivia in owner.field
    assert dragon in owner.field
    assert unprotected not in owner.field
    assert olivia not in owner.removed
    assert dragon not in owner.removed
    assert blocks_effect_destroy(olivia, enemy_effect, engine.state) is True
    assert blocks_effect_destroy(unprotected, enemy_effect, engine.state) is False


def test_pc02r_jolie_protects_white_dragons_not_herself() -> None:
    engine, owner, opponent = _engine()
    jolie = _instance("white_05_02_02r_00", owner, AreaType.FIELD)
    white_dragon = _instance("white_04_02_02r_02", owner, AreaType.FIELD)
    green_dragon = _instance("green_06_02_02r_01", owner, AreaType.FIELD)
    non_dragon = _instance("red_02_02_02_00", owner, AreaType.FIELD)
    enemy_effect = _instance("green_06_02_02r_01", opponent, AreaType.FIELD)
    owner.field = [jolie, white_dragon, green_dragon, non_dragon]
    engine.state.active_idx = 0
    assert can_effect_select(enemy_effect, jolie, engine.state) is True
    assert can_effect_select(enemy_effect, white_dragon, engine.state) is False
    assert can_effect_select(enemy_effect, green_dragon, engine.state) is True
    assert can_effect_select(enemy_effect, non_dragon, engine.state) is True


def test_pc02r_wizardry_two_stage_game_session_and_dragon_extra() -> None:
    session = GameSession(seed=930, mode="debug-card-lab")
    setup_debug_lab(session, "blue_04_03_02r_00", zone="hand", compact_board=True)
    add_debug_card_to_zone(session, "colorless_02_02_02r_00", side="P2", zone="field")
    add_debug_card_to_zone(session, "red_02_02_02_00", side="P2", zone="field")
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == "blue_04_03_02r_00")
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    payload = {"paymentBaseIids": play["paymentDefaultIids"]} if play.get("paymentDefaultIids") else None
    result = session.choose(session.prompt["id"], play["id"], payload)
    assert result["prompt"] is not None
    assert result["prompt"]["kind"] == "effect_target"
    first_ids = [option.get("cardId") for option in result["prompt"]["options"] if option.get("cardId")]
    assert first_ids == ["colorless_02_02_02r_00"]
    assert result["prompt"]["requiredTargetCount"] == 1
    first = next(option for option in result["prompt"]["options"] if option.get("cardId") == "colorless_02_02_02r_00")
    result = session.choose(result["prompt"]["id"], first["id"])
    assert result["prompt"] is not None
    assert result["prompt"]["requiredTargetCount"] == 1
    assert result["prompt"]["minimumTargetCount"] == 1
    assert result["prompt"]["allowVariableTargetCount"] is False
    second_ids = [option.get("cardId") for option in result["prompt"]["options"] if option.get("cardId")]
    assert second_ids == ["red_02_02_02_00"]
    second = next(option for option in result["prompt"]["options"] if option.get("cardId") == "red_02_02_02_00")
    result = session.choose(result["prompt"]["id"], second["id"])
    assert result["error"] is None
    opponent = session.engine.state.players[1]
    assert any(card.card.id == "colorless_02_02_02r_00" for card in opponent.trash)
    assert any(card.card.id == "red_02_02_02_00" and card.rested for card in opponent.base)

    session = GameSession(seed=931, mode="debug-card-lab")
    setup_debug_lab(session, "blue_04_03_02r_00", zone="hand", compact_board=True)
    add_debug_card_to_zone(session, "blue_06_02_02r_01", side="P1", zone="field")
    add_debug_card_to_zone(session, "colorless_02_02_02r_00", side="P2", zone="field")
    add_debug_card_to_zone(session, "colorless_01_02_02r_00", side="P2", zone="field")
    add_debug_card_to_zone(session, "red_02_02_02_00", side="P2", zone="field")
    add_debug_card_to_zone(session, "yellow_03_02_02_00", side="P2", zone="field")
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == "blue_04_03_02r_00")
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    payload = {"paymentBaseIids": play["paymentDefaultIids"]} if play.get("paymentDefaultIids") else None
    result = session.choose(session.prompt["id"], play["id"], payload)
    assert result["prompt"]["requiredTargetCount"] == 2
    assert result["prompt"]["allowVariableTargetCount"] is False
    first_ids = [option.get("cardId") for option in result["prompt"]["options"] if option.get("cardId")]
    assert set(first_ids) == {"colorless_02_02_02r_00", "colorless_01_02_02r_00"}
    first_options = [option for option in result["prompt"]["options"] if option.get("cardId") in {"colorless_02_02_02r_00", "colorless_01_02_02r_00"}]
    result = session.choose(
        result["prompt"]["id"],
        first_options[0]["id"],
        {"selectedOptionIds": [option["id"] for option in first_options]},
    )
    assert result["prompt"]["requiredTargetCount"] == 2
    assert result["prompt"]["allowVariableTargetCount"] is False
    followup_ids = [option.get("cardId") for option in result["prompt"]["options"] if option.get("cardId")]
    assert set(followup_ids) == {"red_02_02_02_00", "yellow_03_02_02_00"}


def test_pc02r_selene_eligible_is_magic_only() -> None:
    session = GameSession(seed=932, mode="debug-card-lab")
    setup_debug_lab(session, "blue_05_02_02r_00", zone="hand", compact_board=True)
    add_debug_card_to_zone(session, "blue_06_02_02r_01", side="P1", zone="field")
    add_debug_card_to_zone(session, "blue_01_03_02r_00", side="P1", zone="deck")
    add_debug_card_to_zone(session, "red_02_02_02_00", side="P1", zone="deck")
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == "blue_05_02_02r_00")
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    payload = {"paymentBaseIids": play["paymentDefaultIids"]} if play.get("paymentDefaultIids") else None
    result = session.choose(session.prompt["id"], play["id"], payload)
    assert result["prompt"] is not None
    option_ids = [option.get("cardId") for option in result["prompt"]["options"] if option.get("cardId")]
    assert option_ids == ["blue_01_03_02r_00"]
    assert "red_02_02_02_00" not in option_ids


def test_pc02r_karapace_and_assault_dive_eligible_match_filters() -> None:
    session = GameSession(seed=933, mode="debug-card-lab")
    setup_debug_lab(session, "yellow_04_02_02r_00", zone="hand", compact_board=True)
    add_debug_card_to_zone(session, "yellow_02_02_02r_00", side="P1", zone="field")
    add_debug_card_to_zone(session, "red_02_02_02_00", side="P1", zone="field")
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == "yellow_04_02_02r_00")
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    payload = {"paymentBaseIids": play["paymentDefaultIids"]} if play.get("paymentDefaultIids") else None
    result = session.choose(session.prompt["id"], play["id"], payload)
    option_ids = [option.get("cardId") for option in result["prompt"]["options"] if option.get("cardId")]
    assert "yellow_02_02_02r_00" in option_ids
    assert "red_02_02_02_00" not in option_ids

    session = GameSession(seed=934, mode="debug-card-lab")
    setup_debug_lab(session, "yellow_05_03_02r_00", zone="hand", compact_board=True)
    add_debug_card_to_zone(session, "yellow_04_02_02r_00", side="P1", zone="deck")
    add_debug_card_to_zone(session, "red_02_02_02_00", side="P1", zone="deck")
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == "yellow_05_03_02r_00")
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    payload = {"paymentBaseIids": play["paymentDefaultIids"]} if play.get("paymentDefaultIids") else None
    result = session.choose(session.prompt["id"], play["id"], payload)
    option_ids = [option.get("cardId") for option in result["prompt"]["options"] if option.get("cardId")]
    assert option_ids == ["yellow_04_02_02r_00"]


def _play_hand_card(session: GameSession, card_id: str) -> dict:
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == card_id)
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    payload = {"paymentBaseIids": play["paymentDefaultIids"]} if play.get("paymentDefaultIids") else None
    return session.choose(session.prompt["id"], play["id"], payload)


def _fill_opponent_base(session: GameSession, count: int = BASE_CAP) -> None:
    opponent = session.engine.state.players[1]
    while len(opponent.base) < count:
        add_debug_card_to_zone(session, "colorless_00_01_02r_00", side="P2", zone="base")


def test_pc02r_assembly_prompts_exact_destroyed_force_discard() -> None:
    session = GameSession(seed=934, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "white_05_03_02r_00",
        zone="hand",
        compact_board=True,
        player_forces=["force_e", "force_so2"],
        opponent_forces=["force_kon", "force_rin"],
    )
    player = session.engine.state.players[0]
    for force in player.forces:
        force.destroyed = True
    for card_id in ("green_02_02_01r_00", "red_02_02_02_00", "colorless_03_02_02r_01"):
        add_debug_card_to_zone(session, card_id, side="P1", zone="deck")

    result = _play_hand_card(session, "white_05_03_02r_00")
    assert result["prompt"] is not None
    assert result["prompt"]["choiceKind"] == "hand_card"
    assert result["prompt"]["requiredTargetCount"] == 2
    assert result["prompt"]["minimumTargetCount"] == 2
    assert result["prompt"]["maximumTargetCount"] == 2
    assert result["prompt"]["allowVariableTargetCount"] is False
    selected = [
        option
        for option in result["prompt"]["options"]
        if option.get("cardId") in {"green_02_02_01r_00", "red_02_02_02_00"}
    ]
    assert len(selected) == 2
    result = session.choose(
        result["prompt"]["id"],
        selected[0]["id"],
        {"selectedOptionIds": [option["id"] for option in selected]},
    )
    assert result["error"] is None
    assert [card.card.id for card in player.hand] == ["colorless_03_02_02r_01"]
    assert {card.card.id for card in player.trash} >= {
        "green_02_02_01r_00",
        "red_02_02_02_00",
    }


def test_pc02r_assembly_direct_callback_clamps_to_available_hand() -> None:
    engine, owner, _ = _engine(policy=RandomLegalPolicy(random.Random(3)))
    source = _instance("white_05_03_02r_00", owner, AreaType.TRASH)
    owner.forces = []
    owner.hand = []
    owner.deck = [_instance("green_02_02_01r_00", owner, AreaType.DECK)]
    # X=2 but only one card is available after drawing; direct engine policy must
    # receive an exact one-card request rather than a variable 1..2 range.
    from zz.forces import Force
    from zz.model import ForceInstance

    owner.forces = [
        ForceInstance(Force("test-force-a", "A", 1), owner, 1),
        ForceInstance(Force("test-force-b", "B", 1), owner, 1),
    ]
    for force in owner.forces:
        force.destroyed = True
    _assembly(source, engine.state, Context(controller=owner, source=source))
    assert len(owner.hand) == 0
    assert any(card.card.id == "green_02_02_01r_00" for card in owner.trash)


def test_pc02r_dual_eagle_direct_policy_requires_exact_two_targets() -> None:
    class RecordingPolicy(PassOnlyPolicy):
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, int]] = []

        def choose_target(self, engine, kind, min_n, max_n, eligible):
            self.calls.append((kind, min_n, max_n))
            return eligible[:max_n]

    policy = RecordingPolicy()
    engine, owner, _ = _engine(policy=policy)
    source = _instance("yellow_08_02_02r_00", owner, AreaType.FIELD)
    ally = _instance("red_02_02_02_00", owner, AreaType.FIELD)
    owner.field = [source, ally]
    _dual_eagle_summon(source, engine.state, Context(controller=owner, source=source))
    assert policy.calls == [("ally_minion", 2, 2)]
    assert sum(card.bp_mod == 300 for card in owner.field) == 2


def test_pc02r_wizardry_full_base_uses_shared_replacement() -> None:
    session = GameSession(seed=935, mode="debug-card-lab")
    session.debug_control_both = True
    setup_debug_lab(session, "blue_04_03_02r_00", zone="hand", compact_board=True)
    add_debug_card_to_zone(session, "colorless_02_02_02r_00", side="P2", zone="field")
    add_debug_card_to_zone(session, "red_02_02_02_00", side="P2", zone="field")
    _fill_opponent_base(session)
    opponent = session.engine.state.players[1]
    assert len(opponent.base) == BASE_CAP
    result = _play_hand_card(session, "blue_04_03_02r_00")
    assert result["prompt"]["requiredTargetCount"] == 1
    assert result["prompt"]["allowVariableTargetCount"] is False
    first = next(option for option in result["prompt"]["options"] if option.get("cardId") == "colorless_02_02_02r_00")
    result = session.choose(result["prompt"]["id"], first["id"])
    second = next(option for option in result["prompt"]["options"] if option.get("cardId") == "red_02_02_02_00")
    result = session.choose(result["prompt"]["id"], second["id"])
    assert result["prompt"] is not None
    assert result["prompt"]["choiceKind"] == "ally_base"
    assert result["prompt"]["playerSide"] == "P2"
    replacement = result["prompt"]["options"][0]
    replaced_iid = replacement["cardIid"]
    result = session.choose(result["prompt"]["id"], replacement["id"])
    assert result["error"] is None
    assert any(card.card.id == "colorless_02_02_02r_00" for card in opponent.trash)
    assert any(card.card.id == "red_02_02_02_00" and card.rested for card in opponent.base)
    assert all(card.card.id != "red_02_02_02_00" for card in opponent.field)
    assert len(opponent.base) == BASE_CAP
    assert all(card.iid != replaced_iid for card in opponent.base)
    assert any(card.iid == replaced_iid for card in opponent.trash)


def test_pc02r_wizardry_random_policy_does_not_skip_legal_targets() -> None:
    engine, owner, opponent = _engine(policy=RandomLegalPolicy(random.Random(1)))
    source = _instance("blue_04_03_02r_00", owner, AreaType.HAND)
    colorless = _instance("colorless_02_02_02r_00", opponent, AreaType.FIELD)
    colored = _instance("red_02_02_02_00", opponent, AreaType.FIELD)
    opponent.field = [colorless, colored]
    owner.hand = [source]
    _wizardry(source, engine.state, Context(controller=owner, source=source))
    assert colorless not in opponent.field
    assert colored not in opponent.field
    assert colored in opponent.base
    assert colored.rested is True


def test_pc02r_oceans_magic_moves_to_base_and_replaces_when_full() -> None:
    session = GameSession(seed=936, mode="debug-card-lab")
    session.debug_control_both = True
    setup_debug_lab(session, "blue_04_02_02r_02", zone="field", compact_board=True)
    add_debug_card_to_zone(session, "green_01_03_02r_00", side="P1", zone="hand")
    add_debug_card_to_zone(session, "green_00_01_02r_00", side="P1", zone="base")
    add_debug_card_to_zone(session, "red_02_02_02_00", side="P2", zone="field")
    _fill_opponent_base(session)
    opponent = session.engine.state.players[1]
    result = _play_hand_card(session, "green_01_03_02r_00")
    assert result["prompt"] is not None
    assert result["prompt"]["kind"] == "effect_target"
    assert result["prompt"]["requiredTargetCount"] == 1
    assert result["prompt"]["allowVariableTargetCount"] is False
    enemy = next(option for option in result["prompt"]["options"] if option.get("cardId") == "red_02_02_02_00")
    result = session.choose(result["prompt"]["id"], enemy["id"])
    assert result["prompt"] is not None
    assert result["prompt"]["choiceKind"] == "ally_base"
    assert result["prompt"]["playerSide"] == "P2"
    replacement = result["prompt"]["options"][0]
    replaced_iid = replacement["cardIid"]
    result = session.choose(result["prompt"]["id"], replacement["id"])
    assert result["error"] is None
    assert any(card.card.id == "red_02_02_02_00" and card.rested for card in opponent.base)
    assert all(card.card.id != "red_02_02_02_00" for card in opponent.field)
    assert len(opponent.base) == BASE_CAP
    assert all(card.iid != replaced_iid for card in opponent.base)
    assert any(card.iid == replaced_iid for card in opponent.trash)


def test_pc02r_rekindled_attack_requires_exact_destroyed_force_count() -> None:
    session = GameSession(seed=937, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "purple_07_02_02r_01",
        zone="field",
        compact_board=True,
        player_forces=["force_e", "force_so2"],
        opponent_forces=["force_kon", "force_rin"],
    )
    add_debug_card_to_zone(session, "colorless_01_02_02r_00", side="P1", zone="trash")
    add_debug_card_to_zone(session, "colorless_02_02_02r_01", side="P1", zone="trash")
    opponent = session.engine.state.players[1]
    opponent.forces[0].destroyed = True
    opponent.forces[1].destroyed = True
    session._prompt_main_action()
    player = session.engine.state.players[0]
    attacker_iid = next(card.iid for card in player.field if card.card.id == "purple_07_02_02r_01")
    attacker = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "attack" and option.get("attacker_iid") == attacker_iid
    )
    result = session.choose(session.prompt["id"], attacker["id"])
    player_target = next(option for option in result["prompt"]["options"] if option.get("kind") == "player")
    result = session.choose(result["prompt"]["id"], player_target["id"])
    assert result["prompt"] is not None
    assert result["prompt"]["kind"] == "effect_target"
    assert result["prompt"]["requiredTargetCount"] == 2
    assert result["prompt"]["minimumTargetCount"] == 2
    assert result["prompt"]["allowVariableTargetCount"] is False
    trash_options = [
        option
        for option in result["prompt"]["options"]
        if option.get("cardId") in {"colorless_01_02_02r_00", "colorless_02_02_02r_01"}
    ]
    assert len(trash_options) == 2
    result = session.choose(
        result["prompt"]["id"],
        trash_options[0]["id"],
        {"selectedOptionIds": [option["id"] for option in trash_options]},
    )
    assert result["error"] is None
    field_ids = [card.card.id for card in player.field]
    assert "purple_07_02_02r_01" in field_ids
    assert "colorless_01_02_02r_00" in field_ids
    assert "colorless_02_02_02r_01" in field_ids

    session = GameSession(seed=938, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "purple_07_02_02r_01",
        zone="field",
        compact_board=True,
        player_forces=["force_e", "force_so2"],
        opponent_forces=["force_kon", "force_rin"],
    )
    opponent = session.engine.state.players[1]
    opponent.forces[0].destroyed = True
    opponent.forces[1].destroyed = True
    session._prompt_main_action()
    player = session.engine.state.players[0]
    attacker_iid = next(card.iid for card in player.field if card.card.id == "purple_07_02_02r_01")
    attacker = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "attack" and option.get("attacker_iid") == attacker_iid
    )
    result = session.choose(session.prompt["id"], attacker["id"])
    player_target = next(option for option in result["prompt"]["options"] if option.get("kind") == "player")
    result = session.choose(result["prompt"]["id"], player_target["id"])
    while result.get("prompt") and result["prompt"]["kind"] == "flash_action":
        flash_pass = next(option for option in result["prompt"]["options"] if option.get("kind") == "flash_pass")
        result = session.choose(result["prompt"]["id"], flash_pass["id"])
    assert result.get("prompt") is None or result["prompt"]["kind"] != "effect_target"
    player = session.engine.state.players[0]
    assert [card.card.id for card in player.field] == ["purple_07_02_02r_01"]
