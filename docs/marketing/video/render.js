const { chromium } = require('playwright');
const fs = require('fs'); const path = require('path');
(async () => {
  const out = process.argv[2]; const fps = 30, dur = 15;
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  await p.goto('file://' + path.resolve(__dirname, 'promo.html')); await p.waitForTimeout(300);
  for (let i = 0; i < fps * dur; i++) {
    await p.evaluate((t) => window.render(t), i / fps);
    await p.screenshot({ path: path.join(out, String(i).padStart(4, '0') + '.jpg'), type: 'jpeg', quality: 92 });
  }
  await b.close();
})();
