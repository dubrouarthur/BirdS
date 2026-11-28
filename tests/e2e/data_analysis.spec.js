// Data analysis in the browser, on the demo server (no model): a messy French CSV is attached, the harness profiles
// it and answers « quel est le CA moyen par mois ? » with a computed chart; the data card shows the columns, the
// one-click analyses and the interactive table. Then every v2 chart type is drawn in a gallery.
//   .venv/bin/python scripts/serve.py --demo --port 9233 &
//   BIRD_URL=http://127.0.0.1:9233/ SHOTS=/tmp/shots node tests/e2e/data_analysis.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: card, chips, chart and table are drawn; a chip switches the analysis; sorting and search work; a cell click
// fills the composer; no third-party request, no CSP or script error, no horizontal scroll. ONLY=<config part>.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9233/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
const CSV = path.join(__dirname, "..", "fixtures", "data", "ventes.csv");
fs.mkdirSync(OUT, { recursive: true });
const CONFIGS = [
  { name: "m360-light", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "light", isMobile: true, hasTouch: true },
  { name: "m360-dark", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "dark", isMobile: true, hasTouch: true },
  { name: "desk-light", viewport: { width: 1280, height: 900 }, colorScheme: "light" },
  { name: "desk-dark", viewport: { width: 1280, height: 900 }, colorScheme: "dark" },
]; // prettier-ignore

const months = [
  "janv. 2024",
  "févr. 2024",
  "mars 2024",
  "avr. 2024",
  "mai 2024",
  "juin 2024",
  "juil. 2024",
  "août 2024",
  "sept. 2024",
  "oct. 2024",
  "nov. 2024",
  "déc. 2024",
];
const GALLERY = [
  { type: "bar", title: "CA par région (k€)", unit: "k€", labels: ["Nord", "Sud", "Est", "Ouest", "IDF"], series: [{ name: "CA", values: [243.7, 193.2, 173.5, 193.1, 176.9] }], annotations: [{ kind: "target", value: 200, label: "objectif" }] },
  { type: "bar", title: "CA 2024 vs 2025 par région", unit: "k€", labels: ["Nord", "Sud", "Est", "Ouest", "IDF"], series: [{ name: "2024", values: [109.9, 96.3, 88.4, 98.6, 84.6] }, { name: "2025", values: [133.8, 96.9, 85.1, 94.5, 92.3] }] },
  { type: "stacked", title: "Ventes par produit et canal", unit: "k€", labels: ["Alpha", "Beta", "Gamma", "Delta"], series: [{ name: "Web", values: [80, 60, 30, 140] }, { name: "Magasin", values: [70, 50, 20, 160] }, { name: "Partenaires", values: [48, 42, 10, 103] }] },
  { type: "hbar", title: "Top 8 clients", unit: "€", labels: ["Richard Énergie", "Simon Retail", "Petit SARL", "Martin & Fils", "Dubois Logistique", "Moreau Santé", "Laurent Bâtiment", "Bernard Industries"], series: [{ name: "CA", values: [124157, 119273, 116689, 90787, 83356, 79012, 70544, 66410] }] },
  { type: "line", title: "CA mensuel 2024", unit: "€", labels: months, series: [{ name: "CA", values: [50462, 40910, 35878, 27919, 49741, 30573, 49685, 39168, 31250, 48390, 30536, 43247] }], annotations: [{ kind: "max" }, { kind: "min" }] },
  { type: "line", title: "Visites et conversions", labels: months, series: [{ name: "Visites", values: [12, 14, 13, 15, 18, 17, 16, 19, 21, 20, 22, 25] }, { name: "Leads", values: [5, 6, 6, 7, 8, 9, 8, 10, 11, 11, 12, 14] }, { name: "Ventes", values: [2, 2, 3, 3, 4, 4, 4, 5, 5, 6, 6, 7] }] },
  { type: "area", title: "Trésorerie (k€)", unit: "k€", labels: months, series: [{ name: "Trésorerie", values: [120, 132, 128, 140, 151, 149, 160, 172, 168, 180, 191, 205] }] },
  { type: "stacked_area", title: "Effectifs par site", labels: ["2021", "2022", "2023", "2024", "2025"], series: [{ name: "Paris", values: [40, 46, 52, 55, 61] }, { name: "Lyon", values: [20, 24, 25, 31, 33] }, { name: "Lille", values: [8, 10, 14, 15, 19] }] },
  { type: "scatter", title: "Prix / quantité", points: Array.from({ length: 60 }, (_, i) => [`#${i + 1}`, 20 + ((i * 37) % 290), Math.max(1, 40 - ((i * 37) % 290) / 9 + ((i * 13) % 11))]), axes: ["Prix unitaire (€)", "Quantité"], units: ["€", ""], stat: { r: -0.82, strength: "forte", n: 60 } },
  { type: "bubble", title: "Marchés : taille, croissance, marge", points: [["France", 12, 4.2, 120], ["Allemagne", 9, 3.1, 160], ["Espagne", 6, 6.5, 70], ["Italie", 5, 2.2, 80], ["Benelux", 8, 5.1, 50]], axes: ["Marge (%)", "Croissance (%)"], units: ["%", "%"] },
  { type: "pie", title: "Répartition des dépenses", unit: "%", labels: ["Salaires", "Locaux", "Marketing", "IT", "Divers"], series: [{ name: "Part", values: [52, 18, 14, 10, 6] }] },
  { type: "donut", title: "Répartition du CA par produit", unit: "€", labels: ["Delta", "Alpha", "Beta", "Zeta", "Gamma", "Epsilon"], series: [{ name: "CA", values: [403341, 198792, 152779, 113968, 79512, 31975] }] },
  { type: "histogram", title: "Distribution des montants de commande", unit: "€", labels: [], series: [], bins: { counts: [42, 88, 101, 76, 54, 38, 27, 19, 14, 9, 6, 4], lo: 0, hi: 6000 } },
  { type: "box", title: "Montant des commandes", unit: "€", labels: [], series: [], box: { min: 37.8, q1: 594.7, median: 1263.6, mean: 2042.4, q3: 2763, max: 12400, outliers: [9100, 10850, 12400] } },
  { type: "heatmap", title: "Ventes par jour et créneau", labels: ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"], series: [{ name: "Matin", values: [12, 18, 15, 20, 26, 40] }, { name: "Midi", values: [30, 28, 33, 35, 44, 52] }, { name: "Après-midi", values: [22, 25, 21, 27, 38, 61] }, { name: "Soir", values: [8, 9, 11, 13, 24, 35] }] },
  { type: "waterfall", title: "Du CA au résultat (k€)", unit: "k€", labels: ["CA", "Achats", "Salaires", "Loyer", "Marketing", "Autres"], series: [{ name: "Montant", values: [980, -410, -290, -60, -75, -38] }] },
  { type: "funnel", title: "Entonnoir de conversion", labels: ["Visiteurs", "Inscrits", "Essai", "Clients", "Fidèles"], series: [{ name: "Personnes", values: [12000, 3400, 1200, 420, 260] }] },
  { type: "combo", title: "CA et marge (%)", labels: ["T1", "T2", "T3", "T4"], series: [{ name: "CA (k€)", values: [127, 108, 120, 122], unit: "k€", mark: "bar" }, { name: "Marge (%)", values: [31, 28, 33, 35], unit: "%", mark: "line", axis: "y2" }] },
  { type: "kpi", title: "CA total 2025", unit: "€", labels: ["2025"], series: [{ name: "CA total 2025", values: [502602] }], kpi: { value: 502602, label: "CA total 2025 · +5,2 % vs 2024", spark: [37901, 47802, 34922, 34236, 57707, 39863, 46536, 42689, 35181, 44784, 37665, 43312] } },
]; // prettier-ignore

async function send(page, text) {
  const before = await page.locator(".turn-user").count();
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.fill("#composer-input", text);
    await page.press("#composer-input", "Enter");
    await page.waitForTimeout(1200);
    if ((await page.locator(".turn-user").count()) > before) break;
  }
  await page.waitForFunction(
    () => !document.querySelector('.turn-bird[aria-busy="true"]'),
    null,
    { timeout: 60000 },
  );
  await page.waitForTimeout(500);
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
    await page.waitForTimeout(1000);
    await page.setInputFiles("#file-input", CSV);
    await page.waitForTimeout(500);
    await send(page, "quel est le CA moyen par mois ?");
    const card = page.locator(".turn-bird").last().locator(".dk-card");
    if (!(await card.count())) {
      problems.push(`${name}: no data card`);
      await page.screenshot({
        path: path.join(OUT, `FAIL-data-${name}.png`),
        fullPage: true,
      });
      await ctx.close();
      continue;
    }
    const chips = await card.locator(".dk-chip").count();
    if (chips < 4) problems.push(`${name}: only ${chips} analysis chips`);
    if (!(await card.locator(".dk-stage .c2-card svg").count()))
      problems.push(`${name}: no chart for the asked question`);
    if (!(await card.locator(".dk-body .dk-row").count()))
      problems.push(`${name}: the table has no rows`);
    const [sw, cw] = await page.evaluate(() => [
      document.documentElement.scrollWidth,
      document.documentElement.clientWidth,
    ]);
    if (sw > cw + 1) problems.push(`${name}: horizontal scroll ${sw} > ${cw}`);
    const vp = page.viewportSize();
    await page.setViewportSize({ width: vp.width, height: 3200 });
    await page.waitForTimeout(400);
    await card.screenshot({ path: path.join(OUT, `datacard-${name}.png`) });
    // a chip: the donut of the shares
    await card.locator(".dk-chip", { hasText: /Répartition/ }).click();
    await page.waitForTimeout(300);
    await card
      .locator(".dk-stage")
      .screenshot({ path: path.join(OUT, `datacard-share-${name}.png`) });
    // sort the CA column (loads the full table), search
    await card.locator(".dk-sort", { hasText: "CA (€)" }).click();
    await page.waitForTimeout(600);
    const firstCa = await card
      .locator(".dk-body .dk-row")
      .first()
      .locator(".dk-cell")
      .nth(8)
      .innerText();
    if (!/\d/.test(firstCa))
      problems.push(
        `${name}: sorted table has no CA in the first row (${firstCa})`,
      );
    await card.locator(".dk-search").first().fill("Delta");
    await page.waitForTimeout(300);
    const count = await card.locator(".dk-count").innerText();
    if (!/sur/.test(count))
      problems.push(`${name}: search did not filter (${count})`);
    await card
      .locator(".dk-table")
      .screenshot({ path: path.join(OUT, `datacard-table-${name}.png`) });
    await card
      .locator(".dk-body .dk-row")
      .first()
      .locator(".dk-cell")
      .nth(2)
      .click();
    const composed = await page.inputValue("#composer-input");
    if (!/ligne \d+/.test(composed))
      problems.push(
        `${name}: a cell click did not fill the composer (${composed})`,
      );
    await page.fill("#composer-input", "");
    // ---- « Modifier le graphique »: 2-3 edits; a click sends one, the next turn re-shows the updated chart
    await card.locator(".dk-chip.is-asked").click();
    await page.waitForTimeout(200);
    if (!(await card.locator(".dk-stage .c2-card").count())) await card.locator(".dk-chip.is-asked").click();
    const nexts = await card.locator(".dk-next-chip").count();
    if (nexts < 2 || nexts > 3) problems.push(`${name}: ${nexts} « Modifier le graphique » chips`);
    if (!(await card.locator(".dk-stage details, .dk-stage .c2-data").count()))
      problems.push(`${name}: no data table alternative under the chart`);
    const turns = await page.locator(".turn-bird").count();
    await card.locator(".dk-next-chip", { hasText: "Par trimestre" }).click();
    await page.waitForFunction((n) => document.querySelectorAll(".turn-bird").length > n &&
      !document.querySelector('.turn-bird[aria-busy="true"]'), turns, { timeout: 60000 }); // prettier-ignore
    await page.waitForTimeout(600);
    const card2 = page.locator(".turn-bird").last().locator(".dk-card");
    if (!(await card2.locator(".dk-version", { hasText: "Version 2" }).count()))
      problems.push(`${name}: the follow-up card has no « Version 2 »`);
    const bars = await card2.locator(".dk-stage .c2-card svg .c2-mark").count();
    if (bars < 8) problems.push(`${name}: the quarterly chart has ${bars} marks`);
    if (!(await card2.locator(".dk-fold").count())) problems.push(`${name}: the table is not folded in the follow-up`);
    if ((await card2.locator(".dk-next-chip").count()) < 2) problems.push(`${name}: no next steps after the edit`);
    await card2.screenshot({ path: path.join(OUT, `datacard-v2-${name}.png`) });
    await page.setViewportSize(vp);
    // ---- gallery of every chart type
    await page.evaluate(async (specs) => {
      const { renderChart2 } = await import("/static/charts2.js");
      const box = document.createElement("div");
      box.id = "c2-gallery";
      box.className = "cards";
      box.style.cssText =
        "display:grid;gap:14px;padding:12px;background:var(--bg)";
      // the app stays in the page (its handlers keep their elements): hidden under the gallery
      for (const el of document.body.children) el.style.display = "none";
      document.body.append(box);
      for (const sp of specs) {
        const el = renderChart2(
          {
            v: 2,
            source: "analysis",
            source_label: "ventes.csv",
            alts: [sp.type],
            x: { name: "", kind: "category" },
            annotations: [],
            ...sp,
          },
          { lang: "fr" },
        );
        if (el) box.append(el);
      }
    }, GALLERY);
    await page.waitForTimeout(600);
    const drawn = await page.locator("#c2-gallery .c2-card svg").count();
    if (drawn < GALLERY.length)
      problems.push(`${name}: gallery drew ${drawn}/${GALLERY.length}`);
    const cards = page.locator("#c2-gallery .c2-card");
    for (let i = 0; i < GALLERY.length; i++)
      await cards
        .nth(i)
        .screenshot({
          path: path.join(
            OUT,
            `chart-${GALLERY[i].type}${GALLERY.slice(0, i).some((g) => g.type === GALLERY[i].type) ? "-2" : ""}-${name}.png`,
          ),
        });
    const [gsw, gcw] = await page.evaluate(() => [
      document.documentElement.scrollWidth,
      document.documentElement.clientWidth,
    ]);
    if (gsw > gcw + 1)
      problems.push(`${name}: gallery horizontal scroll ${gsw} > ${gcw}`);
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.log(problems.join("\n"));
    process.exit(1);
  }
  console.log(
    "ok: data card, analyses, table and every chart type drawn; no third-party request, no CSP error, no overflow",
  );
})();
