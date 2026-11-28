// Bird local in the page: the pairing code, the routing of requests, the pictures, the probe and the pairing call
// (fake fetch), the mode switching of core.js, and the FR/EN parity of its strings. Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import * as L from "../../birds/web/static/local-data.js";
import { LOCAL_CMDS, LOCAL_STRINGS } from "../../birds/web/static/local-i18n.js";
import { activeMode, activeModel, localBase, localPair, modelLabel, state } from "../../birds/web/static/core.js";

const memoryStorage = () => {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    m,
  };
};

test("strings: French and English have the same keys, no empty text", () => {
  assert.deepEqual(Object.keys(LOCAL_STRINGS.fr).sort(), Object.keys(LOCAL_STRINGS.en).sort());
  for (const lang of ["fr", "en"])
    for (const [k, v] of Object.entries(LOCAL_STRINGS[lang])) assert.ok(v.trim() && k.startsWith("local."), k);
  assert.equal(LOCAL_STRINGS.fr["local.mode"], "Bird local (votre machine)");
  assert.equal(LOCAL_STRINGS.fr["local.connect"], "Se connecter au Bird local");
  assert.match(LOCAL_CMDS.vllm, /^vllm serve adubrou\/Bird-S-4B --host 127\.0\.0\.1 --port 8000$/);
});

test("pairing code: typed loosely, compared strictly, shaped like the terminal shows it", () => {
  assert.equal(L.normalizeCode(" abcd-efgh "), "ABCDEFGH");
  assert.equal(L.formatCode("abcdefgh"), "ABCD-EFGH");
  assert.equal(L.formatCode("abc"), "ABC");
  assert.ok(L.codeShapeOk("abcd efgh") && !L.codeShapeOk("ABCD-EFG") && !L.codeShapeOk("ABCD-EFG0"));
  assert.equal(L.codeFromHash("#pair=abcd-efgh"), "ABCD-EFGH");
  assert.equal(L.codeFromHash("#x=1&pair=ABCDEFGH"), "ABCD-EFGH");
  assert.equal(L.codeFromHash("#pair=<script>"), null);
  assert.equal(L.codeFromHash(""), null);
});

test("pairing store: this tab by default, this device only with « Se souvenir », « Oublier » clears both", () => {
  const session = memoryStorage();
  const local = memoryStorage();
  const store = L.pairStore(session, local);
  store.set("abcdefgh");
  assert.equal(session.getItem(L.PAIR_KEY), "ABCD-EFGH");
  assert.equal(local.getItem(L.PAIR_KEY), null);
  assert.ok(!store.remembered());
  store.set("ABCD-EFGH", true);
  assert.equal(local.getItem(L.PAIR_KEY), "ABCD-EFGH");
  assert.ok(store.remembered());
  store.forget();
  assert.equal(store.get(), null);
  assert.equal(session.m.size + local.m.size, 0);
  // storage blocked (private mode): the code lives as long as the page
  const broken = { getItem() { throw new Error("x"); }, setItem() { throw new Error("x"); }, removeItem() { throw new Error("x"); } };
  const s2 = L.pairStore(broken, broken);
  s2.set("ABCDEFGH");
  assert.equal(s2.get(), "ABCD-EFGH");
});

test("routing: the hosted page in Bird local mode sends /api/* to the machine, with the code, never the hosted secrets", () => {
  const ctx = { mode: "local", base: "http://127.0.0.1:8765", code: "ABCD-EFGH", onLocal: false };
  const init = {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Bird-Mode": "local", "X-Bird-Access": "hosted-code", "X-Bird-Token": "hf_x" },
    body: "{}",
  };
  const r = L.routeRequest("/api/chat", init, ctx);
  assert.equal(r.input, "http://127.0.0.1:8765/api/chat");
  assert.equal(r.init.headers["x-bird-pair"], "ABCD-EFGH");
  assert.equal(r.init.headers["x-bird-mode"], "server");
  assert.equal(r.init.headers["x-bird-access"], undefined);
  assert.equal(r.init.headers["x-bird-token"], undefined);
  assert.equal(r.init.credentials, "omit");
  assert.equal(r.init.mode, "cors");
  assert.equal(r.init.body, "{}");
  for (const path of ["/api/tool", "/api/export", "/api/canvas/check", "/api/office", "/api/data/table"])
    assert.ok(L.routeRequest(path, {}, ctx).input.startsWith("http://127.0.0.1:8765/api/"), path);
  // health describes the hosted deployment; non-API and absolute URLs are left alone
  assert.equal(L.routeRequest("/api/health", {}, ctx).input, "/api/health");
  assert.equal(L.routeRequest("/static/app.js", {}, ctx).input, "/static/app.js");
  assert.equal(L.routeRequest("http://127.0.0.1:8765/api/health", {}, ctx).input, "http://127.0.0.1:8765/api/health");
  // hosted modes: nothing changes, the code never reaches the hosted server
  for (const mode of ["server", "user", "demo"]) {
    const h = L.routeRequest("/api/chat", { headers: { a: "1" } }, { ...ctx, mode });
    assert.equal(h.input, "/api/chat");
    assert.deepEqual(h.init.headers, { a: "1" });
  }
  // no code in this tab (a new tab, « Se souvenir » not ticked): still the machine, never the host, no pair header
  const bare = L.routeRequest("/api/chat", { headers: { "X-Bird-Pair": "old" } }, { ...ctx, code: null });
  assert.equal(bare.input, "http://127.0.0.1:8765/api/chat");
  assert.equal(bare.init.headers["x-bird-pair"], undefined);
  // the page served by Bird local without a code yet: unchanged
  assert.equal(L.routeRequest("/api/chat", {}, { ...ctx, code: null, onLocal: true }).input, "/api/chat");
});

test("routing: the page served by Bird local adds the code to its own calls, same URL", () => {
  const headers = new Map([["Content-Type", "application/json"]]);
  const r = L.routeRequest("/api/chat", { headers }, { mode: "server", base: "", code: "ABCD-EFGH", onLocal: true });
  assert.equal(r.input, "/api/chat");
  assert.equal(r.init.headers["x-bird-pair"], "ABCD-EFGH");
  assert.equal(r.init.headers["content-type"], "application/json");
});

test("pictures of a local turn point at the local Bird, other URLs untouched", () => {
  const ev = {
    type: "answer",
    content: "/api/img?u=x stays text in prose? no: only exact strings",
    web_images: [{ src: "/api/img?u=a&e=1&s=2", page: "https://example.org" }],
    widgets: [{ map: { src: "/api/map?t=abc" }, icon: "/api/icon?d=x&s=y", other: "/api/chat" }],
  };
  const out = L.localizeAssets(ev, "http://127.0.0.1:8765");
  assert.equal(out.web_images[0].src, "http://127.0.0.1:8765/api/img?u=a&e=1&s=2");
  assert.equal(out.web_images[0].page, "https://example.org");
  assert.equal(out.widgets[0].map.src, "http://127.0.0.1:8765/api/map?t=abc");
  assert.equal(out.widgets[0].icon, "http://127.0.0.1:8765/api/icon?d=x&s=y");
  assert.equal(out.widgets[0].other, "/api/chat");
  assert.equal(out.content, ev.content);
  assert.equal(ev.web_images[0].src, "/api/img?u=a&e=1&s=2"); // a copy: the original event is untouched
});

const respond = (status, body) => ({ status, json: async () => body });

test("probe: 127.0.0.1 then localhost; found, another program, or nothing", async () => {
  const calls = [];
  const found = await L.probe(async (url, init) => {
    calls.push([url, init.credentials]);
    if (url.startsWith("http://127.0.0.1")) throw new TypeError("refused");
    return respond(200, { bird_local: { paired: false } });
  });
  assert.equal(found.status, "found");
  assert.equal(found.base, "http://localhost:8765");
  assert.deepEqual(calls, [["http://127.0.0.1:8765/api/health", "omit"], ["http://localhost:8765/api/health", "omit"]]);
  assert.equal((await L.probe(async () => respond(200, { model: "x" }))).status, "not_bird");
  assert.equal((await L.probe(async () => { throw new TypeError("down"); })).status, "unreachable");
  assert.deepEqual(L.localBases(9000), ["http://127.0.0.1:9000", "http://localhost:9000"]);
});

test("pair: shape first, then the local Bird decides", async () => {
  let sent = null;
  const fetchOk = async (url, init) => ((sent = [url, init.headers["X-Bird-Pair"]]), respond(200, { ok: true, model: "m" }));
  assert.equal((await L.pair(fetchOk, "http://127.0.0.1:8765", "abcd")).status, "shape");
  assert.equal(sent, null);
  const ok = await L.pair(fetchOk, "http://127.0.0.1:8765", "abcd efgh");
  assert.ok(ok.ok && ok.info.model === "m");
  assert.deepEqual(sent, ["http://127.0.0.1:8765/api/local/pair", "ABCD-EFGH"]);
  assert.equal((await L.pair(async () => respond(401, {}), "b", "ABCDEFGH")).status, "invalid");
  assert.equal((await L.pair(async () => respond(429, {}), "b", "ABCDEFGH")).status, "locked");
  assert.equal((await L.pair(async () => { throw new TypeError("x"); }, "b", "ABCDEFGH")).status, "unreachable");
});

test("mode switching: Bird local only when chosen and paired, back to hosted on disconnect", () => {
  state.health = { modes: { server: true, user: true }, default_mode: "server", local_bird: { port: 8765 }, model: "adubrou/Bird-S-4B" };
  state.prefs.mode = "local";
  localPair.forget();
  // chosen, but no code in this tab (new tab, not remembered): still Bird local, never a silent hop to the host
  assert.equal(activeMode(), "local");
  localPair.set("ABCD-EFGH");
  assert.equal(activeMode(), "local");
  assert.equal(modelLabel(), "Bird local");
  state.localHealth = { model: "adubrou/Bird-S-4B" };
  assert.equal(activeModel(), "adubrou/Bird-S-4B");
  assert.equal(localBase(), "http://127.0.0.1:8765");
  state.prefs.localBase = "http://localhost:8765";
  assert.equal(localBase(), "http://localhost:8765");
  // a stored base that is not one of the two loopback origins of the port is never used
  for (const bad of ["https://evil.example", "http://127.0.0.1:9999", "http://127.0.0.1:8765/x"]) {
    state.prefs.localBase = bad;
    assert.equal(localBase(), "http://127.0.0.1:8765", bad);
  }
  state.prefs.localBase = "http://localhost:8765";
  // health not loaded yet: a paired Bird local still holds (never a silent hop to the hosted model)
  state.health = null;
  assert.equal(activeMode(), "local");
  // a deployment that removed the choice (BIRD_LOCAL_BIRD_PORT=off)
  state.health = { modes: { server: true }, local_bird: null };
  assert.equal(activeMode(), "server");
  // disconnect
  state.health = { modes: { server: true }, local_bird: { port: 8765 } };
  state.prefs.mode = "";
  assert.equal(activeMode(), "server");
  assert.notEqual(modelLabel(), "Bird local");
  // the page served by Bird local itself is the « server » mode of that machine
  state.prefs.mode = "local";
  globalThis.location = { hostname: "127.0.0.1" };
  try {
    assert.equal(activeMode(), "local"); // a hosted copy on 127.0.0.1 (development) is not Bird local
    state.health = { modes: { server: true }, bird_local: { paired: true } };
    assert.equal(activeMode(), "server");
  } finally {
    delete globalThis.location;
    localPair.forget();
    state.prefs.mode = "";
  }
});

test("Safari is told to open Bird local directly; a down model server is told apart from a down Bird local", () => {
  const SAFARI = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15";
  const IOS_CHROME = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0 Mobile/15E148 Safari/604.1";
  const CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36";
  const EDGE = CHROME + " Edg/131.0";
  const FIREFOX = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:132.0) Gecko/20100101 Firefox/132.0";
  const ANDROID = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36";
  assert.ok(L.isSafari(SAFARI) && L.isSafari(IOS_CHROME)); // every iOS browser is WebKit
  for (const ua of [CHROME, EDGE, FIREFOX, ANDROID, "", undefined]) assert.ok(!L.isSafari(ua), ua);
  for (const code of ["unreachable", "endpoint_down", "timeout"]) assert.ok(L.MODEL_DOWN.has(code));
  assert.ok(!L.MODEL_DOWN.has("pair_required") && !L.MODEL_DOWN.has("local_unreachable"));
  for (const lang of ["fr", "en"])
    for (const k of ["local.model.title", "local.model.p", "local.safari"]) assert.ok(LOCAL_STRINGS[lang][k], `${lang} ${k}`);
});
