// Deep research, on screen: the live board while the team works (sub-questions, queries, sources arriving, claims
// checked and corroborated, contradictions, the relation graph growing), the report card under the answer, and the
// full-screen report (table of contents, [n] citations with a bubble, sources cited / consulted, timeline, comparison,
// key figures, confidence per claim, export Word / PDF / slides).
// Everything shown comes from the server's agent_research events and the "report" widget (pages read, quotes found
// in them, counts made by code), never from model prose. h() only (text nodes); no style attribute (CSP).
import { b64ToBytes, button, download, h, icon, state, t, toast } from "./core.js";
import { STRINGS } from "./i18n.js";
import { safeUrl } from "./markdown.js";
import { liveGraph, MODULES, moduleHooks } from "./modules.js";

const FR = {
  "rs.board": "Tableau de bord de la recherche",
  "rs.phase.plan": "Découpage de la question",
  "rs.phase.search": "Recherches en cours",
  "rs.phase.read": "Lecture des sources",
  "rs.phase.extract": "Relevé des affirmations",
  "rs.phase.check": "Recoupement des sources",
  "rs.phase.write": "Rédaction du rapport",
  "rs.phase.done": "Recherche terminée",
  "rs.stat.questions": "sous-questions résolues",
  "rs.stat.sources": "sources retenues",
  "rs.stat.claims": "affirmations vérifiées",
  "rs.stat.crossed": "recoupées",
  "rs.questions": "Sous-questions",
  "rs.q.open": "à chercher",
  "rs.q.resolved": "résolue",
  "rs.q.thin": "peu de sources",
  "rs.q.claims": "{n} affirmation(s)",
  "rs.queries": "Requêtes",
  "rs.query.results": "{n} résultat(s)",
  "rs.sources": "Sources, au fil de la lecture",
  "rs.src.queued": "en attente",
  "rs.src.reading": "lecture…",
  "rs.src.kept": "retenue",
  "rs.src.thin": "peu de contenu",
  "rs.src.error": "illisible",
  "rs.src.flagged": "écartée (page suspecte)",
  "rs.src.unread": "non lue",
  "rs.contra": "Les sources divergent",
  "rs.contra.item": "{a} [{na}] contre {b} [{nb}]",
  "rs.graph": "Carte des relations (en cours)",
  "rs.say.resolved": "Sous-question résolue : {q}",
  "rs.say.done": "Recherche terminée, rapport prêt",
  "rp.card": "Rapport de recherche",
  "rp.meta": "{s} section(s) · {c} source(s) citée(s) · {k} affirmation(s) vérifiée(s)",
  "rp.open": "Ouvrir le rapport",
  "rp.close": "Fermer le rapport",
  "rp.toc": "Sommaire",
  "rp.summary": "Résumé",
  "rp.figures": "Chiffres clés",
  "rp.claims": "Affirmations et niveau de confiance",
  "rp.contra": "Contradictions entre sources",
  "rp.questions": "Sous-questions",
  "rp.timeline": "Chronologie",
  "rp.matrix": "Comparaison",
  "rp.graph": "Carte des relations",
  "rp.sources": "Sources",
  "rp.cited": "Citées ({n})",
  "rp.consulted": "Consultées ({n})",
  "rp.consulted.none": "Toutes les pages lues sont citées.",
  "rp.notcited": "lue, non citée",
  "rp.conf.high": "Confiance élevée",
  "rp.conf.medium": "Confiance moyenne",
  "rp.conf.low": "Confiance faible",
  "rp.conf.help.high": "recoupée par un autre site",
  "rp.conf.help.medium": "citation retrouvée dans une seule source",
  "rp.conf.help.low": "contredite par une autre source, ou phrase peu étayée",
  "rp.also": "recoupée par",
  "rp.against": "contredite par",
  "rp.quote": "Citation",
  "rp.openSource": "Ouvrir la source",
  "rp.cite": "Source {n}",
  "rp.export": "Exporter",
  "rp.word": "Word",
  "rp.pdf": "PDF",
  "rp.slides": "Diapos",
  "rp.export.done": "Fichier prêt",
  "rp.export.error": "L'export n'a pas abouti",
  "rp.note":
    "Chaque phrase citée a été vérifiée dans sa source par Bird ; les chiffres sans source ont été retirés.",
  "rp.counts":
    "{queries} recherche(s) · {read} page(s) lue(s) · {kept} retenue(s) · {claims} affirmation(s) vérifiée(s) · {crossed} recoupée(s)",
  "rp.sourcesTitle": "Sources",
};
const EN = {
  "rs.board": "Research dashboard",
  "rs.phase.plan": "Splitting the question",
  "rs.phase.search": "Searching",
  "rs.phase.read": "Reading the sources",
  "rs.phase.extract": "Recording the claims",
  "rs.phase.check": "Cross-checking the sources",
  "rs.phase.write": "Writing the report",
  "rs.phase.done": "Research done",
  "rs.stat.questions": "sub-questions resolved",
  "rs.stat.sources": "sources kept",
  "rs.stat.claims": "claims checked",
  "rs.stat.crossed": "corroborated",
  "rs.questions": "Sub-questions",
  "rs.q.open": "to search",
  "rs.q.resolved": "resolved",
  "rs.q.thin": "few sources",
  "rs.q.claims": "{n} claim(s)",
  "rs.queries": "Queries",
  "rs.query.results": "{n} result(s)",
  "rs.sources": "Sources, as they are read",
  "rs.src.queued": "queued",
  "rs.src.reading": "reading…",
  "rs.src.kept": "kept",
  "rs.src.thin": "little content",
  "rs.src.error": "unreadable",
  "rs.src.flagged": "set aside (suspicious page)",
  "rs.src.unread": "not read",
  "rs.contra": "The sources disagree",
  "rs.contra.item": "{a} [{na}] against {b} [{nb}]",
  "rs.graph": "Relation map (growing)",
  "rs.say.resolved": "Sub-question resolved: {q}",
  "rs.say.done": "Research done, report ready",
  "rp.card": "Research report",
  "rp.meta": "{s} section(s) · {c} source(s) cited · {k} claim(s) checked",
  "rp.open": "Open the report",
  "rp.close": "Close the report",
  "rp.toc": "Contents",
  "rp.summary": "Summary",
  "rp.figures": "Key figures",
  "rp.claims": "Claims and confidence",
  "rp.contra": "Contradictions between sources",
  "rp.questions": "Sub-questions",
  "rp.timeline": "Timeline",
  "rp.matrix": "Comparison",
  "rp.graph": "Relation map",
  "rp.sources": "Sources",
  "rp.cited": "Cited ({n})",
  "rp.consulted": "Consulted ({n})",
  "rp.consulted.none": "Every page read is cited.",
  "rp.notcited": "read, not cited",
  "rp.conf.high": "High confidence",
  "rp.conf.medium": "Medium confidence",
  "rp.conf.low": "Low confidence",
  "rp.conf.help.high": "corroborated by another site",
  "rp.conf.help.medium": "quote found in one source",
  "rp.conf.help.low": "contradicted by another source, or weakly supported",
  "rp.also": "corroborated by",
  "rp.against": "contradicted by",
  "rp.quote": "Quote",
  "rp.openSource": "Open the source",
  "rp.cite": "Source {n}",
  "rp.export": "Export",
  "rp.word": "Word",
  "rp.pdf": "PDF",
  "rp.slides": "Slides",
  "rp.export.done": "File ready",
  "rp.export.error": "The export failed",
  "rp.note":
    "Bird checked each cited sentence in its source; figures with no source were removed.",
  "rp.counts":
    "{queries} search(es) · {read} page(s) read · {kept} kept · {claims} claim(s) checked · {crossed} corroborated",
  "rp.sourcesTitle": "Sources",
};
for (const [k, v] of Object.entries(FR)) STRINGS.fr[k] ??= v;
for (const [k, v] of Object.entries(EN)) STRINGS.en[k] ??= v;

const str = (v, n) => String(v ?? "").slice(0, n);
const PHASES = ["plan", "search", "read", "extract", "check", "write", "done"];
const Q_STATUS = ["open", "resolved", "thin"];
const SRC_STATUS = ["queued", "reading", "kept", "thin", "error", "flagged", "unread"];
const CONF = ["high", "medium", "low"];
const pick = (v, list, dflt) => (list.includes(v) ? v : dflt);
const int = (v) => (Number.isFinite(Number(v)) ? Math.max(0, Math.round(Number(v))) : 0);

// ------------------------------------------------------------------ the live board

/** agent_research: the whole board, validated; returns a sentence to announce (a question resolved, the end). */
export function applyResearchEvent(turn, ev) {
  const prev = turn.research;
  const board = {
    phase: pick(ev.phase, PHASES, "plan"),
    topic: str(ev.topic, 160),
    questions: (Array.isArray(ev.questions) ? ev.questions : []).slice(0, 5).map((q) => ({
      id: str(q?.id, 8),
      text: str(q?.text, 160),
      query: str(q?.query, 90),
      status: pick(q?.status, Q_STATUS, "open"),
      claims: int(q?.claims),
    })),
    queries: (Array.isArray(ev.queries) ? ev.queries : []).slice(0, 6).map((q) => ({
      q: str(q?.q, 90),
      status: pick(q?.status, ["queued", "running", "done", "error"], "queued"),
      results: int(q?.results),
    })),
    sources: (Array.isArray(ev.sources) ? ev.sources : []).slice(0, 16).map((s) => ({
      domain: str(s?.domain, 60),
      title: str(s?.title, 90),
      status: pick(s?.status, SRC_STATUS, "queued"),
      n: int(s?.n) || null,
      claims: int(s?.claims),
    })),
    claims: {
      seen: int(ev.claims?.seen),
      checked: int(ev.claims?.checked),
      dropped: int(ev.claims?.dropped),
      crossed: int(ev.claims?.crossed),
    },
    contradictions: (Array.isArray(ev.contradictions) ? ev.contradictions : []).slice(0, 4).map((c) => ({
      a: str(c?.a, 40),
      b: str(c?.b, 40),
      na: int(c?.na),
      nb: int(c?.nb),
      text: str(c?.text, 140),
    })),
    graph: ev.graph && Array.isArray(ev.graph.nodes) ? ev.graph : prev?.graph || null,
  };
  turn.research = board;
  if (board.phase === "done" && prev?.phase !== "done") return t("rs.say.done");
  const before = new Set((prev?.questions || []).filter((q) => q.status === "resolved").map((q) => q.id));
  const now = board.questions.find((q) => q.status === "resolved" && !before.has(q.id));
  return now ? t("rs.say.resolved", { q: now.text }) : "";
}

function stat(value, label, extra = "") {
  return h(
    "div",
    { class: `rsb-stat${extra}` },
    h("span", { class: "rsb-stat-n num", text: value }),
    h("span", { class: "rsb-stat-l", text: label }),
  );
}

const Q_MARK = { open: "", resolved: "check", thin: "alert" };

/** The live board inside the team card (replaces the generic board for deep research). */
export function researchBoard(turn) {
  const b = turn.research;
  if (!b) return null;
  const kept = b.sources.filter((s) => s.status === "kept").length;
  const resolved = b.questions.filter((q) => q.status === "resolved").length;
  const phaseAt = PHASES.indexOf(b.phase);
  return h(
    "section",
    { class: "rsb", "aria-label": t("rs.board"), "data-phase": b.phase },
    h(
      "ol",
      { class: "rsb-phases", "aria-label": t("rs.board") },
      PHASES.slice(0, -1).map((p, i) =>
        h("li", {
          class: `rsb-phase ${i < phaseAt ? "is-done" : i === phaseAt ? "is-current" : ""}`,
          ...(i === phaseAt ? { "aria-current": "step" } : {}),
          text: t(`rs.phase.${p}`),
        }),
      ),
    ),
    h(
      "div",
      { class: "rsb-stats" },
      b.questions.length > 0 && stat(`${resolved}/${b.questions.length}`, t("rs.stat.questions")),
      stat(String(kept), t("rs.stat.sources")),
      stat(String(b.claims.checked), t("rs.stat.claims")),
      stat(String(b.claims.crossed), t("rs.stat.crossed")),
    ),
    b.questions.length > 0 &&
      h(
        "div",
        { class: "rsb-block" },
        h("h4", { class: "rsb-h", text: t("rs.questions") }),
        h(
          "ol",
          { class: "rsb-questions" },
          b.questions.map((q) =>
            h(
              "li",
              { class: `rsb-q is-${q.status}`, "data-q": q.id },
              h(
                "span",
                { class: "rsb-q-mark", "aria-hidden": "true" },
                Q_MARK[q.status] ? icon(Q_MARK[q.status]) : null,
              ),
              h(
                "span",
                { class: "rsb-q-body" },
                h("span", { class: "rsb-q-text", text: q.text }),
                h(
                  "span",
                  { class: "rsb-q-meta" },
                  q.query && h("span", { class: "rsb-query" }, icon("web_search"), h("span", { text: q.query })),
                  h("span", {
                    class: "rsb-q-status",
                    text:
                      q.status === "resolved" && q.claims
                        ? `${t("rs.q.resolved")} · ${t("rs.q.claims", { n: q.claims })}`
                        : t(`rs.q.${q.status}`),
                  }),
                ),
              ),
            ),
          ),
        ),
      ),
    b.sources.length > 0 &&
      h(
        "div",
        { class: "rsb-block" },
        h("h4", { class: "rsb-h", text: t("rs.sources") }),
        h(
          "ul",
          { class: "rsb-sources" },
          b.sources
            .filter((s) => s.status !== "queued" && s.status !== "unread")
            .map((s) =>
              h(
                "li",
                { class: `rsb-src is-${s.status}`, title: s.title || s.domain, "data-site": s.domain },
                s.n && h("span", { class: "rsb-src-n num", text: String(s.n) }),
                h("span", { class: "rsb-src-d", text: s.domain || s.title }),
                h("span", {
                  class: "rsb-src-s",
                  text: s.status === "kept" && s.claims ? t("rs.q.claims", { n: s.claims }) : t(`rs.src.${s.status}`),
                }),
              ),
            ),
        ),
      ),
    b.contradictions.length > 0 &&
      h(
        "div",
        { class: "rsb-block rsb-contra", role: "note" },
        h("h4", { class: "rsb-h" }, icon("alert"), h("span", { text: t("rs.contra") })),
        h(
          "ul",
          null,
          b.contradictions.map((c) => h("li", { text: t("rs.contra.item", c) })),
        ),
      ),
    b.graph &&
      (b.graph.nodes || []).length >= 2 &&
      h(
        "div",
        { class: "rsb-block" },
        h("h4", { class: "rsb-h", text: t("rs.graph") }),
        liveGraph(b.graph, turn),
      ),
  );
}

// ------------------------------------------------------------------ the report card under the answer

const widgetsOf = (turn) => turn?.answer?.widgets || [];
const widgetOf = (turn, type) => widgetsOf(turn).find((w) => w?.type === type);

function renderReportCard(w, turn) {
  const sections = (w.sections || []).filter((s) => s?.heading);
  if (!sections.length) return null;
  const cited = (w.sources || []).filter((s) => s.cited).length;
  return h(
    "section",
    { class: "widget mod rp-card", "aria-label": t("rp.card") },
    h("h3", { class: "widget-title mod-title" }, icon("make_document"), h("span", { text: t("rp.card") })),
    h("p", { class: "rp-card-title", text: str(w.title, 140) }),
    h(
      "p",
      { class: "muted rp-card-meta" },
      t("rp.meta", { s: sections.length, c: cited, k: (w.claims || []).length }),
    ),
    (w.figures || []).length > 0 &&
      h(
        "ul",
        { class: "rp-figs is-mini", "aria-label": t("rp.figures") },
        w.figures.slice(0, 3).map((f) => figureTile(f, turn, w)),
      ),
    h(
      "ol",
      { class: "rp-card-toc", "aria-label": t("rp.toc") },
      sections.map((s) => h("li", { text: str(s.heading, 90) })),
    ),
    h(
      "div",
      { class: "mod-actions rp-actions" },
      button("btn-primary btn-small", "expand", t("rp.open"), () => openReport(w, turn), { "data-act": "rp-open" }),
      exportButtons(w, turn),
    ),
  );
}

function exportButtons(w, turn) {
  return [
    button("btn-outline btn-small", "word", t("rp.word"), () => exportReport(w, turn, "docx"), { "data-act": "rp-docx" }),
    button("btn-outline btn-small", "download", t("rp.pdf"), () => exportReport(w, turn, "pdf"), { "data-act": "rp-pdf" }),
    button("btn-outline btn-small", "make_slides", t("rp.slides"), () => exportReport(w, turn, "pptx"), {
      "data-act": "rp-pptx",
    }),
  ];
}

// ------------------------------------------------------------------ the full-screen report

let bubble = null; // the citation bubble open, if any

function closeBubble() {
  if (!bubble) return;
  bubble.btn.setAttribute("aria-expanded", "false");
  bubble.el.remove();
  bubble = null;
}

/** The claim of source n that best supports a sentence (most long words in common), for the bubble. */
export function bestClaim(claims, n, sentence) {
  const words = (s) =>
    new Set(
      String(s || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .match(/[a-z0-9]{5,}/g) || [],
    );
  const want = words(sentence);
  let best = null;
  let score = -1;
  for (const c of claims || []) {
    if (c.n !== n) continue;
    const have = words(`${c.t} ${c.q}`);
    let k = 0;
    for (const x of want) if (have.has(x)) k += 1;
    if (k > score) {
      score = k;
      best = c;
    }
  }
  return best;
}

function citeButton(w, n, sentence, host) {
  const src = (w.sources || []).find((s) => s.n === n);
  if (!src) return null;
  const btn = h("button", {
    class: "rp-cite num",
    type: "button",
    "aria-expanded": "false",
    "aria-label": t("rp.cite", { n }),
    "data-cite": String(n),
    text: `[${n}]`,
  });
  const open = () => {
    if (bubble?.btn === btn) return;
    closeBubble();
    const claim = bestClaim(w.claims, n, sentence);
    const url = safeUrl(src.url);
    const el = h(
      "div",
      { class: "rp-bubble", role: "dialog", "aria-label": t("rp.cite", { n }) },
      h(
        "p",
        { class: "rp-bubble-head" },
        h("span", { class: "source-n num", text: String(n) }),
        h("span", { class: "rp-bubble-d", text: src.domain || src.title }),
      ),
      h("p", { class: "rp-bubble-t", text: src.title }),
      claim?.q && h("blockquote", { class: "rp-bubble-q", text: `« ${claim.q} »` }),
      claim && confBadge(claim.conf),
      url &&
        h(
          "a",
          { class: "rp-bubble-link", href: url, target: "_blank", rel: "noopener noreferrer", referrerpolicy: "no-referrer" },
          t("rp.openSource"),
        ),
    );
    host.append(el);
    const hb = host.getBoundingClientRect();
    const bb = btn.getBoundingClientRect();
    const left = Math.max(8, Math.min(bb.left - hb.left + host.scrollLeft - 20, host.clientWidth - 328));
    el.style.setProperty("--rp-x", `${left}px`);
    el.style.setProperty("--rp-y", `${bb.bottom - hb.top + host.scrollTop + 6}px`);
    btn.setAttribute("aria-expanded", "true");
    bubble = { btn, el, at: Date.now() };
  };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    // a click right after the focus or the hover that opened it keeps it open (a tap fires all three)
    if (bubble?.btn === btn && Date.now() - bubble.at > 400) closeBubble();
    else open();
  });
  btn.addEventListener("mouseenter", () => matchMedia("(hover: hover)").matches && open());
  btn.addEventListener("focus", open);
  btn.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && bubble) {
      e.stopPropagation();
      e.preventDefault();
      closeBubble();
    }
  });
  return btn;
}

function prose(w, sents, host) {
  return h(
    "p",
    { class: "rp-p" },
    (sents || []).flatMap((s, i) => {
      // « … 40 millions d'euros [1]. »: the citation goes before the sentence's final mark
      const m = String(s.t).match(/^(.*?)([.!?…]*)$/s);
      return [
        i ? " " : "",
        m[1],
        ...(s.c || []).flatMap((n) => [" ", citeButton(w, Number(n), s.t, host)]),
        m[2],
      ];
    }),
  );
}

function confBadge(conf) {
  const c = pick(conf, CONF, "medium");
  return h("span", { class: `rp-conf is-${c}`, title: t(`rp.conf.help.${c}`) }, h("span", { class: "rp-conf-dot", "aria-hidden": "true" }), t(`rp.conf.${c}`));
}

function figureTile(f, turn, w) {
  return h(
    "li",
    { class: `rp-fig is-${pick(f.conf, CONF, "medium")}` },
    h("span", { class: "rp-fig-v num", text: str(f.value, 40) }),
    h("span", { class: "rp-fig-l", text: str(f.label, 140) }),
    h("span", { class: "rp-fig-s muted", text: `[${int(f.n)}]${f.date ? ` · ${str(f.date, 20)}` : ""}` }),
  );
}

function sourcesPanel(w) {
  const cited = (w.sources || []).filter((s) => s.cited);
  const other = [
    ...(w.sources || []).filter((s) => !s.cited).map((s) => ({ ...s, why: t("rp.notcited") })),
    ...(w.consulted || []).map((s) => ({ ...s, why: t(`rs.src.${pick(s.status, SRC_STATUS, "thin")}`) })),
  ];
  const item = (s) => {
    const url = safeUrl(s.url);
    return h(
      "li",
      { class: "rp-src", id: s.n ? `rp-src-${s.n}` : null },
      h(
        "div",
        { class: "rp-src-head" },
        s.n && h("span", { class: "source-n num", text: String(s.n) }),
        h("span", { class: "rp-src-d", text: s.domain || "" }),
        s.why && h("span", { class: "rp-src-why muted", text: s.why }),
      ),
      url
        ? h("a", { class: "rp-src-t", href: url, target: "_blank", rel: "noopener noreferrer", referrerpolicy: "no-referrer", text: s.title || url })
        : h("span", { class: "rp-src-t", text: s.title || "" }),
      s.claims > 0 && h("span", { class: "muted rp-src-c", text: t("rs.q.claims", { n: s.claims }) }),
    );
  };
  const lists = {
    cited: h("ol", { class: "rp-srcs", id: "rp-tab-cited" }, cited.map(item)),
    other: other.length
      ? h("ul", { class: "rp-srcs", id: "rp-tab-other", hidden: true }, other.map(item))
      : h("p", { class: "muted", id: "rp-tab-other", hidden: true, text: t("rp.consulted.none") }),
  };
  const tabs = [
    ["cited", t("rp.cited", { n: cited.length })],
    ["other", t("rp.consulted", { n: other.length })],
  ].map(([k, label], i) =>
    h("button", {
      class: "rp-tab",
      type: "button",
      role: "tab",
      "aria-selected": i === 0 ? "true" : "false",
      "aria-controls": `rp-tab-${k}`,
      "data-tab": k,
      tabindex: i === 0 ? "0" : "-1",
      text: label,
    }),
  );
  const bar = h("div", { class: "rp-tabs", role: "tablist", "aria-label": t("rp.sources") }, tabs);
  const show = (k) => {
    for (const b of tabs) {
      const on = b.dataset.tab === k;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
    }
    lists.cited.hidden = k !== "cited";
    lists.other.hidden = k !== "other";
  };
  bar.addEventListener("click", (e) => {
    const b = e.target.closest(".rp-tab");
    if (b) show(b.dataset.tab);
  });
  bar.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = tabs.indexOf(document.activeElement);
    const next = tabs[(i + 1) % tabs.length];
    next.focus();
    show(next.dataset.tab);
  });
  return h(
    "aside",
    { class: "rp-side", "aria-label": t("rp.sources") },
    h("h2", { class: "rp-side-h", text: t("rp.sourcesTitle") }),
    bar,
    lists.cited,
    lists.other,
  );
}

/** The report, full screen (a modal dialog): Escape or the close button brings the focus back to the opener. */
export function openReport(w, turn) {
  const opener = document.activeElement;
  closeBubble();
  document.querySelector("dialog.rp")?.remove();
  const scroller = h("div", { class: "rp-scroll" });
  const toc = [];
  const blocks = [];
  const add = (id, label, ...body) => {
    toc.push([id, label]);
    blocks.push(h("section", { class: "rp-sec", id: `rp-${id}`, "aria-labelledby": `rp-h-${id}` }, h("h2", { id: `rp-h-${id}`, text: label }), ...body));
  };
  if ((w.summary || []).length) add("summary", t("rp.summary"), prose(w, w.summary, scroller));
  if ((w.figures || []).length)
    add("figures", t("rp.figures"), h("ul", { class: "rp-figs" }, w.figures.map((f) => figureTile(f, turn, w))));
  for (const s of w.sections || []) add(str(s.id, 8) || "s", str(s.heading, 90), prose(w, s.sents, scroller));
  const tl = widgetOf(turn, "timeline");
  if (tl) add("timeline", t("rp.timeline"), MODULES.timeline(tl, turn));
  const mx = widgetsOf(turn).find((x) => x?.type === "matrix" && x.origin === "sources");
  if (mx) add("matrix", t("rp.matrix"), MODULES.matrix(mx, turn));
  const gr = widgetOf(turn, "graph");
  if (gr) add("graph", t("rp.graph"), MODULES.graph(gr, turn));
  if ((w.contradictions || []).length)
    add(
      "contra",
      t("rp.contra"),
      h(
        "ul",
        { class: "rp-contra" },
        w.contradictions.map((c) =>
          h(
            "li",
            null,
            h("span", { class: "rp-contra-v num", text: str(c.a?.value, 40) }),
            " ",
            citeButton(w, int(c.a?.n), c.a?.text, scroller),
            h("span", { class: "muted", text: ` ${t("rp.against")} ` }),
            h("span", { class: "rp-contra-v num", text: str(c.b?.value, 40) }),
            " ",
            citeButton(w, int(c.b?.n), c.b?.text, scroller),
            h("p", { class: "muted rp-contra-t", text: str(c.a?.text, 200) }),
          ),
        ),
      ),
    );
  if ((w.claims || []).length)
    add(
      "claims",
      t("rp.claims"),
      h(
        "ul",
        { class: "rp-claims" },
        w.claims.map((c) =>
          h(
            "li",
            { class: `rp-claim is-${pick(c.conf, CONF, "medium")}` },
            h("div", { class: "rp-claim-head" }, confBadge(c.conf), c.date && h("span", { class: "muted num", text: str(c.date, 20) })),
            h("p", { class: "rp-claim-t" }, str(c.t, 220), " ", citeButton(w, int(c.n), c.t, scroller)),
            (c.also || []).length > 0 &&
              h("p", { class: "muted rp-claim-x" }, `${t("rp.also")} `, ...c.also.flatMap((n) => [citeButton(w, int(n), c.t, scroller), " "])),
            (c.against || []).length > 0 &&
              h("p", { class: "rp-claim-x is-against" }, `${t("rp.against")} `, ...c.against.flatMap((n) => [citeButton(w, int(n), c.t, scroller), " "])),
            c.q && h("details", { class: "rp-claim-q" }, h("summary", { text: t("rp.quote") }), h("blockquote", { text: `« ${str(c.q, 260)} »` })),
          ),
        ),
      ),
    );
  if ((w.questions || []).length)
    add(
      "questions",
      t("rp.questions"),
      h(
        "ol",
        { class: "rsb-questions" },
        w.questions.map((q) =>
          h(
            "li",
            { class: `rsb-q is-${pick(q.status, Q_STATUS, "open")}` },
            h("span", { class: "rsb-q-mark", "aria-hidden": "true" }, Q_MARK[q.status] ? icon(Q_MARK[q.status]) : null),
            h("span", { class: "rsb-q-body" }, h("span", { class: "rsb-q-text", text: str(q.text, 160) }), h("span", { class: "rsb-q-status", text: t(`rs.q.${pick(q.status, Q_STATUS, "open")}`) })),
          ),
        ),
      ),
    );
  const c = w.counts || {};
  const nav = h(
    "nav",
    { class: "rp-toc", "aria-label": t("rp.toc") },
    h("h2", { class: "rp-toc-h", text: t("rp.toc") }),
    h(
      "ol",
      null,
      toc.map(([id, label]) =>
        h("li", null, h("a", {
          href: `#rp-${id}`,
          "data-toc": id,
          text: label,
          onclick: (e) => {
            e.preventDefault();
            const target = dialog.querySelector(`#rp-${CSS.escape(id)}`);
            target?.scrollIntoView({ block: "start", behavior: "smooth" });
            target?.querySelector("h2")?.setAttribute("tabindex", "-1");
            target?.querySelector("h2")?.focus({ preventScroll: true });
          },
        })),
      ),
    ),
  );
  const main = h(
    "article",
    { class: "rp-main" },
    h("p", { class: "rp-eyebrow", text: t("rp.card") }),
    h("h1", { class: "rp-title", id: "rp-title", text: str(w.title, 140) }),
    h("p", { class: "muted rp-counts", text: t("rp.counts", { queries: int(c.queries), read: int(c.read), kept: int(c.kept), claims: int(c.claims), crossed: int(c.crossed) }) }),
    ...blocks,
    h("p", { class: "widget-source rp-note", text: t("rp.note") }),
  );
  scroller.append(h("div", { class: "rp-grid" }, nav, main, sourcesPanel(w)));
  const dialog = h(
    "dialog",
    { class: "rp", "aria-labelledby": "rp-title" },
    h(
      "header",
      { class: "rp-bar" },
      h("span", { class: "rp-bar-title", text: str(w.title, 140) }),
      h("div", { class: "rp-bar-acts", role: "group", "aria-label": t("rp.export") }, exportButtons(w, turn)),
      button("btn-quiet btn-icon", "cross", t("rp.close"), () => dialog.close(), { "data-act": "rp-close" }),
    ),
    scroller,
  );
  dialog.addEventListener("close", () => {
    closeBubble();
    dialog.remove();
    document.body.classList.remove("rp-open");
    opener?.focus?.({ preventScroll: true });
  });
  scroller.addEventListener("click", (e) => {
    if (bubble && !e.target.closest(".rp-bubble") && !e.target.closest(".rp-cite")) closeBubble();
  });
  scroller.addEventListener("scroll", () => {
    // the table of contents follows the reading
    let at = toc[0]?.[0];
    for (const [id] of toc) {
      const el = dialog.querySelector(`#rp-${CSS.escape(id)}`);
      if (el && el.getBoundingClientRect().top < 140) at = id;
    }
    for (const a of nav.querySelectorAll("a")) a.toggleAttribute("aria-current", a.dataset.toc === at);
  });
  document.body.append(dialog);
  document.body.classList.add("rp-open");
  dialog.showModal();
  dialog.querySelector('[data-act="rp-close"]')?.focus();
  return dialog;
}

// ------------------------------------------------------------------ exports (the existing office engine)

const plain = (sents) => (sents || []).map((s) => `${s.t}${(s.c || []).map((n) => ` [${n}]`).join("")}`).join(" ");

/** make_document / make_slides arguments from the report: its own sentences and citations, nothing added. */
export function reportFile(w, kind) {
  const fr = state.prefs.lang !== "en";
  const sources = (w.sources || []).filter((s) => s.cited);
  const srcLines = sources.map((s) => `[${s.n}] ${s.title}${s.domain ? ` — ${s.domain}` : ""}${s.url ? ` — ${s.url}` : ""}`);
  if (kind === "pptx") {
    const bullets = (sents) => (sents || []).slice(0, 5).map((s) => `${s.t}${(s.c || []).map((n) => ` [${n}]`).join("")}`.slice(0, 220));
    const slides = [];
    if ((w.summary || []).length) slides.push({ title: fr ? "En bref" : "In short", bullets: bullets(w.summary) });
    if ((w.figures || []).length)
      slides.push({ title: fr ? "Chiffres clés" : "Key figures", bullets: w.figures.slice(0, 5).map((f) => `${f.value} — ${f.label} [${f.n}]`.slice(0, 220)) });
    for (const s of (w.sections || []).slice(0, 8)) slides.push({ title: s.heading, bullets: bullets(s.sents) });
    if (srcLines.length) slides.push({ title: "Sources", bullets: srcLines.slice(0, 8).map((x) => x.slice(0, 220)) });
    return { tool: "make_slides", arguments: { title: str(w.title, 120), slides: slides.slice(0, 12) } };
  }
  const sections = [];
  if ((w.summary || []).length) sections.push({ heading: fr ? "Résumé" : "Summary", content: plain(w.summary) });
  if ((w.figures || []).length)
    sections.push({ heading: fr ? "Chiffres clés" : "Key figures", content: w.figures.map((f) => `- ${f.value} : ${f.label} [${f.n}]`).join("\n") });
  for (const s of w.sections || []) sections.push({ heading: s.heading, content: plain(s.sents) });
  if ((w.contradictions || []).length)
    sections.push({
      heading: fr ? "Contradictions entre sources" : "Contradictions between sources",
      content: w.contradictions.map((c) => `- ${c.a.value} [${c.a.n}] ${fr ? "contre" : "against"} ${c.b.value} [${c.b.n}]`).join("\n"),
    });
  if (srcLines.length) sections.push({ heading: "Sources", content: srcLines.map((x) => `- ${x}`).join("\n") });
  return { tool: "make_document", arguments: { title: str(w.title, 120), sections } };
}

async function exportReport(w, turn, kind) {
  if (kind === "pdf") {
    // PDF: the browser prints the full-screen report (print stylesheet), no third party involved
    const open = document.querySelector("dialog.rp") || openReport(w, turn);
    open.classList.add("is-print");
    setTimeout(() => {
      window.print();
      open.classList.remove("is-print");
    }, 50);
    return;
  }
  try {
    const body = reportFile(w, kind);
    const response = await fetch("/api/tool", {
      method: "POST",
      headers: moduleHooks().headers(),
      body: JSON.stringify({ ...body, lang: state.prefs.lang }),
    });
    const data = await response.json();
    const file = (data.files || [])[0];
    if (!response.ok || !data.ok || !file?.data) throw new Error(data?.error || "export");
    download(file.name, file.mime, new Blob([b64ToBytes(file.data)], { type: file.mime }));
    toast(t("rp.export.done"), "ok");
  } catch {
    toast(t("rp.export.error"), "error");
  }
}

export const REPORT_MODULES = { report: renderReportCard };

/** The report as plain text (copy) or Markdown (export of the answer). */
export function reportText(w) {
  return [
    w.title,
    plain(w.summary),
    ...(w.sections || []).map((s) => `${s.heading}\n${plain(s.sents)}`),
  ]
    .filter(Boolean)
    .join("\n\n");
}
