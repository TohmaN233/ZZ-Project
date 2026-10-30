(function (root) {
  "use strict";

  const lastRenderByApp = new WeakMap();
  const ANCHOR_ATTRIBUTES = [
    ["card", "data-board-card-anchor"],
    ["force", "data-board-force-anchor"],
    ["zone", "data-board-anchor"],
  ];

  function isElement(node) {
    return Boolean(node && node.nodeType === 1);
  }

  function keyFor(node) {
    if (!isElement(node)) return null;
    if (node.classList.contains("hand-slot")) {
      const card = node.querySelector("[data-board-card-anchor]");
      const cardAnchor = card && card.getAttribute("data-board-card-anchor");
      if (cardAnchor) return "hand-slot:card:" + cardAnchor;
    }
    for (const [kind, attribute] of ANCHOR_ATTRIBUTES) {
      const value = node.getAttribute(attribute);
      if (value !== null && value !== "") return kind + ":" + value;
    }
    // Optional banners/overlays can be inserted before these same-tag siblings.
    // Keep the actual board and layout roots instead of reusing them as banners.
    for (const name of ["duel-board", "arena", "topbar"]) {
      if (node.classList.contains(name)) return "structure:" + name;
    }
    if (node.classList.contains("cockpit")) {
      return "structure:cockpit:" + (node.classList.contains("top") ? "top" : "bottom");
    }
    return null;
  }

  function fxSurfaceType(node) {
    if (!isElement(node)) return "";
    if (node.classList.contains("board-animation-layer")) return "board-animation-layer";
    if (node.classList.contains("visual-overlay")) return "visual-overlay";
    return "";
  }

  function fxEvent(node) {
    const type = fxSurfaceType(node);
    const event = type ? node.getAttribute("data-fx-event") : "";
    return event ? type + "\u0000" + event : null;
  }

  function hasLiveFxAncestor(node) {
    for (let parent = node && node.parentElement; parent; parent = parent.parentElement) {
      if (fxEvent(parent)) return true;
    }
    return false;
  }

  function fxEventChanged(current, desired) {
    const currentType = fxSurfaceType(current);
    const desiredType = fxSurfaceType(desired);
    const currentEvent = currentType ? current.getAttribute("data-fx-event") || "" : "";
    const desiredEvent = desiredType ? desired.getAttribute("data-fx-event") || "" : "";
    if (!currentEvent && !desiredEvent) return false;
    return currentType !== desiredType || currentEvent !== desiredEvent;
  }

  function sameLiveFxEvent(current, desired) {
    const currentKey = fxEvent(current);
    return Boolean(currentKey && currentKey === fxEvent(desired));
  }

  function compatibleNode(current, desired) {
    if (!current || !desired || current.nodeType !== desired.nodeType) return false;
    if (!isElement(current)) return true;
    if (current.namespaceURI !== desired.namespaceURI || current.localName !== desired.localName) return false;
    if (fxEventChanged(current, desired)) return false;
    if (current.hasAttribute("id") || desired.hasAttribute("id")) {
      if (current.getAttribute("id") !== desired.getAttribute("id")) return false;
    }
    if (current.localName === "input" && current.getAttribute("type") !== desired.getAttribute("type")) {
      return false;
    }
    return true;
  }

  function addToQueue(map, key, node) {
    const queue = map.get(key);
    if (queue) queue.push(node);
    else map.set(key, [node]);
  }

  function firstUnusedCompatible(map, key, desired, used) {
    const queue = map.get(key);
    if (!queue) return null;
    for (const candidate of queue) {
      if (!used.has(candidate) && compatibleNode(candidate, desired)) return candidate;
    }
    return null;
  }

  function collectMatches(app, desiredRoot) {
    const oldFx = new Map();
    const oldAnchors = new Map();
    const desiredToOld = new WeakMap();
    const assignedOld = new Set();
    const oldElements = app.querySelectorAll("*");
    const desiredElements = desiredRoot.querySelectorAll("*");

    for (const node of oldElements) {
      if (node.hasAttribute("data-fx-owned") || hasLiveFxAncestor(node)) continue;
      const eventKey = fxEvent(node);
      if (eventKey) addToQueue(oldFx, eventKey, node);
      else {
        const anchorKey = keyFor(node);
        if (anchorKey) addToQueue(oldAnchors, anchorKey, node);
      }
    }

    for (const node of desiredElements) {
      if (hasLiveFxAncestor(node)) continue;
      const eventKey = fxEvent(node);
      if (!eventKey) continue;
      const current = firstUnusedCompatible(oldFx, eventKey, node, assignedOld);
      if (!current) continue;
      desiredToOld.set(node, current);
      assignedOld.add(current);
    }

    for (const node of desiredElements) {
      if (hasLiveFxAncestor(node) || fxEvent(node)) continue;
      const anchorKey = keyFor(node);
      if (!anchorKey) continue;
      const current = firstUnusedCompatible(oldAnchors, anchorKey, node, assignedOld);
      if (!current) continue;
      desiredToOld.set(node, current);
      assignedOld.add(current);
    }

    return { desiredToOld, assignedOld };
  }

  function classNameOf(node) {
    return isElement(node) ? node.getAttribute("class") || "" : "";
  }

  function idOf(node) {
    return isElement(node) ? node.getAttribute("id") : null;
  }

  function findLocalMatch(oldChildren, desired, desiredIndex, used, assignedOld) {
    const canUse = (candidate) => {
      if (!candidate || used.has(candidate) || assignedOld.has(candidate)) return false;
      if (isElement(candidate) &&
          (candidate.hasAttribute("data-fx-owned") ||
           keyFor(candidate) ||
           fxEvent(candidate) ||
           hasLiveFxAncestor(candidate))) {
        return false;
      }
      return !fxEventChanged(candidate, desired) && compatibleNode(candidate, desired);
    };

    const positional = oldChildren[desiredIndex];
    if (canUse(positional)) return positional;

    const candidates = oldChildren.filter(canUse);
    if (!candidates.length) return null;
    const desiredId = idOf(desired);
    const desiredClass = classNameOf(desired);
    const score = (candidate) => {
      let value = 0;
      if (idOf(candidate) !== null && idOf(candidate) === desiredId) value += 8;
      if (classNameOf(candidate) === desiredClass) value += 4;
      if (candidate.nodeType === 3 && desired.nodeType === 3) value += 2;
      value -= Math.abs(oldChildren.indexOf(candidate) - desiredIndex) / 100;
      return value;
    };
    candidates.sort((left, right) => score(right) - score(left));
    return candidates[0];
  }

  function isLayoutVariable(name) {
    return name === "--field-w" ||
      name === "--field-h" ||
      name === "--mini-w" ||
      name === "--mini-h" ||
      name === "--hand-w" ||
      name === "--hand-h" ||
      name === "--hand-overlap" ||
      name === "--opponent-hand-overlap";
  }

  function preserveLayoutVariables(current, desired) {
    if (!isElement(current) || !isElement(desired) || !current.style || !desired.style) return;
    const retained = [];
    for (let index = 0; index < current.style.length; index += 1) {
      const name = current.style.item(index);
      if (!isLayoutVariable(name)) continue;
      const value = current.style.getPropertyValue(name);
      if (!value) continue;
      retained.push([name, value, current.style.getPropertyPriority(name)]);
    }
    for (const [name, value, priority] of retained) {
      desired.style.setProperty(name, value, priority);
    }
  }

  function hasAttributeNS(element, attribute) {
    return attribute.namespaceURI
      ? element.hasAttributeNS(attribute.namespaceURI, attribute.localName)
      : element.hasAttribute(attribute.name);
  }

  function getAttributeNS(element, attribute) {
    return attribute.namespaceURI
      ? element.getAttributeNS(attribute.namespaceURI, attribute.localName)
      : element.getAttribute(attribute.name);
  }

  function setAttributeNS(element, attribute, value) {
    if (attribute.namespaceURI) element.setAttributeNS(attribute.namespaceURI, attribute.name, value);
    else element.setAttribute(attribute.name, value);
  }

  function removeAttributeNS(element, attribute) {
    if (attribute.namespaceURI) element.removeAttributeNS(attribute.namespaceURI, attribute.localName);
    else element.removeAttribute(attribute.name);
  }

  function syncAttributes(current, desired) {
    preserveLayoutVariables(current, desired);
    for (let index = current.attributes.length - 1; index >= 0; index -= 1) {
      const attribute = current.attributes[index];
      if (!hasAttributeNS(desired, attribute)) removeAttributeNS(current, attribute);
    }
    for (const attribute of desired.attributes) {
      if (getAttributeNS(current, attribute) !== attribute.value) {
        setAttributeNS(current, attribute, attribute.value);
      }
    }
  }

  function syncFormProperties(current, desired) {
    switch (current.localName) {
      case "input":
      case "button":
      case "output":
      case "progress":
      case "meter":
        if ("value" in current && current.value !== desired.value) current.value = desired.value;
        break;
      case "textarea":
      case "select":
        if (current.localName === "select" && current.multiple) break;
        if (current.value !== desired.value) current.value = desired.value;
        break;
      case "option":
        if (current.selected !== desired.selected) current.selected = desired.selected;
        break;
      default:
        break;
    }
    if (current.localName === "input" && current.checked !== desired.checked) {
      current.checked = desired.checked;
    }
  }

  function reconcileChildren(current, desired, state) {
    const oldChildren = Array.from(current.childNodes);
    const desiredChildren = Array.from(desired.childNodes);
    const usedOld = new Set();
    const liveChildren = [];

    for (let index = 0; index < desiredChildren.length; index += 1) {
      const wanted = desiredChildren[index];
      let live = state.desiredToOld.get(wanted) || null;
      if (live && (!compatibleNode(live, wanted) || usedOld.has(live))) live = null;
      if (!live && !keyFor(wanted) && !fxEvent(wanted)) {
        live = findLocalMatch(oldChildren, wanted, index, usedOld, state.assignedOld);
      }
      if (live) {
        usedOld.add(live);
        live = patchNode(live, wanted, state);
      } else {
        live = wanted;
        graftFreshSubtree(live, state);
      }
      liveChildren.push(live);
    }

    const keep = new Set(liveChildren);
    for (const child of Array.from(current.childNodes)) {
      if (keep.has(child)) continue;
      if (isElement(child) && child.hasAttribute("data-fx-owned")) continue;
      current.removeChild(child);
    }

    let cursor = current.firstChild;
    for (const child of liveChildren) {
      if (child === cursor) {
        cursor = cursor.nextSibling;
        continue;
      }
      current.insertBefore(child, cursor);
      cursor = child.nextSibling;
    }
  }

  function graftFreshSubtree(node, state) {
    if (!isElement(node)) return;
    for (const wanted of Array.from(node.childNodes)) {
      let live = state.desiredToOld.get(wanted) || null;
      if (live && compatibleNode(live, wanted)) {
        live = patchNode(live, wanted, state);
        node.replaceChild(live, wanted);
      } else {
        graftFreshSubtree(wanted, state);
      }
    }
  }

  function patchNode(current, desired, state) {
    if (sameLiveFxEvent(current, desired)) return current;
    if (!compatibleNode(current, desired)) return desired;
    if (current.nodeType === 3 || current.nodeType === 8) {
      if (current.data !== desired.data) current.data = desired.data;
      return current;
    }
    if (!isElement(current)) return current;
    syncAttributes(current, desired);
    reconcileChildren(current, desired, state);
    syncFormProperties(current, desired);
    return current;
  }

  function captureFocus(app) {
    const document = app.ownerDocument;
    const active = document.activeElement;
    if (!active || !app.contains(active)) return null;
    const path = [];
    for (let node = active; node && node !== app; node = node.parentNode) {
      if (!node.parentNode) break;
      path.unshift(Array.prototype.indexOf.call(node.parentNode.childNodes, node));
    }
    const focus = {
      node: active,
      path,
      tag: active.localName || "",
      id: active.getAttribute ? active.getAttribute("id") : null,
      name: active.getAttribute ? active.getAttribute("name") : null,
      type: active.getAttribute ? active.getAttribute("type") : null,
      selection: null,
    };
    if (typeof active.setSelectionRange === "function" &&
        typeof active.selectionStart === "number" &&
        typeof active.selectionEnd === "number") {
      focus.selection = {
        start: active.selectionStart,
        end: active.selectionEnd,
        direction: active.selectionDirection || "none",
      };
    }
    return focus;
  }

  function findFocusReplacement(app, focus) {
    if (focus.node.isConnected && app.contains(focus.node)) return focus.node;
    if (focus.id !== null) {
      const byId = Array.from(app.querySelectorAll("[id]"))
        .find((node) => node.getAttribute("id") === focus.id);
      if (byId) return byId;
    }
    if (focus.name !== null) {
      const byName = Array.from(app.querySelectorAll(focus.tag))
        .find((node) => node.getAttribute("name") === focus.name &&
          (focus.type === null || node.getAttribute("type") === focus.type));
      if (byName) return byName;
    }
    let node = app;
    for (const index of focus.path) {
      node = node.childNodes[index];
      if (!node) return null;
    }
    if (!isElement(node) || node.localName !== focus.tag) return null;
    if (focus.type !== null && node.getAttribute("type") !== focus.type) return null;
    return node;
  }

  function captureScroll(app) {
    const document = app.ownerDocument;
    const nodes = [app, ...app.querySelectorAll("*")];
    if (document.scrollingElement) nodes.push(document.scrollingElement);
    return {
      positions: nodes.map((node) => ({ node, left: node.scrollLeft, top: node.scrollTop })),
      window: document.defaultView
        ? { x: document.defaultView.scrollX, y: document.defaultView.scrollY }
        : null,
    };
  }

  function restoreInteraction(app, focus, scroll) {
    if (focus) {
      const target = findFocusReplacement(app, focus);
      if (target && typeof target.focus === "function") {
        if (app.ownerDocument.activeElement !== target) target.focus({ preventScroll: true });
        if (focus.selection && typeof target.setSelectionRange === "function") {
          target.setSelectionRange(
            focus.selection.start,
            focus.selection.end,
            focus.selection.direction
          );
        }
      }
    }
    for (const position of scroll.positions) {
      const node = position.node;
      if (!node.isConnected) continue;
      if (node.scrollLeft !== position.left) node.scrollLeft = position.left;
      if (node.scrollTop !== position.top) node.scrollTop = position.top;
    }
    const view = app.ownerDocument.defaultView;
    if (view && scroll.window &&
        (view.scrollX !== scroll.window.x || view.scrollY !== scroll.window.y)) {
      view.scrollTo(scroll.window.x, scroll.window.y);
    }
  }

  function patch(app, html) {
    if (!app || app.nodeType !== 1 || typeof app.querySelector !== "function") {
      throw new TypeError("ZZDuelDom.patch requires a real DOM element");
    }
    if (typeof html !== "string") {
      throw new TypeError("ZZDuelDom.patch requires HTML text");
    }
    const previousBoard = app.querySelector(".duel-board");
    const cached = lastRenderByApp.get(app);
    if (cached && cached.html === html && cached.board === previousBoard) {
      return { board: previousBoard, mounted: false };
    }

    const document = app.ownerDocument;
    const template = document.createElement("template");
    template.innerHTML = html;
    const desiredRoot = template.content;
    const state = collectMatches(app, desiredRoot);
    const focus = captureFocus(app);
    const scroll = captureScroll(app);
    const fxOwned = Array.from(app.querySelectorAll("[data-fx-owned]"));

    reconcileChildren(app, desiredRoot, state);

    const board = app.querySelector(".duel-board");
    for (const node of fxOwned) {
      if (app.contains(node)) continue;
      (board || app).appendChild(node);
    }
    restoreInteraction(app, focus, scroll);

    lastRenderByApp.set(app, { html, board });
    return { board, mounted: previousBoard !== board };
  }

  root.ZZDuelDom = { patch };
})(typeof window !== "undefined" ? window : globalThis);
