import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const HTML = fs.readFileSync(new URL("../ui/study-lab.html", import.meta.url), "utf8");
const SCRIPT = fs.readFileSync(new URL("../ui/study-lab.js", import.meta.url), "utf8");
const APP = fs.readFileSync(new URL("../ui/app.js", import.meta.url), "utf8");
const MAC_BUILD = fs.readFileSync(new URL("../scripts/build-macos-app.sh", import.meta.url), "utf8");
const WINDOWS_BUILD = fs.readFileSync(new URL("../windows/build-windows.ps1", import.meta.url), "utf8");
const KATEX = fs.readFileSync(new URL("../ui/vendor/katex/katex.min.js", import.meta.url), "utf8");
const NOTICES = fs.readFileSync(new URL("../THIRD_PARTY_NOTICES.md", import.meta.url), "utf8");

test("Study Lab bindings resolve and expose only explicit LaTeX and Python cells", () => {
  const ids = [...HTML.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "markup ids must be unique");
  const bound = SCRIPT.match(/for \(const id of \[([\s\S]*?)\]\)/)?.[1] || "";
  for (const match of bound.matchAll(/"([A-Za-z][\w-]*)"/g)) {
    assert.ok(ids.includes(match[1]), `missing markup for #${match[1]}`);
  }
  assert.match(HTML, /data-add-kind="latex"/);
  assert.match(HTML, /data-add-kind="python"/);
  assert.doesNotMatch(HTML, /data-add-kind="(?:text|mixed|markdown)"/);
});

test("Study Lab serializes autosaves and sends revisions on every existing-notebook mutation", () => {
  assert.match(SCRIPT, /saveQueue:\s*Promise\.resolve\(\)/);
  assert.match(SCRIPT, /function enqueueMutation\(/);
  assert.match(SCRIPT, /async function flushPendingSaves\(/);
  assert.match(SCRIPT, /await flushPendingSaves\(\);[\s\S]*?\/api\/study\/cell\/move/);
  assert.match(SCRIPT, /await flushPendingSaves\(\);[\s\S]*?\/api\/study\/cell\/delete/);
  assert.match(SCRIPT, /baseUpdatedAt:\s*state\.revision/g);
  assert.match(APP, /baseUpdatedAt:\s*notebook\.updatedAt/);
  assert.match(SCRIPT, /beforeunload/);
});

test("Study Lab renders locally without executing Python", () => {
  assert.match(SCRIPT, /trust:\s*false/);
  assert.match(SCRIPT, /execution is unavailable/);
  assert.doesNotMatch(SCRIPT, /\beval\s*\(|new Function\s*\(|pyodide|\/execute\b/i);
  assert.match(KATEX, /version:"0\.18\.4"/);
  assert.match(NOTICES, /KaTeX 0\.18\.4/);
});

test("both desktop packages require the Study module and offline renderer", () => {
  for (const source of [MAC_BUILD, WINDOWS_BUILD]) {
    assert.match(source, /study_lab\.py/);
    assert.match(source, /study-lab\.js/);
    assert.match(source, /vendor[\\/]katex[\\/]katex\.min\.js/);
    assert.match(source, /KaTeX_Main-Regular\.woff2/);
  }
});
