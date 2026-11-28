// Small modules under an answer: research card, relation graph, timeline, comparison matrix, calculator, checklist.
// Their data come from the server's `widgets` (verified tool results, the harness's own computations, the user's own
// data), never from model prose. Built with h() only (text nodes); SVG through setAttribute; no style attribute
// (CSP): positions through SVG attributes and CSSOM custom properties.
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
import { STRINGS } from "./i18n.js";
import { safeUrl } from "./markdown.js";

// ------------------------------------------------------------------ strings (FR first, EN parity)

const FR = {
  "mod.research.title": "Recherche approfondie",
  "mod.research.plan": "Plan de recherche",
  "mod.research.sources": "Sources lues",
  "mod.research.claims": "{n} affirmation(s) vérifiée(s)",
  "mod.research.none": "aucune affirmation retenue",
  "mod.research.counts":
    "{queries} recherche(s) · {kept} source(s) retenue(s) sur {read} lue(s) · {claims} affirmation(s) vérifiée(s)",
  "mod.research.own": "Vos documents",
  "mod.research.resolved": "Sous-question résolue",
  "mod.research.crossed": "{n} recoupée(s) par un autre site",
  "mod.research.note":
    "Chaque affirmation a été retrouvée mot pour mot dans sa source par Bird.",
  "mod.graph.title": "Carte des relations",
  "mod.graph.hint":
    "Touchez un nœud pour voir ses sources. Glissez pour déplacer, boutons pour zoomer.",
  "mod.graph.zoomIn": "Zoomer",
  "mod.graph.zoomOut": "Dézoomer",
  "mod.graph.reset": "Recentrer",
  "mod.graph.filter": "Filtrer par type",
  "mod.graph.list": "Voir sous forme de liste",
  "mod.graph.node": "{label}, {type}, {n} lien(s)",
  "mod.graph.claims": "Ce que disent les sources",
  "mod.graph.links": "Liens",
  "mod.graph.pick":
    "Sélectionnez un nœud pour afficher ses liens et ses sources.",
  "mod.graph.note":
    "Seules les relations retrouvées dans le texte des sources sont dessinées.",
  "mod.type.organisation": "Organisation",
  "mod.type.personne": "Personne",
  "mod.type.lieu": "Lieu",
  "mod.type.produit": "Produit",
  "mod.type.texte": "Texte, loi",
  "mod.type.concept": "Concept",
  "mod.timeline.title": "Chronologie",
  "mod.timeline.user": "D'après vos dates.",
  "mod.timeline.sources": "Dates relevées dans les sources.",
  "mod.matrix.title": "Comparaison",
  "mod.matrix.sort": "Trier par {col}",
  "mod.matrix.best": "meilleure valeur",
  "mod.matrix.verdict": "Recommandé",
  "mod.matrix.copy": "Copier le tableau",
  "mod.matrix.csv": "Exporter en CSV",
  "mod.matrix.user":
    "D'après votre tableau ; la meilleure valeur est marquée quand le sens est certain (prix, délai, note).",
  "mod.calc.title": "Calcul",
  "mod.calc.note":
    "Calcul exact fait par Bird, pas par le modèle. Modifiez une valeur pour recalculer.",
  "mod.calc.copy": "Copier le résultat",
  "mod.calc.formula": "Formule",
  "mod.check.title": "Liste de tâches",
  "mod.check.progress": "{done} sur {n} faites",
  "mod.check.copy": "Copier la liste",
  "mod.check.export": "Exporter (.md)",
  "mod.check.minutes":
    "Actions relevées dans vos notes (responsable et échéance vérifiés).",
  "mod.check.user": "D'après votre liste.",
  "mod.check.due": "échéance {due}",
  "mod.copied": "Copié",
  "mod.chips": "Suggestions",
  "mod.chips.clarify": "Réponses possibles",
  "mod.tf.title": "Transformer la réponse",
  "mod.tf.shorter": "Raccourcir",
  "mod.tf.longer": "Développer",
  "mod.tf.formal": "Plus formel",
  "mod.tf.translate": "Traduire en anglais",
  "mod.tf.table": "En tableau",
  "mod.tf.list": "En liste",
  "mod.gloss": "Définition",
  "mod.pc.pros": "Avantages",
  "mod.pc.cons": "Inconvénients",
  "mod.pc.user": "D'après vos points.",
  "mod.fig.user": "D'après vos chiffres, tels que vous les avez écrits.",
  "mod.gl.user": "D'après vos définitions.",
  "mod.gl.filter": "Filtrer les termes",
  "mod.gl.none": "Aucun terme ne correspond.",
  "mod.sc.note": "Pages lues par Bird pour cette réponse.",
  "mod.sc.open": "Ouvrir",
  "mod.sc.cite": "Copier la référence",
  "mod.sc.public": "Source publique",
};
const EN = {
  "mod.research.title": "Deep research",
  "mod.research.plan": "Research plan",
  "mod.research.sources": "Sources read",
  "mod.research.claims": "{n} claim(s) checked",
  "mod.research.none": "no claim kept",
  "mod.research.counts":
    "{queries} search(es) · {kept} source(s) kept of {read} read · {claims} claim(s) checked",
  "mod.research.own": "Your documents",
  "mod.research.resolved": "Sub-question resolved",
  "mod.research.crossed": "{n} corroborated by another site",
  "mod.research.note": "Bird found each claim word for word in its source.",
  "mod.graph.title": "Relation map",
  "mod.graph.hint":
    "Tap a node to see its sources. Drag to move, buttons to zoom.",
  "mod.graph.zoomIn": "Zoom in",
  "mod.graph.zoomOut": "Zoom out",
  "mod.graph.reset": "Re-centre",
  "mod.graph.filter": "Filter by type",
  "mod.graph.list": "Show as a list",
  "mod.graph.node": "{label}, {type}, {n} link(s)",
  "mod.graph.claims": "What the sources say",
  "mod.graph.links": "Links",
  "mod.graph.pick": "Select a node to show its links and sources.",
  "mod.graph.note":
    "Only relations found in the text of the sources are drawn.",
  "mod.type.organisation": "Organisation",
  "mod.type.personne": "Person",
  "mod.type.lieu": "Place",
  "mod.type.produit": "Product",
  "mod.type.texte": "Law, text",
  "mod.type.concept": "Concept",
  "mod.timeline.title": "Timeline",
  "mod.timeline.user": "From your dates.",
  "mod.timeline.sources": "Dates found in the sources.",
  "mod.matrix.title": "Comparison",
  "mod.matrix.sort": "Sort by {col}",
  "mod.matrix.best": "best value",
  "mod.matrix.verdict": "Recommended",
  "mod.matrix.copy": "Copy the table",
  "mod.matrix.csv": "Export as CSV",
  "mod.matrix.user":
    "From your table; the best value is marked when the direction is certain (price, delay, rating).",
  "mod.calc.title": "Calculation",
  "mod.calc.note":
    "Exact calculation by Bird, not by the model. Change a value to recompute.",
  "mod.calc.copy": "Copy the result",
  "mod.calc.formula": "Formula",
  "mod.check.title": "Task list",
  "mod.check.progress": "{done} of {n} done",
  "mod.check.copy": "Copy the list",
  "mod.check.export": "Export (.md)",
  "mod.check.minutes":
    "Action items found in your notes (owner and due date checked).",
  "mod.check.user": "From your list.",
  "mod.check.due": "due {due}",
  "mod.copied": "Copied",
  "mod.chips": "Suggestions",
  "mod.chips.clarify": "Possible answers",
  "mod.tf.title": "Transform the answer",
  "mod.tf.shorter": "Shorter",
  "mod.tf.longer": "Expand",
  "mod.tf.formal": "More formal",
  "mod.tf.translate": "Translate into French",
  "mod.tf.table": "As a table",
  "mod.tf.list": "As a list",
  "mod.gloss": "Definition",
  "mod.pc.pros": "Pros",
  "mod.pc.cons": "Cons",
  "mod.pc.user": "From your points.",
  "mod.fig.user": "From your figures, as you wrote them.",
  "mod.gl.user": "From your definitions.",
  "mod.gl.filter": "Filter the terms",
  "mod.gl.none": "No term matches.",
  "mod.sc.note": "Pages Bird read for this answer.",
  "mod.sc.open": "Open",
  "mod.sc.cite": "Copy the reference",
  "mod.sc.public": "Public source",
};
for (const [k, v] of Object.entries(FR)) STRINGS.fr[k] ??= v;
for (const [k, v] of Object.entries(EN)) STRINGS.en[k] ??= v;

let hooks = { onChange: () => {}, onSuggest: () => {}, headers: () => ({ "Content-Type": "application/json" }) };
/** app.js: how a module saves the conversation (ticks), sends a suggestion and builds API headers. */
export const setModuleHooks = (value) => (hooks = { ...hooks, ...value });
export const moduleHooks = () => hooks;

const SVG = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}, ...kids) => {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs))
    if (v !== null && v !== undefined && v !== false)
      el.setAttribute(k, String(v));
  for (const c of kids.flat())
    if (c) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
};
const locale = () => (state.prefs.lang === "en" ? "en-GB" : "fr-FR");
const TYPES = [
  "organisation",
  "personne",
  "lieu",
  "produit",
  "texte",
  "concept",
];
const typeOf = (x) => (TYPES.includes(x) ? x : "concept");

function monoHue(domain) {
  let x = 0;
  for (const ch of String(domain)) x = (x * 31 + ch.charCodeAt(0)) >>> 0;
  return x % 8;
}

/** A citation chip [n] that jumps to source n of the answer. */
function cite(turn, n) {
  const k = Number(n);
  if (!k) return null;
  return h(
    "a",
    {
      class: "mod-cite num",
      href: `#src-${turn.id}-${k}`,
      "aria-label": `${t("sources.title")} ${k}`,
      onclick: (e) => {
        const target = document.getElementById(`src-${turn.id}-${k}`);
        if (target) {
          e.preventDefault();
          target.scrollIntoView({ block: "nearest", behavior: "smooth" });
          target.focus({ preventScroll: true });
        }
      },
    },
    `[${k}]`,
  );
}

function card(cls, title, iconName, ...body) {
  return h(
    "section",
    { class: `widget mod ${cls}`, "aria-label": title },
    h(
      "h3",
      { class: "widget-title mod-title" },
      iconName && icon(iconName),
      h("span", { text: title }),
    ),
    ...body,
  );
}

// ------------------------------------------------------------------ research card

function renderResearch(w, turn) {
  const c = w.counts || {};
  const plan = (w.questions || []).length
    ? h(
        "div",
        { class: "mod-block" },
        h("h4", { class: "eyebrow mod-eyebrow", text: t("mod.research.plan") }),
        h(
          "ol",
          { class: "rs-plan" },
          (w.questions || []).map((q, i) =>
            h(
              "li",
              { class: w.resolved?.[i] ? "rs-plan-done" : null },
              String(q),
              w.resolved?.[i] &&
                h("span", { class: "rs-plan-mark", title: t("mod.research.resolved") }, icon("check")),
            ),
          ),
        ),
      )
    : null;
  const sources = h(
    "ol",
    { class: "rs-sources" },
    (w.sources || []).map((s) => {
      const url = safeUrl(s.url);
      const domain = String(s.domain || "");
      return h(
        "li",
        { class: "rs-source" },
        h(
          "div",
          { class: "rs-head" },
          h("span", { class: "source-n num", text: String(s.n || "") }),
          h(
            "span",
            { class: "rs-domain" },
            h("span", {
              class: `source-mono mono-${monoHue(domain || s.title)}`,
              "aria-hidden": "true",
              text: (domain || s.title || "?")[0].toUpperCase(),
            }),
            h("span", { text: domain || t("mod.research.own") }),
          ),
          h("span", {
            class: "rs-count muted",
            text: s.claims
              ? t("mod.research.claims", { n: s.claims })
              : t("mod.research.none"),
          }),
        ),
        url
          ? h("a", {
              class: "rs-link",
              href: url,
              target: "_blank",
              rel: "noopener noreferrer",
              referrerpolicy: "no-referrer",
              text: String(s.title || url),
            })
          : h("span", { class: "rs-link", text: String(s.title || "") }),
        s.quote &&
          h("blockquote", { class: "rs-quote", text: `« ${s.quote} »` }),
      );
    }),
  );
  return card(
    "mod-research",
    t("mod.research.title"),
    "web_search",
    w.topic && h("p", { class: "rs-topic", text: String(w.topic) }),
    plan,
    h(
      "div",
      { class: "mod-block" },
      h("h4", { class: "eyebrow mod-eyebrow", text: t("mod.research.sources") }),
      sources,
    ),
    h(
      "p",
      { class: "widget-source" },
      t("mod.research.counts", {
        queries: c.queries ?? 0,
        kept: c.kept ?? 0,
        read: c.read ?? 0,
        claims: c.claims ?? 0,
      }),
      c.crossed ? ` · ${t("mod.research.crossed", { n: c.crossed })}` : "",
      " · ",
      t("mod.research.note"),
    ),
  );
}

// ------------------------------------------------------------------ relation graph (in-house force layout)

/** Deterministic force layout (Fruchterman-Reingold, fixed start on a circle, cooling): {id: [x, y]} in a w×h box. */
export function layoutGraph(
  nodes,
  edges,
  { width = 640, height = 400, iterations = 300, seed = null } = {},
) {
  const n = nodes.length;
  const pos = new Map();
  const deg = new Map(nodes.map((d) => [d.id, 0]));
  for (const e of edges) {
    deg.set(e.s, (deg.get(e.s) || 0) + 1);
    deg.set(e.t, (deg.get(e.t) || 0) + 1);
  }
  const order = [...nodes].sort(
    (a, b) =>
      (deg.get(b.id) || 0) - (deg.get(a.id) || 0) ||
      String(a.id).localeCompare(String(b.id)),
  );
  order.forEach((d, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, n);
    const r = i === 0 && n > 3 ? 0 : Math.min(width, height) * 0.35;
    // a graph that grows (live research): the nodes already drawn start where they were
    const was = seed?.get?.(d.id);
    pos.set(d.id, was ? [...was] : [width / 2 + r * Math.cos(a), height / 2 + r * Math.sin(a)]);
  });
  if (n < 2) return Object.fromEntries(pos);
  const k = Math.sqrt((width * height) / n) * 0.75;
  let temp = seed?.size ? width / 16 : width / 8;
  const ids = order.map((d) => d.id);
  for (let it = 0; it < iterations; it++) {
    const disp = new Map(ids.map((id) => [id, [0, 0]]));
    for (let i = 0; i < n; i++)
      for (let j = i + 1; j < n; j++) {
        const [ax, ay] = pos.get(ids[i]);
        const [bx, by] = pos.get(ids[j]);
        let dx = ax - bx;
        let dy = ay - by;
        let d = Math.hypot(dx, dy);
        if (d < 0.01) {
          dx = 0.01 * (i + 1);
          dy = 0.01 * (j + 1);
          d = Math.hypot(dx, dy);
        }
        const f = (k * k) / d;
        const a = disp.get(ids[i]);
        const b = disp.get(ids[j]);
        a[0] += (dx / d) * f;
        a[1] += (dy / d) * f;
        b[0] -= (dx / d) * f;
        b[1] -= (dy / d) * f;
      }
    for (const e of edges) {
      if (!pos.has(e.s) || !pos.has(e.t) || e.s === e.t) continue;
      const [ax, ay] = pos.get(e.s);
      const [bx, by] = pos.get(e.t);
      const dx = ax - bx;
      const dy = ay - by;
      const d = Math.max(0.01, Math.hypot(dx, dy));
      const f = (d * d) / k;
      const a = disp.get(e.s);
      const b = disp.get(e.t);
      a[0] -= (dx / d) * f;
      a[1] -= (dy / d) * f;
      b[0] += (dx / d) * f;
      b[1] += (dy / d) * f;
    }
    for (const id of ids) {
      const [dx, dy] = disp.get(id);
      // a light pull to the centre keeps unlinked nodes in view; it cools with the forces (else, once they are
      // cold, it alone pulls every node onto the centre)
      const p = pos.get(id);
      const pull = 0.02 * Math.min(1, temp / 10);
      const cx = (width / 2 - p[0]) * pull;
      const cy = (height / 2 - p[1]) * pull;
      const d = Math.max(0.01, Math.hypot(dx, dy));
      const step = Math.min(d, temp);
      p[0] = Math.min(width - 40, Math.max(40, p[0] + (dx / d) * step + cx));
      p[1] = Math.min(height - 24, Math.max(24, p[1] + (dy / d) * step + cy));
    }
    temp = Math.max(0.5, temp * 0.97);
  }
  return Object.fromEntries(
    ids.map((id) => [id, pos.get(id).map((v) => Math.round(v * 10) / 10)]),
  );
}

function renderGraph(w, turn) {
  const nodes = (w.nodes || []).filter((d) => d && d.id);
  const ids = new Set(nodes.map((d) => d.id));
  const edges = (w.edges || []).filter((e) => ids.has(e.s) && ids.has(e.t));
  if (nodes.length < 2 || !edges.length) return null;
  const W = 640;
  const H = nodes.length > 10 ? 440 : 360;
  const pos = layoutGraph(nodes, edges, { width: W, height: H });
  const claims = new Map((w.claims || []).map((c) => [c.i, c]));
  const byId = new Map(nodes.map((d) => [d.id, d]));
  const degree = new Map(nodes.map((d) => [d.id, 0]));
  for (const e of edges) {
    degree.set(e.s, degree.get(e.s) + 1);
    degree.set(e.t, degree.get(e.t) + 1);
  }
  const hidden = new Set();
  let selected = null;
  let view = { x: 0, y: 0, k: 1 };

  const world = svg("g", { class: "gr-world" });
  const edgeEls = edges.map((e) => {
    const [x1, y1] = pos[e.s];
    const [x2, y2] = pos[e.t];
    const line = svg("line", {
      class: "gr-edge",
      x1,
      y1,
      x2,
      y2,
      "marker-end": "url(#gr-arrow)",
    });
    const label = svg(
      "text",
      {
        class: "gr-elabel",
        x: (x1 + x2) / 2,
        y: (y1 + y2) / 2 - 4,
        "text-anchor": "middle",
      },
      e.label,
    );
    world.append(line);
    return { e, line, label };
  });
  for (const x of edgeEls) world.append(x.label);
  const nodeEls = nodes.map((d) => {
    const [x, y] = pos[d.id];
    const r = 7 + Math.min(9, degree.get(d.id) * 2);
    const typeLabel = t(`mod.type.${typeOf(d.type)}`);
    const g = svg(
      "g",
      {
        class: `gr-node gr-t-${typeOf(d.type)}`,
        transform: `translate(${x} ${y})`,
        tabindex: "0",
        role: "button",
        "aria-pressed": "false",
        "aria-label": t("mod.graph.node", {
          label: d.label,
          type: typeLabel,
          n: degree.get(d.id),
        }),
      },
      svg("circle", { r }),
      svg(
        "text",
        { class: "gr-label", y: r + 13, "text-anchor": "middle" },
        String(d.label).slice(0, 28),
      ),
    );
    g.addEventListener("click", (ev) => {
      ev.stopPropagation();
      select(selected === d.id ? null : d.id);
    });
    g.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        select(selected === d.id ? null : d.id);
      } else if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(ev.key)) {
        // arrows go from node to node (by degree order), skipping the hidden types
        ev.preventDefault();
        const shown = nodeEls.filter((x) => !x.g.classList.contains("is-hidden"));
        const i = shown.findIndex((x) => x.g === g);
        const step = ev.key === "ArrowRight" || ev.key === "ArrowDown" ? 1 : -1;
        shown[(i + step + shown.length) % shown.length]?.g.focus();
      }
    });
    world.append(g);
    return { d, g };
  });

  const defs = svg(
    "defs",
    {},
    svg(
      "marker",
      {
        id: "gr-arrow",
        viewBox: "0 0 10 10",
        refX: "18",
        refY: "5",
        markerWidth: "7",
        markerHeight: "7",
        orient: "auto-start-reverse",
      },
      svg("path", { d: "M0 0L10 5L0 10z", class: "gr-arrowhead" }),
    ),
  );
  const canvas = svg(
    "svg",
    {
      class: "gr-svg",
      viewBox: `0 0 ${W} ${H}`,
      role: "group",
      "aria-label": w.title || t("mod.graph.title"),
    },
    defs,
    world,
  );

  const apply = () =>
    world.setAttribute(
      "transform",
      `translate(${view.x} ${view.y}) scale(${view.k})`,
    );
  const zoom = (f) => {
    const k = Math.min(3, Math.max(0.5, view.k * f));
    view.x = W / 2 - ((W / 2 - view.x) * k) / view.k;
    view.y = H / 2 - ((H / 2 - view.y) * k) / view.k;
    view.k = k;
    apply();
  };
  // pan: drag the background (pointer events, so touch and pen work too)
  let drag = null;
  canvas.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest(".gr-node")) return;
    drag = {
      x: ev.clientX,
      y: ev.clientY,
      vx: view.x,
      vy: view.y,
      moved: false,
    };
    canvas.setPointerCapture?.(ev.pointerId);
  });
  canvas.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const box = canvas.getBoundingClientRect();
    const s = W / Math.max(1, box.width);
    view.x = drag.vx + (ev.clientX - drag.x) * s;
    view.y = drag.vy + (ev.clientY - drag.y) * s;
    drag.moved =
      drag.moved ||
      Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) > 4;
    apply();
  });
  const end = () => {
    if (drag && !drag.moved) select(null);
    drag = null;
  };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", () => (drag = null));
  canvas.addEventListener(
    "wheel",
    (ev) => {
      if (!ev.ctrlKey && !ev.metaKey) return; // a plain wheel scrolls the conversation
      ev.preventDefault();
      zoom(ev.deltaY < 0 ? 1.15 : 1 / 1.15);
    },
    { passive: false },
  );

  const panel = h(
    "div",
    { class: "gr-panel", "aria-live": "polite" },
    h("p", { class: "muted", text: t("mod.graph.pick") }),
  );

  function select(id) {
    selected = id;
    const near = new Set(id ? [id] : []);
    for (const { e, line, label } of edgeEls) {
      const on = id && (e.s === id || e.t === id);
      if (on) {
        near.add(e.s);
        near.add(e.t);
      }
      line.classList.toggle("is-on", !!on);
      label.classList.toggle("is-on", !!on);
    }
    for (const { d, g } of nodeEls) {
      g.classList.toggle("is-dim", !!id && !near.has(d.id));
      g.classList.toggle("is-on", d.id === id);
      g.setAttribute("aria-pressed", String(d.id === id));
    }
    canvas.classList.toggle("has-pick", !!id);
    if (!id) {
      panel.replaceChildren(
        h("p", { class: "muted", text: t("mod.graph.pick") }),
      );
      return;
    }
    const d = byId.get(id);
    const links = edges.filter((e) => e.s === id || e.t === id);
    const said = [
      ...new Set([
        ...(d.claims || []),
        ...links.flatMap((e) => e.claims || []),
      ]),
    ]
      .map((i) => claims.get(i))
      .filter(Boolean);
    panel.replaceChildren(
      h(
        "h4",
        { class: "gr-pick" },
        h("span", {
          class: `gr-dot gr-t-${typeOf(d.type)}`,
          "aria-hidden": "true",
        }),
        h("span", { text: d.label }),
        h("span", { class: "pill", text: t(`mod.type.${typeOf(d.type)}`) }),
      ),
      links.length
        ? h(
            "div",
            { class: "mod-block" },
            h("h5", { class: "eyebrow mod-eyebrow", text: t("mod.graph.links") }),
            h(
              "ul",
              { class: "gr-links" },
              links.map((e) =>
                h(
                  "li",
                  null,
                  byId.get(e.s).label,
                  h("span", { class: "gr-rel", text: ` ${e.label} ` }),
                  byId.get(e.t).label,
                  " ",
                  ...(e.sources || []).map((n) => cite(turn, n)),
                ),
              ),
            ),
          )
        : null,
      said.length
        ? h(
            "div",
            { class: "mod-block" },
            h("h5", { class: "eyebrow mod-eyebrow", text: t("mod.graph.claims") }),
            h(
              "ul",
              { class: "gr-claims" },
              said.map((c) => h("li", null, c.text, " ", cite(turn, c.n))),
            ),
          )
        : null,
    );
  }

  const presentTypes = TYPES.filter((ty) =>
    nodes.some((d) => typeOf(d.type) === ty),
  );
  const filters =
    presentTypes.length > 1
      ? h(
          "div",
          {
            class: "gr-filters",
            role: "group",
            "aria-label": t("mod.graph.filter"),
          },
          presentTypes.map((ty) => {
            const b = h(
              "button",
              {
                class: `mchip gr-filter gr-t-${ty}`,
                type: "button",
                "aria-pressed": "true",
              },
              h("span", { class: `gr-dot gr-t-${ty}`, "aria-hidden": "true" }),
              t(`mod.type.${ty}`),
            );
            b.addEventListener("click", () => {
              if (hidden.has(ty)) hidden.delete(ty);
              else hidden.add(ty);
              b.setAttribute("aria-pressed", String(!hidden.has(ty)));
              for (const { d, g } of nodeEls)
                g.classList.toggle("is-hidden", hidden.has(typeOf(d.type)));
              for (const { e, line, label } of edgeEls) {
                const off =
                  hidden.has(typeOf(byId.get(e.s).type)) ||
                  hidden.has(typeOf(byId.get(e.t).type));
                line.classList.toggle("is-hidden", off);
                label.classList.toggle("is-hidden", off);
              }
            });
            return b;
          }),
        )
      : null;

  const tools = h(
    "div",
    { class: "gr-tools" },
    button(
      "btn-quiet btn-icon btn-small",
      "plus",
      t("mod.graph.zoomIn"),
      () => zoom(1.25),
      { "data-act": "gr-zoom-in" },
    ),
    button(
      "btn-quiet btn-icon btn-small",
      "minus",
      t("mod.graph.zoomOut"),
      () => zoom(0.8),
      { "data-act": "gr-zoom-out" },
    ),
    button(
      "btn-quiet btn-small",
      "retry",
      t("mod.graph.reset"),
      () => {
        view = { x: 0, y: 0, k: 1 };
        apply();
        select(null);
      },
      { "data-act": "gr-reset" },
    ),
  );

  const list = h(
    "details",
    { class: "gr-list" },
    h("summary", { text: t("mod.graph.list") }),
    h(
      "ul",
      null,
      edges.map((e) =>
        h(
          "li",
          null,
          h("strong", { text: byId.get(e.s).label }),
          ` ${e.label} `,
          h("strong", { text: byId.get(e.t).label }),
          " ",
          ...(e.sources || []).map((n) => cite(turn, n)),
        ),
      ),
    ),
  );

  return card(
    "mod-graph",
    w.title || t("mod.graph.title"),
    "spark",
    h("p", { class: "widget-note muted", text: t("mod.graph.hint") }),
    filters,
    h("div", { class: "gr-stage" }, canvas, tools),
    panel,
    list,
    h("p", { class: "widget-source", text: t("mod.graph.note") }),
  );
}

/** The relation graph while the research runs: compact, no controls, the nodes already drawn keep their place and
 * the new ones fade in; a list of the relations under it (keyboard and screen readers). */
export function liveGraph(w, turn) {
  const nodes = (w.nodes || []).filter((d) => d && d.id);
  const ids = new Set(nodes.map((d) => d.id));
  const edges = (w.edges || []).filter((e) => ids.has(e.s) && ids.has(e.t));
  if (nodes.length < 2) return null;
  turn.ui ||= {};
  const memo = (turn.ui.grLive ||= {}); // label -> [x, y], across redraws of the board
  const W = 560;
  const H = 300;
  const key = (d) => String(d.label).toLowerCase();
  const seed = new Map(nodes.filter((d) => memo[key(d)]).map((d) => [d.id, memo[key(d)]]));
  const pos = layoutGraph(nodes, edges, { width: W, height: H, iterations: seed.size ? 140 : 240, seed });
  const world = svg("g", {});
  for (const e of edges) {
    const [x1, y1] = pos[e.s];
    const [x2, y2] = pos[e.t];
    world.append(svg("line", { class: "gr-edge", x1, y1, x2, y2 }));
  }
  const byId = new Map(nodes.map((d) => [d.id, d]));
  for (const d of nodes) {
    const [x, y] = pos[d.id];
    const fresh = !memo[key(d)];
    world.append(
      svg(
        "g",
        { class: `gr-node gr-t-${typeOf(d.type)}${fresh ? " is-new" : ""}`, transform: `translate(${x} ${y})` },
        svg("circle", { r: 7 }),
        svg("text", { class: "gr-label", y: 20, "text-anchor": "middle" }, String(d.label).slice(0, 24)),
      ),
    );
    memo[key(d)] = [x, y];
  }
  return h(
    "div",
    { class: "gr-live" },
    svg("svg", { class: "gr-svg is-live", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": t("mod.graph.title") }, world),
    h(
      "details",
      { class: "gr-list" },
      h("summary", { text: t("mod.graph.list") }),
      h(
        "ul",
        null,
        edges.map((e) =>
          h("li", null, h("strong", { text: byId.get(e.s).label }), ` ${e.label} `, h("strong", { text: byId.get(e.t).label })),
        ),
      ),
    ),
  );
}

// ------------------------------------------------------------------ timeline

function renderTimeline(w, turn) {
  const ev = (w.events || []).filter((e) => e && e.label);
  if (ev.length < 2) return null;
  return card(
    "mod-timeline",
    w.title || t("mod.timeline.title"),
    "make_chart",
    h(
      "ol",
      { class: "tl-list" },
      ev.map((e) =>
        h(
          "li",
          { class: "tl-item" },
          h("span", { class: "tl-date num", text: String(e.date || e.key) }),
          h("span", { class: "tl-dot", "aria-hidden": "true" }),
          h(
            "span",
            { class: "tl-label" },
            String(e.label),
            e.n ? " " : "",
            e.n ? cite(turn, e.n) : null,
          ),
        ),
      ),
    ),
    h("p", {
      class: "widget-source",
      text:
        w.origin === "user"
          ? t("mod.timeline.user")
          : t("mod.timeline.sources"),
    }),
  );
}

// ------------------------------------------------------------------ comparison matrix

export function parseCell(text) {
  const m = String(text ?? "")
    .replace(/[\s  ](?=\d{3}\b)/g, "")
    .match(/-?\d+(?:[.,]\d+)?/);
  return m ? Number(m[0].replace(",", ".")) : null;
}

/** Row order for a sort on column j: numbers when every row has one, else text (locale order). */
export function sortRows(rows, j, dir = "asc") {
  const nums = rows.map((r) => parseCell(r[j]));
  const numeric = nums.every((v) => v !== null);
  const idx = rows.map((_, i) => i);
  idx.sort((a, b) => {
    const c = numeric
      ? nums[a] - nums[b]
      : String(rows[a][j]).localeCompare(String(rows[b][j]), undefined, {
          numeric: true,
        });
    return dir === "asc" ? c || a - b : -c || a - b;
  });
  return idx;
}

function renderMatrix(w) {
  const cols = w.columns || [];
  const rows = w.rows || [];
  if (cols.length < 2 || rows.length < 2) return null;
  const best = w.best || {};
  let order = rows.map((_, i) => i);
  let sortBy = null;
  let dir = "asc";
  const body = h("tbody");
  const heads = cols.map((c, j) => {
    const b = h(
      "button",
      {
        class: "mx-sort",
        type: "button",
        "aria-label": t("mod.matrix.sort", { col: c }),
      },
      h("span", { text: c }),
      h("span", { class: "mx-arrow", "aria-hidden": "true" }),
    );
    const th = h("th", { scope: "col" }, b);
    b.addEventListener("click", () => {
      dir = sortBy === j && dir === "asc" ? "desc" : "asc";
      sortBy = j;
      order = sortRows(rows, j, dir);
      for (const [k, x] of heads.entries())
        x.th.setAttribute(
          "aria-sort",
          k === j ? (dir === "asc" ? "ascending" : "descending") : "none",
        );
      paint();
    });
    th.setAttribute("aria-sort", "none");
    return { th, b };
  });
  function paint() {
    body.replaceChildren(
      ...order.map((i) => {
        const r = rows[i];
        const verdict = w.verdict === i;
        return h(
          "tr",
          { class: verdict ? "is-verdict" : "" },
          r.map((cell, j) => {
            const isBest = (best[String(j)] || []).includes(i);
            const tag = j === 0 ? "th" : "td";
            return h(
              tag,
              {
                class: isBest ? "is-best" : "",
                ...(j === 0 ? { scope: "row" } : {}),
              },
              h("span", { text: cell || "—" }),
              isBest &&
                h("span", {
                  class: "sr-only",
                  text: ` (${t("mod.matrix.best")})`,
                }),
              j === 0 &&
                verdict &&
                h("span", {
                  class: "pill mx-verdict",
                  text: t("mod.matrix.verdict"),
                }),
            );
          }),
        );
      }),
    );
  }
  paint();
  const md = () =>
    [
      `| ${cols.join(" | ")} |`,
      `|${cols.map(() => "---").join("|")}|`,
      ...rows.map((r) => `| ${r.join(" | ")} |`),
    ].join("\n");
  const csv = () =>
    [cols, ...rows]
      .map((r) =>
        r.map((c) => `"${String(c).replaceAll('"', '""')}"`).join(";"),
      )
      .join("\r\n");
  return card(
    "mod-matrix",
    w.title || t("mod.matrix.title"),
    "make_sheet",
    h(
      "div",
      { class: "table-wrap mx-wrap", tabindex: "0" },
      h(
        "table",
        { class: "md-table mx-table" },
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            heads.map((x) => x.th),
          ),
        ),
        body,
      ),
    ),
    h(
      "div",
      { class: "mod-actions" },
      button(
        "btn-quiet btn-small",
        "copy",
        t("mod.matrix.copy"),
        () => copyText(md(), t("mod.copied")),
        { "data-act": "mx-copy" },
      ),
      button(
        "btn-quiet btn-small",
        "download",
        t("mod.matrix.csv"),
        () =>
          download(
            `${(w.title || "comparaison").replace(/[^\p{L}\d]+/gu, "-")}.csv`,
            "text/csv;charset=utf-8",
            `﻿${csv()}`,
          ),
        { "data-act": "mx-csv" },
      ),
    ),
    h("p", {
      class: "widget-source",
      text:
        (w.notes || []).join(" ") ||
        (w.origin === "user" ? t("mod.matrix.user") : ""),
    }),
  );
}

// ------------------------------------------------------------------ calculator (same formulas as birds/harness/calc.py)

const UNIT = {
  len: {
    km: 1000,
    m: 1,
    cm: 0.01,
    mm: 0.001,
    mi: 1609.344,
    ft: 0.3048,
    in: 0.0254,
    yd: 0.9144,
    NM: 1852,
  },
};

/** The results of a calculator card for the given inputs (numbers): {name: value}. */
export function calcCompute(w, v) {
  const k = w.kind;
  if (k === "unit") {
    if (w.dim === "temp") {
      const c =
        w.from === "°C"
          ? v.value
          : w.from === "°F"
            ? ((v.value - 32) * 5) / 9
            : v.value - 273.15;
      return {
        result:
          w.to === "°C" ? c : w.to === "°F" ? (c * 9) / 5 + 32 : c + 273.15,
      };
    }
    return { result: v.value * Number(w.factor) };
  }
  if (k === "loan") {
    const n = Math.round(v.years * 12);
    const r = v.rate / 100 / 12;
    const pay =
      r === 0 ? v.principal / n : (v.principal * r) / (1 - (1 + r) ** -n);
    return { payment: pay, interest: pay * n - v.principal, total: pay * n };
  }
  if (k === "margin")
    return {
      margin: v.price - v.cost,
      markup: ((v.price - v.cost) / v.cost) * 100,
      rate: ((v.price - v.cost) / v.price) * 100,
      coef: v.price / v.cost,
    };
  if (k === "vat") {
    const r = v.rate / 100;
    const ht = w.base === "ht" ? v.amount : v.amount / (1 + r);
    return { ht, vat: ht * r, ttc: ht * (1 + r) };
  }
  if (k === "change") {
    const delta = (v.base * v.pct) / 100;
    return { delta, result: w.down ? v.base - delta : v.base + delta };
  }
  if (k === "variation")
    return { pct: ((v.b - v.a) / Math.abs(v.a)) * 100, delta: v.b - v.a };
  if (k === "percent_of") return { result: (v.base * v.pct) / 100 };
  if (k === "ratio") return { pct: (v.a / v.b) * 100 };
  return {};
}
// result order of each kind, as the server's rows
const ROWS = {
  unit: ["result"],
  loan: ["payment", "interest", "total"],
  margin: ["margin", "markup", "rate", "coef"],
  vat: ["ht", "vat", "ttc"],
  change: ["delta", "result"],
  variation: ["pct", "delta"],
  percent_of: ["result"],
  ratio: ["pct"],
};
void UNIT;

function renderCalc(w) {
  const inputs = w.inputs || [];
  const rows = w.rows || [];
  const names = ROWS[w.kind] || [];
  if (!rows.length) return null;
  const nf = (places, unit) =>
    new Intl.NumberFormat(locale(), {
      maximumFractionDigits: unit === "€" ? 2 : places,
      minimumFractionDigits: unit === "€" ? 2 : 0,
    });
  const unitOf = (row) =>
    (String(row.value).match(/(?:\s| )([^\d\s ,.-][^\s]*)$/) || [])[1] || "";
  const outs = rows.map((r) =>
    h("output", {
      class: `calc-v num${r.main ? " is-main" : ""}`,
      text: r.value,
    }),
  );
  const fields = inputs.map((inp) =>
    h("input", {
      class: "calc-in num",
      type: "number",
      step: "any",
      inputmode: "decimal",
      value: inp.value,
      "aria-label": inp.label,
      "data-key": inp.key,
    }),
  );
  const live = h("span", { class: "sr-only", "aria-live": "polite" });
  const recompute = () => {
    const v = {};
    for (const [i, f] of fields.entries())
      v[inputs[i].key] = Number(String(f.value).replace(",", "."));
    if (
      Object.values(v).some((x) => !Number.isFinite(x)) ||
      (w.kind === "loan" && !(v.years > 0))
    ) {
      for (const o of outs) o.textContent = "—";
      return;
    }
    const res = calcCompute(w, v);
    names.forEach((name, i) => {
      const unit = unitOf(rows[i]);
      const x = res[name];
      outs[i].textContent = Number.isFinite(x)
        ? `${nf(name === "coef" ? 4 : w.kind === "unit" ? 4 : 2, unit).format(x)}${unit ? (unit === "%" || unit === "€" ? " " : " ") + unit : ""}`
        : "—";
    });
    live.textContent = rows
      .map((r, i) => `${r.label} ${outs[i].textContent}`)
      .join(", ");
  };
  for (const f of fields) f.addEventListener("input", recompute);
  return card(
    "mod-calc",
    w.title || t("mod.calc.title"),
    "tool",
    inputs.length
      ? h(
          "div",
          { class: "calc-inputs" },
          inputs.map((inp, i) =>
            h(
              "label",
              { class: "calc-field" },
              h("span", { class: "calc-label", text: inp.label }),
              h(
                "span",
                { class: "calc-box" },
                fields[i],
                inp.unit && h("span", { class: "calc-unit", text: inp.unit }),
              ),
            ),
          ),
        )
      : null,
    h(
      "dl",
      { class: "calc-rows" },
      rows.map((r, i) =>
        h(
          "div",
          { class: `calc-row${r.main ? " is-main" : ""}` },
          h("dt", { text: r.label }),
          h("dd", null, outs[i]),
        ),
      ),
    ),
    live,
    w.formula &&
      h(
        "p",
        { class: "calc-formula muted" },
        h("span", { text: `${t("mod.calc.formula")} : ` }),
        h("code", { text: w.formula }),
      ),
    h(
      "div",
      { class: "mod-actions" },
      button(
        "btn-quiet btn-small",
        "copy",
        t("mod.calc.copy"),
        () =>
          copyText(
            rows.map((r, i) => `${r.label} ${outs[i].textContent}`).join("\n"),
            t("mod.copied"),
          ),
        { "data-act": "calc-copy" },
      ),
    ),
    h("p", {
      class: "widget-source",
      text: [w.note, t("mod.calc.note")].filter(Boolean).join(" "),
    }),
  );
}

// ------------------------------------------------------------------ checklist (ticks saved with the conversation)

export function checklistMarkdown(w, done) {
  return (w.items || [])
    .map(
      (it, i) =>
        `- [${done[i] ? "x" : " "}] ${it.text}${it.owner ? ` — ${it.owner}` : ""}${it.due ? ` (${it.due})` : ""}`,
    )
    .join("\n");
}

function renderChecklist(w, turn) {
  const items = w.items || [];
  if (items.length < 2) return null;
  turn.ui ||= {};
  turn.ui.checks ||= {};
  const key = `${w.type}:${w.title}`;
  const done = (turn.ui.checks[key] ||= items.map((it) => !!it.done));
  const progress = h("p", {
    class: "ck-progress muted",
    "aria-live": "polite",
  });
  const bar = h("span", { class: "ck-bar-fill" });
  const paint = () => {
    const n = done.filter(Boolean).length;
    progress.textContent = t("mod.check.progress", {
      done: n,
      n: items.length,
    });
    bar.style.setProperty("--p", `${Math.round((n / items.length) * 100)}%`);
  };
  const list = h(
    "ul",
    { class: "chk-list" },
    items.map((it, i) => {
      const box = h("input", {
        type: "checkbox",
        class: "chk-box",
        checked: done[i] || null,
      });
      box.addEventListener("change", () => {
        done[i] = box.checked;
        li.classList.toggle("is-done", box.checked);
        paint();
        hooks.onChange(turn);
      });
      const li = h(
        "li",
        { class: `chk-item${done[i] ? " is-done" : ""}` },
        h(
          "label",
          { class: "chk-label" },
          box,
          h("span", { class: "chk-text", text: it.text }),
        ),
        (it.owner || it.due) &&
          h("span", {
            class: "chk-meta muted",
            text: [it.owner, it.due && t("mod.check.due", { due: it.due })]
              .filter(Boolean)
              .join(" · "),
          }),
      );
      return li;
    }),
  );
  paint();
  return card(
    "mod-check",
    w.title || t("mod.check.title"),
    "check",
    h(
      "div",
      { class: "ck-head" },
      progress,
      h("span", { class: "ck-bar", "aria-hidden": "true" }, bar),
    ),
    list,
    h(
      "div",
      { class: "mod-actions" },
      button(
        "btn-quiet btn-small",
        "copy",
        t("mod.check.copy"),
        () => copyText(checklistMarkdown(w, done), t("mod.copied")),
        { "data-act": "chk-copy" },
      ),
      button(
        "btn-quiet btn-small",
        "download",
        t("mod.check.export"),
        () =>
          download(
            "taches.md",
            "text/markdown;charset=utf-8",
            `# ${w.title}\n\n${checklistMarkdown(w, done)}\n`,
          ),
        { "data-act": "chk-export" },
      ),
    ),
    h("p", {
      class: "widget-source",
      text:
        w.origin === "minutes" ? t("mod.check.minutes") : t("mod.check.user"),
    }),
  );
}

// ------------------------------------------------------------------ registry

// ------------------------------------------------------------------ pros and cons, key figures, glossary, sources

function renderProsCons(w) {
  const col = (cls, label, items, mark) =>
    h(
      "div",
      { class: `pc-col ${cls}` },
      h("h4", { class: "pc-h" }, h("span", { class: "pc-mark", "aria-hidden": "true", text: mark }), label),
      h("ul", { class: "pc-list" }, (items || []).map((x) => h("li", { text: String(x) }))),
    );
  if (!(w.pros || []).length || !(w.cons || []).length) return null;
  return card(
    "mod-proscons",
    w.title || t("mod.pc.pros"),
    "swap",
    h("div", { class: "pc-grid" }, col("is-pro", t("mod.pc.pros"), w.pros, "+"), col("is-con", t("mod.pc.cons"), w.cons, "−")),
    h("p", { class: "widget-source", text: t("mod.pc.user") }),
  );
}

function renderFigures(w) {
  const items = (w.items || []).filter((x) => x?.label && x?.value);
  if (items.length < 2) return null;
  return card(
    "mod-figures",
    w.title || "",
    "make_chart",
    h(
      "ul",
      { class: "fg-grid" },
      items.map((x) =>
        h("li", { class: "fg-tile" }, h("span", { class: "fg-v num", text: String(x.value) }), h("span", { class: "fg-l", text: String(x.label) })),
      ),
    ),
    h("p", { class: "widget-source", text: t("mod.fig.user") }),
  );
}

function renderGlossary(w) {
  const items = (w.items || []).filter((x) => x?.term && x?.def);
  if (items.length < 2) return null;
  const rows = items.map((x) =>
    h("div", { class: "gl-row", "data-term": String(x.term).toLowerCase() }, h("dt", { text: String(x.term) }), h("dd", { text: String(x.def) })),
  );
  const none = h("p", { class: "muted gl-none", hidden: true, text: t("mod.gl.none") });
  const filter =
    items.length > 6 &&
    h("input", {
      class: "gl-filter",
      type: "search",
      placeholder: t("mod.gl.filter"),
      "aria-label": t("mod.gl.filter"),
      oninput: (e) => {
        const q = e.target.value.trim().toLowerCase();
        let shown = 0;
        for (const r of rows) {
          const on = !q || r.dataset.term.includes(q) || r.textContent.toLowerCase().includes(q);
          r.hidden = !on;
          shown += on ? 1 : 0;
        }
        none.hidden = shown > 0;
      },
    });
  return card("mod-glossary", w.title || t("mod.gloss"), "read_file", filter, h("dl", { class: "gl-list" }, rows), none, h("p", { class: "widget-source", text: t("mod.gl.user") }));
}

function renderSourceCards(w, turn) {
  const sources = (turn?.answer?.sources || []).filter((s) => s?.url);
  if (!sources.length) return null;
  return card(
    "mod-sourcecards",
    w.title || t("sources.title"),
    "read_page",
    h(
      "ol",
      { class: "sc-grid" },
      sources.slice(0, 12).map((s) => {
        const url = safeUrl(s.url);
        const domain = String(s.domain || "");
        const n = Number(s.n) || 0;
        return h(
          "li",
          { class: "sc-card", id: `src-${turn.id}-${n}`, tabindex: "-1" },
          h(
            "div",
            { class: "sc-head" },
            h("span", { class: "source-n num", text: String(n || "") }),
            h("span", { class: `source-mono mono-${monoHue(domain || s.title)}`, "aria-hidden": "true", text: (domain || "?")[0].toUpperCase() }),
            h("span", { class: "sc-d", text: domain }),
            s.kind === "gov" && h("span", { class: "badge badge-gov", text: t("mod.sc.public") }),
          ),
          url
            ? h("a", { class: "sc-t", href: url, target: "_blank", rel: "noopener noreferrer", referrerpolicy: "no-referrer", text: String(s.title || url) })
            : h("span", { class: "sc-t", text: String(s.title || "") }),
          s.snippet && h("p", { class: "sc-snip", text: String(s.snippet) }),
          h(
            "div",
            { class: "sc-foot" },
            s.date && h("span", { class: "muted num", text: String(s.date) }),
            button("btn-quiet btn-small", "copy", t("mod.sc.cite"), () => copyText(`${s.title || domain} — ${s.url}`, t("mod.copied")), { "data-act": "sc-cite" }),
          ),
        );
      }),
    ),
    h("p", { class: "widget-source", text: t("mod.sc.note") }),
  );
}

export const MODULES = {
  proscons: renderProsCons,
  figures: renderFigures,
  glossary: renderGlossary,
  sourcecards: renderSourceCards,
  research: renderResearch,
  graph: renderGraph,
  timeline: renderTimeline,
  matrix: renderMatrix,
  calc: renderCalc,
  checklist: renderChecklist,
};

/** The module as plain text (copy) or Markdown (export). */
export function moduleText(w, turn, markdown = false) {
  if (w.type === "proscons")
    return [`${t("mod.pc.pros")} :`, ...(w.pros || []).map((x) => `+ ${x}`), `${t("mod.pc.cons")} :`, ...(w.cons || []).map((x) => `- ${x}`)].join("\n");
  if (w.type === "figures") return (w.items || []).map((x) => `${x.label} : ${x.value}`).join("\n");
  if (w.type === "glossary") return (w.items || []).map((x) => `${x.term} : ${x.def}`).join("\n");
  if (w.type === "sourcecards")
    return (turn?.answer?.sources || []).map((s) => `[${s.n}] ${s.title || ""} — ${s.url}`).join("\n");
  if (w.type === "calc")
    return [
      w.title,
      ...(w.rows || []).map((r) => `${r.label} ${r.value}`),
    ].join("\n");
  if (w.type === "matrix")
    return markdown
      ? [
          `| ${w.columns.join(" | ")} |`,
          `|${w.columns.map(() => "---").join("|")}|`,
          ...w.rows.map((r) => `| ${r.join(" | ")} |`),
        ].join("\n")
      : w.rows.map((r) => r.join(" · ")).join("\n");
  if (w.type === "timeline")
    return (w.events || [])
      .map((e) => `${e.date} — ${e.label}${e.n ? ` [${e.n}]` : ""}`)
      .join("\n");
  if (w.type === "checklist")
    return checklistMarkdown(
      w,
      turn?.ui?.checks?.[`${w.type}:${w.title}`] || [],
    );
  if (w.type === "graph") {
    const byId = new Map((w.nodes || []).map((d) => [d.id, d.label]));
    return (w.edges || [])
      .map(
        (e) =>
          `${byId.get(e.s)} — ${e.label} → ${byId.get(e.t)}${e.sources?.length ? ` [${e.sources.join("][")}]` : ""}`,
      )
      .join("\n");
  }
  if (w.type === "research")
    return [w.topic, ...(w.questions || []).map((q, i) => `${i + 1}. ${q}`)]
      .filter(Boolean)
      .join("\n");
  return "";
}

// ------------------------------------------------------------------ answer enhancements (presentation only)

const TASK = /^\s*\[( |x|X)\]\s+/;

/** Task items (« - [ ] … ») become checkboxes, long tables get sortable headers, acronyms defined in the answer
 * (« Règlement général sur la protection des données (RGPD) ») get their definition on later uses. Idempotent:
 * already enhanced nodes are skipped. Pure presentation of the answer's own text: nothing is added to it. */
export function enhanceAnswer(md, turn) {
  if (!md || !turn?.answer) return;
  turn.ui ||= {};
  const ticks = (turn.ui.mdChecks ||= {});
  let changed = false;
  md.querySelectorAll("li:not([data-enh])").forEach((li, i) => {
    li.dataset.enh = "1";
    const first = li.firstChild;
    if (!first || first.nodeType !== 3 || !TASK.test(first.textContent)) return;
    const k = `${i}:${li.textContent.slice(0, 40)}`;
    const checked =
      k in ticks ? ticks[k] : /x/i.test(first.textContent.match(TASK)[1]);
    first.textContent = first.textContent.replace(TASK, "");
    const box = h("input", {
      type: "checkbox",
      class: "md-task-box",
      checked: checked || null,
      "aria-label": li.textContent.trim().slice(0, 80),
    });
    box.addEventListener("change", () => {
      ticks[k] = box.checked;
      li.classList.toggle("is-done", box.checked);
      hooks.onChange(turn);
    });
    li.classList.add("md-task");
    li.classList.toggle("is-done", !!checked);
    li.prepend(box);
    li.closest("ul,ol")?.classList.add("md-tasks");
    changed = true;
  });
  md.querySelectorAll("table:not([data-enh])").forEach((table) => {
    table.dataset.enh = "1";
    const body = table.tBodies[0];
    if (!body || body.rows.length < 3) return;
    const ths = [...(table.tHead?.rows[0]?.cells || [])];
    ths.forEach((th, j) => {
      const label = th.textContent.trim();
      const b = h("button", {
        class: "mx-sort",
        type: "button",
        "aria-label": t("mod.matrix.sort", { col: label }),
      });
      b.append(
        ...th.childNodes,
        h("span", { class: "mx-arrow", "aria-hidden": "true" }),
      );
      th.replaceChildren(b);
      th.setAttribute("aria-sort", "none");
      b.addEventListener("click", () => {
        const rows = [...body.rows];
        const cells = rows.map((r) =>
          [...r.cells].map((c) => c.textContent.trim()),
        );
        const dir =
          th.getAttribute("aria-sort") === "ascending" ? "desc" : "asc";
        const order = sortRows(cells, j, dir);
        for (const x of ths) x.setAttribute("aria-sort", "none");
        th.setAttribute(
          "aria-sort",
          dir === "asc" ? "ascending" : "descending",
        );
        body.append(...order.map((i) => rows[i]));
      });
    });
    table.classList.add("md-sortable");
  });
  if (!md.dataset.gloss) {
    md.dataset.gloss = "1";
    const text = md.textContent;
    const defs = new Map();
    for (const m of text.matchAll(
      /([A-ZÀ-Ý][\p{L}'’-]+(?:\s+(?:[\p{L}'’-]+)){1,8})\s+\(([A-Z][A-Z0-9]{1,7})\)/gu,
    )) {
      const words = m[1].split(/\s+/);
      const initials = m[2].length;
      const long = words.slice(-Math.min(words.length, initials + 4)).join(" ");
      if (!defs.has(m[2])) defs.set(m[2], long);
    }
    if (defs.size) glossary(md, defs);
  }
  void changed;
}

function glossary(md, defs) {
  const rx = new RegExp(`\\b(${[...defs.keys()].join("|")})\\b`, "g");
  const seen = new Set();
  const walker = document.createTreeWalker(md, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      n.parentElement?.closest("code,pre,a,abbr,button,h1,h2,h3,h4,.code-block")
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const s = node.textContent;
    if (!rx.test(s)) continue;
    rx.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of s.matchAll(rx)) {
      const acr = m[1];
      const defined =
        s.slice(m.index - 2, m.index) === " (" || s[m.index - 1] === "(";
      if (!seen.has(acr) || defined) {
        seen.add(acr); // the definition itself, and the first use, stay plain
        continue;
      }
      frag.append(
        s.slice(last, m.index),
        h(
          "abbr",
          {
            class: "md-gloss",
            title: defs.get(acr),
            tabindex: "0",
            "aria-label": `${acr} : ${defs.get(acr)}`,
          },
          acr,
        ),
      );
      last = m.index + acr.length;
    }
    if (last) {
      frag.append(s.slice(last));
      node.replaceWith(frag);
    }
  }
}
