"use strict";

const { HttpsProxyAgent } = require("https-proxy-agent");
const WebSocket = require("ws");

function firstSupportedProxy(rawRules) {
  for (const rawRule of String(rawRules || "").split(";")) {
    const rule = rawRule.trim();
    const match = /^(PROXY|HTTP|HTTPS)\s+(.+)$/i.exec(rule);
    if (!match) continue;
    const scheme = match[1].toUpperCase() === "HTTPS" ? "https" : "http";
    try {
      const parsed = new URL(`${scheme}://${match[2]}`);
      if (!parsed.hostname || !parsed.port) continue;
      return parsed.toString().replace(/\/$/, "");
    } catch (_error) {
      continue;
    }
  }
  return null;
}

function eventError(event, fallback) {
  if (event instanceof Error) return event;
  if (event && event.error instanceof Error) return event.error;
  return new Error(fallback);
}

function createAdaptiveWebSocketClass({
  resolveProxy,
  WebSocketImpl = WebSocket,
  proxyAgentFactory = (proxyUrl) => new HttpsProxyAgent(proxyUrl),
  attemptTimeoutMs = 8000,
  onRouteSelected = () => {},
} = {}) {
  if (typeof resolveProxy !== "function") throw new TypeError("resolveProxy must be a function");
  if (typeof WebSocketImpl !== "function") throw new TypeError("WebSocketImpl must be a constructor");
  if (typeof proxyAgentFactory !== "function") throw new TypeError("proxyAgentFactory must be a function");
  if (!Number.isInteger(attemptTimeoutMs) || attemptTimeoutMs <= 0) {
    throw new TypeError("attemptTimeoutMs must be a positive integer");
  }

  return class AdaptiveWebSocket {
    #attempts = new Map();
    #closed = false;
    #failures = [];
    #listeners = new Map();
    #remaining = 0;
    #winner = null;

    constructor(url) {
      this.url = String(url || "");
      queueMicrotask(() => this.#start());
    }

    addEventListener(type, listener) {
      if (typeof listener !== "function") return;
      const listeners = this.#listeners.get(type) || new Set();
      listeners.add(listener);
      this.#listeners.set(type, listeners);
    }

    removeEventListener(type, listener) {
      this.#listeners.get(type)?.delete(listener);
    }

    send(value) {
      if (!this.#winner) throw new Error("adaptive WebSocket is not open");
      this.#winner.send(value);
    }

    close() {
      if (this.#closed) return;
      this.#closed = true;
      for (const [socket, attempt] of this.#attempts) {
        clearTimeout(attempt.timer);
        attempt.settled = true;
        socket.close();
      }
      this.#attempts.clear();
      this.#winner = null;
    }

    async #start() {
      if (this.#closed) return;
      let parsed;
      try {
        parsed = new URL(this.url);
      } catch (error) {
        this.#emit("error", { error });
        return;
      }

      const routes = [{ kind: "direct", proxy: null }];
      if (parsed.protocol === "wss:") {
        try {
          const proxy = firstSupportedProxy(await resolveProxy(parsed.toString()));
          if (proxy) routes.push({ kind: "proxy", proxy });
        } catch (error) {
          this.#failures.push(`proxy discovery: ${eventError(error, "unknown failure").message}`);
        }
      }
      if (this.#closed) return;
      this.#remaining = routes.length;
      for (const route of routes) this.#startAttempt(parsed.toString(), route);
    }

    #startAttempt(url, route) {
      let socket;
      try {
        const options = { perMessageDeflate: false };
        if (route.proxy) options.agent = proxyAgentFactory(route.proxy);
        socket = new WebSocketImpl(url, options);
      } catch (error) {
        this.#recordFailure(route, error);
        return;
      }

      const attempt = {
        route,
        settled: false,
        timer: setTimeout(() => {
          this.#failAttempt(socket, new Error(`handshake timed out after ${attemptTimeoutMs}ms`));
        }, attemptTimeoutMs),
      };
      this.#attempts.set(socket, attempt);
      socket.addEventListener("open", (event) => this.#select(socket, event));
      socket.addEventListener("message", (event) => {
        if (socket === this.#winner) this.#emit("message", event);
      });
      socket.addEventListener("error", (event) => {
        if (socket === this.#winner) this.#emit("error", event);
        else this.#failAttempt(socket, eventError(event, "WebSocket error"));
      });
      socket.addEventListener("close", (event) => {
        if (socket === this.#winner) this.#emit("close", event);
        else this.#failAttempt(socket, new Error(event?.reason || "closed before handshake"));
      });
    }

    #select(socket, event) {
      const attempt = this.#attempts.get(socket);
      if (!attempt || attempt.settled || this.#closed) return;
      if (this.#winner) {
        this.#settleAndClose(socket, attempt);
        return;
      }
      attempt.settled = true;
      clearTimeout(attempt.timer);
      this.#winner = socket;
      for (const [candidate, candidateAttempt] of this.#attempts) {
        if (candidate !== socket && !candidateAttempt.settled) {
          this.#settleAndClose(candidate, candidateAttempt);
        }
      }
      onRouteSelected({ ...attempt.route });
      this.#emit("open", event);
    }

    #settleAndClose(socket, attempt) {
      attempt.settled = true;
      clearTimeout(attempt.timer);
      this.#attempts.delete(socket);
      socket.close();
    }

    #failAttempt(socket, error) {
      const attempt = this.#attempts.get(socket);
      if (!attempt || attempt.settled || this.#winner || this.#closed) return;
      attempt.settled = true;
      clearTimeout(attempt.timer);
      this.#attempts.delete(socket);
      socket.close();
      this.#recordFailure(attempt.route, error);
    }

    #recordFailure(route, error) {
      const label = route.proxy ? "proxy" : "direct";
      this.#failures.push(`${label}: ${eventError(error, "unknown failure").message}`);
      this.#remaining -= 1;
      if (this.#remaining === 0 && !this.#winner && !this.#closed) {
        this.#emit("error", {
          error: new Error(`All multiplayer routes failed (${this.#failures.join("; ")})`),
        });
      }
    }

    #emit(type, event) {
      for (const listener of [...(this.#listeners.get(type) || [])]) listener(event);
    }
  };
}

module.exports = {
  createAdaptiveWebSocketClass,
  firstSupportedProxy,
};
