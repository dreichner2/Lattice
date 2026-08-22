"use strict";

import * as pdfjsLib from "/vendor/pdfjs/build/pdf.min.mjs";
import {
  leaveFullscreenBeforeClose,
  pageDirectionForKey,
} from "/pdf-reader-lifecycle.mjs";

globalThis.pdfjsLib = pdfjsLib;

const {
  EventBus,
  FindState,
  LinkTarget,
  PDFFindController,
  PDFLinkService,
  PDFViewer,
  ScrollMode,
  SpreadMode,
} = await import("/vendor/pdfjs/web/pdf_viewer.mjs");

pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/build/pdf.worker.min.mjs";

const CHANNEL = "lattice-pdf-reader";
const STORAGE_KEY = "cs-library:pdf-state";
const ALLOWED_LAYOUTS = new Set(["continuous", "single", "spread"]);
const ALLOWED_SCALE_PRESETS = new Set(["auto", "page-fit", "page-width"]);
const MAX_SAVED_DOCUMENTS = 250;

const $ = (selector) => document.querySelector(selector);
const elements = {
  app: $("#pdfApp"),
  close: $("#closeButton"),
  documentKicker: $("#documentKicker"),
  documentTitle: $("#documentTitle"),
  documentStats: $("#documentStats"),
  error: $("#errorState"),
  errorDetail: $("#errorDetail"),
  errorOpen: $("#errorOpenButton"),
  errorTitle: $("#errorTitle"),
  findCount: $("#findCount"),
  findForm: $("#findForm"),
  findInput: $("#findInput"),
  findNext: $("#findNextButton"),
  findPrevious: $("#findPreviousButton"),
  fit: $("#fitSelect"),
  fullscreen: $("#fullscreenButton"),
  layoutSwitcher: $("#layoutSwitcher"),
  loading: $("#loadingState"),
  loadingDetail: $("#loadingDetail"),
  loadingPercent: $("#loadingPercent"),
  loadingProgress: $("#loadingProgress"),
  nextPage: $("#nextPageButton"),
  open: $("#openButton"),
  outlineTab: $("#outlineTab"),
  outlineView: $("#outlineView"),
  pageCount: $("#pageCount"),
  pageNumber: $("#pageNumberInput"),
  passwordCancel: $("#passwordCancelButton"),
  passwordDialog: $("#passwordDialog"),
  passwordError: $("#passwordError"),
  passwordForm: $("#passwordForm"),
  passwordInput: $("#passwordInput"),
  passwordTitle: $("#passwordTitle"),
  previousPage: $("#previousPageButton"),
  retry: $("#retryButton"),
  reveal: $("#revealButton"),
  rotate: $("#rotateButton"),
  sidebar: $("#sidebar"),
  sidebarButton: $("#sidebarButton"),
  sidebarClose: $("#sidebarCloseButton"),
  sidebarScrim: $("#sidebarScrim"),
  statusText: $("#statusText"),
  thumbnailsTab: $("#thumbnailsTab"),
  thumbnailsView: $("#thumbnailsView"),
  viewer: $("#viewer"),
  viewerContainer: $("#viewerContainer"),
  zoomIn: $("#zoomInButton"),
  zoomOut: $("#zoomOutButton"),
  zoomValue: $("#zoomValue"),
};

const query = new URLSearchParams(window.location.search);
const documentPath = normalizeDocumentPath(query.get("file") || "");
const requestedTitle = cleanLabel(query.get("title") || fileName(documentPath) || "PDF", 240);
const requestedWork = cleanLabel(query.get("work") || "Local document", 180);
const requestedTheme = query.get("theme") === "dark" ? "dark" : "light";
const startedAt = performance.now();

let loadingTask = null;
let pdfDocument = null;
let passwordCallback = null;
let savedState = readSavedState(documentPath);
let layout = normalizeLayout(savedState.layout);
let saveTimer = 0;
let ready = false;
let firstPageRendered = false;
let outlineLoaded = false;
let thumbnailsCreated = false;
let thumbnailObserver = null;
let lastFindQuery = "";
let closePending = false;

document.documentElement.dataset.theme = requestedTheme;
document.title = `${requestedTitle} — Lattice`;
elements.documentTitle.textContent = requestedTitle;
elements.documentKicker.textContent = requestedWork;

const eventBus = new EventBus();
const linkService = new PDFLinkService({
  eventBus,
  externalLinkTarget: LinkTarget.BLANK,
  externalLinkRel: "noopener noreferrer nofollow",
});
const findController = new PDFFindController({
  eventBus,
  linkService,
  updateMatchesCountOnProgress: true,
});
const pdfViewer = new PDFViewer({
  container: elements.viewerContainer,
  viewer: elements.viewer,
  eventBus,
  linkService,
  findController,
  annotationMode: pdfjsLib.AnnotationMode.ENABLE_FORMS,
  imageResourcesPath: "/vendor/pdfjs/web/images/",
  enableHWA: true,
  enableOptimizedPartialRendering: true,
  maxCanvasPixels: 24_000_000,
  removePageBorders: false,
  supportsPinchToZoom: true,
});
linkService.setViewer(pdfViewer);

function cleanLabel(value, maximum) {
  return String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, maximum);
}

function normalizeDocumentPath(value) {
  const path = String(value || "");
  if (
    !path
    || path.includes("\\")
    || path.includes("\0")
    || path.startsWith("/")
    || !path.toLowerCase().endsWith(".pdf")
  ) return "";
  const parts = path.split("/");
  if (
    !["books", "papers", "lectures"].includes(parts[0])
    || parts.some((part) => !part || part === "." || part === "..")
  ) return "";
  return parts.join("/");
}

function fileName(path) {
  return path.split("/").at(-1)?.replace(/\.pdf$/i, "") || "";
}

function contentUrl(path) {
  return `/content/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function postToShelf(type, detail = {}) {
  if (window.parent === window) return;
  window.parent.postMessage({ channel: CHANNEL, type, ...detail }, window.location.origin);
}

function normalizeLayout(value) {
  return ALLOWED_LAYOUTS.has(value) ? value : "continuous";
}

function normalizePage(value, maximum = Number.MAX_SAFE_INTEGER) {
  const page = Math.trunc(Number(value));
  return Number.isFinite(page) ? Math.min(maximum, Math.max(1, page)) : 1;
}

function normalizeRotation(value) {
  const rotation = Math.trunc(Number(value));
  return [0, 90, 180, 270].includes(rotation) ? rotation : 0;
}

function normalizeScale(value, fallback = "page-width") {
  if (ALLOWED_SCALE_PRESETS.has(value)) return value;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0.1 && numeric <= 8 ? numeric : fallback;
}

function readStateMap() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function readSavedState(path) {
  const value = readStateMap()[path];
  if (!value || typeof value !== "object") return {};
  return {
    page: normalizePage(value.page),
    layout: normalizeLayout(value.layout),
    scaleValue: normalizeScale(value.scaleValue),
    rotation: normalizeRotation(value.rotation),
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
  };
}

function persistState() {
  if (!documentPath || !ready) return;
  const value = {
    page: normalizePage(pdfViewer.currentPageNumber, pdfDocument?.numPages || Number.MAX_SAFE_INTEGER),
    layout,
    scaleValue: normalizeScale(pdfViewer.currentScaleValue, layout === "continuous" ? "page-width" : "page-fit"),
    rotation: normalizeRotation(pdfViewer.pagesRotation),
    updatedAt: new Date().toISOString(),
  };
  try {
    const stateMap = readStateMap();
    stateMap[documentPath] = value;
    const retained = Object.entries(stateMap)
      .sort(([, left], [, right]) => String(right?.updatedAt || "").localeCompare(String(left?.updatedAt || "")))
      .slice(0, MAX_SAVED_DOCUMENTS);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(retained)));
  } catch {
    // Reading remains available when browser storage is unavailable.
  }
  postToShelf("state", { path: documentPath, state: value });
}

function scheduleStateSave() {
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(persistState, 320);
}

function setLoadingProgress(loaded, total) {
  let percent = Number.isFinite(total) && total > 0 ? Math.round((loaded / total) * 100) : 0;
  percent = Math.min(96, Math.max(7, percent));
  elements.loadingProgress.style.width = `${percent}%`;
  elements.loadingPercent.textContent = total > 0
    ? `${percent}% of the bytes needed so far`
    : "Reading the document index";
}

function hideLoading() {
  if (elements.loading.hidden || elements.loading.classList.contains("is-fading")) return;
  firstPageRendered = true;
  const elapsed = Math.max(0.1, (performance.now() - startedAt) / 1000);
  elements.statusText.textContent = `Page ready in ${elapsed.toFixed(1)}s`;
  elements.loadingProgress.style.width = "100%";
  elements.loadingPercent.textContent = "First page ready";
  elements.loading.classList.add("is-fading");
  window.setTimeout(() => { elements.loading.hidden = true; }, 240);
  document.documentElement.dataset.pdfReady = "true";
  elements.app.dataset.ready = "true";
  postToShelf("rendered", { path: documentPath, page: pdfViewer.currentPageNumber, loadSeconds: Number(elapsed.toFixed(2)) });
}

function showError(title, detail) {
  elements.loading.hidden = true;
  elements.error.hidden = false;
  elements.errorTitle.textContent = title;
  elements.errorDetail.textContent = cleanLabel(detail, 500) || "Try opening the file in your system PDF app.";
  elements.statusText.textContent = "Could not open PDF";
  elements.app.dataset.ready = "error";
  document.documentElement.dataset.pdfReady = "error";
  postToShelf("error", { path: documentPath, error: elements.errorDetail.textContent });
}

function updatePageControls(pageNumber = pdfViewer.currentPageNumber || 1) {
  const count = pdfDocument?.numPages || 0;
  const page = normalizePage(pageNumber, count || Number.MAX_SAFE_INTEGER);
  elements.pageNumber.value = String(page);
  elements.pageCount.textContent = count ? `of ${count.toLocaleString()}` : "of —";
  elements.previousPage.disabled = !count || page <= 1;
  elements.nextPage.disabled = !count || page >= count;
  for (const thumbnail of elements.thumbnailsView.querySelectorAll(".thumbnail-button")) {
    thumbnail.classList.toggle("is-current", Number(thumbnail.dataset.page) === page);
  }
}

function updateZoom(scale = pdfViewer.currentScale || 1, presetValue = pdfViewer.currentScaleValue) {
  const numeric = Number(scale);
  elements.zoomValue.textContent = Number.isFinite(numeric) ? `${Math.round(numeric * 100)}%` : "—";
  if (ALLOWED_SCALE_PRESETS.has(presetValue)) elements.fit.value = presetValue;
}

function applyLayout(nextLayout, { chooseRecommendedScale = false } = {}) {
  layout = normalizeLayout(nextLayout);
  const page = pdfViewer.currentPageNumber || savedState.page || 1;
  if (layout === "continuous") {
    pdfViewer.scrollMode = ScrollMode.VERTICAL;
    pdfViewer.spreadMode = SpreadMode.NONE;
  } else if (layout === "single") {
    pdfViewer.scrollMode = ScrollMode.PAGE;
    pdfViewer.spreadMode = SpreadMode.NONE;
  } else {
    pdfViewer.scrollMode = ScrollMode.PAGE;
    pdfViewer.spreadMode = SpreadMode.ODD;
  }
  if (pdfDocument) pdfViewer.currentPageNumber = normalizePage(page, pdfDocument.numPages);
  if (chooseRecommendedScale && pdfDocument) {
    pdfViewer.currentScaleValue = layout === "continuous" ? "page-width" : "page-fit";
  }
  for (const button of elements.layoutSwitcher.querySelectorAll("[data-layout]")) {
    button.setAttribute("aria-pressed", String(button.dataset.layout === layout));
  }
  document.documentElement.dataset.layout = layout;
  scheduleStateSave();
}

function goToPage(value) {
  if (!pdfDocument) return;
  pdfViewer.currentPageNumber = normalizePage(value, pdfDocument.numPages);
  elements.viewerContainer.focus({ preventScroll: true });
}

function nextPage() {
  if (!pdfDocument) return;
  if (typeof pdfViewer.nextPage === "function") pdfViewer.nextPage();
  else goToPage(pdfViewer.currentPageNumber + (layout === "spread" ? 2 : 1));
}

function previousPage() {
  if (!pdfDocument) return;
  if (typeof pdfViewer.previousPage === "function") pdfViewer.previousPage();
  else goToPage(pdfViewer.currentPageNumber - (layout === "spread" ? 2 : 1));
}

function setSidebar(open) {
  elements.app.classList.toggle("sidebar-open", open);
  elements.sidebar.setAttribute("aria-hidden", String(!open));
  elements.sidebarButton.setAttribute("aria-expanded", String(open));
  if (open && !outlineLoaded) loadOutline();
}

function setSidebarTab(tab) {
  const pages = tab === "pages";
  elements.outlineTab.setAttribute("aria-selected", String(!pages));
  elements.thumbnailsTab.setAttribute("aria-selected", String(pages));
  elements.outlineView.hidden = pages;
  elements.thumbnailsView.hidden = !pages;
  if (pages) createThumbnails();
}

async function loadOutline() {
  if (!pdfDocument || outlineLoaded) return;
  outlineLoaded = true;
  try {
    const outline = await pdfDocument.getOutline();
    if (!outline?.length) {
      elements.outlineView.innerHTML = '<div class="sidebar-placeholder"><span>—</span><p>This PDF does not include a table of contents.</p></div>';
      return;
    }
    const list = document.createElement("ol");
    list.className = "outline-list";
    const appendItems = (items, parent, depth) => {
      for (const item of items) {
        const row = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = cleanLabel(item.title, 240) || "Untitled section";
        button.style.setProperty("--outline-depth", String(Math.min(depth, 7)));
        button.addEventListener("click", async () => {
          if (item.dest) await linkService.goToDestination(item.dest);
          else if (item.url) window.open(item.url, "_blank", "noopener,noreferrer");
          setSidebar(false);
        });
        row.append(button);
        if (item.items?.length) {
          const children = document.createElement("ol");
          appendItems(item.items, children, depth + 1);
          row.append(children);
        }
        parent.append(row);
      }
    };
    appendItems(outline, list, 0);
    elements.outlineView.replaceChildren(list);
  } catch (error) {
    elements.outlineView.innerHTML = '<div class="sidebar-placeholder"><span>!</span><p>The PDF contents could not be read.</p></div>';
  }
}

async function renderThumbnail(button) {
  if (!pdfDocument || button.dataset.rendered === "true") return;
  button.dataset.rendered = "true";
  const pageNumber = Number(button.dataset.page);
  try {
    const page = await pdfDocument.getPage(pageNumber);
    const unscaled = page.getViewport({ scale: 1 });
    const scale = Math.min(0.34, 126 / Math.max(1, unscaled.width));
    const viewport = page.getViewport({ scale });
    const canvas = document.createElement("canvas");
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.ceil(viewport.width * ratio);
    canvas.height = Math.ceil(viewport.height * ratio);
    canvas.style.width = `${Math.ceil(viewport.width)}px`;
    canvas.style.height = `${Math.ceil(viewport.height)}px`;
    const context = canvas.getContext("2d", { alpha: false });
    await page.render({
      canvasContext: context,
      viewport,
      transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
      background: "rgb(255,255,255)",
    }).promise;
    button.querySelector(".thumbnail-canvas-wrap")?.replaceChildren(canvas);
  } catch {
    button.querySelector(".thumbnail-canvas-wrap")?.replaceChildren(document.createTextNode("Unavailable"));
  }
}

function createThumbnails() {
  if (!pdfDocument || thumbnailsCreated) return;
  thumbnailsCreated = true;
  const fragment = document.createDocumentFragment();
  for (let page = 1; page <= pdfDocument.numPages; page += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "thumbnail-button";
    button.dataset.page = String(page);
    button.setAttribute("aria-label", `Go to page ${page}`);
    const wrap = document.createElement("span");
    wrap.className = "thumbnail-canvas-wrap";
    wrap.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.textContent = `Page ${page}`;
    button.append(wrap, label);
    button.addEventListener("click", () => {
      goToPage(page);
      setSidebar(false);
    });
    fragment.append(button);
  }
  elements.thumbnailsView.replaceChildren(fragment);
  thumbnailObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      thumbnailObserver.unobserve(entry.target);
      renderThumbnail(entry.target);
    }
  }, { root: elements.thumbnailsView, rootMargin: "180px" });
  for (const button of elements.thumbnailsView.querySelectorAll(".thumbnail-button")) {
    thumbnailObserver.observe(button);
  }
  updatePageControls();
}

function runFind({ previous = false, again = false } = {}) {
  const queryText = elements.findInput.value.trim();
  if (!queryText) {
    elements.findCount.textContent = "";
    eventBus.dispatch("findbarclose", { source: elements.findForm });
    return;
  }
  const isAgain = again && queryText === lastFindQuery;
  lastFindQuery = queryText;
  eventBus.dispatch("find", {
    source: elements.findForm,
    type: isAgain ? "again" : "",
    query: queryText,
    caseSensitive: false,
    entireWord: false,
    highlightAll: true,
    findPrevious: previous,
    matchDiacritics: true,
  });
}

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch (error) {
    elements.statusText.textContent = "Fullscreen was blocked";
  }
}

async function requestShelfAction(type) {
  if (type !== "close") {
    postToShelf(type, { path: documentPath });
    return;
  }
  if (closePending) return;

  closePending = true;
  elements.close.disabled = true;
  elements.close.setAttribute("aria-busy", "true");
  try {
    const exited = await leaveFullscreenBeforeClose(document);
    if (!exited) throw new Error("Fullscreen is still active");
    if (window.parent === window) window.location.assign("/");
    else postToShelf("close", { path: documentPath, fullscreen: false });
  } catch {
    closePending = false;
    elements.close.disabled = false;
    elements.close.removeAttribute("aria-busy");
    elements.statusText.textContent = "Exit fullscreen before returning to the shelf";
  }
}

function showPasswordPrompt(reason) {
  elements.passwordError.textContent = reason === pdfjsLib.PasswordResponses.INCORRECT_PASSWORD
    ? "That password was not accepted. Try again."
    : "";
  elements.passwordTitle.textContent = reason === pdfjsLib.PasswordResponses.INCORRECT_PASSWORD
    ? "The PDF password was incorrect"
    : "Enter the PDF password";
  elements.passwordInput.value = "";
  if (!elements.passwordDialog.open) elements.passwordDialog.showModal();
  window.setTimeout(() => elements.passwordInput.focus(), 0);
}

function applyIncomingState(value) {
  if (!value || typeof value !== "object") return;
  savedState = {
    page: normalizePage(value.page, pdfDocument?.numPages || Number.MAX_SAFE_INTEGER),
    layout: normalizeLayout(value.layout),
    scaleValue: normalizeScale(value.scaleValue),
    rotation: normalizeRotation(value.rotation),
  };
  if (ready && pdfDocument) restoreReadingState();
}

function restoreReadingState() {
  layout = normalizeLayout(savedState.layout);
  applyLayout(layout);
  pdfViewer.pagesRotation = normalizeRotation(savedState.rotation);
  pdfViewer.currentPageNumber = normalizePage(savedState.page, pdfDocument.numPages);
  pdfViewer.currentScaleValue = normalizeScale(
    savedState.scaleValue,
    layout === "continuous" ? "page-width" : "page-fit",
  );
  updatePageControls();
  updateZoom();
}

eventBus.on("pagesinit", () => {
  ready = true;
  restoreReadingState();
  elements.pageCount.textContent = `of ${pdfDocument.numPages.toLocaleString()}`;
  elements.documentStats.textContent = `${pdfDocument.numPages.toLocaleString()} pages · range loaded`;
  document.documentElement.dataset.pageCount = String(pdfDocument.numPages);
  postToShelf("ready", {
    path: documentPath,
    pageCount: pdfDocument.numPages,
    capabilities: ["range-loading", "search", "single-page", "two-page", "fullscreen", "rotation"],
  });
});

eventBus.on("pagerendered", (event) => {
  if (!firstPageRendered && event.pageNumber === pdfViewer.currentPageNumber) hideLoading();
});

eventBus.on("pagechanging", (event) => {
  updatePageControls(event.pageNumber);
  scheduleStateSave();
});

eventBus.on("scalechanging", (event) => {
  updateZoom(event.scale, event.presetValue);
  scheduleStateSave();
});

eventBus.on("rotationchanging", () => scheduleStateSave());
eventBus.on("updateviewarea", () => scheduleStateSave());

eventBus.on("updatefindmatchescount", (event) => {
  const { current = 0, total = 0 } = event.matchesCount || {};
  elements.findCount.textContent = total ? `${current || "—"} / ${total}` : "";
});

eventBus.on("updatefindcontrolstate", (event) => {
  const { current = 0, total = 0 } = event.matchesCount || {};
  if (event.state === FindState.NOT_FOUND) elements.findCount.textContent = "No results";
  else if (event.state === FindState.PENDING) elements.findCount.textContent = "Searching…";
  else if (total) elements.findCount.textContent = `${current || "—"} / ${total}`;
});

elements.close.addEventListener("click", () => void requestShelfAction("close"));
elements.open.addEventListener("click", () => void requestShelfAction("open"));
elements.errorOpen.addEventListener("click", () => void requestShelfAction("open"));
elements.reveal.addEventListener("click", () => void requestShelfAction("reveal"));
elements.retry.addEventListener("click", () => window.location.reload());
elements.fullscreen.addEventListener("click", toggleFullscreen);
elements.sidebarButton.addEventListener("click", () => setSidebar(!elements.app.classList.contains("sidebar-open")));
elements.sidebarClose.addEventListener("click", () => setSidebar(false));
elements.sidebarScrim.addEventListener("click", () => setSidebar(false));
elements.outlineTab.addEventListener("click", () => setSidebarTab("outline"));
elements.thumbnailsTab.addEventListener("click", () => setSidebarTab("pages"));
elements.previousPage.addEventListener("click", previousPage);
elements.nextPage.addEventListener("click", nextPage);
elements.pageNumber.addEventListener("change", () => goToPage(elements.pageNumber.value));
elements.pageNumber.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  goToPage(elements.pageNumber.value);
});
elements.zoomIn.addEventListener("click", () => pdfViewer.increaseScale());
elements.zoomOut.addEventListener("click", () => pdfViewer.decreaseScale());
elements.fit.addEventListener("change", () => { pdfViewer.currentScaleValue = elements.fit.value; });
elements.rotate.addEventListener("click", () => {
  pdfViewer.pagesRotation = (normalizeRotation(pdfViewer.pagesRotation) + 90) % 360;
});
for (const button of elements.layoutSwitcher.querySelectorAll("[data-layout]")) {
  button.addEventListener("click", () => applyLayout(button.dataset.layout, { chooseRecommendedScale: true }));
}
elements.findForm.addEventListener("submit", (event) => {
  event.preventDefault();
  runFind({ again: true });
});
elements.findPrevious.addEventListener("click", () => runFind({ previous: true, again: true }));
elements.findInput.addEventListener("input", () => runFind());

elements.passwordForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const password = elements.passwordInput.value;
  if (!password || !passwordCallback) return;
  const callback = passwordCallback;
  passwordCallback = null;
  elements.passwordDialog.close();
  callback(password);
});

elements.passwordCancel.addEventListener("click", () => {
  const callback = passwordCallback;
  passwordCallback = null;
  elements.passwordDialog.close();
  callback?.(new Error("Password entry was cancelled."));
});

document.addEventListener("fullscreenchange", () => {
  const active = Boolean(document.fullscreenElement);
  elements.fullscreen.textContent = active ? "↙" : "⛶";
  elements.fullscreen.setAttribute("aria-label", active ? "Exit fullscreen" : "Enter fullscreen");
  elements.fullscreen.title = active ? "Exit fullscreen (F11)" : "Fullscreen (F11)";
  document.documentElement.dataset.fullscreen = String(active);
  postToShelf("fullscreen", { path: documentPath, active });
});

function handlePageNavigationKey(key) {
  const direction = pageDirectionForKey(key);
  if (!direction) return false;
  if (direction > 0) nextPage();
  else previousPage();
  return true;
}

document.addEventListener("keydown", (event) => {
  const editing = event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement;
  if (event.key === "F11") {
    event.preventDefault();
    toggleFullscreen();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
    event.preventDefault();
    elements.findInput.focus();
    elements.findInput.select();
    return;
  }
  if (event.key === "Escape") {
    if (elements.passwordDialog.open) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else if (elements.app.classList.contains("sidebar-open")) setSidebar(false);
    else void requestShelfAction("close");
    return;
  }
  if (editing || event.ctrlKey || event.metaKey || event.altKey) return;
  if (handlePageNavigationKey(event.key)) {
    event.preventDefault();
  } else if (event.key === "+" || event.key === "=") {
    event.preventDefault();
    pdfViewer.increaseScale();
  } else if (event.key === "-") {
    event.preventDefault();
    pdfViewer.decreaseScale();
  } else if (event.key === "0") {
    event.preventDefault();
    pdfViewer.currentScaleValue = layout === "continuous" ? "page-width" : "page-fit";
  }
});

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin || event.source !== window.parent) return;
  const message = event.data;
  if (!message || message.channel !== CHANNEL) return;
  if (message.type === "theme") {
    document.documentElement.dataset.theme = message.theme === "dark" ? "dark" : "light";
  } else if (message.type === "initialize" && message.path === documentPath) {
    applyIncomingState(message.state);
  } else if (message.type === "focus") {
    elements.viewerContainer.focus({ preventScroll: true });
  } else if (message.type === "shortcut") {
    handlePageNavigationKey(message.key);
  } else if (message.type === "prepare-close") {
    void requestShelfAction("close");
  }
});

window.addEventListener("beforeunload", () => {
  window.clearTimeout(saveTimer);
  persistState();
  thumbnailObserver?.disconnect();
  loadingTask?.destroy();
});

async function openDocument() {
  if (!documentPath) {
    showError("This PDF link is invalid", "Lattice only opens PDF files already present in books, papers, or lectures.");
    return;
  }
  try {
    loadingTask = pdfjsLib.getDocument({
      url: contentUrl(documentPath),
      cMapUrl: "/vendor/pdfjs/cmaps/",
      cMapPacked: true,
      iccUrl: "/vendor/pdfjs/iccs/",
      standardFontDataUrl: "/vendor/pdfjs/standard_fonts/",
      wasmUrl: "/vendor/pdfjs/wasm/",
      disableRange: false,
      disableStream: true,
      disableAutoFetch: true,
      enableHWA: true,
      enableXfa: false,
      rangeChunkSize: 256 * 1024,
      stopAtErrors: false,
      useSystemFonts: true,
      useWasm: true,
      useWorkerFetch: true,
    });
    loadingTask.onProgress = ({ loaded, total }) => setLoadingProgress(loaded, total);
    loadingTask.onPassword = (updatePassword, reason) => {
      passwordCallback = updatePassword;
      showPasswordPrompt(reason);
    };
    pdfDocument = await loadingTask.promise;
    linkService.setDocument(pdfDocument, null);
    findController.setDocument(pdfDocument);
    pdfViewer.setDocument(pdfDocument);
    updatePageControls(savedState.page || 1);

    pdfDocument.getMetadata().then(({ info, contentLength }) => {
      const author = cleanLabel(info?.Author, 120);
      const length = Number(contentLength);
      const size = Number.isFinite(length) && length > 0 ? formatBytes(length) : "local file";
      elements.documentStats.textContent = `${pdfDocument.numPages.toLocaleString()} pages · ${size}${author ? ` · ${author}` : ""}`;
    }).catch(() => {});

    window.setTimeout(() => {
      if (ready && !firstPageRendered) {
        elements.loadingDetail.textContent = "The document is open; finishing the first visible page…";
      }
    }, 3500);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    showError("This PDF could not be opened", message);
  }
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let amount = value;
  let index = -1;
  do {
    amount /= 1024;
    index += 1;
  } while (amount >= 1024 && index < units.length - 1);
  return `${amount >= 100 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

postToShelf("boot", { path: documentPath, title: requestedTitle });
openDocument();
