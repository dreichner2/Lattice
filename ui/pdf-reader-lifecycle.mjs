export function pageDirectionForKey(key) {
  if (key === "ArrowRight" || key === "PageDown") return 1;
  if (key === "ArrowLeft" || key === "PageUp") return -1;
  return 0;
}

function waitForAnimationFrame() {
  return new Promise((resolve) => requestAnimationFrame(resolve));
}

export async function leaveFullscreenBeforeClose(
  documentRoot,
  waitForFrame = waitForAnimationFrame,
) {
  if (documentRoot.fullscreenElement) await documentRoot.exitFullscreen();
  if (documentRoot.fullscreenElement) return false;

  // WebKit and WebView2 update their native fullscreen surfaces after the DOM
  // promise resolves. Keep the iframe alive through two presentation frames so
  // the native host can restore its normal window before the shelf removes it.
  await waitForFrame();
  await waitForFrame();
  return !documentRoot.fullscreenElement;
}
