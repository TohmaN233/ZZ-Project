# ZENONZARD Rulebook - English Edition

This document defines the basic rules used by the current ZZ Clone. Card-specific rulings follow the card text. Identical Japanese rules expressions always have the same rules meaning.

## 1. Objective

Each player battles with a 40-card deck and two Forces. You win by reducing the opposing player's life to 0 or less, or when that player must draw during their draw step while their deck is empty.

Forces have continuous or triggered abilities that protect their player. Card and keyword effects may allow a player to be attacked directly even while that player still controls a Force.

## 2. Cards and Zones

| Type | Description |
| --- | --- |
| Field Minion | A Minion summoned to the Field after its cost is paid. It can attack, block, and move. |
| Base Minion | A Minion mainly placed in the Base as Mana. It can move to the Field by spending movement. |
| Magic | A card placed in the Trash after its cost is paid and its effect resolves. |
| Colorless Mana | A non-card Mana token placed in the Base and used to pay costs. |
| Force | A permanent card selected separately from the deck. It has life and abilities. |

The main zones are Deck, Hand, Field, Base, Trash, Exile, and Force. Only Minions in the Field or Base have an active or rested state. Cards in the Hand, Deck, or Trash do not.

## 3. Core Terms

| Term | Meaning |
| --- | --- |
| BP | Battle power compared during combat between Minions. BP cannot be lower than 0. |
| DP | Damage dealt to a player or Force. DP cannot be lower than 0. |
| Cost | The amount of Mana required to play a card, including colored and free costs. |
| Colored cost | A cost that must be paid with Mana of the corresponding color. |
| Free cost | A cost that may be paid with Mana of any color or with colorless Mana. |
| Active | The upright state in which a card can act. |
| Rested | The sideways state after acting or being used to pay a cost. |
| Movement | The number of times Minions may move between Base and Field during a turn. |
| Minion Mana | A Minion card in the Base. Colorless Mana tokens are not Minion Mana. |

Player life and Force life have a maximum of 10. Recovery cannot raise either above 10.

## 4. Deck Construction and Game Setup

A deck must contain exactly 40 cards. Cards with the same name are normally limited to three copies. A card whose text says it may be included in any quantity ignores this limit.

Each player selects two different Forces. A player cannot select two copies of the same Force.

At the start of the game, each player draws six cards. Each player then mulligans by returning any number of cards, drawing the same number, and shuffling their deck.

Starting player life is calculated as follows:

```text
Player life = 12 - the combined starting life of the two selected Forces
```

For example, Forces with starting life 2 and 3 give their player 7 starting life.

## 5. Turn Sequence

| Step | Procedure |
| --- | --- |
| Start of turn | Resolve start-of-turn effects. Normally gain 1 movement for the turn. The first player gains no movement on turn 1. |
| Refresh | Activate your Field, Base, and Forces. Summoning sickness also ends. |
| Draw | Draw one card. The first player does not draw on turn 1. A player who must draw during this step with an empty deck loses. |
| Mana | Place one Base Minion in the Base, place one colorless Mana, or do nothing. |
| Main | Play cards, move Minions, attack, or end the turn. |
| End of turn | Resolve end-of-turn effects. Turn-only modifiers and unused movement expire. |

## 6. Mana and Paying Costs

Rest active cards or colorless Mana in your Base to pay costs. Rested Mana cannot pay costs.

Colored costs must normally be paid with Mana of the same color. Free costs may be paid with Mana of any color or with colorless Mana.

The Base limit is 10. If a card or colorless Mana would be placed into a full Base, the owner of that Base selects one existing Base object to replace. A replaced card goes to the Trash; a replaced colorless Mana token leaves the game.

## 7. Playing Cards and Summoning

A Field Minion is normally summoned to the Field during its controller's main phase after its cost is paid. It has summoning sickness during that turn and normally cannot attack a player.

A Base Minion is normally placed from the Hand into the Base during the Mana step. It cannot be normally summoned directly to the Field.

A Magic card is played at its specified timing. Its cost is paid, its effect resolves, and it is placed in the Trash. Magic with Flash timing may also be played during a Flash window.

The Field limit is five Minions. If a Minion would enter a full Field, that Field's owner selects one existing Minion to replace. The replaced Minion goes to the Trash.

## 8. Movement

During your main phase, you may spend 1 movement to move a Minion from Base to Field or from Field to Base. A player normally receives 1 movement each turn.

A Base Minion in the Base can move to the Field, and a Minion in the Field can move to the Base. Colorless Mana cannot move to the Field. Token Minions cannot move through normal movement.

A moved Minion keeps its active or rested state. A rested Minion Mana enters the Field rested.

## 9. Attacking and Blocking

During your main phase, you may rest an active Field Minion to attack. The first player cannot attack on turn 1.

Normal attack targets are an opposing Force or the opposing player. A normal action cannot directly attack an opposing Minion unless an effect says otherwise.

While the opponent controls an undestroyed Force, a Minion with summoning sickness normally cannot target the opposing player. It may do so if all opposing Forces are destroyed or a keyword or effect permits it.

After an attack is declared, a Flash window begins. The defender receives priority first. Players alternate playing Flash cards or abilities until both pass consecutively.

After the Flash window, the defender may block with one active Minion that is allowed to block. That Minion becomes rested. If the defender does not block, the attack proceeds to its target.

When blocked, compare the attacking and blocking Minions' BP. A Minion destroys the opposing Minion if its BP is greater than or equal to the opposing BP. If both meet this condition, both are destroyed simultaneously.

When unblocked, the attack deals damage equal to the attacking Minion's DP to the targeted Force or player.

## 10. Damage, Destruction, and Drawing

Damage to a Force reduces its life. A Force at 0 life or less is destroyed and is treated as rested.

When a basic Force is destroyed, resolve its common destruction effect: choose one Base Minion from your deck and place it in your Base, shuffle your deck, then draw one card. A Base Minion placed this way normally does not trigger its placement effect.

The hand limit is 10. If a player with 10 cards draws a card, that card goes to the Trash instead of entering the Hand.

Failing to draw from an empty deck due to a card effect does not cause a loss. Draw as many cards as possible.

## 11. Targets and Optional Effects

An effect using the Japanese term `選ぶ` selects the specified targets before resolving. If no legal target exists, a part that requires that target cannot resolve, or resolves only as far as possible. Whether the card can be played is determined by its text and timing.

An effect using `できる` is optional. If its controller declines, that part does not resolve.

`Up to N` permits any number from 0 through N. For example, “choose up to two” permits choosing zero, one, or two targets.

A fixed quantity such as “choose one” or “choose two cards” normally requires exactly that quantity. If too few targets exist, follow qualifiers in the card text such as optional, maximum, or up to.

If an effect can target a player, the player must be individually selectable. If it can target a Force, each Force must be individually selectable.

## 12. Keyword Abilities

| Keyword | Effect |
| --- | --- |
| Reawaken | Activate this Minion at the end of your turn. |
| Assault | This Minion can attack a player during the turn it entered. It may target a player even while that player controls a Force. |
| Flying | This Field Minion card may be paid for and summoned during a Flash window. Flying does not restrict blocking. |
| Infiltrate | This Minion can be blocked only by a Minion with the same cost. |
| Lethal | During your turn, an opposing Minion that battled this Minion is destroyed at the end of combat. |
| Pierce | During your turn, when this Minion is blocked and wins combat, deal the difference between the attacking and blocking Minions' DP to the original target. When attacking a Force, DP beyond that Force's remaining life is dealt to the opposing player. |
| Link | If you placed your own Mana of the specified color this turn, resolve the Link effect when playing this card from your Hand. The standard effect is to draw one card. |
| Blessing | A special Mana or protection effect supplied from the Base. Follow the individual card text. |

Common non-keyword effects include reducing free costs, modifying BP or DP, preventing selection, and reducing damage. These are handled as statuses applied to a card or Force.

## 13. Common Force Rules

A Force has life and abilities. Its continuous and conditional abilities function while it is active and not destroyed. They do not function while it is rested or destroyed.

Your Forces become active during your refresh step.

All basic Forces have this common destruction effect:

```text
[WHEN DESTROYED]
Choose one Base Minion card from your deck and place it in your Base.
Then shuffle your deck and draw one card.
```

## 14. Basic Forces

| Force | Starting life | Ability summary |
| --- | ---: | --- |
| Force of Evil "Cyclops" | 2 | [CONTINUOUS] All of your Minions get +100 BP. |
| Force of Chaos "Chimera" | 3 | [YOUR TURN] Your colorless Mana counts as every color when paying the cost of a Field Minion. |
| Force of Triumph "Minotaur" | 4 | [CONTINUOUS] Damage dealt to you by opposing Minions is reduced by 1. |
| Force of Twins "Orthrus" | 3 | [CONTINUOUS] Your Minions with cost 5 or more get +1 DP. |
| Holy Force "Sphinx" | 3 | [OPPONENT'S TURN] Your Minions with cost 5 or less cannot be selected by opposing Minion effects. |
| Force of Wisdom "Chiron" | 4 | [CONTINUOUS] Magic cards in your Hand cost 2 less colorless Mana. |
| Force of Beauty "Siren" | 2 | [YOUR TURN] Whenever one of your Minion Mana moves to the Field, place one rested colorless Mana in your Base. |
| Force of Flight "Pegasus" | 3 | [START OF YOUR TURN] If you have 4 or more Mana, gain 1 additional movement for this turn. |
| Force of Revival "Phoenix" | 3 | [END OF YOUR TURN] Activate all of your Mana. |
| Ouroboros - Force of Eternity | 2 | [END OF YOUR TURN] Activate all of your non-token Minions. |
