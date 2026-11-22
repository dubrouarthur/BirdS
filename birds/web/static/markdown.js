// Small, safe Markdown renderer for model output.
// Rule: every character coming from the model is HTML-escaped BEFORE any tag is produced.
// The only tags in the output are the ones written literally in this file.

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

function linkHtml(href, labelHtml) {
  return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${labelHtml}</a>`;
}

function inline(raw, ctx) {
  const stash = [];
  const keep = (html) => `\u0000${stash.push(html) - 1}\u0000`;

  let text = String(raw).replace(/`([^`\n]+)`/g, (_, code) =>
    keep(`<code>${escapeHtml(code)}</code>`),
  );
  text = escapeHtml(text);

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
      return href ? lead + keep(linkHtml(href, url)) + tail : whole;
    },
  );

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

  return text.replace(/\u0000(\d+)\u0000/g, (_, i) => stash[Number(i)] ?? "");
}

const RE_FENCE = /^\s{0,3}(```|~~~)\s*([\w+-]*)\s*$/;
const RE_HEADING = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/;
const RE_HR = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const RE_ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const RE_QUOTE = /^\s{0,3}>\s?(.*)$/;
const RE_TABLE_SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

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

function renderList(items, ctx) {
  // items: [{indent, ordered, start, text}] -> nested lists by indentation.
  let pos = 0;
  const build = (indent) => {
    const ordered = items[pos].ordered;
    const start = items[pos].start;
    let html = ordered
      ? start !== 1
        ? `<ol start="${start}">`
        : "<ol>"
      : "<ul>";
    while (pos < items.length && items[pos].indent >= indent) {
      const item = items[pos];
      if (item.indent > indent + 1) {
        // Deeper item without a parent at this level: nest it under the previous <li>.
        html = html.replace(/<\/li>$/, "") + build(item.indent) + "</li>";
        continue;
      }
      pos += 1;
      html += `<li>${inline(item.text, ctx)}`;
      if (pos < items.length && items[pos].indent > indent + 1)
        html += build(items[pos].indent);
      html += "</li>";
    }
    return html + (ordered ? "</ol>" : "</ul>");
  };
  let out = "";
  while (pos < items.length) out += build(items[pos].indent);
  return out;
}

function blockList(lines, ctx, depth) {
  const out = [];
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
      i += 1;
      const lang = fence[2] ? ` data-lang="${escapeHtml(fence[2])}"` : "";
      out.push(`<pre${lang}><code>${escapeHtml(body.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = line.match(RE_HEADING);
    if (heading) {
      const level = Math.min(Math.max(heading[1].length + 1, 3), 5);
      out.push(`<h${level}>${inline(heading[2], ctx)}</h${level}>`);
      i += 1;
      continue;
    }
    if (RE_HR.test(line)) {
      out.push("<hr>");
      i += 1;
      continue;
    }
    if (isTableStart(lines, i)) {
      const head = splitRow(line);
      const align = splitRow(lines[i + 1]).map((c) =>
        c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : "",
      );
      const cls = (k) => (align[k] ? ` class="al-${align[k]}"` : "");
      let html = '<div class="table-wrap" tabindex="0"><table><thead><tr>';
      head.forEach(
        (cell, k) =>
          (html += `<th scope="col"${cls(k)}>${inline(cell, ctx)}</th>`),
      );
      html += "</tr></thead><tbody>";
      i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        const cells = splitRow(lines[i++]);
        // a row longer than the header keeps its extra cells, joined into the last one, instead of dropping them
        if (cells.length > head.length)
          cells.splice(head.length - 1, cells.length, cells.slice(head.length - 1).join(" | "));
        html += "<tr>";
        head.forEach(
          (_, k) =>
            (html += `<td${cls(k)}>${inline(cells[k] ?? "", ctx)}</td>`),
        );
        html += "</tr>";
      }
      out.push(html + "</tbody></table></div>");
      continue;
    }
    if (RE_QUOTE.test(line) && depth < 4) {
      const inner = [];
      while (i < lines.length && RE_QUOTE.test(lines[i]))
        inner.push(lines[i++].match(RE_QUOTE)[1]);
      out.push(`<blockquote>${blockList(inner, ctx, depth + 1).join("\n")}</blockquote>`);
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
          items[items.length - 1].text += " " + lines[i].trim();
          i += 1;
        } else if (
          !lines[i].trim() &&
          i + 1 < lines.length &&
          RE_ITEM.test(lines[i + 1])
        ) {
          i += 1;
        } else break;
      }
      out.push(renderList(items, ctx));
      continue;
    }
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
      !isTableStart(lines, i)
    )
      para.push(lines[i++]);
    out.push(`<p>${para.map((l) => inline(l.trim(), ctx)).join("<br>")}</p>`);
  }
  return out;
}

function context(options) {
  return {
    cites: new Set(options.cites ?? []),
    anchor: String(options.anchor ?? "src").replace(/[^\w-]/g, ""),
    citeLabel: options.citeLabel ?? "Source {n}",
  };
}

const clean = (source) =>
  String(source ?? "")
    .replace(/\u0000/g, "")
    .replace(/\r\n?/g, "\n");

/**
 * Render Markdown to a list of top-level HTML blocks, each made only of tags written in this file.
 * options.cites: iterable of valid citation numbers; options.anchor: id prefix of the sources list.
 */
export function renderBlocks(source, options = {}) {
  return blockList(clean(source).split("\n"), context(options), 0);
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
  if (fences % 2 === 1) return text.replace(/\n\s{0,3}[`~]{1,2}$/, ""); // inside a code block: literal text
  text = text.replace(/\[[^\]\n]*\]\([^)\s]*$/, (m) => m.slice(1, m.indexOf("]"))); // [label](http…  -> label
  text = text.replace(/\[[^\]\n]{0,60}$/, (m) => (/^\[\d{0,2}$/.test(m) ? "" : m.slice(1))); // "[1" or "[label" waiting for "]"
  text = text.replace(/\[([^\]\n]{1,60})\]$/, (m, label) => (/^\d{1,2}$/.test(label) ? m : label)); // "[label]" before "("
  text = text.replace(/[*_`~#>|-]{1,3}$/, (m) => (/\n$|^$/.test(text.slice(0, -m.length)) ? "" : m)); // marker alone on a new line
  const cut = text.lastIndexOf("\n") + 1;
  let last = text.slice(cut);
  const odd = (str, re) => (str.match(re) || []).length % 2 === 1;
  if (odd(last, /`/g)) last = last.endsWith("`") ? last.slice(0, -1) : last + "`";
  const noCode = last.replace(/`[^`]*`/g, "");
  if (odd(noCode, /\*\*/g)) last = /\*\*\*?$/.test(last) ? last.replace(/\*+$/, "") : last + "**";
  else if (odd(noCode.replace(/\*\*/g, ""), /\*/g) && !/^\s*\*(\s|$)/.test(noCode)) last = last.endsWith("*") ? last.slice(0, -1) : last + "*";
  return text.slice(0, cut) + last;
}
