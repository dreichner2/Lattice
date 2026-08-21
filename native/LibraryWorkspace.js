"use strict";

(() => {
  const clamp = value => Math.min(1, Math.max(0, Number(value) || 0));
  const safeText = (value, limit = 20000) => String(value ?? "").trim().slice(0, limit);
  const canonicalJSON = value => {
    if (Array.isArray(value)) return `[${value.map(canonicalJSON).join(",")}]`;
    if (value && typeof value === "object") {
      return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJSON(value[key])}`).join(",")}}`;
    }
    return JSON.stringify(value);
  };
  const normalizeDocument = detail => {
    const path = safeText(detail?.path, 4000);
    if (!path || !/^(books|papers)\/.+\.(pdf|epub|txt)$/i.test(path)) return null;
    if (path.includes("\\") || path.split("/").some(part => !part || part === "." || part === "..")) return null;
    return {
      workId: safeText(detail.workId, 1000) || null,
      path,
      sha256: safeText(detail.sha256, 128) || null,
      title: safeText(detail.title, 2000) || path.split("/").pop().replace(/\.[^.]+$/, ""),
      format: safeText(detail.format, 20).toLowerCase() || path.split(".").pop().toLowerCase(),
    };
  };
  const normalizePosition = detail => ({
    locator: detail?.locator && typeof detail.locator === "object" ? detail.locator : {},
    page: Number.isInteger(detail?.page) ? detail.page : null,
    progress: clamp(detail?.progress),
    updatedAt: Date.now() / 1000,
  });

  const exported = { canonicalJSON, clamp, normalizeDocument, normalizePosition };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  if (typeof window === "undefined" || typeof document === "undefined") return;
  window.__CS_LIBRARY_WORKSPACE_TEST__ = exported;

  let active = null;
  let annotations = [];
  let saveTimer = 0;
  const call = (action, payload = {}) => window.csLibraryNativeCall?.(action, payload);
  const bridgeAvailable = () => typeof window.csLibraryNativeCall === "function";

  const style = document.createElement("style");
  style.id = "cs-library-workspace-style";
  style.textContent = `
    #csWorkspaceButton{position:fixed;z-index:120;right:18px;bottom:18px;display:none;min-height:38px;padding:0 14px;border:1px solid rgba(255,255,255,.14);border-radius:999px;background:#242833;color:#fff;box-shadow:0 12px 38px rgba(0,0,0,.28);font:700 11px/1 -apple-system,BlinkMacSystemFont,sans-serif;cursor:pointer}
    body.reader-open #csWorkspaceButton{display:block}.cs-workspace{position:fixed;z-index:121;inset:0 0 0 auto;display:flex;width:min(430px,94vw);flex-direction:column;background:color-mix(in srgb,var(--panel-solid,#fff) 97%,transparent);color:var(--ink,#222);border-left:1px solid var(--line,#ddd);box-shadow:-28px 0 80px rgba(0,0,0,.25);transform:translateX(104%);transition:transform .2s ease;backdrop-filter:blur(24px)}
    .cs-workspace.is-open{transform:translateX(0)}.cs-workspace header{display:flex;align-items:center;justify-content:space-between;padding:17px;border-bottom:1px solid var(--line,#ddd)}.cs-workspace h2{margin:0;font:700 20px/1.2 Georgia,serif}.cs-workspace button{cursor:pointer}.cs-workspace-close{width:32px;height:32px;border:1px solid var(--line,#ddd);border-radius:9px;background:transparent;color:inherit;font-size:19px}
    .cs-workspace-search{margin:14px;padding:10px 12px;border:1px solid var(--line,#ddd);border-radius:10px;background:var(--panel,#fff);color:inherit}.cs-workspace-list{min-height:0;overflow:auto;padding:0 14px 18px}.cs-workspace-empty{padding:30px 10px;color:var(--muted,#777);font-size:12px;text-align:center}.cs-workspace-note{margin-top:9px;padding:12px;border:1px solid var(--line,#ddd);border-radius:11px;background:var(--panel,#fff)}.cs-workspace-note blockquote{margin:0 0 8px;padding-left:9px;border-left:3px solid #d6a62b;color:var(--muted,#666);font:12px/1.45 Georgia,serif}.cs-workspace-note p{margin:0;white-space:pre-wrap;font:12px/1.5 -apple-system,BlinkMacSystemFont,sans-serif}.cs-workspace-note small{display:block;margin-top:8px;color:var(--faint,#888);font-size:9px}.cs-workspace-error{margin:0 14px 12px;color:#a33;font-size:10px}
  `;

  const button = document.createElement("button");
  button.id = "csWorkspaceButton";
  button.type = "button";
  button.textContent = "Notebook";
  button.title = "Open reading notebook (Command-Shift-N)";

  const panel = document.createElement("aside");
  panel.className = "cs-workspace";
  panel.setAttribute("aria-label", "Reading notebook");
  const header = document.createElement("header");
  const heading = document.createElement("h2");
  heading.textContent = "Reading notebook";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "cs-workspace-close";
  close.setAttribute("aria-label", "Close notebook");
  close.textContent = "×";
  header.append(heading, close);
  const search = document.createElement("input");
  search.className = "cs-workspace-search";
  search.type = "search";
  search.placeholder = "Search notes and indexed text";
  const error = document.createElement("p");
  error.className = "cs-workspace-error";
  const list = document.createElement("div");
  list.className = "cs-workspace-list";
  panel.append(header, search, error, list);

  const render = items => {
    list.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "cs-workspace-empty";
      empty.textContent = active ? "No notes yet. Select text in the reader and add a note." : "Open a book to see its notes.";
      list.append(empty);
      return;
    }
    for (const item of items) {
      const card = document.createElement("article");
      card.className = "cs-workspace-note";
      if (item.quote || item.snippet) {
        const quote = document.createElement("blockquote");
        quote.textContent = item.quote || item.snippet;
        card.append(quote);
      }
      if (item.note || item.title) {
        const text = document.createElement("p");
        text.textContent = item.note || item.title;
        card.append(text);
      }
      const meta = document.createElement("small");
      meta.textContent = item.locator || item.kind || "Reader note";
      card.append(meta);
      list.append(card);
    }
  };

  const showError = value => { error.textContent = value ? String(value) : ""; };
  const refreshAnnotations = async () => {
    if (!active?.id) return render([]);
    try {
      annotations = await call("annotation.list", { documentId: active.id }) || [];
      render(annotations);
      showError("");
    } catch (reason) { showError(reason); }
  };

  const activate = async raw => {
    const normalized = normalizeDocument(raw);
    if (!normalized || !bridgeAvailable()) return;
    try {
      active = await call("document.upsert", normalized);
      const saved = await call("position.get", { documentId: active.id });
      if (saved) {
        let locator = saved.locator;
        if (typeof locator === "string") {
          try { locator = JSON.parse(locator); } catch { locator = {}; }
        }
        window.dispatchEvent(new CustomEvent("cs-library-reader-restore", {
          detail: { path: active.path, locator, page: saved.page, progress: saved.progress },
        }));
      }
      await refreshAnnotations();
      window.dispatchEvent(new CustomEvent("cs-library-reader-store-ready", { detail: active }));
      showError("");
    } catch (reason) { showError(reason); }
  };

  const savePosition = raw => {
    if (!active?.id) return;
    window.clearTimeout(saveTimer);
    const position = normalizePosition(raw);
    saveTimer = window.setTimeout(() => call("position.save", { documentId: active.id, ...position }).catch(showError), 180);
  };

  button.addEventListener("click", () => { panel.classList.toggle("is-open"); if (panel.classList.contains("is-open")) refreshAnnotations(); });
  close.addEventListener("click", () => panel.classList.remove("is-open"));
  search.addEventListener("input", async () => {
    const query = search.value.trim();
    if (!query) return render(annotations);
    if (query.length < 2) return;
    try { render(await call("search.query", { query, limit: 80 }) || []); showError(""); }
    catch (reason) { showError(reason); }
  });

  window.addEventListener("cs-library-reader-document", event => activate(event.detail));
  window.addEventListener("cs-library-reader-position", event => savePosition(event.detail));
  window.addEventListener("cs-library-reader-bookmark-toggle", async event => {
    if (!active?.id) return;
    const detail = event.detail || {};
    const locator = detail.locator || {};
    const existing = (await call("bookmark.list", { documentId: active.id }) || []).find(item => {
      try { return canonicalJSON(JSON.parse(item.locator)) === canonicalJSON(locator); } catch { return false; }
    });
    if (detail.bookmarked && !existing) {
      await call("bookmark.save", { documentId: active.id, locator, label: detail.label || "Saved position" });
    } else if (!detail.bookmarked && existing) {
      await call("bookmark.delete", { id: existing.id });
    }
  });
  window.addEventListener("cs-library-reader-save-annotation", async event => {
    if (!active?.id) return;
    try {
      await call("annotation.save", { documentId: active.id, ...(event.detail || {}) });
      await refreshAnnotations();
      window.dispatchEvent(new CustomEvent("cs-library-reader-annotation-saved"));
    } catch (reason) { showError(reason); }
  });
  window.addEventListener("cs-library-reader-delete-annotation", async event => {
    const id = safeText(event.detail?.id, 2000);
    if (!active?.id || !id) return;
    try { await call("annotation.delete", { id }); await refreshAnnotations(); }
    catch (reason) { showError(reason); }
  });
  window.addEventListener("cs-library-reader-index", async event => {
    if (!active?.id) return;
    const item = event.detail || {};
    try {
      await call("search.index", { documentId: active.id, items: [{
        id: safeText(item.id, 4000), kind: "chapter", title: safeText(item.title, 2000), body: safeText(item.body, 200000),
      }] });
    } catch (reason) { showError(reason); }
  });
  window.addEventListener("cs-library-reader-annotation-changed", refreshAnnotations);
  window.addEventListener("cs-library-reader-closed", () => {
    window.clearTimeout(saveTimer);
    call("session.finish", {}).catch(() => {});
    active = null;
    annotations = [];
    panel.classList.remove("is-open");
    render([]);
  });
  document.addEventListener("keydown", event => {
    if (!(event.metaKey || event.ctrlKey) || !event.shiftKey || event.key.toLowerCase() !== "n") return;
    event.preventDefault();
    button.click();
  }, true);

  (document.head || document.documentElement).append(style);
  document.body.append(button, panel);
  render([]);
  window.dispatchEvent(new CustomEvent("cs-library-workspace-ready"));
})();
