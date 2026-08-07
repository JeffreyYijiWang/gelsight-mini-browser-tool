const { chromium } = require("playwright");
const fs = require("fs");

const url = process.argv[2] || "http://127.0.0.1:8000/";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    acceptDownloads: true,
    viewport: { width: 1280, height: 760 },
  });
  const page = await context.newPage();
  const consoleMessages = [];
  const pageErrors = [];

  page.on("console", (message) => {
    if (
      ["error", "warning"].includes(message.type()) ||
      message.text().includes("p5.js says")
    ) {
      consoleMessages.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    pageErrors.push(error.message);
  });

  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => window.__gelsightState?.cv && window.__gelsightState?.session,
    null,
    { timeout: 30000 },
  );
  const initialButtons = await page.evaluate(() => ({
    refreshExists: !![...document.querySelectorAll("button")].find(
      (button) => button.textContent === "Refresh",
    ),
    calibrateDisabled: [...document.querySelectorAll("button")].find(
      (button) => button.textContent === "Calibrate",
    )?.disabled,
    exportDisabled: [...document.querySelectorAll("button")].find(
      (button) => button.textContent === "Export",
    )?.disabled,
  }));
  await page.getByText("Demo", { exact: true }).click();
  await page.waitForFunction(
    () => window.__gelsightState?.lastDepth && window.__gelsightState?.stats,
    null,
    { timeout: 30000 },
  );
  const demoButtonAfterLoad = await page
    .getByText("Live", { exact: true })
    .evaluate((button) => button.textContent);

  const beforeControls = await page.evaluate(() => {
    const state = window.__gelsightState;
    const cam = state.meshLayer._renderer.states.curCamera;
    return {
      rect: state.meshRect,
      camera: {
        eyeX: cam.eyeX,
        eyeY: cam.eyeY,
        eyeZ: cam.eyeZ,
        centerX: cam.centerX,
        centerY: cam.centerY,
        centerZ: cam.centerZ,
      },
      loadedCropRect: state.cropRect,
      loadedBaselineCount: state.baselineCount,
      loadedCameraResolution: state.cameraResolution,
    };
  });
  const meshCenterX = beforeControls.rect.x + beforeControls.rect.w / 2;
  const meshCenterY = beforeControls.rect.y + beforeControls.rect.h / 2;

  await page.mouse.move(meshCenterX, meshCenterY);
  await page.mouse.down();
  await page.mouse.move(meshCenterX + 48, meshCenterY + 22, { steps: 5 });
  await page.mouse.up();
  await page.mouse.wheel(0, -360);
  await page.mouse.move(meshCenterX, meshCenterY);
  await page.mouse.down({ button: "right" });
  await page.mouse.move(meshCenterX + 32, meshCenterY - 18, { steps: 4 });
  await page.mouse.up({ button: "right" });
  await page.waitForTimeout(300);

  const result = await page.evaluate(() => {
    const state = window.__gelsightState;
    const depthCanvas = state.depthCanvas;
    const ctx = depthCanvas.getContext("2d", { willReadFrequently: true });
    const data = ctx.getImageData(
      0,
      0,
      depthCanvas.width,
      depthCanvas.height,
    ).data;
    let min = 255;
    let max = 0;
    for (let i = 0; i < data.length; i += 4) {
      min = Math.min(min, data[i]);
      max = Math.max(max, data[i]);
    }
    const cam = state.meshLayer._renderer.states.curCamera;
    return {
      status: state.status,
      stats: state.stats,
      frameMs: state.lastFrameMs,
      depthPixelMin: min,
      depthPixelMax: max,
      hasDct: typeof state.cv.dct,
      hasIdct: typeof state.cv.idct,
      onnxModelMode: state.onnxModelMode,
      onnxModelPath: state.onnxModelPath,
      onnxProviderMode: state.onnxProviderMode,
      onnxExecutionProvider: state.onnxExecutionProvider,
      onnxProviderAttempts: state.onnxProviderAttempts,
      camera: {
        eyeX: cam.eyeX,
        eyeY: cam.eyeY,
        eyeZ: cam.eyeZ,
        centerX: cam.centerX,
        centerY: cam.centerY,
        centerZ: cam.centerZ,
      },
    };
  });

  result.initialButtons = initialButtons;
  result.loadedCropRect = beforeControls.loadedCropRect;
  result.loadedBaselineCount = beforeControls.loadedBaselineCount;
  result.loadedCameraResolution = beforeControls.loadedCameraResolution;
  result.demoButtonAfterLoad = demoButtonAfterLoad;
  result.exportDisabledBeforeCamera = await page
    .getByText("Export", { exact: true })
    .evaluate((button) => button.disabled);
  await page.evaluate(() => {
    window.__gelsightState.cameraEnabled = true;
    window.updateToolbarAvailability();
  });
  const downloadPromise = page.waitForEvent("download");
  await page.getByText("Export", { exact: true }).click();
  const download = await downloadPromise;
  const downloadPath = await download.path();
  const zipBytes = fs.readFileSync(downloadPath);
  const zipEntries = listZipEntries(zipBytes);
  const metadata = JSON.parse(
    readZipEntry(zipBytes, "metadata.json").toString("utf8"),
  );
  result.exportFilename = download.suggestedFilename();
  result.zipEntries = zipEntries;
  result.metadataChecks = {
    schema: metadata.schema,
    version: metadata.version,
    appVersion: metadata.app?.version,
    sourceMode: metadata.source?.mode,
    hasExportProcess: !!metadata.exportProcess,
    hasLiveDisplay: !!metadata.liveDisplay,
    displayPercentiles:
      metadata.liveDisplay?.depthPreviewCanvas?.normalization
        ? [
            metadata.liveDisplay.depthPreviewCanvas.normalization.percentileLow,
            metadata.liveDisplay.depthPreviewCanvas.normalization.percentileHigh,
          ]
        : null,
    displayHeadroom:
      metadata.liveDisplay?.depthPreviewCanvas?.normalization?.headroomPerSide,
    alphaDefault: metadata.controls?.alpha?.defaultValue,
    hasComputerVision: !!metadata.computerVision,
    modelPath: metadata.inference?.modelPath,
    featureOrder: metadata.computerVision?.imagePreprocessing?.modelFeatureOrder,
    markerHigh: metadata.computerVision?.markerFill?.thresholdHighInclusive,
    topLevelPoissonLambda: metadata.poissonIntegration?.regularizationLambda,
    cvPoissonLambda:
      metadata.computerVision?.poissonIntegration?.regularizationLambda,
    hasRealtimeTopLevel: !!metadata.realtime,
    hasControls: !!metadata.controls,
    hasMeshPreview: !!metadata.meshPreview,
    objTriangles: metadata.files?.mesh?.triangleCount,
    solverUnitsDepthPng: metadata.files?.solverUnitsDepth,
    selectedCameraResolution: metadata.camera?.selectedResolution,
    cropRect: metadata.crop?.rectNormalized,
    cropMinimumSize: metadata.crop?.minimumSize,
    liveInferenceResolution: metadata.inference?.inputResolution,
    hasNormalsAndGradients: "normalsAndGradients" in metadata.computerVision,
    hasPoissonIntegration: "poissonIntegration" in metadata.computerVision,
    hasRealtime: "realtime" in metadata.computerVision,
  };

  await context.close();
  await browser.close();

  if (pageErrors.length > 0) {
    throw new Error(`page errors:\n${pageErrors.join("\n")}`);
  }
  const severeConsole = consoleMessages.filter(
    (message) =>
      !message.includes("wasm streaming compile failed") &&
      !message.includes("GL Driver Message") &&
      !message.includes("GPU stall due to ReadPixels") &&
      !message.includes("No available adapters"),
  );
  if (severeConsole.length > 0) {
    throw new Error(`console errors:\n${severeConsole.join("\n")}`);
  }
  if (result.depthPixelMax <= result.depthPixelMin) {
    throw new Error(`blank depth canvas: ${JSON.stringify(result)}`);
  }
  if (result.hasDct !== "function" || result.hasIdct !== "function") {
    throw new Error(`missing OpenCV DCT functions: ${JSON.stringify(result)}`);
  }
  if (
    result.initialButtons.refreshExists ||
    !result.initialButtons.calibrateDisabled ||
    !result.initialButtons.exportDisabled ||
    !result.exportDisabledBeforeCamera
  ) {
    throw new Error(
      `camera-gated buttons were not disabled: ${JSON.stringify(result)}`,
    );
  }
  if (result.demoButtonAfterLoad !== "Live") {
    throw new Error(`demo button did not switch to Live: ${JSON.stringify(result)}`);
  }
  if (
    Math.abs(result.camera.eyeX - beforeControls.camera.eyeX) < 0.001 &&
    Math.abs(result.camera.eyeY - beforeControls.camera.eyeY) < 0.001 &&
    Math.abs(result.camera.eyeZ - beforeControls.camera.eyeZ) < 0.001 &&
    Math.abs(result.camera.centerX - beforeControls.camera.centerX) < 0.001 &&
    Math.abs(result.camera.centerY - beforeControls.camera.centerY) < 0.001
  ) {
    throw new Error(
      `mesh controls did not update camera: ${JSON.stringify(result)}`,
    );
  }
  if (
    Math.abs(result.camera.centerX - beforeControls.camera.centerX) < 0.001 &&
    Math.abs(result.camera.centerY - beforeControls.camera.centerY) < 0.001 &&
    Math.abs(result.camera.centerZ - beforeControls.camera.centerZ) < 0.001
  ) {
    throw new Error(
      `mesh pan did not move camera center: ${JSON.stringify(result)}`,
    );
  }
  if (!/^gelsight_\d{8}_\d{6}\.zip$/.test(result.exportFilename)) {
    throw new Error(`bad export filename: ${JSON.stringify(result)}`);
  }
  for (const entry of [
    "capture.png",
    "depth_16bit.png",
    "depth_solver_units_16bit.png",
    "mesh.obj",
    "metadata.json",
  ]) {
    if (!result.zipEntries.includes(entry)) {
      throw new Error(`missing ZIP entry ${entry}: ${JSON.stringify(result)}`);
    }
  }
  if (
    result.metadataChecks.schema !== "gelsight-mini-export-v2" ||
    result.metadataChecks.version !== "1.034" ||
    result.metadataChecks.appVersion !== "1.034" ||
    result.metadataChecks.sourceMode !== "demo" ||
    !result.metadataChecks.hasExportProcess ||
    !result.metadataChecks.hasLiveDisplay ||
    result.metadataChecks.displayPercentiles?.[0] !== 1 ||
    result.metadataChecks.displayPercentiles?.[1] !== 99 ||
    result.metadataChecks.displayHeadroom !== 0.05 ||
    result.metadataChecks.alphaDefault !== 0.6 ||
    !result.metadataChecks.hasComputerVision ||
    result.metadataChecks.modelPath !== result.onnxModelPath ||
    result.metadataChecks.markerHigh !== 70 ||
    typeof result.metadataChecks.topLevelPoissonLambda !== "number" ||
    typeof result.metadataChecks.cvPoissonLambda !== "number" ||
    !result.metadataChecks.hasRealtimeTopLevel ||
    !result.metadataChecks.hasControls ||
    !result.metadataChecks.hasMeshPreview ||
    result.metadataChecks.objTriangles !== 152482 ||
    result.metadataChecks.solverUnitsDepthPng?.scale !== 1000 ||
    result.metadataChecks.solverUnitsDepthPng?.offset !== 32768 ||
    result.metadataChecks.solverUnitsDepthPng?.filename !==
      "depth_solver_units_16bit.png" ||
    result.metadataChecks.selectedCameraResolution?.width !==
      result.loadedCameraResolution?.width ||
    result.metadataChecks.selectedCameraResolution?.height !==
      result.loadedCameraResolution?.height ||
    typeof result.metadataChecks.cropRect?.x !== "number" ||
    typeof result.metadataChecks.cropMinimumSize !== "number" ||
    !(
      (result.metadataChecks.liveInferenceResolution?.width === 160 &&
        result.metadataChecks.liveInferenceResolution?.height === 120) ||
      (result.metadataChecks.liveInferenceResolution?.width === 320 &&
        result.metadataChecks.liveInferenceResolution?.height === 240)
    ) ||
    !result.metadataChecks.hasNormalsAndGradients ||
    !result.metadataChecks.hasPoissonIntegration ||
    !result.metadataChecks.hasRealtime
  ) {
    throw new Error(
      `metadata constants missing or wrong: ${JSON.stringify(result)}`,
    );
  }
  if (
    Math.abs(result.loadedCropRect?.x - result.metadataChecks.cropRect?.x) >
      0.000001 ||
    Math.abs(result.loadedCropRect?.y - result.metadataChecks.cropRect?.y) >
      0.000001 ||
    result.loadedCameraResolution?.width !==
      result.metadataChecks.selectedCameraResolution?.width ||
    result.loadedCameraResolution?.height !==
      result.metadataChecks.selectedCameraResolution?.height ||
    result.loadedBaselineCount !== 50
  ) {
    throw new Error(
      `demo metadata was not restored: ${JSON.stringify(result)}`,
    );
  }

  console.log("GelSight p5 smoke test passed");
  console.log(JSON.stringify(result, null, 2));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

function listZipEntries(bytes) {
  const entries = [];
  for (let i = 0; i < bytes.length - 4; i += 1) {
    if (
      bytes[i] === 0x50 &&
      bytes[i + 1] === 0x4b &&
      bytes[i + 2] === 0x01 &&
      bytes[i + 3] === 0x02
    ) {
      const nameLength = bytes.readUInt16LE(i + 28);
      const extraLength = bytes.readUInt16LE(i + 30);
      const commentLength = bytes.readUInt16LE(i + 32);
      entries.push(
        bytes.subarray(i + 46, i + 46 + nameLength).toString("utf8"),
      );
      i += 46 + nameLength + extraLength + commentLength - 1;
    }
  }
  return entries;
}

function readZipEntry(bytes, targetName) {
  for (let i = 0; i < bytes.length - 4; i += 1) {
    if (
      bytes[i] === 0x50 &&
      bytes[i + 1] === 0x4b &&
      bytes[i + 2] === 0x03 &&
      bytes[i + 3] === 0x04
    ) {
      const nameLength = bytes.readUInt16LE(i + 26);
      const extraLength = bytes.readUInt16LE(i + 28);
      const compressedSize = bytes.readUInt32LE(i + 18);
      const nameStart = i + 30;
      const dataStart = nameStart + nameLength + extraLength;
      const name = bytes
        .subarray(nameStart, nameStart + nameLength)
        .toString("utf8");
      if (name === targetName) {
        return bytes.subarray(dataStart, dataStart + compressedSize);
      }
      i = dataStart + compressedSize - 1;
    }
  }
  throw new Error(`ZIP entry not found: ${targetName}`);
}
