import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const HTML = fs.readFileSync(new URL("../ui/index.html", import.meta.url), "utf8");
const APP = fs.readFileSync(new URL("../ui/app.js", import.meta.url), "utf8");
const STYLES = fs.readFileSync(new URL("../ui/styles.css", import.meta.url), "utf8");
const MAC_APP = fs.readFileSync(new URL("../native/CSLibraryApp.swift", import.meta.url), "utf8");
const PDF_READER = fs.readFileSync(new URL("../ui/pdf-reader.js", import.meta.url), "utf8");

test("every UI element binding resolves to one unique markup id", () => {
  const markupIds = [...HTML.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(markupIds).size, markupIds.length, "markup ids must be unique");
  const boundIds = [...APP.matchAll(/\$\("#([A-Za-z][\w-]*)"\)/g)].map((match) => match[1]);
  for (const id of boundIds) assert.ok(markupIds.includes(id), `missing markup for #${id}`);
});

test("Lattice presents a generic shared-library brand and separate catalog filters", () => {
  assert.match(HTML, /<title>Lattice<\/title>/);
  assert.match(HTML, /<strong>Lattice<\/strong>\s*<small>A shared knowledge library<\/small>/);
  assert.doesNotMatch(HTML, />CS Library</);
  assert.doesNotMatch(HTML, /Shared Library/);
  assert.match(HTML, /id="subjectNav"[^>]*aria-label="Broad subjects"/);
  assert.match(HTML, /id="shelfNav"[^>]*aria-label="Topic shelves"/);
  assert.match(HTML, /id="subjectChips"[^>]*aria-label="Subject filters"/);
  assert.match(HTML, /id="topicChips"[^>]*aria-label="Topic filters"/);
});

test("Add controls expose the native bridge picker and a multiple file input", () => {
  assert.match(HTML, /id="addButton"/);
  assert.match(HTML, /id="heroAddButton"/);
  assert.match(HTML, /id="addFilesInput"[^>]*multiple[^>]*hidden/);
  assert.match(HTML, /name="importKind" value="book"/);
  assert.match(HTML, /name="importKind" value="paper"/);
  assert.match(HTML, /name="importKind" value="lecture"/);
  assert.match(APP, /window\.sharedLibraryChooseFiles\s*=\s*\(\)\s*=>\s*openImportDialog\(\)/);
});

test("imports use the authenticated raw-body API contract", () => {
  assert.match(APP, /fetch\("\/api\/ai\/status"/);
  assert.match(APP, /fetch\("\/api\/import",\s*\{[\s\S]*?method:\s*"POST"/);
  assert.match(APP, /"X-Library-Token":\s*state\.token/);
  assert.match(APP, /"X-Library-Filename":\s*encodeURIComponent\(item\.file\.name\)/);
  assert.match(APP, /"X-Library-Kind":\s*item\.kind/);
  assert.match(APP, /body:\s*item\.file/);
  assert.match(APP, /new URLSearchParams\(\{ id:\s*item\.jobId, path:\s*item\.path \}\)/);
  assert.match(APP, /fetch\(`\/api\/import-status\?\$\{query\}`/);
  assert.match(APP, /fetch\("\/api\/metadata",\s*\{[\s\S]*?body:\s*JSON\.stringify\(body\)/);
  assert.match(APP, /IMPORT_STATUS_COMPLETE\s*=\s*new Set\(\[[^\]]*"fallback"[^\]]*"manual"/);
  assert.match(APP, /item\.status\s*=\s*item\.jobId\s*\?\s*"enriching"\s*:\s*"complete"/);
  assert.match(APP, /IMPORT_STATUS_FAILED\.has\(status\)[\s\S]*?item\.status\s*=\s*"failed"/);
  assert.match(APP, /item\.editableMetadata\s*=\s*payload\.editableMetadata\s*===\s*true/);
  assert.match(APP, /item\.status\s*===\s*"enriching"\) void pollImportStatus\(item\)/);
  assert.match(APP, /response\.status\s*===\s*404[\s\S]*?metadataStatus[\s\S]*?"ai-enriched"/);
});

test("macOS queues file-open imports until the local service is ready", () => {
  assert.match(MAC_APP, /guard libraryRoot != nil, currentServerURL != nil else \{\s*pendingOpenURLs\.append/);
  assert.match(MAC_APP, /guard let endpoint = serverEndpoint\("\/api\/library"\) else \{\s*pendingOpenURLs\.append/);
  assert.match(MAC_APP, /currentServerURL = url[\s\S]*?pendingOpenURLs\.removeAll\(\)[\s\S]*?importFiles\(pending\)/);
  assert.match(MAC_APP, /guard webInterfaceReady else \{\s*pendingAddMaterials = true/);
  assert.match(MAC_APP, /didFinish navigation:[\s\S]*?pendingAddMaterials[\s\S]*?showAddMaterialsDialog\(\)/);
  assert.match(MAC_APP, /chooseMaterialKind\(\)[\s\S]*?\["book", "paper", "lecture"\]/);
  assert.match(MAC_APP, /let duplicate = payload\?\["duplicate"\] as\? Bool == true/);
});

test("metadata editing sends the supported fields", () => {
  for (const field of ["path", "title", "authors", "year", "edition", "subjectIds", "topics"]) {
    assert.match(APP, new RegExp(`\\b${field}:`));
  }
  assert.match(APP, /state\.library\?\.subjects/);
  assert.match(APP, /checkbox\.name\s*=\s*"subjectIds"/);
  assert.match(APP, /formData\.getAll\("subjectIds"\)/);
  assert.match(APP, /body\.subjectId\s*=\s*body\.subjectIds\[0\]/);
  assert.match(APP, /subject\.known\s*===\s*false/);
  assert.match(APP, /work\.subjectIds\.includes\(state\.subject\)/);
  assert.match(APP, /textField\("Topics",\s*"topics"/);
  assert.match(APP, /item\.draft\s*=\s*body/);
  assert.match(APP, /item\.draft\s*\|\|\s*item\.metadata/);
  assert.match(APP, /form\.querySelectorAll\("input, select, button"\)/);
  assert.match(APP, /work\.editableMetadata\s*===\s*true/);
  assert.match(APP, /if \(item\.error\) return item\.error/);
});

test("overlapping shelf refreshes are coalesced instead of dropped", () => {
  assert.match(APP, /if \(state\.refreshing\) \{[\s\S]*?state\.refreshPending\s*=/);
  assert.match(APP, /if \(pending\) void refreshLibrary\(pending\.change, \{ quiet: pending\.quiet \}\)/);
});

test("file drags cannot navigate the host and begin importing immediately", () => {
  assert.match(APP, /window\.addEventListener\("dragover",[\s\S]*?event\.preventDefault\(\)/);
  assert.match(APP, /window\.addEventListener\("drop",[\s\S]*?event\.preventDefault\(\)/);
  assert.match(APP, /window\.addEventListener\("drop",[\s\S]*?queueImportFiles\(files\)/);
  assert.doesNotMatch(APP, /waitForKind/);
  assert.match(APP, /function queueImportFiles\(fileList\)[\s\S]*?items\.forEach\(\(item\) => uploadImport\(item\)\)/);
  assert.match(APP, /item\.status === "waiting" \? "\+"/);
  assert.match(STYLES, /\.import-item\.is-uploading \.import-item-status/);
  assert.doesNotMatch(STYLES, /\.import-item:not\(\.is-complete\):not\(\.is-failed\) \.import-item-status/);
  assert.match(HTML, /id="dropOverlay"/);
  assert.match(STYLES, /\.drop-overlay\s*\{/);
  assert.match(STYLES, /\.import-shell\s*\{/);
  assert.match(APP, /element\.inert\s*=\s*true/);
  assert.match(APP, /event\.key\s*!==\s*"Tab"[\s\S]*?event\.shiftKey[\s\S]*?last\.focus\(\)/);
  assert.match(APP, /!target\.closest\('\[aria-hidden="true"\], \[inert\]'\)/);
});

test("PDFs use the same embedded reader in native and web app modes", () => {
  assert.match(
    APP,
    /function showPdfReader\(work, file\)[\s\S]*?readerShell\.classList\.add\("is-pdf-web"\)[\s\S]*?readerPdf\.src = `\/pdf-reader\.html\?\$\{params\}`/,
  );
  assert.doesNotMatch(APP, /csLibraryNativeCall\("document\.open"/);
  assert.match(HTML, /id="pdfReader"[^>]*allow="fullscreen"[^>]*allowfullscreen/);
  assert.match(PDF_READER, /leaveFullscreenBeforeClose\(document\)/);
  assert.match(PDF_READER, /message\.type === "prepare-close"/);
  assert.match(APP, /message\.fullscreen === false\) finishReaderClose\(\)/);
  assert.match(APP, /sendPdfReaderMessage\("shortcut", \{ key: event\.key \}\)/);
  assert.match(
    APP,
    /state\.readerMode === "pdf"[\s\S]*?sendPdfReaderMessage\("shortcut", \{ key: Number\(direction\) < 0 \? "ArrowLeft" : "ArrowRight" \}\)/,
  );
});

test("existing CS Library state keys remain stable for upgrades", () => {
  for (const key of [
    "favorites",
    "statuses",
    "recent",
    "theme",
    "layout",
    "epub-settings",
    "epub-progress",
    "epub-bookmarks",
  ]) {
    assert.match(APP, new RegExp(`cs-library:${key}`));
  }
});
