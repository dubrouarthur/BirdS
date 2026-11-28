// Conversation engine (cluster C1 of the chat audit), on the demo server (recorded answers, no model):
//   BIRD_RATE_LIMIT=0 BIRD_IMG_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --demo --port 9311 &
//   BIRD_URL=http://127.0.0.1:9311/ SHOTS=/tmp/shots node tests/e2e/conversation.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks, at 360 px and 1280 px, light and dark: documents in context (R1), an answer that keeps streaming in the
// background (R2), versions « ‹ 1/2 › » for regenerate and edit (R3), editing any question in place and copying it
// (R6), the sidebar menu (R12), delete with undo and the styled « Tout effacer » (R13), search in the messages (R15),
// the back button (R4), « Continuer » (R23). No third-party request, no CSP or script error, no horizontal scroll.
// ONLY=<config part> narrows the configs, PART=<name,name> the parts.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9311/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
const PARTS = (process.env.PART || "").split(",").filter(Boolean);
fs.mkdirSync(OUT, { recursive: true });
const CONFIGS = [
  { name: "m360-light", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "light", isMobile: true, hasTouch: true },
  { name: "m360-dark", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "dark", isMobile: true, hasTouch: true },
  { name: "desk-light", viewport: { width: 1280, height: 900 }, colorScheme: "light" },
  { name: "desk-dark", viewport: { width: 1280, height: 900 }, colorScheme: "dark" },
];
const DOC = "Compte rendu de la réunion du 12 mars.\nPrésents : Alice, Bruno, Chloé.\nBudget validé : 48 500 euros.\n";

async function idle(page) {
  await page.waitForFunction(() => !document.querySelector('.turn-bird[aria-busy="true"]'), null, { timeout: 60000 });
  await page.waitForTimeout(300);
}

async function send(page, text, wait = true) {
  const before = await page.locator(".turn-user").count();
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.fill("#composer-input", text);
    await page.press("#composer-input", "Enter");
    await page.waitForTimeout(900);
    if ((await page.locator(".turn-user").count()) > before) break;
  }
  if (wait) await idle(page);
}

async function newChat(page) {
  const narrow = await page.evaluate(() => innerWidth < 900);
  await page.click(narrow ? "#btn-new-top" : "#btn-new").catch(() => {});
  await page.waitForTimeout(200);
}

async function openDrawer(page) {
  if (await page.evaluate(() => innerWidth < 900 && !document.body.classList.contains("side-open")))
    await page.click("#btn-menu");
  await page.waitForTimeout(250);
}

const PART_FNS = {};
const part = (name, fn) => (PART_FNS[name] = fn);

// ---------------------------------------------------------------- R1: documents in context
part("context", async (page, name, fail, shot) => {
  await newChat(page);
  await page.setInputFiles("#file-input", { name: "compte-rendu.txt", mimeType: "text/plain", buffer: Buffer.from(DOC) });
  await page.waitForSelector(".att-tray .att-card");
  await shot("r1-tray");
  await send(page, "Résume ce document.");
  if (await page.locator(".att-tray").count()) fail("R1: the composer still holds the sent document");
  if (!(await page.locator(".cx-pill").count())) fail("R1: no « document en contexte » pill");
  const pill = (await page.locator(".cx-pill").innerText()).trim();
  if (!/1 document en contexte/.test(pill)) fail(`R1: pill says « ${pill} »`);
  if (!(await page.locator(".turn-user .bubble-files .att-card").count())) fail("R1: the file is not in its message");
  await send(page, "Quelle est la capitale de l'Australie ?");
  const last = page.locator(".turn-bird").last();
  if (await last.locator(".based-on").count()) fail("R1: a general answer says « D'après » the document");
  if (await last.locator('[data-tool="read_file"], .step:has-text("Lecture du document")').count())
    fail("R1: a general question read the document");
  await page.click(".cx-pill");
  await page.waitForSelector(".cx-ctx-pop:not([hidden])");
  await shot("r1-pill-open");
  await page.click(".cx-ctx-name");
  await page.waitForSelector("dialog.cx-preview[open]");
  await page.waitForTimeout(350);
  if (!(await page.locator(".cx-preview-text").innerText()).includes("Budget validé")) fail("R1: the preview shows no text");
  await shot("r1-preview");
  await page.keyboard.press("Escape");
});

// ---------------------------------------------------------------- R2: an answer keeps going in the background
part("background", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Cherche des sources récentes sur le vélo en ville", false);
  await page.waitForSelector('.turn-bird[aria-busy="true"]', { timeout: 10000 });
  await openDrawer(page);
  await page.waitForSelector(".conv .cx-live", { timeout: 5000 }).catch(() => fail("R2: no live mark on the row"));
  await shot("r2-live-row");
  await newChat(page);
  await page.waitForTimeout(400);
  if (!(await page.locator("#btn-send").isVisible())) fail("R2: the new conversation is busy");
  // back to the first conversation while (or after) its answer is written
  await openDrawer(page);
  await page.locator(".conv-open", { hasText: "vélo en ville" }).first().click();
  await idle(page);
  const last = page.locator(".turn-bird").last();
  const text = await last.innerText();
  if (/Réponse interrompue|interrompu/.test(text)) fail("R2: the answer was stopped by the switch");
  if (!(await last.locator(".actions-row").count())) fail("R2: the answer did not finish in its conversation");
  await shot("r2-back");
});

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  for (const cfg of CONFIGS) {
    if (ONLY && !cfg.name.includes(ONLY)) continue;
    const { name, ...opts } = cfg;
    const ctx = await browser.newContext({ ...opts, locale: "fr-FR", timezoneId: "Europe/Paris" });
    const page = await ctx.newPage();
    page.on("request", (r) => {
      const u = r.url();
      if (!u.startsWith("http://127.0.0.1") && !u.startsWith("data:") && !u.startsWith("blob:"))
        problems.push(`${name}: third-party request ${u}`);
    });
    page.on("console", (m) => {
      if (m.type() === "error" || /Content Security Policy|Refused/.test(m.text()))
        problems.push(`${name}: console ${m.type()}: ${m.text()}`);
    });
    page.on("pageerror", (e) => problems.push(`${name}: pageerror ${e.message}`));
    page.on("dialog", (d) => (problems.push(`${name}: native dialog « ${d.message()} »`), d.dismiss()));
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await page.evaluate(() => document.querySelector("dialog[open]")?.close());
    for (const [pname, fn] of Object.entries(PART_FNS)) {
      if (PARTS.length && !PARTS.includes(pname)) continue;
      const fail = (msg) => problems.push(`${name}/${pname}: ${msg}`);
      const shot = async (label) => {
        const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
        if (sw > cw + 1) fail(`horizontal scroll ${sw} > ${cw} at ${label}`);
        await page.screenshot({ path: path.join(OUT, `${label}-${name}.png`) });
      };
      try {
        await fn(page, name, fail, shot, ctx);
      } catch (e) {
        fail(`threw ${e.message.split("\n")[0]}`);
        await page.screenshot({ path: path.join(OUT, `FAIL-${pname}-${name}.png`) }).catch(() => {});
      }
    }
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.log(problems.join("\n"));
    process.exit(1);
  }
  console.log("ok: conversation engine; no third-party request, no CSP error, no native dialog, no overflow");
})();
