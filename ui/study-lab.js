/* Study Lab — classic Jupyter-style notebooks with explicit latex|python cells.
   No automatic segmentation: the user picks the cell kind, always. */
(() => {
  "use strict";

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

  const state = {
    token: "",
    privateToken: capturePrivateAccessToken(),
    notebooks: [],
    currentId: "",
    cells: [],
    revision: "",
    saving: new Map(),
    saveQueue: Promise.resolve(),
    saveError: null,
    pendingMutations: 0,
    catalogMaterials: [],
  };

  const elements = {};

  function cacheElements() {
    for (const id of [
      "studyHeading",
      "editorLayout",
      "emptyLayout",
      "notebookList",
      "cellStack",
      "notebookTitle",
      "workLink",
      "conflictFlag",
      "newNotebookButton",
      "emptyNewButton",
      "linkDialog",
      "linkPathInput",
      "linkSaveButton",
      "linkPathOptions",
      "deleteNotebookButton",
      "newNotebookDialog",
      "newNotebookTitleInput",
      "deleteNotebookDialog",
      "deleteNotebookName",
    ]) {
      elements[id] = document.getElementById(id);
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
    // Quiet inline status in the toolbar subtitle; errors stay visible.
    const sub = document.getElementById("studySub");
    sub.textContent = message;
    sub.style.color = isError ? "var(--danger)" : "";
    if (!isError) {
      clearTimeout(announce.timer);
      announce.timer = setTimeout(() => { sub.textContent = "LaTeX & Python notes linked to your library"; }, 2400);
    }
  }

  function handleStudyError(error, blockSaves = false) {
    if (blockSaves) state.saveError = error;
    if (/another window|fresh notebook revision/i.test(error.message)) {
      elements.conflictFlag.hidden = false;
    }
    announce(error.message, true);
  }

  function enqueueMutation(operation) {
    state.pendingMutations += 1;
    const pending = state.saveQueue.then(operation);
    state.saveQueue = pending
      .catch(() => undefined)
      .finally(() => { state.pendingMutations -= 1; });
    return pending;
  }

  function setEditorDisabled(disabled) {
    if (!elements.editorLayout) return;
    elements.editorLayout
      .querySelectorAll("button, input, textarea")
      .forEach((control) => { control.disabled = disabled; });
  }

  // ------------------------------------------------------------------ katex

  function renderLatex(container, source) {
    container.classList.add("cell-preview");
    container.innerHTML = "";
    if (!source.trim()) {
      const hint = document.createElement("p");
      hint.className = "cell-preview-empty";
      hint.style.cssText = "color:var(--faint);font-size:11px;margin:0;";
      hint.textContent = "Empty LaTeX cell";
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
    } catch (error) {
      const pre = document.createElement("pre");
      pre.textContent = source;
      container.append(pre);
    }
  }

  function renderPythonPreview(container, source, hasRun) {
    container.classList.add("cell-preview");
    container.innerHTML = "";
    const code = document.createElement("code");
    code.textContent = source && source.trim() ? source : "(empty python cell)";
    container.append(code);
    const note = document.createElement("p");
    note.className = "cell-run-note";
    note.textContent = hasRun
      ? "Ran — no output was produced"
      : "Press Run ▶ to execute this cell in the Python kernel";
    container.append(note);
  }

  // ------------------------------------------------------------- rendering

  function renderNotebookList() {
    const list = elements.notebookList;
    list.replaceChildren(
      ...state.notebooks.map((notebook) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = `notebook-item${notebook.id === state.currentId ? " is-active" : ""}`;
        const name = document.createElement("span");
        name.textContent = notebook.title;
        const count = document.createElement("small");
        count.textContent = String(notebook.cellCount);
        item.append(name, count);
        item.addEventListener("click", () => void openNotebook(notebook.id));
        return item;
      }),
    );
  }

  function cellBar(cell) {
    const bar = document.createElement("div");
    bar.className = "cell-bar";
    const chip = document.createElement("span");
    chip.className = "cell-kind-chip";
    chip.textContent = cell.kind;
    bar.append(chip);
    const actions = document.createElement("div");
    actions.className = "cell-actions";
    actions.dataset.cellId = cell.id;

    if (cell.kind === "python") {
      const runButton = document.createElement("button");
      runButton.type = "button";
      runButton.className = "cell-action cell-run";
      runButton.textContent = "Run ▶";
      runButton.dataset.action = "run";
      actions.append(runButton);
    }

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "cell-action";
    toggle.textContent = cell.mode === "edit" ? "Preview" : "Edit";
    toggle.dataset.action = "toggle";
    actions.append(toggle);

    const up = document.createElement("button");
    up.type = "button";
    up.className = "cell-action";
    up.textContent = "↑";
    up.disabled = cell.position === 0;
    up.setAttribute("aria-label", "Move cell up");
    up.dataset.action = "up";
    actions.append(up);

    const down = document.createElement("button");
    down.type = "button";
    down.className = "cell-action";
    down.textContent = "↓";
    down.disabled = cell.position === state.cells.length - 1;
    down.setAttribute("aria-label", "Move cell down");
    down.dataset.action = "down";
    actions.append(down);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "cell-action";
    remove.textContent = "Delete";
    remove.dataset.action = "delete";
    actions.append(remove);

    bar.append(actions);
    return bar;
  }

  function cellBody(cell) {
    const body = document.createElement("div");
    body.className = "cell-body";
    if (cell.mode === "edit") {
      const editor = document.createElement("textarea");
      editor.value = cell.source;
      editor.spellcheck = false;
      editor.placeholder =
        cell.kind === "latex"
          ? "\\begin{equation} e^{i\\pi} + 1 = 0 \\end{equation}"
          : "values = [1, 2, 3]\nsum(values)";
      editor.addEventListener("input", () => {
        cell.source = editor.value;
        scheduleSave(cell);
      });
      body.append(editor);
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
        wrapper.className = `cell is-${cell.kind}`;
        wrapper.dataset.cellId = cell.id;
        wrapper.append(cellBar(cell), cellBody(cell));
        return wrapper;
      }),
    );
    const adder = document.querySelector(".cell-adder");
    adder.hidden = !state.currentId;
  }

  function renderWorkLink() {
    const notebook = state.notebooks.find((item) => item.id === state.currentId);
    const link = notebook && notebook.workPath;
    elements.workLink.textContent = link ? `Linked: ${link} · change` : "Link a library work";
  }

  function refreshCurrentCellCount() {
    const notebook = state.notebooks.find((item) => item.id === state.currentId);
    if (notebook) notebook.cellCount = state.cells.length;
    renderNotebookList();
  }

  async function openNotebook(notebookId) {
    setEditorDisabled(true);
    try {
      await flushPendingSaves();
      const payload = await api(`/api/study/notebook/${encodeURIComponent(notebookId)}`);
      state.currentId = notebookId;
      state.revision = payload.notebook.updatedAt;
      state.saveError = null;
      state.cells = payload.cells.map((cell) => ({ ...cell, mode: "preview" }));
      elements.notebookTitle.value = payload.notebook.title;
      elements.conflictFlag.hidden = true;
      elements.editorLayout.hidden = false;
      elements.emptyLayout.hidden = true;
      renderNotebookList();
      renderWorkLink();
      renderCells();
    } catch (error) {
      handleStudyError(error);
    } finally {
      setEditorDisabled(false);
    }
  }

  async function refreshList() {
    const payload = await api("/api/study/notebooks");
    state.notebooks = payload.notebooks;
    renderNotebookList();
    if (!state.currentId && state.notebooks.length) await openNotebook(state.notebooks[0].id);
  }

  // ------------------------------------------------------------ mutations

  function showNewNotebookDialog() {
    elements.newNotebookDialog.returnValue = "";
    elements.newNotebookTitleInput.value = "Untitled notebook";
    elements.newNotebookDialog.showModal();
    elements.newNotebookTitleInput.select();
  }

  async function createNotebook() {
    try {
      const title = elements.newNotebookTitleInput.value.trim();
      if (!title) return;
      await flushPendingSaves();
      const created = await enqueueMutation(() => api("/api/study/notebooks", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ title }),
      }));
      await refreshList();
      await openNotebook(created.notebook.id);
    } catch (error) {
      handleStudyError(error);
    }
  }

  function scheduleSave(cell) {
    const prior = state.saving.get(cell.id);
    if (prior) clearTimeout(prior.timer);
    const timer = setTimeout(() => {
      state.saving.delete(cell.id);
      void persistCell(cell).catch((error) => handleStudyError(error, true));
    }, 650);
    state.saving.set(cell.id, { timer, cell });
  }

  function persistCell(cell) {
    return enqueueMutation(async () => {
      if (cell.notebookId !== state.currentId) {
        throw new Error("Notebook changed before the pending cell save completed");
      }
      const result = await api("/api/study/cell/update", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({
          cellId: cell.id,
          source: cell.source,
          baseUpdatedAt: state.revision,
        }),
      });
      state.revision = result.notebookUpdatedAt;
      cell.updatedAt = result.cell.updatedAt;
      announce("Saved");
      return result;
    });
  }

  async function flushPendingSaves() {
    if (state.saveError) throw state.saveError;
    while (state.saving.size) {
      const pending = [...state.saving.values()];
      state.saving.clear();
      for (const entry of pending) {
        clearTimeout(entry.timer);
        await persistCell(entry.cell);
      }
    }
    await state.saveQueue;
    if (state.saveError) throw state.saveError;
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
      renderCells();
    } catch (error) {
      handleStudyError(error);
    }
  }

  async function addCell(kind) {
    if (!state.currentId) return;
    try {
      await flushPendingSaves();
      const result = await enqueueMutation(() => api(`/api/study/notebook/${encodeURIComponent(state.currentId)}/cells`, {
        method: "POST",
        mutate: true,
        body: JSON.stringify({
          kind,
          source: "",
          baseUpdatedAt: state.revision,
        }),
      }));
      state.revision = result.notebookUpdatedAt;
      state.cells.push({ ...result.cell, mode: "edit" });
      refreshCurrentCellCount();
      renderCells();
      const editors = elements.cellStack.querySelectorAll("textarea");
      if (editors.length) editors[editors.length - 1].focus();
    } catch (error) {
      handleStudyError(error);
    }
  }

  function renderOutputs(container, cell) {
    container.innerHTML = "";
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
    // If the page lost its notebook context (reload, stale state), reopen
    // the first notebook instead of failing silently.
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
      // Save first so the executed source matches what is on disk.
      await flushPendingSaves();
      if (state.currentId !== notebookId) {
        throw new Error("Notebook changed before the cell could run");
      }
      const source = cell.source;
      const result = await api("/api/study/kernel/run", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({
          notebookId,
          source,
        }),
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
      announce(result.ok ? "Ran without errors" : "Cell raised an error", !result.ok);
    } catch (error) {
      announce(error.message, true);
      elements.conflictFlag.hidden = false;
      elements.conflictFlag.textContent = error.message;
      setTimeout(() => { elements.conflictFlag.hidden = true; }, 6000);
    } finally {
      if (button.isConnected) {
        button.disabled = false;
        button.textContent = "Run ▶";
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
      announce("Kernel restarted — variables cleared");
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
      announce("Renamed");
    } catch (error) {
      handleStudyError(error);
    }
  }

  async function refreshListPreservingSelection() {
    const current = state.currentId;
    const payload = await api("/api/study/notebooks");
    state.notebooks = payload.notebooks;
    renderNotebookList();
    state.currentId = current;
    renderNotebookList();
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

  // ------------------------------------------------------------------ init

  function wireEvents() {
    elements.newNotebookButton.addEventListener("click", showNewNotebookDialog);
    elements.emptyNewButton.addEventListener("click", showNewNotebookDialog);
    elements.deleteNotebookButton.addEventListener("click", () => {
      const notebook = state.notebooks.find((item) => item.id === state.currentId);
      elements.deleteNotebookName.textContent = notebook?.title || "this notebook";
      elements.deleteNotebookDialog.returnValue = "";
      elements.deleteNotebookDialog.showModal();
    });
    elements.newNotebookDialog.addEventListener("close", () => {
      if (elements.newNotebookDialog.returnValue === "confirm") void createNotebook();
    });
    elements.deleteNotebookDialog.addEventListener("close", () => {
      if (elements.deleteNotebookDialog.returnValue === "confirm") void deleteNotebook();
    });
    elements.notebookTitle.addEventListener("change", () => void saveTitle());
    const restartButton = document.getElementById("restartKernelButton");
    if (restartButton) restartButton.addEventListener("click", () => void restartKernel());

    // Delegated handling for every cell action: buttons survive full list
    // re-renders, and a click can never be silently swallowed.
    elements.cellStack.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button || button.disabled) return;
      const actions = button.closest("[data-cell-id]");
      const cellId = actions ? actions.dataset.cellId : "";
      const cell = state.cells.find((item) => item.id === cellId);
      if (!cell) return;
      const action = button.dataset.action;
      if (action === "run") void runCell(cell, button);
      else if (action === "toggle") {
        cell.mode = cell.mode === "edit" ? "preview" : "edit";
        renderCells();
      } else if (action === "up") void moveCell(cell.id, "up");
      else if (action === "down") void moveCell(cell.id, "down");
      else if (action === "delete") void deleteCell(cell.id);
    });

    document.querySelectorAll("[data-add-kind]").forEach((button) => {
      button.addEventListener("click", () => void addCell(button.dataset.addKind));
    });
    elements.workLink.addEventListener("click", () => {
      elements.linkPathInput.value = "";
      elements.linkDialog.showModal();
    });
    elements.linkDialog.addEventListener("close", () => {
      if (elements.linkDialog.returnValue !== "confirm" || !state.currentId) return;
      void (async () => {
        try {
          await flushPendingSaves();
          const workPath = elements.linkPathInput.value.trim();
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
          renderWorkLink();
        } catch (error) {
          handleStudyError(error);
        }
      })();
    });
  }

  window.onerror = function (message, source, line) {
    const sub = document.getElementById("studySub");
    if (sub) sub.textContent = "JS ERROR: " + message + " @" + line;
  };

  async function init() {
    cacheElements();
    wireEvents();
    try {
      const library = await api("/api/library");
      state.token = library.actionToken;
      state.catalogMaterials = Array.isArray(library.materials)
        ? library.materials.filter((material) => typeof material.path === "string")
        : [];
      renderLinkOptions();
      await refreshList();
    } catch (error) {
      announce(error.message, true);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => void init());
  } else {
    void init();
  }

  window.addEventListener("beforeunload", (event) => {
    if (!state.saving.size && !state.pendingMutations) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
