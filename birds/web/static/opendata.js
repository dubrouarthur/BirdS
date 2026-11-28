// Open-data cards under an answer: holidays and working days, entity (Wikipedia + Wikidata), public tenders
// (BOAMP), scholarly works (OpenAlex, Crossref), communes and addresses (geo.api.gouv.fr, BAN), and the source
// line of a statistics chart. Data come only from the server's widgets (tool results, never model text).
// Built with h() only (text nodes, no innerHTML with data); every card shows « Données : … » with the licence.
import { button, copyText, h, icon, state } from "./core.js";
import { safeUrl } from "./markdown.js";

const lang = () => (state.prefs.lang === "en" ? "en" : "fr");
const locale = () => (lang() === "en" ? "en-GB" : "fr-FR");
const nf = (o) => new Intl.NumberFormat(locale(), o);
const IMG_SRC = /^\/api\/img\?u=[^"'\s<>]+$/;
const MAP_SRC =
  /^(\/api\/map\?t=[A-Za-z0-9_\-.]+|\/static\/demo\/[0-9a-f]{16}\.webp)$/;

const S = {
  fr: {
    data: "Données",
    "cal.title": "Calendrier",
    "cal.workdays": "jours ouvrés",
    "cal.workable": "jours ouvrables",
    "cal.holidays": "jours fériés",
    "cal.workdays.hint": "lundi-vendredi, fériés exclus",
    "cal.workable.hint": "lundi-samedi, fériés exclus",
    "cal.year": "Jours fériés {year}",
    "cal.regional": "régional",
    "cal.regional.note":
      "Les jours marqués « régional » ne sont fériés que dans une partie du pays : ils ne sont pas retirés du décompte.",
    "cal.holiday": "Férié",
    "cal.weekend": "Week-end",
    "cal.workday": "Jour ouvré",
    "cal.deadline": "{n} jours ouvrés après le {start}",
    "cal.skipped": "Fériés sautés",
    "cal.none": "Aucun jour férié sur la période",
    "cal.copy": "Copier la date",
    "cal.legend.holiday": "férié",
    "cal.legend.target": "date cherchée",
    "ent.title": "Fiche",
    "ent.more": "Lire sur Wikipédia",
    "ent.extract": "Extrait de Wikipédia",
    "ent.facts": "Données Wikidata",
    "ent.image": "Image",
    "ten.title": "Appels d'offres publics",
    "ten.count": "{n} avis publiés depuis le {since}",
    "ten.count1": "1 avis publié depuis le {since}",
    "ten.none":
      "Aucun avis publié depuis le {since}. Élargissez la période ou les mots-clés.",
    "ten.deadline": "Réponse avant le {date}",
    "ten.closed": "Clôturé",
    "ten.left": "J-{n}",
    "ten.today": "Dernier jour",
    "ten.published": "Publié le {date}",
    "ten.open": "Voir l'avis",
    "pap.title": "Publications",
    "pap.count": "{n} résultats",
    "pap.cited": "Les plus citées parmi les {n} plus pertinentes",
    "pap.recent": "Publiées depuis 3 ans",
    "pap.cites": "{n} citations",
    "pap.cites1": "1 citation",
    "pap.oa": "Accès ouvert",
    "pap.doi.ok": "DOI vérifié",
    "pap.doi.ko": "DOI introuvable",
    "pap.doi.ko.note":
      "Crossref ne connaît pas ce DOI : il n'existe pas ou il est mal recopié.",
    "pap.none": "Aucune publication trouvée.",
    "com.title": "Commune",
    "com.homonyms": "{n} communes portent ce nom",
    "com.address": "Adresse normalisée",
    "com.insee": "Code INSEE",
    "com.cp": "Code postal",
    "com.cps": "Codes postaux",
    "com.pop": "Population",
    "com.dept": "Département",
    "com.region": "Région",
    "com.surface": "Superficie",
    "com.score": "Correspondance {s} %",
    "com.weak": "Correspondance faible : à vérifier",
    "com.copy": "Copier l'adresse",
    "com.inh": "{n} hab.",
    "map.alt": "Carte de {name}",
    "chart.data": "Données : {label}",
    "chart.updated": "mise à jour {date}",
  },
  en: {
    data: "Data",
    "cal.title": "Calendar",
    "cal.workdays": "working days",
    "cal.workable": "working days incl. Saturdays",
    "cal.holidays": "public holidays",
    "cal.workdays.hint": "Monday to Friday, holidays excluded",
    "cal.workable.hint": "Monday to Saturday, holidays excluded",
    "cal.year": "Public holidays {year}",
    "cal.regional": "regional",
    "cal.regional.note":
      "Days marked “regional” are holidays in part of the country only: they stay in the count.",
    "cal.holiday": "Holiday",
    "cal.weekend": "Weekend",
    "cal.workday": "Working day",
    "cal.deadline": "{n} working days after {start}",
    "cal.skipped": "Holidays skipped",
    "cal.none": "No public holiday in between",
    "cal.copy": "Copy the date",
    "cal.legend.holiday": "holiday",
    "cal.legend.target": "date asked",
    "ent.title": "Entry",
    "ent.more": "Read on Wikipedia",
    "ent.extract": "From Wikipedia",
    "ent.facts": "Wikidata facts",
    "ent.image": "Image",
    "ten.title": "Public tenders",
    "ten.count": "{n} notices published since {since}",
    "ten.count1": "1 notice published since {since}",
    "ten.none":
      "No notice published since {since}. Widen the period or the keywords.",
    "ten.deadline": "Reply by {date}",
    "ten.closed": "Closed",
    "ten.left": "{n} days left",
    "ten.today": "Last day",
    "ten.published": "Published {date}",
    "ten.open": "Open the notice",
    "pap.title": "Scholarly works",
    "pap.count": "{n} results",
    "pap.cited": "Most cited of the {n} most relevant",
    "pap.recent": "Published in the last 3 years",
    "pap.cites": "{n} citations",
    "pap.cites1": "1 citation",
    "pap.oa": "Open access",
    "pap.doi.ok": "DOI checked",
    "pap.doi.ko": "DOI not found",
    "pap.doi.ko.note":
      "Crossref does not know this DOI: it does not exist or is mistyped.",
    "pap.none": "No work found.",
    "com.title": "Commune",
    "com.homonyms": "{n} communes have this name",
    "com.address": "Normalised address",
    "com.insee": "INSEE code",
    "com.cp": "Postcode",
    "com.cps": "Postcodes",
    "com.pop": "Population",
    "com.dept": "Département",
    "com.region": "Region",
    "com.surface": "Area",
    "com.score": "{s}% match",
    "com.weak": "Weak match: check it",
    "com.copy": "Copy the address",
    "com.inh": "{n}",
    "map.alt": "Map of {name}",
    "chart.data": "Data: {label}",
    "chart.updated": "updated {date}",
  },
};

export function tt(key, vars) {
  let s = S[lang()][key] ?? S.fr[key] ?? key;
  for (const [k, v] of Object.entries(vars || {}))
    s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

const ext = (href, label, cls = "widget-link") => {
  const url = safeUrl(href || "");
  return url
    ? h(
        "a",
        {
          class: cls,
          href: url,
          target: "_blank",
          rel: "noopener noreferrer",
          referrerpolicy: "no-referrer",
        },
        h("span", { text: label }),
        icon("mail", "ext"),
      )
    : h("span", { text: label });
};

function section(type, title, ...body) {
  const id = `w-${type}-${Math.random().toString(36).slice(2, 8)}`;
  return h(
    "section",
    {
      class: `widget widget-${type} od-card`,
      "aria-labelledby": id,
      "data-widget": type,
    },
    h("h3", { class: "eyebrow widget-title", id, text: title }),
    ...body,
  );
}

/** « Données : <source> · <licence> », both linked; extra parts after. */
function dataFooter(w, ...extra) {
  return h(
    "footer",
    { class: "widget-source od-source" },
    h("span", {
      text: `${tt("data")} : `.replace(" :", lang() === "en" ? ":" : " :"),
    }),
    ext(w.source?.url, w.source?.label || ""),
    w.license?.label && [" · ", ext(w.license.url, w.license.label)],
    ...extra.filter(Boolean).map((x) => [" · ", x]),
  );
}

const iso = (s) =>
  /^\d{4}-\d{2}-\d{2}/.test(String(s || "")) ? String(s).slice(0, 10) : "";
function fmtDay(d, opts = { day: "numeric", month: "long", year: "numeric" }) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(d || ""));
  return m
    ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString(locale(), {
        timeZone: "UTC",
        ...opts,
      })
    : "";
}
const fmtInt = (n) => nf({ maximumFractionDigits: 0 }).format(n);

// ------------------------------------------------------------------ calendar

/** The weeks of a month (Monday first): [[{d: 'YYYY-MM-DD', day, wd} | null, ...7], ...]. */
export function monthWeeks(year, month) {
  const first = new Date(Date.UTC(year, month - 1, 1));
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const lead = (first.getUTCDay() + 6) % 7;
  const cells = Array(lead).fill(null);
  for (let d = 1; d <= days; d++) {
    const wd = (lead + d - 1) % 7;
    cells.push({
      d: `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`,
      day: d,
      wd,
    });
  }
  while (cells.length % 7) cells.push(null);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

function monthGrid(year, month, holidays, marks = {}) {
  const byDay = Object.fromEntries((holidays || []).map((x) => [x.d, x]));
  const dow = [...Array(7)].map((_, i) =>
    new Date(Date.UTC(2024, 0, 1 + i)).toLocaleDateString(locale(), {
      weekday: "narrow",
      timeZone: "UTC",
    }),
  );
  const dowLong = [...Array(7)].map((_, i) =>
    new Date(Date.UTC(2024, 0, 1 + i)).toLocaleDateString(locale(), {
      weekday: "long",
      timeZone: "UTC",
    }),
  );
  const title = new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString(
    locale(),
    {
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    },
  );
  return h(
    "table",
    { class: "od-month" },
    h("caption", { class: "od-month-cap", text: title }),
    h(
      "thead",
      null,
      h(
        "tr",
        null,
        dow.map((d, i) => h("th", { scope: "col", abbr: dowLong[i], text: d })),
      ),
    ),
    h(
      "tbody",
      null,
      monthWeeks(year, month).map((week) =>
        h(
          "tr",
          null,
          week.map((c) => {
            if (!c) return h("td", { class: "od-day is-empty" });
            const hol = byDay[c.d];
            const cls = ["od-day"];
            if (c.wd >= 5) cls.push("is-weekend");
            if (hol) cls.push(hol.regional ? "is-regional" : "is-holiday");
            if (marks[c.d]) cls.push(marks[c.d]);
            const label = `${fmtDay(c.d, { weekday: "long", day: "numeric", month: "long" })}${hol ? ` — ${hol.name}` : ""}`;
            return h(
              "td",
              { class: cls.join(" "), title: hol ? hol.name : null },
              h("span", {
                class: "od-day-n num",
                "aria-hidden": "true",
                text: String(c.day),
              }),
              h("span", { class: "sr-only", text: label }),
            );
          }),
        ),
      ),
    ),
  );
}

function holidayList(w) {
  const rows = w.holidays || [];
  if (!rows.length) return null;
  return h(
    "ul",
    { class: "od-hol-list" },
    rows.map((x) =>
      h(
        "li",
        { class: x.regional ? "is-regional" : "" },
        h("span", {
          class: "od-hol-date num",
          text: fmtDay(x.d, {
            weekday: "short",
            day: "numeric",
            month: "short",
          }),
        }),
        h(
          "span",
          { class: "od-hol-name" },
          x.name,
          x.alt && h("span", { class: "muted", text: ` · ${x.alt}` }),
        ),
        x.regional && h("span", { class: "tag", text: tt("cal.regional") }),
      ),
    ),
  );
}

function kpis(c) {
  if (!c) return null;
  const tile = (n, label, hint) =>
    h(
      "div",
      { class: "kpi" },
      h("span", { class: "kpi-label", text: label }),
      h("span", { class: "kpi-value num", text: fmtInt(n) }),
      hint && h("span", { class: "od-kpi-hint muted", text: hint }),
    );
  return h(
    "div",
    { class: "kpi-row od-kpis" },
    tile(c.workdays, tt("cal.workdays"), tt("cal.workdays.hint")),
    tile(c.workable, tt("cal.workable"), tt("cal.workable.hint")),
  );
}

function legend(withTarget) {
  return h(
    "p",
    { class: "od-legend muted", "aria-hidden": "true" },
    h("span", { class: "od-swatch is-holiday" }),
    tt("cal.legend.holiday"),
    withTarget && [
      h("span", { class: "od-swatch is-target" }),
      tt("cal.legend.target"),
    ],
  );
}

function renderCalendar(w) {
  const zone = w.zone?.label || "";
  const hasRegional = (w.holidays || []).some((x) => x.regional);
  const head = (main, sub) =>
    h(
      "div",
      { class: "od-head" },
      h("p", { class: "od-main", text: main }),
      sub && h("p", { class: "muted od-sub", text: sub }),
    );
  let body = [];
  if (w.mode === "deadline" && w.deadline) {
    const dl = w.deadline;
    const end = fmtDay(dl.end, {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    });
    body = [
      head(
        end,
        `${tt("cal.deadline", { n: dl.days, start: fmtDay(dl.start) })} · ${zone}`,
      ),
      h(
        "p",
        { class: "od-chips" },
        (dl.skipped || []).length
          ? [
              h("span", {
                class: "muted",
                text: `${tt("cal.skipped")} : `.replace(
                  " :",
                  lang() === "en" ? ":" : " :",
                ),
              }),
              dl.skipped.map((s) =>
                h("span", {
                  class: "pill od-pill-hol",
                  text: `${s.name} (${fmtDay(s.d, { day: "numeric", month: "short" })})`,
                }),
              ),
            ]
          : h("span", { class: "muted", text: tt("cal.none") }),
      ),
      monthGrid(w.year, w.month, w.holidays, {
        [dl.end]: "is-target",
        [dl.start]: "is-start",
      }),
      legend(true),
      h(
        "p",
        { class: "place-actions" },
        button("btn-outline btn-small", "copy", tt("cal.copy"), () =>
          copyText(end),
        ),
      ),
    ];
  } else if (w.mode === "day" && w.day) {
    const d = w.day;
    const status = d.holiday
      ? [tt("cal.holiday"), "od-pill-hol"]
      : d.wd >= 5
        ? [tt("cal.weekend"), "od-pill-we"]
        : [tt("cal.workday"), "pill-active"];
    body = [
      head(
        fmtDay(d.d, {
          weekday: "long",
          day: "numeric",
          month: "long",
          year: "numeric",
        }),
        zone,
      ),
      h(
        "p",
        { class: "od-chips" },
        h("span", { class: `pill ${status[1]}`, text: status[0] }),
        d.holiday && h("span", { class: "od-hol-name", text: d.holiday }),
        d.regional && h("span", { class: "tag", text: tt("cal.regional") }),
      ),
      monthGrid(w.year, w.month, w.holidays, { [d.d]: "is-target" }),
      legend(true),
    ];
  } else if (w.mode === "month") {
    const title = new Date(Date.UTC(w.year, w.month - 1, 1)).toLocaleDateString(
      locale(),
      { month: "long", year: "numeric", timeZone: "UTC" },
    );
    body = [
      head(title, zone),
      kpis(w.counts),
      monthGrid(w.year, w.month, w.holidays),
      legend(false),
      holidayList(w),
    ];
  } else {
    body = [
      head(tt("cal.year", { year: w.year }), zone),
      kpis(w.counts),
      holidayList(w),
    ];
  }
  return section(
    "calendar",
    tt("cal.title"),
    ...body,
    hasRegional &&
      h("p", { class: "widget-note", text: tt("cal.regional.note") }),
    dataFooter(w),
  );
}

// ------------------------------------------------------------------ entity

function renderEntity(w) {
  const img =
    w.image && IMG_SRC.test(String(w.image.src || "")) ? w.image : null;
  const pic =
    img &&
    h(
      "figure",
      { class: "od-ent-pic" },
      h("img", {
        src: img.src,
        alt: w.title || "",
        width: String(img.w || 160),
        height: String(img.h || 120),
        loading: "lazy",
        decoding: "async",
        referrerpolicy: "no-referrer",
      }),
    );
  const facts = (w.facts || []).filter((f) => f && f.value);
  const kv =
    facts.length > 0 &&
    h(
      "dl",
      { class: "kv od-kv" },
      facts.map((f) =>
        h(
          "div",
          null,
          h("dt", { text: f.label }),
          h(
            "dd",
            null,
            f.url
              ? ext(
                  f.url,
                  String(f.value)
                    .replace(/^https?:\/\/(www\.)?/, "")
                    .replace(/\/$/, ""),
                )
              : f.value,
            f.date &&
              h("span", { class: "muted od-date", text: ` (${f.date})` }),
          ),
        ),
      ),
    );
  const credit =
    img &&
    h(
      "span",
      null,
      `${tt("ent.image")} : `.replace(" :", lang() === "en" ? ":" : " :"),
      ext(
        img.page,
        [img.artist, img.license].filter(Boolean).join(", ") ||
          "Wikimedia Commons",
      ),
    );
  return section(
    "entity",
    tt("ent.title"),
    h(
      "div",
      { class: `od-ent${pic ? " has-pic" : ""}` },
      pic,
      h(
        "div",
        { class: "od-ent-text" },
        h("p", { class: "od-main", text: w.title || "" }),
        w.description && h("p", { class: "muted od-sub", text: w.description }),
        w.extract && h("p", { class: "od-extract", text: w.extract }),
        w.url && h("p", { class: "od-more" }, ext(w.url, tt("ent.more"))),
      ),
    ),
    kv,
    h(
      "footer",
      { class: "widget-source od-source" },
      h("span", { text: `${tt("ent.extract")} (` }),
      ext(w.license?.url, w.license?.label || "CC BY-SA 4.0"),
      ")",
      w.wikidata && [
        " · ",
        ext(w.wikidata, tt("ent.facts")),
        " (",
        ext(w.data_license?.url, w.data_license?.label || "CC0"),
        ")",
      ],
      credit && [" · ", credit],
    ),
  );
}

// ------------------------------------------------------------------ tenders

function daysLeft(deadline, today = new Date()) {
  const d = iso(deadline);
  if (!d) return null;
  const end = Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((end - now) / 86400000);
}

function renderTenders(w) {
  const items = (w.items || []).filter((i) => i && i.title);
  const since = fmtDay(w.since);
  const count =
    w.total === 1
      ? tt("ten.count1", { since })
      : tt("ten.count", { n: fmtInt(w.total || 0), since });
  const head = h(
    "div",
    { class: "od-head" },
    h("p", {
      class: "od-main",
      text: `« ${w.query || ""} »${w.where ? ` · ${w.where}` : ""}`,
    }),
    h("p", {
      class: "muted od-sub",
      text: items.length ? count : tt("ten.none", { since }),
    }),
  );
  const list = items.length
    ? h(
        "ol",
        { class: "od-list" },
        items.map((i) => {
          const left = daysLeft(i.deadline);
          const chip =
            left === null
              ? null
              : left < 0
                ? h("span", {
                    class: "pill pill-closed",
                    text: tt("ten.closed"),
                  })
                : h("span", {
                    class: `pill ${left <= 7 ? "od-pill-soon" : "pill-active"}`,
                    text:
                      left === 0
                        ? tt("ten.today")
                        : tt("ten.left", { n: left }),
                  });
          return h(
            "li",
            { class: "od-item" },
            h(
              "p",
              { class: "od-item-title" },
              ext(i.url, i.title, "widget-link od-item-link"),
            ),
            h(
              "p",
              { class: "od-item-meta muted" },
              [
                i.buyer,
                (i.deps || []).join(", "),
                i.published &&
                  tt("ten.published", {
                    date: fmtDay(i.published, {
                      day: "numeric",
                      month: "short",
                    }),
                  }),
              ]
                .filter(Boolean)
                .join(" · "),
            ),
            (i.deadline || i.procedure) &&
              h(
                "p",
                { class: "od-item-meta" },
                chip,
                i.deadline &&
                  h("span", {
                    class: "muted",
                    text: tt("ten.deadline", { date: fmtDay(i.deadline) }),
                  }),
                i.procedure &&
                  h("span", { class: "muted", text: ` · ${i.procedure}` }),
              ),
          );
        }),
      )
    : null;
  return section("tenders", tt("ten.title"), head, list, dataFooter(w));
}

// ------------------------------------------------------------------ papers

function renderPapers(w) {
  const items = (w.items || []).filter((i) => i && i.title);
  const doi = w.mode === "doi";
  const sub = doi
    ? null
    : w.pool
      ? tt("pap.cited", { n: w.pool })
      : w.order === "recent"
        ? tt("pap.recent")
        : tt("pap.count", { n: fmtInt(w.total || 0) });
  const head = h(
    "div",
    { class: "od-head" },
    h(
      "p",
      { class: "od-main" },
      doi &&
        h("span", {
          class: `pill ${w.found ? "pill-active" : "pill-closed"}`,
          text: tt(w.found ? "pap.doi.ok" : "pap.doi.ko"),
        }),
      doi
        ? h("span", { class: "num od-doi", text: ` ${w.query}` })
        : `« ${w.query || ""} »`,
    ),
    sub && h("p", { class: "muted od-sub", text: sub }),
  );
  const list =
    items.length > 0 &&
    h(
      "ol",
      { class: "od-list" },
      items.map((i) =>
        h(
          "li",
          { class: "od-item" },
          h(
            "p",
            { class: "od-item-title" },
            ext(i.url, i.title, "widget-link od-item-link"),
          ),
          h(
            "p",
            { class: "od-item-meta muted" },
            [
              (i.authors || []).join(", ") + (i.more ? " et al." : ""),
              i.venue,
              i.year,
            ]
              .filter(Boolean)
              .join(" · "),
          ),
          h(
            "p",
            { class: "od-item-meta" },
            h("span", {
              class: "tag",
              text:
                i.cites === 1
                  ? tt("pap.cites1")
                  : tt("pap.cites", { n: fmtInt(i.cites || 0) }),
            }),
            i.oa_url && [" ", ext(i.oa_url, tt("pap.oa"), "widget-link od-oa")],
            i.doi &&
              h("span", { class: "muted num od-doi", text: ` doi:${i.doi}` }),
          ),
        ),
      ),
    );
  return section(
    "papers",
    tt("pap.title"),
    head,
    doi &&
      !w.found &&
      h("p", { class: "widget-note", text: tt("pap.doi.ko.note") }),
    list || (!doi && h("p", { class: "widget-note", text: tt("pap.none") })),
    dataFooter(w),
  );
}

// ------------------------------------------------------------------ communes and addresses

let mapFrameFn = null;
/** widgets.js hands over its map frame (pins, zoom, broken-image fallback), so maps look the same everywhere. */
export function useMapFrame(fn) {
  mapFrameFn = fn;
}

function communeKv(c) {
  return h(
    "dl",
    { class: "kv od-kv" },
    [
      [tt("com.insee"), h("span", { class: "num", text: c.code })],
      (c.postcodes || []).length && [
        tt(c.postcodes.length > 1 ? "com.cps" : "com.cp"),
        h("span", { class: "num", text: c.postcodes.join(", ") }),
      ],
      c.population != null && [
        tt("com.pop"),
        h("span", {
          class: "num",
          text: tt("com.inh", { n: fmtInt(c.population) }),
        }),
      ],
      c.dept?.name && [tt("com.dept"), `${c.dept.name} (${c.dept.code})`],
      c.region?.name && [tt("com.region"), c.region.name],
      c.surface_km2 != null && [
        tt("com.surface"),
        h("span", {
          class: "num",
          text: `${nf({ maximumFractionDigits: 1 }).format(c.surface_km2)} km²`,
        }),
      ],
    ]
      .filter(Boolean)
      .map(([k, v]) => h("div", null, h("dt", { text: k }), h("dd", null, v))),
  );
}

function mapOf(w, lat, lon, name) {
  if (
    !mapFrameFn ||
    !w.map ||
    !MAP_SRC.test(String(w.map.src || "")) ||
    lat == null
  )
    return null;
  return mapFrameFn(w, [{ n: 1, lat, lon, name }], null, {
    alt: tt("map.alt", { name }),
  });
}

function renderCommune(w) {
  const rows = (w.communes || []).filter(Boolean);
  if (w.mode === "address" && w.address) {
    const a = w.address;
    const text = [a.line1, a.line2].filter(Boolean).join("\n");
    return section(
      "commune",
      tt("com.address"),
      h(
        "address",
        { class: "od-address" },
        h("span", { text: a.line1 }),
        h("br"),
        h("span", { text: a.line2 }),
      ),
      h(
        "p",
        { class: "od-chips" },
        h("span", {
          class: `pill ${a.sure ? "pill-active" : "od-pill-soon"}`,
          text: a.sure
            ? tt("com.score", { s: Math.round(a.score * 100) })
            : tt("com.weak"),
        }),
        a.context && h("span", { class: "muted", text: a.context }),
      ),
      rows[0] && communeKv(rows[0]),
      mapOf(w, a.lat, a.lon, a.label),
      h(
        "p",
        { class: "place-actions" },
        button("btn-outline btn-small", "copy", tt("com.copy"), () =>
          copyText(text),
        ),
      ),
      dataFooter(w),
    );
  }
  if (w.mode === "homonyms") {
    return section(
      "commune",
      tt("com.title"),
      h(
        "div",
        { class: "od-head" },
        h("p", { class: "od-main", text: w.query }),
        h("p", {
          class: "muted od-sub",
          text: tt("com.homonyms", { n: w.total }),
        }),
      ),
      h(
        "div",
        { class: "od-table-wrap" },
        h(
          "table",
          { class: "od-table" },
          h(
            "thead",
            null,
            h(
              "tr",
              null,
              [
                tt("com.dept"),
                tt("com.cp"),
                tt("com.insee"),
                tt("com.pop"),
              ].map((x) => h("th", { scope: "col", text: x })),
            ),
          ),
          h(
            "tbody",
            null,
            rows.map((c) =>
              h(
                "tr",
                null,
                h("th", {
                  scope: "row",
                  text: `${c.dept?.name || ""} (${c.dept?.code || ""})`,
                }),
                h("td", { class: "num", text: (c.postcodes || []).join(", ") }),
                h("td", { class: "num", text: c.code }),
                h("td", {
                  class: "num",
                  text: c.population != null ? fmtInt(c.population) : "—",
                }),
              ),
            ),
          ),
        ),
      ),
      dataFooter(w),
    );
  }
  const c = rows[0];
  if (!c) return null;
  return section(
    "commune",
    tt("com.title"),
    h(
      "div",
      { class: "od-head" },
      h("p", { class: "od-main", text: c.name }),
      h("p", {
        class: "muted od-sub",
        text: [c.dept?.name, c.region?.name].filter(Boolean).join(" · "),
      }),
    ),
    communeKv(c),
    mapOf(w, c.lat, c.lon, c.name),
    dataFooter(w),
  );
}

// ------------------------------------------------------------------ statistics chart source line

/** The « Données : Eurostat (une_rt_a) · licence » line under a chart of real series (chart.js). */
export function chartSourceLine(src) {
  if (!src || !src.label) return null;
  const label = src.dataset ? `${src.label} (${src.dataset})` : src.label;
  return h(
    "p",
    { class: "chart-note od-chart-src" },
    icon("info"),
    h(
      "span",
      null,
      `${tt("data")} : `.replace(" :", lang() === "en" ? ":" : " :"),
      ext(src.url, label),
      src.subtitle && ` — ${src.subtitle}`,
      src.license && [" · ", ext(src.license_url, src.license)],
      src.updated && ` · ${tt("chart.updated", { date: fmtDay(src.updated) })}`,
      src.note && ` · ${src.note}`,
    ),
  );
}

/** The same line as plain text (PNG export foot, copy). */
export function chartSourceText(src) {
  if (!src || !src.label) return "";
  return [
    tt("chart.data", {
      label: src.dataset ? `${src.label} (${src.dataset})` : src.label,
    }),
    src.license,
    src.note,
  ]
    .filter(Boolean)
    .join(" · ");
}

// ------------------------------------------------------------------ registry and plain text

export const OPENDATA_RENDER = {
  calendar: renderCalendar,
  entity: renderEntity,
  tenders: renderTenders,
  papers: renderPapers,
  commune: renderCommune,
};

/** The open-data cards as plain text (copy) or Markdown (export); "" for other widgets. */
export function opendataText(w, markdown = false) {
  const link = (label, url) =>
    markdown && safeUrl(url || "") ? `[${label}](${url})` : label;
  const src = () =>
    `${tt("data")} : ${w.source?.label || ""}${w.license?.label ? ` (${w.license.label})` : ""}`;
  if (w.type === "calendar") {
    if (w.mode === "deadline" && w.deadline)
      return `${tt("cal.deadline", { n: w.deadline.days, start: fmtDay(w.deadline.start) })} : ${fmtDay(w.deadline.end, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}\n${src()}`;
    if (w.mode === "day" && w.day)
      return `${fmtDay(w.day.d, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}${w.day.holiday ? ` — ${w.day.holiday}` : ""}\n${src()}`;
    const lines = (w.holidays || []).map(
      (x) => `${x.d} ${x.name}${x.regional ? ` (${tt("cal.regional")})` : ""}`,
    );
    if (w.counts)
      lines.unshift(
        `${w.counts.workdays} ${tt("cal.workdays")} · ${w.counts.workable} ${tt("cal.workable")}`,
      );
    return [...lines, src()].join("\n");
  }
  if (w.type === "entity")
    return [
      w.title,
      w.extract,
      ...(w.facts || []).map((f) => `${f.label} : ${f.value}`),
      link(w.url || "", w.url),
      src(),
    ]
      .filter(Boolean)
      .join("\n");
  if (w.type === "tenders" || w.type === "papers")
    return [
      ...(w.items || []).map(
        (i, n) =>
          `${n + 1}. ${link(i.title, i.url)}${i.buyer ? ` — ${i.buyer}` : ""}${i.year ? ` (${i.year})` : ""}`,
      ),
      src(),
    ].join("\n");
  if (w.type === "commune") {
    if (w.address) return `${w.address.line1}\n${w.address.line2}\n${src()}`;
    return [
      ...(w.communes || [])
        .filter(Boolean)
        .map(
          (c) =>
            `${c.name} (${c.dept?.code || ""}) — INSEE ${c.code} — ${(c.postcodes || []).join(", ")}${c.population != null ? ` — ${c.population}` : ""}`,
        ),
      src(),
    ].join("\n");
  }
  return "";
}
