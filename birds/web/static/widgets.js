// Rich result cards under an answer: places + static map, company, currency, event (.ics).
// Data come from the server's `widgets` list (tool results and the user's own words, never model text).
// Built with h() only (text nodes, no innerHTML with data); positions set through CSSOM (CSP: no style attribute).
import { button, copyText, download, h, icon, state, t } from "./core.js";
import { safeUrl } from "./markdown.js";
import { buildIcs, icsName } from "./ics.js";

const OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright";
const MAP_SRC =
  /^(\/api\/map\?t=[A-Za-z0-9_\-.]+|\/static\/demo\/[0-9a-f]{16}\.webp)$/;
const TEL = /^\+?[0-9 .()-]{6,20}$/;
const locale = () => (state.prefs.lang === "en" ? "en-GB" : "fr-FR");
const nf = (o) => new Intl.NumberFormat(locale(), o);

// ------------------------------------------------------------------ Web-Mercator (mirrors birds/harness/geo.py)

export function worldXY(lat, lon, z) {
  const la = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const scale = 256 * 2 ** z;
  const phi = (la * Math.PI) / 180;
  return [
    ((lon + 180) / 360) * scale,
    ((1 - Math.log(Math.tan(phi) + 1 / Math.cos(phi)) / Math.PI) / 2) * scale,
  ];
}

/** Position of a point in a w x h map centred on c at zoom z, in % of the frame (may be outside 0..100). */
export function pinPos(lat, lon, c, z, w = 640, h_ = 360) {
  const [cx, cy] = worldXY(c[0], c[1], z);
  const [x, y] = worldXY(lat, lon, z);
  return [((x - cx + w / 2) / w) * 100, ((y - cy + h_ / 2) / h_) * 100];
}

const ext = (href, label, cls = "widget-link", extra = {}) =>
  href &&
  h(
    "a",
    {
      class: cls,
      href,
      target: "_blank",
      rel: "noopener noreferrer",
      referrerpolicy: "no-referrer",
      ...extra,
    },
    h("span", { text: label }),
    icon("mail", "ext"),
  );

function fmtDist(m) {
  if (m === null || m === undefined) return "";
  return m < 1000
    ? `${nf({ maximumFractionDigits: 0 }).format(m)} m`
    : `${nf({ maximumFractionDigits: 1 }).format(m / 1000)} km`;
}

function kindLabel(kind) {
  const key = `place.kind.${kind}`;
  const v = t(key);
  return v === key ? String(kind || "").replace(/_/g, " ") : v;
}

function detailLabel(detail) {
  // OSM "cuisine" values are lists like "chinese;asian": translated piece by piece when known
  const [cuisine, ...rest] = String(detail || "").split(" · ");
  const parts = cuisine
    .split(/[;,]/)
    .map((c) => c.trim())
    .filter(Boolean)
    .map((c) => {
      const key = `cuisine.${c}`;
      const v = t(key);
      return v === key ? c.replace(/_/g, " ") : v;
    });
  return [parts.join(", "), ...rest].filter(Boolean).join(" · ");
}

function section(type, title, ...body) {
  const id = `w-${type}-${Math.random().toString(36).slice(2, 8)}`;
  return h(
    "section",
    {
      class: `widget widget-${type}`,
      "aria-labelledby": id,
      "data-widget": type,
    },
    h("h3", { class: "eyebrow widget-title", id, text: title }),
    ...body,
  );
}

function footer(...parts) {
  return h("footer", { class: "widget-source" }, ...parts);
}

// ------------------------------------------------------------------ map frame (shared by places and company)

function mapFrame(w, places, center, opts = {}) {
  const m = w.map;
  if (!m || !MAP_SRC.test(String(m.src || ""))) return null;
  let dz = 0;
  const frame = h("div", { class: "map-frame" });
  const img = h("img", {
    class: "map-img",
    src: m.src,
    width: String(m.w || 640),
    height: String(m.h || 360),
    alt: opts.alt || t("map.alt.one"),
    decoding: "async",
    referrerpolicy: "no-referrer",
  });
  img.addEventListener("error", () => {
    frame.classList.add("is-broken");
    img.hidden = true;
  });
  const pins = [];
  const layer = h("div", { class: "map-pins", "aria-hidden": "true" });
  const addPin = (p, label, cls) => {
    const pin = h(
      "button",
      {
        class: `map-pin ${cls}`,
        type: "button",
        tabindex: "-1",
        "aria-hidden": "true",
        "data-n": String(p.n ?? ""),
      },
      h("span", { text: label }),
    );
    pin.addEventListener("click", () => opts.onPin?.(p));
    pins.push([pin, p]);
    layer.append(pin);
  };
  if (center) addPin({ ...center, n: "★" }, "★", "map-pin-center");
  for (const p of places) addPin(p, String(p.n), "");
  const place = () => {
    const z = (m.z || 15) + dz;
    for (const [pin, p] of pins) {
      const [x, y] = pinPos(p.lat, p.lon, m.c, z, m.w || 640, m.h || 360);
      pin.style.setProperty("--x", `${x.toFixed(2)}%`);
      pin.style.setProperty("--y", `${y.toFixed(2)}%`);
      pin.hidden = x < 1 || x > 99 || y < 2 || y > 98;
    }
  };
  place();
  const zoom = (step) => () => {
    const next = Math.max(-2, Math.min(3, dz + step));
    if (next === dz) return;
    dz = next;
    frame.classList.remove("is-broken");
    img.hidden = false;
    img.src = `${m.src}${dz ? `&dz=${dz}` : ""}`;
    place();
    zin.disabled = dz >= 3;
    zout.disabled = dz <= -2;
  };
  const zin = button("btn-icon map-zoom-in", "plus", t("map.zoomIn"), zoom(1));
  const zout = button(
    "btn-icon map-zoom-out",
    "minus",
    t("map.zoomOut"),
    zoom(-1),
  );
  // native append() would print `false` as a text node: falsy children are filtered first (h() does it itself)
  const children = [
    img,
    layer,
    h("p", { class: "map-unavailable", text: t("map.unavailable") }),
    h(
      "a",
      {
        class: "map-attr",
        href: OSM_COPYRIGHT,
        target: "_blank",
        rel: "noopener noreferrer",
        referrerpolicy: "no-referrer",
      },
      h("span", { text: w.attribution || "© OpenStreetMap contributors" }),
    ),
    !m.static && h("div", { class: "map-zoom" }, zin, zout),
  ];
  frame.append(...children.filter(Boolean));
  frame._pins = pins;
  return frame;
}

function linkPins(frame, list) {
  if (!frame) return;
  const pinFor = (n) =>
    frame._pins.find(([, p]) => String(p.n) === String(n))?.[0];
  for (const li of list.querySelectorAll("[data-n]")) {
    const on = () => pinFor(li.dataset.n)?.classList.add("is-active");
    const off = () => pinFor(li.dataset.n)?.classList.remove("is-active");
    li.addEventListener("mouseenter", on);
    li.addEventListener("mouseleave", off);
    li.addEventListener("focusin", on);
    li.addEventListener("focusout", off);
  }
}

// ------------------------------------------------------------------ places

function placeCard(p, mode, uidPrefix) {
  const meta = [
    p.kind && kindLabel(p.kind),
    p.detail && detailLabel(p.detail),
    mode !== "list" && mode !== "where" && fmtDist(p.distance_m),
  ].filter(Boolean);
  const site = safeUrl(p.website || "");
  const tel = TEL.test(String(p.phone || ""))
    ? `tel:${String(p.phone).replace(/[^+0-9]/g, "")}`
    : null;
  return h(
    "li",
    {
      class: "place-card",
      id: `${uidPrefix}-${p.n}`,
      "data-n": String(p.n),
      tabindex: "-1",
    },
    h("span", { class: "place-n", "aria-hidden": "true", text: String(p.n) }),
    h(
      "div",
      { class: "place-body" },
      h("h4", { class: "place-name", text: p.name }),
      meta.length > 0 &&
        h("p", { class: "place-meta", text: meta.join(" · ") }),
      p.address && h("p", { class: "place-address", text: p.address }),
      p.hours &&
        h(
          "p",
          { class: "place-hours" },
          h("span", { class: "muted", text: `${t("places.hours")} : ` }),
          h("span", { text: p.hours }),
        ),
      h(
        "p",
        { class: "place-actions" },
        site && ext(site, t("places.site")),
        tel &&
          h(
            "a",
            { class: "widget-link", href: tel },
            h("span", { text: t("places.call") }),
          ),
        ext(safeUrl(p.directions || ""), t("places.route")),
        ext(safeUrl(p.osm || ""), t("places.map")),
        ext(safeUrl(p.wiki || ""), "Wikipédia"),
      ),
    ),
  );
}

function placesTitle(w) {
  const n = (w.places || []).length;
  if (w.mode === "near" && w.center)
    return t("places.title.near", {
      kind: kindLabel(w.query) + (n > 1 ? "s" : ""),
      near: w.center.name,
    });
  if (w.mode === "route" && w.center)
    return t("places.title.route", {
      a: w.center.name,
      b: w.places[1]?.name || "",
    });
  if (w.mode === "list") return t("places.title.list");
  return t("places.title.where", { q: w.places?.[0]?.name || w.query });
}

function renderPlaces(w, turn) {
  const places = (w.places || [])
    .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon))
    .slice(0, 8);
  if (!places.length) return null;
  const prefix = `pl-${turn.id}-${Math.random().toString(36).slice(2, 6)}`;
  const focusCard = (p) => {
    const card = document.getElementById(`${prefix}-${p.n}`);
    if (!card) return;
    card.hidden = false;
    card.scrollIntoView({
      block: "nearest",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
    card.focus({ preventScroll: true });
    card.classList.add("is-cited");
    window.setTimeout(() => card.classList.remove("is-cited"), 1600);
  };
  const center = w.mode === "near" && w.center ? w.center : null;
  const alt =
    w.mode === "near" && w.center
      ? t("map.alt", { n: places.length, near: w.center.name })
      : t("map.alt.list", { names: places.map((p) => p.name).join(", ") });
  const frame = mapFrame(w, places, center, { alt, onPin: focusCard });
  const shown = 3;
  const cards = places.map((p) => placeCard(p, w.mode, prefix));
  cards.forEach((c, i) => (c.hidden = i >= shown && places.length > shown + 1));
  const list = h(
    "ol",
    { class: "place-list", "aria-label": placesTitle(w) },
    cards,
  );
  const hiddenN = cards.filter((c) => c.hidden).length;
  const more =
    hiddenN > 0 &&
    button(
      "btn-outline btn-small place-more",
      "down",
      t("places.more", { n: hiddenN }),
      (e) => {
        cards.forEach((c) => (c.hidden = false));
        e.currentTarget.remove();
      },
    );
  linkPins(frame, list);
  const first = places[0];
  const osmAll = safeUrl(
    center
      ? `https://www.openstreetmap.org/?mlat=${center.lat}&mlon=${center.lon}#map=16/${center.lat}/${center.lon}`
      : first.osm || "",
  );
  const route =
    w.mode === "route" &&
    h(
      "p",
      { class: "place-route" },
      h("span", { text: t("places.crow", { d: fmtDist(w.distance_m) }) }),
      ext(
        safeUrl(w.directions || ""),
        t("places.routeOsm"),
        "btn btn-primary btn-small",
      ),
    );
  return section(
    "places",
    placesTitle(w),
    h("div", { class: "widget-head-links" }, ext(osmAll, t("widget.openOsm"))),
    frame,
    route,
    list,
    more,
    footer(
      h("span", { text: t("places.attr") }),
      " · ",
      ext(
        safeUrl(first.source?.url || ""),
        w.provider === "ban"
          ? "Base Adresse Nationale"
          : w.provider === "photon"
            ? "Photon"
            : "Nominatim",
      ),
      w.mode === "near" &&
        h("span", { class: "muted", text: ` — ${t("places.incomplete")}` }),
    ),
  );
}

// ------------------------------------------------------------------ company

function renderCompany(w) {
  const official = safeUrl(w.source?.url || "");
  if (w.public === false)
    return section(
      "company",
      t("company.title"),
      h("p", { class: "widget-note", text: t("company.nonPublic") }),
      footer(ext(official, t("company.official"))),
    );
  const siren = String(w.siren || "");
  const sirenFmt =
    siren.length === 9
      ? `${siren.slice(0, 3)} ${siren.slice(3, 6)} ${siren.slice(6)}`
      : siren;
  const fmtDate = (d) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(d || ""));
    return m
      ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString(
          locale(),
          { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" },
        )
      : "";
  };
  const rows = [
    [
      "company.siren",
      h(
        "span",
        { class: "num-row" },
        h("span", { class: "num", text: sirenFmt }),
        button("btn-icon btn-small", "copy", t("company.copySiren"), () =>
          copyText(siren),
        ),
      ),
    ],
    w.siret && ["company.siret", h("span", { class: "num", text: w.siret })],
    w.legal_form && ["company.legalForm", w.legal_form],
    w.naf && [
      "company.activity",
      w.naf_label ? `${w.naf_label} (NAF ${w.naf})` : `NAF ${w.naf}`,
    ],
    w.staff && ["company.staff", w.staff],
    w.created && ["company.created", fmtDate(w.created)],
    (w.address || w.commune) && ["company.address", w.address || w.commune],
  ].filter(Boolean);
  const money = (v) =>
    nf({
      notation: "compact",
      maximumFractionDigits: 1,
      style: "currency",
      currency: "EUR",
    }).format(v);
  const fin = w.finances;
  const tiles =
    fin &&
    h(
      "div",
      { class: "kpi-row" },
      fin.revenue != null &&
        h(
          "div",
          { class: "kpi" },
          h("span", {
            class: "kpi-label",
            text: t("company.revenue", { year: fin.year }),
          }),
          h("span", { class: "kpi-value num", text: money(fin.revenue) }),
        ),
      fin.net_income != null &&
        h(
          "div",
          { class: "kpi" },
          h("span", {
            class: "kpi-label",
            text: t("company.netIncome", { year: fin.year }),
          }),
          h("span", { class: "kpi-value num", text: money(fin.net_income) }),
        ),
    );
  const pin =
    w.lat != null && !w.natural_person
      ? [{ n: 1, lat: w.lat, lon: w.lon, name: w.name }]
      : [];
  const frame = pin.length
    ? mapFrame(w, pin, null, { alt: t("map.alt.company", { name: w.name }) })
    : null;
  const closed = w.status === "closed";
  return section(
    "company",
    t("company.title"),
    h(
      "div",
      { class: "company-head" },
      h(
        "p",
        { class: "company-name" },
        h("strong", { text: w.name }),
        w.sigle && h("span", { class: "muted", text: ` (${w.sigle})` }),
      ),
      h("span", {
        class: `pill ${closed ? "pill-closed" : "pill-active"}`,
        text: closed
          ? t("company.closed", { date: fmtDate(w.closed_on) })
          : t("company.active"),
      }),
    ),
    w.natural_person &&
      h("p", { class: "widget-note", text: t("company.naturalPerson") }),
    h(
      "dl",
      { class: "kv company-kv" },
      rows.map(([k, v]) => h("div", null, h("dt", { text: t(k) }), h("dd", null, v))),
    ),
    tiles,
    frame,
    (w.candidates || []).length > 1 &&
      h(
        "div",
        { class: "company-candidates" },
        h("p", { class: "muted", text: t("company.pick") }),
        h(
          "ul",
          null,
          w.candidates.map((c) =>
            h(
              "li",
              null,
              ext(safeUrl(c.url), `${c.name} · ${c.siren} · ${c.commune}`),
            ),
          ),
        ),
      ),
    h(
      "p",
      { class: "place-actions" },
      ext(official, t("company.official"), "btn btn-outline btn-small"),
      ext(safeUrl(w.directors_url || ""), t("company.directors")),
      pin.length > 0 &&
        ext(
          safeUrl(
            `https://www.openstreetmap.org/?mlat=${w.lat}&mlon=${w.lon}#map=17/${w.lat}/${w.lon}`,
          ),
          t("places.map"),
        ),
    ),
    footer(
      h("span", { text: `${t("widget.source")} : ` }),
      ext(official, w.source?.label || "Annuaire des entreprises"),
      h("span", { class: "muted", text: ` — ${t("company.check")}` }),
    ),
  );
}

// ------------------------------------------------------------------ currency

function renderFx(w) {
  let from = w.from;
  let to = w.to;
  let rate = Number(w.rate);
  if (!(rate > 0)) return null;
  const money = (v, cur) => {
    try {
      return nf({
        style: "currency",
        currency: cur,
        maximumFractionDigits: v < 10 ? 4 : 2,
      }).format(v);
    } catch {
      return `${nf({ maximumFractionDigits: 2 }).format(v)} ${cur}`;
    }
  };
  const input = h("input", {
    class: "fx-amount",
    type: "number",
    min: "0",
    step: "any",
    inputmode: "decimal",
    value: String(w.amount ?? 1),
    "aria-label": t("fx.amount"),
  });
  const curLabel = h("span", { class: "fx-cur", text: from });
  const result = h("output", { class: "fx-result num", "aria-live": "polite" });
  const inverse = h("p", { class: "fx-inverse muted num" });
  const paint = () => {
    const amount = Number(String(input.value).replace(",", ".")) || 0;
    curLabel.textContent = from;
    result.textContent = money(amount * rate, to);
    inverse.textContent = `1 ${from} = ${nf({ maximumFractionDigits: 4 }).format(rate)} ${to} · 1 ${to} = ${nf({ maximumFractionDigits: 4 }).format(1 / rate)} ${from}`;
  };
  input.addEventListener("input", paint);
  const swap = button(
    "btn-outline btn-small fx-swap",
    "retry",
    t("fx.swap"),
    () => {
      [from, to, rate] = [to, from, 1 / rate];
      paint();
    },
  );
  paint();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(String(w.date))
    ? new Date(`${w.date}T12:00:00Z`).toLocaleDateString(locale(), {
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : "";
  return section(
    "fx",
    t("fx.title"),
    h(
      "div",
      { class: "fx-row" },
      h("label", { class: "fx-in" }, input, curLabel),
      h("span", { class: "fx-eq", "aria-hidden": "true", text: "=" }),
      result,
    ),
    inverse,
    h("p", { class: "place-actions" }, swap),
    footer(
      h("span", { text: t("fx.reference", { date }) }),
      " · ",
      ext(safeUrl(w.source?.url || ""), w.source?.label || "BCE"),
    ),
  );
}

// ------------------------------------------------------------------ event

/** The event card's chips for the fields as they are now: [["warn" | "info", label], ...]. */
export function eventChips(f, holidays = {}, warnings = []) {
  const out = [];
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(f.date || ""));
  if (m) {
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    const known = warnings.find((x) => x.kind === "holiday" && x.date === f.date);
    const name = holidays[f.date] || known?.label;
    if (name) out.push(["warn", t("event.holiday", { name })]);
    const wd = d.getUTCDay();
    if (wd === 0 || wd === 6)
      out.push([
        "warn",
        t("event.weekend", {
          day: d.toLocaleDateString(locale(), {
            weekday: "long",
            timeZone: "UTC",
          }),
        }),
      ]);
  }
  if (!f.start) out.push(["info", t("event.allDay")]);
  else if (f.assumedEnd || !f.end) out.push(["info", t("event.defaultDuration")]);
  return out;
}

function renderEvent(w) {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(w.start || ""));
  const e = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(w.end || ""));
  if (!m || !e) return null;
  const tz = String(w.tz || "Europe/Paris");
  const field = (key, el) =>
    h(
      "label",
      { class: `ev-field ev-${key}` },
      h("span", { class: "ev-label", text: t(`event.${key}`) }),
      el,
    );
  const title = h("input", {
    type: "text",
    value: w.title || "",
    maxlength: "120",
    autocomplete: "off",
  });
  const date = h("input", { type: "date", value: m[1], required: true });
  const start = h("input", {
    type: "time",
    value: w.all_day ? "" : m[2],
    step: "300",
  });
  const end = h("input", {
    type: "time",
    value: w.all_day ? "" : e[2],
    step: "300",
  });
  const loc = h("input", {
    type: "text",
    value: w.location || "",
    maxlength: "120",
    autocomplete: "off",
  });
  const leaf = h(
    "div",
    { class: "ev-leaf", "aria-hidden": "true" },
    h("span", { class: "ev-month" }),
    h("span", { class: "ev-day num" }),
    h("span", { class: "ev-weekday" }),
  );
  const paintLeaf = () => {
    const d = new Date(`${date.value || m[1]}T12:00:00Z`);
    leaf.children[0].textContent = d.toLocaleDateString(locale(), {
      month: "short",
      timeZone: "UTC",
    });
    leaf.children[1].textContent = String(d.getUTCDate());
    leaf.children[2].textContent = d.toLocaleDateString(locale(), {
      weekday: "long",
      timeZone: "UTC",
    });
  };
  date.addEventListener("input", paintLeaf);
  paintLeaf();
  const current = () => {
    const allDay = !start.value;
    let endDate = date.value;
    if (!allDay && end.value && end.value <= start.value) {
      const d = new Date(`${date.value}T12:00:00Z`);
      d.setUTCDate(d.getUTCDate() + 1);
      endDate = d.toISOString().slice(0, 10);
    }
    let endTime = end.value;
    if (!allDay && !endTime) {
      const [hh, mm] = start.value.split(":").map(Number);
      endTime = `${String(Math.min(23, hh + 1)).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
    }
    return {
      title: title.value.trim() || t("event.untitled"),
      date: date.value,
      start: start.value,
      end: endTime,
      endDate,
      allDay,
      tz,
      location: loc.value.trim(),
      description: w.description || "",
    };
  };
  const text = () => {
    const ev = current();
    const day = new Date(`${ev.date}T12:00:00Z`).toLocaleDateString(locale(), {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    });
    return [
      ev.title,
      ev.allDay ? day : `${day}, ${ev.start}–${ev.end}`,
      ev.location,
    ]
      .filter(Boolean)
      .join("\n");
  };
  // the chips follow the fields: a holiday or a weekend for the day now shown, "all day" when there is no start,
  // "default duration" only while the end is still the one assumed from the words
  let assumedEnd = (w.assumptions || []).includes("default_duration");
  const chipBox = h("p", { class: "ev-chips", "aria-live": "polite" });
  const paintChips = () => {
    const flags = eventChips(
      { date: date.value, start: start.value, end: end.value, assumedEnd },
      w.holidays || {},
      (w.warnings || []).map((x) => ({ ...x, date: x.date || m[1] })),
    );
    const chips = flags.map(([kind, label]) =>
      kind === "warn"
        ? h(
            "span",
            { class: "ev-chip ev-chip-warn" },
            icon("alert"),
            h("span", { text: label }),
          )
        : h("span", { class: "ev-chip", text: label }),
    );
    chipBox.replaceChildren(...chips);
    chipBox.hidden = chips.length === 0;
  };
  date.addEventListener("input", paintChips);
  start.addEventListener("input", paintChips);
  end.addEventListener("input", () => {
    assumedEnd = false;
    paintChips();
  });
  paintChips();
  return section(
    "event",
    t("event.title"),
    h(
      "div",
      { class: "ev-grid" },
      leaf,
      h(
        "div",
        { class: "ev-fields" },
        field("name", title),
        h(
          "div",
          { class: "ev-when" },
          field("date", date),
          field("start", start),
          field("end", end),
        ),
        field("place", loc),
      ),
    ),
    chipBox,
    w.matched &&
      h("p", {
        class: "muted ev-matched",
        text: t("event.matched", { words: w.matched }),
      }),
    h(
      "p",
      { class: "place-actions" },
      button(
        "btn-primary btn-small",
        "download",
        t("event.add"),
        () => {
          const ev = current();
          if (!ev.date) return;
          download(
            icsName(ev.title, ev.date),
            "text/calendar;charset=utf-8",
            buildIcs(ev),
          );
        },
        { "data-act": "ics" },
      ),
      button("btn-outline btn-small", "copy", t("event.copy"), () =>
        copyText(text()),
      ),
    ),
    footer(h("span", { text: t("event.nothingSent") })),
  );
}

// ------------------------------------------------------------------ registry

const RENDER = {
  places: renderPlaces,
  company: renderCompany,
  fx: renderFx,
  event: renderEvent,
};

export function renderWidgets(turn) {
  const list = (turn.answer?.widgets || []).filter((w) => w && RENDER[w.type]);
  if (!list.length) return null;
  const els = [];
  for (const w of list) {
    try {
      const el = RENDER[w.type](w, turn);
      if (el) els.push(el);
    } catch (err) {
      console.warn("widget", w.type, err);
    }
  }
  return els.length ? h("div", { class: "widgets" }, els) : null;
}

/** The widgets as plain text (copy) or Markdown (export). */
export function widgetsText(turn, markdown = false) {
  const out = [];
  for (const w of turn.answer?.widgets || []) {
    if (w.type === "places") {
      for (const p of w.places || [])
        out.push(
          `${p.n}. ${p.name}${p.address ? ` — ${p.address}` : ""}${markdown && p.osm ? ` — ${p.osm}` : ""}`,
        );
      out.push(t("places.attr"));
    } else if (w.type === "company" && w.public !== false) {
      out.push(
        `${w.name} — SIREN ${w.siren}${w.legal_form ? ` — ${w.legal_form}` : ""}${w.address || w.commune ? ` — ${w.address || w.commune}` : ""}`,
        w.source?.url || "",
      );
    } else if (w.type === "fx") {
      out.push(
        `${w.amount} ${w.from} = ${w.result} ${w.to} (${t("fx.short", { date: w.date })})`,
      );
    } else if (w.type === "event") {
      out.push(
        `${w.title} — ${String(w.start).slice(0, 16).replace("T", " ")}${w.all_day ? "" : `–${String(w.end).slice(11, 16)}`}${w.location ? ` — ${w.location}` : ""}`,
      );
    }
  }
  return out.filter(Boolean).join("\n");
}
