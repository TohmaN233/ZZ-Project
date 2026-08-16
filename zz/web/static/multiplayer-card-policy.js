(function (root, factory) {
  const policy = factory();
  if (typeof module === "object" && module.exports) module.exports = policy;
  root.ZZMultiplayerCardPolicy = policy;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function sameId(left, right) {
    return left !== undefined && left !== null && right !== undefined && right !== null
      && String(left) === String(right);
  }

  function actionOptionsForCard(card, options) {
    if (!card || card.iid === undefined || card.iid === null) return [];
    return (options || []).filter((option) => {
      if (sameId(option.cardIid, card.iid) || sameId(option.attacker_iid, card.iid)) return true;
      if (option.kind === "bless") return sameId(option.mana_iid, card.iid);
      if (["play_card", "play_to_base", "move_card", "activate_flash_ability"].includes(option.kind)) {
        return sameId(option.iid, card.iid);
      }
      return false;
    });
  }

  function canMulliganSelect(card, prompt, humanSide, online) {
    if (!card || !prompt || prompt.kind !== "mulligan" || card.faceDown || card.area !== "hand") return false;
    if (online) {
      return Boolean(humanSide && prompt.playerSide === humanSide && card.ownerSide === humanSide);
    }
    return !prompt.playerSide || card.ownerSide === prompt.playerSide;
  }

  function isCardInteractive(card, humanSide, online) {
    if (!card || card.faceDown) return false;
    if (online && card.area === "hand") return Boolean(humanSide && card.ownerSide === humanSide);
    return true;
  }

  return { actionOptionsForCard, canMulliganSelect, isCardInteractive };
});
