// Secondary views: the footprint ("Empreinte"), settings, about, welcome, keyboard help.
import {
  $,
  activeMode,
  activeModel,
  button,
  fmtBytes,
  fmtCo2,
  fmtEnergy,
  fmtInt,
  fmtSeconds,
  fmtSig,
  h,
  hasEnergy,
  icon,
  resetPrefs,
  savePrefs,
  state,
  store,
  t,
  toast, modelLabel } from "./core.js";

let hooks = {};
// replaceChildren would print null/false as text: drop them first
const put = (el, ...children) => el.replaceChildren(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
export const setViewHooks = (value) => (hooks = value);

// ------------------------------------------------------------------ footprint ledger (all-time, local)

const LEDGER_KEY = "bird.ledger";
const LEDGER_MAX = 400;

export function ledgerAdd(usage, convId) {
  const entries = store.json(LEDGER_KEY, []);
  entries.push({ ...usage, type: undefined, ts: Date.now(), conv: convId });
  store.set(LEDGER_KEY, JSON.stringify(entries.slice(-LEDGER_MAX)));
}
export const ledgerAll = () =>
  store
    .json(LEDGER_KEY, [])
    .filter((u) => u && typeof u.prompt_tokens === "number");
export const ledgerReset = () => store.set(LEDGER_KEY, null);

export function convUsages(conv) {
  return (conv?.turns || [])
    .filter((x) => x.role === "assistant" && x.usage)
    .map((x) => x.usage);
}

export function totals(usages) {
  const sum = (key) =>
    usages.reduce((total, u) => total + (Number(u[key]) || 0), 0);
  const withEnergy = usages.filter(hasEnergy);
  const withCo2 = withEnergy.filter((u) => typeof u.co2_g === "number");
  return {
    n: usages.length,
    prompt: sum("prompt_tokens"),
    completion: sum("completion_tokens"),
    seconds: sum("seconds"),
    tools: sum("tool_calls"),
    bytes: sum("bytes_fetched"),
    energyN: withEnergy.length,
    energy: withEnergy.reduce((total, u) => total + u.energy_wh, 0),
    energyKind: withEnergy.some((u) => u.energy_kind === "estimated")
      ? "estimated"
      : "measured",
    co2N: withCo2.length,
    co2: withCo2.reduce((total, u) => total + u.co2_g, 0),
  };
}

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {}))
    el.setAttribute(key, value);
  el.append(...children);
  return el;
}
function topRounded(x, y, w, hgt, r) {
  const rr = Math.min(r, hgt, w / 2);
  return `M${x} ${y + hgt}V${y + rr}a${rr} ${rr} 0 0 1 ${rr}-${rr}h${w - 2 * rr}a${rr} ${rr} 0 0 1 ${rr} ${rr}V${y + hgt}z`;
}

function chart(all) {
  const usages = all.slice(-40);
  const offset = all.length - usages.length;
  const barW = 14;
  const gap = 8;
  const height = 120;
  const plot = height - 10;
  const max = Math.max(
    1,
    ...usages.map((u) => u.prompt_tokens + u.completion_tokens),
  );
  const width = Math.max(usages.length * (barW + gap) + gap, 160);
  const readout = h("p", {
    class: "chart-readout num",
    text: t("fp.chart.hint"),
  });
  const el = svg("svg", {
    class: "chart",
    viewBox: `0 0 ${width} ${height}`,
    width,
    height,
    role: "group",
    "aria-label": t("fp.chart"),
  });
  el.append(
    svg("line", {
      class: "chart-axis",
      x1: 0,
      x2: width,
      y1: height - 0.5,
      y2: height - 0.5,
    }),
  );
  usages.forEach((u, i) => {
    const x = gap + i * (barW + gap);
    const hIn = Math.max(
      u.prompt_tokens > 0 ? 2 : 0,
      (u.prompt_tokens / max) * (plot - 2),
    );
    const hOut = Math.max(
      u.completion_tokens > 0 ? 2 : 0,
      (u.completion_tokens / max) * (plot - 2),
    );
    const extra =
      (u.thinking ? t("fp.bar.thinking") : "") +
      (u.tool_calls ? t("fp.bar.tools", { n: u.tool_calls }) : "");
    const label = t("fp.bar", {
      i: offset + i + 1,
      in: fmtInt(u.prompt_tokens),
      out: fmtInt(u.completion_tokens),
      extra,
    });
    const group = svg("g", {
      class: "chart-bar",
      tabindex: "0",
      role: "img",
      "aria-label": label,
    });
    group.append(
      svg("rect", {
        class: "chart-hit",
        x: x - gap / 2,
        y: 0,
        width: barW + gap,
        height,
      }),
      svg("rect", {
        class: "series-in",
        x,
        y: height - 1 - hIn,
        width: barW,
        height: hIn,
      }),
      svg("path", {
        class: "series-out",
        d: topRounded(x, height - 1 - hIn - 2 - hOut, barW, hOut, 4),
      }),
    );
    if (u.thinking)
      group.append(
        svg("circle", {
          class: "chart-dot",
          cx: x + barW / 2,
          cy: Math.max(4, height - 1 - hIn - 2 - hOut - 6),
          r: 2.2,
        }),
      );
    const show = () => (readout.textContent = label);
    group.addEventListener("mouseenter", show);
    group.addEventListener("focus", show);
    el.append(group);
  });
  return h(
    "figure",
    { class: "panel chart-figure" },
    h(
      "figcaption",
      null,
      h("span", {
        class: "eyebrow",
        text:
          all.length > usages.length
            ? `${t("fp.chart")} · ${t("fp.chart.last", { n: usages.length })}`
            : t("fp.chart"),
      }),
      h(
        "span",
        { class: "legend" },
        h(
          "span",
          { class: "legend-item" },
          h("span", { class: "swatch swatch-in" }),
          t("fp.legend.in"),
        ),
        h(
          "span",
          { class: "legend-item" },
          h("span", { class: "swatch swatch-out" }),
          t("fp.legend.out"),
        ),
        h(
          "span",
          { class: "legend-item" },
          h("span", { class: "swatch swatch-dot" }),
          t("composer.thinking").toLowerCase(),
        ),
      ),
    ),
    h("div", { class: "chart-scroll" }, el),
    readout,
    h(
      "details",
      { class: "chart-table" },
      h("summary", null, icon("chevron", "chev"), t("fp.table")),
      h(
        "table",
        null,
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            h("th", { scope: "col", text: t("fp.col.answer") }),
            h("th", { scope: "col", text: t("row.prompt") }),
            h("th", { scope: "col", text: t("row.completion") }),
            h("th", { scope: "col", text: t("row.seconds") }),
          ),
        ),
        h(
          "tbody",
          null,
          usages.map((u, i) =>
            h(
              "tr",
              null,
              h("th", {
                scope: "row",
                class: "num",
                text: String(offset + i + 1),
              }),
              h("td", { class: "num", text: fmtInt(u.prompt_tokens) }),
              h("td", { class: "num", text: fmtInt(u.completion_tokens) }),
              h("td", { class: "num", text: fmtSeconds(u.seconds) }),
            ),
          ),
        ),
      ),
    ),
  );
}

function splitRow(label, usages, max) {
  const n = usages.length;
  const tokens = usages.reduce(
    (sum, u) => sum + u.prompt_tokens + u.completion_tokens,
    0,
  );
  const avg = n ? Math.round(tokens / n) : 0;
  const bar = h(
    "span",
    { class: "split-bar" },
    h("span", { class: "split-fill" }),
  );
  bar.firstChild.style.inlineSize = `${max ? Math.max(n ? 2 : 0, (avg / max) * 100) : 0}%`; // CSSOM, allowed by the CSP
  return h(
    "div",
    { class: "split-row" },
    h("span", { class: "split-label", text: label }),
    bar,
    h("span", {
      class: "split-value num",
      text: n ? t("fp.split.avg", { n: fmtInt(n), avg: fmtInt(avg) }) : "—",
    }),
  );
}

function splits(usages) {
  const avgOf = (list) =>
    list.length
      ? list.reduce((s, u) => s + u.prompt_tokens + u.completion_tokens, 0) /
        list.length
      : 0;
  const on = usages.filter((u) => u.thinking);
  const off = usages.filter((u) => !u.thinking);
  const withTools = usages.filter((u) => u.tool_calls > 0);
  const without = usages.filter((u) => !u.tool_calls);
  const max = Math.max(
    avgOf(on),
    avgOf(off),
    avgOf(withTools),
    avgOf(without),
    1,
  );
  return h(
    "section",
    { class: "panel" },
    h("h3", { class: "eyebrow", text: t("fp.split") }),
    h("p", { class: "split-title", text: t("fp.split.thinking") }),
    splitRow(t("fp.split.off"), off, max),
    splitRow(t("fp.split.on"), on, max),
    h("p", { class: "split-title", text: t("fp.split.tools") }),
    splitRow(t("fp.split.without"), without, max),
    splitRow(t("fp.split.with"), withTools, max),
  );
}

function comparison(usages) {
  const avg = (list) =>
    list.reduce((s, u) => s + u.prompt_tokens + u.completion_tokens, 0) /
    list.length;
  const on = usages.filter((u) => u.thinking);
  const off = usages.filter((u) => !u.thinking);
  if (!on.length || !off.length) return null;
  const a = avg(on);
  const b = avg(off);
  const x = a >= b ? a / Math.max(b, 1) : b / Math.max(a, 1);
  const ratio =
    x < 1.15
      ? t("fp.compare.same")
      : t(a >= b ? "fp.compare.more" : "fp.compare.less", {
          x: fmtSig(Math.round(x * 10) / 10),
        });
  return h(
    "section",
    { class: "panel panel-accent", "data-compare": "1" },
    h("h3", { class: "eyebrow", text: t("fp.compare.title") }),
    h("p", {
      text: t("fp.compare.text", {
        on: fmtInt(Math.round(a)),
        off: fmtInt(Math.round(b)),
        ratio,
      }),
    }),
    h("p", {
      class: "hint",
      text: t("fp.compare.note", { a: on.length, b: off.length }),
    }),
  );
}

let scope = "conv";
export function renderFootprint() {
  const body = $("view-footprint-body");
  const usages = scope === "all" ? ledgerAll() : convUsages(state.conv);
  const s = totals(usages);
  const demo = activeMode() === "demo";
  const gi = state.health?.grid_intensity_g_per_kwh;
  const eq = state.health?.equivalent;
  const partial = (k) => (k < s.n ? t("fp.partial", { k, n: s.n }) : "");
  const stat = (label, value, sub, cls = "") =>
    h(
      "div",
      { class: `stat ${cls}` },
      h("dt", { text: label }),
      h(
        "dd",
        null,
        h("span", { class: "stat-value num", text: value }),
        sub && h("span", { class: "stat-sub", text: sub }),
      ),
    );
  const seg = (value, label) =>
    h("button", {
      class: `seg${scope === value ? " is-on" : ""}`,
      type: "button",
      role: "radio",
      "aria-checked": String(scope === value),
      "data-scope": value,
      onclick: () => ((scope = value), renderFootprint()),
      text: label,
    });
  const head = h(
    "div",
    { class: "segs", role: "radiogroup", "aria-label": t("fp.scope") },
    seg("conv", t("fp.scope.conv")),
    seg("all", t("fp.scope.all")),
  );
  const how = h(
    "section",
    { class: "panel" },
    h("h3", { class: "eyebrow", text: t("fp.how") }),
    h(
      "ul",
      { class: "how" },
      ["counted", "measured", "estimated", "unavailable"].map((k) =>
        h(
          "li",
          null,
          h("span", { class: `tag tag-${k}`, text: t(`kind.${k}`) }),
          h("span", { text: t(`fp.how.${k}`).replace(/^[^:]+:\s*/, "") }),
        ),
      ),
    ),
    typeof gi === "number" &&
      h("p", { class: "hint", text: t("fp.method", { gi: fmtSig(gi) }) }),
  );
  if (!s.n) {
    put(body, 
      head,
      h("p", { class: "panel panel-empty", text: t("fp.empty") }),
      demo && h("p", { class: "demo-note", text: t("demo.note") }),
      how,
      h("p", { class: "hint", text: t("fp.note") }),
    );
    return;
  }
  const energyStat = s.energyN
    ? stat(
        t("fp.energy"),
        fmtEnergy(s.energy, s.energyKind),
        [t(`kind.${s.energyKind}`), partial(s.energyN)]
          .filter(Boolean)
          .join(" · "),
        "stat-wide",
      )
    : stat(
        t("fp.energy"),
        t("meter.energy.none.long"),
        t(demo && scope === "conv" ? "why.energy.demo" : "why.energy.none"),
        "stat-wide stat-none",
      );
  const co2Stat = s.co2N
    ? stat(
        t("fp.co2"),
        fmtCo2(s.co2),
        [t("kind.estimated"), partial(s.co2N)].filter(Boolean).join(" · "),
        "stat-wide",
      )
    : stat(
        t("fp.co2"),
        t("co2.none"),
        t(s.energyN ? "why.co2.nogrid" : "why.co2.noenergy"),
        "stat-wide stat-none",
      );
  // An everyday comparison only when the operator configured a factor AND its source; never a built-in guess.
  const equivalent =
    s.energyN && eq && eq.wh > 0 && eq.label && eq.source
      ? h(
          "section",
          { class: "panel", "data-equivalent": "1" },
          h("p", {
            text: t("fp.equiv", {
              n: fmtSig(s.energy / eq.wh),
              label: eq.label,
            }),
          }),
          h("p", {
            class: "hint",
            text: t("fp.equiv.source", {
              wh: fmtSig(eq.wh),
              source: eq.source,
            }),
          }),
        )
      : null;
  put(body, 
    head,
    h(
      "dl",
      { class: "stats" },
      stat(
        t("fp.tokens"),
        fmtInt(s.prompt + s.completion),
        t("meter.tokens.split", {
          in: fmtInt(s.prompt),
          out: fmtInt(s.completion),
        }),
        "stat-hero",
      ),
      stat(t("fp.answers"), fmtInt(s.n)),
      stat(t("fp.time"), fmtSeconds(s.seconds)),
      stat(t("fp.tools"), fmtInt(s.tools)),
      stat(t("fp.fetched"), fmtBytes(s.bytes)),
      energyStat,
      co2Stat,
    ),
    equivalent,
    chart(usages),
    scope === "conv" ? comparison(usages) : null,
    splits(usages),
    how,
    demo && h("p", { class: "demo-note", text: t("demo.note") }),
    h("p", { class: "hint", text: t("fp.note") }),
    scope === "all" &&
      button("btn-outline btn-small", "trash", t("fp.reset"), () => {
        if (window.confirm(t("fp.reset.confirm"))) {
          ledgerReset();
          renderFootprint();
        }
      }),
  );
}

// ------------------------------------------------------------------ settings

function field(id, label, hint, control) {
  return h(
    "div",
    { class: "field" },
    h("label", { for: id, text: label }),
    control,
    hint && h("p", { class: "hint", id: `${id}-hint`, text: hint }),
  );
}

export function renderSettings() {
  const body = $("view-settings-body");
  const p = state.prefs;
  const hl = state.health || {};
  const modes = hl.modes || { demo: true };
  const mode = activeMode();
  const select = (id, value, options, onchange) =>
    h(
      "select",
      { id, onchange: (e) => onchange(e.target.value) },
      options.map(([v, label]) =>
        h("option", { value: v, selected: v === value }, label),
      ),
    );

  const modeCard = (value, title, hint, enabled) =>
    h(
      "label",
      {
        class: `mode${mode === value ? " is-on" : ""}${enabled ? "" : " is-off"}`,
      },
      h("input", {
        type: "radio",
        name: "mode",
        value,
        checked: mode === value,
        disabled: !enabled,
        onchange: () => apply({ mode: value }),
      }),
      h(
        "span",
        { class: "mode-text" },
        h("span", { class: "mode-title", text: title }),
        h("span", { class: "mode-hint", text: hint }),
      ),
    );

  const result = h("p", {
    class: "test-result",
    id: "endpoint-result",
    role: "status",
    "aria-live": "polite",
  });
  const urlInput = h("input", {
    id: "set-endpoint",
    type: "url",
    inputmode: "url",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "https://xxxx.endpoints.huggingface.cloud",
    value: p.endpoint,
    "aria-describedby": "set-endpoint-hint",
  });
  const tokenInput = h("input", {
    id: "set-token",
    type: "password",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "hf_…",
    value: p.token,
    "aria-describedby": "set-token-hint",
  });
  const modelInput = h("input", {
    id: "set-model",
    type: "text",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "bird",
    value: p.model,
    "aria-describedby": "set-model-hint",
  });
  const accessInput = h("input", {
    id: "set-access",
    type: "password",
    autocomplete: "off",
    value: p.access,
    "aria-describedby": "set-access-hint",
  });
  const reveal = h("button", {
    class: "btn btn-outline btn-small",
    type: "button",
    "aria-pressed": "false",
    "aria-controls": "set-token",
    text: t("set.endpoint.show"),
  });
  reveal.addEventListener("click", () => {
    const show = tokenInput.type === "password";
    tokenInput.type = show ? "text" : "password";
    reveal.textContent = t(show ? "set.endpoint.hide" : "set.endpoint.show");
    reveal.setAttribute("aria-pressed", String(show));
  });
  const collect = () => ({
    endpoint: urlInput.value.trim(),
    token: tokenInput.value.trim(),
    model: modelInput.value.trim(),
    access: accessInput.value.trim(),
  });
  function apply(patch, quiet) {
    Object.assign(state.prefs, collect(), patch || {});
    savePrefs();
    if (patch) hooks.onPrefs(); // a mode, language or theme change redraws the app
    else hooks.onSaved(); // a typed field is only saved: redrawing here would steal the next click
    if (!quiet) toast(t("toast.saved"), "ok");
  }
  for (const input of [urlInput, tokenInput, modelInput, accessInput])
    input.addEventListener("change", () => apply(null, true));

  const testBtn = button(
    "btn-outline",
    "check",
    t("set.endpoint.test"),
    async () => {
      apply(null, true);
      testBtn.disabled = true;
      result.className = "test-result";
      result.textContent = t("set.endpoint.testing");
      const out = await hooks.testEndpoint();
      testBtn.disabled = false;
      result.className = `test-result ${out.ok ? "is-ok" : out.status === "waking" ? "is-calm" : "is-bad"}`;
      result.replaceChildren(
        icon(out.ok ? "check" : out.status === "waking" ? "moon" : "alert"),
        h("span", { text: out.message }),
      );
      result.dataset.status = out.status;
    },
  );
  testBtn.id = "endpoint-test";

  const hosts = (hl.endpoint_hosts || ["*.endpoints.huggingface.cloud"]).join(
    ", ",
  );
  put(body, 
    h(
      "section",
      {
        class: "panel",
        id: "settings-model",
        "aria-labelledby": "set-model-title",
      },
      h("h3", { id: "set-model-title", text: t("set.model") }),
      h("p", { class: "hint", text: t("set.model.lead") }),
      h(
        "div",
        {
          class: "modes",
          role: "radiogroup",
          "aria-labelledby": "set-model-title",
        },
        modeCard("demo", t("set.mode.demo"), t("set.mode.demo.hint"), true),
        modeCard(
          "server",
          t("set.mode.server"),
          modes.server
            ? t("set.mode.server.hint", { model: hl.model || "bird" })
            : t("set.mode.server.off"),
          !!modes.server,
        ),
        modeCard(
          "user",
          t("set.mode.user"),
          modes.user ? t("set.mode.user.hint") : t("set.mode.user.off"),
          !!modes.user,
        ),
      ),
      modes.user &&
        h(
          "fieldset",
          { class: "endpoint", disabled: mode !== "user" },
          h("legend", { class: "sr-only", text: t("set.mode.user") }),
          field(
            "set-endpoint",
            t("set.endpoint.url"),
            t("set.endpoint.url.hint", { hosts }),
            urlInput,
          ),
          field(
            "set-token",
            t("set.endpoint.token"),
            t("set.endpoint.token.hint"),
            h("div", { class: "input-row" }, tokenInput, reveal),
          ),
          field(
            "set-model",
            t("set.endpoint.model"),
            t("set.endpoint.model.hint"),
            modelInput,
          ),
          h(
            "p",
            { class: "tradeoff" },
            icon("info"),
            h("span", { text: t("set.endpoint.tradeoff") }),
          ),
        ),
      (hl.access_required || p.access) &&
        field(
          "set-access",
          t("set.access"),
          t(hl.access_required ? "set.access.needed" : "set.access.hint"),
          accessInput,
        ),
      mode !== "demo" && h("div", { class: "test-row" }, testBtn, result),
    ),
    h(
      "section",
      { class: "panel", "aria-labelledby": "set-general-title" },
      h("h3", { id: "set-general-title", text: t("set.general") }),
      field(
        "set-lang",
        t("set.lang"),
        null,
        select(
          "set-lang",
          p.lang,
          [
            ["fr", "Français"],
            ["en", "English"],
          ],
          (v) => apply({ lang: v }),
        ),
      ),
      field(
        "set-theme",
        t("set.theme"),
        null,
        select(
          "set-theme",
          p.theme,
          [
            ["system", t("set.theme.system")],
            ["light", t("set.theme.light")],
            ["dark", t("set.theme.dark")],
          ],
          (v) => apply({ theme: v }),
        ),
      ),
      h(
        "label",
        { class: "check" },
        h("input", {
          type: "checkbox",
          id: "set-thinking",
          checked: !!p.thinking,
          onchange: (e) => apply({ thinking: e.target.checked }),
        }),
        h(
          "span",
          null,
          h("span", { class: "check-title", text: t("set.thinking") }),
          h("span", { class: "hint", text: t("set.thinking.hint") }),
        ),
      ),
    ),
    h(
      "section",
      { class: "panel", "aria-labelledby": "set-data-title" },
      h("h3", { id: "set-data-title", text: t("set.data") }),
      h("p", { class: "hint", text: t("set.data.lead") }),
      button("btn-outline btn-danger", "trash", t("set.data.reset"), () => {
        if (!window.confirm(t("set.data.reset.confirm"))) return;
        for (const key of store.keys("bird.")) store.set(key, null);
        resetPrefs();
        savePrefs();
        hooks.onReset();
        toast(t("toast.cleared"), "ok");
      }),
    ),
  );
}

// ------------------------------------------------------------------ about, welcome, shortcuts

export function renderAbout() {
  const block = (title, ...children) =>
    h("section", { class: "panel" }, h("h3", { text: title }), ...children);
  put($("view-about-body"), 
    h(
      "div",
      { class: "about-brand" },
      h("img", { class: "lockup only-light", src: "/static/brand/logo-stacked.svg", alt: "Bird S 4B", width: "87", height: "112" }),
      h("img", { class: "lockup only-dark", src: "/static/brand/logo-stacked-dark.svg", alt: "Bird S 4B", width: "87", height: "112" }),
      h("p", { class: "page-lead", text: t("about.tagline") }),
    ),
    block(t("about.what"), h("p", { text: t("about.what.p") })),
    block(t("about.deal"), h("p", { text: t("about.deal.p") })),
    block(t("about.built"), h("p", { text: t("about.built.p") })),
    block(
      t("about.data"),
      h(
        "ul",
        { class: "data-list" },
        h(
          "li",
          null,
          icon("check"),
          h("span", { text: t("about.data.browser") }),
        ),
        h(
          "li",
          null,
          icon("send"),
          h("span", { text: t("about.data.server") }),
        ),
        h(
          "li",
          null,
          icon("read_page"),
          h("span", { text: t("about.data.web") }),
        ),
      ),
    ),
    block(t("about.meter"), h("p", { text: t("about.meter.p") })),
    h("p", {
      class: "hint",
      text: t("about.current", {
        model: activeModel(),
        mode: t(`mode.${activeMode()}`),
      }),
    }),
  );
}

export function openWelcome() {
  const dialog = $("welcome");
  const point = (ico, title, text) =>
    h(
      "li",
      null,
      h("span", { class: "card-icon" }, icon(ico)),
      h(
        "div",
        null,
        h("p", { class: "welcome-point", text: title }),
        h("p", { text }),
      ),
    );
  put($("welcome-body"), 
    h(
      "ul",
      { class: "welcome-list" },
      point("spark", t("welcome.small"), t("welcome.small.p")),
      point("leaf", t("welcome.frugal"), t("welcome.frugal.p")),
      point("eye", t("welcome.honest"), t("welcome.honest.p")),
    ),
    h("p", { class: "hint", text: t("welcome.local") }),
  );
  if (!dialog.open) dialog.showModal();
  $("welcome-start").focus();
}

export function openShortcuts() {
  const mac = /Mac|iPhone|iPad/.test(navigator.platform || "");
  const mod = mac ? "⌘" : "Ctrl";
  const row = (keys, label) =>
    h(
      "div",
      null,
      h(
        "dt",
        null,
        keys.map((k) => h("kbd", { text: k })),
      ),
      h("dd", { text: label }),
    );
  put($("shortcuts-body"), 
    h(
      "dl",
      { class: "keys" },
      row([mod, "K"], t("keys.new")),
      row(["/"], t("keys.focus")),
      row(
        ["Entrée"].map((k) => (state.prefs.lang === "en" ? "Enter" : k)),
        t("keys.send"),
      ),
      row(
        [
          state.prefs.lang === "en" ? "Shift" : "Maj",
          state.prefs.lang === "en" ? "Enter" : "Entrée",
        ],
        t("keys.newline"),
      ),
      row([state.prefs.lang === "en" ? "Esc" : "Échap"], t("keys.stop")),
      row([mod, "B"], t("keys.side")),
      row(["/"], t("keys.slash")),
      row(["?"], t("keys.help")),
    ),
  );
  const dialog = $("shortcuts");
  if (!dialog.open) dialog.showModal();
}
