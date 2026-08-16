const test = require("node:test");
const assert = require("node:assert/strict");

const {
  actionOptionsForCard,
  canMulliganSelect,
  isCardInteractive,
} = require("../zz/web/static/multiplayer-card-policy.js");

test("options without a card id never attach to hidden opponent cards", () => {
  const card = { area: "hand", faceDown: true, ownerSide: "P2" };
  const options = [{ id: "end", kind: "end_turn" }];
  assert.deepEqual(actionOptionsForCard(card, options), []);
});

test("online mulligan selection is limited to the local player's hand", () => {
  const prompt = { kind: "mulligan", playerSide: "P1" };
  assert.equal(canMulliganSelect({ area: "hand", faceDown: false, ownerSide: "P1" }, prompt, "P1", true), true);
  assert.equal(canMulliganSelect({ area: "hand", faceDown: false, ownerSide: "P2" }, prompt, "P1", true), false);
});

test("an online opponent hand card is never interactive", () => {
  assert.equal(isCardInteractive({ area: "hand", faceDown: false, ownerSide: "P2" }, "P1", true), false);
});
