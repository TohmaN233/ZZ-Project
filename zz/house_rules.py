"""House rules used by the MVP.

HR2: 後攻 mana color swap (applied in engine.legal_actions when streak >= 2).
"""


def apply_swap_mana_color(engine, base_card_iid: int, new_color):
    """Change one colorless base mana to a color, consuming the current mana phase."""
    from zz.engine import IllegalActionError
    from zz.enums import Color, Step

    active = engine.state.active
    for ci in active.base:
        if ci.iid == base_card_iid:
            if engine._mana_color_of(ci) is not Color.COLORLESS:
                raise IllegalActionError("only colorless mana can be swapped")
            if new_color is Color.COLORLESS:
                raise IllegalActionError("swap mana color must choose a non-colorless color")
            ci.mana_color_override = new_color
            active.colorless_only_streak = 0
            if engine.state.step is Step.MANA:
                engine.advance_from_mana()
            return
    raise IllegalActionError(f"no base card with iid={base_card_iid}")
