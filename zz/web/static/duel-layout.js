(function (root) {
  "use strict";

  function normalizeScale(value = 100) {
    const scale = Number(value);
    if (!Number.isInteger(scale) || scale < 80 || scale > 150 || scale % 10 !== 0) {
      throw new Error(`invalid duel scale: ${value}`);
    }
    return scale;
  }

  function zoneCardWidth(width, height, capacity, scale = 100) {
    const fit = Math.min((width - (capacity - 1) * 8) / capacity, height / 1.42);
    return Math.max(1, Math.min(fit * 0.88 * normalizeScale(scale) / 100, height / 1.42));
  }

  function observe(app, scale, onResize) {
    scale = normalizeScale(scale);
    const refresh = () => {
      for (const zone of app.querySelectorAll(".arena .zone-cards")) {
        const style = getComputedStyle(zone);
        const width = zone.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        const height = zone.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
        if (width <= 0 || height <= 0) continue;
        const mini = Boolean(zone.closest(".base-zone, .base-lane"));
        zone.style.setProperty(mini ? "--mini-w" : "--field-w", `${zoneCardWidth(width, height, mini ? 10 : 5, scale)}px`);
        zone.style.setProperty(mini ? "--mini-h" : "--field-h", `calc(var(${mini ? "--mini-w" : "--field-w"}) * 1.42)`);
      }
      for (const cockpit of app.querySelectorAll(".cockpit")) {
        const hand = cockpit.querySelector(".hand-fan");
        if (!hand) continue;
        // Use the viewport rather than the hand's own height to avoid a resize feedback loop.
        const hud = cockpit.querySelector(".cockpit-hud");
        const hudStyle = getComputedStyle(hud);
        const fixedHeight = [...hud.children].filter(e => e.classList.contains("cockpit-force-row") || e.classList.contains("cockpit-command-row"))
          .reduce((sum, e) => sum + e.getBoundingClientRect().height, 0);
        const reservedHeight = fixedHeight + parseFloat(hudStyle.getPropertyValue("--cockpit-identity-min"))
          + parseFloat(hudStyle.paddingTop) + parseFloat(hudStyle.paddingBottom)
          + parseFloat(hudStyle.rowGap) * (hand.classList.contains("top") ? 2 : 3) + 36;
        const heightLimit = window.innerWidth <= 980 ? window.innerHeight * 0.32 : Math.max(1, cockpit.clientHeight - reservedHeight);
        const miniFactor = hand.classList.contains("top") ? 0.62 : 1;
        const width = Math.min(Math.min(cockpit.clientWidth * 0.24, window.innerHeight * 0.15) * scale / 100, heightLimit / (1.42 * miniFactor));
        hand.style.setProperty("--hand-w", `${width}px`);
        hand.style.setProperty("--hand-h", "calc(var(--hand-w) * 1.42)");
        hand.style.setProperty("--mini-w", `${width * 0.62}px`);
        hand.style.setProperty("--mini-h", "calc(var(--mini-w) * 1.42)");
        const cards = hand.querySelector(".hand-cards");
        const count = cards.querySelectorAll(".hand-slot").length;
        const cardWidth = width * miniFactor;
        // Reserve room for the tilted edge cards as well as the hand's padding.
        const availableWidth = cards.clientWidth - 48 - cardWidth * 0.22;
        const overlap = count > 1 ? Math.max(0, (count * cardWidth - availableWidth) / (count - 1)) : 0;
        cards.style.setProperty(hand.classList.contains("top") ? "--opponent-hand-overlap" : "--hand-overlap", `${overlap}px`);
      }
      onResize();
    };
    const observer = new ResizeObserver(refresh);
    for (const element of app.querySelectorAll(".arena .zone-cards, .cockpit")) observer.observe(element);
    window.addEventListener("resize", refresh);
    return { disconnect() { observer.disconnect(); window.removeEventListener("resize", refresh); } };
  }

  const api = { normalizeScale, zoneCardWidth, observe };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ZZDuelLayout = api;
})(typeof window !== "undefined" ? window : globalThis);
