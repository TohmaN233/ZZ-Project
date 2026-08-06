from __future__ import annotations

from zz.cards import CARD_REGISTRY, register
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color, Keyword
from zz.model import Card, CardInstance, Context


def _cost(total: int, color: Color | None = None, colored: int = 0) -> dict[Color, int]:
    cost: dict[Color, int] = {}
    if color is not None and colored:
        cost[color] = colored
    free = total - colored
    if free:
        cost[Color.COLORLESS] = free
    return cost


def _self_played(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.source is ci


def _other_own_minion_played(ci: CardInstance, state, ctx: Context) -> bool:
    source = ctx.source
    return (
        isinstance(source, CardInstance)
        and source is not ci
        and source.owner is ci.owner
        and source.area is AreaType.FIELD
        and source.card.type in {CardType.F_MINION, CardType.B_MINION}
    )


def _other_own_minion_entered_field(ci: CardInstance, state, ctx: Context) -> bool:
    return _other_own_minion_played(ci, state, ctx)


def _move_to_base_rested(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is ci and ci.area is AreaType.BASE:
        ci.rested = True


def _draw_one(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.draw(ci.owner, 1)


def _refresh_self(ci: CardInstance, state, ctx: Context) -> None:
    ci.rested = False


def _turn_end_refresh_base(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.controller is ci.owner and ci.area is AreaType.BASE:
        ci.rested = False


def _own_base_turn_end(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.controller is ci.owner and ci.area is AreaType.BASE


def _buff_ally(bp: int = 0, dp: int = 0, keyword: Keyword | None = None):
    def fn(ci: CardInstance, state, ctx: Context) -> None:
        eng = getattr(state, "engine", None)
        if eng is None:
            return
        targets = eng.select_target(ci.owner, "ally_minion", 1, 1)
        if not targets:
            return
        target = targets[0]
        eng.modify_stat(target, bp_delta=bp, dp_delta=dp)
        if keyword is not None:
            eng.add_keyword(target, keyword)
    return fn


def _surprise_attack(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(ci.owner, "any_minion", 1, 1, source=ci)
    if not targets:
        return
    buff_target = targets[0]
    eng.modify_stat(buff_target, bp_delta=300)
    returns = eng.select_target(
        ci.owner,
        "other_ally_minion",
        0,
        1,
        filter_fn=lambda target: target is not buff_target,
        source=ci,
    )
    if returns:
        eng.return_to_hand(returns[0])


def _return_enemy_max_bp(max_bp: int | None = None):
    def fn(ci: CardInstance, state, ctx: Context) -> None:
        eng = getattr(state, "engine", None)
        if eng is None:
            return
        filter_fn = None
        if max_bp is not None:
            filter_fn = lambda target: eng.effective_bp(target) <= max_bp
        targets = eng.select_target(ci.owner, "enemy_minion", 1, 1, filter_fn=filter_fn)
        if targets:
            eng.return_to_hand(targets[0])
    return fn


def _search_b_minion_to_hand(ci: CardInstance, state, ctx: Context) -> None:
    owner = ci.owner
    eng = getattr(state, "engine", None)
    if eng is not None:
        chosen = eng.select_target(owner, "deck_base_minion", 1, 1)
        candidate = chosen[0] if chosen else None
    else:
        candidate = next(
            (card for card in owner.deck if card.card.type is CardType.B_MINION),
            None,
        )
    if candidate is None:
        if eng is not None:
            eng.rng.shuffle(owner.deck)
        return
    owner.deck.remove(candidate)
    if eng is not None:
        eng.reveal_card(owner, candidate, "deck_search")
        eng.add_to_hand(owner, candidate, from_area=AreaType.DECK)
    else:
        candidate.area = AreaType.HAND
        owner.hand.append(candidate)
    if eng is not None:
        eng.rng.shuffle(owner.deck)


def _aoba_search(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    owner = ci.owner
    top = owner.deck[:4]
    if eng is not None:
        chosen_list = eng.select_target(owner, "top_field_minion", 1, 2, source=ci)
    else:
        chosen_list = [
            card for card in top
            if card.card.type is CardType.F_MINION
        ][:2]
    chosen_iids = {card.iid for card in chosen_list[:2]}
    owner.deck = owner.deck[4:]
    rest: list[CardInstance] = []
    for card in top:
        if card.iid in chosen_iids:
            if eng is not None:
                eng.reveal_card(owner, card, "deck_search")
                eng.add_to_hand(owner, card, from_area=AreaType.DECK)
            else:
                card.area = AreaType.HAND
                owner.hand.append(card)
        else:
            rest.append(card)
    if eng is not None:
        eng.rng.shuffle(rest)
    owner.deck.extend(rest)


def _place_green_base_from_hand_rested(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    owner = ci.owner
    if len(owner.base) >= 10:
        return
    if eng is not None:
        chosen_list = eng.select_target(owner, "ally_green_base_hand", 0, 1)
        candidate = chosen_list[0] if chosen_list else None
    else:
        candidate = next(
            (
                card for card in owner.hand
                if card.card.type is CardType.B_MINION and card.card.mana_color is Color.GREEN
            ),
            None,
        )
    if candidate is None:
        return
    owner.hand.remove(candidate)
    candidate.area = AreaType.BASE
    candidate.rested = True
    owner.base.append(candidate)
    if eng is not None:
        eng.triggers.emit(EffectTiming.ON_PLACE_BASE, Context(controller=owner, source=candidate))
        eng.triggers.resolve_all()


def _heal_when_demete_village_placed(ci: CardInstance, state, ctx: Context) -> None:
    source = ctx.source
    if not isinstance(source, CardInstance):
        return
    if source.owner is ci.owner and source.card.id == "green_00_01_00_00":
        eng = getattr(state, "engine", None)
        if eng is not None:
            eng.heal(ci.owner, 1)


def _rabbie_heal_active(ci: CardInstance, state, ctx: Context) -> bool:
    return ci.area is AreaType.FIELD


def _rest_enemy_cost_at_most(max_cost: int):
    def fn(ci: CardInstance, state, ctx: Context) -> None:
        eng = getattr(state, "engine", None)
        if eng is None:
            return
        def cheap(target: CardInstance) -> bool:
            return sum(target.card.cost.values()) <= max_cost
        targets = eng.select_target(ci.owner, "enemy_minion", 1, 1, filter_fn=cheap)
        if targets:
            eng.rest_target(targets[0])
    return fn


def _rest_enemy_minions(count: int):
    def fn(ci: CardInstance, state, ctx: Context) -> None:
        eng = getattr(state, "engine", None)
        if eng is None:
            return
        targets = eng.select_target(ci.owner, "enemy_minion", count, count)
        for target in targets[:count]:
            eng.rest_target(target)
    return fn


def _binding_ivy(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(ci.owner, "enemy_minion_or_force", 1, 1)
    if targets:
        eng.rest_target(targets[0])


def _wallace_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target.owner is source.owner and target is not source and target.area is AreaType.FIELD:
        return 100, 1
    return 0, 0


def _pelchelsea_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is not source:
        return 0, 0
    eng = getattr(state, "engine", None)
    if eng is None:
        green_mana = sum(1 for card in source.owner.base if card.card.mana_color is Color.GREEN)
    else:
        green_mana = sum(1 for card in source.owner.base if eng._mana_color_of(card) is Color.GREEN)
    if green_mana >= 4:
        return 200, 1
    return 0, 0


def _dalc_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if state.active is not source.owner:
        return 0, 0
    eng = getattr(state, "engine", None)
    keywords = eng.effective_keywords(target) if eng is not None else target.keywords
    if target.owner is source.owner and target is not source and Keyword.PENETRATE in keywords:
        return 100, 1
    return 0, 0


def _card_play_color(card: Card) -> Color:
    for color in card.cost:
        if color is not Color.COLORLESS:
            return color
    return Color.COLORLESS


def _jackknife_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is not source or state.active is not source.owner:
        return 0, 0
    for summoned in getattr(state, "summoned_this_turn", []):
        if summoned is source or summoned.owner is not source.owner:
            continue
        if summoned.card.type is not CardType.F_MINION:
            continue
        if _card_play_color(summoned.card) in {Color.YELLOW, Color.COLORLESS}:
            return 0, 1
    return 0, 0


# Shared colorless cards.
register(Card(
    id="colorless_01_02_00_00",
    name_jp="盾持ちゴブリン",
    name_en="Shield-bearing Goblin",
    type=CardType.F_MINION,
    cost=_cost(1),
    bp=300,
    dp=0,
    effects=[build_effect("move_to_base_rested", EffectTiming.MOVE_TO_BASE)],
))

register(Card(
    id="colorless_05_02_00_02",
    name_jp="ツインテール・シザース",
    name_en="Twin Tail Scissors",
    type=CardType.F_MINION,
    cost=_cost(5),
    bp=500,
    dp=2,
    effects=[build_effect("draw_cards", EffectTiming.ON_SUMMON, condition=_self_played, amount=1)],
))

register(Card(
    id="colorless_06_02_01_04",
    name_jp="「勇気奮わす者」ウォレス",
    name_en="Wallace - The Inspirer",
    type=CardType.F_MINION,
    cost=_cost(6),
    bp=600,
    dp=2,
    aura=_wallace_aura,
))

register(Card(
    id="colorless_03_02_01_07",
    name_jp="「箱を抱く者」パンドリア",
    name_en="Pandoria - The Box Bearer",
    type=CardType.F_MINION,
    cost=_cost(3),
    bp=300,
    dp=1,
    effects=[
        build_effect(
            "search_deck_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_played,
            target_kind="deck_base_minion",
            optional=True,
        )
    ],
))


# Light country Kanatana.
register(Card(
    id="yellow_01_02_01_00",
    name_jp="ジャックナイフスワロウ",
    name_en="Jackknife Swallow",
    type=CardType.F_MINION,
    cost=_cost(1, Color.YELLOW, 1),
    bp=100,
    dp=0,
    effects=[
        build_effect("move_to_base_rested", EffectTiming.MOVE_TO_BASE),
    ],
    aura=_jackknife_aura,
))

register(Card(
    id="yellow_02_02_00_00",
    name_jp="ミーアプリースト",
    name_en="Mia Priest",
    type=CardType.F_MINION,
    cost=_cost(2, Color.YELLOW, 1),
    bp=200,
    dp=1,
    effects=[
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_played,
            target_kind="ally_minion",
            bp_delta=200,
            duration="turn",
        )
    ],
))

register(Card(
    id="yellow_03_02_01_01",
    name_jp="カラス天狗シグレ",
    name_en="Shigure - The Crow Tengu",
    type=CardType.F_MINION,
    cost=_cost(3, Color.YELLOW, 1),
    bp=300,
    dp=1,
    keywords=[Keyword.FLYING],
))

register(Card(
    id="yellow_04_02_00_00",
    name_jp="チータイラ",
    name_en="Cheetaila",
    type=CardType.F_MINION,
    cost=_cost(4, Color.YELLOW, 1),
    bp=400,
    dp=1,
    keywords=[Keyword.FLYING],
))

register(Card(
    id="yellow_04_02_01_00",
    name_jp="イーグルランサー",
    name_en="Eagle Lancer",
    type=CardType.F_MINION,
    cost=_cost(4, Color.YELLOW, 2),
    bp=400,
    dp=1,
    effects=[
        build_effect(
            "return_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_played,
            target_kind="enemy_minion",
            max_bp=400,
        )
    ],
))

register(Card(
    id="yellow_07_02_01_00",
    name_jp="ツーヘッドグリフォン",
    name_en="Two-headed Griffon",
    type=CardType.F_MINION,
    cost=_cost(7, Color.YELLOW, 2),
    bp=700,
    dp=2,
    effects=[
        build_effect(
            "return_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_played,
            target_kind="enemy_minion",
        )
    ],
))

register(Card(
    id="yellow_08_02_01_00",
    name_jp="「双龍頭領」アオバ",
    name_en="Aoba - Twin Dragon Leader",
    type=CardType.F_MINION,
    cost=_cost(9, Color.YELLOW, 3),
    bp=900,
    dp=2,
    effects=[
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _aoba_search,
            _self_played,
            target_kind="top_field_minion",
            min_targets=1,
            max_targets=2,
        ),
        EffectSpec(EffectTiming.ON_ENTER_FIELD, _refresh_self, _other_own_minion_entered_field),
    ],
))

register(Card(
    id="yellow_00_01_00_00",
    name_jp="カナタナの神官",
    name_en="Priest of Kanatana",
    type=CardType.B_MINION,
    cost={},
    mana_color=Color.YELLOW,
    bp=300,
    dp=1,
    keywords=[Keyword.CANNOT_BLOCK],
))

register(Card(
    id="yellow_00_01_01_00",
    name_jp="カナタナの守護者",
    name_en="Guardian of Kanatana",
    type=CardType.B_MINION,
    cost={},
    mana_color=Color.YELLOW,
    bp=100,
    dp=1,
    keywords=[Keyword.CANNOT_BLOCK],
    effects=[
        build_effect(
            "refresh_self",
            EffectTiming.TURN_END,
            condition=_own_base_turn_end,
            active_areas=(AreaType.BASE,),
        )
    ],
))

register(Card(
    id="yellow_02_03_00_00",
    name_jp="不意打ち",
    name_en="Surprise Attack",
    type=CardType.MAGIC,
    cost=_cost(2, Color.YELLOW, 1),
    effects=[
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _surprise_attack,
            target_kind="any_minion",
            min_targets=1,
            max_targets=1,
            params={
                "optional_followup_target_kind": "other_ally_minion",
                "optional_followup_min_targets": 0,
                "optional_followup_max_targets": 1,
                "optional_followup_exclude_first_targets": True,
            },
        )
    ],
    main_timing_ok=False,
    flash_timing_ok=True,
))

register(Card(
    id="yellow_04_03_00_00",
    name_jp="リワインドウインド",
    name_en="Rewind Wind",
    type=CardType.MAGIC,
    cost=_cost(4, Color.YELLOW, 2),
    effects=[build_effect("return_to_hand", EffectTiming.ON_CAST_MAGIC, target_kind="any_minion")],
    main_timing_ok=True,
    flash_timing_ok=True,
))


# Forest country Demete.
register(Card(
    id="green_01_02_01_00",
    name_jp="モルフェオ「ラビィ」",
    name_en="Morpheo Rabbie",
    type=CardType.F_MINION,
    cost=_cost(1, Color.GREEN, 1),
    bp=200,
    dp=0,
    effects=[
        build_effect("move_to_base_rested", EffectTiming.MOVE_TO_BASE),
        EffectSpec(EffectTiming.ON_PLACE_BASE, _heal_when_demete_village_placed, _rabbie_heal_active),
    ],
))

register(Card(
    id="green_02_02_00_00",
    name_jp="「盲目の風読み」メリエルナ",
    name_en="Merielna - The Blind Wind Reader",
    type=CardType.F_MINION,
    cost=_cost(2, Color.GREEN, 1),
    bp=300,
    dp=0,
    effects=[
        build_effect(
            "place_base_from_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_played,
            target_kind="ally_green_base_hand",
            color=Color.GREEN,
            rested=True,
            optional=True,
        )
    ],
))

register(Card(
    id="green_03_02_00_00",
    name_jp="ペルチャルシー",
    name_en="Pelchelsea",
    type=CardType.F_MINION,
    cost=_cost(3, Color.GREEN, 1),
    bp=300,
    dp=1,
    aura=_pelchelsea_aura,
))

register(Card(
    id="green_03_02_01_01",
    name_jp="アパウルツォーク",
    name_en="Apaulzork",
    type=CardType.F_MINION,
    cost=_cost(3, Color.GREEN, 1),
    bp=300,
    dp=1,
    effects=[
        build_effect(
            "rest_targets",
            EffectTiming.ON_ATTACK,
            condition=_self_played,
            target_kind="enemy_minion_cost_at_most_4",
            max_cost=4,
        )
    ],
))

register(Card(
    id="green_05_02_01_01",
    name_jp="ダルティチェロンテ",
    name_en="Dalticheronte",
    type=CardType.F_MINION,
    cost=_cost(5, Color.GREEN, 2),
    bp=500,
    dp=2,
    keywords=[Keyword.PENETRATE],
    aura=_dalc_aura,
))

register(Card(
    id="green_07_02_01_00",
    name_jp="「愛花」アルルーナ",
    name_en="Alruna - The Love Flower",
    type=CardType.F_MINION,
    cost=_cost(7, Color.GREEN, 2),
    bp=600,
    dp=2,
    effects=[
        build_effect(
            "rest_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_played,
            target_kind="enemy_minion",
            min_targets=2,
            max_targets=2,
        )
    ],
))

register(Card(
    id="green_09_02_01_00",
    name_jp="「千年杉」ヤクーツォーク",
    name_en="Yakutzork - The Thousand-year Cedar",
    type=CardType.F_MINION,
    cost=_cost(9, Color.GREEN, 3),
    bp=1000,
    dp=4,
    keywords=[Keyword.PENETRATE],
))

register(Card(
    id="green_00_01_00_00",
    name_jp="デメテーの村娘",
    name_en="Village Girl of Demete",
    type=CardType.B_MINION,
    cost={},
    mana_color=Color.GREEN,
    bp=300,
    dp=1,
    keywords=[Keyword.CANNOT_BLOCK],
))

register(Card(
    id="green_00_01_01_00",
    name_jp="デメテーの守護者",
    name_en="Guardian of Demete",
    type=CardType.B_MINION,
    cost={},
    mana_color=Color.GREEN,
    bp=100,
    dp=1,
    keywords=[Keyword.CANNOT_BLOCK],
    effects=[
        build_effect(
            "refresh_self",
            EffectTiming.TURN_END,
            condition=_own_base_turn_end,
            active_areas=(AreaType.BASE,),
        )
    ],
))

register(Card(
    id="green_01_03_00_00",
    name_jp="バインディングアイヴィ",
    name_en="Binding Ivy",
    type=CardType.MAGIC,
    cost=_cost(1, Color.GREEN, 1),
    effects=[build_effect("rest_targets", EffectTiming.ON_CAST_MAGIC, target_kind="enemy_minion_or_force")],
    main_timing_ok=True,
    flash_timing_ok=True,
))

register(Card(
    id="green_03_03_00_00",
    name_jp="パワーアップル",
    name_en="Power Apple",
    type=CardType.MAGIC,
    cost=_cost(3, Color.GREEN, 2),
    effects=[
        build_effect(
            "stat_modifier",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="ally_minion",
            bp_delta=300,
            dp_delta=1,
            keyword=Keyword.PENETRATE,
            duration="turn",
            official_effect="貫通",
        )
    ],
    main_timing_ok=True,
    flash_timing_ok=True,
))


_ABILITY_JP_BY_ID = {
    "colorless_01_02_00_00": """【常時】
このミニオンはベースに移動するとき、レスト状態で移動する。""",
    "colorless_05_02_00_02": """【召喚時】
自分はカードを1枚引く。""",
    "colorless_06_02_01_04": """【常時】
他の自分のミニオン全てをBP+100/DP+1する。""",
    "colorless_03_02_01_07": """【召喚時】
自分はデッキの中からベース・ミニオンカード1枚を公開して手札に加えることができる。そうした場合、自分のデッキをシャッフルする。""",
    "yellow_01_02_01_00": """【自分のターン】
このターンに他の自分の黄または無色のミニオンを召喚している場合、このミニオンをDP+1する。
【常時】
このミニオンはベースに移動するとき、レスト状態で移動する。""",
    "yellow_02_02_00_00": """【召喚時】
このターン中、自分のミニオン1体をBP+200する。""",
    "yellow_03_02_01_01": "飛来",
    "yellow_04_02_00_00": "飛来",
    "yellow_04_02_01_00": """【召喚時】
相手のBP400以下のミニオン1体を手札に戻す。""",
    "yellow_07_02_01_00": """【召喚時】
相手のミニオン1体を手札に戻す。""",
    "yellow_08_02_01_00": """【召喚時】
自分のデッキを上から4枚見て、その中のフィールド・ミニオンカード2枚を公開して手札に加える。残りをランダムにデッキの下に戻す。
【常時】
他の自分のミニオンがフィールドに出るたび、このミニオンをアクティブにする。""",
    "yellow_00_01_00_00": """《デッキ》
このカードは何枚でもデッキに入れられる。
【常時】
このミニオンはブロックできない。""",
    "yellow_00_01_01_00": """【常時】
このミニオンはブロックできない。
《ベース》【自分のターン終了時】
このマナをアクティブにする。""",
    "yellow_02_03_00_00": """【フラッシュ】
このターン中、ミニオン1体をBP+300する。他のミニオン1体を手札に戻すことができる。""",
    "yellow_04_03_00_00": """【メイン】/【フラッシュ】
ミニオン1体を手札に戻す。""",
    "green_01_02_01_00": """【常時】
自分の「デメテーの村娘」が置かれるたび、自分のプレイヤーを1回復する。
【常時】
このミニオンはベースに移動するとき、レスト状態で移動する。""",
    "green_02_02_00_00": """【召喚時】
自分の手札にある緑のベース・ミニオンカードを1枚を、レスト状態で置くことができる。""",
    "green_03_02_00_00": """【常時】
自分の緑マナが4つ以上ある場合、このミニオンをBP+200/DP+1する。
【相手のターン】
自分のプレイヤーか自分のフォースに与えられる無色のミニオンからのダメージを1軽減する。""",
    "green_03_02_01_01": """【アタック時】
相手のコスト4以下のミニオン1体をレストする。""",
    "green_05_02_01_01": """貫通
【自分のターン】
他の自分の[貫通]を持つミニオン全てをBP+100/DP+1する。""",
    "green_07_02_01_00": """【召喚時】
相手のミニオン2体をレストする。""",
    "green_09_02_01_00": """貫通
【相手のターン】
自分のプレイヤーに与えられるダメージを1軽減する。""",
    "green_00_01_00_00": """《デッキ》
このカードは何枚でもデッキに入れられる。
【常時】
このミニオンはブロックできない。""",
    "green_00_01_01_00": """【常時】
このミニオンはブロックできない。
《ベース》【自分のターン終了時】
このマナをアクティブにする。""",
    "green_01_03_00_00": """【メイン】/【フラッシュ】
ミニオン1体かフォース1つをレストする。""",
    "green_03_03_00_00": """【メイン】/【フラッシュ】
このターン中、ミニオン1体をBP+300/DP+1して[貫通]を与える。""",
}

for _card_id, _ability_jp in _ABILITY_JP_BY_ID.items():
    CARD_REGISTRY[_card_id].ability_jp = _ability_jp


KANATANA_YELLOW_RECIPE: dict[str, int] = {
    "colorless_01_02_00_00": 3,
    "colorless_05_02_00_02": 3,
    "colorless_06_02_01_04": 2,
    "yellow_01_02_01_00": 3,
    "yellow_02_02_00_00": 3,
    "yellow_03_02_01_01": 3,
    "yellow_04_02_00_00": 3,
    "yellow_04_02_01_00": 3,
    "yellow_07_02_01_00": 3,
    "yellow_08_02_01_00": 1,
    "yellow_00_01_00_00": 4,
    "yellow_00_01_01_00": 3,
    "yellow_02_03_00_00": 3,
    "yellow_04_03_00_00": 3,
}

DEMETE_GREEN_RECIPE: dict[str, int] = {
    "colorless_01_02_00_00": 3,
    "colorless_03_02_01_07": 2,
    "colorless_05_02_00_02": 3,
    "green_01_02_01_00": 3,
    "green_02_02_00_00": 3,
    "green_03_02_00_00": 3,
    "green_03_02_01_01": 3,
    "green_05_02_01_01": 3,
    "green_07_02_01_00": 3,
    "green_09_02_01_00": 1,
    "green_00_01_00_00": 4,
    "green_00_01_01_00": 3,
    "green_01_03_00_00": 3,
    "green_03_03_00_00": 3,
}

DECKCODE0_YELLOW_FORCES: list[str] = ["force_e", "force_so2"]
DECKCODE0_GREEN_FORCES: list[str] = ["force_so2", "force_rin"]
