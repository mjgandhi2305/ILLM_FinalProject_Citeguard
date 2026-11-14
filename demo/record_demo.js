// Records the CiteGuard demo video and the screenshots used in the slides.
//
//   (API on :8000 and the web app on :5173, e.g. `make dev`)
//   CHROME=/path/to/chrome node demo/record_demo.js
//
// Needs playwright-core; CHROME points at any Chromium build.
const path = require("path");
const { chromium } = require("playwright-core");

const APP = process.env.APP_URL || "http://localhost:5173";
const OUT = __dirname;
const SHOTS = path.resolve(__dirname, "..", "slides", "assets");

const TEXT = `Transformers replaced recurrent networks for machine translation [1]. Deep learning transformed representation learning [2]. Graph transformers now predict protein folding dynamics [3]. Bidirectional pre-training improved language understanding [4].

References
[1] Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, L., & Polosukhin, I. (2017). Attention is all you need. Advances in Neural Information Processing Systems, 30.
[2] LeCun, Y., Bengio, Y., & Hinton, G. (2016). Deep learning. Nature, 521(7553), 436-444.
[3] Zhang, L., & Kumar, R. (2021). Contrastive graph transformers for protein folding dynamics. Nature Machine Intelligence, 3(4), 211-223.
[4] Smith, J., & Brown, T. (2019). BERT: Pre-training of deep bidirectional transformers for language understanding. Proceedings of NAACL-HLT, 4171-4186.`;

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME, headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    recordVideo: { dir: OUT, size: { width: 1440, height: 900 } },
  });
  const page = await context.newPage();
  const pause = (ms) => page.waitForTimeout(ms);

  await page.goto(APP);
  await pause(1500);
  await page.getByLabel("Input", { exact: true }).click();
  await page.getByLabel("Input", { exact: true }).fill(TEXT);
  await pause(1200);
  for (const name of ["LLM explanations", "Check claims (beta)"]) {
    const box = page.getByLabel(name);
    if ((await box.count()) && !(await box.isChecked())) await box.check();
  }
  await pause(800);
  await page.screenshot({ path: path.join(SHOTS, "demo_input.png") });
  await page.getByRole("button", { name: /Check citations/ }).click();

  // Verdicts stream in first; export buttons appear once explanations (pass 2) are done.
  await page.getByText("Fabricated").first().waitFor({ timeout: 120000 });
  await pause(2000);
  await page.getByRole("button", { name: /csv/i }).first().waitFor({ timeout: 300000 });
  await pause(1500);
  await page.screenshot({ path: path.join(SHOTS, "demo_results.png") });

  await page.getByText("Contrastive graph transformers", { exact: false }).first().click();
  await pause(2500);
  await page.screenshot({ path: path.join(SHOTS, "demo_drawer.png") });
  await page.mouse.wheel(0, 700);
  await pause(2500);
  await page.keyboard.press("Escape");
  await pause(1000);

  await page.getByText("Deep learning", { exact: true }).first().click();
  await pause(2500);
  await page.screenshot({ path: path.join(SHOTS, "demo_correction.png") });
  await pause(1500);

  const video = page.video();
  await context.close();
  await video.saveAs(path.join(OUT, "citeguard_demo.webm"));
  await video.delete();
  await browser.close();
  console.log("saved demo/citeguard_demo.webm and slides/assets/demo_*.png");
})().catch((e) => { console.error(e); process.exit(1); });
