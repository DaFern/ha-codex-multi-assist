"use strict";
// Production panel + simulated HA/native boundary, no real app or microphone.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../custom_components/codex_assist/learning/frontend/launch-panel.js"), "utf8");
const settle = () => new Promise(resolve => setImmediate(resolve));
const requestHash = "#request=" + "a".repeat(32) + "&user=alice&profile=alice-profile";

function harness(options = {}) {
  const messages = [];
  const calls = [];
  const listeners = {};
  const timers = new Map();
  let serial = 0;
  let handler = async () => ({ user_id: "alice", profile_id: "alice-profile", pipeline_id: "learning-pipeline" });
  class Element {
    constructor() { this.children = []; this.events = {}; this.textContent = ""; }
    attachShadow() { return this.shadowRoot = new Element(); }
    append(...nodes) { this.children.push(...nodes); }
    setAttribute() {}
    addEventListener(name, callback) { this.events[name] = callback; }
    set innerHTML(value) { throw new Error("No HTML interpolation"); }
  }
  const location = { pathname: "/voice-match-learning", hash: options.hash ?? requestHash };
  const history = { state: options.history || null, replaceState(state, ignored, url) { this.state = state; location.hash = ""; location.pathname = url; } };
  const registry = new Map();
  const window = {};
  window.top = options.iframe ? {} : window;
  const document = { hidden: false, createElement: () => new Element(),
    addEventListener(name, callback) { listeners[name] = callback; },
    removeEventListener(name) { delete listeners[name]; } };
  const context = vm.createContext({
    HTMLElement: Element, document, window, location, history, URLSearchParams,
    customElements: { get: key => registry.get(key), define: (key, value) => registry.set(key, value) },
    setTimeout: (callback, delay) => { timers.set(++serial, { callback, delay }); return serial; },
    clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(source, context);
  const external = { config: { hasAssist: !options.browser }, fireMessage(message) {
    messages.push(JSON.parse(JSON.stringify(message)));
    if (options.throwAfterSend) throw new Error("Synthetic uncertain native dispatch");
  } };
  const hass = { connected: true, user: { id: "alice" }, connection: {}, auth: { external },
    callWS: async data => { calls.push(JSON.parse(JSON.stringify(data))); return handler(data); } };
  const Panel = registry.get("voice-match-launch-panel");
  const panel = new Panel();
  return { panel, hass, history, location, document, external, messages, calls, listeners, timers,
    setHandler(value) { handler = value; },
    mount() { panel.hass = hass; panel.connectedCallback(); },
    reload() { const next = new Panel(); next.hass = hass; next.connectedCallback(); return next; },
  };
}

async function checks() {
  const h = harness();
  h.mount();
  await settle();
  assert.deepEqual(h.calls, [{ type: "codex_assist/voice_learning/launch_info" }]);
  assert.deepEqual(h.messages, [{ type: "assist/show", payload: { pipeline_id: "learning-pipeline", start_listening: true } }]);
  assert.equal(h.location.hash, "");
  assert.equal(h.history.state.voiceMatchLaunchConsumed, true);
  assert.match(h.panel._message.textContent, /requested/);
  assert.equal(h.panel._open.disabled, true);
  await h.panel._start();
  h.panel.hass = { ...h.hass };
  h.panel.disconnectedCallback();
  h.panel.connectedCallback();
  await settle();
  assert.equal(h.messages.length, 1);
  assert.equal(h.reload()._open.disabled, true, "Reload/Back cannot repeat the native launch");
  assert.equal(h.messages.length, 1);

  const manual = harness({ hash: "" });
  manual.mount();
  await settle();
  assert.equal(manual.calls.length, 0, "Direct page entry is not an automatic launch");
  await manual.panel._start();
  assert.equal(manual.messages.length, 1);

  for (const options of [{ browser: true }, { iframe: true }, { hash: requestHash + "&consent=true" },
    { hash: requestHash.replace("user=alice", "user=bob") }, { hash: "#request=invalid&user=alice&profile=alice-profile" }]) {
    const invalid = harness(options);
    invalid.mount();
    await settle();
    assert.equal(invalid.messages.length, 0);
    assert.equal(invalid.calls.length, 0);
  }

  for (const result of [{ user_id: "bob", profile_id: "alice-profile", pipeline_id: "learning" },
    { user_id: "alice", profile_id: "bob-profile", pipeline_id: "learning" },
    { user_id: "alice", profile_id: "alice-profile", pipeline_id: "preferred" },
    { user_id: "alice", profile_id: "alice-profile", pipeline_id: "last_used" },
    { user_id: "alice", profile_id: "alice-profile", pipeline_id: null }, null]) {
    const changed = harness();
    changed.setHandler(async () => result);
    changed.mount();
    await settle();
    assert.equal(changed.messages.length, 0);
    assert.equal(changed.panel._open.disabled, true);
  }

  for (const change of ["account", "connection", "auth", "hidden", "detached", "route"]) {
    const interrupted = harness();
    let resolve;
    interrupted.setHandler(() => new Promise(complete => { resolve = complete; }));
    interrupted.mount();
    if (change === "account") interrupted.panel.hass = { ...interrupted.hass, user: { id: "bob" } };
    if (change === "connection") interrupted.panel.hass = { ...interrupted.hass, connection: {} };
    if (change === "auth") interrupted.panel.hass = { ...interrupted.hass, auth: { external: interrupted.external } };
    if (change === "hidden") { interrupted.document.hidden = true; interrupted.listeners.visibilitychange(); }
    if (change === "detached") interrupted.panel.disconnectedCallback();
    if (change === "route") interrupted.location.pathname = "/somewhere-else";
    resolve({ user_id: "alice", profile_id: "alice-profile", pipeline_id: "learning" });
    await settle();
    assert.equal(interrupted.messages.length, 0, change);
  }

  const failed = harness({ throwAfterSend: true });
  failed.mount();
  await settle();
  await failed.panel._start();
  assert.equal(failed.messages.length, 1, "Uncertain dispatch cannot be retried");
  assert.match(failed.panel._message.textContent, /could not be verified/);

  const timed = harness();
  let late;
  timed.setHandler(() => new Promise(resolve => { late = resolve; }));
  timed.mount();
  await timed.panel._start();
  assert.equal(timed.calls.length, 1, "Busy click cannot duplicate discovery");
  [...timed.timers.values()].find(timer => timer.delay === 16000).callback();
  await settle();
  late({ user_id: "alice", profile_id: "alice-profile", pipeline_id: "learning" });
  await settle();
  assert.equal(timed.messages.length, 0, "Late read completion after timeout cannot launch");

  const peer = harness();
  peer.setHandler(async () => { throw new Error("synthetic-peer-secret"); });
  peer.mount();
  await settle();
  assert.equal(peer.messages.length, 0);
  assert(!peer.panel._message.textContent.includes("synthetic-peer-secret"));
  console.log("Native learning launcher boundary checks passed");
}

checks().catch(error => { console.error(error); process.exitCode = 1; });
