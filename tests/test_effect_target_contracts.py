from pathlib import Path
import re

import pytest

from tools.run_semantic_scenario import ScenarioRunner
from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, _target_filter, effect_target_filter
from zz.enums import AreaType, CardType, Color
from zz.model import Card, CardInstance, Context
from zz.web.debug_tools import add_debug_card_to_zone
from zz.web.session import GameSession


ROOT = Path(__file__).resolve().parents[1]


def scenario(card_id):
    runner = ScenarioRunner(ROOT / f"tests/semantic_scenarios/pc02r/{card_id}-positive.json", ROOT)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    return runner


def test_roze_prompt_only_offers_cost_seven_field_minions_and_returns_choice():
    runner = scenario("purple_00_01_02r_01")
    add_debug_card_to_zone(runner.session, "purple_00_01_02r_00", side="P1", zone="trash")
    runner._run_action(runner.spec["actions"][0])
    prompt = runner.session.prompt
    assert prompt["kind"] == "effect_target"
    assert [option["cardId"] for option in prompt["options"]] == ["purple_07_02_02r_00"]
    runner._run_action(runner.spec["actions"][1])
    owner = runner.session.engine.state.players[0]
    assert any(card.card.id == "purple_07_02_02r_00" for card in owner.hand)
    assert any(card.card.id == "purple_06_02_02r_01" for card in owner.trash)
    assert runner.session.state_dto()["error"] is None


def test_ruby_dragon_prompt_only_offers_attached_blessing_and_destroys_choice():
    runner = scenario("colorless_05_02_02r_01")
    for action in runner.spec["actions"][:-1]:
        runner._run_action(action)
    prompt = runner.session.prompt
    assert prompt["kind"] == "effect_target"
    assert [option["cardIid"] for option in prompt["options"]] == [runner.captures["boosted_target"]]
    runner._run_action(runner.spec["actions"][-1])
    opponent = runner.session.engine.state.players[1]
    assert any(card.iid == runner.captures["boosted_target"] for card in opponent.trash)
    assert any(card.iid == runner.captures["plain_target"] for card in opponent.field)
    assert runner.session.state_dto()["error"] is None


@pytest.mark.parametrize("param", ["requires_blessing", "requires_boost"])
def test_shared_blessing_filter_requires_live_attachment_not_printed_keyword(param):
    session = GameSession(seed=911, mode="god")
    owner = session.engine.state.players[1]
    host = CardInstance(CARD_REGISTRY["colorless_02_02_02r_00"], owner, area=AreaType.FIELD)
    mana = CardInstance(CARD_REGISTRY["colorless_00_01_02_01"], owner, area=AreaType.BLESSING)
    owner.field.append(host)
    host.blessings.append(mana)
    matcher = _target_filter(session.engine, **{param: True})
    assert matcher(host)
    mana.area = AreaType.BASE
    assert not matcher(host)
    host.blessings.clear()
    assert not matcher(host)


@pytest.mark.parametrize("card_id,valid,invalid,zone", [
    ("red_00_01_02r_01", "colorless_02_02_02r_00", "purple_07_02_02r_00", "enemy_minion"),
    ("yellow_04_02_02r_00", "yellow_02_02_02r_00", "red_02_02_02r_00", "ally_minion"),
    ("yellow_04_02_02r_02", "yellow_06_02_02r_00", "yellow_02_02_02r_00", "ally_minion"),
    ("colorless_01_02_02r_00", "yellow_00_01_02r_00", "colorless_00_01_02r_00", "deck_card"),
])
def test_related_source_contracts_exclude_callback_invalid_targets(card_id, valid, invalid, zone):
    session = GameSession(seed=912, mode="god")
    owner, opponent = session.engine.state.players
    for player in (owner, opponent):
        player.field.clear()
        player.deck.clear()
    recipient = opponent if zone == "enemy_minion" else owner
    area = AreaType.DECK if zone == "deck_card" else AreaType.FIELD
    good = CardInstance(CARD_REGISTRY[valid], recipient, area=area)
    bad = CardInstance(CARD_REGISTRY[invalid], recipient, area=area)
    if zone == "deck_card":
        bad.card = Card("neutral-nymph", "neutral", "neutral", CardType.B_MINION,
                        dp=0, race_jp="ニンフ", printed_color=Color.COLORLESS)
    getattr(recipient, area.value).extend([good, bad])
    source = CardInstance(CARD_REGISTRY[card_id], owner, area=AreaType.FIELD)
    effect = next(effect for effect in source.card.effects if effect.target_kind == zone)
    session._prompt_effect_target(owner, zone, None, 1, effect=effect, source_ci=source)
    assert [option["cardIid"] for option in session.prompt["options"] if option["id"] != "none"] == [good.iid]


@pytest.mark.parametrize("header,keyword,attack", [
    ("【召喚時】", "[加護]", "【アタック時】"),
    ("【召唤时】", "［加护］", "【攻击时】"),
    ("[When Summoned]", "[Boost]", "[When Attacking]"),
])
def test_effect_segments_keep_keyword_body_and_split_next_timing(header, keyword, attack):
    session = GameSession(seed=913, mode="god")
    segments = session._effect_text_segments(f"{header}\nDestroy a minion with {keyword}.\n{attack}\nDraw one card.")
    assert len(segments) == 2
    assert segments[0][1] == f"{header}\nDestroy a minion with {keyword}."
    assert segments[1][1] == f"{attack}\nDraw one card."


@pytest.mark.parametrize("text", [
    "【召喚時】\nこのミニオンに『\n【アタック時】\nカードを1枚引く。』を付与する。\n【破壊時】\nカードを1枚引く。",
    "【召唤时】\n获得『\n【攻击时】\n抽1张牌。』。\n【破坏时】\n抽1张牌。",
    '[When Summoned]\nGive this minion "\n[When Attacking]\nDraw one card."\n[When Destroyed]\nDraw one card.',
])
def test_effect_segments_keep_nested_granted_timing_inside_parent(text):
    session = GameSession(seed=914, mode="god")
    segments = session._effect_text_segments(text)
    assert len(segments) == 2
    assert "Draw one card" in segments[0][1] or "1枚引く" in segments[0][1] or "抽1张" in segments[0][1]


def test_ruby_dragon_prompt_preserves_summon_body_in_all_languages():
    runner = scenario("colorless_05_02_02r_01")
    for action in runner.spec["actions"][:-1]:
        runner._run_action(action)
    fields = runner.session.prompt
    assert "破壊" in fields["effectTextJp"]
    assert "破坏" in fields["effectTextZh"]
    assert "Destroy" in fields["effectTextEn"]


def test_unknown_target_filter_fails_instead_of_offering_unrestricted_targets():
    session = GameSession(seed=915, mode="god")
    effect = EffectSpec(EffectTiming.ON_SUMMON, lambda *_: None, params={"requires_boosst": True})
    with pytest.raises(ValueError, match="requires_boosst"):
        effect_target_filter(session.engine, effect)


def test_pc02r_printed_timing_popups_include_body_in_each_available_language():
    from zz.pc02 import _BLESSING_GRANTED_EFFECTS

    session = GameSession(seed=916, mode="god")
    owner = session.engine.state.players[0]
    checked = {"jp": 0, "zh": 0, "en": 0}
    for card in CARD_REGISTRY.values():
        if "_02r_" not in card.id:
            continue
        source = CardInstance(card, owner)
        abilities = session._card_ability_by_language(source)
        effects = list(card.effects) + list(_BLESSING_GRANTED_EFFECTS.get(card.id, ()))
        for effect in effects:
            for language, ability in abilities.items():
                if not ability:
                    continue
                text, _ = session._matched_effect_segment(source, effect, ability)
                if text is None:
                    continue  # Cleanup callbacks have no printed timing clause.
                body = re.sub(r"【[^】]+】|［[^］]+］|\[[^\]]+\]|《[^》]+》|<[^>]+>", "", text)
                assert body.strip(), (card.id, effect.timing, language, text)
                checked[language] += 1
    assert all(count >= 60 for count in checked.values()), checked


def test_missing_ability_text_uses_official_rule_as_body():
    session = GameSession(seed=919, mode="god")
    source = CardInstance(CARD_REGISTRY["colorless_03_02_02r_03"], session.engine.state.players[0])
    effect = source.card.effects[0]
    text, _ = session._matched_effect_segment(source, effect, "")
    assert text == f"【{effect.official_timing}】\n{effect.official_effect}"


def test_shaina_english_summon_popup_includes_unquoted_granted_abilities():
    session = GameSession(seed=917, mode="god")
    source = CardInstance(CARD_REGISTRY["red_07_02_02r_02"], session.engine.state.players[0])
    fields = session._effect_text_fields(source, source.card.effects[0])
    assert "[Passive] This minion cannot move." in fields["effectTextEn"]
    assert "[At the End of Your Turn] Destroy this" in fields["effectTextEn"]


def test_sapphire_dragon_bless_and_granted_attack_popups_use_own_complete_clause():
    session = GameSession(seed=920, mode="god")
    source = CardInstance(CARD_REGISTRY["colorless_07_02_02r_00"], session.engine.state.players[0])
    bless = next(effect for effect in source.card.effects if effect.timing is EffectTiming.ON_BLESS)
    attack = next(effect for effect in source.card.effects if effect.timing is EffectTiming.ON_ATTACK)
    bless_fields = session._effect_text_fields(source, bless)
    attack_fields = session._effect_text_fields(source, attack)
    for suffix, word, header in (("Jp", "破壊", "【アタック時】"),
                                 ("Zh", "破坏", "【攻击时】"),
                                 ("En", "Destroy", "[When Attacking]")):
        assert word in bless_fields[f"effectText{suffix}"]
        assert attack_fields[f"effectText{suffix}"].startswith(header)
        assert word in attack_fields[f"effectText{suffix}"]


@pytest.mark.parametrize("params", [{"min_cost": 7, "max_cost": 7}, {"requires_blessing": True}])
def test_engine_callback_applies_declared_contract_without_handwritten_filter(params):
    session = GameSession(seed=918, mode="god")
    owner, opponent = session.engine.state.players
    opponent.field.clear()
    good = CardInstance(CARD_REGISTRY["purple_07_02_02r_00"], opponent, area=AreaType.FIELD)
    bad = CardInstance(CARD_REGISTRY["colorless_02_02_02r_00"], opponent, area=AreaType.FIELD)
    opponent.field.extend([bad, good])
    good.blessings.append(CardInstance(CARD_REGISTRY["colorless_00_01_02_01"], opponent, area=AreaType.BLESSING))
    source = CardInstance(CARD_REGISTRY["colorless_05_02_02r_01"], owner, area=AreaType.FIELD)
    offered = []

    class CapturePolicy:
        def choose_target(self, engine, kind, minimum, maximum, eligible):
            offered.extend(eligible)
            return eligible[:maximum]

    session.engine.set_policies(CapturePolicy(), CapturePolicy())

    def callback(ci, state, ctx):
        state.engine.select_target(ci.owner, "enemy_minion", 1, 1, source=ci)

    effect = EffectSpec(EffectTiming.ON_SUMMON, callback, target_kind="enemy_minion", params=params)
    session.engine._run_effect_callback(callback, source, session.engine.state,
                                        Context(controller=owner, source=source), effect=effect)
    assert offered == [good]
