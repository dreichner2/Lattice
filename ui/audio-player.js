"use strict";

(() => {
  const STORAGE_KEY = "cs-library:audio-player-v1";
  const AUDIO_FORMATS = new Set(["MP3", "M4A", "WAV", "FLAC"]);
  const AUDIO_SUFFIX = /\.(?:mp3|m4a|wav|flac)$/i;
  const SAVE_INTERVAL_MS = 2_000;

  function readSavedState() {
    try {
      const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
      if (!value || typeof value !== "object" || !AUDIO_SUFFIX.test(String(value.path || ""))) return null;
      return {
        path: String(value.path),
        title: String(value.title || "Untitled audio"),
        subtitle: String(value.subtitle || "Local audio"),
        currentTime: Math.max(0, Number(value.currentTime) || 0),
        volume: Math.min(1, Math.max(0, Number(value.volume ?? 1))),
        playbackRate: [0.75, 1, 1.25, 1.5, 2].includes(Number(value.playbackRate))
          ? Number(value.playbackRate)
          : 1,
        updatedAt: String(value.updatedAt || ""),
      };
    } catch {
      return null;
    }
  }

  function contentUrl(path) {
    return `/content/${String(path).split("/").map(encodeURIComponent).join("/")}`;
  }

  function isAudioMaterial(material) {
    if (!material || typeof material !== "object") return false;
    return material.materialType === "audio"
      || AUDIO_FORMATS.has(String(material.format || "").toUpperCase())
      || AUDIO_SUFFIX.test(String(material.path || ""));
  }

  function normalizeTrack(material) {
    if (!isAudioMaterial(material)) return null;
    const path = String(material.path || "");
    if (!path || !AUDIO_SUFFIX.test(path)) return null;
    return {
      path,
      title: String(material.title || path.split("/").pop() || "Untitled audio"),
      subtitle: String(material.authors || material.workTitle || material.materialLabel || "Local audio"),
      format: String(material.format || path.split(".").pop() || "audio").toUpperCase(),
    };
  }

  function formatTime(value) {
    const seconds = Math.max(0, Math.floor(Number(value) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    return hours
      ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
      : `${minutes}:${String(remainder).padStart(2, "0")}`;
  }

  function createMarkup() {
    const shell = document.createElement("section");
    shell.className = "lattice-audio";
    shell.id = "latticeAudioPlayer";
    shell.hidden = true;
    shell.setAttribute("aria-label", "Lattice audio player");
    shell.innerHTML = `
      <audio class="lattice-audio-element" preload="metadata"></audio>
      <div class="lattice-audio-shelf" aria-hidden="true">
        <button class="lattice-audio-scrim" type="button" aria-label="Close audio shelf"></button>
        <section class="lattice-audio-library" role="dialog" aria-modal="false" aria-labelledby="latticeAudioShelfTitle">
          <header>
            <div><span>Listen while you learn</span><h2 id="latticeAudioShelfTitle">Audio shelf</h2></div>
            <button class="lattice-audio-close-shelf" type="button" aria-label="Close audio shelf">×</button>
          </header>
          <div class="lattice-audio-list"></div>
          <footer><button class="lattice-audio-add" type="button"><span aria-hidden="true">＋</span> Add audio</button></footer>
        </section>
      </div>
      <div class="lattice-audio-dock">
        <button class="lattice-audio-art" type="button" aria-label="Open audio shelf"><span aria-hidden="true">♪</span></button>
        <button class="lattice-audio-track" type="button" aria-label="Open audio shelf">
          <strong>Nothing playing</strong><small>Choose from your audio shelf</small>
        </button>
        <div class="lattice-audio-transport">
          <button data-audio-action="previous" type="button" aria-label="Previous audio">‹</button>
          <button class="lattice-audio-play" data-audio-action="toggle" type="button" aria-label="Play"><span aria-hidden="true">▶</span></button>
          <button data-audio-action="next" type="button" aria-label="Next audio">›</button>
        </div>
        <div class="lattice-audio-timeline">
          <span class="lattice-audio-current">0:00</span>
          <input class="lattice-audio-seek" type="range" min="0" max="100" step="0.1" value="0" aria-label="Audio position">
          <span class="lattice-audio-duration">0:00</span>
        </div>
        <label class="lattice-audio-rate"><span class="sr-only">Playback speed</span><select aria-label="Playback speed"><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label>
        <button class="lattice-audio-library-button" type="button" aria-label="Open audio shelf" title="Audio shelf">♫</button>
        <button class="lattice-audio-dismiss" type="button" aria-label="Stop and close audio">×</button>
      </div>`;
    document.body.append(shell);
    return shell;
  }

  function create(options = {}) {
    if (window.__latticeAudioPlayer) return window.__latticeAudioPlayer;
    const announce = typeof options.announce === "function" ? options.announce : () => {};
    const onAddAudio = typeof options.onAddAudio === "function" ? options.onAddAudio : () => {};
    const shell = createMarkup();
    const audio = shell.querySelector("audio");
    const shelf = shell.querySelector(".lattice-audio-shelf");
    const list = shell.querySelector(".lattice-audio-list");
    const playButton = shell.querySelector(".lattice-audio-play");
    const title = shell.querySelector(".lattice-audio-track strong");
    const subtitle = shell.querySelector(".lattice-audio-track small");
    const seek = shell.querySelector(".lattice-audio-seek");
    const currentLabel = shell.querySelector(".lattice-audio-current");
    const durationLabel = shell.querySelector(".lattice-audio-duration");
    const rate = shell.querySelector(".lattice-audio-rate select");
    let tracks = [];
    let current = null;
    let pendingRestoreTime = 0;
    let lastSavedAt = 0;
    const saved = readSavedState();

    function currentIndex() {
      return current ? tracks.findIndex((track) => track.path === current.path) : -1;
    }

    function persist(force = false) {
      if (!current) return;
      const now = Date.now();
      if (!force && now - lastSavedAt < SAVE_INTERVAL_MS) return;
      lastSavedAt = now;
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
          path: current.path,
          title: current.title,
          subtitle: current.subtitle,
          currentTime: pendingRestoreTime || (Number.isFinite(audio.currentTime) ? audio.currentTime : 0),
          volume: audio.volume,
          playbackRate: audio.playbackRate,
          updatedAt: new Date().toISOString(),
        }));
      } catch {
        // Playback remains useful when storage is unavailable.
      }
    }

    function updateMediaSession() {
      if (!("mediaSession" in navigator) || !current) return;
      try {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: current.title,
          artist: current.subtitle,
          album: "Lattice",
        });
        navigator.mediaSession.playbackState = audio.paused ? "paused" : "playing";
      } catch {
        // Older embedded webviews may expose only part of Media Session.
      }
    }

    function updateTimeline() {
      const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
      const position = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
      seek.max = String(Math.max(duration, 0));
      seek.value = String(Math.min(position, duration || position));
      currentLabel.textContent = formatTime(position);
      durationLabel.textContent = formatTime(duration);
      seek.style.setProperty("--audio-progress", `${duration ? (position / duration) * 100 : 0}%`);
      if ("mediaSession" in navigator && duration > 0 && position <= duration) {
        try {
          navigator.mediaSession.setPositionState({ duration, playbackRate: audio.playbackRate, position });
        } catch {
          // Position state is optional in WebKit.
        }
      }
    }

    function updatePlaybackState() {
      const playing = !audio.paused && !audio.ended;
      shell.classList.toggle("is-playing", playing);
      playButton.setAttribute("aria-label", playing ? "Pause" : "Play");
      playButton.querySelector("span").textContent = playing ? "Ⅱ" : "▶";
      updateMediaSession();
    }

    function renderList() {
      list.replaceChildren();
      if (!tracks.length) {
        const empty = document.createElement("div");
        empty.className = "lattice-audio-empty";
        const mark = document.createElement("span");
        mark.setAttribute("aria-hidden", "true");
        mark.textContent = "♫";
        const heading = document.createElement("strong");
        heading.textContent = "Your listening shelf is ready";
        const copy = document.createElement("p");
        copy.textContent = "Add an MP3, M4A, WAV, or FLAC file, then keep it playing beside any book.";
        empty.append(mark, heading, copy);
        list.append(empty);
        return;
      }
      tracks.forEach((track, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `lattice-audio-item${track.path === current?.path ? " is-current" : ""}`;
        button.dataset.path = track.path;
        const number = document.createElement("span");
        number.className = "lattice-audio-item-number";
        number.textContent = track.path === current?.path && !audio.paused ? "♪" : String(index + 1).padStart(2, "0");
        const copy = document.createElement("span");
        const strong = document.createElement("strong");
        strong.textContent = track.title;
        const small = document.createElement("small");
        small.textContent = `${track.subtitle} · ${track.format}`;
        copy.append(strong, small);
        const action = document.createElement("span");
        action.className = "lattice-audio-item-action";
        action.textContent = track.path === current?.path && !audio.paused ? "Pause" : "Play";
        button.append(number, copy, action);
        button.addEventListener("click", () => {
          if (track.path === current?.path && !audio.paused) audio.pause();
          else void play(track);
        });
        list.append(button);
      });
    }

    function select(track, { restoreTime = 0 } = {}) {
      const normalized = normalizeTrack(track);
      if (!normalized) throw new Error("That file is not supported audio");
      if (current?.path !== normalized.path) {
        persist(true);
        current = normalized;
        pendingRestoreTime = Math.max(0, Number(restoreTime) || 0);
        audio.src = contentUrl(current.path);
        audio.load();
      }
      shell.hidden = false;
      title.textContent = current.title;
      subtitle.textContent = current.subtitle;
      renderList();
      updateMediaSession();
      persist(true);
      return current;
    }

    async function play(track = current) {
      if (!track) {
        openLibrary();
        return false;
      }
      try {
        select(track);
        await audio.play();
        closeLibrary();
        return true;
      } catch (error) {
        announce(error?.message || "This audio file could not be played", true);
        return false;
      }
    }

    function playOffset(offset) {
      if (!tracks.length) return;
      const index = currentIndex();
      const next = index < 0
        ? (offset > 0 ? 0 : tracks.length - 1)
        : (index + offset + tracks.length) % tracks.length;
      void play(tracks[next]);
    }

    function openLibrary() {
      shell.hidden = false;
      shelf.setAttribute("aria-hidden", "false");
      shell.classList.add("is-shelf-open");
      renderList();
      shell.querySelector(".lattice-audio-close-shelf").focus();
    }

    function closeLibrary() {
      shelf.setAttribute("aria-hidden", "true");
      shell.classList.remove("is-shelf-open");
    }

    function stop() {
      audio.pause();
      persist(true);
      audio.removeAttribute("src");
      audio.load();
      current = null;
      pendingRestoreTime = 0;
      shell.hidden = true;
      closeLibrary();
      try {
        window.localStorage.removeItem(STORAGE_KEY);
      } catch {
        // The dock can still be dismissed when storage is unavailable.
      }
      if ("mediaSession" in navigator) navigator.mediaSession.metadata = null;
    }

    function setLibrary(materials) {
      const unique = new Map();
      (Array.isArray(materials) ? materials : []).forEach((material) => {
        const track = normalizeTrack(material);
        if (track && !unique.has(track.path)) unique.set(track.path, track);
      });
      tracks = [...unique.values()].sort((left, right) => left.title.localeCompare(right.title));
      if (!current && saved) {
        const restored = tracks.find((track) => track.path === saved.path);
        if (restored) {
          audio.volume = saved.volume;
          audio.playbackRate = saved.playbackRate;
          rate.value = String(saved.playbackRate);
          select({ ...restored, title: saved.title || restored.title, subtitle: saved.subtitle || restored.subtitle }, {
            restoreTime: saved.currentTime,
          });
          updatePlaybackState();
        }
      }
      renderList();
    }

    shell.querySelectorAll('[aria-label="Open audio shelf"], .lattice-audio-track').forEach((button) => {
      button.addEventListener("click", openLibrary);
    });
    shell.querySelector(".lattice-audio-scrim").addEventListener("click", closeLibrary);
    shell.querySelector(".lattice-audio-close-shelf").addEventListener("click", closeLibrary);
    shell.querySelector(".lattice-audio-add").addEventListener("click", () => {
      closeLibrary();
      onAddAudio();
    });
    shell.querySelector(".lattice-audio-dismiss").addEventListener("click", stop);
    shell.querySelector('[data-audio-action="previous"]').addEventListener("click", () => playOffset(-1));
    shell.querySelector('[data-audio-action="next"]').addEventListener("click", () => playOffset(1));
    playButton.addEventListener("click", () => {
      if (!current) openLibrary();
      else if (audio.paused) void play();
      else audio.pause();
    });
    seek.addEventListener("input", () => {
      if (Number.isFinite(audio.duration)) audio.currentTime = Math.min(Number(seek.value) || 0, audio.duration);
      updateTimeline();
    });
    rate.addEventListener("change", () => {
      audio.playbackRate = Number(rate.value) || 1;
      persist(true);
    });
    audio.addEventListener("loadedmetadata", () => {
      if (pendingRestoreTime > 0 && Number.isFinite(audio.duration)) {
        audio.currentTime = Math.min(pendingRestoreTime, Math.max(0, audio.duration - 0.25));
      }
      pendingRestoreTime = 0;
      updateTimeline();
    });
    audio.addEventListener("timeupdate", () => {
      updateTimeline();
      persist();
    });
    audio.addEventListener("play", () => { updatePlaybackState(); renderList(); });
    audio.addEventListener("pause", () => { updatePlaybackState(); renderList(); persist(true); });
    audio.addEventListener("ended", () => {
      persist(true);
      if (tracks.length > 1) playOffset(1);
      else updatePlaybackState();
    });
    audio.addEventListener("error", () => {
      if (audio.error) announce("This local audio file could not be played", true);
      updatePlaybackState();
    });
    window.addEventListener("beforeunload", () => persist(true));
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && shell.classList.contains("is-shelf-open")) closeLibrary();
    });

    if ("mediaSession" in navigator) {
      const handlers = {
        play: () => void play(),
        pause: () => audio.pause(),
        previoustrack: () => playOffset(-1),
        nexttrack: () => playOffset(1),
        seekbackward: (detail) => { audio.currentTime = Math.max(0, audio.currentTime - (detail.seekOffset || 15)); },
        seekforward: (detail) => { audio.currentTime = Math.min(audio.duration || Infinity, audio.currentTime + (detail.seekOffset || 15)); },
        seekto: (detail) => { if (detail.seekTime !== undefined) audio.currentTime = detail.seekTime; },
      };
      Object.entries(handlers).forEach(([action, handler]) => {
        try {
          navigator.mediaSession.setActionHandler(action, handler);
        } catch {
          // Unsupported actions are simply unavailable in this webview.
        }
      });
    }

    const controller = {
      closeLibrary,
      isAudioMaterial,
      openLibrary,
      play,
      playMaterial: play,
      setLibrary,
      stop,
      get currentTrack() { return current ? { ...current } : null; },
      get isPlaying() { return Boolean(current && !audio.paused); },
    };
    window.__latticeAudioPlayer = controller;
    return controller;
  }

  window.LatticeAudioPlayer = Object.freeze({ create, isAudioMaterial });
})();
