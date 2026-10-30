(function (root) {
  "use strict";

  // Presentation only. The session animation queue remains the sole clock for rules.
  const BASE = "/static/fx/";
  const eventIds = new WeakMap();
  const effects = new Map();
  const animations = new Set();
  const failures = [];
  const systemMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const hover = matchMedia("(hover: hover) and (pointer: fine)");
  let sequence = 0, app = null, board = null, canvas = null, gl = null, context = null;
  let runtime = null, manifest = null, active = null, raf = 0, lastFrame = 0;
  let phase = "idle";
  let initializationMs = null;
  const idleWaiters = new Set();
  let reduced = false, humanSide = "P1", tilt = null, pointerFrame = 0;
  let renderedEvents = 0, skippedLate = 0, frameCount = 0;
  let cancellation = 0, gpuFailed = false;
  const handles = [];
  let handPositions = new Map();
  const handAnimations = new WeakMap();
  const identityGrade = [1, 0, 0, 0, 1, 0, 0, 0, 1];
  let compositor = null, colorGrade = identityGrade;

  function createCompositor() {
    const shader = (type, source) => {
      const value = gl.createShader(type);
      gl.shaderSource(value, source); gl.compileShader(value);
      if (!gl.getShaderParameter(value, gl.COMPILE_STATUS)) throw new Error(`FX shader: ${gl.getShaderInfoLog(value)}`);
      return value;
    };
    const vertex = shader(gl.VERTEX_SHADER, `attribute vec2 position; varying vec2 uv;
      void main(){uv=position*.5+.5;gl_Position=vec4(position,0.,1.);}`);
    const fragment = shader(gl.FRAGMENT_SHADER, `precision mediump float;
      varying vec2 uv; uniform sampler2D source; uniform mat3 grade;
      void main(){vec4 pixel=texture2D(source,uv);
        gl_FragColor=vec4(clamp(grade*pixel.rgb,0.,1.),pixel.a);}`);
    const program = gl.createProgram();
    gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(`FX compositor: ${gl.getProgramInfoLog(program)}`);
    gl.deleteShader(vertex); gl.deleteShader(fragment);
    const vertices = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vertices);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.bindTexture(gl.TEXTURE_2D, null);
    return { program, vertices, texture, depth: gl.createRenderbuffer(), frame: gl.createFramebuffer(),
      position: gl.getAttribLocation(program, "position"), grade: gl.getUniformLocation(program, "grade"),
      source: gl.getUniformLocation(program, "source"), width: 0, height: 0 };
  }

  function resizeCompositor(width, height) {
    if (!compositor || (compositor.width === width && compositor.height === height)) return;
    gl.bindTexture(gl.TEXTURE_2D, compositor.texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.bindRenderbuffer(gl.RENDERBUFFER, compositor.depth);
    gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, width, height);
    gl.bindFramebuffer(gl.FRAMEBUFFER, compositor.frame);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, compositor.texture, 0);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, compositor.depth);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) throw new Error("FX framebuffer incomplete");
    gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.bindRenderbuffer(gl.RENDERBUFFER, null);
    gl.bindTexture(gl.TEXTURE_2D, null);
    compositor.width = width; compositor.height = height;
  }

  function composite() {
    // CSS filters discard additive RGB when alpha is zero. Grade the original
    // premultiplied RGB on the GPU, retaining both luminous rays and normal smoke.
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    for (const flag of [gl.BLEND, gl.DEPTH_TEST, gl.CULL_FACE, gl.SCISSOR_TEST, gl.STENCIL_TEST]) gl.disable(flag);
    gl.colorMask(true, true, true, true);
    gl.useProgram(compositor.program);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, compositor.texture);
    gl.uniform1i(compositor.source, 0); gl.uniformMatrix3fv(compositor.grade, false, colorGrade);
    gl.bindBuffer(gl.ARRAY_BUFFER, compositor.vertices);
    gl.enableVertexAttribArray(compositor.position);
    gl.vertexAttribPointer(compositor.position, 2, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.disableVertexAttribArray(compositor.position);
    gl.bindBuffer(gl.ARRAY_BUFFER, null); gl.bindTexture(gl.TEXTURE_2D, null); gl.useProgram(null);
  }

  function eventKey(event) {
    if (!event) return "";
    if (!eventIds.has(event)) eventIds.set(event, ++sequence);
    return String(eventIds.get(event));
  }

  function fullMotion() { return !reduced && !systemMotion.matches && !document.hidden; }

  function report(error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!failures.includes(message)) {
      failures.push(message);
      if (failures.length > 20) failures.shift();
      console.error("[ZZFx]", message);
      root.dispatchEvent(new CustomEvent("zz-fx-error", { detail: { message } }));
    }
    showStatus();
  }

  function showStatus() {
    if (!board || !failures.length) return;
    let status = board.querySelector(".fx-status");
    if (!status) {
      status = document.createElement("span");
      status.className = "fx-status";
      status.dataset.fxOwned = "status";
      status.setAttribute("role", "status");
      board.append(status);
    }
    status.textContent = "FX !";
    status.title = failures.join("\n");
  }

  async function fetchChecked(url, type) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response[type]();
  }

  function loadRuntime() {
    if (runtime) return runtime;
    runtime = (async () => {
      phase = "loading-runtime";
      manifest = await fetchChecked(`${BASE}manifest.json`, "json");
      await new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = `${BASE}effekseer.min.js`;
        script.onload = resolve;
        script.onerror = () => reject(new Error("Effekseer script could not be loaded"));
        document.head.append(script);
      });
      const binary = await fetchChecked(`${BASE}effekseer.wasm`, "blob");
      const url = URL.createObjectURL(binary);
      try {
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error("Effekseer initialization timed out")), 15000);
          root.effekseer.initRuntime(url, () => { clearTimeout(timer); resolve(); }, () => {
            clearTimeout(timer); reject(new Error("Effekseer WASM initialization failed"));
          });
        });
      } finally { URL.revokeObjectURL(url); }
      // Native context.init compiles GPU programs synchronously (hundreds of
      // milliseconds on an integrated GPU). Never insert that work mid-flight.
      await waitForIdle();
      phase = "initializing-gpu";
      canvas = document.createElement("canvas");
      canvas.hidden = true;
      canvas.className = "fx-canvas";
      canvas.dataset.fxOwned = "canvas";
      canvas.setAttribute("aria-hidden", "true");
      gl = canvas.getContext("webgl", { alpha: true, premultipliedAlpha: true, antialias: false });
      if (!gl) throw new Error("WebGL unavailable: particle effects disabled");
      canvas.addEventListener("webglcontextlost", (event) => {
        event.preventDefault(); gpuFailed = true; phase = "failed"; stop();
        report(new Error("WebGL context lost; reload to restore particle effects"));
      });
      context = root.effekseer.createContext();
      const initStarted = performance.now();
      context.init(gl, { instanceMaxCount: 2500, squareMaxCount: 6000, enablePremultipliedAlpha: true });
      initializationMs = performance.now() - initStarted;
      // This canvas belongs exclusively to FX. Both native rendering and the
      // compositor set their own draw state; restoring external state would
      // synchronously query the GPU and stall the first card flight on D3D11.
      context.setRestorationOfStatesFlag(false);
      compositor = createCompositor();
      context.setCameraLookAt(0, 0, 1000, 0, 0, 0, 0, 1, 0);
      phase = "loading-effects";
      await Promise.all(Object.keys(manifest.effects).map(loadEffect));
      phase = "ready";
      canvas.hidden = false;
      if (board) { board.append(canvas); resize(); }
    })();
    runtime.catch((error) => {
      phase = "failed";
      gpuFailed = true; stop(); canvas?.remove(); report(error);
    });
    return runtime;
  }

  async function waitForIdle() {
    while (active) {
      phase = "waiting-for-idle";
      await new Promise(resolve => idleWaiters.add(resolve));
    }
  }

  async function prepare() {
    if (!fullMotion()) return { ready: false, disabled: true };
    try {
      await loadRuntime();
      return { ready: phase === "ready" && !gpuFailed };
    } catch (error) {
      // The existing visible FX error remains available when the board mounts;
      // a GPU failure must not prevent the rules/UI from loading.
      report(error);
      return { ready: false, error: String(error.message || error) };
    }
  }

  function releaseIdleWaiters() {
    // onEventEnd and the next onEventStart run in one queue-advance task.
    // Only the end of the whole batch is an initialization opportunity.
    queueMicrotask(() => {
      if (active) return;
      for (const resolve of idleWaiters) resolve();
      idleWaiters.clear();
    });
  }

  function loadEffect(name) {
    const definition = manifest.effects[name];
    if (!definition) throw new Error(`Unknown effect: ${name}`);
    if (effects.has(definition.file)) return effects.get(definition.file);
    const promise = (async () => {
      const data = await fetchChecked(`${BASE}${definition.file}`, "arrayBuffer");
      return new Promise((resolve, reject) => {
        let effect;
        const timer = setTimeout(() => reject(new Error(`Effect load timed out: ${name}`)), 10000);
        const redirect = (path) => {
          const resource = definition.resources[path.replaceAll("\\", "/")];
          if (!resource) throw new Error(`Unmapped resource in ${name}: ${path}`);
          return `${BASE}${resource}`;
        };
        effect = context.loadEffect(data, 1, () => {
          clearTimeout(timer);
          // The native loader can complete synchronously for a resource-free effect.
          queueMicrotask(() => {
            if (!effect.nativeptr) reject(new Error(`Invalid Effekseer binary: ${name}`));
            else resolve(effect);
          });
        }, (reason, path) => {
          clearTimeout(timer); reject(new Error(`${name}: ${reason} (${path})`));
        }, redirect);
      });
    })();
    effects.set(definition.file, promise);
    return promise;
  }

  function resize() {
    if (!canvas || !board || !gl || !context || gpuFailed || phase !== "ready") return;
    const rect = board.getBoundingClientRect();
    const dpr = Math.min(root.devicePixelRatio || 1, 1.5);
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width; canvas.height = height;
      gl.viewport(0, 0, width, height);
      context.setProjectionOrthographic(rect.width, rect.height, 1, 2000);
    }
    resizeCompositor(width, height);
  }

  function transformAngle(transform) {
    if (!transform || transform === "none") return 0;
    const matrix = new DOMMatrixReadOnly(transform);
    return Math.atan2(matrix.b, matrix.a) * 180 / Math.PI;
  }

  function elementSize(el) {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const width = Number.parseFloat(style.width);
    const height = Number.parseFloat(style.height);
    return {
      width: Number.isFinite(width) && width > 0 ? width : rect.width,
      height: Number.isFinite(height) && height > 0 ? height : rect.height,
    };
  }

  function elementPoint(el, bounds) {
    const rect = el.getBoundingClientRect();
    const size = elementSize(el);
    const style = getComputedStyle(el);
    const slot = el.closest(".hand-slot");
    return {
      x: (rect.left + rect.width / 2 - bounds.left) / bounds.width,
      y: (rect.top + rect.height / 2 - bounds.top) / bounds.height,
      ...size,
      rectWidth: rect.width,
      rectHeight: rect.height,
      opacity: Number.parseFloat(style.opacity),
      angle: transformAngle(style.transform) + (slot ? transformAngle(getComputedStyle(slot).transform) : 0),
      el,
    };
  }

  function anchors() {
    const found = new Map();
    if (!board) return found;
    const bounds = board.getBoundingClientRect();
    for (const el of board.querySelectorAll("[data-board-anchor], [data-board-card-anchor], [data-board-force-anchor]")) {
      const point = elementPoint(el, bounds);
      for (const attr of ["data-board-anchor", "data-board-card-anchor", "data-board-force-anchor"]) {
        const key = el.getAttribute(attr);
        if (key) found.set(key, point);
      }
    }
    return found;
  }

  function zone(side, area) { return `${side}:${area}`; }
  function card(side, iid, area = "field") { return iid == null ? zone(side, area) : `${side}:card:${iid}`; }
  function targetKey(event) {
    const side = event.targetSide || event.target?.ownerSide || event.side;
    if (event.type === "damage" || event.type === "heal") {
      return event.targetKind === "force" ? `${event.side}:force:${event.forceId}`
        : event.targetKind === "card" ? card(event.side, event.cardIid) : zone(event.side, "player");
    }
    if (event.type === "block") return card(side, event.blockerIid);
    const kind = event.targetKind || event.target?.targetKind;
    if (kind === "force") return `${side}:force:${event.targetForceId || event.target?.forceId}`;
    if (kind === "card") {
      const iid = event.targetCardIid ?? event.target?.cardIid;
      return iid == null ? null : card(side, iid);
    }
    if (kind === "player") return zone(side, "player");
    return event.type === "effect_target" ? null : zone(side, "field");
  }

  function point(key, fallbackKey) {
    const current = anchors();
    return current.get(key) || active?.source.get(key) || current.get(fallbackKey) || active?.source.get(fallbackKey);
  }

  function sourcePoint(event) {
    const iid = event.card?.iid ?? event.attackerIid;
    if (iid != null) {
      const suffix = `:card:${iid}`;
      let source = null;
      for (const [key, candidate] of active?.source || []) {
        if (!key.endsWith(suffix)) continue;
        if (source && source !== candidate) throw new Error(`Multiple source anchors for card ${iid}`);
        source = candidate;
      }
      if (source) return source;
    }
    const side = event.card?.ownerSide || event.attacker?.ownerSide || event.side;
    const area = event.fromArea || "field";
    return point(zone(side, area));
  }

  function landing(side, area) {
    const at = point(zone(side, area));
    if (!at || !["field", "base", "resolving"].includes(area)) return at;
    const list = at.el.querySelector(area === "resolving" ? ".resolving-cards" : ":scope > .zone-cards");
    if (!list) throw new Error(`Missing zone-cards for ${side}:${area}`);
    const cards = Array.from(list.querySelectorAll(":scope > .card"));
    const incoming = active?.event?.type === "zone_move" && active.event.toArea === area &&
      String(active.event.side) === String(side) ? active.event.card?.iid : null;
    if (incoming != null) {
      const target = cards.find((el) => el.getAttribute("data-board-card-anchor") === `${side}:card:${incoming}`);
      if (target) return elementPoint(target, board.getBoundingClientRect());
    }
    if (area === "resolving") {
      const empty = list.querySelector(".resolving-slot");
      if (empty) return elementPoint(empty, board.getBoundingClientRect());
      // Measure the actual flex slot, including wrapping, without persisting a
      // second card or guessing its position from the existing card count.
      const slot = document.createElement("i");
      slot.className = "resolving-slot";
      list.append(slot);
      const destination = elementPoint(slot, board.getBoundingClientRect());
      slot.remove();
      return destination;
    }
    if (area !== "resolving" && cards.length >= (area === "base" ? 10 : 5)) return at;

    const bounds = board.getBoundingClientRect();
    const last = cards.at(-1);
    const slot = last || list.querySelector(".zone-empty i, .resolving-slot");
    if (!slot) throw new Error(`Missing landing slot for ${side}:${area}`);
    const rect = slot.getBoundingClientRect();
    const size = elementSize(slot);
    let centerX = rect.left + rect.width / 2;
    if (last) {
      const gap = Number.parseFloat(getComputedStyle(list).columnGap) || 0;
      centerX += size.width / 2 + gap + size.width / 2;
    }
    return {
      ...at,
      x: (centerX - bounds.left) / bounds.width,
      y: (rect.top + rect.height / 2 - bounds.top) / bounds.height,
      ...size,
      landingWidth: size.width,
      landingHeight: size.height,
      el: slot,
    };
  }

  function animate(el, frames, options) {
    if (!el || !fullMotion()) return;
    const animation = el.animate(frames, { fill: "none", ...options });
    animations.add(animation);
    animation.onfinish = () => {
      if (options.fill !== "both") { animations.delete(animation); animation.cancel(); }
    };
    animation.oncancel = () => animations.delete(animation);
    return animation;
  }

  function pulse(el, healing = false) {
    animate(el, [{ filter: "brightness(1)" }, { filter: `brightness(${healing ? 1.5 : 2})`, offset: .18 },
      { filter: "brightness(1)" }], { duration: 340 });
  }

  function shake(strength) {
    animate(board, [{ translate: "0 0" }, { translate: `${-strength}px 1px`, offset: .18 },
      { translate: `${strength}px -1px`, offset: .36 }, { translate: `${-strength / 2}px 0`, offset: .6 },
      { translate: "0 0" }], { duration: 220 });
  }

  function fly(el, from, to, duration, delay = 0, options = { arrive: false, rested: false }) {
    if (!el || !from || !to || !board) return;
    const rect = board.getBoundingClientRect();
    const x = from.x * rect.width, y = from.y * rect.height;
    const dx = (to.x - from.x) * rect.width, dy = (to.y - from.y) * rect.height;
    const arc = Math.min(90, Math.hypot(dx, dy) * .18);
    const sourceIsCard = from.el?.classList.contains("card");
    const sourceSize = sourceIsCard ? from : elementSize(el);
    const width = options.arrive
      ? sourceSize.width || el.offsetWidth
      : sourceIsCard ? from.rectWidth || from.width : el.offsetWidth;
    const height = options.arrive ? sourceSize.height || el.offsetHeight : width * 1.42;
    const startOpacity = sourceIsCard ? from.opacity : 0;
    el.classList.add("fx-flight");
    el.style.left = `${x}px`; el.style.top = `${y}px`;
    el.style.width = `${width}px`; el.style.height = `${height}px`;
    if (options.arrive) {
      const endWidth = to.width || to.landingWidth || width;
      const endHeight = to.height || to.landingHeight || height;
      const startScaleX = width / endWidth;
      const startScaleY = height / endHeight;
      const startAngle = sourceIsCard ? from.angle : from.angle || 0;
      const endAngle = options.rested ? 8 : 0;
      const transform = (px, py, scaleX, scaleY, angle) =>
        `translate(calc(-50% + ${px}px), calc(-50% + ${py}px)) rotate(${angle}deg) scale(${scaleX}, ${scaleY})`;
      el.style.width = `${endWidth}px`;
      el.style.height = `${endHeight}px`;
      el.style.opacity = String(Number.isFinite(startOpacity) ? startOpacity : 1);
      // One timing curve over one quadratic arc. Per-waypoint ease-outs brake
      // to zero inside the flight and then restart at the next segment.
      const opacity = Number.isFinite(startOpacity) ? startOpacity : 1;
      const frames = Array.from({ length: 25 }, (_, index) => {
        const progress = index / 24;
        return {
          transform: transform(dx * progress, dy * progress - 2 * arc * progress * (1 - progress),
            startScaleX + (1 - startScaleX) * progress, startScaleY + (1 - startScaleY) * progress,
            startAngle + (endAngle - startAngle) * progress),
          opacity: opacity + (1 - opacity) * progress,
          offset: progress,
        };
      });
      animate(el, frames, { duration, delay, fill: "both", easing: "cubic-bezier(.22,.68,.32,1)" });
      return;
    }

    // Preserve the existing transient path for attacks and draws.
    const endScale = to.landingWidth ? to.landingWidth / width : 1;
    const transform = (px, py, scale, angle) => `translate(calc(-50% + ${px}px), calc(-50% + ${py}px)) scale(${scale}) rotate(${angle}deg)`;
    animate(el, [{ transform: transform(0, 0, .78, -7), opacity: 0 },
      { transform: transform(dx * .15, dy * .15 - arc * .4, 1, -4), opacity: 1, offset: .15 },
      { transform: transform(dx * .55, dy * .55 - arc, (1 + endScale) * .56, 4), opacity: 1, offset: .55 },
      { transform: transform(dx, dy, endScale, 0), opacity: 1, offset: .86 },
      { transform: transform(dx, dy, endScale, 0), opacity: 0 }],
    { duration, delay, fill: "both", easing: "cubic-bezier(.2,.6,.25,1)" });
  }

  function schedule(name, at, delay = 0, size = 1, angle = 0) {
    if (!at || !fullMotion() || gpuFailed) return;
    const token = active, generation = cancellation;
    loadRuntime().then(() => loadEffect(name)).then((effect) => {
      if (!board || active !== token || generation !== cancellation || !fullMotion() || gpuFailed) return;
      const due = token.started + delay;
      const end = Math.min(token.started + token.duration - 45,
        manifest.effects[name].durationMs ? due + manifest.effects[name].durationMs : Infinity);
      if (performance.now() > end - 100) { skippedLate++; return; }
      // All handles in a queue event share one theme (victory has two origins).
      colorGrade = manifest.effects[name].colorMatrix || identityGrade;
      board.querySelector(`.board-animation-layer[data-fx-event="${token.key}"]`)?.classList.add("fx-particles");
      handles.push({ effect, name, point: at, due, end, size, angle, handle: null });
      wake();
    }).catch(report);
  }

  function draw(now) {
    raf = 0;
    if (!board || !fullMotion() || !handles.length || gpuFailed) return;
    resize();
    const rect = board.getBoundingClientRect();
    for (let i = handles.length - 1; i >= 0; i--) {
      const item = handles[i];
      if (now >= item.end) { item.handle?.stop(); handles.splice(i, 1); continue; }
      if (!item.handle && now >= item.due) {
        item.handle = context.play(item.effect, (item.point.x - .5) * rect.width, (.5 - item.point.y) * rect.height, 0);
        const definition = manifest.effects[item.name];
        const scale = definition.scale * item.size * Math.min(1.6, Math.max(.65, rect.height / 850));
        item.handle.setScale(scale, scale, scale);
        item.handle.setRotation(definition.rotationX || 0, 0, item.angle);
        item.handle.setSpeed(definition.speed || 1);
        if (definition.color) item.handle.setAllColor(...definition.color);
        const age = Math.max(0, now - item.due);
        // Native setFrame already advances with the handle's playback speed.
        if (age > 30) item.handle.setFrame(age * .06);
        renderedEvents++;
      }
      if (item.handle && item.end - now < 120) {
        const rgba = [...(manifest.effects[item.name].color || [255, 255, 255, 255])];
        rgba[3] = Math.round(rgba[3] * Math.max(0, (item.end - now) / 120));
        item.handle.setAllColor(...rgba);
      }
    }
    const delta = lastFrame ? Math.min(3, (now - lastFrame) * .06) : 1;
    lastFrame = now;
    context.update(delta);
    renderParticles(); frameCount++;
    if (handles.length) raf = requestAnimationFrame(draw);
    else clearCanvas();
  }

  function renderParticles() {
    gl.bindFramebuffer(gl.FRAMEBUFFER, compositor.frame);
    gl.depthMask(true); gl.colorMask(true, true, true, true); gl.disable(gl.SCISSOR_TEST);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    context.draw(); composite();
  }

  function wake() { if (!raf) { lastFrame = 0; raf = requestAnimationFrame(draw); } }
  function clearCanvas() { if (gl && !gl.isContextLost()) gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT); }
  function stop() {
    cancellation++;
    cancelAnimationFrame(raf); raf = 0;
    for (const item of handles) item.handle?.stop();
    handles.length = 0;
    for (const animation of animations) {
      // A cancelled flight must not expose its inline start position again.
      const target = animation.effect?.target;
      if (target?.classList.contains("fx-flight")) target.style.opacity = "0";
      animation.cancel();
    }
    animations.clear();
    clearCanvas(); resetTilt();
  }

  function onEventStart(event, duration) {
    stop();
    active = { event, key: eventKey(event), duration, started: performance.now(), source: anchors(), presented: false };
  }
  function onEventEnd(event) {
    if (!event || active?.event === event) { stop(); active = null; releaseIdleWaiters(); }
  }

  function beforeRender() {
    handPositions = new Map();
    if (!board || !fullMotion()) return;
    for (const slot of board.querySelectorAll(".hand-slot")) {
      const rect = slot.getBoundingClientRect();
      handPositions.set(slot, { x: rect.left, y: rect.top });
      handAnimations.get(slot)?.cancel();
    }
  }

  function reflowHands() {
    for (const [slot, first] of handPositions) {
      if (!slot.isConnected || !board?.contains(slot)) continue;
      const last = slot.getBoundingClientRect(), dx = first.x - last.left, dy = first.y - last.top;
      if (Math.abs(dx) + Math.abs(dy) < 1) continue;
      const animation = animate(slot, [{ translate: `${dx}px ${dy}px` }, { translate: "0 0" }],
        { duration: 170, easing: "cubic-bezier(.2,.7,.2,1)" });
      if (animation) handAnimations.set(slot, animation);
    }
    handPositions.clear();
  }

  function present() {
    if (!active || active.presented || !board || !fullMotion()) return;
    active.presented = true;
    const e = active.event;
    // This queue slot explains the rule. Particles belong to its actual targets.
    if (e.type === "effect") return;
    const remaining = Math.max(0, active.duration - (performance.now() - active.started) - 45);
    if (remaining < 100) return;
    const source = sourcePoint(e);
    const target = point(targetKey(e), zone(e.targetSide || e.side, "field"));
    // Position belongs to the affected card; destruction style belongs to its
    // cause. Never borrow the victim's color or a previous queue event's source.
    const subject = e.type === "destroy" ? e.sourceCard :
      e.type === "block" ? e.blocker : e.type === "attack" ? e.attacker : e.card;
    const color = subject?.faceDown ? "COLORLESS" : subject?.manaColor || "COLORLESS";
    const palette = {RED: "#f8a06e", BLUE: "#81d8fa", YELLOW: "#f4d77b", GREEN: "#9bdb96",
      PURPLE: "#c1a1e9", WHITE: "#e4edf4", COLORLESS: "#aebbc7"};
    if (!palette[color]) throw new Error(`Unsupported public card FX color: ${color}`);
    const layer = board.querySelector(`.board-animation-layer[data-fx-event="${active.key}"]`);
    if (layer) { layer.dataset.fxColor = color.toLowerCase(); layer.style.setProperty("--fx-accent", palette[color]); }
    if (e.type === "attack") {
      // Declaration precedes Flash/blocking. Only resolved damage owns a hit.
      fly(board.querySelector(".board-attack:not(.persistent) .board-attack-projectile"), source, target, Math.min(650, remaining));
      pulse(source?.el);
    } else if (e.type === "block") {
      const clash = source && target ? { x: (source.x + target.x) / 2, y: (source.y + target.y) / 2 } : target;
      const shell = board.querySelector(".board-clash");
      if (shell && source && target) {
        for (const [prefix, at] of [["from", source], ["to", target], ["mid", clash]]) {
          shell.style.setProperty(`--${prefix}-x`, `${at.x * 100}%`);
          shell.style.setProperty(`--${prefix}-y`, `${at.y * 100}%`);
        }
        const rect = board.getBoundingClientRect();
        shell.style.setProperty("--attack-angle", `${Math.atan2((target.y - source.y) * rect.height,
          (target.x - source.x) * rect.width) * 180 / Math.PI}deg`);
      }
      schedule(`block-${color.toLowerCase()}`, clash, 300); pulse(target?.el);
    } else if (e.type === "damage") {
      schedule(e.targetKind === "force" ? "force-hit" : "hit", target, 0, Math.min(1.2, .75 + (e.amount || 1) * .1));
      // The native emitter owns the strike. A separate whole-target flash and
      // shake at t=0 reads as an earlier hit while its native particles develop.
    } else if (e.type === "heal") {
      schedule("heal", target, 0); pulse(target?.el, true);
    } else if (e.type === "destroy") {
      const shell = board.querySelector(".board-destroy");
      if (shell && source) { shell.style.left = `${source.x * 100}%`; shell.style.top = `${source.y * 100}%`; }
      if (shell && source?.el?.classList.contains("card")) {
        shell.style.width = `${source.width}px`; shell.style.height = `${source.height}px`;
      }
      if (["battle", "effect", "self"].includes(e.cause)) {
        board.querySelector(".board-destroy-card")?.classList.add("fx-dissolving");
        schedule(`destroy-${color.toLowerCase()}`, source, 100, 1.05); shake(2);
      }
    } else if (e.type === "zone_move") {
      const destination = landing(e.side, e.toArea);
      fly(board.querySelector(".board-zone-move-card"), source, destination, Math.min(780, remaining), 0,
        { arrive: ["field", "base", "resolving"].includes(e.toArea), rested: Boolean(e.card?.rested) });
    } else if (e.type === "draw") {
      const from = point(zone(e.side, "deck")), to = point(zone(e.side, "hand"));
      board.querySelectorAll(".board-draw-card").forEach((el, index) => fly(el, from, to, Math.min(560, remaining - index * 60), index * 60));
    } else if (e.type === "effect_target") {
      const key = targetKey(e), affected = point(key);
      const marker = board.querySelector(".board-effect-target");
      if (!affected) {
        marker?.remove();
        report(new Error(`Missing public effect target anchor (${key || "unspecified"}, event ${active.key})`));
        return;
      }
      if (marker) { marker.style.left = `${affected.x * 100}%`; marker.style.top = `${affected.y * 100}%`; }
      schedule("target", affected, 0, .65); pulse(affected.el);
    } else if (e.type === "refresh") {
      pulse(point(zone(e.side, "base"))?.el, true);
    } else if (e.type === "game_result" && e.winnerSide === humanSide) {
      schedule("victory", { x: .35, y: .45 }, 0, 1.2);
      schedule("victory", { x: .65, y: .45 }, 220, 1.2);
    }
  }

  function resetTilt() {
    cancelAnimationFrame(pointerFrame); pointerFrame = 0;
    if (!tilt) return;
    tilt.classList.remove("fx-tilting");
    for (const name of ["--fx-rx", "--fx-ry", "--fx-x", "--fx-y"]) tilt.style.removeProperty(name);
    tilt = null;
  }

  function pointerMove(event) {
    if (!fullMotion() || !hover.matches || app.classList.contains("bless-dragging") || event.buttons) { resetTilt(); return; }
    const el = event.target.closest('.hand-fan.bottom .card[data-fx-face="up"], .catalog-art');
    if (!el || el.closest(".modal-backdrop")) { resetTilt(); return; }
    if (tilt !== el) { resetTilt(); tilt = el; }
    cancelAnimationFrame(pointerFrame);
    pointerFrame = requestAnimationFrame(() => {
      pointerFrame = 0;
      if (!el.isConnected || tilt !== el) return;
      const rect = el.getBoundingClientRect();
      const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
      el.style.setProperty("--fx-rx", `${(0.5 - y) * 9}deg`);
      el.style.setProperty("--fx-ry", `${(x - 0.5) * 9}deg`);
      el.style.setProperty("--fx-x", `${x * 100}%`); el.style.setProperty("--fx-y", `${y * 100}%`);
      el.classList.add("fx-tilting");
    });
  }

  function afterRender(element, options = {}) {
    reduced = Boolean(options.reducedMotion);
    humanSide = options.humanSide || "P1";
    if (app !== element) {
      if (app) { app.removeEventListener("pointermove", pointerMove); app.removeEventListener("pointerleave", resetTilt); }
      app = element;
      app.addEventListener("pointermove", pointerMove, { passive: true });
      app.addEventListener("pointerleave", resetTilt);
    }
    app.classList.toggle("fx-reduced", reduced || systemMotion.matches);
    const next = options.live ? app.querySelector(".duel-board:not(.replay-duel-board)") : null;
    if (next !== board) { stop(); board = next; if (canvas) { canvas.remove(); if (board) board.append(canvas); } }
    if (!board) { active = null; releaseIdleWaiters(); return; }
    showStatus();
    if (!fullMotion()) { stop(); if (active) active.presented = true; return; }
    loadRuntime();
    resize();
    reflowHands();
    // Layout has already refreshed synchronously; presentation starts once per queue event.
    present();
  }

  function motionChanged() {
    app?.classList.toggle("fx-reduced", reduced || systemMotion.matches);
    stop();
    // Do not replay an event missed while the window was hidden or motion was disabled.
    if (active) active.presented = true;
  }
  systemMotion.addEventListener("change", motionChanged);
  document.addEventListener("visibilitychange", motionChanged);
  root.addEventListener("resize", resize);
  root.ZZFx = {
    prepare, eventKey, onEventStart, onEventEnd, beforeRender, afterRender,
    inspect: () => ({ phase, initializationMs, ready: phase === "ready" && !gpuFailed, loadedEffects: effects.size, activeHandles: handles.length,
      activeEffects: handles.map(item => item.name),
      activeOrigins: handles.map(item => ({ name: item.name, x: item.point.x, y: item.point.y })),
      colorGrade: [...colorGrade],
      running: Boolean(raf), renderedEvents, skippedLate, frames: frameCount, errors: [...failures] }),
  };
})(globalThis);
