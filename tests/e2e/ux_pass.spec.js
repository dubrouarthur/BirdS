// The chat's calm states and small layout fixes, on the demo server with a scripted /api/chat stream (no model):
// the model waking up, a slow first word, a paused endpoint, the mail card's missing recipient and blanks, the
// phone top bar, the « Aller à la fin » arrow. 360 px and 1280 px, light and dark, French and English.
//   BIRD_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --demo --port 9311 &
//   BIRD_URL=http://127.0.0.1:9311/ SHOTS=/tmp/ux node tests/e2e/ux_pass.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9311/";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");
fs.mkdirSync(SHOTS, { recursive: true });
const CONFIGS = [
  { name: "m360-light-fr", w: 360, scheme: "light", lang: "fr" },
  { name: "m360-dark-en", w: 360, scheme: "dark", lang: "en" },
  { name: "desk-light-en", w: 1280, scheme: "light", lang: "en" },
  { name: "desk-dark-fr", w: 1280, scheme: "dark", lang: "fr" },
];

// window.fetch for /api/chat replaced by a scripted event stream (sessionStorage « ux.script »), the rest untouched
const STUB = `(() => {
  const raw = sessionStorage.getItem("ux.script");
  if (!raw) return;
  const events = JSON.parse(raw);
  const real = window.fetch.bind(window);
  window.fetch = (url, opts) => {
    if (!String(url).includes("/api/chat")) return real(url, opts);
    const enc = new TextEncoder();
    const body = new ReadableStream({
      async start(c) {
        for (const [ms, ev] of events) {
          await new Promise((r) => setTimeout(r, ms));
          if (ev === "hold") return;
          c.enqueue(enc.encode("data: " + JSON.stringify(ev) + "\\n\\n"));
        }
        c.close();
      },
    });
    return Promise.resolve(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
  };
})();`;

const problems = [];
const third = [];

async function scripted(page, events, ask) {
  await page.evaluate((e) => sessionStorage.setItem("ux.script", JSON.stringify(e)), events);
  await page.reload();
  await page.waitForTimeout(500);
  await page.locator("#composer-input").fill(ask);
  await page.locator("#btn-send").click();
}

(async () => {
  const browser = await chromium.launch();
  for (const c of CONFIGS) {
    const phone = c.w < 600;
    const ctx = await browser.newContext({
      viewport: { width: c.w, height: phone ? 780 : 860 },
      colorScheme: c.scheme,
      locale: c.lang === "fr" ? "fr-FR" : "en-US",
      isMobile: phone,
      hasTouch: phone,
    });
    await ctx.addInitScript((lang) => {
      if (!localStorage.getItem("bird.prefs")) localStorage.setItem("bird.prefs", JSON.stringify({ lang, welcomed: true }));
    }, c.lang);
    await ctx.addInitScript(STUB);
    const page = await ctx.newPage();
    const host = new globalThis.URL(URL).host;
    page.on("request", (r) => {
      const u = r.url();
      if (/^https?:/.test(u) && new globalThis.URL(u).host !== host) third.push(`${c.name}: ${u}`);
    });
    page.on("console", (m) => {
      if (m.type() === "error" || /Content Security Policy|Refused/.test(m.text()))
        problems.push(`${c.name}: console ${m.type()}: ${m.text()}`);
    });
    page.on("pageerror", (e) => problems.push(`${c.name}: pageerror ${e.message}`));
    const fr = c.lang === "fr";
    const shot = (what) => page.screenshot({ path: path.join(SHOTS, `ux-${what}-${c.name}.png`) });
    await page.goto(URL);
    await page.waitForTimeout(800);

    // ---- phone top bar: no bare model dot; the footprint is a plain leaf icon with a name
    const modelShown = await page.locator("#btn-model").isVisible();
    if (phone === modelShown) problems.push(`${c.name}: model chip ${modelShown ? "shown" : "hidden"}`);
    const leaf = await page.locator("#btn-footprint").getAttribute("aria-label");
    if (!leaf) problems.push(`${c.name}: footprint button without a name`);

    // ---- the model waking up: a calm line, a bar that fills, no attempt counter, no countdown
    await scripted(page, [[200, { type: "status", state: "waking", attempt: 3, retry_in: 15 }], [0, "hold"]], "Bonjour");
    await page.waitForTimeout(3500);
    const live = page.locator(".live-calm");
    const wakeText = (await live.innerText().catch(() => "")) || "";
    if (!wakeText.includes(fr ? "Bird se réveille" : "Bird is waking up")) problems.push(`${c.name}: wake line «${wakeText}»`);
    if (/Tentative|Attempt|Nouvel essai|Next try/.test(wakeText)) problems.push(`${c.name}: wake line shows the retries`);
    const bar1 = await page.locator(".wake-bar > span").evaluate((el) => el.getBoundingClientRect().width).catch(() => 0);
    await page.waitForTimeout(2200);
    const bar2 = await page.locator(".wake-bar > span").evaluate((el) => el.getBoundingClientRect().width).catch(() => 0);
    if (!(bar1 > 0 && bar2 > bar1)) problems.push(`${c.name}: wake bar does not fill (${bar1} → ${bar2})`);
    const wrapped = await page.locator(".live-calm .live-time").evaluate((el) => el.getClientRects().length > 1 || el.offsetHeight > 30);
    if (wrapped) problems.push(`${c.name}: elapsed time wraps`);
    await shot("waking");

    // ---- a normal answer slow to start: nothing anxious before 25 s
    await scripted(page, [[100, { type: "status", state: "ready" }], [0, "hold"]], "Explique la photosynthèse");
    await page.waitForTimeout(10000);
    const sub = await page.locator(".live [data-auto-sub]").innerText().catch(() => "");
    if (sub.trim()) problems.push(`${c.name}: a line under the wait at 10 s «${sub}»`);

    // ---- a paused endpoint: a calm card, in words for people, nothing about where the model runs
    await scripted(
      page,
      [
        [100, { type: "error", code: "endpoint_down", message: "Le serveur du modèle est en erreur… console Hugging Face (Inference Endpoints)." }],
        [50, { type: "done" }],
      ],
      "Bonjour",
    );
    await page.waitForTimeout(1200);
    if (await page.locator(".notice-error").count()) problems.push(`${c.name}: paused endpoint shown as a red error`);
    const down = await page.locator(".notice-calm").innerText().catch(() => "");
    if (!down.includes(fr ? "momentanément indisponible" : "briefly unavailable")) problems.push(`${c.name}: paused endpoint text «${down}»`);
    if (/Hugging Face|Inference Endpoints/.test(await page.locator("#conversation").innerText()))
      problems.push(`${c.name}: the host shows in the chat`);
    await shot("down");

    // ---- the mail card: a placeholder recipient becomes a designed hint, the blanks are marked
    await scripted(
      page,
      [
        [100, { type: "answer", content: "Brouillon prêt.", draft_email: { to: [], to_hint: "[destinataires]", subject: "Votre offre", body: "Bonjour [Prénom],\n\nMerci.\n\n[Votre nom]" } }],
        [50, { type: "done" }],
      ],
      "Écris un mail",
    );
    await page.waitForTimeout(1200);
    const meta = await page.locator(".email-card .email-to").innerText().catch(() => "");
    if (/\[|compléter :|complete:/.test(meta)) problems.push(`${c.name}: raw recipient placeholder «${meta}»`);
    if (!(await page.locator(".email-card .email-missing").count())) problems.push(`${c.name}: no recipient hint`);
    const blanks = await page.locator(".email-card .email-fill").count();
    if (blanks !== 2) problems.push(`${c.name}: ${blanks} blanks marked`);
    const mailto = await page.locator(".email-card a[data-mailto]").getAttribute("href");
    if (!/^mailto:\?subject=/.test(mailto || "")) problems.push(`${c.name}: mailto with a recipient ${mailto}`);
    await page.locator(".email-card").scrollIntoViewIfNeeded();
    await shot("mail");

    // ---- an address and a bare name: the name keeps its own « adresse à ajouter », only the address goes to mailto:
    await scripted(
      page,
      [
        [100, { type: "answer", content: "Brouillon prêt.", draft_email: { to: ["marie.dupont@exemple.fr"], to_hint: "Paul Martin", subject: "Réunion", body: "Bonjour,\n\nÀ jeudi." } }],
        [50, { type: "done" }],
      ],
      "Écris un mail",
    );
    await page.waitForTimeout(1200);
    const mixed = page.locator(".email-card").last();
    const named = await mixed.locator(".email-name").innerText().catch(() => "");
    if (!named.includes("Paul Martin") || !(await mixed.locator(".email-name .email-missing").count()))
      problems.push(`${c.name}: a bare name next to an address shows as a real recipient «${named}»`);
    if (await mixed.locator(".email-missing").count() !== 1) problems.push(`${c.name}: mixed recipients, ${await mixed.locator(".email-missing").count()} hints`);
    const mixedTo = await mixed.locator("a[data-mailto]").getAttribute("href");
    if (!/^mailto:marie\.dupont%40exemple\.fr\?/.test(mixedTo || "")) problems.push(`${c.name}: mixed mailto ${mixedTo}`);
    await mixed.scrollIntoViewIfNeeded();
    await shot("mail-mixed");

    // ---- a recipient line longer than the card: « À » stays on the first line, the recipients flow after it
    await scripted(
      page,
      [
        [100, { type: "answer", content: "Brouillon prêt.", draft_email: { to: ["jean-baptiste.delacroix-montmorency@entreprise-exemple-tres-longue.fr", "Marc Petit"], to_hint: "le service comptabilité", subject: "Facture", body: "Bonjour,\n\nCi-joint." } }],
        [50, { type: "done" }],
      ],
      "Écris un mail",
    );
    await page.waitForTimeout(1200);
    const longTo = page.locator(".email-card .email-to").last();
    const lines = await longTo.evaluate((el) => {
      const r = document.createRange();
      r.selectNodeContents(el.firstChild);
      const label = r.getBoundingClientRect();
      r.selectNodeContents([...el.childNodes].slice(1).find((n) => n.textContent.trim()));
      const first = r.getClientRects()[0];
      return { label: label.top, first: first ? first.top : -1, over: el.scrollWidth - el.clientWidth };
    });
    if (Math.abs(lines.label - lines.first) > 4) problems.push(`${c.name}: « À » alone on its line (${lines.label} vs ${lines.first})`);
    if (lines.over > 1) problems.push(`${c.name}: recipient line overflows the card by ${lines.over} px`);
    if ((await longTo.locator(".email-missing").count()) !== 2) problems.push(`${c.name}: long line, not one hint per name`);
    await longTo.scrollIntoViewIfNeeded();
    await shot("mail-long");

    // ---- « Aller à la fin »: a small round arrow with its words for screen readers
    await page.evaluate(() => {
      const s = document.getElementById("scroll");
      s.scrollTop = 0;
      s.dispatchEvent(new Event("scroll"));
    });
    await page.setViewportSize({ width: c.w, height: 420 });
    await page.waitForTimeout(400);
    const jump = page.locator("#btn-jump");
    if (await jump.isVisible()) {
      const box = await jump.boundingBox();
      if (box.width > 46 || Math.abs(box.width - box.height) > 1) problems.push(`${c.name}: jump button ${box.width}×${box.height}`);
      const name = await jump.innerText();
      if (!name.trim()) problems.push(`${c.name}: jump button without words`);
    }
    await ctx.close();
  }
  await browser.close();
  if (third.length) problems.push(...third.map((u) => `third-party request ${u}`));
  for (const p of problems) console.log("FAIL", p);
  console.log(problems.length ? `ux_pass e2e: ${problems.length} problem(s)` : "ux_pass e2e: all checks passed");
  process.exit(problems.length ? 1 : 0);
})();
