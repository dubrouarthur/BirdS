// A tiny in-house renderer for Mermaid-like flowcharts (« flowchart TD », « graph LR »): no library, no network,
// no HTML from the model (labels are text nodes). Enough for process diagrams, decision trees and org charts.
//
//   flowchart TD
//     A[Demande] --> B{Complète ?}
//     B -->|oui| C(Analyse)
//     B -- non --> D[Relance] --> B
//
// parseFlow() is pure (node tests); flowSvg() builds an SVG element in the page's document.

const SHAPES = [
  ["((", "))", "circle"],
  ["([", "])", "stadium"],
  ["[[", "]]", "subroutine"],
  ["[(", ")]", "db"],
  ["{{", "}}", "hexagon"],
  ["[", "]", "rect"],
  ["(", ")", "round"],
  ["{", "}", "diamond"],
  [">", "]", "flag"],
];
const MAX_NODES = 60;
const MAX_EDGES = 120;

function cleanLabel(text) {
  return String(text ?? "")
    .replace(/^["'`]+|["'`]+$/g, "")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<[^>]*>/g, "")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .trim()
    .slice(0, 80);
}

/** One node token: « A », « A[Texte] », « B{Question ?} » -> {id, label, shape} (label/shape null when bare). */
function nodeToken(raw) {
  const s = raw.trim();
  const m = s.match(/^([A-Za-z0-9_À-ſ.-]+)\s*(.*)$/);
  if (!m) return null;
  const id = m[1];
  const rest = m[2].trim();
  if (!rest) return { id, label: null, shape: null };
  for (const [open, close, shape] of SHAPES) {
    if (
      rest.startsWith(open) &&
      rest.endsWith(close) &&
      rest.length >= open.length + close.length
    )
      return {
        id,
        label: cleanLabel(rest.slice(open.length, rest.length - close.length)),
        shape,
      };
  }
  return { id, label: cleanLabel(rest), shape: "rect" };
}

// an edge between two node tokens: -->, ---, -.->, ==>, with a label as |x| or « -- x --> »
const EDGE =
  /\s*(?:--\s+([^-|>][^>]*?)\s+-->|==\s+([^=]+?)\s+==>|(<?)(-{2,3}|={2,3}|-\.+-?)(>|o|x)?\s*(?:\|([^|]*)\|)?)\s*/;

/**
 * Parse the text into {dir: "TD"|"LR", nodes: [{id, label, shape}], edges: [{from, to, label, dashed, thick}],
 * errors: [line numbers that were not understood]}. Never throws.
 */
export function parseFlow(text) {
  const out = { dir: "TD", nodes: [], edges: [], errors: [] };
  const byId = new Map();
  const node = (tok) => {
    if (!tok) return null;
    let n = byId.get(tok.id);
    if (!n) {
      if (byId.size >= MAX_NODES) return null;
      n = {
        id: tok.id,
        label: tok.label ?? tok.id,
        shape: tok.shape || "rect",
      };
      byId.set(tok.id, n);
      out.nodes.push(n);
    } else if (tok.label !== null) {
      n.label = tok.label;
      n.shape = tok.shape || n.shape;
    }
    return n;
  };
  const lines = String(text ?? "")
    .replace(/\r\n?/g, "\n")
    .split(/\n|;(?![^[{(]*[\]})])/);
  lines.forEach((rawLine, i) => {
    const line = rawLine.replace(/%%.*$/, "").trim();
    if (!line) return;
    const head = line.match(/^(?:flowchart|graph)\s*(TD|TB|BT|LR|RL)?\s*$/i);
    if (head) {
      const d = (head[1] || "TD").toUpperCase();
      out.dir = d === "LR" || d === "RL" ? "LR" : "TD";
      return;
    }
    if (
      /^(?:subgraph|end|classDef|class|style|linkStyle|click|direction)\b/i.test(
        line,
      )
    )
      return;
    // split a chain « A --> B -->|x| C » into node tokens and edges
    const parts = [];
    let rest = line;
    let guard = 0;
    while (rest && guard++ < 40) {
      const m = rest.match(EDGE);
      if (!m || m.index === 0) {
        parts.push({ tok: rest });
        break;
      }
      parts.push({ tok: rest.slice(0, m.index) });
      const arrow = m[0];
      parts.push({
        edge: true,
        label: cleanLabel(m[1] ?? m[2] ?? m[6] ?? ""),
        dashed: /-\./.test(arrow),
        thick: /==/.test(arrow),
        open: !/>/.test(arrow),
      });
      rest = rest.slice(m.index + m[0].length);
    }
    const toks = parts
      .filter((p) => !p.edge)
      .map((p) => p.tok.split("&").map((x) => nodeToken(x)));
    if (toks.some((group) => group.some((t) => !t))) {
      out.errors.push(i + 1);
      return;
    }
    let k = 0;
    let prev = null;
    for (const p of parts) {
      if (p.edge) {
        const nextGroup = toks[k];
        for (const a of prev || [])
          for (const b of (nextGroup || []).map(node).filter(Boolean)) {
            if (out.edges.length < MAX_EDGES)
              out.edges.push({
                from: a.id,
                to: b.id,
                label: p.label,
                dashed: p.dashed,
                thick: p.thick,
                open: p.open,
              });
          }
        continue;
      }
      prev = toks[k++].map(node).filter(Boolean);
    }
  });
  return out;
}

/** Layers (longest path from the roots, cycles broken) and the order within each layer (barycentres). */
export function layoutFlow(flow) {
  const ids = flow.nodes.map((n) => n.id);
  const out = new Map(ids.map((id) => [id, []]));
  const indeg = new Map(ids.map((id) => [id, 0]));
  // drop back edges (DFS) so the layering terminates on cycles
  const color = new Map();
  const forward = [];
  const visit = (id) => {
    color.set(id, 1);
    for (const e of flow.edges.filter((x) => x.from === id)) {
      const c = color.get(e.to) || 0;
      if (c === 1) continue; // back edge: drawn, but not used for the layers
      forward.push(e);
      if (c === 0) visit(e.to);
    }
    color.set(id, 2);
  };
  for (const id of ids) if (!color.get(id)) visit(id);
  for (const e of forward) {
    out.get(e.from).push(e.to);
    indeg.set(e.to, indeg.get(e.to) + 1);
  }
  const layer = new Map(ids.map((id) => [id, 0]));
  const queue = ids.filter((id) => indeg.get(id) === 0);
  const deg = new Map(indeg);
  while (queue.length) {
    const id = queue.shift();
    for (const to of out.get(id)) {
      layer.set(to, Math.max(layer.get(to), layer.get(id) + 1));
      deg.set(to, deg.get(to) - 1);
      if (deg.get(to) === 0) queue.push(to);
    }
  }
  const layers = [];
  for (const id of ids) {
    const l = layer.get(id);
    (layers[l] ||= []).push(id);
  }
  // two barycentre passes: each node near the average position of its parents
  const pos = new Map();
  layers.forEach((ls) => ls.forEach((id, i) => pos.set(id, i)));
  for (let pass = 0; pass < 2; pass++)
    for (let l = 1; l < layers.length; l++) {
      const bary = (id) => {
        const parents = forward
          .filter((e) => e.to === id)
          .map((e) => pos.get(e.from));
        return parents.length
          ? parents.reduce((a, b) => a + b, 0) / parents.length
          : pos.get(id);
      };
      layers[l].sort((a, b) => bary(a) - bary(b));
      layers[l].forEach((id, i) => pos.set(id, i));
    }
  return { layers: layers.filter(Boolean), layer, pos };
}

/** Wrap a label in lines of about ``width`` characters (at most 4 lines). */
export function wrapLabel(text, width = 18) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = "";
  for (const w of words) {
    if (cur && (cur + " " + w).length > width) {
      lines.push(cur);
      cur = w;
    } else cur = cur ? `${cur} ${w}` : w;
  }
  if (cur) lines.push(cur);
  if (lines.length > 4)
    return [
      ...lines.slice(0, 3),
      lines
        .slice(3)
        .join(" ")
        .slice(0, width - 1) + "…",
    ];
  return lines.length ? lines : [""];
}

const NS = "http://www.w3.org/2000/svg";
function el(tag, attrs = {}, text) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
}

/** The SVG of a flowchart (text only from labels, as text nodes). Returns null when there is nothing to draw. */
export function flowSvg(flow, { title = "" } = {}) {
  if (!flow.nodes.length) return null;
  const { layers, layer, pos } = layoutFlow(flow);
  const lr = flow.dir === "LR";
  const W = 150;
  const LINE = 16;
  const size = new Map(
    flow.nodes.map((n) => {
      const lines = wrapLabel(n.label);
      const h = Math.max(44, 18 + lines.length * LINE);
      const w =
        n.shape === "diamond"
          ? W + 30
          : n.shape === "circle"
            ? Math.max(70, h)
            : W;
      return [
        n.id,
        {
          w,
          h: n.shape === "diamond" ? h + 22 : n.shape === "circle" ? w : h,
          lines,
        },
      ];
    }),
  );
  const GAP_MAIN = 64;
  const GAP_CROSS = 34;
  const maxCount = Math.max(...layers.map((l) => l.length));
  const cell =
    Math.max(...[...size.values()].map((s) => (lr ? s.h : s.w))) + GAP_CROSS;
  const depth = layers.map((l) =>
    Math.max(...l.map((id) => (lr ? size.get(id).w : size.get(id).h))),
  );
  const offsets = [];
  let acc = 20;
  for (const d of depth) {
    offsets.push(acc);
    acc += d + GAP_MAIN;
  }
  const crossTotal = maxCount * cell;
  const center = new Map();
  for (const n of flow.nodes) {
    const l = layer.get(n.id);
    const count = layers[l].length;
    const start = (crossTotal - count * cell) / 2;
    const cross = 20 + start + pos.get(n.id) * cell + cell / 2;
    const main = offsets[l] + depth[l] / 2;
    center.set(n.id, lr ? { x: main, y: cross } : { x: cross, y: main });
  }
  const width = (lr ? acc - GAP_MAIN : crossTotal) + 40;
  const height = (lr ? crossTotal : acc - GAP_MAIN) + 40;
  const svg = el("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "flow",
    role: "img",
  });
  svg.append(
    el(
      "title",
      {},
      title ||
        flow.nodes
          .map((n) => n.label)
          .join(", ")
          .slice(0, 200),
    ),
  );
  const defs = el("defs");
  const marker = el("marker", {
    id: "flow-arrow",
    viewBox: "0 0 10 10",
    refX: 9,
    refY: 5,
    markerWidth: 7,
    markerHeight: 7,
    orient: "auto-start-reverse",
  });
  marker.append(el("path", { d: "M0 0L10 5L0 10z", class: "flow-head" }));
  defs.append(marker);
  svg.append(defs);
  const border = (id, toward) => {
    // where the line from this node's centre toward a point leaves its box
    const c = center.get(id);
    const s = size.get(id);
    const dx = toward.x - c.x;
    const dy = toward.y - c.y;
    if (!dx && !dy) return c;
    const sx = s.w / 2 / Math.abs(dx || 1e-9);
    const sy = s.h / 2 / Math.abs(dy || 1e-9);
    const diamond = flow.nodes.find((n) => n.id === id)?.shape === "diamond";
    const k = diamond ? 1 / (Math.abs(dx) / (s.w / 2) + Math.abs(dy) / (s.h / 2)) : Math.min(sx, sy);
    return { x: c.x + dx * k, y: c.y + dy * k };
  };
  for (const e of flow.edges) {
    const a = center.get(e.from);
    const b = center.get(e.to);
    if (!a || !b) continue;
    const p1 = border(e.from, b);
    const p2 = border(e.to, a);
    const g = el("g", { class: "flow-edge" });
    const back = (layer.get(e.to) ?? 0) <= (layer.get(e.from) ?? 0);
    let d;
    if (back && e.from !== e.to) {
      // a loop back: around the side, so it never crosses the boxes
      const off = lr
        ? { x: 0, y: -(size.get(e.from).h / 2 + 26) }
        : { x: size.get(e.from).w / 2 + 26, y: 0 };
      const q1 = { x: a.x + off.x, y: a.y + off.y };
      const q2 = { x: b.x + off.x, y: b.y + off.y };
      d = `M${q1.x - (lr ? 0 : off.x)} ${q1.y - (lr ? off.y : 0)} C${q1.x} ${q1.y} ${q2.x} ${q2.y} ${q2.x - (lr ? 0 : off.x * 0.7)} ${q2.y - (lr ? off.y * 0.7 : 0)}`;
    } else d = `M${p1.x} ${p1.y} L${p2.x} ${p2.y}`;
    g.append(
      el("path", {
        d,
        class: `flow-line${e.dashed ? " dashed" : ""}${e.thick ? " thick" : ""}`,
        ...(e.open ? {} : { "marker-end": "url(#flow-arrow)" }),
      }),
    );
    if (e.label) {
      const mx =
        (p1.x + p2.x) / 2 + (back ? (lr ? 0 : size.get(e.from).w / 2 + 26) : 0);
      const my =
        (p1.y + p2.y) / 2 + (back && lr ? -(size.get(e.from).h / 2 + 26) : 0);
      const wLab = Math.min(140, 10 + e.label.length * 7);
      g.append(
        el("rect", {
          x: mx - wLab / 2,
          y: my - 11,
          width: wLab,
          height: 20,
          rx: 6,
          class: "flow-label-bg",
        }),
      );
      g.append(
        el(
          "text",
          { x: mx, y: my + 4, class: "flow-label", "text-anchor": "middle" },
          e.label.slice(0, 22),
        ),
      );
    }
    svg.append(g);
  }
  for (const n of flow.nodes) {
    const c = center.get(n.id);
    const s = size.get(n.id);
    const g = el("g", { class: `flow-node flow-${n.shape}` });
    const x = c.x - s.w / 2;
    const y = c.y - s.h / 2;
    if (n.shape === "diamond")
      g.append(
        el("path", {
          d: `M${c.x} ${y} L${x + s.w} ${c.y} L${c.x} ${y + s.h} L${x} ${c.y}z`,
          class: "flow-box",
        }),
      );
    else if (n.shape === "circle")
      g.append(
        el("circle", { cx: c.x, cy: c.y, r: s.w / 2, class: "flow-box" }),
      );
    else if (n.shape === "hexagon")
      g.append(
        el("path", {
          d: `M${x + 14} ${y} H${x + s.w - 14} L${x + s.w} ${c.y} L${x + s.w - 14} ${y + s.h} H${x + 14} L${x} ${c.y}z`,
          class: "flow-box",
        }),
      );
    else
      g.append(
        el("rect", {
          x,
          y,
          width: s.w,
          height: s.h,
          class: "flow-box",
          rx: n.shape === "round" || n.shape === "stadium" ? s.h / 2.4 : 8,
        }),
      );
    const first = c.y - ((s.lines.length - 1) * LINE) / 2 + 5;
    s.lines.forEach((ln, i) =>
      g.append(
        el(
          "text",
          {
            x: c.x,
            y: first + i * LINE,
            "text-anchor": "middle",
            class: "flow-text",
          },
          ln,
        ),
      ),
    );
    svg.append(g);
  }
  return svg;
}
