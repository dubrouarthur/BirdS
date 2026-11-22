// Frame renderer for promo.html (v4: music + sound effects only, no voice-over).
//   node render.js                 -> all frames at 30 fps + MP4 + contact sheet
//   node render.js stills 1.2,5,9  -> a few PNG stills (for checking)
//   node render.js mux             -> rebuild the soundtrack (audio.py) and re-mux it onto the existing frames' video
//   AUDIO_PY = python with numpy (default: repo .venv)
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");
const { execFileSync } = require("child_process");

const HERE = __dirname;
const SCR =
  "/tmp/claude-0/-home-user-BirdS/27eb98ec-b9ba-5cf1-a125-8008c93c0d55/scratchpad/video4";
const FRAMES = path.join(SCR, "frames");
const FPS = 30;
const OUT = path.join(HERE, "bird-promo-v4-9x16.mp4");
const SHEET = path.join(HERE, "contact-v4.png");
const SILENT = path.join(SCR, "video_silent.mp4");
const CUES = path.join(SCR, "audio_cues.json");
const WAV = path.join(SCR, "soundtrack.wav");
const PY = process.env.AUDIO_PY || path.join(HERE, "..", "..", "..", ".venv", "bin", "python");

function soundtrackAndMux() {
  execFileSync(PY, ["-I", path.join(HERE, "audio.py"), CUES, WAV], { stdio: "inherit" });
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", SILENT, "-i", WAV,
    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
    "-shortest", "-movflags", "+faststart", OUT], { stdio: "inherit" });
}

(async () => {
  const mode = process.argv[2] || "all";
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1080, height: 1920 },
    deviceScaleFactor: 1,
  });
  await page.goto("file://" + path.join(HERE, "promo.html"));
  await page.evaluate(() => document.fonts.ready);
  const duration = await page.evaluate(() => window.DURATION);
  fs.writeFileSync(CUES, JSON.stringify(await page.evaluate(() => window.AUDIO)));
  if (mode === "mux") {
    await browser.close();
    soundtrackAndMux();
    console.log("muxed", OUT);
    return;
  }

  if (mode === "stills") {
    const dir = path.join(SCR, "stills");
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
    const t = i / FPS;
    await page.evaluate((t) => window.render(t), t);
    await page.screenshot({
      path: path.join(FRAMES, `f${String(i).padStart(5, "0")}.png`),
    });
    if (i % 60 === 0) process.stdout.write(`frame ${i}/${n}\n`);
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
      "20",
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

  // contact sheet: 8 key frames, 4x2
  // key moments (T, s): mission, plus petit, mail, deck, invoice, footprint, sobriety, call to action
  const picks = [4.6, 7.5, 10.4, 13.6, 16.3, 20.0, 23.6, 30.2].map((x) => Math.min(n - 1, Math.round(x * FPS)));
  const list = picks.map((p) =>
    path.join(FRAMES, `f${String(p).padStart(5, "0")}.png`),
  );
  const inputs = list.flatMap((f) => ["-i", f]);
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
      ...inputs,
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
