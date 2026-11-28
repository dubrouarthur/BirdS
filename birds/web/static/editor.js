// The deck / document editor: the plan of a file Bird made (titles, points or sections, the picture of each
// slide or section, cover, theme) in a form; "Rebuild" sends it to /api/office with the file itself (its pictures
// are taken back from it on the server) and the pictures added here, and the card shows the new file.
// Model and user text only ever goes through textContent and form values.
import { activeMode, b64ToBytes, button, h, state, t, toast } from "./core.js";

const MAX_SIDE = 1600;
const THEMES = ["corporate", "modern", "warm"];

const thumbUrl = (b64) => {
  try {
    return URL.createObjectURL(
      new Blob([b64ToBytes(b64)], { type: "image/jpeg" }),
    );
  } catch {
    return "";
  }
};

/** A picture chosen here, reduced in the browser (long side 1600 px) before it is sent. */
function readPicture(file) {
  return new Promise((resolve, reject) => {
    if (
      !/^image\/(png|jpeg|webp|gif)$/.test(file.type) ||
      file.size > 25_000_000
    )
      return reject(new Error("type"));
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(
        1,
        MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight),
      );
      const c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(img.naturalWidth * k));
      c.height = Math.max(1, Math.round(img.naturalHeight * k));
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      const png = file.type === "image/png";
      resolve({
        url: c.toDataURL(png ? "image/png" : "image/jpeg", 0.86),
        w: c.width,
        h: c.height,
        preview: c,
      });
    };
    img.onerror = () => (URL.revokeObjectURL(url), reject(new Error("decode")));
    img.src = url;
  });
}

function headers() {
  const p = state.prefs;
  const mode = activeMode();
  const out = {
    "Content-Type": "application/json",
    "X-Bird-Mode": mode,
    "X-Bird-Lang": p.lang,
  };
  if (mode !== "demo" && p.access) out["X-Bird-Access"] = p.access;
  return out;
}

function field(label, control) {
  return h("label", null, h("span", { text: label }), control);
}

function select(options, value, onchange) {
  const el = h("select", { onchange: (e) => onchange(e.target.value) });
  for (const [v, label] of options) {
    const o = h("option", { value: v, text: label });
    if (v === value) o.selected = true;
    el.append(o);
  }
  return el;
}

/** Open the editor for one generated file (file.preview.plan); onDone() after the file was replaced. */
export function openEditor(file, { onDone } = {}) {
  const plan = file?.preview?.plan;
  if (!plan || !plan.args) return;
  const deck = plan.tool === "make_slides";
  const args = JSON.parse(JSON.stringify(plan.args));
  const items = deck ? args.slides || [] : args.sections || [];
  const media = (plan.media || []).filter((m) => m && m.id);
  const uploads = [];
  let theme = THEMES.includes(plan.theme) ? plan.theme : "corporate";
  let cover = plan.cover || "none";
  const pictureOptions = () => [
    ["", t("editor.auto")],
    ["none", t("editor.none")],
    ...media
      .filter((m) => m.kind !== "chart" && !m.logo)
      .map((m) => [m.id, m.alt || m.title || m.id]),
    ...(deck
      ? media
          .filter((m) => m.kind === "chart")
          .map((m) => [`chart:${m.id}`, `📊 ${m.alt || m.id}`])
      : []),
  ];
  const status = h("p", {
    class: "editor-status",
    role: "status",
    "aria-live": "polite",
  });
  const list = h("div", { class: "editor-items" });
  const strip = h("div", { class: "editor-media" });

  function drawStrip() {
    strip.replaceChildren(
      ...media
        .filter((m) => m.kind !== "chart")
        .map((m) =>
          h(
            "figure",
            {
              title: [
                m.alt,
                m.credit && t("editor.credit", { credit: m.credit }),
              ]
                .filter(Boolean)
                .join("\n"),
            },
            m.th || m.local
              ? h("img", {
                  src: m.local || thumbUrl(m.th),
                  alt: String(m.alt || ""),
                })
              : null,
          ),
        ),
    );
  }

  function draw() {
    list.replaceChildren(
      ...items.map((it, i) => {
        const title = h("input", {
          type: "text",
          value: deck ? it.title || "" : it.heading || "",
          "aria-label": deck ? t("editor.title") : t("editor.heading"),
          oninput: (e) =>
            deck ? (it.title = e.target.value) : (it.heading = e.target.value),
        });
        const text = h("textarea", {
          "aria-label": deck ? t("editor.bullets") : t("editor.content"),
          oninput: (e) =>
            deck
              ? (it.bullets = e.target.value
                  .split("\n")
                  .filter((x) => x.trim()))
              : (it.content = e.target.value),
        });
        text.value = deck ? (it.bullets || []).join("\n") : it.content || "";
        const current = deck
          ? it.layout === "chart" && it.chart
            ? `chart:${it.chart}`
            : it.image || ""
          : (it.figures || [])[0] || (Array.isArray(it.figures) ? "none" : "");
        const pic = select(pictureOptions(), current, (v) => {
          if (deck) {
            delete it.image;
            delete it.chart;
            if (it.layout === "chart") delete it.layout;
            if (v.startsWith("chart:")) {
              it.chart = v.slice(6);
            } else if (v) it.image = v;
          } else if (v === "") delete it.figures;
          else it.figures = v === "none" ? [] : [v];
        });
        const move = (d) => {
          const j = i + d;
          if (j < 0 || j >= items.length) return;
          [items[i], items[j]] = [items[j], items[i]];
          draw();
        };
        return h(
          "section",
          { class: "editor-item" },
          h(
            "div",
            { class: "editor-item-head" },
            h("span", {
              class: "editor-n num",
              text: String(i + (deck ? 2 : 1)),
            }),
            title,
            button("btn-icon btn-ghost editor-up", "chevron", t("editor.up"), () => move(-1)),
            button("btn-icon btn-ghost editor-down", "chevron", t("editor.down"), () =>
              move(1),
            ),
            button("btn-icon btn-ghost", "trash", t("editor.remove"), () => {
              if (items.length > 1) (items.splice(i, 1), draw());
            }),
          ),
          field(deck ? t("editor.bullets") : t("editor.content"), text),
          field(t("editor.image"), pic),
        );
      }),
    );
  }

  const picker = h("input", {
    type: "file",
    accept: "image/png,image/jpeg,image/webp",
    hidden: true,
  });
  picker.addEventListener("change", async () => {
    for (const f of [...picker.files].slice(0, 6 - uploads.length)) {
      try {
        const got = await readPicture(f);
        const id = `n${uploads.length + 1}`;
        uploads.push({
          id,
          url: got.url,
          alt: f.name.replace(/\.[a-z0-9]+$/i, "").slice(0, 120),
        });
        media.push({
          id,
          kind: "user",
          alt: uploads.at(-1).alt,
          local: URL.createObjectURL(f),
        });
      } catch {
        toast(t("editor.badimage"), "error");
      }
    }
    picker.value = "";
    drawStrip();
    draw();
    coverSel.replaceWith((coverSel = coverSelect()));
  });
  const coverSelect = () =>
    select(
      [
        ["none", t("editor.none")],
        ...media
          .filter((m) => m.kind === "user" || m.kind === "web")
          .map((m) => [m.id, m.alt || m.id]),
      ],
      cover,
      (v) => (cover = v),
    );
  let coverSel = coverSelect();
  const titleIn = h("input", {
    type: "text",
    value: args.title || "",
    oninput: (e) => (args.title = e.target.value),
  });
  const subIn = h("input", {
    type: "text",
    value: args.subtitle || "",
    oninput: (e) => (args.subtitle = e.target.value),
  });
  const save = button("btn-primary", "check", t("editor.save"), () => submit());
  const dlg = h(
    "dialog",
    {
      class: "editor",
      "aria-label": deck ? t("editor.deck") : t("editor.doc"),
    },
    h(
      "div",
      { class: "editor-body" },
      h(
        "div",
        { class: "editor-head" },
        h("h2", { text: deck ? t("editor.deck") : t("editor.doc") }),
        button("btn-icon btn-ghost", "cross", t("editor.cancel"), () =>
          dlg.close(),
        ),
      ),
      h(
        "div",
        { class: "editor-grid" },
        field(t("editor.title"), titleIn),
        field(t("editor.subtitle"), subIn),
        field(
          t("editor.theme"),
          select(
            THEMES.map((x) => [x, t(`editor.theme.${x}`)]),
            theme,
            (v) => (theme = v),
          ),
        ),
        h("label", null, h("span", { text: t("editor.cover") }), coverSel),
      ),
      h(
        "div",
        { class: "editor-head" },
        strip,
        button("btn-outline btn-small", "image", t("editor.add.image"), () =>
          picker.click(),
        ),
      ),
      picker,
      list,
      h(
        "div",
        { class: "editor-actions" },
        status,
        button(
          "btn-outline btn-small",
          "plus",
          deck ? t("editor.add.slide") : t("editor.add.section"),
          () => {
            items.push(
              deck ? { title: "", bullets: [] } : { heading: "", content: "" },
            );
            draw();
            list.lastElementChild?.querySelector("input")?.focus();
          },
        ),
        button("btn-ghost", null, t("editor.cancel"), () => dlg.close()),
        save,
      ),
    ),
  );
  if (!file.data && media.some((m) => m.kind !== "chart"))
    status.textContent = t("editor.nofile");

  async function submit() {
    save.disabled = true;
    status.textContent = t("editor.working");
    try {
      const body = {
        tool: plan.tool,
        args: { ...args, [deck ? "slides" : "sections"]: items },
        theme,
        cover,
        media: media.filter((m) => !m.local).map(({ th, ...m }) => m),
        sources: plan.sources || [],
        file: file.data || null,
        uploads,
        lang: state.prefs.lang === "en" ? "en" : "fr",
      };
      if (deck)
        body.args.slides = items.map((it) =>
          it.chart ? { ...it, layout: "chart", chart: it.chart } : it,
        );
      const response = await fetch("/api/office", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      const next = data?.files?.[0];
      if (!response.ok || !data.ok || !next) {
        const error = String(
          data?.error || data?.detail?.message || response.status,
        ).slice(0, 200);
        status.textContent = t("editor.failed", { error });
        return;
      }
      Object.assign(file, next);
      dlg.close();
      toast(t("editor.done"), "ok");
      onDone?.();
    } catch (error) {
      status.textContent = t("editor.failed", {
        error: String(error?.message || error).slice(0, 200),
      });
    } finally {
      save.disabled = false;
    }
  }

  dlg.addEventListener("close", () => dlg.remove());
  drawStrip();
  draw();
  document.body.append(dlg);
  dlg.showModal();
  titleIn.focus();
}
