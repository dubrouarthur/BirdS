// Rendering of a conversation: user bubbles, Bird's turns (live status, steps, answer, cards, receipt).
import {
  $,
  activeMode,
  b64ToBytes,
  button,
  copyText,
  download,
  elapsed,
  fmtBytes,
  fmtCo2,
  fmtEnergy,
  fmtInt,
  fmtSeconds,
  fmtSig,
  h,
  hasEnergy,
  icon,
  state,
  t,
  toast,
  toolLabel,
  modelLabel,
} from "./core.js";
import { renderBlocks, renderMarkdown, safeUrl, stabilize } from "./markdown.js";
import { wrapPref } from "./richcode.js";
import { docCard, imageCard, kindOf, middle } from "./attach.js";
import { deckPreview, docPreview, sheetPreview } from "./previews.js";
import { openEditor } from "./editor.js";
import { modelDownCard, unreachableCard } from "./local.js";
import { MODEL_DOWN } from "./local-data.js";
import { chartMarkdown, renderChart } from "./chart.js";
import { moveFull, renderWidgets, widgetsText } from "./widgets.js";
import { renderAgents, renderChecks } from "./agents.js";
import { footprintAnswer } from "./footprint.js";
import { renderPlan } from "./plan.js"; // task plan checklist (w1-harness)
import { canvasCard } from "./canvas.js";
import { enhanceAnswer } from "./modules.js";
import { renderChips, transforms } from "./followups.js";
import { inlineEditor, versionPager } from "./conversation.js"; // « ‹ 1/2 › », editing a question in place
import { birdIcon, flyingBird, flyingText, renderFlight } from "./reflexion.js"; // Mode Réflexion
import { REWRITE_GLYPHS, copyAnswer, feedbackPanel, feedbackThanks, glyph, serialize, setSourcesOpen, treeOf, typeset } from "./answers.js"; // math, citations, rich copy, feedback (chat audit C2)

const cache = new Map(); // turn id -> { md, blocks }
let handlers = {};
export const setHandlers = (value) => (handlers = value);

const hostOf = (url) => {
  const safe = safeUrl(url);
  return safe ? new URL(safe).host.replace(/^www\./, "") : "";
};

function target(tool, args) {
  const a = args && typeof args === "object" ? args : {};
  const str = (k) =>
    typeof a[k] === "string" && a[k].trim() ? a[k].trim() : "";
  if (tool === "draft_email")
    return [Array.isArray(a.to) ? a.to.join(", ") : str("to"), str("subject")]
      .filter(Boolean)
      .join(" — ");
  if (str("url")) return hostOf(str("url")) || str("url");
  return str("query") || str("path") || str("title") || str("subject") || str("name") || "";
}

function details(cls, open, remember, summaryChildren, ...body) {
  const el = h(
    "details",
    { class: cls, open },
    h("summary", null, ...summaryChildren),
    ...body,
  );
  // Only remember toggles made by the user (the initial `open` also fires a toggle event).
  let byUser = false;
  el.firstChild.addEventListener("click", () => (byUser = true));
  el.addEventListener("toggle", () => byUser && remember(el.open));
  return el;
}

// ------------------------------------------------------------------ live status

function liveLine(turn) {
  if (turn.status !== "running") return null;
  const running = turn.steps.find((s) => s.status === "running");
  let text;
  let sub = "";
  let calm = false;
  if (turn.live?.state === "waking") {
    // the model was asleep (scaled to zero): one calm line, no attempt counter nor retry countdown; Bird retries
    // on its own and the thin bar below fills slowly while the wait lasts
    text = t("live.waking");
    sub = t("live.waking.sub");
    calm = true;
  } else if (running) {
    const key = `live.${running.tool}`;
    const label = t(key) === key ? t("live.tool") : t(key);
    const what = target(running.tool, running.arguments);
    text = what ? `${label} : ${what}…` : `${label}…`;
  } else if (turn.text) text = t("live.writing");
  else if (turn.steps.some((s) => s.status === "done")) text = t("live.reading"); // a tool finished: Bird reads it, then writes
  else text = flyingText(turn) || t(turn.thinking ? "live.thinking" : "live.starting");
  // while Bird reasons, the bird the server announced flaps in place of the spinner
  const bird = !running && !turn.text && turn.live?.state !== "waking" ? flyingBird(turn) : null;
  if (running?.tool === "web_search" && state.health?.tools_info?.search?.label)
    sub = t("live.search.via", { label: state.health.tools_info.search.label });
  if (running?.tool === "read_image") sub = t("live.read_image.sub");
  const since = turn.live?.since || turn.started || Date.now();
  // no fixed promise: the "first word in 2 s" line only in the first 3 s of a plain request, then honest updates
  let auto = null;
  if (!sub && !calm && !turn.text) {
    const first = !turn.steps.length && !turn.thinking ? "1" : "";
    const started = String(turn.started || Date.now());
    const line = autoSub(Number(started), first);
    auto = h("p", { class: "live-sub", "data-auto-sub": first, "data-started": started, hidden: !line, text: line });
  }
  return h(
    "div",
    { class: `live${calm ? " live-calm" : ""}` },
    bird || (calm ? birdIcon("hirondelle", "rf-flap live-wake-bird") : h("span", { class: "spinner", "aria-hidden": "true" })),
    h(
      "div",
      { class: "live-body" },
      h(
        "p",
        { class: "live-text" },
        h("span", { text }),
        h("span", { class: "live-time num", "data-since": String(since), "aria-hidden": "true", text: elapsed(since) }),
      ),
      sub ? h("p", { class: "live-sub", text: sub }) : auto,
      calm && wakeBar(since),
    ),
  );
}

function wakeBar(since) {
  const fill = h("span", { "data-wake-since": String(since) });
  fill.style.inlineSize = `${wakeShare(since)}%`; // CSSOM, not a style attribute: the CSP allows no inline styles
  return h("div", { class: "wake-bar", "aria-hidden": "true" }, fill);
}

// A wake-up lasts from a few tens of seconds to a few minutes: the bar fills fast at first, then ever more slowly
// (time constant 60 s), and never reaches the end before the first word does.
function wakeShare(since) {
  const s = Math.max(0, (Date.now() - Number(since)) / 1000);
  return Math.round(6 + 86 * (1 - Math.exp(-s / 60)));
}

// Nothing to say in the first seconds of a normal answer (Bird may be reasoning): a quiet line from 25 s,
// the Stop hint from 60 s only.
const SLOW_AFTER_S = 25;
const SLOWER_AFTER_S = 60;

function autoSub(started, first) {
  const s = (Date.now() - started) / 1000;
  if (s < 3) return first ? t("live.first") : "";
  if (s < SLOW_AFTER_S) return "";
  return t(s < SLOWER_AFTER_S ? "live.slow" : "live.slower");
}


/** Called every second while a request runs: only the small timers change, nothing else is redrawn. */
export function tick() {
  for (const el of document.querySelectorAll("[data-since]")) el.textContent = elapsed(el.dataset.since);
  for (const el of document.querySelectorAll("[data-wake-since]")) el.style.inlineSize = `${wakeShare(el.dataset.wakeSince)}%`;
  for (const el of document.querySelectorAll("[data-auto-sub]")) {
    const line = autoSub(Number(el.dataset.started), el.dataset.autoSub);
    if (el.textContent !== line) el.textContent = line;
    el.hidden = !line;
  }
}

// ------------------------------------------------------------------ steps

function argRows(args) {
  const a = args && typeof args === "object" ? args : {};
  return Object.entries(a).map(([key, value]) => {
    const name = t(`arg.${key}`) === `arg.${key}` ? key : t(`arg.${key}`);
    let text;
    if (typeof value === "string") text = value;
    else if (Array.isArray(value) && value.every((v) => typeof v === "string"))
      text = value.join(", ");
    else if (Array.isArray(value)) text = fmtInt(value.length);
    else text = String(value);
    return h(
      "div",
      null,
      h("dt", { text: name }),
      h("dd", {
        class: text.length > 90 ? "kv-long" : "",
        text: text.slice(0, 1200),
      }),
    );
  });
}

function renderFailedFiles(turn) {
  if (turn.status === "running") return null;
  const failed = turn.steps.filter(
    (s) => s.status === "error" && /^make_(slides|document|sheet)$/.test(s.tool) && !s.retried,
  );
  const made = (turn.files || []).length;
  if (!failed.length || made >= failed.length) return null;
  return h(
    "div",
    { class: "notice notice-warn", role: "status" },
    icon("alert"),
    h(
      "div",
      { class: "notice-text" },
      h("strong", { text: t("retry.title") }),
      h("p", { text: t("retry.text", { tool: toolLabel(failed[0].tool) }) }),
    ),
    h(
      "div",
      { class: "notice-actions" },
      button("btn-primary btn-small", "retry", t("retry.step"), () => handlers.onRetryStep(turn, failed[0]), {
        "data-retry": "1",
      }),
    ),
  );
}

function renderSteps(turn) {
  if (!turn.steps.length) return null;
  const flagged = turn.steps.some((s) =>
    (s.flags || []).includes("possible_injection"),
  );
  const total = turn.steps.reduce((sum, s) => sum + (s.seconds || 0), 0);
  const n = turn.steps.length;
  turn.ui.stepOpen = turn.ui.stepOpen || {};
  const asking = turn.status === "confirm";
  const items = turn.steps.map((raw) => {
    // a step paused on the approval sheet is waiting for you, not running
    const step = asking && raw.status === "running" ? { ...raw, status: "awaiting" } : raw;
    const injection = (step.flags || []).includes("possible_injection");
    const statusIcon = { done: "check", error: "cross", denied: "ban", awaiting: "shield", stopped: "pause" }[
      step.status
    ];
    const what = target(step.tool, step.arguments);
    return h(
      "li",
      { class: `step step-${step.status}${injection ? " step-flagged" : ""}` },
      details(
        "step-box",
        turn.ui.stepOpen[step.index] ?? injection,
        (value) => (turn.ui.stepOpen[step.index] = value),
        [
          h("span", { class: "step-icon" }, icon(step.tool)),
          h(
            "span",
            { class: "step-title" },
            h("span", { class: "step-label", text: toolLabel(step.tool) }),
            what && h("span", { class: "step-target", text: what }),
          ),
          step.info?.label &&
            h("span", {
              class: "badge badge-src", // a fallback is a calm line in the step, never a warning
              title: step.info.fallback_from
                ? t("steps.fallback", { from: step.info.fallback_from, label: step.info.label })
                : t("steps.via", { label: step.info.label }),
              text: step.info.label,
            }),
          step.info?.auto &&
            h("span", { class: "badge badge-auto", title: t("step.auto.title"), text: t("step.auto") }),
          injection &&
            h(
              "span",
              { class: "badge badge-warn badge-flag", title: t("steps.flagged") },
              icon("alert"),
              h("span", { class: "badge-flag-text", text: t("steps.flagged") }),
            ),
          h(
            "span",
            { class: "step-status" },
            step.status === "running"
              ? h("span", { class: "spinner", "aria-hidden": "true" })
              : icon(statusIcon || "check", `status-${step.status}`),
            step.status === "awaiting"
              ? h("span", { class: "step-await-text", text: t("status.awaiting") })
              : h("span", { class: "sr-only", text: t(`status.${step.status}`) }),
            step.status !== "running" &&
              step.seconds > 0 &&
              h("span", { class: "num", text: fmtSeconds(step.seconds) }),
          ),
          icon("chevron", "chev"),
        ],
        h(
          "div",
          { class: "step-body" },
          injection &&
            h(
              "p",
              { class: "step-warning" },
              icon("shield"),
              h("span", { text: t("steps.injection") }),
            ),
          injection && step.flagged_excerpt && ignoredQuote(step),
          h("p", { class: "eyebrow", text: t("steps.args") }),
          h("dl", { class: "kv" }, argRows(step.arguments)),
          (step.preview || step.summary) &&
            h("p", { class: "eyebrow", text: t("steps.result") }),
          step.summary && h("p", { class: "step-summary", text: step.summary }),
          step.preview && h("p", { class: "step-preview", text: step.preview }),
          step.info?.fallback_from &&
            h("p", {
              class: "hint",
              text: t("steps.fallback", { from: step.info.fallback_from, label: step.info.label }),
            }),
          (step.repairs || []).length > 0 &&
            h("p", { class: "step-repairs" }, icon("check"), t("steps.repaired", { n: step.repairs.length })),
          step.status === "error" &&
            /^make_(slides|document|sheet)$/.test(step.tool) &&
            turn.status !== "running" &&
            button("btn-outline btn-small", "retry", t("retry.step"), () => handlers.onRetryStep(turn, step), {
              "data-retry-step": String(step.index),
            }),
        ),
      ),
    );
  });
  return details(
    "steps",
    turn.ui.steps ??
      (turn.status === "running" || turn.status === "confirm" || flagged),
    (value) => (turn.ui.steps = value),
    [
      icon("chevron", "chev"),
      h("span", {
        class: "steps-count",
        text: n === 1 ? t("steps.count.one") : t("steps.count.many", { n }),
      }),
      h("span", {
        class: "steps-names",
        text: [...new Set(turn.steps.map((s) => toolLabel(s.tool)))].join(
          " · ",
        ),
      }),
      flagged &&
        h(
          "span",
          { class: "badge badge-warn" },
          icon("alert"),
          t("steps.flagged"),
        ),
      asking && h("span", { class: "badge badge-await" }, icon("shield"), t("steps.awaiting")),
      turn.status !== "running" &&
        !asking &&
        total > 0 &&
        h("span", { class: "num steps-time", text: fmtSeconds(total) }),
    ],
    h("ol", { class: "timeline", "aria-label": t("steps.title") }, items),
  );
}

/** The sentence Bird ignored, quoted as plain text (never Markdown, never a link), with where it came from. */
function ignoredQuote(step) {
  const host = hostOf(String(step.arguments?.url || ""));
  return h(
    "figure",
    { class: "ignored" },
    h("figcaption", { class: "eyebrow", text: host ? t("steps.ignored.from", { host }) : t("steps.ignored") }),
    h("blockquote", { class: "ignored-text", text: String(step.flagged_excerpt) }),
  );
}

// ------------------------------------------------------------------ confirmation sheet

function renderConfirm(turn) {
  const c = turn.confirm;
  if (!c) return null;
  if (turn.status !== "confirm") {
    if (c.decision === undefined) return null;
    return h(
      "p",
      { class: `confirm-done confirm-${c.decision ? "yes" : "no"}` },
      icon(c.decision ? "check" : "ban"),
      t(c.decision ? "confirm.allowed" : "confirm.denied"),
    );
  }
  return h(
    "section",
    {
      class: "sheet",
      role: "group",
      "aria-labelledby": `confirm-${turn.id}`,
      "data-confirm": "1",
    },
    h(
      "header",
      { class: "sheet-head" },
      h("span", { class: "sheet-icon" }, icon("shield")),
      h("h3", { id: `confirm-${turn.id}`, text: t("confirm.title") }),
    ),
    h(
      "div",
      { class: "sheet-grid" },
      h(
        "div",
        null,
        h("p", { class: "eyebrow", text: t("confirm.what") }),
        h("p", { class: "sheet-tool" }, icon(c.tool), toolLabel(c.tool)),
        h("dl", { class: "kv kv-box" }, argRows(c.arguments)),
      ),
      h(
        "div",
        null,
        h("p", { class: "eyebrow", text: t("confirm.why") }),
        h("p", { class: "sheet-why", text: String(c.reason || "") }),
        ...turn.steps
          .filter((s) => s.flagged_excerpt && (s.flags || []).includes("possible_injection"))
          .slice(-1)
          .map((s) =>
            h(
              "details",
              { class: "sheet-ignored", open: !window.matchMedia("(max-width: 640px)").matches },
              h("summary", null, icon("chevron", "chev"), t("steps.ignored")),
              ignoredQuote(s),
            ),
          ),
        h("p", { class: "eyebrow", text: t("confirm.then") }),
        h(
          "ul",
          { class: "sheet-then" },
          h("li", null, icon("check"), t("confirm.then.allow")),
          h("li", null, icon("ban"), t("confirm.then.deny")),
        ),
      ),
    ),
    h(
      "div",
      { class: "sheet-actions" },
      button(
        "btn-outline",
        null,
        t("confirm.deny"),
        () => handlers.onConfirm(turn, false),
        { "data-confirm-deny": "1" },
      ),
      button(
        "btn-quiet",
        null,
        t("confirm.refine"),
        () => handlers.onConfirm(turn, false, { refine: true }),
        { "data-confirm-refine": "1", title: t("confirm.refine.hint") },
      ),
      button(
        "btn-primary",
        null,
        t("confirm.allow"),
        () => handlers.onConfirm(turn, true),
        { "data-confirm-allow": "1" },
      ),
    ),
  );
}

// ------------------------------------------------------------------ result cards

const ICON_SRC = /^\/api\/icon\?d=[a-z0-9.-]+&s=[0-9a-f]{24}$/;
function monoHue(domain) {
  let x = 0;
  for (const ch of String(domain)) x = (x * 31 + ch.charCodeAt(0)) >>> 0;
  return x % 8;
}

function renderSources(turn) {
  const sources = turn.answer?.sources || [];
  if (!sources.length) return null;
  // « donne-moi tes sources »: the source cards module shows them (modules.js), with the same anchors
  if ((turn.answer?.widgets || []).some((w) => w?.type === "sourcecards")) return null;
  // « 3 sources »: a pill with the sites' marks; the list opens under it (and from a citation's bubble, answers.js)
  const panelId = `srcp-${turn.id}`;
  turn.ui = turn.ui || {};
  const open = Boolean(turn.ui.sourcesOpen);
  const marks = sources.slice(0, 3).map((source) => {
    const url = safeUrl(source.url);
    const domain = String(source.domain || (url ? hostOf(url) : ""));
    return h("span", { class: `src-pill-mark source-mono mono-${monoHue(domain)}`, "aria-hidden": "true", text: (domain[0] || "?").toUpperCase() });
  });
  const pill = h(
    "button",
    {
      type: "button",
      class: "src-pill",
      "aria-expanded": String(open),
      "aria-controls": panelId,
      "data-act": "sources",
      onclick: () => {
        const now = pill.getAttribute("aria-expanded") !== "true";
        setSourcesOpen(pill, now);
        turn.ui.sourcesOpen = now;
      },
    },
    h("span", { class: "src-pill-marks" }, marks),
    h("span", { class: "src-pill-text", text: sources.length === 1 ? t("src.pill.one") : t("src.pill.many", { n: sources.length }) }),
    icon("chevron", "src-pill-chev"),
  );
  return h(
    "section",
    { class: `sources${open ? " is-open" : ""}`, "aria-label": t("sources.title") },
    pill,
    h(
      "ol",
      { class: "source-list src-panel", id: panelId, hidden: !open },
      sources.map((source) => {
        const url = safeUrl(source.url);
        const title = String(source.title || source.url || "");
        const n = Number(source.n) || 0;
        const domain = String(source.domain || (url ? hostOf(url) : ""));
        const mono = h("span", { class: `source-mono mono-${monoHue(domain)}`, "aria-hidden": "true", text: (domain[0] || "?").toUpperCase() });
        const iconUrl = ICON_SRC.test(String(source.icon || "")) ? source.icon : null;
        const fav =
          iconUrl &&
          h("img", { class: "source-icon", src: iconUrl, width: "16", height: "16", alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
        if (fav) {
          mono.hidden = true;
          fav.addEventListener("error", () => {
            fav.remove();
            mono.hidden = false;
          });
        }
        const meta = [domain, source.date && String(source.date)].filter(Boolean).join(" · ");
        return h(
          "li",
          { id: `src-${turn.id}-${n}`, tabindex: "-1", class: `source-card source-${source.kind || "web"}` },
          h("span", { class: "source-n num", text: String(n || "") }),
          h(
            "span",
            { class: "source-body" },
            url
              ? h("a", {
                  href: url,
                  target: "_blank",
                  rel: "noopener noreferrer",
                  referrerpolicy: "no-referrer",
                  text: title,
                })
              : h("span", { text: title }),
            url &&
              h(
                "span",
                { class: "source-host" },
                fav,
                mono,
                h("span", { text: meta }),
                source.kind === "gov" && h("span", { class: "badge badge-gov", text: t("src.public") }),
              ),
            source.snippet && h("span", { class: "source-snippet", text: String(source.snippet) }),
          ),
        );
      }),
    ),
  );
}

function slideStrip(preview) {
  const slides = preview.slides || [];
  const card = (n, title, body, cls = "") =>
    h(
      "li",
      { class: `slide ${cls}`, "aria-label": t("files.slide.n", { n }) },
      h("div", { class: "slide-inner" }, h("p", { class: "slide-title", text: title }), body),
      h("span", { class: "slide-num num", "aria-hidden": "true", text: String(n) }),
    );
  return h(
    "ol",
    { class: "slide-strip", tabindex: "0", "aria-label": t("files.preview") },
    card(1, String(preview.title || ""), h("p", { class: "slide-sub", text: preview.subtitle || "" }), "slide-cover"),
    slides.map((s, i) => {
      const bullets = (s.bullets || []).filter((b) => String(b).trim());
      return card(
        i + 2,
        String(s.title || ""),
        bullets.length
          ? h(
              "ul",
              null,
              bullets.slice(0, 6).map((b) =>
                h("li", { class: /^(\s{2,}|-{1,2}\s|>\s?|◦)/.test(b) ? "sub" : "", text: String(b).replace(/^(\s+|-{1,2}\s|>\s?|◦\s?)/, "") }),
              ),
              bullets.length > 6 && h("li", { class: "more", text: t("files.more.bullets", { n: bullets.length - 6 }) }),
            )
          : null,
        bullets.length ? "" : "slide-section",
      );
    }),
  );
}

function filePreview(preview, onDownload, onEdit = null) {
  if (!preview || typeof preview !== "object") return null;
  if (preview.v === 2) {
    // what the file really holds (read back by the server), drawn in the file's own design
    if (preview.kind === "slides") {
      const deck = deckPreview(preview, { onDownload, onEdit });
      return deck && h("div", null, deck, preview.notes > 0 && h("p", { class: "hint", text: t("files.notes", { n: preview.notes }) }));
    }
    if (preview.kind === "document") return docPreview(preview, { onDownload, onEdit });
    if (preview.kind === "sheet") return sheetPreview(preview);
  }
  if (preview.kind === "slides") {
    const notes = (preview.slides || []).filter((s) => s.notes);
    return h(
      "div",
      null,
      slideStrip(preview),
      notes.length > 0 && h("p", { class: "hint", text: t("files.notes", { n: notes.length }) }),
    );
  }
  if (preview.kind === "document") {
    const doc = h("div", { class: "doc-preview" });
    const page = h("div", { class: "doc-page" }, h("p", { class: "doc-title", text: String(preview.title || "") }));
    for (const s of preview.sections || []) {
      page.append(h("p", { class: "doc-h", text: String(s.heading || "") }));
      const body = h("div", { class: "md md-small" });
      // Safe by construction: renderMarkdown escapes the model's text before emitting its own tags.
      body.innerHTML = renderMarkdown(String(s.content || ""));
      page.append(body);
    }
    doc.append(page);
    return doc;
  }
  if (preview.kind === "sheet") {
    const more = (preview.total_rows || 0) - (preview.rows || []).length;
    return h(
      "div",
      { class: "table-wrap", tabindex: "0" },
      h(
        "table",
        { class: "sheet-preview" },
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            (preview.columns || []).map((c) =>
              h("th", { scope: "col", text: String(c) }),
            ),
          ),
        ),
        h(
          "tbody",
          null,
          (preview.rows || []).map((r) =>
            h(
              "tr",
              null,
              r.map((c) =>
                h("td", {
                  class: /^-?[\d\s.,]+$/.test(String(c)) ? "num al-right" : "",
                  text: String(c),
                  title: String(c), // the whole cell on hover: the preview shows one line of it
                }),
              ),
            ),
          ),
        ),
      ),
      more > 0 &&
        h("p", {
          class: "hint",
          text: t("files.more.rows", { n: fmtInt(more) }),
        }),
    );
  }
  return null;
}

function renderFiles(turn) {
  const inCanvas = turn.answer?.canvas?.files || []; // a Word document is one card: the canvas card
  const files = (turn.files || []).filter(
    (f) => f && typeof f.name === "string" && !inCanvas.includes(f.name),
  );
  if (!files.length) return null;
  turn.ui.fileOpen = turn.ui.fileOpen || {};
  return h(
    "div",
    { class: "cards" },
    files.map((file, i) => {
      const name =
        file.name.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 120) || "fichier";
      const ext = (name.match(/\.([A-Za-z0-9]{1,5})$/) || [
        "",
        "",
      ])[1].toUpperCase();
      const p = file.preview || {};
      const meta =
        p.kind === "slides"
          ? t("files.slides", { n: p.v === 2 ? p.total || 0 : (p.slides || []).length })
          : p.kind === "document"
            ? t("files.sections", {
                n: p.v === 2 ? (p.blocks || []).filter((b) => b && b.k === "h" && b.l === 1).length : (p.sections || []).length,
              })
            : p.kind === "sheet"
              ? [
                  t("files.rows", { n: p.total_rows || 0 }),
                  (p.columns || []).length > 1 && t("files.cols", { n: p.columns.length }),
                ]
                  .filter(Boolean)
                  .join(" · ")
              : "";
      const kind =
        {
          slides: "make_slides",
          document: "make_document",
          sheet: "make_sheet",
        }[p.kind] || "file";
      const save = file.data
        ? () =>
            download(
              name,
              file.mime || "application/octet-stream",
              new Blob([b64ToBytes(file.data)], { type: file.mime || "application/octet-stream" }),
            )
        : null;
      // a deck or document Bird made carries its plan: it can be edited and rebuilt here (editor.js)
      const edit = p.v === 2 && p.plan ? () => openEditor(file, { onDone: () => handlers.onChange?.(turn) }) : null;
      const preview = filePreview(p, save, edit);
      return h(
        "section",
        { class: `card file-card${p.v === 2 ? ` file-${p.kind}` : ""}`, "data-file": name },
        h(
          "header",
          { class: "card-head" },
          h("span", { class: "card-icon" }, icon(kind)),
          h(
            "div",
            { class: "card-title" },
            h("p", { class: "card-name", text: p.title || name, title: p.title || name }),
            h("p", {
              class: "card-meta",
              text: [ext, meta, file.size ? fmtBytes(file.size) : ""]
                .filter(Boolean)
                .join(" · "),
            }),
          ),
          save
            ? button("btn-primary btn-small card-dl", "download", t("files.download"), save, {
                "aria-label": t("files.download"), // the label is hidden on a phone, the name stays
              })
            : null,
        ),
        !file.data &&
          h(
            "p",
            { class: "card-note" },
            icon("info"),
            t(file.error === "too_large" ? "files.toolarge" : "files.lost"),
          ),
        preview &&
          details(
            "card-preview",
            turn.ui.fileOpen[i] ?? true,
            (v) => (turn.ui.fileOpen[i] = v),
            [icon("chevron", "chev"), t("files.preview")],
            preview,
          ),
      );
    }),
  );
}

// « [Prénom] », « [date] »: the blanks the draft leaves to the user, marked so they are not sent as they are
function fillMarks(text) {
  return text
    .split(/(\[[^[\]\n]{1,40}\])/)
    .map((part, i) => (i % 2 ? h("mark", { class: "email-fill", title: t("email.fill"), text: part }) : part));
}

// a quiet dashed pill: what is still to add before the mail can leave
const missingPill = (key) => h("span", { class: "email-missing" }, icon("plus"), h("span", { text: t(key) }));

function renderEmail(turn) {
  const draft = turn.answer?.draft_email;
  if (!draft || typeof draft !== "object") return null;
  const to = Array.isArray(draft.to)
    ? draft.to.join(", ")
    : String(draft.to ?? "");
  const subject = String(draft.subject ?? "");
  const body = String(draft.body ?? "");
  // a bare name ("Marc Petit") is not an address: shown to complete, never put in the mailto: link
  const isAddress = (s) => /^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$/.test(s);
  // "Marc <marc@example.fr>" keeps only the address in angle brackets
  const parts = to
    .split(",")
    .map((s) => s.trim())
    .map((s) => (s.match(/<([^<>\s]+@[^<>\s]+)>$/) || [null, s])[1])
    .filter(Boolean);
  // a placeholder the model wrote in place of a recipient (« [destinataires] », « <nom> », « à compléter ») is not
  // a name: the card says plainly that a recipient is to add
  const isPlaceholder = (s) =>
    /^[[<{(].*[\]>})]$/.test(s) || /^(destinataires?|recipients?|à compléter|to complete|tbd|\?+|…|\.\.\.)$/i.test(s);
  const names = [String(draft.to_hint ?? ""), ...parts.filter((s) => !isAddress(s))]
    .flatMap((s) => s.split(","))
    .map((s) => s.trim())
    .filter((s) => s && !isPlaceholder(s));
  const addresses = parts.filter(isAddress);
  // A mailto: link the user chooses to click. It only opens their own mail app with the draft: nothing is sent.
  const mailto = `mailto:${addresses
    .map((s) => encodeURIComponent(s))
    .join(
      ",",
    )}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  return h(
    "section",
    { class: "card email-card", "aria-label": t("email.title") },
    h(
      "header",
      { class: "card-head" },
      h("span", { class: "card-icon" }, icon("draft_email")),
      h(
        "div",
        { class: "card-title" },
        h("p", { class: "card-name", text: subject || t("email.title") }),
        h(
          "p",
          { class: "card-meta email-to", "data-email-to": addresses.length ? "set" : "missing" },
          h("span", { text: `${t("email.to")} ` }),
          // the addresses, then each name with its own « adresse à ajouter »: a name never reads as a real recipient
          // (it is not in the mailto: link); nobody at all reads « destinataire à ajouter »
          addresses.length || names.length
            ? [...addresses, ...names].flatMap((who, i, all) => {
                // the comma stays with the recipient before it: a line never starts with « , »
                const sep = i < all.length - 1 ? "," : "";
                return [
                  i ? " " : null,
                  i < addresses.length
                    ? h("span", { class: "email-addr" }, who + sep)
                    : h("span", { class: "email-name" }, who, " ", missingPill("email.to.noaddr"), sep),
                ];
              })
            : missingPill("email.to.missing"),
        ),
      ),
    ),
    h("div", { class: "email-body" }, fillMarks(body)),
    h(
      "div",
      { class: "card-actions" },
      button("btn-outline btn-small", "copy", t("email.copy.subject"), () =>
        copyText(subject),
      ),
      button("btn-outline btn-small", "copy", t("email.copy.body"), () =>
        copyText(body),
      ),
      mailto.length < 1900 &&
        h(
          "a",
          {
            class: "btn btn-outline btn-small",
            href: mailto,
            "data-mailto": "1",
          },
          icon("mail"),
          h("span", { class: "btn-label", text: t("email.open") }),
        ),
    ),
    h(
      "p",
      { class: "card-note" },
      icon("ban"),
      h("span", { text: t("email.notsent") }),
    ),
  );
}

// ------------------------------------------------------------------ the receipt (resource meter)

export function meterRows(usage) {
  const demo = usage.tokens_kind === "scripted";
  const gi = state.health?.grid_intensity_g_per_kwh;
  const energy = hasEnergy(usage);
  const tokenKind = demo
    ? "scripted"
    : usage.tokens_kind === "estimated"
      ? "estimated"
      : "counted";
  const tokenWhy = (key) =>
    demo
      ? "why.tokens.demo"
      : usage.tokens_kind === "estimated"
        ? "why.tokens.estimated"
        : key;
  return [
    [
      "row.prompt",
      fmtInt(usage.prompt_tokens),
      tokenKind,
      tokenWhy("why.prompt"),
    ],
    [
      "row.completion",
      fmtInt(usage.completion_tokens),
      tokenKind,
      tokenWhy("why.completion"),
    ],
    ["row.seconds", fmtSeconds(usage.seconds), "measured", "why.seconds"],
    typeof usage.first_token_seconds === "number" && [
      "row.first",
      fmtSeconds(usage.first_token_seconds),
      "measured",
      "why.first",
    ],
    ["row.tools", fmtInt(usage.tool_calls), "counted", "why.tools"],
    [
      "row.fetched",
      fmtBytes(usage.bytes_fetched),
      demo ? "scripted" : "counted",
      demo ? "why.fetched.demo" : "why.fetched",
    ],
    energy
      ? [
          "row.energy",
          fmtEnergy(usage.energy_wh, usage.energy_kind),
          usage.energy_kind,
          ...energyWhy(usage),
        ]
      : [
          "row.energy",
          t("meter.energy.none.long"),
          "unavailable",
          demo ? "why.energy.demo" : "why.energy.none",
        ],
    energy && typeof usage.co2_g === "number"
      ? [
          "row.co2",
          fmtCo2(usage.co2_g),
          "estimated",
          "why.co2",
          { gi: gi ?? "?" },
        ]
      : [
          "row.co2",
          t("co2.none"),
          "unavailable",
          energy ? "why.co2.nogrid" : "why.co2.noenergy",
        ],
    ["row.model", `${modelLabel()} · ${String(usage.model || "?")}`, "configured", "why.model"],
    [
      "row.thinking",
      usage.thinking ? t("yes") : t("no"),
      "configured",
      usage.thinking ? "why.thinking.on" : "why.thinking.off",
    ],
  ];
}

/** The explanation of the energy row: [i18n key, vars, links]. */
function energyWhy(usage) {
  const b = usage.energy_basis || {};
  if (usage.energy_method === "power_time")
    return [
      "why.energy.power",
      { s: fmtSig(b.busy_seconds || 0), pue: fmtSig(b.pue || 1) },
    ];
  if (usage.energy_method === "tokens") {
    const range =
      typeof b.low_wh === "number" && typeof b.high_wh === "number"
        ? t("why.energy.tokens.range", { low: fmtEnergy(b.low_wh), high: fmtEnergy(b.high_wh) })
        : "";
    const scope = b.serving_overhead
      ? t("why.energy.tokens.scope", { k: fmtSig(b.serving_overhead) })
      : "";
    return [
      "why.energy.tokens",
      {
        out: fmtInt(b.output_tokens ?? usage.completion_tokens),
        in: fmtInt((b.input_tokens ?? usage.prompt_tokens) - (b.cached_tokens || 0)),
        whout: fmtSig(b.wh_per_1k_out ?? 0),
        whin: fmtSig(b.wh_per_1k_in ?? 0),
        cached: b.cached_tokens > 0 ? t("why.energy.tokens.cached", { n: fmtInt(b.cached_tokens) }) : "",
        scope,
        range,
      },
      (state.health?.energy?.tokens?.sources || []).filter((s) => safeUrl(s.url)),
    ];
  }
  return [`why.energy.${usage.energy_kind}`, { source: usage.energy_source || "?" }];
}

export function meterTable(usage) {
  return h(
    "table",
    { class: "meter-table" },
    h(
      "tbody",
      null,
      meterRows(usage).filter(Boolean).map(([label, value, kind, why, vars, links]) =>
        h(
          "tr",
          { class: `kind-${kind}` },
          h("th", { scope: "row", text: t(label) }),
          h(
            "td",
            { class: "meter-value" },
            h("span", { class: "num", text: value }),
            h("span", { class: `tag tag-${kind}`, text: t(`kind.${kind}`) }),
          ),
          h(
            "td",
            { class: "meter-why" },
            t(why, vars),
            links?.length
              ? [
                  ` ${t("why.energy.sources")} `,
                  links.map((s, i) => [
                    i ? ", " : "",
                    h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: s.label }),
                  ]),
                  ".",
                ]
              : null,
          ),
        ),
      ),
    ),
  );
}

/** The latest answer shows its full receipt; earlier ones fold it into a one-line chip that expands in place. */
function renderReceipt(turn, isLast = true) {
  const u = turn.usage;
  if (!u) return null;
  // every answer, the latest included: one discreet line; the full receipt opens on demand
  const open = !!turn.ui.receipt;
  const energy = hasEnergy(u) ? `${fmtEnergy(u.energy_wh, u.energy_kind)} · ` : "";
  const id = `rc-${turn.id}`;
  const chip = h(
    "button",
    {
      class: "receipt-chip",
      type: "button",
      "aria-expanded": String(open),
      "aria-controls": id,
      onclick: () => {
        turn.ui.receipt = !turn.ui.receipt;
        updateTurn(turn);
        document.querySelector(`[data-turn="${turn.id}"] .receipt-chip`)?.focus();
      },
    },
    icon("leaf"),
    h("span", { class: "receipt-chip-text num" }, `${energy}${u.tokens_kind === "estimated" ? "≈ " : ""}${fmtInt(u.prompt_tokens + u.completion_tokens)} ${t("meter.tokens")} · ${fmtSeconds(u.seconds)}`),
    u.tokens_kind === "scripted" && h("span", { class: "tag tag-scripted", text: t("kind.scripted") }),
    icon("chevron", "chev"),
  );
  return h("div", { class: `receipt-fold${open ? " is-open" : ""}` }, chip, open && h("div", { id }, fullReceipt(turn)));
}

function fullReceipt(turn) {
  const u = turn.usage;
  const energy = hasEnergy(u);
  const figure = (value, label, sub, cls = "", tag = null) => {
    const v = h("span", { class: "fig-value num", text: value });
    const l = h("span", { class: "fig-label", text: cls.includes("fig-none") ? `${label} :` : label });
    return h("div", { class: `fig ${cls}` }, cls.includes("fig-none") ? [l, v] : [v, l], tag, sub && h("span", { class: "fig-sub", text: sub }));
  };
  const chips = [
    u.tool_calls === 0
      ? t("meter.tools.zero")
      : u.tool_calls === 1
        ? t("meter.tools.one")
        : t("meter.tools.many", { n: u.tool_calls }),
    u.bytes_fetched > 0 && t("meter.fetched", { v: fmtBytes(u.bytes_fetched) }),
    t(u.thinking ? "meter.thinking.on" : "meter.thinking.off"),
    u.tokens_kind === "scripted" ? `${modelLabel()} (${t("demo.badge")})` : modelLabel(),
  ].filter(Boolean);
  return h(
    "section",
    { class: "receipt", "aria-label": t("meter.label") },
    h(
      "div",
      { class: "receipt-main" },
      h("span", { class: "receipt-mark" }, icon("leaf")),
      h(
        "div",
        { class: "figs" },
        figure(
          `${u.tokens_kind === "estimated" ? "≈ " : ""}${fmtInt(u.prompt_tokens + u.completion_tokens)}`,
          t("meter.tokens"),
          t("meter.tokens.split", {
            in: fmtInt(u.prompt_tokens),
            out: fmtInt(u.completion_tokens),
          }),
          "",
          u.tokens_kind === "scripted" && h("span", { class: "tag tag-scripted", text: t("kind.scripted") }),
        ),
        figure(fmtSeconds(u.seconds), t("meter.time"), turn.wake_s > 0 ? t("meter.wake", { s: fmtSeconds(turn.wake_s) }) : null),
        energy
          ? figure(
              fmtEnergy(u.energy_wh, u.energy_kind),
              t("meter.energy"),
              u.energy_method === "power_time"
                ? t("meter.energy.upper")
                : u.energy_method === "tokens"
                  ? t("meter.energy.tokens")
                  : t(`kind.${u.energy_kind}`),
              "fig-energy",
            )
          : figure(t("meter.energy.none"), t("meter.energy"), null, "fig-none"),
        energy &&
          typeof u.co2_g === "number" &&
          figure(fmtCo2(u.co2_g), t("row.co2"), t("kind.estimated")),
      ),
    ),
    h(
      "p",
      { class: "receipt-chips" },
      chips.map((c) => h("span", { text: c })),
    ),
    // ---- footprint.js mount hook: the answer's emissions, water, graphics-card time and equivalents
    footprintAnswer(u, state.conv, { onOpenPage: () => handlers.onOpenFootprint() }),
    details(
      "receipt-detail",
      turn.ui.meter ?? false,
      (value) => (turn.ui.meter = value),
      [icon("chevron", "chev"), t("meter.detail")],
      meterTable(u),
      h(
        "p",
        { class: "receipt-more" },
        h("button", {
          class: "link",
          type: "button",
          onclick: () => handlers.onOpenFootprint(),
          text: t("meter.open"),
        }),
      ),
    ),
  );
}

// ------------------------------------------------------------------ answer (streaming-stable Markdown)

function paintMarkdown(turn, entry) {
  const streaming = turn.status === "running" && !turn.answer;
  const source = turn.answer ? turn.answer.content : stabilize(turn.text || "");
  const cites = (turn.answer?.sources || []).map((s) => Number(s.n));
  // Long code blocks already on screen keep their open/folded state across re-renders (streaming, final answer)
  entry.expanded ||= new Set();
  for (const fig of entry.md.querySelectorAll("figure.code-block[data-i]")) {
    const i = Number(fig.dataset.i);
    if (fig.hasAttribute("data-collapsed")) entry.expanded.delete(i);
    else entry.expanded.add(i);
  }
  // Safe by construction: renderBlocks escapes all model text before emitting its own tags.
  const blocks = renderBlocks(source, {
    cites,
    anchor: `src-${turn.id}`,
    citeLabel: `${t("sources.title")} {n}`,
    copyCode: t("code.copy.label"),
    copyText: t("code.copy"),
    rich: true, // answer mode: typography, pseudo-headings, callouts, steps, highlighted code
    final: Boolean(turn.answer), // key numbers, pros/cons, folding and syntax badges wait for the whole answer
    lang: state.conv?.lang || state.prefs.lang,
    wrap: wrapPref(),
    codeChecks: turn.answer?.code_checks,
    suppress: turn.answer?.widgets?.length ? ["kpis"] : [], // a structured widget owns the key numbers
    expanded: entry.expanded,
    labels: mdLabels(),
  });
  const md = entry.md;
  let first = 0;
  while (
    first < blocks.length &&
    first < entry.blocks.length &&
    blocks[first] === entry.blocks[first]
  )
    first += 1;
  while (md.children.length > first) md.lastChild.remove();
  if (first < blocks.length)
    md.insertAdjacentHTML("beforeend", blocks.slice(first).join(""));
  entry.blocks = blocks;
  md.classList.toggle("streaming", streaming);
  if (md.querySelector(".md-math")) typeset(md); // self-hosted KaTeX, loaded the first time a formula shows
  if (turn.answer) enhanceAnswer(md, turn); // task boxes, sortable tables, glossary (modules.js)
}

function mdLabels() {
  return {
    text: t("md.lang.text"),
    wrap: t("code.wrap"),
    download: t("code.download"),
    downloadLabel: t("code.download.label"),
    more: t("code.more"),
    less: t("code.less"),
    checkOk: t("code.check.ok"),
    checkJson: t("code.check.json"),
    checkTitle: t("code.check.title"),
    checkErr: t("code.check.err"),
    checkExcerpt: t("code.check.excerpt"),
    copyFormula: t("code.copy.formula"),
    copyTex: t("md.math.copy"),
    copied: t("code.copied.formula"),
    listMore: t("md.more"),
    callout: { note: t("md.callout.note"), tip: t("md.callout.tip"), important: t("md.callout.important"), warn: t("md.callout.warn") },
  };
}

/** The answer as the clipboard takes it: HTML (real headings, lists, tables) and plain text (answers.js). */
export function richCopy(turn) {
  const md = cache.get(turn.id)?.md;
  const out = md
    ? serialize(treeOf(md))
    : { text: String(turn.answer?.content || ""), html: `<meta charset="utf-8"><p>${escapeText(turn.answer?.content || "")}</p>` };
  const extra = widgetsText(turn);
  if (extra) {
    out.text = `${out.text}\n\n${extra}`;
    out.html += extra.split("\n").filter(Boolean).map((line) => `<p>${escapeText(line)}</p>`).join("");
  }
  return out;
}

const escapeText = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function renderActions(turn, isLast) {
  if (turn.status === "running" || turn.status === "confirm" || !turn.answer)
    return null;
  const vote = (value) => () => {
    turn.feedback = turn.feedback === value ? null : value;
    // a thumbs down opens the reasons panel (answers.js); taking it back drops what was said
    turn.ui.fbOpen = turn.feedback === "down";
    turn.ui.fbThanks = false;
    if (turn.feedback !== "down") delete turn.feedbackDetail;
    handlers.onChange(turn);
    if (turn.feedback === "up") toast(t("toast.feedback"), "ok");
    if (turn.ui.fbOpen) requestAnimationFrame(() => document.querySelector(`#fb-${CSS.escape(turn.id)}-t`)?.closest(".fb-panel")?.querySelector(".fb-chip")?.focus());
  };
  const turns = state.conv?.turns || [];
  const at = turns.indexOf(turn);
  // the answers to this question (regenerated): « ‹ 1/2 › »
  const pager = at >= 0 && versionPager(turns, at, (j) => handlers.onVersion(at, j), state.busy);
  return h(
    "div",
    { class: "actions-row", role: "group", "aria-label": t("turn.bird") },
    pager,
    pager && h("span", { class: "actions-sep", "aria-hidden": "true" }),
    button(
      "btn-quiet btn-icon btn-small",
      "copy",
      t("act.copy"),
      (e) => copyAnswer(e.currentTarget, richCopy(turn)), // text/html + text/plain; the icon says « Copié »
      { "data-act": "copy" },
    ),
    isLast &&
      !state.busy &&
      button(
        "btn-quiet btn-icon btn-small",
        "retry",
        t("act.regenerate"),
        () => handlers.onRegenerate(turn),
        { "data-act": "regenerate" },
      ),
    h("span", { class: "actions-sep", "aria-hidden": "true" }),
    button(
      `btn-quiet btn-icon btn-small${turn.feedback === "up" ? " is-on" : ""}`,
      "up",
      t("act.up"),
      vote("up"),
      {
        "aria-pressed": String(turn.feedback === "up"),
        "data-act": "up",
        title: `${t("act.up")} — ${t("act.feedback.note")}`,
      },
    ),
    button(
      `btn-quiet btn-icon btn-small${turn.feedback === "down" ? " is-on" : ""}`,
      "thumbdown",
      t("act.down"),
      vote("down"),
      {
        "aria-pressed": String(turn.feedback === "down"),
        "data-act": "down",
        title: `${t("act.down")} — ${t("act.feedback.note")}`,
      },
    ),
    moreMenu([
      ["markdown", t("act.copy.md"), "copy-md", () => copyText(turn.answer.content, t("toast.copied.md"))],
      ["word", t("act.export.docx.item"), "export-docx", () => handlers.onExport(turn, "docx")],
      ["download", t("act.export.md.item"), "export-md", () => handlers.onExport(turn, "md")],
      // one-click transforms of the last answer (followups.js): a new request, as if typed, grouped behind
      // « Réécrire » with a drawing each (shorter, longer, formal, translate, table, list)
      ...(isLast && !state.busy && handlers.onSuggest
        ? [[
            "edit",
            t("act.rewrite"),
            "rewrite",
            null,
            transforms().map(([label, prompt], i) => [glyph(REWRITE_GLYPHS[i] || "edit"), label, `tf-${i}`, () => handlers.onSuggest(prompt)]),
          ]]
        : []),
    ]),
  );
}

/** The versions of a turn that has no actions row (failed, stopped before any word), or null. */
function pagerRow(turn) {
  const turns = state.conv?.turns || [];
  const at = turns.indexOf(turn);
  const pager = at >= 0 && versionPager(turns, at, (j) => handlers.onVersion(at, j), state.busy);
  return pager ? h("div", { class: "actions-row" }, pager) : null;
}

/** "Plus": a menu button (arrow keys, Home/End, Escape back to the button, closes on outside click). */
function moreMenu(items) {
  let menu = null;
  const trigger = button("btn-quiet btn-icon btn-small", "more", t("act.more"), () => (menu.hidden ? openMenu(0) : closeMenu(false)), {
    "aria-haspopup": "menu",
    "aria-expanded": "false",
    "data-act": "more",
  });
  // [icon, label, act, run, sub?]: an entry with sub opens its list in place (« Réécrire » and its rewrites), with
  // « Retour » first: the menu stays short and every rewrite has its own drawing (answers.js glyph)
  const make = (list, back) => {
    const out = list.map(([ico, label, act, run, sub]) =>
      h(
        "button",
        {
          class: `menu-item${sub ? " menu-parent" : ""}`,
          type: "button",
          role: "menuitem",
          tabindex: "-1",
          "data-act": act,
          ...(sub ? { "aria-haspopup": "menu" } : {}),
          onclick: () => (sub ? show(make(sub, act), 0) : (closeMenu(true), run())),
        },
        typeof ico === "string" ? icon(ico) : ico,
        h("span", { text: label }),
        sub && icon("chevron", "menu-sub-chev"),
      ),
    );
    if (back)
      out.unshift(
        h(
          "button",
          { class: "menu-item menu-back", type: "button", role: "menuitem", tabindex: "-1", "data-act": "menu-back", onclick: () => show(top, top.findIndex((e) => e.dataset.act === back)) },
          icon("back"),
          h("span", { text: t("act.back") }),
        ),
      );
    return out;
  };
  const top = make(items);
  let entries = top;
  const show = (list, index) => {
    entries = list;
    menu.replaceChildren(...list);
    list.at(index)?.focus();
  };
  const onOutside = (e) => !wrap.contains(e.target) && closeMenu(false);
  function openMenu(index) {
    if (entries !== top) show(top, 0);
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    // opens upward when the conversation area has no room below the button (the composer sits there)
    const area = $("scroll").getBoundingClientRect();
    const below = area.bottom - trigger.getBoundingClientRect().bottom;
    menu.classList.toggle("menu-up", below < menu.offsetHeight + 8);
    entries.at(index)?.focus();
    document.addEventListener("pointerdown", onOutside, true);
  }
  function closeMenu(refocus) {
    if (menu.hidden) return;
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", onOutside, true);
    if (refocus) trigger.focus();
  }
  menu = h(
    "div",
    {
      class: "menu",
      role: "menu",
      hidden: true,
      "aria-label": t("act.more"),
      onkeydown: (e) => {
        const i = entries.indexOf(document.activeElement);
        const go = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: entries.length - 1 }[e.key];
        if (go !== undefined) {
          e.preventDefault();
          entries[(go + entries.length) % entries.length].focus();
        } else if (e.key === "ArrowRight" && document.activeElement?.classList.contains("menu-parent")) {
          e.preventDefault();
          document.activeElement.click();
        } else if ((e.key === "ArrowLeft" || e.key === "Escape") && entries !== top) {
          e.preventDefault();
          e.stopPropagation();
          entries[0].click(); // « Retour »
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          closeMenu(true);
        } else if (e.key === "Tab") closeMenu(false);
      },
    },
    entries,
  );
  trigger.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      openMenu(e.key === "ArrowDown" ? 0 : -1);
    }
  });
  const wrap = h("span", { class: "menu-wrap" }, trigger, menu);
  return wrap;
}

// codes whose message is already a sentence written for people (by this page, the server or the endpoint check);
// anything else ("internal", or a code this page does not know) is shown as a plain sentence, the raw text folded away
const FRIENDLY_ERRORS = new Set(
  (
    "waking endpoint_down network offline dropped stopped access_code rate_limited confirm_invalid agent_state_used " +
    "unauthorized wrong_route " +
    "unknown_model blocked disabled not_configured host_not_allowed https_only invalid_url address bad_request " +
    "demo invalid_model invalid_token port server timeout unreachable attachment_invalid attachment_too_long " +
    "attachment_type cross_origin image_invalid image_too_large image_too_small image_type invalid_mode " +
    "invalid_request message_too_long request_too_large too_large too_many_attachments too_many_messages " +
    "pair_required pair_invalid pair_locked"
  ).split(" "),
);

function renderError(turn, isLast) {
  if (!turn.error) return null;
  const code = turn.error.code;
  if (code === "local_unreachable")
    // Bird local did not answer: the three steps to start it, never a raw network error
    return unreachableCard({
      compact: true,
      onRetry: isLast && !state.busy ? () => handlers.onRetry() : null,
      onOff: isLast && handlers.onLocalOff ? () => handlers.onLocalOff() : null,
    });
  if (turn.mode === "local" && MODEL_DOWN.has(code))
    // Bird local answered, its model server (vLLM) did not: the command to start it, not a hosted-endpoint sentence
    return modelDownCard({
      onRetry: isLast && !state.busy ? () => handlers.onRetry() : null,
      onOff: isLast && handlers.onLocalOff ? () => handlers.onLocalOff() : null,
    });
  // the model asleep or paused is not the user's doing: a calm card (moon, no red), in words for people. The
  // server's sentence for a paused endpoint speaks to its administrator: folded away, and only for someone who
  // set their own endpoint in Settings.
  const down = code === "endpoint_down";
  const calm = code === "waking" || down;
  const friendly = FRIENDLY_ERRORS.has(code) || /^http_\d+$/.test(code);
  // an HTTP status without a sentence (a gateway page) gets a plain message; its number stays in the details
  const raw = down
    ? state.prefs.endpoint
      ? turn.error.message || ""
      : ""
    : friendly
      ? /^http_\d+$/.test(code)
        ? turn.error.detail || ""
        : ""
      : turn.error.detail || turn.error.message;
  const done = turn.steps.filter((s) => s.status === "done").length;
  const before =
    !calm && done
      ? h("p", { class: "notice-steps", text: t(done === 1 ? "error.steps.one" : "error.steps.many", { n: done }) })
      : null;
  const needsSettings = [
    "access_code",
    "unauthorized",
    "wrong_route",
    "unknown_model",
    "blocked",
    "disabled",
    "not_configured",
    "host_not_allowed",
    "https_only",
    "invalid_url",
    "pair_required",
    "pair_invalid",
  ].includes(code);
  return h(
    "div",
    {
      class: `notice ${calm ? "notice-calm" : "notice-error"}`,
      role: calm ? "status" : "alert",
    },
    icon(calm ? "moon" : "alert"),
    h(
      "div",
      { class: "notice-text" },
      h("strong", { text: down ? t("error.down.title") : calm ? t("error.waking.title") : t("turn.error") }),
      h("p", {
        text: down ? t("error.down") : calm ? t("error.waking") : friendly ? turn.error.message : t("error.internal"),
      }),
      before,
      raw &&
        h(
          "details",
          { class: "notice-details" },
          h("summary", { text: t("error.details") }),
          h("pre", { text: raw.slice(0, 400) }),
        ),
    ),
    h(
      "div",
      { class: "notice-actions" },
      needsSettings &&
        button("btn-outline btn-small", "gear", t("error.settings"), () =>
          handlers.onOpenSettings(),
        ),
      // any failed turn can be tried again, even after later messages: a new version from there (« ‹ 1/2 › »)
      !state.busy &&
        button(
          "btn-outline btn-small",
          "retry",
          t("turn.retry"),
          () => handlers.onRetry(turn),
          { "data-act": "retry" },
        ),
    ),
  );
}

/** "D'après : facture.pdf" — the attachments this answer actually read, linked to their card in the message. */
function renderCharts(turn) {
  const charts = (turn.answer?.charts || [])
    .filter((c) => c && typeof c === "object")
    .slice(0, 3);
  if (!charts.length) return null;
  turn.ui.charts = turn.ui.charts || {};
  return h(
    "div",
    { class: "cards chart-cards" },
    charts.map((spec, i) => {
      // charts are drawn once per turn and kept: a re-render (streaming, a toggle) must not reset hover or focus
      const key = `${spec.id || i}:${state.prefs.lang}`;
      if (!turn.ui.charts[key])
        turn.ui.charts[key] = renderChart(spec, {
          lang: state.prefs.lang,
          onXlsx: (s) => handlers.onChartXlsx?.(turn, s),
        });
      return turn.ui.charts[key];
    }),
  );
}

const IMG_OK = /^\/(?:api\/img\?|static\/demo\/)/;

function webImageTile(turn, img) {
  const page = safeUrl(img.page);
  const domain = String(img.domain || hostOf(img.page) || "");
  const title = String(img.title || domain);
  const frame = h("span", { class: "web-image-frame" });
  const el = h("img", {
    src: img.src,
    alt: String(img.alt || title),
    width: "168",
    height: "126",
    loading: "lazy",
    decoding: "async",
    referrerpolicy: "no-referrer",
  });
  // an image that does not load (expired link, upstream error) is removed, not shown as an empty frame; the
  // section goes when none is left
  el.addEventListener(
    "error",
    () => {
      const li = el.closest("li");
      const list = li?.parentElement;
      li?.remove();
      if (list && !list.children.length) list.closest("section")?.remove();
    },
    { once: true },
  );
  frame.append(el);
  if (img.demo)
    frame.append(
      h("span", { class: "tag web-image-badge", text: t("webimg.demo") }),
    );
  const n = Number(img.n) || 0;
  const cap = h(
    "span",
    { class: "web-image-cap" },
    h("span", { class: "web-image-title", text: title }),
    h(
      "span",
      { class: "web-image-host" },
      n ? h("span", { class: "web-image-n num", text: `[${n}]` }) : null,
      h("span", { text: domain }),
    ),
  );
  return page
    ? h(
        "a",
        {
          class: "web-image",
          href: page,
          target: "_blank",
          rel: "noopener noreferrer",
          "aria-label": t("webimg.open", { title, domain }),
        },
        frame,
        cap,
      )
    : h("span", { class: "web-image" }, frame, cap);
}

function renderWebImages(turn) {
  const images = (turn.answer?.web_images || [])
    .filter((x) => x && typeof x === "object" && typeof x.src === "string" && IMG_OK.test(x.src))
    .slice(0, 4); // 3 beside a web answer, up to 4 when pictures were asked (backends.pick_web_images)
  if (!images.length) return null;
  // kept between re-renders: an image that already loaded (or failed) is not fetched or laid out again
  if (turn.ui.webImagesLang !== state.prefs.lang) {
    turn.ui.webImages = webImagesSection(turn, images);
    turn.ui.webImagesLang = state.prefs.lang;
  }
  return turn.ui.webImages.querySelector("li") ? turn.ui.webImages : null;
}

function webImagesSection(turn, images) {
  return h(
    "section",
    { class: "web-images", "aria-label": t("webimg.aria") },
    h("h3", { class: "eyebrow", text: t("webimg.title") }),
    h(
      "ul",
      { class: "web-image-list" },
      images.map((img) => h("li", null, webImageTile(turn, img))),
    ),
    h("p", { class: "web-image-note", text: t("webimg.note") }),
  );
}

function basedOn(turn) {
  if (!turn.answer) return null;
  const names = [
    ...new Set(
      turn.steps
        .filter((s) => (s.tool === "read_file" || s.tool === "read_image") && s.status === "done")
        .map((s) => String(s.arguments?.path || s.arguments?.name || "").split("/").pop())
        .filter(Boolean),
    ),
  ];
  if (!names.length) return null;
  return h(
    "p",
    { class: "based-on" },
    h("span", { class: "based-label", text: t("att.basedon") }),
    names.map((name) =>
      h(
        "button",
        {
          class: `based-chip ${kindOf(name).cls}`,
          type: "button",
          title: name,
          onclick: () => {
            const card = [...document.querySelectorAll("[data-att]")].find((x) => x.dataset.att === name);
            if (card) {
              card.scrollIntoView({ block: "center" });
              card.focus();
            }
          },
        },
        icon(/\.(jpe?g|png|webp)$/i.test(name) ? "image" : "file"),
        middle(name, 28),
      ),
    ),
  );
}

function quoteFirst(turn) {
  const list = turn.answer?.widgets?.length ? turn.answer.widgets : turn.widgets || [];
  return list.some((w) => w && w.type === "quote");
}

function widgetsFor(turn, entry) {
  // the answer's cards, or the ones sent as each pre-called tool returned (`widget` event): shown while the model
  // writes, and kept when it fails
  const list = turn.answer?.widgets?.length ? turn.answer.widgets : turn.widgets || [];
  if (!list.length) return null;
  if (entry.widgetsOf !== list) {
    entry.widgetsOf = list;
    // the answer's cards are most often the early ones again: the same cards keep their DOM (and its state: an
    // open full screen, an expanded list); others are drawn again and take over a full screen left open
    const key = JSON.stringify(list);
    if (key !== entry.widgetsKey) {
      entry.widgetsKey = key;
      const old = entry.widgets;
      entry.widgets = renderWidgets(turn, list);
      moveFull(old, entry.widgets);
    }
  }
  return entry.widgets;
}

/** The focused control of a turn, as a selector and its rank among the matches, so a redraw can give it back. */
function focusKey(el) {
  const a = document.activeElement;
  if (!a || a === el || !el.contains(a)) return null;
  // a map open in full screen keeps its node across redraws: the focused control itself is given back
  if (a.closest(".widget-places.is-full")) return { node: a };
  const sel = a.hasAttribute("data-crew-summary")
    ? "[data-crew-summary]"
    : a.dataset.act
      ? `[data-act="${CSS.escape(a.dataset.act)}"]`
      : null;
  if (!sel) return null;
  return { sel, rank: [...el.querySelectorAll(sel)].indexOf(a), crew: !!a.closest(".crew") };
}

function restoreFocus(el, key) {
  if (key?.node) {
    if (key.node.isConnected && document.activeElement !== key.node) key.node.focus({ preventScroll: true });
    return;
  }
  if (!key || el.contains(document.activeElement)) return;
  const all = el.querySelectorAll(key.sel);
  // the way out of a team that just finished is gone: its folded line takes the focus, never <body>
  const next = all[key.rank] || all[0] || (key.crew ? el.querySelector("[data-crew-summary]") : null);
  next?.focus({ preventScroll: true });
}

/**
 * The plan, the steps and the flight of a finished answer as ONE folded line (« 2 étapes · Fiche encyclopédique ·
 * Recherche web · Hirondelle · 1,3 s »); open, it shows the plan's items, the steps' timeline and the flight's
 * summary and checks, unchanged. Not merged: while it runs, when something needs the reader (a plan done in part,
 * a suspicious page, an approval) or when there is only one of them.
 */
function workLine(turn, plan, steps, flight) {
  const parts = [plan, steps, flight].filter(Boolean);
  if (parts.length < 2 || turn.status !== "done" || turn.crew) return null;
  if (plan?.querySelector(".tplan-partial") || steps?.querySelector(".badge-warn, .badge-await")) return null;
  const level = flight?.dataset.level;
  const own = turn.steps.filter((s) => !s.agent);
  const n = own.length;
  const total = own.reduce((sum, s) => sum + (s.seconds || 0), 0);
  const names = [...new Set(own.map((s) => toolLabel(s.tool)))].join(" · ");
  const badge = flight?.querySelector(".rf-badge")?.cloneNode(true);
  const planCount = plan?.querySelector(".tplan-count")?.textContent || "";
  const flightHead = [flight?.querySelector(".rf-line")?.textContent, flight?.querySelector(".rf-meta")?.textContent]
    .filter(Boolean)
    .join(" · ");
  return details(
    "steps worklog",
    turn.ui.work ?? false,
    (value) => (turn.ui.work = value),
    [
      icon("chevron", "chev"),
      badge,
      h("span", { class: "steps-count", text: n ? (n === 1 ? t("steps.count.one") : t("steps.count.many", { n })) : planCount }),
      h("span", {
        class: "steps-names",
        text: [names, level && t(`rf.level.${level}`)].filter(Boolean).join(" · "),
      }),
      total > 0 && h("span", { class: "num steps-time", text: fmtSeconds(total) }),
    ],
    h(
      "div",
      { class: "work-body" },
      plan && [h("p", { class: "work-h", text: [t("plan.title"), planCount].join(" · ") }), plan.querySelector(".tplan-list")],
      steps && [h("p", { class: "work-h", text: t("steps.title") }), steps.querySelector("ol.timeline")],
      // Mode Réflexion's flight gives its summary and checks; a plain reasoning keeps its own fold
      flight && (level ? [h("p", { class: "work-h", text: flightHead }), flight.querySelector(".rf-body")] : flight),
    ),
  );
}

function fillAssistant(el, turn, isLast) {
  // the turn is redrawn on every event (each agent_step of a team): the focused control keeps the focus, or a
  // keyboard user is sent back to the top of the page and Escape on <body> would stop the answer
  const focus = focusKey(el);
  let entry = cache.get(turn.id);
  if (!entry) {
    entry = { md: h("div", { class: "md" }), blocks: [] };
    cache.set(turn.id, entry);
  }
  const hasText = !!(turn.answer || turn.text);
  if (hasText) paintMarkdown(turn, entry);
  const mode = turn.mode || activeMode();
  const planEl = renderPlan(turn);
  const stepsEl = renderSteps(turn.crew ? { ...turn, steps: turn.steps.filter((s) => !s.agent) } : turn); // crew steps sit in their lane
  // Mode Réflexion: « Bird a pris son vol en Faucon », the reasoning summary, the checks, the full reasoning
  const flightEl =
    renderFlight(
      turn,
      details,
      turn.reasoning &&
        details(
          "reasoning rf-full",
          turn.ui.reasoning ?? false,
          (value) => (turn.ui.reasoning = value),
          [icon("chevron", "chev"), t("rf.full")],
          h("div", { class: "reasoning-body", text: turn.reasoning }),
        ),
    ) ||
      (turn.reasoning &&
        details(
          "reasoning",
          turn.ui.reasoning ?? false,
          (value) => (turn.ui.reasoning = value),
          [icon("chevron", "chev"), icon("spark"), t("reasoning.title")],
          h("div", { class: "reasoning-body", text: turn.reasoning }),
        ));
  // a finished answer opens on one folded line at most: the plan, the steps and the flight together (R25)
  const work = workLine(turn, planEl, stepsEl, flightEl);
  const children = [
    byline(entry, turn, mode),
    renderAgents(turn, handlers),
    ...(work ? [work] : [planEl, stepsEl, flightEl]),
    hasText && entry.md,
    turn.answer?.fallback && h("p", { class: "answer-note", "data-notice": "fallback", text: turn.answer.fallback }),
    // markets: the quote card (its period chips) comes before the chart it drives (finance.js)
    quoteFirst(turn) && widgetsFor(turn, entry),
    renderCharts(turn),
    renderWebImages(turn),
    !quoteFirst(turn) && widgetsFor(turn, entry),
    turn.crew?.done && renderChecks(turn), // « Vérifications faites »: the team's checks, figure by figure
    canvasCard(turn), // the deck, document, page or sheet of this turn, in the canvas
    basedOn(turn),
    (!turn.crew || turn.crew.done || turn.live?.state === "waking") && liveLine(turn),
    renderConfirm(turn),
    renderSources(turn),
    renderFailedFiles(turn),
    renderFiles(turn),
    renderEmail(turn),
    renderError(turn, isLast),
    turn.status !== "stopped" &&
      turn.answer?.stop_reason === "repetition" &&
      h(
        "div",
        { class: "stopped", "data-notice": "looped" },
        icon("pause"),
        h("span", { text: t("turn.looped") }),
        isLast &&
          !state.busy &&
          button("btn-outline btn-small", "retry", t("turn.restart"), () => handlers.onRetry(turn), { "data-act": "restart" }),
      ),
    turn.status === "stopped" &&
      h(
        "div",
        { class: "stopped" },
        icon("pause"),
        h("span", { text: turn.stoppedAt ? t("turn.stopped.at", { step: toolLabel(turn.stoppedAt) }) : t("turn.stopped") }),
        // words already written: « Continuer » picks up from there (Régénérer stays in the actions row); none: Relancer
        isLast &&
          !state.busy &&
          (turn.answer?.content
            ? button("btn-outline btn-small", "send", t("cx.continue"), () => handlers.onContinue(turn), { "data-act": "continue" })
            : button("btn-outline btn-small", "retry", t("turn.restart"), () => handlers.onRetry(turn), { "data-act": "restart" })),
      ),
    renderActions(turn, isLast),
    turn.ui?.fbOpen &&
      turn.answer &&
      feedbackPanel(turn, {
        onSave: (detail) => {
          turn.feedbackDetail = detail; // kept with the conversation, in this browser only
          turn.ui.fbOpen = false;
          turn.ui.fbThanks = true;
          handlers.onChange(turn);
          setTimeout(() => {
            turn.ui.fbThanks = false; // the thank-you is a moment, not a fixture under the answer
            handlers.onChange(turn);
          }, 6000);
        },
        onClose: () => {
          turn.ui.fbOpen = false;
          handlers.onChange(turn);
          document.querySelector(`[data-turn="${CSS.escape(turn.id)}"] [data-act="down"]`)?.focus();
        },
      }),
    turn.ui?.fbThanks && turn.feedback === "down" && feedbackThanks(),
    // a failed or stopped turn without text still shows its versions (it was a retry)
    !turn.answer && turn.status !== "running" && pagerRow(turn),
    isLast && handlers.onSuggest && renderChips(turn, handlers.onSuggest, state.busy),
    renderReceipt(turn, isLast),
  ];
  const kids = children.filter(Boolean);
  if (kids[0] === entry.byline && el.firstChild === entry.byline) {
    // the header stays attached (its wing animation keeps running); only what follows it is replaced
    while (el.lastChild !== entry.byline) el.lastChild.remove();
    el.append(...kids.slice(1));
  } else {
    el.replaceChildren(...kids);
  }
  restoreFocus(el, focus);
  el.querySelector(".widget-places.is-full")?._reinert?.();
  el.setAttribute("aria-busy", String(turn.status === "running"));
}

// The bird mark next to « Bird »: body and two wings as separate paths, so the wings can beat while an answer is
// being prepared (CSS .byline.is-flying). A constant drawn here, never model output.
const SVG_NS = "http://www.w3.org/2000/svg";
const MARK_PATHS = [
  ["body", "M5 49C15 45.5 26 40.5 36 34.5c3-1.8 5.2-5.1 8.4-7.1 3.9-2.4 8.6-1.5 10.8 1.9L61.5 30.4l-5.6 2.3c-1 3.1-3.4 5.7-6.9 7.4C38 45.2 22 49.5 5 49z"],
  ["wing-back", "M40.5 31.5C38.5 21 30 10.5 14.5 5.5c4.2 6.8 6.2 14.2 8.2 20.9 1.3 4.3 3.3 8.2 6.8 11.3z"],
  ["wing-front", "M43.5 28.5c.5-7.8 3.8-15.8 10.8-22.3-1 5.9-.3 10.7-.8 15.3-.3 3.2-1.7 5.8-4.6 7.6z"],
];
// Kept across re-renders of the turn (one per streamed chunk): a new header would restart the wing animation.
function byline(entry, turn, mode) {
  if (!entry.byline || entry.bylineMode !== mode) {
    entry.bylineMode = mode;
    entry.byline = h(
      "header",
      { class: "byline" },
      birdMark(),
      h("h2", { class: "byline-name", text: t("turn.bird") }),
      mode === "demo" &&
        h("span", {
          class: "badge badge-demo",
          title: t("demo.note"),
          text: t("demo.badge"),
        }),
    );
  }
  entry.byline.classList.toggle("is-flying", turn.status === "running");
  return entry.byline;
}

function birdMark() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "byline-mark");
  svg.setAttribute("viewBox", "0 0 64 56");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const [part, d] of MARK_PATHS) {
    const p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("class", `mark-${part}`);
    p.setAttribute("d", d);
    svg.appendChild(p);
  }
  return svg;
}

let editingTurn = null; // the question being edited in place, if any

/** Edit the question turns[i] in place (the last one by default): the bubble becomes an editor. */
export function editUser(turn) {
  if (state.busy || !turn || turn.role !== "user") return;
  editingTurn = turn;
  renderConversation();
}

function renderUser(turn, i) {
  const turns = state.conv?.turns || [];
  const files = (turn.attachments || []).length > 0 || (turn.images || []).length > 0;
  if (editingTurn === turn && !state.busy) {
    const done = () => {
      editingTurn = null;
      renderConversation();
      document.querySelectorAll("#conversation > .turn")[i]?.querySelector('[data-act="edit"]')?.focus({ preventScroll: true });
    };
    return h(
      "article",
      { class: "turn turn-user is-editing" },
      h("h2", { class: "sr-only", text: t("turn.you") }),
      inlineEditor(turn.content, {
        keeps: files,
        onCancel: done,
        onSend: (text) => {
          editingTurn = null;
          handlers.onEditSend(i, text);
        },
      }),
    );
  }
  if (editingTurn === turn) editingTurn = null;
  const pager = versionPager(turns, i, (j) => handlers.onVersion(i, j), state.busy);
  return h(
    "article",
    { class: "turn turn-user cx-has-acts" },
    h("h2", { class: "sr-only", text: t("turn.you") }),
    h(
      "div",
      { class: "bubble-wrap" },
      h(
        "div",
        { class: "bubble" },
        (turn.images || []).length > 0 &&
          h(
            "div",
            { class: "bubble-gallery", role: "list", "aria-label": t("att.gallery") },
            turn.images.map((img, k) =>
              h(
                "div",
                { role: "listitem", "data-att": img.name },
                imageCard(img, {
                  compact: true,
                  onOpen: () => handlers.onLightbox(turn.images, k),
                }),
              ),
            ),
          ),
        h("p", { class: "bubble-text", text: turn.content }),
        (turn.attachments || []).length > 0 &&
          h(
            "div",
            { class: "bubble-files" },
            turn.attachments.map((a) => {
              const doc = typeof a === "string" ? { name: a } : a;
              const full = (state.conv?.attachments || []).find((x) => x.name === doc.name);
              const excerpt = full && full.encoding !== "base64" && full.content ? full.content : "";
              return docCard(doc, { compact: true, excerpt });
            }),
          ),
      ),
    ),
    // every question can be copied, edited in place (a new version from there) and shows its versions
    h(
      "div",
      { class: "cx-user-acts", role: "group", "aria-label": t("turn.you") },
      pager,
      button("btn-quiet btn-icon btn-small", "copy", t("cx.copy.user"), () => copyText(turn.content, t("cx.copied.user")), {
        "data-act": "copy-user",
      }),
      !state.busy &&
        button("btn-quiet btn-icon btn-small", "edit", t("cx.edit"), () => editUser(turn), { "data-act": "edit" }),
    ),
  );
}

export function renderConversation() {
  const root = $("conversation");
  const turns = state.conv?.turns || [];
  const keep = new Set(
    turns.filter((x) => x.role === "assistant").map((x) => x.id),
  );
  for (const id of cache.keys()) if (!keep.has(id)) cache.delete(id);
  root.replaceChildren(
    ...turns.map((turn, i) => {
      if (turn.role === "user")
        return turn.hidden ? h("div", { class: "turn turn-hidden", hidden: true }) : renderUser(turn, i);
      turn.ui = turn.ui || {};
      const el = h("article", {
        class: "turn turn-bird",
        "data-turn": turn.id,
      });
      fillAssistant(el, turn, i === turns.length - 1);
      return el;
    }),
  );
}

export function updateTurn(turn) {
  const el = document.querySelector(`[data-turn="${turn.id}"]`);
  const turns = state.conv?.turns || [];
  if (el) fillAssistant(el, turn, turns[turns.length - 1] === turn);
}

/** Cheap path while tokens stream in: only the Markdown blocks that changed are touched. */
export function updateStream(turn) {
  const entry = cache.get(turn.id);
  if (!entry || !entry.md.isConnected) return updateTurn(turn);
  paintMarkdown(turn, entry);
}

export function forgetRendered() {
  cache.clear();
}

// ------------------------------------------------------------------ export as Markdown

export function exportMarkdown(conv) {
  const lines = [`# ${conv.title || t("export.title")}`, ""];
  for (const turn of conv.turns) {
    if (turn.role === "user") {
      lines.push(`## ${t("turn.you")}`, "", turn.content, "");
      if ((turn.attachments || []).length)
        lines.push(turn.attachments.map((n) => `- ${n}`).join("\n"), "");
      continue;
    }
    lines.push(`## ${t("turn.bird")}`, "");
    for (const s of turn.steps || [])
      lines.push(
        `- ${toolLabel(s.tool)}${target(s.tool, s.arguments) ? ` : ${target(s.tool, s.arguments)}` : ""} (${t(`status.${s.status}`)})`,
      );
    if ((turn.steps || []).length) lines.push("");
    if (turn.answer) lines.push(turn.answer.content, "");
    for (const chart of turn.answer?.charts || [])
      lines.push(
        `**${t("chart.export")} : ${chart.title}**`,
        "",
        chartMarkdown(chart, state.prefs.lang),
        "",
      );
    for (const img of turn.answer?.web_images || [])
      lines.push(`- ${t("webimg.export")} : ${img.title} — ${img.page}`);
    if ((turn.answer?.web_images || []).length) lines.push("");
    const extra = turn.answer ? widgetsText(turn, true) : "";
    if (extra) lines.push(extra, "");
    const draft = turn.answer?.draft_email;
    if (draft)
      lines.push(
        `> **${t("email.title")}** — ${t("email.to")} ${Array.isArray(draft.to) ? draft.to.join(", ") : draft.to}`,
        `> **${draft.subject}**`,
        ">",
        ...String(draft.body)
          .split("\n")
          .map((l) => `> ${l}`),
        "",
      );
    for (const s of turn.answer?.sources || [])
      lines.push(`${s.n}. ${s.title} — ${s.url}`);
    if ((turn.answer?.sources || []).length) lines.push("");
    if (turn.usage) {
      const u = turn.usage;
      const energy = hasEnergy(u)
        ? `${fmtEnergy(u.energy_wh, u.energy_kind)} (${t(`kind.${u.energy_kind}`)})`
        : t("meter.energy.none.long");
      lines.push(
        `*${t("export.footprint")} : ${t("meter.tokens.split", { in: fmtInt(u.prompt_tokens), out: fmtInt(u.completion_tokens) })} · ${fmtSeconds(u.seconds)} · ${energy} · ${u.model}*`,
        "",
      );
    }
  }
  return lines.join("\n");
}
