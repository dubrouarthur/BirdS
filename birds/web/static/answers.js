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

if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("copy", onCopy);
  document.addEventListener("click", onClick);
}
