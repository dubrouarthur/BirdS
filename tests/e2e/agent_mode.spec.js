// Mode Agent in the browser, on the demo server (scripted team, no model).
//   .venv/bin/python scripts/serve.py --demo --port 9071 &
//   BIRD_URL=http://127.0.0.1:9071/ SHOTS=/tmp/shots node tests/e2e/agent_mode.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const { chromium, devices } = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9071/";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");
const DECK =
  "Fais une présentation de 6 diapos sur l'évolution du télétravail en France depuis 2019 avec des chiffres sourcés";
const CONFIGS = [
  { name: "iphone14-light", ...devices["iPhone 14"], colorScheme: "light" },
  { name: "iphone14-dark", ...devices["iPhone 14"], colorScheme: "dark" },
  {
    name: "desktop-light",
    viewport: { width: 1440, height: 900 },
    colorScheme: "light",
  },
  {
    name: "desktop-dark",
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
  },
];

function check(cond, what) {
  if (!cond) throw new Error(`FAILED: ${what}`);
  console.log(`  ok  ${what}`);
}

async function send(page, text) {
  await page.fill("#composer-input", text);
  await page.press("#composer-input", "Enter");
}

async function idle(page) {
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
  await page.waitForFunction(
    () => !document.querySelector('.turn-bird[aria-busy="true"]'),
    null,
    { timeout: 60000 },
  );
}

async function noHorizontalScroll(page, what) {
  const [sw, cw] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  check(sw <= cw + 1, `${what}: no horizontal scroll (${sw} <= ${cw})`);
}

async function newConversation(page) {
  const narrow = await page.evaluate(() => innerWidth < 900);
  await page.click(narrow ? "#btn-new-top" : "#btn-new");
  await page.waitForTimeout(200);
}

async function run(cfg) {
  console.log(cfg.name);
  const { name, ...options } = cfg;
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
  await page.waitForTimeout(300);

  // 1. the control shows Auto by default
  check(
    (await page.inputValue("#agent-mode")) === "auto",
    "composer control defaults to Auto",
  );
  await page.screenshot({ path: path.join(SHOTS, `${name}-0-composer.png`) });

  // 2. the deck request starts the team: chip, two parallel drafts, the version kept, the file, the folded line
  await send(page, DECK);
  await page.waitForSelector(".crew-chip .crew-title", { timeout: 15000 });
  check(
    (await page.textContent(".crew-chip .crew-title")).includes(
      "Mode Agent activé",
    ),
    "chip « Mode Agent activé »",
  );
  check(
    await page.isVisible('[data-act="agent-off"]'),
    "way-out button while the team works",
  );
  await page.waitForSelector(
    '[data-phase="drafts"] .crew-lane[data-status="running"]',
    { timeout: 20000 },
  );
  const boxes = await page.$$eval('[data-phase="drafts"] .crew-lane', (els) =>
    els
      .map((e) => e.getBoundingClientRect())
      .map((r) => ({ x: r.x, y: r.y, w: r.width })),
  );
  check(
    boxes.length === 2 &&
      Math.abs(boxes[0].y - boxes[1].y) < 2 &&
      boxes[0].x !== boxes[1].x,
    "two draft lanes side by side",
  );
  await page.screenshot({
    path: path.join(SHOTS, `${name}-1-running.png`),
    fullPage: false,
  });
  await noHorizontalScroll(page, "while running");
  await page.waitForSelector('[data-lane="verificateur"][data-status="done"]', {
    timeout: 30000,
  });
  const kept = await page.textContent(
    '[data-lane="verificateur"] .crew-detail',
  );
  check(
    /retenue/.test(kept),
    `checker lane shows « retenue » (${kept.trim()})`,
  );
  const drafts = await page.$$eval('[data-phase="drafts"] .crew-lane', (els) =>
    els.map((e) => e.dataset.status),
  );
  check(
    drafts.every((s) => s === "done"),
    "both drafts reached done",
  );
  await page.screenshot({ path: path.join(SHOTS, `${name}-2-checked.png`) });
  await idle(page);
  check(await page.isVisible(".turn-bird .cards"), "file card shown");
  const line = await page.textContent(".crew-fold > summary .crew-sum-text");
  check(
    /^Équipe : \d+ agents/.test(line),
    `board folded to one line (${line})`,
  );
  check(
    !(await page.isVisible('[data-act="agent-off"]')),
    "way-out button gone once done",
  );
  await page.screenshot({
    path: path.join(SHOTS, `${name}-3-done.png`),
    fullPage: true,
  });
  await page.click(".crew-fold > summary");
  await page.waitForTimeout(200);
  check(
    await page.isVisible('.crew-fold[open] [data-phase="drafts"]'),
    "folded line expands on click",
  );
  await page
    .locator(".crew")
    .screenshot({ path: path.join(SHOTS, `${name}-4-expanded.png`) });
  await noHorizontalScroll(page, "done, expanded");

  // 3. « Bonjour »: no team
  await newConversation(page);
  await send(page, "Bonjour");
  await idle(page);
  check((await page.$$(".crew-chip")).length === 0, "no chip on « Bonjour »");

  // 4. the way out: stop the team, resend in simple mode
  await newConversation(page);
  await send(page, DECK);
  await page.waitForSelector('[data-act="agent-off"]', { timeout: 15000 });
  await page.waitForTimeout(800);
  await page.click('[data-act="agent-off"]');
  await page.waitForTimeout(500);
  await idle(page);
  check(
    (await page.$$(".crew")).length === 0,
    "after « Revenir au mode simple »: no lanes",
  );
  check(
    await page.isVisible(".turn-bird .cards"),
    "single-agent answer with its file",
  );
  check(
    (await page.inputValue("#agent-mode")) === "auto",
    "composer setting unchanged (Auto)",
  );
  await page.screenshot({ path: path.join(SHOTS, `${name}-5-simple.png`) });

  // 4b. Stop while the drafts run: the running lanes read « arrêté » (grey), never a red failure
  await newConversation(page);
  await send(page, DECK);
  await page.waitForSelector(
    '[data-phase="drafts"] .crew-lane[data-status="running"]',
    { timeout: 20000 },
  );
  await page.click("#btn-stop");
  await idle(page);
  await page
    .locator(".crew-fold > summary")
    .click()
    .catch(() => {});
  const after = await page.$$eval(".crew-lane", (els) =>
    els.map((e) => e.dataset.status),
  );
  check(
    after.includes("stopped") && !after.includes("error"),
    `after Stop: lanes stopped, none in error (${after.join(",")})`,
  );

  // 5. Désactivé: no team on the same request
  await newConversation(page);
  await page.selectOption("#agent-mode", "off");
  await send(page, DECK);
  await idle(page);
  check((await page.$$(".crew-chip")).length === 0, "Désactivé: no chip");
  await page.selectOption("#agent-mode", "auto");
  check(errors.length === 0, `no page error (${errors.join(" | ")})`);
  await browser.close();
}

// The Send button stays inside the composer with text typed, at 320, 390 and 430 px, and the Agent pill keeps its
// label (« AGENT » over the value) and its ✦ icon.
async function composerFits() {
  console.log("composer widths");
  const browser = await chromium.launch();
  for (const width of [320, 390, 430]) {
    const ctx = await browser.newContext({
      ...devices["iPhone 14"],
      viewport: { width, height: 760 },
      locale: "fr-FR",
    });
    const page = await ctx.newPage();
    await page.goto(URL);
    await page
      .locator("#welcome-start")
      .click({ timeout: 4000 })
      .catch(() => {});
    for (const text of ["Bonjour, peux-tu m'aider ?", "x".repeat(2500)]) {
      await page.fill("#composer-input", text);
      await page.waitForTimeout(150);
      const g = await page.evaluate(() => {
        const r = (s) => document.querySelector(s).getBoundingClientRect();
        const vis = (s) => r(s).width > 2;
        return {
          send: r("#btn-send"),
          box: r("#composer"),
          label: vis(".agent-pill-label"),
          icon: vis("#agent-pill .icon"),
        };
      });
      check(
        g.send.right <= g.box.right - 1 && g.send.left >= g.box.left,
        `${width} px, ${text.length} chars: Send inside the composer (${g.send.right.toFixed(1)} <= ${g.box.right.toFixed(1)})`,
      );
      check(g.label && g.icon, `${width} px: the Agent pill shows its label and ✦`);
    }
    await ctx.close();
  }
  await browser.close();
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  await composerFits();
  const only = process.argv.slice(2);
  for (const cfg of CONFIGS)
    if (!only.length || only.includes(cfg.name)) await run(cfg);
  console.log("all checks passed");
})().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
