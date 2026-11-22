// Shared pieces: state, storage, i18n, DOM helpers, icons, formatting, toasts.
import { makeT } from "./i18n.js";

export const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ storage (always optional)

export const store = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      if (value === null || value === undefined) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
      return true;
    } catch {
      return false; // private mode or quota: persistence is optional
    }
  },
  json(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key) ?? "null");
      return value ?? fallback;
    } catch {
      return fallback;
    }
  },
  keys(prefix) {
    try {
      return Object.keys(localStorage).filter((k) => k.startsWith(prefix));
    } catch {
      return [];
    }
  },
};

const DEFAULT_PREFS = { lang: "fr", theme: "system", thinking: true, thinkingV: 2, mode: "", endpoint: "", token: "", model: "", access: "", welcomed: false };

/** First visit (nothing stored): French when any of the browser's languages is French, English otherwise. */
function detectLang() {
  try {
    const list = navigator.languages?.length ? navigator.languages : [navigator.language || ""];
    return list.some((l) => /^fr/i.test(l || "")) ? "fr" : "en";
  } catch {
    return "fr";
  }
}
const storedPrefs = store.json("bird.prefs", null);

export const state = {
  prefs: { ...DEFAULT_PREFS, ...(storedPrefs?.lang ? {} : { lang: detectLang() }), ...(storedPrefs || {}) },
  health: null,
  convs: [], // index: [{id, title, created, updated, n}]
  conv: null, // the open conversation {id, title, created, updated, turns, attachments}
  view: "chat",
  thinking: true,
  busy: false,
  abort: null,
  online: typeof navigator === "undefined" ? true : navigator.onLine !== false,
  editing: false,
  seq: 0,
};
if (state.prefs.lang !== "en") state.prefs.lang = "fr";
// Reasoning became the default (v2). Prefs saved before kept the old default (false) without anyone choosing
// it: switch them on once; a choice made in Settings after that is kept.
if (storedPrefs && storedPrefs.thinkingV !== 2) {
  state.prefs.thinking = true;
  state.prefs.thinkingV = 2;
}
state.thinking = !!state.prefs.thinking;

export const t = makeT(() => state.prefs.lang);
export const savePrefs = () => store.set("bird.prefs", JSON.stringify(state.prefs));
if (storedPrefs && storedPrefs.thinkingV !== 2) savePrefs();
export const resetPrefs = () => (state.prefs = { ...DEFAULT_PREFS, lang: state.prefs.lang, welcomed: true });

/** The mode actually used for requests: the saved choice if this server offers it, else the server default. */
export function activeMode() {
  const modes = state.health?.modes || { demo: true };
  const wanted = state.prefs.mode;
  if (wanted && modes[wanted]) return wanted;
  return state.health?.default_mode || "demo";
}
export const isDemo = () => activeMode() === "demo";
/** The product name shown to people (the technical name served by the endpoint stays in the details). */
export const modelLabel = () => state.health?.model_label || "Bird S 4B";
export function activeModel() {
  const mode = activeMode();
  if (mode === "demo") return state.health?.demo_model || "bird-demo";
  if (mode === "user") return state.prefs.model || "adubrou/Bird-S-4B";
  return state.health?.model || "adubrou/Bird-S-4B";
}

// ------------------------------------------------------------------ DOM

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(3)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

// Icons are constants defined here, never model output.
const ICONS = {
  web_search: '<circle cx="9" cy="9" r="5.2"/><path d="M13 13l4 4"/>',
  read_page: '<circle cx="10" cy="10" r="6.5"/><path d="M3.5 10h13M10 3.5c2 2 2.8 4.2 2.8 6.5S12 14.500 10 16.500C8 14.500 7.200 12.300 7.200 10S8 5.500 10 3.500z"/>',
  read_file: '<path d="M5.500 3h6l3.500 3.500V17h-9.500z"/><path d="M11.500 3v3.500H15M8 10.500h4.500M8 13.500h4.500"/>',
  draft_email: '<rect x="3" y="5" width="14" height="10.500" rx="1.500"/><path d="M3.500 6.500l6.500 5 6.500-5"/>',
  make_slides: '<rect x="3" y="4" width="14" height="9" rx="1.200"/><path d="M10 13v3.500M7 16.500h6"/>',
  make_document: '<path d="M5.500 3h6l3.500 3.500V17h-9.500z"/><path d="M8 9h4.500M8 11.500h4.500M8 14h3"/>',
  make_sheet: '<rect x="3.500" y="4" width="13" height="12" rx="1.200"/><path d="M3.500 8h13M3.500 12h13M8 4v12"/>',
  make_chart: '<path d="M3.500 16.500h13"/><path d="M5.500 16.500V10.500M10 16.500V5M14.500 16.500V8.500" stroke-width="2.400"/>',
  run_python: '<rect x="4.500" y="3" width="11" height="14" rx="1.500"/><path d="M7.500 6.500h5M7.500 10.500h.01M10 10.500h.01M12.500 10.500h.01M7.500 13.500h.01M10 13.500h.01M12.500 13.500h.01"/>',
  tool: '<circle cx="10" cy="10" r="2.200"/><circle cx="10" cy="10" r="6.500"/>',
  check: '<path d="M4.500 10.500l3.500 3.500 7.500-8"/>',
  cross: '<path d="M5.500 5.500l9 9M14.500 5.500l-9 9"/>',
  ban: '<circle cx="10" cy="10" r="6.500"/><path d="M5.500 14.500l9-9"/>',
  alert: '<path d="M10 3.500l7 12.500H3z"/><path d="M10 8.500v3.500M10 14.200h.01"/>',
  shield: '<path d="M10 3l6 2.200v4.300c0 3.600-2.400 6.300-6 7.500-3.600-1.200-6-3.900-6-7.500V5.200z"/><path d="M7.500 10l1.800 1.800 3.200-3.600"/>',
  download: '<path d="M10 3.500v9M6 9l4 4 4-4M4 16.500h12"/>',
  copy: '<rect x="7" y="7" width="9.500" height="9.500" rx="1.500"/><path d="M13 7V5a1.500 1.500 0 0 0-1.500-1.500H5A1.500 1.500 0 0 0 3.500 5v6.500A1.500 1.500 0 0 0 5 13h2"/>',
  markdown: '<rect x="2.500" y="5" width="15" height="10" rx="1.500"/><path d="M5.500 12.500v-5l2.200 2.600 2.200-2.600v5M13.800 7.500v5M11.800 10.700l2 2 2-2"/>',
  leaf: '<path d="M4 16c0-6.500 4.200-11 12-12 .2 7.600-3.600 12-9.600 12.400M4 16.600C6 12.500 8.600 10 12 8.200"/>',
  chevron: '<path d="M7.500 5l5 5-5 5"/>',
  down: '<path d="M10 4v12M5 11l5 5 5-5"/>',
  file: '<path d="M5.500 3h6l3.500 3.500V17h-9.500z"/><path d="M11.500 3v3.500H15"/>',
  retry: '<path d="M4.500 10a5.500 5.500 0 1 0 1.800-4.100M4.500 4v3h3"/>',
  edit: '<path d="M4 16l.600-3.200L13.500 4l2.500 2.500-8.800 8.800z"/><path d="M12 5.500L14.500 8"/>',
  up: '<path d="M6.500 9.500l3-6c1.200.200 1.800 1 1.600 2.200L10.700 8h4.100c1 0 1.700.900 1.500 1.900l-1 4.800c-.200.800-.800 1.300-1.600 1.300H6.500z"/><path d="M6.500 9.500h-3v6.500h3"/>',
  thumbdown: '<path d="M13.500 10.500l-3 6c-1.200-.200-1.800-1-1.600-2.200L9.300 12H5.200c-1 0-1.700-.900-1.500-1.900l1-4.800C4.900 4.500 5.500 4 6.300 4h7.200z"/><path d="M13.500 10.500h3V4h-3"/>',
  mail: '<path d="M11 4h5v5M16 4l-7 7"/><path d="M14 11.500V15a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h3.500"/>',
  clip: '<path d="M14.500 9.500l-5 5a3 3 0 0 1-4.200-4.200l6-6a2 2 0 0 1 2.800 2.800l-5.800 5.800a1 1 0 0 1-1.400-1.400l5-5"/>',
  plus: '<path d="M10 4v12M4 10h12"/>',
  search: '<circle cx="9" cy="9" r="5.200"/><path d="M13 13l4 4"/>',
  more: '<path d="M5 10h.01M10 10h.01M15 10h.01"/>',
  trash: '<path d="M4.500 6h11M8 6V4.200h4V6M6 6l.700 10h6.600L14 6M8.500 9v4.500M11.500 9v4.500"/>',
  gear: '<circle cx="10" cy="10" r="2.400"/><path d="M10 3v2M10 15v2M3 10h2M15 10h2M5.100 5.100l1.400 1.400M13.500 13.500l1.400 1.400M5.100 14.900l1.400-1.400M13.500 6.500l1.400-1.400"/>',
  info: '<circle cx="10" cy="10" r="6.500"/><path d="M10 9.200v4M10 6.600h.01"/>',
  keyboard: '<rect x="2.500" y="5.500" width="15" height="9" rx="1.500"/><path d="M5.500 8.500h.01M8.500 8.500h.01M11.500 8.500h.01M14.500 8.500h.01M6.500 11.500h7"/>',
  menu: '<path d="M3.500 6h13M3.500 10h13M3.500 14h13"/>',
  back: '<path d="M11.500 5l-5 5 5 5M7 10h9"/>',
  send: '<path d="M10 16V4.500M5 9.200l5-5 5 5"/>',
  pause: '<path d="M7.500 5v10M12.500 5v10"/>',
  stop: '<rect class="fill" x="5.500" y="5.500" width="9" height="9" rx="1.500"/>',
  eye: '<path d="M2.500 10S5.300 5 10 5s7.500 5 7.500 5-2.800 5-7.500 5-7.500-5-7.500-5z"/><circle cx="10" cy="10" r="2.200"/>',
  spark: '<path d="M10 3l1.600 4.400L16 9l-4.400 1.600L10 15l-1.600-4.400L4 9l4.400-1.600z"/>',
  image: '<rect x="3" y="4" width="14" height="12" rx="1.600"/><circle cx="7.500" cy="8.300" r="1.400"/><path d="M3.500 14.500l4-4 3 3 2.500-2.500 3.500 3.500"/>',
  read_image: '<rect x="3" y="4" width="14" height="12" rx="1.600"/><circle cx="7.500" cy="8.300" r="1.400"/><path d="M3.500 14.500l4-4 3 3 2.500-2.500 3.500 3.500"/>',
  camera: '<path d="M3 7.2c0-.9.7-1.6 1.6-1.6h2l1.2-1.800h4.400l1.200 1.800h2c.900 0 1.600.700 1.600 1.600v7.200c0 .900-.700 1.600-1.600 1.600H4.600c-.900 0-1.600-.700-1.600-1.600z"/><circle cx="10" cy="10.600" r="3"/>',
  word: '<path d="M5.500 3h6l3.500 3.500V17h-9.500z"/><path d="M11.500 3v3.500H15M7.500 9.500l1 4 1.500-3 1.500 3 1-4"/>',
  moon: '<path d="M16 11.600A6.600 6.600 0 0 1 8.400 4a6.600 6.600 0 1 0 7.600 7.600z"/>',
};

export function icon(name, cls = "") {
  const wrap = document.createElement("span");
  wrap.innerHTML = `<svg class="icon ${cls}" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${ICONS[name] || ICONS.tool}</svg>`;
  return wrap.firstChild;
}

export function button(cls, iconName, label, onclick, extra = {}) {
  const iconOnly = cls.includes("btn-icon");
  return h(
    "button",
    { class: `btn ${cls}`, type: "button", onclick, "aria-label": iconOnly ? label : null, title: iconOnly ? label : null, ...extra },
    iconName && icon(iconName),
    !iconOnly && h("span", { class: "btn-label", text: label }),
  );
}

// ------------------------------------------------------------------ formatting

const nf = (options) => new Intl.NumberFormat(state.prefs.lang === "en" ? "en-GB" : "fr-FR", options);
export const fmtInt = (n) => nf({ maximumFractionDigits: 0 }).format(n || 0);
export const fmtSeconds = (s) => `${nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(s || 0)} ${t("unit.s")}`;
export const fmtSig = (v) => nf({ maximumSignificantDigits: 3 }).format(v);

export function fmtBytes(bytes) {
  if (!bytes) return `0 ${t("unit.kb")}`;
  if (bytes < 1000) return `${fmtInt(bytes)} ${t("unit.b")}`;
  if (bytes < 1e6) return `${nf({ maximumFractionDigits: bytes < 1e4 ? 1 : 0 }).format(bytes / 1000)} ${t("unit.kb")}`;
  return `${nf({ maximumFractionDigits: 1 }).format(bytes / 1e6)} ${t("unit.mb")}`;
}

export const hasEnergy = (u) => !!u && typeof u.energy_wh === "number" && (u.energy_kind === "measured" || u.energy_kind === "estimated");
export const fmtEnergy = (wh, kind) => `${kind === "estimated" ? "≈ " : ""}${fmtSig(wh)} Wh`;
export const fmtCo2 = (g) => `≈ ${fmtSig(g)} g CO₂e`;
export const toolLabel = (tool) => {
  const key = `tool.${tool}`;
  const label = t(key);
  return label === key ? String(tool) : label;
};
export function fmtDate(ts) {
  try {
    return new Intl.DateTimeFormat(state.prefs.lang === "en" ? "en-GB" : "fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(ts));
  } catch {
    return "";
  }
}

// ------------------------------------------------------------------ feedback to the user

export function announce(text) {
  const live = $("live");
  live.textContent = "";
  window.setTimeout(() => (live.textContent = text), 30);
}

/** A short message. `action` ({label, run}) adds one button (e.g. "Annuler"); `ms` overrides how long it stays. */
export function toast(text, kind = "info", { action, ms } = {}) {
  const host = $("toasts");
  for (const old of [...host.children]) if (old.dataset.text === text && !old.classList.contains("toast-out")) old.remove(); // the same message once
  const el = h(
    "div",
    { class: `toast toast-${kind}${action ? " has-action" : ""}`, role: kind === "error" ? "alert" : "status", "data-text": text },
    icon(kind === "error" ? "alert" : kind === "ok" ? "check" : "info"),
    h("span", { text }),
  );
  const close = () => {
    el.classList.add("toast-out");
    window.setTimeout(() => el.remove(), 250);
  };
  if (action)
    el.append(
      h("button", {
        class: "toast-action",
        type: "button",
        text: action.label,
        onclick: () => {
          close();
          action.run();
        },
      }),
    );
  host.append(el);
  while (host.children.length > 3) host.firstChild.remove();
  window.setTimeout(close, ms || (kind === "error" ? 6000 : 2600));
  return el;
}

export async function copyText(text, message) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = h("textarea", { class: "sr-only", "aria-hidden": "true", tabindex: "-1" });
    area.value = text;
    document.body.append(area);
    area.select();
    try {
      document.execCommand("copy");
    } catch {
      /* nothing else to try */
    }
    area.remove();
  }
  toast(message || t("toast.copied"), "ok");
}

/** Offer bytes as a download through a Blob URL (no server round trip, nothing leaves the browser). */
export function download(name, mime, data) {
  const blob = data instanceof Blob ? data : new Blob([data], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name, class: "sr-only", tabindex: "-1" });
  document.body.append(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export const uid = (prefix) => `${prefix}${Date.now().toString(36)}${(state.seq++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;
