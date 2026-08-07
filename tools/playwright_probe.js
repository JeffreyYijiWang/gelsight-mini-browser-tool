const path = require("path");
const { chromium } = require("playwright");

const args = process.argv.slice(2);

function takeValue(flag, fallback = undefined) {
  const index = args.indexOf(flag);
  if (index === -1) return fallback;
  const value = args[index + 1];
  if (value === undefined || value.startsWith("--")) return fallback;
  return value;
}

function hasFlag(flag) {
  return args.includes(flag);
}

const url = takeValue(
  "--url",
  args.find((arg) => !arg.startsWith("--")) || "http://127.0.0.1:8001/",
);
const clickText = takeValue("--click");
const waitMs = Number(takeValue("--wait-ms", "8000"));
const screenshot = takeValue("--screenshot");
const profileDir = path.resolve(__dirname, "..", ".playwright-profile");

(async () => {
  const context = await chromium.launchPersistentContext(profileDir, {
    headless: true,
    viewport: { width: 1280, height: 760 },
  });
  const page = context.pages()[0] || (await context.newPage());
  const consoleMessages = [];
  const pageErrors = [];
  const requestFailures = [];

  page.on("console", (message) => {
    const text = `${message.type()}: ${message.text()}`;
    consoleMessages.push(text);
    console.log(`console ${text}`);
  });
  page.on("pageerror", (error) => {
    pageErrors.push(error.message);
    console.log(`pageerror ${error.message}`);
  });
  page.on("requestfailed", (request) => {
    const failure =
      `${request.url()} ${request.failure()?.errorText || ""}`.trim();
    requestFailures.push(failure);
    console.log(`requestfailed ${failure}`);
  });

  await page.goto(url, { waitUntil: "domcontentloaded" });

  if (hasFlag("--wait-ready") || hasFlag("--wait-depth")) {
    await page.waitForFunction(
      () => window.__gelsightState?.cv && window.__gelsightState?.session,
      null,
      { timeout: waitMs },
    );
  }

  if (clickText) {
    await page.getByText(clickText, { exact: true }).click();
  }

  if (hasFlag("--wait-depth")) {
    await page.waitForFunction(
      () => window.__gelsightState?.lastDepth && window.__gelsightState?.stats,
      null,
      { timeout: waitMs },
    );
  } else if (!hasFlag("--wait-ready")) {
    await page.waitForTimeout(waitMs);
  }

  const state = await page.evaluate(() => {
    const gs = window.__gelsightState;
    const depthCanvas = gs?.depthCanvas;
    let depthPixelMin = null;
    let depthPixelMax = null;

    if (depthCanvas) {
      const ctx = depthCanvas.getContext("2d", { willReadFrequently: true });
      const data = ctx.getImageData(
        0,
        0,
        depthCanvas.width,
        depthCanvas.height,
      ).data;
      depthPixelMin = 255;
      depthPixelMax = 0;
      for (let i = 0; i < data.length; i += 4) {
        depthPixelMin = Math.min(depthPixelMin, data[i]);
        depthPixelMax = Math.max(depthPixelMax, data[i]);
      }
    }

    return {
      href: location.href,
      bodyText: document.body.innerText.slice(0, 1000),
      gelsight: gs
        ? {
            status: gs.status,
            hasCv: !!gs.cv,
            cvDct: typeof gs.cv?.dct,
            cvIdct: typeof gs.cv?.idct,
            hasSession: !!gs.session,
            hasDepth: !!gs.lastDepth,
            stats: gs.stats,
            lastFrameMs: gs.lastFrameMs,
            depthPixelMin,
            depthPixelMax,
          }
        : null,
      globals: {
        hasP5: !!window.p5,
        hasOrt: !!window.ort,
        cvType: typeof window.cv,
        cvThen: typeof window.cv?.then,
      },
    };
  });

  if (screenshot) {
    const target = path.resolve(process.cwd(), screenshot);
    await page.screenshot({ path: target, fullPage: true });
    state.screenshot = target;
  }

  await context.close();

  console.log("probe result");
  console.log(
    JSON.stringify(
      {
        state,
        pageErrors,
        requestFailures,
        consoleMessages,
      },
      null,
      2,
    ),
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
