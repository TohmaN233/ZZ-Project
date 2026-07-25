from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

from zz.enums import AreaType, CardType, Color, Keyword

if TYPE_CHECKING:
    from zz.model import CardInstance, Context, ForceInstance, GameState, Player
    from zz.engine import Engine


@dataclass
class Force:
    id: str
    name_jp: str
    initial_life: int
    passive: Optional[Callable] = None     # signature: (force_instance, engine) -> None (called at game start)
    on_destroy: Optional[Callable] = None  # signature: (force_instance, state, ctx) -> None
    ability_jp: str = ""
    ability_en: str = ""


# ---- shared on_destroy ----------------------------------------------

def _search_bminion_shuffle_draw(fi: "ForceInstance", state: "GameState", ctx: "Context") -> None:
    """Common 破壊時 across all 10: search deck for 1 B-Minion, place to Base, shuffle, draw 1.
    If no B-Minion found, still shuffle and draw.

    For 麗 セイレーン and 悪 サイクロプス, rulebook says 【配置時】効果は発揮しない:
    the placed B-Minion does NOT fire its ON_PLAY. (No B-Minion in Aguma has ON_PLAY, so MVP-safe.)
    """
    from zz.enums import CardType
    owner: "Player" = fi.owner
    eng: "Engine" = state.engine if hasattr(state, "engine") else None
    if eng:
        eng.handle_force_destroy_base_search(fi)
        return
    for i, ci in enumerate(list(owner.deck)):
        if ci.card.type is CardType.B_MINION:
            owner.deck.pop(i)
            ci.area = AreaType.BASE
            ci.rested = False
            owner.base.append(ci)
            break


# ---- HR1 toggle -----------------------------------------------------

from zz.house_rules import HR1_CYCLOPS_BP_DELTA


# ---- 10 Force passives ----------------------------------------------

_MINION_TYPES = (CardType.F_MINION, CardType.B_MINION)


def _force_can_exert(fi: "ForceInstance") -> bool:
    return not fi.destroyed and not fi.rested


def _passive_cyclops(fi: "ForceInstance", engine: "Engine") -> None:
    """悪 サイクロプス: 自分のミニオン全て BP+HR1_CYCLOPS_BP_DELTA (Minion only — not tokens/Magic)"""
    def modifier_fn(ci: "CardInstance", state):
        if (_force_can_exert(fi)
            and ci.owner is fi.owner
            and ci.card.type in _MINION_TYPES):
            return HR1_CYCLOPS_BP_DELTA, 0
        return 0, 0
    modifier_fn._force_iid = id(fi)
    engine._passive_modifiers.append(("force_passive", modifier_fn))


def _passive_chimera(fi: "ForceInstance", engine: "Engine") -> None:
    """混 キマイラ: own turn, colorless mana → all colors for F-Minion cost."""
    def modifier_fn(player, ci_being_paid_for):
        if not _force_can_exert(fi):
            return False
        if player is not fi.owner:
            return False
        # only own turn
        if engine.state.active is not fi.owner:
            return False
        return ci_being_paid_for.card.type is CardType.F_MINION
    modifier_fn._force_iid = id(fi)
    engine._passive_modifiers.append(("chimera_colorless_anycolor", modifier_fn))


def _passive_minotauros(fi: "ForceInstance", engine: "Engine") -> None:
    """凱 ミノタウロス: -1 DP-damage to own player from enemy minions."""
    def modifier_fn(damage_amount, source_kind, target_player=None, source=None):
        if target_player is not fi.owner:
            return damage_amount
        if not _force_can_exert(fi) or source_kind != "minion_dp":
            return damage_amount
        return max(0, damage_amount - 1)
    modifier_fn._force_iid = id(fi)
    engine._passive_modifiers.append(("player_dmg_reduce_from_minion", modifier_fn))


def _passive_orthrus(fi: "ForceInstance", engine: "Engine") -> None:
    """双 オルトロス: own cost>=5 minions get DP+1 (Minion only — not tokens/Magic)."""
    def modifier_fn(ci, state):
        if (not _force_can_exert(fi)
            or ci.owner is not fi.owner
            or ci.card.type not in _MINION_TYPES):
            return 0, 0
        total_cost = sum(ci.card.cost.values())
        if total_cost >= 5:
            return 0, 1
        return 0, 0
    modifier_fn._force_iid = id(fi)
    engine._passive_modifiers.append(("force_passive", modifier_fn))


def _passive_sphinx(fi: "ForceInstance", engine: "Engine") -> None:
    """聖 スフィンクス: enemy turn, own cost<=5 minions cannot be selected by enemy minion effects."""
    def predicate(ci, selector_kind, source=None):
        if not _force_can_exert(fi):
            return True
        if ci.owner is not fi.owner:
            return True
        if engine.state.active is fi.owner:
            return True
        total_cost = sum(ci.card.cost.values())
        if total_cost <= 5 and selector_kind == "enemy_minion_effect":
            return False
        return True
    predicate._force_iid = id(fi)
    engine._passive_modifiers.append(("sphinx_selection_ward", predicate))


def _passive_chiron(fi: "ForceInstance", engine: "Engine") -> None:
    """知 ケイローン: own hand Magic cards' free cost -2."""
    def modifier_fn(ci, current_cost=None):
        if not _force_can_exert(fi) or ci.owner is not fi.owner:
            return dict(current_cost or ci.card.cost)
        if ci.card.type is not CardType.MAGIC:
            return dict(current_cost or ci.card.cost)
        new_cost = dict(current_cost or ci.card.cost)
        new_cost[Color.COLORLESS] = max(0, new_cost.get(Color.COLORLESS, 0) - 2)
        return new_cost
    modifier_fn._force_iid = id(fi)
    engine._passive_modifiers.append(("magic_cost_reduce", modifier_fn))


def _passive_siren(fi: "ForceInstance", engine: "Engine") -> None:
    """麗 セイレーン: own turn, when own minion-mana moves to Field OR own KAGO mana is granted from Base,
    place 1 colorless mana token (rested) to Base."""
    def hook(event_kind, ci, state):
        if not _force_can_exert(fi) or engine.state.active is not fi.owner:
            return
        if event_kind == "minion_mana_moves_to_field":
            if ci.owner is fi.owner:
                if len(fi.owner.base) >= 10:
                    return
                token = engine.place_generated_colorless_mana(fi.owner)
                token.rested = True
        # KAGO branch unreachable in Aguma MVP
    hook._force_iid = id(fi)
    engine._passive_modifiers.append(("siren_mana_hook", hook))


def _passive_pegasus(fi: "ForceInstance", engine: "Engine") -> None:
    """翔 ペガサス: own turn start, if own mana >= 4, +1 movement right."""
    def at_turn_start():
        if not _force_can_exert(fi) or engine.state.active is not fi.owner:
            return
        if len(fi.owner.base) >= 4:
            engine.grant_movement_right(fi.owner, 1)
    at_turn_start._force_iid = id(fi)
    engine._passive_modifiers.append(("turn_start_hook", at_turn_start))


def _passive_phoenix(fi: "ForceInstance", engine: "Engine") -> None:
    """甦 フェニックス: own turn end, refresh all own mana."""
    def at_turn_end():
        if not _force_can_exert(fi) or engine.state.active is not fi.owner:
            return
        for ci in fi.owner.base:
            ci.rested = False
    at_turn_end._force_iid = id(fi)
    engine._passive_modifiers.append(("turn_end_hook", at_turn_end))


def _passive_ouroboros(fi: "ForceInstance", engine: "Engine") -> None:
    """輪 ウロボロス: own turn end, refresh all own non-token minions."""
    def at_turn_end():
        if not _force_can_exert(fi) or engine.state.active is not fi.owner:
            return
        for ci in fi.owner.field:
            if ci.card.type is not CardType.MANA_TOKEN:
                ci.rested = False
    at_turn_end._force_iid = id(fi)
    engine._passive_modifiers.append(("turn_end_hook", at_turn_end))


# ---- Force definitions ---------------------------------------------

FORCE_DESTROY_TEXT_JP = (
    "【破壊時】\n"
    "自分のデッキからベース・ミニオンカード1枚を選び、ベースに置く。"
    "その後、デッキをシャッフルし、自分はカードを1枚引く。"
)


F_CYCLOPS = Force(
    id="force_e", name_jp='悪のフォース "サイクロプス"',
    initial_life=2, passive=_passive_cyclops,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【常時】\n自分のミニオン全てをBP+200する。\n" + FORCE_DESTROY_TEXT_JP,
)

F_CHIMERA = Force(
    id="force_kon", name_jp='混のフォース "キマイラ"',
    initial_life=3, passive=_passive_chimera,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【自分のターン】\n自分の無色マナはフィールド・ミニオンのコスト支払いでは全ての色として扱う。\n" + FORCE_DESTROY_TEXT_JP,
)

F_MINOTAUROS = Force(
    id="force_kai", name_jp='凱のフォース "ミノタウロス"',
    initial_life=4, passive=_passive_minotauros,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【常時】\n相手のミニオンから自分のプレイヤーに与えられるダメージを1軽減する。\n" + FORCE_DESTROY_TEXT_JP,
)

F_ORTHRUS = Force(
    id="force_so", name_jp='双のフォース "オルトロス"',
    initial_life=3, passive=_passive_orthrus,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【常時】\n自分のコスト5以上のミニオン全てをDP+1する。\n" + FORCE_DESTROY_TEXT_JP,
)

F_SPHINX = Force(
    id="force_sei", name_jp='聖のフォース "スフィンクス"',
    initial_life=3, passive=_passive_sphinx,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【相手のターン】\n自分のコスト5以下のミニオンは相手のミニオンの効果で選ばれない。\n" + FORCE_DESTROY_TEXT_JP,
)

F_CHIRON = Force(
    id="force_chi", name_jp='知のフォース "ケイローン"',
    initial_life=4, passive=_passive_chiron,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【常時】\n自分の手札にあるマジックカードの無色コストを2減らす。\n" + FORCE_DESTROY_TEXT_JP,
)

F_SIREN = Force(
    id="force_li", name_jp='麗のフォース "セイレーン"',
    initial_life=2, passive=_passive_siren,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【自分のターン】\n自分のミニオン・マナがフィールドに移動するたび、無色マナ1つをレスト状態でベースに置く。\n" + FORCE_DESTROY_TEXT_JP,
)

F_PEGASUS = Force(
    id="force_sho", name_jp='翔のフォース "ペガサス"',
    initial_life=3, passive=_passive_pegasus,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【自分のターン開始時】\n自分のマナが4つ以上ある場合、このターンの移動権を1増やす。\n" + FORCE_DESTROY_TEXT_JP,
)

F_PHOENIX = Force(
    id="force_so2", name_jp='甦のフォース "フェニックス"',
    initial_life=3, passive=_passive_phoenix,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【自分のターン終了時】\n自分のマナ全てをアクティブにする。\n" + FORCE_DESTROY_TEXT_JP,
)

F_OUROBOROS = Force(
    id="force_rin", name_jp='輪のフォース "ウロボロス"',
    initial_life=2, passive=_passive_ouroboros,
    on_destroy=_search_bminion_shuffle_draw,
    ability_jp="【自分のターン終了時】\n自分のミニオン全てをアクティブにする。\n" + FORCE_DESTROY_TEXT_JP,
)


ALL_FORCES = {
    f.id: f for f in [
        F_CYCLOPS, F_CHIMERA, F_MINOTAUROS, F_ORTHRUS, F_SPHINX,
        F_CHIRON, F_SIREN, F_PEGASUS, F_PHOENIX, F_OUROBOROS,
    ]
}
