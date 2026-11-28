// The brand story in the browser: the corporate site (/a-propos/) and the chat welcome, on the demo server:
//   .venv/bin/python scripts/serve.py --demo --port 9461 &
//   BIRD_URL=http://127.0.0.1:9461 SHOTS=/tmp/shots node tests/e2e/brand.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks, at 360, 768 and 1280 px, light and dark, French and English:
//   site   no third-party request, no CSP or script error, no horizontal scroll, nothing left invisible after a
//          scroll through the page (reveal), the hero mail draft is filled on load and again when scrolled back to,
//          the gallery stays short on phones and tablets, no placeholder address, « Nous écrire » leads to a real
//          section, the freedom-to-install section comes right after the hero
//   chat   the welcome says lightness and freedom to install, fits the screen, and closes on an uncluttered chat
// Screenshots of every section (look at them). ONLY=<tag part> narrows.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const BASE = (process.env.BIRD_URL || "http://127.0.0.1:9461").replace(/\/$/, "");
const OUT = process.env.SHOTS || path.join(__dirname, "shots", "brand");
const ONLY = process.env.ONLY || "";
fs.mkdirSync(OUT, { recursive: true });
const SECTIONS = "body > section, main > section, body > footer, main > footer";
let failures = 0;
function check(ok, what) {
  if (!ok) failures++;
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
}

async function context(browser, w, theme, locale) {
  const ctx = await browser.newContext({
    viewport: { width: w, height: w < 500 ? 780 : 900 },
    colorScheme: theme,
    locale,
    isMobile: w < 500,
    hasTouch: w < 500,
  });
  const page = await ctx.newPage();
  const third = [];
  const errors = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.protocol.startsWith("http") && !/^(127\.0\.0\.1|localhost)$/.test(u.hostname)) third.push(r.url());
  });
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  return { ctx, page, third, errors };
}

async function site(browser, lang, w, theme) {
  const tag = `site-${lang}-${w}-${theme}`;
  if (ONLY && !tag.includes(ONLY)) return;
  const { ctx, page, third, errors } = await context(browser, w, theme, lang === "fr" ? "fr-FR" : "en-US");
  await page.goto(`${BASE}/a-propos/${lang === "fr" ? "" : "en/"}`, { waitUntil: "networkidle" });
  const draft = () =>
    page.evaluate(() => {
      const card = document.querySelector(".hero-scene .sc-card");
      return card ? { text: card.innerText.trim().length, opacity: +getComputedStyle(card).opacity } : null;
    });
  const first = await draft();
  check(first && first.text > 80 && first.opacity > 0.9, `${tag} hero mail draft filled on load`);
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  for (let y = 0; y < height; y += 350) {
    await page.evaluate((v) => window.scrollTo(0, v), y);
    await page.waitForTimeout(40);
  }
  await page.waitForTimeout(800);
  const info = await page.evaluate((sel) => {
    const hidden = [];
    for (const el of document.querySelectorAll("main *")) {
      const r = el.getBoundingClientRect();
      if (r.width > 40 && r.height > 40 && +getComputedStyle(el).opacity < 0.05 && !el.closest("[aria-hidden=true]"))
        hidden.push(el.className || el.tagName);
    }
    const ids = [...document.querySelectorAll(sel)].map((s) => s.id || s.className);
    const gallery = document.querySelector("#fonctions, #features");
    const contacts = [...document.querySelectorAll(".contact-mail")].map((a) => a.getAttribute("href"));
    return {
      hidden,
      ids,
      overflow: document.documentElement.scrollWidth - innerWidth,
      gallery: gallery ? Math.round(gallery.getBoundingClientRect().height) : 0,
      contacts,
      body: document.body.innerText,
    };
  }, SECTIONS);
  check(info.hidden.length === 0, `${tag} nothing left invisible after scrolling (${info.hidden.slice(0, 3)})`);
  check(info.overflow <= 0, `${tag} no horizontal scroll`);
  check(w >= 900 || info.gallery < 1900, `${tag} gallery stays short (${info.gallery} px)`);
  check(!/birdmodels\.example|TODO/.test(info.body), `${tag} no placeholder address`);
  check(info.contacts.length > 0 && info.contacts.every((h) => !h.startsWith("mailto:")), `${tag} « Nous écrire » leads to a page`);
  check(info.ids[1] === (lang === "fr" ? "installer" : "install"), `${tag} freedom to install right after the hero`);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  const back = await draft();
  check(back && back.text > 80 && back.opacity > 0.9, `${tag} hero draft complete when scrolled back to`);
  check(third.length === 0, `${tag} no third-party request ${third.slice(0, 2)}`);
  check(errors.length === 0, `${tag} no CSP or script error ${errors.slice(0, 1)}`);
  await page.evaluate(() => document.querySelector(".site-header")?.style.setProperty("position", "static", "important"));
  let i = 0;
  for (const s of await page.$$(SECTIONS)) {
    const box = await s.boundingBox();
    if (!box || box.height < 4) continue;
    await s.scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
    await s.screenshot({ path: path.join(OUT, `${tag}-${String(i++).padStart(2, "0")}.png`) });
  }
  await ctx.close();
}

async function chat(browser, lang, w, theme) {
  const tag = `chat-${lang}-${w}-${theme}`;
  if (ONLY && !tag.includes(ONLY)) return;
  const { ctx, page, third, errors } = await context(browser, w, theme, lang === "fr" ? "fr-FR" : "en-US");
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  await page.waitForSelector("dialog[open]", { timeout: 5000 }).catch(() => {});
  const w8 = await page.evaluate(() => {
    const d = document.querySelector("dialog[open]");
    if (!d) return null;
    const r = d.getBoundingClientRect();
    return { text: d.innerText, fits: r.bottom <= innerHeight + 1 && r.right <= innerWidth + 1, scroll: d.scrollHeight - d.clientHeight };
  });
  check(!!w8, `${tag} welcome opens on a first visit`);
  if (w8) {
    const freedom = lang === "fr" ? /liberté d'installer nos modèles où vous voulez/ : /freedom to install our models wherever you want/;
    check(freedom.test(w8.text), `${tag} welcome: lightness and freedom to install`);
    check(/Conçu en France|Designed in France/.test(w8.text), `${tag} welcome: designed in France`);
    check(w8.fits && w8.scroll <= 2, `${tag} welcome fits the screen`);
    await page.screenshot({ path: path.join(OUT, `${tag}-welcome.png`) });
    await page.click("#welcome-close");
    await page.waitForTimeout(300);
  }
  const empty = await page.evaluate(() => ({
    sign: document.querySelector(".fi-sign")?.innerText || "",
    overflow: document.documentElement.scrollWidth - innerWidth,
  }));
  check(/où vous voulez|wherever you want/i.test(empty.sign), `${tag} empty chat signature`);
  check(empty.overflow <= 0, `${tag} no horizontal scroll`);
  check(third.length === 0, `${tag} no third-party request`);
  check(errors.length === 0, `${tag} no script error ${errors.slice(0, 1)}`);
  await page.screenshot({ path: path.join(OUT, `${tag}-empty.png`) });
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch();
  for (const lang of ["fr", "en"])
    for (const w of [360, 768, 1280])
      for (const theme of ["light", "dark"]) {
        await site(browser, lang, w, theme);
        await chat(browser, lang, w, theme);
      }
  await browser.close();
  console.log(failures ? `\n${failures} check(s) failed` : "\nall checks passed");
  process.exit(failures ? 1 : 0);
})();
