"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const STORAGE = {
  favorites: "cs-library:favorites",
  statuses: "cs-library:statuses",
  recent: "cs-library:recent",
  theme: "cs-library:theme",
  layout: "cs-library:layout",
  epubSettings: "cs-library:epub-settings",
  epubProgress: "cs-library:epub-progress",
  epubBookmarks: "cs-library:epub-bookmarks",
};

const DEFAULT_EPUB_SETTINGS = Object.freeze({
  font: "serif",
  fontSize: 19,
  lineHeight: 1.7,
  pageWidth: 760,
  tone: "paper",
});

const IS_NATIVE_APP = new URLSearchParams(window.location.search).get("app") === "1";

const state = {
  library: null,
  token: "",
  query: "",
  view: "all",
  subject: "all",
  sort: "title",
  layout: readStorage(STORAGE.layout, "grid"),
  favorites: new Set(readStorage(STORAGE.favorites, [])),
  statuses: readStorage(STORAGE.statuses, {}),
  recent: readStorage(STORAGE.recent, {}),
  selectedId: null,
  workById: new Map(),
  revision: 0,
  eventSource: null,
  refreshTimer: null,
  refreshing: false,
  readerPath: "",
  readerWorkId: "",
  readerMode: "",
  readerLastFocus: null,
  epubPackage: null,
  epubIndex: -1,
  epubEntry: "",
  epubPageIndex: 0,
  epubFocused: false,
  epubRestoreRatio: null,
  nativeReaderRestore: null,
  epubScrollFrame: 0,
  epubSaveTimer: 0,
  epubTurnTimer: 0,
  epubTurning: false,
  epubSettings: { ...DEFAULT_EPUB_SETTINGS, ...readStorage(STORAGE.epubSettings, {}) },
  epubProgress: readStorage(STORAGE.epubProgress, {}) || {},
  epubBookmarks: readStorage(STORAGE.epubBookmarks, {}) || {},
};

const elements = {
  allCount: $("#allCount"),
  allFileCount: $("#allFileCount"),
  artifactStat: $("#artifactStat"),
  clearFilters: $("#clearFiltersButton"),
  clearRecent: $("#clearRecentButton"),
  drawer: $("#detailDrawer"),
  drawerBody: $("#drawerBody"),
  drawerClose: $("#drawerClose"),
  drawerScrim: $("#drawerScrim"),
  empty: $("#emptyState"),
  favoriteCount: $("#favoriteCount"),
  finishedCount: $("#finishedCount"),
  focusSearch: $("#focusSearchButton"),
  grid: $("#libraryGrid"),
  integrityStat: $("#integrityStat"),
  menuButton: $("#menuButton"),
  materialNav: $("#materialNav"),
  mobileScrim: $("#mobileScrim"),
  random: $("#randomButton"),
  readerBack: $("#readerBackButton"),
  readerBackdrop: $("#readerBackdrop"),
  readerBookmark: $("#readerBookmarkButton"),
  readerClose: $("#readerCloseButton"),
  readerDocument: $("#documentReader"),
  readerFinder: $("#readerFinderButton"),
  readerFocus: $("#readerFocusButton"),
  readerKicker: $("#readerKicker"),
  readerLoading: $("#readerLoading"),
  readerMac: $("#readerMacButton"),
  readerPdf: $("#pdfReader"),
  readerSettings: $("#readerSettingsButton"),
  readerShell: $("#readerShell"),
  readerStage: $("#readerStage"),
  readerTitle: $("#readerTitle"),
  readerToc: $("#readerTocButton"),
  readingCount: $("#readingCount"),
  recentRow: $("#recentRow"),
  recentSection: $("#recentSection"),
  resultCount: $("#resultCount"),
  search: $("#searchInput"),
  sectionEyebrow: $("#sectionEyebrow"),
  sectionTitle: $("#sectionTitle"),
  shelfNav: $("#shelfNav"),
  sidebarStatusDot: $("#sidebarStatusDot"),
  sidebarStatusText: $("#sidebarStatusText"),
  sizeStat: $("#sizeStat"),
  sort: $("#sortSelect"),
  subjectChips: $("#subjectChips"),
  theme: $("#themeButton"),
  syncPill: $("#syncPill"),
  syncText: $("#syncText"),
  toastRegion: $("#toastRegion"),
  viewButton: $("#viewButton"),
  workStat: $("#workStat"),
  epubBookmarkList: $("#epubBookmarkList"),
  epubBookmarks: $("#epubBookmarks"),
  epubChapterLabel: $("#epubChapterLabel"),
  epubFontOptions: $("#epubFontOptions"),
  epubFontSize: $("#epubFontSize"),
  epubFontSizeValue: $("#epubFontSizeValue"),
  epubFrame: $("#epubFrame"),
  epubFrameWrap: $("#epubFrameWrap"),
  epubFocusExit: $("#epubFocusExit"),
  epubLineHeight: $("#epubLineHeight"),
  epubLineHeightValue: $("#epubLineHeightValue"),
  epubNext: $("#epubNext"),
  epubNextLabel: $("#epubNextLabel"),
  epubPageWidth: $("#epubPageWidth"),
  epubPageWidthValue: $("#epubPageWidthValue"),
  epubPanelScrim: $("#epubPanelScrim"),
  epubPrevious: $("#epubPrevious"),
  epubPreviousLabel: $("#epubPreviousLabel"),
  epubProgressBar: $("#epubProgressBar"),
  epubProgressLabel: $("#epubProgressLabel"),
  epubReader: $("#epubReader"),
  epubResetSettings: $("#epubResetSettings"),
  epubSettingsClose: $("#epubSettingsClose"),
  epubSettingsPanel: $("#epubSettingsPanel"),
  epubTocClose: $("#epubTocClose"),
  epubTocList: $("#epubTocList"),
  epubTocPanel: $("#epubTocPanel"),
  epubTocSearch: $("#epubTocSearch"),
  epubToneOptions: $("#epubToneOptions"),
};

function readStorage(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

function writeStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // The catalog remains fully usable when browser storage is unavailable.
  }
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function button(className, text, action, label = text) {
  const element = node("button", className, text);
  element.type = "button";
  element.setAttribute("aria-label", label);
  element.addEventListener("click", action);
  return element;
}

function humanBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes;
  let unit = -1;
  do {
    size /= 1024;
    unit += 1;
  } while (size >= 1024 && unit < units.length - 1);
  return `${size >= 100 ? size.toFixed(0) : size.toFixed(1)} ${units[unit]}`;
}

function monogram(title) {
  const words = title
    .replace(/[^A-Za-z0-9 ]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .filter((word, index) => index > 0 || !["the", "a", "an"].includes(word.toLowerCase()));
  if (!words.length) return "CS";
  return words.slice(0, 2).map((word) => word[0].toUpperCase()).join("");
}

function compactSubject(subject) {
  return subject.replace(" & ", " · ");
}

function primaryFile(work) {
  return work.files[0];
}

function isBrowserReadable(file) {
  return ["EPUB", "PDF", "TXT"].includes(file.format);
}

function contentUrl(path) {
  return `/content/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function documentUrl(path) {
  return `/document/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function epubPackageUrl(path) {
  return `/api/epub?path=${encodeURIComponent(path)}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function inlineMarkdown(value) {
  const tokens = [];
  const stash = (html) => {
    const index = tokens.push(html) - 1;
    return `\u0001TOKEN${index}\u0002`;
  };
  let prepared = String(value).replace(/`([^`\n]+)`/g, (_match, code) => {
    const localPath = String(code).trim();
    if (/^(books|papers)\/[^\s`]+\/?$/.test(localPath)) {
      return stash(`<a href="#" class="md-book-link" data-md-link="${escapeHtml(localPath)}"><code>${escapeHtml(localPath)}</code><span>Open</span></a>`);
    }
    return stash(`<code>${escapeHtml(code)}</code>`);
  });
  prepared = prepared.replace(/(!?)\[([^\]]+)]\(([^)\s]+)(?:\s+["'][^)]*["'])?\)/g, (_match, image, label, target) => {
    if (image) return stash(`<span class="md-image-note">Image: ${escapeHtml(label)}</span>`);
    const cleanTarget = String(target).trim();
    const safeTarget = /^(https?:\/\/|#|\/|\.{0,2}\/|[A-Za-z0-9_.-][^:]*)/i.test(cleanTarget)
      && !/^(javascript|data|file):/i.test(cleanTarget);
    if (!safeTarget) return escapeHtml(label);
    return stash(`<a href="#" data-md-link="${escapeHtml(cleanTarget)}">${escapeHtml(label)}</a>`);
  });
  let rendered = escapeHtml(prepared)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|[\s(])_([^_\n]+)_/g, "$1<em>$2</em>")
    .replace(/~~([^~]+)~~/g, "<del>$1</del>");
  rendered = rendered.replace(/\u0001TOKEN(\d+)\u0002/g, (_match, index) => tokens[Number(index)] || "");
  return rendered;
}

function markdownCells(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function headingId(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "section";
}

function renderMarkdown(markdown) {
  const lines = String(markdown).replace(/\r\n?/g, "\n").replace(/<!--[\s\S]*?-->/g, "").split("\n");
  const output = [];
  let index = 0;
  const isSpecial = (line, next = "") => (
    !line.trim()
    || /^\s*```/.test(line)
    || /^#{1,6}\s+/.test(line)
    || /^\s*>/.test(line)
    || /^\s*([-*+] |\d+[.)] )/.test(line)
    || /^\s*((-{3,})|(\*{3,})|(_{3,}))\s*$/.test(line)
    || (line.includes("|") && /^\s*\|?\s*:?-{3,}/.test(next))
  );

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const fence = line.match(/^\s*```\s*([\w-]*)/);
    if (fence) {
      const code = [];
      index += 1;
      while (index < lines.length && !/^\s*```/.test(lines[index])) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      const language = fence[1] ? ` data-language="${escapeHtml(fence[1])}"` : "";
      output.push(`<pre${language}><code>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2].replace(/\s+#+\s*$/, "");
      output.push(`<h${level} id="${headingId(text)}">${inlineMarkdown(text)}</h${level}>`);
      index += 1;
      continue;
    }
    if (/^\s*((-{3,})|(\*{3,})|(_{3,}))\s*$/.test(line)) {
      output.push("<hr>");
      index += 1;
      continue;
    }
    if (line.includes("|") && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const headers = markdownCells(line);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) rows.push(markdownCells(lines[index++]));
      output.push(`<div class="doc-table-wrap"><table><thead><tr>${headers.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_header, cellIndex) => `<td>${inlineMarkdown(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quote = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(lines[index++].replace(/^\s*>\s?/, ""));
      output.push(`<blockquote>${inlineMarkdown(quote.join(" "))}</blockquote>`);
      continue;
    }
    const listMatch = line.match(/^\s*([-*+]|\d+[.)])\s+(.+)$/);
    if (listMatch) {
      const ordered = /^\d/.test(listMatch[1]);
      const tag = ordered ? "ol" : "ul";
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*([-*+]|\d+[.)])\s+(.+)$/);
        if (!item || /^\d/.test(item[1]) !== ordered) break;
        let content = item[2];
        index += 1;
        while (index < lines.length && /^\s{2,}\S/.test(lines[index]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[index])) {
          content += ` ${lines[index].trim()}`;
          index += 1;
        }
        const task = content.match(/^\[([ xX])]\s+(.+)$/);
        if (task) content = `<span class="task-box${task[1].trim() ? " is-checked" : ""}" aria-hidden="true"></span>${inlineMarkdown(task[2])}`;
        else content = inlineMarkdown(content);
        items.push(`<li>${content}</li>`);
      }
      output.push(`<${tag}>${items.join("")}</${tag}>`);
      continue;
    }
    const paragraph = [line.trim()];
    index += 1;
    while (index < lines.length && !isSpecial(lines[index], lines[index + 1] || "")) paragraph.push(lines[index++].trim());
    output.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
  }
  return output.join("\n");
}

function setLiveStatus(mode, message) {
  elements.syncPill.dataset.status = mode;
  elements.syncText.textContent = message;
  elements.sidebarStatusDot.dataset.status = mode;
  elements.sidebarStatusText.textContent = mode === "live" ? "Watching books & papers" : message;
}

function workStatus(id) {
  return state.statuses[id] || "unread";
}

function statusLabel(status) {
  return { unread: "Not started", reading: "Reading", finished: "Finished" }[status] || "Not started";
}

function announce(message, isError = false) {
  const toast = node("div", `toast${isError ? " is-error" : ""}`, message);
  elements.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 3200);
}

function persistActivity() {
  writeStorage(STORAGE.favorites, [...state.favorites]);
  writeStorage(STORAGE.statuses, state.statuses);
  writeStorage(STORAGE.recent, state.recent);
}

function recordOpen(work) {
  state.recent[work.id] = Date.now();
  if (workStatus(work.id) === "unread") state.statuses[work.id] = "reading";
  persistActivity();
  renderNavigationCounts();
  renderRecent();
}

async function localAction(path, action) {
  const response = await fetch("/api/action", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Library-Token": state.token,
    },
    body: JSON.stringify({ path, action }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Local action failed");
  return payload;
}

function showReaderShell(title, kicker, mode) {
  if (!document.body.classList.contains("reader-open")) state.readerLastFocus = document.activeElement;
  state.readerMode = mode;
  elements.readerTitle.textContent = title;
  elements.readerKicker.textContent = kicker;
  elements.readerLoading.hidden = false;
  elements.readerPdf.hidden = true;
  elements.readerDocument.hidden = true;
  elements.epubReader.hidden = true;
  elements.readerToc.hidden = true;
  elements.readerSettings.hidden = true;
  elements.readerBookmark.hidden = true;
  elements.readerFocus.hidden = mode !== "epub";
  elements.readerFocus.setAttribute("aria-pressed", "false");
  elements.readerFocus.setAttribute("aria-label", "Focus on the page");
  elements.readerFocus.title = "Focus on the page";
  elements.epubFocusExit.hidden = true;
  state.epubFocused = false;
  elements.readerShell.classList.remove("is-focused");
  elements.readerShell.classList.toggle("is-epub", mode === "epub");
  document.body.classList.add("reader-open");
  elements.readerShell.setAttribute("aria-hidden", "false");
  elements.readerBack.focus();
  closeDrawer();
  closeMobileMenu();
}

function closeReader() {
  saveEpubPosition();
  window.dispatchEvent(new CustomEvent("cs-library-reader-closed"));
  window.clearTimeout(state.epubSaveTimer);
  window.clearTimeout(state.epubTurnTimer);
  window.cancelAnimationFrame(state.epubScrollFrame);
  document.body.classList.remove("reader-open");
  elements.readerShell.setAttribute("aria-hidden", "true");
  elements.readerShell.classList.remove("is-epub", "is-focused");
  delete elements.readerShell.dataset.path;
  delete elements.readerShell.dataset.workId;
  delete elements.readerShell.dataset.format;
  elements.readerPdf.src = "about:blank";
  elements.epubFrame.src = "about:blank";
  elements.readerPdf.hidden = true;
  elements.epubReader.hidden = true;
  elements.readerDocument.hidden = true;
  elements.readerDocument.replaceChildren();
  closeEpubPanels();
  elements.readerMac.hidden = true;
  elements.readerFinder.hidden = true;
  elements.readerToc.hidden = true;
  elements.readerSettings.hidden = true;
  elements.readerBookmark.hidden = true;
  elements.readerFocus.hidden = true;
  elements.readerFocus.setAttribute("aria-pressed", "false");
  elements.readerFocus.setAttribute("aria-label", "Focus on the page");
  elements.readerFocus.title = "Focus on the page";
  elements.epubFocusExit.hidden = true;
  state.readerPath = "";
  state.readerWorkId = "";
  state.readerMode = "";
  state.epubPackage = null;
  state.epubIndex = -1;
  state.epubEntry = "";
  state.epubPageIndex = 0;
  state.epubFocused = false;
  state.epubTurning = false;
  state.epubRestoreRatio = null;
  state.nativeReaderRestore = null;
  elements.epubFrame.classList.remove("is-page-turning");
  if (state.readerLastFocus && document.contains(state.readerLastFocus)) state.readerLastFocus.focus();
  state.readerLastFocus = null;
}

window.csLibraryCloseReader = closeReader;

function configureLocalReaderActions(work, file) {
  state.readerPath = file.path;
  state.readerWorkId = work.id;
  elements.readerShell.dataset.path = file.path;
  elements.readerShell.dataset.workId = work.id;
  elements.readerShell.dataset.format = file.format;
  elements.readerMac.hidden = false;
  elements.readerFinder.hidden = false;
  elements.readerMac.textContent = file.format === "EPUB" ? "Open in Books" : "Open on Mac";
  const descriptor = {
    path: file.path,
    workId: work.id,
    sha256: file.sha256 || "",
    title: file.title || work.title,
    format: file.format,
  };
  window.dispatchEvent(new CustomEvent("cs-library-reader-document", { detail: descriptor }));
  return descriptor;
}

function showPdfReader(work, file) {
  if (!file.exists) {
    announce(`${file.title} is no longer on this Mac`, true);
    return;
  }
  recordOpen(work);
  showReaderShell(file.title, `${work.title} · PDF`, "pdf");
  const descriptor = configureLocalReaderActions(work, file);
  elements.readerPdf.title = `${file.title} PDF reader`;
  const useWebFallback = () => {
    elements.readerPdf.hidden = false;
    elements.readerPdf.src = contentUrl(file.path);
  };
  if (IS_NATIVE_APP && typeof window.csLibraryNativeCall === "function") {
    window.csLibraryNativeCall("document.upsert", descriptor)
      .then(() => window.csLibraryNativeCall("document.open", { path: file.path }))
      .then(result => { if (!result?.opened) useWebFallback(); })
      .catch(useWebFallback);
  } else {
    useWebFallback();
  }
  renderCards();
}

async function showTextReader(work, file) {
  if (!file.exists) {
    announce(`${file.title} is no longer on this Mac`, true);
    return;
  }
  recordOpen(work);
  showReaderShell(file.title, `${work.title} · ${file.format}`, "text");
  configureLocalReaderActions(work, file);
  try {
    const response = await fetch(contentUrl(file.path), { cache: "no-store" });
    if (!response.ok) throw new Error(`Text request failed (${response.status})`);
    const pre = node("pre", "plain-document");
    pre.textContent = await response.text();
    elements.readerDocument.replaceChildren(pre);
    elements.readerDocument.hidden = false;
    elements.readerLoading.hidden = true;
  } catch (error) {
    elements.readerLoading.hidden = true;
    elements.readerDocument.hidden = false;
    elements.readerDocument.innerHTML = `<div class="reader-error"><h3>Could not open this file</h3><p>${escapeHtml(error.message)}</p></div>`;
    announce(error.message, true);
  }
  renderCards();
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, Number(value)));
}

function normalizeEpubSettings(value) {
  const settings = value && typeof value === "object" ? value : {};
  return {
    font: ["serif", "sans", "mono"].includes(settings.font) ? settings.font : DEFAULT_EPUB_SETTINGS.font,
    fontSize: clamp(Number(settings.fontSize) || DEFAULT_EPUB_SETTINGS.fontSize, 14, 28),
    lineHeight: clamp(Number(settings.lineHeight) || DEFAULT_EPUB_SETTINGS.lineHeight, 1.3, 2.1),
    pageWidth: clamp(Number(settings.pageWidth) || DEFAULT_EPUB_SETTINGS.pageWidth, 560, 980),
    tone: ["paper", "sepia", "night"].includes(settings.tone) ? settings.tone : DEFAULT_EPUB_SETTINGS.tone,
  };
}

function currentEpubChapter() {
  return state.epubPackage?.chapters?.[state.epubIndex] || null;
}

function closeEpubPanels() {
  elements.epubReader.classList.remove("toc-open", "settings-open");
  elements.readerToc.setAttribute("aria-expanded", "false");
  elements.readerSettings.setAttribute("aria-expanded", "false");
}

function toggleEpubPanel(panel) {
  const opening = !elements.epubReader.classList.contains(`${panel}-open`);
  closeEpubPanels();
  if (opening) elements.epubReader.classList.add(`${panel}-open`);
  elements.readerToc.setAttribute("aria-expanded", String(panel === "toc" && opening));
  elements.readerSettings.setAttribute("aria-expanded", String(panel === "settings" && opening));
  if (opening && panel === "toc") window.setTimeout(() => elements.epubTocSearch.focus(), 220);
}

function epubFramePalette() {
  return {
    paper: { paper: "#fffdf8", ink: "#28251f", muted: "#6f6a61", line: "rgba(59,51,42,.15)", code: "#f1ece3", accent: "#8a4d32", scheme: "light" },
    sepia: { paper: "#f4ead6", ink: "#342a20", muted: "#766554", line: "rgba(73,55,37,.17)", code: "#e9dcc4", accent: "#855139", scheme: "light" },
    night: { paper: "#20231e", ink: "#e8e3d7", muted: "#aaa69c", line: "rgba(238,232,220,.14)", code: "#171a16", accent: "#dfa17c", scheme: "dark" },
  }[state.epubSettings.tone];
}

function applyEpubFrameStyles() {
  if (state.readerMode !== "epub") return;
  let documentRoot;
  try {
    documentRoot = elements.epubFrame.contentDocument;
  } catch {
    return;
  }
  if (!documentRoot?.documentElement) return;
  const palette = epubFramePalette();
  const fonts = {
    serif: 'Iowan Old Style, Palatino, "Palatino Linotype", Georgia, serif',
    sans: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif',
    mono: '"SFMono-Regular", Menlo, Consolas, monospace',
  };
  const horizontalPadding = state.epubFocused ? "clamp(22px, 5vw, 54px)" : "clamp(26px, 6vw, 68px)";
  const verticalPadding = state.epubFocused ? "clamp(14px, 2.7vh, 26px)" : "clamp(24px, 4.5vh, 44px)";
  const lineHeight = state.epubFocused
    ? Math.max(1.3, state.epubSettings.lineHeight - 0.12).toFixed(2)
    : state.epubSettings.lineHeight;
  const paragraphGap = state.epubFocused ? ".82em" : "1.02em";
  let style = documentRoot.getElementById("cs-library-reader-style");
  if (!style) {
    style = documentRoot.createElement("style");
    style.id = "cs-library-reader-style";
    (documentRoot.head || documentRoot.documentElement).append(style);
  }
  style.textContent = `
    :root {
      --reader-page-offset: 0px;
      --reader-pad-x: ${horizontalPadding};
      --reader-pad-y: ${verticalPadding};
      color-scheme: ${palette.scheme} !important;
      background: ${palette.paper} !important;
    }
    html {
      width: 100% !important;
      height: 100% !important;
      overflow: hidden !important;
      overscroll-behavior: none !important;
      touch-action: none !important;
      scroll-behavior: auto !important;
      scrollbar-width: none;
      background: ${palette.paper} !important;
    }
    html::-webkit-scrollbar { display: none; }
    body {
      box-sizing: border-box !important;
      width: calc(100vw - var(--reader-pad-x) - var(--reader-pad-x)) !important;
      min-width: calc(100vw - var(--reader-pad-x) - var(--reader-pad-x)) !important;
      max-width: none !important;
      height: calc(100vh - var(--reader-pad-y) - var(--reader-pad-y)) !important;
      min-height: 0 !important;
      margin: var(--reader-pad-y) var(--reader-pad-x) !important;
      padding: 0 !important;
      column-width: calc(100vw - var(--reader-pad-x) - var(--reader-pad-x)) !important;
      column-gap: calc(var(--reader-pad-x) + var(--reader-pad-x)) !important;
      column-fill: auto !important;
      overflow: visible !important;
      background: ${palette.paper} !important;
      color: ${palette.ink} !important;
      font-family: ${fonts[state.epubSettings.font]} !important;
      font-size: ${state.epubSettings.fontSize}px !important;
      line-height: ${lineHeight} !important;
      overflow-wrap: break-word !important;
      transform: translate3d(var(--reader-page-offset), 0, 0) !important;
      transform-origin: top left !important;
      transition: none !important;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    body, p, li, dd, dt, blockquote { color: ${palette.ink} !important; }
    p, li, dd, dt { font-family: inherit !important; font-size: inherit !important; line-height: inherit !important; }
    p { margin-top: 0.28em !important; margin-bottom: ${paragraphGap} !important; }
    h1, h2, h3, h4, h5, h6 {
      max-width: 100% !important;
      break-after: avoid-column;
      color: ${palette.ink} !important;
      font-family: ${state.epubSettings.font === "mono" ? fonts.mono : fonts.serif} !important;
      line-height: 1.18 !important;
      letter-spacing: -0.018em !important;
      text-wrap: balance;
    }
    h1 { font-size: 2.25em !important; }
    h2 { margin-top: 1.8em !important; font-size: 1.65em !important; }
    h3 { margin-top: 1.55em !important; font-size: 1.3em !important; }
    a { color: ${palette.accent} !important; text-decoration-thickness: .07em !important; text-underline-offset: .17em !important; }
    body > :first-child { margin-top: 0 !important; }
    p, li { orphans: 2; widows: 2; }
    img, svg, video, canvas {
      max-width: 100% !important;
      max-height: calc(100vh - var(--reader-pad-y) - var(--reader-pad-y) - 2em) !important;
      height: auto !important;
      break-inside: avoid-column;
      object-fit: contain;
    }
    body#cover #cover-image {
      display: flex !important;
      width: 100% !important;
      height: 100% !important;
      align-items: center !important;
      justify-content: center !important;
      break-inside: avoid-column;
    }
    body#cover #cover-image > * { max-height: 100% !important; margin: 0 auto !important; }
    figure, table, pre, blockquote { break-inside: avoid-column; }
    table { max-width: 100% !important; border-collapse: collapse !important; font-size: .86em !important; }
    th, td { padding: .55em .7em !important; border: 1px solid ${palette.line} !important; }
    pre { max-width: 100% !important; overflow: auto !important; padding: 1em !important; border-radius: .55em !important; background: ${palette.code} !important; font-size: .78em !important; line-height: 1.55 !important; white-space: pre !important; }
    code { font-family: ${fonts.mono} !important; font-size: .86em !important; }
    :not(pre) > code { padding: .12em .3em !important; border-radius: .25em !important; background: ${palette.code} !important; }
    blockquote { margin: 1.5em 0 !important; padding: .3em 1.2em !important; border-left: 3px solid ${palette.accent} !important; }
    hr { border: 0 !important; border-top: 1px solid ${palette.line} !important; }
  `;
}

function epubPageMetrics() {
  const fallback = { pageWidth: 1, pageCount: 1, pageIndex: 0 };
  if (state.readerMode !== "epub") return fallback;
  try {
    const view = elements.epubFrame.contentWindow;
    const documentRoot = elements.epubFrame.contentDocument;
    const scrolling = documentRoot?.scrollingElement || documentRoot?.documentElement;
    const pageWidth = Math.max(1, Number(view?.innerWidth || elements.epubFrame.clientWidth || 1));
    const extent = Math.max(
      pageWidth,
      Number(scrolling?.scrollWidth || 0),
      Number(documentRoot?.documentElement?.scrollWidth || 0),
      Number(documentRoot?.body?.scrollWidth || 0),
    );
    const pageCount = Math.max(1, Math.ceil(Math.max(0, extent - 1) / pageWidth));
    const pageIndex = clamp(Math.round(Number(state.epubPageIndex) || 0), 0, pageCount - 1);
    return { pageWidth, pageCount, pageIndex };
  } catch {
    return fallback;
  }
}

function currentEpubRatio() {
  const { pageCount, pageIndex } = epubPageMetrics();
  return pageCount > 1 ? pageIndex / (pageCount - 1) : 0;
}

function clearEpubPageTurn() {
  window.clearTimeout(state.epubTurnTimer);
  state.epubTurnTimer = 0;
  state.epubTurning = false;
  elements.epubFrame.classList.remove("is-page-turning");
}

function scrollEpubToPage(pageIndex, { animate = false } = {}) {
  try {
    const metrics = epubPageMetrics();
    const target = clamp(Math.round(pageIndex), 0, metrics.pageCount - 1);
    const commit = () => {
      const documentRoot = elements.epubFrame.contentDocument;
      state.epubPageIndex = target;
      documentRoot?.documentElement?.style.setProperty("--reader-page-offset", `${-target * metrics.pageWidth}px`);
      updateEpubLocation();
      saveEpubPosition();
    };
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!animate || reducedMotion || target === metrics.pageIndex) {
      clearEpubPageTurn();
      commit();
      return true;
    }
    if (state.epubTurning) return false;
    state.epubTurning = true;
    elements.epubFrame.classList.add("is-page-turning");
    state.epubTurnTimer = window.setTimeout(() => {
      commit();
      window.requestAnimationFrame(() => window.requestAnimationFrame(clearEpubPageTurn));
    }, 85);
    return true;
  } catch {
    // The chapter load handler will establish the page once its document is ready.
    return false;
  }
}

function restoreEpubRatio(ratio) {
  const metrics = epubPageMetrics();
  const target = metrics.pageCount > 1
    ? Math.round(clamp(Number(ratio) || 0, 0, 1) * (metrics.pageCount - 1))
    : 0;
  scrollEpubToPage(target);
}

function restoreEpubFragment() {
  try {
    const documentRoot = elements.epubFrame.contentDocument;
    const view = elements.epubFrame.contentWindow;
    const rawHash = view?.location?.hash?.slice(1) || "";
    if (!rawHash || !documentRoot) return false;
    let identifier = rawHash;
    try {
      identifier = decodeURIComponent(rawHash);
    } catch {
      // EPUB fragment identifiers do not have to be percent encoded.
    }
    const target = documentRoot.getElementById(identifier) || documentRoot.querySelector(`[name="${CSS.escape(identifier)}"]`);
    if (!target) return false;
    const metrics = epubPageMetrics();
    const scrolling = documentRoot.scrollingElement || documentRoot.documentElement;
    const absoluteLeft = Number(target.getBoundingClientRect().left || 0) + Number(view?.scrollX || scrolling?.scrollLeft || 0);
    if (scrolling) scrolling.scrollLeft = 0;
    view?.scrollTo({ left: 0, top: 0, behavior: "auto" });
    scrollEpubToPage(Math.floor(Math.max(0, absoluteLeft) / metrics.pageWidth));
    return true;
  } catch {
    return false;
  }
}

function setEpubFocus(focused, { announceChange = true } = {}) {
  const next = Boolean(focused) && state.readerMode === "epub";
  if (state.epubFocused === next) return;
  const ratio = currentEpubRatio();
  state.epubFocused = next;
  closeEpubPanels();
  elements.readerShell.classList.toggle("is-focused", next);
  elements.readerFocus.setAttribute("aria-pressed", String(next));
  elements.readerFocus.setAttribute("aria-label", next ? "Show reader controls" : "Focus on the page");
  elements.readerFocus.title = next ? "Show reader controls" : "Focus on the page";
  elements.epubFocusExit.hidden = !next;
  applyEpubFrameStyles();
  window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
    restoreEpubRatio(ratio);
    try {
      if (next) elements.epubFrame.contentDocument?.body?.focus({ preventScroll: true });
      else elements.readerFocus.focus({ preventScroll: true });
    } catch {
      // Position restoration still succeeds if the embedded page cannot take focus.
    }
  }));
  if (announceChange) announce(next ? "Focus mode on — press Escape to show controls" : "Reader controls shown");
}

function updateEpubLocation() {
  const chapter = currentEpubChapter();
  const chapters = state.epubPackage?.chapters || [];
  if (!chapter || !chapters.length) return;
  const metrics = epubPageMetrics();
  const safeRatio = metrics.pageCount > 1 ? metrics.pageIndex / (metrics.pageCount - 1) : 0;
  const overall = clamp((state.epubIndex + safeRatio) / chapters.length, 0, 1);
  const percentage = Math.round(overall * 100);
  elements.epubChapterLabel.textContent = `${chapter.label} · Page ${metrics.pageIndex + 1} of ${metrics.pageCount}`;
  elements.epubChapterLabel.title = `Section ${state.epubIndex + 1} of ${chapters.length}`;
  elements.epubProgressLabel.textContent = `${percentage}%`;
  elements.epubProgressBar.style.width = `${Math.max(0.5, overall * 100)}%`;
  elements.readerKicker.textContent = `${chapter.label} · EPUB`;

  const previous = chapters[state.epubIndex - 1];
  const next = chapters[state.epubIndex + 1];
  const hasPreviousPage = metrics.pageIndex > 0;
  const hasNextPage = metrics.pageIndex < metrics.pageCount - 1;
  elements.epubPrevious.disabled = !hasPreviousPage && !previous;
  elements.epubNext.disabled = !hasNextPage && !next;
  elements.epubPreviousLabel.textContent = hasPreviousPage ? `Page ${metrics.pageIndex}` : (previous?.label || "Beginning");
  elements.epubNextLabel.textContent = hasNextPage ? `Page ${metrics.pageIndex + 2}` : (next?.label || "End of book");
  elements.epubPrevious.setAttribute("aria-label", hasPreviousPage ? `Previous page, page ${metrics.pageIndex}` : (previous ? `Previous section, ${previous.label}` : "Beginning of book"));
  elements.epubNext.setAttribute("aria-label", hasNextPage ? `Next page, page ${metrics.pageIndex + 2}` : (next ? `Next section, ${next.label}` : "End of book"));

  let markedCurrent = false;
  $$(".epub-toc-item", elements.epubTocList).forEach((item) => {
    const current = !markedCurrent && item.dataset.entry === chapter.entry;
    item.classList.toggle("is-current", current);
    if (current) markedCurrent = true;
  });
  const bookmarks = Array.isArray(state.epubBookmarks[state.readerPath]) ? state.epubBookmarks[state.readerPath] : [];
  const isBookmarked = bookmarks.some((bookmark) => bookmark.entry === chapter.entry);
  elements.readerBookmark.classList.toggle("is-bookmarked", isBookmarked);
  elements.readerBookmark.textContent = isBookmarked ? "★" : "☆";
  elements.readerBookmark.setAttribute("aria-label", isBookmarked ? "Remove chapter bookmark" : "Bookmark this position");
  window.dispatchEvent(new CustomEvent("cs-library-reader-position", {
    detail: {
      locator: { type: "epub", entry: chapter.entry, index: state.epubIndex, ratio: safeRatio },
      page: metrics.pageIndex,
      progress: overall,
    },
  }));
}

function saveEpubPosition() {
  const chapter = currentEpubChapter();
  if (state.readerMode !== "epub" || !state.readerPath || !chapter) return;
  state.epubProgress[state.readerPath] = {
    entry: chapter.entry,
    index: state.epubIndex,
    ratio: currentEpubRatio(),
    updatedAt: Date.now(),
  };
  writeStorage(STORAGE.epubProgress, state.epubProgress);
}

function handleEpubScroll() {
  window.cancelAnimationFrame(state.epubScrollFrame);
  state.epubScrollFrame = window.requestAnimationFrame(() => updateEpubLocation());
  window.clearTimeout(state.epubSaveTimer);
  state.epubSaveTimer = window.setTimeout(saveEpubPosition, 280);
}

function preventEpubPanning(event) {
  if (state.readerMode === "epub") event.preventDefault();
}

function renderEpubToc() {
  const packageData = state.epubPackage;
  if (!packageData) return;
  const source = packageData.toc.length
    ? packageData.toc
    : packageData.chapters.map((chapter) => ({ ...chapter, spineIndex: chapter.index, depth: 0 }));
  const items = source.map((tocItem) => {
    const item = button("epub-toc-item", tocItem.label, () => {
      const index = tocItem.spineIndex >= 0
        ? tocItem.spineIndex
        : packageData.chapters.findIndex((chapter) => chapter.entry === tocItem.entry);
      if (index >= 0) navigateEpub(index, { url: tocItem.url, ratio: null });
    }, `Open ${tocItem.label}`);
    item.dataset.entry = tocItem.entry;
    item.dataset.search = tocItem.label.toLowerCase();
    item.style.setProperty("--toc-depth", String(tocItem.depth || 0));
    return item;
  });
  elements.epubTocList.replaceChildren(...items);
  elements.epubTocSearch.value = "";
}

function renderEpubBookmarks() {
  const raw = state.epubBookmarks[state.readerPath];
  const bookmarks = (Array.isArray(raw) ? raw : [])
    .filter((bookmark) => bookmark && typeof bookmark.entry === "string")
    .sort((a, b) => Number(b.createdAt || 0) - Number(a.createdAt || 0));
  elements.epubBookmarks.hidden = bookmarks.length === 0;
  const rows = bookmarks.map((bookmark) => {
    const row = node("div", "epub-bookmark-row");
    const link = button("epub-bookmark-link", `${bookmark.label} · ${Math.round(clamp(bookmark.ratio || 0, 0, 1) * 100)}%`, () => {
      const index = state.epubPackage.chapters.findIndex((chapter) => chapter.entry === bookmark.entry);
      if (index >= 0) navigateEpub(index, { ratio: clamp(bookmark.ratio || 0, 0, 1) });
    });
    const remove = button("epub-bookmark-remove", "×", () => {
      state.epubBookmarks[state.readerPath] = bookmarks.filter((candidate) => candidate.entry !== bookmark.entry);
      writeStorage(STORAGE.epubBookmarks, state.epubBookmarks);
      renderEpubBookmarks();
      updateEpubLocation();
    }, `Remove bookmark for ${bookmark.label}`);
    row.append(link, remove);
    return row;
  });
  elements.epubBookmarkList.replaceChildren(...rows);
}

function toggleEpubBookmark() {
  const chapter = currentEpubChapter();
  if (!chapter || !state.readerPath) return;
  const bookmarks = Array.isArray(state.epubBookmarks[state.readerPath])
    ? [...state.epubBookmarks[state.readerPath]]
    : [];
  const existing = bookmarks.findIndex((bookmark) => bookmark.entry === chapter.entry);
  const bookmark = {
    entry: chapter.entry,
    index: state.epubIndex,
    ratio: currentEpubRatio(),
    label: chapter.label,
    createdAt: Date.now(),
  };
  if (existing >= 0) {
    bookmarks.splice(existing, 1);
    announce(`Removed bookmark from ${chapter.label}`);
  } else {
    bookmarks.unshift(bookmark);
    announce(`Bookmarked ${chapter.label}`);
  }
  state.epubBookmarks[state.readerPath] = bookmarks.slice(0, 50);
  writeStorage(STORAGE.epubBookmarks, state.epubBookmarks);
  renderEpubBookmarks();
  updateEpubLocation();
  window.dispatchEvent(new CustomEvent("cs-library-reader-bookmark-toggle", {
    detail: { bookmarked: existing < 0, locator: { type: "epub", ...bookmark }, label: chapter.label },
  }));
}

function applyEpubSettings({ persist = true, preservePosition = false } = {}) {
  const ratio = preservePosition ? currentEpubRatio() : null;
  state.epubSettings = normalizeEpubSettings(state.epubSettings);
  const settings = state.epubSettings;
  elements.epubReader.dataset.tone = settings.tone;
  elements.epubReader.style.setProperty("--epub-page-width", `${settings.pageWidth}px`);
  elements.epubFontSize.value = String(settings.fontSize);
  elements.epubFontSizeValue.value = `${settings.fontSize} px`;
  elements.epubLineHeight.value = String(settings.lineHeight);
  elements.epubLineHeightValue.value = settings.lineHeight.toFixed(1);
  elements.epubPageWidth.value = String(settings.pageWidth);
  elements.epubPageWidthValue.value = `${settings.pageWidth} px`;
  $$('[data-epub-font]', elements.epubFontOptions).forEach((item) => item.classList.toggle("is-active", item.dataset.epubFont === settings.font));
  $$('[data-epub-tone]', elements.epubToneOptions).forEach((item) => item.classList.toggle("is-active", item.dataset.epubTone === settings.tone));
  applyEpubFrameStyles();
  if (persist) writeStorage(STORAGE.epubSettings, settings);
  if (ratio !== null) {
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => restoreEpubRatio(ratio)));
  }
}

function navigateEpub(index, { url = "", ratio = 0 } = {}) {
  const chapters = state.epubPackage?.chapters || [];
  const chapter = chapters[index];
  if (!chapter) return;
  clearEpubPageTurn();
  if (state.epubIndex >= 0 && state.epubEntry) saveEpubPosition();
  state.epubIndex = index;
  state.epubEntry = chapter.entry;
  state.epubPageIndex = 0;
  const targetUrl = url || chapter.url;
  state.epubRestoreRatio = ratio === null || targetUrl.includes("#") ? null : clamp(ratio, 0, 1);
  elements.readerLoading.hidden = false;
  elements.epubFrame.title = `${state.epubPackage.title} — ${chapter.label}`;
  elements.epubFrame.src = targetUrl;
  closeEpubPanels();
}

function turnEpubPage(offset) {
  if (!offset || state.readerMode !== "epub" || state.epubTurning) return;
  const metrics = epubPageMetrics();
  const target = metrics.pageIndex + Math.sign(offset);
  if (target >= 0 && target < metrics.pageCount) {
    scrollEpubToPage(target, { animate: true });
    return;
  }
  const chapterTarget = state.epubIndex + Math.sign(offset);
  if (chapterTarget < 0 || chapterTarget >= (state.epubPackage?.chapters?.length || 0)) return;
  navigateEpub(chapterTarget, { ratio: offset < 0 ? 1 : 0 });
}

function handleEpubFrameLink(event) {
  const anchor = event.target.closest?.("a[href]");
  if (!anchor || !state.epubPackage) return;
  let target;
  try {
    target = new URL(anchor.href, elements.epubFrame.contentWindow.location.href);
  } catch {
    return;
  }
  const prefix = `/epub/${state.epubPackage.bookKey}/`;
  if (target.origin === window.location.origin && target.pathname.startsWith(prefix)) {
    let entry = "";
    try {
      entry = decodeURIComponent(target.pathname.slice(prefix.length));
    } catch {
      return;
    }
    const index = state.epubPackage.chapters.findIndex((chapter) => chapter.entry === entry);
    if (index >= 0) {
      event.preventDefault();
      navigateEpub(index, { url: `${target.pathname}${target.hash}`, ratio: null });
    }
    return;
  }
  event.preventDefault();
  if (/^https?:$/.test(target.protocol)) window.open(target.href, "_blank", "noopener,noreferrer");
  else announce("That link is outside this local book", true);
}

function handleEpubKeydown(event) {
  if (state.readerMode !== "epub" || event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key === "Escape" && state.epubFocused) {
    event.preventDefault();
    setEpubFocus(false);
    return;
  }
  const tag = event.target?.tagName?.toLowerCase();
  if (["input", "textarea", "select"].includes(tag)) return;
  if (IS_NATIVE_APP && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    event.preventDefault();
    return;
  }
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    turnEpubPage(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    turnEpubPage(1);
  }
}

function handleNativeReaderArrow(direction) {
  if (!IS_NATIVE_APP || state.readerMode !== "epub" || !document.body.classList.contains("reader-open")) return false;
  const active = document.activeElement;
  const tag = active?.tagName?.toLowerCase();
  if (["input", "textarea", "select"].includes(tag) || active?.isContentEditable) return false;
  if (active === elements.epubFrame) {
    try {
      const frameActive = elements.epubFrame.contentDocument?.activeElement;
      const frameTag = frameActive?.tagName?.toLowerCase();
      if (["input", "textarea", "select"].includes(frameTag) || frameActive?.isContentEditable) return false;
    } catch {
      // Same-origin EPUB chapters normally expose their active element.
    }
  }
  turnEpubPage(Number(direction) < 0 ? -1 : 1);
  return true;
}

window.csLibraryHandleNativeArrow = handleNativeReaderArrow;

function handleEpubFrameLoad() {
  if (state.readerMode !== "epub" || elements.epubFrame.src === "about:blank") return;
  try {
    const documentRoot = elements.epubFrame.contentDocument;
    const view = elements.epubFrame.contentWindow;
    if (!documentRoot || !view) throw new Error("The chapter could not be displayed");
    state.epubPageIndex = 0;
    documentRoot.documentElement.style.setProperty("--reader-page-offset", "0px");
    const scrolling = documentRoot.scrollingElement || documentRoot.documentElement;
    if (scrolling) scrolling.scrollLeft = 0;
    view.scrollTo({ left: 0, top: 0, behavior: "auto" });
    applyEpubFrameStyles();
    if (documentRoot.body) documentRoot.body.tabIndex = -1;
    documentRoot.addEventListener("click", handleEpubFrameLink);
    documentRoot.addEventListener("keydown", handleEpubKeydown);
    documentRoot.addEventListener("wheel", preventEpubPanning, { passive: false });
    documentRoot.addEventListener("touchmove", preventEpubPanning, { passive: false });
    view.addEventListener("scroll", handleEpubScroll, { passive: true });
    const restoreRatio = state.epubRestoreRatio;
    state.epubRestoreRatio = null;
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      if (restoreRatio !== null) restoreEpubRatio(restoreRatio);
      else restoreEpubFragment();
      elements.readerLoading.hidden = true;
      updateEpubLocation();
    }));
  } catch (error) {
    elements.readerLoading.hidden = true;
    announce(error.message, true);
  }
}

async function showEpubReader(work, file) {
  if (!file.exists) {
    announce(`${file.title} is no longer on this Mac`, true);
    return;
  }
  recordOpen(work);
  showReaderShell(file.title, `${work.title} · EPUB`, "epub");
  configureLocalReaderActions(work, file);
  elements.readerToc.hidden = false;
  elements.readerSettings.hidden = false;
  elements.readerBookmark.hidden = false;
  try {
    const response = await fetch(epubPackageUrl(file.path), { cache: "no-store" });
    const packageData = await response.json();
    if (!response.ok) throw new Error(packageData.error || `EPUB request failed (${response.status})`);
    if (state.readerMode !== "epub" || state.readerPath !== file.path) return;
    state.epubPackage = packageData;
    state.epubIndex = -1;
    state.epubEntry = "";
    elements.epubReader.hidden = false;
    applyEpubSettings({ persist: false });
    renderEpubToc();
    renderEpubBookmarks();
    const nativeSaved = state.nativeReaderRestore?.path === file.path ? state.nativeReaderRestore.locator : null;
    const saved = nativeSaved?.type === "epub" ? nativeSaved : state.epubProgress[file.path];
    let index = packageData.chapters.findIndex((chapter) => chapter.entry === saved?.entry);
    if (index < 0) index = clamp(Number(saved?.index) || 0, 0, packageData.chapters.length - 1);
    navigateEpub(index, { ratio: clamp(Number(saved?.ratio) || 0, 0, 1) });
  } catch (error) {
    elements.readerLoading.hidden = true;
    elements.epubReader.hidden = true;
    elements.readerToc.hidden = true;
    elements.readerSettings.hidden = true;
    elements.readerBookmark.hidden = true;
    elements.readerDocument.hidden = false;
    elements.readerDocument.innerHTML = `<div class="reader-error"><h3>Could not open this EPUB</h3><p>${escapeHtml(error.message)}</p></div>`;
    announce(error.message, true);
  }
  renderCards();
}

async function openOnMac(work, file) {
  if (!file.exists) {
    announce(`${file.title} is no longer on this Mac`, true);
    return;
  }
  recordOpen(work);
  try {
    await localAction(file.path, "open");
    announce(`Opened ${file.title} on your Mac`);
  } catch (error) {
    announce(error.message, true);
  }
  renderCards();
  if (state.selectedId === work.id) renderDrawer(work);
}

async function openFile(work, file) {
  if (file.format === "EPUB") await showEpubReader(work, file);
  else if (file.format === "PDF") showPdfReader(work, file);
  else if (file.format === "TXT") await showTextReader(work, file);
  else await openOnMac(work, file);
}

function normalizedReaderPath(currentDocument, target) {
  let decoded;
  try {
    decoded = decodeURIComponent(target.split("#", 1)[0].split("?", 1)[0]);
  } catch {
    decoded = target.split("#", 1)[0].split("?", 1)[0];
  }
  decoded = decoded.replace(/^\/(document|content)\//, "").replace(/^\//, "");
  const rootRelative = /^(books|papers|notes|manifests)\//.test(decoded) || /^[A-Z][A-Z_]+\.md$/.test(decoded);
  const parts = rootRelative ? [] : currentDocument.split("/").slice(0, -1);
  decoded.split("/").forEach((part) => {
    if (!part || part === ".") return;
    if (part === "..") parts.pop();
    else parts.push(part);
  });
  return parts.join("/");
}

async function openDocument(path, title = "Library document") {
  showReaderShell(title, "From your library desk", "document");
  state.readerPath = "";
  state.readerWorkId = "";
  elements.readerMac.hidden = true;
  elements.readerFinder.hidden = true;
  elements.readerDocument.dataset.path = path;
  try {
    const response = await fetch(documentUrl(path), { cache: "no-store" });
    if (!response.ok) throw new Error(`Document request failed (${response.status})`);
    const text = await response.text();
    if (path.endsWith(".sha256")) {
      const pre = node("pre", "plain-document manifest-document");
      pre.textContent = text;
      elements.readerDocument.replaceChildren(pre);
    } else {
      elements.readerDocument.innerHTML = renderMarkdown(text);
    }
    elements.readerDocument.hidden = false;
    elements.readerLoading.hidden = true;
    elements.readerStage.scrollTop = 0;
  } catch (error) {
    elements.readerLoading.hidden = true;
    elements.readerDocument.hidden = false;
    elements.readerDocument.innerHTML = `<div class="reader-error"><h3>Could not open this document</h3><p>${escapeHtml(error.message)}</p></div>`;
    announce(error.message, true);
  }
}

function handleDocumentLink(event) {
  const link = event.target.closest("[data-md-link]");
  if (!link) return;
  event.preventDefault();
  const target = link.dataset.mdLink || "";
  if (/^https?:\/\//i.test(target)) {
    window.open(target, "_blank", "noopener,noreferrer");
    return;
  }
  if (target.startsWith("#")) {
    const targetHeading = elements.readerDocument.querySelector(`#${CSS.escape(target.slice(1))}`);
    if (targetHeading) targetHeading.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  const currentDocument = elements.readerDocument.dataset.path || "";
  const path = normalizedReaderPath(currentDocument, target);
  const material = state.library.materials.find((item) => item.path === path);
  if (material) {
    const work = state.workById.get(material.workId);
    if (work) openFile(work, material);
    return;
  }
  const collection = state.library.works.find((work) => work.localPath === `${path.replace(/\/$/, "")}/` || work.localPath === path);
  if (collection) {
    closeReader();
    showDrawer(collection.id);
    return;
  }
  if (/\.(md|sha256)$/i.test(path)) {
    openDocument(path, link.textContent.trim() || "Library document");
    return;
  }
  announce("That linked local file is not currently on the shelf", true);
}

async function revealFile(file) {
  try {
    await localAction(file.path, "reveal");
    announce("Revealed the file in Finder");
  } catch (error) {
    announce(error.message, true);
  }
}

function makeCover(work, drawer = false) {
  if (drawer) {
    return node("div", "drawer-cover", monogram(work.title));
  }
  const cover = node("button", "book-cover");
  cover.type = "button";
  cover.setAttribute("aria-label", `View details for ${work.title}`);
  cover.addEventListener("click", () => showDrawer(work.id));

  const top = node("div", "cover-top");
  top.append(
    node("span", "cover-shelf", compactSubject(work.subject)),
    node("span", `format-badge${work.cataloged ? "" : " is-new"}`, work.cataloged ? (work.isCollection ? `${work.fileCount} FILES` : work.formats[0]) : "NEW"),
  );
  const bottom = node("div", "cover-bottom");
  bottom.append(node("p", "cover-title", work.title), node("span", "cover-author", work.authors));
  cover.append(top, node("div", "cover-monogram", monogram(work.title)), bottom);
  return cover;
}

function toggleFavorite(work) {
  if (state.favorites.has(work.id)) state.favorites.delete(work.id);
  else state.favorites.add(work.id);
  persistActivity();
  renderNavigationCounts();
  renderCards();
  if (state.selectedId === work.id) renderDrawer(work);
}

function makeCard(work) {
  const card = node("article", `book-card subject-${work.subjectId}${work.cataloged ? "" : " is-new-arrival"}${work.isAvailable ? "" : " is-unavailable"}`);
  card.dataset.id = work.id;
  const favorite = button(
    `favorite-button${state.favorites.has(work.id) ? " is-favorite" : ""}`,
    state.favorites.has(work.id) ? "♥" : "♡",
    (event) => {
      event.stopPropagation();
      toggleFavorite(work);
    },
    `${state.favorites.has(work.id) ? "Remove" : "Add"} ${work.title} ${state.favorites.has(work.id) ? "from" : "to"} favorites`,
  );

  const info = node("div", "book-info");
  info.append(node("h3", "book-title", work.title), node("p", "book-author", work.authors));
  const meta = node("div", "book-meta");
  meta.append(node("span", "", work.edition), node("span", "", humanBytes(work.totalBytes)));
  const status = workStatus(work.id);
  if (status !== "unread") meta.append(node("span", "book-status", statusLabel(status)));
  if (!work.isAvailable) meta.append(node("span", "book-status is-missing", "Missing"));
  info.append(meta);

  const actions = node("div", "card-actions");
  const primaryAction = button("button button-primary button-small", work.isCollection ? "Browse files" : isBrowserReadable(primaryFile(work)) ? "Read here" : "Open on Mac", () => {
      if (work.isCollection) showDrawer(work.id);
      else openFile(work, primaryFile(work));
    });
  primaryAction.disabled = !work.isAvailable;
  actions.append(primaryAction, button("button button-quiet button-small", "Details", () => showDrawer(work.id)));
  info.append(actions);
  card.append(favorite, makeCover(work), info);
  return card;
}

function makeMaterialCard(material) {
  const work = state.workById.get(material.workId);
  const card = node("article", `book-card material-card subject-${material.subjectId}${work.cataloged ? "" : " is-new-arrival"}`);
  card.dataset.material = material.path;
  const favorite = button(
    `favorite-button${state.favorites.has(work.id) ? " is-favorite" : ""}`,
    state.favorites.has(work.id) ? "♥" : "♡",
    (event) => {
      event.stopPropagation();
      toggleFavorite(work);
    },
    `${state.favorites.has(work.id) ? "Remove" : "Add"} ${work.title} ${state.favorites.has(work.id) ? "from" : "to"} favorites`,
  );

  const cover = node("button", "book-cover");
  cover.type = "button";
  cover.setAttribute("aria-label", `${isBrowserReadable(material) ? "Read" : "Open"} ${material.title}`);
  cover.addEventListener("click", () => openFile(work, material));
  const top = node("div", "cover-top");
  top.append(node("span", "cover-shelf", material.materialLabel), node("span", "format-badge", material.format));
  const bottom = node("div", "cover-bottom");
  bottom.append(node("p", "cover-title", material.title), node("span", "cover-author", work.title));
  cover.append(top, node("div", "cover-monogram", monogram(material.title)), bottom);

  const info = node("div", "book-info");
  info.append(node("h3", "book-title", material.title), node("p", "book-author", `${work.title} · ${material.authors}`));
  const meta = node("div", "book-meta");
  meta.append(node("span", "", material.format), node("span", "", humanBytes(material.bytes)), node("span", "book-status", material.materialLabel));
  info.append(meta);
  const actions = node("div", "card-actions");
  actions.append(
    button("button button-primary button-small", isBrowserReadable(material) ? "Read here" : "Open on Mac", () => openFile(work, material)),
    button("button button-quiet button-small", "Work details", () => showDrawer(work.id)),
  );
  info.append(actions);
  card.append(favorite, cover, info);
  return card;
}

function isMaterialView() {
  return state.view === "files" || state.view.startsWith("material:");
}

function filteredMaterials() {
  if (!state.library) return [];
  const query = state.query.trim().toLowerCase();
  const requestedType = state.view.startsWith("material:") ? state.view.split(":", 2)[1] : null;
  const materials = state.library.materials.filter((material) => {
    if (requestedType && material.materialType !== requestedType) return false;
    if (state.subject !== "all" && material.subjectId !== state.subject) return false;
    if (!query) return true;
    const haystack = [
      material.title,
      material.workTitle,
      material.authors,
      material.subject,
      material.path,
      material.format,
      material.materialLabel,
      material.access,
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
  const sorters = {
    title: (a, b) => a.title.localeCompare(b.title),
    author: (a, b) => a.authors.localeCompare(b.authors) || a.title.localeCompare(b.title),
    subject: (a, b) => a.subject.localeCompare(b.subject) || a.title.localeCompare(b.title),
    recent: (a, b) => (state.recent[b.workId] || 0) - (state.recent[a.workId] || 0) || a.title.localeCompare(b.title),
  };
  materials.sort(sorters[state.sort] || sorters.title);
  return materials;
}

function filteredWorks() {
  if (!state.library) return [];
  const query = state.query.trim().toLowerCase();
  let works = state.library.works.filter((work) => {
    if (state.subject !== "all" && work.subjectId !== state.subject) return false;
    if (state.view === "favorites" && !state.favorites.has(work.id)) return false;
    if (state.view === "reading" && workStatus(work.id) !== "reading") return false;
    if (state.view === "finished" && workStatus(work.id) !== "finished") return false;
    if (!query) return true;
    const haystack = [
      work.title,
      work.authors,
      work.subject,
      work.edition,
      work.access,
      ...work.files.flatMap((file) => [file.title, file.path, file.format]),
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });

  const sorters = {
    title: (a, b) => a.title.localeCompare(b.title),
    author: (a, b) => a.authors.localeCompare(b.authors) || a.title.localeCompare(b.title),
    subject: (a, b) => a.subject.localeCompare(b.subject) || a.title.localeCompare(b.title),
    recent: (a, b) => (state.recent[b.id] || 0) - (state.recent[a.id] || 0) || a.title.localeCompare(b.title),
  };
  works.sort(sorters[state.sort] || sorters.title);
  return works;
}

function renderCards() {
  if (!state.library) return;
  // Free-text search runs across the physical 72-file shelf so a query such as
  // "Lecture 12" returns that exact PDF instead of only its parent collection.
  const materialMode = isMaterialView() || (state.view === "all" && state.query.trim().length > 0);
  const items = materialMode ? filteredMaterials() : filteredWorks();
  elements.grid.replaceChildren(...items.map(materialMode ? makeMaterialCard : makeCard));
  elements.grid.classList.toggle("is-list", state.layout === "list");
  elements.empty.hidden = items.length > 0;
  elements.grid.hidden = items.length === 0;
  const noun = materialMode ? (items.length === 1 ? "file" : "files") : (items.length === 1 ? "work" : "works");
  elements.resultCount.textContent = `${items.length} ${noun} shown`;
  updateSectionHeading();
}

function updateSectionHeading() {
  const viewNames = {
    all: ["The complete collection", "All works"],
    files: ["Every local artifact", "All files"],
    favorites: ["Your hand-picked shelf", "Favorites"],
    reading: ["Your active stack", "Currently reading"],
    finished: ["Your completed shelf", "Finished books"],
  };
  let [eyebrow, title] = viewNames[state.view] || viewNames.all;
  if (state.view.startsWith("material:")) {
    const materialType = state.library.materialTypes.find((item) => `material:${item.id}` === state.view);
    if (materialType) [eyebrow, title] = ["Material collection", materialType.name];
  }
  if (state.query.trim()) {
    eyebrow = "Search across every local file";
    title = `Results for “${state.query.trim()}”`;
  }
  if (state.subject !== "all") {
    const subject = state.library.subjects.find((item) => item.id === state.subject);
    if (subject) {
      eyebrow = "Subject shelf";
      title = subject.name;
    }
  }
  elements.sectionEyebrow.textContent = eyebrow;
  elements.sectionTitle.textContent = title;
}

function renderNavigationCounts() {
  if (!state.library) return;
  elements.allCount.textContent = state.library.stats.works;
  elements.allFileCount.textContent = state.library.stats.artifacts;
  elements.favoriteCount.textContent = state.favorites.size;
  elements.readingCount.textContent = state.library.works.filter((work) => workStatus(work.id) === "reading").length;
  elements.finishedCount.textContent = state.library.works.filter((work) => workStatus(work.id) === "finished").length;
}

function setView(view) {
  state.view = view;
  state.subject = "all";
  syncNavigation();
  renderSubjectChips();
  renderCards();
  closeMobileMenu();
}

function setSubject(subjectId, preserveView = false) {
  state.subject = subjectId;
  if (!preserveView) state.view = "all";
  syncNavigation();
  renderSubjectChips();
  renderCards();
  closeMobileMenu();
}

function syncNavigation() {
  $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === state.view));
  $$(".material-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === state.view));
  $$(".subject-item").forEach((item) => item.classList.toggle("is-active", state.view === "all" && item.dataset.subject === state.subject));
}

function renderMaterials() {
  const items = state.library.materialTypes.map((materialType) => {
    const view = `material:${materialType.id}`;
    const item = button("shelf-item material-item", "", () => setView(view), `Show ${materialType.name}`);
    item.dataset.view = view;
    item.append(node("span", "shelf-dot"), node("span", "", materialType.name), node("span", "nav-count", materialType.count));
    return item;
  });
  elements.materialNav.replaceChildren(...items);
}

function renderShelves() {
  const counts = Object.fromEntries(
    state.library.subjects.map((subject) => [subject.id, state.library.works.filter((work) => work.subjectId === subject.id).length]),
  );
  const items = state.library.subjects.map((subject) => {
    const item = button("shelf-item subject-item", "", () => setSubject(subject.id), `Open ${subject.name} shelf`);
    item.dataset.subject = subject.id;
    item.append(node("span", "shelf-dot"), node("span", "", subject.name), node("span", "nav-count", counts[subject.id]));
    return item;
  });
  elements.shelfNav.replaceChildren(...items);
}

function renderSubjectChips() {
  const all = button(`chip${state.subject === "all" ? " is-active" : ""}`, "All subjects", () => setSubject("all", true));
  const chips = state.library.subjects.map((subject) => {
    const chip = button(`chip${state.subject === subject.id ? " is-active" : ""}`, subject.name, () => setSubject(subject.id, true));
    return chip;
  });
  elements.subjectChips.replaceChildren(all, ...chips);
}

function renderRecent() {
  if (!state.library) return;
  const recent = state.library.works
    .filter((work) => state.recent[work.id])
    .sort((a, b) => state.recent[b.id] - state.recent[a.id])
    .slice(0, 3);
  elements.recentSection.hidden = recent.length === 0;
  const cards = recent.map((work) => {
    const card = button("recent-card", "", () => openFile(work, primaryFile(work)), `Continue ${work.title}`);
    card.append(node("span", "recent-mini-cover", monogram(work.title)));
    const text = node("span", "");
    text.append(node("strong", "", work.title), node("small", "", `${statusLabel(workStatus(work.id))} · ${work.formats.join(" / ")}`));
    card.append(text, node("span", "recent-arrow", "↗"));
    return card;
  });
  elements.recentRow.replaceChildren(...cards);
}

function setStatus(work, status) {
  state.statuses[work.id] = status;
  persistActivity();
  renderNavigationCounts();
  renderCards();
  renderDrawer(work);
  announce(`${work.title}: ${statusLabel(status)}`);
}

function renderDrawer(work) {
  const body = node("div", "");
  const lead = node("div", `drawer-lead subject-${work.subjectId}`);
  const title = node("div", "drawer-title");
  title.append(node("h2", "", work.title), node("p", "", work.authors));
  const pills = node("div", "drawer-pills");
  pills.append(node("span", "pill", work.edition), node("span", "pill", work.formats.join(" / ")));
  if (work.isCollection) pills.append(node("span", "pill", `${work.fileCount} files`));
  if (!work.cataloged) pills.append(node("span", "pill pill-new", "New local arrival"));
  title.append(pills);
  lead.append(makeCover(work, true), title);
  body.append(lead);

  const actions = node("div", "drawer-actions");
  const firstFile = primaryFile(work);
  const readAction = button("button button-primary", isBrowserReadable(firstFile) ? "Read here" : (firstFile.format === "EPUB" ? "Open in Books" : "Open on Mac"), () => openFile(work, firstFile));
  readAction.disabled = !firstFile.exists;
  actions.append(readAction);
  if (isBrowserReadable(firstFile)) {
    const macAction = button("button button-quiet", "Open on Mac", () => openOnMac(work, firstFile));
    macAction.disabled = !firstFile.exists;
    actions.append(macAction);
  }
  actions.append(button("button button-quiet", state.favorites.has(work.id) ? "♥ Favorited" : "♡ Favorite", () => toggleFavorite(work)));
  const finderAction = button("button button-quiet", "Finder", () => revealFile(firstFile), "Reveal in Finder");
  finderAction.disabled = !firstFile.exists;
  actions.append(finderAction);
  body.append(actions);

  const progress = node("section", "drawer-section");
  const progressHeading = node("div", "drawer-section-title");
  progressHeading.append(node("h3", "", "Reading status"), node("span", "", "Saved in this browser"));
  const options = node("div", "status-options");
  [
    ["unread", "Not started"],
    ["reading", "Reading"],
    ["finished", "Finished"],
  ].forEach(([status, label]) => {
    options.append(button(`status-button${workStatus(work.id) === status ? " is-active" : ""}`, label, () => setStatus(work, status)));
  });
  progress.append(progressHeading, options);
  body.append(progress);

  const filesSection = node("section", "drawer-section");
  const fileHeading = node("div", "drawer-section-title");
  fileHeading.append(node("h3", "", work.isCollection ? "Files in this collection" : "Local file"), node("span", "", `${work.fileCount} ${work.fileCount === 1 ? "file" : "files"}`));
  const fileList = node("div", "file-list");
  work.files.forEach((file) => {
    const row = node("div", `file-row${file.exists ? "" : " is-missing"}`);
    const details = node("div", "");
    details.append(node("strong", "", file.title), node("small", "", `${file.format} · ${humanBytes(file.bytes)} · ${file.exists ? file.path : "Missing from this Mac"}`));
    const fileActions = node("div", "file-actions");
    if (file.exists) {
      fileActions.append(button("mini-action mini-action-primary", isBrowserReadable(file) ? "Read here" : "Open", () => openFile(work, file)));
      if (isBrowserReadable(file)) fileActions.append(button("mini-action", "Mac", () => openOnMac(work, file), `Open ${file.title} on this Mac`));
      fileActions.append(button("mini-action", "Finder", () => revealFile(file), `Reveal ${file.title} in Finder`));
    } else {
      fileActions.append(node("span", "missing-label", "Not on Mac"));
    }
    row.append(details, fileActions);
    fileList.append(row);
  });
  filesSection.append(fileHeading, fileList);
  body.append(filesSection);

  const metadataSection = node("section", "drawer-section");
  const metadataHeading = node("div", "drawer-section-title");
  metadataHeading.append(node("h3", "", "Shelf information"));
  const metadataGrid = node("div", "metadata-grid");
  [
    ["Shelf", work.subject],
    ["Access", work.access],
    ["Size", humanBytes(work.totalBytes)],
    ["Local path", work.localPath],
    ["Availability", work.isAvailable ? "On this Mac" : `${work.availableFileCount}/${work.fileCount} files on this Mac`],
    ["License note", primaryFile(work).license],
  ].forEach(([label, value]) => {
    const item = node("div", "metadata-item");
    item.append(node("span", "", label), node("strong", "", value));
    metadataGrid.append(item);
  });
  metadataSection.append(metadataHeading, metadataGrid);
  if (work.sourceUrl) {
    const link = node("a", "source-link", "Visit the official source ↗");
    link.href = work.sourceUrl;
    link.target = "_blank";
    link.rel = "noreferrer";
    metadataSection.append(link);
  }
  body.append(metadataSection);
  elements.drawerBody.replaceChildren(body);
}

function showDrawer(workId) {
  const work = state.library.works.find((item) => item.id === workId);
  if (!work) return;
  state.selectedId = workId;
  renderDrawer(work);
  document.body.classList.add("drawer-open");
  elements.drawer.setAttribute("aria-hidden", "false");
  elements.drawerClose.focus();
}

function closeDrawer() {
  document.body.classList.remove("drawer-open");
  elements.drawer.setAttribute("aria-hidden", "true");
  state.selectedId = null;
}

function openMobileMenu() {
  document.body.classList.add("sidebar-open");
}

function closeMobileMenu() {
  document.body.classList.remove("sidebar-open");
}

function clearFilters() {
  state.query = "";
  state.view = "all";
  state.subject = "all";
  elements.search.value = "";
  syncNavigation();
  renderSubjectChips();
  renderCards();
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  elements.theme.textContent = theme === "dark" ? "☼" : "◒";
  elements.theme.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`);
  const meta = $("meta[name='theme-color']");
  if (meta) meta.content = theme === "dark" ? "#171915" : "#f2eee5";
}

function initializeTheme() {
  const saved = readStorage(STORAGE.theme, null);
  const theme = saved || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(theme);
}

function bindEvents() {
  window.addEventListener("cs-library-reader-restore", event => {
    const saved = event.detail;
    if (!saved || saved.path !== state.readerPath) return;
    state.nativeReaderRestore = saved;
    const locator = saved.locator;
    if (state.readerMode !== "epub" || !state.epubPackage || locator?.type !== "epub") return;
    let index = state.epubPackage.chapters.findIndex(chapter => chapter.entry === locator.entry);
    if (index < 0) index = clamp(Number(locator.index) || 0, 0, state.epubPackage.chapters.length - 1);
    navigateEpub(index, { ratio: clamp(Number(locator.ratio) || 0, 0, 1) });
  });
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => setView(item.dataset.view)));
  $$("[data-document]").forEach((item) => item.addEventListener("click", () => openDocument(item.dataset.document, item.dataset.title)));
  elements.search.addEventListener("input", () => {
    state.query = elements.search.value;
    renderCards();
  });
  elements.sort.addEventListener("change", () => {
    state.sort = elements.sort.value;
    renderCards();
  });
  elements.viewButton.addEventListener("click", () => {
    state.layout = state.layout === "grid" ? "list" : "grid";
    writeStorage(STORAGE.layout, state.layout);
    elements.viewButton.textContent = state.layout === "grid" ? "☷" : "▦";
    elements.viewButton.setAttribute("aria-label", `Switch to ${state.layout === "grid" ? "list" : "grid"} view`);
    renderCards();
  });
  elements.theme.addEventListener("click", () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    writeStorage(STORAGE.theme, theme);
    applyTheme(theme);
  });
  elements.random.addEventListener("click", () => {
    const choices = isMaterialView() ? filteredMaterials() : filteredWorks();
    if (!choices.length) return;
    const choice = choices[Math.floor(Math.random() * choices.length)];
    showDrawer(isMaterialView() ? choice.workId : choice.id);
  });
  elements.focusSearch.addEventListener("click", () => elements.search.focus());
  elements.clearFilters.addEventListener("click", clearFilters);
  elements.clearRecent.addEventListener("click", () => {
    state.recent = {};
    writeStorage(STORAGE.recent, state.recent);
    renderRecent();
    announce("Recent activity cleared");
  });
  elements.drawerClose.addEventListener("click", closeDrawer);
  elements.drawerScrim.addEventListener("click", closeDrawer);
  elements.readerBack.addEventListener("click", closeReader);
  elements.readerClose.addEventListener("click", closeReader);
  elements.readerBackdrop.addEventListener("click", closeReader);
  elements.readerDocument.addEventListener("click", handleDocumentLink);
  elements.readerToc.addEventListener("click", () => toggleEpubPanel("toc"));
  elements.readerSettings.addEventListener("click", () => toggleEpubPanel("settings"));
  elements.readerBookmark.addEventListener("click", toggleEpubBookmark);
  elements.readerFocus.addEventListener("click", () => setEpubFocus(!state.epubFocused));
  elements.epubFocusExit.addEventListener("click", () => setEpubFocus(false));
  elements.readerPdf.addEventListener("load", () => {
    if (state.readerMode === "pdf" && document.body.classList.contains("reader-open")) elements.readerLoading.hidden = true;
  });
  elements.epubFrame.addEventListener("load", handleEpubFrameLoad);
  elements.epubPrevious.addEventListener("click", () => turnEpubPage(-1));
  elements.epubNext.addEventListener("click", () => turnEpubPage(1));
  elements.epubPanelScrim.addEventListener("click", closeEpubPanels);
  elements.epubTocClose.addEventListener("click", closeEpubPanels);
  elements.epubSettingsClose.addEventListener("click", closeEpubPanels);
  elements.epubTocSearch.addEventListener("input", () => {
    const query = elements.epubTocSearch.value.trim().toLowerCase();
    $$(".epub-toc-item", elements.epubTocList).forEach((item) => {
      item.hidden = Boolean(query) && !item.dataset.search.includes(query);
    });
  });
  $$('[data-epub-font]', elements.epubFontOptions).forEach((item) => item.addEventListener("click", () => {
    state.epubSettings.font = item.dataset.epubFont;
    applyEpubSettings({ preservePosition: true });
  }));
  $$('[data-epub-tone]', elements.epubToneOptions).forEach((item) => item.addEventListener("click", () => {
    state.epubSettings.tone = item.dataset.epubTone;
    applyEpubSettings({ preservePosition: true });
  }));
  elements.epubFontSize.addEventListener("input", () => {
    state.epubSettings.fontSize = Number(elements.epubFontSize.value);
    applyEpubSettings({ preservePosition: true });
  });
  elements.epubLineHeight.addEventListener("input", () => {
    state.epubSettings.lineHeight = Number(elements.epubLineHeight.value);
    applyEpubSettings({ preservePosition: true });
  });
  elements.epubPageWidth.addEventListener("input", () => {
    state.epubSettings.pageWidth = Number(elements.epubPageWidth.value);
    applyEpubSettings({ preservePosition: true });
  });
  elements.epubResetSettings.addEventListener("click", () => {
    state.epubSettings = { ...DEFAULT_EPUB_SETTINGS };
    applyEpubSettings({ preservePosition: true });
    announce("Reading appearance reset");
  });
  elements.readerMac.addEventListener("click", () => {
    const work = state.workById.get(state.readerWorkId);
    const file = work?.files.find((item) => item.path === state.readerPath);
    if (work && file) openOnMac(work, file);
  });
  elements.readerFinder.addEventListener("click", () => {
    const work = state.workById.get(state.readerWorkId);
    const file = work?.files.find((item) => item.path === state.readerPath);
    if (file) revealFile(file);
  });
  elements.menuButton.addEventListener("click", openMobileMenu);
  elements.mobileScrim.addEventListener("click", closeMobileMenu);
  document.addEventListener("keydown", (event) => {
    if (state.readerMode === "epub" && document.body.classList.contains("reader-open") && event.key !== "Escape") handleEpubKeydown(event);
    if (event.key === "/" && !document.body.classList.contains("reader-open") && document.activeElement !== elements.search) {
      event.preventDefault();
      elements.search.focus();
    }
    if (event.key === "Escape") {
      if (state.readerMode === "epub" && (elements.epubReader.classList.contains("toc-open") || elements.epubReader.classList.contains("settings-open"))) closeEpubPanels();
      else if (state.readerMode === "epub" && state.epubFocused) setEpubFocus(false);
      else if (document.body.classList.contains("reader-open")) closeReader();
      else if (document.body.classList.contains("drawer-open")) closeDrawer();
      else closeMobileMenu();
    }
  });
  window.addEventListener("beforeunload", () => state.eventSource?.close());
}

function initializeLibrary(payload) {
  const readerPath = state.readerPath;
  state.library = payload;
  state.token = payload.actionToken;
  state.revision = Number(payload.revision || state.revision || 0);
  state.workById = new Map(payload.works.map((work) => [work.id, work]));
  elements.workStat.textContent = payload.stats.works;
  elements.artifactStat.textContent = payload.stats.artifacts;
  elements.sizeStat.textContent = humanBytes(payload.stats.bytes);
  elements.integrityStat.textContent = `${payload.stats.present}/${payload.stats.indexedArtifacts || payload.stats.artifacts}`;
  renderNavigationCounts();
  renderMaterials();
  renderShelves();
  renderSubjectChips();
  renderRecent();
  renderCards();
  if (state.selectedId) {
    const selected = state.workById.get(state.selectedId);
    if (selected) renderDrawer(selected);
    else closeDrawer();
  }
  if (readerPath && state.readerMode !== "document" && !payload.materials.some((item) => item.path === readerPath)) {
    closeReader();
    announce("The open file was removed from your local shelf", true);
  }
}

function describeShelfChange(change) {
  const added = change?.added?.length || 0;
  const removed = change?.removed?.length || 0;
  const updated = change?.updated?.length || 0;
  const parts = [];
  if (added) parts.push(`${added} ${added === 1 ? "file" : "files"} added`);
  if (removed) parts.push(`${removed} removed`);
  if (updated) parts.push(`${updated} updated`);
  return parts.length ? `Shelf updated · ${parts.join(", ")}` : "Shelf index refreshed";
}

async function refreshLibrary(change = null, { quiet = false } = {}) {
  if (state.refreshing) return;
  state.refreshing = true;
  try {
    const response = await fetch("/api/library", { cache: "no-store" });
    if (!response.ok) throw new Error(`Catalog request failed (${response.status})`);
    const payload = await response.json();
    const previousRevision = state.revision;
    if (Number(payload.revision || 0) !== previousRevision || !state.library) initializeLibrary(payload);
    setLiveStatus("live", "Live sync");
    const effectiveChange = change || payload.change;
    if (!quiet && Number(payload.revision || 0) > previousRevision && effectiveChange) {
      announce(describeShelfChange(effectiveChange));
      elements.syncPill.classList.remove("did-update");
      requestAnimationFrame(() => elements.syncPill.classList.add("did-update"));
    }
  } catch (error) {
    setLiveStatus("offline", "Reconnecting…");
    if (!quiet) announce(error.message, true);
  } finally {
    state.refreshing = false;
  }
}

function connectLiveUpdates() {
  if (window.EventSource) {
    state.eventSource = new EventSource("/api/events");
    state.eventSource.addEventListener("library-ready", (event) => {
      setLiveStatus("live", "Live sync");
      try {
        const message = JSON.parse(event.data);
        if (Number(message.revision || 0) > state.revision) refreshLibrary(null, { quiet: true });
      } catch {
        // A malformed status event does not interrupt periodic refreshes.
      }
    });
    state.eventSource.addEventListener("library-changed", (event) => {
      try {
        refreshLibrary(JSON.parse(event.data));
      } catch {
        refreshLibrary();
      }
    });
    state.eventSource.onopen = () => setLiveStatus("live", "Live sync");
    state.eventSource.onerror = () => setLiveStatus("waiting", "Reconnecting…");
  } else {
    setLiveStatus("waiting", "Auto refresh");
  }
  state.refreshTimer = window.setInterval(() => refreshLibrary(null, { quiet: true }), 12000);
}

async function start() {
  initializeTheme();
  bindEvents();
  setLiveStatus("waiting", "Connecting…");
  try {
    const response = await fetch("/api/library", { cache: "no-store" });
    if (!response.ok) throw new Error(`Catalog request failed (${response.status})`);
    initializeLibrary(await response.json());
    connectLiveUpdates();
  } catch (error) {
    elements.grid.replaceChildren();
    elements.grid.hidden = true;
    elements.empty.hidden = false;
    $("h3", elements.empty).textContent = "The local catalog could not load";
    $("p", elements.empty).textContent = error.message;
    elements.clearFilters.hidden = true;
    setLiveStatus("offline", "Shelf offline");
    announce(error.message, true);
  }
}

start();
