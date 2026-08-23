(function () {
  "use strict";

  const STORAGE = Object.freeze({
    model: "cs-library:tutor-model",
    effort: "cs-library:tutor-effort",
    scope: "cs-library:tutor-scope",
    works: "cs-library:tutor-works",
    courses: "cs-library:tutor-courses",
  });
  const MODELS = new Set(["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]);
  const EFFORTS = new Set(["low", "medium", "high", "xhigh", "max"]);
  const SESSION_ID = /^[A-Za-z0-9_-]{20,160}$/;

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
      // Tutor preferences are optional and may remain session-only.
    }
  }

  function element(tag, className = "", text) {
    const value = document.createElement(tag);
    if (className) value.className = className;
    if (text !== undefined) value.textContent = text;
    return value;
  }

  function safeIdList(value, maximum = 48) {
    if (!Array.isArray(value)) return [];
    return value
      .filter((item, index) => typeof item === "string" && item && item.length <= 200 && value.indexOf(item) === index)
      .slice(0, maximum);
  }

  function appendInline(parent, text) {
    text = String(text || "");
    const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[0-9]{1,2}\])/g;
    let offset = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > offset) parent.append(document.createTextNode(text.slice(offset, match.index)));
      const token = match[0];
      if (token.startsWith("`")) parent.append(element("code", "", token.slice(1, -1)));
      else if (token.startsWith("**")) parent.append(element("strong", "", token.slice(2, -2)));
      else parent.append(element("sup", "", token));
      offset = match.index + token.length;
    }
    if (offset < text.length) parent.append(document.createTextNode(text.slice(offset)));
  }

  function renderTutorText(text) {
    const fragment = document.createDocumentFragment();
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    let index = 0;
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
        const pre = element("pre");
        const codeNode = element("code", "", code.join("\n"));
        if (fence[1]) codeNode.dataset.language = fence[1];
        pre.append(codeNode);
        fragment.append(pre);
        continue;
      }
      const heading = line.match(/^\s*(#{1,4})\s+(.+)$/);
      if (heading) {
        const headingNode = element(heading[1].length < 3 ? "h3" : "h4");
        appendInline(headingNode, heading[2].replace(/\s+#+\s*$/, ""));
        fragment.append(headingNode);
        index += 1;
        continue;
      }
      if (/^\s*>\s?/.test(line)) {
        const quote = [];
        while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
          quote.push(lines[index++].replace(/^\s*>\s?/, ""));
        }
        const blockquote = element("blockquote");
        appendInline(blockquote, quote.join(" "));
        fragment.append(blockquote);
        continue;
      }
      const list = line.match(/^\s*([-*+] |\d+[.)] )(.+)$/);
      if (list) {
        const ordered = /^\d/.test(list[1]);
        const listNode = element(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const item = lines[index].match(/^\s*([-*+] |\d+[.)] )(.+)$/);
          if (!item || /^\d/.test(item[1]) !== ordered) break;
          const itemNode = element("li");
          appendInline(itemNode, item[2]);
          listNode.append(itemNode);
          index += 1;
        }
        fragment.append(listNode);
        continue;
      }
      const paragraphLines = [line.trim()];
      index += 1;
      while (
        index < lines.length
        && lines[index].trim()
        && !/^\s*(```|#{1,4}\s|>\s?|[-*+] |\d+[.)] )/.test(lines[index])
      ) {
        paragraphLines.push(lines[index++].trim());
      }
      const paragraph = element("p");
      appendInline(paragraph, paragraphLines.join(" "));
      fragment.append(paragraph);
    }
    return fragment;
  }

  function create(options = {}) {
    const elements = {
      close: document.querySelector("#tutorCloseButton"),
      conversation: document.querySelector("#tutorConversation"),
      clearSources: document.querySelector("#tutorClearSources"),
      effort: document.querySelector("#tutorEffortSelect"),
      expand: document.querySelector("#tutorExpandButton"),
      form: document.querySelector("#tutorForm"),
      headingContext: document.querySelector("#tutorHeadingContext"),
      input: document.querySelector("#tutorInput"),
      launch: document.querySelector("#tutorOpenButton"),
      model: document.querySelector("#tutorModelSelect"),
      newConversation: document.querySelector("#tutorNewButton"),
      panel: document.querySelector("#tutorPanel"),
      peekHeading: document.querySelector("#tutorPeekHeading"),
      peekNote: document.querySelector("#tutorPeekNote"),
      runtime: document.querySelector("#tutorRuntimeStatus"),
      scopeButton: document.querySelector("#tutorScopeButton"),
      scopeLabel: document.querySelector("#tutorScopeLabel"),
      scrim: document.querySelector("#tutorScrim"),
      send: document.querySelector("#tutorSendButton"),
      sourceApply: document.querySelector("#tutorSourceApply"),
      sourceCancel: document.querySelector("#tutorSourceCancel"),
      sourceClose: document.querySelector("#tutorSourceClose"),
      sourceList: document.querySelector("#tutorSourceList"),
      sourceSearch: document.querySelector("#tutorSourceSearch"),
      sourceSheet: document.querySelector("#tutorSourceSheet"),
      selectedCount: document.querySelector("#tutorSelectedCount"),
      welcome: document.querySelector("#tutorWelcome"),
    };
    if (Object.values(elements).some((value) => !value)) return null;

    const savedModel = readStorage(STORAGE.model, "gpt-5.6-luna");
    const savedEffort = readStorage(STORAGE.effort, "medium");
    const savedScope = readStorage(STORAGE.scope, "all");
    const state = {
      token: "",
      library: null,
      catalog: null,
      model: MODELS.has(savedModel) ? savedModel : "gpt-5.6-luna",
      effort: EFFORTS.has(savedEffort) ? savedEffort : "medium",
      scope: savedScope === "selected" ? "selected" : "all",
      workIds: new Set(safeIdList(readStorage(STORAGE.works, []))),
      courseIds: new Set(safeIdList(readStorage(STORAGE.courses, []))),
      draftScope: "all",
      draftWorkIds: new Set(),
      draftCourseIds: new Set(),
      sessionId: "",
      messages: [],
      ready: false,
      busy: false,
      destroyed: false,
      lastFocus: null,
      requestController: null,
      statusTimer: 0,
      presentation: "full",
      contextSession: "",
    };

    elements.model.value = state.model;
    elements.effort.value = state.effort;

    function workMap() {
      return new Map((state.library?.works || []).map((work) => [String(work.id), work]));
    }

    function courseMap() {
      return new Map((state.catalog?.courses || []).map((course) => [String(course.id), course]));
    }

    function reconcileSelections() {
      const works = workMap();
      const courses = courseMap();
      state.workIds = new Set([...state.workIds].filter((id) => works.get(id)?.tutorEligible !== false));
      state.courseIds = new Set([...state.courseIds].filter((id) => courses.has(id)));
      persistScope();
      renderScopeLabel();
      renderPresentation();
    }

    function persistScope() {
      writeStorage(STORAGE.scope, state.scope);
      writeStorage(STORAGE.works, [...state.workIds]);
      writeStorage(STORAGE.courses, [...state.courseIds]);
    }

    function setRuntime(mode, message) {
      elements.runtime.dataset.status = mode;
      elements.runtime.querySelector("p").textContent = message;
    }

    function updateComposer() {
      const hasText = Boolean(elements.input.value.trim());
      const hasSources = state.scope === "all" || state.workIds.size + state.courseIds.size > 0;
      elements.input.disabled = !state.ready || state.busy;
      elements.send.disabled = !state.ready || state.busy || !hasText || !hasSources;
      elements.send.setAttribute("aria-label", state.busy ? "Tutor is thinking" : "Send to Lattice Tutor");
    }

    function autoSizeInput() {
      elements.input.style.height = "auto";
      elements.input.style.height = `${Math.min(145, Math.max(42, elements.input.scrollHeight))}px`;
      updateComposer();
    }

    function renderScopeLabel() {
      if (state.scope === "all") {
        elements.scopeLabel.textContent = "Whole library";
        return;
      }
      const total = state.workIds.size + state.courseIds.size;
      elements.scopeLabel.textContent = total === 1 ? "1 selected source" : `${total} selected sources`;
    }

    function scrollConversation() {
      window.requestAnimationFrame(() => {
        elements.conversation.scrollTop = elements.conversation.scrollHeight;
      });
    }

    function renderMessages() {
      const children = [];
      if (!state.messages.length) {
        elements.welcome.hidden = false;
        elements.conversation.replaceChildren(elements.welcome);
        return;
      }
      elements.welcome.hidden = true;
      for (const message of state.messages) {
        if (message.role === "error") {
          const error = element("div", "tutor-message-error", message.text);
          error.setAttribute("role", "alert");
          children.push(error);
          continue;
        }
        const item = element("article", `tutor-message ${message.role === "user" ? "is-user" : "is-tutor"}`);
        item.append(element("div", "tutor-message-label", message.role === "user" ? "You" : "Lattice Tutor"));
        const bubble = element("div", "tutor-message-bubble");
        if (message.role === "user") bubble.textContent = message.text;
        else bubble.append(renderTutorText(message.text));
        item.append(bubble);
        if (message.role === "tutor" && message.citations?.length) {
          const citations = element("div", "tutor-citations");
          for (const citation of message.citations) {
            const citationButton = element("button", "tutor-citation");
            citationButton.type = "button";
            citationButton.title = citation.locator ? `${citation.title} — ${citation.locator}` : citation.title;
            citationButton.append(
              element("span", "", String(citation.number || citations.childElementCount + 1)),
              element("strong", "", citation.locator ? `${citation.title} · ${citation.locator}` : citation.title),
            );
            citationButton.addEventListener("click", () => options.onOpenCitation?.(citation));
            citations.append(citationButton);
          }
          item.append(citations);
        }
        children.push(item);
      }
      if (state.busy) {
        const typingMessage = element("article", "tutor-message is-tutor");
        typingMessage.append(element("div", "tutor-message-label", "Lattice Tutor"));
        const typing = element("div", "tutor-typing");
        typing.setAttribute("aria-label", "Tutor is thinking");
        typing.append(element("span"), element("span"), element("span"));
        typingMessage.append(typing);
        children.push(typingMessage);
      }
      elements.conversation.replaceChildren(...children);
      scrollConversation();
    }

    function selectedCountText() {
      const count = state.draftWorkIds.size + state.draftCourseIds.size;
      return count === 1 ? "1 selected" : `${count} selected`;
    }

    function sourceSearchText(item) {
      return [item.title, item.authors, item.subject, item.topic, item.institution, item.code]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase();
    }

    function sourceOption(item, kind) {
      const isWork = kind === "work";
      const id = String(item.id);
      const restricted = isWork && item.tutorEligible === false;
      const selection = isWork ? state.draftWorkIds : state.draftCourseIds;
      const label = element("label", `tutor-source-option${selection.has(id) ? " is-selected" : ""}${restricted ? " is-restricted" : ""}`);
      const checkbox = element("input");
      checkbox.type = "checkbox";
      checkbox.checked = selection.has(id);
      checkbox.disabled = restricted;
      checkbox.setAttribute("aria-label", `${selection.has(id) ? "Remove" : "Add"} ${item.title}`);
      const copy = element("span", "tutor-source-option-copy");
      const detail = isWork
        ? [item.authors, item.subject, item.formats?.join(" / ")].filter(Boolean).join(" · ")
        : [item.institution, item.code, `${item.lectureCount || item.lectures?.length || 0} lectures`].filter(Boolean).join(" · ");
      copy.append(element("strong", "", item.title), element("small", "", restricted ? (item.tutorRestriction || "Reserved for human study") : detail));
      const badge = element("em", "", restricted ? "Study only" : isWork ? (item.formats?.[0] || "File") : "Video catalog");
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) selection.add(id);
        else selection.delete(id);
        state.draftScope = "selected";
        const selectedRadio = document.querySelector('input[name="tutorScopeMode"][value="selected"]');
        if (selectedRadio) selectedRadio.checked = true;
        renderSourceList();
      });
      label.append(checkbox, copy, badge);
      return label;
    }

    function renderSourceList() {
      const query = elements.sourceSearch.value.trim().toLocaleLowerCase();
      const groups = [];
      const works = [...(state.library?.works || [])]
        .filter((work) => !query || sourceSearchText(work).includes(query))
        .sort((left, right) => String(left.title).localeCompare(String(right.title)));
      const courses = [...(state.catalog?.courses || [])]
        .filter((course) => !query || sourceSearchText(course).includes(query))
        .sort((left, right) => String(left.title).localeCompare(String(right.title)));

      const workGroups = new Map();
      for (const work of works) {
        const groupName = work.kind === "paper" ? "Papers" : work.kind === "lecture" ? "Lecture notes" : "Books and local works";
        if (!workGroups.has(groupName)) workGroups.set(groupName, []);
        workGroups.get(groupName).push(work);
      }
      for (const [title, items] of workGroups) {
        const group = element("section", "tutor-source-group");
        group.append(element("h4", "", title), ...items.map((item) => sourceOption(item, "work")));
        groups.push(group);
      }
      if (courses.length) {
        const group = element("section", "tutor-source-group");
        group.append(element("h4", "", "Video courses · metadata only"), ...courses.map((item) => sourceOption(item, "course")));
        groups.push(group);
      }
      if (!groups.length) groups.push(element("div", "tutor-source-empty", "No books, papers, notes, or video courses match that search."));
      elements.sourceList.replaceChildren(...groups);
      elements.selectedCount.textContent = selectedCountText();
    }

    function openSourceSheet() {
      state.draftScope = state.scope;
      state.draftWorkIds = new Set(state.workIds);
      state.draftCourseIds = new Set(state.courseIds);
      elements.sourceSearch.value = "";
      const radio = document.querySelector(`input[name="tutorScopeMode"][value="${state.draftScope}"]`);
      if (radio) radio.checked = true;
      renderSourceList();
      elements.sourceSheet.hidden = false;
      elements.sourceSheet.setAttribute("aria-hidden", "false");
      elements.sourceSearch.focus();
    }

    function closeSourceSheet() {
      elements.sourceSheet.setAttribute("aria-hidden", "true");
      elements.sourceSheet.hidden = true;
      elements.scopeButton.focus();
    }

    async function post(path, payload, signal) {
      if (!state.token) throw new Error("The local library session is not ready yet");
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Library-Token": state.token,
        },
        body: JSON.stringify(payload),
        signal,
      });
      let value = {};
      try {
        value = await response.json();
      } catch {
        // The status code still supplies a useful generic error below.
      }
      if (!response.ok) throw new Error(value.error || `Tutor request failed (${response.status})`);
      return value;
    }

    function validSessionId() {
      return SESSION_ID.test(state.sessionId) ? state.sessionId : "";
    }

    function ensureSessionId() {
      if (validSessionId()) return state.sessionId;
      if (typeof crypto.randomUUID === "function") state.sessionId = crypto.randomUUID();
      else {
        const bytes = new Uint8Array(24);
        crypto.getRandomValues(bytes);
        state.sessionId = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
      }
      return state.sessionId;
    }

    function stopCurrentTurn() {
      if (!state.busy) return;
      const sessionId = validSessionId();
      if (sessionId) void post("/api/tutor/cancel", { sessionId }).catch(() => {});
      state.requestController?.abort();
      state.requestController = null;
      state.busy = false;
      setRuntime(state.ready ? "ready" : "error", state.ready ? "Tutor turn stopped" : "Tutor unavailable");
      renderMessages();
      updateComposer();
    }

    function resetConversation({ announce = false } = {}) {
      const sessionId = validSessionId();
      stopCurrentTurn();
      if (sessionId) void post("/api/tutor/reset", { sessionId }).catch(() => {});
      state.sessionId = "";
      state.messages = [];
      renderMessages();
      if (announce) options.announce?.("Started a new Tutor conversation");
    }

    function applySourceSheet() {
      if (state.draftScope === "selected" && state.draftWorkIds.size + state.draftCourseIds.size === 0) {
        options.announce?.("Select at least one Tutor source", true);
        return;
      }
      const previous = JSON.stringify([state.scope, [...state.workIds].sort(), [...state.courseIds].sort()]);
      state.scope = state.draftScope;
      state.workIds = new Set(state.draftWorkIds);
      state.courseIds = new Set(state.draftCourseIds);
      const next = JSON.stringify([state.scope, [...state.workIds].sort(), [...state.courseIds].sort()]);
      persistScope();
      renderScopeLabel();
      renderPresentation();
      closeSourceSheet();
      if (previous !== next) resetConversation();
      updateComposer();
    }

    async function refreshStatus() {
      if (state.destroyed) return;
      try {
        const response = await fetch("/api/tutor/status", { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `Tutor status failed (${response.status})`);
        state.ready = payload.ready === true;
        if (!state.busy) {
          const index = payload.index || {};
          const sourceCount = payload.sources?.eligibleWorks || 0;
          if (state.ready && index.indexing) {
            setRuntime("busy", `Indexing ${index.indexed || 0}/${index.total || sourceCount} eligible sources on this device`);
          } else if (state.ready) {
            setRuntime("ready", `${sourceCount} local works ready · ${payload.sources?.videoCourses || 0} video courses by metadata`);
          } else {
            setRuntime("error", payload.message || "Sign in to Codex on this computer to use Tutor");
          }
        }
      } catch (error) {
        state.ready = false;
        if (!state.busy) setRuntime("error", error.message || "Tutor status is unavailable");
      }
      updateComposer();
    }

    async function sendMessage(message) {
      const question = String(message || "").trim();
      if (!question || state.busy || !state.ready) return;
      if (state.scope === "selected" && state.workIds.size + state.courseIds.size === 0) {
        openSourceSheet();
        options.announce?.("Choose at least one Tutor source", true);
        return;
      }
      elements.input.value = "";
      autoSizeInput();
      state.messages.push({ role: "user", text: question });
      state.busy = true;
      setRuntime("busy", "Tutor is reading the chosen sources…");
      renderMessages();
      updateComposer();
      const controller = new AbortController();
      state.requestController = controller;
      const sessionId = ensureSessionId();
      try {
        const response = await post("/api/tutor/chat", {
          sessionId,
          message: question,
          model: state.model,
          effort: state.effort,
          scope: state.scope,
          workIds: [...state.workIds],
          courseIds: [...state.courseIds],
        }, controller.signal);
        if (response.sessionId && SESSION_ID.test(response.sessionId)) state.sessionId = response.sessionId;
        state.messages.push({
          role: "tutor",
          text: String(response.answer || "Tutor returned no answer."),
          citations: Array.isArray(response.citations) ? response.citations : [],
        });
        const scopeLabel = response.scope?.mode === "selected" ? "chosen sources" : "whole library";
        setRuntime("ready", response.grounded ? `Grounded in ${scopeLabel} · citations included` : `Answered from ${scopeLabel} · source limits noted`);
      } catch (error) {
        if (error.name !== "AbortError") {
          state.messages.push({ role: "error", text: error.message || "Tutor could not answer that question" });
          setRuntime("error", error.message || "Tutor turn failed");
        }
      } finally {
        if (state.requestController === controller) state.requestController = null;
        state.busy = false;
        renderMessages();
        updateComposer();
        if (document.body.classList.contains("tutor-open")) elements.input.focus();
      }
    }

    function renderPresentation() {
      const compact = state.presentation === "peek";
      const exactBook = state.scope === "selected" && state.workIds.size === 1 && state.courseIds.size === 0;
      const exactCourse = state.scope === "selected" && state.courseIds.size === 1 && state.workIds.size === 0;
      document.body.classList.toggle("tutor-peek", compact);
      document.body.classList.toggle("tutor-context-session", Boolean(state.contextSession));
      document.body.classList.toggle("tutor-reader-session", state.contextSession === "reader");
      document.body.classList.toggle("tutor-video-session", state.contextSession === "video");
      elements.headingContext.textContent = state.contextSession === "reader"
        ? (exactBook ? "This book only" : "Reading companion")
        : state.contextSession === "video"
          ? (exactCourse ? "This course only" : "Video companion")
          : "Optional study companion";
      elements.input.placeholder = state.contextSession === "reader" && exactBook
        ? "Ask about this book…"
        : state.contextSession === "video" && exactCourse
          ? "Ask about this course…"
          : "Ask about your library…";
      elements.peekHeading.textContent = state.contextSession === "reader" && exactBook
        ? "Ask about this book"
        : state.contextSession === "video" && exactCourse
          ? "Ask about this course"
          : "Ask about these sources";
      elements.peekNote.textContent = state.contextSession === "video"
        ? "Your lecture stays visible while you talk."
        : state.contextSession === "reader"
          ? "Your page stays open while you talk."
          : "Your library stays open while you talk.";
      elements.expand.textContent = compact ? "↗" : "↙";
      const sizeAction = compact ? "Expand Tutor" : "Make Tutor compact";
      elements.expand.setAttribute("aria-label", sizeAction);
      elements.expand.title = sizeAction;
    }

    function open({ presentation = "full", contextSession = presentation === "peek" ? "reader" : "" } = {}) {
      if (!document.body.classList.contains("tutor-open")) state.lastFocus = document.activeElement;
      state.presentation = presentation === "peek" ? "peek" : "full";
      state.contextSession = ["reader", "video"].includes(contextSession) ? contextSession : "";
      renderPresentation();
      document.body.classList.add("tutor-open");
      elements.panel.setAttribute("aria-hidden", "false");
      window.requestAnimationFrame(() => (
        state.presentation === "peek" || state.messages.length ? elements.input : elements.scopeButton
      ).focus());
      void refreshStatus();
    }

    function toggleSize() {
      if (!document.body.classList.contains("tutor-open") || !state.contextSession) return;
      state.presentation = state.presentation === "peek" ? "full" : "peek";
      renderPresentation();
      elements.input.focus({ preventScroll: true });
    }

    function close() {
      if (!document.body.classList.contains("tutor-open")) return false;
      if (!elements.sourceSheet.hidden) closeSourceSheet();
      document.body.classList.remove("tutor-open", "tutor-peek", "tutor-context-session", "tutor-reader-session", "tutor-video-session");
      state.presentation = "full";
      state.contextSession = "";
      renderPresentation();
      elements.panel.setAttribute("aria-hidden", "true");
      if (state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus();
      state.lastFocus = null;
      return true;
    }

    function setExactSource(kind, id, { presentation = "full" } = {}) {
      const stringId = String(id || "");
      if (!stringId) return false;
      if (kind === "work") {
        const work = workMap().get(stringId);
        if (!work) return false;
        if (work.tutorEligible === false) {
          options.announce?.(work.tutorRestriction || "This edition is reserved for human study", true);
          return false;
        }
        state.workIds = new Set([stringId]);
        state.courseIds = new Set();
      } else {
        if (!courseMap().has(stringId)) return false;
        state.workIds = new Set();
        state.courseIds = new Set([stringId]);
      }
      state.scope = "selected";
      persistScope();
      renderScopeLabel();
      resetConversation();
      open({
        presentation,
        contextSession: presentation === "peek" ? (kind === "course" ? "video" : "reader") : "",
      });
      return true;
    }

    elements.launch.addEventListener("click", open);
    elements.expand.addEventListener("click", toggleSize);
    elements.close.addEventListener("click", close);
    elements.scrim.addEventListener("click", close);
    elements.newConversation.addEventListener("click", () => resetConversation({ announce: true }));
    elements.scopeButton.addEventListener("click", openSourceSheet);
    elements.sourceClose.addEventListener("click", closeSourceSheet);
    elements.sourceCancel.addEventListener("click", closeSourceSheet);
    elements.sourceApply.addEventListener("click", applySourceSheet);
    elements.clearSources.addEventListener("click", () => {
      state.draftWorkIds.clear();
      state.draftCourseIds.clear();
      state.draftScope = "selected";
      const selectedRadio = document.querySelector('input[name="tutorScopeMode"][value="selected"]');
      if (selectedRadio) selectedRadio.checked = true;
      renderSourceList();
    });
    elements.sourceSearch.addEventListener("input", renderSourceList);
    document.querySelectorAll('input[name="tutorScopeMode"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        if (radio.checked) state.draftScope = radio.value === "selected" ? "selected" : "all";
      });
    });
    elements.model.addEventListener("change", () => {
      if (!MODELS.has(elements.model.value)) return;
      state.model = elements.model.value;
      writeStorage(STORAGE.model, state.model);
    });
    elements.effort.addEventListener("change", () => {
      if (!EFFORTS.has(elements.effort.value)) return;
      state.effort = elements.effort.value;
      writeStorage(STORAGE.effort, state.effort);
    });
    elements.input.addEventListener("input", autoSizeInput);
    elements.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        void sendMessage(elements.input.value);
      }
    });
    elements.form.addEventListener("submit", (event) => {
      event.preventDefault();
      void sendMessage(elements.input.value);
    });
    document.querySelectorAll("[data-tutor-prompt]").forEach((starter) => {
      starter.addEventListener("click", () => void sendMessage(starter.dataset.tutorPrompt));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !document.body.classList.contains("tutor-open")) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!elements.sourceSheet.hidden) closeSourceSheet();
      else close();
    }, true);
    const handleReaderClosed = () => {
      if (state.contextSession === "reader") close();
    };
    window.addEventListener("cs-library-reader-closed", handleReaderClosed);

    renderScopeLabel();
    renderMessages();
    autoSizeInput();
    void refreshStatus();
    state.statusTimer = window.setInterval(refreshStatus, 12_000);

    return Object.freeze({
      close,
      open,
      openForCourse(courseId) {
        return setExactSource("course", courseId);
      },
      peekForCourse(courseId) {
        return setExactSource("course", courseId, { presentation: "peek" });
      },
      openForWork(workId) {
        return setExactSource("work", workId);
      },
      peekForWork(workId) {
        return setExactSource("work", workId, { presentation: "peek" });
      },
      closeContext(contextSession) {
        return state.contextSession === contextSession ? close() : false;
      },
      setLibrary(library) {
        state.library = library && typeof library === "object" ? library : null;
        state.token = String(library?.actionToken || "");
        reconcileSelections();
        renderSourceList();
      },
      setVideoCatalog(catalog) {
        state.catalog = catalog && typeof catalog === "object" ? catalog : null;
        reconcileSelections();
        renderSourceList();
      },
      destroy() {
        state.destroyed = true;
        window.clearInterval(state.statusTimer);
        window.removeEventListener("cs-library-reader-closed", handleReaderClosed);
        stopCurrentTurn();
      },
    });
  }

  window.LatticeTutor = Object.freeze({ create });
})();
