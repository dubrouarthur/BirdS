// The answer content beyond Markdown (cluster C2 of the chat audit): typeset math, citation bubbles and the sources
// pill, rich copy (text/html + text/plain), the thumbs-down reasons, the work line. Strings: answers-i18n.js.
//
// Math: markdown.js leaves a placeholder per formula (data-tex, its source as written). typeset() loads the
// self-hosted KaTeX (static/vendor/katex, MIT, licence in « À propos ») the first time an answer has one, renders
// every placeholder in place and keeps the source for copying. The page's CSP forbids inline style attributes, so
// KaTeX's are moved to data-kx-style and applied through the CSSOM. Nothing is fetched from a third party.
import { copyText, t } from "./core.js";

export const KATEX = "/static/vendor/katex/katex.min.js";
export const KATEX_CSS = "/static/vendor/katex/katex.min.css";

/** KaTeX's HTML for one formula, its inline styles moved to data-kx-style (applied by applyStyles). Throws on bad TeX. */
export function katexHtml(katex, tex, display) {
  const html = katex.renderToString(String(tex), {
    displayMode: Boolean(display),
    throwOnError: true,
    strict: "ignore",
    trust: false, // no \href, \url, \htmlClass…: a formula never makes a link or an attribute
    output: "htmlAndMathml", // MathML for screen readers, HTML for the eye
    maxSize: 20,
    maxExpand: 300,
  });
  return html.replace(/ style="([^"]*)"/g, ' data-kx-style="$1"');
}

function applyStyles(root) {
  for (const el of root.querySelectorAll("[data-kx-style]")) {
    el.style.cssText = el.getAttribute("data-kx-style");
    el.removeAttribute("data-kx-style");
  }
}

let loading = null;
function loadKatex() {
  if (globalThis.katex?.renderToString) return Promise.resolve(globalThis.katex);
  if (!loading) {
    if (!document.querySelector(`link[href="${KATEX_CSS}"]`))
      document.head.append(Object.assign(document.createElement("link"), { rel: "stylesheet", href: KATEX_CSS }));
    // the UMD build sets self.katex when imported as a module
    loading = import(KATEX).then(
      () => globalThis.katex || null,
      () => ((loading = null), null), // offline or blocked: the formulas stay as written, retried next time
    );
  }
  return loading;
}

/** Typeset every formula placeholder under root (idempotent: a typeset formula is left alone). */
export async function typeset(root) {
  const nodes = [...root.querySelectorAll(".md-math:not([data-typeset]):not([data-pending])")];
  if (!nodes.length) return 0;
  const katex = await loadKatex();
  if (!katex) return 0;
  let done = 0;
  for (const el of nodes) {
    if (!el.isConnected || el.hasAttribute("data-typeset")) continue;
    try {
      const out = document.createElement("span");
      out.className = "md-math-out";
      out.innerHTML = katexHtml(katex, el.dataset.tex, el.hasAttribute("data-display"));
      applyStyles(out);
      el.prepend(out);
      el.dataset.typeset = "1";
      done += 1;
    } catch {
      // TeX KaTeX does not know: shown as written, never a red error in the answer
      el.dataset.typeset = "raw";
      el.title = t("md.math.raw");
    }
  }
  return done;
}

/** The TeX of a formula placeholder as the reader copies it: delimiters included. */
export function texOf(el) {
  const tex = el.getAttribute("data-tex") || "";
  return el.hasAttribute("data-display") ? `$$${tex}$$` : `$${tex}$`;
}

/**
 * A copied selection that holds formulas gives their TeX, never KaTeX's glyph soup (« 6CO2​+6H2​O »). A selection
 * inside one formula copies the whole formula.
 */
function onCopy(e) {
  const sel = globalThis.getSelection?.();
  if (!sel || sel.isCollapsed || !sel.rangeCount || !e.clipboardData) return;
  const range = sel.getRangeAt(0);
  const node = range.commonAncestorContainer;
  const within = (node.nodeType === 1 ? node : node.parentElement)?.closest?.(".md-math[data-typeset]");
  if (within) {
    e.clipboardData.setData("text/plain", texOf(within));
    e.preventDefault();
    return;
  }
  const frag = range.cloneContents();
  const maths = frag.querySelectorAll(".md-math");
  if (!maths.length) return;
  for (const m of maths) m.replaceWith(document.createTextNode(texOf(m)));
  const box = document.createElement("div");
  box.className = "md-copy-box";
  box.append(frag);
  document.body.append(box);
  const text = box.innerText;
  const html = box.innerHTML;
  box.remove();
  e.clipboardData.setData("text/plain", text);
  e.clipboardData.setData("text/html", html);
  e.preventDefault();
}

function onClick(e) {
  const btn = e.target.closest?.("[data-copy-tex]");
  if (!btn) return;
  const el = btn.closest(".md-math");
  if (el) copyText(texOf(el), t("md.math.copied"));
}

// ------------------------------------------------------------------ citations: the bubble and the sources panel

/** Open or close the « N sources » panel that a pill controls. */
export function setSourcesOpen(pill, open) {
  const panel = pill && document.getElementById(pill.getAttribute("aria-controls"));
  if (!panel) return;
  pill.setAttribute("aria-expanded", String(open));
  panel.hidden = !open;
  pill.closest(".sources")?.classList.toggle("is-open", open);
}

/** What the bubble of citation [n] says, read from the source card it points to (never from the model's text). */
export function citeFacts(item) {
  const link = item.querySelector(".source-body > a");
  const title = (link || item.querySelector(".source-body > span"))?.textContent?.trim() || "";
  return {
    n: item.querySelector(".source-n")?.textContent?.trim() || "",
    title,
    url: link?.href || "",
    host: item.querySelector(".source-host > span:not(.source-mono):not(.badge)")?.textContent?.trim() || "",
    snippet: item.querySelector(".source-snippet")?.textContent?.trim() || "",
  };
}

let bubble = null; // {el, anchor}
let hideTimer = 0;

function hideBubble(refocus = false) {
  clearTimeout(hideTimer);
  if (!bubble) return;
  const { el, anchor } = bubble;
  anchor.removeAttribute("aria-describedby");
  anchor.setAttribute("aria-expanded", "false");
  el.remove();
  bubble = null;
  if (refocus) anchor.focus();
}

function place(el, anchor) {
  const r = anchor.getBoundingClientRect();
  const w = Math.min(320, innerWidth - 24);
  el.style.width = `${w}px`;
  const left = Math.min(Math.max(12, r.left + r.width / 2 - w / 2), innerWidth - w - 12);
  const h = el.offsetHeight;
  const above = r.top - h - 8 >= 12;
  el.style.left = `${left}px`;
  el.style.top = `${above ? r.top - h - 8 : Math.min(r.bottom + 8, innerHeight - h - 12)}px`;
  el.dataset.side = above ? "above" : "below";
}

function showBubble(anchor) {
  const item = document.getElementById(decodeURIComponent((anchor.getAttribute("href") || "").slice(1)));
  if (!item) return;
  if (bubble?.anchor === anchor) return;
  hideBubble();
  const f = citeFacts(item);
  const el = document.createElement("div");
  el.className = "cite-bubble";
  el.id = `cb-${item.id}`;
  el.setAttribute("role", "tooltip");
  const head = document.createElement("p");
  head.className = "cite-bubble-host";
  head.textContent = `${f.n} · ${f.host}`.replace(/^ · /, "");
  const title = document.createElement(f.url ? "a" : "p");
  title.className = "cite-bubble-title";
  title.textContent = f.title;
  if (f.url) Object.assign(title, { href: f.url, target: "_blank", rel: "noopener noreferrer", referrerPolicy: "no-referrer" });
  el.append(head, title);
  if (f.snippet) {
    const p = document.createElement("p");
    p.className = "cite-bubble-snippet";
    p.textContent = f.snippet;
    el.append(p);
  }
  const all = document.createElement("button");
  all.type = "button";
  all.className = "cite-bubble-all";
  all.textContent = t("src.bubble.all");
  all.addEventListener("click", () => {
    const pill = item.closest(".sources")?.querySelector(".src-pill");
    if (pill) setSourcesOpen(pill, true);
    hideBubble();
    item.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    item.focus({ preventScroll: true });
  });
  el.append(all);
  el.addEventListener("pointerenter", () => clearTimeout(hideTimer));
  el.addEventListener("pointerleave", () => !bubble?.pinned && (hideTimer = setTimeout(hideBubble, 250)));
  document.body.append(el);
  place(el, anchor);
  anchor.setAttribute("aria-describedby", el.id);
  anchor.setAttribute("aria-expanded", "true");
  bubble = { el, anchor };
}

const citeOf = (target) => target?.closest?.("sup.cite > a");

function onCiteClick(e) {
  const a = citeOf(e.target);
  if (a) {
    // a tap (or a click) opens the bubble instead of jumping to a list that is folded
    e.preventDefault();
    // a second click closes the bubble that the first one pinned; a bubble opened by hover or focus stays
    if (bubble?.anchor === a && bubble.pinned) hideBubble();
    else {
      showBubble(a);
      if (bubble) bubble.pinned = true;
    }
    return;
  }
  if (bubble && !bubble.el.contains(e.target)) hideBubble();
}

if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("copy", onCopy);
  document.addEventListener("click", onClick);
  document.addEventListener("click", onCiteClick);
  const fine = () => matchMedia("(hover: hover) and (pointer: fine)").matches;
  document.addEventListener("pointerover", (e) => {
    const a = citeOf(e.target);
    if (a && fine()) {
      clearTimeout(hideTimer);
      showBubble(a);
    }
  });
  document.addEventListener("pointerout", (e) => {
    const a = citeOf(e.target);
    if (a && bubble?.anchor === a && !bubble.pinned && fine() && !bubble.el.contains(e.relatedTarget))
      hideTimer = setTimeout(hideBubble, 250);
  });
  document.addEventListener("focusin", (e) => {
    const a = citeOf(e.target);
    if (a) showBubble(a);
    else if (bubble && !bubble.el.contains(e.target)) hideBubble();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && bubble) {
      e.stopPropagation();
      hideBubble(true);
    }
  }, true);
  // the bubble follows its mark while the conversation scrolls, and goes when the mark leaves the screen
  addEventListener(
    "scroll",
    () => {
      if (!bubble) return;
      const r = bubble.anchor.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight) hideBubble();
      else place(bubble.el, bubble.anchor);
    },
    true,
  );
  addEventListener("resize", () => bubble && hideBubble());
}
