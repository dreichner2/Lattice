/* Lattice Study Workspace — local notebooks for prose, math, and trusted Python. */
(() => {
  "use strict";

  function createSaveTracker() {
    const dirty = new Set();
    let failure = null;
    return {
      markDirty(cellId) {
        if (cellId) dirty.add(cellId);
      },
      markFailed(cellId, error) {
        if (cellId) dirty.add(cellId);
        failure = { cellId: cellId || "", error };
      },
      markSucceeded(cellId, complete = true) {
        if (complete && cellId) dirty.delete(cellId);
        if (failure?.cellId === cellId) failure = null;
      },
      reset() {
        dirty.clear();
        failure = null;
      },
      dirtyIds() {
        return [...dirty];
      },
      shouldWarn(pending = 0) {
        return dirty.size > 0 || pending > 0 || Boolean(failure);
      },
      get dirtyCount() { return dirty.size; },
      get failure() { return failure; },
    };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { createSaveTracker };
  }
  if (typeof window === "undefined" || typeof document === "undefined") return;

  const PRIVATE_ACCESS_STORAGE = "lattice:private-access";
  const THEME_STORAGE = "cs-library:theme";
  const RAIL_STORAGE = "lattice:study-rail-collapsed";
  const EMBED_VERSION = 1;
  const EMBED_READY = "lattice-study-ready";
  const EMBED_CONTEXT = "lattice-study-context";
  const EMBED_STATUS = "lattice-study-status";

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

  function readBooleanStorage(key) {
    try { return window.localStorage.getItem(key) === "true"; } catch { return false; }
  }

  function isEmbeddedFrame() {
    try { return window.parent !== window; } catch { return true; }
  }

  const state = {
    token: "",
    privateToken: capturePrivateAccessToken(),
    notebooks: [],
    currentId: "",
    cells: [],
    revision: "",
    saving: new Map(),
    saveQueue: Promise.resolve(),
    saveTracker: createSaveTracker(),
    pendingMutations: 0,
    catalogMaterials: [],
    notebookQuery: "",
    railCollapsed: readBooleanStorage(RAIL_STORAGE),
    embedded: isEmbeddedFrame(),
    embedContext: null,
    contextResolving: false,
    resolvedContextKey: "",
    initialized: false,
  };

  const elements = {};

  function cacheElements() {
    for (const id of [
      "studyHeading",
      "studySub",
      "workspaceHeader",
      "editorLayout",
      "emptyLayout",
      "studySidebar",
      "notebookList",
      "noSearchResults",
      "notebookSearch",
      "sidebarCount",
      "cellStack",
      "notebookStart",
      "notebookTitle",
      "notebookCellCount",
      "workLink",
      "conflictFlag",
      "saveStatus",
      "saveStatusText",
      "railToggleButton",
      "newNotebookButton",
      "railNewButton",
      "emptyNewButton",
      "readerContext",
      "readerContextTitle",
      "readerContextPath",
      "linkDialog",
      "linkPathInput",
      "linkSaveButton",
      "linkPathOptions",
      "deleteNotebookButton",
      "newNotebookDialog",
      "newNotebookTitleInput",
      "deleteNotebookDialog",
      "deleteNotebookName",
      "shortcutButton",
      "shortcutDialog",
      "restartKernelButton",
    ]) {
      elements[id] = document.getElementById(id);
    }
  }

  function applyTheme(theme) {
    const resolved = theme === "light" || theme === "dark"
      ? theme
      : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.dataset.theme = resolved;
  }

  function initializeTheme() {
    let saved = "";
    try { saved = window.localStorage.getItem(THEME_STORAGE) || ""; } catch { /* unavailable */ }
    applyTheme(saved);
  }

  function hasPendingWork() {
    return state.saving.size > 0
      || state.pendingMutations > 0
      || state.saveTracker.dirtyCount > 0;
  }

  function postEmbeddedStatus(overrides = {}) {
    if (!state.embedded) return;
    const dirty = hasPendingWork();
    window.parent.postMessage({
      type: EMBED_STATUS,
      version: EMBED_VERSION,
      dirty,
      saved: !dirty && !state.saveTracker.failure,
      ...(state.currentId ? { notebookId: state.currentId } : {}),
      ...overrides,
    }, window.location.origin);
  }

  function setSaveStatus(kind, message) {
    if (!elements.saveStatus) return;
    elements.saveStatus.className = `save-status is-${kind}`;
    elements.saveStatusText.textContent = message;
    postEmbeddedStatus({ saved: kind === "saved" && !state.saveTracker.failure });
  }

  function settleSaveStatus() {
    if (state.saveTracker.failure) {
      setSaveStatus("error", "Could not save");
    } else if (hasPendingWork()) {
      setSaveStatus("saving", "Saving…");
    } else {
      setSaveStatus("saved", "Saved locally");
    }
  }

  async function api(route, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      "X-Lattice-Private-Token": state.privateToken,
      ...(options.headers || {}),
    };
    if (options.mutate) headers["X-Library-Token"] = state.token;
    const response = await fetch(route, { ...options, headers });
    let payload = {};
    try { payload = await response.json(); } catch { /* empty body */ }
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
    return payload;
  }

  function announce(message, isError = false) {
    elements.studySub.textContent = message;
    elements.studySub.classList.toggle("is-error", isError);
    if (isError) return;
    clearTimeout(announce.timer);
    announce.timer = setTimeout(() => {
      elements.studySub.textContent = state.embedded
        ? "Notes that stay beside your reading."
        : "Think on the page. Keep the source close.";
      elements.studySub.classList.remove("is-error");
    }, 2600);
  }

  function handleStudyError(error, blockSaves = false, cell = null) {
    if (blockSaves) state.saveTracker.markFailed(cell?.id || "", error);
    if (/another window|fresh notebook revision/i.test(error.message)) {
      elements.conflictFlag.hidden = false;
      setSaveStatus("conflict", "Needs review");
    } else {
      setSaveStatus("error", blockSaves ? "Could not save" : "Action failed");
    }
    announce(error.message, true);
  }

  function enqueueMutation(operation) {
    state.pendingMutations += 1;
    setSaveStatus("saving", "Saving…");
    const pending = state.saveQueue.then(operation);
    let failed = false;
    state.saveQueue = pending
      .catch(() => { failed = true; })
      .finally(() => {
        state.pendingMutations -= 1;
        if (failed) postEmbeddedStatus({ saved: false });
        else settleSaveStatus();
      });
    return pending;
  }

  function setEditorDisabled(disabled) {
    if (!elements.editorLayout) return;
    elements.editorLayout
      .querySelectorAll("button, input, textarea")
      .forEach((control) => { control.disabled = disabled; });
  }

  // ---------------------------------------------------------- safe rendering

  function renderInlineMarkdown(container, source) {
    const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\$[^$\n]+\$|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;
    let cursor = 0;
    for (const match of source.matchAll(pattern)) {
      if (match.index > cursor) container.append(document.createTextNode(source.slice(cursor, match.index)));
      const token = match[0];
      if (token.startsWith("`")) {
        const code = document.createElement("code");
        code.textContent = token.slice(1, -1);
        container.append(code);
      } else if (token.startsWith("**")) {
        const strong = document.createElement("strong");
        strong.textContent = token.slice(2, -2);
        container.append(strong);
      } else if (token.startsWith("*")) {
        const emphasis = document.createElement("em");
        emphasis.textContent = token.slice(1, -1);
        container.append(emphasis);
      } else if (token.startsWith("$")) {
        const math = document.createElement("span");
        try {
          window.katex.render(token.slice(1, -1), math, {
            displayMode: false,
            throwOnError: false,
            strict: false,
            trust: false,
          });
        } catch {
          math.textContent = token;
        }
        container.append(math);
      } else {
        const parts = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
        if (parts) {
          const link = document.createElement("a");
          link.textContent = parts[1];
          link.href = parts[2];
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          container.append(link);
        } else {
          container.append(document.createTextNode(token));
        }
      }
      cursor = match.index + token.length;
    }
    if (cursor < source.length) container.append(document.createTextNode(source.slice(cursor)));
  }

  function isMarkdownBoundary(line) {
    return !line.trim()
      || /^#{1,6}\s/.test(line)
      || /^```/.test(line)
      || /^\$\$/.test(line)
      || /^>\s?/.test(line)
      || /^\s*(?:[-+*]|\d+\.)\s+/.test(line)
      || /^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line);
  }

  function renderMarkdown(container, source) {
    container.classList.add("cell-preview", "markdown-preview");
    container.replaceChildren();
    if (!source.trim()) {
      const hint = document.createElement("p");
      hint.className = "cell-preview-empty";
      hint.textContent = "An empty note — choose Edit and capture the idea in your own words.";
      container.append(hint);
      return;
    }

    const lines = source.replace(/\r\n?/g, "\n").split("\n");
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index += 1; continue; }

      const fence = line.match(/^```\s*([^\s`]*)/);
      if (fence) {
        const codeLines = [];
        index += 1;
        while (index < lines.length && !/^```\s*$/.test(lines[index])) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        if (fence[1]) code.dataset.language = fence[1];
        code.textContent = codeLines.join("\n");
        pre.append(code);
        container.append(pre);
        continue;
      }

      if (/^\$\$/.test(line)) {
        const mathLines = [line.replace(/^\$\$\s*/, "")];
        let closed = /\$\$\s*$/.test(mathLines[0]);
        if (closed) mathLines[0] = mathLines[0].replace(/\$\$\s*$/, "");
        index += 1;
        while (!closed && index < lines.length) {
          const next = lines[index];
          closed = /\$\$\s*$/.test(next);
          mathLines.push(next.replace(/\$\$\s*$/, ""));
          index += 1;
        }
        const math = document.createElement("div");
        math.className = "markdown-math";
        try {
          window.katex.render(mathLines.join("\n"), math, {
            displayMode: true,
            throwOnError: false,
            strict: false,
            trust: false,
          });
        } catch {
          math.textContent = `$$${mathLines.join("\n")}$$`;
        }
        container.append(math);
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        const node = document.createElement(`h${heading[1].length}`);
        renderInlineMarkdown(node, heading[2]);
        container.append(node);
        index += 1;
        continue;
      }

      if (/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)) {
        container.append(document.createElement("hr"));
        index += 1;
        continue;
      }

      if (/^>\s?/.test(line)) {
        const quoted = [];
        while (index < lines.length && /^>\s?/.test(lines[index])) {
          quoted.push(lines[index].replace(/^>\s?/, ""));
          index += 1;
        }
        const quote = document.createElement("blockquote");
        renderInlineMarkdown(quote, quoted.join(" "));
        container.append(quote);
        continue;
      }

      const listMatch = line.match(/^\s*((?:[-+*])|(?:\d+\.))\s+(.+)$/);
      if (listMatch) {
        const ordered = /\d+\./.test(listMatch[1]);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const itemMatch = lines[index].match(/^\s*((?:[-+*])|(?:\d+\.))\s+(.+)$/);
          if (!itemMatch || /\d+\./.test(itemMatch[1]) !== ordered) break;
          const item = document.createElement("li");
          renderInlineMarkdown(item, itemMatch[2]);
          list.append(item);
          index += 1;
        }
        container.append(list);
        continue;
      }

      const paragraphLines = [line.trim()];
      index += 1;
      while (index < lines.length && !isMarkdownBoundary(lines[index])) {
        paragraphLines.push(lines[index].trim());
        index += 1;
      }
      const paragraph = document.createElement("p");
      renderInlineMarkdown(paragraph, paragraphLines.join(" "));
      container.append(paragraph);
    }
  }

  function renderLatex(container, source) {
    container.classList.add("cell-preview", "latex-preview");
    container.replaceChildren();
    if (!source.trim()) {
      const hint = document.createElement("p");
      hint.className = "cell-preview-empty";
      hint.textContent = "An empty math cell";
      container.append(hint);
      return;
    }
    try {
      window.katex.render(source, container, {
        displayMode: true,
        throwOnError: false,
        strict: false,
        trust: false,
      });
    } catch {
      const pre = document.createElement("pre");
      pre.textContent = source;
      container.append(pre);
    }
  }

  function renderPythonPreview(container, source, hasRun) {
    container.classList.add("cell-preview", "python-preview");
    container.replaceChildren();
    const code = document.createElement("code");
    code.textContent = source && source.trim() ? source : "# An empty Python cell";
    container.append(code);
    const note = document.createElement("p");
    note.className = "cell-run-note";
    note.textContent = hasRun
      ? "Ran — no output was produced"
      : "Run with ⌘ Enter when you are ready";
    container.append(note);
  }

  // ------------------------------------------------------------- rendering

  function notebookLabel(notebook) {
    return notebook.workTitle || notebook.workPath || "Unlinked notebook";
  }

  function renderNotebookList() {
    const query = state.notebookQuery.trim().toLocaleLowerCase();
    const filtered = state.notebooks.filter((notebook) => (
      `${notebook.title} ${notebook.workTitle || ""} ${notebook.workPath || ""}`
        .toLocaleLowerCase()
        .includes(query)
    ));
    elements.notebookList.replaceChildren(
      ...filtered.map((notebook) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = `notebook-item${notebook.id === state.currentId ? " is-active" : ""}`;
        item.setAttribute("aria-current", notebook.id === state.currentId ? "page" : "false");
        const copy = document.createElement("span");
        copy.className = "notebook-item-copy";
        const name = document.createElement("strong");
        name.textContent = notebook.title;
        const context = document.createElement("small");
        context.textContent = notebookLabel(notebook);
        copy.append(name, context);
        const count = document.createElement("span");
        count.className = "notebook-item-count";
        count.textContent = String(notebook.cellCount);
        count.setAttribute("aria-label", `${notebook.cellCount} cells`);
        item.append(copy, count);
        item.addEventListener("click", () => void openNotebook(notebook.id));
        return item;
      }),
    );
    elements.noSearchResults.hidden = filtered.length > 0 || !query;
    elements.sidebarCount.textContent = `${state.notebooks.length} notebook${state.notebooks.length === 1 ? "" : "s"}`;
  }

  function cellKindLabel(kind) {
    if (kind === "markdown") return "Note";
    if (kind === "latex") return "Math";
    return "Python";
  }

  function makeCellAction(label, action, ariaLabel = label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "cell-action";
    button.textContent = label;
    button.dataset.action = action;
    button.setAttribute("aria-label", ariaLabel);
    return button;
  }

  function cellBar(cell) {
    const bar = document.createElement("div");
    bar.className = "cell-bar";
    const identity = document.createElement("div");
    identity.className = "cell-identity";
    const grip = document.createElement("span");
    grip.className = "cell-grip";
    grip.textContent = "⠿";
    grip.setAttribute("aria-hidden", "true");
    const chip = document.createElement("span");
    chip.className = "cell-kind-chip";
    chip.textContent = cellKindLabel(cell.kind);
    identity.append(grip, chip);

    const actions = document.createElement("div");
    actions.className = "cell-actions";
    actions.dataset.cellId = cell.id;

    if (cell.kind === "python") {
      const runButton = makeCellAction("Run", "run", "Run Python cell");
      runButton.classList.add("cell-run");
      actions.append(runButton);
    }
    actions.append(makeCellAction(cell.mode === "edit" ? "Preview" : "Edit", "toggle"));
    const up = makeCellAction("↑", "up", "Move cell up");
    up.disabled = cell.position === 0;
    const down = makeCellAction("↓", "down", "Move cell down");
    down.disabled = cell.position === state.cells.length - 1;
    const remove = makeCellAction("×", "delete", "Delete cell");
    remove.classList.add("cell-delete");
    actions.append(up, down, remove);
    bar.append(identity, actions);
    return bar;
  }

  function fitTextarea(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.max(112, Math.min(textarea.scrollHeight, 520))}px`;
  }

  function cellBody(cell) {
    const body = document.createElement("div");
    body.className = "cell-body";
    if (cell.mode === "edit") {
      const editor = document.createElement("textarea");
      editor.value = cell.source;
      editor.dataset.cellId = cell.id;
      editor.spellcheck = cell.kind === "markdown";
      editor.setAttribute("aria-label", `Edit ${cellKindLabel(cell.kind)} cell`);
      editor.setAttribute("aria-keyshortcuts", "Meta+Enter Control+Enter Escape");
      editor.placeholder = cell.kind === "markdown"
        ? "Write what this means in your own words…"
        : cell.kind === "latex"
          ? "e^{i\\pi} + 1 = 0"
          : "values = [1, 2, 3]\nsum(values)";
      editor.addEventListener("input", () => {
        cell.source = editor.value;
        fitTextarea(editor);
        scheduleSave(cell);
      });
      editor.addEventListener("keydown", (event) => handleEditorKeydown(event, cell));
      body.append(editor);
      window.requestAnimationFrame(() => fitTextarea(editor));
    } else if (cell.kind === "markdown") {
      renderMarkdown(body, cell.source);
    } else if (cell.kind === "latex") {
      renderLatex(body, cell.source);
    } else if (cell.outputs && cell.outputs.length) {
      renderOutputs(body, cell);
    } else if (cell.hasRun) {
      renderPythonPreview(body, "", true);
    } else {
      renderPythonPreview(body, cell.source, false);
    }
    return body;
  }

  function renderCells() {
    elements.cellStack.replaceChildren(
      ...state.cells.map((cell) => {
        const wrapper = document.createElement("article");
        wrapper.className = `cell is-${cell.kind}${cell.mode === "edit" ? " is-editing" : ""}`;
        wrapper.dataset.cellId = cell.id;
        wrapper.append(cellBar(cell), cellBody(cell));
        return wrapper;
      }),
    );
    document.querySelector(".cell-adder").hidden = !state.currentId;
    elements.notebookStart.hidden = !state.currentId || state.cells.length > 0;
    elements.notebookCellCount.textContent = `${state.cells.length} cell${state.cells.length === 1 ? "" : "s"}`;
  }

  function renderWorkLink() {
    const notebook = state.notebooks.find((item) => item.id === state.currentId);
    const label = notebook?.workTitle || notebook?.workPath;
    elements.workLink.textContent = label ? `Linked to ${label}` : "Link a library work";
    elements.workLink.title = notebook?.workPath || "";
  }

  function renderReaderContext() {
    const context = state.embedContext;
    elements.readerContext.hidden = !state.embedded || !context;
    if (!context) return;
    elements.readerContextTitle.textContent = context.workTitle || "Current reading";
    elements.readerContextPath.textContent = context.workPath || "";
  }

  function refreshCurrentCellCount() {
    const notebook = state.notebooks.find((item) => item.id === state.currentId);
    if (notebook) notebook.cellCount = state.cells.length;
    renderNotebookList();
    renderCells();
  }

  function applyRailState() {
    document.body.classList.toggle("rail-collapsed", state.railCollapsed);
    elements.railToggleButton.setAttribute("aria-expanded", String(!state.railCollapsed));
    elements.railToggleButton.setAttribute(
      "aria-label",
      state.railCollapsed ? "Expand notebook rail" : "Collapse notebook rail",
    );
  }

  function toggleRail() {
    state.railCollapsed = !state.railCollapsed;
    try { window.localStorage.setItem(RAIL_STORAGE, String(state.railCollapsed)); } catch { /* unavailable */ }
    applyRailState();
  }

  async function openNotebook(notebookId) {
    if (notebookId === state.currentId && state.cells.length) return;
    setEditorDisabled(true);
    try {
      await flushPendingSaves();
      const payload = await api(`/api/study/notebook/${encodeURIComponent(notebookId)}`);
      state.currentId = notebookId;
      state.revision = payload.notebook.updatedAt;
      state.saveTracker.reset();
      state.cells = payload.cells.map((cell) => ({ ...cell, mode: "preview" }));
      elements.notebookTitle.value = payload.notebook.title;
      elements.conflictFlag.hidden = true;
      elements.editorLayout.hidden = false;
      elements.emptyLayout.hidden = true;
      renderNotebookList();
      renderWorkLink();
      renderCells();
      settleSaveStatus();
    } catch (error) {
      handleStudyError(error);
    } finally {
      setEditorDisabled(false);
    }
  }

  async function refreshList({ openFirst = true } = {}) {
    const payload = await api("/api/study/notebooks");
    state.notebooks = payload.notebooks;
    renderNotebookList();
    if (openFirst && !state.currentId && state.notebooks.length && !state.embedContext) {
      await openNotebook(state.notebooks[0].id);
    }
    if (!state.notebooks.length && !state.currentId) {
      elements.editorLayout.hidden = true;
      elements.emptyLayout.hidden = false;
    }
  }

  // ------------------------------------------------------------ mutations

  function selectStarter(starter) {
    const input = elements.newNotebookDialog.querySelector(`input[name="starter"][value="${starter}"]`);
    if (input) input.checked = true;
  }

  function showNewNotebookDialog(starter = "notes") {
    elements.newNotebookDialog.returnValue = "";
    elements.newNotebookTitleInput.value = state.embedContext?.workTitle
      ? `${state.embedContext.workTitle} notes`.slice(0, 200)
      : "Untitled notebook";
    selectStarter(starter);
    elements.newNotebookDialog.showModal();
    elements.newNotebookTitleInput.select();
  }

  function starterCells(starter) {
    if (starter === "blank") return [];
    if (starter === "worked") return [
      { kind: "markdown", source: "" },
      { kind: "latex", source: "" },
    ];
    if (starter === "experiment") return [
      { kind: "markdown", source: "" },
      { kind: "python", source: "" },
    ];
    return [{ kind: "markdown", source: "" }];
  }

  async function createNotebook({ title, starter = "notes", workPath = "" } = {}) {
    try {
      const resolvedTitle = (title || elements.newNotebookTitleInput.value).trim();
      if (!resolvedTitle) return null;
      await flushPendingSaves();
      const created = await enqueueMutation(() => api("/api/study/notebooks", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ title: resolvedTitle }),
      }));
      await refreshList({ openFirst: false });
      await openNotebook(created.notebook.id);
      if (workPath) await linkCurrentNotebook(workPath);
      for (const cell of starterCells(starter)) {
        await addCell(cell.kind, cell.source, { focus: false });
      }
      const firstEditor = elements.cellStack.querySelector("textarea");
      if (firstEditor) firstEditor.focus();
      return created.notebook;
    } catch (error) {
      handleStudyError(error);
      return null;
    }
  }

  function scheduleSave(cell) {
    state.saveTracker.markDirty(cell.id);
    const prior = state.saving.get(cell.id);
    if (prior) clearTimeout(prior.timer);
    const timer = setTimeout(() => {
      state.saving.delete(cell.id);
      void persistCell(cell).catch((error) => handleStudyError(error, true, cell));
    }, 650);
    state.saving.set(cell.id, { timer, cell });
    setSaveStatus("saving", "Saving…");
  }

  function persistCell(cell) {
    const source = cell.source;
    return enqueueMutation(async () => {
      if (cell.notebookId !== state.currentId) {
        throw new Error("Notebook changed before the pending cell save completed");
      }
      const result = await api("/api/study/cell/update", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({
          cellId: cell.id,
          source,
          baseUpdatedAt: state.revision,
        }),
      });
      state.revision = result.notebookUpdatedAt;
      cell.updatedAt = result.cell.updatedAt;
      state.saveTracker.markSucceeded(cell.id, cell.source === source);
      announce("Saved locally");
      return result;
    });
  }

  async function flushPendingSaves() {
    while (state.saving.size || state.saveTracker.dirtyCount) {
      const pending = [...state.saving.values()];
      state.saving.clear();
      const cells = new Map(pending.map((entry) => [entry.cell.id, entry.cell]));
      for (const cellId of state.saveTracker.dirtyIds()) {
        const cell = state.cells.find((item) => item.id === cellId);
        if (cell) cells.set(cell.id, cell);
      }
      if (!cells.size) break;
      for (const entry of pending) {
        clearTimeout(entry.timer);
      }
      for (const cell of cells.values()) {
        try {
          await persistCell(cell);
        } catch (error) {
          handleStudyError(error, true, cell);
          throw error;
        }
      }
    }
    await state.saveQueue;
    if (state.saveTracker.failure) throw state.saveTracker.failure.error;
    settleSaveStatus();
  }

  async function moveCell(cellId, direction) {
    try {
      await flushPendingSaves();
      const result = await enqueueMutation(() => api("/api/study/cell/move", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ cellId, direction, baseUpdatedAt: state.revision }),
      }));
      state.revision = result.notebookUpdatedAt;
      const index = state.cells.findIndex((cell) => cell.id === cellId);
      const target = direction === "up" ? index - 1 : index + 1;
      if (index >= 0 && target >= 0 && target < state.cells.length) {
        const [moved] = state.cells.splice(index, 1);
        state.cells.splice(target, 0, moved);
        state.cells.forEach((cell, position) => { cell.position = position; });
        renderCells();
      }
    } catch (error) {
      handleStudyError(error);
    }
  }

  async function deleteCell(cellId) {
    try {
      await flushPendingSaves();
      const result = await enqueueMutation(() => api("/api/study/cell/delete", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ cellId, baseUpdatedAt: state.revision }),
      }));
      state.revision = result.notebookUpdatedAt;
      state.cells = state.cells.filter((cell) => cell.id !== cellId);
      state.cells.forEach((cell, position) => { cell.position = position; });
      refreshCurrentCellCount();
    } catch (error) {
      handleStudyError(error);
    }
  }

  async function addCell(kind = "markdown", source = "", { focus = true } = {}) {
    if (!state.currentId || !["markdown", "latex", "python"].includes(kind)) return null;
    try {
      await flushPendingSaves();
      const result = await enqueueMutation(() => api(`/api/study/notebook/${encodeURIComponent(state.currentId)}/cells`, {
        method: "POST",
        mutate: true,
        body: JSON.stringify({
          kind,
          source,
          baseUpdatedAt: state.revision,
        }),
      }));
      state.revision = result.notebookUpdatedAt;
      state.cells.push({ ...result.cell, mode: "edit" });
      refreshCurrentCellCount();
      if (focus) {
        const editor = elements.cellStack.querySelector(`[data-cell-id="${result.cell.id}"] textarea`);
        editor?.focus();
      }
      return result.cell;
    } catch (error) {
      handleStudyError(error);
      return null;
    }
  }

  function renderOutputs(container, cell) {
    container.replaceChildren();
    const outputs = cell.outputs || [];
    if (!outputs.length) return;
    const wrap = document.createElement("div");
    wrap.className = "cell-outputs";
    for (const output of outputs) {
      if (output.type === "stream") {
        const pre = document.createElement("pre");
        pre.className = `cell-output stream-${output.name === "stderr" ? "stderr" : "stdout"}`;
        pre.textContent = output.text;
        wrap.append(pre);
      } else if (output.type === "result") {
        const pre = document.createElement("pre");
        pre.className = "cell-output cell-result";
        pre.textContent = output.text;
        wrap.append(pre);
      } else if (output.type === "error") {
        const block = document.createElement("div");
        block.className = "cell-output cell-error";
        const name = document.createElement("strong");
        name.textContent = `${output.name}: ${output.message}`;
        const trace = document.createElement("pre");
        trace.textContent = output.traceback || "";
        block.append(name, trace);
        wrap.append(block);
      } else if (
        output.type === "image"
        && output.mime === "image/png"
        && typeof output.data === "string"
        && output.data.length <= 5_400_000
        && /^[A-Za-z0-9+/]*={0,2}$/.test(output.data)
      ) {
        const image = document.createElement("img");
        image.className = "cell-output cell-image";
        image.alt = "Matplotlib figure";
        image.src = `data:image/png;base64,${output.data}`;
        wrap.append(image);
      }
    }
    container.append(wrap);
  }

  async function runCell(cell, button) {
    if (!state.currentId && state.notebooks.length) {
      await openNotebook(state.notebooks[0].id);
      const reopened = state.cells.find((item) => item.id === cell.id);
      if (reopened) cell = reopened;
    }
    if (!state.currentId) {
      announce("Open a notebook before running a cell", true);
      return;
    }
    if (!cell.source.trim()) {
      announce("That cell is empty — add some Python first", true);
      return;
    }
    const notebookId = state.currentId;
    button.disabled = true;
    button.textContent = "Running…";
    try {
      await flushPendingSaves();
      if (state.currentId !== notebookId) {
        throw new Error("Notebook changed before the cell could run");
      }
      const source = cell.source;
      const result = await api("/api/study/kernel/run", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ notebookId, source }),
      });
      const currentCell = state.currentId === notebookId
        ? state.cells.find((item) => item.id === cell.id)
        : null;
      if (currentCell) {
        currentCell.outputs = result.outputs;
        currentCell.hasRun = true;
        currentCell.mode = "preview";
        renderCells();
      }
      announce(result.ok ? "Python finished" : "Python raised an error", !result.ok);
    } catch (error) {
      announce(error.message, true);
    } finally {
      if (button.isConnected) {
        button.disabled = false;
        button.textContent = "Run";
      }
    }
  }

  async function restartKernel() {
    if (!state.currentId) return;
    const notebookId = state.currentId;
    try {
      await api("/api/study/kernel/restart", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ notebookId }),
      });
      if (state.currentId === notebookId) {
        for (const cell of state.cells) delete cell.outputs;
        renderCells();
      }
      announce("Python restarted — variables cleared");
    } catch (error) {
      announce(error.message, true);
    }
  }

  async function saveTitle() {
    if (!state.currentId) return;
    try {
      await flushPendingSaves();
      const result = await enqueueMutation(() => api(`/api/study/notebook/${encodeURIComponent(state.currentId)}`, {
        method: "POST",
        mutate: true,
        body: JSON.stringify({
          title: elements.notebookTitle.value.trim() || "Untitled notebook",
          baseUpdatedAt: state.revision,
        }),
      }));
      state.revision = result.notebookUpdatedAt;
      await refreshListPreservingSelection();
      announce("Notebook renamed");
    } catch (error) {
      handleStudyError(error);
    }
  }

  async function refreshListPreservingSelection() {
    const current = state.currentId;
    const payload = await api("/api/study/notebooks");
    state.notebooks = payload.notebooks;
    state.currentId = current;
    renderNotebookList();
    renderWorkLink();
  }

  async function deleteNotebook() {
    if (!state.currentId) return;
    try {
      await flushPendingSaves();
      await enqueueMutation(() => api(
        `/api/study/notebook/${encodeURIComponent(state.currentId)}/delete`,
        {
          method: "POST",
          mutate: true,
          body: JSON.stringify({ baseUpdatedAt: state.revision }),
        },
      ));
      state.currentId = "";
      state.revision = "";
      state.cells = [];
      state.resolvedContextKey = "";
      await refreshList();
      if (!state.notebooks.length) {
        elements.editorLayout.hidden = true;
        elements.emptyLayout.hidden = false;
      }
      announce("Notebook deleted");
    } catch (error) {
      handleStudyError(error);
    }
  }

  async function linkCurrentNotebook(workPath) {
    if (!state.currentId) return;
    await flushPendingSaves();
    const result = await enqueueMutation(() => api(`/api/study/notebook/${encodeURIComponent(state.currentId)}/link`, {
      method: "POST",
      mutate: true,
      body: JSON.stringify({ workPath, baseUpdatedAt: state.revision }),
    }));
    state.revision = result.notebookUpdatedAt;
    const notebook = state.notebooks.find((item) => item.id === state.currentId);
    if (notebook) {
      notebook.workPath = result.notebook.workPath;
      notebook.workTitle = result.notebook.workTitle;
    }
    renderNotebookList();
    renderWorkLink();
  }

  function renderLinkOptions() {
    elements.linkPathOptions.replaceChildren(
      ...state.catalogMaterials.map((material) => {
        const option = document.createElement("option");
        option.value = material.path;
        option.label = material.title || material.path;
        return option;
      }),
    );
  }

  // ------------------------------------------------------- reader embedding

  function normalizeEmbedContext(value) {
    if (!value || typeof value !== "object") return null;
    const workPath = typeof value.workPath === "string" ? value.workPath.trim() : "";
    const workTitle = typeof value.workTitle === "string" ? value.workTitle.trim().slice(0, 200) : "";
    if (!workPath || workPath.length > 1024 || /[\0-\x1f]/.test(workPath)) return null;
    return {
      workPath,
      workTitle,
      mode: value.mode === "lab" ? "lab" : "notes",
      compact: value.compact !== false,
    };
  }

  function applyEmbeddedPresentation() {
    document.body.classList.toggle("is-embedded", state.embedded);
    document.body.classList.toggle("is-compact", Boolean(state.embedContext?.compact));
    document.body.classList.toggle("reader-notes-mode", state.embedContext?.mode === "notes");
    renderReaderContext();
  }

  async function resolveEmbeddedContext() {
    const context = state.embedContext;
    if (!state.initialized || !context || state.contextResolving) return;
    const key = `${context.workPath}\n${context.mode}`;
    if (state.resolvedContextKey === key && state.currentId) {
      postEmbeddedStatus();
      return;
    }
    state.contextResolving = true;
    try {
      const material = state.catalogMaterials.find((item) => item.path === context.workPath);
      if (!material) throw new Error("This reader item is not available in the current library.");
      const linked = state.notebooks.find((notebook) => notebook.workPath === context.workPath);
      if (linked) {
        await openNotebook(linked.id);
      } else {
        const titleBase = context.workTitle || material.title || "Reading";
        await createNotebook({
          title: `${titleBase} notes`.slice(0, 200),
          starter: "notes",
          workPath: context.workPath,
        });
      }
      state.resolvedContextKey = key;
      postEmbeddedStatus({ saved: !hasPendingWork() && !state.saveTracker.failure });
    } catch (error) {
      handleStudyError(error);
      postEmbeddedStatus({ saved: false });
    } finally {
      state.contextResolving = false;
      if (state.embedContext && state.embedContext !== context) {
        void resolveEmbeddedContext();
      }
    }
  }

  function handleEmbeddedMessage(event) {
    if (!state.embedded) return;
    if (event.origin !== window.location.origin || event.source !== window.parent) return;
    const message = event.data;
    if (!message || message.type !== EMBED_CONTEXT || message.version !== EMBED_VERSION) return;
    const context = normalizeEmbedContext(message.context);
    if (!context) {
      announce("The reader sent an invalid study context", true);
      postEmbeddedStatus({ saved: false });
      return;
    }
    state.embedContext = context;
    if (message.context.theme === "light" || message.context.theme === "dark") {
      applyTheme(message.context.theme);
    }
    applyEmbeddedPresentation();
    void resolveEmbeddedContext();
  }

  function announceEmbeddedReady() {
    if (!state.embedded) return;
    window.parent.postMessage({ type: EMBED_READY, version: EMBED_VERSION }, window.location.origin);
  }

  // ---------------------------------------------------------- interactions

  function toggleCellMode(cell) {
    cell.mode = cell.mode === "edit" ? "preview" : "edit";
    renderCells();
    if (cell.mode === "edit") {
      const editor = elements.cellStack.querySelector(`[data-cell-id="${cell.id}"] textarea`);
      editor?.focus();
    }
  }

  function handleEditorKeydown(event, cell) {
    if (event.key === "Tab") {
      event.preventDefault();
      const editor = event.currentTarget;
      editor.setRangeText("  ", editor.selectionStart, editor.selectionEnd, "end");
      cell.source = editor.value;
      scheduleSave(cell);
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (cell.kind === "python") {
        const runButton = elements.cellStack.querySelector(
          `[data-cell-id="${cell.id}"] [data-action="run"]`,
        );
        if (runButton) void runCell(cell, runButton);
      } else {
        cell.mode = "preview";
        renderCells();
      }
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      cell.mode = "preview";
      renderCells();
    }
  }

  function isTypingTarget(target) {
    return target instanceof HTMLInputElement
      || target instanceof HTMLTextAreaElement
      || target instanceof HTMLSelectElement
      || target?.isContentEditable;
  }

  function handleGlobalKeydown(event) {
    const command = event.metaKey || event.ctrlKey;
    if (command && event.key.toLowerCase() === "s") {
      event.preventDefault();
      // flushPendingSaves already records the exact cell that failed. Keep this
      // outer handler display-only so it cannot replace that identity with an
      // empty failure that a successful retry would never clear.
      void flushPendingSaves().then(() => announce("Saved locally")).catch((error) => handleStudyError(error));
      return;
    }
    if (command && event.key === "\\") {
      event.preventDefault();
      toggleRail();
      return;
    }
    if (command && event.shiftKey && event.key.toLowerCase() === "n") {
      event.preventDefault();
      showNewNotebookDialog();
      return;
    }
    if (command && event.altKey && ["m", "l", "p"].includes(event.key.toLowerCase())) {
      event.preventDefault();
      const kinds = { m: "markdown", l: "latex", p: "python" };
      void addCell(kinds[event.key.toLowerCase()]);
      return;
    }
    if (event.key === "/" && !isTypingTarget(event.target) && !state.embedded) {
      event.preventDefault();
      if (state.railCollapsed) toggleRail();
      elements.notebookSearch.focus();
    }
  }

  function wireEvents() {
    elements.newNotebookButton.addEventListener("click", () => showNewNotebookDialog());
    elements.railNewButton.addEventListener("click", () => showNewNotebookDialog());
    elements.emptyNewButton.addEventListener("click", () => showNewNotebookDialog("blank"));
    elements.railToggleButton.addEventListener("click", toggleRail);
    elements.shortcutButton.addEventListener("click", () => elements.shortcutDialog.showModal());
    elements.notebookSearch.addEventListener("input", () => {
      state.notebookQuery = elements.notebookSearch.value;
      renderNotebookList();
    });

    document.querySelectorAll("[data-starter]").forEach((button) => {
      button.addEventListener("click", () => showNewNotebookDialog(button.dataset.starter));
    });

    elements.deleteNotebookButton.addEventListener("click", () => {
      const notebook = state.notebooks.find((item) => item.id === state.currentId);
      elements.deleteNotebookName.textContent = notebook?.title || "this notebook";
      elements.deleteNotebookDialog.returnValue = "";
      elements.deleteNotebookDialog.showModal();
    });
    elements.newNotebookDialog.addEventListener("close", () => {
      if (elements.newNotebookDialog.returnValue !== "confirm") return;
      const selected = elements.newNotebookDialog.querySelector('input[name="starter"]:checked');
      void createNotebook({
        starter: selected?.value || "notes",
        workPath: state.embedContext?.workPath || "",
      });
    });
    elements.deleteNotebookDialog.addEventListener("close", () => {
      if (elements.deleteNotebookDialog.returnValue === "confirm") void deleteNotebook();
    });
    elements.notebookTitle.addEventListener("change", () => void saveTitle());
    elements.restartKernelButton.addEventListener("click", () => void restartKernel());

    elements.cellStack.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button || button.disabled) return;
      const actions = button.closest("[data-cell-id]");
      const cellId = actions ? actions.dataset.cellId : "";
      const cell = state.cells.find((item) => item.id === cellId);
      if (!cell) return;
      const action = button.dataset.action;
      if (action === "run") void runCell(cell, button);
      else if (action === "toggle") toggleCellMode(cell);
      else if (action === "up") void moveCell(cell.id, "up");
      else if (action === "down") void moveCell(cell.id, "down");
      else if (action === "delete") void deleteCell(cell.id);
    });

    document.querySelectorAll("[data-add-kind]").forEach((button) => {
      button.addEventListener("click", () => void addCell(button.dataset.addKind));
    });
    elements.workLink.addEventListener("click", () => {
      const notebook = state.notebooks.find((item) => item.id === state.currentId);
      elements.linkPathInput.value = notebook?.workPath || "";
      elements.linkDialog.showModal();
    });
    elements.linkDialog.addEventListener("close", () => {
      if (elements.linkDialog.returnValue !== "confirm" || !state.currentId) return;
      void linkCurrentNotebook(elements.linkPathInput.value.trim()).catch((error) => handleStudyError(error));
    });
    document.addEventListener("keydown", handleGlobalKeydown);
    window.addEventListener("message", handleEmbeddedMessage);
  }

  window.onerror = function (message) {
    if (elements.studySub) announce(`Study Workspace error: ${message}`, true);
  };

  async function init() {
    cacheElements();
    initializeTheme();
    wireEvents();
    applyRailState();
    applyEmbeddedPresentation();
    announceEmbeddedReady();
    try {
      const library = await api("/api/library");
      state.token = library.actionToken;
      state.catalogMaterials = Array.isArray(library.materials)
        ? library.materials.filter((material) => typeof material.path === "string")
        : [];
      renderLinkOptions();
      await refreshList({ openFirst: !state.embedContext });
      state.initialized = true;
      await resolveEmbeddedContext();
      settleSaveStatus();
    } catch (error) {
      state.initialized = true;
      handleStudyError(error);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => void init());
  } else {
    void init();
  }

  window.addEventListener("beforeunload", (event) => {
    if (!state.saveTracker.shouldWarn(state.saving.size + state.pendingMutations)) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
