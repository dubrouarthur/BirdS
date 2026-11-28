// Follow-up chips under the last answer and one-click transforms of the answer. Bird writes its own next steps
// (the ``suggestions`` event, birds/harness/nextsteps.py: the user's voice, validated server side); the widget
// chips below (weather, map, draft, table) are deterministic and fill in. A chip only sends a request the user
// could have typed; the harness reads it like any other.
import { h, state, t } from "./core.js";
import { canvasSuggestions } from "./canvas.js";

const lang = () => (state.prefs.lang === "en" ? "en" : "fr");
const L = (fr, en) => (lang() === "en" ? en : fr);

/** Is there a Markdown table with figures in the answer (two rows or more)? */
export function hasNumericTable(text) {
  const rows = String(text || "")
    .split("\n")
    .filter((l) => /^\s*\|.+\|\s*$/.test(l) && !/^\s*\|?\s*:?-{2,}/.test(l));
  return (
    rows.length >= 3 && rows.slice(1).filter((r) => /\d/.test(r)).length >= 2
  );
}

/** The 2-3 follow-up suggestions of an answer: [{label, prompt, kind}]. */
export function suggestions(answer) {
  if (!answer) return [];
  const out = [];
  const add = (label, prompt, kind = "follow") => {
    if (out.length < 3 && !out.some((x) => x.prompt === prompt))
      out.push({ label, prompt, kind });
  };
  // a document that evolves in the canvas: the next steps the harness read in its structure (a missing section…)
  for (const c of answer.canvas?.next || []) add(c.label, c.prompt, "canvas");
  const code = answer.canvas?.kind === "code" ? answer.canvas.hints : null;
  if (code?.web) {
    // the next steps of a page, from what its files already have (canvas_web.ref: code.hints)
    if (!code.mobile)
      add(
        L("Version mobile", "Mobile layout"),
        L("Améliore l'affichage de la page sur mobile.", "Improve the page's layout on mobile."),
        "canvas",
      );
    if (!code.dark)
      add(
        L("Mode sombre", "Dark mode"),
        L("Ajoute un mode sombre automatique à la page.", "Add an automatic dark mode to the page."),
        "canvas",
      );
    add(
      code.js ? L("Accessible au clavier", "Keyboard accessible") : L("Un peu d'interaction", "Some interaction"),
      code.js
        ? L("Rends la page accessible au clavier et aux lecteurs d'écran.",
            "Make the page accessible with the keyboard and screen readers.")
        : L("Ajoute un peu d'interaction en JavaScript à la page.", "Add some JavaScript interaction to the page."),
      "canvas",
    );
    add(
      L("Animations douces", "Subtle animations"),
      L("Ajoute des animations douces à la page.", "Add subtle animations to the page."),
      "canvas",
    );
  } else if (code && code.lang === "python") {
    add(
      L("Gérer les erreurs", "Handle errors"),
      L("Ajoute la gestion des erreurs au script.", "Add error handling to the script."),
      "canvas",
    );
    add(
      L("Ajouter des tests", "Add tests"),
      L("Ajoute des tests unitaires au script.", "Add unit tests to the script."),
      "canvas",
    );
  }
  if (answer.canvas?.aid)
    for (const c of canvasSuggestions(answer.canvas)) add(c.label, c.prompt, c.kind);
  const widgets = answer.widgets || [];
  for (const w of widgets) {
    if (w.type === "weather") {
      // the day after the one the card shows, read from its relative-day field (w.day is the ISO date)
      const kind = w.day_kind || (/demain|tomorrow/i.test(String(w.day || "")) ? "tomorrow" : "today");
      const place = w.place?.name ? String(w.place.name) : "";
      const where = place ? L(` à ${place}`, ` in ${place}`) : "";
      if (kind === "today")
        add(L("Et demain ?", "What about tomorrow?"), L(`et demain${where} ?`, `what about tomorrow${where}?`));
      else if (kind === "tomorrow")
        add(
          L("Et après-demain ?", "And the day after?"),
          L(`et après-demain${where} ?`, `what about the day after tomorrow${where}?`),
        );
      else if (/^\d{4}-\d{2}-\d{2}$/.test(String(w.day || ""))) {
        const next = new Date(`${w.day}T12:00:00Z`);
        next.setUTCDate(next.getUTCDate() + 1);
        const day = next.toLocaleDateString(lang() === "en" ? "en-GB" : "fr-FR", {
          weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
        add(L("Et le lendemain ?", "And the next day?"), L(`et le ${day}${where} ?`, `what about ${day}${where}?`));
      }
      // no « Restaurants autour » under a forecast: Bird's own next steps fill the row
    } else if (w.type === "places" && (w.places || []).length) {
      const p = w.places[0];
      add(
        L("Itinéraire", "Directions"),
        L(`itinéraire pour aller à ${p.name}`, `directions to ${p.name}`),
      );
      if (p.address)
        add(
          L("La météo là-bas", "Weather there"),
          L("et la météo là-bas ?", "and the weather there?"),
        );
    } else if (w.type === "fx" && w.from && w.to) {
      add(
        L(`De ${w.to} en ${w.from}`, `From ${w.to} to ${w.from}`),
        L(
          `convertis ${w.amount ?? 1} ${w.to} en ${w.from}`,
          `convert ${w.amount ?? 1} ${w.to} to ${w.from}`,
        ),
      );
    } else if (w.type === "research") {
      const graph = widgets.find((x) => x.type === "graph");
      const deg = new Map();
      for (const e of graph?.edges || []) {
        deg.set(e.s, (deg.get(e.s) || 0) + 1);
        deg.set(e.t, (deg.get(e.t) || 0) + 1);
      }
      const top = (graph?.nodes || [])
        .filter((n) => n.type !== "lieu")
        .sort((a, b) => (deg.get(b.id) || 0) - (deg.get(a.id) || 0))
        .slice(0, 2);
      for (const n of top)
        add(
          L(`Approfondir ${n.label}`, `Dig into ${n.label}`),
          L(
            `Fais une recherche approfondie sur ${n.label}`,
            `Deep research on ${n.label}`,
          ),
          "research",
        );
      if (!graph)
        add(
          L("Carte des acteurs", "Map of players"),
          L(
            `Fais la carte des acteurs de ${w.topic}`,
            `Make a map of the players in ${w.topic}`,
          ),
          "research",
        );
    } else if (w.type === "calc" && w.kind === "loan") {
      const v = Object.fromEntries(
        (w.inputs || []).map((i) => [i.key, i.value]),
      );
      const years = Number(v.years) + 5;
      if (years <= 30)
        add(
          L(`Sur ${years} ans`, `Over ${years} years`),
          L(
            `mensualité d'un prêt de ${v.principal} € sur ${years} ans à ${v.rate} %`,
            `monthly payment of a loan of ${v.principal} € over ${years} years at ${v.rate} %`,
          ),
        );
    } else if (w.type === "matrix") {
      add(
        L("En graphique", "As a chart"),
        L("mets ça sous forme de graphique", "show that as a chart"),
      );
    }
  }
  if (answer.draft_email) {
    add(
      L("Plus court", "Shorter"),
      L("Rends ce mail plus court.", "Make this e-mail shorter."),
      "mail",
    );
    add(
      L("Plus formel", "More formal"),
      L("Rends ce mail plus formel.", "Make this e-mail more formal."),
      "mail",
    );
    add(
      L("En anglais", "In French"),
      L("Traduis ce mail en anglais.", "Translate this e-mail into French."),
      "mail",
    );
  }
  if (!(answer.charts || []).length && hasNumericTable(answer.content))
    add(
      L("En graphique", "As a chart"),
      L("mets ça sous forme de graphique", "show that as a chart"),
    );
  return out;
}

const LABEL_MAX = 60; // nextsteps.LABEL_HARD: a longer label was cut, its chip is dropped (never trimmed)
const PROMPT_MAX = 200;
const fold = (x) =>
  String(x || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

/** The next steps Bird wrote for this answer (the ``suggestions`` event, validated by the server in
 * birds/harness/nextsteps.py), checked again here: strings only, lengths (a too long label drops its chip: a
 * trimmed label would promise another request than the one sent), at most 3, no duplicates. */
export function cleanSuggestions(items) {
  const out = [];
  for (const it of Array.isArray(items) ? items : []) {
    if (!it || typeof it.label !== "string" || typeof it.prompt !== "string") continue;
    const prompt = String(it.prompt ?? "").replace(/\s+/g, " ").trim().slice(0, PROMPT_MAX);
    let label = String(it.label ?? "").replace(/\s+/g, " ").trim();
    if (!prompt || !label || label.length >= LABEL_MAX) continue;
    if (out.some((x) => fold(x.prompt) === fold(prompt) || fold(x.label) === fold(label))) continue;
    out.push({ label, prompt });
    if (out.length === 3) break;
  }
  return out;
}

/** The chips of an answer: Bird's own next steps first, then the widget chips (weather, map, draft…) to fill up
 * to three, without repeating a request. No regex cuts Bird's question into pieces any more. */
export function chipItems(answer) {
  if (!answer) return [];
  const items = cleanSuggestions(answer.suggestions).map((x) => ({ ...x, kind: "next" }));
  for (const w of suggestions(answer)) {
    if (items.length >= 3) break;
    const k = fold(w.prompt);
    if (!items.some((x) => fold(x.prompt) === k || fold(x.label) === fold(w.label))) items.push(w);
  }
  return items;
}

/** The transforms of the « Plus » menu: [label, prompt]. */
export function transforms() {
  return [
    [
      t("mod.tf.shorter"),
      L(
        "Raccourcis ta réponse précédente.",
        "Make your previous answer shorter.",
      ),
    ],
    [
      t("mod.tf.longer"),
      L(
        "Développe ta réponse précédente avec plus de détails.",
        "Expand your previous answer with more detail.",
      ),
    ],
    [
      t("mod.tf.formal"),
      L(
        "Reformule ta réponse précédente sur un ton plus formel.",
        "Rewrite your previous answer in a more formal tone.",
      ),
    ],
    [
      t("mod.tf.translate"),
      L(
        "Traduis ta réponse précédente en anglais.",
        "Translate your previous answer into French.",
      ),
    ],
    [
      t("mod.tf.table"),
      L(
        "Présente ta réponse précédente sous forme de tableau.",
        "Present your previous answer as a table.",
      ),
    ],
    [
      t("mod.tf.list"),
      L(
        "Présente ta réponse précédente sous forme de liste à puces.",
        "Present your previous answer as a bulleted list.",
      ),
    ],
  ];
}

function fillComposer(text) {
  const box = document.getElementById("composer-input");
  if (!box) return;
  box.value = text;
  box.dispatchEvent(new Event("input", { bubbles: true }));
  box.focus();
  box.setSelectionRange(text.length, text.length);
}

/** The answers whose next steps are still coming (the late ``suggestions`` event after « final »): their chip row
 * waits for them, so the row appears once, in its final order. In memory only: a reloaded turn never waits. */
export const chipsWaiting = new WeakSet();

/** The chip row of the last answer, or null: each chip sends a request the user could have typed. */
export function renderChips(turn, onSuggest, busy = false) {
  if (!turn?.answer || turn.status === "running" || busy || chipsWaiting.has(turn)) return null;
  const items = chipItems(
    turn.canvasLive?.phase === "final" && !turn.answer.canvas
      ? { ...turn.answer, canvas: turn.canvasLive } // a deck made this turn (its card is above the chips)
      : turn.answer,
  );
  if (!items.length) return null;
  return h(
    "div",
    { class: "chips-row", role: "group", "aria-label": t("mod.chips") },
    items.map((it) =>
      h(
        "button",
        {
          class: `mchip mchip-${it.kind}`,
          type: "button",
          "data-act": `chip-${it.kind}`,
          title: it.prompt,
          // « fill »: the chip writes the start of a message the user completes (their own figures)
          onclick: () => (it.kind === "fill" ? fillComposer(it.prompt) : onSuggest(it.prompt)),
        },
        h("span", { class: "mchip-arrow", "aria-hidden": "true" }, "↳"),
        h("span", { class: "mchip-text" }, it.label),
      ),
    ),
  );
}
