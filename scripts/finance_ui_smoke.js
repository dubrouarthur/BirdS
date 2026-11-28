// The quote card on a server (the demo replays recorded CoinGecko and ECB answers; a live server uses the real
// endpoint): card and chart shown, figure dated, change said with a sign and an arrow, source and licence linked,
// period chips and « Pour continuer » asks re-draw the updated chart (continuity), 360 px and 1280 px, light and dark,
// no horizontal scroll, no third-party request, no CSP error. The near misses show no quote card.
//
//   BIRD_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --demo --port 9481 &
//   BIRD_URL=http://127.0.0.1:9481/ SHOTS=/tmp/finshots node scripts/finance_ui_smoke.js [case ...]
//
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const pw = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9481/";
const SHOTS = process.env.SHOTS || path.join(process.cwd(), "finance-shots");
const TIMEOUT = Number(process.env.TURN_TIMEOUT || 60000);
const failures = [];

const CASES = {
  bitcoin: { ask: "cours du bitcoin", source: /CoinGecko/, chips: true },
  compare: { ask: "compare bitcoin et ethereum sur 6 mois", source: /CoinGecko/, compare: true },
  euro: { ask: "évolution de l'euro dollar sur 6 mois", source: /BCE/, chips: true },
  english: { ask: "bitcoin price over the past year", source: /CoinGecko/, lang: "en" },
  // near misses: a lesson, a task, a product: no quote card
  "no-lesson": { ask: "cours de piano à Lyon le samedi", none: true },
  "no-task": { ask: "plan d'action commercial pour 2027", none: true },
  "no-product": { ask: "prix de l'iPhone 16", none: true },
};

function check(cond, what) {
  if (cond) return console.log(`  ok    ${what}`);
  console.log(`  FAIL  ${what}`);
  failures.push(what);
}

async function open(browser, { width, scheme, lang }) {
  const ctx = await browser.newContext({
    viewport: { width, height: 2000 },
    colorScheme: scheme,
    locale: lang === "en" ? "en-GB" : "fr-FR",
    deviceScaleFactor: width < 500 ? 2 : 1,
  });
  const page = await ctx.newPage();
  page.errors = [];
  page.thirdParty = [];
  page.csp = [];
  page.on("pageerror", (e) => page.errors.push(String(e)));
  page.on("console", (m) => /Content Security Policy|Refused to/.test(m.text()) && page.csp.push(m.text()));
  page.on("request", (r) => {
    const u = new globalThis.URL(r.url());
    if (!["127.0.0.1", "localhost"].includes(u.hostname) && !u.protocol.startsWith("data") && u.protocol !== "blob:")
      page.thirdParty.push(r.url());
  });
  await page.goto(URL);
  await page.locator("#welcome-start").click({ timeout: 6000 }).catch(() => {});
  if (lang === "en")
    await page
      .evaluate(() => {
        const p = JSON.parse(localStorage.getItem("bird.prefs") || "{}");
        localStorage.setItem("bird.prefs", JSON.stringify({ ...p, lang: "en" }));
      })
      .then(() => page.reload())
      .then(() => page.locator("#welcome-start").click({ timeout: 3000 }).catch(() => {}));
  await page.waitForTimeout(300);
  return { ctx, page };
}

async function waitTurn(page) {
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: TIMEOUT });
  await page.waitForTimeout(500);
}

async function ask(page, text) {
  await page.fill("#composer-input", text);
  await page.press("#composer-input", "Enter");
  await waitTurn(page);
}

async function run(browser, name, c, width, scheme) {
  const { ctx, page } = await open(browser, { width, scheme, lang: c.lang });
  const label = `${name}-${width}-${scheme}`;
  await ask(page, c.ask);
  const card = page.locator(".widget-quote").last();
  if (c.none) {
    check((await page.locator(".widget-quote").count()) === 0, `${label}: no quote card`);
    await page.screenshot({ path: path.join(SHOTS, `${label}.png`), fullPage: false });
  } else {
    const shown = (await card.count()) > 0 && (await card.isVisible());
    check(shown, `${label}: quote card shown`);
    if (shown) {
      const text = await card.innerText();
      check(c.source.test(text), `${label}: source named`);
      check((await card.locator(".fin-source a[href]").count()) >= 2, `${label}: source and licence linked`);
      check(/Clôture du|Cours du|Taux de référence|Close of|Price on|ECB reference/.test(text), `${label}: figure dated`);
      check(!/temps réel(?! )|en temps réel|real time(?!\b)/i.test(text.replace(/pas en temps réel|not real time/gi, "")),
            `${label}: never « real time »`); // prettier-ignore
      check((await card.locator(".fin-change .fin-arrow").count()) >= 1, `${label}: change has an arrow`);
      check(/[+−]\d/.test(await card.locator(".fin-pct").first().innerText()), `${label}: change has a sign`);
      check((await card.locator(".fin-change .sr-only").count()) >= 1, `${label}: change said in words`);
      const chart = page.locator(".chart-card").last();
      check((await chart.count()) > 0, `${label}: history chart drawn`);
      check((await chart.locator(".od-chart-src a[href]").count()) >= 2, `${label}: chart source and licence`);
      check((await chart.locator('[data-act="chart-png"]').count()) === 1, `${label}: PNG export`);
      check((await chart.locator('[data-act="chart-csv"]').count()) === 1, `${label}: CSV export`);
      check((await chart.locator("table").count()) >= 1, `${label}: table alternative`);
      if (c.compare) check(/base 100/.test(await chart.innerText()), `${label}: rebased to 100`);
      await card.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(SHOTS, `${label}.png`), fullPage: false });
      await card.screenshot({ path: path.join(SHOTS, `${label}-card.png`) });
      await chart.screenshot({ path: path.join(SHOTS, `${label}-chart.png`) });
      if (c.chips && width === 1280 && scheme === "light") {
        // continuity: a period chip asks again, the next turn shows the updated card and chart
        const chips = card.locator(".fin-range:not([disabled])");
        check((await chips.count()) >= 2, `${label}: period chips`);
        const before = await page.locator(".widget-quote").count();
        await chips.last().click();
        await waitTurn(page);
        check((await page.locator(".widget-quote").count()) > before, `${label}: a period chip re-draws the card`);
        const pressed = await page.locator(".widget-quote").last().locator('.fin-range[aria-pressed="true"]').innerText();
        check(pressed.trim().length > 0, `${label}: the new period is the pressed chip (${pressed.trim()})`);
        const next = page.locator(".widget-quote").last().locator(".od-next-chip");
        check((await next.count()) >= 2, `${label}: 2-3 next asks`);
        const n2 = await page.locator(".chart-card").count();
        await next.first().click(); // another period or a comparison (the last one may be a conversion)
        await waitTurn(page);
        check((await page.locator(".chart-card").count()) > n2, `${label}: a next ask draws the updated chart`);
        await page.screenshot({ path: path.join(SHOTS, `${label}-next.png`), fullPage: false });
      }
    }
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check(overflow <= 1, `${label}: no horizontal scroll (${overflow}px)`);
  check(page.thirdParty.length === 0, `${label}: no third-party request ${page.thirdParty.slice(0, 2).join(" ")}`);
  check(page.csp.length === 0, `${label}: no CSP error`);
  check(page.errors.length === 0, `${label}: no page error ${page.errors.slice(0, 1).join(" ")}`);
  await ctx.close();
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await pw.chromium.launch();
  const names = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(CASES);
  const layouts = (process.env.LAYOUTS || "1280:light,360:dark,360:light,1280:dark")
    .split(",")
    .map((x) => x.split(":"))
    .map(([w, s]) => [Number(w), s]);
  for (const name of names) {
    console.log(name);
    for (const [width, scheme] of layouts) await run(browser, name, CASES[name], width, scheme);
  }
  await browser.close();
  console.log(failures.length ? `${failures.length} FAILED` : "all checks passed");
  process.exit(failures.length ? 1 : 0);
})();
