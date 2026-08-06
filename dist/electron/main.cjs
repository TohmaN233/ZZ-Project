var __getOwnPropNames = Object.getOwnPropertyNames;
var __commonJS = (cb, mod) => function __require() {
  return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};

// node_modules/ms/index.js
var require_ms = __commonJS({
  "node_modules/ms/index.js"(exports2, module2) {
    var s = 1e3;
    var m = s * 60;
    var h = m * 60;
    var d = h * 24;
    var w = d * 7;
    var y = d * 365.25;
    module2.exports = function(val, options) {
      options = options || {};
      var type = typeof val;
      if (type === "string" && val.length > 0) {
        return parse(val);
      } else if (type === "number" && isFinite(val)) {
        return options.long ? fmtLong(val) : fmtShort(val);
      }
      throw new Error(
        "val is not a non-empty string or a valid number. val=" + JSON.stringify(val)
      );
    };
    function parse(str) {
      str = String(str);
      if (str.length > 100) {
        return;
      }
      var match = /^(-?(?:\d+)?\.?\d+) *(milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w|years?|yrs?|y)?$/i.exec(
        str
      );
      if (!match) {
        return;
      }
      var n = parseFloat(match[1]);
      var type = (match[2] || "ms").toLowerCase();
      switch (type) {
        case "years":
        case "year":
        case "yrs":
        case "yr":
        case "y":
          return n * y;
        case "weeks":
        case "week":
        case "w":
          return n * w;
        case "days":
        case "day":
        case "d":
          return n * d;
        case "hours":
        case "hour":
        case "hrs":
        case "hr":
        case "h":
          return n * h;
        case "minutes":
        case "minute":
        case "mins":
        case "min":
        case "m":
          return n * m;
        case "seconds":
        case "second":
        case "secs":
        case "sec":
        case "s":
          return n * s;
        case "milliseconds":
        case "millisecond":
        case "msecs":
        case "msec":
        case "ms":
          return n;
        default:
          return void 0;
      }
    }
    function fmtShort(ms) {
      var msAbs = Math.abs(ms);
      if (msAbs >= d) {
        return Math.round(ms / d) + "d";
      }
      if (msAbs >= h) {
        return Math.round(ms / h) + "h";
      }
      if (msAbs >= m) {
        return Math.round(ms / m) + "m";
      }
      if (msAbs >= s) {
        return Math.round(ms / s) + "s";
      }
      return ms + "ms";
    }
    function fmtLong(ms) {
      var msAbs = Math.abs(ms);
      if (msAbs >= d) {
        return plural(ms, msAbs, d, "day");
      }
      if (msAbs >= h) {
        return plural(ms, msAbs, h, "hour");
      }
      if (msAbs >= m) {
        return plural(ms, msAbs, m, "minute");
      }
      if (msAbs >= s) {
        return plural(ms, msAbs, s, "second");
      }
      return ms + " ms";
    }
    function plural(ms, msAbs, n, name) {
      var isPlural = msAbs >= n * 1.5;
      return Math.round(ms / n) + " " + name + (isPlural ? "s" : "");
    }
  }
});

// node_modules/debug/src/common.js
var require_common = __commonJS({
  "node_modules/debug/src/common.js"(exports2, module2) {
    function setup(env) {
      createDebug.debug = createDebug;
      createDebug.default = createDebug;
      createDebug.coerce = coerce;
      createDebug.disable = disable;
      createDebug.enable = enable;
      createDebug.enabled = enabled;
      createDebug.humanize = require_ms();
      createDebug.destroy = destroy;
      Object.keys(env).forEach((key) => {
        createDebug[key] = env[key];
      });
      createDebug.names = [];
      createDebug.skips = [];
      createDebug.formatters = {};
      function selectColor(namespace) {
        let hash = 0;
        for (let i = 0; i < namespace.length; i++) {
          hash = (hash << 5) - hash + namespace.charCodeAt(i);
          hash |= 0;
        }
        return createDebug.colors[Math.abs(hash) % createDebug.colors.length];
      }
      createDebug.selectColor = selectColor;
      function createDebug(namespace) {
        let prevTime;
        let enableOverride = null;
        let namespacesCache;
        let enabledCache;
        function debug(...args) {
          if (!debug.enabled) {
            return;
          }
          const self = debug;
          const curr = Number(/* @__PURE__ */ new Date());
          const ms = curr - (prevTime || curr);
          self.diff = ms;
          self.prev = prevTime;
          self.curr = curr;
          prevTime = curr;
          args[0] = createDebug.coerce(args[0]);
          if (typeof args[0] !== "string") {
            args.unshift("%O");
          }
          let index = 0;
          args[0] = args[0].replace(/%([a-zA-Z%])/g, (match, format) => {
            if (match === "%%") {
              return "%";
            }
            index++;
            const formatter = createDebug.formatters[format];
            if (typeof formatter === "function") {
              const val = args[index];
              match = formatter.call(self, val);
              args.splice(index, 1);
              index--;
            }
            return match;
          });
          createDebug.formatArgs.call(self, args);
          const logFn = self.log || createDebug.log;
          logFn.apply(self, args);
        }
        debug.namespace = namespace;
        debug.useColors = createDebug.useColors();
        debug.color = createDebug.selectColor(namespace);
        debug.extend = extend;
        debug.destroy = createDebug.destroy;
        Object.defineProperty(debug, "enabled", {
          enumerable: true,
          configurable: false,
          get: () => {
            if (enableOverride !== null) {
              return enableOverride;
            }
            if (namespacesCache !== createDebug.namespaces) {
              namespacesCache = createDebug.namespaces;
              enabledCache = createDebug.enabled(namespace);
            }
            return enabledCache;
          },
          set: (v) => {
            enableOverride = v;
          }
        });
        if (typeof createDebug.init === "function") {
          createDebug.init(debug);
        }
        return debug;
      }
      function extend(namespace, delimiter) {
        const newDebug = createDebug(this.namespace + (typeof delimiter === "undefined" ? ":" : delimiter) + namespace);
        newDebug.log = this.log;
        return newDebug;
      }
      function enable(namespaces) {
        createDebug.save(namespaces);
        createDebug.namespaces = namespaces;
        createDebug.names = [];
        createDebug.skips = [];
        const split = (typeof namespaces === "string" ? namespaces : "").trim().replace(/\s+/g, ",").split(",").filter(Boolean);
        for (const ns of split) {
          if (ns[0] === "-") {
            createDebug.skips.push(ns.slice(1));
          } else {
            createDebug.names.push(ns);
          }
        }
      }
      function matchesTemplate(search, template) {
        let searchIndex = 0;
        let templateIndex = 0;
        let starIndex = -1;
        let matchIndex = 0;
        while (searchIndex < search.length) {
          if (templateIndex < template.length && (template[templateIndex] === search[searchIndex] || template[templateIndex] === "*")) {
            if (template[templateIndex] === "*") {
              starIndex = templateIndex;
              matchIndex = searchIndex;
              templateIndex++;
            } else {
              searchIndex++;
              templateIndex++;
            }
          } else if (starIndex !== -1) {
            templateIndex = starIndex + 1;
            matchIndex++;
            searchIndex = matchIndex;
          } else {
            return false;
          }
        }
        while (templateIndex < template.length && template[templateIndex] === "*") {
          templateIndex++;
        }
        return templateIndex === template.length;
      }
      function disable() {
        const namespaces = [
          ...createDebug.names,
          ...createDebug.skips.map((namespace) => "-" + namespace)
        ].join(",");
        createDebug.enable("");
        return namespaces;
      }
      function enabled(name) {
        for (const skip of createDebug.skips) {
          if (matchesTemplate(name, skip)) {
            return false;
          }
        }
        for (const ns of createDebug.names) {
          if (matchesTemplate(name, ns)) {
            return true;
          }
        }
        return false;
      }
      function coerce(val) {
        if (val instanceof Error) {
          return val.stack || val.message;
        }
        return val;
      }
      function destroy() {
        console.warn("Instance method `debug.destroy()` is deprecated and no longer does anything. It will be removed in the next major version of `debug`.");
      }
      createDebug.enable(createDebug.load());
      return createDebug;
    }
    module2.exports = setup;
  }
});

// node_modules/debug/src/browser.js
var require_browser = __commonJS({
  "node_modules/debug/src/browser.js"(exports2, module2) {
    exports2.formatArgs = formatArgs;
    exports2.save = save;
    exports2.load = load;
    exports2.useColors = useColors;
    exports2.storage = localstorage();
    exports2.destroy = /* @__PURE__ */ (() => {
      let warned = false;
      return () => {
        if (!warned) {
          warned = true;
          console.warn("Instance method `debug.destroy()` is deprecated and no longer does anything. It will be removed in the next major version of `debug`.");
        }
      };
    })();
    exports2.colors = [
      "#0000CC",
      "#0000FF",
      "#0033CC",
      "#0033FF",
      "#0066CC",
      "#0066FF",
      "#0099CC",
      "#0099FF",
      "#00CC00",
      "#00CC33",
      "#00CC66",
      "#00CC99",
      "#00CCCC",
      "#00CCFF",
      "#3300CC",
      "#3300FF",
      "#3333CC",
      "#3333FF",
      "#3366CC",
      "#3366FF",
      "#3399CC",
      "#3399FF",
      "#33CC00",
      "#33CC33",
      "#33CC66",
      "#33CC99",
      "#33CCCC",
      "#33CCFF",
      "#6600CC",
      "#6600FF",
      "#6633CC",
      "#6633FF",
      "#66CC00",
      "#66CC33",
      "#9900CC",
      "#9900FF",
      "#9933CC",
      "#9933FF",
      "#99CC00",
      "#99CC33",
      "#CC0000",
      "#CC0033",
      "#CC0066",
      "#CC0099",
      "#CC00CC",
      "#CC00FF",
      "#CC3300",
      "#CC3333",
      "#CC3366",
      "#CC3399",
      "#CC33CC",
      "#CC33FF",
      "#CC6600",
      "#CC6633",
      "#CC9900",
      "#CC9933",
      "#CCCC00",
      "#CCCC33",
      "#FF0000",
      "#FF0033",
      "#FF0066",
      "#FF0099",
      "#FF00CC",
      "#FF00FF",
      "#FF3300",
      "#FF3333",
      "#FF3366",
      "#FF3399",
      "#FF33CC",
      "#FF33FF",
      "#FF6600",
      "#FF6633",
      "#FF9900",
      "#FF9933",
      "#FFCC00",
      "#FFCC33"
    ];
    function useColors() {
      if (typeof window !== "undefined" && window.process && (window.process.type === "renderer" || window.process.__nwjs)) {
        return true;
      }
      if (typeof navigator !== "undefined" && navigator.userAgent && navigator.userAgent.toLowerCase().match(/(edge|trident)\/(\d+)/)) {
        return false;
      }
      let m;
      return typeof document !== "undefined" && document.documentElement && document.documentElement.style && document.documentElement.style.WebkitAppearance || // Is firebug? http://stackoverflow.com/a/398120/376773
      typeof window !== "undefined" && window.console && (window.console.firebug || window.console.exception && window.console.table) || // Is firefox >= v31?
      // https://developer.mozilla.org/en-US/docs/Tools/Web_Console#Styling_messages
      typeof navigator !== "undefined" && navigator.userAgent && (m = navigator.userAgent.toLowerCase().match(/firefox\/(\d+)/)) && parseInt(m[1], 10) >= 31 || // Double check webkit in userAgent just in case we are in a worker
      typeof navigator !== "undefined" && navigator.userAgent && navigator.userAgent.toLowerCase().match(/applewebkit\/(\d+)/);
    }
    function formatArgs(args) {
      args[0] = (this.useColors ? "%c" : "") + this.namespace + (this.useColors ? " %c" : " ") + args[0] + (this.useColors ? "%c " : " ") + "+" + module2.exports.humanize(this.diff);
      if (!this.useColors) {
        return;
      }
      const c = "color: " + this.color;
      args.splice(1, 0, c, "color: inherit");
      let index = 0;
      let lastC = 0;
      args[0].replace(/%[a-zA-Z%]/g, (match) => {
        if (match === "%%") {
          return;
        }
        index++;
        if (match === "%c") {
          lastC = index;
        }
      });
      args.splice(lastC, 0, c);
    }
    exports2.log = console.debug || console.log || (() => {
    });
    function save(namespaces) {
      try {
        if (namespaces) {
          exports2.storage.setItem("debug", namespaces);
        } else {
          exports2.storage.removeItem("debug");
        }
      } catch (error) {
      }
    }
    function load() {
      let r;
      try {
        r = exports2.storage.getItem("debug") || exports2.storage.getItem("DEBUG");
      } catch (error) {
      }
      if (!r && typeof process !== "undefined" && "env" in process) {
        r = process.env.DEBUG;
      }
      return r;
    }
    function localstorage() {
      try {
        return localStorage;
      } catch (error) {
      }
    }
    module2.exports = require_common()(exports2);
    var { formatters } = module2.exports;
    formatters.j = function(v) {
      try {
        return JSON.stringify(v);
      } catch (error) {
        return "[UnexpectedJSONParseError]: " + error.message;
      }
    };
  }
});

// node_modules/debug/src/node.js
var require_node = __commonJS({
  "node_modules/debug/src/node.js"(exports2, module2) {
    var tty = require("tty");
    var util = require("util");
    exports2.init = init;
    exports2.log = log;
    exports2.formatArgs = formatArgs;
    exports2.save = save;
    exports2.load = load;
    exports2.useColors = useColors;
    exports2.destroy = util.deprecate(
      () => {
      },
      "Instance method `debug.destroy()` is deprecated and no longer does anything. It will be removed in the next major version of `debug`."
    );
    exports2.colors = [6, 2, 3, 4, 5, 1];
    try {
      const supportsColor = require("supports-color");
      if (supportsColor && (supportsColor.stderr || supportsColor).level >= 2) {
        exports2.colors = [
          20,
          21,
          26,
          27,
          32,
          33,
          38,
          39,
          40,
          41,
          42,
          43,
          44,
          45,
          56,
          57,
          62,
          63,
          68,
          69,
          74,
          75,
          76,
          77,
          78,
          79,
          80,
          81,
          92,
          93,
          98,
          99,
          112,
          113,
          128,
          129,
          134,
          135,
          148,
          149,
          160,
          161,
          162,
          163,
          164,
          165,
          166,
          167,
          168,
          169,
          170,
          171,
          172,
          173,
          178,
          179,
          184,
          185,
          196,
          197,
          198,
          199,
          200,
          201,
          202,
          203,
          204,
          205,
          206,
          207,
          208,
          209,
          214,
          215,
          220,
          221
        ];
      }
    } catch (error) {
    }
    exports2.inspectOpts = Object.keys(process.env).filter((key) => {
      return /^debug_/i.test(key);
    }).reduce((obj, key) => {
      const prop = key.substring(6).toLowerCase().replace(/_([a-z])/g, (_, k) => {
        return k.toUpperCase();
      });
      let val = process.env[key];
      if (/^(yes|on|true|enabled)$/i.test(val)) {
        val = true;
      } else if (/^(no|off|false|disabled)$/i.test(val)) {
        val = false;
      } else if (val === "null") {
        val = null;
      } else {
        val = Number(val);
      }
      obj[prop] = val;
      return obj;
    }, {});
    function useColors() {
      return "colors" in exports2.inspectOpts ? Boolean(exports2.inspectOpts.colors) : tty.isatty(process.stderr.fd);
    }
    function formatArgs(args) {
      const { namespace: name, useColors: useColors2 } = this;
      if (useColors2) {
        const c = this.color;
        const colorCode = "\x1B[3" + (c < 8 ? c : "8;5;" + c);
        const prefix = `  ${colorCode};1m${name} \x1B[0m`;
        args[0] = prefix + args[0].split("\n").join("\n" + prefix);
        args.push(colorCode + "m+" + module2.exports.humanize(this.diff) + "\x1B[0m");
      } else {
        args[0] = getDate() + name + " " + args[0];
      }
    }
    function getDate() {
      if (exports2.inspectOpts.hideDate) {
        return "";
      }
      return (/* @__PURE__ */ new Date()).toISOString() + " ";
    }
    function log(...args) {
      return process.stderr.write(util.formatWithOptions(exports2.inspectOpts, ...args) + "\n");
    }
    function save(namespaces) {
      if (namespaces) {
        process.env.DEBUG = namespaces;
      } else {
        delete process.env.DEBUG;
      }
    }
    function load() {
      return process.env.DEBUG;
    }
    function init(debug) {
      debug.inspectOpts = {};
      const keys = Object.keys(exports2.inspectOpts);
      for (let i = 0; i < keys.length; i++) {
        debug.inspectOpts[keys[i]] = exports2.inspectOpts[keys[i]];
      }
    }
    module2.exports = require_common()(exports2);
    var { formatters } = module2.exports;
    formatters.o = function(v) {
      this.inspectOpts.colors = this.useColors;
      return util.inspect(v, this.inspectOpts).split("\n").map((str) => str.trim()).join(" ");
    };
    formatters.O = function(v) {
      this.inspectOpts.colors = this.useColors;
      return util.inspect(v, this.inspectOpts);
    };
  }
});

// node_modules/debug/src/index.js
var require_src = __commonJS({
  "node_modules/debug/src/index.js"(exports2, module2) {
    if (typeof process === "undefined" || process.type === "renderer" || process.browser === true || process.__nwjs) {
      module2.exports = require_browser();
    } else {
      module2.exports = require_node();
    }
  }
});

// node_modules/agent-base/dist/helpers.js
var require_helpers = __commonJS({
  "node_modules/agent-base/dist/helpers.js"(exports2) {
    "use strict";
    var __createBinding = exports2 && exports2.__createBinding || (Object.create ? (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      var desc = Object.getOwnPropertyDescriptor(m, k);
      if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
        desc = { enumerable: true, get: function() {
          return m[k];
        } };
      }
      Object.defineProperty(o, k2, desc);
    }) : (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      o[k2] = m[k];
    }));
    var __setModuleDefault = exports2 && exports2.__setModuleDefault || (Object.create ? (function(o, v) {
      Object.defineProperty(o, "default", { enumerable: true, value: v });
    }) : function(o, v) {
      o["default"] = v;
    });
    var __importStar = exports2 && exports2.__importStar || function(mod) {
      if (mod && mod.__esModule) return mod;
      var result = {};
      if (mod != null) {
        for (var k in mod) if (k !== "default" && Object.prototype.hasOwnProperty.call(mod, k)) __createBinding(result, mod, k);
      }
      __setModuleDefault(result, mod);
      return result;
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.req = exports2.json = exports2.toBuffer = void 0;
    var http2 = __importStar(require("http"));
    var https = __importStar(require("https"));
    async function toBuffer(stream) {
      let length = 0;
      const chunks = [];
      for await (const chunk of stream) {
        length += chunk.length;
        chunks.push(chunk);
      }
      return Buffer.concat(chunks, length);
    }
    exports2.toBuffer = toBuffer;
    async function json(stream) {
      const buf = await toBuffer(stream);
      const str = buf.toString("utf8");
      try {
        return JSON.parse(str);
      } catch (_err) {
        const err = _err;
        err.message += ` (input: ${str})`;
        throw err;
      }
    }
    exports2.json = json;
    function req(url, opts = {}) {
      const href = typeof url === "string" ? url : url.href;
      const req2 = (href.startsWith("https:") ? https : http2).request(url, opts);
      const promise = new Promise((resolve, reject) => {
        req2.once("response", resolve).once("error", reject).end();
      });
      req2.then = promise.then.bind(promise);
      return req2;
    }
    exports2.req = req;
  }
});

// node_modules/agent-base/dist/index.js
var require_dist = __commonJS({
  "node_modules/agent-base/dist/index.js"(exports2) {
    "use strict";
    var __createBinding = exports2 && exports2.__createBinding || (Object.create ? (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      var desc = Object.getOwnPropertyDescriptor(m, k);
      if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
        desc = { enumerable: true, get: function() {
          return m[k];
        } };
      }
      Object.defineProperty(o, k2, desc);
    }) : (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      o[k2] = m[k];
    }));
    var __setModuleDefault = exports2 && exports2.__setModuleDefault || (Object.create ? (function(o, v) {
      Object.defineProperty(o, "default", { enumerable: true, value: v });
    }) : function(o, v) {
      o["default"] = v;
    });
    var __importStar = exports2 && exports2.__importStar || function(mod) {
      if (mod && mod.__esModule) return mod;
      var result = {};
      if (mod != null) {
        for (var k in mod) if (k !== "default" && Object.prototype.hasOwnProperty.call(mod, k)) __createBinding(result, mod, k);
      }
      __setModuleDefault(result, mod);
      return result;
    };
    var __exportStar = exports2 && exports2.__exportStar || function(m, exports3) {
      for (var p in m) if (p !== "default" && !Object.prototype.hasOwnProperty.call(exports3, p)) __createBinding(exports3, m, p);
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.Agent = void 0;
    var net2 = __importStar(require("net"));
    var http2 = __importStar(require("http"));
    var https_1 = require("https");
    __exportStar(require_helpers(), exports2);
    var INTERNAL = Symbol("AgentBaseInternalState");
    var Agent = class extends http2.Agent {
      constructor(opts) {
        super(opts);
        this[INTERNAL] = {};
      }
      /**
       * Determine whether this is an `http` or `https` request.
       */
      isSecureEndpoint(options) {
        if (options) {
          if (typeof options.secureEndpoint === "boolean") {
            return options.secureEndpoint;
          }
          if (typeof options.protocol === "string") {
            return options.protocol === "https:";
          }
        }
        const { stack } = new Error();
        if (typeof stack !== "string")
          return false;
        return stack.split("\n").some((l) => l.indexOf("(https.js:") !== -1 || l.indexOf("node:https:") !== -1);
      }
      // In order to support async signatures in `connect()` and Node's native
      // connection pooling in `http.Agent`, the array of sockets for each origin
      // has to be updated synchronously. This is so the length of the array is
      // accurate when `addRequest()` is next called. We achieve this by creating a
      // fake socket and adding it to `sockets[origin]` and incrementing
      // `totalSocketCount`.
      incrementSockets(name) {
        if (this.maxSockets === Infinity && this.maxTotalSockets === Infinity) {
          return null;
        }
        if (!this.sockets[name]) {
          this.sockets[name] = [];
        }
        const fakeSocket = new net2.Socket({ writable: false });
        this.sockets[name].push(fakeSocket);
        this.totalSocketCount++;
        return fakeSocket;
      }
      decrementSockets(name, socket) {
        if (!this.sockets[name] || socket === null) {
          return;
        }
        const sockets = this.sockets[name];
        const index = sockets.indexOf(socket);
        if (index !== -1) {
          sockets.splice(index, 1);
          this.totalSocketCount--;
          if (sockets.length === 0) {
            delete this.sockets[name];
          }
        }
      }
      // In order to properly update the socket pool, we need to call `getName()` on
      // the core `https.Agent` if it is a secureEndpoint.
      getName(options) {
        const secureEndpoint = this.isSecureEndpoint(options);
        if (secureEndpoint) {
          return https_1.Agent.prototype.getName.call(this, options);
        }
        return super.getName(options);
      }
      createSocket(req, options, cb) {
        const connectOpts = {
          ...options,
          secureEndpoint: this.isSecureEndpoint(options)
        };
        const name = this.getName(connectOpts);
        const fakeSocket = this.incrementSockets(name);
        Promise.resolve().then(() => this.connect(req, connectOpts)).then((socket) => {
          this.decrementSockets(name, fakeSocket);
          if (socket instanceof http2.Agent) {
            try {
              return socket.addRequest(req, connectOpts);
            } catch (err) {
              return cb(err);
            }
          }
          this[INTERNAL].currentSocket = socket;
          super.createSocket(req, options, cb);
        }, (err) => {
          this.decrementSockets(name, fakeSocket);
          cb(err);
        });
      }
      createConnection() {
        const socket = this[INTERNAL].currentSocket;
        this[INTERNAL].currentSocket = void 0;
        if (!socket) {
          throw new Error("No socket was returned in the `connect()` function");
        }
        return socket;
      }
      get defaultPort() {
        return this[INTERNAL].defaultPort ?? (this.protocol === "https:" ? 443 : 80);
      }
      set defaultPort(v) {
        if (this[INTERNAL]) {
          this[INTERNAL].defaultPort = v;
        }
      }
      get protocol() {
        return this[INTERNAL].protocol ?? (this.isSecureEndpoint() ? "https:" : "http:");
      }
      set protocol(v) {
        if (this[INTERNAL]) {
          this[INTERNAL].protocol = v;
        }
      }
    };
    exports2.Agent = Agent;
  }
});

// node_modules/https-proxy-agent/dist/parse-proxy-response.js
var require_parse_proxy_response = __commonJS({
  "node_modules/https-proxy-agent/dist/parse-proxy-response.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.parseProxyResponse = void 0;
    var debug_1 = __importDefault(require_src());
    var debug = (0, debug_1.default)("https-proxy-agent:parse-proxy-response");
    function parseProxyResponse(socket) {
      return new Promise((resolve, reject) => {
        let buffersLength = 0;
        const buffers = [];
        function read() {
          const b = socket.read();
          if (b)
            ondata(b);
          else
            socket.once("readable", read);
        }
        function cleanup() {
          socket.removeListener("end", onend);
          socket.removeListener("error", onerror);
          socket.removeListener("readable", read);
        }
        function onend() {
          cleanup();
          debug("onend");
          reject(new Error("Proxy connection ended before receiving CONNECT response"));
        }
        function onerror(err) {
          cleanup();
          debug("onerror %o", err);
          reject(err);
        }
        function ondata(b) {
          buffers.push(b);
          buffersLength += b.length;
          const buffered = Buffer.concat(buffers, buffersLength);
          const endOfHeaders = buffered.indexOf("\r\n\r\n");
          if (endOfHeaders === -1) {
            debug("have not received end of HTTP headers yet...");
            read();
            return;
          }
          const headerParts = buffered.slice(0, endOfHeaders).toString("ascii").split("\r\n");
          const firstLine = headerParts.shift();
          if (!firstLine) {
            socket.destroy();
            return reject(new Error("No header received from proxy CONNECT response"));
          }
          const firstLineParts = firstLine.split(" ");
          const statusCode = +firstLineParts[1];
          const statusText = firstLineParts.slice(2).join(" ");
          const headers = {};
          for (const header of headerParts) {
            if (!header)
              continue;
            const firstColon = header.indexOf(":");
            if (firstColon === -1) {
              socket.destroy();
              return reject(new Error(`Invalid header from proxy CONNECT response: "${header}"`));
            }
            const key = header.slice(0, firstColon).toLowerCase();
            const value = header.slice(firstColon + 1).trimStart();
            const current = headers[key];
            if (typeof current === "string") {
              headers[key] = [current, value];
            } else if (Array.isArray(current)) {
              current.push(value);
            } else {
              headers[key] = value;
            }
          }
          debug("got proxy server response: %o %o", firstLine, headers);
          cleanup();
          resolve({
            connect: {
              statusCode,
              statusText,
              headers
            },
            buffered
          });
        }
        socket.on("error", onerror);
        socket.on("end", onend);
        read();
      });
    }
    exports2.parseProxyResponse = parseProxyResponse;
  }
});

// node_modules/https-proxy-agent/dist/index.js
var require_dist2 = __commonJS({
  "node_modules/https-proxy-agent/dist/index.js"(exports2) {
    "use strict";
    var __createBinding = exports2 && exports2.__createBinding || (Object.create ? (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      var desc = Object.getOwnPropertyDescriptor(m, k);
      if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
        desc = { enumerable: true, get: function() {
          return m[k];
        } };
      }
      Object.defineProperty(o, k2, desc);
    }) : (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      o[k2] = m[k];
    }));
    var __setModuleDefault = exports2 && exports2.__setModuleDefault || (Object.create ? (function(o, v) {
      Object.defineProperty(o, "default", { enumerable: true, value: v });
    }) : function(o, v) {
      o["default"] = v;
    });
    var __importStar = exports2 && exports2.__importStar || function(mod) {
      if (mod && mod.__esModule) return mod;
      var result = {};
      if (mod != null) {
        for (var k in mod) if (k !== "default" && Object.prototype.hasOwnProperty.call(mod, k)) __createBinding(result, mod, k);
      }
      __setModuleDefault(result, mod);
      return result;
    };
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.HttpsProxyAgent = void 0;
    var net2 = __importStar(require("net"));
    var tls = __importStar(require("tls"));
    var assert_1 = __importDefault(require("assert"));
    var debug_1 = __importDefault(require_src());
    var agent_base_1 = require_dist();
    var url_1 = require("url");
    var parse_proxy_response_1 = require_parse_proxy_response();
    var debug = (0, debug_1.default)("https-proxy-agent");
    var setServernameFromNonIpHost = (options) => {
      if (options.servername === void 0 && options.host && !net2.isIP(options.host)) {
        return {
          ...options,
          servername: options.host
        };
      }
      return options;
    };
    var HttpsProxyAgent = class extends agent_base_1.Agent {
      constructor(proxy, opts) {
        super(opts);
        this.options = { path: void 0 };
        this.proxy = typeof proxy === "string" ? new url_1.URL(proxy) : proxy;
        this.proxyHeaders = opts?.headers ?? {};
        debug("Creating new HttpsProxyAgent instance: %o", this.proxy.href);
        const host = (this.proxy.hostname || this.proxy.host).replace(/^\[|\]$/g, "");
        const port = this.proxy.port ? parseInt(this.proxy.port, 10) : this.proxy.protocol === "https:" ? 443 : 80;
        this.connectOpts = {
          // Attempt to negotiate http/1.1 for proxy servers that support http/2
          ALPNProtocols: ["http/1.1"],
          ...opts ? omit(opts, "headers") : null,
          host,
          port
        };
      }
      /**
       * Called when the node-core HTTP client library is creating a
       * new HTTP request.
       */
      async connect(req, opts) {
        const { proxy } = this;
        if (!opts.host) {
          throw new TypeError('No "host" provided');
        }
        let socket;
        if (proxy.protocol === "https:") {
          debug("Creating `tls.Socket`: %o", this.connectOpts);
          socket = tls.connect(setServernameFromNonIpHost(this.connectOpts));
        } else {
          debug("Creating `net.Socket`: %o", this.connectOpts);
          socket = net2.connect(this.connectOpts);
        }
        const headers = typeof this.proxyHeaders === "function" ? this.proxyHeaders() : { ...this.proxyHeaders };
        const host = net2.isIPv6(opts.host) ? `[${opts.host}]` : opts.host;
        let payload = `CONNECT ${host}:${opts.port} HTTP/1.1\r
`;
        if (proxy.username || proxy.password) {
          const auth = `${decodeURIComponent(proxy.username)}:${decodeURIComponent(proxy.password)}`;
          headers["Proxy-Authorization"] = `Basic ${Buffer.from(auth).toString("base64")}`;
        }
        headers.Host = `${host}:${opts.port}`;
        if (!headers["Proxy-Connection"]) {
          headers["Proxy-Connection"] = this.keepAlive ? "Keep-Alive" : "close";
        }
        for (const name of Object.keys(headers)) {
          payload += `${name}: ${headers[name]}\r
`;
        }
        const proxyResponsePromise = (0, parse_proxy_response_1.parseProxyResponse)(socket);
        socket.write(`${payload}\r
`);
        const { connect, buffered } = await proxyResponsePromise;
        req.emit("proxyConnect", connect);
        this.emit("proxyConnect", connect, req);
        if (connect.statusCode === 200) {
          req.once("socket", resume);
          if (opts.secureEndpoint) {
            debug("Upgrading socket connection to TLS");
            return tls.connect({
              ...omit(setServernameFromNonIpHost(opts), "host", "path", "port"),
              socket
            });
          }
          return socket;
        }
        socket.destroy();
        const fakeSocket = new net2.Socket({ writable: false });
        fakeSocket.readable = true;
        req.once("socket", (s) => {
          debug("Replaying proxy buffer for failed request");
          (0, assert_1.default)(s.listenerCount("data") > 0);
          s.push(buffered);
          s.push(null);
        });
        return fakeSocket;
      }
    };
    HttpsProxyAgent.protocols = ["http", "https"];
    exports2.HttpsProxyAgent = HttpsProxyAgent;
    function resume(socket) {
      socket.resume();
    }
    function omit(obj, ...keys) {
      const ret = {};
      let key;
      for (key in obj) {
        if (!keys.includes(key)) {
          ret[key] = obj[key];
        }
      }
      return ret;
    }
  }
});

// node_modules/ws/lib/constants.js
var require_constants = __commonJS({
  "node_modules/ws/lib/constants.js"(exports2, module2) {
    "use strict";
    var BINARY_TYPES = ["nodebuffer", "arraybuffer", "fragments"];
    var hasBlob = typeof Blob !== "undefined";
    if (hasBlob) BINARY_TYPES.push("blob");
    module2.exports = {
      BINARY_TYPES,
      CLOSE_TIMEOUT: 3e4,
      EMPTY_BUFFER: Buffer.alloc(0),
      GUID: "258EAFA5-E914-47DA-95CA-C5AB0DC85B11",
      hasBlob,
      kForOnEventAttribute: Symbol("kIsForOnEventAttribute"),
      kListener: Symbol("kListener"),
      kStatusCode: Symbol("status-code"),
      kWebSocket: Symbol("websocket"),
      NOOP: () => {
      }
    };
  }
});

// node_modules/ws/lib/buffer-util.js
var require_buffer_util = __commonJS({
  "node_modules/ws/lib/buffer-util.js"(exports2, module2) {
    "use strict";
    var { EMPTY_BUFFER } = require_constants();
    var FastBuffer = Buffer[Symbol.species];
    function concat(list, totalLength) {
      if (list.length === 0) return EMPTY_BUFFER;
      if (list.length === 1) return list[0];
      const target = Buffer.allocUnsafe(totalLength);
      let offset = 0;
      for (let i = 0; i < list.length; i++) {
        const buf = list[i];
        target.set(buf, offset);
        offset += buf.length;
      }
      if (offset < totalLength) {
        return new FastBuffer(target.buffer, target.byteOffset, offset);
      }
      return target;
    }
    function _mask(source, mask, output, offset, length) {
      for (let i = 0; i < length; i++) {
        output[offset + i] = source[i] ^ mask[i & 3];
      }
    }
    function _unmask(buffer, mask) {
      for (let i = 0; i < buffer.length; i++) {
        buffer[i] ^= mask[i & 3];
      }
    }
    function toArrayBuffer(buf) {
      if (buf.length === buf.buffer.byteLength) {
        return buf.buffer;
      }
      return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length);
    }
    function toBuffer(data) {
      toBuffer.readOnly = true;
      if (Buffer.isBuffer(data)) return data;
      let buf;
      if (data instanceof ArrayBuffer) {
        buf = new FastBuffer(data);
      } else if (ArrayBuffer.isView(data)) {
        buf = new FastBuffer(data.buffer, data.byteOffset, data.byteLength);
      } else {
        buf = Buffer.from(data);
        toBuffer.readOnly = false;
      }
      return buf;
    }
    module2.exports = {
      concat,
      mask: _mask,
      toArrayBuffer,
      toBuffer,
      unmask: _unmask
    };
    if (!process.env.WS_NO_BUFFER_UTIL) {
      try {
        const bufferUtil = require("bufferutil");
        module2.exports.mask = function(source, mask, output, offset, length) {
          if (length < 48) _mask(source, mask, output, offset, length);
          else bufferUtil.mask(source, mask, output, offset, length);
        };
        module2.exports.unmask = function(buffer, mask) {
          if (buffer.length < 32) _unmask(buffer, mask);
          else bufferUtil.unmask(buffer, mask);
        };
      } catch (e) {
      }
    }
  }
});

// node_modules/ws/lib/limiter.js
var require_limiter = __commonJS({
  "node_modules/ws/lib/limiter.js"(exports2, module2) {
    "use strict";
    var kDone = Symbol("kDone");
    var kRun = Symbol("kRun");
    var Limiter = class {
      /**
       * Creates a new `Limiter`.
       *
       * @param {Number} [concurrency=Infinity] The maximum number of jobs allowed
       *     to run concurrently
       */
      constructor(concurrency) {
        this[kDone] = () => {
          this.pending--;
          this[kRun]();
        };
        this.concurrency = concurrency || Infinity;
        this.jobs = [];
        this.pending = 0;
      }
      /**
       * Adds a job to the queue.
       *
       * @param {Function} job The job to run
       * @public
       */
      add(job) {
        this.jobs.push(job);
        this[kRun]();
      }
      /**
       * Removes a job from the queue and runs it if possible.
       *
       * @private
       */
      [kRun]() {
        if (this.pending === this.concurrency) return;
        if (this.jobs.length) {
          const job = this.jobs.shift();
          this.pending++;
          job(this[kDone]);
        }
      }
    };
    module2.exports = Limiter;
  }
});

// node_modules/ws/lib/permessage-deflate.js
var require_permessage_deflate = __commonJS({
  "node_modules/ws/lib/permessage-deflate.js"(exports2, module2) {
    "use strict";
    var zlib = require("zlib");
    var bufferUtil = require_buffer_util();
    var Limiter = require_limiter();
    var { kStatusCode } = require_constants();
    var FastBuffer = Buffer[Symbol.species];
    var TRAILER = Buffer.from([0, 0, 255, 255]);
    var kPerMessageDeflate = Symbol("permessage-deflate");
    var kTotalLength = Symbol("total-length");
    var kCallback = Symbol("callback");
    var kBuffers = Symbol("buffers");
    var kError = Symbol("error");
    var zlibLimiter;
    var PerMessageDeflate = class {
      /**
       * Creates a PerMessageDeflate instance.
       *
       * @param {Object} [options] Configuration options
       * @param {(Boolean|Number)} [options.clientMaxWindowBits] Advertise support
       *     for, or request, a custom client window size
       * @param {Boolean} [options.clientNoContextTakeover=false] Advertise/
       *     acknowledge disabling of client context takeover
       * @param {Number} [options.concurrencyLimit=10] The number of concurrent
       *     calls to zlib
       * @param {Boolean} [options.isServer=false] Create the instance in either
       *     server or client mode
       * @param {Number} [options.maxPayload=0] The maximum allowed message length
       * @param {(Boolean|Number)} [options.serverMaxWindowBits] Request/confirm the
       *     use of a custom server window size
       * @param {Boolean} [options.serverNoContextTakeover=false] Request/accept
       *     disabling of server context takeover
       * @param {Number} [options.threshold=1024] Size (in bytes) below which
       *     messages should not be compressed if context takeover is disabled
       * @param {Object} [options.zlibDeflateOptions] Options to pass to zlib on
       *     deflate
       * @param {Object} [options.zlibInflateOptions] Options to pass to zlib on
       *     inflate
       */
      constructor(options) {
        this._options = options || {};
        this._threshold = this._options.threshold !== void 0 ? this._options.threshold : 1024;
        this._maxPayload = this._options.maxPayload | 0;
        this._isServer = !!this._options.isServer;
        this._deflate = null;
        this._inflate = null;
        this.params = null;
        if (!zlibLimiter) {
          const concurrency = this._options.concurrencyLimit !== void 0 ? this._options.concurrencyLimit : 10;
          zlibLimiter = new Limiter(concurrency);
        }
      }
      /**
       * @type {String}
       */
      static get extensionName() {
        return "permessage-deflate";
      }
      /**
       * Create an extension negotiation offer.
       *
       * @return {Object} Extension parameters
       * @public
       */
      offer() {
        const params = {};
        if (this._options.serverNoContextTakeover) {
          params.server_no_context_takeover = true;
        }
        if (this._options.clientNoContextTakeover) {
          params.client_no_context_takeover = true;
        }
        if (this._options.serverMaxWindowBits) {
          params.server_max_window_bits = this._options.serverMaxWindowBits;
        }
        if (this._options.clientMaxWindowBits) {
          params.client_max_window_bits = this._options.clientMaxWindowBits;
        } else if (this._options.clientMaxWindowBits == null) {
          params.client_max_window_bits = true;
        }
        return params;
      }
      /**
       * Accept an extension negotiation offer/response.
       *
       * @param {Array} configurations The extension negotiation offers/reponse
       * @return {Object} Accepted configuration
       * @public
       */
      accept(configurations) {
        configurations = this.normalizeParams(configurations);
        this.params = this._isServer ? this.acceptAsServer(configurations) : this.acceptAsClient(configurations);
        return this.params;
      }
      /**
       * Releases all resources used by the extension.
       *
       * @public
       */
      cleanup() {
        if (this._inflate) {
          this._inflate.close();
          this._inflate = null;
        }
        if (this._deflate) {
          const callback = this._deflate[kCallback];
          this._deflate.close();
          this._deflate = null;
          if (callback) {
            callback(
              new Error(
                "The deflate stream was closed while data was being processed"
              )
            );
          }
        }
      }
      /**
       *  Accept an extension negotiation offer.
       *
       * @param {Array} offers The extension negotiation offers
       * @return {Object} Accepted configuration
       * @private
       */
      acceptAsServer(offers) {
        const opts = this._options;
        const accepted = offers.find((params) => {
          if (opts.serverNoContextTakeover === false && params.server_no_context_takeover || params.server_max_window_bits && (opts.serverMaxWindowBits === false || typeof opts.serverMaxWindowBits === "number" && opts.serverMaxWindowBits > params.server_max_window_bits) || typeof opts.clientMaxWindowBits === "number" && !params.client_max_window_bits) {
            return false;
          }
          return true;
        });
        if (!accepted) {
          throw new Error("None of the extension offers can be accepted");
        }
        if (opts.serverNoContextTakeover) {
          accepted.server_no_context_takeover = true;
        }
        if (opts.clientNoContextTakeover) {
          accepted.client_no_context_takeover = true;
        }
        if (typeof opts.serverMaxWindowBits === "number") {
          accepted.server_max_window_bits = opts.serverMaxWindowBits;
        }
        if (typeof opts.clientMaxWindowBits === "number") {
          accepted.client_max_window_bits = opts.clientMaxWindowBits;
        } else if (accepted.client_max_window_bits === true || opts.clientMaxWindowBits === false) {
          delete accepted.client_max_window_bits;
        }
        return accepted;
      }
      /**
       * Accept the extension negotiation response.
       *
       * @param {Array} response The extension negotiation response
       * @return {Object} Accepted configuration
       * @private
       */
      acceptAsClient(response) {
        const params = response[0];
        if (this._options.clientNoContextTakeover === false && params.client_no_context_takeover) {
          throw new Error('Unexpected parameter "client_no_context_takeover"');
        }
        if (!params.client_max_window_bits) {
          if (typeof this._options.clientMaxWindowBits === "number") {
            params.client_max_window_bits = this._options.clientMaxWindowBits;
          }
        } else if (this._options.clientMaxWindowBits === false || typeof this._options.clientMaxWindowBits === "number" && params.client_max_window_bits > this._options.clientMaxWindowBits) {
          throw new Error(
            'Unexpected or invalid parameter "client_max_window_bits"'
          );
        }
        return params;
      }
      /**
       * Normalize parameters.
       *
       * @param {Array} configurations The extension negotiation offers/reponse
       * @return {Array} The offers/response with normalized parameters
       * @private
       */
      normalizeParams(configurations) {
        configurations.forEach((params) => {
          Object.keys(params).forEach((key) => {
            let value = params[key];
            if (value.length > 1) {
              throw new Error(`Parameter "${key}" must have only a single value`);
            }
            value = value[0];
            if (key === "client_max_window_bits") {
              if (value !== true) {
                const num = +value;
                if (!Number.isInteger(num) || num < 8 || num > 15) {
                  throw new TypeError(
                    `Invalid value for parameter "${key}": ${value}`
                  );
                }
                value = num;
              } else if (!this._isServer) {
                throw new TypeError(
                  `Invalid value for parameter "${key}": ${value}`
                );
              }
            } else if (key === "server_max_window_bits") {
              const num = +value;
              if (!Number.isInteger(num) || num < 8 || num > 15) {
                throw new TypeError(
                  `Invalid value for parameter "${key}": ${value}`
                );
              }
              value = num;
            } else if (key === "client_no_context_takeover" || key === "server_no_context_takeover") {
              if (value !== true) {
                throw new TypeError(
                  `Invalid value for parameter "${key}": ${value}`
                );
              }
            } else {
              throw new Error(`Unknown parameter "${key}"`);
            }
            params[key] = value;
          });
        });
        return configurations;
      }
      /**
       * Decompress data. Concurrency limited.
       *
       * @param {Buffer} data Compressed data
       * @param {Boolean} fin Specifies whether or not this is the last fragment
       * @param {Function} callback Callback
       * @public
       */
      decompress(data, fin, callback) {
        zlibLimiter.add((done) => {
          this._decompress(data, fin, (err, result) => {
            done();
            callback(err, result);
          });
        });
      }
      /**
       * Compress data. Concurrency limited.
       *
       * @param {(Buffer|String)} data Data to compress
       * @param {Boolean} fin Specifies whether or not this is the last fragment
       * @param {Function} callback Callback
       * @public
       */
      compress(data, fin, callback) {
        zlibLimiter.add((done) => {
          this._compress(data, fin, (err, result) => {
            done();
            callback(err, result);
          });
        });
      }
      /**
       * Decompress data.
       *
       * @param {Buffer} data Compressed data
       * @param {Boolean} fin Specifies whether or not this is the last fragment
       * @param {Function} callback Callback
       * @private
       */
      _decompress(data, fin, callback) {
        const endpoint = this._isServer ? "client" : "server";
        if (!this._inflate) {
          const key = `${endpoint}_max_window_bits`;
          const windowBits = typeof this.params[key] !== "number" ? zlib.Z_DEFAULT_WINDOWBITS : this.params[key];
          this._inflate = zlib.createInflateRaw({
            ...this._options.zlibInflateOptions,
            windowBits
          });
          this._inflate[kPerMessageDeflate] = this;
          this._inflate[kTotalLength] = 0;
          this._inflate[kBuffers] = [];
          this._inflate.on("error", inflateOnError);
          this._inflate.on("data", inflateOnData);
        }
        this._inflate[kCallback] = callback;
        this._inflate.write(data);
        if (fin) this._inflate.write(TRAILER);
        this._inflate.flush(() => {
          const err = this._inflate[kError];
          if (err) {
            this._inflate.close();
            this._inflate = null;
            callback(err);
            return;
          }
          const data2 = bufferUtil.concat(
            this._inflate[kBuffers],
            this._inflate[kTotalLength]
          );
          if (this._inflate._readableState.endEmitted) {
            this._inflate.close();
            this._inflate = null;
          } else {
            this._inflate[kTotalLength] = 0;
            this._inflate[kBuffers] = [];
            if (fin && this.params[`${endpoint}_no_context_takeover`]) {
              this._inflate.reset();
            }
          }
          callback(null, data2);
        });
      }
      /**
       * Compress data.
       *
       * @param {(Buffer|String)} data Data to compress
       * @param {Boolean} fin Specifies whether or not this is the last fragment
       * @param {Function} callback Callback
       * @private
       */
      _compress(data, fin, callback) {
        const endpoint = this._isServer ? "server" : "client";
        if (!this._deflate) {
          const key = `${endpoint}_max_window_bits`;
          const windowBits = typeof this.params[key] !== "number" ? zlib.Z_DEFAULT_WINDOWBITS : this.params[key];
          this._deflate = zlib.createDeflateRaw({
            ...this._options.zlibDeflateOptions,
            windowBits
          });
          this._deflate[kTotalLength] = 0;
          this._deflate[kBuffers] = [];
          this._deflate.on("data", deflateOnData);
        }
        this._deflate[kCallback] = callback;
        this._deflate.write(data);
        this._deflate.flush(zlib.Z_SYNC_FLUSH, () => {
          if (!this._deflate) {
            return;
          }
          let data2 = bufferUtil.concat(
            this._deflate[kBuffers],
            this._deflate[kTotalLength]
          );
          if (fin) {
            data2 = new FastBuffer(data2.buffer, data2.byteOffset, data2.length - 4);
          }
          this._deflate[kCallback] = null;
          this._deflate[kTotalLength] = 0;
          this._deflate[kBuffers] = [];
          if (fin && this.params[`${endpoint}_no_context_takeover`]) {
            this._deflate.reset();
          }
          callback(null, data2);
        });
      }
    };
    module2.exports = PerMessageDeflate;
    function deflateOnData(chunk) {
      this[kBuffers].push(chunk);
      this[kTotalLength] += chunk.length;
    }
    function inflateOnData(chunk) {
      this[kTotalLength] += chunk.length;
      if (this[kPerMessageDeflate]._maxPayload < 1 || this[kTotalLength] <= this[kPerMessageDeflate]._maxPayload) {
        this[kBuffers].push(chunk);
        return;
      }
      this[kError] = new RangeError("Max payload size exceeded");
      this[kError].code = "WS_ERR_UNSUPPORTED_MESSAGE_LENGTH";
      this[kError][kStatusCode] = 1009;
      this.removeListener("data", inflateOnData);
      this.reset();
    }
    function inflateOnError(err) {
      this[kPerMessageDeflate]._inflate = null;
      if (this[kError]) {
        this[kCallback](this[kError]);
        return;
      }
      err[kStatusCode] = 1007;
      this[kCallback](err);
    }
  }
});

// node_modules/ws/lib/validation.js
var require_validation = __commonJS({
  "node_modules/ws/lib/validation.js"(exports2, module2) {
    "use strict";
    var { isUtf8 } = require("buffer");
    var { hasBlob } = require_constants();
    var tokenChars = [
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      // 0 - 15
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      // 16 - 31
      0,
      1,
      0,
      1,
      1,
      1,
      1,
      1,
      0,
      0,
      1,
      1,
      0,
      1,
      1,
      0,
      // 32 - 47
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      0,
      0,
      0,
      0,
      0,
      0,
      // 48 - 63
      0,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      // 64 - 79
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      0,
      0,
      0,
      1,
      1,
      // 80 - 95
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      // 96 - 111
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      1,
      0,
      1,
      0,
      1,
      0
      // 112 - 127
    ];
    function isValidStatusCode(code) {
      return code >= 1e3 && code <= 1014 && code !== 1004 && code !== 1005 && code !== 1006 || code >= 3e3 && code <= 4999;
    }
    function _isValidUTF8(buf) {
      const len = buf.length;
      let i = 0;
      while (i < len) {
        if ((buf[i] & 128) === 0) {
          i++;
        } else if ((buf[i] & 224) === 192) {
          if (i + 1 === len || (buf[i + 1] & 192) !== 128 || (buf[i] & 254) === 192) {
            return false;
          }
          i += 2;
        } else if ((buf[i] & 240) === 224) {
          if (i + 2 >= len || (buf[i + 1] & 192) !== 128 || (buf[i + 2] & 192) !== 128 || buf[i] === 224 && (buf[i + 1] & 224) === 128 || // Overlong
          buf[i] === 237 && (buf[i + 1] & 224) === 160) {
            return false;
          }
          i += 3;
        } else if ((buf[i] & 248) === 240) {
          if (i + 3 >= len || (buf[i + 1] & 192) !== 128 || (buf[i + 2] & 192) !== 128 || (buf[i + 3] & 192) !== 128 || buf[i] === 240 && (buf[i + 1] & 240) === 128 || // Overlong
          buf[i] === 244 && buf[i + 1] > 143 || buf[i] > 244) {
            return false;
          }
          i += 4;
        } else {
          return false;
        }
      }
      return true;
    }
    function isBlob(value) {
      return hasBlob && typeof value === "object" && typeof value.arrayBuffer === "function" && typeof value.type === "string" && typeof value.stream === "function" && (value[Symbol.toStringTag] === "Blob" || value[Symbol.toStringTag] === "File");
    }
    module2.exports = {
      isBlob,
      isValidStatusCode,
      isValidUTF8: _isValidUTF8,
      tokenChars
    };
    if (isUtf8) {
      module2.exports.isValidUTF8 = function(buf) {
        return buf.length < 24 ? _isValidUTF8(buf) : isUtf8(buf);
      };
    } else if (!process.env.WS_NO_UTF_8_VALIDATE) {
      try {
        const isValidUTF8 = require("utf-8-validate");
        module2.exports.isValidUTF8 = function(buf) {
          return buf.length < 32 ? _isValidUTF8(buf) : isValidUTF8(buf);
        };
      } catch (e) {
      }
    }
  }
});

// node_modules/ws/lib/receiver.js
var require_receiver = __commonJS({
  "node_modules/ws/lib/receiver.js"(exports2, module2) {
    "use strict";
    var { Writable } = require("stream");
    var PerMessageDeflate = require_permessage_deflate();
    var {
      BINARY_TYPES,
      EMPTY_BUFFER,
      kStatusCode,
      kWebSocket
    } = require_constants();
    var { concat, toArrayBuffer, unmask } = require_buffer_util();
    var { isValidStatusCode, isValidUTF8 } = require_validation();
    var FastBuffer = Buffer[Symbol.species];
    var GET_INFO = 0;
    var GET_PAYLOAD_LENGTH_16 = 1;
    var GET_PAYLOAD_LENGTH_64 = 2;
    var GET_MASK = 3;
    var GET_DATA = 4;
    var INFLATING = 5;
    var DEFER_EVENT = 6;
    var Receiver = class extends Writable {
      /**
       * Creates a Receiver instance.
       *
       * @param {Object} [options] Options object
       * @param {Boolean} [options.allowSynchronousEvents=true] Specifies whether
       *     any of the `'message'`, `'ping'`, and `'pong'` events can be emitted
       *     multiple times in the same tick
       * @param {String} [options.binaryType=nodebuffer] The type for binary data
       * @param {Object} [options.extensions] An object containing the negotiated
       *     extensions
       * @param {Boolean} [options.isServer=false] Specifies whether to operate in
       *     client or server mode
       * @param {Number} [options.maxBufferedChunks=0] The maximum number of
       *     buffered data chunks
       * @param {Number} [options.maxFragments=0] The maximum number of message
       *     fragments
       * @param {Number} [options.maxPayload=0] The maximum allowed message length
       * @param {Boolean} [options.skipUTF8Validation=false] Specifies whether or
       *     not to skip UTF-8 validation for text and close messages
       */
      constructor(options = {}) {
        super();
        this._allowSynchronousEvents = options.allowSynchronousEvents !== void 0 ? options.allowSynchronousEvents : true;
        this._binaryType = options.binaryType || BINARY_TYPES[0];
        this._extensions = options.extensions || {};
        this._isServer = !!options.isServer;
        this._maxBufferedChunks = options.maxBufferedChunks | 0;
        this._maxFragments = options.maxFragments | 0;
        this._maxPayload = options.maxPayload | 0;
        this._skipUTF8Validation = !!options.skipUTF8Validation;
        this[kWebSocket] = void 0;
        this._bufferedBytes = 0;
        this._buffers = [];
        this._compressed = false;
        this._payloadLength = 0;
        this._mask = void 0;
        this._fragmented = 0;
        this._masked = false;
        this._fin = false;
        this._opcode = 0;
        this._totalPayloadLength = 0;
        this._messageLength = 0;
        this._numFragments = 0;
        this._fragments = [];
        this._errored = false;
        this._loop = false;
        this._state = GET_INFO;
      }
      /**
       * Implements `Writable.prototype._write()`.
       *
       * @param {Buffer} chunk The chunk of data to write
       * @param {String} encoding The character encoding of `chunk`
       * @param {Function} cb Callback
       * @private
       */
      _write(chunk, encoding, cb) {
        if (this._opcode === 8 && this._state == GET_INFO) return cb();
        if (this._maxBufferedChunks > 0 && this._buffers.length >= this._maxBufferedChunks) {
          cb(
            this.createError(
              RangeError,
              "Too many buffered chunks",
              false,
              1008,
              "WS_ERR_TOO_MANY_BUFFERED_PARTS"
            )
          );
          return;
        }
        this._bufferedBytes += chunk.length;
        this._buffers.push(chunk);
        this.startLoop(cb);
      }
      /**
       * Consumes `n` bytes from the buffered data.
       *
       * @param {Number} n The number of bytes to consume
       * @return {Buffer} The consumed bytes
       * @private
       */
      consume(n) {
        this._bufferedBytes -= n;
        if (n === this._buffers[0].length) return this._buffers.shift();
        if (n < this._buffers[0].length) {
          const buf = this._buffers[0];
          this._buffers[0] = new FastBuffer(
            buf.buffer,
            buf.byteOffset + n,
            buf.length - n
          );
          return new FastBuffer(buf.buffer, buf.byteOffset, n);
        }
        const dst = Buffer.allocUnsafe(n);
        do {
          const buf = this._buffers[0];
          const offset = dst.length - n;
          if (n >= buf.length) {
            dst.set(this._buffers.shift(), offset);
          } else {
            dst.set(new Uint8Array(buf.buffer, buf.byteOffset, n), offset);
            this._buffers[0] = new FastBuffer(
              buf.buffer,
              buf.byteOffset + n,
              buf.length - n
            );
          }
          n -= buf.length;
        } while (n > 0);
        return dst;
      }
      /**
       * Starts the parsing loop.
       *
       * @param {Function} cb Callback
       * @private
       */
      startLoop(cb) {
        this._loop = true;
        do {
          switch (this._state) {
            case GET_INFO:
              this.getInfo(cb);
              break;
            case GET_PAYLOAD_LENGTH_16:
              this.getPayloadLength16(cb);
              break;
            case GET_PAYLOAD_LENGTH_64:
              this.getPayloadLength64(cb);
              break;
            case GET_MASK:
              this.getMask();
              break;
            case GET_DATA:
              this.getData(cb);
              break;
            case INFLATING:
            case DEFER_EVENT:
              this._loop = false;
              return;
          }
        } while (this._loop);
        if (!this._errored) cb();
      }
      /**
       * Reads the first two bytes of a frame.
       *
       * @param {Function} cb Callback
       * @private
       */
      getInfo(cb) {
        if (this._bufferedBytes < 2) {
          this._loop = false;
          return;
        }
        const buf = this.consume(2);
        if ((buf[0] & 48) !== 0) {
          const error = this.createError(
            RangeError,
            "RSV2 and RSV3 must be clear",
            true,
            1002,
            "WS_ERR_UNEXPECTED_RSV_2_3"
          );
          cb(error);
          return;
        }
        const compressed = (buf[0] & 64) === 64;
        if (compressed && !this._extensions[PerMessageDeflate.extensionName]) {
          const error = this.createError(
            RangeError,
            "RSV1 must be clear",
            true,
            1002,
            "WS_ERR_UNEXPECTED_RSV_1"
          );
          cb(error);
          return;
        }
        this._fin = (buf[0] & 128) === 128;
        this._opcode = buf[0] & 15;
        this._payloadLength = buf[1] & 127;
        if (this._opcode === 0) {
          if (compressed) {
            const error = this.createError(
              RangeError,
              "RSV1 must be clear",
              true,
              1002,
              "WS_ERR_UNEXPECTED_RSV_1"
            );
            cb(error);
            return;
          }
          if (!this._fragmented) {
            const error = this.createError(
              RangeError,
              "invalid opcode 0",
              true,
              1002,
              "WS_ERR_INVALID_OPCODE"
            );
            cb(error);
            return;
          }
          this._opcode = this._fragmented;
        } else if (this._opcode === 1 || this._opcode === 2) {
          if (this._fragmented) {
            const error = this.createError(
              RangeError,
              `invalid opcode ${this._opcode}`,
              true,
              1002,
              "WS_ERR_INVALID_OPCODE"
            );
            cb(error);
            return;
          }
          this._compressed = compressed;
        } else if (this._opcode > 7 && this._opcode < 11) {
          if (!this._fin) {
            const error = this.createError(
              RangeError,
              "FIN must be set",
              true,
              1002,
              "WS_ERR_EXPECTED_FIN"
            );
            cb(error);
            return;
          }
          if (compressed) {
            const error = this.createError(
              RangeError,
              "RSV1 must be clear",
              true,
              1002,
              "WS_ERR_UNEXPECTED_RSV_1"
            );
            cb(error);
            return;
          }
          if (this._payloadLength > 125 || this._opcode === 8 && this._payloadLength === 1) {
            const error = this.createError(
              RangeError,
              `invalid payload length ${this._payloadLength}`,
              true,
              1002,
              "WS_ERR_INVALID_CONTROL_PAYLOAD_LENGTH"
            );
            cb(error);
            return;
          }
        } else {
          const error = this.createError(
            RangeError,
            `invalid opcode ${this._opcode}`,
            true,
            1002,
            "WS_ERR_INVALID_OPCODE"
          );
          cb(error);
          return;
        }
        if (!this._fin && !this._fragmented) this._fragmented = this._opcode;
        this._masked = (buf[1] & 128) === 128;
        if (this._isServer) {
          if (!this._masked) {
            const error = this.createError(
              RangeError,
              "MASK must be set",
              true,
              1002,
              "WS_ERR_EXPECTED_MASK"
            );
            cb(error);
            return;
          }
        } else if (this._masked) {
          const error = this.createError(
            RangeError,
            "MASK must be clear",
            true,
            1002,
            "WS_ERR_UNEXPECTED_MASK"
          );
          cb(error);
          return;
        }
        if (this._payloadLength === 126) this._state = GET_PAYLOAD_LENGTH_16;
        else if (this._payloadLength === 127) this._state = GET_PAYLOAD_LENGTH_64;
        else this.haveLength(cb);
      }
      /**
       * Gets extended payload length (7+16).
       *
       * @param {Function} cb Callback
       * @private
       */
      getPayloadLength16(cb) {
        if (this._bufferedBytes < 2) {
          this._loop = false;
          return;
        }
        this._payloadLength = this.consume(2).readUInt16BE(0);
        this.haveLength(cb);
      }
      /**
       * Gets extended payload length (7+64).
       *
       * @param {Function} cb Callback
       * @private
       */
      getPayloadLength64(cb) {
        if (this._bufferedBytes < 8) {
          this._loop = false;
          return;
        }
        const buf = this.consume(8);
        const num = buf.readUInt32BE(0);
        if (num > Math.pow(2, 53 - 32) - 1) {
          const error = this.createError(
            RangeError,
            "Unsupported WebSocket frame: payload length > 2^53 - 1",
            false,
            1009,
            "WS_ERR_UNSUPPORTED_DATA_PAYLOAD_LENGTH"
          );
          cb(error);
          return;
        }
        this._payloadLength = num * Math.pow(2, 32) + buf.readUInt32BE(4);
        this.haveLength(cb);
      }
      /**
       * Payload length has been read.
       *
       * @param {Function} cb Callback
       * @private
       */
      haveLength(cb) {
        if (this._payloadLength && this._opcode < 8) {
          this._totalPayloadLength += this._payloadLength;
          if (this._totalPayloadLength > this._maxPayload && this._maxPayload > 0) {
            const error = this.createError(
              RangeError,
              "Max payload size exceeded",
              false,
              1009,
              "WS_ERR_UNSUPPORTED_MESSAGE_LENGTH"
            );
            cb(error);
            return;
          }
        }
        if (this._masked) this._state = GET_MASK;
        else this._state = GET_DATA;
      }
      /**
       * Reads mask bytes.
       *
       * @private
       */
      getMask() {
        if (this._bufferedBytes < 4) {
          this._loop = false;
          return;
        }
        this._mask = this.consume(4);
        this._state = GET_DATA;
      }
      /**
       * Reads data bytes.
       *
       * @param {Function} cb Callback
       * @private
       */
      getData(cb) {
        let data = EMPTY_BUFFER;
        if (this._payloadLength) {
          if (this._bufferedBytes < this._payloadLength) {
            this._loop = false;
            return;
          }
          data = this.consume(this._payloadLength);
          if (this._masked && (this._mask[0] | this._mask[1] | this._mask[2] | this._mask[3]) !== 0) {
            unmask(data, this._mask);
          }
        }
        if (this._opcode > 7) {
          this.controlMessage(data, cb);
          return;
        }
        if (this._maxFragments > 0 && ++this._numFragments > this._maxFragments) {
          const error = this.createError(
            RangeError,
            "Too many message fragments",
            false,
            1008,
            "WS_ERR_TOO_MANY_BUFFERED_PARTS"
          );
          cb(error);
          return;
        }
        if (this._compressed) {
          this._state = INFLATING;
          this.decompress(data, cb);
          return;
        }
        if (data.length) {
          this._messageLength = this._totalPayloadLength;
          this._fragments.push(data);
        }
        this.dataMessage(cb);
      }
      /**
       * Decompresses data.
       *
       * @param {Buffer} data Compressed data
       * @param {Function} cb Callback
       * @private
       */
      decompress(data, cb) {
        const perMessageDeflate = this._extensions[PerMessageDeflate.extensionName];
        perMessageDeflate.decompress(data, this._fin, (err, buf) => {
          if (err) return cb(err);
          if (buf.length) {
            this._messageLength += buf.length;
            if (this._messageLength > this._maxPayload && this._maxPayload > 0) {
              const error = this.createError(
                RangeError,
                "Max payload size exceeded",
                false,
                1009,
                "WS_ERR_UNSUPPORTED_MESSAGE_LENGTH"
              );
              cb(error);
              return;
            }
            this._fragments.push(buf);
          }
          this.dataMessage(cb);
          if (this._state === GET_INFO) this.startLoop(cb);
        });
      }
      /**
       * Handles a data message.
       *
       * @param {Function} cb Callback
       * @private
       */
      dataMessage(cb) {
        if (!this._fin) {
          this._state = GET_INFO;
          return;
        }
        const messageLength = this._messageLength;
        const fragments = this._fragments;
        this._totalPayloadLength = 0;
        this._messageLength = 0;
        this._fragmented = 0;
        this._numFragments = 0;
        this._fragments = [];
        if (this._opcode === 2) {
          let data;
          if (this._binaryType === "nodebuffer") {
            data = concat(fragments, messageLength);
          } else if (this._binaryType === "arraybuffer") {
            data = toArrayBuffer(concat(fragments, messageLength));
          } else if (this._binaryType === "blob") {
            data = new Blob(fragments);
          } else {
            data = fragments;
          }
          if (this._allowSynchronousEvents) {
            this.emit("message", data, true);
            this._state = GET_INFO;
          } else {
            this._state = DEFER_EVENT;
            setImmediate(() => {
              this.emit("message", data, true);
              this._state = GET_INFO;
              this.startLoop(cb);
            });
          }
        } else {
          const buf = concat(fragments, messageLength);
          if (!this._skipUTF8Validation && !isValidUTF8(buf)) {
            const error = this.createError(
              Error,
              "invalid UTF-8 sequence",
              true,
              1007,
              "WS_ERR_INVALID_UTF8"
            );
            cb(error);
            return;
          }
          if (this._state === INFLATING || this._allowSynchronousEvents) {
            this.emit("message", buf, false);
            this._state = GET_INFO;
          } else {
            this._state = DEFER_EVENT;
            setImmediate(() => {
              this.emit("message", buf, false);
              this._state = GET_INFO;
              this.startLoop(cb);
            });
          }
        }
      }
      /**
       * Handles a control message.
       *
       * @param {Buffer} data Data to handle
       * @return {(Error|RangeError|undefined)} A possible error
       * @private
       */
      controlMessage(data, cb) {
        if (this._opcode === 8) {
          if (data.length === 0) {
            this._loop = false;
            this.emit("conclude", 1005, EMPTY_BUFFER);
            this.end();
          } else {
            const code = data.readUInt16BE(0);
            if (!isValidStatusCode(code)) {
              const error = this.createError(
                RangeError,
                `invalid status code ${code}`,
                true,
                1002,
                "WS_ERR_INVALID_CLOSE_CODE"
              );
              cb(error);
              return;
            }
            const buf = new FastBuffer(
              data.buffer,
              data.byteOffset + 2,
              data.length - 2
            );
            if (!this._skipUTF8Validation && !isValidUTF8(buf)) {
              const error = this.createError(
                Error,
                "invalid UTF-8 sequence",
                true,
                1007,
                "WS_ERR_INVALID_UTF8"
              );
              cb(error);
              return;
            }
            this._loop = false;
            this.emit("conclude", code, buf);
            this.end();
          }
          this._state = GET_INFO;
          return;
        }
        if (this._allowSynchronousEvents) {
          this.emit(this._opcode === 9 ? "ping" : "pong", data);
          this._state = GET_INFO;
        } else {
          this._state = DEFER_EVENT;
          setImmediate(() => {
            this.emit(this._opcode === 9 ? "ping" : "pong", data);
            this._state = GET_INFO;
            this.startLoop(cb);
          });
        }
      }
      /**
       * Builds an error object.
       *
       * @param {function(new:Error|RangeError)} ErrorCtor The error constructor
       * @param {String} message The error message
       * @param {Boolean} prefix Specifies whether or not to add a default prefix to
       *     `message`
       * @param {Number} statusCode The status code
       * @param {String} errorCode The exposed error code
       * @return {(Error|RangeError)} The error
       * @private
       */
      createError(ErrorCtor, message, prefix, statusCode, errorCode) {
        this._loop = false;
        this._errored = true;
        const err = new ErrorCtor(
          prefix ? `Invalid WebSocket frame: ${message}` : message
        );
        Error.captureStackTrace(err, this.createError);
        err.code = errorCode;
        err[kStatusCode] = statusCode;
        return err;
      }
    };
    module2.exports = Receiver;
  }
});

// node_modules/ws/lib/sender.js
var require_sender = __commonJS({
  "node_modules/ws/lib/sender.js"(exports2, module2) {
    "use strict";
    var { Duplex } = require("stream");
    var { randomFillSync } = require("crypto");
    var {
      types: { isUint8Array }
    } = require("util");
    var PerMessageDeflate = require_permessage_deflate();
    var { EMPTY_BUFFER, kWebSocket, NOOP } = require_constants();
    var { isBlob, isValidStatusCode } = require_validation();
    var { mask: applyMask, toBuffer } = require_buffer_util();
    var kByteLength = Symbol("kByteLength");
    var maskBuffer = Buffer.alloc(4);
    var RANDOM_POOL_SIZE = 8 * 1024;
    var randomPool;
    var randomPoolPointer = RANDOM_POOL_SIZE;
    var DEFAULT = 0;
    var DEFLATING = 1;
    var GET_BLOB_DATA = 2;
    var Sender = class _Sender {
      /**
       * Creates a Sender instance.
       *
       * @param {Duplex} socket The connection socket
       * @param {Object} [extensions] An object containing the negotiated extensions
       * @param {Function} [generateMask] The function used to generate the masking
       *     key
       */
      constructor(socket, extensions, generateMask) {
        this._extensions = extensions || {};
        if (generateMask) {
          this._generateMask = generateMask;
          this._maskBuffer = Buffer.alloc(4);
        }
        this._socket = socket;
        this._firstFragment = true;
        this._compress = false;
        this._bufferedBytes = 0;
        this._queue = [];
        this._state = DEFAULT;
        this.onerror = NOOP;
        this[kWebSocket] = void 0;
      }
      /**
       * Frames a piece of data according to the HyBi WebSocket protocol.
       *
       * @param {(Buffer|String)} data The data to frame
       * @param {Object} options Options object
       * @param {Boolean} [options.fin=false] Specifies whether or not to set the
       *     FIN bit
       * @param {Function} [options.generateMask] The function used to generate the
       *     masking key
       * @param {Boolean} [options.mask=false] Specifies whether or not to mask
       *     `data`
       * @param {Buffer} [options.maskBuffer] The buffer used to store the masking
       *     key
       * @param {Number} options.opcode The opcode
       * @param {Boolean} [options.readOnly=false] Specifies whether `data` can be
       *     modified
       * @param {Boolean} [options.rsv1=false] Specifies whether or not to set the
       *     RSV1 bit
       * @return {(Buffer|String)[]} The framed data
       * @public
       */
      static frame(data, options) {
        let mask;
        let merge = false;
        let offset = 2;
        let skipMasking = false;
        if (options.mask) {
          mask = options.maskBuffer || maskBuffer;
          if (options.generateMask) {
            options.generateMask(mask);
          } else {
            if (randomPoolPointer === RANDOM_POOL_SIZE) {
              if (randomPool === void 0) {
                randomPool = Buffer.alloc(RANDOM_POOL_SIZE);
              }
              randomFillSync(randomPool, 0, RANDOM_POOL_SIZE);
              randomPoolPointer = 0;
            }
            mask[0] = randomPool[randomPoolPointer++];
            mask[1] = randomPool[randomPoolPointer++];
            mask[2] = randomPool[randomPoolPointer++];
            mask[3] = randomPool[randomPoolPointer++];
          }
          skipMasking = (mask[0] | mask[1] | mask[2] | mask[3]) === 0;
          offset = 6;
        }
        let dataLength;
        if (typeof data === "string") {
          if ((!options.mask || skipMasking) && options[kByteLength] !== void 0) {
            dataLength = options[kByteLength];
          } else {
            data = Buffer.from(data);
            dataLength = data.length;
          }
        } else {
          dataLength = data.length;
          merge = options.mask && options.readOnly && !skipMasking;
        }
        let payloadLength = dataLength;
        if (dataLength >= 65536) {
          offset += 8;
          payloadLength = 127;
        } else if (dataLength > 125) {
          offset += 2;
          payloadLength = 126;
        }
        const target = Buffer.allocUnsafe(merge ? dataLength + offset : offset);
        target[0] = options.fin ? options.opcode | 128 : options.opcode;
        if (options.rsv1) target[0] |= 64;
        target[1] = payloadLength;
        if (payloadLength === 126) {
          target.writeUInt16BE(dataLength, 2);
        } else if (payloadLength === 127) {
          target[2] = target[3] = 0;
          target.writeUIntBE(dataLength, 4, 6);
        }
        if (!options.mask) return [target, data];
        target[1] |= 128;
        target[offset - 4] = mask[0];
        target[offset - 3] = mask[1];
        target[offset - 2] = mask[2];
        target[offset - 1] = mask[3];
        if (skipMasking) return [target, data];
        if (merge) {
          applyMask(data, mask, target, offset, dataLength);
          return [target];
        }
        applyMask(data, mask, data, 0, dataLength);
        return [target, data];
      }
      /**
       * Sends a close message to the other peer.
       *
       * @param {Number} [code] The status code component of the body
       * @param {(String|Buffer)} [data] The message component of the body
       * @param {Boolean} [mask=false] Specifies whether or not to mask the message
       * @param {Function} [cb] Callback
       * @public
       */
      close(code, data, mask, cb) {
        let buf;
        if (code === void 0) {
          buf = EMPTY_BUFFER;
        } else if (typeof code !== "number" || !isValidStatusCode(code)) {
          throw new TypeError("First argument must be a valid error code number");
        } else if (data === void 0 || !data.length) {
          buf = Buffer.allocUnsafe(2);
          buf.writeUInt16BE(code, 0);
        } else {
          const length = Buffer.byteLength(data);
          if (length > 123) {
            throw new RangeError("The message must not be greater than 123 bytes");
          }
          buf = Buffer.allocUnsafe(2 + length);
          buf.writeUInt16BE(code, 0);
          if (typeof data === "string") {
            buf.write(data, 2);
          } else if (isUint8Array(data)) {
            buf.set(data, 2);
          } else {
            throw new TypeError("Second argument must be a string or a Uint8Array");
          }
        }
        const options = {
          [kByteLength]: buf.length,
          fin: true,
          generateMask: this._generateMask,
          mask,
          maskBuffer: this._maskBuffer,
          opcode: 8,
          readOnly: false,
          rsv1: false
        };
        if (this._state !== DEFAULT) {
          this.enqueue([this.dispatch, buf, false, options, cb]);
        } else {
          this.sendFrame(_Sender.frame(buf, options), cb);
        }
      }
      /**
       * Sends a ping message to the other peer.
       *
       * @param {*} data The message to send
       * @param {Boolean} [mask=false] Specifies whether or not to mask `data`
       * @param {Function} [cb] Callback
       * @public
       */
      ping(data, mask, cb) {
        let byteLength;
        let readOnly;
        if (typeof data === "string") {
          byteLength = Buffer.byteLength(data);
          readOnly = false;
        } else if (isBlob(data)) {
          byteLength = data.size;
          readOnly = false;
        } else {
          data = toBuffer(data);
          byteLength = data.length;
          readOnly = toBuffer.readOnly;
        }
        if (byteLength > 125) {
          throw new RangeError("The data size must not be greater than 125 bytes");
        }
        const options = {
          [kByteLength]: byteLength,
          fin: true,
          generateMask: this._generateMask,
          mask,
          maskBuffer: this._maskBuffer,
          opcode: 9,
          readOnly,
          rsv1: false
        };
        if (isBlob(data)) {
          if (this._state !== DEFAULT) {
            this.enqueue([this.getBlobData, data, false, options, cb]);
          } else {
            this.getBlobData(data, false, options, cb);
          }
        } else if (this._state !== DEFAULT) {
          this.enqueue([this.dispatch, data, false, options, cb]);
        } else {
          this.sendFrame(_Sender.frame(data, options), cb);
        }
      }
      /**
       * Sends a pong message to the other peer.
       *
       * @param {*} data The message to send
       * @param {Boolean} [mask=false] Specifies whether or not to mask `data`
       * @param {Function} [cb] Callback
       * @public
       */
      pong(data, mask, cb) {
        let byteLength;
        let readOnly;
        if (typeof data === "string") {
          byteLength = Buffer.byteLength(data);
          readOnly = false;
        } else if (isBlob(data)) {
          byteLength = data.size;
          readOnly = false;
        } else {
          data = toBuffer(data);
          byteLength = data.length;
          readOnly = toBuffer.readOnly;
        }
        if (byteLength > 125) {
          throw new RangeError("The data size must not be greater than 125 bytes");
        }
        const options = {
          [kByteLength]: byteLength,
          fin: true,
          generateMask: this._generateMask,
          mask,
          maskBuffer: this._maskBuffer,
          opcode: 10,
          readOnly,
          rsv1: false
        };
        if (isBlob(data)) {
          if (this._state !== DEFAULT) {
            this.enqueue([this.getBlobData, data, false, options, cb]);
          } else {
            this.getBlobData(data, false, options, cb);
          }
        } else if (this._state !== DEFAULT) {
          this.enqueue([this.dispatch, data, false, options, cb]);
        } else {
          this.sendFrame(_Sender.frame(data, options), cb);
        }
      }
      /**
       * Sends a data message to the other peer.
       *
       * @param {*} data The message to send
       * @param {Object} options Options object
       * @param {Boolean} [options.binary=false] Specifies whether `data` is binary
       *     or text
       * @param {Boolean} [options.compress=false] Specifies whether or not to
       *     compress `data`
       * @param {Boolean} [options.fin=false] Specifies whether the fragment is the
       *     last one
       * @param {Boolean} [options.mask=false] Specifies whether or not to mask
       *     `data`
       * @param {Function} [cb] Callback
       * @public
       */
      send(data, options, cb) {
        const perMessageDeflate = this._extensions[PerMessageDeflate.extensionName];
        let opcode = options.binary ? 2 : 1;
        let rsv1 = options.compress;
        let byteLength;
        let readOnly;
        if (typeof data === "string") {
          byteLength = Buffer.byteLength(data);
          readOnly = false;
        } else if (isBlob(data)) {
          byteLength = data.size;
          readOnly = false;
        } else {
          data = toBuffer(data);
          byteLength = data.length;
          readOnly = toBuffer.readOnly;
        }
        if (this._firstFragment) {
          this._firstFragment = false;
          if (rsv1 && perMessageDeflate && perMessageDeflate.params[perMessageDeflate._isServer ? "server_no_context_takeover" : "client_no_context_takeover"]) {
            rsv1 = byteLength >= perMessageDeflate._threshold;
          }
          this._compress = rsv1;
        } else {
          rsv1 = false;
          opcode = 0;
        }
        if (options.fin) this._firstFragment = true;
        const opts = {
          [kByteLength]: byteLength,
          fin: options.fin,
          generateMask: this._generateMask,
          mask: options.mask,
          maskBuffer: this._maskBuffer,
          opcode,
          readOnly,
          rsv1
        };
        if (isBlob(data)) {
          if (this._state !== DEFAULT) {
            this.enqueue([this.getBlobData, data, this._compress, opts, cb]);
          } else {
            this.getBlobData(data, this._compress, opts, cb);
          }
        } else if (this._state !== DEFAULT) {
          this.enqueue([this.dispatch, data, this._compress, opts, cb]);
        } else {
          this.dispatch(data, this._compress, opts, cb);
        }
      }
      /**
       * Gets the contents of a blob as binary data.
       *
       * @param {Blob} blob The blob
       * @param {Boolean} [compress=false] Specifies whether or not to compress
       *     the data
       * @param {Object} options Options object
       * @param {Boolean} [options.fin=false] Specifies whether or not to set the
       *     FIN bit
       * @param {Function} [options.generateMask] The function used to generate the
       *     masking key
       * @param {Boolean} [options.mask=false] Specifies whether or not to mask
       *     `data`
       * @param {Buffer} [options.maskBuffer] The buffer used to store the masking
       *     key
       * @param {Number} options.opcode The opcode
       * @param {Boolean} [options.readOnly=false] Specifies whether `data` can be
       *     modified
       * @param {Boolean} [options.rsv1=false] Specifies whether or not to set the
       *     RSV1 bit
       * @param {Function} [cb] Callback
       * @private
       */
      getBlobData(blob, compress, options, cb) {
        this._bufferedBytes += options[kByteLength];
        this._state = GET_BLOB_DATA;
        blob.arrayBuffer().then((arrayBuffer) => {
          if (this._socket.destroyed) {
            const err = new Error(
              "The socket was closed while the blob was being read"
            );
            process.nextTick(callCallbacks, this, err, cb);
            return;
          }
          this._bufferedBytes -= options[kByteLength];
          const data = toBuffer(arrayBuffer);
          if (!compress) {
            this._state = DEFAULT;
            this.sendFrame(_Sender.frame(data, options), cb);
            this.dequeue();
          } else {
            this.dispatch(data, compress, options, cb);
          }
        }).catch((err) => {
          process.nextTick(onError, this, err, cb);
        });
      }
      /**
       * Dispatches a message.
       *
       * @param {(Buffer|String)} data The message to send
       * @param {Boolean} [compress=false] Specifies whether or not to compress
       *     `data`
       * @param {Object} options Options object
       * @param {Boolean} [options.fin=false] Specifies whether or not to set the
       *     FIN bit
       * @param {Function} [options.generateMask] The function used to generate the
       *     masking key
       * @param {Boolean} [options.mask=false] Specifies whether or not to mask
       *     `data`
       * @param {Buffer} [options.maskBuffer] The buffer used to store the masking
       *     key
       * @param {Number} options.opcode The opcode
       * @param {Boolean} [options.readOnly=false] Specifies whether `data` can be
       *     modified
       * @param {Boolean} [options.rsv1=false] Specifies whether or not to set the
       *     RSV1 bit
       * @param {Function} [cb] Callback
       * @private
       */
      dispatch(data, compress, options, cb) {
        if (!compress) {
          this.sendFrame(_Sender.frame(data, options), cb);
          return;
        }
        const perMessageDeflate = this._extensions[PerMessageDeflate.extensionName];
        this._bufferedBytes += options[kByteLength];
        this._state = DEFLATING;
        perMessageDeflate.compress(data, options.fin, (_, buf) => {
          if (this._socket.destroyed) {
            const err = new Error(
              "The socket was closed while data was being compressed"
            );
            callCallbacks(this, err, cb);
            return;
          }
          this._bufferedBytes -= options[kByteLength];
          this._state = DEFAULT;
          options.readOnly = false;
          this.sendFrame(_Sender.frame(buf, options), cb);
          this.dequeue();
        });
      }
      /**
       * Executes queued send operations.
       *
       * @private
       */
      dequeue() {
        while (this._state === DEFAULT && this._queue.length) {
          const params = this._queue.shift();
          this._bufferedBytes -= params[3][kByteLength];
          Reflect.apply(params[0], this, params.slice(1));
        }
      }
      /**
       * Enqueues a send operation.
       *
       * @param {Array} params Send operation parameters.
       * @private
       */
      enqueue(params) {
        this._bufferedBytes += params[3][kByteLength];
        this._queue.push(params);
      }
      /**
       * Sends a frame.
       *
       * @param {(Buffer | String)[]} list The frame to send
       * @param {Function} [cb] Callback
       * @private
       */
      sendFrame(list, cb) {
        if (list.length === 2) {
          this._socket.cork();
          this._socket.write(list[0]);
          this._socket.write(list[1], cb);
          this._socket.uncork();
        } else {
          this._socket.write(list[0], cb);
        }
      }
    };
    module2.exports = Sender;
    function callCallbacks(sender, err, cb) {
      if (typeof cb === "function") cb(err);
      for (let i = 0; i < sender._queue.length; i++) {
        const params = sender._queue[i];
        const callback = params[params.length - 1];
        if (typeof callback === "function") callback(err);
      }
    }
    function onError(sender, err, cb) {
      callCallbacks(sender, err, cb);
      sender.onerror(err);
    }
  }
});

// node_modules/ws/lib/event-target.js
var require_event_target = __commonJS({
  "node_modules/ws/lib/event-target.js"(exports2, module2) {
    "use strict";
    var { kForOnEventAttribute, kListener } = require_constants();
    var kCode = Symbol("kCode");
    var kData = Symbol("kData");
    var kError = Symbol("kError");
    var kMessage = Symbol("kMessage");
    var kReason = Symbol("kReason");
    var kTarget = Symbol("kTarget");
    var kType = Symbol("kType");
    var kWasClean = Symbol("kWasClean");
    var Event = class {
      /**
       * Create a new `Event`.
       *
       * @param {String} type The name of the event
       * @throws {TypeError} If the `type` argument is not specified
       */
      constructor(type) {
        this[kTarget] = null;
        this[kType] = type;
      }
      /**
       * @type {*}
       */
      get target() {
        return this[kTarget];
      }
      /**
       * @type {String}
       */
      get type() {
        return this[kType];
      }
    };
    Object.defineProperty(Event.prototype, "target", { enumerable: true });
    Object.defineProperty(Event.prototype, "type", { enumerable: true });
    var CloseEvent = class extends Event {
      /**
       * Create a new `CloseEvent`.
       *
       * @param {String} type The name of the event
       * @param {Object} [options] A dictionary object that allows for setting
       *     attributes via object members of the same name
       * @param {Number} [options.code=0] The status code explaining why the
       *     connection was closed
       * @param {String} [options.reason=''] A human-readable string explaining why
       *     the connection was closed
       * @param {Boolean} [options.wasClean=false] Indicates whether or not the
       *     connection was cleanly closed
       */
      constructor(type, options = {}) {
        super(type);
        this[kCode] = options.code === void 0 ? 0 : options.code;
        this[kReason] = options.reason === void 0 ? "" : options.reason;
        this[kWasClean] = options.wasClean === void 0 ? false : options.wasClean;
      }
      /**
       * @type {Number}
       */
      get code() {
        return this[kCode];
      }
      /**
       * @type {String}
       */
      get reason() {
        return this[kReason];
      }
      /**
       * @type {Boolean}
       */
      get wasClean() {
        return this[kWasClean];
      }
    };
    Object.defineProperty(CloseEvent.prototype, "code", { enumerable: true });
    Object.defineProperty(CloseEvent.prototype, "reason", { enumerable: true });
    Object.defineProperty(CloseEvent.prototype, "wasClean", { enumerable: true });
    var ErrorEvent = class extends Event {
      /**
       * Create a new `ErrorEvent`.
       *
       * @param {String} type The name of the event
       * @param {Object} [options] A dictionary object that allows for setting
       *     attributes via object members of the same name
       * @param {*} [options.error=null] The error that generated this event
       * @param {String} [options.message=''] The error message
       */
      constructor(type, options = {}) {
        super(type);
        this[kError] = options.error === void 0 ? null : options.error;
        this[kMessage] = options.message === void 0 ? "" : options.message;
      }
      /**
       * @type {*}
       */
      get error() {
        return this[kError];
      }
      /**
       * @type {String}
       */
      get message() {
        return this[kMessage];
      }
    };
    Object.defineProperty(ErrorEvent.prototype, "error", { enumerable: true });
    Object.defineProperty(ErrorEvent.prototype, "message", { enumerable: true });
    var MessageEvent = class extends Event {
      /**
       * Create a new `MessageEvent`.
       *
       * @param {String} type The name of the event
       * @param {Object} [options] A dictionary object that allows for setting
       *     attributes via object members of the same name
       * @param {*} [options.data=null] The message content
       */
      constructor(type, options = {}) {
        super(type);
        this[kData] = options.data === void 0 ? null : options.data;
      }
      /**
       * @type {*}
       */
      get data() {
        return this[kData];
      }
    };
    Object.defineProperty(MessageEvent.prototype, "data", { enumerable: true });
    var EventTarget = {
      /**
       * Register an event listener.
       *
       * @param {String} type A string representing the event type to listen for
       * @param {(Function|Object)} handler The listener to add
       * @param {Object} [options] An options object specifies characteristics about
       *     the event listener
       * @param {Boolean} [options.once=false] A `Boolean` indicating that the
       *     listener should be invoked at most once after being added. If `true`,
       *     the listener would be automatically removed when invoked.
       * @public
       */
      addEventListener(type, handler, options = {}) {
        for (const listener of this.listeners(type)) {
          if (!options[kForOnEventAttribute] && listener[kListener] === handler && !listener[kForOnEventAttribute]) {
            return;
          }
        }
        let wrapper;
        if (type === "message") {
          wrapper = function onMessage(data, isBinary) {
            const event = new MessageEvent("message", {
              data: isBinary ? data : data.toString()
            });
            event[kTarget] = this;
            callListener(handler, this, event);
          };
        } else if (type === "close") {
          wrapper = function onClose(code, message) {
            const event = new CloseEvent("close", {
              code,
              reason: message.toString(),
              wasClean: this._closeFrameReceived && this._closeFrameSent
            });
            event[kTarget] = this;
            callListener(handler, this, event);
          };
        } else if (type === "error") {
          wrapper = function onError(error) {
            const event = new ErrorEvent("error", {
              error,
              message: error.message
            });
            event[kTarget] = this;
            callListener(handler, this, event);
          };
        } else if (type === "open") {
          wrapper = function onOpen() {
            const event = new Event("open");
            event[kTarget] = this;
            callListener(handler, this, event);
          };
        } else {
          return;
        }
        wrapper[kForOnEventAttribute] = !!options[kForOnEventAttribute];
        wrapper[kListener] = handler;
        if (options.once) {
          this.once(type, wrapper);
        } else {
          this.on(type, wrapper);
        }
      },
      /**
       * Remove an event listener.
       *
       * @param {String} type A string representing the event type to remove
       * @param {(Function|Object)} handler The listener to remove
       * @public
       */
      removeEventListener(type, handler) {
        for (const listener of this.listeners(type)) {
          if (listener[kListener] === handler && !listener[kForOnEventAttribute]) {
            this.removeListener(type, listener);
            break;
          }
        }
      }
    };
    module2.exports = {
      CloseEvent,
      ErrorEvent,
      Event,
      EventTarget,
      MessageEvent
    };
    function callListener(listener, thisArg, event) {
      if (typeof listener === "object" && listener.handleEvent) {
        listener.handleEvent.call(listener, event);
      } else {
        listener.call(thisArg, event);
      }
    }
  }
});

// node_modules/ws/lib/extension.js
var require_extension = __commonJS({
  "node_modules/ws/lib/extension.js"(exports2, module2) {
    "use strict";
    var { tokenChars } = require_validation();
    function push(dest, name, elem) {
      if (dest[name] === void 0) dest[name] = [elem];
      else dest[name].push(elem);
    }
    function parse(header) {
      const offers = /* @__PURE__ */ Object.create(null);
      let params = /* @__PURE__ */ Object.create(null);
      let mustUnescape = false;
      let isEscaping = false;
      let inQuotes = false;
      let extensionName;
      let paramName;
      let start = -1;
      let code = -1;
      let end = -1;
      let i = 0;
      for (; i < header.length; i++) {
        code = header.charCodeAt(i);
        if (extensionName === void 0) {
          if (end === -1 && tokenChars[code] === 1) {
            if (start === -1) start = i;
          } else if (i !== 0 && (code === 32 || code === 9)) {
            if (end === -1 && start !== -1) end = i;
          } else if (code === 59 || code === 44) {
            if (start === -1) {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
            if (end === -1) end = i;
            const name = header.slice(start, end);
            if (code === 44) {
              push(offers, name, params);
              params = /* @__PURE__ */ Object.create(null);
            } else {
              extensionName = name;
            }
            start = end = -1;
          } else {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
        } else if (paramName === void 0) {
          if (end === -1 && tokenChars[code] === 1) {
            if (start === -1) start = i;
          } else if (code === 32 || code === 9) {
            if (end === -1 && start !== -1) end = i;
          } else if (code === 59 || code === 44) {
            if (start === -1) {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
            if (end === -1) end = i;
            push(params, header.slice(start, end), true);
            if (code === 44) {
              push(offers, extensionName, params);
              params = /* @__PURE__ */ Object.create(null);
              extensionName = void 0;
            }
            start = end = -1;
          } else if (code === 61 && start !== -1 && end === -1) {
            paramName = header.slice(start, i);
            start = end = -1;
          } else {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
        } else {
          if (isEscaping) {
            if (tokenChars[code] !== 1) {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
            if (start === -1) start = i;
            else if (!mustUnescape) mustUnescape = true;
            isEscaping = false;
          } else if (inQuotes) {
            if (tokenChars[code] === 1) {
              if (start === -1) start = i;
            } else if (code === 34 && start !== -1) {
              inQuotes = false;
              end = i;
            } else if (code === 92) {
              isEscaping = true;
            } else {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
          } else if (code === 34 && header.charCodeAt(i - 1) === 61) {
            inQuotes = true;
          } else if (end === -1 && tokenChars[code] === 1) {
            if (start === -1) start = i;
          } else if (start !== -1 && (code === 32 || code === 9)) {
            if (end === -1) end = i;
          } else if (code === 59 || code === 44) {
            if (start === -1) {
              throw new SyntaxError(`Unexpected character at index ${i}`);
            }
            if (end === -1) end = i;
            let value = header.slice(start, end);
            if (mustUnescape) {
              value = value.replace(/\\/g, "");
              mustUnescape = false;
            }
            push(params, paramName, value);
            if (code === 44) {
              push(offers, extensionName, params);
              params = /* @__PURE__ */ Object.create(null);
              extensionName = void 0;
            }
            paramName = void 0;
            start = end = -1;
          } else {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
        }
      }
      if (start === -1 || inQuotes || code === 32 || code === 9) {
        throw new SyntaxError("Unexpected end of input");
      }
      if (end === -1) end = i;
      const token = header.slice(start, end);
      if (extensionName === void 0) {
        push(offers, token, params);
      } else {
        if (paramName === void 0) {
          push(params, token, true);
        } else if (mustUnescape) {
          push(params, paramName, token.replace(/\\/g, ""));
        } else {
          push(params, paramName, token);
        }
        push(offers, extensionName, params);
      }
      return offers;
    }
    function format(extensions) {
      return Object.keys(extensions).map((extension) => {
        let configurations = extensions[extension];
        if (!Array.isArray(configurations)) configurations = [configurations];
        return configurations.map((params) => {
          return [extension].concat(
            Object.keys(params).map((k) => {
              let values = params[k];
              if (!Array.isArray(values)) values = [values];
              return values.map((v) => v === true ? k : `${k}=${v}`).join("; ");
            })
          ).join("; ");
        }).join(", ");
      }).join(", ");
    }
    module2.exports = { format, parse };
  }
});

// node_modules/ws/lib/websocket.js
var require_websocket = __commonJS({
  "node_modules/ws/lib/websocket.js"(exports2, module2) {
    "use strict";
    var EventEmitter = require("events");
    var https = require("https");
    var http2 = require("http");
    var net2 = require("net");
    var tls = require("tls");
    var { randomBytes, createHash } = require("crypto");
    var { Duplex, Readable } = require("stream");
    var { URL: URL2 } = require("url");
    var PerMessageDeflate = require_permessage_deflate();
    var Receiver = require_receiver();
    var Sender = require_sender();
    var { isBlob } = require_validation();
    var {
      BINARY_TYPES,
      CLOSE_TIMEOUT,
      EMPTY_BUFFER,
      GUID,
      kForOnEventAttribute,
      kListener,
      kStatusCode,
      kWebSocket,
      NOOP
    } = require_constants();
    var {
      EventTarget: { addEventListener, removeEventListener }
    } = require_event_target();
    var { format, parse } = require_extension();
    var { toBuffer } = require_buffer_util();
    var kAborted = Symbol("kAborted");
    var protocolVersions = [8, 13];
    var readyStates = ["CONNECTING", "OPEN", "CLOSING", "CLOSED"];
    var subprotocolRegex = /^[!#$%&'*+\-.0-9A-Z^_`|a-z~]+$/;
    var WebSocket = class _WebSocket extends EventEmitter {
      /**
       * Create a new `WebSocket`.
       *
       * @param {(String|URL)} address The URL to which to connect
       * @param {(String|String[])} [protocols] The subprotocols
       * @param {Object} [options] Connection options
       */
      constructor(address, protocols, options) {
        super();
        this._binaryType = BINARY_TYPES[0];
        this._closeCode = 1006;
        this._closeFrameReceived = false;
        this._closeFrameSent = false;
        this._closeMessage = EMPTY_BUFFER;
        this._closeTimer = null;
        this._errorEmitted = false;
        this._extensions = {};
        this._paused = false;
        this._protocol = "";
        this._readyState = _WebSocket.CONNECTING;
        this._receiver = null;
        this._sender = null;
        this._socket = null;
        if (address !== null) {
          this._bufferedAmount = 0;
          this._isServer = false;
          this._redirects = 0;
          if (protocols === void 0) {
            protocols = [];
          } else if (!Array.isArray(protocols)) {
            if (typeof protocols === "object" && protocols !== null) {
              options = protocols;
              protocols = [];
            } else {
              protocols = [protocols];
            }
          }
          initAsClient(this, address, protocols, options);
        } else {
          this._autoPong = options.autoPong;
          this._closeTimeout = options.closeTimeout;
          this._isServer = true;
        }
      }
      /**
       * For historical reasons, the custom "nodebuffer" type is used by the default
       * instead of "blob".
       *
       * @type {String}
       */
      get binaryType() {
        return this._binaryType;
      }
      set binaryType(type) {
        if (!BINARY_TYPES.includes(type)) return;
        this._binaryType = type;
        if (this._receiver) this._receiver._binaryType = type;
      }
      /**
       * @type {Number}
       */
      get bufferedAmount() {
        if (!this._socket) return this._bufferedAmount;
        return this._socket._writableState.length + this._sender._bufferedBytes;
      }
      /**
       * @type {String}
       */
      get extensions() {
        return Object.keys(this._extensions).join();
      }
      /**
       * @type {Boolean}
       */
      get isPaused() {
        return this._paused;
      }
      /**
       * @type {Function}
       */
      /* istanbul ignore next */
      get onclose() {
        return null;
      }
      /**
       * @type {Function}
       */
      /* istanbul ignore next */
      get onerror() {
        return null;
      }
      /**
       * @type {Function}
       */
      /* istanbul ignore next */
      get onopen() {
        return null;
      }
      /**
       * @type {Function}
       */
      /* istanbul ignore next */
      get onmessage() {
        return null;
      }
      /**
       * @type {String}
       */
      get protocol() {
        return this._protocol;
      }
      /**
       * @type {Number}
       */
      get readyState() {
        return this._readyState;
      }
      /**
       * @type {String}
       */
      get url() {
        return this._url;
      }
      /**
       * Set up the socket and the internal resources.
       *
       * @param {Duplex} socket The network socket between the server and client
       * @param {Buffer} head The first packet of the upgraded stream
       * @param {Object} options Options object
       * @param {Boolean} [options.allowSynchronousEvents=false] Specifies whether
       *     any of the `'message'`, `'ping'`, and `'pong'` events can be emitted
       *     multiple times in the same tick
       * @param {Function} [options.generateMask] The function used to generate the
       *     masking key
       * @param {Number} [options.maxBufferedChunks=0] The maximum number of
       *     buffered data chunks
       * @param {Number} [options.maxFragments=0] The maximum number of message
       *     fragments
       * @param {Number} [options.maxPayload=0] The maximum allowed message size
       * @param {Boolean} [options.skipUTF8Validation=false] Specifies whether or
       *     not to skip UTF-8 validation for text and close messages
       * @private
       */
      setSocket(socket, head, options) {
        const receiver = new Receiver({
          allowSynchronousEvents: options.allowSynchronousEvents,
          binaryType: this.binaryType,
          extensions: this._extensions,
          isServer: this._isServer,
          maxBufferedChunks: options.maxBufferedChunks,
          maxFragments: options.maxFragments,
          maxPayload: options.maxPayload,
          skipUTF8Validation: options.skipUTF8Validation
        });
        const sender = new Sender(socket, this._extensions, options.generateMask);
        this._receiver = receiver;
        this._sender = sender;
        this._socket = socket;
        receiver[kWebSocket] = this;
        sender[kWebSocket] = this;
        socket[kWebSocket] = this;
        receiver.on("conclude", receiverOnConclude);
        receiver.on("drain", receiverOnDrain);
        receiver.on("error", receiverOnError);
        receiver.on("message", receiverOnMessage);
        receiver.on("ping", receiverOnPing);
        receiver.on("pong", receiverOnPong);
        sender.onerror = senderOnError;
        if (socket.setTimeout) socket.setTimeout(0);
        if (socket.setNoDelay) socket.setNoDelay();
        if (head.length > 0) socket.unshift(head);
        socket.on("close", socketOnClose);
        socket.on("data", socketOnData);
        socket.on("end", socketOnEnd);
        socket.on("error", socketOnError);
        this._readyState = _WebSocket.OPEN;
        this.emit("open");
      }
      /**
       * Emit the `'close'` event.
       *
       * @private
       */
      emitClose() {
        if (!this._socket) {
          this._readyState = _WebSocket.CLOSED;
          this.emit("close", this._closeCode, this._closeMessage);
          return;
        }
        if (this._extensions[PerMessageDeflate.extensionName]) {
          this._extensions[PerMessageDeflate.extensionName].cleanup();
        }
        this._receiver.removeAllListeners();
        this._readyState = _WebSocket.CLOSED;
        this.emit("close", this._closeCode, this._closeMessage);
      }
      /**
       * Start a closing handshake.
       *
       *          +----------+   +-----------+   +----------+
       *     - - -|ws.close()|-->|close frame|-->|ws.close()|- - -
       *    |     +----------+   +-----------+   +----------+     |
       *          +----------+   +-----------+         |
       * CLOSING  |ws.close()|<--|close frame|<--+-----+       CLOSING
       *          +----------+   +-----------+   |
       *    |           |                        |   +---+        |
       *                +------------------------+-->|fin| - - - -
       *    |         +---+                      |   +---+
       *     - - - - -|fin|<---------------------+
       *              +---+
       *
       * @param {Number} [code] Status code explaining why the connection is closing
       * @param {(String|Buffer)} [data] The reason why the connection is
       *     closing
       * @public
       */
      close(code, data) {
        if (this.readyState === _WebSocket.CLOSED) return;
        if (this.readyState === _WebSocket.CONNECTING) {
          const msg = "WebSocket was closed before the connection was established";
          abortHandshake(this, this._req, msg);
          return;
        }
        if (this.readyState === _WebSocket.CLOSING) {
          if (this._closeFrameSent && (this._closeFrameReceived || this._receiver._writableState.errorEmitted)) {
            this._socket.end();
          }
          return;
        }
        this._readyState = _WebSocket.CLOSING;
        this._sender.close(code, data, !this._isServer, (err) => {
          if (err) return;
          this._closeFrameSent = true;
          if (this._closeFrameReceived || this._receiver._writableState.errorEmitted) {
            this._socket.end();
          }
        });
        setCloseTimer(this);
      }
      /**
       * Pause the socket.
       *
       * @public
       */
      pause() {
        if (this.readyState === _WebSocket.CONNECTING || this.readyState === _WebSocket.CLOSED) {
          return;
        }
        this._paused = true;
        this._socket.pause();
      }
      /**
       * Send a ping.
       *
       * @param {*} [data] The data to send
       * @param {Boolean} [mask] Indicates whether or not to mask `data`
       * @param {Function} [cb] Callback which is executed when the ping is sent
       * @public
       */
      ping(data, mask, cb) {
        if (this.readyState === _WebSocket.CONNECTING) {
          throw new Error("WebSocket is not open: readyState 0 (CONNECTING)");
        }
        if (typeof data === "function") {
          cb = data;
          data = mask = void 0;
        } else if (typeof mask === "function") {
          cb = mask;
          mask = void 0;
        }
        if (typeof data === "number") data = data.toString();
        if (this.readyState !== _WebSocket.OPEN) {
          sendAfterClose(this, data, cb);
          return;
        }
        if (mask === void 0) mask = !this._isServer;
        this._sender.ping(data || EMPTY_BUFFER, mask, cb);
      }
      /**
       * Send a pong.
       *
       * @param {*} [data] The data to send
       * @param {Boolean} [mask] Indicates whether or not to mask `data`
       * @param {Function} [cb] Callback which is executed when the pong is sent
       * @public
       */
      pong(data, mask, cb) {
        if (this.readyState === _WebSocket.CONNECTING) {
          throw new Error("WebSocket is not open: readyState 0 (CONNECTING)");
        }
        if (typeof data === "function") {
          cb = data;
          data = mask = void 0;
        } else if (typeof mask === "function") {
          cb = mask;
          mask = void 0;
        }
        if (typeof data === "number") data = data.toString();
        if (this.readyState !== _WebSocket.OPEN) {
          sendAfterClose(this, data, cb);
          return;
        }
        if (mask === void 0) mask = !this._isServer;
        this._sender.pong(data || EMPTY_BUFFER, mask, cb);
      }
      /**
       * Resume the socket.
       *
       * @public
       */
      resume() {
        if (this.readyState === _WebSocket.CONNECTING || this.readyState === _WebSocket.CLOSED) {
          return;
        }
        this._paused = false;
        if (!this._receiver._writableState.needDrain) this._socket.resume();
      }
      /**
       * Send a data message.
       *
       * @param {*} data The message to send
       * @param {Object} [options] Options object
       * @param {Boolean} [options.binary] Specifies whether `data` is binary or
       *     text
       * @param {Boolean} [options.compress] Specifies whether or not to compress
       *     `data`
       * @param {Boolean} [options.fin=true] Specifies whether the fragment is the
       *     last one
       * @param {Boolean} [options.mask] Specifies whether or not to mask `data`
       * @param {Function} [cb] Callback which is executed when data is written out
       * @public
       */
      send(data, options, cb) {
        if (this.readyState === _WebSocket.CONNECTING) {
          throw new Error("WebSocket is not open: readyState 0 (CONNECTING)");
        }
        if (typeof options === "function") {
          cb = options;
          options = {};
        }
        if (typeof data === "number") data = data.toString();
        if (this.readyState !== _WebSocket.OPEN) {
          sendAfterClose(this, data, cb);
          return;
        }
        const opts = {
          binary: typeof data !== "string",
          mask: !this._isServer,
          compress: true,
          fin: true,
          ...options
        };
        if (!this._extensions[PerMessageDeflate.extensionName]) {
          opts.compress = false;
        }
        this._sender.send(data || EMPTY_BUFFER, opts, cb);
      }
      /**
       * Forcibly close the connection.
       *
       * @public
       */
      terminate() {
        if (this.readyState === _WebSocket.CLOSED) return;
        if (this.readyState === _WebSocket.CONNECTING) {
          const msg = "WebSocket was closed before the connection was established";
          abortHandshake(this, this._req, msg);
          return;
        }
        if (this._socket) {
          this._readyState = _WebSocket.CLOSING;
          this._socket.destroy();
        }
      }
    };
    Object.defineProperty(WebSocket, "CONNECTING", {
      enumerable: true,
      value: readyStates.indexOf("CONNECTING")
    });
    Object.defineProperty(WebSocket.prototype, "CONNECTING", {
      enumerable: true,
      value: readyStates.indexOf("CONNECTING")
    });
    Object.defineProperty(WebSocket, "OPEN", {
      enumerable: true,
      value: readyStates.indexOf("OPEN")
    });
    Object.defineProperty(WebSocket.prototype, "OPEN", {
      enumerable: true,
      value: readyStates.indexOf("OPEN")
    });
    Object.defineProperty(WebSocket, "CLOSING", {
      enumerable: true,
      value: readyStates.indexOf("CLOSING")
    });
    Object.defineProperty(WebSocket.prototype, "CLOSING", {
      enumerable: true,
      value: readyStates.indexOf("CLOSING")
    });
    Object.defineProperty(WebSocket, "CLOSED", {
      enumerable: true,
      value: readyStates.indexOf("CLOSED")
    });
    Object.defineProperty(WebSocket.prototype, "CLOSED", {
      enumerable: true,
      value: readyStates.indexOf("CLOSED")
    });
    [
      "binaryType",
      "bufferedAmount",
      "extensions",
      "isPaused",
      "protocol",
      "readyState",
      "url"
    ].forEach((property) => {
      Object.defineProperty(WebSocket.prototype, property, { enumerable: true });
    });
    ["open", "error", "close", "message"].forEach((method) => {
      Object.defineProperty(WebSocket.prototype, `on${method}`, {
        enumerable: true,
        get() {
          for (const listener of this.listeners(method)) {
            if (listener[kForOnEventAttribute]) return listener[kListener];
          }
          return null;
        },
        set(handler) {
          for (const listener of this.listeners(method)) {
            if (listener[kForOnEventAttribute]) {
              this.removeListener(method, listener);
              break;
            }
          }
          if (typeof handler !== "function") return;
          this.addEventListener(method, handler, {
            [kForOnEventAttribute]: true
          });
        }
      });
    });
    WebSocket.prototype.addEventListener = addEventListener;
    WebSocket.prototype.removeEventListener = removeEventListener;
    module2.exports = WebSocket;
    function initAsClient(websocket, address, protocols, options) {
      const opts = {
        allowSynchronousEvents: true,
        autoPong: true,
        closeTimeout: CLOSE_TIMEOUT,
        protocolVersion: protocolVersions[1],
        maxBufferedChunks: 256 * 1024,
        maxFragments: 16 * 1024,
        maxPayload: 100 * 1024 * 1024,
        skipUTF8Validation: false,
        perMessageDeflate: true,
        followRedirects: false,
        maxRedirects: 10,
        ...options,
        socketPath: void 0,
        hostname: void 0,
        protocol: void 0,
        timeout: void 0,
        method: "GET",
        host: void 0,
        path: void 0,
        port: void 0
      };
      websocket._autoPong = opts.autoPong;
      websocket._closeTimeout = opts.closeTimeout;
      if (!protocolVersions.includes(opts.protocolVersion)) {
        throw new RangeError(
          `Unsupported protocol version: ${opts.protocolVersion} (supported versions: ${protocolVersions.join(", ")})`
        );
      }
      let parsedUrl;
      if (address instanceof URL2) {
        parsedUrl = address;
      } else {
        try {
          parsedUrl = new URL2(address);
        } catch {
          throw new SyntaxError(`Invalid URL: ${address}`);
        }
      }
      if (parsedUrl.protocol === "http:") {
        parsedUrl.protocol = "ws:";
      } else if (parsedUrl.protocol === "https:") {
        parsedUrl.protocol = "wss:";
      }
      websocket._url = parsedUrl.href;
      const isSecure = parsedUrl.protocol === "wss:";
      const isIpcUrl = parsedUrl.protocol === "ws+unix:";
      let invalidUrlMessage;
      if (parsedUrl.protocol !== "ws:" && !isSecure && !isIpcUrl) {
        invalidUrlMessage = `The URL's protocol must be one of "ws:", "wss:", "http:", "https:", or "ws+unix:"`;
      } else if (isIpcUrl && !parsedUrl.pathname) {
        invalidUrlMessage = "The URL's pathname is empty";
      } else if (parsedUrl.hash) {
        invalidUrlMessage = "The URL contains a fragment identifier";
      }
      if (invalidUrlMessage) {
        const err = new SyntaxError(invalidUrlMessage);
        if (websocket._redirects === 0) {
          throw err;
        } else {
          emitErrorAndClose(websocket, err);
          return;
        }
      }
      const defaultPort2 = isSecure ? 443 : 80;
      const key = randomBytes(16).toString("base64");
      const request = isSecure ? https.request : http2.request;
      const protocolSet = /* @__PURE__ */ new Set();
      let perMessageDeflate;
      opts.createConnection = opts.createConnection || (isSecure ? tlsConnect : netConnect);
      opts.defaultPort = opts.defaultPort || defaultPort2;
      opts.port = parsedUrl.port || defaultPort2;
      opts.host = parsedUrl.hostname.startsWith("[") ? parsedUrl.hostname.slice(1, -1) : parsedUrl.hostname;
      opts.headers = {
        ...opts.headers,
        "Sec-WebSocket-Version": opts.protocolVersion,
        "Sec-WebSocket-Key": key,
        Connection: "Upgrade",
        Upgrade: "websocket"
      };
      opts.path = parsedUrl.pathname + parsedUrl.search;
      opts.timeout = opts.handshakeTimeout;
      if (opts.perMessageDeflate) {
        perMessageDeflate = new PerMessageDeflate({
          ...opts.perMessageDeflate,
          isServer: false,
          maxPayload: opts.maxPayload
        });
        opts.headers["Sec-WebSocket-Extensions"] = format({
          [PerMessageDeflate.extensionName]: perMessageDeflate.offer()
        });
      }
      if (protocols.length) {
        for (const protocol of protocols) {
          if (typeof protocol !== "string" || !subprotocolRegex.test(protocol) || protocolSet.has(protocol)) {
            throw new SyntaxError(
              "An invalid or duplicated subprotocol was specified"
            );
          }
          protocolSet.add(protocol);
        }
        opts.headers["Sec-WebSocket-Protocol"] = protocols.join(",");
      }
      if (opts.origin) {
        if (opts.protocolVersion < 13) {
          opts.headers["Sec-WebSocket-Origin"] = opts.origin;
        } else {
          opts.headers.Origin = opts.origin;
        }
      }
      if (parsedUrl.username || parsedUrl.password) {
        opts.auth = `${parsedUrl.username}:${parsedUrl.password}`;
      }
      if (isIpcUrl) {
        const parts = opts.path.split(":");
        opts.socketPath = parts[0];
        opts.path = parts[1];
      }
      let req;
      if (opts.followRedirects) {
        if (websocket._redirects === 0) {
          websocket._originalIpc = isIpcUrl;
          websocket._originalSecure = isSecure;
          websocket._originalHostOrSocketPath = isIpcUrl ? opts.socketPath : parsedUrl.host;
          const headers = options && options.headers;
          options = { ...options, headers: {} };
          if (headers) {
            for (const [key2, value] of Object.entries(headers)) {
              options.headers[key2.toLowerCase()] = value;
            }
          }
        } else if (websocket.listenerCount("redirect") === 0) {
          const isSameHost = isIpcUrl ? websocket._originalIpc ? opts.socketPath === websocket._originalHostOrSocketPath : false : websocket._originalIpc ? false : parsedUrl.host === websocket._originalHostOrSocketPath;
          if (!isSameHost || websocket._originalSecure && !isSecure) {
            delete opts.headers.authorization;
            delete opts.headers.cookie;
            if (!isSameHost) delete opts.headers.host;
            opts.auth = void 0;
          }
        }
        if (opts.auth && !options.headers.authorization) {
          options.headers.authorization = "Basic " + Buffer.from(opts.auth).toString("base64");
        }
        req = websocket._req = request(opts);
        if (websocket._redirects) {
          websocket.emit("redirect", websocket.url, req);
        }
      } else {
        req = websocket._req = request(opts);
      }
      if (opts.timeout) {
        req.on("timeout", () => {
          abortHandshake(websocket, req, "Opening handshake has timed out");
        });
      }
      req.on("error", (err) => {
        if (req === null || req[kAborted]) return;
        req = websocket._req = null;
        emitErrorAndClose(websocket, err);
      });
      req.on("response", (res) => {
        const location = res.headers.location;
        const statusCode = res.statusCode;
        if (location && opts.followRedirects && statusCode >= 300 && statusCode < 400) {
          if (++websocket._redirects > opts.maxRedirects) {
            abortHandshake(websocket, req, "Maximum redirects exceeded");
            return;
          }
          req.abort();
          let addr;
          try {
            addr = new URL2(location, address);
          } catch (e) {
            const err = new SyntaxError(`Invalid URL: ${location}`);
            emitErrorAndClose(websocket, err);
            return;
          }
          initAsClient(websocket, addr, protocols, options);
        } else if (!websocket.emit("unexpected-response", req, res)) {
          abortHandshake(
            websocket,
            req,
            `Unexpected server response: ${res.statusCode}`
          );
        }
      });
      req.on("upgrade", (res, socket, head) => {
        websocket.emit("upgrade", res);
        if (websocket.readyState !== WebSocket.CONNECTING) return;
        req = websocket._req = null;
        const upgrade = res.headers.upgrade;
        if (upgrade === void 0 || upgrade.toLowerCase() !== "websocket") {
          abortHandshake(websocket, socket, "Invalid Upgrade header");
          return;
        }
        const digest = createHash("sha1").update(key + GUID).digest("base64");
        if (res.headers["sec-websocket-accept"] !== digest) {
          abortHandshake(websocket, socket, "Invalid Sec-WebSocket-Accept header");
          return;
        }
        const serverProt = res.headers["sec-websocket-protocol"];
        let protError;
        if (serverProt !== void 0) {
          if (!protocolSet.size) {
            protError = "Server sent a subprotocol but none was requested";
          } else if (!protocolSet.has(serverProt)) {
            protError = "Server sent an invalid subprotocol";
          }
        } else if (protocolSet.size) {
          protError = "Server sent no subprotocol";
        }
        if (protError) {
          abortHandshake(websocket, socket, protError);
          return;
        }
        if (serverProt) websocket._protocol = serverProt;
        const secWebSocketExtensions = res.headers["sec-websocket-extensions"];
        if (secWebSocketExtensions !== void 0) {
          if (!perMessageDeflate) {
            const message = "Server sent a Sec-WebSocket-Extensions header but no extension was requested";
            abortHandshake(websocket, socket, message);
            return;
          }
          let extensions;
          try {
            extensions = parse(secWebSocketExtensions);
          } catch (err) {
            const message = "Invalid Sec-WebSocket-Extensions header";
            abortHandshake(websocket, socket, message);
            return;
          }
          const extensionNames = Object.keys(extensions);
          if (extensionNames.length !== 1 || extensionNames[0] !== PerMessageDeflate.extensionName) {
            const message = "Server indicated an extension that was not requested";
            abortHandshake(websocket, socket, message);
            return;
          }
          try {
            perMessageDeflate.accept(extensions[PerMessageDeflate.extensionName]);
          } catch (err) {
            const message = "Invalid Sec-WebSocket-Extensions header";
            abortHandshake(websocket, socket, message);
            return;
          }
          websocket._extensions[PerMessageDeflate.extensionName] = perMessageDeflate;
        }
        websocket.setSocket(socket, head, {
          allowSynchronousEvents: opts.allowSynchronousEvents,
          generateMask: opts.generateMask,
          maxBufferedChunks: opts.maxBufferedChunks,
          maxFragments: opts.maxFragments,
          maxPayload: opts.maxPayload,
          skipUTF8Validation: opts.skipUTF8Validation
        });
      });
      if (opts.finishRequest) {
        opts.finishRequest(req, websocket);
      } else {
        req.end();
      }
    }
    function emitErrorAndClose(websocket, err) {
      websocket._readyState = WebSocket.CLOSING;
      websocket._errorEmitted = true;
      websocket.emit("error", err);
      websocket.emitClose();
    }
    function netConnect(options) {
      options.path = options.socketPath;
      return net2.connect(options);
    }
    function tlsConnect(options) {
      options.path = void 0;
      if (!options.servername && options.servername !== "") {
        options.servername = net2.isIP(options.host) ? "" : options.host;
      }
      return tls.connect(options);
    }
    function abortHandshake(websocket, stream, message) {
      websocket._readyState = WebSocket.CLOSING;
      const err = new Error(message);
      Error.captureStackTrace(err, abortHandshake);
      if (stream.setHeader) {
        stream[kAborted] = true;
        stream.abort();
        if (stream.socket && !stream.socket.destroyed) {
          stream.socket.destroy();
        }
        process.nextTick(emitErrorAndClose, websocket, err);
      } else {
        stream.destroy(err);
        stream.once("error", websocket.emit.bind(websocket, "error"));
        stream.once("close", websocket.emitClose.bind(websocket));
      }
    }
    function sendAfterClose(websocket, data, cb) {
      if (data) {
        const length = isBlob(data) ? data.size : toBuffer(data).length;
        if (websocket._socket) websocket._sender._bufferedBytes += length;
        else websocket._bufferedAmount += length;
      }
      if (cb) {
        const err = new Error(
          `WebSocket is not open: readyState ${websocket.readyState} (${readyStates[websocket.readyState]})`
        );
        process.nextTick(cb, err);
      }
    }
    function receiverOnConclude(code, reason) {
      const websocket = this[kWebSocket];
      websocket._closeFrameReceived = true;
      websocket._closeMessage = reason;
      websocket._closeCode = code;
      if (websocket._socket[kWebSocket] === void 0) return;
      websocket._socket.removeListener("data", socketOnData);
      process.nextTick(resume, websocket._socket);
      if (code === 1005) websocket.close();
      else websocket.close(code, reason);
    }
    function receiverOnDrain() {
      const websocket = this[kWebSocket];
      if (!websocket.isPaused) websocket._socket.resume();
    }
    function receiverOnError(err) {
      const websocket = this[kWebSocket];
      if (websocket._socket[kWebSocket] !== void 0) {
        websocket._socket.removeListener("data", socketOnData);
        process.nextTick(resume, websocket._socket);
        websocket.close(err[kStatusCode]);
      }
      if (!websocket._errorEmitted) {
        websocket._errorEmitted = true;
        websocket.emit("error", err);
      }
    }
    function receiverOnFinish() {
      this[kWebSocket].emitClose();
    }
    function receiverOnMessage(data, isBinary) {
      this[kWebSocket].emit("message", data, isBinary);
    }
    function receiverOnPing(data) {
      const websocket = this[kWebSocket];
      if (websocket._autoPong) websocket.pong(data, !this._isServer, NOOP);
      websocket.emit("ping", data);
    }
    function receiverOnPong(data) {
      this[kWebSocket].emit("pong", data);
    }
    function resume(stream) {
      stream.resume();
    }
    function senderOnError(err) {
      const websocket = this[kWebSocket];
      if (websocket.readyState === WebSocket.CLOSED) return;
      if (websocket.readyState === WebSocket.OPEN) {
        websocket._readyState = WebSocket.CLOSING;
        setCloseTimer(websocket);
      }
      this._socket.end();
      if (!websocket._errorEmitted) {
        websocket._errorEmitted = true;
        websocket.emit("error", err);
      }
    }
    function setCloseTimer(websocket) {
      websocket._closeTimer = setTimeout(
        websocket._socket.destroy.bind(websocket._socket),
        websocket._closeTimeout
      );
    }
    function socketOnClose() {
      const websocket = this[kWebSocket];
      this.removeListener("close", socketOnClose);
      this.removeListener("data", socketOnData);
      this.removeListener("end", socketOnEnd);
      websocket._readyState = WebSocket.CLOSING;
      if (!this._readableState.endEmitted && !websocket._closeFrameReceived && !websocket._receiver._writableState.errorEmitted && this._readableState.length !== 0) {
        const chunk = this.read(this._readableState.length);
        websocket._receiver.write(chunk);
      }
      websocket._receiver.end();
      this[kWebSocket] = void 0;
      clearTimeout(websocket._closeTimer);
      if (websocket._receiver._writableState.finished || websocket._receiver._writableState.errorEmitted) {
        websocket.emitClose();
      } else {
        websocket._receiver.on("error", receiverOnFinish);
        websocket._receiver.on("finish", receiverOnFinish);
      }
    }
    function socketOnData(chunk) {
      if (!this[kWebSocket]._receiver.write(chunk)) {
        this.pause();
      }
    }
    function socketOnEnd() {
      const websocket = this[kWebSocket];
      websocket._readyState = WebSocket.CLOSING;
      websocket._receiver.end();
      this.end();
    }
    function socketOnError() {
      const websocket = this[kWebSocket];
      this.removeListener("error", socketOnError);
      this.on("error", NOOP);
      if (websocket) {
        websocket._readyState = WebSocket.CLOSING;
        this.destroy();
      }
    }
  }
});

// node_modules/ws/lib/stream.js
var require_stream = __commonJS({
  "node_modules/ws/lib/stream.js"(exports2, module2) {
    "use strict";
    var WebSocket = require_websocket();
    var { Duplex } = require("stream");
    function emitClose(stream) {
      stream.emit("close");
    }
    function duplexOnEnd() {
      if (!this.destroyed && this._writableState.finished) {
        this.destroy();
      }
    }
    function duplexOnError(err) {
      this.removeListener("error", duplexOnError);
      this.destroy();
      if (this.listenerCount("error") === 0) {
        this.emit("error", err);
      }
    }
    function createWebSocketStream(ws, options) {
      let terminateOnDestroy = true;
      const duplex = new Duplex({
        ...options,
        autoDestroy: false,
        emitClose: false,
        objectMode: false,
        writableObjectMode: false
      });
      ws.on("message", function message(msg, isBinary) {
        const data = !isBinary && duplex._readableState.objectMode ? msg.toString() : msg;
        if (!duplex.push(data)) ws.pause();
      });
      ws.once("error", function error(err) {
        if (duplex.destroyed) return;
        terminateOnDestroy = false;
        duplex.destroy(err);
      });
      ws.once("close", function close() {
        if (duplex.destroyed) return;
        duplex.push(null);
      });
      duplex._destroy = function(err, callback) {
        if (ws.readyState === ws.CLOSED) {
          callback(err);
          process.nextTick(emitClose, duplex);
          return;
        }
        let called = false;
        ws.once("error", function error(err2) {
          called = true;
          callback(err2);
        });
        ws.once("close", function close() {
          if (!called) callback(err);
          process.nextTick(emitClose, duplex);
        });
        if (terminateOnDestroy) ws.terminate();
      };
      duplex._final = function(callback) {
        if (ws.readyState === ws.CONNECTING) {
          ws.once("open", function open() {
            duplex._final(callback);
          });
          return;
        }
        if (ws._socket === null) return;
        if (ws._socket._writableState.finished) {
          callback();
          if (duplex._readableState.endEmitted) duplex.destroy();
        } else {
          ws._socket.once("finish", function finish() {
            callback();
          });
          ws.close();
        }
      };
      duplex._read = function() {
        if (ws.isPaused) ws.resume();
      };
      duplex._write = function(chunk, encoding, callback) {
        if (ws.readyState === ws.CONNECTING) {
          ws.once("open", function open() {
            duplex._write(chunk, encoding, callback);
          });
          return;
        }
        ws.send(chunk, callback);
      };
      duplex.on("end", duplexOnEnd);
      duplex.on("error", duplexOnError);
      return duplex;
    }
    module2.exports = createWebSocketStream;
  }
});

// node_modules/ws/lib/subprotocol.js
var require_subprotocol = __commonJS({
  "node_modules/ws/lib/subprotocol.js"(exports2, module2) {
    "use strict";
    var { tokenChars } = require_validation();
    function parse(header) {
      const protocols = /* @__PURE__ */ new Set();
      let start = -1;
      let end = -1;
      let i = 0;
      for (i; i < header.length; i++) {
        const code = header.charCodeAt(i);
        if (end === -1 && tokenChars[code] === 1) {
          if (start === -1) start = i;
        } else if (i !== 0 && (code === 32 || code === 9)) {
          if (end === -1 && start !== -1) end = i;
        } else if (code === 44) {
          if (start === -1) {
            throw new SyntaxError(`Unexpected character at index ${i}`);
          }
          if (end === -1) end = i;
          const protocol2 = header.slice(start, end);
          if (protocols.has(protocol2)) {
            throw new SyntaxError(`The "${protocol2}" subprotocol is duplicated`);
          }
          protocols.add(protocol2);
          start = end = -1;
        } else {
          throw new SyntaxError(`Unexpected character at index ${i}`);
        }
      }
      if (start === -1 || end !== -1) {
        throw new SyntaxError("Unexpected end of input");
      }
      const protocol = header.slice(start, i);
      if (protocols.has(protocol)) {
        throw new SyntaxError(`The "${protocol}" subprotocol is duplicated`);
      }
      protocols.add(protocol);
      return protocols;
    }
    module2.exports = { parse };
  }
});

// node_modules/ws/lib/websocket-server.js
var require_websocket_server = __commonJS({
  "node_modules/ws/lib/websocket-server.js"(exports2, module2) {
    "use strict";
    var EventEmitter = require("events");
    var http2 = require("http");
    var { Duplex } = require("stream");
    var { createHash } = require("crypto");
    var extension = require_extension();
    var PerMessageDeflate = require_permessage_deflate();
    var subprotocol = require_subprotocol();
    var WebSocket = require_websocket();
    var { CLOSE_TIMEOUT, GUID, kWebSocket } = require_constants();
    var keyRegex = /^[+/0-9A-Za-z]{22}==$/;
    var RUNNING = 0;
    var CLOSING = 1;
    var CLOSED = 2;
    var WebSocketServer = class extends EventEmitter {
      /**
       * Create a `WebSocketServer` instance.
       *
       * @param {Object} options Configuration options
       * @param {Boolean} [options.allowSynchronousEvents=true] Specifies whether
       *     any of the `'message'`, `'ping'`, and `'pong'` events can be emitted
       *     multiple times in the same tick
       * @param {Boolean} [options.autoPong=true] Specifies whether or not to
       *     automatically send a pong in response to a ping
       * @param {Number} [options.backlog=511] The maximum length of the queue of
       *     pending connections
       * @param {Boolean} [options.clientTracking=true] Specifies whether or not to
       *     track clients
       * @param {Number} [options.closeTimeout=30000] Duration in milliseconds to
       *     wait for the closing handshake to finish after `websocket.close()` is
       *     called
       * @param {Function} [options.handleProtocols] A hook to handle protocols
       * @param {String} [options.host] The hostname where to bind the server
       * @param {Number} [options.maxBufferedChunks=262144] The maximum number of
       *     buffered data chunks
       * @param {Number} [options.maxFragments=16384] The maximum number of message
       *     fragments
       * @param {Number} [options.maxPayload=104857600] The maximum allowed message
       *     size
       * @param {Boolean} [options.noServer=false] Enable no server mode
       * @param {String} [options.path] Accept only connections matching this path
       * @param {(Boolean|Object)} [options.perMessageDeflate=false] Enable/disable
       *     permessage-deflate
       * @param {Number} [options.port] The port where to bind the server
       * @param {(http.Server|https.Server)} [options.server] A pre-created HTTP/S
       *     server to use
       * @param {Boolean} [options.skipUTF8Validation=false] Specifies whether or
       *     not to skip UTF-8 validation for text and close messages
       * @param {Function} [options.verifyClient] A hook to reject connections
       * @param {Function} [options.WebSocket=WebSocket] Specifies the `WebSocket`
       *     class to use. It must be the `WebSocket` class or class that extends it
       * @param {Function} [callback] A listener for the `listening` event
       */
      constructor(options, callback) {
        super();
        options = {
          allowSynchronousEvents: true,
          autoPong: true,
          maxBufferedChunks: 256 * 1024,
          maxFragments: 16 * 1024,
          maxPayload: 100 * 1024 * 1024,
          skipUTF8Validation: false,
          perMessageDeflate: false,
          handleProtocols: null,
          clientTracking: true,
          closeTimeout: CLOSE_TIMEOUT,
          verifyClient: null,
          noServer: false,
          backlog: null,
          // use default (511 as implemented in net.js)
          server: null,
          host: null,
          path: null,
          port: null,
          WebSocket,
          ...options
        };
        if (options.port == null && !options.server && !options.noServer || options.port != null && (options.server || options.noServer) || options.server && options.noServer) {
          throw new TypeError(
            'One and only one of the "port", "server", or "noServer" options must be specified'
          );
        }
        if (options.port != null) {
          this._server = http2.createServer((req, res) => {
            const body = http2.STATUS_CODES[426];
            res.writeHead(426, {
              "Content-Length": body.length,
              "Content-Type": "text/plain"
            });
            res.end(body);
          });
          this._server.listen(
            options.port,
            options.host,
            options.backlog,
            callback
          );
        } else if (options.server) {
          this._server = options.server;
        }
        if (this._server) {
          const emitConnection = this.emit.bind(this, "connection");
          this._removeListeners = addListeners(this._server, {
            listening: this.emit.bind(this, "listening"),
            error: this.emit.bind(this, "error"),
            upgrade: (req, socket, head) => {
              this.handleUpgrade(req, socket, head, emitConnection);
            }
          });
        }
        if (options.perMessageDeflate === true) options.perMessageDeflate = {};
        if (options.clientTracking) {
          this.clients = /* @__PURE__ */ new Set();
          this._shouldEmitClose = false;
        }
        this.options = options;
        this._state = RUNNING;
      }
      /**
       * Returns the bound address, the address family name, and port of the server
       * as reported by the operating system if listening on an IP socket.
       * If the server is listening on a pipe or UNIX domain socket, the name is
       * returned as a string.
       *
       * @return {(Object|String|null)} The address of the server
       * @public
       */
      address() {
        if (this.options.noServer) {
          throw new Error('The server is operating in "noServer" mode');
        }
        if (!this._server) return null;
        return this._server.address();
      }
      /**
       * Stop the server from accepting new connections and emit the `'close'` event
       * when all existing connections are closed.
       *
       * @param {Function} [cb] A one-time listener for the `'close'` event
       * @public
       */
      close(cb) {
        if (this._state === CLOSED) {
          if (cb) {
            this.once("close", () => {
              cb(new Error("The server is not running"));
            });
          }
          process.nextTick(emitClose, this);
          return;
        }
        if (cb) this.once("close", cb);
        if (this._state === CLOSING) return;
        this._state = CLOSING;
        if (this.options.noServer || this.options.server) {
          if (this._server) {
            this._removeListeners();
            this._removeListeners = this._server = null;
          }
          if (this.clients) {
            if (!this.clients.size) {
              process.nextTick(emitClose, this);
            } else {
              this._shouldEmitClose = true;
            }
          } else {
            process.nextTick(emitClose, this);
          }
        } else {
          const server = this._server;
          this._removeListeners();
          this._removeListeners = this._server = null;
          server.close(() => {
            emitClose(this);
          });
        }
      }
      /**
       * See if a given request should be handled by this server instance.
       *
       * @param {http.IncomingMessage} req Request object to inspect
       * @return {Boolean} `true` if the request is valid, else `false`
       * @public
       */
      shouldHandle(req) {
        if (this.options.path) {
          const index = req.url.indexOf("?");
          const pathname = index !== -1 ? req.url.slice(0, index) : req.url;
          if (pathname !== this.options.path) return false;
        }
        return true;
      }
      /**
       * Handle a HTTP Upgrade request.
       *
       * @param {http.IncomingMessage} req The request object
       * @param {Duplex} socket The network socket between the server and client
       * @param {Buffer} head The first packet of the upgraded stream
       * @param {Function} cb Callback
       * @public
       */
      handleUpgrade(req, socket, head, cb) {
        socket.on("error", socketOnError);
        const key = req.headers["sec-websocket-key"];
        const upgrade = req.headers.upgrade;
        const version = +req.headers["sec-websocket-version"];
        if (req.method !== "GET") {
          const message = "Invalid HTTP method";
          abortHandshakeOrEmitwsClientError(this, req, socket, 405, message);
          return;
        }
        if (upgrade === void 0 || upgrade.toLowerCase() !== "websocket") {
          const message = "Invalid Upgrade header";
          abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
          return;
        }
        if (key === void 0 || !keyRegex.test(key)) {
          const message = "Missing or invalid Sec-WebSocket-Key header";
          abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
          return;
        }
        if (version !== 13 && version !== 8) {
          const message = "Missing or invalid Sec-WebSocket-Version header";
          abortHandshakeOrEmitwsClientError(this, req, socket, 400, message, {
            "Sec-WebSocket-Version": "13, 8"
          });
          return;
        }
        if (!this.shouldHandle(req)) {
          abortHandshake(socket, 400);
          return;
        }
        const secWebSocketProtocol = req.headers["sec-websocket-protocol"];
        let protocols = /* @__PURE__ */ new Set();
        if (secWebSocketProtocol !== void 0) {
          try {
            protocols = subprotocol.parse(secWebSocketProtocol);
          } catch (err) {
            const message = "Invalid Sec-WebSocket-Protocol header";
            abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
            return;
          }
        }
        const secWebSocketExtensions = req.headers["sec-websocket-extensions"];
        const extensions = {};
        if (this.options.perMessageDeflate && secWebSocketExtensions !== void 0) {
          const perMessageDeflate = new PerMessageDeflate({
            ...this.options.perMessageDeflate,
            isServer: true,
            maxPayload: this.options.maxPayload
          });
          try {
            const offers = extension.parse(secWebSocketExtensions);
            if (offers[PerMessageDeflate.extensionName]) {
              perMessageDeflate.accept(offers[PerMessageDeflate.extensionName]);
              extensions[PerMessageDeflate.extensionName] = perMessageDeflate;
            }
          } catch (err) {
            const message = "Invalid or unacceptable Sec-WebSocket-Extensions header";
            abortHandshakeOrEmitwsClientError(this, req, socket, 400, message);
            return;
          }
        }
        if (this.options.verifyClient) {
          const info = {
            origin: req.headers[`${version === 8 ? "sec-websocket-origin" : "origin"}`],
            secure: !!(req.socket.authorized || req.socket.encrypted),
            req
          };
          if (this.options.verifyClient.length === 2) {
            this.options.verifyClient(info, (verified, code, message, headers) => {
              if (!verified) {
                return abortHandshake(socket, code || 401, message, headers);
              }
              this.completeUpgrade(
                extensions,
                key,
                protocols,
                req,
                socket,
                head,
                cb
              );
            });
            return;
          }
          if (!this.options.verifyClient(info)) return abortHandshake(socket, 401);
        }
        this.completeUpgrade(extensions, key, protocols, req, socket, head, cb);
      }
      /**
       * Upgrade the connection to WebSocket.
       *
       * @param {Object} extensions The accepted extensions
       * @param {String} key The value of the `Sec-WebSocket-Key` header
       * @param {Set} protocols The subprotocols
       * @param {http.IncomingMessage} req The request object
       * @param {Duplex} socket The network socket between the server and client
       * @param {Buffer} head The first packet of the upgraded stream
       * @param {Function} cb Callback
       * @throws {Error} If called more than once with the same socket
       * @private
       */
      completeUpgrade(extensions, key, protocols, req, socket, head, cb) {
        if (!socket.readable || !socket.writable) return socket.destroy();
        if (socket[kWebSocket]) {
          throw new Error(
            "server.handleUpgrade() was called more than once with the same socket, possibly due to a misconfiguration"
          );
        }
        if (this._state > RUNNING) return abortHandshake(socket, 503);
        const digest = createHash("sha1").update(key + GUID).digest("base64");
        const headers = [
          "HTTP/1.1 101 Switching Protocols",
          "Upgrade: websocket",
          "Connection: Upgrade",
          `Sec-WebSocket-Accept: ${digest}`
        ];
        const ws = new this.options.WebSocket(null, void 0, this.options);
        if (protocols.size) {
          const protocol = this.options.handleProtocols ? this.options.handleProtocols(protocols, req) : protocols.values().next().value;
          if (protocol) {
            headers.push(`Sec-WebSocket-Protocol: ${protocol}`);
            ws._protocol = protocol;
          }
        }
        if (extensions[PerMessageDeflate.extensionName]) {
          const params = extensions[PerMessageDeflate.extensionName].params;
          const value = extension.format({
            [PerMessageDeflate.extensionName]: [params]
          });
          headers.push(`Sec-WebSocket-Extensions: ${value}`);
          ws._extensions = extensions;
        }
        this.emit("headers", headers, req);
        socket.write(headers.concat("\r\n").join("\r\n"));
        socket.removeListener("error", socketOnError);
        ws.setSocket(socket, head, {
          allowSynchronousEvents: this.options.allowSynchronousEvents,
          maxBufferedChunks: this.options.maxBufferedChunks,
          maxFragments: this.options.maxFragments,
          maxPayload: this.options.maxPayload,
          skipUTF8Validation: this.options.skipUTF8Validation
        });
        if (this.clients) {
          this.clients.add(ws);
          ws.on("close", () => {
            this.clients.delete(ws);
            if (this._shouldEmitClose && !this.clients.size) {
              process.nextTick(emitClose, this);
            }
          });
        }
        cb(ws, req);
      }
    };
    module2.exports = WebSocketServer;
    function addListeners(server, map) {
      for (const event of Object.keys(map)) server.on(event, map[event]);
      return function removeListeners() {
        for (const event of Object.keys(map)) {
          server.removeListener(event, map[event]);
        }
      };
    }
    function emitClose(server) {
      server._state = CLOSED;
      server.emit("close");
    }
    function socketOnError() {
      this.destroy();
    }
    function abortHandshake(socket, code, message, headers) {
      message = message || http2.STATUS_CODES[code];
      headers = {
        Connection: "close",
        "Content-Type": "text/html",
        "Content-Length": Buffer.byteLength(message),
        ...headers
      };
      socket.once("finish", socket.destroy);
      socket.end(
        `HTTP/1.1 ${code} ${http2.STATUS_CODES[code]}\r
` + Object.keys(headers).map((h) => `${h}: ${headers[h]}`).join("\r\n") + "\r\n\r\n" + message
      );
    }
    function abortHandshakeOrEmitwsClientError(server, req, socket, code, message, headers) {
      if (server.listenerCount("wsClientError")) {
        const err = new Error(message);
        Error.captureStackTrace(err, abortHandshakeOrEmitwsClientError);
        server.emit("wsClientError", err, socket, req);
      } else {
        abortHandshake(socket, code, message, headers);
      }
    }
  }
});

// node_modules/ws/index.js
var require_ws = __commonJS({
  "node_modules/ws/index.js"(exports2, module2) {
    "use strict";
    var createWebSocketStream = require_stream();
    var extension = require_extension();
    var PerMessageDeflate = require_permessage_deflate();
    var Receiver = require_receiver();
    var Sender = require_sender();
    var subprotocol = require_subprotocol();
    var WebSocket = require_websocket();
    var WebSocketServer = require_websocket_server();
    WebSocket.createWebSocketStream = createWebSocketStream;
    WebSocket.extension = extension;
    WebSocket.PerMessageDeflate = PerMessageDeflate;
    WebSocket.Receiver = Receiver;
    WebSocket.Sender = Sender;
    WebSocket.Server = WebSocketServer;
    WebSocket.subprotocol = subprotocol;
    WebSocket.WebSocket = WebSocket;
    WebSocket.WebSocketServer = WebSocketServer;
    module2.exports = WebSocket;
  }
});

// electron/adaptive-websocket.js
var require_adaptive_websocket = __commonJS({
  "electron/adaptive-websocket.js"(exports2, module2) {
    "use strict";
    var { HttpsProxyAgent } = require_dist2();
    var WebSocket = require_ws();
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
    function createAdaptiveWebSocketClass2({
      resolveProxy,
      WebSocketImpl = WebSocket,
      proxyAgentFactory = (proxyUrl) => new HttpsProxyAgent(proxyUrl),
      attemptTimeoutMs = 8e3,
      onRouteSelected = () => {
      }
    } = {}) {
      if (typeof resolveProxy !== "function") throw new TypeError("resolveProxy must be a function");
      if (typeof WebSocketImpl !== "function") throw new TypeError("WebSocketImpl must be a constructor");
      if (typeof proxyAgentFactory !== "function") throw new TypeError("proxyAgentFactory must be a function");
      if (!Number.isInteger(attemptTimeoutMs) || attemptTimeoutMs <= 0) {
        throw new TypeError("attemptTimeoutMs must be a positive integer");
      }
      return class AdaptiveWebSocket {
        #attempts = /* @__PURE__ */ new Map();
        #closed = false;
        #failures = [];
        #listeners = /* @__PURE__ */ new Map();
        #remaining = 0;
        #winner = null;
        constructor(url) {
          this.url = String(url || "");
          queueMicrotask(() => this.#start());
        }
        addEventListener(type, listener) {
          if (typeof listener !== "function") return;
          const listeners = this.#listeners.get(type) || /* @__PURE__ */ new Set();
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
            }, attemptTimeoutMs)
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
              error: new Error(`All multiplayer routes failed (${this.#failures.join("; ")})`)
            });
          }
        }
        #emit(type, event) {
          for (const listener of [...this.#listeners.get(type) || []]) listener(event);
        }
      };
    }
    module2.exports = {
      createAdaptiveWebSocketClass: createAdaptiveWebSocketClass2,
      firstSupportedProxy
    };
  }
});

// electron/lan-manager.js
var require_lan_manager = __commonJS({
  "electron/lan-manager.js"(exports2, module2) {
    "use strict";
    var childProcess = require("node:child_process");
    var dgramModule = require("node:dgram");
    var netModule = require("node:net");
    var osModule = require("node:os");
    var path2 = require("node:path");
    var SERVICE = "zz-multiplayer";
    var PROTOCOL_VERSION = 1;
    var DEFAULT_HOST_PORT = 32145;
    var DEFAULT_DISCOVERY_PORT = 32146;
    var BROADCAST_ADDRESS = "255.255.255.255";
    var STARTUP_MARKER = "Serving ZZ multiplayer WebSocket at ";
    var DISCOVERY_KEYS = Object.freeze([
      "capacity",
      "host",
      "players",
      "port",
      "protocolVersion",
      "roomCode",
      "serverName",
      "service"
    ]);
    var LanManager2 = class {
      #spawn;
      #dgram;
      #net;
      #os;
      #clock;
      #timers;
      #discoveryPort;
      #broadcastIntervalMs;
      #readinessTimeoutMs;
      #stopTimeoutMs;
      #maxPacketBytes;
      #maxLogEntries;
      #maxLogChars;
      #process = null;
      #hostConfig = null;
      #state = "stopped";
      #startPromise = null;
      #stopPromise = null;
      #broadcastSocket = null;
      #broadcastInterval = null;
      #roomPacket = null;
      #discoveries = /* @__PURE__ */ new Set();
      #logs = [];
      #lastError = null;
      constructor({
        spawn: spawn2 = childProcess.spawn,
        dgram = dgramModule,
        net: net2 = netModule,
        os = osModule,
        clock = () => Date.now(),
        timers = globalThis,
        discoveryPort = DEFAULT_DISCOVERY_PORT,
        broadcastIntervalMs = 1e3,
        readinessTimeoutMs = 15e3,
        stopTimeoutMs = 3e3,
        maxPacketBytes = 1024,
        maxLogEntries = 40,
        maxLogChars = 2e3
      } = {}) {
        if (typeof spawn2 !== "function") throw new TypeError("spawn must be a function");
        if (!dgram || typeof dgram.createSocket !== "function") throw new TypeError("dgram.createSocket is required");
        if (!net2 || typeof net2.isIP !== "function") {
          throw new TypeError("net.isIP is required");
        }
        if (!os || typeof os.networkInterfaces !== "function") throw new TypeError("os.networkInterfaces is required");
        if (typeof clock !== "function" && (!clock || typeof clock.now !== "function")) {
          throw new TypeError("clock must be a function or expose now()");
        }
        for (const name of ["setTimeout", "clearTimeout", "setInterval", "clearInterval"]) {
          if (!timers || typeof timers[name] !== "function") throw new TypeError(`timers.${name} is required`);
        }
        this.#spawn = spawn2;
        this.#dgram = dgram;
        this.#net = net2;
        this.#os = os;
        this.#clock = typeof clock === "function" ? clock : () => clock.now();
        this.#timers = timers;
        this.#discoveryPort = requirePort(discoveryPort, "discoveryPort");
        this.#broadcastIntervalMs = requirePositiveInteger(broadcastIntervalMs, "broadcastIntervalMs");
        this.#readinessTimeoutMs = requirePositiveInteger(readinessTimeoutMs, "readinessTimeoutMs");
        this.#stopTimeoutMs = requirePositiveInteger(stopTimeoutMs, "stopTimeoutMs");
        this.#maxPacketBytes = requirePositiveInteger(maxPacketBytes, "maxPacketBytes");
        this.#maxLogEntries = requirePositiveInteger(maxLogEntries, "maxLogEntries");
        this.#maxLogChars = requirePositiveInteger(maxLogChars, "maxLogChars");
      }
      startHost({ projectRoot: projectRoot2, python = "python", port = DEFAULT_HOST_PORT, serverName } = {}) {
        const config = {
          projectRoot: requireAbsolutePath(projectRoot2, "projectRoot"),
          python: requireNonBlankString(python, "python"),
          port: requirePort(port, "port"),
          serverName: normalizeServerName(serverName, this.#os)
        };
        if (this.#state === "starting" || this.#state === "running") {
          if (!sameHostConfig(config, this.#hostConfig)) {
            throw new Error("LAN host is already active with different settings");
          }
          return this.#startPromise || Promise.resolve(this.getSnapshot());
        }
        if (this.#state === "stopping") throw new Error("LAN host is stopping");
        this.#hostConfig = config;
        this.#state = "starting";
        this.#lastError = null;
        const args = [
          "-m",
          "zz.multiplayer.websocket_server",
          "--host",
          "0.0.0.0",
          "--port",
          String(config.port)
        ];
        let child;
        try {
          child = this.#spawn(config.python, args, {
            cwd: config.projectRoot,
            windowsHide: true,
            stdio: ["ignore", "pipe", "pipe"]
          });
          assertChildProcess(child);
        } catch (error) {
          this.#state = "stopped";
          this.#hostConfig = null;
          this.#recordError("SPAWN_FAILED", error);
          return Promise.reject(error);
        }
        this.#process = child;
        child.stdout.on("data", (chunk) => this.#appendLog("stdout", chunk));
        child.stderr.on("data", (chunk) => this.#appendLog("stderr", chunk));
        child.once("error", (error) => this.#handleProcessError(child, error));
        child.once("exit", (code, signal) => this.#handleProcessExit(child, code, signal));
        const startPromise = this.#waitForStartupMarker(child).then(() => {
          if (this.#process !== child || this.#state !== "starting") {
            throw new Error("LAN host stopped before becoming ready");
          }
          this.#state = "running";
          return this.getSnapshot();
        }).catch((error) => {
          if (this.#process === child) {
            this.#recordError("READINESS_FAILED", error);
            this.#clearBroadcast();
            this.#process = null;
            try {
              child.kill();
            } catch (killError) {
              this.#appendLog("system", `Failed to stop host: ${errorMessage(killError)}`);
            }
          }
          if (this.#state !== "stopping") this.#state = "stopped";
          this.#hostConfig = null;
          throw error;
        }).finally(() => {
          if (this.#startPromise === startPromise) this.#startPromise = null;
        });
        this.#startPromise = startPromise;
        return startPromise;
      }
      stopHost() {
        if (this.#stopPromise) return this.#stopPromise;
        this.#clearBroadcast();
        this.#closeDiscoveries();
        this.#roomPacket = null;
        const child = this.#process;
        this.#process = null;
        this.#hostConfig = null;
        this.#state = "stopping";
        if (!child) {
          this.#state = "stopped";
          return Promise.resolve(this.getSnapshot());
        }
        const stopPromise = new Promise((resolve) => {
          let finished = false;
          let timeout = null;
          const finish = () => {
            if (finished) return;
            finished = true;
            if (timeout !== null) this.#timers.clearTimeout(timeout);
            child.removeListener("exit", finish);
            child.removeListener("close", finish);
            this.#state = "stopped";
            resolve(this.getSnapshot());
          };
          child.once("exit", finish);
          child.once("close", finish);
          timeout = this.#timers.setTimeout(finish, this.#stopTimeoutMs);
          try {
            child.kill();
          } catch (error) {
            this.#appendLog("system", `Failed to stop host: ${errorMessage(error)}`);
            finish();
          }
        }).finally(() => {
          if (this.#stopPromise === stopPromise) this.#stopPromise = null;
        });
        this.#stopPromise = stopPromise;
        return stopPromise;
      }
      updateRoom(room) {
        if (this.#state !== "running" || !this.#hostConfig || !this.#process) {
          throw new Error("LAN host must be running before advertising a room");
        }
        const packet = makeRoomPacket(room, this.#hostConfig, this.#localAddresses());
        const encoded = Buffer.from(JSON.stringify(packet), "utf8");
        if (encoded.length > this.#maxPacketBytes) throw new RangeError("discovery packet is too large");
        this.#roomPacket = packet;
        if (!this.#broadcastSocket) {
          this.#startBroadcastSocket();
        } else {
          this.#sendBroadcast();
        }
        return this.getSnapshot();
      }
      clearRoom() {
        this.#roomPacket = null;
        this.#clearBroadcast();
        return this.getSnapshot();
      }
      discover({ timeoutMs = 1500 } = {}) {
        const duration = requirePositiveInteger(timeoutMs, "timeoutMs");
        const socket = this.#dgram.createSocket("udp4");
        assertDatagramSocket(socket);
        const rooms = /* @__PURE__ */ new Map();
        return new Promise((resolve, reject) => {
          const discovery = {
            socket,
            timeout: null,
            done: false,
            finish: (error) => {
              if (discovery.done) return;
              discovery.done = true;
              if (discovery.timeout !== null) this.#timers.clearTimeout(discovery.timeout);
              this.#discoveries.delete(discovery);
              closeSocket(socket);
              if (error) {
                reject(error);
                return;
              }
              resolve([...rooms.values()].sort(compareDiscoveredRooms));
            }
          };
          this.#discoveries.add(discovery);
          socket.on("message", (message, rinfo) => {
            const room = parseDiscoveryPacket(message, rinfo, this.#net, this.#maxPacketBytes);
            if (!room) return;
            rooms.set(`${room.serverName}:${room.port}:${room.roomCode}`, room);
          });
          socket.once("error", (error) => discovery.finish(error));
          discovery.timeout = this.#timers.setTimeout(() => discovery.finish(), duration);
          try {
            socket.bind({ port: this.#discoveryPort, address: "0.0.0.0", exclusive: false });
          } catch (error) {
            discovery.finish(error);
          }
        });
      }
      getManualEndpoints() {
        const port = this.#hostConfig?.port ?? DEFAULT_HOST_PORT;
        const addresses = this.#localAddresses();
        return {
          localUrl: `ws://127.0.0.1:${port}`,
          addresses,
          urls: addresses.map((address) => `ws://${address}:${port}`)
        };
      }
      getSnapshot() {
        return {
          state: this.#state,
          pid: Number.isInteger(this.#process?.pid) ? this.#process.pid : null,
          port: this.#hostConfig?.port ?? null,
          serverName: this.#hostConfig?.serverName ?? null,
          room: this.#roomPacket ? cloneJson(this.#roomPacket) : null,
          manualEndpoints: this.getManualEndpoints(),
          log: this.#logs.map((entry) => ({ ...entry })),
          lastError: this.#lastError ? { ...this.#lastError } : null,
          broadcasting: this.#broadcastSocket !== null,
          discovering: this.#discoveries.size
        };
      }
      #startBroadcastSocket() {
        const socket = this.#dgram.createSocket("udp4");
        assertDatagramSocket(socket);
        this.#broadcastSocket = socket;
        socket.once("error", (error) => {
          if (this.#broadcastSocket !== socket) return;
          this.#recordError("BROADCAST_ERROR", error);
          this.#clearBroadcast();
        });
        socket.bind(0, () => {
          if (this.#broadcastSocket !== socket) return;
          socket.setBroadcast(true);
          this.#sendBroadcast();
        });
        this.#broadcastInterval = this.#timers.setInterval(
          () => this.#sendBroadcast(),
          this.#broadcastIntervalMs
        );
      }
      #sendBroadcast() {
        if (!this.#broadcastSocket || !this.#roomPacket) return;
        const encoded = Buffer.from(JSON.stringify(this.#roomPacket), "utf8");
        this.#broadcastSocket.send(
          encoded,
          this.#discoveryPort,
          BROADCAST_ADDRESS,
          (error) => {
            if (error) this.#recordError("BROADCAST_SEND_FAILED", error);
          }
        );
      }
      #clearBroadcast() {
        if (this.#broadcastInterval !== null) {
          this.#timers.clearInterval(this.#broadcastInterval);
          this.#broadcastInterval = null;
        }
        if (this.#broadcastSocket) {
          closeSocket(this.#broadcastSocket);
          this.#broadcastSocket = null;
        }
      }
      #closeDiscoveries() {
        for (const discovery of [...this.#discoveries]) discovery.finish();
      }
      #waitForStartupMarker(child) {
        return new Promise((resolve, reject) => {
          let done = false;
          const finish = (error) => {
            if (done) return;
            done = true;
            this.#timers.clearTimeout(timeout);
            child.stdout.removeListener("data", onData);
            child.removeListener("error", onError);
            child.removeListener("exit", onExit);
            error ? reject(error) : resolve();
          };
          const onData = (chunk) => {
            if (String(chunk ?? "").includes(STARTUP_MARKER)) finish();
          };
          const onError = (error) => finish(error);
          const onExit = (code, signal) => finish(new Error(
            `LAN host exited before readiness marker (${code ?? signal ?? "unknown"})`
          ));
          const timeout = this.#timers.setTimeout(
            () => finish(new Error("Timed out waiting for LAN host readiness marker")),
            this.#readinessTimeoutMs
          );
          child.stdout.on("data", onData);
          child.once("error", onError);
          child.once("exit", onExit);
        });
      }
      #handleProcessError(child, error) {
        if (this.#process !== child) return;
        this.#recordError("PROCESS_ERROR", error);
        this.#process = null;
        this.#hostConfig = null;
        this.#state = "stopped";
        this.#clearBroadcast();
      }
      #handleProcessExit(child, code, signal) {
        if (this.#process !== child) return;
        const error = new Error(`LAN host exited before shutdown (${code ?? signal ?? "unknown"})`);
        this.#recordError("PROCESS_EXITED", error);
        this.#process = null;
        this.#hostConfig = null;
        this.#state = "stopped";
        this.#clearBroadcast();
      }
      #appendLog(stream, chunk) {
        const text = String(chunk ?? "").trim();
        if (!text) return;
        this.#logs.push({
          at: this.#now(),
          stream,
          text: text.slice(0, this.#maxLogChars)
        });
        if (this.#logs.length > this.#maxLogEntries) {
          this.#logs.splice(0, this.#logs.length - this.#maxLogEntries);
        }
      }
      #recordError(code, error) {
        this.#lastError = { code, message: errorMessage(error), at: this.#now() };
        this.#appendLog("system", `${code}: ${this.#lastError.message}`);
      }
      #localAddresses() {
        const addresses = /* @__PURE__ */ new Set();
        const interfaces = this.#os.networkInterfaces() || {};
        for (const records of Object.values(interfaces)) {
          if (!Array.isArray(records)) continue;
          for (const record of records) {
            if (!record || record.internal === true) continue;
            const family = record.family;
            if (family !== "IPv4" && family !== 4) continue;
            if (typeof record.address !== "string" || this.#net.isIP(record.address) !== 4) continue;
            if (record.address.startsWith("127.")) continue;
            addresses.add(record.address);
          }
        }
        return [...addresses].sort();
      }
      #now() {
        const value = Number(this.#clock());
        return Number.isFinite(value) ? value : Date.now();
      }
    };
    function makeRoomPacket(room, hostConfig, localAddresses) {
      if (!isPlainObject(room)) throw new TypeError("room must be an object");
      const capacity = requirePositiveInteger(room.capacity, "room.capacity");
      const players = requireNonNegativeInteger(room.players, "room.players");
      if (players > capacity) throw new RangeError("room.players must not exceed room.capacity");
      return {
        service: SERVICE,
        protocolVersion: PROTOCOL_VERSION,
        serverName: hostConfig.serverName,
        host: localAddresses[0] || "",
        port: hostConfig.port,
        roomCode: requireRoomCode(room.roomCode),
        players,
        capacity
      };
    }
    function parseDiscoveryPacket(message, rinfo, net2, maxPacketBytes) {
      if (!Buffer.isBuffer(message) || message.length === 0 || message.length > maxPacketBytes) return null;
      if (!rinfo || typeof rinfo.address !== "string" || net2.isIP(rinfo.address) !== 4) return null;
      let value;
      try {
        value = JSON.parse(message.toString("utf8"));
      } catch (_) {
        return null;
      }
      if (!isPlainObject(value)) return null;
      const keys = Object.keys(value).sort();
      if (keys.length !== DISCOVERY_KEYS.length || keys.some((key, index) => key !== DISCOVERY_KEYS[index])) return null;
      if (value.service !== SERVICE || value.protocolVersion !== PROTOCOL_VERSION) return null;
      if (typeof value.serverName !== "string" || !value.serverName.trim() || value.serverName.length > 80) return null;
      if (typeof value.host !== "string" || value.host.length > 45) return null;
      if (!Number.isInteger(value.port) || value.port < 1 || value.port > 65535) return null;
      if (typeof value.roomCode !== "string" || !/^[A-Z0-9]{6}$/.test(value.roomCode)) return null;
      if (!Number.isInteger(value.capacity) || value.capacity < 1 || value.capacity > 16) return null;
      if (!Number.isInteger(value.players) || value.players < 0 || value.players > value.capacity) return null;
      return {
        service: SERVICE,
        protocolVersion: PROTOCOL_VERSION,
        serverName: value.serverName,
        host: rinfo.address,
        port: value.port,
        roomCode: value.roomCode,
        players: value.players,
        capacity: value.capacity
      };
    }
    function normalizeServerName(value, os) {
      if (value === void 0 || value === null || value === "") {
        const fallback = typeof os.hostname === "function" ? os.hostname() : "";
        return requireServerName(fallback || "ZZ LAN Server");
      }
      return requireServerName(value);
    }
    function requireServerName(value) {
      const normalized = requireNonBlankString(value, "serverName").trim();
      if (normalized.length > 80) throw new RangeError("serverName must be at most 80 characters");
      return normalized;
    }
    function requireRoomCode(value) {
      if (typeof value !== "string" || !/^[A-Z0-9]{6}$/.test(value)) {
        throw new TypeError("room.roomCode must contain exactly six uppercase letters or digits");
      }
      return value;
    }
    function requireAbsolutePath(value, label) {
      const normalized = requireNonBlankString(value, label);
      if (!path2.isAbsolute(normalized)) throw new TypeError(`${label} must be an absolute path`);
      return path2.resolve(normalized);
    }
    function requireNonBlankString(value, label) {
      if (typeof value !== "string" || !value.trim()) throw new TypeError(`${label} must be a non-empty string`);
      return value;
    }
    function requirePort(value, label) {
      if (!Number.isInteger(value) || value < 1 || value > 65535) {
        throw new RangeError(`${label} must be an integer from 1 to 65535`);
      }
      return value;
    }
    function requirePositiveInteger(value, label) {
      if (!Number.isInteger(value) || value <= 0) throw new RangeError(`${label} must be a positive integer`);
      return value;
    }
    function requireNonNegativeInteger(value, label) {
      if (!Number.isInteger(value) || value < 0) throw new RangeError(`${label} must be a non-negative integer`);
      return value;
    }
    function sameHostConfig(left, right) {
      return Boolean(right) && left.projectRoot === right.projectRoot && left.python === right.python && left.port === right.port && left.serverName === right.serverName;
    }
    function assertChildProcess(child) {
      if (!child || typeof child.once !== "function" || typeof child.removeListener !== "function" || typeof child.kill !== "function" || !child.stdout || typeof child.stdout.on !== "function" || !child.stderr || typeof child.stderr.on !== "function") {
        throw new TypeError("spawn must return a child process with piped stdout and stderr");
      }
    }
    function assertDatagramSocket(socket) {
      if (!socket || typeof socket.on !== "function" || typeof socket.once !== "function" || typeof socket.bind !== "function" || typeof socket.send !== "function" || typeof socket.close !== "function") {
        throw new TypeError("dgram.createSocket must return a UDP socket");
      }
    }
    function closeSocket(socket) {
      try {
        socket.close();
      } catch (error) {
        if (error?.code !== "ERR_SOCKET_DGRAM_NOT_RUNNING") throw error;
      }
    }
    function errorMessage(error) {
      return error instanceof Error ? error.message : String(error);
    }
    function isPlainObject(value) {
      if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
      const prototype = Object.getPrototypeOf(value);
      return prototype === Object.prototype || prototype === null;
    }
    function cloneJson(value) {
      return JSON.parse(JSON.stringify(value));
    }
    function compareDiscoveredRooms(left, right) {
      return left.serverName.localeCompare(right.serverName) || left.host.localeCompare(right.host) || left.port - right.port || left.roomCode.localeCompare(right.roomCode);
    }
    module2.exports = {
      DEFAULT_DISCOVERY_PORT,
      DEFAULT_HOST_PORT,
      LanManager: LanManager2,
      PROTOCOL_VERSION,
      SERVICE
    };
  }
});

// zz/multiplayer/compatibility.json
var require_compatibility = __commonJS({
  "zz/multiplayer/compatibility.json"(exports2, module2) {
    module2.exports = {
      applicationVersion: "0.2.0",
      protocolVersion: 1,
      rulesVersion: "0.0.2",
      cardDatabaseChecksum: "sha256:b54eb5257a2ae0d157fde2bacb502d40aa26323be34449fc00b8670cfe1837c8"
    };
  }
});

// electron/multiplayer-client.js
var require_multiplayer_client = __commonJS({
  "electron/multiplayer-client.js"(exports2, module2) {
    "use strict";
    var { randomUUID } = require("node:crypto");
    var compatibility = require_compatibility();
    var LOCAL_COMPATIBILITY = Object.freeze({ ...compatibility });
    var PROTOCOL_VERSION = LOCAL_COMPATIBILITY.protocolVersion;
    var MultiplayerClientState = Object.freeze({
      OFFLINE: "OFFLINE",
      CONNECTING: "CONNECTING",
      CONNECTED: "CONNECTED",
      IN_ROOM: "IN_ROOM",
      MATCH_STARTING: "MATCH_STARTING",
      IN_MATCH: "IN_MATCH",
      RECONNECTING: "RECONNECTING",
      MATCH_FINISHED: "MATCH_FINISHED",
      ERROR: "ERROR"
    });
    var ALLOWED_TRANSITIONS = Object.freeze({
      OFFLINE: /* @__PURE__ */ new Set(["CONNECTING", "RECONNECTING"]),
      CONNECTING: /* @__PURE__ */ new Set(["CONNECTED", "OFFLINE", "ERROR"]),
      CONNECTED: /* @__PURE__ */ new Set(["IN_ROOM", "MATCH_STARTING", "IN_MATCH", "RECONNECTING", "OFFLINE", "ERROR"]),
      IN_ROOM: /* @__PURE__ */ new Set(["CONNECTED", "MATCH_STARTING", "IN_MATCH", "RECONNECTING", "OFFLINE", "ERROR"]),
      MATCH_STARTING: /* @__PURE__ */ new Set(["CONNECTED", "IN_MATCH", "MATCH_FINISHED", "RECONNECTING", "OFFLINE", "ERROR"]),
      IN_MATCH: /* @__PURE__ */ new Set(["CONNECTED", "MATCH_FINISHED", "RECONNECTING", "OFFLINE", "ERROR"]),
      RECONNECTING: /* @__PURE__ */ new Set(["CONNECTED", "IN_ROOM", "MATCH_STARTING", "IN_MATCH", "MATCH_FINISHED", "OFFLINE", "ERROR"]),
      MATCH_FINISHED: /* @__PURE__ */ new Set(["CONNECTED", "RECONNECTING", "OFFLINE", "ERROR"]),
      ERROR: /* @__PURE__ */ new Set(["OFFLINE", "RECONNECTING"])
    });
    var ROOM_COMMAND_STATES = /* @__PURE__ */ new Set([
      MultiplayerClientState.IN_ROOM,
      MultiplayerClientState.MATCH_STARTING,
      MultiplayerClientState.IN_MATCH,
      MultiplayerClientState.MATCH_FINISHED
    ]);
    var SERVER_MESSAGE_TYPES = /* @__PURE__ */ new Set([
      "WELCOME",
      "ROOM_STATE",
      "MATCH_STARTED",
      "STATE_SNAPSHOT",
      "ACTION_RESULT",
      "ERROR",
      "ROOM_CLOSED"
    ]);
    var MultiplayerDesktopClient2 = class {
      #WebSocketImpl;
      #uuidFactory;
      #socket = null;
      #socketListeners = null;
      #helloSent = false;
      #listeners = /* @__PURE__ */ new Set();
      #room = null;
      #view = null;
      #error = null;
      #pendingAction = null;
      #recovery = null;
      #pendingActionNeedsReplay = false;
      constructor({ WebSocketImpl = globalThis.WebSocket, uuidFactory = randomUUID } = {}) {
        if (typeof WebSocketImpl !== "function") {
          throw new TypeError("WebSocketImpl must be a constructor");
        }
        if (typeof uuidFactory !== "function") {
          throw new TypeError("uuidFactory must be a function");
        }
        this.#WebSocketImpl = WebSocketImpl;
        this.#uuidFactory = uuidFactory;
        this.state = MultiplayerClientState.OFFLINE;
        this.url = null;
        this.connectionId = null;
        this.playerId = null;
        this.matchId = null;
      }
      get room() {
        return cloneJson(this.#room);
      }
      get view() {
        return cloneJson(this.#view);
      }
      get error() {
        return cloneJson(this.#error);
      }
      get pendingAction() {
        return cloneJson(this.#pendingAction);
      }
      get canSubmitAction() {
        return this.state === MultiplayerClientState.IN_MATCH && this.#pendingAction === null && this.#view !== null && Number.isInteger(this.#view.revision) && this.#view.revision >= 0;
      }
      getSnapshot() {
        return {
          state: this.state,
          url: this.url,
          connectionId: this.connectionId,
          playerId: this.playerId,
          matchId: this.matchId,
          room: cloneJson(this.#room),
          view: cloneJson(this.#view),
          error: cloneJson(this.#error),
          pendingAction: cloneJson(this.#pendingAction),
          canSubmitAction: this.canSubmitAction,
          canReconnect: this.#recovery !== null,
          reconnectAttemptActive: this.state === MultiplayerClientState.RECONNECTING && this.#socket !== null
        };
      }
      getRecoverySession() {
        return cloneJson(this.#recovery);
      }
      restoreRecoverySession(session2) {
        if (this.state !== MultiplayerClientState.OFFLINE || this.#socket !== null) {
          throw new Error("recovery session can only be restored while offline");
        }
        const recovery = validateRecoverySession(session2);
        this.#recovery = recovery;
        this.url = recovery.url;
        this.playerId = recovery.playerId;
        this.matchId = recovery.matchId;
        this.#pendingAction = cloneJson(recovery.pendingAction);
        return this.getSnapshot();
      }
      onEvent(listener) {
        if (typeof listener !== "function") {
          throw new TypeError("listener must be a function");
        }
        this.#listeners.add(listener);
        return () => {
          this.#listeners.delete(listener);
        };
      }
      connect({ url } = {}) {
        if (this.state !== MultiplayerClientState.OFFLINE || this.#socket !== null) {
          throw new Error(`client cannot connect from ${this.state}`);
        }
        const normalizedUrl = validateWebSocketUrl(url);
        this.#clearRecovery();
        this.url = normalizedUrl;
        this.#error = null;
        this.#helloSent = false;
        this.#setState(MultiplayerClientState.CONNECTING);
        let socket;
        try {
          socket = new this.#WebSocketImpl(normalizedUrl);
          this.#assertSocket(socket);
          this.#socket = socket;
          this.#attachSocketListeners(socket);
        } catch (error) {
          this.#socket = null;
          this.#socketListeners = null;
          this.#recordError("CONNECT_FAILED", error);
          this.#setState(MultiplayerClientState.ERROR);
          throw error;
        }
        return this.getSnapshot();
      }
      reconnect() {
        if (this.#recovery === null) throw new Error("no reconnect session is available");
        if (this.#socket !== null) throw new Error("reconnect socket is already active");
        if (![MultiplayerClientState.OFFLINE, MultiplayerClientState.RECONNECTING, MultiplayerClientState.ERROR].includes(this.state)) {
          throw new Error(`client cannot reconnect from ${this.state}`);
        }
        this.url = this.#recovery.url;
        this.#error = null;
        this.#helloSent = false;
        this.#pendingActionNeedsReplay = this.#pendingAction !== null;
        this.#setState(MultiplayerClientState.RECONNECTING);
        let socket;
        try {
          socket = new this.#WebSocketImpl(this.url);
          this.#assertSocket(socket);
          this.#socket = socket;
          this.#attachSocketListeners(socket);
        } catch (error) {
          this.#socket = null;
          this.#socketListeners = null;
          this.#recordError("RECONNECT_FAILED", error);
          this.#emitEvent("RECONNECT_FAILED");
          throw error;
        }
        return this.getSnapshot();
      }
      disconnect({ preserveRecovery = false } = {}) {
        if (this.state === MultiplayerClientState.OFFLINE && this.#socket === null) {
          return this.getSnapshot();
        }
        const socket = this.#socket;
        this.#detachSocketListeners(socket);
        this.#socket = null;
        this.#helloSent = false;
        if (socket !== null) {
          socket.close();
        }
        this.url = preserveRecovery && this.#recovery ? this.#recovery.url : null;
        this.connectionId = null;
        this.playerId = preserveRecovery && this.#recovery ? this.#recovery.playerId : null;
        this.matchId = preserveRecovery && this.#recovery ? this.#recovery.matchId : null;
        this.#room = null;
        this.#view = null;
        this.#error = null;
        this.#pendingAction = preserveRecovery && this.#recovery ? cloneJson(this.#recovery.pendingAction) : null;
        this.#pendingActionNeedsReplay = false;
        if (!preserveRecovery) this.#clearRecovery();
        this.#setState(MultiplayerClientState.OFFLINE);
        return this.getSnapshot();
      }
      suspend() {
        return this.disconnect({ preserveRecovery: true });
      }
      createRoom({ displayName } = {}) {
        this.#requireState("CREATE_ROOM", /* @__PURE__ */ new Set([MultiplayerClientState.CONNECTED]));
        const payload = {};
        if (displayName !== void 0) payload.displayName = requireNonBlankString(displayName, "displayName");
        this.#sendCommand("CREATE_ROOM", payload);
      }
      joinRoom({ roomCode, displayName } = {}) {
        this.#requireState("JOIN_ROOM", /* @__PURE__ */ new Set([MultiplayerClientState.CONNECTED]));
        if (typeof roomCode !== "string" || !/^[A-Z0-9]{6}$/.test(roomCode)) {
          throw new TypeError("roomCode must contain exactly six uppercase letters or digits");
        }
        const payload = { roomCode };
        if (displayName !== void 0) payload.displayName = requireNonBlankString(displayName, "displayName");
        this.#sendCommand("JOIN_ROOM", payload);
      }
      selectDeck({ deck, forces, profile } = {}) {
        this.#requireState("SELECT_DECK", /* @__PURE__ */ new Set([MultiplayerClientState.IN_ROOM]));
        if (!isPlainObject(deck) || Object.keys(deck).length === 0) {
          throw new TypeError("deck must be a non-empty object");
        }
        for (const [cardId, count] of Object.entries(deck)) {
          if (!cardId || !Number.isInteger(count) || count < 1 || count > 99) {
            throw new TypeError("deck entries must have a card id and an integer count from 1 to 99");
          }
        }
        if (!Array.isArray(forces) || forces.length !== 2 || forces.some((id) => typeof id !== "string" || !id)) {
          throw new TypeError("forces must contain exactly two non-empty ids");
        }
        this.#sendCommand("SELECT_DECK", {
          deck: cloneJson(deck),
          forces: [...forces],
          ...profile ? { profile: cloneJson(profile) } : {}
        });
      }
      setReady({ ready } = {}) {
        this.#requireState("SET_READY", /* @__PURE__ */ new Set([MultiplayerClientState.IN_ROOM]));
        if (typeof ready !== "boolean") throw new TypeError("ready must be a boolean");
        this.#sendCommand("SET_READY", { ready });
      }
      submitAction({ action, clientActionId } = {}) {
        if (!isPlainObject(action)) throw new TypeError("action must be an object");
        if (!this.canSubmitAction) {
          if (this.#pendingAction !== null) throw new Error("an action is awaiting acknowledgement");
          throw new Error("client is not ready to submit an action");
        }
        if (!this.matchId || !this.playerId) {
          throw new Error("match and player identity are required");
        }
        const actionId = clientActionId === void 0 ? this.#newId("clientActionId") : requireNonBlankString(clientActionId, "clientActionId");
        const submission = {
          matchId: this.matchId,
          playerId: this.playerId,
          clientActionId: actionId,
          expectedRevision: this.#view.revision,
          action: cloneJson(action)
        };
        this.#pendingAction = cloneJson(submission);
        this.#syncRecoverySession();
        try {
          this.#sendCommand("SUBMIT_ACTION", submission);
        } catch (error) {
          this.#pendingAction = null;
          this.#syncRecoverySession();
          throw error;
        }
        return actionId;
      }
      surrender({ clientActionId } = {}) {
        return this.submitAction({ action: { kind: "SURRENDER" }, clientActionId });
      }
      requestSync() {
        this.#requireState("REQUEST_SYNC", ROOM_COMMAND_STATES);
        const payload = this.matchId ? { matchId: this.matchId } : {};
        this.#sendCommand("REQUEST_SYNC", payload);
      }
      leaveRoom() {
        this.#requireState("LEAVE_ROOM", ROOM_COMMAND_STATES);
        this.#sendCommand("LEAVE_ROOM", {});
      }
      #assertSocket(socket) {
        if (socket === null || typeof socket !== "object" || typeof socket.addEventListener !== "function" || typeof socket.removeEventListener !== "function" || typeof socket.send !== "function" || typeof socket.close !== "function") {
          throw new TypeError("WebSocketImpl must provide the standard WebSocket event API");
        }
      }
      #attachSocketListeners(socket) {
        const listeners = {
          open: () => this.#handleOpen(socket),
          message: (event) => this.#handleMessage(socket, event),
          error: (event) => this.#handleSocketError(socket, event),
          close: (event) => this.#handleUnexpectedClose(socket, event)
        };
        this.#socketListeners = listeners;
        for (const [type, listener] of Object.entries(listeners)) {
          socket.addEventListener(type, listener);
        }
      }
      #detachSocketListeners(socket) {
        if (socket === null || this.#socketListeners === null) return;
        for (const [type, listener] of Object.entries(this.#socketListeners)) {
          socket.removeEventListener(type, listener);
        }
        this.#socketListeners = null;
      }
      #handleOpen(socket) {
        if (socket !== this.#socket || ![MultiplayerClientState.CONNECTING, MultiplayerClientState.RECONNECTING].includes(this.state)) return;
        try {
          if (!this.#helloSent) {
            this.#helloSent = true;
            this.#sendEnvelope("HELLO", helloCompatibilityPayload());
          }
          if (this.state === MultiplayerClientState.CONNECTING) {
            this.#setState(MultiplayerClientState.CONNECTED);
          }
        } catch (error) {
          this.#failConnection(socket, "HELLO_FAILED", error);
        }
      }
      #handleMessage(socket, event) {
        if (socket !== this.#socket) return;
        try {
          const raw = event && typeof event === "object" && "data" in event ? event.data : event;
          const text = Buffer.isBuffer(raw) ? raw.toString("utf8") : raw;
          if (typeof text !== "string") throw new TypeError("server message must be UTF-8 text");
          const message = JSON.parse(text);
          this.#applyServerMessage(message);
          const publicMessage = cloneJson(message);
          if (publicMessage.type === "ROOM_STATE" && isPlainObject(publicMessage.payload)) {
            delete publicMessage.payload.reconnectToken;
          }
          this.#emitEvent(message.type, { message: publicMessage });
        } catch (error) {
          this.#failConnection(socket, error?.code || "INVALID_SERVER_MESSAGE", error);
        }
      }
      #handleSocketError(socket, event) {
        if (socket !== this.#socket) return;
        const error = event instanceof Error ? event : event && event.error instanceof Error ? event.error : new Error("WebSocket error");
        this.#failConnection(socket, "SOCKET_ERROR", error);
      }
      #handleUnexpectedClose(socket, event) {
        if (socket !== this.#socket) return;
        const code = event && Number.isInteger(event.code) ? event.code : null;
        const reason = event && typeof event.reason === "string" ? event.reason : "";
        this.#detachSocketListeners(socket);
        this.#socket = null;
        this.#helloSent = false;
        const error = new Error(reason || "WebSocket closed unexpectedly");
        if (this.#recovery !== null) {
          this.#recordError("RECONNECT_REQUIRED", error, { closeCode: code });
          if (this.state !== MultiplayerClientState.RECONNECTING) {
            this.#setState(MultiplayerClientState.RECONNECTING);
          } else {
            this.#emitEvent("RECONNECT_FAILED");
          }
          return;
        }
        this.#recordError("UNEXPECTED_CLOSE", error, { closeCode: code });
        this.#setState(MultiplayerClientState.ERROR);
      }
      #failConnection(socket, code, error) {
        this.#detachSocketListeners(socket);
        if (this.#socket === socket) this.#socket = null;
        this.#helloSent = false;
        try {
          socket.close();
        } finally {
          if (this.#recovery !== null && this.state === MultiplayerClientState.RECONNECTING) {
            this.#recordError("RECONNECT_FAILED", error, { causeCode: code });
            this.#emitEvent("RECONNECT_FAILED");
          } else {
            this.#recordError(code, error);
            this.#setState(MultiplayerClientState.ERROR);
          }
        }
      }
      #applyServerMessage(message) {
        if (!isPlainObject(message)) throw new TypeError("server message must be an object");
        if (message.protocolVersion !== PROTOCOL_VERSION) throw new Error("unsupported protocol version");
        requireNonBlankString(message.messageId, "messageId");
        if (!SERVER_MESSAGE_TYPES.has(message.type)) throw new Error(`unsupported server message type ${String(message.type)}`);
        if (!isPlainObject(message.payload)) throw new TypeError("server message payload must be an object");
        const payload = cloneJson(message.payload);
        switch (message.type) {
          case "WELCOME":
            requireCompatibleServer(payload.compatibility);
            this.connectionId = optionalString(payload.connectionId);
            this.playerId = optionalString(payload.playerId) || this.playerId;
            if (this.state === MultiplayerClientState.RECONNECTING && this.#recovery !== null) {
              this.#sendCommand("RECONNECT", {
                roomCode: this.#recovery.roomCode,
                playerId: this.#recovery.playerId,
                reconnectToken: this.#recovery.reconnectToken
              });
            }
            break;
          case "ROOM_STATE":
            {
              const reconnectToken = optionalString(payload.reconnectToken);
              delete payload.reconnectToken;
              this.#room = payload;
              this.playerId = optionalString(payload.playerId) || this.playerId;
              this.matchId = optionalString(payload.matchId) || this.matchId;
              if (reconnectToken) this.#setRecoveryToken(reconnectToken);
              this.#applyRoomStatus(payload.status);
            }
            break;
          case "MATCH_STARTED":
            this.matchId = optionalString(payload.matchId) || optionalString(message.matchId);
            this.playerId = optionalString(payload.playerId) || this.playerId;
            this.#view = requirePlainObjectClone(payload.view, "MATCH_STARTED view");
            this.#pendingAction = null;
            this.#pendingActionNeedsReplay = false;
            this.#syncRecoverySession();
            this.#setState(MultiplayerClientState.IN_MATCH);
            break;
          case "STATE_SNAPSHOT":
            this.matchId = optionalString(payload.matchId) || optionalString(message.matchId) || this.matchId;
            this.playerId = optionalString(payload.playerId) || this.playerId;
            this.#view = requirePlainObjectClone(payload.view, "STATE_SNAPSHOT view");
            this.#setState(this.#view.gameOver ? MultiplayerClientState.MATCH_FINISHED : MultiplayerClientState.IN_MATCH);
            this.#syncRecoverySession();
            if (this.#pendingActionNeedsReplay && this.#pendingAction !== null && !this.#view.gameOver) {
              this.#pendingActionNeedsReplay = false;
              this.#sendCommand("SUBMIT_ACTION", this.#pendingAction);
            }
            break;
          case "ACTION_RESULT":
            this.#applyActionResult(payload);
            break;
          case "ERROR":
            this.#error = payload;
            if (optionalString(payload.clientActionId) === this.#pendingAction?.clientActionId) {
              this.#pendingAction = null;
              this.#syncRecoverySession();
            }
            if (this.state === MultiplayerClientState.RECONNECTING) {
              const retryable = ["DUPLICATE_CONNECTION", "SEAT_ALREADY_CONNECTED"].includes(payload.code);
              const socket = this.#socket;
              this.#detachSocketListeners(socket);
              this.#socket = null;
              this.#helloSent = false;
              if (socket !== null) socket.close();
              if (retryable) {
                this.#recordError(payload.code, new Error(payload.message || payload.code));
                this.#emitEvent("RECONNECT_FAILED");
              } else {
                this.#clearRecovery();
                this.#setState(MultiplayerClientState.ERROR);
              }
              break;
            }
            if (payload.fatal === true) {
              const socket = this.#socket;
              this.#detachSocketListeners(socket);
              this.#socket = null;
              this.#helloSent = false;
              if (socket !== null) socket.close();
              this.#setState(MultiplayerClientState.ERROR);
            }
            break;
          case "ROOM_CLOSED":
            this.#clearRoomSession();
            this.#setState(MultiplayerClientState.CONNECTED);
            break;
          default:
            throw new Error(`unsupported server message type ${message.type}`);
        }
      }
      #applyRoomStatus(status) {
        if (status === "STARTING" || status === "RUNNING") {
          if (this.state !== MultiplayerClientState.IN_MATCH) this.#setState(MultiplayerClientState.MATCH_STARTING);
          return;
        }
        if (status === "FINISHED") {
          this.#setState(MultiplayerClientState.MATCH_FINISHED);
          return;
        }
        if (status === "CLOSED") {
          this.#clearRoomSession();
          this.#setState(MultiplayerClientState.CONNECTED);
          return;
        }
        this.#setState(MultiplayerClientState.IN_ROOM);
      }
      #applyActionResult(payload) {
        const actionId = optionalString(payload.clientActionId);
        if (actionId && actionId === this.#pendingAction?.clientActionId) this.#pendingAction = null;
        this.#view = requirePlainObjectClone(payload.view, "ACTION_RESULT view");
        this.#syncRecoverySession();
        if (payload.matchFinished === true || this.#view.gameOver === true) {
          this.#setState(MultiplayerClientState.MATCH_FINISHED);
        } else {
          this.#setState(MultiplayerClientState.IN_MATCH);
        }
      }
      #clearRoomSession() {
        this.#room = null;
        this.#view = null;
        this.#pendingAction = null;
        this.#pendingActionNeedsReplay = false;
        this.matchId = null;
        this.playerId = null;
        this.#clearRecovery();
      }
      #setRecoveryToken(reconnectToken) {
        if (!this.#room || !this.url || !this.playerId) {
          throw new Error("reconnect token arrived before room identity");
        }
        this.#recovery = {
          url: this.url,
          roomCode: requireRoomCode(this.#room.roomCode),
          playerId: this.playerId,
          matchId: this.matchId,
          reconnectToken: requireNonBlankString(reconnectToken, "reconnectToken"),
          pendingAction: cloneJson(this.#pendingAction)
        };
      }
      #syncRecoverySession() {
        if (this.#recovery === null) return;
        this.#recovery = {
          ...this.#recovery,
          url: this.url || this.#recovery.url,
          playerId: this.playerId || this.#recovery.playerId,
          matchId: this.matchId,
          pendingAction: cloneJson(this.#pendingAction)
        };
      }
      #clearRecovery() {
        this.#recovery = null;
        this.#pendingActionNeedsReplay = false;
      }
      #requireState(command, allowedStates) {
        if (!allowedStates.has(this.state)) throw new Error(`${command} is not allowed from ${this.state}`);
      }
      #sendCommand(type, payload) {
        this.#sendEnvelope(type, payload);
      }
      #sendEnvelope(type, payload) {
        const socket = this.#socket;
        if (socket === null) throw new Error("WebSocket is not connected");
        const envelope = {
          protocolVersion: PROTOCOL_VERSION,
          messageId: this.#newId("messageId"),
          type,
          payload: cloneJson(payload)
        };
        socket.send(JSON.stringify(envelope));
      }
      #newId(label) {
        return requireNonBlankString(this.#uuidFactory(), label);
      }
      #setState(nextState) {
        if (nextState === this.state) return;
        const allowed = ALLOWED_TRANSITIONS[this.state];
        if (!allowed || !allowed.has(nextState)) {
          throw new Error(`invalid multiplayer client transition ${this.state} -> ${nextState}`);
        }
        this.state = nextState;
        this.#emitEvent("STATE_CHANGED");
      }
      #recordError(code, error, extra = {}) {
        this.#error = {
          code,
          message: error instanceof Error ? error.message : String(error),
          ...extra
        };
      }
      #emitEvent(type, detail = {}) {
        const event = { type, ...cloneJson(detail), snapshot: this.getSnapshot() };
        for (const listener of [...this.#listeners]) listener(cloneJson(event));
      }
    };
    function validateWebSocketUrl(value) {
      if (typeof value !== "string" || !value) throw new TypeError("url must be a non-empty string");
      let parsed;
      try {
        parsed = new URL(value);
      } catch (error) {
        throw new TypeError("url must be a valid ws:// or wss:// URL", { cause: error });
      }
      if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") {
        throw new TypeError("url must use ws:// or wss://");
      }
      return parsed.toString();
    }
    function helloCompatibilityPayload() {
      return {
        applicationVersion: LOCAL_COMPATIBILITY.applicationVersion,
        rulesVersion: LOCAL_COMPATIBILITY.rulesVersion,
        cardDatabaseChecksum: LOCAL_COMPATIBILITY.cardDatabaseChecksum
      };
    }
    function requireCompatibleServer(value) {
      const expectedKeys = Object.keys(LOCAL_COMPATIBILITY).sort();
      if (!isPlainObject(value) || JSON.stringify(Object.keys(value).sort()) !== JSON.stringify(expectedKeys) || expectedKeys.some((key) => value[key] !== LOCAL_COMPATIBILITY[key])) {
        const error = new Error("Server game version is incompatible with this client.");
        error.code = "INCOMPATIBLE_GAME_VERSION";
        throw error;
      }
    }
    function validateRecoverySession(value) {
      if (!isPlainObject(value)) throw new TypeError("recovery session must be an object");
      const required = /* @__PURE__ */ new Set([
        "matchId",
        "pendingAction",
        "playerId",
        "reconnectToken",
        "roomCode",
        "url"
      ]);
      const keys = Object.keys(value);
      if (keys.length !== required.size || keys.some((key) => !required.has(key))) {
        throw new TypeError("recovery session has invalid fields");
      }
      const matchId = value.matchId === null ? null : requireNonBlankString(value.matchId, "matchId");
      const pendingAction = value.pendingAction === null ? null : requirePlainObjectClone(value.pendingAction, "pendingAction");
      return {
        url: validateWebSocketUrl(value.url),
        roomCode: requireRoomCode(value.roomCode),
        playerId: requireNonBlankString(value.playerId, "playerId"),
        matchId,
        reconnectToken: requireNonBlankString(value.reconnectToken, "reconnectToken"),
        pendingAction
      };
    }
    function cloneJson(value) {
      if (value === null || value === void 0) return value;
      return JSON.parse(JSON.stringify(value));
    }
    function isPlainObject(value) {
      if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
      const prototype = Object.getPrototypeOf(value);
      return prototype === Object.prototype || prototype === null;
    }
    function requirePlainObjectClone(value, label) {
      if (!isPlainObject(value)) throw new TypeError(`${label} must be an object`);
      return cloneJson(value);
    }
    function requireNonBlankString(value, label) {
      if (typeof value !== "string" || !value.trim()) throw new TypeError(`${label} must be a non-empty string`);
      return value;
    }
    function requireRoomCode(value) {
      if (typeof value !== "string" || !/^[A-Z0-9]{6}$/.test(value)) {
        throw new TypeError("roomCode must contain exactly six uppercase letters or digits");
      }
      return value;
    }
    function optionalString(value) {
      return typeof value === "string" && value ? value : null;
    }
    module2.exports = {
      LOCAL_COMPATIBILITY,
      MultiplayerClientState,
      MultiplayerDesktopClient: MultiplayerDesktopClient2,
      PROTOCOL_VERSION
    };
  }
});

// electron/update-checker.js
var require_update_checker = __commonJS({
  "electron/update-checker.js"(exports2, module2) {
    "use strict";
    var RELEASE_API_URL = "https://api.github.com/repos/TohmaN233/ZZ-Project/releases/latest";
    var LATEST_RELEASE_URL2 = "https://github.com/TohmaN233/ZZ-Project/releases/latest";
    var PROJECT_WEBSITE_URL2 = "https://tohman233.github.io/ZZ-Project/";
    function parseVersion(value) {
      const raw = String(value || "").trim();
      const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec(raw);
      if (!match) throw new Error(`invalid semantic version: ${raw || "<empty>"}`);
      return {
        raw,
        core: match.slice(1, 4).map(Number),
        prerelease: match[4] ? match[4].split(".") : []
      };
    }
    function comparePrerelease(left, right) {
      if (left.length === 0 || right.length === 0) {
        if (left.length === right.length) return 0;
        return left.length === 0 ? 1 : -1;
      }
      const length = Math.max(left.length, right.length);
      for (let index = 0; index < length; index += 1) {
        if (left[index] === void 0) return -1;
        if (right[index] === void 0) return 1;
        if (left[index] === right[index]) continue;
        const leftNumber = /^\d+$/.test(left[index]) ? Number(left[index]) : null;
        const rightNumber = /^\d+$/.test(right[index]) ? Number(right[index]) : null;
        if (leftNumber !== null && rightNumber !== null) return Math.sign(leftNumber - rightNumber);
        if (leftNumber !== null) return -1;
        if (rightNumber !== null) return 1;
        return left[index] < right[index] ? -1 : 1;
      }
      return 0;
    }
    function compareVersions(leftValue, rightValue) {
      const left = parseVersion(leftValue);
      const right = parseVersion(rightValue);
      for (let index = 0; index < left.core.length; index += 1) {
        if (left.core[index] !== right.core[index]) {
          return Math.sign(left.core[index] - right.core[index]);
        }
      }
      return comparePrerelease(left.prerelease, right.prerelease);
    }
    async function checkLatestRelease2({ currentVersion, fetchImpl }) {
      if (typeof fetchImpl !== "function") throw new TypeError("fetchImpl must be a function");
      const current = parseVersion(currentVersion).raw.replace(/^v/, "");
      const response = await fetchImpl(RELEASE_API_URL, {
        headers: {
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2026-03-10"
        }
      });
      if (!response || typeof response.ok !== "boolean") {
        throw new Error("GitHub update check returned an invalid response");
      }
      if (!response.ok) throw new Error(`GitHub update check failed: HTTP ${response.status}`);
      const release = await response.json();
      if (!release || typeof release.tag_name !== "string") {
        throw new Error("GitHub latest release is missing tag_name");
      }
      const latestVersion = parseVersion(release.tag_name).raw.replace(/^v/, "");
      return {
        status: compareVersions(current, latestVersion) < 0 ? "available" : "current",
        currentVersion: current,
        latestVersion,
        releaseUrl: LATEST_RELEASE_URL2,
        releaseName: typeof release.name === "string" ? release.name : null,
        publishedAt: typeof release.published_at === "string" ? release.published_at : null
      };
    }
    module2.exports = {
      LATEST_RELEASE_URL: LATEST_RELEASE_URL2,
      PROJECT_WEBSITE_URL: PROJECT_WEBSITE_URL2,
      RELEASE_API_URL,
      checkLatestRelease: checkLatestRelease2,
      compareVersions,
      parseVersion
    };
  }
});

// electron/main.js
var { app, BrowserWindow, dialog, ipcMain, Menu, net, session, shell } = require("electron");
var { spawn } = require("node:child_process");
var fs = require("node:fs/promises");
var http = require("node:http");
var path = require("node:path");
var { createAdaptiveWebSocketClass } = require_adaptive_websocket();
var { LanManager } = require_lan_manager();
var { MultiplayerDesktopClient } = require_multiplayer_client();
var {
  checkLatestRelease,
  LATEST_RELEASE_URL,
  PROJECT_WEBSITE_URL
} = require_update_checker();
var mainWindow = null;
var serverProcess = null;
var serverUrl = null;
var serverState = "stopped";
var trustedOrigin = null;
var serverLog = [];
var multiplayerRoute = "UNSELECTED";
var AdaptiveWebSocket = createAdaptiveWebSocketClass({
  resolveProxy: (url) => session.defaultSession.resolveProxy(url),
  onRouteSelected: (route) => {
    multiplayerRoute = route.kind.toUpperCase();
    appendLog(`Multiplayer route selected: ${multiplayerRoute}`);
  }
});
var multiplayerClient = new MultiplayerDesktopClient({ WebSocketImpl: AdaptiveWebSocket });
var lanManager = new LanManager();
var multiplayerRecoveryPath = null;
var multiplayerRecoveryWrite = Promise.resolve();
var multiplayerReconnectTimer = null;
var multiplayerReconnectDelayMs = 1e3;
var shutdownPrepared = false;
var shutdownPromise = null;
var updateCheckPromise = null;
var updateStatus = { status: "idle", currentVersion: null };
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
function projectRoot() {
  return path.resolve(__dirname, "..");
}
function applicationIconPath() {
  return path.join(app.getAppPath(), "electron", "icon.png");
}
function openHelpUrl(url, label) {
  shell.openExternal(url).catch((error) => {
    appendLog(`Opening ${label} failed: ${error.message || error}`);
  });
}
function installApplicationMenu() {
  const template = [];
  if (process.platform === "darwin") {
    template.push({
      label: app.name,
      submenu: [{ role: "about" }, { type: "separator" }, { role: "quit" }]
    });
  }
  template.push(
    { role: "fileMenu" },
    { role: "viewMenu" },
    { role: "windowMenu" },
    {
      role: "help",
      submenu: [
        {
          label: "\u9879\u76EE\u53D1\u5E03\u9875 / Project Page",
          click: () => openHelpUrl(PROJECT_WEBSITE_URL, "project page")
        },
        {
          label: "\u6700\u65B0\u7248\u672C / Latest Release",
          click: () => openHelpUrl(LATEST_RELEASE_URL, "latest release")
        }
      ]
    }
  );
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}
function defaultPort() {
  const raw = Number(process.env.ZZ_WEB_PORT || 0);
  return Number.isInteger(raw) && raw >= 0 && raw <= 65535 ? raw : 0;
}
function normalizePort(value) {
  const raw = Number(value);
  return Number.isInteger(raw) && raw >= 0 && raw <= 65535 ? raw : defaultPort();
}
function appendLog(chunk) {
  const text = String(chunk || "").trim();
  if (!text) return;
  serverLog.push(text);
  if (serverLog.length > 40) serverLog.splice(0, serverLog.length - 40);
}
function statusSnapshot() {
  return {
    state: serverState,
    url: serverUrl,
    pid: serverProcess ? serverProcess.pid : null,
    log: [...serverLog]
  };
}
async function checkForApplicationUpdate() {
  if (updateStatus.status === "current" || updateStatus.status === "available") return { ...updateStatus };
  if (updateCheckPromise) return updateCheckPromise;
  const currentVersion = app.getVersion();
  updateStatus = { status: "checking", currentVersion };
  updateCheckPromise = checkLatestRelease({
    currentVersion,
    fetchImpl: (url, options) => net.fetch(url, options)
  }).then((result) => {
    updateStatus = result;
    appendLog(result.status === "available" ? `Application update available: ${result.currentVersion} -> ${result.latestVersion}` : `Application update check complete: ${result.currentVersion} is current`);
    return { ...updateStatus };
  }).catch((error) => {
    const message = error && error.message ? error.message : String(error);
    updateStatus = { status: "error", currentVersion, error: message };
    appendLog(`Application update check failed: ${message}`);
    return { ...updateStatus };
  }).finally(() => {
    updateCheckPromise = null;
  });
  return updateCheckPromise;
}
function multiplayerSnapshot() {
  const snapshot = multiplayerClient.getSnapshot();
  const lan = lanManager.getSnapshot();
  return {
    ...snapshot,
    status: snapshot.state,
    lastError: snapshot.error,
    networkRoute: multiplayerRoute,
    lan: {
      ...lan,
      state: String(lan.state || "stopped").toUpperCase(),
      localUrl: lan.manualEndpoints.localUrl,
      addresses: lan.manualEndpoints.addresses,
      urls: lan.manualEndpoints.urls
    }
  };
}
function queueMultiplayerRecoveryWrite() {
  if (!multiplayerRecoveryPath) return multiplayerRecoveryWrite;
  const recovery = multiplayerClient.getRecoverySession();
  const targetPath = multiplayerRecoveryPath;
  multiplayerRecoveryWrite = multiplayerRecoveryWrite.then(async () => {
    if (recovery === null) {
      await fs.rm(targetPath, { force: true });
      return;
    }
    await fs.mkdir(path.dirname(targetPath), { recursive: true });
    const temporaryPath = `${targetPath}.tmp`;
    await fs.writeFile(temporaryPath, `${JSON.stringify(recovery)}
`, {
      encoding: "utf8",
      mode: 384
    });
    await fs.rename(temporaryPath, targetPath);
  }).catch((error) => {
    appendLog(`Multiplayer recovery write failed: ${error.message || error}`);
  });
  return multiplayerRecoveryWrite;
}
async function restoreMultiplayerRecovery() {
  if (!multiplayerRecoveryPath) return false;
  let raw;
  try {
    raw = await fs.readFile(multiplayerRecoveryPath, "utf8");
  } catch (error) {
    if (error && error.code === "ENOENT") return false;
    throw error;
  }
  try {
    multiplayerClient.restoreRecoverySession(JSON.parse(raw));
    return true;
  } catch (error) {
    appendLog(`Multiplayer recovery restore failed: ${error.message || error}`);
    return false;
  }
}
function scheduleMultiplayerReconnect() {
  if (multiplayerClient.state !== "RECONNECTING" || !multiplayerClient.getSnapshot().canReconnect) {
    if (multiplayerReconnectTimer !== null) clearTimeout(multiplayerReconnectTimer);
    multiplayerReconnectTimer = null;
    return;
  }
  if (multiplayerReconnectTimer !== null) return;
  multiplayerReconnectTimer = setTimeout(() => {
    multiplayerReconnectTimer = null;
    if (multiplayerClient.state !== "RECONNECTING") return;
    if (multiplayerClient.getSnapshot().reconnectAttemptActive) return;
    try {
      multiplayerClient.reconnect();
    } catch (error) {
      appendLog(`Multiplayer reconnect attempt failed: ${error.message || error}`);
      scheduleMultiplayerReconnect();
    }
  }, multiplayerReconnectDelayMs);
}
function syncLanAdvertisement() {
  const lan = lanManager.getSnapshot();
  if (lan.state !== "running") return;
  const room = multiplayerClient.room;
  if (room && ["WAITING_FOR_PLAYERS", "READY_CHECK"].includes(room.status)) {
    lanManager.updateRoom({
      roomCode: room.roomCode,
      players: Array.isArray(room.players) ? room.players.length : 0,
      capacity: room.capacity
    });
  } else {
    lanManager.clearRoom();
  }
}
function broadcastMultiplayerEvent(event) {
  syncLanAdvertisement();
  queueMultiplayerRecoveryWrite();
  scheduleMultiplayerReconnect();
  const payload = {
    ...event,
    snapshot: multiplayerSnapshot()
  };
  if (!mainWindow || mainWindow.isDestroyed() || !isTrustedUrl(mainWindow.webContents.getURL())) return;
  mainWindow.webContents.send("multiplayer:event", payload);
}
multiplayerClient.onEvent(broadcastMultiplayerEvent);
function rememberTrustedOrigin(url) {
  trustedOrigin = new URL(url).origin;
}
function isTrustedUrl(url) {
  if (!trustedOrigin || !url) return false;
  try {
    return new URL(url).origin === trustedOrigin;
  } catch (_) {
    return false;
  }
}
function isTrustedReplayUrl(url) {
  if (!isTrustedUrl(url)) return false;
  try {
    const parsed = new URL(url);
    return parsed.hash.startsWith("#/replay/");
  } catch (_) {
    return false;
  }
}
function assertTrustedSender(event) {
  const senderUrl = event.senderFrame ? event.senderFrame.url : event.sender.getURL();
  if (!isTrustedUrl(senderUrl)) {
    throw new Error("Untrusted IPC sender.");
  }
}
function waitForHttp(url, timeoutMs = 15e3) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const poll = () => {
      const request = http.get(url, (response) => {
        response.resume();
        resolve(true);
      });
      request.on("error", (error) => {
        if (Date.now() - startedAt >= timeoutMs) {
          reject(error);
          return;
        }
        setTimeout(poll, 250);
      });
      request.setTimeout(1e3, () => {
        request.destroy();
      });
    };
    poll();
  });
}
function pythonArgs(port) {
  const args = [
    "-m",
    "zz.web.server",
    "--host",
    "127.0.0.1",
    "--port",
    String(port)
  ];
  if (process.env.ZZ_ASSET_ROOT) {
    args.push("--asset-root", process.env.ZZ_ASSET_ROOT);
  }
  return args;
}
async function startServer(options = {}) {
  if (serverProcess && serverState !== "stopped") {
    return statusSnapshot();
  }
  const port = normalizePort(options.port);
  serverState = "starting";
  const python = process.env.ZZ_PYTHON || "python";
  serverProcess = spawn(python, pythonArgs(port), {
    cwd: projectRoot(),
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"]
  });
  serverProcess.stdout.on("data", (chunk) => {
    const text = chunk.toString("utf8");
    appendLog(text);
    const match = text.match(/https?:\/\/127\.0\.0\.1:\d+\//);
    if (match) {
      serverUrl = match[0];
    }
  });
  serverProcess.stderr.on("data", appendLog);
  serverProcess.on("exit", (code, signal) => {
    appendLog(`Python server exited: ${code ?? signal}`);
    serverProcess = null;
    if (serverState !== "stopping") {
      serverState = "stopped";
    }
  });
  const readinessUrl = new Promise((resolve, reject) => {
    const startedAt = Date.now();
    const readUrl = () => {
      if (serverUrl) {
        resolve(serverUrl);
        return;
      }
      if (Date.now() - startedAt > 15e3) {
        reject(new Error("Timed out waiting for Python server URL."));
        return;
      }
      setTimeout(readUrl, 100);
    };
    readUrl();
  });
  serverUrl = await readinessUrl;
  await waitForHttp(serverUrl, 15e3);
  serverState = "running";
  return statusSnapshot();
}
function waitForProcessExit(child, timeoutMs = 5e3) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve(true);
    };
    child.once("exit", finish);
    child.once("close", finish);
    setTimeout(() => {
      if (!done) child.kill();
      finish();
    }, timeoutMs);
  });
}
async function stopServer() {
  if (!serverProcess) {
    serverState = "stopped";
    return statusSnapshot();
  }
  serverState = "stopping";
  const processToStop = serverProcess;
  processToStop.kill();
  await waitForProcessExit(processToStop);
  if (serverProcess === processToStop) {
    serverProcess = null;
  }
  serverState = "stopped";
  serverUrl = null;
  return statusSnapshot();
}
function createReplayWindow(url) {
  if (!isTrustedReplayUrl(url)) {
    throw new Error("Untrusted replay URL.");
  }
  const replayWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    backgroundColor: "#05090c",
    icon: applicationIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  replayWindow.webContents.on("will-navigate", (event, targetUrl) => {
    if (!isTrustedUrl(targetUrl)) {
      event.preventDefault();
    }
  });
  replayWindow.webContents.setWindowOpenHandler(({ url: targetUrl }) => isTrustedUrl(targetUrl) ? { action: "allow" } : { action: "deny" });
  replayWindow.loadURL(url);
  return replayWindow;
}
async function createWindow() {
  const status = await startServer();
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 980,
    minHeight: 680,
    icon: applicationIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  rememberTrustedOrigin(serverUrl);
  mainWindow.webContents.on("will-navigate", (event, targetUrl) => {
    if (!isTrustedUrl(targetUrl)) {
      event.preventDefault();
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => isTrustedUrl(url) ? { action: "allow" } : { action: "deny" });
  await mainWindow.loadURL(serverUrl);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  return status;
}
function registerIpc() {
  ipcMain.handle("server:start", async (_event, options) => {
    assertTrustedSender(_event);
    return startServer(options || {});
  });
  ipcMain.handle("server:stop", async (_event) => {
    assertTrustedSender(_event);
    return stopServer();
  });
  ipcMain.handle("server:status", async (_event) => {
    assertTrustedSender(_event);
    return statusSnapshot();
  });
  ipcMain.handle("dialog:openFolder", async (_event) => {
    assertTrustedSender(_event);
    const result = await dialog.showOpenDialog({ properties: ["openDirectory"] });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("shell:openPath", async (_event, targetPath) => {
    assertTrustedSender(_event);
    if (typeof targetPath !== "string" || !targetPath || !path.isAbsolute(targetPath) || targetPath.includes("\0")) {
      return { ok: false, error: "invalid_path" };
    }
    const error = await shell.openPath(targetPath);
    return { ok: !error, error: error || null };
  });
  ipcMain.handle("replay:openWindow", async (_event, payload) => {
    assertTrustedSender(_event);
    const url = payload && typeof payload.url === "string" ? payload.url : "";
    createReplayWindow(url);
    return { ok: true };
  });
  ipcMain.handle("assets:selectRoot", async (_event) => {
    assertTrustedSender(_event);
    const result = await dialog.showOpenDialog({ properties: ["openDirectory"], title: "Select asset root" });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("decks:selectRoot", async (_event) => {
    assertTrustedSender(_event);
    const result = await dialog.showOpenDialog({ properties: ["openDirectory"], title: "Select deck root" });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("app:getVersion", async (_event) => {
    assertTrustedSender(_event);
    return app.getVersion();
  });
  ipcMain.handle("app:checkForUpdates", async (_event) => {
    assertTrustedSender(_event);
    return checkForApplicationUpdate();
  });
  ipcMain.handle("app:openReleasePage", async (_event) => {
    assertTrustedSender(_event);
    await shell.openExternal(LATEST_RELEASE_URL);
    return { ok: true };
  });
  ipcMain.handle("app:quit", async (_event) => {
    assertTrustedSender(_event);
    app.quit();
    return { ok: true };
  });
  ipcMain.handle("multiplayer:status", async (_event) => {
    assertTrustedSender(_event);
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:connect", async (_event, config) => {
    assertTrustedSender(_event);
    multiplayerRoute = "CHECKING";
    multiplayerClient.connect(config || {});
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:disconnect", async (_event) => {
    assertTrustedSender(_event);
    multiplayerClient.disconnect();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:reconnect", async (_event) => {
    assertTrustedSender(_event);
    multiplayerRoute = "CHECKING";
    multiplayerClient.reconnect();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:createRoom", async (_event, payload) => {
    assertTrustedSender(_event);
    multiplayerClient.createRoom(payload || {});
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:joinRoom", async (_event, payload) => {
    assertTrustedSender(_event);
    multiplayerClient.joinRoom(payload || {});
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:selectDeck", async (_event, payload) => {
    assertTrustedSender(_event);
    multiplayerClient.selectDeck(payload || {});
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:setReady", async (_event, ready) => {
    assertTrustedSender(_event);
    multiplayerClient.setReady({ ready });
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:submitAction", async (_event, action) => {
    assertTrustedSender(_event);
    const clientActionId = multiplayerClient.submitAction({ action });
    await queueMultiplayerRecoveryWrite();
    return { ...multiplayerSnapshot(), clientActionId };
  });
  ipcMain.handle("multiplayer:surrender", async (_event) => {
    assertTrustedSender(_event);
    const clientActionId = multiplayerClient.surrender();
    await queueMultiplayerRecoveryWrite();
    return { ...multiplayerSnapshot(), clientActionId };
  });
  ipcMain.handle("multiplayer:requestSync", async (_event) => {
    assertTrustedSender(_event);
    multiplayerClient.requestSync();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:leaveRoom", async (_event) => {
    assertTrustedSender(_event);
    multiplayerClient.leaveRoom();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:lanStatus", async (_event) => {
    assertTrustedSender(_event);
    return multiplayerSnapshot().lan;
  });
  ipcMain.handle("multiplayer:startLanHost", async (_event, options) => {
    assertTrustedSender(_event);
    await lanManager.startHost({
      projectRoot: projectRoot(),
      python: process.env.ZZ_PYTHON || "python",
      port: options && options.port,
      serverName: options && options.serverName
    });
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:stopLanHost", async (_event) => {
    assertTrustedSender(_event);
    await lanManager.stopHost();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:discoverLan", async (_event, options) => {
    assertTrustedSender(_event);
    return lanManager.discover(options || {});
  });
}
app.whenReady().then(async () => {
  installApplicationMenu();
  if (process.platform === "darwin" && app.dock) app.dock.setIcon(applicationIconPath());
  multiplayerRecoveryPath = path.join(app.getPath("userData"), "multiplayer-recovery.json");
  const shouldReconnect = await restoreMultiplayerRecovery();
  registerIpc();
  await createWindow();
  if (shouldReconnect) {
    try {
      multiplayerClient.reconnect();
    } catch (error) {
      appendLog(`Initial multiplayer reconnect failed: ${error.message || error}`);
      scheduleMultiplayerReconnect();
    }
  }
  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
    }
  });
});
app.on("before-quit", (event) => {
  if (shutdownPrepared) return;
  event.preventDefault();
  if (shutdownPromise !== null) return;
  if (multiplayerReconnectTimer !== null) clearTimeout(multiplayerReconnectTimer);
  multiplayerReconnectTimer = null;
  if (multiplayerClient.getSnapshot().canReconnect) multiplayerClient.suspend();
  else multiplayerClient.disconnect();
  shutdownPromise = Promise.allSettled([
    queueMultiplayerRecoveryWrite(),
    lanManager.stopHost(),
    stopServer()
  ]).finally(() => {
    shutdownPrepared = true;
    app.quit();
  });
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
