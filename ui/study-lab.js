/* Study Lab — classic Jupyter-style notebooks with explicit latex|python cells.
   No automatic segmentation: the user picks the cell kind, always. */
(() => {
  "use strict";

  const state = {
    token: "",
    notebooks: [],
    currentId: "",
    cells: [],
    revision: "",
    saving: new Map(),
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
    ]) {
      elements[id] = document.getElementById(id);
    }
  }

  async function api(route, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
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

  function renderPythonPreview(container, source) {
    container.classList.add("cell-preview");
    container.innerHTML = "";
    const note = document.createElement("p");
    note.style.cssText = "color:var(--faint);font-size:10px;margin:0 0 8px;";
    note.textContent = "Python execution arrives with the runtime update.";
    const code = document.createElement("code");
    code.textContent = source || "(empty python cell)";
    container.append(note, code);
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
        item.addEventListener("click", () => openNotebook(notebook.id));
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

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "cell-action";
    toggle.textContent = cell.mode === "edit" ? "Preview" : "Edit";
    toggle.addEventListener("click", () => {
      cell.mode = cell.mode === "edit" ? "preview" : "edit";
      renderCells();
    });

    const up = document.createElement("button");
    up.type = "button";
    up.className = "cell-action";
    up.textContent = "↑";
    up.disabled = cell.position === 0;
    up.setAttribute("aria-label", "Move cell up");
    up.addEventListener("click", () => moveCell(cell.id, "up"));

    const down = document.createElement("button");
    down.type = "button";
    down.className = "cell-action";
    down.textContent = "↓";
    down.disabled = cell.position === state.cells.length - 1;
    down.setAttribute("aria-label", "Move cell down");
    down.addEventListener("click", () => moveCell(cell.id, "down"));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "cell-action";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => deleteCell(cell.id));

    actions.append(toggle, up, down, remove);
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
          : "import numpy as np";
      editor.addEventListener("input", () => {
        cell.source = editor.value;
        scheduleSave(cell);
      });
      body.append(editor);
    } else if (cell.kind === "latex") {
      renderLatex(body, cell.source);
    } else {
      renderPythonPreview(body, cell.source);
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

  async function openNotebook(notebookId) {
    try {
      const payload = await api(`/api/study/notebook/${encodeURIComponent(notebookId)}`);
      state.currentId = notebookId;
      state.revision = payload.notebook.updatedAt;
      state.cells = payload.cells.map((cell) => ({ ...cell, mode: "preview" }));
      elements.notebookTitle.value = payload.notebook.title;
      elements.conflictFlag.hidden = true;
      elements.editorLayout.hidden = false;
      elements.emptyLayout.hidden = true;
      renderNotebookList();
      renderWorkLink();
      renderCells();
    } catch (error) {
      announce(error.message, true);
    }
  }

  async function refreshList() {
    const payload = await api("/api/study/notebooks");
    state.notebooks = payload.notebooks;
    renderNotebookList();
    if (!state.currentId && state.notebooks.length) await openNotebook(state.notebooks[0].id);
  }

  // ------------------------------------------------------------ mutations

  async function createNotebook() {
    try {
      const title = window.prompt("Notebook title", "Untitled notebook");
      if (!title) return;
      const created = await api("/api/study/notebooks", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ title }),
      });
      await refreshList();
      await openNotebook(created.notebook.id);
    } catch (error) {
      announce(error.message, true);
    }
  }

  function scheduleSave(cell) {
    clearTimeout(state.saving.get(cell.id));
    const timer = setTimeout(() => void saveCell(cell), 650);
    state.saving.set(cell.id, timer);
  }

  async function saveCell(cell) {
    try {
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
    } catch (error) {
      if (/another window/i.test(error.message)) elements.conflictFlag.hidden = false;
      announce(error.message, true);
    }
  }

  async function moveCell(cellId, direction) {
    try {
      const result = await api("/api/study/cell/move", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ cellId, direction, baseUpdatedAt: state.revision }),
      });
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
      announce(error.message, true);
    }
  }

  async function deleteCell(cellId) {
    try {
      const result = await api("/api/study/cell/delete", {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ cellId, baseUpdatedAt: state.revision }),
      });
      state.revision = result.notebookUpdatedAt;
      state.cells = state.cells.filter((cell) => cell.id !== cellId);
      state.cells.forEach((cell, position) => { cell.position = position; });
      renderCells();
    } catch (error) {
      announce(error.message, true);
    }
  }

  async function addCell(kind) {
    if (!state.currentId) return;
    try {
      const result = await api(`/api/study/notebook/${encodeURIComponent(state.currentId)}/cells`, {
        method: "POST",
        mutate: true,
        body: JSON.stringify({ kind, source: "" }),
      });
      state.revision = result.notebookUpdatedAt;
      state.cells.push({ ...result.cell, mode: "edit" });
      renderCells();
      const editors = elements.cellStack.querySelectorAll("textarea");
      if (editors.length) editors[editors.length - 1].focus();
    } catch (error) {
      announce(error.message, true);
    }
  }

  async function saveTitle() {
    if (!state.currentId) return;
    try {
      const result = await api(`/api/study/notebook/${encodeURIComponent(state.currentId)}`, {
        method: "POST",
        mutate: true,
        body: JSON.stringify({
          title: elements.notebookTitle.value.trim() || "Untitled notebook",
          baseUpdatedAt: state.revision,
        }),
      });
      state.revision = result.notebookUpdatedAt;
      await refreshListPreservingSelection();
      announce("Renamed");
    } catch (error) {
      announce(error.message, true);
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

  // ------------------------------------------------------------------ init

  function wireEvents() {
    elements.newNotebookButton.addEventListener("click", () => void createNotebook());
    elements.emptyNewButton.addEventListener("click", () => void createNotebook());
    elements.notebookTitle.addEventListener("change", () => void saveTitle());
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
          const workPath = elements.linkPathInput.value.trim();
          const result = await api(`/api/study/notebook/${encodeURIComponent(state.currentId)}/link`, {
            method: "POST",
            mutate: true,
            body: JSON.stringify({ workPath }),
          });
          state.revision = result.notebookUpdatedAt;
          const notebook = state.notebooks.find((item) => item.id === state.currentId);
          if (notebook) notebook.workPath = workPath;
          renderWorkLink();
        } catch (error) {
          announce(error.message, true);
        }
      })();
    });
  }

  async function init() {
    cacheElements();
    wireEvents();
    try {
      const library = await api("/api/library");
      state.token = library.actionToken;
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
})();
