// Rich result cards under an answer: places + static map, company, currency, weather, world clock, event (.ics).
// Data come from the server's `widgets` list (tool results and the user's own words, never model text).
// Built with h() only (text nodes, no innerHTML with data); positions set through CSSOM (CSP: no style attribute).
import {
  button,
  copyText,
  download,
  h,
  icon,
  state,
  t,
  toast,
} from "./core.js";
import { safeUrl } from "./markdown.js";
import { buildIcs, icsName } from "./ics.js";
import { MODULES, moduleText } from "./modules.js";
import { REPORT_MODULES, reportText } from "./research.js";
import { dataCardText, renderDataCard } from "./datakit.js"; // data analysis hook: the data card
import { OPENDATA_RENDER, opendataText, useMapFrame } from "./opendata.js"; // open data

const OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright";
const MAP_SRC =
  /^(\/api\/map\?t=[A-Za-z0-9_\-.]+|\/static\/demo\/[0-9a-f]{16}\.webp)$/;
const CLUSTER_MIN = 9; // pins on the map before close ones are grouped
const CLUSTER_R = 26; // px: pins closer than this to a group's first pin join it
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

// find_places' query keywords (intents.KINDS) -> the OSM kind keys of the label tables
const KIND_ALIAS = {
  coworking: "coworking_space",
  bookshop: "books",
  "subway station": "subway_entrance",
};
const kindKey = (kind) =>
  KIND_ALIAS[kind] ||
  String(kind || "")
    .trim()
    .replace(/\s+/g, "_");

function kindLabel(kind) {
  const key = `place.kind.${kindKey(kind)}`;
  const v = t(key);
  return v === key ? String(kind || "").replace(/_/g, " ") : v;
}

/** "8 restaurants", "1 hôpital", "3 bornes de recharge": explicit plural forms, never a bare "+s". */
export function kindCount(kind, n) {
  const key = `place.kinds.${kindKey(kind)}`;
  const plural = t(key);
  const one = kindLabel(kind).toLocaleLowerCase(locale());
  if (n === 1) return `1 ${one}`;
  return `${nf({ maximumFractionDigits: 0 }).format(n)} ${plural === key ? one : plural}`;
}

function detailLabel(detail) {
  // OSM "cuisine" values are lists like "chinese;asian": only the values with a translation are shown (free text
  // such as "cave a manger, epicerie de terroirs" or a description is in no known language: dropped)
  const [cuisine] = String(detail || "").split(" · ");
  return cuisine
    .split(/[;,]/)
    .map((c) => c.trim().toLowerCase())
    .filter(Boolean)
    .map((c) => {
      const key = `cuisine.${c}`;
      const v = t(key);
      return v === key ? "" : v;
    })
    .filter(Boolean)
    .join(", ");
}

// ------------------------------------------------------------------ opening hours (a small subset of OSM syntax)

const OSM_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

/** OSM opening_hours -> {today, rules: [[days, hours]]} in the UI language, or null (shown raw) when the value uses
 * syntax beyond "Mo-Fr 09:00-12:00,14:00-18:00; Sa 10:00-13:00; Su off; PH off; 24/7". ``day``: 0 = Monday. */
export function fmtHours(raw, day = (new Date().getDay() + 6) % 7) {
  const text = String(raw || "").trim();
  if (!text) return null;
  const names = t("hours.days").split(",");
  const clock = (hm) => {
    const [h, m] = hm.split(":").map(Number);
    if (state.prefs.lang === "en") return hm;
    if (h === 0 && m === 0) return t("hours.midnight");
    return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
  };
  const SPAN = /^([01]?\d|2[0-4]):([0-5]\d)\+?-([01]?\d|2[0-4]):([0-5]\d)\+?$/;
  if (text === "24/7")
    return {
      today: t("hours.always"),
      rules: [[t("hours.everyDay"), t("hours.always")]],
    };
  const rules = [];
  const byDay = new Array(7).fill(null);
  for (const part of text
    .split(";")
    .map((x) => x.trim())
    .filter(Boolean)) {
    const m =
      /^((?:(?:Mo|Tu|We|Th|Fr|Sa|Su|PH)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?)(?:,(?:Mo|Tu|We|Th|Fr|Sa|Su|PH)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?)*)?\s*(.*)$/.exec(
        part,
      );
    if (!m) return null;
    const daysSpec = m[1] || "Mo-Su";
    const rest = m[2].trim();
    let hours;
    if (/^(off|closed)$/i.test(rest)) hours = t("hours.closed");
    else {
      const spans = rest.split(",").map((x) => x.trim());
      if (!spans.length || !spans.every((x) => SPAN.test(x))) return null;
      hours = spans
        .map((x) => {
          const [, a, b, c, d] = SPAN.exec(x);
          return `${clock(`${a.padStart(2, "0")}:${b}`)} – ${clock(`${c.padStart(2, "0")}:${d}`)}`;
        })
        .join(", ");
    }
    const labels = [];
    for (const spec of daysSpec.split(",")) {
      if (spec === "PH") {
        labels.push(t("hours.holidays"));
        continue;
      }
      const [a, b] = spec.split("-").map((d) => OSM_DAYS.indexOf(d));
      const end = b === undefined ? a : b;
      for (let i = a; ; i = (i + 1) % 7) {
        byDay[i] = hours;
        if (i === end) break;
      }
      if (a === 0 && end === 6) labels.push(t("hours.everyDay"));
      else
        labels.push(b === undefined ? names[a] : `${names[a]}–${names[end]}`);
    }
    rules.push([labels.join(", "), hours]);
  }
  return { today: byDay[day] ?? (m0(text) ? t("hours.closed") : null), rules };
}
const m0 = (text) => /\b(Mo|Tu|We|Th|Fr|Sa|Su)\b/.test(text);

function hoursBlock(raw) {
  const got = fmtHours(raw);
  const colon = state.prefs.lang === "en" ? ": " : " : ";
  const label = h("span", { class: "muted", text: `${t("places.hours")} · ` });
  if (!got)
    return h("p", { class: "place-hours" }, label, h("span", { text: raw }));
  const single = got.rules.length === 1;
  const cap = (x) => x.charAt(0).toLocaleUpperCase(locale()) + x.slice(1);
  return h(
    "div",
    { class: "place-hours" },
    h(
      "p",
      null,
      label,
      h("span", {
        text: single
          ? `${cap(got.rules[0][0])}${colon}${got.rules[0][1]}`
          : `${cap(t("hours.today"))}${colon}${got.today ?? "—"}`,
      }),
    ),
    !single &&
      h(
        "details",
        { class: "place-hours-all" },
        h("summary", { text: t("hours.all") }),
        h(
          "ul",
          null,
          got.rules.map(([d, x]) => h("li", { text: `${cap(d)}${colon}${x}` })),
        ),
      ),
  );
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

// ------------------------------------------------------------------ pin declutter

const PIN = 26; // label size in CSS px (.map-pin, border-box)
const TAIL = 7; // .map-pin --tail: from the point to the label's bottom

/** Offsets [dx, dy] in px for pins whose labels would overlap: the first pin stays, the next ones try nearby
 * slots (right, left, up, diagonals, then farther). Rings ({ring: true}) never move but are avoided.
 * ``pts``: [{x, y, ring?}] in px (the point each pin marks). */
export function declutter(pts, size = PIN, gap = 3) {
  const step = size + gap;
  const slots = [[0, 0]];
  for (const k of [1, 2, 3])
    slots.push(
      [k * step, 0], [-k * step, 0], [0, -k * step], [k * step, -k * step], [-k * step, -k * step],
      [k * step, k * step * 0.5], [-k * step, k * step * 0.5],
    ); // prettier-ignore
  const boxes = [];
  const hit = (cx, cy) =>
    boxes.some(([bx, by, r]) => Math.abs(bx - cx) < r && Math.abs(by - cy) < r);
  for (const q of pts)
    if (q.ring) boxes.push([q.x, q.y, (size + 16) / 2 + gap]);
  return pts.map((q) => {
    if (q.ring) return [0, 0];
    const cy0 = q.y - TAIL - size / 2;
    for (const [dx, dy] of slots) {
      const cx = q.x + dx;
      const cy = cy0 + dy;
      if (!hit(cx, cy)) {
        boxes.push([cx, cy, size + gap]);
        return [dx, dy];
      }
    }
    boxes.push([q.x, cy0, size + gap]);
    return [0, 0];
  });
}

// ------------------------------------------------------------------ map frame (shared by places and company)

function mapFrame(w, places, center, opts = {}) {
  const m = w.map;
  if (!m || !MAP_SRC.test(String(m.src || ""))) return null;
  let dz = 0;
  const frame = h("div", { class: "map-frame" });
  // live maps: an @2x render for high-density screens (same area, zoom + 1); the frame never exceeds 640 px
  const srcset = (src) => (m.static ? null : `${src} 1x, ${src}&s=2 2x`);
  const img = h("img", {
    class: "map-img",
    src: m.src,
    srcset: srcset(m.src),
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
    // a thin leader from the true point to a pin moved aside by declutter()
    const leader = h("span", { class: "map-leader", hidden: true });
    pins.push([pin, p, leader]);
    layer.append(leader, pin);
  };
  // the centre of a "near" search is a ring drawn under the numbered pins, not a pin of its own
  if (center) {
    const ring = h("span", { class: "map-center" });
    pins.push([ring, { ...center, n: "★" }, null]);
    layer.append(ring);
  }
  for (const p of places) addPin(p, String(p.n), "");
  // dense maps: pins that would overlap are drawn as one numbered group; a tap zooms in (or opens the list)
  const clusters = h("div", { class: "map-clusters" });
  layer.append(clusters);
  const group = (pts) => {
    clusters.replaceChildren();
    const solo = pts.filter((q) => !q.ring);
    if (solo.length < CLUSTER_MIN) return pts;
    const groups = [];
    for (const q of solo) {
      const g = groups.find((x) => Math.hypot(x.x - q.x, x.y - q.y) < CLUSTER_R);
      if (g) g.members.push(q);
      else groups.push({ x: q.x, y: q.y, members: [q] });
    }
    const out = pts.filter((q) => q.ring);
    for (const g of groups) {
      if (g.members.length < 3) {
        out.push(...g.members);
        continue;
      }
      const cx = g.members.reduce((s, q) => s + q.x, 0) / g.members.length;
      const cy = g.members.reduce((s, q) => s + q.y, 0) / g.members.length;
      for (const q of g.members) {
        q.pin.hidden = true;
        q.leader.hidden = true;
      }
      const ps = g.members.map((q) => q.p);
      const bubble = h(
        "button",
        {
          class: "map-cluster",
          type: "button",
          tabindex: "-1",
          "aria-hidden": "true",
          title: t("map.cluster", { n: ps.length, list: ps.map((p) => p.n).join(", ") }),
        },
        h("span", { text: String(ps.length) }),
      );
      bubble.style.setProperty("--x", `${((cx / (frame.clientWidth || 1)) * 100).toFixed(2)}%`);
      bubble.style.setProperty("--y", `${((cy / (frame.clientHeight || 1)) * 100).toFixed(2)}%`);
      bubble.addEventListener("click", () => {
        if (!m.static && dz < 3) zoom(1)();
        else opts.onCluster?.(ps);
      });
      clusters.append(bubble);
    }
    return out;
  };
  const place = () => {
    const z = (m.z || 15) + dz;
    const W = frame.clientWidth || 0;
    const H = frame.clientHeight || 0;
    const pts = [];
    for (const [pin, p, leader] of pins) {
      const [x, y] = pinPos(p.lat, p.lon, m.c, z, m.w || 640, m.h || 360);
      pin.style.setProperty("--x", `${x.toFixed(2)}%`);
      pin.style.setProperty("--y", `${y.toFixed(2)}%`);
      if (leader) {
        leader.style.setProperty("--x", `${x.toFixed(2)}%`);
        leader.style.setProperty("--y", `${y.toFixed(2)}%`);
      }
      pin.hidden = x < 1 || x > 99 || y < 2 || y > 98;
      if (!pin.hidden)
        pts.push({
          x: (x / 100) * W,
          y: (y / 100) * H,
          pin,
          leader,
          ring: !leader,
          p,
        });
    }
    pts.splice(0, pts.length, ...(W ? group(pts) : pts));
    // overlapping pins are fanned out (in CSS px, once the frame has a size), each with a leader to its point
    const moves = W ? declutter(pts) : pts.map(() => [0, 0]);
    pts.forEach((q, i) => {
      if (q.ring) return;
      const [dx, dy] = moves[i];
      const moved = dx !== 0 || dy !== 0;
      q.pin.style.setProperty("--dx", `${dx}px`);
      q.pin.style.setProperty("--dy", `${dy}px`);
      q.pin.classList.toggle("is-moved", moved);
      q.leader.hidden = !moved;
      if (moved) {
        // from the point to the bottom of the moved label (TAIL above the point, plus the move)
        const lx = dx;
        const ly = dy - TAIL;
        q.leader.style.setProperty(
          "--len",
          `${Math.hypot(lx, ly).toFixed(1)}px`,
        );
        q.leader.style.setProperty(
          "--angle",
          `${Math.atan2(ly, lx).toFixed(4)}rad`,
        );
      }
    });
  };
  place();
  if (typeof ResizeObserver === "function")
    new ResizeObserver(place).observe(frame);
  // zoom: the new image is loaded first, then swapped with the pins in one go (they never sit on the old image)
  let pending = null;
  const zoom = (step) => () => {
    const next = Math.max(-2, Math.min(3, dz + step));
    if (next === dz) return;
    const src = `${m.src}${next ? `&dz=${next}` : ""}`;
    const pre = new Image();
    if (srcset(src)) pre.srcset = srcset(src);
    pending = pre;
    frame.classList.add("is-loading");
    frame.setAttribute("aria-busy", "true");
    const done = (okay) => {
      if (pending !== pre) return; // a later click won
      pending = null;
      frame.classList.remove("is-loading");
      frame.setAttribute("aria-busy", "false");
      if (!okay) {
        toast(t("map.unavailable"), "error");
        return;
      }
      dz = next;
      frame.classList.remove("is-broken");
      img.hidden = false;
      img.src = src;
      img.srcset = srcset(src) || "";
      place();
      zin.disabled = dz >= 3;
      zout.disabled = dz <= -2;
    };
    pre.onload = () => done(true);
    pre.onerror = () => done(false);
    pre.src = src;
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
    (!m.static || opts.onFull) &&
      h(
        "div",
        { class: "map-zoom" },
        !m.static && zin,
        !m.static && zout,
        opts.onFull && button("btn-icon map-full", "expand", t("map.full"), () => opts.onFull()),
      ),
  ];
  frame.append(...children.filter(Boolean));
  frame._pins = pins;
  frame._place = place;
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

const LIST_MAX = 25; // tools/places.py MAX_LIST
const MAX_CARDS = 8;

function placeCard(p, mode, uidPrefix, leg = null) {
  const meta = [
    p.kind && kindLabel(p.kind),
    p.detail && detailLabel(p.detail),
    mode !== "list" && mode !== "where" && fmtDist(p.distance_m),
    leg && t("places.leg", { d: fmtDist(leg.m), n: leg.a }),
  ].filter(Boolean);
  const site = safeUrl(p.website || "");
  const tel = TEL.test(String(p.phone || ""))
    ? `tel:${String(p.phone).replace(/[^+0-9]/g, "")}`
    : null;
  const address = p.address && p.address !== p.name ? p.address : "";
  const copy = p.address || p.name;
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
      address && h("p", { class: "place-address", text: address }),
      p.hours && hoursBlock(p.hours),
      h(
        "p",
        { class: "place-actions" },
        ext(safeUrl(p.directions || ""), t("places.route")),
        h(
          "button",
          {
            class: "widget-link place-copy",
            type: "button",
            onclick: () => copyText(copy, t("places.copied")),
          },
          h("span", { text: t("places.copy") }),
        ),
        ext(safeUrl(p.osm || ""), t("places.osm"), "widget-link", {
          title: t("widget.openOsm"),
        }),
        site && ext(site, t("places.site")),
        tel &&
          h(
            "a",
            { class: "widget-link", href: tel },
            h("span", { text: t("places.call") }),
          ),
        ext(safeUrl(p.wiki || ""), "Wikipédia"),
      ),
    ),
  );
}

function placesTitle(w) {
  const n = (w.places || []).length;
  if (w.mode === "near" && w.center) {
    // "8 restaurants · autour de : Gare de Lyon": no article to guess before the place's name
    const [count, ...kinds] = kindCount(w.query, n).split(" ");
    return t("places.title.near", {
      n: count,
      kinds: kinds.join(" "),
      near: w.center.name,
    });
  }
  if (w.mode === "route" && w.center)
    return t("places.title.route", {
      a: w.center.name,
      b: w.places[1]?.name || "",
    });
  if (w.mode === "list")
    return n > 1 ? t("places.title.listN", { n }) : t("places.title.list");
  return t("places.title.where", { q: w.places?.[0]?.name || w.query });
}

/** "1 → 3 → 2 → 4": the visit order of a list (card numbers). */
export function orderLine(order) {
  return (order || []).map(String).join(" → ");
}

function planBlock(w, prefix) {
  if (w.mode !== "list" || !w.plan || !(w.legs || []).length) return null;
  const total = fmtDist(w.total_m);
  const head =
    w.plan === "order"
      ? h(
          "p",
          { class: "place-plan-line" },
          h("strong", { text: `${t("places.order")} · ` }),
          h("span", {
            class: "place-plan-seq",
            text: t("places.orderLine", { seq: orderLine(w.order), d: total }),
          }),
        )
      : h(
          "p",
          { class: "place-plan-line" },
          h("strong", { text: `${t("places.legs")} · ` }),
          h("span", {
            text: w.legs
              .map((x) => `${x.a}–${x.b} ${fmtDist(x.m)}`)
              .join(" · "),
          }),
        );
  const matrix =
    Array.isArray(w.matrix) &&
    w.matrix.length > 2 &&
    h(
      "details",
      { class: "place-matrix" },
      h("summary", { text: t("places.matrix") }),
      h(
        "div",
        { class: "place-matrix-scroll" },
        h(
          "table",
          null,
          h(
            "thead",
            null,
            h(
              "tr",
              null,
              h("th", { scope: "col", text: "" }),
              w.matrix.map((_, j) =>
                h("th", { scope: "col", text: String(j + 1) }),
              ),
            ),
          ),
          h(
            "tbody",
            null,
            w.matrix.map((row, i) =>
              h(
                "tr",
                null,
                h("th", { scope: "row", text: String(i + 1) }),
                row.map((m, j) =>
                  h("td", { text: i === j ? "—" : fmtDist(m) }),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  return h(
    "div",
    { class: "place-plan", id: `${prefix}-plan` },
    head,
    matrix,
    ext(
      safeUrl(w.itinerary || ""),
      t("places.itinerary"),
      "btn btn-outline btn-small",
    ),
  );
}

// the places of a list that are not on the map, each kind said for what it is: not found (the provider answered
// with nothing), not checked (the map service failed or was busy: never shown as « not found ») or not shown
// (past the 25 places or the size of one card)
const LEFT_OUT = [
  ["missing", "places.missing"],
  ["unchecked", "places.unchecked"],
  ["not_shown", "places.notShown"],
];

function missingLine(w) {
  const lines = LEFT_OUT.map(([field, key]) => {
    const names = (w[field] || []).map(String).filter(Boolean);
    if (!names.length) return null;
    return h(
      "p",
      { class: "place-missing", role: "note" },
      icon("alert"),
      h("span", {
        text: t(names.length === 1 ? `${key}.one` : `${key}.many`, {
          n: names.length,
          list: names.join(" ; "),
        }),
      }),
    );
  }).filter(Boolean);
  return lines.length ? lines : null;
}

function renderPlaces(w, turn) {
  const max = w.mode === "list" ? LIST_MAX : MAX_CARDS;
  const places = (w.places || [])
    .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon))
    .slice(0, max);
  if (!places.length) return null;
  const prefix = `pl-${turn.id}-${Math.random().toString(36).slice(2, 6)}`;
  const shown = w.mode === "list" ? 5 : 3;
  let sec = null;
  let cards = [];
  let open = false;
  let more = null;
  const showAll = (on) => {
    open = on;
    cards.forEach(
      (c, i) => (c.hidden = !open && i >= shown && cards.length > shown + 1),
    );
    if (more) {
      more.setAttribute("aria-expanded", String(open));
      more.querySelector(".btn-label").textContent = moreLabel();
      more.classList.toggle("is-open", open);
    }
  };
  const focusCard = (p) => {
    const card = document.getElementById(`${prefix}-${p.n}`);
    if (!card) return;
    if (card.hidden) showAll(true);
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
  const frame = mapFrame(w, places, center, {
    alt,
    onPin: focusCard,
    onCluster: (members) => focusCard(members[0]),
    onFull: () => toggleFull(),
  });
  // a planned list (« dans quel ordre les visiter ») is listed in its visit order, each card with its leg
  const byN = new Map(places.map((p) => [p.n, p]));
  const legTo = new Map((w.legs || []).map((x) => [x.b, x]));
  const ordered =
    w.mode === "list" && w.plan === "order" && Array.isArray(w.order)
      ? w.order.map((n) => byN.get(n)).filter(Boolean)
      : places;
  cards = ordered.map((p) => placeCard(p, w.mode, prefix, legTo.get(p.n)));
  const list = h(
    "ol",
    { class: "place-list", "aria-label": placesTitle(w), id: `${prefix}-list` },
    cards,
  );
  const hiddenN = Math.max(0, cards.length - shown);
  const moreLabel = () =>
    open ? t("places.less") : t("places.more", { n: hiddenN });
  // a toggle, not a self-removing button: keyboard focus never drops to <body>
  if (cards.length > shown + 1)
    more = button(
      "btn-outline btn-small place-more",
      "down",
      moreLabel(),
      () => {
        showAll(!open);
        if (open) cards[shown].focus();
      },
      { "aria-expanded": "false", "aria-controls": `${prefix}-list` },
    );
  showAll(false);
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
  // full screen: the map and its list fill the window (the list is a bottom sheet on a phone); Escape closes
  let back = null;
  const close = button(
    "btn-icon map-full-close",
    "cross",
    t("map.fullClose"),
    () => toggleFull(false),
  );
  // a modal: Escape closes, Tab wraps inside it, and the page behind is inert (keyboard and screen readers)
  let inerted = [];
  const onKey = (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      toggleFull(false);
    } else if (e.key === "Tab") {
      const all = focusables(sec);
      if (!all.length) return;
      const first = all[0];
      const last = all[all.length - 1];
      const inside = sec.contains(document.activeElement);
      if (e.shiftKey && (!inside || document.activeElement === first)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (!inside || document.activeElement === last)) {
        e.preventDefault();
        first.focus();
      }
    }
  };
  // the turn is redrawn while the model writes: what it adds next to the card is not inert yet, focus comes back
  const onFocus = (e) => {
    if (!sec.contains(e.target)) close.focus({ preventScroll: true });
  };
  function toggleFull(force) {
    const on = force ?? !sec.classList.contains("is-full");
    if (on === sec.classList.contains("is-full")) return;
    sec.classList.toggle("is-full", on);
    document.documentElement.classList.toggle("has-map-full", on);
    if (on) {
      back = document.activeElement;
      sec.setAttribute("role", "dialog");
      sec.setAttribute("aria-modal", "true");
      document.addEventListener("keydown", onKey, true);
      document.addEventListener("focusin", onFocus, true);
      inerted = inertAround(sec);
      showAll(true);
      close.focus({ preventScroll: true });
    } else {
      sec.removeAttribute("role");
      sec.removeAttribute("aria-modal");
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("focusin", onFocus, true);
      for (const el of inerted) el.inert = false;
      inerted = [];
      showAll(false);
      // the button that opened it may be gone (the card was drawn again): this card's own button then
      (back?.isConnected ? back : sec.querySelector(".map-full"))?.focus?.({
        preventScroll: true,
      });
    }
    frame?._place?.();
  }
  const itinerary =
    w.mode === "list" && !w.plan && places.length >= 2
      ? ext(safeUrl(w.itinerary || ""), t("places.itinerary"))
      : null;
  sec = section(
    "places",
    placesTitle(w),
    close,
    h(
      "div",
      { class: "widget-head-links" },
      ext(osmAll, t("widget.openOsm")),
      itinerary && " · ",
      itinerary,
    ),
    frame,
    route,
    planBlock(w, prefix),
    missingLine(w),
    h("div", { class: "place-sheet" }, list, more),
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
  sec._full = toggleFull; // turns.js: a card drawn again hands its full screen over (moveFull)
  // turns.js, after each redraw of the turn: what was drawn next to an open card is made inert too, and a focus
  // lost when the card was moved in the page comes back to it
  sec._reinert = () => {
    if (!sec.classList.contains("is-full")) return;
    for (const el of inerted) el.inert = false;
    inerted = inertAround(sec);
    // the turn may be drawn before it is put back in the page: the focus is checked once it is there
    requestAnimationFrame(() => {
      if (sec.classList.contains("is-full") && !sec.contains(document.activeElement))
        close.focus({ preventScroll: true });
    });
  };
  return sec;
}

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])';

function focusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter(
    (el) => !el.closest("[hidden],[inert]") && el.getClientRects().length,
  );
}

/** Make everything but ``el`` and its ancestors inert; returns what was changed (to undo it). */
function inertAround(el) {
  const out = [];
  for (let n = el; n && n.parentElement && n !== document.body; n = n.parentElement) {
    for (const sib of n.parentElement.children) {
      if (sib === n || sib.inert || sib.tagName === "SCRIPT") continue;
      sib.inert = true;
      out.push(sib);
    }
  }
  return out;
}

/** A card list drawn again (the answer's cards replace the early ones): a map open in full screen in ``old`` is
 * closed there, so the page is never left locked, and opened on the same card of ``next``. */
export function moveFull(old, next) {
  const cards = (root) => [...(root?.querySelectorAll?.(".widget-places") || [])];
  const i = cards(old).findIndex((s) => s.classList.contains("is-full"));
  if (i < 0) return;
  cards(old)[i]._full?.(false);
  const target = cards(next)[i];
  if (target?._full) requestAnimationFrame(() => target.isConnected && target._full(true));
}

// ------------------------------------------------------------------ company

/** "383 474 814" (SIREN), "383 474 814 00100" (SIRET): the groups used by the register. */
export function fmtSiren(v) {
  const d = String(v || "");
  if (/^\d{9}$/.test(d))
    return `${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6)}`;
  if (/^\d{14}$/.test(d))
    return `${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6, 9)} ${d.slice(9)}`;
  return d;
}

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
  const sirenFmt = fmtSiren(siren);
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
    w.siret && [
      "company.siret",
      h("span", { class: "num", text: fmtSiren(w.siret) }),
    ],
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
      rows.map(([k, v]) =>
        h("div", null, h("dt", { text: t(k) }), h("dd", null, v)),
      ),
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
          w.candidates.map((c) => {
            const shown = String(c.siren) === siren;
            const label = [c.name, fmtSiren(c.siren), c.commune]
              .filter(Boolean)
              .join(" · ");
            return h(
              "li",
              shown ? { "aria-current": "true", class: "is-current" } : null,
              shown
                ? [
                    h("span", { text: label }),
                    h("span", { class: "pill", text: t("company.shown") }),
                  ]
                : ext(safeUrl(c.url), label),
            );
          }),
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
    const raw = String(input.value).trim().replace(",", ".");
    const amount = Number(raw);
    curLabel.textContent = from;
    // empty, negative or not a number: no figure at all rather than "0,00 €" or "-4,55 €"
    result.textContent =
      raw === "" || !Number.isFinite(amount) || amount < 0
        ? "—"
        : money(amount * rate, to);
    inverse.textContent = `1 ${from} = ${nf({ maximumFractionDigits: 4 }).format(rate)} ${to} · 1 ${to} = ${nf({ maximumFractionDigits: 4 }).format(1 / rate)} ${from}`;
  };
  input.addEventListener("input", paint);
  const swap = button(
    "btn-outline btn-small fx-swap",
    "swap",
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
export { placesTitle };

export function eventChips(f, holidays = {}, warnings = []) {
  const out = [];
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(f.date || ""));
  if (m) {
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    const known = warnings.find(
      (x) => x.kind === "holiday" && x.date === f.date,
    );
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
  else if (f.assumedEnd || !f.end)
    out.push(["info", t("event.defaultDuration")]);
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
    w.weather &&
      h(
        "p",
        { class: "ev-weather" },
        wxIcon(w.weather.icon, 22),
        h("span", {
          text: t("event.weather", {
            place: w.weather.place,
            sky: String(w.weather.label || "").toLowerCase(),
            min: deg(w.weather.min),
            max: deg(w.weather.max),
          }),
        }),
        w.weather.rain > 0 &&
          h("span", { class: "muted", text: ` · ${mm(w.weather.rain)}` }),
      ),
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

// ------------------------------------------------------------------ weather (MET Norway forecast, drawn here)

const SVGNS = "http://www.w3.org/2000/svg";
function sv(tag, attrs, ...children) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {}))
    if (v !== null && v !== undefined && v !== false)
      el.setAttribute(k, String(v));
  for (const c of children.flat())
    if (c) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}

// weather glyphs on a 32 x 32 grid: unions of plain shapes, coloured by class (tokens in app.css, light and dark)
const rays = (cx, cy, r1, r2, cls = "wx-ray") =>
  [0, 45, 90, 135, 180, 225, 270, 315].map((a) => {
    const c = Math.cos((a * Math.PI) / 180);
    const s = Math.sin((a * Math.PI) / 180);
    return sv("line", {
      class: cls,
      x1: (cx + r1 * c).toFixed(2),
      y1: (cy + r1 * s).toFixed(2),
      x2: (cx + r2 * c).toFixed(2),
      y2: (cy + r2 * s).toFixed(2),
    });
  });
const sun = (cx, cy, r) => [
  ...rays(cx, cy, r + 2.6, r + 5.2),
  sv("circle", { class: "wx-sun", cx, cy, r }),
];
const moon = (tf = null) =>
  sv("path", {
    class: "wx-moon",
    d: "M13.1 8.23A8 8 0 1 0 22.77 17.9A7 7 0 0 1 13.1 8.23z",
    transform: tf,
  });
// a cloud: three discs and a base; ``high`` leaves room below for rain or snow
function cloud(high, cls = "wx-cloud", dx = 0, dy = 0) {
  const y = (high ? 0 : 4) + dy;
  return sv(
    "g",
    { class: cls },
    sv("circle", { cx: 11 + dx, cy: 15 + y, r: 5 }),
    sv("circle", { cx: 17.5 + dx, cy: 11.5 + y, r: 6.5 }),
    sv("circle", { cx: 23 + dx, cy: 15.5 + y, r: 4.5 }),
    sv("rect", { x: 11 + dx, y: 14.5 + y, width: 12, height: 5.5, rx: 1 }),
  );
}
const drops = (xs, len = 4) =>
  xs.map((x) =>
    sv("line", { class: "wx-drop", x1: x, y1: 23, x2: x - 1.4, y2: 23 + len }),
  );
const flakes = (pts) =>
  pts.map(([x, y]) =>
    sv("circle", { class: "wx-flake", cx: x, cy: y, r: 1.6 }),
  );

const GLYPHS = {
  sun: () => sun(16, 16, 6),
  moon: () => [moon()],
  partly_day: () => [...sun(11.5, 11.5, 4.4), cloud(false, "wx-cloud", 2, 1)],
  partly_night: () => [
    moon("translate(-2.5 -3.5) scale(0.78)"),
    cloud(false, "wx-cloud", 2, 1),
  ],
  cloud: () => [cloud(false)],
  fog: () => [
    cloud(true, "wx-cloud wx-cloud-fog", 0, -2),
    ...[20, 24, 28].map((y, i) =>
      sv("line", {
        class: "wx-fog",
        x1: 6 + (i % 2) * 3,
        y1: y,
        x2: 26 - (i % 2) * 2,
        y2: y,
      }),
    ),
  ],
  drizzle: () => [
    cloud(true, "wx-cloud wx-cloud-rain"),
    ...drops([13, 20], 3.2),
  ],
  rain: () => [
    cloud(true, "wx-cloud wx-cloud-rain"),
    ...drops([11, 16.5, 22], 5),
  ],
  showers: () => [
    ...sun(10.5, 9.5, 3.8),
    cloud(true, "wx-cloud wx-cloud-rain", 2, 0),
    ...drops([15, 21], 4.2),
  ],
  sleet: () => [
    cloud(true, "wx-cloud wx-cloud-rain"),
    ...drops([12], 4.5),
    ...flakes([[19.5, 25.5]]),
  ],
  snow: () => [
    cloud(true, "wx-cloud"),
    ...flakes([
      [11, 24.5],
      [16.5, 28],
      [22, 24.5],
    ]),
  ],
  // no symbol from MET, or one we do not know: a dashed ring, never a cloud that would say « cloudy »
  unknown: () => [
    sv("circle", { class: "wx-unknown", cx: 16, cy: 16, r: 9 }),
    sv("line", { class: "wx-unknown", x1: 12, y1: 16, x2: 20, y2: 16 }),
  ],
  thunder: () => [
    cloud(true, "wx-cloud wx-cloud-rain"),
    sv("polygon", {
      class: "wx-bolt",
      points: "17.5,19 12.5,25.5 16,25.5 14,31 21,23.5 17.4,23.5 19.6,19",
    }),
  ],
};

/** An inline SVG weather icon (decorative: the label is written next to it). */
export function wxIcon(name, size = 32, label = "") {
  const draw = GLYPHS[name] || GLYPHS.unknown;
  return sv(
    "svg",
    {
      class: `wx-icon wx-${GLYPHS[name] ? name : "unknown"}`,
      viewBox: "0 0 32 32",
      width: size,
      height: size,
      role: label ? "img" : null,
      "aria-label": label || null,
      "aria-hidden": label ? null : "true",
      focusable: "false",
    },
    label ? sv("title", null, label) : null,
    draw(),
  );
}

const deg = (v) =>
  v === null || v === undefined
    ? "–"
    : `${nf({ maximumFractionDigits: 0 }).format(Math.round(v) || 0).replace(/^-/, "−")}°`;
const mm = (v) => `${nf({ maximumFractionDigits: 1 }).format(v)} mm`;

function wxDate(iso, opts) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  return m
    ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], 12)).toLocaleDateString(
        locale(),
        {
          timeZone: "UTC",
          ...opts,
        },
      )
    : "";
}

/** The hourly strip: temperature line with labels, rain bars, hours. Redrawn at the real width (text at 12 px). */
export function hourlyStrip(hours, width) {
  const pts = (hours || []).filter(
    (p) => /T\d{2}:\d{2}$/.test(p.t) && Number.isFinite(p.temp),
  );
  const W = Math.max(260, Math.round(width || 640));
  const H = 148;
  const padX = 14;
  if (pts.length < 2) return null;
  const tOf = (p) => {
    const [d, hm] = p.t.split("T");
    const [y, mo, da] = d.split("-").map(Number);
    const [hh, mi] = hm.split(":").map(Number);
    return Date.UTC(y, mo - 1, da, hh, mi) / 3600000;
  };
  const t0 = tOf(pts[0]);
  const last = pts[pts.length - 1];
  const t1 = Math.max(tOf(last) + (last.step || 1), t0 + 6);
  const x = (t) => padX + ((t - t0) / (t1 - t0)) * (W - 2 * padX);
  const temps = pts.map((p) => p.temp);
  let lo = Math.min(...temps);
  let hi = Math.max(...temps);
  if (hi - lo < 4) {
    const mid = (hi + lo) / 2;
    lo = mid - 2;
    hi = mid + 2;
  }
  const yT = (v) => 44 + (1 - (v - lo) / (hi - lo)) * 42; // line between y 44 and 86
  const rains = pts.map((p) => (p.rain || 0) / (p.step || 1));
  const rMax = Math.max(1, ...rains);
  const base = 122;
  const g = [];
  // light grid: the bar baseline
  g.push(
    sv("line", {
      class: "wx-axis",
      x1: padX,
      y1: base + 0.5,
      x2: W - padX,
      y2: base + 0.5,
    }),
  );
  const hourW = (W - 2 * padX) / (t1 - t0);
  for (const p of pts) {
    const r = p.rain || 0;
    if (r <= 0) continue;
    const step = p.step || 1;
    const bh = Math.max(2, (r / step / rMax) * 30);
    g.push(
      sv("rect", {
        class: "wx-bar",
        x: (x(tOf(p)) + 1).toFixed(1),
        y: (base - bh).toFixed(1),
        width: Math.max(2, hourW * step - 2).toFixed(1),
        height: bh.toFixed(1),
        rx: 1.5,
      }),
    );
  }
  const line = pts
    .map(
      (p, i) =>
        `${i ? "L" : "M"}${x(tOf(p)).toFixed(1)} ${yT(p.temp).toFixed(1)}`,
    )
    .join(" ");
  const area = `${line} L${x(tOf(last)).toFixed(1)} 92 L${x(t0).toFixed(1)} 92 Z`;
  g.push(sv("path", { class: "wx-area", d: area }));
  g.push(sv("path", { class: "wx-line", d: line }));
  // labels: every 3 h on wide screens, every 4 or 6 h on narrow ones, always on 6-hour points
  const every = W < 340 ? 4 : W < 480 ? 3 : 2;
  const hiIdx = temps.indexOf(Math.max(...temps));
  const loIdx = temps.indexOf(Math.min(...temps));
  let lastX = -99;
  pts.forEach((p, i) => {
    const hh = Number(p.t.slice(11, 13));
    const xi = x(tOf(p));
    const keyPoint = i === 0 || i === hiIdx || i === loIdx;
    const regular = (p.step || 1) >= 6 || hh % every === 0;
    if (!(regular || keyPoint) || xi - lastX < 34) return;
    lastX = xi;
    g.push(
      sv("circle", {
        class: "wx-dot",
        cx: xi.toFixed(1),
        cy: yT(p.temp).toFixed(1),
        r: 2.6,
      }),
    );
    g.push(
      sv(
        "text",
        {
          class: "wx-t",
          x: xi.toFixed(1),
          y: (yT(p.temp) - 8).toFixed(1),
          "text-anchor": "middle",
        },
        deg(p.temp),
      ),
    );
    if (p.icon) {
      const ic = wxIcon(p.icon, 18);
      ic.setAttribute("x", (xi - 9).toFixed(1));
      ic.setAttribute("y", "2");
      g.push(ic);
    }
    g.push(
      sv(
        "text",
        {
          class: "wx-h",
          x: xi.toFixed(1),
          y: H - 6,
          "text-anchor": i === 0 ? "start" : xi > W - 30 ? "end" : "middle",
        },
        i === 0 && hours.now ? t("weather.nowShort") : `${hh}h`,
      ),
    );
  });
  // rain amounts above the wettest bar only (the rest is in the tooltip-free table below for screen readers)
  const wet = rains.indexOf(Math.max(...rains));
  if (rains[wet] > 0) {
    const p = pts[wet];
    g.push(
      sv(
        "text",
        {
          class: "wx-r",
          x: (x(tOf(p)) + (hourW * (p.step || 1)) / 2).toFixed(1),
          y: (base - Math.max(2, (rains[wet] / rMax) * 30) - 4).toFixed(1),
          "text-anchor": "middle",
        },
        mm(p.rain),
      ),
    );
  }
  return sv(
    "svg",
    {
      class: "wx-strip",
      viewBox: `0 0 ${W} ${H}`,
      width: W,
      height: H,
      role: "img",
      "aria-label": t("weather.stripAlt"),
    },
    g,
  );
}

function renderWeather(w) {
  const s = w.summary || {};
  const place = w.place || {};
  const day = String(w.day || "");
  const dayName =
    w.day_kind === "today"
      ? t("weather.today")
      : w.day_kind === "tomorrow"
        ? t("weather.tomorrow")
        : wxDate(day, { weekday: "long" });
  const dayFull = wxDate(day, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const label = String(s.label || "");
  const big = h(
    "div",
    { class: "wx-now" },
    wxIcon(s.icon, 64),
    h(
      "div",
      { class: "wx-now-text" },
      h("span", { class: "wx-temp num", text: deg(s.temp) }),
      h("span", { class: "wx-sky", text: label }),
      h("span", {
        class: "wx-when muted",
        text:
          s.kind === "now"
            ? t("weather.nowAt", { time: String(s.at || "").slice(11, 16) })
            : t("weather.dayMax"),
      }),
    ),
  );
  const head = h(
    "div",
    { class: "wx-head" },
    h(
      "div",
      { class: "wx-place" },
      h("strong", { class: "wx-name", text: place.name || "" }),
      place.region &&
        h("span", { class: "muted wx-region", text: place.region }),
      h(
        "span",
        { class: "wx-day" },
        w.day_kind !== "date" && h("span", { class: "pill wx-pill", text: dayName }),
        h("span", { class: w.day_kind === "date" ? "wx-date" : "muted", text: dayFull }),
      ),
    ),
    big,
  );
  const facts = [
    s.min != null &&
      s.max != null && [t("weather.minmax"), `${deg(s.min)} / ${deg(s.max)}`],
    s.rain_mm != null && [
      t("weather.rain"),
      mm(s.rain_mm) +
        (s.rain_prob != null
          ? ` · ${nf({ maximumFractionDigits: 0 }).format(s.rain_prob)} %`
          : ""),
    ],
    s.wind_kmh != null && [t("weather.wind"), `${s.wind_kmh} km/h`],
  ].filter(Boolean);
  const kv = h(
    "dl",
    { class: "wx-facts" },
    facts.map(([k, v]) =>
      h(
        "div",
        { class: "wx-fact" },
        h("dt", { text: k }),
        h("dd", { class: "num", text: v }),
      ),
    ),
  );
  // the hourly strip, redrawn at the width it really has
  const hours = (w.hours || []).slice(0, 30);
  hours.now = s.kind === "now";
  const six = hours.some((p) => (p.step || 1) >= 6);
  const stripBox = h("div", { class: "wx-strip-box" });
  const draw = () => {
    const width = stripBox.clientWidth || 640;
    if (Math.abs((stripBox._w || 0) - width) < 2 && stripBox.firstChild) return;
    stripBox._w = width;
    const svg = hourlyStrip(hours, width);
    stripBox.replaceChildren(...(svg ? [svg] : []));
  };
  draw();
  if (typeof ResizeObserver !== "undefined")
    new ResizeObserver(draw).observe(stripBox);
  const hourly =
    hours.length > 1 &&
    h(
      "div",
      { class: "wx-block" },
      h(
        "p",
        { class: "wx-block-title" },
        h("span", { text: six ? t("weather.hourly6") : t("weather.hourly") }),
        h(
          "span",
          { class: "wx-legend muted" },
          h("span", { class: "wx-key wx-key-line", "aria-hidden": "true" }),
          t("weather.temp"),
          h("span", { class: "wx-key wx-key-bar", "aria-hidden": "true" }),
          t("weather.rainMm"),
        ),
      ),
      stripBox,
    );
  const tiles = (w.days || []).slice(0, 7);
  const week =
    tiles.length > 1 &&
    h(
      "div",
      { class: "wx-block" },
      h(
        "p",
        { class: "wx-block-title" },
        h("span", { text: t("weather.days", { n: tiles.length }) }),
      ),
      h(
        "ol",
        { class: "wx-days" },
        tiles.map((d) =>
          h(
            "li",
            {
              class: `wx-tile${d.d === day ? " is-current" : ""}`,
              "aria-current": d.d === day ? "date" : null,
              title: d.label || null,
            },
            h("span", {
              class: "wx-dow",
              text: wxDate(d.d, { weekday: "short" }),
            }),
            wxIcon(d.icon, 26, d.label || ""),
            h("span", { class: "wx-hi num", text: deg(d.max) }),
            h("span", { class: "wx-lo num", text: deg(d.min) }),
            h("span", {
              class: `wx-mm num${d.rain > 0 ? "" : " is-dry"}`,
              // null: MET gave no precipitation for that day, which is not « 0 »
              text:
                d.rain == null
                  ? "–"
                  : d.rain > 0
                    ? nf({ maximumFractionDigits: 1 }).format(d.rain)
                    : "0",
              "aria-label":
                d.rain == null
                  ? t("weather.rainUnknown")
                  : d.rain > 0
                    ? mm(d.rain)
                    : t("weather.noRain"),
            }),
          ),
        ),
      ),
      h("p", { class: "wx-unit muted", text: t("weather.tileUnit") }),
    );
  const upd = /T(\d{2}:\d{2})/.exec(String(w.updated || ""));
  const tz = String(w.tz || "UTC");
  return section(
    "weather",
    t("weather.title"),
    head,
    facts.length && kv,
    hourly,
    week,
    footer(
      h("span", { text: `${t("weather.forecast")} · ` }),
      ext(safeUrl(w.source?.url || ""), t("weather.data")),
      " · ",
      ext(safeUrl(w.license?.url || ""), `${t("weather.license")} ${w.license?.label || "CC BY 4.0"}`),
      upd &&
        h("span", {
          text: ` · ${t("weather.updated", { time: `${upd[1]} UTC` })}`,
        }),
      h("span", {
        class: "muted",
        text: ` · ${tz === "UTC" ? t("weather.tzUtc") : t("weather.tz", { tz: tz.split("/").pop().replace(/_/g, " ") })}`,
      }),
    ),
  );
}

// ------------------------------------------------------------------ world clock + common slot

const hhmm = (zone, at = new Date()) => {
  try {
    return new Intl.DateTimeFormat(locale(), {
      timeZone: zone,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(at);
  } catch {
    return "";
  }
};
const dayIn = (zone, at = new Date()) => {
  try {
    return new Intl.DateTimeFormat(locale(), {
      timeZone: zone,
      weekday: "short",
    }).format(at);
  } catch {
    return "";
  }
};

/** "+6 h", "−4 h 30" (minutes of difference with the user's zone). */
export function fmtDiff(min) {
  if (!min) return t("clock.same");
  const a = Math.abs(min);
  const hh = Math.floor(a / 60);
  const mi = a % 60;
  const span = mi ? `${hh} h ${String(mi).padStart(2, "0")}` : `${hh} h`;
  return `${min > 0 ? "+" : "−"}${span}`;
}

/** The text copied by « Copier le créneau ». */
export function slotText(w, slot, wide = false) {
  const rows = w.cities || [];
  const day = wxDate(w.timeline?.date, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const parts = rows.map(
    (r, i) => `${slot.local[i][0]}–${slot.local[i][1]} ${r.name}`,
  );
  return `${t(wide ? "clock.wideShort" : "clock.common")} (${day}) : ${parts.join(" · ")}`;
}

function renderClock(w) {
  const rows = w.cities || [];
  if (!rows.length) return null;
  const timeEls = [];
  const list = h(
    "ul",
    { class: "ck-list" },
    rows.map((r) => {
      const time = h("span", {
        class: "ck-time num",
        text: hhmm(r.zone) || String(r.local || "").slice(11, 16),
      });
      const dayEl = h("span", { class: "ck-dow", text: dayIn(r.zone) });
      timeEls.push([time, dayEl, r.zone]);
      return h(
        "li",
        { class: `ck-row${r.user ? " is-user" : ""}` },
        h(
          "span",
          { class: "ck-city" },
          h("strong", { text: r.name }),
          r.user && h("span", { class: "pill ck-you", text: t("clock.you") }),
          h(
            "span",
            { class: "muted ck-meta" },
            [
              r.offset,
              !r.user ? fmtDiff(r.diff_min) : "",
              r.multi ? t("clock.multi") : "",
            ]
              .filter(Boolean)
              .join(" · "),
          ),
        ),
        h("span", { class: "ck-clock" }, dayEl, time),
      );
    }),
  );
  // live: the times follow the browser's clock (the zone database is the browser's own: no request)
  const timer = window.setInterval(() => {
    if (!list.isConnected) {
      if (list._seen) window.clearInterval(timer); // the turn was removed: stop
      return;
    }
    list._seen = true;
    for (const [el, d, zone] of timeEls) {
      el.textContent = hhmm(zone) || el.textContent;
      d.textContent = dayIn(zone) || d.textContent;
    }
  }, 15000);
  const tl = w.timeline;
  let board = null;
  let actions = null;
  let note = null;
  if (tl && Array.isArray(tl.rows) && tl.rows.length === rows.length) {
    const cols = 24;
    const grid = h("div", {
      class: "ck-grid",
      role: "img",
      "aria-label": t("clock.gridAlt"),
    });
    const place = (el, c1, c2, r1, r2) => {
      el.style.gridColumn = `${c1} / ${c2}`;
      el.style.gridRow = `${r1} / ${r2}`;
      return el;
    };
    // hours of the user's day, every 3 h
    tl.user_hours.forEach((hh, i) => {
      if (i % 3 === 0)
        grid.append(
          place(
            h("span", { class: "ck-hour", text: `${hh}h` }),
            i + 2,
            i + 5,
            1,
            2,
          ),
        );
    });
    rows.forEach((r, ri) => {
      grid.append(
        place(
          h("span", {
            class: `ck-label${r.user ? " is-user" : ""}`,
            text: r.name,
          }),
          1,
          2,
          ri + 2,
          ri + 3,
        ),
      );
      const row = tl.rows[ri];
      for (let i = 0; i < cols; i++) {
        const q = row.office[i] || 0; // quarters of this hour within office hours
        const lh = Math.floor(row.hours[i]);
        const night = lh < 7 || lh >= 21;
        const cell = h("span", {
          class: `ck-cell${q === 4 ? " is-office" : q > 0 ? " is-part" : night ? " is-night" : ""}`,
        });
        if (i % 3 === 0) cell.dataset.h = String(lh);
        if (i % 6 === 0) cell.classList.add("is-major");
        grid.append(place(cell, i + 2, i + 3, ri + 2, ri + 3));
      }
    });
    const slots = (w.common || []).length ? w.common : w.wide || [];
    const wide = !(w.common || []).length && slots.length > 0;
    const uz = w.user_tz;
    // columns from the board's first hour (the user's local midnight, an UTC instant computed by the server)
    const t0 = Date.parse(String(tl.start || "").replace(/Z$/, ":00Z"));
    const startCol = (iso) =>
      (Date.parse(String(iso).replace(/Z$/, ":00Z")) - t0) / 3600000;
    for (const sl of slots) {
      const a = startCol(sl.start);
      const b = startCol(sl.end);
      const c1 = Math.max(0, Math.floor(a));
      const c2 = Math.min(24, Math.ceil(b));
      if (c2 <= c1) continue;
      grid.append(
        place(
          h("span", {
            class: `ck-band${wide ? " is-wide" : ""}`,
            "aria-hidden": "true",
          }),
          c1 + 2,
          c2 + 2,
          2,
          rows.length + 2,
        ),
      );
    }
    // now, when the board shows today
    const now = new Date();
    const todayHere = new Intl.DateTimeFormat("en-CA", { timeZone: uz }).format(
      now,
    );
    if (todayHere === tl.date) {
      const [hh, mi] = (hhmm(uz, now) || "0:0").split(":").map(Number);
      const nowEl = h("span", { class: "ck-now", "aria-hidden": "true" });
      nowEl.style.setProperty("--at", String((hh + mi / 60) / 24));
      grid.append(place(nowEl, 2, 26, 2, rows.length + 2));
    }
    const me = Math.max(
      0,
      rows.findIndex((r) => r.user),
    );
    const dayLabel = wxDate(tl.date, {
      weekday: "long",
      day: "numeric",
      month: "long",
    });
    note = slots.length
      ? h(
          "div",
          { class: `ck-slot${wide ? " is-wide" : ""}` },
          h("span", {
            class: "ck-slot-title",
            text: wide ? t("clock.none") : t("clock.common"),
          }),
          wide && h("span", { class: "muted", text: t("clock.wide") }),
          h(
            "ul",
            { class: "ck-slot-list" },
            slots.slice(0, 3).map((sl) =>
              h(
                "li",
                null,
                h("strong", {
                  class: "num",
                  text: `${sl.local[me][0]}–${sl.local[me][1]}`,
                }),
                h("span", {
                  class: "muted",
                  text: ` ${t("clock.yourTime", { city: rows[me].name })}`,
                }),
                h(
                  "span",
                  { class: "ck-slot-others" },
                  rows
                    .map((r, i) =>
                      i === me
                        ? ""
                        : `${r.name} ${sl.local[i][0]}–${sl.local[i][1]}`,
                    )
                    .filter(Boolean)
                    .join(" · "),
                ),
              ),
            ),
          ),
        )
      : h("p", { class: "widget-note", text: t("clock.noneAtAll") });
    board = h(
      "div",
      { class: "ck-board" },
      h(
        "p",
        { class: "wx-block-title" },
        h("span", { text: t("clock.board", { day: dayLabel }) }),
        h(
          "span",
          { class: "wx-legend muted" },
          h("span", { class: "ck-key is-office", "aria-hidden": "true" }),
          t("clock.office"),
        ),
      ),
      grid,
    );
    if (slots.length)
      actions = h(
        "p",
        { class: "place-actions" },
        button(
          "btn-outline btn-small",
          "copy",
          t("clock.copy"),
          () => copyText(slotText(w, slots[0], wide)),
          {
            "data-act": "copy-slot",
          },
        ),
      );
  }
  return section(
    "clock",
    t("clock.title"),
    list,
    board,
    note,
    actions,
    footer(h("span", { text: t("clock.foot") })),
  );
}
// ------------------------------------------------------------------ registry

const RENDER = {
  places: renderPlaces,
  company: renderCompany,
  fx: renderFx,
  weather: renderWeather,
  clock: renderClock,
  event: renderEvent,
  ...MODULES, // research, graph, timeline, matrix, calc, checklist (modules.js)
  ...REPORT_MODULES, // the deep research report card and its full-screen view (research.js)
  datacard: renderDataCard, // data analysis hook (datakit.js)
  ...OPENDATA_RENDER, // open data (opendata.js)
};
useMapFrame(mapFrame); // open data: the commune card's map is the same frame as the others

export function renderWidgets(turn, widgets = turn.answer?.widgets || []) {
  const list = (widgets || []).filter((w) => w && RENDER[w.type]);
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
    } else if (w.type === "weather") {
      const s = w.summary || {};
      out.push(
        `${w.place?.name || ""}, ${w.day} — ${s.label || ""}${s.min != null ? ` ${s.min}…${s.max} °C` : ""}${s.rain_mm ? ` — ${s.rain_mm} mm` : ""}${s.wind_kmh != null ? ` — ${s.wind_kmh} km/h` : ""} (${t("weather.forecast")}, ${t("weather.data")} CC BY 4.0)`,
      );
    } else if (w.type === "clock") {
      out.push(
        (w.cities || [])
          .map(
            (r) =>
              `${r.name} ${String(r.local || "").slice(11, 16)} (${r.offset})`,
          )
          .join(" · "),
      );
      const sl = (w.common || [])[0] || (w.wide || [])[0];
      if (sl) out.push(slotText(w, sl, !(w.common || []).length));
    } else if (w.type === "report") {
      out.push(reportText(w));
    } else if (MODULES[w.type]) {
      out.push(moduleText(w, turn, markdown));
    } else if (w.type === "datacard") {
      out.push(dataCardText(w)); // data analysis hook (datakit.js)
    } else if (w.type === "event") {
      out.push(
        `${w.title} — ${String(w.start).slice(0, 16).replace("T", " ")}${w.all_day ? "" : `–${String(w.end).slice(11, 16)}`}${w.location ? ` — ${w.location}` : ""}`,
      );
    } else out.push(opendataText(w, markdown)); // open data ("" for other types)
  }
  return out.filter(Boolean).join("\n");
}
