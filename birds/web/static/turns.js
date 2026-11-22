// Rendering of a conversation: user bubbles, Bird's turns (live status, steps, answer, cards, receipt).
import {
  $,
  activeMode,
  b64ToBytes,
  button,
  copyText,
  download,
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
import { docCard, imageCard, kindOf, middle } from "./attach.js";
import { deckPreview, docPreview, sheetPreview } from "./previews.js";

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
  let retry = null;
  if (turn.live?.state === "waking") {
    text = t("live.waking");
    sub = t("live.waking.sub", { n: turn.live.attempt || 1 });
    calm = true;
    const wait = Number(turn.live.retry_in);
    if (wait >= 0) {
      const at = String((turn.live.at || Date.now()) + wait * 1000);
      retry = h("span", { class: "num", "data-retry-at": at, text: retryText(Number(at)) });
    }
  } else if (running) {
    const key = `live.${running.tool}`;
    const label = t(key) === key ? t("live.tool") : t(key);
    const what = target(running.tool, running.arguments);
    text = what ? `${label} : ${what}…` : `${label}…`;
  } else if (turn.text) text = t("live.writing");
  else if (turn.steps.some((s) => s.status === "done")) text = t("live.reading"); // a tool finished: Bird reads it, then writes
  else text = t(turn.thinking ? "live.thinking" : "live.starting");
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
    h("span", { class: calm ? "pulse" : "spinner", "aria-hidden": "true" }),
    h(
      "div",
      null,
      h(
        "p",
        { class: "live-text" },
        h("span", { text }),
        h("span", { class: "live-time num", "data-since": String(since), "aria-hidden": "true", text: elapsed(since) }),
      ),
      sub ? h("p", { class: "live-sub" }, retry && [retry, " · "], sub) : auto,
    ),
  );
}

function retryText(at) {
  const left = Math.max(0, Math.ceil((at - Date.now()) / 1000));
  return left > 0 ? t("live.retry.in", { n: left }) : t("live.retry.now");
}

function autoSub(started, first) {
  const s = (Date.now() - started) / 1000;
  if (s < 3) return first ? t("live.first") : "";
  if (s < 8) return "";
  return t(s < 20 ? "live.slow" : "live.slower");
}

const elapsed = (since) => {
  const s = Math.max(0, Math.round((Date.now() - Number(since)) / 1000));
  return s < 1 ? "" : s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")}`;
};
/** Called every second while a request runs: only the small timers change, nothing else is redrawn. */
export function tick() {
  for (const el of document.querySelectorAll("[data-since]")) el.textContent = elapsed(el.dataset.since);
  for (const el of document.querySelectorAll("[data-retry-at]")) el.textContent = retryText(Number(el.dataset.retryAt));
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
              class: `badge badge-src${step.info.fallback_from ? " badge-warn" : ""}`,
              title: step.info.fallback_from
                ? t("steps.fallback", { from: step.info.fallback_from, label: step.info.label })
                : t("steps.via", { label: step.info.label }),
              text: step.info.label,
            }),
          injection &&
            h(
              "span",
              { class: "badge badge-warn" },
              icon("alert"),
              t("steps.flagged"),
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

function renderSources(turn) {
  const sources = turn.answer?.sources || [];
  if (!sources.length) return null;
  return h(
    "section",
    { class: "sources", "aria-label": t("sources.title") },
    h("h3", { class: "eyebrow", text: t("sources.title") }),
    h(
      "ol",
      { class: "source-list" },
      sources.map((source) => {
        const url = safeUrl(source.url);
        const title = String(source.title || source.url || "");
        const n = Number(source.n) || 0;
        return h(
          "li",
          { id: `src-${turn.id}-${n}`, tabindex: "-1" },
          h("span", { class: "source-n num", text: String(n || "") }),
          h(
            "span",
            { class: "source-body" },
            url
              ? h("a", {
                  href: url,
                  target: "_blank",
                  rel: "noopener noreferrer",
                  text: title,
                })
              : h("span", { text: title }),
            url && h("span", { class: "source-host", text: hostOf(url) }),
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

function filePreview(preview, onDownload) {
  if (!preview || typeof preview !== "object") return null;
  if (preview.v === 2) {
    // what the file really holds (read back by the server), drawn in the file's own design
    if (preview.kind === "slides") {
      const deck = deckPreview(preview, { onDownload });
      return deck && h("div", null, deck, preview.notes > 0 && h("p", { class: "hint", text: t("files.notes", { n: preview.notes }) }));
    }
    if (preview.kind === "document") return docPreview(preview, { onDownload });
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
  const files = (turn.files || []).filter(
    (f) => f && typeof f.name === "string",
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
      const preview = filePreview(p, save);
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
  const hint = [String(draft.to_hint ?? "").trim(), ...parts.filter((s) => !isAddress(s))]
    .filter(Boolean)
    .join(", ");
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
        h("p", {
          class: "card-meta",
          text: [
            addresses.length || !hint ? `${t("email.to")} ${addresses.join(", ") || "—"}` : "",
            hint ? `${t("email.tohint")} ${hint}` : "",
          ]
            .filter(Boolean)
            .join(" · "),
        }),
      ),
    ),
    h("div", { class: "email-body", text: body }),
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
          usage.energy_method === "power_time" ? "why.energy.power" : `why.energy.${usage.energy_kind}`,
          usage.energy_method === "power_time"
            ? {
                gpu: usage.energy_basis?.gpu || "GPU",
                s: fmtSig(usage.energy_basis?.busy_seconds || 0),
                pue: fmtSig(usage.energy_basis?.pue || 1),
              }
            : { source: usage.energy_source || "?" },
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

export function meterTable(usage) {
  return h(
    "table",
    { class: "meter-table" },
    h(
      "tbody",
      null,
      meterRows(usage).filter(Boolean).map(([label, value, kind, why, vars]) =>
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
          h("td", { class: "meter-why", text: t(why, vars) }),
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
              u.energy_method === "power_time" ? t("meter.energy.upper") : t(`kind.${u.energy_kind}`),
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
  // Safe by construction: renderBlocks escapes all model text before emitting its own tags.
  const blocks = renderBlocks(source, {
    cites,
    anchor: `src-${turn.id}`,
    citeLabel: `${t("sources.title")} {n}`,
    copyCode: t("code.copy.label"),
    copyText: t("code.copy"),
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
}

export function plainText(turn) {
  const md = cache.get(turn.id)?.md;
  if (!md) return String(turn.answer?.content || "");
  const heads = [...md.querySelectorAll(".code-head")]; // the language label and "Copy" are not part of the answer
  for (const el of heads) el.hidden = true;
  const text = md.innerText.trim();
  for (const el of heads) el.hidden = false;
  return text;
}

function renderActions(turn, isLast) {
  if (turn.status === "running" || turn.status === "confirm" || !turn.answer)
    return null;
  const vote = (value) => () => {
    turn.feedback = turn.feedback === value ? null : value;
    handlers.onChange(turn);
    if (turn.feedback) toast(t("toast.feedback"), "ok");
  };
  return h(
    "div",
    { class: "actions-row", role: "group", "aria-label": t("turn.bird") },
    button(
      "btn-quiet btn-icon btn-small",
      "copy",
      t("act.copy"),
      () => copyText(plainText(turn)),
      { "data-act": "copy" },
    ),
    isLast &&
      !state.busy &&
      button(
        "btn-quiet btn-icon btn-small",
        "retry",
        t("act.regenerate"),
        () => handlers.onRegenerate(),
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
    ]),
  );
}

/** "Plus": a menu button (arrow keys, Home/End, Escape back to the button, closes on outside click). */
function moreMenu(items) {
  let menu = null;
  const trigger = button("btn-quiet btn-icon btn-small", "more", t("act.more"), () => (menu.hidden ? openMenu(0) : closeMenu(false)), {
    "aria-haspopup": "menu",
    "aria-expanded": "false",
    "data-act": "more",
  });
  const entries = items.map(([ico, label, act, run]) =>
    h(
      "button",
      { class: "menu-item", type: "button", role: "menuitem", tabindex: "-1", "data-act": act, onclick: () => (closeMenu(true), run()) },
      icon(ico),
      h("span", { text: label }),
    ),
  );
  const onOutside = (e) => !wrap.contains(e.target) && closeMenu(false);
  function openMenu(index) {
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
    "waking network offline dropped stopped access_code rate_limited confirm_invalid unauthorized wrong_route " +
    "unknown_model blocked disabled not_configured host_not_allowed https_only invalid_url address bad_request " +
    "demo invalid_model invalid_token port server timeout unreachable attachment_invalid attachment_too_long " +
    "attachment_type cross_origin image_invalid image_too_large image_too_small image_type invalid_mode " +
    "invalid_request message_too_long request_too_large too_large too_many_attachments too_many_messages"
  ).split(" "),
);

function renderError(turn, isLast) {
  if (!turn.error) return null;
  const code = turn.error.code;
  const calm = code === "waking";
  const friendly = FRIENDLY_ERRORS.has(code) || /^http_\d+$/.test(code);
  // an HTTP status without a sentence (a gateway page) gets a plain message; its number stays in the details
  const raw = friendly
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
      h("strong", { text: calm ? t("error.waking.title") : t("turn.error") }),
      h("p", { text: calm ? t("error.waking") : friendly ? turn.error.message : t("error.internal") }),
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
      isLast &&
        !state.busy &&
        button(
          "btn-outline btn-small",
          "retry",
          t("turn.retry"),
          () => handlers.onRetry(),
          { "data-act": "retry" },
        ),
    ),
  );
}

/** "D'après : facture.pdf" — the attachments this answer actually read, linked to their card in the message. */
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

function fillAssistant(el, turn, isLast) {
  let entry = cache.get(turn.id);
  if (!entry) {
    entry = { md: h("div", { class: "md" }), blocks: [] };
    cache.set(turn.id, entry);
  }
  const hasText = !!(turn.answer || turn.text);
  if (hasText) paintMarkdown(turn, entry);
  const mode = turn.mode || activeMode();
  const children = [
    h(
      "header",
      { class: "byline" },
      h("h2", { class: "byline-name", text: t("turn.bird") }),
      mode === "demo" &&
        h("span", {
          class: "badge badge-demo",
          title: t("demo.note"),
          text: t("demo.badge"),
        }),
    ),
    renderSteps(turn),
    turn.reasoning &&
      details(
        "reasoning",
        turn.ui.reasoning ?? false,
        (value) => (turn.ui.reasoning = value),
        [icon("chevron", "chev"), icon("spark"), t("reasoning.title")],
        h("div", { class: "reasoning-body", text: turn.reasoning }),
      ),
    hasText && entry.md,
    basedOn(turn),
    liveLine(turn),
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
          button("btn-outline btn-small", "retry", t("turn.restart"), () => handlers.onRetry(), { "data-act": "restart" }),
      ),
    turn.status === "stopped" &&
      h(
        "div",
        { class: "stopped" },
        icon("pause"),
        h("span", { text: turn.stoppedAt ? t("turn.stopped.at", { step: toolLabel(turn.stoppedAt) }) : t("turn.stopped") }),
        isLast &&
          !state.busy &&
          button("btn-outline btn-small", "retry", t("turn.restart"), () => handlers.onRetry(), { "data-act": "restart" }),
      ),
    renderActions(turn, isLast),
    renderReceipt(turn, isLast),
  ];
  el.replaceChildren(...children.filter(Boolean));
  el.setAttribute("aria-busy", String(turn.status === "running"));
}

function renderUser(turn, isLastUser) {
  return h(
    "article",
    { class: "turn turn-user" },
    h("h2", { class: "sr-only", text: t("turn.you") }),
    h(
      "div",
      { class: "bubble-wrap" },
      isLastUser &&
        !state.busy &&
        button(
          "btn-quiet btn-icon btn-small bubble-edit",
          "edit",
          t("act.edit"),
          () => handlers.onEdit(),
          { "data-act": "edit" },
        ),
      h(
        "div",
        { class: "bubble" },
        (turn.images || []).length > 0 &&
          h(
            "div",
            { class: "bubble-gallery", role: "list", "aria-label": t("att.gallery") },
            turn.images.map((img, i) =>
              h(
                "div",
                { role: "listitem", "data-att": img.name },
                imageCard(img, {
                  compact: true,
                  onOpen: () => handlers.onLightbox(turn.images, i),
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
  );
}

export function renderConversation() {
  const root = $("conversation");
  const turns = state.conv?.turns || [];
  const keep = new Set(
    turns.filter((x) => x.role === "assistant").map((x) => x.id),
  );
  for (const id of cache.keys()) if (!keep.has(id)) cache.delete(id);
  const lastUser = turns.map((x) => x.role).lastIndexOf("user");
  root.replaceChildren(
    ...turns.map((turn, i) => {
      if (turn.role === "user")
        return renderUser(turn, i === lastUser && i >= turns.length - 2);
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
