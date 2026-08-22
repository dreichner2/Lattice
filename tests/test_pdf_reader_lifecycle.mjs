import assert from "node:assert/strict";
import test from "node:test";

import {
  leaveFullscreenBeforeClose,
  pageDirectionForKey,
} from "../ui/pdf-reader-lifecycle.mjs";

test("left and right arrows navigate pages in every reader layout", () => {
  for (const layout of ["continuous", "single", "spread"]) {
    assert.equal(pageDirectionForKey("ArrowLeft", layout), -1);
    assert.equal(pageDirectionForKey("ArrowRight", layout), 1);
  }
  assert.equal(pageDirectionForKey("PageUp"), -1);
  assert.equal(pageDirectionForKey("PageDown"), 1);
  assert.equal(pageDirectionForKey("Home"), 0);
});

test("fullscreen is exited and presented before the iframe may close", async () => {
  const order = [];
  const documentRoot = {
    fullscreenElement: {},
    async exitFullscreen() {
      order.push("exit-fullscreen");
      this.fullscreenElement = null;
    },
  };
  const waitForFrame = async () => { order.push("presentation-frame"); };

  assert.equal(await leaveFullscreenBeforeClose(documentRoot, waitForFrame), true);
  assert.deepEqual(order, ["exit-fullscreen", "presentation-frame", "presentation-frame"]);
});

test("close is refused while the host still reports fullscreen", async () => {
  const documentRoot = {
    fullscreenElement: {},
    async exitFullscreen() {},
  };
  let frames = 0;
  assert.equal(await leaveFullscreenBeforeClose(documentRoot, async () => { frames += 1; }), false);
  assert.equal(frames, 0);
});
