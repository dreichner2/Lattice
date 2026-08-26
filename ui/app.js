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
  pdfState: "cs-library:pdf-state",
};

const DEFAULT_EPUB_SETTINGS = Object.freeze({
  font: "serif",
  fontSize: 19,
  lineHeight: 1.7,
  pageWidth: 760,
  tone: "paper",
});

const IMPORT_ACCEPTED = /\.(pdf|epub|txt|mp3|m4a|wav|flac)$/i;
const AUDIO_ACCEPTED = /\.(mp3|m4a|wav|flac)$/i;
const AUDIO_FORMATS = new Set(["MP3", "M4A", "WAV", "FLAC"]);
const IMPORT_KINDS = new Set(["book", "paper", "lecture", "audio"]);
const DEFAULT_IMPORT_KIND = "book";
const IMPORT_FILE_ACCEPT = ".pdf,.epub,.txt,.mp3,.m4a,.wav,.flac,application/pdf,application/epub+zip,text/plain,audio/mpeg,audio/mp4,audio/wav,audio/flac";
const AUDIO_FILE_ACCEPT = ".mp3,.m4a,.wav,.flac,audio/mpeg,audio/mp4,audio/wav,audio/flac";
const IMPORT_STATUS_COMPLETE = new Set(["complete", "completed", "ready", "succeeded", "success", "fallback", "manual"]);
const IMPORT_STATUS_FAILED = new Set(["failed", "error"]);
// A bounded server queue can legitimately take several minutes for a large
// multi-file drop. Poll long enough for every queued item to reach a terminal
// state instead of presenting a still-running job as a fallback after ~2 min.
const IMPORT_POLL_LIMIT = 900;
const PRIVATE_ACCESS_STORAGE = "lattice:private-access";

function capturePrivateAccessToken() {
  try {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const candidate = fragment.get("access") || "";
    if (/^[A-Za-z0-9_-]{43,128}$/.test(candidate)) {
      window.sessionStorage.setItem(PRIVATE_ACCESS_STORAGE, candidate);
    }
    if (fragment.has("access")) {
      fragment.delete("access");
      const suffix = fragment.toString();
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}${window.location.search}${suffix ? `#${suffix}` : ""}`,
      );
    }
    return window.sessionStorage.getItem(PRIVATE_ACCESS_STORAGE) || "";
  } catch {
    return "";
  }
}

const APP_MODE = new URLSearchParams(window.location.search).get("app");
const IS_NATIVE_APP = APP_MODE === "1";
const IS_WINDOWS = APP_MODE === "windows" || navigator.userAgent.includes("Windows");
const COMPUTER_LABEL = IS_WINDOWS ? "PC" : "Mac";
const FILE_MANAGER_LABEL = IS_WINDOWS ? "Explorer" : "Finder";
const SYSTEM_OPEN_LABEL = IS_WINDOWS ? "Open in Windows" : "Open on Mac";

const state = {
  library: null,
  token: "",
  privateToken: capturePrivateAccessToken(),
  query: "",
  view: "all",
  subject: "all",
  topic: "all",
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
  refreshPending: null,
  readerPath: "",
  readerWorkId: "",
  readerMode: "",
  audioPlayer: null,
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
  pdfState: readStorage(STORAGE.pdfState, {}) || {},
  pdfClosePending: false,
  pdfCloseTimer: 0,
  readerDesk: null,
  videoCatalog: null,
  videoLibrary: null,
  tutor: null,
  imports: [],
  importKind: "book",
  importDialogLastFocus: null,
  aiStatus: null,
  dragDepth: 0,
};

const elements = {
  appActionsMenu: $("#appActionsMenu"),
  appCheckUpdatesButton: $("#appCheckUpdatesButton"),
  appCheckUpdatesDetail: $("#appCheckUpdatesDetail"),
  appCheckUpdatesTitle: $("#appCheckUpdatesTitle"),
  appChooseLibraryButton: $("#appChooseLibraryButton"),
  appDisconnectLibraryButton: $("#appDisconnectLibraryButton"),
  appLibraryActionsDivider: $("#appLibraryActionsDivider"),
  appMoreButton: $("#appMoreButton"),
  appMoveLibraryButton: $("#appMoveLibraryButton"),
  appOpenLibraryButton: $("#appOpenLibraryButton"),
  appPlatformLabel: $("#appPlatformLabel"),
  appReconnectLibraryButton: $("#appReconnectLibraryButton"),
  appReloadButton: $("#appReloadButton"),
  appShell: $(".app-shell"),
  appVersionLabel: $("#appVersionLabel"),
  addButton: $("#addButton"),
  addFilesInput: $("#addFilesInput"),
  aiReadiness: $("#aiReadiness"),
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
  heroAddButton: $("#heroAddButton"),
  heroDescription: $("#heroDescription"),
  heroEyebrow: $("#heroEyebrow"),
  heroTrust: $("#heroTrust"),
  grid: $("#libraryGrid"),
  integrityStat: $("#integrityStat"),
  integrityStatLabel: $("#integrityStatLabel"),
  integrityStatNote: $("#integrityStatNote"),
  librarySection: $("#librarySection"),
  menuButton: $("#menuButton"),
  materialNav: $("#materialNav"),
  mobileScrim: $("#mobileScrim"),
  nativeAppMenu: $("#nativeAppMenu"),
  pageTitle: $("#pageTitle"),
  random: $("#randomButton"),
  readerBack: $("#readerBackButton"),
  readerAudio: $("#readerAudioButton"),
  readerBackdrop: $("#readerBackdrop"),
  readerBookmark: $("#readerBookmarkButton"),
  readerClose: $("#readerCloseButton"),
  readerDocument: $("#documentReader"),
  readerDesk: $("#readerDesk"),
  readerDeskButton: $("#readerDeskButton"),
  readerFinder: $("#readerFinderButton"),
  readerFocus: $("#readerFocusButton"),
  readerKicker: $("#readerKicker"),
  readerLoading: $("#readerLoading"),
  readerMac: $("#readerMacButton"),
  readerPdf: $("#pdfReader"),
  readerSettings: $("#readerSettingsButton"),
  readerShell: $("#readerShell"),
  readerStage: $("#readerStage"),
  readerTutor: $("#readerTutorButton"),
  readerTutorPeek: $("#readerTutorPeekButton"),
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
  subjectNav: $("#subjectNav"),
  sidebarStatusDot: $("#sidebarStatusDot"),
  sidebarStatusText: $("#sidebarStatusText"),
  sizeStat: $("#sizeStat"),
  sizeStatLabel: $("#sizeStatLabel"),
  sizeStatNote: $("#sizeStatNote"),
  sort: $("#sortSelect"),
  subjectChips: $("#subjectChips"),
  topicChips: $("#topicChips"),
  theme: $("#themeButton"),
  syncPill: $("#syncPill"),
  syncText: $("#syncText"),
  toastRegion: $("#toastRegion"),
  viewButton: $("#viewButton"),
  workStat: $("#workStat"),
  workStatLabel: $("#workStatLabel"),
  workStatNote: $("#workStatNote"),
  artifactStatLabel: $("#artifactStatLabel"),
  artifactStatNote: $("#artifactStatNote"),
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
  dropOverlay: $("#dropOverlay"),
  importBackdrop: $("#importBackdrop"),
  importChoose: $("#importChooseButton"),
  importClose: $("#importCloseButton"),
  importDropZone: $("#importDropZone"),
  importKindPicker: $("#importKindPicker"),
  importQueue: $("#importQueue"),
  importShell: $("#importShell"),
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

function humanDate(value) {
  const date = new Date(`${value}T12:00:00`);
  return Number.isNaN(date.valueOf())
    ? String(value || "—")
    : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function monogram(title) {
  const words = title
    .replace(/[^A-Za-z0-9 ]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .filter((word, index) => index > 0 || !["the", "a", "an"].includes(word.toLowerCase()));
  if (!words.length) return "L";
  return words.slice(0, 2).map((word) => word[0].toUpperCase()).join("");
}

function compactSubject(subject) {
  return String(subject || "Other").replace(" & ", " · ");
}

function subjectSummary(item) {
  const subjects = Array.isArray(item?.subjects) && item.subjects.length
    ? item.subjects
    : [item?.subject || "Other"];
  return subjects.join(" · ");
}

function slugId(value) {
  return String(value || "other").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "other";
}

function normalizeLibraryPayload(payload) {
  const library = payload && typeof payload === "object" ? payload : {};
  library.works = Array.isArray(library.works) ? library.works : [];
  library.materials = Array.isArray(library.materials) ? library.materials : [];
  library.subjects = (Array.isArray(library.subjects) ? library.subjects : [])
    .map((subject) => typeof subject === "string"
      ? { id: slugId(subject), name: subject }
      : { ...subject, id: subject.id || slugId(subject.name || subject.label), name: subject.name || subject.label || "Other" });
  const subjectNames = new Map(library.subjects.map((subject) => [subject.id, subject.name]));

  const topics = new Map();
  (Array.isArray(library.topics) ? library.topics : []).forEach((topic) => {
    const normalized = typeof topic === "string"
      ? { id: slugId(topic), name: topic }
      : { ...topic, id: topic.id || slugId(topic.name || topic.label), name: topic.name || topic.label || "Other" };
    topics.set(normalized.id, normalized);
  });

  const normalizeAssignedSubjects = (item, fallback = null) => {
    const suppliedIds = Array.isArray(item.subjectIds)
      ? item.subjectIds
      : Array.isArray(item.subject_ids)
        ? item.subject_ids
        : [];
    let subjectIds = suppliedIds
      .filter((subjectId) => typeof subjectId === "string" && subjectId)
      .filter((subjectId, index, values) => values.indexOf(subjectId) === index);
    if (!subjectIds.length && fallback?.subjectIds?.length) subjectIds = [...fallback.subjectIds];
    if (!subjectIds.length) subjectIds = [item.subjectId || item.subject_id || "other"];

    const suppliedNames = Array.isArray(item.subjects) ? item.subjects : [];
    const subjects = subjectIds.map((subjectId, index) => {
      const name = subjectNames.get(subjectId)
        || suppliedNames[index]
        || (index === 0 ? item.subject : "")
        || "Other";
      if (!subjectNames.has(subjectId)) {
        const subject = { id: subjectId, name };
        library.subjects.push(subject);
        subjectNames.set(subject.id, subject.name);
      }
      return name;
    });
    item.subjectIds = subjectIds;
    item.subjects = subjects;
    item.subjectId = subjectIds[0];
    item.subject = subjects[0];
  };

  library.works.forEach((work) => {
    const legacyTopic = !work.topic && !work.topicId;
    work.topic = work.topic || work.shelf || (legacyTopic ? work.subject : "") || "Unsorted";
    work.topicId = work.topicId || work.shelfId || (legacyTopic ? work.subjectId : "") || slugId(work.topic);
    normalizeAssignedSubjects(work);
    if (!topics.has(work.topicId)) topics.set(work.topicId, { id: work.topicId, name: work.topic });
  });
  const workById = new Map(library.works.map((work) => [work.id, work]));
  library.materials.forEach((material) => {
    const work = workById.get(material.workId);
    normalizeAssignedSubjects(material, work);
    material.topicId = material.topicId || work?.topicId || slugId(material.topic || "Unsorted");
    material.topic = material.topic || work?.topic || "Unsorted";
  });
  library.topics = [...topics.values()];
  return library;
}

function primaryFile(work) {
  return work.files[0];
}

function isBrowserReadable(file) {
  return ["EPUB", "PDF", "TXT"].includes(file.format);
}

function isAudioPlayable(file) {
  return Boolean(file) && (
    file.materialType === "audio"
    || AUDIO_FORMATS.has(String(file.format || "").toUpperCase())
    || AUDIO_ACCEPTED.test(String(file.path || ""))
  );
}

function inAppActionLabel(file) {
  if (isAudioPlayable(file)) return "Listen";
  if (isBrowserReadable(file)) return "Read here";
  return SYSTEM_OPEN_LABEL;
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
  elements.sidebarStatusText.textContent = mode === "live" ? "Watching shared materials" : message;
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

async function vaultAction(path, operation) {
  const response = await fetch(`/api/vault/${operation}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Library-Token": state.token,
    },
    body: JSON.stringify({ path }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Vault action failed");
  return payload;
}

const VAULT_OPERATION_LABELS = {
  checkout: "Verified vault copy ready",
  checkin: "Released local copy to the vault",
  restore: "Restored to this device",
};

async function runVaultOperation(path, operation) {
  try {
    const payload = await vaultAction(path, operation);
    announce(payload.warning || VAULT_OPERATION_LABELS[operation] || "Vault updated");
    await refreshLibrary(null, { quiet: true });
  } catch (error) {
    announce(error.message, true);
  }
}

async function responsePayload(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function selectedImportKind() {
  const selected = elements.importKindPicker.querySelector('input[name="importKind"]:checked')?.value;
  return IMPORT_KINDS.has(selected) ? selected : DEFAULT_IMPORT_KIND;
}

function setImportKind(kind) {
  const normalized = IMPORT_KINDS.has(kind) ? kind : DEFAULT_IMPORT_KIND;
  const option = elements.importKindPicker.querySelector(`input[name="importKind"][value="${normalized}"]`);
  if (option) option.checked = true;
  state.importKind = normalized;
  elements.addFilesInput.accept = normalized === "audio" ? AUDIO_FILE_ACCEPT : IMPORT_FILE_ACCEPT;
  return normalized;
}

function importKindForFile(file, preferredKind) {
  if (AUDIO_ACCEPTED.test(String(file?.name || ""))) return "audio";
  const normalized = IMPORT_KINDS.has(preferredKind) ? preferredKind : DEFAULT_IMPORT_KIND;
  return normalized === "audio" ? DEFAULT_IMPORT_KIND : normalized;
}

function setImportBackgroundInert(inert) {
  const regions = [
    elements.appShell,
    elements.drawer,
    elements.readerShell,
    document.querySelector("#latticeAudioPlayer"),
    document.querySelector("#tutorScrim"),
    document.querySelector("#tutorPanel"),
  ];
  regions.filter(Boolean).forEach((element) => { element.inert = inert; });
}

function setAIReadiness(status, title, detail) {
  elements.aiReadiness.dataset.status = status;
  const strong = $("strong", elements.aiReadiness);
  const small = $("small", elements.aiReadiness);
  strong.textContent = title;
  small.textContent = detail;
}

async function refreshAIStatus() {
  if (selectedImportKind() === "audio") {
    state.aiStatus = { ready: true, audio: true };
    setAIReadiness("ready", "Local audio import", "Audio bytes stay local; only shelf details are indexed.");
    return;
  }
  setAIReadiness("checking", "Checking Luna metadata…", "Files are added even when AI is unavailable.");
  try {
    const response = await fetch("/api/ai/status", { cache: "no-store" });
    const payload = await responsePayload(response);
    if (!response.ok) throw new Error(payload.error || `AI status failed (${response.status})`);
    const ready = payload.ready === true || (payload.available === true && payload.authenticated !== false);
    state.aiStatus = { ...payload, ready };
    if (ready) {
      setAIReadiness("ready", "Luna metadata is ready", "New files will be named and categorized automatically.");
    } else {
      setAIReadiness("fallback", "Local metadata fallback", payload.message || "Sign in to Codex to enable automatic details. You can still edit everything here.");
    }
  } catch {
    state.aiStatus = { ready: false };
    setAIReadiness("fallback", "Local metadata fallback", "Luna is unavailable right now. Files still import and their details remain editable.");
  }
}

function openImportDialog({ chooseImmediately = false, kind = DEFAULT_IMPORT_KIND } = {}) {
  setImportKind(kind);
  if (!document.body.classList.contains("import-open")) state.importDialogLastFocus = document.activeElement;
  document.body.classList.add("import-open");
  setImportBackgroundInert(true);
  elements.importShell.setAttribute("aria-hidden", "false");
  renderImportQueue();
  refreshAIStatus();
  if (chooseImmediately) elements.addFilesInput.click();
  else elements.importClose.focus();
}

function openAudioImportDialog({ chooseImmediately = false } = {}) {
  openImportDialog({ chooseImmediately, kind: "audio" });
}

function closeImportDialog() {
  document.body.classList.remove("import-open");
  elements.importShell.setAttribute("aria-hidden", "true");
  setImportBackgroundInert(false);
  elements.addFilesInput.value = "";
  setImportKind(DEFAULT_IMPORT_KIND);
  const target = state.importDialogLastFocus;
  state.importDialogLastFocus = null;
  const targetIsVisible = target
    && document.contains(target)
    && !target.hidden
    && !target.closest('[aria-hidden="true"], [inert]');
  if (targetIsVisible) target.focus();
  else elements.addButton.focus();
}

function chooseImportFiles() {
  setImportKind(selectedImportKind());
  elements.addFilesInput.value = "";
  elements.addFilesInput.click();
}

window.sharedLibraryChooseFiles = () => openImportDialog();

function runImportPrimaryAction() {
  const waiting = state.imports.filter((item) => item.status === "waiting");
  if (!waiting.length) {
    chooseImportFiles();
    return;
  }
  const kind = selectedImportKind();
  waiting.forEach((item) => {
    if (kind === "audio" && !AUDIO_ACCEPTED.test(String(item.file?.name || ""))) {
      item.status = "failed";
      item.error = "Choose an MP3, M4A, WAV, or FLAC file for the audio shelf.";
      return;
    }
    item.kind = importKindForFile(item.file, kind);
    uploadImport(item);
  });
  renderImportQueue();
}

function importStatusLabel(item) {
  if (item.status === "waiting") return "Ready to add";
  if (item.status === "uploading") return "Copying to the shared shelf…";
  if (item.status === "enriching") return item.statusMessage || "Luna is filling in the details…";
  if (item.status === "saving") return "Saving details…";
  if (item.status === "failed") return item.error || "Could not add this file";
  if (item.error) return item.error;
  if (item.duplicate) return "Already on the shelf";
  if (item.aiFallback) return "Added with editable local details";
  if (item.status === "complete") return "Ready on the shelf";
  return "Preparing…";
}

function importMetadataValue(metadata, key, fallback = "") {
  const value = metadata?.[key];
  if (Array.isArray(value)) return value.join(", ");
  return value === null || value === undefined ? fallback : String(value);
}

function normalizeImportMetadata(metadata) {
  if (!metadata || typeof metadata !== "object") return null;
  const rawSubjectIds = Array.isArray(metadata.subjectIds)
    ? metadata.subjectIds
    : Array.isArray(metadata.subject_ids)
      ? metadata.subject_ids
      : [metadata.subjectId || metadata.subject_id || "other"];
  const subjectIds = rawSubjectIds
    .filter((subjectId) => typeof subjectId === "string" && subjectId)
    .filter((subjectId, index, values) => values.indexOf(subjectId) === index);
  if (!subjectIds.length) subjectIds.push("other");
  const subjects = subjectIds.map((subjectId, index) => (
    (state.library?.subjects || []).find((entry) => entry.id === subjectId)?.name
    || (Array.isArray(metadata.subjects) ? metadata.subjects[index] : "")
    || (index === 0 ? metadata.subject : "")
    || "Other"
  ));
  return {
    ...metadata,
    subjectIds,
    subjects,
    subjectId: subjectIds[0],
    subject: subjects[0],
    topics: Array.isArray(metadata.topics) ? metadata.topics : [],
  };
}

function metadataEditor(item) {
  const metadata = item.draft || item.metadata || {};
  const form = node("form", "import-metadata-form");
  form.dataset.path = item.path;

  const textField = (label, name, value, placeholder = "") => {
    const wrapper = node("label", "import-field");
    wrapper.append(node("span", "", label));
    const input = document.createElement("input");
    input.name = name;
    input.value = value;
    input.placeholder = placeholder;
    wrapper.append(input);
    return wrapper;
  };

  form.append(
    textField("Title", "title", importMetadataValue(metadata, "title", item.file?.name || ""), "Title"),
    textField("Authors or creators", "authors", importMetadataValue(metadata, "authors"), "Separate names with commas"),
  );
  const compact = node("div", "import-field-row");
  compact.append(
    textField("Year", "year", importMetadataValue(metadata, "year"), "YYYY"),
    textField("Edition", "edition", importMetadataValue(metadata, "edition"), "Optional"),
  );
  form.append(compact);

  const subjectField = document.createElement("fieldset");
  subjectField.className = "import-field import-subject-field";
  const subjectLegend = document.createElement("legend");
  subjectLegend.textContent = "Subjects";
  const subjectOptions = node("div", "import-subject-options");
  const selectedSubjects = new Set(metadata.subjectIds || [metadata.subjectId || "other"]);
  const availableSubjects = state.library?.subjects?.length
    ? state.library.subjects
    : [{ id: metadata.subjectId || "other", name: metadata.subject || "Other" }];
  availableSubjects.forEach((subject) => {
    const option = node("label", "import-subject-option");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "subjectIds";
    checkbox.value = subject.id;
    checkbox.checked = selectedSubjects.has(subject.id);
    if (subject.known === false) {
      checkbox.disabled = true;
      option.classList.add("is-from-newer-taxonomy");
      option.title = "Preserved from another device; update Lattice before changing this subject.";
    }
    option.append(checkbox, node("span", "", subject.name));
    subjectOptions.append(option);
  });
  const subjectHelp = node("small", "import-field-help", "Choose every broad subject this item belongs to.");
  subjectField.append(subjectLegend, subjectOptions, subjectHelp);
  const topicsField = textField("Topics", "topics", importMetadataValue(metadata, "topics"), "Comma-separated topics");
  topicsField.classList.add("import-topics-field");
  form.append(subjectField, topicsField);

  const actions = node("div", "import-form-actions");
  actions.append(
    button("button button-quiet", "Cancel", () => {
      item.editing = false;
      renderImportQueue();
    }),
  );
  const submit = node("button", "button button-primary", "Save details");
  submit.type = "submit";
  actions.append(submit);
  form.append(actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const firstSubject = form.querySelector('input[name="subjectIds"]');
    const hasSubject = Boolean(form.querySelector('input[name="subjectIds"]:checked'));
    if (firstSubject) {
      firstSubject.setCustomValidity(hasSubject ? "" : "Choose at least one subject.");
      if (!hasSubject) {
        firstSubject.reportValidity();
        return;
      }
    }
    await saveImportMetadata(item, new FormData(form));
  });
  if (item.status === "saving") {
    form.querySelectorAll("input, select, button").forEach((control) => { control.disabled = true; });
  }
  return form;
}

function renderImportQueue() {
  const waitingCount = state.imports.filter((item) => item.status === "waiting").length;
  elements.importChoose.textContent = waitingCount
    ? `Add ${waitingCount} ${waitingCount === 1 ? "file" : "files"}`
    : "Choose files";
  if (!state.imports.length) {
    elements.importQueue.replaceChildren(node("p", "import-queue-empty", "Files you add will appear here with their progress and editable details."));
    return;
  }
  const rows = state.imports.map((item) => {
    const row = node("article", `import-item is-${item.status}${item.aiFallback ? " is-fallback" : ""}`);
    const statusIcon = node(
      "span",
      "import-item-status",
      item.status === "complete" ? "✓" : item.status === "failed" ? "!" : item.status === "waiting" ? "+" : "↻",
    );
    statusIcon.setAttribute("aria-hidden", "true");
    const copy = node("div", "import-item-copy");
    copy.append(
      node("strong", "", item.metadata?.title || item.file?.name || item.path || "Imported material"),
      node("small", "", importStatusLabel(item)),
    );
    const controls = node("div", "import-item-controls");
    if ((item.status === "complete" || item.status === "failed") && item.path && item.editableMetadata) {
      controls.append(button("import-edit-button", item.editing ? "Editing" : "Edit details", () => {
        item.editing = !item.editing;
        renderImportQueue();
      }));
    }
    row.append(statusIcon, copy, controls);
    if (item.editing && item.path) row.append(metadataEditor(item));
    return row;
  });
  elements.importQueue.replaceChildren(...rows);
}

async function saveImportMetadata(item, formData) {
  if (item.status === "saving") return;
  const topics = String(formData.get("topics") || "")
    .split(",")
    .map((topic) => topic.trim())
    .filter(Boolean);
  const body = {
    path: item.path,
    title: String(formData.get("title") || "").trim(),
    authors: String(formData.get("authors") || "").trim(),
    year: String(formData.get("year") || "").trim(),
    edition: String(formData.get("edition") || "").trim(),
    subjectIds: formData.getAll("subjectIds").map((subjectId) => String(subjectId)),
    topics,
  };
  body.subjectId = body.subjectIds[0] || "other";
  item.draft = body;
  item.status = "saving";
  renderImportQueue();
  try {
    const response = await fetch("/api/metadata", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Library-Token": state.token,
      },
      body: JSON.stringify(body),
    });
    const payload = await responsePayload(response);
    if (!response.ok) throw new Error(payload.error || `Metadata save failed (${response.status})`);
    item.metadata = normalizeImportMetadata(payload.metadata || { ...item.metadata, ...body });
    item.draft = null;
    item.editing = false;
    item.status = "complete";
    item.aiFallback = false;
    item.error = "";
    renderImportQueue();
    await refreshLibrary(null, { quiet: true });
    announce("Details saved to the shared shelf");
  } catch (error) {
    item.status = "complete";
    item.error = error.message;
    item.editing = true;
    renderImportQueue();
    announce(error.message, true);
  }
}

function importItemForFile(file, kind) {
  return {
    id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
    file,
    kind,
    status: "waiting",
    path: "",
    jobId: "",
    metadata: null,
    duplicate: false,
    aiFallback: false,
    statusMessage: "",
    editing: false,
    editableMetadata: false,
    draft: null,
    error: "",
  };
}

function queueImportFiles(fileList) {
  const files = [...fileList];
  const preferredKind = selectedImportKind();
  const accepted = files.filter((file) => (
    IMPORT_ACCEPTED.test(file.name)
    && (preferredKind !== "audio" || AUDIO_ACCEPTED.test(file.name))
  ));
  const rejected = files.length - accepted.length;
  if (rejected) announce(`${rejected} unsupported ${rejected === 1 ? "file was" : "files were"} skipped`, true);
  if (!accepted.length) return;
  const dialogKind = accepted.every((file) => AUDIO_ACCEPTED.test(file.name))
    ? "audio"
    : importKindForFile(accepted[0], preferredKind);
  openImportDialog({ kind: dialogKind });
  const items = accepted.map((file) => importItemForFile(
    file,
    importKindForFile(file, preferredKind),
  ));
  state.imports.unshift(...items);
  renderImportQueue();
  items.forEach((item) => uploadImport(item));
}

async function uploadImport(item) {
  item.status = "uploading";
  renderImportQueue();
  try {
    const response = await fetch("/api/import", {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Library-Token": state.token,
        "X-Library-Filename": encodeURIComponent(item.file.name),
        "X-Library-Kind": item.kind,
      },
      body: item.file,
    });
    const payload = await responsePayload(response);
    if (!response.ok) throw new Error(payload.error || `Import failed (${response.status})`);
    item.path = payload.path || "";
    item.jobId = payload.jobId || "";
    item.metadata = normalizeImportMetadata(payload.metadata);
    item.duplicate = payload.duplicate === true;
    item.editableMetadata = payload.editableMetadata === true;
    // A duplicate can still carry a recovery job when its synchronized
    // sidecar was left pending by an earlier shutdown. Poll every real job.
    item.status = item.jobId ? "enriching" : "complete";
    item.aiFallback = !item.jobId && !item.duplicate && state.aiStatus?.ready === false;
    renderImportQueue();
    await refreshLibrary(null, { quiet: true });
    if (item.status === "enriching") await pollImportStatus(item);
    else announce(item.duplicate ? `${item.file.name} is already on the shelf` : `${item.file.name} was added`);
  } catch (error) {
    item.status = "failed";
    item.error = error.message;
    renderImportQueue();
    announce(`${item.file.name}: ${error.message}`, true);
  }
}

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function pollImportStatus(item) {
  let consecutiveErrors = 0;
  for (let attempt = 0; attempt < IMPORT_POLL_LIMIT; attempt += 1) {
    await wait(attempt < 8 ? 750 : 1500);
    try {
      const query = new URLSearchParams({ id: item.jobId, path: item.path });
      const response = await fetch(`/api/import-status?${query}`, {
        cache: "no-store",
        headers: { "X-Library-Token": state.token },
      });
      const payload = await responsePayload(response);
      if (!response.ok) {
        if (response.status === 404) {
          await refreshLibrary(null, { quiet: true });
          const work = state.library?.works?.find((candidate) => candidate.files?.some((file) => file.path === item.path));
          const metadataStatus = String(work?.metadataStatus || "");
          if (["ai-enriched", "local-fallback", "manual"].includes(metadataStatus)) {
            item.status = "complete";
            item.aiFallback = metadataStatus === "local-fallback";
            item.metadata = normalizeImportMetadata({
              title: work.title,
              authors: work.authors,
              year: work.year || null,
              edition: work.edition || "",
              subjectIds: work.subjectIds,
              subjects: work.subjects,
              subjectId: work.subjectId,
              subject: work.subject,
              topics: work.topics || [],
            });
            item.error = "";
            renderImportQueue();
            return;
          }
        }
        throw new Error(payload.error || `Metadata status failed (${response.status})`);
      }
      if (payload.id) item.jobId = String(payload.id);
      consecutiveErrors = 0;
      const status = String(payload.status || payload.state || "pending").toLowerCase();
      item.statusMessage = String(payload.message || "");
      if (payload.metadata) item.metadata = normalizeImportMetadata(payload.metadata);
      if (IMPORT_STATUS_COMPLETE.has(status)) {
        item.status = "complete";
        item.aiFallback = status === "fallback" || payload.fallback === true || payload.ai === "fallback";
        renderImportQueue();
        await refreshLibrary(null, { quiet: true });
        announce(`${item.file.name} is ready`);
        return;
      }
      if (IMPORT_STATUS_FAILED.has(status)) {
        item.status = "failed";
        item.aiFallback = false;
        item.error = payload.message || payload.error || "The file was added, but its details could not be saved";
        renderImportQueue();
        await refreshLibrary(null, { quiet: true });
        announce(`${item.file.name} was added, but its details need attention`, true);
        return;
      }
    } catch (error) {
      consecutiveErrors += 1;
      item.statusMessage = consecutiveErrors < 5
        ? "Metadata connection interrupted; retrying…"
        : "Still reconnecting to the local metadata service…";
      item.error = "";
      renderImportQueue();
      continue;
    }
  }
  item.status = "enriching";
  item.statusMessage = "Automatic metadata is still pending; Lattice will keep checking.";
  renderImportQueue();
  window.setTimeout(() => {
    if (item.status === "enriching") void pollImportStatus(item);
  }, 15000);
}

function openWorkMetadataEditor(work) {
  const file = primaryFile(work);
  let item = state.imports.find((candidate) => candidate.path === file.path);
  if (!item) {
    item = {
      id: `edit-${work.id}`,
      file: { name: file.title || file.path.split("/").pop() },
      kind: work.materialType || "book",
      status: "complete",
      path: file.path,
      metadata: {
        title: work.title,
        authors: work.authors,
        year: work.year || "",
        edition: work.edition || "",
        subjectIds: work.subjectIds || [work.subjectId || "other"],
        subjects: work.subjects || [work.subject || "Other"],
        subjectId: work.subjectId || "other",
        subject: work.subject || "Other",
        topics: work.topics || (work.topic ? [work.topic] : []),
      },
      duplicate: false,
      aiFallback: false,
      editableMetadata: work.editableMetadata === true,
      draft: null,
      editing: true,
      error: "",
    };
    state.imports.unshift(item);
  } else {
    item.editing = true;
  }
  closeDrawer();
  openImportDialog({ kind: item.kind });
  renderImportQueue();
}

function isFileDrag(event) {
  return [...(event.dataTransfer?.types || [])].includes("Files") || Boolean(event.dataTransfer?.files?.length);
}

function showDropOverlay() {
  elements.dropOverlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("file-dragging");
}

function hideDropOverlay() {
  state.dragDepth = 0;
  elements.dropOverlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("file-dragging");
}

function bindImportEvents() {
  elements.addButton.addEventListener("click", () => openImportDialog());
  elements.heroAddButton.addEventListener("click", () => openImportDialog());
  elements.importChoose.addEventListener("click", runImportPrimaryAction);
  elements.importDropZone.addEventListener("click", chooseImportFiles);
  elements.importClose.addEventListener("click", closeImportDialog);
  elements.importBackdrop.addEventListener("click", closeImportDialog);
  elements.importKindPicker.addEventListener("change", () => {
    setImportKind(selectedImportKind());
    void refreshAIStatus();
  });
  elements.addFilesInput.addEventListener("change", () => queueImportFiles(elements.addFilesInput.files));
  elements.importShell.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const panel = $(".import-panel", elements.importShell);
    const focusable = $$('button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])', panel)
      .filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  window.addEventListener("dragenter", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    state.dragDepth += 1;
    showDropOverlay();
  });
  window.addEventListener("dragover", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    showDropOverlay();
  });
  window.addEventListener("dragleave", (event) => {
    if (!state.dragDepth) return;
    event.preventDefault();
    state.dragDepth = Math.max(0, state.dragDepth - 1);
    if (!state.dragDepth) hideDropOverlay();
  });
  window.addEventListener("drop", (event) => {
    event.preventDefault();
    const files = event.dataTransfer?.files;
    hideDropOverlay();
    if (files?.length) queueImportFiles(files);
  });
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
  elements.readerDeskButton.hidden = true;
  elements.readerAudio.hidden = true;
  elements.readerTutor.hidden = true;
  elements.readerTutorPeek.hidden = true;
  // The PDF reader supplies its own visible focus control. Keep this bridge
  // button available in the hidden host toolbar so older native app menus can
  // still invoke the same shared focus action.
  elements.readerFocus.hidden = mode !== "epub" && mode !== "pdf";
  elements.readerFocus.setAttribute("aria-pressed", "false");
  elements.readerFocus.setAttribute("aria-label", "Focus on the page");
  elements.readerFocus.title = "Focus on the page";
  elements.epubFocusExit.hidden = true;
  state.epubFocused = false;
  elements.readerShell.classList.remove("is-focused", "is-pdf-web");
  elements.readerShell.classList.toggle("is-epub", mode === "epub");
  document.body.classList.add("reader-open");
  elements.readerShell.setAttribute("aria-hidden", "false");
  elements.readerBack.focus();
  closeDrawer();
  closeMobileMenu();
}

function finishReaderClose() {
  window.clearTimeout(state.pdfCloseTimer);
  state.pdfClosePending = false;
  state.pdfCloseTimer = 0;
  saveEpubPosition();
  state.readerDesk?.deactivate();
  window.dispatchEvent(new CustomEvent("cs-library-reader-closed"));
  window.clearTimeout(state.epubSaveTimer);
  window.clearTimeout(state.epubTurnTimer);
  window.cancelAnimationFrame(state.epubScrollFrame);
  document.body.classList.remove("reader-open");
  elements.readerShell.setAttribute("aria-hidden", "true");
  elements.readerShell.classList.remove("is-epub", "is-focused", "is-pdf-web");
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
  elements.readerDeskButton.hidden = true;
  elements.readerAudio.hidden = true;
  elements.readerTutor.hidden = true;
  elements.readerTutorPeek.hidden = true;
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

function closeReader() {
  const activePdf = state.readerMode === "pdf"
    && document.body.classList.contains("reader-open")
    && elements.readerPdf.src !== "about:blank";
  if (!activePdf) {
    finishReaderClose();
    return;
  }
  if (state.pdfClosePending) return;

  state.pdfClosePending = true;
  sendPdfReaderMessage("prepare-close");
  state.pdfCloseTimer = window.setTimeout(async () => {
    if (!state.pdfClosePending) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
    } catch {
      // The iframe normally owns fullscreen exit. Keep the reader intact if the
      // host still reports a fullscreen element instead of tearing it down.
    }
    if (document.fullscreenElement) {
      state.pdfClosePending = false;
      state.pdfCloseTimer = 0;
      announce("Exit fullscreen before returning to the shelf", true);
      return;
    }
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    finishReaderClose();
  }, 1500);
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
  const tutorAvailable = work.tutorEligible !== false;
  elements.readerTutor.hidden = !tutorAvailable;
  elements.readerTutorPeek.hidden = !tutorAvailable || file.format !== "PDF";
  elements.readerTutor.title = !tutorAvailable
    ? (work.tutorRestriction || "This edition is reserved for human study")
    : `Ask Tutor about ${work.title}`;
  elements.readerTutorPeek.title = !tutorAvailable
    ? (work.tutorRestriction || "This edition is reserved for human study")
    : `Open compact Tutor for ${work.title}`;
  elements.readerMac.textContent = file.format === "EPUB" && !IS_WINDOWS ? "Open in Books" : SYSTEM_OPEN_LABEL;
  elements.readerFinder.textContent = FILE_MANAGER_LABEL;
  const descriptor = {
    path: file.path,
    workId: work.id,
    sha256: file.sha256 || "",
    title: file.title || work.title,
    workTitle: work.title,
    format: file.format,
  };
  elements.readerDeskButton.hidden = false;
  elements.readerAudio.hidden = false;
  state.readerDesk?.activate(descriptor);
  window.dispatchEvent(new CustomEvent("cs-library-reader-document", { detail: descriptor }));
  return descriptor;
}

const PDF_READER_CHANNEL = "lattice-pdf-reader";
const PDF_LAYOUTS = new Set(["continuous", "single", "spread"]);
const PDF_SCALE_PRESETS = new Set(["auto", "page-fit", "page-width"]);

function normalizePdfReaderState(value) {
  if (!value || typeof value !== "object") return null;
  const numericScale = Number(value.scaleValue);
  const scaleValue = PDF_SCALE_PRESETS.has(value.scaleValue)
    ? value.scaleValue
    : Number.isFinite(numericScale) && numericScale >= 0.1 && numericScale <= 8
      ? numericScale
      : "page-width";
  const rotation = [0, 90, 180, 270].includes(Number(value.rotation)) ? Number(value.rotation) : 0;
  return {
    page: Math.max(1, Math.trunc(Number(value.page)) || 1),
    layout: PDF_LAYOUTS.has(value.layout) ? value.layout : "continuous",
    scaleValue,
    rotation,
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : new Date().toISOString(),
  };
}

function sendPdfReaderMessage(type, detail = {}) {
  if (state.readerMode !== "pdf" || !elements.readerPdf.contentWindow) return;
  elements.readerPdf.contentWindow.postMessage(
    { channel: PDF_READER_CHANNEL, type, ...detail },
    window.location.origin,
  );
}

async function recognizePdfPageText(message) {
  const page = Math.max(1, Math.trunc(Number(message.page)) || 1);
  const requestId = String(message.requestId || "").slice(0, 120);
  if (typeof window.csLibraryNativeCall !== "function") {
    sendPdfReaderMessage("ocr-result", {
      requestId,
      page,
      lines: [],
      error: "On-device text recognition is available in the Lattice macOS app.",
    });
    return;
  }
  try {
    const result = await window.csLibraryNativeCall("pdf.ocrPage", {
      path: state.readerPath,
      page,
    });
    sendPdfReaderMessage("ocr-result", {
      requestId,
      page,
      lines: Array.isArray(result?.lines) ? result.lines : [],
      cached: result?.cached === true,
    });
  } catch (error) {
    const detail = IS_WINDOWS
      ? "This scan has no embedded text. On-device text recognition is currently available in Lattice for macOS."
      : String(error?.message || error || "Text recognition failed").slice(0, 500);
    sendPdfReaderMessage("ocr-result", {
      requestId,
      page,
      lines: [],
      error: detail,
    });
  }
}

function syncReaderBookmarkButton(bookmarked) {
  const active = Boolean(bookmarked);
  if (state.readerMode === "epub") {
    elements.readerBookmark.classList.toggle("is-bookmarked", active);
    elements.readerBookmark.textContent = active ? "★" : "☆";
    elements.readerBookmark.setAttribute("aria-label", active ? "Remove this bookmark" : "Bookmark this position");
  } else if (state.readerMode === "pdf") {
    sendPdfReaderMessage("bookmark-status", { bookmarked: active });
  }
}

function navigateReaderDeskLocator(locator) {
  if (!locator || typeof locator !== "object") return;
  if (state.readerMode === "pdf" && locator.type === "pdf") {
    sendPdfReaderMessage("navigate", { page: Math.max(1, Math.trunc(Number(locator.page)) || 1) });
    return;
  }
  if (state.readerMode !== "epub" || locator.type !== "epub" || !state.epubPackage) return;
  let index = state.epubPackage.chapters.findIndex((chapter) => chapter.entry === locator.entry);
  if (index < 0) index = clamp(Number(locator.index) || 0, 0, state.epubPackage.chapters.length - 1);
  navigateEpub(index, { ratio: clamp(Number(locator.ratio) || 0, 0, 1) });
}

function initializeReaderDesk() {
  state.readerDesk = window.LatticeReaderDesk?.create({
    root: elements.readerDesk,
    shell: elements.readerShell,
    toggle: elements.readerDeskButton,
    onNavigate: navigateReaderDeskLocator,
    onBookmarkState: syncReaderBookmarkButton,
    onClose: () => {
      if (state.readerMode === "pdf") {
        elements.readerPdf.focus({ preventScroll: true });
        sendPdfReaderMessage("focus");
      }
    },
  }) || null;
}

function initializePdfReaderFrame() {
  if (!state.readerPath) return;
  const localState = normalizePdfReaderState(state.pdfState[state.readerPath]);
  const nativeLocator = state.nativeReaderRestore?.path === state.readerPath
    ? state.nativeReaderRestore.locator
    : null;
  const initialState = nativeLocator?.type === "pdf"
    ? { ...(localState || normalizePdfReaderState({})), page: Math.max(1, Math.trunc(Number(nativeLocator.page)) || 1) }
    : localState;
  sendPdfReaderMessage("initialize", {
    path: state.readerPath,
    theme: document.documentElement.dataset.theme || "light",
    state: initialState,
  });
}

function persistPdfReaderState(path, value) {
  if (path !== state.readerPath) return;
  const normalized = normalizePdfReaderState(value);
  if (!normalized) return;
  state.pdfState[path] = normalized;
  const retained = Object.entries(state.pdfState)
    .sort(([, left], [, right]) => String(right?.updatedAt || "").localeCompare(String(left?.updatedAt || "")))
    .slice(0, 250);
  state.pdfState = Object.fromEntries(retained);
  writeStorage(STORAGE.pdfState, state.pdfState);
  window.dispatchEvent(new CustomEvent("cs-library-reader-position", {
    detail: {
      path,
      workId: state.readerWorkId,
      locator: {
        type: "pdf",
        page: normalized.page,
        layout: normalized.layout,
        scaleValue: normalized.scaleValue,
        rotation: normalized.rotation,
      },
      progress: 0,
    },
  }));
}

function handlePdfReaderMessage(event) {
  if (
    event.origin !== window.location.origin
    || event.source !== elements.readerPdf.contentWindow
    || state.readerMode !== "pdf"
  ) return;
  const message = event.data;
  if (!message || message.channel !== PDF_READER_CHANNEL || message.path !== state.readerPath) return;
  if (message.type === "boot" || message.type === "ready") {
    initializePdfReaderFrame();
  } else if (message.type === "rendered") {
    elements.readerLoading.hidden = true;
    elements.readerPdf.focus({ preventScroll: true });
    sendPdfReaderMessage("focus");
  } else if (message.type === "state") {
    persistPdfReaderState(message.path, message.state);
    state.readerDesk?.setLocation(
      { type: "pdf", page: Math.max(1, Math.trunc(Number(message.state?.page)) || 1) },
      `Page ${Math.max(1, Math.trunc(Number(message.state?.page)) || 1)}`,
    );
  } else if (message.type === "location") {
    const page = Math.max(1, Math.trunc(Number(message.page)) || 1);
    state.readerDesk?.setLocation({ type: "pdf", page }, `Page ${page}`);
  } else if (message.type === "selection") {
    const page = Math.max(1, Math.trunc(Number(message.page)) || 1);
    state.readerDesk?.setSelection(message.text, { type: "pdf", page }, `Page ${page}`);
  } else if (message.type === "ocr-request") {
    void recognizePdfPageText(message);
  } else if (message.type === "open-desk") {
    state.readerDesk?.open(message.view === "bookmarks" ? "bookmarks" : "notes");
  } else if (message.type === "open-audio") {
    if (state.audioPlayer) state.audioPlayer.openLibrary();
    else openAudioImportDialog();
  } else if (message.type === "toggle-bookmark") {
    const page = Math.max(1, Math.trunc(Number(message.page)) || 1);
    state.readerDesk?.setLocation({ type: "pdf", page }, `Page ${page}`);
    const bookmarked = state.readerDesk?.toggleCurrentBookmark() || false;
    syncReaderBookmarkButton(bookmarked);
  } else if (message.type === "focus-mode") {
    const focused = message.active === true;
    elements.readerFocus.setAttribute("aria-pressed", String(focused));
    elements.readerFocus.setAttribute("aria-label", focused ? "Show PDF controls" : "Focus on the PDF");
    elements.readerFocus.title = focused ? "Show PDF controls" : "Focus on the PDF";
    announce(focused ? "Focus mode on — press Escape to show controls" : "Reader controls shown");
  } else if (message.type === "close") {
    if (message.fullscreen === false) finishReaderClose();
    else sendPdfReaderMessage("prepare-close");
  } else if (message.type === "open") {
    const work = state.workById.get(state.readerWorkId);
    const file = work?.files.find((item) => item.path === state.readerPath);
    if (work && file) openOnMac(work, file);
  } else if (message.type === "reveal") {
    const work = state.workById.get(state.readerWorkId);
    const file = work?.files.find((item) => item.path === state.readerPath);
    if (file) revealFile(file);
  } else if (message.type === "error") {
    elements.readerLoading.hidden = true;
    announce(message.error || "This PDF could not be opened", true);
  }
}

function showPdfReader(work, file) {
  if (!file.exists) {
    announce(`${file.title} is no longer on this computer`, true);
    return;
  }
  recordOpen(work);
  showReaderShell(file.title, `${work.title} · PDF`, "pdf");
  configureLocalReaderActions(work, file);
  elements.readerPdf.title = `${file.title} PDF reader`;
  // Keep PDF behavior and controls identical in the macOS and Windows apps.
  // The native bridge still receives the document and reading-position events
  // dispatched above/below; it no longer replaces this shared reader with a
  // separate PDFKit window on macOS.
  elements.readerShell.classList.add("is-pdf-web");
  elements.readerPdf.hidden = false;
  const params = new URLSearchParams({
    file: file.path,
    title: file.title || work.title,
    work: work.title,
    theme: document.documentElement.dataset.theme || "light",
  });
  elements.readerPdf.src = `/pdf-reader.html?${params}`;
  renderCards();
}

async function showTextReader(work, file) {
  if (!file.exists) {
    announce(`${file.title} is no longer on this computer`, true);
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

function toggleActiveReaderFocus() {
  if (!document.body.classList.contains("reader-open")) return false;
  if (state.readerMode === "pdf") {
    sendPdfReaderMessage("toggle-focus");
    return true;
  }
  if (state.readerMode === "epub") {
    setEpubFocus(!state.epubFocused);
    return true;
  }
  return false;
}

window.csLibraryToggleReaderFocus = toggleActiveReaderFocus;

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
  const locator = {
    type: "epub",
    entry: chapter.entry,
    index: state.epubIndex,
    ratio: safeRatio,
    pageIndex: metrics.pageIndex,
    pageCount: metrics.pageCount,
  };
  const isBookmarked = state.readerDesk?.setLocation(locator, chapter.label) || false;
  syncReaderBookmarkButton(isBookmarked);
  window.dispatchEvent(new CustomEvent("cs-library-reader-position", {
    detail: {
      locator,
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
  // Bookmarks now live in the shared Reading Desk so PDF and EPUB use one
  // non-invasive surface and multiple positions in one chapter stay distinct.
  elements.epubBookmarks.hidden = true;
  elements.epubBookmarkList.replaceChildren();
}

function toggleEpubBookmark() {
  const chapter = currentEpubChapter();
  if (!chapter || !state.readerPath) return;
  if (state.readerDesk) {
    const bookmarked = state.readerDesk.toggleCurrentBookmark();
    syncReaderBookmarkButton(bookmarked);
    announce(bookmarked ? `Bookmarked this position in ${chapter.label}` : `Removed this bookmark from ${chapter.label}`);
    return;
  }
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
  // This function is invoked only by the native shell. Do not depend on the
  // `?app=1` presentation hint here: redirects and restored WebKit sessions can
  // legitimately omit that query string while the native bridge is still
  // active. The old gate caused macOS to consume Left/Right and then silently
  // refuse to turn the page.
  if (!document.body.classList.contains("reader-open")) return false;
  const active = document.activeElement;
  const tag = active?.tagName?.toLowerCase();
  if (["input", "textarea", "select"].includes(tag) || active?.isContentEditable) return false;
  if (active === elements.epubFrame || active === elements.readerPdf) {
    try {
      const frameActive = active.contentDocument?.activeElement;
      const frameTag = frameActive?.tagName?.toLowerCase();
      if (["input", "textarea", "select"].includes(frameTag) || frameActive?.isContentEditable) return false;
    } catch {
      // Same-origin reader frames normally expose their active element.
    }
  }
  if (state.readerMode === "pdf") {
    sendPdfReaderMessage("shortcut", { key: Number(direction) < 0 ? "ArrowLeft" : "ArrowRight" });
    return true;
  }
  if (state.readerMode !== "epub") return false;
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
    documentRoot.addEventListener("mouseup", () => {
      const text = view.getSelection()?.toString().trim() || "";
      if (text) state.readerDesk?.setSelection(text);
    });
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
    announce(`${file.title} is no longer on this computer`, true);
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
    announce(`${file.title} is no longer on this computer`, true);
    return;
  }
  recordOpen(work);
  try {
    await localAction(file.path, "open");
    announce(`Opened ${file.title} on your ${COMPUTER_LABEL}`);
  } catch (error) {
    announce(error.message, true);
  }
  renderCards();
  if (state.selectedId === work.id) renderDrawer(work);
}

async function openFile(work, file) {
  if (file.availability === "away") {
    announce("This book's local copy was released to the vault. Restore it to read here.", true);
    return;
  }
  if (isAudioPlayable(file)) {
    recordOpen(work);
    await state.audioPlayer?.playMaterial(file);
    renderCards();
  } else if (file.format === "EPUB") await showEpubReader(work, file);
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
  const rootRelative = /^(books|papers|lectures|notes|manifests)\//.test(decoded) || /^[A-Z][A-Z_]+\.md$/.test(decoded);
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

function openTutorCitation(citation) {
  if (!citation || typeof citation !== "object") return;
  if (citation.kind === "video") {
    state.tutor?.close();
    if (!state.videoLibrary?.openCourseById(String(citation.courseId || ""))) {
      announce("That cited video course is no longer in the catalog", true);
    }
    return;
  }
  if (citation.kind === "document") {
    state.tutor?.close();
    void openDocument(String(citation.path || ""), String(citation.title || "Library document"));
    return;
  }
  const work = state.workById.get(String(citation.workId || ""));
  const file = work?.files.find((item) => item.path === citation.path);
  if (!work || !file) {
    announce("That cited local source is no longer on the shelf", true);
    return;
  }
  if (file.format === "PDF") {
    const page = Number(String(citation.locator || "").match(/\bpage\s+(\d+)\b/i)?.[1] || 0);
    if (page > 0) {
      state.pdfState[file.path] = {
        ...(normalizePdfReaderState(state.pdfState[file.path]) || {}),
        page,
        updatedAt: new Date().toISOString(),
      };
      writeStorage(STORAGE.pdfState, state.pdfState);
    }
  }
  state.tutor?.close();
  void openFile(work, file);
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
    announce(`Revealed the file in ${FILE_MANAGER_LABEL}`);
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
    node("span", "cover-shelf", compactSubject(work.topic || work.subject)),
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
  const card = node("article", `book-card subject-${work.topicId || work.subjectId}${work.cataloged ? "" : " is-new-arrival"}${work.isAvailable ? "" : " is-unavailable"}`);
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
  meta.append(node("span", "", subjectSummary(work)), node("span", "", work.edition), node("span", "", humanBytes(work.totalBytes)));
  const status = workStatus(work.id);
  if (status !== "unread") meta.append(node("span", "book-status", statusLabel(status)));
  if (!work.isAvailable) meta.append(node("span", "book-status is-missing", "Missing"));
  info.append(meta);

  const actions = node("div", "card-actions");
  const primaryAction = button("button button-primary button-small", work.isCollection ? "Browse files" : inAppActionLabel(primaryFile(work)), () => {
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
  const vaultEntry = state.library?.vault?.checkedOut?.[material.path];
  const vaultPhase = vaultEntry?.phase;
  const card = node("article", `book-card material-card subject-${material.topicId || material.subjectId}${work.cataloged ? "" : " is-new-arrival"}${material.availability === "away" ? " is-away" : ""}`);
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
  cover.setAttribute("aria-label", `${isAudioPlayable(material) ? "Listen to" : isBrowserReadable(material) ? "Read" : "Open"} ${material.title}`);
  cover.addEventListener("click", () => openFile(work, material));
  const top = node("div", "cover-top");
  top.append(node("span", "cover-shelf", material.materialLabel), node("span", "format-badge", material.format));
  const bottom = node("div", "cover-bottom");
  bottom.append(node("p", "cover-title", material.title), node("span", "cover-author", work.title));
  cover.append(top, node("div", "cover-monogram", monogram(material.title)), bottom);

  const info = node("div", "book-info");
  info.append(node("h3", "book-title", material.title), node("p", "book-author", `${work.title} · ${material.authors}`));
  const meta = node("div", "book-meta");
  meta.append(node("span", "", subjectSummary(material)), node("span", "", material.format), node("span", "", humanBytes(material.bytes)), node("span", "book-status", material.materialLabel));
  info.append(meta);
  if (material.availability === "away" || vaultPhase === "away") {
    info.append(node("p", "vault-note", "In the vault — restore to read on this device"));
  } else if (vaultPhase === "local") {
    info.append(node("p", "vault-note", "Verified vault copy ready — local copy still available"));
  } else if (vaultPhase === "return-pending" || vaultPhase === "restore-pending") {
    info.append(node("p", "vault-note", "Finishing a crash-safe vault transition"));
  }
  const actions = node("div", "card-actions");
  actions.append(
    button("button button-primary button-small", inAppActionLabel(material), () => openFile(work, material)),
    button("button button-quiet button-small", "Work details", () => showDrawer(work.id)),
  );
  if (material.availability === "away" || vaultPhase === "away") {
    actions.append(
      button("button button-quiet button-small", "Restore from vault", () => runVaultOperation(material.path, "restore")),
    );
  } else if (vaultPhase === "local") {
    actions.append(
      button("button button-quiet button-small", "Release local copy", () => runVaultOperation(material.path, "checkin")),
    );
  } else if (
    vaultPhase !== "return-pending"
    && vaultPhase !== "restore-pending"
    && material.vaultEligible === true
    && state.library?.vault?.available === true
  ) {
    actions.append(
      button("button button-quiet button-small", "Check out to vault", () => runVaultOperation(material.path, "checkout")),
    );
  }
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
    if (state.subject !== "all" && !material.subjectIds.includes(state.subject)) return false;
    if (state.topic !== "all" && material.topicId !== state.topic) return false;
    if (!query) return true;
    const haystack = [
      material.title,
      material.workTitle,
      material.authors,
      ...material.subjects,
      material.topic,
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
    topic: (a, b) => a.topic.localeCompare(b.topic) || a.title.localeCompare(b.title),
    recent: (a, b) => (state.recent[b.workId] || 0) - (state.recent[a.workId] || 0) || a.title.localeCompare(b.title),
  };
  materials.sort(sorters[state.sort] || sorters.title);
  return materials;
}

function filteredWorks() {
  if (!state.library) return [];
  const query = state.query.trim().toLowerCase();
  let works = state.library.works.filter((work) => {
    if (state.subject !== "all" && !work.subjectIds.includes(state.subject)) return false;
    if (state.topic !== "all" && work.topicId !== state.topic) return false;
    if (state.view === "favorites" && !state.favorites.has(work.id)) return false;
    if (state.view === "reading" && workStatus(work.id) !== "reading") return false;
    if (state.view === "finished" && workStatus(work.id) !== "finished") return false;
    if (!query) return true;
    const haystack = [
      work.title,
      work.authors,
      ...work.subjects,
      work.topic,
      ...(Array.isArray(work.topics) ? work.topics : []),
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
    topic: (a, b) => a.topic.localeCompare(b.topic) || a.title.localeCompare(b.title),
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
    finished: ["Your completed shelf", "Finished works"],
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
  if (state.topic !== "all") {
    const topic = state.library.topics.find((item) => item.id === state.topic);
    if (topic) {
      eyebrow = state.subject === "all" ? "Topic shelf" : `${title} · topic`;
      title = topic.name;
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

function replaceHeroEyebrow(text) {
  const dot = node("span");
  dot.setAttribute("aria-hidden", "true");
  elements.heroEyebrow.replaceChildren(dot, document.createTextNode(` ${text}`));
}

function replaceHeroTrust(items) {
  elements.heroTrust.replaceChildren(...items.map((label) => {
    const item = node("span");
    const dot = node("i");
    dot.setAttribute("aria-hidden", "true");
    item.append(dot, document.createTextNode(` ${label}`));
    return item;
  }));
}

function renderHero() {
  const isVideos = state.view === "videos";
  if (isVideos) {
    const catalog = state.videoCatalog;
    replaceHeroEyebrow("Free · source-traceable · in-app playback");
    elements.pageTitle.textContent = "Your shared lecture hall";
    elements.heroDescription.textContent = "A broad, searchable archive of complete courses and individual lectures—streamed from official publishers inside one focused study workspace.";
    elements.random.firstChild.textContent = "Choose a lecture for me ";
    elements.focusSearch.textContent = "Search the lectures";
    replaceHeroTrust(["Official course sources", "Privacy-enhanced embeds", "Completion stays local"]);
    elements.workStatLabel.textContent = "Courses";
    elements.workStat.textContent = catalog ? new Intl.NumberFormat().format(catalog.stats.courses) : "—";
    elements.workStatNote.textContent = "complete course tracks";
    elements.artifactStatLabel.textContent = "Lectures";
    elements.artifactStat.textContent = catalog ? new Intl.NumberFormat().format(catalog.stats.lectures) : "—";
    elements.artifactStatNote.textContent = "searchable videos";
    elements.sizeStatLabel.textContent = "Publishers";
    elements.sizeStat.textContent = catalog ? (catalog.stats.sources ?? catalog.stats.institutions) : "—";
    elements.sizeStatNote.textContent = "official sources";
    elements.integrityStatLabel.textContent = "Verified";
    elements.integrityStat.textContent = catalog ? humanDate(catalog.verifiedAt) : "—";
    elements.integrityStatNote.textContent = catalog ? `${String(catalog.verifiedAt).slice(0, 4)} source check` : "public and embeddable";
    return;
  }
  replaceHeroEyebrow("Private · local · searchable");
  elements.pageTitle.textContent = "Knowledge, shared simply";
  elements.heroDescription.textContent = "A private home for books, papers, lecture notes, and references across every subject—with focused reading tools and live updates between your computers.";
  elements.random.firstChild.textContent = "Choose my next read ";
  elements.focusSearch.textContent = "Search the shelf";
  replaceHeroTrust(["Loopback only", "Files stay local", "Shared by Syncthing"]);
  elements.workStatLabel.textContent = "Collection";
  elements.workStat.textContent = state.library?.stats.works ?? "—";
  elements.workStatNote.textContent = "logical works";
  elements.artifactStatLabel.textContent = "Materials";
  elements.artifactStat.textContent = state.library?.stats.artifacts ?? "—";
  elements.artifactStatNote.textContent = "local files";
  elements.sizeStatLabel.textContent = "Footprint";
  elements.sizeStat.textContent = state.library ? humanBytes(state.library.stats.bytes) : "—";
  elements.sizeStatNote.textContent = "local shelf";
  elements.integrityStatLabel.textContent = "Integrity";
  elements.integrityStat.textContent = state.library ? `${state.library.stats.present}/${state.library.stats.indexedArtifacts || state.library.stats.artifacts}` : "—";
  elements.integrityStatNote.textContent = "files available";
}

function renderViewMode() {
  const isVideos = state.view === "videos";
  const lectureTotal = state.videoCatalog
    ? new Intl.NumberFormat().format(state.videoCatalog.stats.lectures)
    : "all";
  elements.librarySection.hidden = isVideos;
  if (isVideos) elements.recentSection.hidden = true;
  else renderRecent();
  elements.search.placeholder = isVideos
    ? `Search courses, instructors, topics, or ${lectureTotal} lectures…`
    : "Search title, author, topic, or file…";
  state.videoLibrary?.setQuery(state.query);
  state.videoLibrary?.setActive(isVideos);
  if (isVideos) closeDrawer();
  renderHero();
}

function setView(view) {
  state.view = view;
  state.subject = "all";
  state.topic = "all";
  syncNavigation();
  if (view !== "videos") {
    renderSubjectChips();
    renderTopicChips();
    renderCards();
  }
  renderViewMode();
  closeMobileMenu();
}

function setSubject(subjectId, preserveView = false) {
  state.subject = subjectId;
  state.topic = "all";
  if (!preserveView) state.view = "all";
  syncNavigation();
  renderSubjectChips();
  renderTopicChips();
  renderCards();
  renderViewMode();
  closeMobileMenu();
}

function setTopic(topicId, preserveView = false) {
  state.topic = topicId;
  if (!preserveView) state.view = "all";
  syncNavigation();
  renderSubjectChips();
  renderTopicChips();
  renderCards();
  renderViewMode();
  closeMobileMenu();
}

function syncNavigation() {
  $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === state.view));
  $$(".material-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === state.view));
  $$(".subject-item").forEach((item) => item.classList.toggle("is-active", state.view === "all" && item.dataset.subject === state.subject));
  $$(".topic-item").forEach((item) => item.classList.toggle("is-active", state.view === "all" && item.dataset.topic === state.topic));
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
    state.library.topics.map((topic) => [topic.id, state.library.works.filter((work) => work.topicId === topic.id).length]),
  );
  const items = state.library.topics.map((topic) => {
    const item = button("shelf-item topic-item", "", () => setTopic(topic.id), `Open ${topic.name} topic`);
    item.dataset.topic = topic.id;
    item.append(node("span", "shelf-dot"), node("span", "", topic.name), node("span", "nav-count", counts[topic.id]));
    return item;
  });
  elements.shelfNav.replaceChildren(...items);
}

function renderSubjects() {
  const counts = Object.fromEntries(
    state.library.subjects.map((subject) => [subject.id, state.library.works.filter((work) => work.subjectIds.includes(subject.id)).length]),
  );
  const items = state.library.subjects
    .filter((subject) => counts[subject.id] > 0)
    .map((subject) => {
      const item = button("shelf-item subject-item", "", () => setSubject(subject.id), `Open ${subject.name}`);
      item.dataset.subject = subject.id;
      item.append(node("span", "shelf-dot"), node("span", "", subject.name), node("span", "nav-count", counts[subject.id]));
      return item;
    });
  elements.subjectNav.replaceChildren(...items);
}

function renderSubjectChips() {
  const all = button(`chip${state.subject === "all" ? " is-active" : ""}`, "All subjects", () => setSubject("all", true));
  const chips = state.library.subjects.map((subject) => {
    const chip = button(`chip${state.subject === subject.id ? " is-active" : ""}`, subject.name, () => setSubject(subject.id, true));
    return chip;
  });
  elements.subjectChips.replaceChildren(all, ...chips);
}

function renderTopicChips() {
  const available = state.library.topics.filter((topic) => state.subject === "all"
    || state.library.works.some((work) => work.subjectIds.includes(state.subject) && work.topicId === topic.id));
  const all = button(`chip${state.topic === "all" ? " is-active" : ""}`, "All topics", () => setTopic("all", true));
  const chips = available.map((topic) => button(
    `chip${state.topic === topic.id ? " is-active" : ""}`,
    topic.name,
    () => setTopic(topic.id, true),
  ));
  elements.topicChips.replaceChildren(all, ...chips);
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
  const lead = node("div", `drawer-lead subject-${work.topicId || work.subjectId}`);
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
  const readAction = button("button button-primary", inAppActionLabel(firstFile), () => openFile(work, firstFile));
  readAction.disabled = !firstFile.exists;
  actions.append(readAction);
  if (isBrowserReadable(firstFile) || isAudioPlayable(firstFile)) {
    const macAction = button("button button-quiet", SYSTEM_OPEN_LABEL, () => openOnMac(work, firstFile));
    macAction.disabled = !firstFile.exists;
    actions.append(macAction);
  }
  if (work.tutorEligible !== false) {
    actions.append(button("button button-quiet", "✦ Ask Tutor", () => state.tutor?.openForWork(work.id), `Ask Tutor about ${work.title}`));
  }
  actions.append(button("button button-quiet", state.favorites.has(work.id) ? "♥ Favorited" : "♡ Favorite", () => toggleFavorite(work)));
  if (work.editableMetadata === true) actions.append(button("button button-quiet", "Edit details", () => openWorkMetadataEditor(work)));
  const finderAction = button("button button-quiet", FILE_MANAGER_LABEL, () => revealFile(firstFile), `Reveal in ${FILE_MANAGER_LABEL}`);
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
    details.append(node("strong", "", file.title), node("small", "", `${file.format} · ${humanBytes(file.bytes)} · ${file.exists ? file.path : "Missing from this computer"}`));
    const fileActions = node("div", "file-actions");
    if (file.exists) {
      fileActions.append(button("mini-action mini-action-primary", isAudioPlayable(file) ? "Listen" : isBrowserReadable(file) ? "Read here" : "Open", () => openFile(work, file)));
      if (isBrowserReadable(file) || isAudioPlayable(file)) fileActions.append(button("mini-action", COMPUTER_LABEL, () => openOnMac(work, file), `Open ${file.title} on this computer`));
      fileActions.append(button("mini-action", FILE_MANAGER_LABEL, () => revealFile(file), `Reveal ${file.title} in ${FILE_MANAGER_LABEL}`));
    } else {
      fileActions.append(node("span", "missing-label", "Not on this computer"));
    }
    row.append(details, fileActions);
    fileList.append(row);
  });
  filesSection.append(fileHeading, fileList);
  body.append(filesSection);

  const metadataSection = node("section", "drawer-section");
  const metadataHeading = node("div", "drawer-section-title");
  metadataHeading.append(node("h3", "", "Library information"));
  const metadataGrid = node("div", "metadata-grid");
  [
    ["Subjects", subjectSummary(work)],
    ["Topic", work.topic],
    ["Access", work.access],
    ["Size", humanBytes(work.totalBytes)],
    ["Local path", work.localPath],
    ["Availability", work.isAvailable ? "On this computer" : `${work.availableFileCount}/${work.fileCount} files on this computer`],
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
  state.topic = "all";
  elements.search.value = "";
  syncNavigation();
  renderSubjectChips();
  renderTopicChips();
  renderCards();
}

function setNativeAppMenuOpen(open) {
  if (elements.nativeAppMenu.hidden) return;
  elements.appActionsMenu.hidden = !open;
  elements.appMoreButton.setAttribute("aria-expanded", String(open));
  elements.nativeAppMenu.classList.toggle("is-open", open);
  if (open) requestAnimationFrame(() => elements.appCheckUpdatesButton.focus());
}

async function initializeNativeAppMenu() {
  if (typeof window.csLibraryNativeCall !== "function") return;
  try {
    const info = await window.csLibraryNativeCall("app.info");
    if (!info || !["macOS", "windows"].includes(info.platform) || typeof info.version !== "string") return;
    // Builds from before the shared Windows menu shipped did not include a
    // capability list. Preserve their existing macOS Update and Move Library
    // actions while keeping every additional desktop action opt-in.
    const legacyCapabilities = info.platform === "macOS"
      ? ["app.checkForUpdates", "app.moveLibrary"]
      : [];
    const capabilities = new Set(
      Array.isArray(info.capabilities) ? info.capabilities : legacyCapabilities,
    );
    const actionButtons = new Map([
      ["app.checkForUpdates", elements.appCheckUpdatesButton],
      ["app.moveLibrary", elements.appMoveLibraryButton],
      ["app.disconnectLibrary", elements.appDisconnectLibraryButton],
      ["app.reconnectLibrary", elements.appReconnectLibraryButton],
      ["app.openLibraryFolder", elements.appOpenLibraryButton],
      ["app.chooseLibrary", elements.appChooseLibraryButton],
      ["app.reload", elements.appReloadButton],
    ]);
    actionButtons.forEach((button, action) => { button.hidden = !capabilities.has(action); });
    const hasLibraryActions = [
      elements.appOpenLibraryButton,
      elements.appChooseLibraryButton,
      elements.appReloadButton,
    ].some(button => !button.hidden);
    elements.appLibraryActionsDivider.hidden = !hasLibraryActions;
    elements.appPlatformLabel.textContent = info.platform === "windows"
      ? "Lattice for Windows"
      : "Lattice for macOS";
    elements.appVersionLabel.textContent = `Version ${info.version}`;
    elements.nativeAppMenu.hidden = ![...actionButtons.values()].some(button => !button.hidden);
    applyNativeAppStatus(info.status);
  } catch {
    // A regular browser has no native desktop actions to expose.
  }
}

function applyNativeAppStatus(status) {
  if (!status || typeof status !== "object") return;
  if (typeof status.version === "string") {
    elements.appVersionLabel.textContent = `Version ${status.version}`;
  }
  const busy = status.busy === true;
  elements.appCheckUpdatesButton.disabled = busy;
  if (typeof status.libraryActionsEnabled === "boolean") {
    elements.appMoveLibraryButton.disabled = !status.libraryActionsEnabled || busy;
    elements.appDisconnectLibraryButton.disabled = !status.libraryActionsEnabled || busy;
    elements.appReconnectLibraryButton.disabled = !status.libraryActionsEnabled || busy;
    elements.appOpenLibraryButton.disabled = !status.libraryActionsEnabled;
    elements.appChooseLibraryButton.disabled = !status.libraryActionsEnabled;
  }
  if (typeof status.browserControlsEnabled === "boolean") {
    elements.appReloadButton.disabled = !status.browserControlsEnabled;
  }
  if (busy && typeof status.text === "string" && status.text) {
    elements.appCheckUpdatesTitle.textContent = status.text;
    elements.appCheckUpdatesDetail.textContent = status.progressVisible
      ? (status.progressIndeterminate ? "Working securely…" : `${Math.round(Number(status.progress) || 0)}% complete`)
      : "Working securely…";
    return;
  }
  elements.appCheckUpdatesTitle.textContent = "Check for updates";
  elements.appCheckUpdatesDetail.textContent = status.tone === "updateAvailable" && status.text
    ? status.text
    : "Look for a newer release";
}

async function invokeNativeAppAction(action) {
  setNativeAppMenuOpen(false);
  try {
    await window.csLibraryNativeCall(action);
  } catch (error) {
    announce(error?.message || "That Lattice action is unavailable.", true);
  }
}

function bindNativeAppMenuEvents() {
  elements.appMoreButton.addEventListener("click", (event) => {
    event.stopPropagation();
    setNativeAppMenuOpen(elements.appActionsMenu.hidden);
  });
  elements.appActionsMenu.addEventListener("click", event => event.stopPropagation());
  elements.appCheckUpdatesButton.addEventListener("click", () => {
    void invokeNativeAppAction("app.checkForUpdates");
  });
  elements.appMoveLibraryButton.addEventListener("click", () => {
    void invokeNativeAppAction("app.moveLibrary");
  });
  elements.appDisconnectLibraryButton.addEventListener("click", () => {
    void invokeNativeAppAction("app.disconnectLibrary");
  });
  elements.appReconnectLibraryButton.addEventListener("click", () => {
    void invokeNativeAppAction("app.reconnectLibrary");
  });
  elements.appOpenLibraryButton.addEventListener("click", () => {
    void invokeNativeAppAction("app.openLibraryFolder");
  });
  elements.appChooseLibraryButton.addEventListener("click", () => {
    void invokeNativeAppAction("app.chooseLibrary");
  });
  elements.appReloadButton.addEventListener("click", () => {
    void invokeNativeAppAction("app.reload");
  });
  window.addEventListener("lattice-native-status", event => applyNativeAppStatus(event.detail));
  document.addEventListener("click", (event) => {
    if (!elements.nativeAppMenu.contains(event.target)) setNativeAppMenuOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || elements.appActionsMenu.hidden) return;
    setNativeAppMenuOpen(false);
    elements.appMoreButton.focus();
  });
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  elements.theme.textContent = theme === "dark" ? "☼" : "◒";
  elements.theme.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`);
  const meta = $("meta[name='theme-color']");
  if (meta) meta.content = theme === "dark" ? "#171915" : "#f2eee5";
  sendPdfReaderMessage("theme", { theme });
}

function initializeTheme() {
  const saved = readStorage(STORAGE.theme, null);
  const theme = saved || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(theme);
}

function bindEvents() {
  bindImportEvents();
  bindNativeAppMenuEvents();
  window.addEventListener("message", handlePdfReaderMessage);
  window.addEventListener("message", (event) => {
    if (
      event.origin !== window.location.origin
      || event.source !== elements.epubFrame.contentWindow
      || state.readerMode !== "epub"
      || event.data?.type !== "cs-library-reader-selection"
    ) return;
    state.readerDesk?.setSelection(event.data.text);
  });
  window.addEventListener("cs-library-reader-restore", event => {
    const saved = event.detail;
    if (!saved || saved.path !== state.readerPath) return;
    state.nativeReaderRestore = saved;
    const locator = saved.locator;
    if (state.readerMode === "pdf" && locator?.type === "pdf") {
      sendPdfReaderMessage("navigate", { page: Math.max(1, Math.trunc(Number(locator.page)) || 1) });
      return;
    }
    if (state.readerMode !== "epub" || !state.epubPackage || locator?.type !== "epub") return;
    let index = state.epubPackage.chapters.findIndex(chapter => chapter.entry === locator.entry);
    if (index < 0) index = clamp(Number(locator.index) || 0, 0, state.epubPackage.chapters.length - 1);
    navigateEpub(index, { ratio: clamp(Number(locator.ratio) || 0, 0, 1) });
  });
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => setView(item.dataset.view)));
  $$("[data-document]").forEach((item) => item.addEventListener("click", () => openDocument(item.dataset.document, item.dataset.title)));
  elements.search.addEventListener("input", () => {
    state.query = elements.search.value;
    if (state.view === "videos") state.videoLibrary?.setQuery(state.query);
    else renderCards();
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
    if (state.view === "videos") {
      state.videoLibrary?.randomLecture();
      return;
    }
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
  elements.readerAudio.addEventListener("click", () => state.audioPlayer?.openLibrary());
  const openReaderTutor = () => {
    if (state.readerWorkId) state.tutor?.peekForWork(state.readerWorkId);
  };
  elements.readerTutor.addEventListener("click", openReaderTutor);
  elements.readerTutorPeek.addEventListener("click", openReaderTutor);
  elements.readerFocus.addEventListener("click", toggleActiveReaderFocus);
  elements.epubFocusExit.addEventListener("click", () => setEpubFocus(false));
  elements.readerPdf.addEventListener("load", () => {
    if (state.readerMode === "pdf" && document.body.classList.contains("reader-open")) {
      elements.readerLoading.hidden = true;
      initializePdfReaderFrame();
    }
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
    if (
      state.readerMode === "pdf"
      && document.body.classList.contains("reader-open")
      && !event.ctrlKey
      && !event.metaKey
      && !event.altKey
      && (event.key === "ArrowLeft" || event.key === "ArrowRight")
    ) {
      const tag = event.target?.tagName?.toLowerCase();
      if (!["input", "textarea", "select"].includes(tag) && !event.target?.isContentEditable) {
        event.preventDefault();
        sendPdfReaderMessage("shortcut", { key: event.key });
        return;
      }
    }
    if (state.readerMode === "epub" && document.body.classList.contains("reader-open") && event.key !== "Escape") handleEpubKeydown(event);
    if (event.key === "/" && !document.body.classList.contains("reader-open") && !state.videoLibrary?.isPlayerOpen && document.activeElement !== elements.search) {
      event.preventDefault();
      elements.search.focus();
    }
    if (event.key === "Escape") {
      if (document.body.classList.contains("import-open")) {
        closeImportDialog();
        return;
      }
      if (state.videoLibrary?.handleEscape()) return;
      if (state.readerMode === "epub" && (elements.epubReader.classList.contains("toc-open") || elements.epubReader.classList.contains("settings-open"))) closeEpubPanels();
      else if (state.readerMode === "epub" && state.epubFocused) setEpubFocus(false);
      else if (document.body.classList.contains("reader-open")) closeReader();
      else if (document.body.classList.contains("drawer-open")) closeDrawer();
      else closeMobileMenu();
    }
  });
  window.addEventListener("beforeunload", () => {
    state.eventSource?.close();
    state.videoLibrary?.closePlayer();
    state.tutor?.destroy();
  });
}

function initializeLibrary(payload) {
  const readerPath = state.readerPath;
  state.library = normalizeLibraryPayload(payload);
  payload = state.library;
  state.token = payload.actionToken;
  state.revision = Number(payload.revision || state.revision || 0);
  state.workById = new Map(payload.works.map((work) => [work.id, work]));
  state.tutor?.setLibrary(payload);
  state.audioPlayer?.setLibrary(payload.materials);
  elements.workStat.textContent = payload.stats.works;
  elements.artifactStat.textContent = payload.stats.artifacts;
  elements.sizeStat.textContent = humanBytes(payload.stats.bytes);
  elements.integrityStat.textContent = `${payload.stats.present}/${payload.stats.indexedArtifacts || payload.stats.artifacts}`;
  renderNavigationCounts();
  renderMaterials();
  renderSubjects();
  renderShelves();
  renderSubjectChips();
  renderTopicChips();
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
  renderViewMode();
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
  if (state.refreshing) {
    const pending = state.refreshPending;
    state.refreshPending = {
      change: change || pending?.change || null,
      quiet: quiet && (pending?.quiet ?? true),
    };
    return;
  }
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
    const pending = state.refreshPending;
    state.refreshPending = null;
    if (pending) void refreshLibrary(pending.change, { quiet: pending.quiet });
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

async function insertTutorArtifact(artifact) {
  // Insert into the most recent notebook; create one if none exists.
  const privateHeaders = { "X-Lattice-Private-Token": state.privateToken };
  const listResponse = await fetch("/api/study/notebooks", {
    cache: "no-store",
    headers: privateHeaders,
  });
  if (!listResponse.ok) throw new Error("Study Lab is unavailable");
  const list = await listResponse.json();
  let notebook = list.notebooks[0];
  const token = state.token;
  if (!notebook) {
    const createResponse = await fetch("/api/study/notebooks", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Library-Token": token,
        ...privateHeaders,
      },
      body: JSON.stringify({ title: `From Tutor — ${new Date().toLocaleDateString()}` }),
    });
    if (!createResponse.ok) throw new Error("Could not create a notebook");
    notebook = (await createResponse.json()).notebook;
  }
  const insertResponse = await fetch(
    `/api/study/notebook/${encodeURIComponent(notebook.id)}/cells`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Library-Token": token,
        ...privateHeaders,
      },
      body: JSON.stringify({
        kind: artifact.kind,
        source: artifact.source,
        baseUpdatedAt: notebook.updatedAt,
      }),
    },
  );
  if (!insertResponse.ok) {
    const payload = await insertResponse.json().catch(() => ({}));
    throw new Error(payload.error || "Insert failed");
  }
  announce(`Inserted into "${notebook.title}"`);
}

async function start() {
  initializeTheme();
  state.audioPlayer = window.LatticeAudioPlayer?.create({
    announce,
    onAddAudio: () => openAudioImportDialog({ chooseImmediately: true }),
  }) || null;
  initializeReaderDesk();
  state.tutor = window.LatticeTutor?.create({
    announce,
    onOpenCitation: openTutorCitation,
    onInsertArtifact: insertTutorArtifact,
    onInsertError: (error) => announce(error.message || "Insert failed", true),
  }) || null;
  state.videoLibrary = window.CSVideoLibrary?.create({
    announce,
    onCatalog: (catalog) => {
      state.videoCatalog = catalog;
      state.tutor?.setVideoCatalog(catalog);
      if (state.view === "videos") renderViewMode();
    },
    onAskTutor: (course) => state.tutor?.peekForCourse(course.id),
    onCloseTutor: () => state.tutor?.closeContext("video"),
    onClearQuery: () => {
      state.query = "";
      elements.search.value = "";
    },
    openSources: () => openDocument(
      "notes/provenance/free-video-lectures-2026-08-21.md",
      "Video lecture sources",
    ),
  }) || null;
  bindEvents();
  await initializeNativeAppMenu();
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

const studyLabButton = document.getElementById("studyLabButton");
if (studyLabButton) {
  studyLabButton.addEventListener("click", () => {
    window.location.href = "/study-lab.html";
  });
}

start();
