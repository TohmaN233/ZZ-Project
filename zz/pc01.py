from __future__ import annotations

import csv
import re
from pathlib import Path

from zz.cards import CARD_REGISTRY, register
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, AttackTargetKind, CardType, Color, Keyword
from zz.model import Card, CardInstance, Context, ForceInstance, Player


PC01_PACK_JP = "PC:01 AWAKEN"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CARD_TSV = PROJECT_ROOT / "data" / "cards_bilingual_v4.tsv"
LEGACY_CARD_TSV = PROJECT_ROOT.parent / "cards" / "cards_bilingual_v4.tsv"
DEFAULT_CARD_TSV = LOCAL_CARD_TSV if LOCAL_CARD_TSV.exists() else LEGACY_CARD_TSV


_TYPE_BY_OFFICIAL = {
    "base_minion": CardType.B_MINION,
    "field_minion": CardType.F_MINION,
    "magic": CardType.MAGIC,
}

_COLOR_BY_OFFICIAL = {
    "red": Color.RED,
    "yellow": Color.YELLOW,
    "white": Color.WHITE,
    "green": Color.GREEN,
    "blue": Color.BLUE,
    "purple": Color.PURPLE,
    "colorless": Color.COLORLESS,
}

_COLOR_BY_SEESAA_LABEL = {
    "赤": Color.RED,
    "黄": Color.YELLOW,
    "白": Color.WHITE,
    "緑": Color.GREEN,
    "青": Color.BLUE,
    "紫": Color.PURPLE,
    "無": Color.COLORLESS,
    "無色": Color.COLORLESS,
}

_KEYWORD_MARKERS = {
    "襲撃": Keyword.RUSH,
    "飛来": Keyword.FLYING,
    "再起": Keyword.REAWAKEN,
    "貫通": Keyword.PENETRATE,
    "潜入": Keyword.SNEAKING,
    "奪命": Keyword.DEATH_BLOW,
    "連携": Keyword.COOPERATION,
    "加護": Keyword.KAGO,
}

_EXTRA_KEYWORDS_BY_ID = {
    "blue_05_02_01_00": (Keyword.UNBLOCKABLE,),
}

_CARD_FACE_OVERRIDES = {
    "colorless_01_02_01_01": {
        "official_name_jp": "荒野の旅人",
        "bp": "100",
        "dp": "0",
    },
    "colorless_03_02_00_03": {
        "bp": "300",
        "dp": "1",
        "ability_jp": "襲撃",
    },
    "white_04_02_01_01": {
        "bp": "500",
        "dp": "1",
    },
    "yellow_04_02_01_02": {
        "bp": "400",
        "dp": "1",
    },
    "yellow_05_02_01_00": {
        "bp": "600",
        "dp": "1",
    },
    "colorless_010_02_01_00": {
        "bp": "1200",
        "dp": "3",
        "ability_jp": (
            "［襲撃］\n"
            "【アタック時】\n"
            "相手のプレイヤーに3ダメージを与える。このダメージは相手のフォース1つ毎に1軽減される。"
        ),
    },
    "colorless_012_02_01_00": {
        "bp": "1000",
        "dp": "3",
        "ability_jp": (
            "【自分のターン】\n"
            "自分の手札にあるこのカードのフリーコストは、お互いの破壊されたフォース1つ毎に3減らされる。"
        ),
    },
}


def _own_base_turn_end(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.controller is ci.owner and ci.area is AreaType.BASE


def _self_source(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.source is ci


def _self_source_on_own_turn(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.source is ci and _is_own_turn(ci, state)


def _attacking_player(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.source is ci and isinstance(ctx.target, Player)


def _source_is_self_and_target_own_player(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.source is ci and ctx.target is not None and ctx.target is ci.owner


def _source_is_self_and_target_opponent_player(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.source is ci and isinstance(ctx.target, Player) and ctx.target is not ci.owner


def _source_is_self_and_own_turn(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.source is ci and _is_own_turn(ci, state)


def _other_own_source(ci: CardInstance, state, ctx: Context) -> bool:
    source = ctx.source
    return (
        isinstance(source, CardInstance)
        and source is not ci
        and source.owner is ci.owner
        and ci.area is AreaType.FIELD
    )


def _other_own_minion_destroyed(ci: CardInstance, state, ctx: Context) -> bool:
    target = ctx.target
    return (
        isinstance(target, CardInstance)
        and target is not ci
        and target.owner is ci.owner
        and ci.area is AreaType.FIELD
    )


def _other_own_minion_attacks_force(ci: CardInstance, state, ctx: Context) -> bool:
    source = ctx.source
    return (
        isinstance(source, CardInstance)
        and source is not ci
        and source.owner is ci.owner
        and isinstance(ctx.target, ForceInstance)
        and ci.area is AreaType.FIELD
    )


def _own_turn_start(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.controller is ci.owner and ci.area is AreaType.FIELD


def _mana_color_of(ci: CardInstance) -> Color:
    override = getattr(ci, "mana_color_override", None)
    if override is not None:
        return override
    if ci.card.mana_color is not None:
        return ci.card.mana_color
    for color in ci.card.cost:
        if color is not Color.COLORLESS:
            return color
    return Color.COLORLESS


def _own_color_mana_count(ci: CardInstance, color: Color) -> int:
    return sum(1 for base_ci in ci.owner.base if _mana_color_of(base_ci) is color)


def _self_source_and_own_color_mana_at_least(color: Color, amount: int):
    def condition(ci: CardInstance, state, ctx: Context) -> bool:
        return _self_source(ci, state, ctx) and _own_color_mana_count(ci, color) >= amount
    return condition


def _self_source_and_mana_color_placed_this_turn(color: Color):
    def condition(ci: CardInstance, state, ctx: Context) -> bool:
        return _self_source(ci, state, ctx) and f"turn:placed_mana:{color.name}" in ci.owner.flags
    return condition


def _own_color_mana_at_least(color: Color, amount: int):
    def condition(ci: CardInstance, state, ctx: Context) -> bool:
        return _own_color_mana_count(ci, color) >= amount
    return condition


def _own_turn_end_and_color_mana_at_least(color: Color, amount: int):
    def condition(ci: CardInstance, state, ctx: Context) -> bool:
        return (
            ctx.controller is ci.owner
            and ci.area is AreaType.FIELD
            and _own_color_mana_count(ci, color) >= amount
        )
    return condition


def _own_magic_cast(ci: CardInstance, state, ctx: Context) -> bool:
    source = ctx.source
    return (
        ci.area is AreaType.FIELD
        and ctx.controller is ci.owner
        and isinstance(source, CardInstance)
        and source.card.type is CardType.MAGIC
    )


def _own_turn_end_with_other_minion(ci: CardInstance, state, ctx: Context) -> bool:
    return (
        ctx.controller is ci.owner
        and ci.area is AreaType.FIELD
        and any(other is not ci for other in ci.owner.field)
    )


def _marker_effect() -> EffectSpec:
    return EffectSpec(EffectTiming.CONTINUOUS, lambda ci, state, ctx: None)


def _clean_text(value: str | None) -> str:
    return (
        str(value or "")
        .replace("\r\n", "\n")
        .replace("\\n", "\n")
        .replace("/n", "\n")
        .strip()
    )


def _parse_int(value: str | None) -> int:
    text = str(value or "").strip()
    if not text or text == "-":
        return 0
    if text.endswith("+"):
        return int(text[:-1] or "0")
    return int(text)


def _cost_from_image_id(card_id: str) -> int:
    match = re.match(r"^[a-z]+_(\d+)_", card_id)
    if match is None:
        return 0
    return int(match.group(1))


def _seesaa_cost_rows(path: Path = DEFAULT_CARD_TSV.with_name("seesaa.tsv")) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            row["name_jp"].strip(): (row.get("cost") or "").strip()
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("name_jp")
        }


_SEESAA_COST_BY_NAME = _seesaa_cost_rows()


def _parse_seesaa_cost_label(label: str | None) -> dict[Color, int] | None:
    text = str(label or "").strip()
    match = re.fullmatch(r"(\d+)\(([^0-9)]+)(\d+)\)", text)
    if match is None:
        return None
    total = int(match.group(1))
    color = _COLOR_BY_SEESAA_LABEL.get(match.group(2))
    colored = int(match.group(3))
    if color is None:
        return None
    colored = min(colored, total)
    if color is Color.COLORLESS:
        return {Color.COLORLESS: total}
    cost = {color: colored}
    colorless = total - colored
    if colorless:
        cost[Color.COLORLESS] = colorless
    return cost


def _seesaa_cost(row: dict[str, str]) -> dict[Color, int] | None:
    direct = _parse_seesaa_cost_label(row.get("cost") or row.get("cost_official"))
    if direct is not None:
        return direct
    for name_key in ("official_name_jp", "name_jp"):
        name = _clean_text(row.get(name_key))
        if not name:
            continue
        cost = _parse_seesaa_cost_label(_SEESAA_COST_BY_NAME.get(name))
        if cost is not None:
            return cost
    return None


def _total_cost(row: dict[str, str]) -> int:
    label = (row.get("cost") or row.get("cost_official") or "").strip()
    if label.endswith("+"):
        return _cost_from_image_id(row["image_id"])
    exact_match = re.fullmatch(r"(\d+)\([^)]*\)", label)
    if exact_match is not None:
        return int(exact_match.group(1))
    return _parse_int(label)


def _cost(row: dict[str, str], color: Color, card_type: CardType) -> dict[Color, int]:
    if card_type is CardType.B_MINION:
        return {}
    official_cost = _seesaa_cost(row)
    if official_cost is not None:
        return official_cost
    total = _total_cost(row)
    if total <= 0:
        return {}
    if color is Color.COLORLESS:
        return {Color.COLORLESS: total}
    colored = 1
    colorless = total - colored
    cost = {color: colored}
    if colorless:
        cost[Color.COLORLESS] = colorless
    return cost


def _keywords(ability_jp: str) -> list[Keyword]:
    keywords: list[Keyword] = []
    lines = [
        line.strip()
        for line in ability_jp.splitlines()
        if line.strip()
    ]
    for marker, keyword in _KEYWORD_MARKERS.items():
        marker_re = re.compile(rf"^[［\[]\s*{re.escape(marker)}(?:[：:].+)?\s*[］\]]$")
        standalone_re = re.compile(rf"^{re.escape(marker)}(?:\s*[：:]\s*.*)?$")
        # A card can mention a keyword in its rules text without owning it.
        # For example, Tuhansapi says that it can receive [Bless], but it is
        # not itself Bless mana.  Only standalone keyword markers contribute
        # to the intrinsic keyword list.
        if any(line == marker or marker_re.match(line) or standalone_re.match(line) for line in lines):
            keywords.append(keyword)
    # Printed keyword badges may be adjacent on one line (for example
    # ``［襲撃］［再起］``).  Treat the complete line as a keyword-only
    # sequence, while still ignoring keyword mentions embedded in prose.
    for line in lines:
        markers = re.findall(r"[［\[]\s*([^］\]]+?)\s*[］\]]", line)
        if not markers or "".join(f"［{marker}］" for marker in markers) != line.replace(" ", ""):
            continue
        for marker in markers:
            marker = marker.strip()
            keyword = _KEYWORD_MARKERS.get(marker)
            if keyword is not None and keyword not in keywords:
                keywords.append(keyword)
    if "このミニオンはブロックできない" in ability_jp or "このカードはブロックできない" in ability_jp:
        keywords.append(Keyword.CANNOT_BLOCK)
    return keywords


def _cooperation_color(ability_jp: str) -> Color | None:
    match = re.search(r"[［\[]\s*連携\s*[：:]\s*([^］\]\s]+)\s*[］\]]", ability_jp)
    if not match:
        return None
    return _COLOR_BY_SEESAA_LABEL.get(match.group(1).strip())


def _effects(card_id: str, ability_jp: str) -> list:
    effects = []
    if "ベースに移動するとき、レスト状態で移動する" in ability_jp:
        effects.append(build_effect("move_to_base_rested", EffectTiming.MOVE_TO_BASE))
    if "《ベース》" in ability_jp and "【自分のターン終了時】" in ability_jp and "アクティブ" in ability_jp:
        effects.append(
            build_effect(
                "refresh_self",
                EffectTiming.TURN_END,
                condition=_own_base_turn_end,
                active_areas=(AreaType.BASE,),
            )
        )
    if "【配置時】" in ability_jp and "自分はカードを1枚引く" in ability_jp:
        effects.append(build_effect("draw_cards", EffectTiming.ON_PLACE_BASE, condition=_self_source, amount=1))
    cooperation_color = _cooperation_color(ability_jp)
    if cooperation_color is not None:
        effects.append(
            build_effect(
                "draw_cards",
                EffectTiming.ON_SUMMON,
                condition=_self_source_and_mana_color_placed_this_turn(cooperation_color),
                amount=1,
                official_condition="連携",
            )
        )
    effects.extend(_extra_effects(card_id))
    return effects


def _extra_effects(card_id: str) -> list:
    return list(_EXTRA_EFFECTS_BY_ID.get(card_id, ()))


def _magic_timing_flags(ability_jp: str, card_type: CardType) -> tuple[bool, bool]:
    if card_type is not CardType.MAGIC:
        return True, False
    has_main = "【メイン】" in ability_jp
    has_flash = "【フラッシュ】" in ability_jp
    if has_main or has_flash:
        return has_main, has_flash
    return True, False


def _card_from_row(row: dict[str, str]) -> Card:
    row = _row_with_face_overrides(row)
    card_id = row["image_id"].strip()
    card_type = _TYPE_BY_OFFICIAL[row["card_type"].strip()]
    color = _COLOR_BY_OFFICIAL[(row.get("attribute") or row.get("color") or "").strip()]
    ability_jp = _clean_text(row.get("ability_jp"))
    keywords = _keywords(ability_jp)
    keywords.extend(keyword for keyword in _EXTRA_KEYWORDS_BY_ID.get(card_id, ()) if keyword not in keywords)
    main_timing_ok, flash_timing_ok = _magic_timing_flags(ability_jp, card_type)
    return Card(
        id=card_id,
        name_jp=_clean_text(row.get("official_name_jp") or row.get("name_jp")),
        name_en=_clean_text(row.get("name_en")),
        type=card_type,
        cost=_cost(row, color, card_type),
        bp=_parse_int(row.get("bp")),
        dp=_parse_int(row.get("dp")),
        mana_color=color if card_type is CardType.B_MINION else None,
        keywords=keywords,
        race_jp=_clean_text(row.get("race_jp")),
        ability_jp=ability_jp,
        ability_en=_clean_text(row.get("ability_en")),
        effects=_effects(card_id, ability_jp),
        aura=_extra_aura(card_id),
        keyword_aura=_extra_keyword_aura(card_id),
        main_timing_ok=main_timing_ok,
        flash_timing_ok=flash_timing_ok,
    )


def _row_with_face_overrides(row: dict[str, str]) -> dict[str, str]:
    card_id = row["image_id"].strip()
    overrides = _CARD_FACE_OVERRIDES.get(card_id)
    if not overrides:
        return row
    merged = dict(row)
    for key, value in overrides.items():
        if not _clean_text(merged.get(key)):
            merged[key] = value
    return merged


def _pc01_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            dict(row)
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("pack_jp_official") == PC01_PACK_JP
        ]
    rows.sort(key=lambda row: int(row.get("official_order") or 999999))
    return rows


def register_pc01_cards(path: Path = DEFAULT_CARD_TSV) -> list[str]:
    registered_ids: list[str] = []
    for row in _pc01_rows(path):
        card_id = row["image_id"].strip()
        if card_id not in CARD_REGISTRY:
            register(_card_from_row(row))
        registered_ids.append(card_id)
    return registered_ids


def _is_own_turn(source: CardInstance, state) -> bool:
    return state.active is source.owner


def _is_card_color(card, color: Color) -> bool:
    if card.mana_color is not None:
        return card.mana_color is color
    return color in card.cost


def _other_own_field_minion(source: CardInstance, target: CardInstance) -> bool:
    return target is not source and target.owner is source.owner and target.area is AreaType.FIELD


def _own_field_minion(source: CardInstance, target: CardInstance) -> bool:
    return target.owner is source.owner and target.area is AreaType.FIELD


def _pc01_red_other_own_bp(source: CardInstance, target: CardInstance, state, amount: int) -> tuple[int, int]:
    if _is_own_turn(source, state) and _other_own_field_minion(source, target):
        return amount, 0
    return 0, 0


def _diana_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if (
        _is_own_turn(source, state)
        and _other_own_field_minion(source, target)
        and _is_card_color(target.card, Color.RED)
    ):
        return 200, 0
    return 0, 0


def _dancing_cutlass_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is source and source.area is AreaType.FIELD and not _is_own_turn(source, state):
        return 400, 0
    return 0, 0


def _undine_magic_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if (
        target is source
        and source.area is AreaType.FIELD
        and _is_own_turn(source, state)
        and "cast_magic_this_turn" in source.owner.flags
    ):
        return 0, 1
    return 0, 0


def _bankguys_rush_aura(source: CardInstance, target: CardInstance, state) -> list[Keyword]:
    if (
        _is_own_turn(source, state)
        and _own_field_minion(source, target)
        and target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and sum(target.card.cost.values()) <= 3
    ):
        return [Keyword.RUSH]
    return []


def _riyabo_life_keyword_aura(source: CardInstance, target: CardInstance, state) -> list[Keyword]:
    if (
        target is source
        and source.area is AreaType.FIELD
        and source.owner.life >= 7
    ):
        return [Keyword.RUSH, Keyword.PENETRATE, Keyword.REAWAKEN]
    return []


def _audrey_reawaken_aura(source: CardInstance, target: CardInstance, state) -> list[Keyword]:
    if (
        source.area is AreaType.FIELD
        and target is not source
        and _own_field_minion(source, target)
        and target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and _is_card_color(target.card, Color.WHITE)
    ):
        return [Keyword.REAWAKEN]
    return []


def _sams_rush_dp_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    eng = getattr(state, "engine", None)
    if (
        eng is not None
        and _is_own_turn(source, state)
        and _own_field_minion(source, target)
        and target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and eng.has_keyword(target, Keyword.RUSH)
    ):
        return 0, 1
    return 0, 0


def _boareater_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is source and source.owner.life <= 3:
        return 200, 1
    return 0, 0


def _fearsome_pheasant_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is not source:
        return 0, 0
    if not source.owner.forces:
        return 0, 0
    if all(force.destroyed for force in source.owner.forces):
        return 0, 1
    return 0, 0


def _gleyg_smasher_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is not source:
        return 0, 0
    others = [
        ci for ci in source.owner.field
        if ci is not source
        and ci.card.type is not CardType.MANA_TOKEN
        and not ci.card.is_token
    ]
    return 200 * len(others), 0


def _destroyed_own_force_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is not source:
        return 0, 0
    count = sum(1 for force in source.owner.forces if force.destroyed)
    return 200 * count, count


def _destroyed_enemy_force_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is not source:
        return 0, 0
    opponent = state.players[1 - state.players.index(source.owner)]
    count = sum(1 for force in opponent.forces if force.destroyed)
    return 200 * count, count


def _white_opponent_turn_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if not _is_own_turn(source, state) and _own_field_minion(source, target):
        return 200, 0
    return 0, 0


def _force_count_self_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is not source:
        return 0, 0
    count = len([force for force in source.owner.forces if not force.destroyed])
    return 100 * count, count


def _basic_shadowhand_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is not source:
        return 0, 0
    opponent = state.players[1 - state.players.index(source.owner)]
    count = sum(1 for force in opponent.forces if force.destroyed)
    return 200 * count, count


def _basic_crabion_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is not source:
        return 0, 0
    count = sum(1 for force in source.owner.forces if not force.destroyed)
    return 200 * count, 0


def _basic_howling_dire_aura(source: CardInstance, target: CardInstance, state) -> tuple[int, int]:
    if target is source:
        return 0, 0
    if target.owner is source.owner and target.area is AreaType.FIELD:
        return 100, 0
    return 0, 0


def _pixie_draw_once(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.target is not ci.owner or ci.area is not AreaType.FIELD:
        return
    flag = f"_pixie_drawn_{id(ci.owner)}"
    if getattr(ctx, flag, False):
        return
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    setattr(ctx, flag, True)
    eng.draw(ci.owner, 1)


def _acid_dragon_gain_dp(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.target is not ci.owner or ci.area is not AreaType.FIELD:
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.modify_stat(ci, dp_delta=1, duration="permanent")


def _mold_gain_bp(ci: CardInstance, state, ctx: Context) -> None:
    if not _other_own_minion_destroyed(ci, state, ctx):
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.modify_stat(ci, bp_delta=100, duration="permanent")


def _brave_drummer_attack(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is not ci:
        return
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    others = [other for other in ci.owner.field if other is not ci and other.card.type is not CardType.MANA_TOKEN]
    eng.modify_stat(ci, dp_delta=len(others))


def _schedule_refresh_all_base_at_turn_end(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is ci:
        eng = getattr(state, "engine", None)
        if eng is not None:
            owner = ci.owner

            def refresh_base() -> None:
                for base in owner.base:
                    base.rested = False

            eng.schedule_turn_end_effect(owner, refresh_base)


def _barichalguo_refresh(ci: CardInstance, state, ctx: Context) -> None:
    source = ctx.source
    if (
        ci.area is AreaType.FIELD
        and ctx.target is ci.owner
        and isinstance(source, CardInstance)
        and source.owner is not ci.owner
        and sum(source.card.cost.values()) <= 5
    ):
        ci.rested = False


def _ashbringer_buff_force_attacker(ci: CardInstance, state, ctx: Context) -> None:
    source = ctx.source
    eng = getattr(state, "engine", None)
    if eng is not None and _other_own_minion_attacks_force(ci, state, ctx):
        eng.modify_stat(source, bp_delta=200)


def _zintine_destroy_and_refresh(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is not ci:
        return
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(ci.owner, "other_ally_minion", 0, 1, filter_fn=lambda target: target is not ci, source=ci)
    if not targets:
        return
    eng.destroy_target(targets[0], source=ci)
    ci.rested = False


def _aleshand_move_minion_mana_to_field(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is not ci:
        return
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(
        ci.owner,
        "ally_minion_base",
        0,
        3,
        filter_fn=lambda target: target.card.type in (CardType.B_MINION, CardType.F_MINION),
        source=ci,
    )
    for target in targets[:3]:
        if target not in ci.owner.base:
            continue
        replace_iid = None
        if len(ci.owner.field) >= 5:
            replacements = eng.select_target(ci.owner, "ally_minion", 1, 1, source=ci)
            if not replacements:
                return
            replace_iid = replacements[0].iid
        eng.move_base_minion_to_field(ci.owner, target, rested=False, replace_field_iid=replace_iid)


def _odd_eye_destroy_minion_and_force(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    minions = eng.select_target(ci.owner, "enemy_minion", 0, 1, source=ci)
    if minions:
        eng.destroy_target(minions[0], source=ci)
    forces = eng.select_target(ci.owner, "enemy_force", 0, 1, source=ci)
    if forces:
        eng.destroy_target(forces[0], source=ci)


def _crimson_mail_force_attack_dp(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is not ci or not isinstance(ctx.target, ForceInstance):
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.modify_stat(ci, dp_delta=1)


def _arondai_mark_player_attack(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is ci and isinstance(ctx.target, Player) and ctx.target is not ci.owner:
        ci.owner.flags.add("turn:arondai_player_attack")


def _arondai_attacking_enemy_player(ci: CardInstance, state, ctx: Context) -> bool:
    return ctx.source is ci and isinstance(ctx.target, Player) and ctx.target is not ci.owner


def _arondai_block_ping(ci: CardInstance, state, ctx: Context) -> None:
    if "turn:arondai_player_attack" not in ci.flags or ci.area is not AreaType.FIELD:
        return
    blocked = ctx.target
    if not isinstance(blocked, CardInstance) or blocked.owner is not ci.owner:
        return
    opponent = state.players[1 - state.players.index(ci.owner)]
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng._damage_player(opponent, 1, source=ci)


def _alababaster_attack_player_damage(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is not ci or not isinstance(ctx.target, Player) or ctx.target is ci.owner:
        return
    live_forces = sum(1 for force in ctx.target.forces if not force.destroyed)
    amount = max(0, 3 - live_forces)
    eng = getattr(state, "engine", None)
    if eng is not None and amount:
        eng._damage_player(ctx.target, amount, source=ci)


def _vicerave_battle_win_damage(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is not ci or not _is_own_turn(ci, state):
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        build_effect("damage_targets", EffectTiming.ON_BATTLE_WIN, target_kind="opponent_player_and_forces").fn(ci, state, ctx)


def _axe_biter_gain_bp(ci: CardInstance, state, ctx: Context) -> None:
    source = ctx.source
    if ci.area is not AreaType.FIELD or not isinstance(source, CardInstance) or source.owner is not ci.owner:
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.modify_stat(ci, bp_delta=100, duration="permanent")


def _raven_cat_gain_bp(ci: CardInstance, state, ctx: Context) -> None:
    if not _other_own_source(ci, state, ctx):
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.modify_stat(ci, bp_delta=200)


def _brigitte_draw_on_green_cost5_enter(ci: CardInstance, state, ctx: Context) -> None:
    source = ctx.source
    if (
        ci.area is not AreaType.FIELD
        or not _is_own_turn(ci, state)
        or not isinstance(source, CardInstance)
        or source is ci
        or source.owner is not ci.owner
        or source.area is not AreaType.FIELD
        or sum(source.card.cost.values()) < 5
        or not _is_card_color(source.card, Color.GREEN)
    ):
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.draw(ci.owner, 1)


def _angela_buff_on_yellow_enter(ci: CardInstance, state, ctx: Context) -> None:
    source = ctx.source
    if (
        ci.area is not AreaType.FIELD
        or not isinstance(source, CardInstance)
        or source is ci
        or source.owner is not ci.owner
        or source.area is not AreaType.FIELD
        or not _is_card_color(source.card, Color.YELLOW)
    ):
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        for target in list(ci.owner.field):
            eng.modify_stat(target, bp_delta=100)


def _asogi_buff_flying_enter(ci: CardInstance, state, ctx: Context) -> None:
    source = ctx.source
    eng = getattr(state, "engine", None)
    if (
        ci.area is not AreaType.FIELD
        or not isinstance(source, CardInstance)
        or source.owner is not ci.owner
        or source.area is not AreaType.FIELD
        or not ((eng is not None and eng.has_keyword(source, Keyword.FLYING)) or Keyword.FLYING in source.keywords)
    ):
        return
    if eng is not None:
        eng.modify_stat(source, bp_delta=300, dp_delta=1)


def _basic_eola_raptor_attack(ci: CardInstance, state, ctx: Context) -> None:
    if ctx.source is not ci:
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.modify_stat(ci, bp_delta=300)


def _basic_control_current(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(ci.owner, "any_minion", 1, 1, source=ci)
    if not targets:
        return
    target = targets[0]
    eng.modify_stat(target, bp_delta=300)
    if "マーフォーク" in target.card.race_jp:
        eng.draw(ci.owner, 1)


def _basic_reactive_shield(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(ci.owner, "any_minion", 1, 1, source=ci)
    if not targets:
        return
    target = targets[0]
    eng.modify_stat(target, bp_delta=300)
    if state.active is not ci.owner:
        target.rested = False


def _basic_tuba_magic_gain_bp(ci: CardInstance, state, ctx: Context) -> None:
    if not _own_magic_cast(ci, state, ctx):
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.modify_stat(ci, bp_delta=100, duration="permanent")


def _basic_little_plank_change_colorless_mana(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(
        ci.owner,
        "ally_colorless_mana_token",
        1,
        1,
        source=ci,
    )
    if not targets:
        return
    chosen_color = None
    for flag in list(ci.flags):
        if not flag.startswith("pending_mana_color:"):
            continue
        ci.flags.remove(flag)
        chosen_color = Color[flag.split(":", 1)[1]]
        break
    if chosen_color is None:
        chosen_color = eng.rng.choice([
            Color.RED,
            Color.YELLOW,
            Color.WHITE,
            Color.GREEN,
            Color.BLUE,
            Color.PURPLE,
        ])
    targets[0].mana_color_override = chosen_color


def _basic_replace_draw_discard(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    eng.draw(ci.owner, 2)
    targets = eng.select_target(ci.owner, "hand_card", 1, 1, source=ci)
    if not targets:
        return
    eng.discard_from_hand(ci.owner, targets[0])


def _basic_returning_demons(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(
        ci.owner,
        "trash_minion",
        0,
        2,
        filter_fn=lambda target: "デーモン" in target.card.race_jp,
        source=ci,
    )
    for target in targets[:2]:
        if target not in ci.owner.trash:
            continue
        eng.add_to_hand(ci.owner, target, from_area=AreaType.TRASH)


def _basic_emergency_excavation(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(
        ci.owner,
        "ally_colorless_mana_token",
        1,
        1,
        source=ci,
    )
    if not targets:
        return
    eng._eject_base_card(ci.owner, targets[0])
    eng.draw(ci.owner, 2)


def _marisa_buff_blue_damage_source(ci: CardInstance, state, ctx: Context) -> None:
    source = ctx.source
    if (
        ci.area is not AreaType.FIELD
        or not _is_own_turn(ci, state)
        or not isinstance(source, CardInstance)
        or source is ci
        or source.owner is not ci.owner
        or source.area is not AreaType.FIELD
        or source.card.type not in (CardType.F_MINION, CardType.B_MINION)
        or not _is_card_color(source.card, Color.BLUE)
    ):
        return
    eng = getattr(state, "engine", None)
    if eng is not None:
        eng.modify_stat(source, dp_delta=1, duration="permanent")


def _catherine_purple_force_destroy_reward(ci: CardInstance, state, ctx: Context) -> None:
    if getattr(ctx, "_catherine_rewarded", False):
        return
    source = ctx.source
    target = ctx.target
    if (
        ci.area is not AreaType.FIELD
        or not _is_own_turn(ci, state)
        or not isinstance(source, CardInstance)
        or source is ci
        or source.owner is not ci.owner
        or source.area is not AreaType.FIELD
        or source.card.type not in (CardType.F_MINION, CardType.B_MINION)
        or not _is_card_color(source.card, Color.PURPLE)
        or not isinstance(target, ForceInstance)
        or not target.destroyed
        or getattr(ctx, "damage_kind", None) != "minion_dp"
    ):
        return
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    replace_iid = None
    if len(ci.owner.base) >= 10:
        replacements = eng.select_target(ci.owner, "ally_base", 1, 1, source=ci)
        if not replacements:
            return
        replace_iid = replacements[0].iid
    setattr(ctx, "_catherine_rewarded", True)
    eng.place_generated_colorless_mana(ci.owner, replace_base_iid=replace_iid)
    eng.draw(ci.owner, 1)


def _catherine_purple_force_destroy_condition(ci: CardInstance, state, ctx: Context) -> bool:
    source = ctx.source
    target = ctx.target
    return (
        ci.area is AreaType.FIELD
        and _is_own_turn(ci, state)
        and isinstance(source, CardInstance)
        and source is not ci
        and source.owner is ci.owner
        and source.area is AreaType.FIELD
        and source.card.type in (CardType.F_MINION, CardType.B_MINION)
        and _is_card_color(source.card, Color.PURPLE)
        and isinstance(target, ForceInstance)
        and target.destroyed
        and getattr(ctx, "damage_kind", None) == "minion_dp"
    )


def _basic_gert_force_blocker(ci: CardInstance, state, ctx: Context) -> None:
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    targets = eng.select_target(ci.owner, "enemy_minion", 1, 1, source=ci)
    if not targets:
        return
    target = targets[0]
    target.rested = False
    target.flags.add("turn:must_block")


def _basic_pinkscara_damage_draw(ci: CardInstance, state, ctx: Context) -> None:
    source = ctx.source
    if (
        ci.area is not AreaType.FIELD
        or not _is_own_turn(ci, state)
        or not isinstance(source, CardInstance)
        or source is ci
        or source.owner is not ci.owner
    ):
        return
    if getattr(ctx, "_pinkscara_drawn", False):
        return
    eng = getattr(state, "engine", None)
    if eng is None:
        return
    setattr(ctx, "_pinkscara_drawn", True)
    eng.draw(ci.owner, 1)


def _extra_aura(card_id: str):
    return _EXTRA_AURAS_BY_ID.get(card_id)


def _extra_keyword_aura(card_id: str):
    return _EXTRA_KEYWORD_AURAS_BY_ID.get(card_id)


_EXTRA_EFFECTS_BY_ID = {
    "blue_02_02_00_00": (
        EffectSpec(EffectTiming.ON_CAST_MAGIC, _basic_tuba_magic_gain_bp),
    ),
    "red_02_02_00_00": (
        EffectSpec(EffectTiming.ON_ATTACK, _basic_eola_raptor_attack, condition=_self_source),
    ),
    "blue_03_02_00_00": (
        build_effect("draw_cards", EffectTiming.ON_SUMMON, condition=_self_source, amount=1),
    ),
    "red_02_03_00_01": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion",
            bp_delta=-300,
            duration="turn",
        ),
    ),
    "red_03_02_00_00": (
        build_effect(
            "create_tokens",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            amount=1,
            token_id="s_golem_token",
            name_jp="S・ゴレイム・トークン",
            color=Color.RED,
            cost=1,
            bp=100,
            dp=1,
        ),
    ),
    "blue_05_02_00_00": (
        EffectSpec(EffectTiming.ON_DAMAGE_PLAYER, _basic_pinkscara_damage_draw),
        EffectSpec(EffectTiming.ON_DAMAGE_FORCE, _basic_pinkscara_damage_draw),
    ),
    "blue_02_03_00_00": (
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _basic_control_current,
            target_kind="any_minion",
            params={"target_role": "beneficial"},
        ),
    ),
    "blue_03_03_00_00": (
        build_effect("draw_cards", EffectTiming.ON_CAST_MAGIC, amount=2),
    ),
    "blue_03_03_00_01": (
        build_effect(
            "move_to_base_targets",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion",
            rested=True,
        ),
    ),
    "colorless_02_02_00_02": (
        build_effect("draw_cards", EffectTiming.ON_DESTROY, amount=1),
    ),
    "colorless_02_02_00_03": (
        build_effect("heal_targets", EffectTiming.ON_DESTROY, target_kind="ally_force", amount=1),
    ),
    "colorless_03_02_00_00": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="any_minion",
            bp_delta=300,
            duration="turn",
            exclude_self=True,
        ),
    ),
    "red_02_03_00_00": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="any_minion",
            bp_delta=300,
            keyword=Keyword.RUSH,
            duration="turn",
        ),
    ),
    "colorless_03_02_00_02": (
        build_effect("heal_targets", EffectTiming.ON_SUMMON, condition=_self_source, target_kind="owner_player"),
    ),
    "colorless_03_02_00_04": (
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _basic_little_plank_change_colorless_mana,
            condition=_self_source,
            target_kind="ally_colorless_mana_token",
            params={"choose_mana_color": True},
        ),
    ),
    "colorless_04_02_00_01": (_marker_effect(),),
    "colorless_04_02_00_03": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="enemy_minion",
            max_bp=400,
        ),
    ),
    "purple_04_02_00_00": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_DESTROY,
            target_kind="enemy_minion",
            max_cost=4,
        ),
    ),
    "colorless_06_02_00_00": (
        build_effect(
            "damage_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="opponent_player",
            amount=1,
        ),
    ),
    "colorless_07_02_00_00": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="enemy_minion",
            max_bp=500,
        ),
    ),
    "green_05_02_00_00": (
        build_effect("rest_targets", EffectTiming.ON_SUMMON, condition=_self_source, target_kind="enemy_minion"),
    ),
    "purple_02_03_00_00": (
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _basic_returning_demons,
            target_kind="trash_minion",
            min_targets=0,
            max_targets=2,
            params={"race": "デーモン", "allow_variable_targets": True},
        ),
    ),
    "purple_02_03_00_01": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="any_minion",
            bp_delta=300,
            keyword=Keyword.DEATH_BLOW,
            duration="turn",
        ),
    ),
    "purple_05_02_00_00": (
        build_effect(
            "return_from_trash_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="trash_field_minion",
            optional=True,
        ),
    ),
    "purple_05_03_00_00": (
        build_effect("destroy_targets", EffectTiming.ON_CAST_MAGIC, target_kind="any_minion"),
    ),
    "red_01_03_00_00": (
        EffectSpec(EffectTiming.ON_CAST_MAGIC, _basic_emergency_excavation, target_kind="ally_colorless_mana_token"),
    ),
    "green_04_03_00_00": (
        build_effect(
            "place_base_from_deck",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="deck_base_minion",
            card_id="green_00_01_00_00",
            min_targets=0,
            max_targets=2,
            rested=True,
            optional=True,
        ),
    ),
    "yellow_05_02_00_00": (_marker_effect(),),
    "white_02_03_00_01": (
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _basic_replace_draw_discard,
            params={"post_draw_discard_hand": True, "draw_amount": 2},
        ),
    ),
    "white_02_02_00_00": (_marker_effect(),),
    "white_02_03_00_00": (
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _basic_reactive_shield,
            target_kind="any_minion",
            params={"target_role": "beneficial", "defensive_reactive": True, "bp_delta": 300},
        ),
    ),
    "white_05_02_00_00": (
        EffectSpec(EffectTiming.ON_SUMMON, _basic_gert_force_blocker, condition=_self_source, target_kind="enemy_minion"),
    ),
    "yellow_01_03_00_00": (
        build_effect(
            "look_top_to_hand",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="top3_field_minion",
            top_n=3,
        ),
    ),
    "colorless_01_02_01_01": (
        build_effect(
            "search_deck_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="deck_base_minion",
            card_ids=(
                "red_00_01_00_00",
                "yellow_00_01_00_00",
                "white_00_01_00_00",
                "green_00_01_00_00",
                "blue_00_01_00_00",
                "purple_00_01_00_00",
            ),
            optional=True,
        ),
    ),
    "white_03_03_00_00": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="any_minion",
            min_cost=5,
        ),
    ),
    "yellow_03_02_00_00": (
        build_effect(
            "look_top_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="top2_field_minion",
            top_n=2,
        ),
    ),
    "blue_04_03_01_00": (
        build_effect(
            "grant_unblockable",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="ally_minion",
            return_if_race="シーワーム",
        ),
    ),
    "colorless_03_02_01_01": (
        build_effect("place_colorless_mana", EffectTiming.ON_DESTROY),
    ),
    "colorless_03_02_01_03": (
        EffectSpec(EffectTiming.ON_DAMAGE_PLAYER, _pixie_draw_once),
    ),
    "colorless_03_02_01_04": (
        build_effect(
            "search_deck_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="deck_minion",
            optional=True,
            race="ゴブリン",
            exclude_card_id="colorless_03_02_01_04",
        ),
    ),
    "colorless_04_02_01_02": (
        EffectSpec(EffectTiming.ON_DAMAGE_PLAYER, _acid_dragon_gain_dp),
    ),
    "colorless_04_02_01_04": (_marker_effect(),),
    "colorless_04_02_01_06": (
        EffectSpec(EffectTiming.ON_DESTROY, _mold_gain_bp, condition=_other_own_minion_destroyed),
    ),
    "colorless_05_02_01_05": (_marker_effect(),),
    "colorless_06_02_01_01": (
        EffectSpec(EffectTiming.ON_ATTACK, _brave_drummer_attack, condition=_self_source),
    ),
    "colorless_06_02_01_02": (
        build_effect(
            "damage_targets",
            EffectTiming.ON_DAMAGE_PLAYER,
            condition=_source_is_self_and_target_opponent_player,
            target_kind="opponent_forces",
            amount=2,
        ),
    ),
    "colorless_06_02_01_03": (_marker_effect(),),
    "colorless_07_02_01_01": (
        EffectSpec(EffectTiming.ON_SUMMON, _schedule_refresh_all_base_at_turn_end, condition=_self_source),
    ),
    "colorless_08_02_01_01": (
        EffectSpec(
            EffectTiming.ON_ATTACK,
            lambda ci, state, ctx: ci.flags.add("unblockable_by_cost_at_most_3"),
            condition=_self_source,
        ),
    ),
    "colorless_08_02_01_02": (_marker_effect(),),
    "green_02_03_01_00": (
        build_effect("prevent_player_damage", EffectTiming.ON_CAST_MAGIC, amount=1),
    ),
    "green_03_02_01_00": (
        EffectSpec(EffectTiming.ON_ATTACK, _barichalguo_refresh),
    ),
    "green_03_02_01_02": (
        EffectSpec(EffectTiming.ON_ENTER_FIELD, _brigitte_draw_on_green_cost5_enter),
    ),
    "green_04_02_01_01": (_marker_effect(),),
    "green_05_02_01_00": (
        build_effect(
            "place_base_from_deck",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="deck_base_minion",
            card_id="green_00_01_00_00",
            rested=True,
            optional=True,
        ),
    ),
    "purple_02_02_01_01": (
        _marker_effect(),
        EffectSpec(EffectTiming.ON_ATTACK, _ashbringer_buff_force_attacker),
    ),
    "purple_03_03_01_00": (
        build_effect(
            "summon_from_trash",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="trash_field_minion",
            max_cost=4,
        ),
    ),
    "purple_04_02_01_00": (_marker_effect(),),
    "purple_06_02_01_00": (
        build_effect(
            "summon_from_trash",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="trash_field_minion",
            max_cost=3,
        ),
    ),
    "purple_06_02_01_01": (
        EffectSpec(EffectTiming.ON_ATTACK, _zintine_destroy_and_refresh, condition=_self_source, target_kind="other_ally_minion", optional=True),
    ),
    "purple_07_02_01_00": (
        EffectSpec(EffectTiming.ON_DESTROY, _odd_eye_destroy_minion_and_force),
    ),
    "purple_08_02_01_00": (
        _marker_effect(),
        build_effect(
            "summon_from_trash",
            EffectTiming.ON_ATTACK,
            condition=_self_source,
            target_kind="trash_field_minion",
            color=Color.PURPLE,
            exclude_card_id="purple_08_02_01_00",
        ),
    ),
    "white_01_03_01_00": (
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            lambda ci, state, ctx: ci.owner.flags.add("hunter_must_be_blocked"),
        ),
    ),
    "white_02_02_01_00": (
        build_effect("force_block", EffectTiming.ON_ATTACK, condition=_self_source),
    ),
    "white_04_02_01_01": (_marker_effect(),),
    "white_06_02_01_02": (
        EffectSpec(EffectTiming.ON_BATTLE_WIN, _axe_biter_gain_bp),
    ),
    "white_08_02_01_00": (
        _marker_effect(),
        EffectSpec(EffectTiming.ON_BATTLE_WIN, _vicerave_battle_win_damage),
    ),
    "white_08_02_01_01": (
        build_effect(
            "stat_modifier_all",
            EffectTiming.ON_ATTACK,
            condition=_self_source_and_own_color_mana_at_least(Color.WHITE, 4),
            target_kind="ally_minion",
            bp_delta=100,
            duration="permanent",
        ),
        _marker_effect(),
    ),
    "white_09_02_01_00": (
        build_effect(
            "force_block",
            EffectTiming.ON_ATTACK,
            condition=_self_source,
            target_kind="enemy_minion",
            choose_target=True,
            optional=True,
        ),
    ),
    "yellow_03_02_01_00": (
        EffectSpec(EffectTiming.ON_ENTER_FIELD, _raven_cat_gain_bp),
    ),
    "yellow_03_02_01_02": (
        EffectSpec(EffectTiming.ON_ENTER_FIELD, _angela_buff_on_yellow_enter),
    ),
    "yellow_04_02_01_02": (
        EffectSpec(EffectTiming.ON_ENTER_FIELD, _asogi_buff_flying_enter),
    ),
    "blue_02_03_01_01": (
        build_effect(
            "move_to_base_targets",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion_cost_at_most_4",
            max_cost=4,
            rested=True,
        ),
    ),
    "blue_02_02_01_00": (
        build_effect("draw_cards", EffectTiming.ON_SUMMON, condition=_self_source, amount=1, scope="both"),
    ),
    "blue_03_02_01_00": (
        build_effect(
            "refresh_targets",
            EffectTiming.ON_DAMAGE_PLAYER,
            condition=_self_source,
            target_kind="ally_base",
            max_targets=1,
            optional=True,
            only_rested=True,
        ),
        build_effect(
            "refresh_targets",
            EffectTiming.ON_DAMAGE_FORCE,
            condition=_self_source,
            target_kind="ally_base",
            max_targets=1,
            optional=True,
            only_rested=True,
        ),
    ),
    "blue_03_02_01_01": (
        EffectSpec(EffectTiming.ON_DAMAGE_PLAYER, _marisa_buff_blue_damage_source),
        EffectSpec(EffectTiming.ON_DAMAGE_FORCE, _marisa_buff_blue_damage_source),
    ),
    "blue_02_03_01_00": (
        build_effect(
            "stat_modifier_all",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion",
            max_cost=4,
            dp_delta=-1,
            duration="turn",
            applies_to_future=True,
        ),
    ),
    "blue_05_02_01_02": (
        build_effect(
            "create_tokens",
            EffectTiming.ON_CAST_MAGIC,
            condition=_own_magic_cast,
            amount=1,
            token_id="merfolk_token",
            name_jp="マーフォーク・トークン",
            color=Color.BLUE,
            cost=2,
            bp=200,
            dp=1,
        ),
    ),
    "blue_06_02_01_00": (
        build_effect(
            "refresh_targets",
            EffectTiming.ON_DAMAGE_PLAYER,
            condition=_self_source,
            target_kind="ally_base",
            min_targets=1,
            max_targets=2,
            optional=True,
            only_rested=True,
        ),
        build_effect(
            "refresh_targets",
            EffectTiming.ON_DAMAGE_FORCE,
            condition=_self_source,
            target_kind="ally_base",
            min_targets=1,
            max_targets=2,
            optional=True,
            only_rested=True,
        ),
    ),
    "blue_07_02_01_00": (
        build_effect(
            "move_to_base_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="enemy_minion_cost_at_most_4",
            min_targets=2,
            max_targets=2,
            max_cost=4,
            rested=True,
        ),
    ),
    "blue_08_02_01_00": (
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _aleshand_move_minion_mana_to_field,
            condition=_self_source,
            target_kind="ally_minion_base",
            min_targets=0,
            max_targets=3,
            optional=True,
        ),
        build_effect(
            "move_to_base_targets",
            EffectTiming.ON_ATTACK,
            condition=_self_source,
            target_kind="enemy_minion",
            rested=True,
        ),
    ),
    "blue_08_02_01_01": (
        build_effect(
            "move_to_base_targets",
            EffectTiming.ON_ATTACK,
            condition=_self_source_and_own_color_mana_at_least(Color.BLUE, 4),
            target_kind="enemy_minion_cost_at_least_6",
            min_cost=6,
            rested=True,
        ),
    ),
    "blue_05_02_01_01": (
        build_effect(
            "return_from_trash_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="trash_magic_cost_at_most_4",
        ),
    ),
    "colorless_02_02_01_01": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_DESTROY,
            target_kind="any_minion",
            all_targets=True,
            max_bp=300,
        ),
    ),
    "colorless_02_02_01_03": (
        build_effect(
            "stat_modifier_all",
            EffectTiming.ON_ATTACK,
            condition=_self_source,
            target_kind="ally_minion",
            bp_delta=100,
            duration="turn",
        ),
    ),
    "colorless_03_02_01_00": (
        build_effect("rest_self", EffectTiming.ON_SUMMON, condition=_self_source),
    ),
    "colorless_03_02_01_02": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="enemy_minion",
            max_dp=0,
        ),
    ),
    "colorless_04_02_01_00": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_ATTACK,
            condition=_self_source,
            target_kind="enemy_minion",
            all_targets=True,
            max_bp=200,
        ),
    ),
    "colorless_04_02_01_03": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="enemy_minion",
            color=Color.COLORLESS,
        ),
    ),
    "colorless_04_02_01_01": (
        build_effect(
            "look_top_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="top3_field_minion",
            top_n=3,
        ),
    ),
    "colorless_05_02_01_02": (
        build_effect(
            "create_tokens",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            amount=1,
            token_id="slime_block_token",
            name_jp="スライム・ブロック・トークン",
            color=Color.COLORLESS,
            cost=1,
            bp=300,
            dp=0,
        ),
    ),
    "colorless_04_02_01_05": (
        build_effect(
            "heal_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="owner_player_or_force",
        ),
    ),
    "colorless_05_02_01_01": (
        build_effect("heal_targets", EffectTiming.ON_DESTROY, target_kind="owner_player", amount=2),
    ),
    "colorless_05_02_01_04": (
        build_effect("heal_targets", EffectTiming.ON_SUMMON, condition=_self_source, target_kind="owner_player_and_forces"),
    ),
    "colorless_05_02_01_06": (
        build_effect(
            "discard_target_draw",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="hand_base_minion",
            amount=2,
            optional=True,
        ),
    ),
    "colorless_05_02_01_07": (
        build_effect("increase_movement_right", EffectTiming.ON_SUMMON, condition=_self_source),
        build_effect("increase_movement_right", EffectTiming.TURN_START, condition=_own_turn_start),
    ),
    "colorless_08_02_01_00": (
        build_effect("draw_until_hand_size", EffectTiming.ON_SUMMON, condition=_self_source, hand_size=4),
    ),
    "colorless_09_02_01_01": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="any_minion",
            all_targets=True,
            max_bp=500,
        ),
    ),
    "colorless_010_02_01_00": (
        EffectSpec(EffectTiming.ON_ATTACK, _alababaster_attack_player_damage, condition=_self_source),
    ),
    "green_01_03_01_00": (
        build_effect("heal_targets", EffectTiming.ON_CAST_MAGIC, target_kind="owner_player"),
    ),
    "green_04_03_01_00": (
        build_effect(
            "rest_targets",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="any_minion_or_force",
            min_targets=0,
            max_targets=2,
            optional=True,
            lock_until_next_refresh_on_own_turn=True,
        ),
    ),
    "green_08_02_01_00": (
        build_effect(
            "rest_targets",
            EffectTiming.ON_ATTACK,
            target_kind="enemy_minion",
            all_targets=True,
            max_cost=4,
        ),
        build_effect(
            "heal_targets",
            EffectTiming.TURN_END,
            condition=_own_turn_end_and_color_mana_at_least(Color.GREEN, 4),
            target_kind="owner_player",
            amount=1,
        ),
    ),
    "purple_01_03_01_00": (
        build_effect("destroy_targets", EffectTiming.ON_CAST_MAGIC, target_kind="any_minion", max_cost=3),
    ),
    "purple_02_02_01_00": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_DESTROY,
            target_kind="enemy_minion",
            bp_delta=-200,
            dp_delta=-1,
            duration="turn",
        ),
    ),
    "purple_03_02_01_00": (
        EffectSpec(EffectTiming.ON_ATTACK, _crimson_mail_force_attack_dp, condition=_self_source),
    ),
    "purple_03_02_01_01": (
        EffectSpec(
            EffectTiming.ON_DAMAGE_FORCE,
            _catherine_purple_force_destroy_reward,
            condition=_catherine_purple_force_destroy_condition,
        ),
    ),
    "purple_08_03_01_00": (
        build_effect("destroy_targets", EffectTiming.ON_CAST_MAGIC, target_kind="any_minion", all_targets=True),
    ),
    "purple_08_02_01_01": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_ATTACK,
            condition=_own_color_mana_at_least(Color.PURPLE, 4),
            target_kind="enemy_minion_cost_at_most_4",
        ),
    ),
    "red_02_03_01_00": (
        build_effect("block_life_gain_and_damage_reduction", EffectTiming.ON_CAST_MAGIC),
        build_effect("draw_cards", EffectTiming.ON_CAST_MAGIC, amount=1),
    ),
    "red_03_02_01_01": (
        build_effect("draw_cards", EffectTiming.ON_ATTACK, condition=_attacking_player, amount=1),
    ),
    "red_04_02_01_00": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="enemy_minion",
            bp_delta=-300,
            duration="turn",
        ),
    ),
    "red_05_03_01_00": (
        build_effect(
            "create_tokens",
            EffectTiming.ON_CAST_MAGIC,
            amount=2,
            token_id="s_golem_token",
            name_jp="S・ゴレイム・トークン",
            color=Color.RED,
            cost=1,
            bp=100,
            dp=1,
        ),
    ),
    "red_06_02_01_00": (
        build_effect(
            "create_tokens",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            amount=2,
            token_id="s_golem_token",
            name_jp="S・ゴレイム・トークン",
            color=Color.RED,
            cost=1,
            bp=100,
            dp=1,
        ),
    ),
    "red_08_02_01_00": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_source_and_own_color_mana_at_least(Color.RED, 4),
            target_kind="enemy_minion",
            bp_delta=-600,
            duration="turn",
        ),
    ),
    "red_09_02_01_00": (
        build_effect(
            "create_tokens",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            amount=2,
            token_id="s_golem_token",
            name_jp="S・ゴレイム・トークン",
            color=Color.RED,
            cost=1,
            bp=100,
            dp=1,
            optional=True,
        ),
        EffectSpec(EffectTiming.ON_ATTACK, _arondai_mark_player_attack, condition=_arondai_attacking_enemy_player),
    ),
    "red_04_03_01_00": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion",
            bp_delta=-600,
            duration="turn",
        ),
    ),
    "red_07_02_01_00": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="enemy_minion",
            min_targets=2,
            max_targets=2,
            bp_delta=-400,
            duration="turn",
        ),
    ),
    "white_01_02_01_00": (
        build_effect("heal_targets", EffectTiming.ON_SUMMON, condition=_self_source, target_kind="ally_force"),
    ),
    "white_03_03_01_00": (
        build_effect("heal_targets", EffectTiming.ON_CAST_MAGIC, target_kind="owner_forces"),
        build_effect("prevent_force_damage", EffectTiming.ON_CAST_MAGIC, amount=1),
    ),
    "white_05_02_01_00": (
        build_effect("draw_cards", EffectTiming.ON_BATTLE_WIN, condition=_self_source, amount=1),
    ),
    "white_05_03_01_00": (
        build_effect(
            "destroy_targets",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion",
            all_targets=True,
            max_cost=3,
        ),
    ),
    "white_06_02_01_00": (
        build_effect("refresh_self", EffectTiming.ON_BATTLE_WIN, condition=_self_source_on_own_turn),
    ),
    "yellow_03_03_01_00": (
        build_effect("refresh_targets", EffectTiming.ON_CAST_MAGIC, target_kind="any_minion"),
    ),
    "yellow_02_03_01_00": (
        build_effect(
            "return_to_hand",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="any_minion",
            max_cost=4,
        ),
    ),
    "yellow_04_02_01_01": (
        build_effect("return_self_to_hand", EffectTiming.TURN_END, condition=_own_turn_end_with_other_minion),
    ),
    "yellow_05_02_01_00": (
        build_effect(
            "refresh_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="ally_minion_cost_at_most_4",
            max_cost=4,
        ),
    ),
    "yellow_05_03_01_00": (
        build_effect("draw_cards", EffectTiming.ON_CAST_MAGIC, amount=2),
        EffectSpec(EffectTiming.ON_CAST_MAGIC, _schedule_refresh_all_base_at_turn_end, condition=_self_source),
    ),
    "yellow_06_02_01_00": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="other_ally_minion",
            bp_delta=200,
            dp_delta=1,
            duration="turn",
        ),
    ),
    "yellow_08_02_01_01": (
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="ally_minion",
            bp_delta=300,
            dp_delta=1,
            duration="turn",
        ),
        build_effect(
            "return_to_hand",
            EffectTiming.ON_ATTACK,
            condition=_own_color_mana_at_least(Color.YELLOW, 4),
            target_kind="enemy_minion_cost_at_most_4",
        ),
    ),
    "colorless_05_02_01_03": (
        build_effect("draw_cards", EffectTiming.ON_CAST_MAGIC, condition=_own_magic_cast, amount=1),
    ),
    "colorless_07_02_01_02": (
        build_effect("discard_hand_draw", EffectTiming.ON_SUMMON, condition=_self_source, amount=5, scope="both"),
    ),
    "colorless_09_02_01_02": (
        build_effect(
            "exchange_player_force_life",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="ally_force",
            player_scope="opponent",
        ),
    ),
}


_EXTRA_AURAS_BY_ID = {
    "blue_01_02_01_00": _undine_magic_aura,
    "red_03_02_01_00": _diana_aura,
    "red_03_02_01_02": lambda source, target, state: _pc01_red_other_own_bp(source, target, state, 100),
    "red_03_02_01_03": _gleyg_smasher_aura,
    "colorless_01_02_01_00": _fearsome_pheasant_aura,
    "red_04_02_00_00": _sams_rush_dp_aura,
    "colorless_02_02_01_00": _dancing_cutlass_aura,
    "colorless_02_02_01_02": _boareater_aura,
    "colorless_03_02_01_05": _destroyed_own_force_aura,
    "colorless_04_02_00_04": _basic_howling_dire_aura,
    "purple_03_02_00_00": _basic_shadowhand_aura,
    "white_04_02_01_00": _white_opponent_turn_aura,
    "white_03_02_00_00": _basic_crabion_aura,
    "white_06_02_01_01": _force_count_self_aura,
    "purple_08_02_01_01": _destroyed_enemy_force_aura,
}


_EXTRA_KEYWORD_AURAS_BY_ID = {
    "red_05_02_01_00": _bankguys_rush_aura,
    "green_06_02_01_00": _riyabo_life_keyword_aura,
    "white_03_02_01_00": _audrey_reawaken_aura,
}


PC01_CARD_IDS = register_pc01_cards()
