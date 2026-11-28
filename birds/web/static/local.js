// « Se connecter au Bird local »: the chat on the user's own machine (docs/LOCAL.md). The settings choice and its
// connect flow, the « Bird local ne répond pas » card, the pairing dialog of the page served locally, the routing of
// the page's requests. The logic without the DOM is in local-data.js.
import {
  $,
  activeMode,
  button,
  copyText,
  h,
  icon,
  localBase,
  localPair,
  onLocalOrigin,
  savePrefs,
  state,
  t,
  toast,
} from "./core.js";
import { STRINGS } from "./i18n.js";
import { LOCAL_CMDS, LOCAL_STRINGS } from "./local-i18n.js";
import * as L from "./local-data.js";

for (const [lang, strings] of Object.entries(LOCAL_STRINGS)) Object.assign(STRINGS[lang], strings);

const hostOf = (base) => String(base || "").replace(/^https?:\/\//, "");
export const localPort = () => state.health?.local_bird?.port || L.DEFAULT_PORT;
/** The hosted page offers Bird local (its CSP lets it reach the loopback port). */
export const localOffered = () => !onLocalOrigin() && !!state.health?.local_bird;

// ------------------------------------------------------------------ routing of the page's requests

let installed = false;
/** Every fetch of the page goes through routeRequest: in « Bird local » mode, /api/* goes to the user's machine. */
export function installRouting() {
  if (installed || typeof globalThis.fetch !== "function") return;
  installed = true;
  const original = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (input, init) => {
    const ctx = { mode: activeMode(), base: localBase(), code: localPair.get(), onLocal: onLocalOrigin() };
    const routed = L.routeRequest(input, init || {}, ctx);
    return original(routed.input, routed.init);
  };
  // scripts/bird_local.py opens http://127.0.0.1:8765/#pair=CODE: keep the code for this tab, clean the address bar
  if (L.isLoopback(location.hostname)) {
    const code = L.codeFromHash(location.hash);
    if (code) {
      localPair.set(code, false);
      history.replaceState(null, "", location.pathname + location.search);
    }
  }
}

/** Pictures in an event of a local turn are served by the local Bird. */
export const localizeEvent = (event) => L.localizeAssets(event, localBase());

/** Refresh what the paired local Bird says about itself (model, measured energy). Quiet on failure. */
export async function refreshLocal() {
  if (activeMode() !== "local") return null;
  try {
    const r = await fetch(`${localBase()}/api/health`, {
      headers: { "X-Bird-Pair": localPair.get() || "" },
      mode: "cors",
      credentials: "omit",
      cache: "no-store",
      targetAddressSpace: "loopback",
    });
    const body = await r.json();
    if (body?.bird_local?.paired) {
      state.localHealth = { ...body.bird_local, energy: body.energy, base: localBase() };
      return state.localHealth;
    }
  } catch {
    /* not running: the turn's error card says what to do */
  }
  return null;
}

// ------------------------------------------------------------------ « Bird local ne répond pas »

function commandRow(cmd) {
  return h(
    "div",
    { class: "local-cmd" },
    // one unbreakable piece per word: at 360 px the command wraps between words, never inside « --port »
    h("code", null, cmd.split(" ").flatMap((w, i) => [i ? " " : "", h("span", { class: "local-tok", text: w })])),
    button("btn-quiet btn-icon btn-small", "copy", t("local.copy"), async () => {
      if (await copyText(cmd)) toast(t("local.copied"), "ok");
    }),
  );
}

/** The three steps to start Bird local, never a raw error. */
export function unreachableCard({ onRetry, onOff, port = localPort(), compact = false } = {}) {
  const step = (n, title, extra) =>
    h(
      "li",
      { class: "local-step" },
      h("span", { class: "local-step-n", "aria-hidden": "true", text: String(n) }),
      h("div", { class: "local-step-body" }, h("strong", { text: title }), extra),
    );
  return h(
    "div",
    { class: `local-down${compact ? " local-compact" : ""}`, role: "status", "data-local": "down" },
    h(
      "div",
      { class: "local-down-head" },
      icon("monitor"),
      h("div", null, h("strong", { text: t("local.down.title") }), h("p", { text: t("local.down.p") })),
    ),
    h(
      "ol",
      { class: "local-steps" },
      step(1, t("local.step1"), commandRow(LOCAL_CMDS.vllm)),
      step(2, t("local.step2"), commandRow(port === L.DEFAULT_PORT ? LOCAL_CMDS.bird : `${LOCAL_CMDS.bird} --port ${port}`)),
      step(3, t("local.step3")),
    ),
    h("p", { class: "local-perm", text: t("local.perm") }),
    h(
      "div",
      { class: "local-actions" },
      onRetry && button("btn-primary btn-small", "retry", t("local.retry"), onRetry, { "data-act": "local-retry" }),
      onOff && button("btn-outline btn-small", null, t("local.disconnect"), onOff, { "data-act": "local-off" }),
    ),
  );
}

// ------------------------------------------------------------------ Settings → Modèle → Bird local

/** Leave Bird local: the hosted model again. ``forget`` also removes the code from this browser. */
export function disconnect(onPrefs, { forget = false } = {}) {
  if (forget) localPair.forget();
  state.prefs.mode = "";
  state.localHealth = null;
  state.localPanel = false;
  savePrefs();
  toast(t(forget ? "local.toast.forgot" : "local.toast.off"), "ok");
  onPrefs?.();
}

/** The panel under the « Bird local » choice: connected, or the connect flow (search, code, three steps). */
export function localPanel({ onPrefs }) {
  const box = h("div", { class: "local-panel", id: "local-panel", "aria-live": "polite" });
  let found = null; // {base, health}

  const connected = () => {
    const lh = state.localHealth;
    const host = hostOf(lh?.base || localBase());
    box.replaceChildren(
      h(
        "div",
        { class: "local-ok", "data-local": "connected" },
        h("span", { class: "local-ok-mark", "aria-hidden": "true" }, icon("check")),
        h(
          "div",
          null,
          h("strong", { text: t("local.connected") }),
          h("p", { text: lh?.model ? t("local.connected.p", { host, model: lh.model }) : t("local.connected.wait", { host }) }),
        ),
      ),
      h(
        "div",
        { class: "local-actions" },
        button("btn-outline btn-small", null, t("local.disconnect"), () => disconnect(onPrefs), { "data-act": "local-off" }),
        button("btn-quiet btn-small", "trash", t("local.forget"), () => disconnect(onPrefs, { forget: true }), {
          "data-act": "local-forget",
        }),
      ),
    );
    if (!lh?.model) refreshLocal().then((got) => got && box.isConnected && connected());
  };

  const searching = () => {
    box.replaceChildren(h("p", { class: "local-searching", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), t("local.searching")));
  };

  const form = () => {
    const err = h("p", { class: "local-err", id: "local-code-err", role: "alert" });
    const input = h("input", {
      id: "local-code",
      type: "text",
      inputmode: "text",
      autocomplete: "one-time-code",
      autocapitalize: "characters",
      spellcheck: "false",
      maxlength: "12",
      placeholder: "ABCD-EFGH",
      value: localPair.get() || "",
      "aria-describedby": "local-code-hint local-code-err",
    });
    input.addEventListener("input", () => {
      const pos = input.value.length;
      const next = L.formatCode(input.value);
      if (next !== input.value && pos >= input.value.length) input.value = next;
      err.textContent = "";
      input.removeAttribute("aria-invalid");
    });
    const remember = h("input", { type: "checkbox", id: "local-remember", checked: localPair.remembered() });
    const go = h(
      "button",
      { class: "btn btn-primary", type: "submit", "data-act": "local-connect" },
      icon("monitor"),
      h("span", { class: "btn-label", text: t("local.connect") }),
    );
    const f = h(
      "form",
      { class: "local-form", novalidate: true },
      h("p", { class: "local-found", "data-local": "found" }, icon("check"), h("span", { text: t("local.found", { host: hostOf(found.base) }) })),
      h(
        "div",
        { class: "field" },
        h("label", { for: "local-code", text: t("local.code") }),
        input,
        h("p", { class: "hint", id: "local-code-hint", text: t("local.code.hint") }),
        err,
      ),
      h("label", { class: "check" }, remember, h("span", null, h("span", { class: "check-title", text: t("local.remember") }))),
      h("div", { class: "local-actions" }, go),
      h("p", { class: "tradeoff" }, icon("shield"), h("span", { text: t("local.privacy") })),
    );
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fail = (key) => {
        err.textContent = t(key);
        input.setAttribute("aria-invalid", "true");
        go.disabled = false;
        go.querySelector(".btn-label").textContent = t("local.connect");
        input.focus();
      };
      if (!L.codeShapeOk(input.value)) return fail("local.err.shape");
      go.disabled = true;
      go.querySelector(".btn-label").textContent = t("local.connecting");
      const out = await L.pair(globalThis.fetch, found.base, input.value);
      if (!out.ok) return fail(out.status === "locked" ? "local.err.locked" : out.status === "unreachable" ? "local.err.gone" : "local.err.invalid");
      localPair.set(input.value, remember.checked);
      state.prefs.mode = "local";
      state.prefs.localBase = found.base;
      state.localHealth = { ...out.info, energy: found.health?.energy, base: found.base };
      state.localPanel = false;
      savePrefs();
      toast(t("local.toast.paired"), "ok");
      onPrefs?.();
    });
    box.replaceChildren(f);
    if (!input.value) input.focus({ preventScroll: true });
  };

  const search = async () => {
    searching();
    const got = await L.probe(globalThis.fetch, localPort());
    if (!box.isConnected && got.status !== "found") return;
    if (got.status === "found") {
      found = got;
      form();
    } else if (got.status === "not_bird") {
      box.replaceChildren(
        h("p", { class: "local-err", role: "alert", text: t("local.notbird", { port: localPort() }) }),
        unreachableCard({ onRetry: search }),
      );
    } else box.replaceChildren(unreachableCard({ onRetry: search }));
  };

  if (activeMode() === "local" && localPair.get()) connected();
  else queueMicrotask(search);
  return box;
}

// ------------------------------------------------------------------ the page served by Bird local: pairing

/** On http://127.0.0.1:8765 without the code (opened by hand): ask for it once, in a small dialog. */
export function openPairDialog(onDone) {
  if ($("local-pair")) return;
  const err = h("p", { class: "local-err", id: "local-pair-err", role: "alert" });
  const input = h("input", {
    id: "local-pair-code",
    type: "text",
    autocomplete: "one-time-code",
    autocapitalize: "characters",
    spellcheck: "false",
    maxlength: "12",
    placeholder: "ABCD-EFGH",
    "aria-describedby": "local-pair-err",
  });
  const dlg = h(
    "dialog",
    { id: "local-pair", class: "local-dialog", "aria-labelledby": "local-pair-title" },
    h(
      "form",
      { method: "dialog", class: "local-form", novalidate: true },
      h("div", { class: "local-down-head" }, icon("monitor"), h("div", null,
        h("strong", { id: "local-pair-title", text: t("local.pair.title") }),
        h("p", { text: t("local.pair.p") }))),  // prettier-ignore
      h("div", { class: "field" }, h("label", { for: "local-pair-code", text: t("local.code") }), input, err),
      h("div", { class: "local-actions" }, h("button", { class: "btn btn-primary", type: "submit" }, h("span", { class: "btn-label", text: t("local.pair.go") }))),
    ),
  );
  dlg.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!L.codeShapeOk(input.value)) {
      err.textContent = t("local.err.shape");
      return;
    }
    const out = await L.pair(globalThis.fetch, location.origin, input.value);
    if (!out.ok) {
      err.textContent = t(out.status === "locked" ? "local.err.locked" : "local.err.invalid");
      input.focus();
      return;
    }
    localPair.set(input.value, false);
    dlg.close();
    dlg.remove();
    onDone?.();
  });
  dlg.addEventListener("cancel", (e) => e.preventDefault()); // nothing works without the code
  document.body.append(dlg);
  dlg.showModal();
  input.focus();
}

// ------------------------------------------------------------------ footprint

/** One line on the Empreinte page: in Bird local, energy is measured or estimated on the user's machine. */
export function footprintNote() {
  const local = activeMode() === "local" ? state.localHealth : onLocalOrigin() ? state.health?.bird_local : null;
  if (!local) return null;
  const measured = local.measured || state.health?.energy?.measured;
  return h("p", { class: "local-fp", "data-local": "footprint" }, icon("monitor"), h("span", { text: t(measured ? "local.fp.measured" : "local.fp.estimated") }));
}
