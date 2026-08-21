(() => {
  "use strict";

  if (window.top !== window || window.__CS_LIBRARY_SHARED_STATE__) return;
  window.__CS_LIBRARY_SHARED_STATE__ = true;

  const namespace = "localStorage";
  const allowedPrefix = "cs-library:";
  const endpoint = path => new URL(path, window.location.origin).toString();
  const original = {
    getItem: Storage.prototype.getItem,
    setItem: Storage.prototype.setItem,
    removeItem: Storage.prototype.removeItem,
    clear: Storage.prototype.clear,
  };
  let token = "";
  let hydrating = false;

  const syncRequest = (method, path, body = null) => {
    try {
      const request = new XMLHttpRequest();
      request.open(method, endpoint(path), false);
      if (token) request.setRequestHeader("X-Library-Token", token);
      if (body !== null) request.setRequestHeader("Content-Type", "application/json");
      request.send(body === null ? null : JSON.stringify(body));
      if (request.status < 200 || request.status >= 300) return null;
      return JSON.parse(request.responseText || "null");
    } catch {
      return null;
    }
  };

  const post = (path, body) => {
    if (!token) return;
    try {
      fetch(endpoint(path), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Library-Token": token,
        },
        body: JSON.stringify(body),
        keepalive: true,
        cache: "no-store",
      }).catch(() => {});
    } catch {
      // Native state mirroring is best-effort. Local storage remains authoritative
      // until the next successful desktop launch synchronizes it again.
    }
  };

  const initialize = () => {
    const library = syncRequest("GET", "/api/library");
    token = String(library?.actionToken || "");
    if (!token) return;
    const snapshot = syncRequest(
      "GET",
      `/api/state/snapshot?namespace=${encodeURIComponent(namespace)}`,
    );
    const values = snapshot?.values;
    if (!values || typeof values !== "object") return;
    hydrating = true;
    try {
      Object.entries(values).forEach(([key, value]) => {
        if (!key.startsWith(allowedPrefix)) return;
        original.setItem.call(window.localStorage, key, String(value));
      });
    } finally {
      hydrating = false;
    }
  };

  Storage.prototype.setItem = function setItem(key, value) {
    original.setItem.call(this, key, value);
    if (
      !hydrating
      && this === window.localStorage
      && String(key).startsWith(allowedPrefix)
    ) {
      post("/api/state/set", {
        namespace,
        key: String(key),
        value: String(value),
      });
    }
  };

  Storage.prototype.removeItem = function removeItem(key) {
    original.removeItem.call(this, key);
    if (
      !hydrating
      && this === window.localStorage
      && String(key).startsWith(allowedPrefix)
    ) {
      post("/api/state/delete", { namespace, key: String(key) });
    }
  };

  Storage.prototype.clear = function clear() {
    if (this !== window.localStorage) {
      original.clear.call(this);
      return;
    }
    const mirroredKeys = [];
    for (let index = 0; index < this.length; index += 1) {
      const key = this.key(index);
      if (key?.startsWith(allowedPrefix)) mirroredKeys.push(key);
    }
    original.clear.call(this);
    if (!hydrating) {
      mirroredKeys.forEach(key => post("/api/state/delete", { namespace, key }));
    }
  };

  window.csLibraryStateBridge = Object.freeze({
    exportURL: endpoint("/api/state/export"),
    token: () => token,
    syncNow() {
      const values = {};
      for (let index = 0; index < window.localStorage.length; index += 1) {
        const key = window.localStorage.key(index);
        if (!key?.startsWith(allowedPrefix)) continue;
        values[key] = original.getItem.call(window.localStorage, key) ?? "";
      }
      post("/api/state/batch", { namespace, values });
    },
  });

  initialize();
})();
