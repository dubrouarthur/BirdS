// Frame renderer for promo.html (v5: licensed music track, no voice-over).
//   node render.js                    -> all frames at 30 fps + MP4 + contact sheet
//   node render.js stills 1.2,5,9     -> a few PNG stills (for checking); QUERY="wd=..&wu=.." previews the end card
//   node render.js mux                -> rebuild the soundtrack (audio.py) and re-mux it onto the existing silent video
//   AUDIO_PY = python with numpy (default: repo .venv)
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");
const { execFileSync } = require("child_process");

const HERE = __dirname;
const SCR =
  "/tmp/claude-0/-home-user-BirdS/27eb98ec-b9ba-5cf1-a125-8008c93c0d55/scratchpad/video5/render";
const FRAMES = path.join(SCR, "frames");
const FPS = 30;
const OUT = path.join(HERE, "bird-promo-v5-9x16.mp4");
const SHEET = path.join(HERE, "contact-v5.png");
const SILENT = path.join(SCR, "video_silent.mp4");
const CUES = path.join(SCR, "audio_cues.json");
const WAV = path.join(SCR, "soundtrack.wav");
const PY =
  process.env.AUDIO_PY ||
  path.join(HERE, "..", "..", "..", ".venv", "bin", "python");
// contact sheet: 8 settled moments (s)
const PICKS = [1.95, 6.6, 10.6, 14.6, 18.5, 21.4, 24.4, 33.5];

function soundtrackAndMux() {
  // audio.py writes the final, loudness-normalised soundtrack (-14 LUFS, true peak <= -1 dBTP)
  execFileSync(PY, ["-I", path.join(HERE, "audio.py"), CUES, WAV], {
    stdio: "inherit",
  });
  execFileSync(
    "ffmpeg",
    [
      "-y",
      "-loglevel",
      "error",
      "-i",
      SILENT,
      "-i",
      WAV,
      "-map",
      "0:v",
      "-map",
      "1:a",
      "-c:v",
      "copy",
      "-c:a",
      "aac",
      "-b:a",
      "256k",
      "-ar",
      "48000",
      "-shortest",
      "-movflags",
      "+faststart",
      OUT,
    ],
    { stdio: "inherit" },
  );
}

(async () => {
  const mode = process.argv[2] || "all";
  fs.mkdirSync(SCR, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1080, height: 1920 },
    deviceScaleFactor: 1,
  });
  const q = process.env.QUERY ? "?" + process.env.QUERY : "";
  await page.goto("file://" + path.join(HERE, "promo.html") + q);
  await page.evaluate(() => document.fonts.ready);
  const duration = await page.evaluate(() => window.DURATION);
  fs.writeFileSync(
    CUES,
    JSON.stringify(await page.evaluate(() => window.AUDIO)),
  );
  if (mode === "mux") {
    await browser.close();
    soundtrackAndMux();
    console.log("muxed", OUT);
    return;
  }
  if (mode === "stills") {
    const dir = process.env.STILLS || path.join(SCR, "stills");
    fs.mkdirSync(dir, { recursive: true });
    for (const ts of process.argv[3].split(",")) {
      const t = parseFloat(ts);
      await page.evaluate((t) => window.render(t), t);
      await page.screenshot({ path: path.join(dir, `t${t.toFixed(2)}.png`) });
    }
    await browser.close();
    return;
  }

  fs.rmSync(FRAMES, { recursive: true, force: true });
  fs.mkdirSync(FRAMES, { recursive: true });
  const n = Math.round(duration * FPS);
  for (let i = 0; i < n; i++) {
    await page.evaluate((t) => window.render(t), i / FPS);
    await page.screenshot({
      path: path.join(FRAMES, `f${String(i).padStart(5, "0")}.png`),
    });
    if (i % 90 === 0) process.stdout.write(`frame ${i}/${n}\n`);
  }
  await browser.close();

  execFileSync(
    "ffmpeg",
    [
      "-y",
      "-loglevel",
      "error",
      "-framerate",
      String(FPS),
      "-i",
      path.join(FRAMES, "f%05d.png"),
      "-c:v",
      "libx264",
      "-preset",
      "slow",
      "-crf",
      "18",
      "-pix_fmt",
      "yuv420p",
      "-movflags",
      "+faststart",
      "-r",
      String(FPS),
      SILENT,
    ],
    { stdio: "inherit" },
  );
  soundtrackAndMux();

  const picks = PICKS.map((x) => Math.min(n - 1, Math.round(x * FPS)));
  const list = picks.map((p) =>
    path.join(FRAMES, `f${String(p).padStart(5, "0")}.png`),
  );
  const filt =
    list.map((_, k) => `[${k}:v]scale=360:640[v${k}]`).join(";") +
    ";" +
    list.map((_, k) => `[v${k}]`).join("") +
    "xstack=inputs=8:layout=0_0|360_0|720_0|1080_0|0_640|360_640|720_640|1080_640[out]";
  execFileSync(
    "ffmpeg",
    [
      "-y",
      "-loglevel",
      "error",
      ...list.flatMap((f) => ["-i", f]),
      "-filter_complex",
      filt,
      "-map",
      "[out]",
      "-frames:v",
      "1",
      SHEET,
    ],
    { stdio: "inherit" },
  );
  console.log(
    "done",
    OUT,
    SHEET,
    "frames",
    n,
    "picks",
    picks.map((p) => (p / FPS).toFixed(2)).join(","),
  );
})();
