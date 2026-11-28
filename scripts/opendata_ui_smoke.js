// Open-data cards on the demo server (real tools on recorded provider answers, no model): every card shows its
// source and licence, renders at 360 px and 1280 px, light and dark, without horizontal scroll, contacts no third
// party, and its « Pour continuer » asks start the next card.
//
//   .venv/bin/python scripts/serve.py --demo --port 9477 &
//   BIRD_URL=http://127.0.0.1:9477/ SHOTS=/tmp/odshots node scripts/opendata_ui_smoke.js [case ...]
//
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const pw = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9477/";
const SHOTS = process.env.SHOTS || path.join(process.cwd(), "opendata-shots");
const failures = [];

const CASES = {
  calendar: { ask: "jours fériés de mai 2027", sel: ".widget-calendar", source: /calendrier\.api\.gouv\.fr/, next: true },
  year: { ask: "quels sont les jours fériés en 2027 ?", sel: ".widget-calendar", source: /calendrier/, next: true },
  germany: { ask: "public holidays in Germany in 2027", sel: ".widget-calendar", source: /Nager/i, lang: "en" },
  entity: { ask: "c'est quoi l'Unesco ?", sel: ".widget-entity", source: /Wikip/ },
  stats: { ask: "le chômage en France et en Allemagne depuis 2015", sel: ".od-chart-src", source: /Eurostat/ },
  worldbank: { ask: "PIB de la France et du Japon depuis 2010", sel: ".od-chart-src", source: /Banque mondiale|World Bank/ },
  insee: { ask: "population de Roubaix depuis 1968", sel: ".od-chart-src", source: /Insee|INSEE/ },
  tenders: { ask: "appels d'offres maintenance informatique", sel: ".widget-tenders", source: /BOAMP/, next: true },
  papers: { ask: "articles scientifiques sur les batteries sodium-ion", sel: ".widget-papers", source: /OpenAlex/, next: true },
  doi: { ask: "vérifie ce DOI 10.1038/nature14539", sel: ".widget-papers", source: /Crossref/ },
  commune: { ask: "code postal de Roubaix", sel: ".widget-commune", source: /geo\.api\.gouv\.fr/, next: true },
  address: { ask: "normalise cette adresse : 20 av de segur paris", sel: ".widget-commune", source: /Adresse/ },
  // near misses: the user's own figures, leave or bids, a bare J+N, a task on their text: no open-data card at all
  "no-invoice": { ask: "Calcule J+30 sur la facture du 3 décembre", none: true },
  "no-leave": { ask: "combien de jours ouvrés de congés me reste-t-il ?", none: true },
  "no-translate": { ask: "Translate into French: public holidays in Germany in 2027", none: true, lang: "en" },
  "no-rent": { ask: "inflation de mes loyers depuis 2020", none: true },
  "no-bids": { ask: "appels d'offres que nous avons perdus en 2025", none: true },
};
const OD_CARDS = ".widget-calendar, .widget-entity, .widget-tenders, .widget-papers, .widget-commune, .od-chart-src";

function check(cond, what) {
  if (cond) return console.log(`  ok    ${what}`);
  console.log(`  FAIL  ${what}`);
  failures.push(what);
}

async function open(browser, { width, scheme, lang }) {
  const ctx = await browser.newContext({
    viewport: { width, height: 2400 }, // tall: a whole card fits above the composer in its screenshot
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
    await page.evaluate(() => {
      const p = JSON.parse(localStorage.getItem("bird.prefs") || "{}");
      localStorage.setItem("bird.prefs", JSON.stringify({ ...p, lang: "en" }));
    }).then(() => page.reload()).then(() => page.locator("#welcome-start").click({ timeout: 3000 }).catch(() => {}));
  await page.waitForTimeout(300);
  return { ctx, page };
}

async function ask(page, text) {
  await page.fill("#composer-input", text);
  await page.press("#composer-input", "Enter");
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 30000 });
  await page.waitForTimeout(400);
}

async function run(browser, name, c, width, scheme) {
  const { ctx, page } = await open(browser, { width, scheme, lang: c.lang });
  const label = `${name}-${width}-${scheme}`;
  await ask(page, c.ask);
  if (c.none) {
    check((await page.locator(OD_CARDS).count()) === 0, `${label}: no open-data card`);
    check((await page.locator(".turn, [data-turn], .msg").count()) > 0, `${label}: an answer is shown`);
    await page.screenshot({ path: path.join(SHOTS, `${label}.png`), fullPage: false });
  }
  const card = page.locator(c.sel || "#no-such-card").last();
  const shown = await card.count().then((n) => n > 0 && card.isVisible());
  if (!c.none) check(shown, `${label}: card shown`);
  if (shown) {
    const host = c.sel === ".od-chart-src" ? page.locator(".chart-card").last() : card;
    const text = await host.innerText();
    check(c.source.test(text), `${label}: source named`);
    // the source line names the provider AND links its licence: two links at least
    const foot = host.locator(".od-source, .od-chart-src").last();
    const links = await foot.locator("a[href]").count();
    check(links >= 2, `${label}: source and licence linked (${links} links)`);
    await host.scrollIntoViewIfNeeded();
    await host.screenshot({ path: path.join(SHOTS, `${label}.png`) });
    if (c.next && width === 1280 && scheme === "light") {
      const chips = page.locator(".od-next-chip");
      check((await chips.count()) >= 2, `${label}: 2-3 next asks`);
      const before = await page.locator(".widget, .chart-card").count();
      await chips.first().click();
      await page.waitForSelector("#btn-send:not([hidden])", { timeout: 30000 });
      await page.waitForTimeout(500);
      check((await page.locator(".turn, [data-turn]").count()) >= 2, `${label}: a next ask starts a new turn`);
      check((await page.locator(".widget, .chart-card").count()) > before, `${label}: the next ask shows its card`);
      await page.screenshot({ path: path.join(SHOTS, `${label}-next.png`), fullPage: false });
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
  for (const name of names) {
    console.log(name);
    for (const [width, scheme] of [[1280, "light"], [360, "dark"], [360, "light"], [1280, "dark"]])
      await run(browser, name, CASES[name], width, scheme);
  }
  await browser.close();
  console.log(failures.length ? `${failures.length} FAILED` : "all checks passed");
  process.exit(failures.length ? 1 : 0);
})();
