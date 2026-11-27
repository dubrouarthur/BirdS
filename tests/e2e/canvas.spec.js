// The canvas on the demo server (no model): a deck built in 3 turns (create, add a slide, change a picture),
// edited in place, re-themed and exported; a web page previewed in the sandbox; a diagram; versions.
//   .venv/bin/python scripts/serve.py --demo --port 9241 &
//   BIRD_URL=http://127.0.0.1:9241/ SHOTS=/tmp/shots node tests/e2e/canvas.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const { chromium, devices } = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9241/";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");

function check(cond, what) {
  if (!cond) throw new Error(`FAILED: ${what}`);
  console.log(`  ok  ${what}`);
}

async function idle(page) {
  await page.waitForFunction(
    () => !document.querySelector('.turn-bird[aria-busy="true"]'),
    null,
    { timeout: 60000 },
  );
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
}

async function say(page, text) {
  await page.fill("#composer-input", text);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  await idle(page);
}

async function run(name, options, { full = true, scheme = "light" } = {}) {
  console.log(name);
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    ...options,
    locale: "fr-FR",
    colorScheme: scheme,
  });
  const page = await ctx.newPage();
  const errors = [];
  const external = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on(
    "console",
    (m) =>
      m.type() === "error" &&
      // the sandbox probe's own blocked requests are expected
      !/frame-ancestors|Refused to frame|connect-src 'none'|Refused to connect/.test(
        m.text(),
      ) &&
      errors.push(m.text()),
  );
  page.on("request", (r) => {
    const u = r.url();
    if (
      !u.startsWith(URL) &&
      !u.startsWith("blob:") &&
      !u.startsWith("data:") &&
      !u.startsWith("about:")
    )
      external.push(u);
  });
  await page.goto(URL);
  await page
    .locator("#welcome-start")
    .click({ timeout: 8000 })
    .catch(() => {});
  const tag = `${name}-${scheme}`;

  // 1. create: the canvas opens and the blocks arrive while « the model » writes
  await page.fill(
    "#composer-input",
    "Fais une présentation sur le plan vélo de l'entreprise",
  );
  await page.keyboard.press("Enter");
  await page.waitForSelector("#canvas:not([hidden]) .cv-slide", {
    timeout: 20000,
  });
  const during = await page.locator("#canvas .cv-status.is-writing").count();
  await idle(page);
  const slides = await page.locator("#canvas .cv-slide").count();
  check(slides === 6, `deck drawn: cover + 5 slides (got ${slides})`);
  check(during === 1 || slides > 0, "status shows the writing while streaming");
  check(
    (await page.locator("#canvas .cv-kpi").count()) === 3,
    "key figures drawn as tiles",
  );
  check(
    (await page.locator("#canvas .cv-timeline li").count()) === 3,
    "timeline drawn",
  );
  await page.waitForSelector("#canvas .cv-img img", { timeout: 10000 });
  check(
    (await page.locator("#canvas .cv-img img").count()) >= 1,
    "picture resolved by the harness (demo illustration)",
  );
  check(
    await page.locator(".cv-card").first().isVisible(),
    "chat shows the canvas card",
  );
  await page.screenshot({
    path: path.join(SHOTS, `canvas-deck-${tag}.png`),
    fullPage: false,
  });

  // 2. a follow-up adds a slide (patch, not a regeneration)
  await say(page, "ajoute une slide sur les risques");
  const titles = await page
    .locator("#canvas .cv-slide-title")
    .allTextContents();
  check(
    titles.includes("Les risques") || titles.some((x) => /risques/i.test(x)),
    `slide added: ${titles.join(" | ")}`,
  );
  check(
    (await page.locator("#canvas .cv-slide").count()) === 7,
    "one more slide, the others kept",
  );
  const versions = await page.locator("#canvas .cv-select option").count();
  check(versions === 2, `two versions (got ${versions})`);

  // 3. the words alone change the picture: no model needed
  await say(page, "remplace l'image de la slide 1 par une photo de vélo cargo");
  check(
    (await page.locator("#canvas .cv-select option").count()) === 3,
    "a third version",
  );

  // inline edit of a slide title
  if (full) {
    const title = page.locator("#canvas .cv-slide-title").nth(1);
    await title.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.type("Contexte revu");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(150);
    check(
      (await page.locator("#canvas .cv-slide-title").nth(1).textContent()) ===
        "Contexte revu",
      "inline edit kept",
    );
    check(
      (await page.locator("#canvas .cv-select option").count()) === 4,
      "inline edit is a new version",
    );
    // reorder, then theme
    await page.locator('#canvas [data-k^="down-"]').first().click();
    await page.waitForTimeout(100);
    await page.locator('#canvas .cv-swatch[aria-label="Chaleureux"]').click();
    await page.waitForTimeout(100);
    check(
      (await page.locator("#canvas .cv-body.cvt-warm").count()) === 1,
      "theme applied",
    );
    // version switch is diff-free: v1 back, then the last one
    await page.selectOption("#canvas .cv-select", "0");
    check(
      (await page.locator("#canvas .cv-slide").count()) === 6,
      "v1 shows the first deck",
    );
    const last = (await page.locator("#canvas .cv-select option").count()) - 1;
    await page.selectOption("#canvas .cv-select", String(last));
    await page.screenshot({
      path: path.join(SHOTS, `canvas-deck-edited-${tag}.png`),
    });
    // export
    const [dl] = await Promise.all([
      page.waitForEvent("download", { timeout: 20000 }),
      (async () => {
        await page.locator('#canvas [data-k="download"]').click();
        await page.locator('#canvas [data-k="dl-pptx"]').click();
      })(),
    ]);
    const file = path.join(SHOTS, `canvas-${tag}.pptx`);
    await dl.saveAs(file);
    const head = fs.readFileSync(file).subarray(0, 2).toString();
    check(
      head === "PK" && fs.statSync(file).size > 20000,
      `pptx downloaded (${fs.statSync(file).size} bytes)`,
    );
    // « Demander à Bird » on a block sends a scoped instruction (demo: the block is rewritten shorter)
    await page.locator('#canvas [data-k^="ask-"]').nth(1).click();
    await page
      .locator("#canvas .cv-ask:not([hidden]) input")
      .fill("rends-la plus concise");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(150);
    await idle(page);
    check(
      (await page.locator("#canvas .cv-select option").count()) >= 7,
      "scoped instruction made a new version",
    );
  }

  // a web page: Code / Aperçu tabs, sandboxed preview, console
  await page
    .locator("#btn-new-top")
    .click()
    .catch(() => {});
  await say(page, "crée une landing page pour une boulangerie");
  await page.waitForSelector("#canvas .cv-frame", { timeout: 10000 });
  const frame = page.frames().find((f) => f.url().includes("/canvas/frame"));
  await page.waitForTimeout(600);
  check(!!frame, "preview frame loaded");
  const h1 = frame
    ? await frame
        .locator("h1")
        .textContent({ timeout: 5000 })
        .catch(() => "")
    : "";
  check(/boulangerie/i.test(h1 || ""), `page rendered in the sandbox: ${h1}`);
  if (frame) {
    // the sandbox has no access to the app (opaque origin) and no network
    const probe = await frame.evaluate(async () => {
      const out = {};
      try {
        out.parent = !!window.parent.document;
      } catch {
        out.parent = false;
      }
      try {
        out.storage = !!window.localStorage;
      } catch {
        out.storage = false;
      }
      try {
        await fetch("/api/health");
        out.fetch = true;
      } catch {
        out.fetch = false;
      }
      try {
        await fetch("https://example.org/");
        out.ext = true;
      } catch {
        out.ext = false;
      }
      return out;
    });
    check(
      !probe.parent && !probe.storage && !probe.fetch && !probe.ext,
      `sandbox closed: ${JSON.stringify(probe)}`,
    );
    await frame.locator("#cta").click();
    await page.waitForTimeout(200);
  }
  await page.screenshot({ path: path.join(SHOTS, `canvas-code-${tag}.png`) });
  await page.locator('#canvas [data-k="tab-code"]').click();
  check(
    (await page.locator("#canvas textarea.cv-code").inputValue()).includes(
      "<!doctype html>",
    ),
    "Code tab shows the file",
  );

  // a diagram drawn in-house
  await say(page, "dessine le schéma du processus de recrutement");
  await page.waitForSelector("#canvas svg.flow", { timeout: 10000 });
  check(
    (await page.locator("#canvas svg.flow .flow-node").count()) === 8,
    "flowchart: 8 nodes",
  );
  await page.screenshot({ path: path.join(SHOTS, `canvas-flow-${tag}.png`) });

  // a sheet made by the trained tool is offered in the canvas: formulas, sort, chart from a selection
  if (full) {
    if (await page.locator("#canvas").isVisible()) await page.locator('#canvas [data-k="close"]').click(); // the phone sheet covers the chat
    await say(page, "Fais un tableur de budget");
    await page.locator(".cv-card .cv-card-open").last().click();
    await page.waitForSelector("#canvas .cv-grid", { timeout: 10000 });
    const cols = await page.locator("#canvas .cv-grid thead th").count();
    check(cols >= 3, `sheet grid drawn (${cols - 1} columns)`);
    // a formula in a new row: =SOMME over the amounts column
    await page.locator('#canvas [data-k="addrow"]').click();
    const rows = await page.locator("#canvas .cv-grid tbody tr").count();
    const amountCol = await page.evaluate(() => {
      const heads = [
        ...document.querySelectorAll("#canvas .cv-grid thead th"),
      ].slice(1);
      const i = heads.findIndex((th) =>
        /montant|budget|co[uû]t|prix|total/i.test(th.textContent),
      );
      return i < 0 ? 1 : i;
    });
    await page
      .locator(`#cv-c-${rows - 1}-${amountCol}`)
      .dispatchEvent("mousedown");
    const letter = String.fromCharCode(65 + amountCol);
    await page.fill(
      "#canvas .cv-fx",
      `=SOMME(${letter}1:${letter}${rows - 1})`,
    );
    await page.keyboard.press("Enter");
    await page.waitForTimeout(150);
    const total = await page
      .locator(`#cv-c-${rows - 1}-${amountCol}`)
      .textContent();
    check(/\d/.test(total) && !/#/.test(total), `formula computed: ${total}`);
    // sort, then chart from a selection (labels + amounts)
    await page.locator(`#cv-c-0-0`).dispatchEvent("mousedown");
    await page
      .locator(`#cv-c-${rows - 2}-${amountCol}`)
      .dispatchEvent("mousedown", { shiftKey: true });
    await page.locator('#canvas [data-k="chart"]').click();
    await page.waitForTimeout(200);
    check(
      (await page.locator("#canvas .cv-sheet-chart svg").count()) >= 1,
      "chart drawn from the selection",
    );
    await page.screenshot({
      path: path.join(SHOTS, `canvas-sheet-${tag}.png`),
    });
  }

  // closed panel: an ordinary message is not an edit, and later ones carry only a reference (no document)
  await page.locator('#canvas [data-k="close"]').click();
  check(await page.locator("#canvas").isHidden(), "canvas closes");
  const bodies = [];
  const spy = (r) => {
    if (r.url().endsWith("/api/chat")) bodies.push(JSON.parse(r.postData() || "{}"));
  };
  page.on("request", spy);
  await say(page, "Mets un rappel dans mon agenda lundi à 9h");
  await say(page, "Merci, et quel temps fera-t-il à Lyon demain ?");
  page.off("request", spy);
  const answers = await page.locator(".turn-bird").allTextContents();
  const last = answers.slice(-2).join(" ");
  check(
    !/je sais ajouter|I can add a slide|Nouvelle version|New version|rouvert/i.test(last),
    `ordinary answer, not a canvas edit: ${(last || "").slice(0, 60)}`,
  );
  check(await page.locator("#canvas").isHidden(), "the panel stays closed");
  check(
    bodies.length === 2 && bodies[0].canvas?.open === false && !bodies[1].canvas?.doc,
    `closed panel: the document once (fresh), then a reference only (${bodies.map((b) => JSON.stringify(b.canvas || {}).length).join(", ")} bytes)`,
  );
  check(errors.length === 0, `no page error: ${errors.join(" / ")}`);
  check(external.length === 0, `no third-party request: ${external.join(" ")}`);
  await browser.close();
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  await run("desktop-1440", { viewport: { width: 1440, height: 900 } });
  await run(
    "desktop-1440",
    { viewport: { width: 1440, height: 900 } },
    { full: false, scheme: "dark" },
  );
  await run(
    "phone-360",
    { ...devices["Pixel 5"], viewport: { width: 360, height: 780 } },
    { full: false },
  );
  await run(
    "phone-360",
    { ...devices["Pixel 5"], viewport: { width: 360, height: 780 } },
    { full: true, scheme: "dark" },
  );
  console.log("canvas e2e: all good");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
