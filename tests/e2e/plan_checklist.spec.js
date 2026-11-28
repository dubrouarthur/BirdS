// The task plan's checklist in the browser, on the demo server (recorded answers, no model): « prépare une
// présentation … et un mail … » ticks both items; with a spreadsheet asked as well, the last item is left undone
// and the turn says plainly « Partiellement fait : tableur manque. ».
//   .venv/bin/python scripts/serve.py --demo --port 9243 &
//   BIRD_URL=http://127.0.0.1:9243/ SHOTS=/tmp/shots node tests/e2e/plan_checklist.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: items ticked, the partial line, the checklist folds and unfolds with the keyboard, the live region hears
// « Fait : … », no third-party request, no CSP or script error, no horizontal scroll; screenshots at 360 px and
// 1440 px, light and dark (look at them). ONLY=<config part> narrows.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9243/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
fs.mkdirSync(OUT, { recursive: true });
const ASKS = [
  {
    id: "complete",
    text: "Prépare une présentation sur la sobriété numérique et un mail pour l'annoncer à l'équipe.",
    done: 2,
    total: 2,
    partial: false,
  },
  {
    id: "partial",
    text: "Prépare une présentation sur la sobriété numérique, un mail pour l'annoncer et un tableur du budget.",
    done: 2,
    total: 3,
    partial: true,
  },
];
const CONFIGS = [
  {
    name: "m360-light",
    viewport: { width: 360, height: 780 },
    deviceScaleFactor: 2,
    colorScheme: "light",
    isMobile: true,
    hasTouch: true,
  },
  {
    name: "m360-dark",
    viewport: { width: 360, height: 780 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
    isMobile: true,
    hasTouch: true,
  },
  {
    name: "desk-light",
    viewport: { width: 1440, height: 900 },
    colorScheme: "light",
  },
  {
    name: "desk-dark",
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
  },
];

async function send(page, text) {
  const before = await page.locator(".turn-user").count();
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.fill("#composer-input", text);
    await page.press("#composer-input", "Enter");
    await page.waitForTimeout(1200);
    if ((await page.locator(".turn-user").count()) > before) break;
  }
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
  await page.waitForFunction(
    () => !document.querySelector('.turn-bird[aria-busy="true"]'),
    null,
    { timeout: 60000 },
  );
  await page.waitForTimeout(400);
  // a deck opens in the canvas, which covers a phone's whole screen: close it like a user to read the chat
  if (await page.evaluate(() => innerWidth < 900 && document.documentElement.classList.contains("cv-open"))) {
    await page.evaluate(() => document.querySelector('.cv-panel [data-act="close"], .cv-close')?.click());
    await page.waitForTimeout(300);
  }
}

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  for (const cfg of CONFIGS) {
    if (ONLY && !cfg.name.includes(ONLY)) continue;
    const { name, ...opts } = cfg;
    const ctx = await browser.newContext({
      ...opts,
      locale: "fr-FR",
      timezoneId: "Europe/Paris",
    });
    const page = await ctx.newPage();
    page.on("request", (r) => {
      const u = r.url();
      if (
        !u.startsWith("http://127.0.0.1") &&
        !u.startsWith("data:") &&
        !u.startsWith("blob:")
      )
        problems.push(`${name}: third-party request ${u}`);
    });
    page.on("console", (m) => {
      if (
        m.type() === "error" ||
        /Content Security Policy|Refused/.test(m.text())
      )
        problems.push(`${name}: console ${m.type()}: ${m.text()}`);
    });
    page.on("pageerror", (e) =>
      problems.push(`${name}: pageerror ${e.message}`),
    );
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    // every text the live region said during the run (it is cleared between announcements)
    await page.evaluate(() => {
      window.__said = [];
      const seen = new MutationObserver(() =>
        document
          .querySelectorAll("[aria-live]")
          .forEach(
            (el) => el.textContent && window.__said.push(el.textContent),
          ),
      );
      seen.observe(document.body, {
        subtree: true,
        childList: true,
        characterData: true,
      });
    });
    for (const ask of ASKS) {
      const narrow = await page.evaluate(() => innerWidth < 900);
      await page.click(narrow ? "#btn-new-top" : "#btn-new").catch(() => {});
      await page.waitForTimeout(150);
      await send(page, ask.text);
      const last = page.locator(".turn-bird").last();
      // a complete plan folds into the answer's one work line with the steps (chat audit R25); a partial one stays
      const plan = last.locator(ask.partial ? "details.tplan" : "details.worklog, details.tplan").first();
      if (!(await plan.count())) {
        problems.push(`${name}/${ask.id}: no checklist`);
        await page.screenshot({
          path: path.join(OUT, `FAIL-plan-${ask.id}-${name}.png`),
        });
        continue;
      }
      const done = await last.locator(".tplan-item.is-done").count();
      const total = await last.locator(".tplan-item").count();
      if (done !== ask.done || total !== ask.total)
        problems.push(`${name}/${ask.id}: ${done}/${total} ticked`);
      const missing = await last.locator(".tplan-missing").count();
      if (!!missing !== ask.partial)
        problems.push(`${name}/${ask.id}: partial line ${missing}`);
      if (ask.partial) {
        const said = (await last.locator(".tplan-missing").innerText()).trim();
        if (!/Partiellement fait : tableur manque\./.test(said))
          problems.push(`${name}/${ask.id}: « ${said} »`);
        if (!(await plan.evaluate((el) => el.open)))
          problems.push(`${name}/${ask.id}: a partial plan is folded`);
      } else if (await plan.evaluate((el) => el.open))
        problems.push(`${name}/${ask.id}: a complete plan stays open`);
      // opened, the work line keeps every row inside its box (a long detail ends in « … », it is not cut off)
      if (!ask.partial) {
        const was0 = await plan.evaluate((el) => el.open);
        if (!was0) await plan.evaluate((el) => (el.open = true));
        await page.waitForTimeout(150);
        const spill = await plan.evaluate((el) => {
          const box = el.getBoundingClientRect();
          return [...el.querySelectorAll(".work-body *")].filter((c) => {
            const r = c.getBoundingClientRect();
            return r.width > 0 && r.right > box.right + 1;
          }).length;
        });
        if (spill) problems.push(`${name}/${ask.id}: ${spill} element(s) of the work line run past its box`);
        if (!was0) await plan.evaluate((el) => (el.open = false));
        await page.waitForTimeout(150);
      }
      // keyboard: the summary is focusable and toggles the list
      await plan.locator(":scope > summary").focus();
      const was = await plan.evaluate((el) => el.open);
      await page.keyboard.press("Enter");
      await page.waitForTimeout(150);
      if ((await plan.evaluate((el) => el.open)) === was)
        problems.push(`${name}/${ask.id}: Enter did not toggle`);
      if (!was) {
        // leave it open for the screenshot
      } else {
        await page.keyboard.press("Enter");
        await page.waitForTimeout(150);
      }
      const said = await page.evaluate(() => window.__said.join(" | "));
      if (!/Fait : présentation/.test(said))
        problems.push(
          `${name}/${ask.id}: nothing read out (${said.slice(0, 200)})`,
        );
      const [sw, cw] = await page.evaluate(() => [
        document.documentElement.scrollWidth,
        document.documentElement.clientWidth,
      ]);
      if (sw > cw + 1)
        problems.push(`${name}/${ask.id}: horizontal scroll ${sw} > ${cw}`);
      const vp = page.viewportSize();
      await page.setViewportSize({ width: vp.width, height: 2200 });
      await page.waitForTimeout(300);
      await page.locator(".turn-user").last().scrollIntoViewIfNeeded();
      await page.screenshot({
        path: path.join(OUT, `plan-${ask.id}-${name}.png`),
      });
      await (ask.partial ? last.locator(".tplan-wrap") : plan)
        .screenshot({
          path: path.join(OUT, `plan-${ask.id}-${name}-crop.png`),
        });
      await page.setViewportSize(vp);
      await page.waitForTimeout(150);
    }
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.log(problems.join("\n"));
    process.exit(1);
  }
  console.log(
    "ok: checklists ticked, partial said plainly, keyboard and live region work; no third-party request, no CSP error, no overflow",
  );
})();
