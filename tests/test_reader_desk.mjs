import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import test from "node:test";

const require = createRequire(import.meta.url);
const desk = require("../ui/reader-desk.js");
const HTML = fs.readFileSync(new URL("../ui/index.html", import.meta.url), "utf8");
const SOURCE = fs.readFileSync(new URL("../ui/reader-desk.js", import.meta.url), "utf8");
const STYLES = fs.readFileSync(new URL("../ui/reader-desk.css", import.meta.url), "utf8");
const APP = fs.readFileSync(new URL("../ui/app.js", import.meta.url), "utf8");
const PDF = fs.readFileSync(new URL("../ui/pdf-reader.js", import.meta.url), "utf8");
const WORKSPACE = fs.readFileSync(new URL("../native/LibraryWorkspace.js", import.meta.url), "utf8");
const IMMERSIVE = fs.readFileSync(new URL("../native/ImmersiveEPUB.js", import.meta.url), "utf8");

const descriptor = {
  path: "books/example.pdf",
  workId: "example",
  sha256: "a".repeat(64),
  title: "Example",
  workTitle: "Example",
  format: "PDF",
};

test("reader locators preserve one-based PDF pages and distinct EPUB positions", () => {
  assert.deepEqual(desk.normalizeLocator({ type: "pdf", page: 7 }), { type: "pdf", page: 7 });
  assert.deepEqual(desk.normalizeLocator({ type: "pdf", page: 0 }), { type: "pdf", page: 1 });
  assert.equal(desk.locatorKey({ type: "pdf", page: 7 }), "pdf:7");

  const first = { type: "epub", entry: "text/chapter.xhtml", index: 2, ratio: 0.125, pageIndex: 1, pageCount: 8 };
  const second = { ...first, ratio: 0.75, pageIndex: 6 };
  assert.notEqual(desk.locatorKey(first), desk.locatorKey(second));
  assert.equal(desk.normalizeLocator(first).pageIndex, 1);
});

test("captured passages and edited notes retain the location where they were authored", () => {
  assert.deepEqual(desk.resolveSavedNoteLocation({
    selectionLocator: { type: "pdf", page: 4 },
    selectionLabel: "Page 4",
    currentLocator: { type: "pdf", page: 12 },
    currentLabel: "Page 12",
  }), {
    locator: { type: "pdf", page: 4 },
    label: "Page 4",
  });

  const original = {
    locator: { type: "epub", entry: "text/one.xhtml", index: 1, ratio: 0.25, pageIndex: 2, pageCount: 8 },
    label: "The original chapter",
  };
  assert.deepEqual(desk.resolveSavedNoteLocation({
    existing: original,
    selectionLocator: { type: "pdf", page: 9 },
    selectionLabel: "Page 9",
    currentLocator: { type: "pdf", page: 12 },
    currentLabel: "Page 12",
  }), original);
});

test("edition keys prefer the digest and durable storage keeps only object documents", () => {
  assert.equal(desk.documentKey(descriptor), `sha256:${"a".repeat(64)}`);
  assert.equal(desk.documentKey({ ...descriptor, sha256: "" }), "path:books/example.pdf");
  assert.deepEqual(desk.normalizeStore({ documents: { ok: { updatedAt: 2 }, broken: null } }), {
    version: 1,
    documents: { ok: { updatedAt: 2 } },
    legacyMigrations: { epubBookmarksByPath: {}, nativeNotesByTitle: {} },
  });
});

test("legacy EPUB migrations are claimed once by title and path across digest changes", () => {
  const firstEdition = {
    path: "books/example.epub",
    title: "Example",
    format: "EPUB",
    sha256: "a".repeat(64),
  };
  const changedDigest = { ...firstEdition, sha256: "b".repeat(64) };
  const sameTitleDifferentPath = { ...changedDigest, path: "books/other-example.epub" };
  const store = desk.normalizeStore({ documents: {} });

  assert.equal(desk.claimLegacyNativeNotesMigration(store, { ...firstEdition, format: "PDF", path: "books/example.pdf" }), false);
  assert.equal(desk.claimLegacyNativeNotesMigration(store, { ...firstEdition, path: "books/not-an-epub.pdf" }), false);
  assert.deepEqual(store.legacyMigrations.nativeNotesByTitle, {});
  assert.equal(desk.claimLegacyNativeNotesMigration(store, firstEdition), true);
  assert.equal(store.legacyMigrations.nativeNotesByTitle.Example, "books/example.epub");
  assert.equal(desk.claimLegacyNativeNotesMigration(store, changedDigest), false);
  assert.equal(desk.claimLegacyNativeNotesMigration(store, sameTitleDifferentPath), false);

  const upgraded = desk.normalizeStore({
    documents: {
      "sha256:old": {
        descriptor: firstEdition,
        migrations: { epubBookmarks: true, nativeNotes: true },
      },
    },
  });
  assert.equal(upgraded.legacyMigrations.epubBookmarksByPath["books/example.epub"], true);
  assert.equal(upgraded.legacyMigrations.nativeNotesByTitle.Example, "books/example.epub");
});

test("Study Lab context uses a strict source handshake and never puts context in its URL", () => {
  assert.deepEqual(desk.buildStudyContext(descriptor, "lab", true), {
    workPath: "books/example.pdf",
    workTitle: "Example",
    mode: "lab",
    compact: true,
  });
  assert.doesNotMatch(JSON.stringify(desk.buildStudyContext(descriptor)), /sha256|workId|token|access/i);
  assert.match(SOURCE, /event\.origin !== window\.location\.origin \|\| event\.source !== elements\.labFrame\.contentWindow/);
  assert.match(SOURCE, /type: "lattice-study-context", version: 1, context/);
  assert.match(SOURCE, /elements\.labFrame\.src = "\/study-lab\.html"/);
  assert.doesNotMatch(SOURCE, /study-lab\.html\?/);
  assert.doesNotMatch(SOURCE, /study-lab\.html#/);
});

test("shared desk exposes Notes, full Study Lab, and exact bookmarks responsively", () => {
  const ids = [...HTML.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(ids.filter((id, index) => ids.indexOf(id) !== index), []);
  for (const id of [
    "readerDeskButton",
    "readerDeskNotesView",
    "readerDeskLabView",
    "readerStudyLab",
    "readerDeskBookmarksView",
    "readerDeskDraft",
  ]) assert.match(HTML, new RegExp(`id="${id}"`));
  assert.match(STYLES, /@media \(min-width: 1100px\)[\s\S]*grid-template-columns: minmax\(0, 1fr\) minmax\(350px, 29vw\)/);
  assert.match(STYLES, /@media \(max-width: 700px\)[\s\S]*transform: translateY\(104%\)/);
  assert.match(STYLES, /@media \(max-width: 1099px\)[\s\S]*reader-desk-scrim/);
  assert.match(STYLES, /\.reader-content-pane \{[\s\S]*width: 100%;[\s\S]*height: 100%;[\s\S]*overflow: auto;/);
  assert.match(STYLES, /\.reader-shell\.is-pdf-web \.reader-content-pane,[\s\S]*\.reader-shell\.is-epub \.reader-content-pane \{[\s\S]*overflow: hidden;/);
  assert.match(SOURCE, /localStorage\.setItem\(STORAGE_KEY/);
  assert.match(SOURCE, /cs-library-reader-save-annotation/);
  assert.match(SOURCE, /cs-library-reader-bookmark-toggle/);
  assert.match(HTML, /id="readerDesk"[^>]*aria-hidden="true"[^>]*\sinert(?:\s|>)/);
  assert.match(SOURCE, /root\.inert = !interactive/);
  assert.match(SOURCE, /fallbackTabIndexes[\s\S]*element\.setAttribute\("tabindex", "-1"\)/);
  assert.match(SOURCE, /active\.format === "epub"[\s\S]*LEGACY_NATIVE_NOTES_KEY/);
  assert.match(SOURCE, /legacyMigrations\.nativeNotesByTitle/);
  assert.doesNotMatch(SOURCE, /(?:removeItem|setItem)\(LEGACY_(?:EPUB_BOOKMARKS|NATIVE_NOTES)_KEY/);
});

test("PDF and EPUB readers report locators and navigate through the shared desk", () => {
  assert.match(PDF, /message\.type === "navigate"[\s\S]*goToPage\(message\.page \?\? message\.locator\?\.page\)/);
  assert.match(PDF, /postToShelf\("location"[\s\S]*normalizePage\(event\.pageNumber/);
  assert.match(PDF, /postToShelf\("toggle-bookmark", \{ path: documentPath, page \}\)/);
  assert.match(PDF, /closest\?\.\("\.page\[data-page-number\]"\)[\s\S]*pageElement\.dataset\.pageNumber/);
  assert.match(APP, /message\.type === "selection"[\s\S]*setSelection\(message\.text, \{ type: "pdf", page \}, `Page \$\{page\}`\)/);
  assert.match(APP, /message\.type === "navigate"|sendPdfReaderMessage\("navigate"/);
  assert.match(APP, /state\.readerDesk\.toggleCurrentBookmark\(\)/);
  assert.match(APP, /pageIndex: metrics\.pageIndex,[\s\S]*pageCount: metrics\.pageCount/);
});

test("native injections keep persistence while suppressing their duplicate panels", () => {
  assert.match(WORKSPACE, /hasSharedReaderDesk/);
  assert.match(WORKSPACE, /cs-library-reader-native-snapshot/);
  assert.match(IMMERSIVE, /hasSharedReaderDesk/);
  assert.match(IMMERSIVE, /#readerDeskButton:not\(\[hidden\]\)/);
});
