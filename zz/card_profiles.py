from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Mapping

from zz.enums import CardType, Color, Keyword


CARD_PROFILE_VERSION = "card_profile_v1"
CARD_TAXONOMY_VERSION = "card_taxonomy_v1_3"


REMOVAL_TEMPLATES = {
    "destroy_targets",
    "damage_targets",
    "return_to_hand",
    "move_to_base_targets",
    "rest_targets",
}
BUFF_TEMPLATES = {
    "stat_modifier",
    "stat_modifier_all",
    "grant_keyword",
    "refresh_targets",
    "heal_targets",
}
DRAW_TEMPLATES = {
    "draw_cards",
    "draw_until_hand_size",
    "discard_hand_draw",
    "discard_target_draw",
}
TRASH_RECURSION_TEMPLATES = {
    "return_from_trash_to_hand",
    "summon_from_trash",
}
SEARCH_TEMPLATES = {
    "look_top_to_hand",
    "search_deck_to_hand",
}
TOKEN_GENERATION_TEMPLATES = {
    "create_tokens",
}
BASE_DEVELOPMENT_TEMPLATES = {
    "place_base_from_deck",
    "place_base_from_hand",
}
MANA_RAMP_TEMPLATES = {
    "place_colorless_mana",
}
MOVEMENT_RANGE_TEMPLATES = {
    "increase_movement_right",
}
FIELD_TO_BASE_TEMPLATES = {
    "move_to_base_targets",
    "move_to_base_rested",
}
RETURN_TO_HAND_TEMPLATES = {
    "return_to_hand",
    "return_self_to_hand",
}
EVASION_TEMPLATES = {
    "grant_unblockable",
}
COMBAT_CONTROL_TEMPLATES = {
    "force_block",
}
SELF_REFRESH_TEMPLATES = {
    "refresh_self",
}
HAND_FILTER_TEMPLATES = {
    "discard_target_draw",
}


_COLORS = ("blue", "colorless", "green", "none", "purple", "red", "white", "yellow")
_CARD_TAXONOMY_VOCABULARY: dict[str, tuple[str, ...]] = {
    "identity:card_type": ("b_minion", "f_minion", "magic", "mana_token"),
    "identity:color": _COLORS,
    "identity:mana_color": _COLORS,
    "role": (
        "aura",
        "base_development",
        "base_to_field",
        "buff",
        "combat_control",
        "combat_payoff",
        "combo_piece",
        "color_fix",
        "death_payoff",
        "draw",
        "evasion",
        "field_self_refresh",
        "field_to_base",
        "finisher",
        "hand_filter",
        "life_exchange",
        "mana_ramp",
        "mana_self_refresh",
        "movement_range",
        "removal",
        "return_to_hand",
        "search",
        "static_rule",
        "tempo_attacker",
        "token_generation",
        "trash_recursion",
    ),
    "target": (
        "any_target_unsafe_on_own",
        "beneficial",
        "can_choose_zero_targets",
        "enemy_preferred",
        "harmful",
        "own_preferred",
    ),
    "phase": (
        "defensive_reactive",
        "offensive_proactive",
        "setup_only",
    ),
    "risk": (
        "can_fizzle_without_targets",
        "cannot_block",
        "self_harm_effect",
        "self_stun",
        "target_value_sensitive",
    ),
    "cost": (
        "self_cost",
    ),
}

_REVIEWED_CARD_TAXONOMY_TAGS_V1_3: dict[str, tuple[str, ...]] = {
    "blue_02_02_00_00": ("role:buff",),
    "blue_03_02_01_01": ("phase:setup_only", "role:buff", "role:draw"),
    "blue_05_02_00_00": ("role:combat_payoff", "role:draw"),
    "blue_08_02_01_00": (
        "risk:self_harm_effect",
        "risk:target_value_sensitive",
        "role:base_to_field",
        "role:field_to_base",
        "role:removal",
        "target:can_choose_zero_targets",
        "target:enemy_preferred",
        "target:harmful",
        "target:own_preferred",
    ),
    "colorless_03_02_00_04": (
        "risk:can_fizzle_without_targets",
        "risk:target_value_sensitive",
        "role:color_fix",
        "target:own_preferred",
    ),
    "colorless_03_02_01_03": ("role:draw",),
    "colorless_03_02_01_06": ("role:combat_control",),
    "colorless_04_02_00_01": ("role:static_rule",),
    "colorless_04_02_01_02": ("role:combat_payoff",),
    "colorless_04_02_01_04": ("role:static_rule",),
    "colorless_05_02_01_05": ("role:static_rule",),
    "colorless_06_02_01_01": ("role:combat_payoff",),
    "colorless_06_02_01_03": ("role:static_rule",),
    "colorless_07_02_01_01": ("role:buff",),
    "colorless_08_02_01_01": ("role:combat_payoff",),
    "colorless_08_02_01_02": ("role:static_rule",),
    "green_03_02_01_00": ("role:combat_payoff",),
    "green_04_02_01_01": ("role:static_rule",),
    "purple_02_02_00_00": ("role:combat_control",),
    "purple_02_02_01_01": ("role:aura",),
    "purple_03_02_01_00": ("role:combat_payoff",),
    "purple_03_02_01_01": ("phase:setup_only", "role:buff", "role:draw"),
    "purple_04_02_01_00": ("role:static_rule",),
    "purple_05_02_01_00": ("role:combat_control",),
    "red_02_02_00_00": ("role:combat_payoff",),
    "red_02_03_01_00": ("phase:offensive_proactive", "role:draw"),
    "red_09_02_01_00": (
        "phase:setup_only",
        "role:buff",
        "role:token_generation",
        "target:can_choose_zero_targets",
    ),
    "white_01_03_01_00": ("phase:offensive_proactive", "role:buff"),
    "white_02_02_00_00": ("role:static_rule",),
    "white_02_03_00_00": (
        "phase:defensive_reactive",
        "risk:can_fizzle_without_targets",
        "risk:target_value_sensitive",
    ),
    "white_02_03_00_01": ("role:draw",),
    "white_03_03_01_00": (
        "phase:defensive_reactive",
        "risk:can_fizzle_without_targets",
        "risk:target_value_sensitive",
        "role:buff",
        "target:beneficial",
        "target:own_preferred",
    ),
    "white_04_02_01_01": ("role:static_rule",),
    "white_06_02_01_02": ("role:buff", "role:combat_payoff"),
    "white_08_02_01_00": ("role:combat_payoff", "role:static_rule"),
    "yellow_03_02_01_00": ("role:aura",),
    "yellow_03_02_01_02": ("phase:setup_only", "role:buff", "role:draw"),
    "yellow_04_02_01_02": ("role:aura",),
    "yellow_05_02_00_00": ("role:static_rule",),
}


@dataclass
class CardIdentity:
    card_id: str
    name_jp: str
    name_en: str
    card_type: str
    color: str
    cost_total: int
    bp: int
    dp: int
    mana_color: str


@dataclass
class TargetSemantics:
    harmful: bool = False
    beneficial: bool = False
    enemy_preferred: bool = False
    own_preferred: bool = False
    any_target_unsafe_on_own: bool = False
    can_choose_zero_targets: bool = False


@dataclass
class PhaseSemantics:
    own_turn_preferred: bool = False
    enemy_turn_preferred: bool = False
    offensive_proactive: bool = False
    defensive_reactive: bool = False
    setup_only: bool = False
    own_turn_lockdown: bool = False


@dataclass
class ZoneValue:
    good_mana_card: bool = False
    poor_mana_card: bool = False
    protect_in_base: bool = False
    stay_field_as_blocker: bool = False
    usually_should_not_attack: bool = False


@dataclass
class TacticalRisks:
    cannot_block: bool = False
    self_stun: bool = False
    zero_dp_attacker: bool = False
    low_bp_attacker: bool = False
    self_harm_effect: bool = False
    can_fizzle_without_targets: bool = False
    target_value_sensitive: bool = False


@dataclass
class CardProfile:
    version: str
    identity: CardIdentity
    roles: tuple[str, ...] = field(default_factory=tuple)
    target_semantics: TargetSemantics = field(default_factory=TargetSemantics)
    phase_semantics: PhaseSemantics = field(default_factory=PhaseSemantics)
    zone_value: ZoneValue = field(default_factory=ZoneValue)
    tactical_risks: TacticalRisks = field(default_factory=TacticalRisks)

    def to_dict(self) -> dict:
        return asdict(self)


def build_card_profile(card) -> CardProfile:
    roles = _build_roles(card)
    target_semantics = _build_target_semantics(card, roles)
    own_turn_lockdown = _has_own_turn_rest_lockdown(card)
    phase_semantics = PhaseSemantics(
        own_turn_preferred=bool(getattr(card, "main_timing_ok", False)),
        enemy_turn_preferred=bool(
            getattr(card, "flash_timing_ok", False)
            and "defensive_flash" in roles
            and not own_turn_lockdown
        ),
        offensive_proactive=_is_offensive_proactive(card, roles),
        defensive_reactive="defensive_flash" in roles,
        setup_only=_is_setup_only(card, roles),
        own_turn_lockdown=own_turn_lockdown,
    )
    cost_total = sum(card.cost.values())
    zone_value = ZoneValue(
        good_mana_card=card.type == CardType.B_MINION or getattr(card, "mana_color", None) is not None,
        poor_mana_card=card.type == CardType.MAGIC and bool({"removal", "buff", "combo_piece"} & set(roles)),
        protect_in_base=("finisher" in roles or "combo_piece" in roles) and cost_total >= 4,
        stay_field_as_blocker=card.type in (CardType.F_MINION, CardType.B_MINION)
        and getattr(card, "bp", 0) >= 400
        and getattr(card, "dp", 0) <= 1,
        usually_should_not_attack=card.type in (CardType.F_MINION, CardType.B_MINION) and getattr(card, "dp", 0) == 0,
    )
    tactical_risks = TacticalRisks(
        cannot_block=Keyword.CANNOT_BLOCK in set(getattr(card, "keywords", []) or []),
        self_stun=any(
            str(getattr(effect, "template_id", "") or "") == "rest_self"
            for effect in getattr(card, "effects", []) or []
        ),
        zero_dp_attacker=card.type in (CardType.F_MINION, CardType.B_MINION) and getattr(card, "dp", 0) == 0,
        low_bp_attacker=card.type in (CardType.F_MINION, CardType.B_MINION)
        and getattr(card, "bp", 0) <= 200
        and getattr(card, "dp", 0) <= 1,
        self_harm_effect=target_semantics.harmful and target_semantics.own_preferred,
        can_fizzle_without_targets=_can_fizzle_without_targets(card, target_semantics),
        target_value_sensitive=any(effect.target_kind is not None for effect in getattr(card, "effects", [])),
    )

    return CardProfile(
        version=CARD_PROFILE_VERSION,
        identity=CardIdentity(
            card_id=card.id,
            name_jp=card.name_jp,
            name_en=card.name_en,
            card_type=card.type.value,
            color=_primary_color(card),
            cost_total=cost_total,
            bp=card.bp,
            dp=card.dp,
            mana_color=_color_name(getattr(card, "mana_color", None)) or "",
        ),
        roles=roles,
        target_semantics=target_semantics,
        phase_semantics=phase_semantics,
        zone_value=zone_value,
        tactical_risks=tactical_risks,
    )


def build_card_profiles(cards: Mapping[str, object]) -> dict[str, CardProfile]:
    return {
        card_id: build_card_profile(card)
        for card_id, card in cards.items()
    }


def card_taxonomy_vocabulary() -> dict[str, tuple[str, ...]]:
    """Return the stable multi-label card taxonomy vocabulary."""
    return {
        namespace: tuple(labels)
        for namespace, labels in _CARD_TAXONOMY_VOCABULARY.items()
    }


def card_profile_tags(profile: CardProfile) -> tuple[str, ...]:
    """Return sorted namespaced taxonomy tags for one card profile."""
    tags: list[str] = [
        f"identity:card_type:{profile.identity.card_type}",
        f"identity:color:{_taxonomy_identity_value(profile.identity.color)}",
        f"identity:mana_color:{_taxonomy_identity_value(profile.identity.mana_color)}",
    ]
    tags.extend(f"role:{role}" for role in _taxonomy_role_labels(profile))
    tags.extend(_active_vocabulary_bool_tags("target", profile.target_semantics))
    tags.extend(_active_vocabulary_bool_tags("phase", profile.phase_semantics))
    tags.extend(_active_vocabulary_bool_tags("risk", profile.tactical_risks))
    return _apply_reviewed_card_taxonomy_tags(profile.identity.card_id, tuple(tags))


def card_profile_taxonomy(profile: CardProfile) -> dict[str, Any]:
    """Return a JSON-friendly taxonomy view without changing CardProfile."""
    tags = card_profile_tags(profile)
    return {
        "taxonomyVersion": CARD_TAXONOMY_VERSION,
        "cardProfileVersion": profile.version,
        "identity": {
            "card_type": profile.identity.card_type,
            "color": _taxonomy_identity_value(profile.identity.color),
            "mana_color": _taxonomy_identity_value(profile.identity.mana_color),
        },
        "roles": list(_taxonomy_labels_from_tags(tags, "role")),
        "target": list(_taxonomy_labels_from_tags(tags, "target")),
        "phase": list(_taxonomy_labels_from_tags(tags, "phase")),
        "risk": list(_taxonomy_labels_from_tags(tags, "risk")),
        "tags": list(tags),
    }


def validate_card_taxonomy_tags(tags: tuple[str, ...] | list[str]) -> list[str]:
    """Return validation errors for tags not covered by the v1 vocabulary."""
    vocabulary = card_taxonomy_vocabulary()
    errors: list[str] = []
    for tag in tags:
        parsed = _parse_taxonomy_tag(str(tag))
        if parsed is None:
            errors.append(f"malformed taxonomy tag: {tag!r}")
            continue
        namespace, label = parsed
        allowed = vocabulary.get(namespace)
        if allowed is None:
            errors.append(f"unknown taxonomy namespace: {namespace!r}")
        elif label not in allowed:
            errors.append(f"unknown taxonomy label for {namespace!r}: {label!r}")
    return errors


def validate_card_profile_taxonomy(profile: CardProfile) -> list[str]:
    return validate_card_taxonomy_tags(card_profile_tags(profile))


def build_card_taxonomy_review_items(cards: Mapping[str, object]) -> list[dict[str, Any]]:
    """List effects/keywords that need human taxonomy review."""
    items: list[dict[str, Any]] = []
    for registry_id, card in sorted(cards.items(), key=lambda item: str(item[0])):
        card_id = str(getattr(card, "id", registry_id))
        if _has_reviewed_card_taxonomy_tags(card_id):
            continue
        profile = build_card_profile(card)
        taxonomy = card_profile_taxonomy(profile)
        card_info = {
            "registryId": str(registry_id),
            "cardId": card_id,
            "cardNameJp": str(getattr(card, "name_jp", "")),
            "cardNameEn": str(getattr(card, "name_en", "")),
            "effectTextJp": str(getattr(card, "ability_jp", "") or ""),
            "effectTextEn": str(getattr(card, "ability_en", "") or ""),
            "currentRoles": list(taxonomy["roles"]),
            "currentTags": [
                tag for tag in taxonomy["tags"]
                if not tag.startswith("identity:")
            ],
        }
        for effect in getattr(card, "effects", []) or []:
            if _effect_taxonomy_candidates(effect, card):
                continue
            items.append({
                **card_info,
                "source": "effect",
                "effect": _effect_description(effect),
                "options": list(_review_options_for_effect(effect, card)),
            })
        for keyword in getattr(card, "keywords", []) or []:
            if _keyword_taxonomy_candidates(keyword):
                continue
            items.append({
                **card_info,
                "source": "keyword",
                "effect": f"keyword:{_keyword_name(keyword)}",
                "options": list(_review_options_for_keyword(keyword)),
            })
        for trigger in getattr(card, "triggers", []) or []:
            items.append({
                **card_info,
                "source": "legacy_trigger",
                "effect": _trigger_description(trigger),
                "options": list(_review_options_for_trigger(trigger, card)),
            })
    return items


def build_card_taxonomy_inventory(cards: Mapping[str, object]) -> dict[str, Any]:
    """Build a deterministic taxonomy inventory for a card mapping."""
    profiles = build_card_profiles(cards)
    card_rows: dict[str, dict[str, Any]] = {}
    validation_errors: list[str] = []
    tag_counts_by_namespace: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    cards_with_multiple_roles = 0
    cards_without_roles = 0

    for registry_id, profile in sorted(profiles.items(), key=lambda item: str(item[0])):
        taxonomy = card_profile_taxonomy(profile)
        tags = list(taxonomy["tags"])
        errors = validate_card_taxonomy_tags(tags)
        validation_errors.extend(
            f"{registry_id}: {error}"
            for error in errors
        )
        roles = list(taxonomy["roles"])
        if len(roles) > 1:
            cards_with_multiple_roles += 1
        if not roles:
            cards_without_roles += 1
        for role in roles:
            role_counts[role] = role_counts.get(role, 0) + 1
        for tag in tags:
            parsed = _parse_taxonomy_tag(tag)
            if parsed is None:
                continue
            namespace, _label = parsed
            tag_counts_by_namespace[namespace] = tag_counts_by_namespace.get(namespace, 0) + 1
        card_rows[str(registry_id)] = {
            "registryId": str(registry_id),
            "cardId": profile.identity.card_id,
            "nameJp": profile.identity.name_jp,
            "nameEn": profile.identity.name_en,
            "taxonomy": taxonomy,
            "tags": tags,
        }

    return {
        "taxonomyVersion": CARD_TAXONOMY_VERSION,
        "cardProfileVersion": CARD_PROFILE_VERSION,
        "totalCards": len(card_rows),
        "vocabulary": {
            namespace: list(labels)
            for namespace, labels in card_taxonomy_vocabulary().items()
        },
        "summary": {
            "cardsWithMultipleRoles": cards_with_multiple_roles,
            "cardsWithoutRoles": cards_without_roles,
            "tagCountsByNamespace": dict(sorted(tag_counts_by_namespace.items())),
            "roleCounts": dict(sorted(role_counts.items())),
        },
        "cards": card_rows,
        "validationErrors": validation_errors,
    }


def _taxonomy_identity_value(value: str | None) -> str:
    return value if value else "none"


def _taxonomy_role_labels(profile: CardProfile) -> tuple[str, ...]:
    allowed = set(_CARD_TAXONOMY_VOCABULARY["role"])
    return tuple(
        role
        for role in profile.roles
        if role in allowed
    )


def _apply_reviewed_card_taxonomy_tags(card_id: str, tags: tuple[str, ...]) -> tuple[str, ...]:
    reviewed_tags = _REVIEWED_CARD_TAXONOMY_TAGS_V1_3.get(card_id)
    if reviewed_tags is None:
        return tuple(sorted(set(tags)))
    identity_tags = {
        tag
        for tag in tags
        if tag.startswith("identity:")
    }
    return tuple(sorted(identity_tags | set(reviewed_tags)))


def _has_reviewed_card_taxonomy_tags(card_id: str) -> bool:
    return card_id in _REVIEWED_CARD_TAXONOMY_TAGS_V1_3


def _taxonomy_labels_from_tags(tags: tuple[str, ...], namespace: str) -> tuple[str, ...]:
    return tuple(
        label
        for tag in tags
        for parsed in [_parse_taxonomy_tag(tag)]
        if parsed is not None
        for parsed_namespace, label in [parsed]
        if parsed_namespace == namespace
    )


def _active_bool_fields(instance: object) -> tuple[str, ...]:
    return tuple(
        field_info.name
        for field_info in fields(instance)
        if bool(getattr(instance, field_info.name))
    )


def _active_vocabulary_bool_labels(namespace: str, instance: object) -> tuple[str, ...]:
    allowed = set(_CARD_TAXONOMY_VOCABULARY.get(namespace, ()))
    return tuple(
        name
        for name in _active_bool_fields(instance)
        if name in allowed
    )


def _active_vocabulary_bool_tags(namespace: str, instance: object) -> tuple[str, ...]:
    return tuple(
        f"{namespace}:{name}"
        for name in _active_vocabulary_bool_labels(namespace, instance)
    )


def _parse_taxonomy_tag(tag: str) -> tuple[str, str] | None:
    parts = tag.split(":")
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) == 3 and parts[0] == "identity":
        return f"{parts[0]}:{parts[1]}", parts[2]
    return None


def _effect_role_candidates(effect: object, card: object | None = None) -> set[str]:
    template_id = str(getattr(effect, "template_id", "") or "")
    roles: set[str] = set()
    if template_id in REMOVAL_TEMPLATES:
        roles.add("removal")
    if template_id in BUFF_TEMPLATES:
        roles.add("buff")
    if template_id in DRAW_TEMPLATES:
        roles.add("draw")
    if template_id in TRASH_RECURSION_TEMPLATES:
        roles.update({"combo_piece", "trash_recursion"})
    if template_id in SEARCH_TEMPLATES:
        roles.add("search")
    if template_id in TOKEN_GENERATION_TEMPLATES:
        roles.add("token_generation")
    if template_id in BASE_DEVELOPMENT_TEMPLATES:
        roles.add("base_development")
    if template_id in MANA_RAMP_TEMPLATES:
        roles.add("mana_ramp")
    if template_id in MOVEMENT_RANGE_TEMPLATES:
        roles.add("movement_range")
    if template_id in FIELD_TO_BASE_TEMPLATES:
        roles.add("field_to_base")
    if template_id in RETURN_TO_HAND_TEMPLATES:
        roles.add("return_to_hand")
    if template_id in EVASION_TEMPLATES:
        roles.update({"buff", "evasion"})
    if template_id in COMBAT_CONTROL_TEMPLATES:
        roles.add("combat_control")
    if template_id in SELF_REFRESH_TEMPLATES:
        roles.add(_self_refresh_role(effect, card))
    if template_id in HAND_FILTER_TEMPLATES:
        roles.add("hand_filter")
    if template_id == "exchange_player_force_life":
        roles.update({"combo_piece", "life_exchange"})
    if _effect_timing_value(effect) == "on_destroy":
        roles.add("death_payoff")
    return roles


def _keyword_role_candidates(keyword: object) -> set[str]:
    if keyword == Keyword.RUSH:
        return {"tempo_attacker"}
    if keyword == Keyword.REAWAKEN:
        return {"field_self_refresh"}
    if keyword in {Keyword.FLYING, Keyword.SNEAKING, Keyword.UNBLOCKABLE}:
        return {"evasion"}
    if keyword == Keyword.PENETRATE:
        return {"finisher"}
    if keyword == Keyword.REACTIVE:
        return {"defensive_flash"}
    return set()


def _effect_taxonomy_candidates(effect: object, card: object | None = None) -> set[str]:
    tags = {f"role:{role}" for role in _effect_role_candidates(effect, card)}
    if str(getattr(effect, "template_id", "") or "") == "rest_self":
        tags.update({"cost:self_cost", "risk:self_stun"})
    return tags


def _keyword_taxonomy_candidates(keyword: object) -> set[str]:
    allowed_roles = set(_CARD_TAXONOMY_VOCABULARY["role"])
    tags = {
        f"role:{role}"
        for role in _keyword_role_candidates(keyword)
        if role in allowed_roles
    }
    if keyword == Keyword.REACTIVE:
        tags.add("phase:defensive_reactive")
    if keyword == Keyword.CANNOT_BLOCK:
        tags.add("risk:cannot_block")
    return tags


def _build_roles(card) -> tuple[str, ...]:
    roles: set[str] = set()
    for effect in getattr(card, "effects", []):
        roles.update(_effect_role_candidates(effect, card))

    keywords = set(getattr(card, "keywords", []))
    for keyword in keywords:
        roles.update(_keyword_role_candidates(keyword))
    if (card.type == CardType.MAGIC and getattr(card, "flash_timing_ok", False)) or Keyword.REACTIVE in keywords:
        roles.add("defensive_flash")

    return tuple(sorted(roles))


def _build_target_semantics(card, roles: tuple[str, ...]) -> TargetSemantics:
    semantics = TargetSemantics(
        harmful="removal" in roles,
        beneficial="buff" in roles,
    )

    for effect in getattr(card, "effects", []):
        target_kind = effect.target_kind or ""
        if effect.optional or effect.min_targets == 0:
            semantics.can_choose_zero_targets = True
        if "enemy" in target_kind or "opponent" in target_kind:
            semantics.enemy_preferred = True
        if "ally" in target_kind or "owner" in target_kind:
            semantics.own_preferred = True
        if target_kind.startswith("any_") and semantics.harmful:
            semantics.any_target_unsafe_on_own = True

    return semantics


def _can_fizzle_without_targets(card, target_semantics: TargetSemantics) -> bool:
    if target_semantics.can_choose_zero_targets:
        return False
    return any(
        (effect.target_kind is not None and effect.min_targets > 0)
        for effect in getattr(card, "effects", [])
    )


def _is_setup_only(card, roles: tuple[str, ...]) -> bool:
    setup_roles = {
        "base_development",
        "color_fix",
        "combo_piece",
        "draw",
        "hand_filter",
        "mana_ramp",
        "search",
        "token_generation",
    }
    return bool(setup_roles & set(roles))


def _is_offensive_proactive(card, roles: tuple[str, ...]) -> bool:
    if getattr(card, "type", None) != CardType.MAGIC:
        return False
    if not (getattr(card, "main_timing_ok", False) or getattr(card, "flash_timing_ok", False)):
        return False
    proactive_roles = {"buff", "combat_control", "removal"}
    if proactive_roles & set(roles):
        return True
    return _has_bp_or_dp_gain_text(card)


def _has_bp_or_dp_gain_text(card: object) -> bool:
    text_parts = [
        str(getattr(card, "ability_jp", "") or ""),
        str(getattr(card, "ability_en", "") or ""),
    ]
    for effect in getattr(card, "effects", []) or []:
        text_parts.extend([
            str(getattr(effect, "official_timing", "") or ""),
            str(getattr(effect, "official_effect", "") or ""),
        ])
    text = " ".join(text_parts).lower()
    return any(
        marker in text
        for marker in (
            "bp+",
            "dp+",
            "bp＋",
            "dp＋",
            "gains +",
            "gain +",
        )
    )


def _has_own_turn_rest_lockdown(card) -> bool:
    return any(
        str(getattr(effect, "template_id", "") or "") == "rest_targets"
        and bool((getattr(effect, "params", {}) or {}).get("lock_until_next_refresh_on_own_turn"))
        for effect in getattr(card, "effects", []) or []
    )


def _review_options_for_effect(effect: object, card: object | None = None) -> tuple[str, ...]:
    template_id = str(getattr(effect, "template_id", "") or "")
    target_kind = str(getattr(effect, "target_kind", "") or "")
    timing = _effect_timing_value(effect)
    options: list[str] = []
    if template_id == "rest_self":
        options.extend(["cost:self_cost", "risk:self_stun"])
    if "enemy" in target_kind or "opponent" in target_kind:
        options.extend(["role:removal", "role:combat_control"])
    if "ally" in target_kind or "owner" in target_kind:
        options.append("role:buff")
    if "deck" in target_kind or target_kind.startswith("top"):
        options.append("role:search")
    if "trash" in target_kind:
        options.extend(["role:trash_recursion", "role:combo_piece"])
    if "ally_minion_base" in target_kind:
        options.append("role:base_to_field")
    if "base" in target_kind:
        options.append("role:base_development")
    if "mana" in target_kind:
        options.append("role:mana_ramp")
    if "colorless_mana" in target_kind or "color" in target_kind:
        options.append("role:color_fix")
    if timing in {"on_attack", "on_battle_win", "on_damage_player", "on_damage_force"}:
        options.extend(["role:combat_payoff", "role:buff", "role:removal"])
    if timing == "continuous":
        options.extend(_review_options_for_continuous_effect(effect, card))
    if timing == "on_summon":
        options.extend(["role:buff", "role:search", "role:token_generation", "role:base_development"])
    if timing == "on_cast_magic":
        options.extend([
            "role:buff",
            "role:removal",
            "role:draw",
            "role:base_development",
            "role:mana_ramp",
            "role:color_fix",
            "phase:offensive_proactive",
            "phase:defensive_reactive",
        ])
    options.extend(["manual:no_role", "manual:needs_card_text"])
    return tuple(dict.fromkeys(options))


def _review_options_for_continuous_effect(effect: object, card: object | None = None) -> tuple[str, ...]:
    text = _card_effect_review_text(effect, card)
    if _looks_like_static_rule_text(text):
        return ("role:static_rule",)
    if _looks_like_aura_text(text):
        return ("role:aura",)
    return ("role:aura", "role:static_rule")


def _card_effect_review_text(effect: object, card: object | None = None) -> str:
    parts = [
        str(getattr(effect, "official_timing", "") or ""),
        str(getattr(effect, "official_effect", "") or ""),
    ]
    if card is not None:
        parts.extend([
            str(getattr(card, "ability_jp", "") or ""),
            str(getattr(card, "ability_en", "") or ""),
        ])
    return " ".join(parts).lower()


def _looks_like_static_rule_text(text: str) -> bool:
    if "【召喚時】" in text and ("2回" in text or "二回" in text or "twice" in text):
        return True
    return any(
        marker in text
        for marker in (
            "選択できない",
            "フリーコスト",
            "対象の数",
            "アタックできない",
            "ブロックできない",
            "ブロックも移動もできない",
            "必ずブロック",
            "cannot be selected",
            "cannot attack",
            "cannot block",
            "must block",
            "free cost",
        )
    )


def _looks_like_aura_text(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "bp+",
            "dp+",
            "bp＋",
            "dp＋",
            "gains +",
            "gain +",
        )
    )


def _review_options_for_keyword(keyword: object) -> tuple[str, ...]:
    keyword_name = _keyword_name(keyword)
    by_keyword = {
        "RUSH": ("role:tempo_attacker", "manual:no_role"),
        "REAWAKEN": ("role:field_self_refresh", "manual:no_role"),
        "DEATH_BLOW": ("role:combat_control", "role:removal", "manual:no_role"),
        "CANNOT_BLOCK": ("risk:cannot_block", "manual:no_role"),
        "COOPERATION": ("role:buff", "manual:no_role"),
        "BLESS": ("role:buff", "new_role:protection", "manual:no_role"),
        "KAGO": ("role:buff", "new_role:protection", "manual:no_role"),
        "COST_REDUCTION": ("new_role:cost_reduction", "manual:no_role"),
    }
    return by_keyword.get(keyword_name, ("manual:no_role", "manual:needs_card_text"))


def _review_options_for_trigger(trigger: object, card: object) -> tuple[str, ...]:
    timing = _trigger_timing_value(trigger)
    name = str(getattr(card, "name_en", "") or "").lower()
    options: list[str] = []
    if "arrow" in name or "strike" in name:
        options.append("role:removal")
    if "cry" in name:
        options.append("role:buff")
    if timing in {"on_play", "on_attack"}:
        options.extend(["role:buff", "role:removal"])
    options.extend(["manual:convert_to_effect_spec", "manual:no_role"])
    return tuple(dict.fromkeys(options))


def _self_refresh_role(effect: object, card: object | None) -> str:
    text_parts = [
        str(getattr(effect, "official_timing", "") or ""),
        str(getattr(effect, "official_effect", "") or ""),
    ]
    if card is not None:
        text_parts.extend([
            str(getattr(card, "ability_jp", "") or ""),
            str(getattr(card, "ability_en", "") or ""),
        ])
    text = " ".join(text_parts).lower()
    timing = _effect_timing_value(effect)
    card_type = getattr(card, "type", None)
    if any(
        marker in text
        for marker in (
            "《ベース》",
            "<base>",
            "this mana",
            "このマナ",
            "マナをアクティブ",
            "mana enters the active state",
        )
    ):
        return "mana_self_refresh"
    if card_type == CardType.B_MINION and timing in {"turn_end", "on_place_base", "move_to_base"}:
        return "mana_self_refresh"
    return "field_self_refresh"


def _effect_description(effect: object) -> str:
    template_id = str(getattr(effect, "template_id", None))
    timing = _effect_timing_value(effect)
    target_kind = str(getattr(effect, "target_kind", None))
    official_timing = str(getattr(effect, "official_timing", "") or "")
    official_effect = str(getattr(effect, "official_effect", "") or "")
    parts = [
        f"template:{template_id}",
        f"timing:{timing}",
        f"target:{target_kind}",
    ]
    if official_timing:
        parts.append(f"officialTiming:{official_timing}")
    if official_effect:
        parts.append(f"officialEffect:{official_effect}")
    return " | ".join(parts)


def _effect_timing_value(effect) -> str:
    timing = getattr(effect, "timing", None)
    return str(getattr(timing, "value", timing) or "")


def _trigger_timing_value(trigger: object) -> str:
    timing = getattr(trigger, "when", None)
    return str(getattr(timing, "value", timing) or "")


def _trigger_description(trigger: object) -> str:
    fn = getattr(trigger, "fn", None)
    callback_name = str(getattr(fn, "__name__", "") or "")
    description = f"trigger:{_trigger_timing_value(trigger)}"
    if callback_name:
        description += f" | callback:{callback_name}"
    return description


def _keyword_name(keyword: object) -> str:
    return str(getattr(keyword, "name", keyword) or "")


def _primary_color(card) -> str:
    mana_color = getattr(card, "mana_color", None)
    if mana_color is not None:
        return _color_name(mana_color) or ""
    cost = card.cost
    non_colorless = [
        color
        for color, amount in cost.items()
        if amount and color != Color.COLORLESS
    ]
    if non_colorless:
        return _color_name(sorted(non_colorless, key=lambda color: color.value)[0]) or ""
    if cost:
        return "colorless"
    return ""


def _color_name(color: Color | None) -> str | None:
    if color is None:
        return None
    return color.name.lower()
