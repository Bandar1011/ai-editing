import test from "node:test";
import assert from "node:assert/strict";
import { movedPosition, overlayBox } from "../web/canvas.mjs";
test("dragging stores resolution-independent positions", () => {
  const before = { x: 0.5, y: 0.75 };
  assert.deepEqual(movedPosition(before, 30, -60, 300, 600), {
    x: 0.6,
    y: 0.65,
  });
  assert.deepEqual(movedPosition(before, 60, -120, 600, 1200), {
    x: 0.6,
    y: 0.65,
  });
  assert.deepEqual(before, { x: 0.5, y: 0.75 });
});
test("a layer can reach the frame edges without saving off-canvas centres", () => {
  assert.deepEqual(movedPosition({ x: 0.5, y: 0.5 }, -1000, 1000, 300, 600), {
    x: 0,
    y: 1,
  });
});
test("existing overlay presets keep their positions until moved", () => {
  assert.deepEqual(overlayBox({ layout: "top" }), {
    width: 0.88,
    height: 0.38,
    x: 0.5,
    y: 0.24,
  });
  assert.equal(overlayBox({ layout: "bottom" }).y, 0.67);
  assert.deepEqual(overlayBox({ layout: "full", x: 0.3, y: 0.7 }), {
    width: 1,
    height: 1,
    x: 0.3,
    y: 0.7,
  });
});
