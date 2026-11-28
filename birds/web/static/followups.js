// Follow-up chips under the last answer, clarify chips when Bird asks back, one-click transforms of the answer.
// Deterministic: the chips depend on what the answer IS (its widgets, its draft, a table), never on what the model
// suggests. A chip only sends a request the user could have typed; the harness reads it like any other.
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

const ASKS_BACK =
  /(?:souhaitez-vous|voulez-vous|préférez-vous|préfères-tu|veux-tu|souhaites-tu|vous préférez|plutôt|would you like|do you want|do you prefer|which (?:one|would)|should i)\b/i;

/** Options of a question Bird asks back at the end of its answer (« Souhaitez-vous un mail, une note ou un
 * tableau ? »): 2 to 4 short options, else []. */
export function clarifyOptions(text) {
  const paras = String(text || "")
    .trim()
    .split(/\n\s*\n/);
  const last = (paras.at(-1) || "").trim();
  if (!last.endsWith("?") || last.length > 260 || !ASKS_BACK.test(last))
    return [];
  const sentence = last.split(/(?<=[.!])\s+/).at(-1);
  const body = sentence
    .replace(
      /^.*?(?:souhaitez-vous|voulez-vous|préférez-vous|préfères-tu|veux-tu|souhaites-tu|vous préférez|would you like|do you want|do you prefer|should i)\s*/i,
      "",
    )
    .replace(/\?\s*$/, "")
    .replace(/^(?:que je|qu'on|plutôt|me|to|that i|i)\s+/i, "");
  const parts = body
    .split(/\s*,\s*|\s+ou bien\s+|\s+ou\s+|\s+or\s+/i)
    .map((p) =>
      p
        .replace(/^(?:plutôt|rather|bien)\s+/i, "")
        .replace(/[.;:]+$/, "")
        .trim(),
    )
    .filter((p) => p.length >= 2 && p.length <= 60);
  if (parts.length < 2 || parts.length > 4) return [];
  return parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1));
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

/** The chip row of the last answer, or null. */
export function renderChips(turn, onSuggest, busy = false) {
  if (!turn?.answer || turn.status === "running" || busy) return null;
  const clarify = clarifyOptions(turn.answer.content);
  const items = clarify.length
    ? clarify.map((c) => ({ label: c, prompt: c, kind: "clarify" }))
    : suggestions(turn.answer);
  if (!items.length) return null;
  return h(
    "div",
    {
      class: `chips-row${clarify.length ? " is-clarify" : ""}`,
      role: "group",
      "aria-label": clarify.length ? t("mod.chips.clarify") : t("mod.chips"),
    },
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
        it.label,
      ),
    ),
  );
}
