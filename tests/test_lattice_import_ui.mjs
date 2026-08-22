import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const HTML = fs.readFileSync(new URL("../ui/index.html", import.meta.url), "utf8");
const APP = fs.readFileSync(new URL("../ui/app.js", import.meta.url), "utf8");
const STYLES = fs.readFileSync(new URL("../ui/styles.css", import.meta.url), "utf8");
const MAC_APP = fs.readFileSync(new URL("../native/CSLibraryApp.swift", import.meta.url), "utf8");
const MAC_BRIDGE = fs.readFileSync(new URL("../native/ReaderBridge.swift", import.meta.url), "utf8");
const MAC_BUILD = fs.readFileSync(new URL("../scripts/build-macos-app.sh", import.meta.url), "utf8");
const MAC_UPDATE = fs.readFileSync(new URL("../native/MacUpdateChecker.swift", import.meta.url), "utf8");
const MAC_INSTALLER = fs.readFileSync(new URL("../native/MacUpdateInstaller.swift", import.meta.url), "utf8");
const PDF_HTML = fs.readFileSync(new URL("../ui/pdf-reader.html", import.meta.url), "utf8");
const PDF_READER = fs.readFileSync(new URL("../ui/pdf-reader.js", import.meta.url), "utf8");
const PDF_STYLES = fs.readFileSync(new URL("../ui/pdf-reader.css", import.meta.url), "utf8");

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

test("macOS Move Library delegates to the verified shared storage helper", () => {
  assert.match(MAC_APP, /Move Library to External Storage…/);
  assert.match(MAC_APP, /#selector\(moveLibrary\(_:\)\)/);
  assert.match(MAC_APP, /--folder-id", "cs-library-3b8290f24f15"/);
  assert.match(MAC_APP, /--protected-path", Bundle\.main\.bundleURL\.path/);
  assert.match(MAC_APP, /copy and verify every file/);
  assert.match(MAC_APP, /libraryMoveInProgress/);
  assert.match(MAC_BUILD, /server\/move_library\.py/);
});

test("macOS reconnect distinguishes a running process from active library sync", () => {
  assert.match(MAC_APP, /payload\["folderPaused"\] as\? Bool == true/);
  assert.match(MAC_APP, /Resume this exact folder now\?/);
  assert.match(MAC_APP, /choice\.addButton\(withTitle: "Resume Sync"\)/);
  assert.match(MAC_APP, /arguments\.append\("--resume-existing-pause"\)/);
  assert.match(MAC_APP, /Library sync remains paused/);
});

test("desktop apps expose native actions in the inline header menu", () => {
  assert.match(HTML, /id="nativeAppMenu"[^>]*hidden/);
  assert.match(HTML, /id="appMoreButton"[^>]*aria-label="Lattice options"/);
  assert.match(HTML, /id="appCheckUpdatesButton"/);
  assert.match(HTML, /id="appMoveLibraryButton"/);
  assert.match(HTML, /id="appDisconnectLibraryButton"/);
  assert.match(HTML, /id="appReconnectLibraryButton"/);
  assert.match(HTML, /id="appOpenLibraryButton"[^>]*hidden/);
  assert.match(HTML, /id="appChooseLibraryButton"[^>]*hidden/);
  assert.match(HTML, /id="appReloadButton"[^>]*hidden/);
  assert.match(STYLES, /\.native-app-menu\s*\{[\s\S]*?position:\s*relative/);
  assert.match(STYLES, /\.app-more-button\s*\{/);
  assert.match(APP, /csLibraryNativeCall\("app\.info"\)/);
  assert.match(APP, /invokeNativeAppAction\("app\.checkForUpdates"\)/);
  assert.match(APP, /invokeNativeAppAction\("app\.moveLibrary"\)/);
  assert.match(APP, /invokeNativeAppAction\("app\.disconnectLibrary"\)/);
  assert.match(APP, /invokeNativeAppAction\("app\.reconnectLibrary"\)/);
  assert.match(APP, /invokeNativeAppAction\("app\.openLibraryFolder"\)/);
  assert.match(APP, /invokeNativeAppAction\("app\.chooseLibrary"\)/);
  assert.match(APP, /invokeNativeAppAction\("app\.reload"\)/);
  assert.match(APP, /\["macOS", "windows"\]\.includes\(info\.platform\)/);
  assert.match(APP, /info\.platform === "macOS"[\s\S]*?"app\.checkForUpdates", "app\.moveLibrary"/);
  assert.match(MAC_BRIDGE, /case "app\.info":/);
  assert.match(MAC_BRIDGE, /case "app\.checkForUpdates", "app\.moveLibrary", "app\.disconnectLibrary", "app\.reconnectLibrary":/);
  assert.match(MAC_APP, /#selector\(disconnectLibraryDrive\(_:\)\)/);
  assert.match(MAC_APP, /#selector\(reconnectLibrarySync\(_:\)\)/);
  assert.match(MAC_APP, /"version": self\?\.installedAppVersion\(\)/);
  assert.doesNotMatch(MAC_APP, /NSTitlebarAccessoryViewController/);
  assert.match(MAC_UPDATE, /releases\/latest\/download\/update-manifest\.json/);
  assert.match(MAC_UPDATE, /SecKeyVerifySignature/);
  assert.match(MAC_UPDATE, /Lattice-macOS\.zip/);
  assert.match(MAC_UPDATE, /github\.com/);
  assert.match(MAC_APP, /addButton\(withTitle: "Install Update"\)/);
  assert.match(MAC_APP, /Darwin\.kill\(reportedParentPID, 0\) == 0/);
  assert.match(MAC_APP, /"--no-browser",\s*"--isolated"/);
  assert.match(MAC_APP, /locateRunningLibrary\(requireCurrentParent: true\)/);
  assert.match(MAC_INSTALLER, /\/Applications\/Lattice\.app/);
  assert.match(MAC_INSTALLER, /archiveDigestMismatch/);
  assert.match(MAC_INSTALLER, /SecStaticCodeCheckValidity/);
  assert.match(MAC_INSTALLER, /cpuType == 0x0100_000c/);
  assert.match(MAC_INSTALLER, /candidateDidNotBecomeHealthy/);
  assert.match(MAC_INSTALLER, /moveItem\(at: backup, to: plan\.targetApplication\)/);
  assert.match(MAC_INSTALLER, /helper-plan\.json/);
  assert.match(MAC_INSTALLER, /candidate-activation\.json/);
  assert.match(MAC_INSTALLER, /guard arguments\.count == 3,[\s\S]*?arguments\[1\] == candidateFlag/);
  assert.match(MAC_INSTALLER, /process\.arguments = \[helperFlag, prepared\.operationID\]/);
  assert.match(MAC_INSTALLER, /arguments: \[candidateFlag, plan\.operationID\]/);
  assert.doesNotMatch(MAC_INSTALLER, /process\.arguments = \[helperFlag[^\n]*prepared\.token/);
  assert.doesNotMatch(MAC_INSTALLER, /arguments: \[candidateFlag[^\n]*plan\.token/);
  assert.match(MAC_BUILD, /MacUpdateChecker\.swift/);
  assert.match(MAC_BUILD, /MacUpdateInstaller\.swift/);
  assert.match(MAC_BUILD, /-framework Security/);
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

test("PDFs expose the same distraction-free focus mode as EPUBs", () => {
  assert.match(PDF_HTML, /id="focusButton"[^>]*aria-pressed="false"[^>]*aria-keyshortcuts="F"/);
  assert.match(PDF_HTML, /id="focusExitButton"[^>]*Show PDF controls[^>]*hidden/);
  assert.match(PDF_STYLES, /\.pdf-app\.is-focused\s*\{[\s\S]*?grid-template-rows:\s*0 minmax\(0, 1fr\)/);
  assert.match(PDF_STYLES, /\.pdf-app\.is-focused \.reader-main\s*\{[\s\S]*?grid-template-rows:\s*0 minmax\(0, 1fr\) 0/);
  assert.match(PDF_READER, /function setFocusMode\(focused/);
  assert.match(PDF_READER, /postToShelf\("focus-mode", \{ path: documentPath, active: next \}\)/);
  assert.match(PDF_READER, /message\.type === "toggle-focus"/);
  assert.match(PDF_READER, /event\.key\.toLowerCase\(\) === "f"/);
  assert.match(APP, /window\.csLibraryToggleReaderFocus = toggleActiveReaderFocus/);
  assert.match(MAC_APP, /window\.csLibraryToggleReaderFocus\?\.\(\)/);
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
