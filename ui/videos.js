"use strict";

(() => {
  const STORAGE = {
    completed: "cs-library:video-completed",
    positions: "cs-library:video-positions",
    source: "cs-library:video-source",
    sort: "cs-library:video-sort",
  };
  const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

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
      return true;
    } catch {
      return false;
    }
  }

  function node(tag, className = "", text = "") {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== "") element.textContent = text;
    return element;
  }

  function button(className, text, action, label = text) {
    const element = node("button", className, text);
    element.type = "button";
    element.setAttribute("aria-label", label);
    element.addEventListener("click", action);
    return element;
  }

  function slugify(value) {
    return String(value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value) || 0);
  }

  function humanDate(value) {
    const date = new Date(`${value}T12:00:00`);
    return Number.isNaN(date.valueOf())
      ? value
      : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
  }

  function searchText(course) {
    return [
      course.title,
      course.code,
      course.institution,
      course.source?.label,
      course.term,
      course.level,
      course.subject,
      course.description,
      course.license,
      ...(course.instructors || []),
    ].join(" ").toLowerCase();
  }

  function validateCatalog(payload) {
    if (!payload || !Array.isArray(payload.courses) || !payload.courses.length) {
      throw new Error("The video lecture catalog is empty");
    }
    if (!Array.isArray(payload.sources) || !payload.sources.length) {
      throw new Error("The video lecture catalog has no sources");
    }
    const sources = payload.sources.map((source) => {
      if (
        !source
        || typeof source.id !== "string"
        || !source.id
        || typeof source.label !== "string"
        || !source.label
        || !Number.isInteger(source.courseCount)
        || source.courseCount < 1
      ) {
        throw new Error("The video lecture source catalog is malformed");
      }
      return source;
    });
    const sourceIds = new Set(sources.map((source) => source.id));
    if (sourceIds.size !== sources.length) throw new Error("The video lecture sources are duplicated");
    const courses = payload.courses.map((course) => {
      if (
        !course
        || typeof course.id !== "string"
        || !Array.isArray(course.lectures)
        || !course.lectures.length
        || !sourceIds.has(course.source?.id)
        || typeof course.source?.label !== "string"
      ) {
        throw new Error("The video lecture catalog is malformed");
      }
      const lectures = course.lectures.filter((lecture) => VIDEO_ID.test(lecture?.id) && lecture?.title);
      if (!lectures.length) throw new Error(`No playable lectures found for ${course.title || course.id}`);
      return { ...course, lectures, lectureCount: lectures.length, searchText: searchText(course) };
    });
    return { ...payload, courses, sources };
  }

  function create(options = {}) {
    const elements = {
      clearFilters: document.querySelector("#clearVideoFiltersButton"),
      complete: document.querySelector("#videoCompleteButton"),
      courseGrid: document.querySelector("#videoCourseGrid"),
      courseProgress: document.querySelector("#videoCourseProgressBar"),
      empty: document.querySelector("#videoEmptyState"),
      frame: document.querySelector("#videoFrame"),
      framePlaceholder: document.querySelector("#videoFramePlaceholder"),
      lectureSource: document.querySelector("#videoLectureSource"),
      next: document.querySelector("#videoNextButton"),
      nextLabel: document.querySelector("#videoNextLabel"),
      nowPosition: document.querySelector("#videoNowPosition"),
      nowTitle: document.querySelector("#videoNowTitle"),
      playerBack: document.querySelector("#videoPlayerBack"),
      playerBackdrop: document.querySelector("#videoPlayerBackdrop"),
      playerClose: document.querySelector("#videoPlayerClose"),
      playerCourseTitle: document.querySelector("#videoPlayerCourseTitle"),
      playerKicker: document.querySelector("#videoPlayerKicker"),
      playerShell: document.querySelector("#videoPlayerShell"),
      playerSource: document.querySelector("#videoPlayerSource"),
      previous: document.querySelector("#videoPreviousButton"),
      previousLabel: document.querySelector("#videoPreviousLabel"),
      queueCode: document.querySelector("#videoQueueCode"),
      queueDescription: document.querySelector("#videoQueueDescription"),
      queueList: document.querySelector("#videoQueueList"),
      queueMeta: document.querySelector("#videoQueueMeta"),
      queueSearch: document.querySelector("#videoQueueSearch"),
      resultCount: document.querySelector("#videoResultCount"),
      section: document.querySelector("#videoSection"),
      sort: document.querySelector("#videoSortSelect"),
      source: document.querySelector("#videoSourceSelect"),
      sourceNotes: document.querySelector("#videoSourcesButton"),
      subjectChips: document.querySelector("#videoSubjectChips"),
      watchedCount: document.querySelector("#videoWatchedCount"),
    };
    const state = {
      active: false,
      catalog: null,
      completed: new Set(readStorage(STORAGE.completed, [])),
      course: null,
      index: -1,
      lastFocus: null,
      positions: readStorage(STORAGE.positions, {}) || {},
      query: "",
      source: readStorage(STORAGE.source, "all"),
      sort: readStorage(STORAGE.sort, "recommended"),
      subject: "all",
    };

    if (!["recommended", "title", "most", "progress"].includes(state.sort)) state.sort = "recommended";
    elements.sort.value = state.sort;

    function completedCount(course) {
      return course.lectures.reduce((total, lecture) => total + Number(state.completed.has(lecture.id)), 0);
    }

    function persistProgress() {
      const completedSaved = writeStorage(STORAGE.completed, [...state.completed]);
      const positionsSaved = writeStorage(STORAGE.positions, state.positions);
      if (!completedSaved || !positionsSaved) options.announce?.("Video progress could not be saved on this computer", true);
    }

    function courseMatches(course) {
      if (state.subject !== "all" && course.subject !== state.subject) return null;
      if (state.source !== "all" && course.source.id !== state.source) return null;
      const query = state.query.trim().toLowerCase();
      if (!query) return { course, lectureMatches: [], metadataMatch: true };
      const metadataMatch = course.searchText.includes(query);
      const lectureMatches = course.lectures.filter((lecture) => lecture.title.toLowerCase().includes(query));
      if (!metadataMatch && !lectureMatches.length) return null;
      return { course, lectureMatches, metadataMatch };
    }

    function filteredCourses() {
      if (!state.catalog) return [];
      const originalOrder = new Map(state.catalog.courses.map((course, index) => [course.id, index]));
      const results = state.catalog.courses.map(courseMatches).filter(Boolean);
      const sorters = {
        recommended: (a, b) => originalOrder.get(a.course.id) - originalOrder.get(b.course.id),
        title: (a, b) => a.course.title.localeCompare(b.course.title),
        most: (a, b) => b.course.lectureCount - a.course.lectureCount || a.course.title.localeCompare(b.course.title),
        progress: (a, b) => {
          const aCount = completedCount(a.course);
          const bCount = completedCount(b.course);
          const aActive = Number(aCount > 0 && aCount < a.course.lectureCount);
          const bActive = Number(bCount > 0 && bCount < b.course.lectureCount);
          return bActive - aActive || bCount - aCount || a.course.title.localeCompare(b.course.title);
        },
      };
      return results.sort(sorters[state.sort] || sorters.recommended);
    }

    function makeProgress(course, compact = false) {
      const count = completedCount(course);
      const wrap = node("div", compact ? "video-card-progress is-compact" : "video-card-progress");
      const label = node("span", "", `${count}/${course.lectureCount} complete`);
      const track = node("div");
      const bar = node("i");
      bar.style.width = `${course.lectureCount ? (count / course.lectureCount) * 100 : 0}%`;
      track.append(bar);
      wrap.append(label, track);
      return wrap;
    }

    function preferredLecture(course, matches = []) {
      const positioned = state.positions[course.id];
      if (matches.length) return matches[0].id;
      if (positioned && course.lectures.some((lecture) => lecture.id === positioned)) return positioned;
      return course.lectures.find((lecture) => !state.completed.has(lecture.id))?.id || course.lectures[0].id;
    }

    function makeCourseCard(result) {
      const { course, lectureMatches, metadataMatch } = result;
      const card = node("article", `video-course-card video-subject-${slugify(course.subject)}`);
      const cover = button("video-course-cover", "", () => openCourse(course, preferredLecture(course, lectureMatches)), `Watch ${course.title}`);
      const coverTop = node("div", "video-cover-top");
      coverTop.append(node("span", "", course.code), node("span", "", `${formatNumber(course.lectureCount)} videos`));
      const play = node("span", "video-cover-play", "▶");
      play.setAttribute("aria-hidden", "true");
      const coverBottom = node("div", "video-cover-bottom");
      coverBottom.append(node("small", "", course.subject), node("strong", "", course.title));
      cover.append(coverTop, play, coverBottom);

      const body = node("div", "video-course-body");
      const institution = node("p", "video-course-institution", `${course.institution} · ${course.term}`);
      const title = node("h3", "", course.title);
      const description = node("p", "video-course-description", course.description);
      const tags = node("div", "video-course-tags");
      tags.append(node("span", "", course.level), node("span", "", course.license.includes("CC ") ? "Open license" : "Free stream"));
      body.append(institution, title, description, tags);
      if (state.query.trim() && lectureMatches.length && !metadataMatch) {
        const match = node("div", "video-lecture-match");
        match.append(
          node("strong", "", `${lectureMatches.length} matching ${lectureMatches.length === 1 ? "lecture" : "lectures"}`),
          node("span", "", lectureMatches.slice(0, 2).map((lecture) => lecture.title).join(" · ")),
        );
        body.append(match);
      }
      body.append(makeProgress(course));
      const actions = node("div", "video-course-actions");
      const count = completedCount(course);
      const label = count ? "Continue course" : "Start watching";
      actions.append(
        button("button button-primary button-small", label, () => openCourse(course, preferredLecture(course, lectureMatches))),
        button("button button-quiet button-small", "Course site ↗", () => window.open(course.sourceUrl, "_blank", "noopener,noreferrer")),
      );
      body.append(actions);
      card.append(cover, body);
      return card;
    }

    function renderSubjectChips() {
      if (!state.catalog) return;
      const sourceCourses = state.source === "all"
        ? state.catalog.courses
        : state.catalog.courses.filter((course) => course.source.id === state.source);
      const counts = Object.fromEntries(
        state.catalog.subjects.map((subject) => [subject, sourceCourses.filter((course) => course.subject === subject).length]),
      );
      const all = button(`chip${state.subject === "all" ? " is-active" : ""}`, "All subjects", () => {
        state.subject = "all";
        render();
      });
      const chips = state.catalog.subjects.map((subject) => {
        const chip = button(`chip${state.subject === subject ? " is-active" : ""}`, `${subject} ${counts[subject]}`, () => {
          state.subject = subject;
          render();
        });
        return chip;
      });
      elements.subjectChips.replaceChildren(all, ...chips);
    }

    function renderSourceOptions() {
      if (!state.catalog) return;
      const sourceIds = new Set(state.catalog.sources.map((source) => source.id));
      if (state.source !== "all" && !sourceIds.has(state.source)) {
        state.source = "all";
        writeStorage(STORAGE.source, state.source);
      }
      const all = node("option", "", `All sources (${state.catalog.courses.length})`);
      all.value = "all";
      const options = state.catalog.sources.map((source) => {
        const option = node("option", "", `${source.label} (${source.courseCount})`);
        option.value = source.id;
        return option;
      });
      elements.source.replaceChildren(all, ...options);
      elements.source.value = state.source;
    }

    function render() {
      if (!state.catalog) return;
      const results = filteredCourses();
      elements.courseGrid.replaceChildren(...results.map(makeCourseCard));
      elements.courseGrid.hidden = results.length === 0;
      elements.empty.hidden = results.length > 0;
      const lectures = results.reduce((total, result) => {
        if (!state.query.trim() || result.metadataMatch) return total + result.course.lectureCount;
        return total + result.lectureMatches.length;
      }, 0);
      elements.resultCount.textContent = `${formatNumber(results.length)} ${results.length === 1 ? "course" : "courses"} · ${formatNumber(lectures)} ${lectures === 1 ? "lecture" : "lectures"}`;
      renderSubjectChips();
    }

    function embedUrl(lecture) {
      if (lecture.embedUrl) return lecture.embedUrl;
      const query = new URLSearchParams({
        autoplay: "1",
        playsinline: "1",
        rel: "0",
        modestbranding: "1",
        origin: window.location.origin,
      });
      return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(lecture.id)}?${query}`;
    }

    function currentLecture() {
      return state.course?.lectures?.[state.index] || null;
    }

    function renderQueue() {
      if (!state.course) return;
      const query = elements.queueSearch.value.trim().toLowerCase();
      const rows = state.course.lectures.map((lecture, index) => {
        const row = button(
          `video-queue-item${index === state.index ? " is-current" : ""}${state.completed.has(lecture.id) ? " is-complete" : ""}`,
          "",
          () => playLecture(index),
          `Play ${lecture.title}`,
        );
        row.dataset.search = lecture.title.toLowerCase();
        row.hidden = Boolean(query) && !row.dataset.search.includes(query);
        const number = node("span", "video-queue-number", state.completed.has(lecture.id) ? "✓" : String(index + 1));
        const copy = node("span", "video-queue-copy");
        copy.append(node("small", "", `Lecture ${index + 1}`), node("strong", "", lecture.title));
        const play = node("span", "video-queue-play", index === state.index ? "Playing" : "▶");
        row.append(number, copy, play);
        return row;
      });
      elements.queueList.replaceChildren(...rows);
      const current = elements.queueList.querySelector(".is-current");
      if (current && !query) current.scrollIntoView({ block: "nearest" });
    }

    function updatePlayerState() {
      const lecture = currentLecture();
      if (!state.course || !lecture) return;
      const complete = state.completed.has(lecture.id);
      const count = completedCount(state.course);
      elements.nowPosition.textContent = `Lecture ${state.index + 1} of ${state.course.lectureCount}`;
      elements.nowTitle.textContent = lecture.title;
      elements.lectureSource.href = lecture.sourceUrl;
      elements.complete.classList.toggle("is-complete", complete);
      elements.complete.setAttribute("aria-pressed", String(complete));
      elements.complete.lastChild.textContent = complete ? " Completed" : " Mark complete";
      elements.watchedCount.textContent = formatNumber(count);
      elements.courseProgress.style.width = `${state.course.lectureCount ? (count / state.course.lectureCount) * 100 : 0}%`;
      elements.previous.disabled = state.index === 0;
      elements.next.disabled = state.index >= state.course.lectures.length - 1;
      elements.previousLabel.textContent = state.index > 0 ? state.course.lectures[state.index - 1].title : "Beginning";
      elements.nextLabel.textContent = state.index < state.course.lectures.length - 1 ? state.course.lectures[state.index + 1].title : "Course complete";
      renderQueue();
    }

    function playLecture(index, { autoplay = true } = {}) {
      if (!state.course) return;
      const nextIndex = Math.min(state.course.lectures.length - 1, Math.max(0, Number(index) || 0));
      const lecture = state.course.lectures[nextIndex];
      state.index = nextIndex;
      state.positions[state.course.id] = lecture.id;
      persistProgress();
      elements.framePlaceholder.hidden = false;
      elements.frame.title = `${state.course.title}: ${lecture.title}`;
      elements.frame.src = autoplay ? embedUrl(lecture) : "about:blank";
      updatePlayerState();
      render();
    }

    function openCourse(course, videoId = "") {
      const index = Math.max(0, course.lectures.findIndex((lecture) => lecture.id === videoId));
      state.lastFocus = document.activeElement;
      state.course = course;
      state.index = index;
      elements.playerCourseTitle.textContent = course.title;
      elements.playerKicker.textContent = `${course.code} · ${course.institution}`;
      elements.playerSource.href = course.sourceUrl;
      elements.queueCode.textContent = `${course.code} · ${course.term}`;
      elements.queueMeta.textContent = `${formatNumber(course.lectureCount)} lectures · ${course.level}`;
      elements.queueDescription.textContent = course.description;
      elements.queueSearch.value = "";
      document.body.classList.add("video-player-open");
      elements.playerShell.setAttribute("aria-hidden", "false");
      playLecture(index);
      elements.playerBack.focus();
    }

    function closePlayer() {
      if (!document.body.classList.contains("video-player-open")) return false;
      document.body.classList.remove("video-player-open");
      elements.playerShell.setAttribute("aria-hidden", "true");
      elements.frame.src = "about:blank";
      elements.frame.title = "Video lecture player";
      elements.framePlaceholder.hidden = false;
      state.course = null;
      state.index = -1;
      if (state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus();
      state.lastFocus = null;
      return true;
    }

    function toggleComplete() {
      const lecture = currentLecture();
      if (!state.course || !lecture) return;
      if (state.completed.has(lecture.id)) state.completed.delete(lecture.id);
      else state.completed.add(lecture.id);
      persistProgress();
      updatePlayerState();
      render();
      options.announce?.(state.completed.has(lecture.id) ? "Lecture marked complete" : "Completion mark removed");
    }

    function clearFilters() {
      state.subject = "all";
      state.source = "all";
      state.query = "";
      elements.source.value = state.source;
      writeStorage(STORAGE.source, state.source);
      options.onClearQuery?.();
      render();
    }

    async function load() {
      try {
        const response = await fetch("/api/lectures", { cache: "no-store" });
        if (!response.ok) throw new Error(`Lecture catalog request failed (${response.status})`);
        state.catalog = validateCatalog(await response.json());
        renderSourceOptions();
        document.querySelector("#videoCount").textContent = formatNumber(state.catalog.stats.lectures);
        render();
        options.onCatalog?.(state.catalog);
        return state.catalog;
      } catch (error) {
        elements.courseGrid.replaceChildren();
        elements.courseGrid.hidden = true;
        elements.empty.hidden = false;
        elements.empty.querySelector("h3").textContent = "The video catalog could not load";
        elements.empty.querySelector("p").textContent = error.message;
        elements.clearFilters.hidden = true;
        document.querySelector("#videoCount").textContent = "!";
        options.announce?.(error.message, true);
        throw error;
      }
    }

    elements.sort.addEventListener("change", () => {
      state.sort = elements.sort.value;
      writeStorage(STORAGE.sort, state.sort);
      render();
    });
    elements.source.addEventListener("change", () => {
      state.source = elements.source.value;
      writeStorage(STORAGE.source, state.source);
      render();
    });
    elements.clearFilters.addEventListener("click", clearFilters);
    elements.sourceNotes.addEventListener("click", () => options.openSources?.());
    elements.playerBack.addEventListener("click", closePlayer);
    elements.playerBackdrop.addEventListener("click", closePlayer);
    elements.playerClose.addEventListener("click", closePlayer);
    elements.complete.addEventListener("click", toggleComplete);
    elements.previous.addEventListener("click", () => playLecture(state.index - 1));
    elements.next.addEventListener("click", () => playLecture(state.index + 1));
    elements.queueSearch.addEventListener("input", renderQueue);
    elements.frame.addEventListener("load", () => {
      if (elements.frame.src !== "about:blank") elements.framePlaceholder.hidden = true;
    });

    const ready = load();
    ready.catch(() => {});
    return {
      get catalog() {
        return state.catalog;
      },
      get isPlayerOpen() {
        return document.body.classList.contains("video-player-open");
      },
      ready,
      closePlayer,
      handleEscape: closePlayer,
      randomLecture() {
        if (!state.catalog) return false;
        const courses = filteredCourses();
        if (!courses.length) return false;
        const result = courses[Math.floor(Math.random() * courses.length)];
        const choices = result.lectureMatches.length ? result.lectureMatches : result.course.lectures;
        const lecture = choices[Math.floor(Math.random() * choices.length)];
        openCourse(result.course, lecture.id);
        return true;
      },
      setActive(active) {
        state.active = Boolean(active);
        elements.section.hidden = !state.active;
        if (!state.active) closePlayer();
        else render();
      },
      setQuery(query) {
        state.query = String(query || "");
        if (state.active) render();
      },
    };
  }

  window.CSVideoLibrary = Object.freeze({ create });
})();
