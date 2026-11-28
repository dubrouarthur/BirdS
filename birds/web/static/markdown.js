// Small, safe Markdown renderer for model output.
// Rule: every character coming from the model is HTML-escaped BEFORE any tag is produced.
// The only tags in the output are the ones written literally in this file (and in richcode.js).
//
// With options.rich, conservative detectors turn the small model's own conventions into richer blocks
// (pseudo-headings, callouts, label/value rows, step lists, key numbers, pros/cons). A detector never drops,
// reorders or invents text: a missed detection falls back to the plain rendering.

import { ICON, highlight, langInfo, sniff } from "./richcode.js";

const ESC = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ESC[c]);
}

/** Returns a normalised http(s) URL, or null for anything else (javascript:, data:, relative...). */
export function safeUrl(raw) {
  const text = String(raw).trim();
  if (!/^https?:\/\/[^\s<>"'`\\]+$/i.test(text)) return null;
  try {
    const url = new URL(text);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.href
      : null;
  } catch {
    return null;
  }
}

const unescapeHtml = (s) =>
  s.replace(
    /&(amp|lt|gt|quot|#39);/g,
    (m) =>
      ({ "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" })[
        m
      ],
  );

function linkHtml(href, labelHtml, title = "") {
  const tip = title ? ` title="${escapeHtml(title)}"` : "";
  return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer"${tip}>${labelHtml}</a>`;
}

/** A long bare URL shows its host and path, ellipsed; the full address stays in the link and its title. */
function shortUrl(href) {
  if (href.length <= 48) return null;
  try {
    const u = new URL(href);
    const text = (u.host + u.pathname).replace(/\/$/, "");
    return text.length > 42 ? `${text.slice(0, 40)}…` : text;
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ typography (outside code and links only)

const LETTER = "A-Za-zÀ-ÖØ-öø-ÿŒœ";
const RE_APOS = new RegExp(`([${LETTER}])&#39;(?=[${LETTER}])`, "g");

function typography(text, fr) {
  // works on escaped text; \u0000n\u0000 placeholders (code, links) are left alone
  return text
    .split(/(\u0000\d+\u0000)/)
    .map((seg, k) => {
      if (k % 2) return seg;
      let s = seg
        .replace(RE_APOS, "$1’")
        .replace(/(^|[^.])\.\.\.(?!\.)/g, "$1…")
        .replace(/(\S) - (?=\S)/g, "$1 – ");
      if (!fr) return s;
      s = s
        .replace(/ :(?![\w/])/g, " :")
        .replace(/ ([;!?])(?![\w/])/g, " $1")
        .replace(/« /g, "« ")
        .replace(/ »/g, " »")
        .replace(
          /\b(\d{1,3})((?: \d{3})+)(?![\d,.]?\d)/g,
          (m, a, b) => a + b.replace(/ /g, " "),
        )
        .replace(/(\d) (%|€|k€|M€|Md€|°C)(?![\w])/g, "$1 $2")
        .replace(
          /\b(\d{1,3})(er|re|e|ème)\b(?![-\d])/g,
          '$1<sup class="md-ord">$2</sup>',
        );
      return s;
    })
    .join("");
}

// ------------------------------------------------------------------ inline

const RE_FILE_NAME =
  /^[\w-][\w.-]{0,60}\.(?:py|js|mjs|ts|tsx|json|sh|csv|xlsx|xls|docx|doc|pptx|pdf|txt|md|html|css|sql|ya?ml|xml|zip|gz|png|jpe?g|svg|ini|toml|env|log)$/i;
const RE_EXCEL = /^=\s*[A-Za-z$('"]/;
const RE_FORMULA = /^[^=`]{1,48}=[^=].*[-+*/×÷]/;

/**
 * A display formula only breaks after a top-level operator ("BFR =" / "(stocks + clients) -" / "(…)"): the pieces
 * are kept whole and joined by the original spaces, so the copied text is the formula as written.
 */
function formulaSegments(code) {
  const out = [];
  let depth = 0;
  let from = 0;
  for (let k = 0; k < code.length; k++) {
    const c = code[k];
    if ("([{".includes(c)) depth++;
    else if (")]}".includes(c)) depth = Math.max(0, depth - 1);
    else if (!depth && "=+-*/×÷".includes(c) && code[k - 1] === " " && code[k + 1] === " ") {
      out.push(code.slice(from, k + 1));
      from = k + 2;
      k++;
    }
  }
  out.push(code.slice(from));
  return out.filter(Boolean);
}

function codeSpan(code, ctx, mode) {
  if (ctx.rich && RE_EXCEL.test(code) && code.length <= 200) {
    const label = escapeHtml(ctx.labels.copyFormula);
    return (
      `<span class="md-chip"><code class="md-chip-code">${highlight(code, "excel").join(" ")}</code>` +
      `<button type="button" class="md-chip-copy" data-copy-inline data-done="${escapeHtml(ctx.labels.copied)}" aria-label="${label}" title="${label}">${ICON.copy}</button></span>`
    );
  }
  if (ctx.rich && mode.formula && RE_FORMULA.test(code))
    return `<span class="md-formula"><code>${formulaSegments(code).map((g) => `<span class="md-fseg">${escapeHtml(g)}</span>`).join(" ")}</code></span>`;
  if (ctx.rich && RE_FILE_NAME.test(code))
    return `<code class="md-file">${escapeHtml(code)}</code>`;
  return `<code${code.length > 60 ? ' class="md-long"' : ""}>${escapeHtml(code)}</code>`;
}

// ------------------------------------------------------------------ math (typeset by answers.js with KaTeX)

// \(…\) inline; \[…\] and $$…$$ display; $…$ inline when TeX is inside (checked by the caller). One line each.
const RE_MATH_INLINE =
  /\\\((.+?)\\\)|\\\[(.+?)\\\]|\$\$(.+?)\$\$|(?<![\w$\\])\$([^\s$](?:[^$\n]{0,198}?[^\s$\\])?)\$(?![\w$])/g;
const RE_MATH_OPEN = /^\s{0,3}(\\\[|\$\$)\s*(.*)$/;

/**
 * A formula placeholder: its TeX in data-tex, its source as written (with delimiters) shown until answers.js
 * typesets it, and kept for copying. Display formulas get a « copy the TeX » button.
 */
function mathHtml(tex, display, raw, ctx, pending = false) {
  const src = `<span class="md-math-src">${escapeHtml(raw)}</span>`;
  const attrs = `data-tex="${escapeHtml(String(tex).trim())}"${display ? " data-display" : ""}${pending ? " data-pending" : ""}`;
  if (!display || !ctx.block) return `<span class="md-math${display ? " md-math--display" : ""}" ${attrs}>${src}</span>`;
  const label = escapeHtml(ctx.labels.copyTex);
  return (
    `<div class="md-math md-math--block" ${attrs}>${src}` +
    `<button type="button" class="md-math-copy" data-copy-tex aria-label="${label}" title="${label}"${pending ? " disabled" : ""}>${ICON.copy}</button></div>`
  );
}

/** A display formula on its own lines (\[ … \] or $$ … $$): {html, next} or null (then it is ordinary text). */
function mathBlock(lines, i, ctx) {
  const open = lines[i].match(RE_MATH_OPEN);
  if (!open) return null;
  const close = open[1] === "$$" ? "$$" : "\\]";
  const body = [];
  let rest = open[2];
  for (let j = i; j < lines.length && j - i < 80; j += 1) {
    if (j > i) rest = lines[j];
    const k = rest.indexOf(close);
    if (k >= 0) {
      body.push(rest.slice(0, k));
      if (rest.slice(k + close.length).trim()) return null; // text after the formula: the paragraph handles it
      const tex = body.join("\n");
      if (!tex.trim()) return null;
      const raw = lines.slice(i, j + 1).join("\n").trim();
      return { html: mathHtml(tex, true, raw, { ...ctx, block: true }), next: j + 1 };
    }
    body.push(rest);
  }
  // still streaming: the formula shows as written, typeset once it closes; a final answer without the closing
  // delimiter is plain text
  if (ctx.final || lines.length - i > 80) return null;
  const raw = lines.slice(i).join("\n").trim();
  return { html: mathHtml(body.join("\n"), true, raw, { ...ctx, block: true }, true), next: lines.length };
}

function inline(raw, ctx, mode = {}) {
  const stash = [];
  const keep = (html) => `\u0000${stash.push(html) - 1}\u0000`;

  let text = String(raw).replace(/`([^`\n]+)`/g, (_, code) =>
    keep(codeSpan(code, ctx, mode)),
  );
  if (ctx.rich) text = text.replace(RE_MATH_INLINE, (whole, a, b, c, d) => {
    const tex = a ?? b ?? c ?? d;
    // a lone $…$ is math only with TeX inside (x^2, \alpha, a_{n}, a single letter): « 5 $ et 10 $ » stays text
    if (d !== undefined && !/[\\^_{}]|^[A-Za-z]$/.test(d)) return whole;
    return keep(mathHtml(tex, a === undefined && d === undefined, whole, ctx));
  });
  text = escapeHtml(text);
  // a formula shown on its own line takes the punctuation that follows it, so no line starts with "."
  text = text.replace(/\u0000(\d+)\u0000([.,;])(?=\s|$)/g, (whole, k, p) => {
    const html = stash[Number(k)];
    if (!html.startsWith('<span class="md-formula">')) return whole;
    stash[Number(k)] = html.replace(/<\/span>$/, `<span class="md-formula-p">${p}</span></span>`);
    return `\u0000${k}\u0000`;
  });

  // [label](url): only http(s) becomes a link; anything else stays visible, inert text.
  text = text.replace(
    /\[([^\]\n]+)\]\(([^()\s]+)\)/g,
    (whole, label, target) => {
      const href = safeUrl(unescapeHtml(target));
      return href ? keep(linkHtml(href, label)) : whole;
    },
  );
  // Bare URLs.
  text = text.replace(
    /(^|[\s(])(https?:\/\/[^\s<>\u0000]+)/g,
    (whole, lead, target) => {
      let url = target;
      let tail = "";
      const trimmed = url.match(/(?:[.,;:!?)\]]|&#39;|&quot;)+$/);
      if (trimmed) {
        tail = trimmed[0];
        url = url.slice(0, -tail.length);
      }
      const href = safeUrl(unescapeHtml(url));
      if (!href) return whole;
      const short = ctx.rich ? shortUrl(href) : null;
      return (
        lead +
        keep(
          short ? linkHtml(href, escapeHtml(short), href) : linkHtml(href, url),
        ) +
        tail
      );
    },
  );

  if (ctx.lang) text = typography(text, ctx.lang === "fr");

  text = text
    .replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^\w*])\*([^*\s][^*\n]*?)\*(?![\w*])/g, "$1<em>$2</em>")
    .replace(/(^|[^\w_])__([^_\n]+?)__(?![\w_])/g, "$1<strong>$2</strong>")
    .replace(/(^|[^\w_])_([^_\s][^_\n]*?)_(?![\w_])/g, "$1<em>$2</em>");

  // Citations [n] -> link to the matching entry of the sources list.
  text = text.replace(/\[(\d{1,2})\]/g, (whole, n) => {
    if (!ctx.cites.has(Number(n))) return whole;
    const label = escapeHtml(ctx.citeLabel.replace("{n}", n));
    return `<sup class="cite"><a href="#${ctx.anchor}-${n}" aria-label="${label}">${n}</a></sup>`;
  });

  text = text.replace(/\u0001/g, "<br>"); // hard line break inside a list item
  return text.replace(/\u0000(\d+)\u0000/g, (_, i) => stash[Number(i)] ?? "");
}

// ------------------------------------------------------------------ block grammar

const RE_FENCE = /^\s{0,3}(```|~~~)\s*([\w+-]*)\s*$/;
const RE_HEADING = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/;
const RE_HR = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const RE_ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const RE_QUOTE = /^\s{0,3}>\s?(.*)$/;
const RE_TABLE_SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
const RE_FILE_LINE =
  /^(?:\*\*)?(?:Fichier|Script|File|Nom du fichier|Filename)(?:\*\*)?\s*:\s*(?:\*\*)?`?([\w.-]{1,64}\.\w{1,6})`?(?:\*\*)?\s*$/i;

/**
 * Split a table row into cells with a small scanner. "\\|" is a literal pipe, and a pipe inside a code span
 * (matching backtick runs) does not split. Deliberate deviation from GFM, which splits on a bare pipe even
 * inside a code span: a model writing `a|b` in a cell means one cell, and losing half of it reads as a bug.
 */
function splitRow(line) {
  const text = line.trim();
  const cells = [];
  let cell = "";
  let fence = 0; // length of the backtick run that opened the current code span, 0 outside one
  let endsWithPipe = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    endsWithPipe = false;
    if (c === "\\" && text[i + 1] === "|") {
      cell += "|";
      i++;
    } else if (c === "`") {
      let run = 1;
      while (text[i + run] === "`") run++;
      const ticks = "`".repeat(run);
      if (!fence) {
        // opens a span only if the same run closes it later on this line
        const close = text.indexOf(ticks, i + run);
        if (close >= 0 && text[close + run] !== "`") fence = run;
      } else if (run === fence) fence = 0;
      cell += ticks;
      i += run - 1;
    } else if (c === "|" && !fence) {
      cells.push(cell);
      cell = "";
      endsWithPipe = true;
    } else cell += c;
  }
  if (!endsWithPipe) cells.push(cell);
  if (text.startsWith("|")) cells.shift();
  return cells.map((x) => x.trim());
}

function isTableStart(lines, i) {
  return (
    lines[i].includes("|") &&
    i + 1 < lines.length &&
    lines[i + 1].includes("-") &&
    RE_TABLE_SEP.test(lines[i + 1]) &&
    lines[i + 1].includes("|")
  );
}

const norm = (s) =>
  String(s)
    .replace(/[*_`#]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .toLowerCase();

// ------------------------------------------------------------------ detectors (rich mode)

// Letter and email openings and closings: never a heading, and they put the answer in "letter mode" (no callouts)
const RE_SALUTE =
  /^(?:bonjour|bonsoir|madame|monsieur|mesdames|messieurs|mademoiselle|cher|chère|chers|chères|cordialement|bien cordialement|bien à vous|salutations|sincères salutations|meilleures salutations|respectueusement|bonne journée|hello|hi|dear|regards|best regards|kind regards|sincerely)(?=$|[\s,.!])/iu;

/** A short bare line (or a bold-only line) that introduces a list, a table or code: the text of a heading, or null. */
function pseudoHeading(raw) {
  let text = raw.trim();
  if (RE_SALUTE.test(text.replace(/^\*\*/, ""))) return null;
  const bold = text.match(/^\*\*([^*\n]+)\*\*\s*:?$/);
  if (bold) text = bold[1].trim();
  else if (/[`[\]*_]|https?:/.test(text)) return null;
  const colon = /\s*:$/.test(text);
  text = text.replace(/\s*:$/, "").trim();
  if (!text || text.length > 60 || /[.,;!?:]$/.test(text)) return null;
  if (/^(?:[-*+>]\s|\d+[.)](\s|$)|#)/.test(text)) return null;
  if (
    /^(voici|voilà|here is|here are|ci-dessous|below|par exemple|for example)\b/i.test(
      text,
    )
  )
    return null;
  if (colon && !bold && text.split(/\s+/).length > 4) return null; // "Voilà ce que je propose de faire :" is prose
  return text;
}

/** The first line of a multi-line paragraph is a title when it is short and bare and the rest is real prose. */
function leadHeading(para) {
  const first = para[0].trim();
  const rest = para.slice(1).join(" ").trim();
  if (first.length > 40 || first.split(/\s+/).length > 5 || /[:,]/.test(first) || !/^\p{Lu}/u.test(first)) return null;
  if (rest.length < 60 || !/[.!?…)]$/.test(rest)) return null;
  return pseudoHeading(first);
}

const CALLOUTS = [
  [
    "warn",
    /^(attention|avertissement|prudence|mise en garde|warning|caution)$/i,
  ],
  ["important", /^(important)$/i],
  ["note", /^(note|remarque|nb|n\.b\.|à noter)$/i],
  ["tip", /^(conseil|astuce|tip|bon à savoir)$/i],
  ["key", /^(à retenir|en résumé|en bref|key takeaway|in short|to remember)$/i],
  ["decision", /^(décisions?|decisions?)$/i],
];
const RE_CALLOUT_HEAD =
  /^(\*\*)?([\p{L}. ]{2,20}?)(\s*[:,!])?(\*\*)?(\s*[:,!])?(?=\s|$)/u;

// "Attention, nous avons le regret de…" opens a letter's sentence, not a warning
const RE_LETTER_TURN = /^[\s,!]*(?:nous|je|j['’]|on)\b|regrett?/i;
// a closing offer of help never belongs inside a callout: it moves out as its own paragraph
const RE_OFFER =
  /(?<=[.!?…]\s+|^)(?=(?:je peux|je reste|souhaitez-vous|voulez-vous|n['’]hésitez pas|si vous (?:le )?souhaitez|dites-moi|i can|let me know|feel free)\b)/iu;

/** [kind, keyword, rest] when a paragraph opens with a callout keyword followed by ":" "," or "!". */
function calloutHead(text, ctx) {
  if (ctx.letter) return null; // a drafted letter or email is shown as written
  const m = text.match(RE_CALLOUT_HEAD);
  if (!m || !(m[3] || m[5]) || Boolean(m[1]) !== Boolean(m[4])) return null;
  const word = m[2].trim();
  const sep = (m[3] || m[5]).trim();
  for (const [kind, re] of CALLOUTS) {
    if (!re.test(word)) continue;
    if (sep !== ":" && kind !== "warn") return null; // "Note, …" is a sentence; "Attention, …" is a warning
    if (sep !== ":" && RE_LETTER_TURN.test(text.slice(m[0].length))) return null;
    return [
      kind,
      word,
      (m[3] || "") + (m[5] || "") + text.slice(m[0].length), // the separator stays: the text reads the same
    ];
  }
  return null;
}

const CALLOUT_ICON = {
  warn: "alert",
  important: "star",
  note: "info",
  tip: "bulb",
  key: "star",
  decision: "check",
  caution: "alert",
};

function callout(kind, inner) {
  return `<div class="md-callout md-callout--${kind}" role="note"><span class="md-callout-ico">${ICON[CALLOUT_ICON[kind]]}</span><div class="md-callout-body">${inner}</div></div>`;
}

const RE_PAIR = /^(?:\*\*)?([\p{L}][\p{L}'’ -]{0,31}?)(?:\*\*)?\s*:\s+(\S.*)$/u;
function pairs(lines) {
  if (lines.length < 2) return null;
  const out = [];
  for (const line of lines) {
    const m = line.trim().match(RE_PAIR);
    if (!m || m[1].trim().split(/\s+/).length > 4 || m[2].length > 220)
      return null;
    out.push([m[1].trim(), m[2]]);
  }
  // a dialogue or a transcript ("Client : …" / "Moi : …") is not a set of fields: labels repeat, values are utterances
  if (new Set(out.map(([k]) => norm(k))).size < out.length) return null;
  if (out.some(([, v]) => /[?!]\s*["»”]?$/.test(v.trim()))) return null;
  return out;
}

const FIGURE =
  /^(?:\*\*)?([^:*\n`]{2,40}?)(?:\*\*)?\s*:\s*((?:[-+−]\s?)?\d[\d   .,]*(?:\s?(?:%|€|k€|M€|Md€|\$|h|j|jours|ans|pts?|points?|clients|°C))?)(?:\s+(\S.{0,23}))?$/;
const figureOf = (text) => {
  const m = text.trim().match(FIGURE);
  return m
    ? { label: m[1].trim(), value: m[2].trim(), tail: m[3] || "" }
    : null;
};

const RE_MONTH =
  /^(?:janv|févr|fevr|mars|avr|mai|juin|juil|août|aout|sept|oct|nov|déc|dec|jan|feb|mar|apr|may|jun|jul|aug|sep)/i;
const RE_PHONE = /^(?:0\d(?:[\s.\u00a0\u202f]?\d{2}){4}|\+\d{2,3}(?:[\s.\u00a0\u202f]?\d{1,2}){4,5})$/;
const RE_UNIT = /(?:%|€|k€|M€|Md€|\$|h|j|jours|ans|pts?|points?|clients|°C)$/;
const bigNumber = (v) => Number(v.replace(/[^\d,.]/g, "").replace(/[.,](?=\d{3}(?:\D|$))/g, "").replace(",", ".")) >= 1000;
/** A figure that is a date ("15 mars 2025"), a phone number or a bare year is not a key number. */
const isMetric = (f) =>
  !RE_MONTH.test(f.tail) &&
  !RE_PHONE.test(f.value.trim()) &&
  !(/^(?:19|20)\d{2}$/.test(f.value.trim()) && !f.tail);

// "Avantages", "Avantages courants", "Points forts du leasing": the keyword opens a label of at most 5 words.
// "Pour" and "Contre" count only alone ("Pour vos salariés" is not a list of pros), and "Risques" pairs only with
// a clear "Avantages" / "Points forts" label.
const PROS =
  /^(?:(?:avantages?|points? forts?|atouts?|pros|advantages?|benefits?|strengths?)(\s\S+){0,4}|pour)$/i;
const CONS =
  /^(?:(?:inconvénients?|points? faibles?|limites?|cons|disadvantages?|drawbacks?|weaknesses?)(\s\S+){0,4}|contre)$/i;
const RISKS = /^(?:risques?|risks?)(\s\S+){0,4}$/i;
const CLEAR_PROS = /^(?:avantages?|points? forts?|advantages?|strengths?)\b/i;
const isProsCons = (pro, con) =>
  PROS.test(pro) && (CONS.test(con) || (RISKS.test(con) && CLEAR_PROS.test(pro)));

// ------------------------------------------------------------------ lists

/** Nodes {item, children} by indentation: an item deeper than its predecessor + 1 nests under it. */
function listTree(items) {
  const root = { children: [] };
  const stack = [root];
  for (const item of items) {
    const node = { item, children: [] };
    while (
      stack.length > 1 &&
      item.indent <= stack[stack.length - 1].item.indent + 1
    )
      stack.pop();
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  }
  return root.children;
}

const RE_KEYED = /^([\p{L}][\p{L}\p{N}'’.& -]{0,39}?) : (?=\S)/u;
const RE_BOLD_LEAD = /^\*\*([^*\n]{1,80})\*\*\s*(?::\s*)?/;

function itemHtml(node, ctx, keyed) {
  const text = node.item.text;
  const k = keyed && text.match(RE_KEYED);
  if (k && k[1].trim().split(/\s+/).length <= 5)
    return `<span class="md-li-k">${inline(k[1], ctx)}</span>${inline(text.slice(k[1].length), ctx)}`;
  return inline(text, ctx);
}

/**
 * "1. **Prix** :" over a nested list: a section label, not a step. Short noun label (one to four words, no final
 * period, not an instruction such as "Ouvrez…" or "Créer un compte"): the label text, or null.
 */
function sectionLabel(text) {
  const t = text.trim();
  const m = t.match(/^\*\*([^*\n]+)\*\*\s*:?$/) || t.match(/^([^*`[\]\n]+?)\s*:?$/);
  if (!m) return null;
  const label = m[1].replace(/\s*:$/, "").trim();
  const words = label.split(/\s+/);
  if (!label || words.length > 4 || label.length > 40 || /[.,;!?]$/.test(label)) return null;
  const w0 = words[0].toLowerCase();
  if (/ez$/.test(w0) || (words.length > 1 && /(?:er|ir|re|oir)$/.test(w0) && !/^(?:premier|dernier)$/.test(w0)))
    return null; // "Ouvrez le fichier", "Créer un compte": an instruction
  return label;
}

function sectionsHtml(run, first, ctx, level, grow) {
  const secs = run.map((node, k) => {
    const n = `<span class="md-ph-n">${first + k}.</span> `;
    const label = sectionLabel(node.item.text) ?? node.item.text; // the item still being written
    const kids = listHtml(node.children, ctx, level + 1, { growing: grow && k === run.length - 1 });
    return `<section class="md-sec"><h4 class="md-ph">${n}${inline(label, ctx)}</h4>${kids}</section>`;
  });
  return `<div class="md-sections">${secs.join("")}</div>`;
}

function listHtml(nodes, ctx, level, opts = {}) {
  let html = "";
  let start = 0;
  while (start < nodes.length) {
    // a bullet list followed by a numbered one (or the reverse) is two lists
    let end = start + 1;
    while (
      end < nodes.length &&
      nodes[end].item.ordered === nodes[start].item.ordered
    )
      end++;
    const run = nodes.slice(start, end);
    start = end;
    const ordered = run[0].item.ordered;
    const first = run[0].item.start;
    // Still streaming: the last item is still being written, so the layout is decided from the finished items
    // only, and the finer touches (keyed labels, airy spacing) wait until the list is complete. A class never
    // flips back and forth while the reader watches.
    const grow = Boolean(opts.growing) && start >= nodes.length;
    const done = grow ? run.slice(0, -1) : run;
    const texts = done.map((n) => n.item.text);
    const avg = texts.reduce((a, t) => a + t.length, 0) / Math.max(texts.length, 1);
    // numbered labels over nested lists ("1. Prix" / "2. Intégrations"): sections with the in-answer heading style
    if (
      ctx.rich &&
      ordered &&
      level === 0 &&
      done.length >= 2 &&
      done.every((n) => n.children.length && sectionLabel(n.item.text))
    ) {
      html += sectionsHtml(run, first, ctx, level, grow);
      continue;
    }
    const keyed =
      ctx.rich &&
      !grow &&
      run.length >= 2 &&
      texts.filter((t) => RE_KEYED.test(t) && !RE_BOLD_LEAD.test(t)).length >=
        Math.ceil(run.length * 0.8);
    const steps =
      ctx.rich &&
      ordered &&
      level === 0 &&
      done.length >= 3 &&
      (texts.filter((t) => RE_BOLD_LEAD.test(t)).length >= 2 || (!grow && avg > 50));
    const airy = ctx.rich && !grow && !steps && avg > 120; // a step list has its own rhythm
    const fold = opts.fold && level === 0 && run.length > 12;
    const cls = [steps && "md-steps", airy && "md-airy", keyed && "md-keyed"]
      .filter(Boolean)
      .join(" ");
    const tag = ordered ? "ol" : "ul";
    let list = `<${tag}${ordered && first !== 1 ? ` start="${first}"` : ""}${cls ? ` class="${cls}"` : ""}>`;
    run.forEach((node, k) => {
      const kids = node.children.length
        ? listHtml(node.children, ctx, level + 1, { growing: grow && k === run.length - 1 })
        : "";
      const hidden = fold && k >= 8 ? " hidden" : "";
      if (steps) {
        const b = node.item.text.match(RE_BOLD_LEAD);
        const title = b
          ? `<span class="md-step-t">${inline(b[1], ctx)}</span>`
          : "";
        const rest = b ? node.item.text.slice(b[0].length) : node.item.text;
        const body = rest.trim()
          ? `<span class="md-step-b">${inline(rest, ctx)}</span>`
          : "";
        list += `<li${hidden}><span class="md-step-n" aria-hidden="true">${first + k}</span><div class="md-step-c">${title}${body}${kids}</div></li>`;
      } else list += `<li${hidden}>${itemHtml(node, ctx, keyed)}${kids}</li>`;
    });
    list += `</${tag}>`;
    if (fold) {
      const more = escapeHtml(
        ctx.labels.listMore.replace("{n}", String(run.length - 8)),
      );
      list = `<div class="md-fold">${list}<button type="button" class="md-more" data-md-more>${ICON.chevron}<span>${more}</span></button></div>`;
    }
    html += list;
  }
  return html;
}

/** Key numbers: 3 to 6 "label : figure" items and nothing else (optionally under one caption item). */
function keyNumbers(nodes, ctx) {
  let caption = null;
  let leaves = nodes;
  if (nodes.length === 1 && nodes[0].children.length) {
    caption = nodes[0].item.text;
    leaves = nodes[0].children;
    if (figureOf(caption)) return null;
  }
  if (
    leaves.length < 3 ||
    leaves.length > 6 ||
    leaves.some((n) => n.children.length)
  )
    return null;
  const figs = leaves.map((n) => figureOf(n.item.text));
  if (figs.some((f) => !f || !isMetric(f))) return null;
  // at least one real measure: a unit, or a number in the thousands
  if (!figs.some((f) => RE_UNIT.test(f.value) || bigNumber(f.value))) return null;
  const cap = caption ? `<figcaption>${inline(caption, ctx)}</figcaption>` : "";
  const cells = figs
    .map(
      (f) =>
        `<div class="md-kpi"><dt>${inline(f.label, ctx)}</dt><dd><span class="md-kpi-v">${inline(f.value, ctx)}</span>` +
        `${f.tail ? ` <small>${inline(f.tail, ctx)}</small>` : ""}</dd></div>`,
    )
    .join("");
  return `<figure class="md-kpis">${cap}<dl>${cells}</dl></figure>`;
}

// ------------------------------------------------------------------ tables

const RE_NUM_CELL =
  /^(?:[-+−]\s?)?(?:\d[\d   .,]*\d|\d)\s?(?:%|€|k€|M€|Md€|\$|£|h|j|ms|s|pts?|x)?$|^\d{1,2}\/\d{1,2}\/\d{2,4}$|^\d{4}-\d{2}-\d{2}$/;
const RE_BEST =
  /[✅✓★]|\((?:meilleur|recommandé|recommandée|best|recommended)\)/i;
const plainCell = (c) => c.replace(/\*\*|__|`/g, "").trim();

function tableHtml(head, align, rows, ctx, growing = false) {
  const ncol = head.length;
  // numeric alignment is decided once the table is complete, so a column does not flip while rows arrive
  const num = head.map((_, k) => {
    if (growing) return false;
    const vals = rows.map((r) => plainCell(r[k] ?? "")).filter(Boolean);
    return (
      ctx.rich &&
      vals.length > 0 &&
      vals.filter((v) => RE_NUM_CELL.test(v)).length >=
        Math.ceil(vals.length * 0.8)
    );
  });
  const bestCol = head.map(
    (h) => ctx.rich && (/^\*\*[^*]+\*\*$/.test(h.trim()) || RE_BEST.test(h)),
  );
  const allBold = head.map(
    (_, k) =>
      rows.length > 1 &&
      rows.every((r) => /^\*\*[^*]+\*\*$/.test((r[k] ?? "").trim())),
  );
  const cls = (k, cell) => {
    const c = [];
    if (align[k]) c.push(`al-${align[k]}`);
    else if (num[k] && k > 0) c.push("md-num");
    if (bestCol[k]) c.push("md-best");
    else if (
      cell !== undefined &&
      ctx.rich &&
      ((k > 0 && !allBold[k] && /^\*\*[^*]+\*\*$/.test(cell.trim())) ||
        RE_BEST.test(cell))
    )
      c.push("md-best");
    return c.length ? ` class="${c.join(" ")}"` : "";
  };
  const tcls = ctx.rich
    ? ` class="md-table${ncol > 3 ? " md-table--wide" : ""}"`
    : "";
  let html = `<div class="table-wrap" tabindex="0"><table${tcls}><thead><tr>`;
  head.forEach(
    (cell, k) => (html += `<th scope="col"${cls(k)}>${inline(cell, ctx)}</th>`),
  );
  html += "</tr></thead><tbody>";
  for (const cells of rows) {
    html += "<tr>";
    head.forEach(
      (_, k) =>
        (html += `<td${cls(k, cells[k] ?? "")}>${inline(cells[k] ?? "", ctx)}</td>`),
    );
    html += "</tr>";
  }
  return html + "</tbody></table></div>";
}

// ------------------------------------------------------------------ code blocks

function jsonCheck(code) {
  try {
    JSON.parse(code);
    return { kind: "ok" };
  } catch (err) {
    if (/\/\/|\/\*|\.\.\.|…/.test(code)) return { kind: "excerpt" };
    const msg = String(err?.message || "");
    let line = Number((msg.match(/line (\d+)/) || [])[1] || 0);
    const pos = msg.match(/position (\d+)/);
    if (!line && pos) line = code.slice(0, Number(pos[1])).split("\n").length;
    return { kind: "error", line: line || 1, msg: msg.slice(0, 120) };
  }
}

function codeBlock(code, name, closed, ctx) {
  const L = ctx.labels;
  const index = ctx.fence++;
  const given = langInfo(name);
  const lines = code.split("\n");
  const n = lines.length;
  // an unlabelled fence the server read as Python or JSON (tidy.code_checks, "sniffed"): its verdict and its label
  const guessed =
    !name && closed && ctx.final
      ? ctx.checks.find(
          (c) =>
            c &&
            c.sniffed &&
            c.i === index &&
            c.n === n &&
            (c.lang === "python" || c.lang === "json"),
        ) || null
      : null;
  const key =
    given.key || (name || !closed ? null : guessed ? guessed.lang : sniff(code));
  const info = key ? langInfo(key) : given;
  const label = escapeHtml(info.label || name || L.text);
  const file = ctx.file;
  ctx.file = null;
  let check = guessed ? { ...guessed, json: guessed.lang === "json" } : null;
  if (ctx.final && closed && name) {
    if (info.key === "json") check = { ...jsonCheck(code), json: true };
    else if (info.key === "python")
      check =
        ctx.checks.find(
          (c) => c && c.i === index && c.n === n && c.lang === "python",
        ) || null;
  }
  const title = escapeHtml(L.checkTitle);
  let badge = "";
  if (check?.kind === "ok")
    badge = `<span class="code-check code-check--ok" title="${title}">${ICON.check}<span>${escapeHtml(check.json ? L.checkJson : L.checkOk)}</span></span>`;
  else if (check?.kind === "excerpt")
    badge = `<span class="code-check code-check--excerpt" title="${title}">${escapeHtml(L.checkExcerpt)}</span>`;
  else if (check?.kind === "error") {
    const tip = escapeHtml(`${L.checkTitle} ${String(check.msg || "")}`.trim());
    badge = `<span class="code-check code-check--err" title="${tip}">${ICON.alert}<span>${escapeHtml(L.checkErr.replace("{line}", String(check.line || 1)))}</span></span>`;
  }
  const errLine = check?.kind === "error" ? Number(check.line) : 0;
  const copyLabel = escapeHtml(
    ctx.copyCode
      .replace("{lang}", info.label || name || "")
      .replace(/\s+/g, " ")
      .trim(),
  );
  // The head has its tools from the first streamed line (wrap and download wait, disabled, for the closing fence),
  // so nothing moves in the head when the block completes.
  const off = closed ? "" : " disabled";
  const tools = [];
  if (!closed || n > 1)
    tools.push(
      `<button type="button" class="code-btn code-btn--icon" data-code-wrap aria-pressed="${ctx.wrap}" title="${escapeHtml(L.wrap)}"${off}>${ICON.wrap}<span class="sr-only">${escapeHtml(L.wrap)}</span></button>`,
    );
  if (
    !closed ||
    n >= 3 ||
    (n >= 2 && ["json", "sql", "python"].includes(info.key))
  ) {
    const fname =
      file ||
      (info.key === "excel"
        ? "formule.txt"
        : `bird-${info.key || "code"}.${info.ext}`);
    const dl = escapeHtml(L.downloadLabel.replace("{file}", fname));
    tools.push(
      `<button type="button" class="code-btn" data-code-download data-file="${escapeHtml(fname)}" data-mime="${info.mime}" aria-label="${dl}" title="${dl}"${off}>${ICON.download}<span class="code-btn-t">${escapeHtml(L.download)}</span></button>`,
    );
  }
  tools.push(
    `<button type="button" class="code-copy" data-copy-code aria-label="${copyLabel}">${ICON.copy}<span class="code-btn-t">${escapeHtml(ctx.copyText)}</span></button>`,
  );
  const head =
    `<div class="code-head"><span class="code-lang">${label}</span>` +
    (file ? `<span class="code-file">${escapeHtml(file)}</span>` : "") +
    badge +
    `<span class="code-tools">${tools.join("")}</span></div>`;
  // Line spans and the line-number gutter exist while streaming too (only the colours wait for the closing fence),
  // so the text never shifts when the block completes.
  const painted = closed ? highlight(code, info.key) : lines.map(escapeHtml);
  const body = painted
    .map(
      (l, k) =>
        `<span class="ln${errLine === k + 1 ? " ln--err" : ""}">${l}${k < n - 1 ? "\n" : ""}</span>`,
    )
    .join("");
  const long = n > 12 ? ` data-long${n > 99 ? '="3"' : ""}` : "";
  // A long block is folded only when it arrives whole (final render, history): never under the eyes of a reader
  // who watched it stream or opened it (ctx.expanded holds those blocks' indices).
  const foldable = closed && n > 25;
  const collapse = foldable && ctx.final && !ctx.expanded.has(index);
  const more = escapeHtml(L.more.replace("{n}", String(n)));
  const moreBtn = foldable
    ? `<button type="button" class="code-more" data-code-more aria-expanded="${!collapse}" data-more="${more}" data-less="${escapeHtml(L.less)}">${ICON.chevron}<span class="code-more-t">${collapse ? more : escapeHtml(L.less)}</span></button>`
    : "";
  const lang = escapeHtml(info.key || name || "");
  return (
    `<figure class="code-block${ctx.wrap ? " is-wrapped" : ""}"${lang ? ` data-lang="${lang}"` : ""} data-i="${index}" data-lines="${n}"${long}${collapse ? " data-collapsed" : ""}>` +
    `${head}<pre class="code-pre"><code>${body}</code></pre>${moreBtn}</figure>`
  );
}

// ------------------------------------------------------------------ blocks

function paragraph(para, start, lines, i, ctx, depth) {
  const texts = para.map((l) => l.trim());
  const rich = ctx.rich && depth === 0;
  if (rich && para.length === 1) {
    let j = i;
    while (j < lines.length && !lines[j].trim()) j++;
    const opensBlock =
      j < lines.length &&
      (RE_ITEM.test(lines[j]) ||
        RE_FENCE.test(lines[j]) ||
        isTableStart(lines, j));
    const label =
      (start === 0 || !lines[start - 1].trim()) && opensBlock && indentOf(para[0]) < 2
        ? pseudoHeading(texts[0])
        : null;
    if (label)
      return {
        kind: "heading",
        label,
        html: `<h4 class="md-ph">${inline(label, ctx)}</h4>`,
      };
  }
  if (rich) {
    // still streaming the last paragraph: its lines are not all written, so label/value rows wait for it to end
    const kv = growingAt(lines, i, ctx) ? null : pairs(texts);
    if (kv) {
      const dl = `<dl class="md-pairs">${kv.map(([k, v]) => `<div><dt>${inline(k, ctx)}</dt><dd>${inline(v, ctx)}</dd></div>`).join("")}</dl>`;
      const lead = CALLOUTS.find(
        ([kind, re]) =>
          (kind === "decision" || kind === "key") && re.test(kv[0][0]),
      );
      return { kind: "pairs", html: lead ? callout(lead[0], dl) : dl };
    }
    const head = texts.join(" ").length <= 700 ? calloutHead(texts[0], ctx) : null;
    if (head) {
      const [kind, word, rest] = head;
      // the callout keeps the warning itself; a trailing offer ("Je peux vous aider…") follows as plain text
      let body = [rest, ...texts.slice(1)];
      let tail = [];
      for (let k = 0; k < body.length; k++) {
        const at = body[k].search(RE_OFFER);
        if (at < 0 || (k === 0 && !/\p{L}/u.test(body[0].slice(0, at)))) continue;
        tail = [body[k].slice(at).trim(), ...body.slice(k + 1)];
        body = [...body.slice(0, k), body[k].slice(0, at).trimEnd()].filter((l, j) => j === 0 || l);
        break;
      }
      const first = `<strong class="md-callout-label">${inline(word, ctx)}</strong>${inline(body[0], ctx)}`;
      const more = body.slice(1).map((l) => inline(l, ctx));
      return {
        kind: "callout",
        html: callout(kind, `<p>${[first, ...more].join("<br>")}</p>`),
        after: tail.length
          ? { kind: "p", html: `<p>${tail.map((l) => inline(l, ctx)).join("<br>")}</p>` }
          : null,
      };
    }
  }
  const codes = texts.join("\n").match(/`[^`\n]+`/g) || [];
  const mode = { formula: rich && codes.length === 1 };
  return {
    kind: "p",
    html: `<p>${texts.map((l) => inline(l, ctx, mode)).join("<br>")}</p>`,
  };
}

const RE_ADMONITION = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$/i;
const RE_SOURCE = /^(?:—|--|–)\s*(\S.{0,150})$|^Source\s*:\s*(\S.{0,200})$/i;

function quote(inner, ctx, depth) {
  if (ctx.rich) {
    const first = inner.findIndex((l) => l.trim());
    const adm = first >= 0 && inner[first].trim().match(RE_ADMONITION);
    if (adm) {
      const kind = {
        note: "note",
        tip: "tip",
        important: "important",
        warning: "warn",
        caution: "warn",
      }[adm[1].toLowerCase()];
      const body = blockList(inner.slice(first + 1), ctx, depth + 1)
        .map((b) => b.html)
        .join("");
      const label = `<p class="md-callout-title">${escapeHtml(ctx.labels.callout[kind])}</p>`;
      return callout(kind, label + body);
    }
    let last = inner.length - 1;
    while (last > 0 && !inner[last].trim()) last--;
    const src = last > 0 && inner[last].trim().match(RE_SOURCE);
    if (src) {
      const body = blockList(inner.slice(0, last), ctx, depth + 1)
        .map((b) => b.html)
        .join("");
      return `<figure class="md-quote"><blockquote>${body}</blockquote><figcaption><cite>${inline(src[1] || src[2], ctx)}</cite></figcaption></figure>`;
    }
  }
  return `<blockquote>${blockList(inner, ctx, depth + 1)
    .map((b) => b.html)
    .join("\n")}</blockquote>`;
}

/** While streaming: does the block that ended at line i reach the end of the text (so it is still being written)? */
const growingAt = (lines, i, ctx) => !ctx.final && lines.slice(i).every((l) => !l.trim());

const indentOf = (line) => line.match(/^\s*/)[0].replace(/\t/g, "    ").length;

/** After a blank line inside a list: is the next line an indented paragraph of the last item? */
function continuation(lines, i, items) {
  let j = i;
  while (j < lines.length && !lines[j].trim()) j++;
  if (j >= lines.length) return false;
  const next = lines[j];
  return (
    indentOf(next) >= 2 &&
    indentOf(next) > items[items.length - 1].indent &&
    !RE_ITEM.test(next) &&
    !RE_FENCE.test(next) &&
    !RE_QUOTE.test(next) &&
    !isTableStart(lines, j)
  );
}

function blockList(lines, ctx, depth) {
  const out = [];
  const push = (block) => {
    const prev = out[out.length - 1];
    // the same heading twice in a row (the model restating its title): keep the first
    if (
      block.kind === "heading" &&
      prev?.kind === "heading" &&
      norm(prev.label) === norm(block.label)
    )
      return;
    out.push(block);
    if (block.after) out.push(block.after);
  };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const fence = line.match(RE_FENCE);
    if (fence) {
      const body = [];
      i += 1;
      while (
        i < lines.length &&
        !(RE_FENCE.test(lines[i]) && lines[i].trim().startsWith(fence[1]))
      )
        body.push(lines[i++]);
      const closed = i < lines.length;
      i += 1;
      // A small model sometimes wraps its whole answer in a ```markdown fence: that is formatted text, not code
      // to copy, so it is rendered as Markdown (once: a fence inside it stays a code block).
      if (depth === 0 && /^(markdown|md)$/i.test(fence[2] || "")) {
        out.push(...blockList(body, ctx, depth + 1));
        continue;
      }
      push({
        kind: "code",
        html: codeBlock(body.join("\n"), fence[2] || "", closed, ctx),
      });
      continue;
    }
    const math = ctx.rich ? mathBlock(lines, i, ctx) : null;
    if (math) {
      push({ kind: "math", html: math.html });
      i = math.next;
      continue;
    }
    const heading = line.match(RE_HEADING);
    if (heading) {
      const level = Math.min(Math.max(heading[1].length + 1, 3), 5);
      push({
        kind: "heading",
        label: heading[2],
        html: `<h${level}>${inline(heading[2], ctx)}</h${level}>`,
      });
      i += 1;
      continue;
    }
    if (RE_HR.test(line)) {
      push({ kind: "hr", html: "<hr>" });
      i += 1;
      continue;
    }
    if (isTableStart(lines, i)) {
      const head = splitRow(line);
      const align = splitRow(lines[i + 1]).map((c) =>
        c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : "",
      );
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        const cells = splitRow(lines[i++]);
        // a row longer than the header keeps its extra cells, joined into the last one, instead of dropping them
        if (cells.length > head.length)
          cells.splice(
            head.length - 1,
            cells.length,
            cells.slice(head.length - 1).join(" | "),
          );
        rows.push(cells);
      }
      push({
        kind: "table",
        html: tableHtml(head, align, rows, ctx, growingAt(lines, i, ctx)),
      });
      continue;
    }
    if (RE_QUOTE.test(line) && depth < 4) {
      const inner = [];
      while (i < lines.length && RE_QUOTE.test(lines[i]))
        inner.push(lines[i++].match(RE_QUOTE)[1]);
      push({ kind: "quote", html: quote(inner, ctx, depth) });
      continue;
    }
    if (RE_ITEM.test(line)) {
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(RE_ITEM);
        if (m) {
          const ordered = /\d/.test(m[2]);
          const indent = m[1].replace(/\t/g, "    ").length;
          // A bullet list followed by a numbered one (or the reverse) is two lists.
          if (
            items.length &&
            indent <= items[0].indent + 1 &&
            ordered !== items[0].ordered
          )
            break;
          items.push({
            indent,
            ordered,
            start: ordered ? parseInt(m[2], 10) : 1,
            text: m[3],
          });
          i += 1;
        } else if (lines[i].trim() && /^\s+/.test(lines[i]) && items.length) {
          const last = items[items.length - 1];
          // two trailing spaces or a backslash: a hard line break, kept inside the item
          const hard = ctx.rich && /(?: {2,}|\\)$/.test(last.text);
          last.text =
            (hard
              ? last.text.replace(/(?: +|\\)$/, "") + "\u0001"
              : last.text + " ") + lines[i].trim();
          i += 1;
        } else if (ctx.rich && !lines[i].trim() && items.length && continuation(lines, i, items)) {
          // "* x" / blank / "  suite de x": an indented paragraph belongs to the item above it
          let j = i;
          while (!lines[j].trim()) j++;
          items[items.length - 1].text += `\u0001\u0001${lines[j].trim()}`;
          i = j + 1;
        } else if (
          !lines[i].trim() &&
          i + 1 < lines.length &&
          RE_ITEM.test(lines[i + 1])
        ) {
          i += 1;
        } else break;
      }
      const nodes = listTree(items);
      const kpis =
        ctx.rich && ctx.final && !ctx.suppress.has("kpis")
          ? keyNumbers(nodes, ctx)
          : null;
      if (kpis) push({ kind: "kpis", html: kpis });
      else
        push({
          kind: "list",
          html: listHtml(nodes, ctx, 0, {
            fold: ctx.rich && ctx.final,
            growing: growingAt(lines, i, ctx),
          }),
        });
      continue;
    }
    const start = i;
    const para = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !RE_FENCE.test(lines[i]) &&
      !RE_HEADING.test(lines[i]) &&
      !RE_HR.test(lines[i]) &&
      !RE_ITEM.test(lines[i]) &&
      !RE_QUOTE.test(lines[i]) &&
      !isTableStart(lines, i) &&
      !(ctx.rich && RE_MATH_OPEN.test(lines[i]) && mathBlock(lines, i, ctx)) // a display formula ends the paragraph
    )
      para.push(lines[i++]);
    // "Fichier : `backup.sh`" right above a fence names the block: it moves into the code head
    const named =
      ctx.rich &&
      para.length === 1 &&
      i < lines.length &&
      RE_FENCE.test(lines[i]) &&
      para[0].trim().match(RE_FILE_LINE);
    if (named) {
      ctx.file = named[1];
      continue;
    }
    // "Bonjour M. Dupont," opens a letter or an email: what follows is shown as written (no callouts)
    if (ctx.rich && depth === 0 && para[0].trim().length <= 80 && RE_SALUTE.test(para[0].trim()))
      ctx.letter = true;
    // "Recommandation" alone on the first line of a paragraph of prose: a heading over that paragraph
    const lead =
      ctx.rich &&
      depth === 0 &&
      para.length >= 2 &&
      indentOf(para[0]) < 2 &&
      !growingAt(lines, i, ctx) && // the paragraph is complete: no title that comes and goes per sentence
      (start === 0 || !lines[start - 1].trim())
        ? leadHeading(para)
        : null;
    if (lead) {
      push({ kind: "heading", label: lead, html: `<h4 class="md-ph">${inline(lead, ctx)}</h4>` });
      push(paragraph(para.slice(1), start + 1, lines, i, ctx, depth));
      continue;
    }
    push(paragraph(para, start, lines, i, ctx, depth));
  }
  return ctx.rich && ctx.final && depth === 0 ? prosCons(out, ctx) : out;
}

/** "Avantages" + list, then "Inconvénients" + list: one two-column block (only once the answer is final). */
function prosCons(out, ctx) {
  const res = [];
  for (let k = 0; k < out.length; k++) {
    const [a, b, c, d] = out.slice(k, k + 4);
    if (
      d &&
      a.kind === "heading" &&
      b.kind === "list" &&
      c.kind === "heading" &&
      isProsCons(norm(a.label), norm(c.label)) &&
      d.kind === "list"
    ) {
      const col = (cls, h, list) =>
        `<section class="md-pc md-pc--${cls}"><h4 class="md-pc-t">${inline(h.label, ctx)}</h4>${list.html}</section>`;
      res.push({
        kind: "proscons",
        html: `<div class="md-proscons">${col("pro", a, b)}${col("con", c, d)}</div>`,
      });
      k += 3;
    } else res.push(out[k]);
  }
  return res;
}

const LABELS = {
  text: "Texte",
  wrap: "Retour à la ligne",
  download: "Télécharger",
  downloadLabel: "Télécharger {file}",
  more: "Afficher les {n} lignes",
  less: "Réduire",
  checkOk: "Syntaxe Python valide", // parsed by the server (ast), never run: the badge never says « testé »
  checkJson: "Syntaxe JSON valide",
  checkTitle:
    "Syntaxe analysée sans exécuter le code : ni la logique ni le résultat ne sont vérifiés.",
  checkErr: "Syntaxe à vérifier, ligne {line}",
  checkExcerpt: "Extrait",
  copyFormula: "Copier la formule",
  copyTex: "Copier la formule (TeX)",
  copied: "Formule copiée.",
  listMore: "Afficher les {n} autres",
  callout: {
    note: "Note",
    tip: "Conseil",
    important: "Important",
    warn: "Attention",
    key: "À retenir",
    decision: "Décision",
  },
};

function context(options) {
  const labels = { ...LABELS, ...(options.labels || {}) };
  labels.callout = { ...LABELS.callout, ...(options.labels?.callout || {}) };
  return {
    cites: new Set(options.cites ?? []),
    anchor: String(options.anchor ?? "src").replace(/[^\w-]/g, ""),
    citeLabel: options.citeLabel ?? "Source {n}",
    copyCode: String(options.copyCode ?? "Copier le code {lang}"),
    copyText: String(options.copyText ?? "Copier"),
    rich: Boolean(options.rich),
    final: Boolean(options.final),
    lang: options.lang === "fr" || options.lang === "en" ? options.lang : null,
    wrap: Boolean(options.wrap),
    checks: Array.isArray(options.codeChecks) ? options.codeChecks : [],
    suppress: new Set(options.suppress || []),
    expanded: new Set(options.expanded || []),
    labels,
    fence: 0,
    file: null,
    letter: false,
  };
}

const clean = (source) =>
  String(source ?? "")
    .replace(/[\u0000\u0001]/g, "")
    .replace(/\r\n?/g, "\n");

/**
 * Render Markdown to a list of top-level HTML blocks (each ONE element), made only of tags written in this file.
 * options.cites: iterable of valid citation numbers; options.anchor: id prefix of the sources list.
 * options.rich: answer mode (detectors, typography with options.lang); options.final: the answer is complete
 * (key numbers, pros/cons, folding, syntax badges); options.codeChecks: the server's verdicts; options.wrap:
 * code lines wrap; options.suppress: detectors a structured widget replaces ("kpis"); options.labels: UI strings;
 * options.expanded: indices of long code blocks the reader has seen open (never folded again on re-render).
 */
export function renderBlocks(source, options = {}) {
  return blockList(clean(source).split("\n"), context(options), 0).map(
    (b) => b.html,
  );
}

export function renderMarkdown(source, options = {}) {
  return renderBlocks(source, options).join("\n");
}

/**
 * Make a partial (still streaming) answer safe to render without flashes of raw markup:
 * hide an unfinished link or citation at the very end, and close emphasis or code left open on the last line.
 */
export function stabilize(partial) {
  let text = clean(partial);
  const fences = (text.match(/^\s{0,3}(```|~~~)/gm) || []).length;
  if (fences % 2 === 1) {
    // the opening fence line itself is still being written ("```pyt"): wait for its end, so the label does not
    // flicker through "J", "JavaScript", "JSON"
    const cut = text.lastIndexOf("\n");
    if (/^\s{0,3}(?:```|~~~)/.test(text.slice(cut + 1))) return text.slice(0, Math.max(cut, 0));
    return text.replace(/\n\s{0,3}[`~]{1,2}$/, ""); // inside a code block: literal text
  }
  text = text.replace(/\[[^\]\n]*\]\([^)\s]*$/, (m) =>
    m.slice(1, m.indexOf("]")),
  ); // [label](http…  -> label
  text = text.replace(/\[[^\]\n]{0,60}$/, (m) =>
    /^\[\d{0,2}$/.test(m) ? "" : m.slice(1),
  ); // "[1" or "[label" waiting for "]"
  text = text.replace(/\[([^\]\n]{1,60})\]$/, (m, label) =>
    /^\d{1,2}$/.test(label) ? m : label,
  ); // "[label]" before "("
  text = text.replace(/[*_`~#>|-]{1,3}$/, (m) =>
    /\n$|^$/.test(text.slice(0, -m.length)) ? "" : m,
  ); // marker alone on a new line
  // "2" or "  2." starting the next item: wait for its text, so the list above does not look finished for a moment
  text = text.replace(/(^|\n)[ \t]*(?:[-*+]|\d{1,9}[.)]?)[ \t]*$/, "$1");
  const cut = text.lastIndexOf("\n") + 1;
  let last = text.slice(cut);
  const odd = (str, re) => (str.match(re) || []).length % 2 === 1;
  if (odd(last, /`/g))
    last = last.endsWith("`") ? last.slice(0, -1) : last + "`";
  const noCode = last.replace(/`[^`]*`/g, "");
  if (odd(noCode, /\*\*/g))
    last = /\*\*\*?$/.test(last) ? last.replace(/\*+$/, "") : last + "**";
  else if (
    odd(noCode.replace(/\*\*/g, ""), /\*/g) &&
    !/^\s*\*(\s|$)/.test(noCode)
  )
    last = last.endsWith("*") ? last.slice(0, -1) : last + "*";
  return text.slice(0, cut) + last;
}
