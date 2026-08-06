from __future__ import annotations

import re


FILTER_GROUP_LABELS = {
    "cardtype": {"ja": "カード種別", "zh": "卡牌类型", "en": "Card Type"},
    "attribute": {"ja": "属性", "zh": "属性", "en": "Attribute"},
    "cost": {"ja": "コスト", "zh": "费用", "en": "Cost"},
    "series": {"ja": "シリーズ", "zh": "卡包", "en": "Series"},
    "race": {"ja": "種族", "zh": "种族", "en": "Race"},
    "reality": {"ja": "レアリティ", "zh": "稀有度", "en": "Rarity"},
    "dp": {"ja": "DP", "zh": "DP", "en": "DP"},
    "effect": {"ja": "キーワード能力", "zh": "关键词能力", "en": "Keyword Ability"},
    "effect_timing": {"ja": "効果タイミング", "zh": "效果时点", "en": "Effect Timing"},
    "conditions": {"ja": "条件", "zh": "条件", "en": "Condition"},
}


FILTER_OPTION_LABELS = {
    "cardtype": {
        "ベース・ミニオン": ("基地随从", "Base Minion"),
        "フィールド・ミニオン": ("战场随从", "Field Minion"),
        "マジック": ("魔法", "Magic"),
        "ミニオン・トークン": ("衍生随从", "Minion Token"),
    },
    "attribute": {
        "赤": ("红", "Red"),
        "黄": ("黄", "Yellow"),
        "白": ("白", "White"),
        "緑": ("绿", "Green"),
        "青": ("蓝", "Blue"),
        "紫": ("紫", "Purple"),
        "無色": ("无色", "Colorless"),
    },
    "series": {
        "EX:02 幻影の剣士": ("EX:02 幻影剑士", "EX:02 Phantom Swordsman"),
        "EX:01 魔術都市の9戦士": ("EX:01 魔术都市的九战士", "EX:01 Nine Warriors of the Magic City"),
        "ベーシック": ("基础", "Basic"),
    },
    "race": {
        "アーティスト": ("艺术家", "Artist"),
        "アームズ": ("武装", "Arms"),
        "アイテム": ("道具", "Item"),
        "アヴィアン": ("鸟族", "Avian"),
        "アルカナ": ("奥秘", "Arcana"),
        "アンデッド": ("不死族", "Undead"),
        "アンドロイド": ("人造人", "Android"),
        "ウイング": ("翼族", "Wing"),
        "エヴォーカー": ("召唤师", "Evoker"),
        "エルフ": ("精灵", "Elf"),
        "エンジェル": ("天使", "Angel"),
        "仮面": ("假面", "Mask"),
        "ガーディアン": ("守卫", "Guardian"),
        "カードバトラー": ("卡牌斗士", "Card Battler"),
        "キマイラ": ("奇美拉", "Chimera"),
        "黒の剣士": ("黑衣剑士", "Black Swordsman"),
        "コア": ("核心", "Core"),
        "ゴブリン": ("哥布林", "Goblin"),
        "ゴレイム": ("魔像", "Golem"),
        "シーワーム": ("海龙", "Sea Wyrm"),
        "ジャイアント": ("巨人", "Giant"),
        "ジュエリスト": ("珠宝师", "Jewelist"),
        "スケルトン": ("骷髅", "Skeleton"),
        "スプライト": ("妖精", "Sprite"),
        "絶剣": ("绝剑", "Absolute Sword"),
        "閃光": ("闪光", "Flash"),
        "セントール": ("半人马", "Centaur"),
        "ソード": ("剑", "Sword"),
        "ソルジャー": ("士兵", "Soldier"),
        "ダイナソー": ("恐龙", "Dinosaur"),
        "ツリーフォーク": ("树人", "Treefolk"),
        "デーモン": ("恶魔", "Demon"),
        "デミゴッド": ("半神", "Demigod"),
        "トライブ": ("部族", "Tribe"),
        "ドラゴニュート": ("龙人", "Dragonewt"),
        "ドラゴン": ("龙", "Dragon"),
        "ドワーフ": ("矮人", "Dwarf"),
        "ニンフ": ("宁芙", "Nymph"),
        "ハンター": ("猎人", "Hunter"),
        "ビースト": ("兽", "Beast"),
        "ヒューマノイド": ("人形", "Humanoid"),
        "氷剣": ("冰剑", "Ice Sword"),
        "ファイブスター": ("五星", "Five Star"),
        "フェニックス": ("凤凰", "Phoenix"),
        "マーフォーク": ("人鱼", "Merfolk"),
        "モルフェオ": ("莫尔菲奥", "Morpheo"),
        "モンスター": ("怪物", "Monster"),
        "ラット": ("鼠", "Rat"),
        "レギオン": ("军团", "Legion"),
        "光導": ("光导", "Astral"),
    },
    "effect": {
        "襲撃": ("袭击", "Assault"),
        "飛来": ("飞来", "Flying"),
        "再起": ("再起", "Reawaken"),
        "貫通": ("贯通", "Pierce"),
        "潜入": ("潜入", "Infiltrate"),
        "奪命": ("夺命", "Lethal"),
        "連携": ("连携", "Link"),
        "加護": ("加护", "Blessing"),
        "変形": ("变形", "Transform"),
        "大変身": ("大变身", "Mega Morph"),
        "スイッチ": ("切换", "Switch"),
        "進化": ("进化", "Evolve"),
        "コスト軽減": ("费用减免", "Cost Reduction"),
    },
    "conditions": {
        "デッキ": ("卡组", "Deck"),
        "ベース": ("基地", "Base"),
        "トラッシュ": ("废弃区", "Trash"),
        "付与能力": ("赋予能力", "Granted Ability"),
    },
}


TIMING_LABELS = {
    "メイン": ("主要阶段", "Main"),
    "フラッシュ": ("Flash", "Flash"),
    "自分のターン": ("自己回合", "On Your Turn"),
    "自分のマナフェイズ": ("自己的 Mana 阶段", "During Your Mana Phase"),
    "自分のターン終了時": ("自己回合结束时", "At the End of Your Turn"),
    "自分のターン開始時": ("自己回合开始时", "At the Start of Your Turn"),
    "アタック時": ("攻击时", "When Attacking"),
    "ブロック時": ("阻挡时", "When Blocking"),
    "相手のターン": ("对手回合", "On the Opponent's Turn"),
    "召喚時": ("召唤时", "When Summoned"),
    "常時": ("常时", "Passive"),
    "進撃時": ("进击时", "When Advancing"),
    "配置時": ("配置时", "When Placed"),
    "後退時": ("后退时", "When Retreating"),
    "破壊時": ("破坏时", "When Destroyed"),
    "加護時": ("加护时", "When Blessed"),
    "変形時": ("变形时", "When Transforming"),
    "変身時": ("变身时", "When Morphing"),
}


def filter_group_labels(group: str) -> dict[str, str]:
    labels = FILTER_GROUP_LABELS.get(group)
    if labels is None:
        raise ValueError(f"missing filter group localization: {group}")
    return {"labelJp": labels["ja"], "labelZh": labels["zh"], "labelEn": labels["en"]}


def filter_option_labels(group: str, value: str, label: str) -> dict[str, str]:
    jp = label or value
    if group in {"cost", "reality", "dp"} or _ascii_only(jp):
        zh = en = jp
    elif group == "effect_timing":
        zh, en = _timing_translation(jp)
    else:
        localized = FILTER_OPTION_LABELS.get(group, {}).get(jp)
        if localized is None:
            raise ValueError(f"missing filter option localization: {group}={jp}")
        zh, en = localized
    return {"labelJp": jp, "labelZh": zh, "labelEn": en}


def _timing_translation(value: str) -> tuple[str, str]:
    direct = TIMING_LABELS.get(value)
    if direct is not None:
        return direct
    parts = re.split(r"\s*(&|/)\s*", value)
    if len(parts) <= 1:
        raise ValueError(f"missing effect timing localization: {value}")
    zh_parts: list[str] = []
    en_parts: list[str] = []
    for part in parts:
        if part in {"&", "/"}:
            separator = f" {part} "
            zh_parts.append(separator)
            en_parts.append(separator)
            continue
        localized = TIMING_LABELS.get(part)
        if localized is None:
            raise ValueError(f"missing effect timing localization: {value}")
        zh_parts.append(localized[0])
        en_parts.append(localized[1])
    return "".join(zh_parts), "".join(en_parts)


def _ascii_only(value: str) -> bool:
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True
