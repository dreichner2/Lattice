import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import test from "node:test";

const require = createRequire(import.meta.url);
const { createSaveTracker } = require("../ui/study-lab.js");

const HTML = fs.readFileSync(new URL("../ui/study-lab.html", import.meta.url), "utf8");
const SCRIPT = fs.readFileSync(new URL("../ui/study-lab.js", import.meta.url), "utf8");
const CSS = fs.readFileSync(new URL("../ui/study-lab.css", import.meta.url), "utf8");
const APP = fs.readFileSync(new URL("../ui/app.js", import.meta.url), "utf8");
const MAC_BUILD = fs.readFileSync(new URL("../scripts/build-macos-app.sh", import.meta.url), "utf8");
const WINDOWS_BUILD = fs.readFileSync(new URL("../windows/build-windows.ps1", import.meta.url), "utf8");
const KATEX = fs.readFileSync(new URL("../ui/vendor/katex/katex.min.js", import.meta.url), "utf8");
const NOTICES = fs.readFileSync(new URL("../THIRD_PARTY_NOTICES.md", import.meta.url), "utf8");

test("Study Workspace bindings resolve and prose is a first-class cell kind", () => {
  const ids = [...HTML.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "markup ids must be unique");
  const bound = SCRIPT.match(/for \(const id of \[([\s\S]*?)\]\)/)?.[1] || "";
  for (const match of bound.matchAll(/"([A-Za-z][\w-]*)"/g)) {
    assert.ok(ids.includes(match[1]), `missing markup for #${match[1]}`);
  }
  assert.match(HTML, /data-add-kind="markdown"/);
  assert.match(HTML, /data-add-kind="latex"/);
  assert.match(HTML, /data-add-kind="python"/);
  assert.match(SCRIPT, /kind === "markdown"/);
  assert.match(SCRIPT, /function renderMarkdown\(/);
  assert.match(HTML, /Turn reading into understanding/);
  assert.match(HTML, /data-starter="notes"/);
  assert.match(HTML, /id="newNotebookDialog"/);
  assert.match(HTML, /id="deleteNotebookDialog"/);
  assert.doesNotMatch(SCRIPT, /window\.(?:prompt|confirm)\s*\(/);
  assert.doesNotMatch(SCRIPT, /import numpy/);
});

test("Study Workspace has responsive, accessible, and compact reader layouts", () => {
  assert.match(HTML, /class="study-skip-link"/);
  assert.match(HTML, /id="saveStatus" role="status" aria-live="polite"/);
  assert.match(HTML, /aria-controls="studySidebar" aria-expanded="true"/);
  assert.match(HTML, /id="notebookSearch" type="search"/);
  assert.match(CSS, /\.rail-collapsed \.study-layout/);
  assert.match(CSS, /\.is-embedded \.study-toolbar/);
  assert.match(CSS, /\.reader-notes-mode \[data-add-kind="latex"\]/);
  assert.match(CSS, /@media \(max-width: 680px\)/);
  assert.match(CSS, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(CSS, /@media \(forced-colors: active\)/);
});

test("Study Workspace serializes autosaves and sends revisions on every existing-notebook mutation", () => {
  assert.match(SCRIPT, /saveQueue:\s*Promise\.resolve\(\)/);
  assert.match(SCRIPT, /function enqueueMutation\(/);
  assert.match(SCRIPT, /async function flushPendingSaves\(/);
  assert.match(SCRIPT, /await flushPendingSaves\(\);[\s\S]*?\/api\/study\/cell\/move/);
  assert.match(SCRIPT, /await flushPendingSaves\(\);[\s\S]*?\/api\/study\/cell\/delete/);
  assert.ok((SCRIPT.match(/baseUpdatedAt:\s*state\.revision/g) || []).length >= 6);
  assert.match(SCRIPT, /function refreshCurrentCellCount\(/);
  assert.match(APP, /baseUpdatedAt:\s*notebook\.updatedAt/);
  assert.match(SCRIPT, /beforeunload/);
  assert.match(SCRIPT, /state\.saveTracker\.shouldWarn/);
  assert.match(SCRIPT, /setSaveStatus\("saving", "Saving…"\)/);
  assert.match(SCRIPT, /setSaveStatus\("saved", "Saved locally"\)/);
  assert.match(SCRIPT, /setSaveStatus\("error", blockSaves \? "Could not save" : "Action failed"\)/);
});

test("failed autosaves stay dirty, retry cleanly, and block unsafe unload", () => {
  const tracker = createSaveTracker();
  const transient = new Error("temporary network failure");
  tracker.markDirty("cell-1");
  tracker.markFailed("cell-1", transient);
  assert.deepEqual(tracker.dirtyIds(), ["cell-1"]);
  assert.equal(tracker.failure.error, transient);
  assert.equal(tracker.shouldWarn(), true);

  tracker.markSucceeded("cell-1", true);
  assert.deepEqual(tracker.dirtyIds(), []);
  assert.equal(tracker.failure, null);
  assert.equal(tracker.shouldWarn(), false);

  tracker.markDirty("cell-2");
  tracker.markFailed("cell-2", transient);
  tracker.markSucceeded("cell-2", false);
  assert.deepEqual(tracker.dirtyIds(), ["cell-2"], "a newer edit must remain dirty");
  assert.equal(tracker.failure, null, "a successful retry clears the stale error");
  assert.equal(tracker.shouldWarn(), true);
});

test("the explicit save shortcut preserves the cell-specific retry failure", () => {
  assert.match(
    SCRIPT,
    /flushPendingSaves\(\)\.then\(\(\) => announce\("Saved locally"\)\)\.catch\(\(error\) => handleStudyError\(error\)\)/,
  );
  assert.doesNotMatch(
    SCRIPT,
    /flushPendingSaves\(\)[^\n]+handleStudyError\(error, true\)/,
  );
});

test("embedded reader handshake is same-origin, versioned, and URL-clean", () => {
  assert.match(SCRIPT, /const EMBED_READY = "lattice-study-ready"/);
  assert.match(SCRIPT, /const EMBED_CONTEXT = "lattice-study-context"/);
  assert.match(SCRIPT, /const EMBED_STATUS = "lattice-study-status"/);
  assert.match(SCRIPT, /event\.origin !== window\.location\.origin \|\| event\.source !== window\.parent/);
  assert.match(SCRIPT, /message\.type !== EMBED_CONTEXT \|\| message\.version !== EMBED_VERSION/);
  assert.match(SCRIPT, /postMessage\(\{ type: EMBED_READY, version: EMBED_VERSION \}, window\.location\.origin\)/);
  assert.match(SCRIPT, /type: EMBED_STATUS,[\s\S]*?dirty,[\s\S]*?saved:/);
  assert.match(SCRIPT, /state\.notebooks\.find\(\(notebook\) => notebook\.workPath === context\.workPath\)/);
  assert.match(SCRIPT, /workPath: context\.workPath/);
  assert.doesNotMatch(SCRIPT, /[?&](?:access|workPath|workTitle)=/);
  assert.doesNotMatch(HTML, /[?&](?:access|workPath|workTitle)=/);
});

test("Study Workspace keeps the private launch capability out of request URLs", () => {
  for (const source of [SCRIPT, APP]) {
    assert.match(source, /sessionStorage/);
    assert.match(source, /history\.replaceState/);
    assert.match(source, /X-Lattice-Private-Token/);
  }
  assert.doesNotMatch(SCRIPT, /[?&]access=/);
  assert.doesNotMatch(APP, /[?&]access=/);
});

test("Markdown and math render locally without trusting authored markup", () => {
  assert.match(SCRIPT, /function renderInlineMarkdown\(/);
  assert.match(SCRIPT, /document\.createTextNode/);
  assert.match(SCRIPT, /\.textContent = token/);
  assert.match(SCRIPT, /rel = "noopener noreferrer"/);
  assert.match(SCRIPT, /trust:\s*false/g);
  assert.doesNotMatch(SCRIPT, /\.innerHTML\s*=/);
  assert.match(KATEX, /version:"0\.18\.4"/);
  assert.match(NOTICES, /KaTeX 0\.18\.4/);
});

test("Python runs only through the guarded kernel API", () => {
  assert.match(HTML, /Only run code you trust/);
  assert.match(SCRIPT, /\/api\/study\/kernel\/run/);
  assert.match(SCRIPT, /\/api\/study\/kernel\/restart/);
  assert.match(SCRIPT, /await flushPendingSaves\(\);[\s\S]*?\/api\/study\/kernel\/run/);
  assert.doesNotMatch(SCRIPT, /\bsaveCell\s*\(/);
  assert.match(SCRIPT, /const notebookId = state\.currentId;[\s\S]*?body: JSON\.stringify\(\{ notebookId, source \}\)/);
  assert.match(SCRIPT, /state\.currentId === notebookId[\s\S]*?state\.cells\.find/);
  assert.match(SCRIPT, /output\.mime === "image\/png"/);
  assert.match(SCRIPT, /\.textContent = output\.(?:text|traceback)/);
  assert.doesNotMatch(SCRIPT, /\beval\s*\(|new Function\s*\(|pyodide/i);
});

test("keyboard shortcuts cover saving, cell work, navigation, and discovery", () => {
  assert.match(HTML, /Keyboard shortcuts/);
  assert.match(SCRIPT, /event\.key\.toLowerCase\(\) === "s"/);
  assert.match(SCRIPT, /event\.key === "Enter"/);
  assert.match(SCRIPT, /event\.altKey && \["m", "l", "p"\]/);
  assert.match(SCRIPT, /event\.key === "\/"/);
  assert.match(SCRIPT, /event\.key === "Tab"/);
  assert.match(SCRIPT, /event\.key === "Escape"/);
});

test("both desktop packages require the Study module and offline renderer", () => {
  for (const source of [MAC_BUILD, WINDOWS_BUILD]) {
    assert.match(source, /study_lab\.py/);
    assert.match(source, /study_python\.py/);
    assert.match(source, /study_kernel\.py/);
    assert.match(source, /study-lab\.js/);
    assert.match(source, /vendor[\\/]katex[\\/]katex\.min\.js/);
    assert.match(source, /KaTeX_Main-Regular\.woff2/);
  }
});
