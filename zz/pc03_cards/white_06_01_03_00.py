from __future__ import annotations

from typing import Any

from zz.enums import AreaType, AttackTargetKind
from zz.model import AttackTarget, CardInstance, ForceInstance
from zz.pc01 import _card_from_row

CARD_ID = "white_06_01_03_00"


def _attack_target_restricted(
    source: CardInstance,
    attacker: CardInstance,
    target: AttackTarget,
    state: Any,
) -> bool:
    return (
        source.area is AreaType.FIELD
        and state.active is not source.owner
        and attacker.owner is state.active
        and attacker.owner is not source.owner
        and target.kind is AttackTargetKind.FORCE
        and isinstance(target.ref, ForceInstance)
        and target.ref.owner is source.owner
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    # The shared combat path consumes this predicate before offering and revalidates after target selection.
    card.attack_target_restriction = _attack_target_restricted
    return card
