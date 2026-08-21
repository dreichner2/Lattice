import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";


const SOURCE = fs.readFileSync(
  new URL("../native/ImmersiveEPUB.js", import.meta.url),
  "utf8",
);


function loadReaderScript() {
  let expanded = true;
  let clicks = 0;
  let focuses = 0;
  let storageFailure = false;

  const toggle = {
    getAttribute(name) {
      return name === "aria-expanded" && expanded ? "true" : "false";
    },
    click() {
      clicks += 1;
      expanded = true;
    },
  };
  const search = { focus() { focuses += 1; } };
  const document = {
    readyState: "loading",
    documentElement: { classList: { add() {} } },
    getElementById() { return {}; },
    querySelector(selector) {
      if (selector === "#readerTocButton:not([hidden])") return toggle;
      if (selector === "#epubTocSearch") return search;
      return null;
    },
    addEventListener() {},
  };
  const window = { __CS_LIBRARY_TEST__: {}, addEventListener() {} };
  window.top = window;

  vm.runInNewContext(SOURCE, {
    window,
    document,
    localStorage: {
      getItem() { return null; },
      setItem() {
        if (storageFailure) throw new Error("quota exceeded");
      },
    },
    setTimeout(callback) { callback(); return 1; },
    setInterval() { return 1; },
    clearInterval() {},
    MutationObserver: class {},
    Date,
    Math,
    JSON,
  });

  return {
    window,
    counters: () => ({ clicks, focuses }),
    closeContents: () => { expanded = false; },
    failStorage: () => { storageFailure = true; },
  };
}


test("find keeps an open Contents panel open and focuses search", () => {
  const reader = loadReaderScript();

  reader.window.csLibraryFocusEpubSearch();
  assert.deepEqual(reader.counters(), { clicks: 0, focuses: 1 });

  reader.closeContents();
  reader.window.csLibraryFocusEpubSearch();
  assert.deepEqual(reader.counters(), { clicks: 1, focuses: 2 });
});


test("note storage reports success and failure", () => {
  const reader = loadReaderScript();
  const writeNotes = reader.window.__CS_LIBRARY_TEST__.writeNotes;

  assert.equal(writeNotes({ book: [] }), true);
  reader.failStorage();
  assert.equal(writeNotes({ book: [{ note: "keep this draft" }] }), false);
});
