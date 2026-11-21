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
  h,
  hasEnergy,
  icon,
  state,
  t,
  toast,
  toolLabel,
  modelLabel,
} from "./core.js";
import { renderBlocks, safeUrl, stabilize } from "./markdown.js";

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
  return str("query") || str("path") || str("title") || str("subject") || "";
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
    text = t("live.waking");
    sub = t("live.waking.sub", { n: turn.live.attempt || 1 });
    calm = true;
  } else if (running) {
    const key = `live.${running.tool}`;
    const label = t(key) === key ? t("live.tool") : t(key);
    const what = target(running.tool, running.arguments);
    text = what ? `${label} : ${what}…` : `${label}…`;
  } else if (turn.text) text = t("live.writing");
  else text = t(turn.thinking ? "live.thinking" : "live.starting");
  return h(
    "div",
    { class: `live${calm ? " live-calm" : ""}` },
    h("span", { class: calm ? "pulse" : "spinner", "aria-hidden": "true" }),
    h(
      "div",
      null,
      h("p", { class: "live-text", text }),
      sub && h("p", { class: "live-sub", text: sub }),
    ),
  );
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

function renderSteps(turn) {
  if (!turn.steps.length) return null;
  const flagged = turn.steps.some((s) =>
    (s.flags || []).includes("possible_injection"),
  );
  const total = turn.steps.reduce((sum, s) => sum + (s.seconds || 0), 0);
  const n = turn.steps.length;
  turn.ui.stepOpen = turn.ui.stepOpen || {};
  const items = turn.steps.map((step) => {
    const injection = (step.flags || []).includes("possible_injection");
    const statusIcon = { done: "check", error: "cross", denied: "ban" }[
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
            h("span", { class: "sr-only", text: t(`status.${step.status}`) }),
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
          h("p", { class: "eyebrow", text: t("steps.args") }),
          h("dl", { class: "kv" }, argRows(step.arguments)),
          (step.preview || step.summary) &&
            h("p", { class: "eyebrow", text: t("steps.result") }),
          step.summary && h("p", { class: "step-summary", text: step.summary }),
          step.preview && h("p", { class: "step-preview", text: step.preview }),
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
      turn.status !== "running" &&
        total > 0 &&
        h("span", { class: "num steps-time", text: fmtSeconds(total) }),
    ],
    h("ol", { class: "timeline", "aria-label": t("steps.title") }, items),
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

function filePreview(preview) {
  if (!preview || typeof preview !== "object") return null;
  if (preview.kind === "slides") {
    return h(
      "ol",
      { class: "outline" },
      (preview.slides || []).map((s, i) =>
        h(
          "li",
          null,
          h("span", { class: "outline-n num", text: String(i + 1) }),
          h(
            "div",
            null,
            h("p", { class: "outline-title", text: String(s.title || "") }),
            h(
              "ul",
              null,
              (s.bullets || []).map((b) => h("li", { text: String(b) })),
            ),
          ),
        ),
      ),
    );
  }
  if (preview.kind === "document") {
    return h(
      "div",
      { class: "doc-preview" },
      (preview.sections || []).map((s) =>
        h(
          "section",
          null,
          h("p", { class: "outline-title", text: String(s.heading || "") }),
          h("p", { text: String(s.content || "") }),
        ),
      ),
    );
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
          ? t("files.slides", { n: (p.slides || []).length })
          : p.kind === "document"
            ? t("files.sections", { n: (p.sections || []).length })
            : p.kind === "sheet"
              ? t("files.rows", { n: p.total_rows || 0 })
              : "";
      const kind =
        {
          slides: "make_slides",
          document: "make_document",
          sheet: "make_sheet",
        }[p.kind] || "file";
      const preview = filePreview(p);
      return h(
        "section",
        { class: "card file-card", "data-file": name },
        h(
          "header",
          { class: "card-head" },
          h("span", { class: "card-icon" }, icon(kind)),
          h(
            "div",
            { class: "card-title" },
            h("p", { class: "card-name", text: p.title || name }),
            h("p", {
              class: "card-meta",
              text: [ext, meta, file.size ? fmtBytes(file.size) : ""]
                .filter(Boolean)
                .join(" · "),
            }),
          ),
          file.data
            ? button(
                "btn-primary btn-small",
                "download",
                t("files.download"),
                () =>
                  download(
                    name,
                    file.mime || "application/octet-stream",
                    new Blob([b64ToBytes(file.data)], {
                      type: file.mime || "application/octet-stream",
                    }),
                  ),
              )
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
  // A mailto: link the user chooses to click. It only opens their own mail app with the draft: nothing is sent.
  const mailto = `mailto:${to
    .split(",")
    .map((s) => encodeURIComponent(s.trim()))
    .filter(Boolean)
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
        h("p", { class: "card-meta", text: `${t("email.to")} ${to || "—"}` }),
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
          `why.energy.${usage.energy_kind}`,
          { source: usage.energy_source || "?" },
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
      meterRows(usage).map(([label, value, kind, why, vars]) =>
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

function renderReceipt(turn) {
  const u = turn.usage;
  if (!u) return null;
  const energy = hasEnergy(u);
  const figure = (value, label, sub, cls = "") =>
    h(
      "div",
      { class: `fig ${cls}` },
      h("span", { class: "fig-value num", text: value }),
      h("span", { class: "fig-label", text: label }),
      sub && h("span", { class: "fig-sub", text: sub }),
    );
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
          fmtInt(u.prompt_tokens + u.completion_tokens),
          t("meter.tokens"),
          t("meter.tokens.split", {
            in: fmtInt(u.prompt_tokens),
            out: fmtInt(u.completion_tokens),
          }),
        ),
        figure(fmtSeconds(u.seconds), t("meter.time")),
        energy
          ? figure(
              fmtEnergy(u.energy_wh, u.energy_kind),
              t("meter.energy"),
              t(`kind.${u.energy_kind}`),
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
  return md ? md.innerText.trim() : String(turn.answer?.content || "");
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
    button(
      "btn-quiet btn-icon btn-small",
      "markdown",
      t("act.copy.md"),
      () => copyText(turn.answer.content, t("toast.copied.md")),
      { "data-act": "copy-md" },
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
  );
}

function renderError(turn, isLast) {
  if (!turn.error) return null;
  const code = turn.error.code;
  const calm = code === "waking";
  const needsSettings = [
    "access_code",
    "unauthorized",
    "wrong_route",
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
      h("p", { text: calm ? t("error.waking") : turn.error.message }),
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
    liveLine(turn),
    renderConfirm(turn),
    renderSources(turn),
    renderFiles(turn),
    renderEmail(turn),
    renderError(turn, isLast),
    turn.status === "stopped" &&
      h("p", { class: "stopped", text: t("turn.stopped") }),
    renderActions(turn, isLast),
    renderReceipt(turn),
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
        h("p", { class: "bubble-text", text: turn.content }),
        (turn.attachments || []).length > 0 &&
          h(
            "p",
            { class: "bubble-files" },
            turn.attachments.map((name) =>
              h("span", { class: "chip-file" }, icon("file"), name),
            ),
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
