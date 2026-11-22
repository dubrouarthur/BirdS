// Attachments: documents (text, PDF, Office) and images, from the picker, the camera, drag-and-drop or paste.
// Images are decoded, oriented (EXIF), downscaled and re-encoded HERE, in the browser; they are sent once with
// the message that carries them and never stored (localStorage keeps only their name and size).
import {
  $,
  announce,
  fmtBytes,
  fmtInt,
  h,
  icon,
  state,
  t,
  toast,
  uid,
} from "./core.js";

export const TEXT_EXT =
  /\.(txt|md|markdown|csv|tsv|json|log|rst|yaml|yml|xml|html?)$/i;
export const BINARY_EXT = /\.(pdf|docx|xlsx|pptx)$/i;
export const IMAGE_TYPES = /^image\/(png|jpeg|webp|heic|heif|gif|bmp|avif)$/i;
const IMAGE_EXT = /\.(png|jpe?g|webp|heic|heif|gif|bmp|avif)$/i;
const MAX_SIDE = 1568; // long side sent to the model: 1568 px = 49 patches of 32 px (Qwen3.5 vision: 16 px x merge 2)
const MAX_IMAGES = 3;
const MAX_BINARY = 2_000_000; // bytes of one PDF / Office file (base64 grows it by a third; Vercel caps requests at 4.5 MB)

export const KINDS = {
  pdf: { label: "PDF", cls: "k-pdf" },
  docx: { label: "Word", cls: "k-word" },
  xlsx: { label: "Excel", cls: "k-excel" },
  pptx: { label: "PowerPoint", cls: "k-ppt" },
  csv: { label: "CSV", cls: "k-sheet" },
  tsv: { label: "TSV", cls: "k-sheet" },
  md: { label: "Markdown", cls: "k-text" },
  markdown: { label: "Markdown", cls: "k-text" },
  json: { label: "JSON", cls: "k-text" },
  txt: { label: "Texte", cls: "k-text" },
  image: { label: "Image", cls: "k-image" },
};
export const extOf = (name) =>
  (String(name).match(/\.([A-Za-z0-9]{1,8})$/) || ["", ""])[1].toLowerCase();
export const kindOf = (name) =>
  KINDS[extOf(name)] || {
    label: (extOf(name) || "txt").toUpperCase(),
    cls: "k-text",
  };

/** "un-tres-long-nom-de-fichier.pdf" -> "un-tres-lo…fichier.pdf" (the extension stays visible). */
export function middle(name, max = 26) {
  const s = String(name);
  if (s.length <= max) return s;
  const keep = max - 1;
  return `${s.slice(0, Math.ceil(keep * 0.55))}…${s.slice(s.length - Math.floor(keep * 0.45))}`;
}

// ------------------------------------------------------------------ pending images (this message only)

export const pending = { images: [] };

function safeName(name, fallback) {
  const s = String(name || "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "")
    .slice(0, 60);
  return s || fallback;
}

async function decode(file) {
  // EXIF orientation: createImageBitmap honours it with imageOrientation "from-image" (the default in current
  // browsers); an <img> fallback covers browsers whose createImageBitmap cannot decode the type (e.g. HEIC in Safari).
  try {
    return await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.decoding = "async";
      img.src = url;
      await img.decode();
      return img;
    } finally {
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }
}

function canvasOf(source, w, h) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, w, h);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(source, 0, 0, w, h);
  return canvas;
}

/** A blob: URL for display (the CSP allows blob: images, never data:). */
function blobUrl(source, w, h) {
  return new Promise((resolve) =>
    canvasOf(source, w, h).toBlob((blob) => resolve(blob ? URL.createObjectURL(blob) : ""), "image/jpeg", 0.82),
  );
}

function encode(source, w, h, type, quality) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff"; // transparent PNGs become white, not black, once in JPEG
  ctx.fillRect(0, 0, w, h);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(source, 0, 0, w, h);
  return canvas.toDataURL(type, quality);
}

export async function addImage(file, onChange) {
  const lim = state.health?.image_limits || {};
  const minPixels = lim.min_pixels || 200_000;
  const minSide = lim.min_side || 300;
  const item = {
    id: uid("i"),
    name: safeName(file.name, "photo.jpg"),
    size: file.size,
    status: "reading",
    w: 0,
    h: 0,
    url: "",
    thumb: "",
  };
  if (pending.images.length >= (lim.max || MAX_IMAGES)) {
    toast(t("att.img.toomany", { max: lim.max || MAX_IMAGES }), "error");
    return;
  }
  pending.images.push(item);
  onChange();
  let bitmap;
  try {
    bitmap = await decode(file);
  } catch {
    item.status = "error";
    item.error =
      /\.(heic|heif)$/i.test(file.name) || /hei[cf]/i.test(file.type)
        ? "att.img.heic"
        : "att.img.unreadable";
    onChange();
    return;
  }
  const w0 = bitmap.width || bitmap.naturalWidth;
  const h0 = bitmap.height || bitmap.naturalHeight;
  if (w0 * h0 < minPixels || Math.min(w0, h0) < minSide) {
    item.status = "error";
    item.error = "att.img.small";
    item.w = w0;
    item.h = h0;
    item.thumb = encode(
      bitmap,
      Math.max(1, Math.round((w0 * 72) / Math.max(w0, h0))),
      Math.max(1, Math.round((h0 * 72) / Math.max(w0, h0))),
      "image/jpeg",
      0.7,
    );
    onChange();
    return;
  }
  const scale = Math.min(1, MAX_SIDE / Math.max(w0, h0));
  const w = Math.round(w0 * scale);
  const hgt = Math.round(h0 * scale);
  let url = encode(bitmap, w, hgt, "image/jpeg", 0.88);
  if (url.length > 1_300_000) url = encode(bitmap, w, hgt, "image/jpeg", 0.72);
  const ts = 240 / Math.max(w, hgt);
  item.thumb = encode(
    bitmap,
    Math.max(1, Math.round(w * ts)),
    Math.max(1, Math.round(hgt * ts)),
    "image/jpeg",
    0.8,
  );
  bitmap.close?.();
  if (!/\.jpe?g$/i.test(item.name))
    item.name = item.name.replace(/\.[^.]+$/, "") + ".jpg";
  Object.assign(item, {
    url,
    w,
    h: hgt,
    status: "ready",
    sent: Math.round((url.length * 3) / 4),
  });
  announce(t("att.added", { name: item.name }));
  onChange();
}

export function removeImage(id, onChange) {
  const i = pending.images.findIndex((x) => x.id === id);
  if (i >= 0) {
    announce(t("att.removed", { name: pending.images[i].name }));
    pending.images.splice(i, 1);
  }
  onChange();
}

export const readyImages = () =>
  pending.images.filter((x) => x.status === "ready");
export const busyImages = () =>
  pending.images.some((x) => x.status === "reading");

// ------------------------------------------------------------------ documents (conversation-wide)

export async function readDocument(file) {
  const name = safeName(file.name, "document.txt");
  if (BINARY_EXT.test(name)) {
    if (file.size > MAX_BINARY)
      return { error: "att.doc.toolarge", name, size: file.size };
    const buf = new Uint8Array(await file.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i += 0x8000)
      bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    return { name, size: file.size, content: btoa(bin), encoding: "base64" };
  }
  if (
    TEXT_EXT.test(name) ||
    /^text\//.test(file.type) ||
    file.type === "application/json"
  ) {
    const text = await file.text();
    return {
      name: /\.[A-Za-z0-9]{1,8}$/.test(name) ? name : `${name}.txt`,
      size: file.size,
      content: text,
      encoding: "text",
    };
  }
  return { error: "att.doc.type", name, size: file.size };
}

export const isImageFile = (file) =>
  IMAGE_TYPES.test(file.type || "") || IMAGE_EXT.test(file.name || "");

// ------------------------------------------------------------------ cards

/** A document card. `doc`: {name, size, encoding, status?, content?}. */
export function docCard(doc, { onRemove, status, compact, excerpt } = {}) {
  const k = kindOf(doc.name);
  const ext = extOf(doc.name) || "txt";
  return h(
    "div",
    {
      class: `att-card att-doc ${k.cls}${compact ? " is-compact" : ""}`,
      tabindex: "0",
      title: doc.name,
      "data-att": doc.name,
    },
    h("span", {
      class: "att-badge",
      "aria-hidden": "true",
      text: ext.slice(0, 4).toUpperCase(),
    }),
    h(
      "span",
      { class: "att-meta" },
      h("span", {
        class: "att-name",
        text: middle(doc.name, compact ? 24 : 28),
      }),
      h(
        "span",
        { class: "att-sub" },
        [
          k.label,
          doc.size
            ? fmtBytes(doc.size)
            : doc.content
              ? `${fmtInt(doc.content.length)} car.`
              : "",
        ]
          .filter(Boolean)
          .join(" · "),
        status &&
          h("span", {
            class: `att-status st-${status.kind}`,
            text: status.text,
          }),
      ),
    ),
    onRemove &&
      h(
        "button",
        {
          class: "att-x",
          type: "button",
          "aria-label": t("composer.attach.remove", { name: doc.name }),
          onclick: onRemove,
        },
        icon("cross"),
      ),
    excerpt &&
      h(
        "details",
        { class: "att-excerpt" },
        h("summary", { text: t("att.excerpt") }),
        h("pre", {
          text: excerpt.slice(0, 4000) + (excerpt.length > 4000 ? "\n…" : ""),
        }),
      ),
  );
}

/** An image card: thumbnail (or a neutral placeholder after reload), size, status, remove. */
export function imageCard(img, { onRemove, onOpen, compact } = {}) {
  const status =
    img.status === "reading"
      ? { kind: "busy", text: t("att.reading") }
      : img.status === "error"
        ? { kind: "err", text: t(img.error || "att.img.unreadable") }
        : null;
  const thumb = img.thumb
    ? h("img", {
        class: "att-thumb",
        src: img.thumb,
        alt: img.name,
        width: "72",
        height: "72",
        draggable: "false",
      })
    : h(
        "span",
        { class: "att-thumb att-ghost", "aria-hidden": "true" },
        icon("image"),
      );
  const body = [
    thumb,
    !compact &&
      h(
        "span",
        { class: "att-meta" },
        h("span", { class: "att-name", text: middle(img.name, 22) }),
        h(
          "span",
          { class: "att-sub" },
          img.w ? `${img.w}×${img.h}` : img.thumb ? "" : t("att.img.notkept"),
          img.sent ? ` · ${fmtBytes(img.sent)}` : "",
          status &&
            h("span", {
              class: `att-status st-${status.kind}`,
              text: status.text,
            }),
        ),
      ),
  ];
  const el = h(
    onOpen && img.thumb ? "button" : "div",
    {
      class: `att-card att-img${compact ? " is-compact" : ""}${img.status === "error" ? " is-error" : ""}`,
      type: onOpen && img.thumb ? "button" : null,
      tabindex: onOpen && img.thumb ? null : "0",
      title: img.thumb ? img.name : t("att.img.notkept"),
      "aria-label":
        onOpen && img.thumb ? t("att.img.open", { name: img.name }) : null,
      onclick: onOpen && img.thumb ? onOpen : null,
    },
    body,
  );
  if (!onRemove) return el;
  return h(
    "div",
    { class: "att-wrap" },
    el,
    h(
      "button",
      {
        class: "att-x",
        type: "button",
        "aria-label": t("composer.attach.remove", { name: img.name }),
        onclick: onRemove,
      },
      icon("cross"),
    ),
  );
}

// ------------------------------------------------------------------ lightbox

let gallery = [];
let at = 0;
function paintLightbox() {
  const item = gallery[at];
  if (!item) return;
  $("lightbox-img").src = item.view || item.thumb;
  $("lightbox-img").alt = item.name;
  $("lightbox-cap").textContent =
    `${item.name}${item.w ? ` · ${item.w}×${item.h}` : ""}${gallery.length > 1 ? ` · ${at + 1}/${gallery.length}` : ""}`;
  $("lightbox-prev").hidden = $("lightbox-next").hidden = gallery.length < 2;
}
export function openLightbox(items, index) {
  gallery = items.filter((x) => x.thumb || x.view);
  at = Math.max(0, gallery.indexOf(items[index]));
  paintLightbox();
  const d = $("lightbox");
  if (!d.open) d.showModal();
  $("lightbox-close").focus();
}
export function bindLightbox() {
  const d = $("lightbox");
  const step = (n) => {
    at = (at + n + gallery.length) % gallery.length;
    paintLightbox();
  };
  $("lightbox-close").addEventListener("click", () => d.close());
  $("lightbox-prev").addEventListener("click", () => step(-1));
  $("lightbox-next").addEventListener("click", () => step(1));
  d.addEventListener("click", (e) => e.target === d && d.close());
  d.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
  });
}
