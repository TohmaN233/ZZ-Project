from enum import Enum, auto


class Color(Enum):
    COLORLESS = 0
    RED = 1
    YELLOW = 2
    WHITE = 3
    GREEN = 4
    BLUE = 5
    PURPLE = 6


class CardType(Enum):
    F_MINION   = "f_minion"     # フィールド・ミニオン
    B_MINION   = "b_minion"     # ベース・ミニオン
    MAGIC      = "magic"
    MANA_TOKEN = "mana_token"   # placed by 無色マナの配置 action


class AreaType(Enum):
    DECK   = "deck"
    HAND   = "hand"
    BASE   = "base"
    FIELD  = "field"
    FORCE  = "force"
    TRASH  = "trash"
    REMOVED = "removed"   # 無色マナ destroyed go here (out of game)


class Phase(Enum):
    STANDBY = "standby"
    MANA    = "mana"
    MAIN    = "main"
    END     = "end"


class Step(Enum):
    START   = "start"
    REFRESH = "refresh"
    DRAW    = "draw"
    MANA    = "mana"
    MAIN    = "main"
    END     = "end"
    FLASH   = "flash"   # sub-state of attack sequence


class Keyword(Enum):
    REAWAKEN = auto()
    RUSH = auto()
    REACTIVE = auto()
    PENETRATE = auto()
    FLYING = auto()
    SNEAKING = auto()
    DEATH_BLOW = auto()
    COOPERATION = auto()
    BLESS = auto()
    COST_REDUCTION = auto()
    CANNOT_BLOCK = auto()
    KAGO = auto()             # 加護 (surfaced from Siren; no Aguma card uses it)
    UNBLOCKABLE = auto()


class TriggerTiming(Enum):
    ON_PLAY     = "on_play"      # 配置時
    ON_DESTROY  = "on_destroy"   # 破壊時
    TURN_START  = "turn_start"
    TURN_ON     = "turn_on"
    TURN_ENEMY  = "turn_enemy"
    TURN_END    = "turn_end"
    ON_ATTACK   = "on_attack"    # アタック時
    ON_BLOCK    = "on_block"
    MOVE_BACK   = "move_back"    # ベースに戻る時
    ON_MOVE_TO_FIELD = "on_move_to_field"  # for Siren's "minion mana moves to field"


class AttackTargetKind(Enum):
    PLAYER = "player"
    FORCE  = "force"
    MINION = "minion"


class Side(Enum):
    """Identity of a player slot, independent of name."""
    P1 = 0
    P2 = 1
