// Word-like documents in the canvas, on the demo server (no model): a « document Word » request opens the canvas
// with ONE card (first page, version, .docx / PDF), A4 pages in the template (cover, contents with page numbers,
// numbered headings, callouts, table, figure caption, notes, « n / N »), in-place editing, a section moved, a
// callout inserted, ✦ with two variants to choose from, a chip that adds the missing section where the template
// puts it, an older version restored, the .docx downloaded (checked by scripts/check_docx.py). 1280 and 360 px,
// light and dark; no third-party request.
//   BIRD_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --demo --port 9361 &
//   BIRD_URL=http://127.0.0.1:9361/ SHOTS=/tmp/shots node tests/e2e/canvas_docs.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9361/";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";

function check(cond, what) {
  if (!cond) throw new Error(`FAILED: ${what}`);
  console.log(`  ok  ${what}`);
}

async function idle(page) {
  await page.waitForFunction(() => !document.querySelector('.turn-bird[aria-busy="true"]'), null, {
    timeout: 60000,
  });
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
}

async function say(page, text) {
  if (await page.evaluate(() => !!document.querySelector(".main")?.inert))
    await page.locator('#canvas [data-k="close"]').click();
  await page.fill("#composer-input", text);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  await idle(page);
}

const version = (page) =>
  page.evaluate(() => {
    const sel = document.querySelector('#canvas [data-k="versions"]');
    return sel ? sel.options.length : 0;
  });

async function run(name, options, scheme) {
  console.log(`${name} (${scheme})`);
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...options, locale: "fr-FR", colorScheme: scheme, acceptDownloads: true });
  await ctx.addInitScript(() => localStorage.setItem("bird.prefs", JSON.stringify({ lang: "fr", welcomed: true })));
  const page = await ctx.newPage();
  const errors = [];
  const external = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("request", (r) => {
    const u = r.url();
    if (!u.startsWith(URL) && !/^(blob|data|about):/.test(u)) external.push(u);
  });
  await page.goto(URL);
  const tag = `${name}-${scheme}`;
  const phone = name === "phone";

  // 1. a Word document: the canvas opens on its pages, the chat has ONE card and no file line
  await say(page, "Rédige un document Word : note de cadrage pour le projet CRM de l'équipe commerciale");
  await page.waitForSelector("#canvas:not([hidden]) .cv-doc .cv-a4", { timeout: 10000 });
  await page.waitForTimeout(400);
  check((await page.locator(".turn-bird").last().locator(".cv-card").count()) === 1, "one card in the chat");
  check((await page.locator(".turn-bird").last().locator(".cards .file-card, .cards > *").count()) === 0, "no file card");
  const said = await page.locator(".turn-bird .md").last().innerText();
  check(!/Fichier\s*:|[\w-]\.docx\b/.test(said), "no « Fichier : x.docx » line in the answer");
  check(/note de cadrage/i.test(said), "the answer names the template");
  check(
    (await page.locator("#canvas .cv-kicker").first().innerText()).toLowerCase().includes("note de cadrage"),
    "the template's name on the page",
  );
  const heads = await page.locator("#canvas .cv-h1").allInnerTexts();
  check(heads.length === 5 && /^1\.\s*Contexte/.test(heads[0]), `numbered headings (${heads.join(" | ")})`);
  check((await page.locator("#canvas .cv-h2").count()) >= 2, "sub-headings (H2) numbered too");
  check((await page.locator("#canvas .cv-callout.cv-tone-key").count()) === 1, "a « À retenir » callout");
  check((await page.locator("#canvas .cv-callout.cv-tone-warn").count()) === 1, "an « Attention » callout");
  check((await page.locator("#canvas .cv-a4 .cv-table th").count()) === 3, "a table with its header row");
  await page.waitForSelector("#canvas .cv-figure img", { timeout: 10000 });
  check(/^Figure 1/.test(await page.locator("#canvas .cv-caption").first().innerText()), "a numbered figure caption");
  check((await page.locator("#canvas .cv-notes li").count()) === 1, "the footnote listed at the end");
  check((await page.locator("#canvas sup.cv-fn").count()) >= 2, "its call in the text, as a superscript");
  const toc = await page.locator("#canvas .cv-toc li").count();
  check(toc >= 5, `table of contents (${toc} entries)`);
  if (!phone) {
    const pages = await page.locator("#canvas .cv-a4").count();
    check(pages >= 3, `A4 pages (${pages})`);
    const foot = await page.locator("#canvas .cv-a4-foot").last().innerText();
    check(new RegExp(`^${pages} / ${pages}$`).test(foot.trim()), `page numbers « n / N » (${foot})`);
    const tocPage = await page.locator("#canvas .cv-toc-page").first().innerText();
    check(/^\d+$/.test(tocPage.trim()), "the contents give each heading its page");
    check(
      await page.evaluate(() => {
        const r = document.querySelector("#canvas .cv-a4:not(.cv-a4-cover)").getBoundingClientRect();
        return Math.abs(r.height / r.width - 297 / 210) < 0.02;
      }),
      "a page is A4 (297 / 210)",
    );
  }
  // the next steps come late (the « suggestions » event after « final »): the row appears once, complete
  await page.waitForSelector(".chips-row .mchip", { timeout: 15000 }).catch(() => {});
  const chips = await page.locator(".chips-row .mchip").allInnerTexts();
  check(chips.length >= 2 && chips.length <= 3 && chips.some((c) => /Ajouter/.test(c)), `2-3 next steps (${chips})`);
  await page.screenshot({ path: path.join(SHOTS, `docs-create-${tag}.png`) });
  if (!phone) {
    await page.locator("#canvas .cv-body").evaluate((e) => (e.scrollTop = e.clientHeight * 1.05));
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(SHOTS, `docs-pages-${tag}.png`) });
    await page.locator("#canvas .cv-body").evaluate((e) => (e.scrollTop = 0));
  }

  // 2. in-place edit of a section title: a new version, the contents follow
  const v0 = await version(page);
  const title = page.locator('#canvas [data-path="b2:title"]');
  await title.scrollIntoViewIfNeeded();
  await title.click();
  await page.keyboard.press("Control+A");
  await page.keyboard.type("Objectifs du projet");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(250);
  check((await version(page)) === v0 + 1, "an inline edit is a new version");
  check(
    (await page.locator("#canvas .cv-toc li").allInnerTexts()).some((x) => /Objectifs du projet/.test(x)),
    "the contents follow the edit",
  );

  // 3. move the first section down: numbering follows
  await page.locator('#canvas [data-path="b1:title"]').hover();
  await page.locator('#canvas [data-k="down-b1"]').click({ force: phone });
  await page.waitForTimeout(250);
  const heads2 = await page.locator("#canvas .cv-h1").allInnerTexts();
  check(/^1\.\s*Objectifs du projet/.test(heads2[0]) && /^2\.\s*Contexte/.test(heads2[1]), "section moved, renumbered");

  // 4. insert a « Attention » callout in a section
  const warn0 = await page.locator("#canvas .cv-callout.cv-tone-warn").count();
  await page.locator('#canvas [data-path="b2:title"]').hover();
  await page.locator('#canvas [data-k="ins-b2"]').click({ force: phone });
  await page.locator('#canvas [data-k="ins-warn-b2"]').click();
  await page.waitForTimeout(250);
  check((await page.locator("#canvas .cv-callout.cv-tone-warn").count()) === warn0 + 1, "a callout inserted");

  // 5. ✦ on a section: two variants side by side, one chosen = a new version
  const v1 = await version(page);
  await page.locator('#canvas [data-path="b1:title"]').hover();
  await page.locator('#canvas [data-k="ask-b1"]').click({ force: phone });
  await page.locator('#canvas [data-k="rw-shorter-b1"]').click();
  await page.waitForSelector("#canvas .cv-variants", { timeout: 20000 });
  await idle(page);
  check((await page.locator("#canvas .cv-variant").count()) === 2, "two variants shown in place of the section");
  check(/variantes/i.test(await page.locator(".turn-bird .md").last().innerText()), "the chat says to choose");
  if (phone && (await page.evaluate(() => document.querySelector("#canvas")?.hidden))) {
    await page.locator(".turn-bird").last().locator('[data-act^="cv-open-"]').click();
  }
  await page.locator("#canvas .cv-variants").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(SHOTS, `docs-variants-${tag}.png`) });
  await page.locator('#canvas [data-k="pick-2-b1"]').click();
  await page.waitForTimeout(250);
  check((await version(page)) === v1 + 1, "the chosen variant is the next version");
  check((await page.locator("#canvas .cv-variants").count()) === 0, "the chooser is gone");
  const label = await page.locator('#canvas [data-k="versions"] option:checked').innerText();
  check(/Variante 2/.test(label), `the version says which variant (${label})`);

  // 6. a next-step chip adds the missing section where the template puts it, and the turn shows « Version N »
  await say(page, "Ajoute une section Livrables au document");
  if (phone && (await page.evaluate(() => document.querySelector("#canvas")?.hidden)))
    await page.locator(".turn-bird").last().locator('[data-act^="cv-open-"]').click();
  await page.waitForTimeout(300);
  const heads3 = await page.locator("#canvas .cv-h1").allInnerTexts();
  const at = heads3.findIndex((x) => /Livrables/.test(x));
  check(at > 0 && at < heads3.length - 2, `the section goes where the template puts it (${heads3.join(" | ")})`);
  check(/^Version \d+ du document/.test(await page.locator(".turn-bird .md").last().innerText()), "« Version N » said");
  check(
    /Version \d+/.test(await page.locator(".turn-bird").last().locator(".cv-card-meta").innerText()),
    "the card shows the new version",
  );

  // 7. history: an older version, then « Restaurer »
  const vn = await version(page);
  await page.selectOption('#canvas [data-k="versions"]', "0");
  await page.waitForSelector('#canvas [data-k="restore"]');
  await page.locator('#canvas [data-k="restore"]').click();
  await page.waitForTimeout(250);
  check((await version(page)) === vn + 1, "a restore is a new version");
  check(/^1\.\s*Contexte/.test((await page.locator("#canvas .cv-h1").allInnerTexts())[0]), "v1 content is back");

  // 8. the .docx from the card in the chat (checked by scripts/check_docx.py against the page outline)
  if (phone) await page.locator('#canvas [data-k="close"]').click();
  const outline = await page.evaluate(() =>
    [...document.querySelectorAll("#canvas .cv-h1, #canvas .cv-h2, #canvas .cv-h3")].map((x) =>
      x.children.length
        ? [...x.children].map((c) => c.textContent.trim()).filter(Boolean).join(" ")
        : x.textContent.trim(),
    ),
  );
  const [dl] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(".turn-bird").last().locator('[data-act^="cv-docx-"]').click(),
  ]);
  const file = path.join(SHOTS, `docs-${tag}.docx`);
  await dl.saveAs(file);
  fs.writeFileSync(`${file}.json`, JSON.stringify({ headings: outline }));
  check(fs.statSync(file).size > 5000, "the .docx downloaded from the card");
  await page.screenshot({ path: path.join(SHOTS, `docs-card-${tag}.png`) });

  check(errors.length === 0, `no page error (${errors.slice(0, 3).join(" | ")})`);
  check(external.length === 0, `no third-party request (${external.slice(0, 3).join(" ")})`);
  await browser.close();
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const runs = [
    ["desktop", { viewport: { width: 1280, height: 900 } }, "light"],
    ["desktop", { viewport: { width: 1280, height: 900 } }, "dark"],
    ["phone", { viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, hasTouch: true, isMobile: true }, "light"],
    ["phone", { viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, hasTouch: true, isMobile: true }, "dark"],
  ];
  for (const [name, opts, scheme] of runs) if (!ONLY || ONLY === `${name}-${scheme}`) await run(name, opts, scheme);
  console.log("canvas_docs: all checks passed");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
