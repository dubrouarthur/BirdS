// « Se connecter au Bird local » end to end: a fake OpenAI-compatible server (tests/fixtures/fake_vllm.py) stands in
// for vLLM, scripts/bird_local.py runs the local Bird on 127.0.0.1:8765, and a hosted-mode page (serve.py --demo on
// another port, its origin allowed by the local Bird) connects to it and runs a full turn through it.
//   node tests/e2e/bird_local.spec.js            (starts and stops the three servers itself; ports 8399, 8765, 9417)
//   SHOTS=/tmp/shots ONLY=desk-light node tests/e2e/bird_local.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: the third choice in Settings → Modèle; with Bird local stopped, the three-step card (never a raw error); the
// connect flow (found, wrong code refused, right code accepted); the header badge « Bird local »; a turn answered by
// the machine, every /api/ call of the turn sent to 127.0.0.1:8765 and none to the hosted server; the footprint note;
// Bird local stopped mid-conversation: the card in the turn; disconnect returns to the hosted model; the page served
// by Bird local itself (http://127.0.0.1:8765/#pair=CODE). No CSP or script error, no third party, no horizontal
// scroll. Screenshots at 360 px and 1280 px, light and dark (look at them).
const { chromium } = require("playwright");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

const ROOT = path.resolve(__dirname, "..", "..");
const PY = process.env.PYTHON || path.join(ROOT, ".venv", "bin", "python");
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
const HOSTED = `http://127.0.0.1:${process.env.HOSTED_PORT || 9417}`;
const LOCAL = "http://127.0.0.1:8765";
const CODE = "K7QM-W4XD";
fs.mkdirSync(OUT, { recursive: true });

const CONFIGS = [
  { name: "m360-light", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "light", isMobile: true, hasTouch: true },
  { name: "m360-dark", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "dark", isMobile: true, hasTouch: true },
  { name: "desk-light", viewport: { width: 1280, height: 900 }, colorScheme: "light" },
  { name: "desk-dark", viewport: { width: 1280, height: 900 }, colorScheme: "dark" },
].filter((c) => !ONLY || c.name.includes(ONLY));

const procs = [];
function start(args, name) {
  const p = spawn(PY, args, { cwd: ROOT, env: { ...process.env, XDG_CONFIG_HOME: path.join(OUT, ".cfg") }, stdio: ["ignore", "pipe", "pipe"] });
  p.log = "";
  p.stdout.on("data", (d) => (p.log += d));
  p.stderr.on("data", (d) => (p.log += d));
  p.name = name;
  procs.push(p);
  return p;
}
function stop(p) {
  if (p && p.exitCode === null) p.kill("SIGTERM");
}
async function waitUp(url, ms = 30000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const ok = await new Promise((res) => {
      http.get(url, (r) => (r.resume(), res(r.statusCode < 500))).on("error", () => res(false));
    });
    if (ok) return;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`not up: ${url}`);
}
async function waitDown(url, ms = 10000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const up = await new Promise((res) => http.get(url, (r) => (r.resume(), res(true))).on("error", () => res(false)));
    if (!up) return;
    await new Promise((r) => setTimeout(r, 200));
  }
}
const startLocal = () =>
  start(["scripts/bird_local.py", "--vllm-url", "http://127.0.0.1:8399/v1", "--no-browser", "--pairing-code", CODE,
    "--allow-origin", HOSTED, "--port", "8765"], "bird_local"); // prettier-ignore

const problems = [];
function watch(page, name, apiCalls) {
  page.on("request", (r) => {
    const u = r.url();
    // the hosted page and Bird local are both on this machine (127.0.0.1, or localhost for the second probe)
    if (!/^http:\/\/(127\.0\.0\.1|localhost):/.test(u) && !u.startsWith("data:") && !u.startsWith("blob:"))
      problems.push(`${name}: third-party request ${u}`);
    if (/\/api\//.test(u)) apiCalls.push(u);
  });
  page.on("console", (m) => {
    const text = m.text();
    // a fetch to a stopped Bird local logs « Failed to load resource » / ERR_CONNECTION_REFUSED: expected there
    if (/ERR_CONNECTION_REFUSED|Failed to load resource|Failed to fetch/.test(text)) return;
    if (m.type() === "error" || /Content Security Policy|Refused/.test(text)) problems.push(`${name}: console ${m.type()}: ${text}`);
  });
  page.on("pageerror", (e) => problems.push(`${name}: pageerror ${e.message}`));
}
async function noHScroll(page, name, where) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (over > 1) problems.push(`${name}: horizontal scroll ${over}px on ${where}`);
}
const prefs = (extra = {}) =>
  JSON.stringify({ lang: "fr", theme: "system", welcomed: true, thinking: true, thinkingV: 2, ...extra });

async function newPage(browser, cfg, init) {
  const { name, ...opts } = cfg;
  const ctx = await browser.newContext({ ...opts, locale: "fr-FR", timezoneId: "Europe/Paris" });
  await ctx.addInitScript(init.script, init.arg);
  const page = await ctx.newPage();
  const apiCalls = [];
  watch(page, name, apiCalls);
  return { ctx, page, apiCalls };
}
const setStorage = ([p, pair]) => {
  if (sessionStorage.getItem("e2e.init")) return; // once per tab: a reload keeps what the page stored
  sessionStorage.setItem("e2e.init", "1");
  localStorage.setItem("bird.prefs", p);
  if (pair) localStorage.setItem("bird.localPair", pair);
};

async function openModelSettings(page) {
  // the model pill opens the model choice; on a phone the pill shows only in Bird local, else the menu leads there
  if (await page.locator("#btn-model").isVisible()) await page.click("#btn-model");
  else {
    await page.click("#btn-menu");
    await page.click("#nav-settings");
  }
  await page.waitForSelector("#settings-model");
}
async function chooseLocal(page) {
  await page.locator('.mode-local').click();
  await page.waitForSelector('#local-panel [data-local="found"], #local-panel [data-local="down"]', { timeout: 15000 });
}
async function shot(page, file, locator) {
  if (locator) await locator.scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(OUT, file) });
}
async function send(page, text) {
  await page.fill("#composer-input", text);
  await page.press("#composer-input", "Enter");
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
  await page.waitForTimeout(400);
}

(async () => {
  const fake = start(["tests/fixtures/fake_vllm.py", "--port", "8399", "--structured"], "fake_vllm");
  const hosted = start(["scripts/serve.py", "--demo", "--port", HOSTED.split(":").pop()], "hosted");
  await waitUp("http://127.0.0.1:8399/v1/models");
  await waitUp(`${HOSTED}/api/health`);
  const browser = await chromium.launch();
  let local = null;
  try {
    // ---- A. Bird local stopped: the choice, then the three steps
    for (const cfg of CONFIGS) {
      const { ctx, page } = await newPage(browser, cfg, { script: setStorage, arg: [prefs(), null] });
      await page.goto(HOSTED, { waitUntil: "networkidle" });
      await openModelSettings(page);
      if ((await page.locator("#settings-model .mode-local").count()) !== 1) problems.push(`${cfg.name}: no Bird local choice`);
      const title = await page.locator(".mode-local .mode-title").innerText();
      if (!/Bird local \(votre machine\)/.test(title)) problems.push(`${cfg.name}: local choice title « ${title} »`);
      await chooseLocal(page);
      const down = page.locator('#local-panel [data-local="down"]');
      if (!(await down.count())) problems.push(`${cfg.name}: no « ne répond pas » card with Bird local stopped`);
      else {
        const text = await down.innerText();
        if (!/vllm serve adubrou\/Bird-S-4B --host 127\.0\.0\.1 --port 8000/.test(text) || !/bird_local\.py/.test(text))
          problems.push(`${cfg.name}: the card lacks the commands`);
        if ((await down.locator(".local-step").count()) !== 3) problems.push(`${cfg.name}: not three steps`);
        if (/TypeError|Failed|HTTP|ERR_/.test(text)) problems.push(`${cfg.name}: raw error in the card`);
      }
      await noHScroll(page, cfg.name, "settings (down)");
      await shot(page, `local-unreachable-${cfg.name}.png`, page.locator("#local-panel"));
      await ctx.close();
    }

    // ---- B. Bird local running: connect, a turn through it, footprint, disconnect
    local = startLocal();
    await waitUp(`${LOCAL}/api/health`);
    for (const cfg of CONFIGS) {
      const { ctx, page, apiCalls } = await newPage(browser, cfg, { script: setStorage, arg: [prefs(), null] });
      await page.goto(HOSTED, { waitUntil: "networkidle" });
      await openModelSettings(page);
      await shot(page, `local-settings-${cfg.name}.png`, page.locator("#settings-model"));
      await chooseLocal(page);
      if (!(await page.locator('#local-panel [data-local="found"]').count())) {
        problems.push(`${cfg.name}: Bird local running but not found`);
        await shot(page, `FAIL-local-found-${cfg.name}.png`);
        await ctx.close();
        continue;
      }
      // a wrong code is refused, in words
      await page.fill("#local-code", "WXYZ-WXYZ");
      await page.click('[data-act="local-connect"]');
      await page.waitForFunction(() => document.querySelector("#local-code-err")?.textContent.trim());
      const err = await page.locator("#local-code-err").innerText();
      if (!/ne correspond pas/.test(err)) problems.push(`${cfg.name}: wrong code message « ${err} »`);
      await page.fill("#local-code", CODE.toLowerCase());
      await shot(page, `local-connect-${cfg.name}.png`, page.locator("#local-panel"));
      await page.click('[data-act="local-connect"]');
      await page.waitForSelector('#local-panel [data-local="connected"]', { timeout: 10000 });
      await page.waitForFunction(() => /adubrou\/Bird-S-4B/.test(document.querySelector('[data-local="connected"]')?.textContent || ""));
      const chip = await page.locator("#model-name").textContent(); // the pill folds its label on a phone
      if (!/Bird local/.test(chip) || !(await page.locator("#btn-model.is-local").count()))
        problems.push(`${cfg.name}: header pill « ${chip} » without the local badge`);
      const stored = await page.evaluate(() => [sessionStorage.getItem("bird.localPair"), localStorage.getItem("bird.localPair")]);
      if (stored[0] !== CODE || stored[1] !== null) problems.push(`${cfg.name}: code storage ${JSON.stringify(stored)}`);
      await noHScroll(page, cfg.name, "settings (connected)");
      await shot(page, `local-connected-${cfg.name}.png`, page.locator("#local-panel"));

      // a full turn, answered by the machine
      await page.click("#btn-back");
      const before = apiCalls.length;
      await send(page, "Bonjour, tu tournes où ?");
      const answer = await page.locator(".turn-bird").last().innerText();
      if (!/votre machine/.test(answer)) problems.push(`${cfg.name}: answer not from Bird local: « ${answer.slice(0, 120)} »`);
      const turnCalls = apiCalls.slice(before);
      if (!turnCalls.some((u) => u.startsWith(`${LOCAL}/api/chat`))) problems.push(`${cfg.name}: no /api/chat to Bird local`);
      const leaked = turnCalls.filter((u) => u.startsWith(HOSTED) && !u.includes("/api/health"));
      if (leaked.length) problems.push(`${cfg.name}: the hosted server saw ${leaked.join(", ")}`);
      await noHScroll(page, cfg.name, "conversation");
      await shot(page, `local-conversation-${cfg.name}.png`);

      // the footprint says where the energy is
      await page.click("#btn-footprint");
      const note = page.locator('[data-local="footprint"]');
      await note.waitFor({ timeout: 5000 }).catch(() => {});
      if (!(await note.count()) || !/votre machine/.test(await note.innerText())) problems.push(`${cfg.name}: no local footprint note`);
      else await shot(page, `local-footprint-${cfg.name}.png`, note);

      // reload: still Bird local (sessionStorage), then disconnect returns to the hosted model
      await page.reload({ waitUntil: "networkidle" });
      if (!(await page.locator("#btn-model.is-local").count())) problems.push(`${cfg.name}: not local after reload`);
      await openModelSettings(page);
      await page.click('[data-act="local-off"]');
      await page.waitForTimeout(300);
      if (await page.locator("#btn-model.is-local").count()) problems.push(`${cfg.name}: still local after disconnect`);
      await ctx.close();
    }

    // the page served by Bird local itself, opened by the command with the code in the fragment
    {
      const cfg = CONFIGS[CONFIGS.length - 1] || { name: "desk", viewport: { width: 1280, height: 900 } };
      const { ctx, page, apiCalls } = await newPage(browser, cfg, { script: setStorage, arg: [prefs(), null] });
      await page.goto(`${LOCAL}/#pair=${CODE}`, { waitUntil: "networkidle" });
      if (page.url().includes("pair=")) problems.push("local page: the code stays in the address bar");
      if (await page.locator("#local-pair[open]").count()) problems.push("local page: asks for the code it was given");
      await send(page, "Bonjour");
      const answer = await page.locator(".turn-bird").last().innerText();
      if (!/votre machine/.test(answer)) problems.push(`local page: answer « ${answer.slice(0, 80)} »`);
      if (apiCalls.some((u) => !u.startsWith(LOCAL))) problems.push("local page: a call left the machine");
      await shot(page, `local-app-${cfg.name}.png`);
      await ctx.close();
      // opened by hand, without any code: the page Bird local serves works at once (no pairing dialog, a full turn)
      const b = await newPage(browser, cfg, { script: setStorage, arg: [prefs(), null] });
      await b.page.goto(LOCAL, { waitUntil: "networkidle" });
      if (await b.page.locator("#local-pair[open]").count()) problems.push("local page without code: asks for a code");
      await send(b.page, "Bonjour sans code");
      const own = await b.page.locator(".turn-bird").last().innerText();
      if (!/votre machine/.test(own)) problems.push(`local page without code: answer « ${own.slice(0, 80)} »`);
      await shot(b.page, `local-app-nocode-${cfg.name}.png`);
      await b.ctx.close();
    }

    // ---- B1b. the ready-made link the command prints (#bird-local=PORT:CODE): connected at once, nothing typed
    {
      const cfg = CONFIGS[0];
      const { ctx, page, apiCalls } = await newPage(browser, cfg, { script: setStorage, arg: [prefs(), null] });
      await page.goto(`${HOSTED}/#bird-local=8765:${CODE}`, { waitUntil: "networkidle" });
      if (page.url().includes("bird-local=")) problems.push("hosted link: the code stays in the address bar");
      await send(page, "Bonjour par le lien");
      const t = await page.locator(".turn-bird").last().innerText();
      if (!/votre machine/.test(t)) problems.push(`hosted link: answer « ${t.slice(0, 80)} »`);
      if (!apiCalls.some((u) => u.startsWith(LOCAL) && u.includes("/api/chat"))) problems.push("hosted link: the turn did not go to the machine");
      await ctx.close();
    }

    // ---- B2. a new tab where the code was kept for one tab only: still the machine, never the hosted server
    for (const cfg of CONFIGS) {
      const { ctx, page, apiCalls } = await newPage(browser, cfg, { script: setStorage, arg: [prefs({ mode: "local" }), null] });
      await page.goto(HOSTED, { waitUntil: "networkidle" });
      await send(page, "Bonjour, sans code");
      const leaked = apiCalls.filter((u) => u.startsWith(HOSTED) && !u.includes("/api/health"));
      if (leaked.length) problems.push(`${cfg.name}: no code, the hosted server saw ${leaked.join(", ")}`);
      const text = await page.locator(".turn-bird").last().innerText();
      if (!/code d'appairage/.test(text)) problems.push(`${cfg.name}: no code, turn says « ${text.slice(0, 120)} »`);
      await ctx.close();
    }

    // ---- B3. the model server (vLLM) stopped while Bird local runs: the vllm command, never a hosted sentence
    stop(fake);
    await waitDown("http://127.0.0.1:8399/v1/models");
    for (const cfg of CONFIGS) {
      const { ctx, page } = await newPage(browser, cfg, { script: setStorage, arg: [prefs({ mode: "local" }), CODE] });
      await page.goto(HOSTED, { waitUntil: "networkidle" });
      await send(page, "Bonjour");
      const card = page.locator('.turn-bird [data-local="model-down"]').last();
      if (!(await card.count())) {
        problems.push(`${cfg.name}: no « le modèle ne répond pas » card`);
        await shot(page, `FAIL-local-model-down-${cfg.name}.png`);
      } else {
        const text = await card.innerText();
        if (!/vllm serve adubrou\/Bird-S-4B/.test(text) || /Vérifiez l'adresse|HTTP \d/.test(text))
          problems.push(`${cfg.name}: model-down card « ${text.slice(0, 160)} »`);
        await noHScroll(page, cfg.name, "model-down card");
        await shot(page, `local-model-down-${cfg.name}.png`, card);
      }
      await ctx.close();
    }

    // ---- C. Bird local stopped mid-conversation: the card in the turn, never a raw error
    stop(local);
    await waitDown(`${LOCAL}/api/health`);
    for (const cfg of CONFIGS) {
      const { ctx, page } = await newPage(browser, cfg, { script: setStorage, arg: [prefs({ mode: "local" }), CODE] });
      await page.goto(HOSTED, { waitUntil: "networkidle" });
      if (!(await page.locator("#btn-model.is-local").count())) problems.push(`${cfg.name}: remembered pairing not local`);
      await send(page, "Bonjour");
      const card = page.locator('.turn-bird [data-local="down"]').last();
      if (!(await card.count())) {
        problems.push(`${cfg.name}: no « ne répond pas » card in the turn`);
        await shot(page, `FAIL-local-turn-${cfg.name}.png`);
      } else {
        const text = await card.innerText();
        if (/TypeError|Failed to fetch|HTTP \d/.test(text)) problems.push(`${cfg.name}: raw error in the turn card`);
        if (!(await card.locator('[data-act="local-retry"]').count())) problems.push(`${cfg.name}: no « Réessayer »`);
        await noHScroll(page, cfg.name, "turn card");
        await shot(page, `local-turn-down-${cfg.name}.png`, card);
      }
      await ctx.close();
    }
  } catch (e) {
    problems.push(`crash: ${e.stack || e}`);
  } finally {
    await browser.close();
    for (const p of procs) stop(p);
  }
  if (problems.length) {
    for (const p of procs) if (p.log.trim()) console.error(`--- ${p.name}\n${p.log.slice(-2000)}`);
    console.error(problems.join("\n"));
    process.exit(1);
  }
  console.log(`bird_local e2e: OK (${CONFIGS.length} configs), shots in ${OUT}`);
})();
