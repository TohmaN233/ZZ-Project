(function () {
  async function bootDuel() {
    if (
      !window.ZZApp ||
      typeof window.ZZApp.bootApp !== "function" ||
      typeof window.ZZApp.loadState !== "function"
    ) {
      throw new Error("ZZApp boot runtime is not available.");
    }
    await window.ZZApp.bootApp("duel");
    if (
      typeof window.ZZApp.consumePendingDuelLaunch === "function" &&
      window.ZZApp.consumePendingDuelLaunch()
    ) {
      return null;
    }
    return window.ZZApp.loadState();
  }

  window.ZZDuelRuntime = {
    boot: bootDuel,
    render: window.ZZApp.renderDuelView,
  };

  bootDuel();
})();
