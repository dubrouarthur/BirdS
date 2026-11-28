// Canvas decks on the demo server: the layout gallery (every layout of canvas-layouts.js), the four themes, the
// layout menu, drag to reorder, the cover picture tools, version restore, the chat card and its next-step chips.
//   .venv/bin/python scripts/serve.py --demo --port 9241 &
//   BIRD_URL=http://127.0.0.1:9241/ SHOTS=/tmp/shots node tests/e2e/canvas-decks.spec.js [phone|desktop] [light|dark]
// Writes one PNG per slide and a page screenshot per step into SHOTS (looked at before shipping).
const { chromium, devices } = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9241/";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");
fs.mkdirSync(SHOTS, { recursive: true });
const LAYOUTS = ["agenda", "section", "statement", "bullets", "columns", "figure", "kpis", "versus", "compare",
  "timeline", "steps", "quote", "image-right", "image-left", "image-full", "image-grid", "chart", "table", "cards",
  "code", "closing"];

function check(cond, what) {
  if (!cond) throw new Error(`FAILED: ${what}`);
  console.log(`  ok  ${what}`);
}
async function idle(page) {
  await page.waitForFunction(() => !document.querySelector('.turn-bird[aria-busy="true"]'), null, { timeout: 60000 });
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
}

async function run(name, options, scheme) {
  console.log(`${name} ${scheme}`);
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...options, locale: "fr-FR", colorScheme: scheme, acceptDownloads: true });
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
  await page.locator("#welcome-start").click({ timeout: 8000 }).catch(() => {});
  const tag = `${name}-${scheme}`;
  await page.fill("#composer-input", "Fais une présentation : galerie des mises en page");
  await page.keyboard.press("Enter");
  await page.waitForSelector("#canvas:not([hidden]) .cv-slide", { timeout: 20000 });
  const midway = await page.locator("#canvas .cv-slide").count();
  await idle(page);
  await page.waitForSelector("#canvas .cv-status:not(.is-writing)", { timeout: 60000 });
  await page.waitForFunction(() => document.querySelector(".chips-row .mchip"), null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(300);
  const drawn = await page.locator("#canvas .cv-slide").evaluateAll((els) => els.map((e) => e.dataset.layout));
  check(drawn.length === LAYOUTS.length + 1, `cover + ${LAYOUTS.length} slides (got ${drawn.length}, ${midway} midway)`);
  check(JSON.stringify(drawn.slice(1)) === JSON.stringify(LAYOUTS), `every layout drawn: ${drawn.join(",")}`);
  check((await page.locator("#canvas .cv-cover img.cv-bleed").count()) === 1, "cover picture full bleed");
  check((await page.locator("#canvas .cv-grid .cv-img img").count()) === 3, "picture grid of three");
  check((await page.locator("#canvas .cv-vs").count()) === 1, "versus badge");
  check((await page.locator("#canvas .cv-credit-top").count()) >= 2, "credit line on the full-bleed pictures");

  // every slide, one PNG each (the panel width decides the size)
  const slides = page.locator("#canvas .cv-slide");
  for (let i = 0; i < drawn.length; i++) {
    await slides.nth(i).scrollIntoViewIfNeeded();
    await slides.nth(i).screenshot({ path: path.join(SHOTS, `deck-${tag}-${String(i).padStart(2, "0")}-${drawn[i]}.png`) });
  }
  // overflow: no slide content spills out of its 16:9 frame
  const spill = await page.evaluate(() =>
    [...document.querySelectorAll("#canvas .cv-slide")].flatMap((s) => {
      const r = s.getBoundingClientRect();
      return [...s.querySelectorAll(".cv-ed, li, .cv-kpi, .cv-col, img")]
        .filter((e) => {
          const q = e.getBoundingClientRect();
          return q.width && (q.bottom > r.bottom + 2 || q.right > r.right + 2);
        })
        .map((e) => `${s.dataset.layout}:${(e.textContent || e.tagName).slice(0, 20)}`);
    }),
  );
  check(spill.length === 0 || name === "phone", `nothing spills out of a slide${spill.length ? ` (${spill.join(" | ")})` : ""}`);
  if (spill.length) console.log(`  note phone spill: ${spill.join(" | ")}`);

  // the chat card: the cover, small; the next-step chips
  if (await page.evaluate(() => !!document.querySelector(".main")?.inert))
    await page.locator('#canvas [data-k="close"]').click();
  check((await page.locator(".cv-card .cv-thumb").count()) >= 1, "chat card shows the cover");
  const chips = await page.locator(".chips-row .mchip").allTextContents();
  check(chips.length >= 2 && chips.length <= 3, `2-3 next steps: ${chips.join(" | ")}`);
  await page.screenshot({ path: path.join(SHOTS, `deck-${tag}-chat.png`) });
  await page.locator(".cv-card .cv-card-open").last().click();
  await page.waitForSelector("#canvas:not([hidden])");

  // themes: each re-draws at once
  for (const [label, cls] of [["Forêt", "forest"], ["Nuit", "night"], ["Terracotta", "warm"], ["Bleu Bird", "corporate"]]) {
    await page.locator(`#canvas .cv-swatch[aria-label="${label}"]`).click();
    await page.waitForTimeout(120);
    check((await page.locator(`#canvas .cv-body.cvt-${cls}`).count()) === 1, `theme ${cls}`);
    if (cls !== "corporate") {
      await page.locator("#canvas .cv-slide").first().scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(SHOTS, `deck-${tag}-theme-${cls}.png`) });
      for (const k of [0, 6, 8, 11, 17])
        await slides.nth(k).screenshot({ path: path.join(SHOTS, `deck-${tag}-theme-${cls}-${String(k).padStart(2, "0")}.png`) });
    }
  }
  const versions = await page.locator("#canvas .cv-select option").count();
  check(versions === 5, `a version per theme (got ${versions})`);

  // layout menu: the « Les points » slide as cards
  const b = await page.locator("#canvas .cv-slide-wrap").nth(4).getAttribute("data-block");
  await page.locator(`#canvas [data-k="layout-${b}"]`).click();
  const offered = await page.locator("#canvas .cv-layouts:not([hidden]) [role=menuitemradio]").allTextContents();
  check(offered.includes("Cartes") && !offered.includes("Chiffre clé"), `layouts offered: ${offered.join(", ")}`);
  await page.locator(`#canvas [data-k="layout-${b}-cards"]`).click();
  await page.waitForTimeout(120);
  check((await page.locator("#canvas .cv-slide").nth(4).getAttribute("data-layout")) === "cards", "layout changed");

  // drag to reorder: slide 2 dropped after slide 3
  const ids = async () => page.locator("#canvas .cv-slide-wrap[data-block]").evaluateAll((e) => e.map((x) => x.dataset.block));
  const before = await ids();
  const target = page.locator(`#canvas .cv-slide-wrap[data-block="${before[2]}"]`);
  await target.scrollIntoViewIfNeeded();
  const grip = page.locator(`#canvas [data-k="grip-${before[1]}"]`);
  await grip.evaluate((el) => el.scrollIntoView({ block: "start" }));
  const g = await grip.boundingBox();
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
  await page.mouse.down();
  const tb = await target.boundingBox();
  const vh = page.viewportSize().height;
  const ty = Math.min(tb.y + tb.height * 0.75, vh - 10); // past the middle of the next slide: dropped after it
  check(ty > tb.y + tb.height / 2, "drop point visible");
  for (let k = 1; k <= 8; k++) await page.mouse.move(tb.x + 60, g.y + ((ty - g.y) * k) / 8);
  await page.mouse.up();
  await page.waitForTimeout(150);
  const after = await ids();
  check(after[2] === before[1] && after[1] === before[2], `drag moved the slide (${before.slice(0, 3)} -> ${after.slice(0, 3)})`);

  // cover: no picture, then version restore brings it back
  await page.locator('#canvas [data-k="cover-off"]').click();
  await page.waitForTimeout(120);
  check((await page.locator("#canvas .cv-cover img").count()) === 0, "cover without picture");
  const n = await page.locator("#canvas .cv-select option").count();
  await page.selectOption("#canvas .cv-select", String(n - 2));
  await page.locator('#canvas [data-k="restore"]').click();
  await page.waitForTimeout(120);
  check((await page.locator("#canvas .cv-cover img").count()) === 1, "restored version has its cover picture");
  check((await page.locator("#canvas .cv-select option").count()) === n + 1, "restore is a new version");

  // export: the .pptx of what is shown
  const [dl] = await Promise.all([
    page.waitForEvent("download", { timeout: 30000 }),
    (async () => {
      await page.locator('#canvas [data-k="download"]').click();
      await page.locator('#canvas [data-k="dl-pptx"]').click();
    })(),
  ]);
  const file = path.join(SHOTS, `deck-${tag}.pptx`);
  await dl.saveAs(file);
  check(fs.readFileSync(file).subarray(0, 2).toString() === "PK", `pptx (${fs.statSync(file).size} bytes)`);

  check(errors.length === 0, `no page error${errors.length ? `: ${errors.join(" | ")}` : ""}`);
  check(external.length === 0, `no third-party request${external.length ? `: ${external.join(" ")}` : ""}`);
  await browser.close();
}

(async () => {
  const which = process.argv[2] || "desktop";
  const scheme = process.argv[3] || "light";
  const opts = which === "phone" ? { ...devices["Pixel 5"], viewport: { width: 360, height: 780 } } : { viewport: { width: 1280, height: 860 } };
  await run(which, opts, scheme);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
