import pkg from "/tmp/e2e-chipan/node_modules/playwright-core/index.js";
const { chromium } = pkg;
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const BASE = process.env.CHIPAN_URL || "http://127.0.0.1:8080";
const OUT = process.env.CHIPAN_E2E_DIR || "/tmp/chipan-e2e";
mkdirSync(OUT, { recursive: true });

function box(h) {
  return { x: Math.round(h.x), y: Math.round(h.y), w: Math.round(h.width), h: Math.round(h.height), text: h.text };
}

function drift(a, b) {
  return {
    dx: Math.abs(a.x - b.x),
    dy: Math.abs(a.y - b.y),
    dw: Math.abs(a.w - b.w),
    dh: Math.abs(a.h - b.h),
  };
}

const failures = [];
function assert(cond, msg, extra) {
  if (!cond) failures.push({ msg, extra });
}

const browser = await chromium.launch({
  executablePath: "/opt/google/chrome/chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.setDefaultTimeout(20000);

await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForSelector("#run");
await page.waitForTimeout(600);

async function snap(name) {
  const handle = await page.$("#run");
  const rect = await handle.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height, text: el.textContent, disabled: el.disabled };
  });
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
  return box({ ...rect, text: rect.text });
}

const idle = await snap("01-idle");
assert(idle.text === "生成这份研判", "idle label", idle);
assert(idle.h === 42, "idle height locked", idle);

const intents = page.locator("#strats .strat");
const n0 = await intents.count();
assert(n0 === 4, "four primary questions", n0);

await intents.nth(1).click();
const afterIntent = await snap("02-intent");
assert(afterIntent.text === idle.text, "label stable after intent", afterIntent);
assert(drift(idle, afterIntent).dh === 0 && drift(idle, afterIntent).dw <= 2, "size stable after intent", {
  idle,
  afterIntent,
  drift: drift(idle, afterIntent),
});
assert(drift(idle, afterIntent).dy <= 2 && drift(idle, afterIntent).dx <= 2, "position stable after intent", {
  idle,
  afterIntent,
});

await page.click("#moreIntents");
await page.waitForTimeout(200);
const afterMore = await snap("03-more-intents");
assert(afterMore.text === idle.text, "label stable after more intents", afterMore);
assert(drift(idle, afterMore).dy <= 2 && drift(idle, afterMore).dw <= 2 && drift(idle, afterMore).dh === 0, "footer pinned when extra questions open", {
  idle,
  afterMore,
  drift: drift(idle, afterMore),
});
assert((await intents.count()) === 6, "six questions when expanded");

await page.click("#tuneBtn");
await page.waitForTimeout(200);
const afterTune = await snap("04-tune");
assert(drift(idle, afterTune).dy <= 2 && drift(idle, afterTune).dh === 0, "footer pinned when weights open", {
  idle,
  afterTune,
  drift: drift(idle, afterTune),
});

await page.click("#run");
await page.waitForTimeout(250);
const busy = await snap("05-busy");
assert(busy.text === idle.text, "label never changes while running", busy);
assert(drift(idle, busy).dy <= 2 && drift(idle, busy).dh === 0, "button does not jump on submit", {
  idle,
  busy,
  drift: drift(idle, busy),
});

const started = Date.now();
await page.waitForFunction(() => {
  const card = document.querySelector("#out .card, #out .fail");
  return Boolean(card);
}, { timeout: 25000 });
const ready = await snap("06-ready");
assert(ready.text === idle.text, "label still unchanged after ready", ready);
assert(drift(idle, ready).dy <= 2 && drift(idle, ready).dh === 0, "button does not jump when result lands", {
  idle,
  ready,
  drift: drift(idle, ready),
});
const elapsed = Date.now() - started;
assert(elapsed < 25000, "research finishes in e2e window", elapsed);

const thesis = await page.locator("#out .thesis").count();
assert(thesis === 1, "decision card rendered");

await page.locator("#strats .strat").nth(3).click();
await page.waitForTimeout(200);
const afterLens = await snap("07-lens");
assert(afterLens.text === idle.text, "label stable on lens switch", afterLens);
assert(drift(idle, afterLens).dy <= 2, "button stays put on lens switch", {
  idle,
  afterLens,
  drift: drift(idle, afterLens),
});

await page.click("#tape .tick:nth-child(4)");
await page.waitForTimeout(800);
const afterTape = await snap("08-symbol");
assert(afterTape.text === idle.text, "label stable after symbol change", afterTape);

const report = {
  ok: failures.length === 0,
  idle,
  samples: { afterIntent, afterMore, afterTune, busy, ready, afterLens, afterTape },
  failures,
};
writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
process.exit(failures.length ? 1 : 0);
