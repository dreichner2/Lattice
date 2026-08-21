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
  style("cs-native-reader-ui", `
    html.cs-native-reader .reader-shell.is-epub .reader-panel{inset:0!important;border:0!important;border-radius:0!important;background:#111318!important}
    html.cs-native-reader .reader-shell.is-epub .reader-toolbar{min-height:56px!important;background:color-mix(in srgb,var(--panel-solid) 86%,transparent)!important;box-shadow:0 8px 30px rgba(0,0,0,.08)!important}
    html.cs-native-reader .reader-shell.is-epub .epub-frame-wrap{padding:clamp(12px,2.3vh,28px) clamp(18px,3vw,50px) 8px!important}
    html.cs-native-reader .reader-shell.is-epub .epub-frame{border-radius:10px!important;box-shadow:0 28px 80px rgba(23,25,31,.22),0 4px 12px rgba(23,25,31,.1)!important}
    html.cs-native-reader .reader-shell.is-epub .epub-footer{min-height:64px!important;padding-bottom:10px!important}
    html.cs-native-reader .reader-shell.is-focused .epub-frame-wrap{padding:8px!important}
    html.cs-native-reader .reader-shell.is-focused .epub-frame{border:0!important;border-radius:0!important;box-shadow:none!important}
    #nativeReadingSession{display:inline-flex;min-height:30px;align-items:center;gap:6px;padding:0 10px;border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--muted);font-size:8px;font-weight:760;white-space:nowrap}
    #nativeReadingSession:before{content:"";width:5px;height:5px;border-radius:50%;background:var(--success);box-shadow:0 0 0 3px color-mix(in srgb,var(--success) 13%,transparent)}
    #nativeReaderNotesButton{font-size:14px!important}#nativeReaderNotesButton.has-selection{border-color:color-mix(in srgb,var(--accent) 46%,var(--line))!important;background:var(--accent-soft)!important;color:var(--accent-ink)!important}
    .native-notes{position:absolute;z-index:42;inset:0 0 0 auto;display:flex;width:min(390px,90vw);flex-direction:column;overflow:hidden;border-left:1px solid var(--line);background:color-mix(in srgb,var(--panel-solid) 96%,transparent);color:var(--ink);box-shadow:-24px 0 70px rgba(0,0,0,.22);backdrop-filter:blur(24px);transform:translateX(103%);transition:transform .25s cubic-bezier(.2,.75,.25,1)}
    .native-notes.is-open{transform:translateX(0)}.native-notes header{display:flex;min-height:68px;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--line)}
    .native-notes header span,.native-notes header strong{display:block}.native-notes header span{color:var(--faint);font-size:7px;font-weight:840;letter-spacing:.13em;text-transform:uppercase}.native-notes header strong{margin-top:3px;font-family:Georgia,serif;font-size:18px}
    .native-notes-close,.native-note-delete{display:grid;place-items:center;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--ink);cursor:pointer}.native-notes-close{width:32px;height:32px;font-size:18px}
    .native-note-compose{display:grid;gap:9px;padding:14px;border-bottom:1px solid var(--line)}.native-note-quote{display:none;max-height:92px;overflow:auto;padding:10px 11px;border-left:3px solid var(--accent);border-radius:0 9px 9px 0;background:var(--accent-soft);color:var(--accent-ink);font:11px/1.5 Georgia,serif}.native-note-quote.has-selection{display:block}
    .native-note-input{min-height:88px;resize:vertical;padding:10px 11px;border:1px solid var(--line);border-radius:10px;outline:0;background:var(--panel);color:var(--ink);font:11px/1.5 -apple-system,BlinkMacSystemFont,sans-serif}.native-note-input:focus{border-color:color-mix(in srgb,var(--accent) 48%,var(--line))}
    .native-note-save{min-height:36px;border:1px solid var(--accent-deep);border-radius:9px;background:var(--accent-deep);color:#fff;cursor:pointer;font-size:9px;font-weight:760}.native-note-list{min-height:0;overflow-y:auto;padding:12px}.native-note-empty{padding:36px 15px;color:var(--muted);font-size:10px;line-height:1.55;text-align:center}
    .native-note-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;padding:11px;border:1px solid var(--line);border-radius:11px;background:var(--panel)}.native-note-card+.native-note-card{margin-top:8px}.native-note-card blockquote{margin:0 0 7px;color:var(--muted);font:10px/1.45 Georgia,serif}.native-note-card p{margin:0;font-size:10px;line-height:1.5}.native-note-card small{display:block;margin-top:8px;color:var(--faint);font-size:7px}.native-note-delete{width:27px;height:27px;font-size:14px}
    .native-reader-shortcuts{position:absolute;z-index:12;right:18px;bottom:72px;padding:7px 10px;border:1px solid rgba(255,255,255,.1);border-radius:999px;background:rgba(17,19,24,.62);color:rgba(255,255,255,.72);font-size:7px;font-weight:720;pointer-events:none;backdrop-filter:blur(12px)}
    .reader-shell.is-focused .native-reader-shortcuts,.reader-shell.is-focused #nativeReadingSession,.reader-shell.is-focused #nativeReaderNotesButton{opacity:0!important;pointer-events:none!important}@media(max-width:760px){#nativeReadingSession,.native-reader-shortcuts{display:none!important}}
  `);

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
