// Mode Réflexion in the page: the composer's bird slider (an « Auto » switch and five birds, as Claude's) and the « Bird a pris son vol en
// Faucon » header of an answer, with the reasoning summary and the checks the server ran
// (birds/harness/reflexion.py). Drawings and facts: reflexion-data.js; strings: reflexion-i18n.js (rf.* keys).
import { h, icon, state, t } from "./core.js";
import { STRINGS } from "./i18n.js";
import { BIRDS, CHOICES, LEVELS, flightFacts, flightMetaKeys, normalizeChoice } from "./reflexion-data.js";
import { REFLEXION_STRINGS } from "./reflexion-i18n.js";

for (const [lang, strings] of Object.entries(REFLEXION_STRINGS)) Object.assign(STRINGS[lang], strings);

/** An inline SVG of one bird (a constant drawing of reflexion-data.js). */
export function birdIcon(key, cls = "") {
  const wrap = document.createElement("span");
  wrap.innerHTML = `<svg class="rf-bird ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${BIRDS[key] || BIRDS.auto}</svg>`;
  return wrap.firstChild;
}

const nameOf = (key) => t(`rf.level.${key}`);
const asOf = (key) => t(`rf.level.${key}.as`); // « Faucon » / « an Owl », for the header line

// ------------------------------------------------------------------ the picker

let picker = null; // {button, menu, scrim, onPick}

// the slider's resting place while Bird chooses (« Auto »): the middle bird, the usual flight
const AUTO_REST = LEVELS.indexOf("faucon");

function close(focusButton = true) {
  if (!picker || picker.menu.hidden) return;
  picker.menu.hidden = true;
  picker.scrim.hidden = true;
  picker.button.setAttribute("aria-expanded", "false");
  document.removeEventListener("pointerdown", outside, true);
  if (focusButton) picker.button.focus();
}

function outside(e) {
  if (!picker.menu.contains(e.target) && !picker.button.contains(e.target)) close(false);
}

function open() {
  renderMenu();
  const phone = window.matchMedia("(max-width: 640px)").matches;
  const box = picker.button.getBoundingClientRect();
  // fixed, never absolute: the dock scrolls and would clip a popover (the photo menu's lesson); a phone gets a sheet
  picker.menu.style.insetInlineStart = phone ? "" : `${Math.max(12, Math.min(box.left, window.innerWidth - 372))}px`;
  picker.menu.style.insetBlockEnd = phone ? "" : `${Math.max(12, window.innerHeight - box.top + 8)}px`;
  picker.menu.hidden = false;
  picker.scrim.hidden = !phone;
  picker.button.setAttribute("aria-expanded", "true");
  document.addEventListener("pointerdown", outside, true);
  picker.menu.querySelector("#rf-range")?.focus();
}

const valueText = (key) => `${nameOf(key)} · ${t(`rf.level.${key}.label`)}`;

/** The popover, as Claude's: one « Auto » switch and one slider from the hummingbird to the albatross. Built once per
 * opening; a choice updates it in place (syncMenu), never rebuilds it: a slider rebuilt under the pointer drops the drag. */
function renderMenu() {
  picker.lang = state.prefs.lang;
  const range = h("input", {
    id: "rf-range",
    class: "rf-range",
    type: "range",
    min: "0",
    max: String(LEVELS.length - 1),
    step: "1",
    "aria-labelledby": "rf-menu-title",
    "aria-describedby": "rf-now-hint",
  });
  // live while dragging, committed at once: no « OK » button
  range.addEventListener("input", () => pick(LEVELS[Number(range.value)] || "faucon"));
  const autoSwitch = h("input", {
    id: "rf-auto",
    class: "rf-switch",
    type: "checkbox",
    role: "switch",
    "aria-describedby": "rf-auto-hint",
    onchange: (e) => pick(e.target.checked ? "auto" : LEVELS[Number(range.value)]),
  });
  const nowIcon = h("span", { class: "rf-opt-icon" });
  const nowName = h("b");
  const nowLabel = h("span", { class: "rf-opt-label" });
  const nowHint = h("span", { class: "rf-opt-hint", id: "rf-now-hint" });
  const now = h("div", { class: "rf-now", "aria-live": "polite" }, nowIcon, h("span", { class: "rf-opt-text" }, h("span", { class: "rf-opt-name" }, nowName, nowLabel), nowHint));
  const ticks = LEVELS.map((key) =>
    h("button", { class: "rf-tick", type: "button", tabindex: "-1", "data-level": key, title: valueText(key), onclick: () => pick(key) }, birdIcon(key)),
  );
  const slider = h(
    "div",
    { class: "rf-slider" },
    range,
    h("div", { class: "rf-ticks", "aria-hidden": "true" }, ...ticks),
    h("div", { class: "rf-scale", "aria-hidden": "true" }, h("span", { text: t("rf.slider.fast") }), h("span", { text: t("rf.slider.deep") })),
  );
  picker.menu.replaceChildren(
    h(
      "div",
      { class: "rf-menu-head" },
      h("p", { class: "rf-menu-title", id: "rf-menu-title", text: t("rf.menu") }),
      h(
        "label",
        { class: "rf-auto", for: "rf-auto" },
        h("span", { class: "rf-auto-text" }, h("b", { text: t("rf.level.auto") }), h("span", { id: "rf-auto-hint", class: "rf-auto-hint", text: t("rf.slider.auto") })),
        autoSwitch,
      ),
    ),
    now,
    slider,
  );
  picker.ui = { range, autoSwitch, now, nowIcon, nowName, nowLabel, nowHint, ticks, slider, shown: null };
  syncMenu();
}

function syncMenu() {
  const ui = picker.ui;
  if (!ui) return;
  const current = normalizeChoice(state.reflexion);
  const auto = current === "auto";
  // while Bird chooses, the thumb rests where it was (the middle bird at first): « Auto » off goes back to it
  const shown = auto ? ui.shown || LEVELS[AUTO_REST] : current;
  ui.shown = shown;
  const index = LEVELS.indexOf(shown);
  const key = auto ? "auto" : shown;
  ui.autoSwitch.checked = auto;
  if (ui.range.value !== String(index)) ui.range.value = String(index);
  ui.range.setAttribute("aria-valuetext", auto ? `${t("rf.level.auto")} · ${t("rf.level.auto.hint")}` : valueText(shown));
  ui.slider.style.setProperty("--rf-pos", `${(index / (LEVELS.length - 1)) * 100}%`);
  ui.slider.dataset.level = shown;
  ui.slider.classList.toggle("is-auto", auto);
  ui.now.hidden = auto; // « Auto » is already said by the switch row: the card names a bird only when one is chosen
  ui.now.dataset.level = key;
  ui.nowIcon.dataset.level = key;
  if (ui.nowIcon.dataset.drawn !== key) {
    ui.nowIcon.dataset.drawn = key;
    ui.nowIcon.replaceChildren(birdIcon(key));
  }
  ui.nowName.textContent = auto ? t("rf.level.auto") : nameOf(shown);
  ui.nowLabel.textContent = auto ? "" : ` · ${t(`rf.level.${shown}.label`)}`;
  ui.nowHint.textContent = t(`rf.level.${key}.hint`);
  ui.ticks.forEach((b, i) => b.classList.toggle("is-on", !auto && i === index));
}

/** A choice applies at once and the popover stays open: Escape, Tab past the slider or a click outside closes it. */
function pick(key) {
  const next = normalizeChoice(key);
  if (next !== state.reflexion) picker.onPick(next);
  syncMenu();
}

function onKey(e) {
  if (e.key === "Escape") {
    e.preventDefault();
    close();
  } else if (e.key === "Tab") {
    // two controls: Tab moves between the switch and the slider, leaving them closes (as the menu did)
    const stops = [...picker.menu.querySelectorAll("#rf-auto, #rf-range")];
    const i = stops.indexOf(document.activeElement);
    const j = i + (e.shiftKey ? -1 : 1);
    if (j < 0 || j >= stops.length) close(false);
    else {
      e.preventDefault();
      stops[j].focus();
    }
  }
}

/** Wires the picker into the composer row (``slot``); ``onPick(choice)`` stores the choice and redraws. */
export function mountPicker(slot, onPick) {
  const button = h("button", {
    id: "rf-button",
    class: "rf-pill",
    type: "button",
    "aria-haspopup": "dialog",
    "aria-expanded": "false",
    "aria-controls": "rf-menu",
  });
  const menu = h("div", { id: "rf-menu", class: "rf-menu", role: "dialog", "aria-labelledby": "rf-menu-title", hidden: true });
  const scrim = h("div", { class: "rf-scrim", hidden: true, onclick: () => close(false) });
  menu.addEventListener("keydown", onKey);
  // no focus on press (as the send button): focusing the dock shows it « typing », hides its note and moves it,
  // and the release then landed on the text box (seen at 360 px): the click opened nothing
  button.addEventListener("mousedown", (e) => e.preventDefault());
  button.addEventListener("click", () => (menu.hidden ? open() : close()));
  button.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      open();
    }
  });
  slot.replaceWith(button);
  button.after(scrim, menu);
  picker = { button, menu, scrim, onPick };
  updatePicker();
}

/** The pill shows the bird chosen (its drawing and its name, « Auto » for Bird's own choice). */
export function updatePicker() {
  if (!picker) return;
  const key = normalizeChoice(state.reflexion);
  const name = nameOf(key);
  picker.button.dataset.level = key;
  picker.button.setAttribute("aria-label", t("rf.button", { name }));
  picker.button.title = t(`rf.level.${key}.hint`);
  // the children are rebuilt only when the bird or the language changes: a redraw between pointerdown and pointerup
  // would remove the pressed drawing and the browser would drop the click
  const sig = `${key}|${state.prefs.lang}`;
  if (picker.sig !== sig) {
    picker.sig = sig;
    picker.button.replaceChildren(
    birdIcon(key),
    h("span", { class: "rf-pill-name", text: name }),
    h("span", { class: "rf-pill-caret", "aria-hidden": "true" }, icon("chevron")),
    );
  }
  // an open menu is redrawn only when its language changed: the composer redraws often, and a menu rebuilt under
  // the pointer or the focus would lose the click and the arrow keys
  if (!picker.menu.hidden) picker.lang !== state.prefs.lang ? renderMenu() : syncMenu();
}

// ------------------------------------------------------------------ in the conversation

const arrived = new Set(); // the arrival flight plays once per answer, never at each redraw

/** The live line's bird while Bird reasons: the level the server announced (event « reflexion »), flapping. */
export function flyingBird(turn) {
  const key = turn.flight?.level;
  return LEVELS.includes(key) ? birdIcon(key, "rf-flap") : null;
}

export function flyingText(turn) {
  const key = turn.flight?.level;
  return LEVELS.includes(key) ? t("rf.flying", { bird: asOf(key) }) : "";
}

/**
 * The answer's flight header: « Bird a pris son vol en Faucon · Précis · choisi par Bird », opened on the
 * reasoning summary, the checks and the full reasoning. Null when the server sent no ``reflexion`` field.
 */
export function renderFlight(turn, detailsFn, fullReasoning) {
  const rf = turn.answer?.reflexion;
  if (!rf || !LEVELS.includes(rf.level)) return null;
  const facts = flightFacts(rf);
  const summary = Array.isArray(rf.summary) ? rf.summary.filter((s) => typeof s === "string" && s) : [];
  const first = !arrived.has(turn.id);
  arrived.add(turn.id);
  const meta = flightMetaKeys(rf).map((k) => t(k)).join(" · ");
  const body = h(
    "div",
    { class: "rf-body" },
    summary.length > 0 && [
      h("p", { class: "rf-h", text: t("rf.summary") }),
      h("ul", { class: "rf-sum" }, summary.map((s) => h("li", { text: s }))),
    ],
    facts.length > 0 && [
      h("p", { class: "rf-h", text: t("rf.checks") }),
      h(
        "ul",
        { class: "rf-facts" },
        facts.map((f) =>
          h(
            "li",
            { "data-kind": f.kind },
            icon(f.kind === "ok" || f.kind === "fixed" ? "check" : f.kind === "warn" ? "alert" : "info"),
            h("span", { text: t(f.key, f.vars) }),
          ),
        ),
      ),
    ],
    fullReasoning,
  );
  const el = detailsFn(
    `rf-flight${first ? " rf-arrive" : ""}`,
    turn.ui.flight ?? false,
    (value) => (turn.ui.flight = value),
    [
      h("span", { class: "rf-badge", "data-level": rf.level }, birdIcon(rf.level)),
      h(
        "span",
        { class: "rf-sumtext" },
        h("span", { class: "rf-line", text: t("rf.flight", { bird: asOf(rf.level) }) }),
        h("span", { class: "rf-meta", text: meta }),
      ),
      icon("chevron", "chev"),
    ],
    body,
  );
  el.dataset.level = rf.level;
  return el;
}

export function flightText(rf) {
  return rf && LEVELS.includes(rf.level) ? t("rf.flight", { bird: asOf(rf.level) }) : "";
}
