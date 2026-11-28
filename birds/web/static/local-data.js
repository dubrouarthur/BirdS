// Bird local, the logic without the DOM (tests/js/local.test.mjs): where the local Bird is, the pairing code, how a
// request of the page is routed to it, how its picture URLs are made absolute. docs/LOCAL.md.
//
// Privacy: in « Bird local » mode every /api/ call of the page goes to the user's machine (health excepted, which
// describes the hosted deployment); the hosted server sees no message, no attachment, no tool call.

export const PAIR_KEY = "bird.localPair"; // the pairing code: sessionStorage, or localStorage with « Se souvenir »
export const DEFAULT_PORT = 8765;
export const CODE_LEN = 8;
const ALPHABET = /^[23456789ABCDEFGHJKMNPQRSTVWXYZ]+$/;
// headers of the hosted modes that must never reach the local machine (the hosted access code, a typed endpoint)
const HOSTED_ONLY = ["x-bird-access", "x-bird-endpoint", "x-bird-token", "x-bird-model"];
const ASSET = /^\/api\/(img|map|icon)\?\S*$/; // pictures signed by the local Bird: shown from it, never from the host

export const isLoopback = (hostname) => ["127.0.0.1", "localhost", "[::1]"].includes(String(hostname || "").toLowerCase());

/** Safari (macOS, and every iOS browser, all WebKit) blocks an https page from calling http://127.0.0.1: the page
 * served by Bird local is the way there. Chrome, Edge, Firefox and their iOS-less cousins accept the loopback. */
export function isSafari(ua) {
  const u = String(ua || "");
  if (/\b(iPhone|iPad|iPod)\b/.test(u)) return true;
  return /Safari\//.test(u) && !/(Chrome|Chromium|CriOS|Edg|OPR|Firefox|FxiOS|Android)/.test(u);
}

/** Errors of a local turn that mean the user's model server (vLLM) is down while Bird local itself answers. */
export const MODEL_DOWN = new Set(["unreachable", "endpoint_down", "timeout", "waking"]);

/** The two exact loopback origins the page may reach (the CSP lists the same two, nothing wider). */
export const localBases = (port = DEFAULT_PORT) => [`http://127.0.0.1:${port}`, `http://localhost:${port}`];

/** What the user typed, the way the local Bird compares it: upper case, no separator. */
export const normalizeCode = (value) => String(value || "").replace(/[\s\-_.]/g, "").toUpperCase().slice(0, 64);
/** Typed « abcd efgh » → « ABCD-EFGH ». */
export function formatCode(value) {
  const n = normalizeCode(value).slice(0, CODE_LEN);
  return n.length > 4 ? `${n.slice(0, 4)}-${n.slice(4)}` : n;
}
export const codeShapeOk = (value) => {
  const n = normalizeCode(value);
  return n.length === CODE_LEN && ALPHABET.test(n);
};

/** The pairing code, kept for this tab (sessionStorage) or on this device (localStorage, « Se souvenir »). */
export function pairStore(session, local) {
  const safe = (fn, fallback = null) => {
    try {
      return fn();
    } catch {
      return fallback; // storage blocked: pairing lasts as long as the page
    }
  };
  let memory = null;
  return {
    get() {
      return safe(() => session?.getItem(PAIR_KEY)) || safe(() => local?.getItem(PAIR_KEY)) || memory;
    },
    remembered() {
      return !!safe(() => local?.getItem(PAIR_KEY));
    },
    set(code, remember = false) {
      const value = formatCode(code);
      memory = value;
      safe(() => session?.setItem(PAIR_KEY, value));
      if (remember) safe(() => local?.setItem(PAIR_KEY, value));
      else safe(() => local?.removeItem(PAIR_KEY));
      return value;
    },
    forget() {
      memory = null;
      safe(() => session?.removeItem(PAIR_KEY));
      safe(() => local?.removeItem(PAIR_KEY));
    },
  };
}

/** « #pair=ABCD-EFGH » opened by scripts/bird_local.py: the code, or null. The fragment never leaves the browser. */
export function codeFromHash(hash) {
  const m = /(?:^#|&)pair=([A-Za-z0-9-]{4,20})(?:&|$)/.exec(String(hash || ""));
  return m && codeShapeOk(m[1]) ? formatCode(m[1]) : null;
}

/** « #bird-local=8765:ABCD-EFGH », the ready-made link scripts/bird_local.py prints for the hosted chat: {port, code}
 * or null. Nothing to type; the fragment never leaves the browser. */
export function linkFromHash(hash) {
  const m = /(?:^#|&)bird-local=(\d{2,5}):([A-Za-z0-9-]{4,20})(?:&|$)/.exec(String(hash || ""));
  return m && codeShapeOk(m[2]) ? { port: Number(m[1]), code: formatCode(m[2]) } : null;
}

const plainHeaders = (headers) => {
  const out = {};
  if (!headers) return out;
  if (typeof headers.forEach === "function" && !Array.isArray(headers)) headers.forEach((v, k) => (out[k.toLowerCase()] = v));
  else for (const [k, v] of Array.isArray(headers) ? headers : Object.entries(headers)) out[k.toLowerCase()] = v;
  return out;
};

/**
 * Where a request of the page goes. ctx: {mode, base, code, onLocal}.
 * - the page served by Bird local itself (onLocal): same URL, plus the pairing code;
 * - the hosted page in « local » mode: /api/* (health excepted) to the local Bird, with the code (even without one:
 *   never to the host), without cookies,
 *   with the hosted-only headers removed and the server mode of the local Bird;
 * - anything else: unchanged.
 */
export function routeRequest(input, init = {}, ctx = {}) {
  const url = typeof input === "string" ? input : null;
  if (!url || !url.startsWith("/api/")) return { input, init };
  if (ctx.onLocal) {
    if (!ctx.code) return { input, init };
    const headers = { ...plainHeaders(init.headers), "x-bird-pair": ctx.code };
    return { input, init: { ...init, headers } };
  }
  if (ctx.mode !== "local" || !ctx.base || url.startsWith("/api/health")) return { input, init };
  const headers = plainHeaders(init.headers);
  for (const k of HOSTED_ONLY) delete headers[k];
  // no code in this tab yet: still the machine, never the host; Bird local answers pair_required
  if (ctx.code) headers["x-bird-pair"] = ctx.code;
  else delete headers["x-bird-pair"];
  if (headers["x-bird-mode"]) headers["x-bird-mode"] = "server";
  return {
    input: ctx.base + url,
    // Chrome's Local Network Access: the page says it means the loopback (other browsers ignore the field)
    init: { ...init, headers, mode: "cors", credentials: "omit", targetAddressSpace: "loopback" },
  };
}

/** A copy of an event where the local Bird's picture URLs (/api/img, /api/map, /api/icon) point at it. */
export function localizeAssets(value, base) {
  if (!base) return value;
  if (typeof value === "string") return ASSET.test(value) ? base + value : value;
  if (Array.isArray(value)) return value.map((v) => localizeAssets(v, base));
  if (value && typeof value === "object") {
    const out = {};
    for (const [k, v] of Object.entries(value)) out[k] = localizeAssets(v, base);
    return out;
  }
  return value;
}

async function getJson(fetchFn, url, init, timeoutMs) {
  const ctrl = typeof AbortController === "function" ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : 0;
  try {
    const r = await fetchFn(url, { ...init, mode: "cors", credentials: "omit", cache: "no-store", targetAddressSpace: "loopback", ...(ctrl ? { signal: ctrl.signal } : {}) });
    let body = null;
    try {
      body = await r.json();
    } catch {
      body = null;
    }
    return { status: r.status, body };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Look for the local Bird on 127.0.0.1 then localhost. → {status: "found", base, health} | {status: "not_bird"} |
 * {status: "unreachable"}. Never throws.
 */
export async function probe(fetchFn, port = DEFAULT_PORT, { timeoutMs = 2500 } = {}) {
  let answered = false;
  for (const base of localBases(port)) {
    try {
      const { status, body } = await getJson(fetchFn, `${base}/api/health`, { method: "GET" }, timeoutMs);
      answered = true;
      if (status === 200 && body?.bird_local) return { status: "found", base, health: body };
    } catch {
      /* not this name */
    }
  }
  return { status: answered ? "not_bird" : "unreachable" };
}

/** Check a typed code against the local Bird. → {ok, status: "ok"|"invalid"|"locked"|"unreachable"|"shape", info}. */
export async function pair(fetchFn, base, code, { timeoutMs = 4000 } = {}) {
  if (!codeShapeOk(code)) return { ok: false, status: "shape" };
  try {
    const { status, body } = await getJson(
      fetchFn,
      `${base}/api/local/pair`,
      { method: "POST", headers: { "X-Bird-Pair": formatCode(code) } },
      timeoutMs,
    );
    if (status === 200 && body?.ok) return { ok: true, status: "ok", info: body };
    if (status === 429) return { ok: false, status: "locked" };
    return { ok: false, status: "invalid" };
  } catch {
    return { ok: false, status: "unreachable" };
  }
}

/** The visitor's system, for the one install command: "windows", "mac" or "linux". */
export function osOf(ua) {
  const u = String(ua || "");
  if (/Windows/i.test(u)) return "windows";
  if (/Mac OS X|Macintosh/i.test(u) && !/\b(iPhone|iPad|iPod)\b/.test(u)) return "mac";
  return "linux";
}

/** One command per system: it installs Bird and the model, starts them, and this page connects on its own. */
export function installCommand(os, origin) {
  const site = /^https:\/\//.test(String(origin || "")) ? origin : "https://bird-s.vercel.app";
  return os === "windows" ? `irm ${site}/install.ps1 | iex` : `curl -fsSL ${site}/install.sh | sh`;
}
