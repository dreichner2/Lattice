(() => {
  const style = (id, css) => {
    if (document.getElementById(id)) return;
    const node = document.createElement("style");
    node.id = id;
    node.textContent = css;
    (document.head || document.documentElement).append(node);
  };

  const focusContentsSearch = targetDocument => {
    const toggle = targetDocument.querySelector("#readerTocButton:not([hidden])");
    if (toggle?.getAttribute("aria-expanded") !== "true") toggle?.click();
    setTimeout(() => targetDocument.querySelector("#epubTocSearch")?.focus(), 220);
  };

  if (window.top !== window) {
    style("cs-native-epub-page", `
      html{scrollbar-width:none!important}html::-webkit-scrollbar{display:none!important}
      body{-webkit-font-smoothing:antialiased!important;text-rendering:optimizeLegibility!important}
      ::selection{background:rgba(103,119,235,.27)!important}
    `);
    document.addEventListener("dblclick", event => {
      if (!event.target.closest("a,button,input,textarea,select")) {
        window.top.document.querySelector("#readerFocusButton:not([hidden])")?.click();
      }
    });
    document.addEventListener("mouseup", () => {
      const text = window.getSelection()?.toString().trim() || "";
      if (!text) return;
      const source = window.top.document.querySelector("#epubChapterLabel")?.textContent || document.title || "";
      window.top.postMessage({ type: "cs-library-reader-selection", text, source }, window.location.origin);
    });
    document.addEventListener("keydown", event => {
      if (["input", "textarea", "select"].includes(event.target?.tagName?.toLowerCase()) || event.target?.isContentEditable) return;
      const topDocument = window.top.document;
      if (event.metaKey && event.key.toLowerCase() === "f") {
        event.preventDefault();
        focusContentsSearch(topDocument);
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const keyName = event.key.toLowerCase();
      const selector = event.code === "Space"
        ? (event.shiftKey ? "#epubPrevious" : "#epubNext")
        : ({ f: "#readerFocusButton:not([hidden])", b: "#readerBookmarkButton:not([hidden])", t: "#readerTocButton:not([hidden])", a: "#readerSettingsButton:not([hidden])", n: "#nativeReaderNotesButton" })[keyName];
      if (selector) { event.preventDefault(); topDocument.querySelector(selector)?.click(); }
    }, true);
    return;
  }

  document.documentElement.classList.add("cs-native-reader");
  window.csLibraryFocusEpubSearch = () => focusContentsSearch(document);
  // Native-reader chrome is declared in ui/styles.css. The main page CSP only
  // permits same-origin stylesheets, so an injected inline <style> is blocked.

  const key = "cs-library:native-reader-notes";
  let started = 0;
  let timer = 0;
  let selection = "";
  let selectionSource = "";
  const $ = selector => document.querySelector(selector);
  const bookKey = () => ($("#readerTitle")?.textContent || "Untitled").trim();
  const chapter = () => ($("#epubChapterLabel")?.textContent || "").trim();
  const read = () => { try { return JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch { return {}; } };
  const write = value => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch {
      return false;
    }
  };
  if (window.__CS_LIBRARY_TEST__) window.__CS_LIBRARY_TEST__.writeNotes = write;

  const renderNotes = () => {
    const list = $(".native-note-list");
    if (!list) return;
    const notes = read()[bookKey()] || [];
    list.replaceChildren();
    if (!notes.length) {
      const empty = document.createElement("div");
      empty.className = "native-note-empty";
      empty.textContent = "Select a passage or write a note. Everything stays in this app on this Mac.";
      list.append(empty);
      return;
    }
    [...notes].sort((a, b) => b.createdAt - a.createdAt).forEach(note => {
      const card = document.createElement("article");
      card.className = "native-note-card";
      const body = document.createElement("div");
      if (note.quote) { const quote = document.createElement("blockquote"); quote.textContent = note.quote; body.append(quote); }
      if (note.note) { const text = document.createElement("p"); text.textContent = note.note; body.append(text); }
      const meta = document.createElement("small");
      meta.textContent = [note.chapter, new Date(note.createdAt).toLocaleString()].filter(Boolean).join(" · ");
      body.append(meta);
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "native-note-delete"; remove.textContent = "×"; remove.setAttribute("aria-label", "Delete note");
      remove.addEventListener("click", () => {
        const all = read();
        all[bookKey()] = (all[bookKey()] || []).filter(item => item.id !== note.id);
        if (write(all)) renderNotes();
      });
      card.append(body, remove); list.append(card);
    });
  };

  const ensureUI = () => {
    const reader = $("#epubReader");
    const actions = $(".reader-actions");
    if (!reader || !actions) return;
    if (!$("#nativeReadingSession")) { const pill = document.createElement("span"); pill.id = "nativeReadingSession"; pill.textContent = "Reading 0m"; actions.prepend(pill); }
    if (!reader.querySelector(".native-reader-shortcuts")) { const hint = document.createElement("div"); hint.className = "native-reader-shortcuts"; hint.textContent = "Space page · F focus · B bookmark · T contents · N notes"; reader.append(hint); }
    if (!$("#nativeReaderNotesButton")) {
      const button = document.createElement("button");
      button.type = "button"; button.id = "nativeReaderNotesButton"; button.className = "reader-tool-button"; button.textContent = "✎"; button.title = "Quotes and notes (N)";
      button.addEventListener("click", () => { $(".native-notes")?.classList.toggle("is-open"); renderNotes(); });
      actions.insertBefore(button, $("#readerMacButton"));
    }
    if (reader.querySelector(".native-notes")) return;

    const panel = document.createElement("aside"); panel.className = "native-notes"; panel.setAttribute("aria-label", "Quotes and notes");
    const header = document.createElement("header");
    const heading = document.createElement("div");
    const overline = document.createElement("span"); overline.textContent = "Study while you read";
    const title = document.createElement("strong"); title.textContent = "Quotes & notes"; heading.append(overline, title);
    const close = document.createElement("button"); close.type = "button"; close.className = "native-notes-close"; close.textContent = "×"; close.addEventListener("click", () => panel.classList.remove("is-open"));
    header.append(heading, close);
    const compose = document.createElement("div"); compose.className = "native-note-compose";
    const quote = document.createElement("div"); quote.className = "native-note-quote";
    const input = document.createElement("textarea"); input.className = "native-note-input"; input.placeholder = "Write a note about this page or passage…";
    input.addEventListener("input", () => input.setCustomValidity(""));
    const save = document.createElement("button"); save.type = "button"; save.className = "native-note-save"; save.textContent = "Save to this book";
    save.addEventListener("click", () => {
      const note = input.value.trim(); if (!note && !selection) return;
      const all = read(); const name = bookKey(); const notes = all[name] || [];
      notes.push({ id: `${Date.now()}-${Math.random().toString(16).slice(2)}`, quote: selection, note, chapter: selectionSource || chapter(), createdAt: Date.now() });
      all[name] = notes.slice(-250);
      if (!write(all)) {
        input.setCustomValidity("This note could not be saved. Free some local storage and try again.");
        input.reportValidity();
        return;
      }
      input.setCustomValidity(""); input.value = ""; selection = ""; selectionSource = ""; quote.textContent = ""; quote.classList.remove("has-selection"); $("#nativeReaderNotesButton")?.classList.remove("has-selection"); renderNotes();
    });
    compose.append(quote, input, save);
    const list = document.createElement("div"); list.className = "native-note-list";
    panel.append(header, compose, list); reader.append(panel);
  };

  window.addEventListener("message", event => {
    if (event.origin !== location.origin || event.data?.type !== "cs-library-reader-selection") return;
    selection = String(event.data.text || "").trim().slice(0, 4000);
    selectionSource = String(event.data.source || chapter()).trim();
    const quote = $(".native-note-quote"); if (quote) { quote.textContent = selection; quote.classList.toggle("has-selection", !!selection); }
    $("#nativeReaderNotesButton")?.classList.toggle("has-selection", !!selection);
  });

  const sync = () => {
    const active = document.body.classList.contains("reader-open") && $("#readerShell")?.classList.contains("is-epub");
    const pill = $("#nativeReadingSession"); const notes = $("#nativeReaderNotesButton");
    if (!active) {
      started = 0; clearInterval(timer); timer = 0; selection = ""; selectionSource = "";
      if (pill) pill.hidden = true; if (notes) { notes.hidden = true; notes.classList.remove("has-selection"); }
      $(".native-notes")?.classList.remove("is-open"); return;
    }
    ensureUI(); $("#nativeReadingSession")?.removeAttribute("hidden"); $("#nativeReaderNotesButton")?.removeAttribute("hidden"); renderNotes();
    if (!started) started = Date.now();
    if (!timer) timer = setInterval(() => { const minutes = Math.floor((Date.now() - started) / 60000); const node = $("#nativeReadingSession"); if (node) node.textContent = minutes < 60 ? `Reading ${minutes}m` : `Reading ${Math.floor(minutes / 60)}h ${minutes % 60}m`; }, 15000);
  };

  document.addEventListener("keydown", event => {
    const active = document.body.classList.contains("reader-open") && $("#readerShell")?.classList.contains("is-epub");
    if (!active || ["input", "textarea", "select"].includes(event.target?.tagName?.toLowerCase()) || event.target?.isContentEditable) return;
    if (event.metaKey && event.key.toLowerCase() === "f") { event.preventDefault(); focusContentsSearch(document); return; }
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const keyName = event.key.toLowerCase();
    if (event.code === "Space") { event.preventDefault(); $(event.shiftKey ? "#epubPrevious" : "#epubNext")?.click(); }
    else if (keyName === "f") { event.preventDefault(); $("#readerFocusButton:not([hidden])")?.click(); }
    else if (keyName === "b") { event.preventDefault(); $("#readerBookmarkButton:not([hidden])")?.click(); }
    else if (keyName === "t") { event.preventDefault(); $("#readerTocButton:not([hidden])")?.click(); }
    else if (keyName === "a") { event.preventDefault(); $("#readerSettingsButton:not([hidden])")?.click(); }
    else if (keyName === "n") { event.preventDefault(); $("#nativeReaderNotesButton")?.click(); }
  }, true);

  const install = () => {
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    const shell = $("#readerShell"); if (shell) observer.observe(shell, { attributes: true, attributeFilter: ["class", "aria-hidden"] });
  };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", install, { once: true }) : install();
})();
