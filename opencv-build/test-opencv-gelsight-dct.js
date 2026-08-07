const cvPromise = require("../p5/vendor/opencv-gelsight.js");

cvPromise
  .then((cv) => {
    if (typeof cv.dct !== "function" || typeof cv.idct !== "function") {
      throw new Error("OpenCV.js build must export cv.dct and cv.idct");
    }

    const src = cv.matFromArray(2, 2, cv.CV_32FC1, [1, 2, 3, 4]);
    const tmp = new cv.Mat();
    const out = new cv.Mat();

    cv.dct(src, tmp, 0);
    cv.idct(tmp, out, 0);

    const roundtrip = Array.from(out.data32F);
    const maxError = roundtrip.reduce(
      (error, value, index) => Math.max(error, Math.abs(value - (index + 1))),
      0,
    );

    src.delete();
    tmp.delete();
    out.delete();

    if (maxError > 1e-5) {
      throw new Error(`DCT round-trip error too high: ${maxError}`);
    }

    console.log("OpenCV.js DCT smoke test passed");
    console.log(`dct=${typeof cv.dct} idct=${typeof cv.idct} dft=${typeof cv.dft}`);
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
