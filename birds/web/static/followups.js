// Follow-up chips under the last answer and one-click transforms of the answer. Bird writes its own next steps
// (the ``suggestions`` event, birds/harness/nextsteps.py: the user's voice, validated server side); the widget
// chips below (weather, map, draft, table) are deterministic and fill in. A chip only sends a request the user
// could have typed; the harness reads it like any other.
import { h, state, t } from "./core.js";

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
  const widgets = answer.widgets || [];
  for (const w of widgets) {
    if (w.type === "weather") {
      const tomorrow = /demain|tomorrow/i.test(String(w.day || ""));
      add(
        tomorrow
          ? L("Et après-demain ?", "And the day after?")
          : L("Et demain ?", "What about tomorrow?"),
        tomorrow
          ? L("et après-demain ?", "what about the day after tomorrow?")
          : L("et demain ?", "what about tomorrow?"),
      );
      add(
        L("Restaurants autour", "Restaurants nearby"),
        L("et des restaurants autour ?", "and restaurants nearby?"),
      );
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

const LABEL_MAX = 42;
const PROMPT_MAX = 200;
const fold = (x) =>
  String(x || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

/** The next steps Bird wrote for this answer (the ``suggestions`` event, validated by the server in
 * birds/harness/nextsteps.py), checked again here: strings only, lengths, at most 3, no duplicates. */
export function cleanSuggestions(items) {
  const out = [];
  for (const it of Array.isArray(items) ? items : []) {
    if (!it || typeof it !== "object") continue;
    const prompt = String(it.prompt ?? "").replace(/\s+/g, " ").trim().slice(0, PROMPT_MAX);
    let label = String(it.label ?? "").replace(/\s+/g, " ").trim();
    if (!prompt || !label) continue;
    if (label.length > LABEL_MAX) label = `${label.slice(0, LABEL_MAX - 1).trimEnd()}…`;
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

/** The answers whose next steps are still coming (the late ``suggestions`` event after « final »): their chip row
 * waits for them, so the row appears once, in its final order. In memory only: a reloaded turn never waits. */
export const chipsWaiting = new WeakSet();

/** The chip row of the last answer, or null: each chip sends a request the user could have typed. */
export function renderChips(turn, onSuggest, busy = false) {
  if (!turn?.answer || turn.status === "running" || busy || chipsWaiting.has(turn)) return null;
  const items = chipItems(turn.answer);
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
          onclick: () => onSuggest(it.prompt),
        },
        h("span", { class: "mchip-arrow", "aria-hidden": "true" }, "↳"),
        h("span", { class: "mchip-text" }, it.label),
      ),
    ),
  );
}
