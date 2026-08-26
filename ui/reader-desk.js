"use strict";

(() => {
  const STORAGE_KEY = "cs-library:reader-desk:v1";
  const LEGACY_EPUB_BOOKMARKS_KEY = "cs-library:epub-bookmarks";
  const LEGACY_NATIVE_NOTES_KEY = "cs-library:native-reader-notes";
  const STORE_VERSION = 1;
  const MAX_DOCUMENTS = 250;
  const MAX_NOTES = 500;
  const MAX_BOOKMARKS = 500;

  const clamp = (value, minimum = 0, maximum = 1) => Math.min(maximum, Math.max(minimum, Number(value) || 0));
  const safeText = (value, limit = 100000) => String(value ?? "").replace(/\u0000/g, "").slice(0, limit);

  function normalizeDescriptor(value) {
    if (!value || typeof value !== "object") return null;
    const path = safeText(value.path, 4000).trim();
    if (
      !/^(books|papers|lectures)\/.+\.(pdf|epub|txt)$/i.test(path)
      || path.includes("\\")
      || path.split("/").some((part) => !part || part === "." || part === "..")
    ) return null;
    const format = safeText(value.format || path.split(".").at(-1), 20).trim().toLowerCase();
    return {
      path,
      workId: safeText(value.workId, 1000).trim(),
      sha256: /^[a-f0-9]{64}$/i.test(String(value.sha256 || "")) ? String(value.sha256).toLowerCase() : "",
      title: safeText(value.title || path.split("/").at(-1), 2000).trim(),
      workTitle: safeText(value.workTitle || value.title || path.split("/").at(-1), 2000).trim(),
      format,
    };
  }

  function normalizeLocator(value) {
    if (!value || typeof value !== "object") return null;
    if (value.type === "pdf") {
      return {
        type: "pdf",
        page: Math.max(1, Math.trunc(Number(value.page)) || 1),
      };
    }
    if (value.type === "epub") {
      const entry = safeText(value.entry, 4000).trim();
      if (!entry) return null;
      return {
        type: "epub",
        entry,
        index: Math.max(0, Math.trunc(Number(value.index)) || 0),
        ratio: clamp(value.ratio),
        pageIndex: Math.max(0, Math.trunc(Number(value.pageIndex)) || 0),
        pageCount: Math.max(1, Math.trunc(Number(value.pageCount)) || 1),
      };
    }
    return null;
  }

  function locatorKey(value) {
    const locator = normalizeLocator(value);
    if (!locator) return "";
    if (locator.type === "pdf") return `pdf:${locator.page}`;
    return `epub:${locator.entry}:${locator.ratio.toFixed(4)}`;
  }

  function documentKey(descriptor) {
    const normalized = normalizeDescriptor(descriptor);
    if (!normalized) return "";
    return normalized.sha256 ? `sha256:${normalized.sha256}` : `path:${normalized.path}`;
  }

  function buildStudyContext(descriptor, mode = "lab", compact = false) {
    const normalized = normalizeDescriptor(descriptor);
    if (!normalized) return null;
    return {
      workPath: normalized.path,
      workTitle: normalized.workTitle,
      mode: mode === "notes" ? "notes" : "lab",
      compact: Boolean(compact),
    };
  }

  function normalizeLegacyMigrations(value, documents = {}) {
    const epubBookmarksByPath = Object.entries(
      value?.epubBookmarksByPath && typeof value.epubBookmarksByPath === "object"
        ? value.epubBookmarksByPath
        : {},
    ).flatMap(([path, migrated]) => {
      const descriptor = migrated === true ? normalizeDescriptor({ path, format: "epub" }) : null;
      return descriptor?.format === "epub" && /\.epub$/i.test(descriptor.path) ? [[descriptor.path, true]] : [];
    });
    const nativeNotesByTitle = Object.entries(
      value?.nativeNotesByTitle && typeof value.nativeNotesByTitle === "object"
        ? value.nativeNotesByTitle
        : {},
    ).flatMap(([title, path]) => {
      const safeTitle = safeText(title, 2000).trim();
      const descriptor = normalizeDescriptor({ path, title: safeTitle, format: "epub" });
      return safeTitle && descriptor?.format === "epub" && /\.epub$/i.test(descriptor.path)
        ? [[safeTitle, descriptor.path]]
        : [];
    });

    const normalized = {
      epubBookmarksByPath: Object.fromEntries(epubBookmarksByPath),
      nativeNotesByTitle: Object.fromEntries(nativeNotesByTitle),
    };
    for (const item of Object.values(documents)) {
      const descriptor = normalizeDescriptor(item?.descriptor);
      if (descriptor?.format !== "epub" || !/\.epub$/i.test(descriptor.path)) continue;
      if (item?.migrations?.epubBookmarks) normalized.epubBookmarksByPath[descriptor.path] = true;
      if (
        item?.migrations?.nativeNotes
        && !Object.hasOwn(normalized.nativeNotesByTitle, descriptor.title)
      ) normalized.nativeNotesByTitle[descriptor.title] = descriptor.path;
    }
    return normalized;
  }

  function normalizeStore(value) {
    const documents = value?.documents && typeof value.documents === "object" && !Array.isArray(value.documents)
      ? value.documents
      : {};
    const retained = Object.entries(documents)
      .filter(([, item]) => item && typeof item === "object")
      .sort(([, left], [, right]) => Number(right.updatedAt || 0) - Number(left.updatedAt || 0))
      .slice(0, MAX_DOCUMENTS);
    const retainedDocuments = Object.fromEntries(retained);
    return {
      version: STORE_VERSION,
      documents: retainedDocuments,
      legacyMigrations: normalizeLegacyMigrations(value?.legacyMigrations, retainedDocuments),
    };
  }

  function claimLegacyNativeNotesMigration(store, descriptor) {
    const normalized = normalizeDescriptor(descriptor);
    if (
      normalized?.format !== "epub"
      || !/\.epub$/i.test(normalized.path)
      || !store
      || typeof store !== "object"
    ) return false;
    store.legacyMigrations = normalizeLegacyMigrations(store.legacyMigrations);
    const ledger = store.legacyMigrations.nativeNotesByTitle;
    if (Object.hasOwn(ledger, normalized.title)) return false;
    ledger[normalized.title] = normalized.path;
    return true;
  }

  function createId(prefix) {
    const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `${prefix}-${random}`;
  }

  function parseLocator(value) {
    if (value && typeof value === "object") return normalizeLocator(value);
    if (typeof value !== "string") return null;
    try { return normalizeLocator(JSON.parse(value)); } catch { return null; }
  }

  function formatLocator(locator, label = "") {
    const normalized = normalizeLocator(locator);
    if (!normalized) return label || "Current reading position";
    if (normalized.type === "pdf") return `Page ${normalized.page}`;
    const progress = Math.round(normalized.ratio * 100);
    return label ? `${label} · ${progress}%` : `Chapter position · ${progress}%`;
  }

  function resolveSavedNoteLocation({
    existing = null,
    selectionLocator = null,
    selectionLabel = "",
    currentLocator = null,
    currentLabel = "",
  } = {}) {
    if (existing) {
      return {
        locator: normalizeLocator(existing.locator),
        label: safeText(existing.label, 500).trim(),
      };
    }
    const captured = normalizeLocator(selectionLocator);
    return {
      locator: captured || normalizeLocator(currentLocator),
      label: safeText(captured ? selectionLabel : currentLabel, 500).trim(),
    };
  }

  const exported = {
    STORAGE_KEY,
    buildStudyContext,
    documentKey,
    locatorKey,
    normalizeDescriptor,
    normalizeLegacyMigrations,
    normalizeLocator,
    normalizeStore,
    claimLegacyNativeNotesMigration,
    resolveSavedNoteLocation,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  if (typeof window === "undefined" || typeof document === "undefined") return;

  window.__LATTICE_SHARED_READER_DESK__ = true;

  function create(options = {}) {
    const root = options.root || document.getElementById("readerDesk");
    const shell = options.shell || document.getElementById("readerShell");
    const toggle = options.toggle || document.getElementById("readerDeskButton");
    if (!root || !shell || !toggle) return null;

    const elements = {
      addBookmark: root.querySelector("#readerDeskAddBookmark"),
      bookmarkCount: root.querySelector("#readerDeskBookmarkCount"),
      bookmarkList: root.querySelector("#readerDeskBookmarkList"),
      close: root.querySelector("#readerDeskClose"),
      draft: root.querySelector("#readerDeskDraft"),
      draftStatus: root.querySelector("#readerDeskDraftStatus"),
      labFrame: root.querySelector("#readerStudyLab"),
      labStatus: root.querySelector("#readerDeskLabStatus"),
      location: root.querySelector("#readerDeskLocation"),
      noteCount: root.querySelector("#readerDeskNoteCount"),
      noteList: root.querySelector("#readerDeskNoteList"),
      noteSave: root.querySelector("#readerDeskNoteSave"),
      quote: root.querySelector("#readerDeskQuote"),
      quoteClear: root.querySelector("#readerDeskQuoteClear"),
      scrim: document.getElementById("readerDeskScrim"),
      tabs: [...root.querySelectorAll("[data-reader-desk-tab]")],
      views: [...root.querySelectorAll("[data-reader-desk-view]")],
      title: root.querySelector("#readerDeskTitle"),
    };

    root.dataset.sharedReaderDesk = "true";
    let store = readStore();
    let active = null;
    let activeKey = "";
    let currentLocator = null;
    let currentLocationLabel = "";
    let selection = "";
    let selectionLocator = null;
    let selectionLocationLabel = "";
    let editingId = "";
    let activeTab = "notes";
    let labLoaded = false;
    let labReady = false;
    const supportsInert = "inert" in root;
    const fallbackTabIndexes = new Map();
    const focusableSelector = [
      "a[href]",
      "button",
      "input",
      "select",
      "textarea",
      "iframe",
      "summary",
      "[contenteditable]:not([contenteditable='false'])",
      "[tabindex]",
    ].join(",");

    function setDeskInteractive(interactive) {
      root.setAttribute("aria-hidden", String(!interactive));
      if (interactive) root.removeAttribute("inert");
      else root.setAttribute("inert", "");
      if (supportsInert) {
        root.inert = !interactive;
        return;
      }
      if (!interactive) {
        for (const element of root.querySelectorAll(focusableSelector)) {
          if (!fallbackTabIndexes.has(element)) fallbackTabIndexes.set(element, element.getAttribute("tabindex"));
          element.setAttribute("tabindex", "-1");
        }
        return;
      }
      for (const [element, tabIndex] of fallbackTabIndexes) {
        if (tabIndex === null) element.removeAttribute("tabindex");
        else element.setAttribute("tabindex", tabIndex);
      }
      fallbackTabIndexes.clear();
    }

    const fallbackInertObserver = supportsInert ? null : new MutationObserver(() => {
      if (root.getAttribute("aria-hidden") === "true") setDeskInteractive(false);
    });
    fallbackInertObserver?.observe(root, { childList: true, subtree: true });

    function readStore() {
      try { return normalizeStore(JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}")); }
      catch { return normalizeStore({}); }
    }

    function writeStore() {
      if (!activeKey || !store.documents[activeKey]) return false;
      store.documents[activeKey].updatedAt = Date.now();
      store = normalizeStore(store);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
        return true;
      } catch {
        setDraftStatus("Local storage is full. Copy this draft before closing.", true);
        return false;
      }
    }

    function currentDocument() {
      return activeKey ? store.documents[activeKey] : null;
    }

    function ensureDocument(descriptor) {
      const key = documentKey(descriptor);
      if (!key) return "";
      if (!store.documents[key]) {
        store.documents[key] = {
          descriptor,
          bookmarks: [],
          notes: [],
          draft: "",
          migrations: {},
          updatedAt: Date.now(),
        };
      }
      const item = store.documents[key];
      item.descriptor = descriptor;
      item.bookmarks = Array.isArray(item.bookmarks) ? item.bookmarks : [];
      item.notes = Array.isArray(item.notes) ? item.notes : [];
      item.draft = safeText(item.draft, 100000);
      item.migrations = item.migrations && typeof item.migrations === "object" ? item.migrations : {};
      return key;
    }

    function migrateLegacy() {
      const item = currentDocument();
      if (!item || !active) return;
      const migrationLedger = store.legacyMigrations;
      if (
        active.format === "epub"
        && /\.epub$/i.test(active.path)
        && !Object.hasOwn(migrationLedger.epubBookmarksByPath, active.path)
      ) {
        try {
          const legacy = JSON.parse(localStorage.getItem(LEGACY_EPUB_BOOKMARKS_KEY) || "{}");
          for (const bookmark of Array.isArray(legacy?.[active.path]) ? legacy[active.path] : []) {
            const locator = normalizeLocator({ type: "epub", ...bookmark });
            if (!locator || item.bookmarks.some((saved) => locatorKey(saved.locator) === locatorKey(locator))) continue;
            item.bookmarks.push({
              id: createId("bookmark"),
              locator,
              label: safeText(bookmark.label, 500).trim() || "Saved position",
              createdAt: Number(bookmark.createdAt) || Date.now(),
            });
          }
          migrationLedger.epubBookmarksByPath[active.path] = true;
        } catch { /* Malformed legacy data is left untouched. */ }
      }
      if (
        active.format === "epub"
        && /\.epub$/i.test(active.path)
        && !Object.hasOwn(migrationLedger.nativeNotesByTitle, active.title)
      ) {
        try {
          const legacy = JSON.parse(localStorage.getItem(LEGACY_NATIVE_NOTES_KEY) || "{}");
          for (const note of Array.isArray(legacy?.[active.title]) ? legacy[active.title] : []) {
            const id = safeText(note.id, 2000).trim() || createId("note");
            if (item.notes.some((saved) => saved.id === id)) continue;
            item.notes.push({
              id,
              body: safeText(note.note, 100000).trim(),
              quote: safeText(note.quote, 20000).trim(),
              locator: normalizeLocator(note.locator) || null,
              label: safeText(note.chapter, 500).trim(),
              createdAt: Number(note.createdAt) || Date.now(),
              updatedAt: Number(note.createdAt) || Date.now(),
            });
          }
          claimLegacyNativeNotesMigration(store, active);
        } catch { /* Malformed legacy data is left untouched. */ }
      }
      item.bookmarks = item.bookmarks.slice(-MAX_BOOKMARKS);
      item.notes = item.notes.slice(-MAX_NOTES);
      writeStore();
    }

    function setDraftStatus(message, error = false) {
      if (!elements.draftStatus) return;
      elements.draftStatus.textContent = message;
      elements.draftStatus.dataset.error = String(Boolean(error));
    }

    function renderMarkdown(target, source) {
      target.replaceChildren();
      const text = safeText(source, 100000).trim();
      if (!text) return;
      const fragment = document.createDocumentFragment();
      let code = null;
      let list = null;
      for (const rawLine of text.split(/\r?\n/)) {
        if (/^```/.test(rawLine)) {
          if (code) { fragment.append(code); code = null; }
          else { code = document.createElement("pre"); }
          list = null;
          continue;
        }
        if (code) {
          code.textContent += `${code.textContent ? "\n" : ""}${rawLine}`;
          continue;
        }
        const heading = rawLine.match(/^(#{1,3})\s+(.+)/);
        const bullet = rawLine.match(/^[-*]\s+(.+)/);
        const quote = rawLine.match(/^>\s?(.*)/);
        if (heading) {
          list = null;
          const node = document.createElement(`h${heading[1].length + 2}`);
          node.textContent = heading[2];
          fragment.append(node);
        } else if (bullet) {
          if (!list) { list = document.createElement("ul"); fragment.append(list); }
          const row = document.createElement("li"); row.textContent = bullet[1]; list.append(row);
        } else if (quote) {
          list = null;
          const node = document.createElement("blockquote"); node.textContent = quote[1]; fragment.append(node);
        } else if (rawLine.trim()) {
          list = null;
          const node = document.createElement("p"); node.textContent = rawLine; fragment.append(node);
        } else {
          list = null;
        }
      }
      if (code) fragment.append(code);
      target.append(fragment);
    }

    function navigate(locator) {
      const normalized = normalizeLocator(locator);
      if (!normalized) return;
      options.onNavigate?.(normalized);
      if (isCompact()) close();
    }

    function renderNotes() {
      const item = currentDocument();
      const notes = [...(item?.notes || [])].sort((left, right) => Number(right.updatedAt || 0) - Number(left.updatedAt || 0));
      elements.noteCount.textContent = String(notes.length);
      elements.noteList.replaceChildren();
      if (!notes.length) {
        const empty = document.createElement("div");
        empty.className = "reader-desk-empty";
        empty.innerHTML = "<strong>Your margin is clear.</strong><span>Capture a thought without leaving the page. Markdown stays local to this Lattice profile.</span>";
        elements.noteList.append(empty);
        return;
      }
      for (const note of notes) {
        const card = document.createElement("article");
        card.className = "reader-note-card";
        if (note.quote) {
          const quote = document.createElement("blockquote");
          quote.textContent = note.quote;
          card.append(quote);
        }
        const body = document.createElement("div");
        body.className = "reader-note-body";
        renderMarkdown(body, note.body);
        card.append(body);
        const footer = document.createElement("footer");
        const location = document.createElement("button");
        location.type = "button";
        location.className = "reader-note-location";
        location.textContent = formatLocator(note.locator, note.label);
        location.disabled = !normalizeLocator(note.locator);
        location.addEventListener("click", () => navigate(note.locator));
        const actions = document.createElement("span");
        const edit = document.createElement("button");
        edit.type = "button";
        edit.textContent = "Edit";
        edit.addEventListener("click", () => editNote(note));
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Delete";
        remove.addEventListener("click", () => deleteNote(note.id));
        actions.append(edit, remove);
        footer.append(location, actions);
        card.append(footer);
        elements.noteList.append(card);
      }
    }

    function renderBookmarks() {
      const item = currentDocument();
      const bookmarks = [...(item?.bookmarks || [])].sort((left, right) => Number(right.createdAt || 0) - Number(left.createdAt || 0));
      elements.bookmarkCount.textContent = String(bookmarks.length);
      elements.bookmarkList.replaceChildren();
      if (!bookmarks.length) {
        const empty = document.createElement("div");
        empty.className = "reader-desk-empty";
        empty.innerHTML = "<strong>No saved places yet.</strong><span>Bookmarks remember the exact PDF page or position within an EPUB chapter.</span>";
        elements.bookmarkList.append(empty);
        return;
      }
      for (const bookmark of bookmarks) {
        const row = document.createElement("article");
        row.className = "reader-bookmark-card";
        const go = document.createElement("button");
        go.type = "button";
        go.className = "reader-bookmark-go";
        const marker = document.createElement("span");
        marker.textContent = "◆";
        const copy = document.createElement("span");
        const title = document.createElement("strong");
        title.textContent = bookmark.label || formatLocator(bookmark.locator);
        const location = document.createElement("small");
        location.textContent = formatLocator(bookmark.locator);
        copy.append(title, location);
        go.append(marker, copy);
        go.addEventListener("click", () => navigate(bookmark.locator));
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "reader-bookmark-delete";
        remove.setAttribute("aria-label", `Delete ${title.textContent}`);
        remove.textContent = "×";
        remove.addEventListener("click", () => deleteBookmark(bookmark.id));
        row.append(go, remove);
        elements.bookmarkList.append(row);
      }
    }

    function renderSelection() {
      elements.quote.textContent = selection;
      elements.quote.closest(".reader-note-quote")?.classList.toggle("has-quote", Boolean(selection));
    }

    function render() {
      const item = currentDocument();
      elements.title.textContent = active?.workTitle || active?.title || "Reading Desk";
      elements.draft.value = item?.draft || "";
      elements.location.textContent = formatLocator(currentLocator, currentLocationLabel);
      renderSelection();
      renderNotes();
      renderBookmarks();
      updateCurrentBookmarkState();
    }

    function editNote(note) {
      editingId = note.id;
      selection = safeText(note.quote, 20000).trim();
      selectionLocator = normalizeLocator(note.locator);
      selectionLocationLabel = safeText(note.label, 500).trim();
      elements.draft.value = safeText(note.body, 100000);
      elements.noteSave.textContent = "Update note";
      renderSelection();
      setTab("notes");
      open("notes");
      elements.draft.focus();
    }

    function resetComposer() {
      editingId = "";
      selection = "";
      selectionLocator = null;
      selectionLocationLabel = "";
      elements.noteSave.textContent = "Save note";
      renderSelection();
    }

    function saveNote() {
      const item = currentDocument();
      if (!item) return false;
      const body = safeText(elements.draft.value, 100000).trim();
      if (!body && !selection) {
        setDraftStatus("Write a thought or select a passage first.", true);
        elements.draft.focus();
        return false;
      }
      const now = Date.now();
      const existing = editingId ? item.notes.find((note) => note.id === editingId) : null;
      const savedLocation = resolveSavedNoteLocation({
        existing,
        selectionLocator,
        selectionLabel: selectionLocationLabel,
        currentLocator,
        currentLabel: currentLocationLabel,
      });
      const note = {
        id: existing?.id || createId("note"),
        body,
        quote: selection,
        locator: savedLocation.locator,
        label: savedLocation.label,
        createdAt: existing?.createdAt || now,
        updatedAt: now,
      };
      if (existing) Object.assign(existing, note);
      else item.notes.push(note);
      item.notes = item.notes.slice(-MAX_NOTES);
      item.draft = "";
      if (!writeStore()) return false;
      elements.draft.value = "";
      resetComposer();
      renderNotes();
      setDraftStatus(existing ? "Note updated locally." : "Note saved locally.");
      window.dispatchEvent(new CustomEvent("cs-library-reader-save-annotation", { detail: {
        id: note.id,
        locator: note.locator || {},
        quote: note.quote,
        note: note.body,
        color: "yellow",
        createdAt: note.createdAt / 1000,
      } }));
      return true;
    }

    function deleteNote(id) {
      const item = currentDocument();
      if (!item) return false;
      const before = item.notes.length;
      item.notes = item.notes.filter((note) => note.id !== id);
      if (item.notes.length === before) return false;
      writeStore();
      if (editingId === id) resetComposer();
      renderNotes();
      window.dispatchEvent(new CustomEvent("cs-library-reader-delete-annotation", { detail: { id } }));
      return true;
    }

    function addBookmark() {
      const item = currentDocument();
      const locator = normalizeLocator(currentLocator);
      if (!item || !locator) return null;
      const key = locatorKey(locator);
      const existing = item.bookmarks.find((bookmark) => locatorKey(bookmark.locator) === key);
      if (existing) return existing;
      const bookmark = {
        id: createId("bookmark"),
        locator,
        label: currentLocationLabel || formatLocator(locator),
        createdAt: Date.now(),
      };
      item.bookmarks.push(bookmark);
      item.bookmarks = item.bookmarks.slice(-MAX_BOOKMARKS);
      writeStore();
      renderBookmarks();
      updateCurrentBookmarkState();
      window.dispatchEvent(new CustomEvent("cs-library-reader-bookmark-toggle", { detail: {
        bookmarked: true,
        id: bookmark.id,
        locator: bookmark.locator,
        label: bookmark.label,
        createdAt: bookmark.createdAt / 1000,
      } }));
      return bookmark;
    }

    function deleteBookmark(id) {
      const item = currentDocument();
      if (!item) return false;
      const bookmark = item.bookmarks.find((saved) => saved.id === id);
      if (!bookmark) return false;
      item.bookmarks = item.bookmarks.filter((saved) => saved.id !== id);
      writeStore();
      renderBookmarks();
      updateCurrentBookmarkState();
      window.dispatchEvent(new CustomEvent("cs-library-reader-bookmark-toggle", { detail: {
        bookmarked: false,
        id: bookmark.id,
        locator: bookmark.locator,
        label: bookmark.label,
      } }));
      return true;
    }

    function toggleCurrentBookmark() {
      const item = currentDocument();
      const key = locatorKey(currentLocator);
      if (!item || !key) return false;
      const existing = item.bookmarks.find((bookmark) => locatorKey(bookmark.locator) === key);
      if (existing) {
        deleteBookmark(existing.id);
        return false;
      }
      addBookmark();
      return true;
    }

    function isCurrentBookmarked() {
      const item = currentDocument();
      const key = locatorKey(currentLocator);
      return Boolean(item && key && item.bookmarks.some((bookmark) => locatorKey(bookmark.locator) === key));
    }

    function updateCurrentBookmarkState() {
      const bookmarked = isCurrentBookmarked();
      elements.addBookmark.classList.toggle("is-bookmarked", bookmarked);
      elements.addBookmark.textContent = bookmarked ? "Remove this bookmark" : "Bookmark this spot";
      options.onBookmarkState?.(bookmarked);
      return bookmarked;
    }

    function setLocation(locator, label = "") {
      currentLocator = normalizeLocator(locator);
      currentLocationLabel = safeText(label, 500).trim();
      elements.location.textContent = formatLocator(currentLocator, currentLocationLabel);
      return updateCurrentBookmarkState();
    }

    function setSelection(value, locator = currentLocator, label = currentLocationLabel) {
      selection = safeText(value, 20000).trim();
      selectionLocator = selection ? normalizeLocator(locator) : null;
      selectionLocationLabel = selection ? safeText(label, 500).trim() : "";
      renderSelection();
      if (selection) setDraftStatus("Passage captured. Add your thought when ready.");
    }

    function setTab(tab) {
      activeTab = ["notes", "lab", "bookmarks"].includes(tab) ? tab : "notes";
      for (const button of elements.tabs) {
        const selected = button.dataset.readerDeskTab === activeTab;
        button.setAttribute("aria-selected", String(selected));
        button.classList.toggle("is-active", selected);
      }
      for (const view of elements.views) view.hidden = view.dataset.readerDeskView !== activeTab;
      if (activeTab === "lab") loadLab();
    }

    function isCompact() {
      return window.matchMedia("(max-width: 1099px)").matches;
    }

    function sendStudyContext() {
      if (!labReady || !elements.labFrame.contentWindow || !active) return;
      const context = buildStudyContext(active, activeTab === "lab" ? "lab" : "notes", isCompact());
      if (!context) return;
      elements.labFrame.contentWindow.postMessage(
        { type: "lattice-study-context", version: 1, context },
        window.location.origin,
      );
    }

    function loadLab() {
      if (!labLoaded) {
        labLoaded = true;
        labReady = false;
        elements.labStatus.textContent = "Opening the full local notebook…";
        elements.labFrame.src = "/study-lab.html";
      } else {
        sendStudyContext();
      }
    }

    function handleStudyMessage(event) {
      if (event.origin !== window.location.origin || event.source !== elements.labFrame.contentWindow) return;
      const message = event.data;
      if (!message || message.version !== 1) return;
      if (message.type === "lattice-study-ready") {
        labReady = true;
        elements.labStatus.textContent = "Linked to this source · saved locally";
        sendStudyContext();
      } else if (message.type === "lattice-study-status") {
        elements.labStatus.textContent = message.dirty
          ? "Saving notebook changes…"
          : message.saved === false ? "Notebook needs attention" : "Notebook saved locally";
      }
    }

    function open(tab = activeTab) {
      setTab(tab);
      root.classList.add("is-open");
      setDeskInteractive(true);
      shell.classList.add("reader-desk-open");
      toggle.setAttribute("aria-expanded", "true");
      toggle.classList.add("is-active");
      elements.scrim?.removeAttribute("hidden");
      window.setTimeout(() => (activeTab === "notes" ? elements.draft : elements.tabs.find((item) => item.dataset.readerDeskTab === activeTab))?.focus(), 0);
      sendStudyContext();
    }

    function close() {
      root.classList.remove("is-open");
      setDeskInteractive(false);
      shell.classList.remove("reader-desk-open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.classList.remove("is-active");
      elements.scrim?.setAttribute("hidden", "");
      if (!toggle.hidden && toggle.getClientRects().length) toggle.focus({ preventScroll: true });
      else options.onClose?.();
    }

    function activate(rawDescriptor) {
      const descriptor = normalizeDescriptor(rawDescriptor);
      if (!descriptor) return false;
      active = descriptor;
      activeKey = ensureDocument(descriptor);
      currentLocator = null;
      currentLocationLabel = "";
      selection = "";
      resetComposer();
      migrateLegacy();
      render();
      sendStudyContext();
      return true;
    }

    function deactivate() {
      close();
      active = null;
      activeKey = "";
      currentLocator = null;
      currentLocationLabel = "";
      selection = "";
      editingId = "";
      selectionLocator = null;
      selectionLocationLabel = "";
      elements.draft.value = "";
      renderSelection();
    }

    function mergeNativeSnapshot(detail) {
      const item = currentDocument();
      if (!item || !active || detail?.path !== active.path) return;
      let changed = false;
      for (const raw of Array.isArray(detail.bookmarks) ? detail.bookmarks : []) {
        const locator = parseLocator(raw.locator);
        if (!locator) continue;
        const id = safeText(raw.id, 2000).trim() || createId("bookmark");
        if (item.bookmarks.some((saved) => saved.id === id || locatorKey(saved.locator) === locatorKey(locator))) continue;
        item.bookmarks.push({ id, locator, label: safeText(raw.label, 500).trim(), createdAt: Number(raw.createdAt) * 1000 || Date.now() });
        changed = true;
      }
      for (const raw of Array.isArray(detail.annotations) ? detail.annotations : []) {
        const id = safeText(raw.id, 2000).trim();
        if (!id) continue;
        const existing = item.notes.find((saved) => saved.id === id);
        const updatedAt = Number(raw.updatedAt) * 1000 || Date.now();
        if (existing && Number(existing.updatedAt || 0) >= updatedAt) continue;
        const note = {
          id,
          body: safeText(raw.note, 100000).trim(),
          quote: safeText(raw.quote, 20000).trim(),
          locator: parseLocator(raw.locator),
          label: existing?.label || "",
          createdAt: Number(raw.createdAt) * 1000 || updatedAt,
          updatedAt,
        };
        if (existing) Object.assign(existing, note);
        else item.notes.push(note);
        changed = true;
      }
      if (!changed) return;
      item.bookmarks = item.bookmarks.slice(-MAX_BOOKMARKS);
      item.notes = item.notes.slice(-MAX_NOTES);
      writeStore();
      renderNotes();
      renderBookmarks();
    }

    toggle.addEventListener("click", () => root.classList.contains("is-open") ? close() : open("notes"));
    elements.close.addEventListener("click", close);
    elements.scrim?.addEventListener("click", close);
    elements.tabs.forEach((button) => button.addEventListener("click", () => setTab(button.dataset.readerDeskTab)));
    elements.addBookmark.addEventListener("click", toggleCurrentBookmark);
    elements.quoteClear.addEventListener("click", () => setSelection(""));
    elements.noteSave.addEventListener("click", saveNote);
    elements.draft.addEventListener("input", () => {
      const item = currentDocument();
      if (!item) return;
      item.draft = safeText(elements.draft.value, 100000);
      writeStore();
      setDraftStatus("Draft saved locally.");
    });
    elements.draft.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        saveNote();
      }
    });
    root.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      close();
    });
    window.addEventListener("message", handleStudyMessage);
    window.addEventListener("resize", sendStudyContext, { passive: true });
    window.addEventListener("cs-library-reader-native-snapshot", (event) => mergeNativeSnapshot(event.detail));

    setDeskInteractive(false);
    setTab("notes");
    render();

    return {
      activate,
      addBookmark,
      close,
      deactivate,
      isCurrentBookmarked,
      mergeNativeSnapshot,
      open,
      setLocation,
      setSelection,
      setTab,
      toggleCurrentBookmark,
    };
  }

  window.LatticeReaderDesk = { ...exported, create };
})();
