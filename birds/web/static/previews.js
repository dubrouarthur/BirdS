// Previews of generated files, drawn from what the file really holds (the server reads the written file):
// a deck as its slides (shapes on a 1280 x 720 canvas, scaled with container units), a document as an A4 page,
// a sheet as its styled table. Model text only ever goes through textContent; geometry goes through the CSSOM.
import { button, h, t } from "./core.js";

const HEX = /^[0-9A-Fa-f]{6}$/;
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
const color = (v, d) => (HEX.test(String(v || "")) ? `#${v}` : d);
const px = (el, prop, v) =>
  el.style.setProperty(prop, `calc(var(--px) * ${num(v)})`);

// Calibri, or its metric twin Carlito, sets the line breaks of the real file; without either the fallback face is
// wider, so the text is drawn a little smaller to keep the same breaks (checked once per page).
let narrow = null;
function hasCalibri() {
  if (narrow !== null) return narrow;
  try {
    const c = document.createElement("canvas").getContext("2d");
    const w = (f) => (
      (c.font = `40px ${f}`),
      c.measureText("Mesurez l'espace des lettres 0123").width
    );
    narrow = ["Carlito", "Calibri"].some(
      (f) => w(`${f}, monospace`) !== w("monospace"),
    );
  } catch {
    narrow = true;
  }
  return narrow;
}

function para(p, heading) {
  const runs = Array.isArray(p.r) ? p.r : [];
  const el = h(heading ? "h4" : "p", { class: "sh-p" });
  const first = runs[0] || {};
  el.style.lineHeight = String(1.2207 * (num(p.ls) || 1));
  // the paragraph's own size sets the strut of each line: the largest run, as in the file (not the page's 16px)
  const size = Math.max(...runs.map((r) => num(r.s) || 18), 1);
  el.style.setProperty("font-size", `calc(var(--pt) * ${size})`);
  if (p.al === "ctr") el.style.textAlign = "center";
  else if (p.al === "r") el.style.textAlign = "right";
  if (p.sb)
    el.style.setProperty(
      "margin-block-start",
      `calc(var(--px) * ${num(p.sb) * 1.3333})`,
    );
  if (p.sa)
    el.style.setProperty(
      "margin-block-end",
      `calc(var(--px) * ${num(p.sa) * 1.3333})`,
    );
  if (p.bu) {
    px(el, "padding-inline-start", p.bu.m);
    px(el, "text-indent", p.bu.i);
    const b = h("span", {
      class: "sh-bu",
      "aria-hidden": "true",
      text: String(p.bu.ch || "•"),
    });
    px(b, "inline-size", -num(p.bu.i));
    b.style.color = color(p.bu.c, "#1e5bd8");
    b.style.setProperty("font-size", `calc(var(--pt) * ${num(first.s) || 18})`);
    el.append(b);
  }
  for (const r of runs) {
    const s = h("span", { text: String(r.t ?? "") });
    s.style.setProperty("font-size", `calc(var(--pt) * ${num(r.s) || 18})`);
    s.style.color = color(r.c, "#121a2e");
    if (r.b) s.style.fontWeight = "700";
    if (r.k)
      s.style.setProperty("letter-spacing", `calc(var(--pt) * ${num(r.k)})`);
    el.append(s);
  }
  return el;
}

/** One slide, drawn from its shapes. `live`: the big stage (real headings); thumbnails are decorative. */
export function slideCanvas(slide, live) {
  const canvas = h("div", {
    class: `slide-canvas${hasCalibri() ? "" : " no-calibri"}`,
  });
  for (const sh of Array.isArray(slide.shapes) ? slide.shapes : []) {
    const el = h("div", {
      class: `sh sh-${sh.g === "o" ? "o" : sh.g === "rr" ? "rr" : "r"}`,
    });
    px(el, "left", sh.x);
    px(el, "top", sh.y);
    px(el, "width", sh.w);
    px(el, "height", sh.h);
    if (sh.f) el.style.background = color(sh.f, "transparent");
    if (sh.g === "rr") px(el, "border-radius", num(sh.h) / 2);
    if (Array.isArray(sh.p)) {
      el.classList.add(`sh-a${sh.a === "m" ? "m" : sh.a === "b" ? "b" : "t"}`);
      sh.p.forEach((p, i) => el.append(para(p, live && sh.ti && i === 0)));
    }
    canvas.append(el);
  }
  return canvas;
}

/** A deck: one big slide at a time, controls, counter, filmstrip of exact miniatures, full-screen view. */
export function deckPreview(p, { onDownload, full = false } = {}) {
  const slides = (Array.isArray(p.slides) ? p.slides : []).filter(
    (s) => s && Array.isArray(s.shapes),
  );
  if (!slides.length) return null;
  const total = num(p.total) || slides.length;
  let at = 0;
  const stage = h("div", {
    class: "deck-stage",
    tabindex: "0",
    "aria-roledescription": t("files.deck.slide"),
  });
  const counter = h("p", {
    class: "deck-count num",
    "aria-live": "polite",
    "aria-atomic": "true",
  });
  const film = h("ol", {
    class: "deck-film",
    "aria-label": t("files.deck.film"),
  });
  const prev = button(
    "btn-icon btn-ghost deck-prev",
    "chevron",
    t("files.deck.prev"),
    () => go(at - 1),
  );
  const next = button(
    "btn-icon btn-ghost deck-next",
    "chevron",
    t("files.deck.next"),
    () => go(at + 1),
  );
  const thumbs = slides.map((s, i) => {
    const b = h(
      "button",
      {
        type: "button",
        class: "deck-thumb",
        "aria-label": t("files.deck.goto", {
          n: s.n || i + 1,
          title: s.title || "",
        }),
        onclick: () => go(i),
      },
      h(
        "span",
        { class: "slide-frame", "aria-hidden": "true" },
        slideCanvas(s, false),
      ),
      h("span", {
        class: "deck-thumb-n num",
        "aria-hidden": "true",
        text: String(s.n || i + 1),
      }),
    );
    film.append(h("li", null, b));
    return b;
  });
  function go(i) {
    at = Math.max(0, Math.min(slides.length - 1, i));
    const s = slides[at];
    const frame = h("div", { class: "slide-frame" }, slideCanvas(s, true));
    stage.replaceChildren(frame);
    stage.setAttribute(
      "aria-label",
      t("files.deck.goto", { n: s.n || at + 1, title: s.title || "" }),
    );
    counter.textContent = `${s.n || at + 1} / ${total}`;
    prev.disabled = at === 0;
    next.disabled = at === slides.length - 1;
    thumbs.forEach((b, j) =>
      j === at
        ? b.setAttribute("aria-current", "true")
        : b.removeAttribute("aria-current"),
    );
    const th = thumbs[at];
    if (th && film.scrollWidth > film.clientWidth) {
      film.scrollTo({
        left: th.offsetLeft - (film.clientWidth - th.offsetWidth) / 2,
        behavior: "smooth",
      });
    }
  }
  const keys = (e) => {
    if (e.key === "ArrowRight" || e.key === "PageDown") go(at + 1);
    else if (e.key === "ArrowLeft" || e.key === "PageUp") go(at - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(slides.length - 1);
    else return;
    e.preventDefault();
  };
  // swipe with one finger; two fingers are a pinch zoom, never a slide change
  let x0 = null;
  let fingers = 0;
  stage.addEventListener("pointerdown", (e) => {
    fingers += e.pointerType === "touch" ? 1 : 0;
    x0 = e.pointerType === "mouse" || fingers > 1 ? null : e.clientX;
  });
  const lift = (e) => (fingers = Math.max(0, fingers - (e.pointerType === "touch" ? 1 : 0)));
  stage.addEventListener("pointercancel", (e) => ((x0 = null), lift(e)));
  stage.addEventListener("pointerup", (e) => {
    if (x0 !== null && fingers === 1 && Math.abs(e.clientX - x0) > 40)
      go(at + (e.clientX < x0 ? 1 : -1));
    x0 = null;
    lift(e);
  });
  const root = h(
    "section",
    {
      class: `deck${full ? " deck-full" : ""}`,
      "aria-roledescription": t("files.deck.role"),
      "aria-label": t("files.deck.label", { title: p.title || "" }),
      onkeydown: keys,
    },
    stage,
    h(
      "div",
      { class: "deck-bar" },
      prev,
      counter,
      next,
      h("span", { class: "deck-gap" }),
      !full &&
        button("btn-icon btn-ghost", "expand", t("files.deck.full"), () =>
          openFull(p, at, onDownload),
        ),
      onDownload &&
        button(
          "btn-icon btn-ghost",
          "download",
          t("files.download"),
          onDownload,
        ),
    ),
    film,
  );
  root.go = go;
  go(0);
  return root;
}

// a phone or a short window: the full-screen view is the whole screen (edge to edge, real full screen and
// landscape where the browser allows it), so it is never smaller than the slide in the chat
const SMALL = "(max-width: 700px), (max-height: 500px)";

function openFull(p, at, onDownload) {
  const deck = deckPreview(p, { onDownload, full: true });
  const close = button(
    "btn-icon btn-ghost deck-close",
    "cross",
    t("files.deck.close"),
    () => dlg.close(),
  );
  const dlg = h(
    "dialog",
    {
      class: "deck-dialog",
      "aria-label": t("files.deck.label", { title: p.title || "" }),
    },
    close,
    deck,
    h("p", { class: "deck-rotate", text: t("files.deck.rotate") }),
  );
  let fs = false;
  dlg.addEventListener("close", () => {
    if (fs && document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    try {
      screen.orientation?.unlock?.();
    } catch {
      /* not supported */
    }
    dlg.remove();
  });
  dlg.addEventListener("click", (e) => e.target === dlg && dlg.close());
  // leaving the browser's full screen (Esc, back gesture) leaves the view too
  document.addEventListener("fullscreenchange", function off() {
    if (document.fullscreenElement) return;
    document.removeEventListener("fullscreenchange", off);
    if (fs && dlg.open) dlg.close();
  });
  document.body.append(dlg);
  dlg.showModal();
  deck.go(at);
  deck.querySelector(".deck-stage").focus();
  if (window.matchMedia?.(SMALL).matches && document.documentElement.requestFullscreen) {
    document.documentElement
      .requestFullscreen({ navigationUI: "hide" })
      .then(() => {
        fs = true;
        return screen.orientation?.lock?.("landscape");
      })
      .catch(() => {});
  }
}

// ------------------------------------------------------------------ document: an A4 page

const runsOf = (el, runs) => {
  for (const r of Array.isArray(runs) ? runs : []) {
    const text = String(r?.[0] ?? "");
    el.append(
      r?.[2] ? h("code", { text }) : r?.[1] ? h("strong", { text }) : text,
    );
  }
  return el;
};

export function docPreview(p) {
  const page = h("div", { class: "a4" });
  let list = null;
  for (const b of Array.isArray(p.blocks) ? p.blocks : []) {
    if (!b || typeof b !== "object") continue;
    if (b.k !== "li") list = null;
    if (b.k === "title")
      page.append(runsOf(h("h4", { class: "a4-title" }), b.r));
    else if (b.k === "subtitle")
      page.append(runsOf(h("p", { class: "a4-sub" }), b.r));
    else if (b.k === "h")
      page.append(
        runsOf(
          h(`h${Math.min(6, 4 + num(b.l))}`, {
            class: `a4-h${Math.min(3, num(b.l) || 1)}`,
          }),
          b.r,
        ),
      );
    else if (b.k === "li") {
      const ordered = Number.isFinite(b.n);
      const li = runsOf(
        h("li", { class: `a4-l${Math.min(2, num(b.l))}` }),
        b.r,
      );
      if (ordered) li.dataset.n = `${b.n}.`;
      if (!list || list.ordered !== ordered) {
        list = h(ordered ? "ol" : "ul", { class: "a4-list" });
        list.ordered = ordered;
        page.append(list);
      }
      list.append(li);
    } else if (b.k === "callout")
      page.append(
        runsOf(
          h("p", {
            class: `a4-callout a4-${b.c === "decision" ? "decision" : "action"}`,
          }),
          b.r,
        ),
      );
    else if (b.k === "quote")
      page.append(runsOf(h("blockquote", { class: "a4-quote" }), b.r));
    else if (b.k === "code")
      page.append(h("pre", { class: "a4-code", text: String(b.t || "") }));
    else if (b.k === "rule") page.append(h("hr", { class: "a4-rule" }));
    else if (b.k === "table") page.append(docTable(b));
    else if (b.k === "p") page.append(runsOf(h("p", { class: "a4-p" }), b.r));
  }
  const wrap = h(
    "div",
    { class: "a4-wrap is-clipped" },
    h(
      "div",
      { class: "a4-scroll", tabindex: "0", "aria-label": t("files.preview") },
      page,
    ),
  );
  const more = button(
    "btn-ghost btn-small a4-more",
    "down",
    t("files.doc.all"),
    () => {
      wrap.classList.remove("is-clipped");
      more.remove();
    },
  );
  wrap.append(more);
  return wrap;
}

function docTable(b) {
  const rows = Array.isArray(b.rows) ? b.rows : [];
  const table = h("table", { class: "a4-table" });
  let zebra = 0;
  rows.forEach((row, i) => {
    const tr = h("tr", {
      class:
        i === 0
          ? ""
          : row.total
            ? "is-total"
            : ++zebra % 2 === 0
              ? "is-zebra"
              : "",
    });
    for (const c of Array.isArray(row.c) ? row.c : []) {
      tr.append(
        h(i === 0 ? "th" : "td", {
          class: c?.[1] ? "num" : "",
          text: String(c?.[0] ?? ""),
          scope: i === 0 ? "col" : null,
        }),
      );
    }
    (i === 0
      ? table.appendChild(h("thead"))
      : table.tBodies[0] || table.appendChild(h("tbody"))
    ).append(tr);
  });
  return h(
    "div",
    { class: "a4-table-wrap" },
    table,
    b.more > 0 &&
      h("p", { class: "a4-hint", text: t("files.more.rows", { n: b.more }) }),
  );
}

// ------------------------------------------------------------------ sheet: the styled table

export function sheetPreview(p) {
  const kinds = Array.isArray(p.kinds) ? p.kinds : [];
  const widths = Array.isArray(p.widths) ? p.widths : [];
  const cls = (j) =>
    kinds[j] === "num" ? "num" : kinds[j] === "date" ? "date" : "";
  const colgroup = h(
    "colgroup",
    null,
    (p.columns || []).map((_, j) => {
      const col = h("col");
      col.style.inlineSize = `${Math.max(6, Math.min(50, num(widths[j]) || 10)) * 0.62}em`;
      return col;
    }),
  );
  const body = h("tbody");
  let last = -1;
  for (const row of Array.isArray(p.rows) ? p.rows : []) {
    if (num(row.i) > last + 1)
      body.append(
        h(
          "tr",
          { class: "is-gap" },
          h("td", {
            colspan: String((p.columns || []).length || 1),
            text: "⋯",
          }),
        ),
      );
    last = num(row.i);
    const tr = h("tr", {
      class:
        row.t === 2
          ? "is-grand"
          : row.t === 1
            ? "is-total"
            : num(row.i) % 2 === 1
              ? "is-zebra"
              : "",
    });
    (Array.isArray(row.c) ? row.c : []).forEach((c, j) =>
      tr.append(
        h("td", {
          class: cls(j),
          text: String(c ?? ""),
          title: String(c ?? ""),
        }),
      ),
    );
    body.append(tr);
  }
  const more = num(p.total_rows) - (p.rows || []).length;
  return h(
    "div",
    { class: "xl" },
    h(
      "div",
      { class: "xl-scroll", tabindex: "0", "aria-label": t("files.preview") },
      h(
        "table",
        { class: "xl-table" },
        colgroup,
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            (p.columns || []).map((c, j) =>
              h("th", { scope: "col", class: cls(j), text: String(c) }),
            ),
          ),
        ),
        body,
      ),
    ),
    more > 0 &&
      h("p", { class: "hint", text: t("files.more.rows", { n: more }) }),
  );
}
