// Pure helpers of the canvas pictures (no DOM): tested in tests/js/canvas.test.mjs.

/** What a placeholder shows of its search: the words of the picture, never the model's notation
 * (« [Paris bike cargo 1] » -> « Paris bike cargo »; the server cleans it too: images.clean_query). */
export function cleanQuery(q) {
  return String(q || "")
    .replace(/[[\]{}()«»"“”<>]/g, " ")
    .replace(
      /^\s*(?:(?:une?|des|la|le|les|a|an|the)\s+)?(?:photos?|images?|illustrations?|pictures?|visuels?)\s*(?:de|d['’]|du|des|of|:|-)?\s*/i,
      "",
    )
    .replace(/(?<![\w-])(?:n°\s*)?\d{1,2}(?![\w-])/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^[ .,:;_-]+|[ .,:;_-]+$/g, "")
    .slice(0, 80);
}

/** Image parts of a deck or document still without a picture (searched or not): the slides to complete. */
export function missingPictures(doc) {
  const out = [];
  (doc?.blocks || []).forEach((b, i) => {
    if ((b.parts || []).some((p) => p.t === "image" && !p.media)) out.push(i + 1);
  });
  return out;
}
