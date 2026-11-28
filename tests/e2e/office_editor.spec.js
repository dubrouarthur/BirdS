// Deck and document previews (pictures, charts, tables, themes) and the editor, on the demo server (no model).
//   .venv/bin/python scripts/serve.py --demo --port 9072 &
//   BIRD_URL=http://127.0.0.1:9072/ SHOTS=/tmp/shots node tests/e2e/office_editor.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const { chromium, devices } = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9072/";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");
const PNG = path.join(
  __dirname,
  "..",
  "..",
  "birds",
  "web",
  "static",
  "brand",
  "icon-512.png",
);

function check(cond, what) {
  if (!cond) throw new Error(`FAILED: ${what}`);
  console.log(`  ok  ${what}`);
}

async function idle(page) {
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
  await page.waitForFunction(
    () => !document.querySelector('.turn-bird[aria-busy="true"]'),
    null,
    { timeout: 60000 },
  );
}

async function run(name, options) {
  console.log(name);
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...options, locale: "fr-FR" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.goto(URL);
  await page
    .locator("#welcome-start")
    .click({ timeout: 8000 })
    .catch(() => {});
  await page.fill(
    "#composer-input",
    "Prépare une présentation pptx sur la sobriété numérique",
  );
  await page.press("#composer-input", "Enter");
  await idle(page);
  await page.waitForSelector(".deck-stage .slide-canvas", { timeout: 20000 });
  check(
    (await page.locator(".deck-thumb").count()) >= 7,
    "agenda and closing slides are in the preview",
  );
  fs.mkdirSync(SHOTS, { recursive: true });
  await page
    .locator(".file-card")
    .first()
    .screenshot({ path: path.join(SHOTS, `${name}-deck.png`) });
  const edit = page.locator(".deck .office-edit-btn");
  check((await edit.count()) === 1, "the deck preview has an Edit button");
  await edit.click();
  await page.waitForSelector("dialog.editor[open]");
  check(
    (await page.locator(".editor-item").count()) === 5,
    "the editor lists the five slides of the plan",
  );
  await page
    .locator(".editor-item input[type=text]")
    .first()
    .fill("Contexte et enjeux");
  await page.selectOption(".editor-grid select", "warm");
  await page.setInputFiles("dialog.editor input[type=file]", PNG);
  await page.waitForSelector(".editor-media img");
  await page.locator(".editor-item select").nth(1).selectOption("n1");
  await page
    .locator("dialog.editor")
    .screenshot({ path: path.join(SHOTS, `${name}-editor.png`) });
  await page.locator("dialog.editor .btn-primary").click();
  await page.waitForSelector("dialog.editor", {
    state: "detached",
    timeout: 30000,
  });
  await page.waitForTimeout(400);
  const titles = await page
    .locator(".deck-thumb")
    .evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")));
  check(
    titles.some((x) => x.includes("Contexte et enjeux")),
    "the rebuilt deck shows the edited title",
  );
  check(
    (await page.locator(".deck-film img.sh-img").count()) >= 1,
    "the added picture is drawn in the preview",
  );
  await page.locator(".deck-thumb").nth(3).click();
  await page
    .locator(".file-card")
    .first()
    .screenshot({ path: path.join(SHOTS, `${name}-deck-edited.png`) });
  const sw = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  check(sw <= 1, "no horizontal scroll");
  check(
    !errors.filter((e) => !/favicon|ERR_ABORTED/.test(e)).length,
    `no console errors ${errors.join(" | ")}`,
  );
  await browser.close();
}

(async () => {
  await run("desktop", {
    viewport: { width: 1440, height: 900 },
    colorScheme: "light",
  });
  await run("iphone", { ...devices["iPhone 14"], colorScheme: "dark" });
  console.log("all good");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
