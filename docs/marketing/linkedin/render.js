// Renders the LinkedIn assets: node render.js (Playwright + Chromium, pre-installed)
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  for (const [f, w, h, outs] of [['logo.html', 400, 400, [['bird-linkedin-logo-400.png', 1], ['bird-linkedin-logo-800.png', 2]]],
    ['banner.html', 1128, 191, [['bird-linkedin-banniere-1128x191.png', 1], ['bird-linkedin-banniere-2256x382.png', 2]]]]) {
    for (const [out, dpr] of outs) {
      const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: dpr });
      await p.goto('file://' + __dirname + '/' + f);
      await p.evaluate(() => document.fonts.ready);
      await p.screenshot({ path: __dirname + '/' + out });
      await p.close();
    }
  }
  await b.close();
})();
