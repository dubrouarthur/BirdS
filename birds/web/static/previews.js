// Previews of generated files, drawn from what the file really holds (the server reads the written file):
// a deck as its slides (shapes on a 1280 x 720 canvas, scaled with container units), a document as an A4 page,
// a sheet as its styled table. Model text only ever goes through textContent; geometry goes through the CSSOM.
import { b64ToBytes, button, h, t } from "./core.js";

// ------------------------------------------------------------------ pictures, charts and tables of the file

// thumbnails come as base64 JPEG in the preview (p.media); the CSP has no data: in img-src, so each becomes a
// blob: URL once (cached by key: the same picture in the stage and the filmstrip is decoded once)
const blobs = new Map();
function mediaUrl(media, key) {
  if (!media || typeof media[key] !== "string") return null;
  if (!blobs.has(key)) {
    try {
      blobs.set(key, URL.createObjectURL(new Blob([b64ToBytes(media[key])], { type: "image/jpeg" })));
    } catch {
      return null;
    }
  }
  return blobs.get(key);
}

const rgba = (hex, a) => {
  if (!HEX.test(String(hex || ""))) return "transparent";
  const n = parseInt(hex, 16);
  return `rgb(${n >> 16} ${(n >> 8) & 255} ${n & 255} / ${Math.max(0, Math.min(1, num(a)))})`;
};

const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs, text) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, String(v));
  if (text !== undefined) el.textContent = String(text);
  return el;
}

const fmtValue = (v, unit) => {
  if (!Number.isFinite(Number(v))) return "";
  const lang = document.documentElement.lang === "en" ? "en-GB" : "fr-FR";
  const out = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(Number(v));
  return unit ? `${out}\u00a0${unit}` : out;
};

/** A native chart of the deck, redrawn from its data: columns, bars, a line or a doughnut, in the theme colours. */
export function chartSvg(ch, w, h) {
  const W = Math.max(1, num(w));
  const H = Math.max(1, num(h));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "sh-chart", "aria-hidden": "true" });
  const cats = (Array.isArray(ch?.cats) ? ch.cats : []).map(String);
  const ser = (Array.isArray(ch?.ser) ? ch.ser : []).filter((x) => x && Array.isArray(x.v));
  const pal = (Array.isArray(ch?.pal) ? ch.pal : []).filter((c) => HEX.test(String(c)));
  const col = (j) => `#${pal[j % Math.max(1, pal.length)] || "1e5bd8"}`;
  const unit = String(ch?.u || "");
  const fs = 17;
  if (!cats.length || !ser.length) return svg;
  const legend = ser.length > 1 || ch.t === "pie";
  const legendItems = ch.t === "pie" ? cats : ser.map((x) => String(x.n || ""));
  const plotH = H - (legend ? 40 : 0);
  if (legend) {
    let x = 0;
    const g = s("g");
    legendItems.forEach((name, j) => {
      g.append(s("rect", { x, y: H - 26, width: 12, height: 12, fill: col(j) }));
      g.append(s("text", { x: x + 18, y: H - 15, "font-size": fs, fill: "#121a2e" }, name.slice(0, 24)));
      x += 30 + Math.min(24, name.length) * fs * 0.5;
    });
    g.setAttribute("transform", `translate(${Math.max(0, (W - x) / 2)} 0)`);
    svg.append(g);
  }
  if (ch.t === "pie") {
    const vals = ser[0].v.map((v) => Math.max(0, num(v)));
    const total = vals.reduce((a, b) => a + b, 0) || 1;
    const r = Math.min(W, plotH) / 2 - 10;
    const cx = W / 2;
    const cy = plotH / 2;
    let a = -Math.PI / 2;
    vals.forEach((v, j) => {
      const sweep = (2 * Math.PI * v) / total;
      const x1 = cx + r * Math.cos(a);
      const y1 = cy + r * Math.sin(a);
      const x2 = cx + r * Math.cos(a + sweep);
      const y2 = cy + r * Math.sin(a + sweep);
      const large = sweep > Math.PI ? 1 : 0;
      svg.append(s("path", { d: `M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} Z`, fill: col(j),
                             stroke: "#fff", "stroke-width": 3 }));
      if (sweep > 0.35) {
        const m = a + sweep / 2;
        svg.append(s("text", { x: cx + r * 0.79 * Math.cos(m), y: cy + r * 0.79 * Math.sin(m) + 6,
                               "text-anchor": "middle", "font-size": fs + 1, "font-weight": 700, fill: "#fff" },
                     fmtValue(ser[0].v[j], unit)));
      }
      a += sweep;
    });
    svg.append(s("circle", { cx, cy, r: r * 0.58, fill: "#fff" }));
    return svg;
  }
  const flat = ser.flatMap((x) => x.v.map(num));
  const max = Math.max(...flat, 0) || 1;
  const min = Math.min(...flat, 0);
  const span = max - min || 1;
  if (ch.t === "barh") {
    const left = Math.min(W * 0.35, 12 + Math.max(...cats.map((c) => c.length)) * fs * 0.5);
    const slot = plotH / cats.length;
    const bh = (slot * 0.62) / ser.length;
    cats.forEach((c, i) => {
      svg.append(s("text", { x: left - 10, y: slot * (i + 0.5) + 6, "text-anchor": "end", "font-size": fs,
                             fill: "#121a2e" }, c.slice(0, 32)));
      ser.forEach((x, j) => {
        const v = num(x.v[i]);
        const bw = ((W - left - 70) * Math.max(0, v - Math.min(min, 0))) / span;
        const y = slot * i + slot * 0.19 + j * bh;
        svg.append(s("rect", { x: left, y, width: Math.max(0, bw), height: bh - 3, fill: col(j) }));
        svg.append(s("text", { x: left + bw + 8, y: y + bh / 2 + 5, "font-size": fs, "font-weight": 700,
                               fill: "#121a2e" }, fmtValue(x.v[i], unit)));
      });
    });
    return svg;
  }
  const top = 34;
  const bottom = plotH - 30;
  const slot = W / cats.length;
  const y = (v) => bottom - ((num(v) - Math.min(min, 0)) / span) * (bottom - top);
  svg.append(s("line", { x1: 0, x2: W, y1: y(0), y2: y(0), stroke: "#d9dee8", "stroke-width": 1.5 }));
  cats.forEach((c, i) =>
    svg.append(s("text", { x: slot * (i + 0.5), y: plotH - 6, "text-anchor": "middle", "font-size": fs,
                           fill: "#121a2e" }, c.slice(0, 18))),
  );
  if (ch.t === "line") {
    ser.forEach((x, j) => {
      const pts = x.v.map((v, i) => [slot * (i + 0.5), y(v)]);
      svg.append(s("polyline", { points: pts.map((p) => p.join(",")).join(" "), fill: "none", stroke: col(j),
                                 "stroke-width": 4, "stroke-linejoin": "round" }));
      pts.forEach(([px2, py], i) => {
        svg.append(s("circle", { cx: px2, cy: py, r: 6, fill: "#fff", stroke: col(j), "stroke-width": 3 }));
        if (cats.length * ser.length <= 16)
          svg.append(s("text", { x: px2, y: py - 14, "text-anchor": "middle", "font-size": fs, "font-weight": 700,
                                 fill: "#121a2e" }, fmtValue(x.v[i], unit)));
      });
    });
    return svg;
  }
  const bw = (slot * 0.64) / ser.length;
  ser.forEach((x, j) =>
    x.v.forEach((v, i) => {
      const bx = slot * i + slot * 0.18 + j * bw;
      const y0 = Math.min(y(v), y(0));
      svg.append(s("rect", { x: bx, y: y0, width: bw - 4, height: Math.abs(y(0) - y(v)), fill: col(j) }));
      if (cats.length * ser.length <= 16)
        svg.append(s("text", { x: bx + (bw - 4) / 2, y: y0 - 8, "text-anchor": "middle", "font-size": fs,
                               "font-weight": 700, fill: "#121a2e" }, fmtValue(v, unit)));
    }),
  );
  return svg;
}

function tableGrid(tb) {
  const rows = Array.isArray(tb?.rows) ? tb.rows : [];
  const grid = h("div", { class: "sh-table", role: "table" });
  const cw = (Array.isArray(tb.cw) ? tb.cw : []).map(num);
  const rh = (Array.isArray(tb.rh) ? tb.rh : []).map(num);
  grid.style.gridTemplateColumns = cw.map((w) => `calc(var(--px) * ${w})`).join(" ");
  grid.style.gridTemplateRows = rh.map((v) => `calc(var(--px) * ${v})`).join(" ");
  rows.forEach((row, i) =>
    (Array.isArray(row) ? row : []).forEach((c) => {
      const cell = h("div", { class: `sh-cell${c?.al === "r" ? " is-r" : ""}`, role: i ? "cell" : "columnheader",
                              text: String(c?.t ?? "") });
      cell.style.background = color(c?.f, "transparent");
      cell.style.color = color(c?.c, "#121a2e");
      cell.style.setProperty("font-size", `calc(var(--pt) * ${num(tb.s) || 16})`);
      if (c?.b) cell.style.fontWeight = "700";
      grid.append(cell);
    }),
  );
  return grid;
}


const HEX = /^[0-9A-Fa-f]{6}$/;
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
const color = (v, d) => (HEX.test(String(v || "")) ? `#${v}` : d);
const px = (el, prop, v) =>
  el.style.setProperty(prop, `calc(var(--px) * ${num(v)})`);

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
export function slideCanvas(slide, live, media) {
  const canvas = h("div", { class: "slide-canvas" });
  if (slide.bg) canvas.style.background = color(slide.bg, "#fff");
  for (const sh of Array.isArray(slide.shapes) ? slide.shapes : []) {
    if (sh.img) {
      const url = mediaUrl(media, sh.img);
      if (!url) continue;
      const img = h("img", { class: "sh sh-img", src: url, alt: live ? String(sh.alt || "") : "", decoding: "async" });
      for (const k of ["left", "top", "width", "height"]) px(img, k, sh[k[0] === "l" ? "x" : k[0] === "t" ? "y" : k[0]]);
      canvas.append(img);
      continue;
    }
    const el = h("div", {
      class: `sh sh-${sh.g === "o" ? "o" : sh.g === "rr" ? "rr" : "r"}`,
    });
    px(el, "left", sh.x);
    px(el, "top", sh.y);
    px(el, "width", sh.w);
    px(el, "height", sh.h);
    if (sh.ch) {
      el.append(chartSvg(sh.ch, sh.w, sh.h));
      canvas.append(el);
      continue;
    }
    if (sh.tb) {
      el.append(tableGrid(sh.tb));
      canvas.append(el);
      continue;
    }
    if (sh.f) el.style.background = sh.o !== undefined ? rgba(sh.f, sh.o) : color(sh.f, "transparent");
    if (sh.gr && Array.isArray(sh.gr.s))
      el.style.background = `linear-gradient(${num(sh.gr.a) + 90}deg, ${sh.gr.s
        .map((st) => `${rgba(st[1], st[2])} ${Math.round(num(st[0]) * 100)}%`)
        .join(", ")})`;
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
export function deckPreview(p, { onDownload, onEdit, full = false } = {}) {
  const slides = (Array.isArray(p.slides) ? p.slides : []).filter(
    (s) => s && Array.isArray(s.shapes),
  );
  if (!slides.length) return null;
  const total = Math.max(num(p.total), slides.length);
  // past the preview cap, the deck ends on a card that says how many slides the file still holds
  const more = total - slides.length;
  const last = slides.length - (more > 0 ? 0 : 1);
  let at = 0;
  const stage = h("div", {
    class: "deck-stage",
    tabindex: "0",
    role: "group",
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
        tabindex: "-1",
        "aria-label": t("files.deck.goto", {
          n: s.n || i + 1,
          title: s.title || "",
        }),
        onclick: () => go(i),
      },
      h(
        "span",
        { class: "slide-frame", "aria-hidden": "true" },
        slideCanvas(s, false, p.media),
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
  const moreText = () => t("files.deck.more", { n: more });
  if (more > 0) {
    const b = h(
      "button",
      { type: "button", class: "deck-thumb deck-thumb-more", tabindex: "-1", onclick: () => go(slides.length) },
      h("span", { class: "slide-frame" }, h("span", { class: "deck-more-n", text: moreText() })),
    );
    film.append(h("li", null, b));
    thumbs.push(b);
  }
  function endCard() {
    return h(
      "div",
      { class: "slide-frame deck-end" },
      h(
        "div",
        { class: "deck-end-in" },
        h("p", { class: "deck-end-n", text: moreText() }),
        h("p", { text: t("files.deck.more.hint") }),
        onDownload && button("btn-primary btn-small", "download", t("files.download"), onDownload),
      ),
    );
  }
  function go(i) {
    at = Math.max(0, Math.min(last, i));
    const s = slides[at] || { n: `${slides.length + 1}–${total}`, title: moreText() };
    stage.replaceChildren(
      slides[at] ? h("div", { class: "slide-frame" }, slideCanvas(s, true, p.media)) : endCard(),
    );
    stage.setAttribute(
      "aria-label",
      t("files.deck.goto", { n: s.n || at + 1, title: s.title || "" }),
    );
    // seen: "2 / 31"; heard: "Slide 2 of 31: Part 1"
    counter.replaceChildren(
      h("span", { "aria-hidden": "true", text: `${s.n || at + 1} / ${total}` }),
      h("span", {
        class: "sr-only",
        text: t("files.deck.status", { n: s.n || at + 1, total, title: s.title || "" }),
      }),
    );
    prev.disabled = at === 0;
    next.disabled = at === last;
    // one tab stop for the whole filmstrip (the current slide); arrows move within it
    thumbs.forEach((b, j) => {
      b.tabIndex = j === at ? 0 : -1;
      if (j === at) b.setAttribute("aria-current", "true");
      else b.removeAttribute("aria-current");
    });
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
    else if (e.key === "End") go(last);
    else return;
    e.preventDefault();
    if (e.target.classList?.contains("deck-thumb")) thumbs[at]?.focus();
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
        onEdit &&
        button("btn-ghost btn-small office-edit-btn", "edit", t("files.edit"), onEdit),
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

export function docPreview(p, { onDownload, onEdit } = {}) {
  const page = h("div", { class: "a4", "data-office": ["modern", "warm"].includes(p.theme) ? p.theme : null });
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
            class: `a4-callout a4-${b.c === "decision" ? "decision" : b.c === "warn" ? "warn" : "action"}`,
          }),
          b.r,
        ),
      );
    else if (b.k === "quote")
      page.append(runsOf(h("blockquote", { class: "a4-quote" }), b.r));
    else if (b.k === "code")
      page.append(h("pre", { class: "a4-code", text: String(b.t || "") }));
    else if (b.k === "rule") page.append(h("hr", { class: "a4-rule" }));
    else if (b.k === "img") {
      const url = mediaUrl(p.media, b.m);
      if (!url) continue;
      const img = h("img", { src: url, alt: String(b.alt || ""), decoding: "async" });
      if (num(b.w) > 0) img.style.inlineSize = `calc(var(--cm) * ${Math.min(16.2, num(b.w))})`;
      page.append(h("figure", { class: "a4-fig" }, img));
    } else if (b.k === "cap") page.append(runsOf(h("p", { class: "a4-cap" }), b.r));
    else if (b.k === "toch") page.append(runsOf(h("p", { class: "a4-toch" }), b.r));
    else if (b.k === "toc")
      page.append(runsOf(h("p", { class: `a4-toc${num(b.l) > 1 ? " is-l2" : ""}` }), b.r));
    else if (b.k === "pb") page.append(h("hr", { class: "a4-pb", "aria-hidden": "true" }));
    else if (b.k === "src") page.append(runsOf(h("p", { class: "a4-p a4-src" }), b.r));
    else if (b.k === "table") page.append(docTable(b));
    else if (b.k === "p") page.append(runsOf(h("p", { class: "a4-p" }), b.r));
  }
  if (num(p.more) > 0)
    page.append(h("p", { class: "a4-cut", text: t("files.doc.more", { n: num(p.more) }) }));
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
      less.focus();
    },
  );
  // once open, the page can be long: "Show less" and the download stay at hand at the bottom of the window
  const less = button("btn-ghost btn-small a4-less", "down", t("files.doc.less"), () => {
    wrap.classList.add("is-clipped");
    wrap.querySelector(".a4-scroll").scrollTop = 0;
    wrap.scrollIntoView({ block: "nearest" });
    more.focus();
  }, { "aria-label": t("files.doc.less") }); // its label hides on a phone
  wrap.append(
    more,
    h(
      "div",
      { class: "a4-bar" },
      less,
      onEdit && button("btn-ghost btn-small office-edit-btn", "edit", t("files.edit"), onEdit),
      onDownload && button("btn-primary btn-small btn-icon", "download", t("files.download"), onDownload),
    ),
  );
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
  const scroller = h(
    "div",
    {
      class: "xl-scroll",
      tabindex: "0",
      "aria-label": t("files.preview"),
      // a shadow on the frozen first column while the sheet is scrolled sideways
      onscroll: (e) => e.currentTarget.classList.toggle("is-x", Math.abs(e.currentTarget.scrollLeft) > 0),
    },
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
  );
  return h(
    "div",
    { class: "xl" },
    scroller,
    more > 0 &&
      h("p", { class: "hint", text: t("files.more.rows", { n: more }) }),
  );
}
