"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const STORAGE = {
  favorites: "cs-library:favorites",
  statuses: "cs-library:statuses",
  recent: "cs-library:recent",
  theme: "cs-library:theme",
  layout: "cs-library:layout",
};

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
  readingCount: $("#readingCount"),
  recentRow: $("#recentRow"),
  recentSection: $("#recentSection"),
  resultCount: $("#resultCount"),
  search: $("#searchInput"),
  sectionEyebrow: $("#sectionEyebrow"),
  sectionTitle: $("#sectionTitle"),
  shelfNav: $("#shelfNav"),
  sizeStat: $("#sizeStat"),
  sort: $("#sortSelect"),
  subjectChips: $("#subjectChips"),
  theme: $("#themeButton"),
  toastRegion: $("#toastRegion"),
  viewButton: $("#viewButton"),
  workStat: $("#workStat"),
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
  return ["PDF", "TXT"].includes(file.format);
}

function contentUrl(path) {
  return `/content/${path.split("/").map(encodeURIComponent).join("/")}`;
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

async function openFile(work, file) {
  recordOpen(work);
  if (isBrowserReadable(file)) {
    window.open(contentUrl(file.path), "_blank", "noopener");
    announce(`Opened ${file.title}`);
  } else {
    try {
      await localAction(file.path, "open");
      announce(`Opened ${file.title} in its Mac app`);
    } catch (error) {
      announce(error.message, true);
    }
  }
  renderCards();
  if (state.selectedId === work.id) renderDrawer(work);
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
    node("span", "format-badge", work.isCollection ? `${work.fileCount} FILES` : work.formats[0]),
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
  const card = node("article", `book-card subject-${work.subjectId}`);
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
  info.append(meta);

  const actions = node("div", "card-actions");
  actions.append(
    button("button button-primary button-small", work.isCollection ? "Browse files" : isBrowserReadable(primaryFile(work)) ? "Read" : "Open", () => {
      if (work.isCollection) showDrawer(work.id);
      else openFile(work, primaryFile(work));
    }),
    button("button button-quiet button-small", "Details", () => showDrawer(work.id)),
  );
  info.append(actions);
  card.append(favorite, makeCover(work), info);
  return card;
}

function makeMaterialCard(material) {
  const work = state.workById.get(material.workId);
  const card = node("article", `book-card material-card subject-${material.subjectId}`);
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
    button("button button-primary button-small", isBrowserReadable(material) ? "Read" : "Open", () => openFile(work, material)),
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
  title.append(pills);
  lead.append(makeCover(work, true), title);
  body.append(lead);

  const actions = node("div", "drawer-actions");
  actions.append(
    button("button button-primary", work.isCollection ? "Open first file" : isBrowserReadable(primaryFile(work)) ? "Read now" : "Open in app", () => openFile(work, primaryFile(work))),
    button("button button-quiet", state.favorites.has(work.id) ? "♥ Favorited" : "♡ Favorite", () => toggleFavorite(work)),
    button("button button-quiet", "Finder", () => revealFile(primaryFile(work)), "Reveal in Finder"),
  );
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
    const row = node("div", "file-row");
    const details = node("div", "");
    details.append(node("strong", "", file.title), node("small", "", `${file.format} · ${humanBytes(file.bytes)} · ${file.path}`));
    const fileActions = node("div", "file-actions");
    fileActions.append(
      button("mini-action", isBrowserReadable(file) ? "Read" : "Open", () => openFile(work, file)),
      button("mini-action", "Finder", () => revealFile(file), `Reveal ${file.title} in Finder`),
    );
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
    ["Availability", work.isAvailable ? "On this Mac" : "Missing files"],
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
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => setView(item.dataset.view)));
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
  elements.menuButton.addEventListener("click", openMobileMenu);
  elements.mobileScrim.addEventListener("click", closeMobileMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && document.activeElement !== elements.search) {
      event.preventDefault();
      elements.search.focus();
    }
    if (event.key === "Escape") {
      if (document.body.classList.contains("drawer-open")) closeDrawer();
      else closeMobileMenu();
    }
  });
}

function initializeLibrary(payload) {
  state.library = payload;
  state.token = payload.actionToken;
  state.workById = new Map(payload.works.map((work) => [work.id, work]));
  elements.workStat.textContent = payload.stats.works;
  elements.artifactStat.textContent = payload.stats.artifacts;
  elements.sizeStat.textContent = humanBytes(payload.stats.bytes);
  elements.integrityStat.textContent = `${payload.stats.present}/${payload.stats.artifacts}`;
  renderNavigationCounts();
  renderMaterials();
  renderShelves();
  renderSubjectChips();
  renderRecent();
  renderCards();
}

async function start() {
  initializeTheme();
  bindEvents();
  try {
    const response = await fetch("/api/library", { cache: "no-store" });
    if (!response.ok) throw new Error(`Catalog request failed (${response.status})`);
    initializeLibrary(await response.json());
  } catch (error) {
    elements.grid.replaceChildren();
    elements.grid.hidden = true;
    elements.empty.hidden = false;
    $("h3", elements.empty).textContent = "The local catalog could not load";
    $("p", elements.empty).textContent = error.message;
    elements.clearFilters.hidden = true;
    announce(error.message, true);
  }
}

start();
