const { chromium } = require("playwright");

const DEFAULT_URL = "http://127.0.0.1:8002/p5/";
const probeName = process.argv[2] || "status";
const url = process.argv[3] || DEFAULT_URL;

const probes = {
  async status(page) {
    await waitForReady(page);
    return page.evaluate(() => {
      const state = window.__gelsightState;
      return {
        status: state.status,
        model: state.onnxModelMode,
        provider: state.onnxExecutionProvider,
        preprocessMode: state.preprocessMode,
        liveInferenceMode: state.liveInferenceMode,
        cropRect: state.cropRect,
      };
    });
  },

  async toolbar(page) {
    await waitForReady(page);
    return page.evaluate(() => ({
      liveInferenceMode: window.__gelsightState.liveInferenceMode,
      toolbar: [...document.querySelector(".toolbar").children].map((el) => ({
        tag: el.tagName,
        text: el.textContent.trim(),
        value: el.value || el.querySelector?.("select")?.value || null,
      })),
    }));
  },

  async wasmBenchmark(page) {
    await waitForReady(page);
    return page.evaluate(async () => ({
      status: window.__gelsightState.status,
      provider: window.__gelsightState.onnxExecutionProvider,
      fast: await window.__gelsightBenchmarkWasmMlp("fast", 5, "both"),
      full: await window.__gelsightBenchmarkWasmMlp("full", 2, "both"),
    }));
  },

  async meshSynthetic(page) {
    await waitForReady(page);
    await page.evaluate(() => {
      const state = window.__gelsightState;
      const width = 320;
      const height = 240;
      const depth = new Float32Array(width * height);
      for (let y = 0; y < height; y += 1) {
        for (let x = 0; x < width; x += 1) {
          depth[y * width + x] =
            Math.sin(x * 0.08) * 2 + Math.cos(y * 0.08) * 2;
        }
      }
      state.lastDepth = depth;
      state.stats = { min: -4, max: 4, mean: 0, finite: depth.length };
    });
    await page.waitForTimeout(250);
    return page.evaluate(() => ({
      drawLast: window.__gelsightState.profile.drawLast,
      drawPanelsLast: window.__gelsightState.profile.drawPanelsLast,
      drawMeshLast: window.__gelsightState.profile.drawMeshLast,
      meshGlLast: window.__gelsightState.profile.meshGlLast,
    }));
  },

  async cropMove(page) {
    await loadDemoAndWaitForCrop(page, "move");
    const before = await cropProbeState(page, "move");
    await dragHandle(page, before.handle, 32, 24);
    const after = await page.evaluate(() => ({
      crop: { ...window.__gelsightState.cropRect },
      slider: window.__gelsightState.cropFraction,
    }));
    return { before, after };
  },

  async cropScale(page) {
    await loadDemoAndWaitForCrop(page, "scale");
    const before = await cropProbeState(page, "scale");
    await dragHandle(page, before.handle, -40, -30);
    const after = await page.evaluate(() => ({
      crop: { ...window.__gelsightState.cropRect },
      slider: window.__gelsightState.cropFraction,
    }));
    return { before, after };
  },
};

probes["crop-move"] = probes.cropMove;
probes["crop-scale"] = probes.cropScale;

(async () => {
  const probe = probes[probeName];
  if (!probe) {
    throw new Error(
      `Unknown probe "${probeName}". Choose one of: ${Object.keys(probes).join(
        ", ",
      )}.`,
    );
  }

  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 760 } });
    await page.goto(url, { waitUntil: "domcontentloaded" });
    const result = await probe(page);
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

async function waitForReady(page) {
  await page.waitForFunction(
    () => window.__gelsightState?.cv && window.__gelsightState?.session,
    null,
    { timeout: 30000 },
  );
}

async function loadDemoAndWaitForCrop(page, handleName) {
  await waitForReady(page);
  await page.getByText("Demo", { exact: true }).click();
  await page.waitForFunction(
    (name) =>
      window.__gelsightState?.lastDepth &&
      window.__gelsightState?.cropHandleRects?.[name],
    handleName,
    { timeout: 30000 },
  );
}

async function cropProbeState(page, handleName) {
  return page.evaluate((name) => {
    const state = window.__gelsightState;
    return {
      crop: { ...state.cropRect },
      handle: { ...state.cropHandleRects[name] },
    };
  }, handleName);
}

async function dragHandle(page, handle, dx, dy) {
  await page.mouse.move(handle.x + handle.w / 2, handle.y + handle.h / 2);
  await page.mouse.down();
  await page.mouse.move(
    handle.x + handle.w / 2 + dx,
    handle.y + handle.h / 2 + dy,
    { steps: 4 },
  );
  await page.mouse.up();
}
