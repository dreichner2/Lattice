import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const SOURCE = fs.readFileSync(new URL("../native/SharedReaderState.js", import.meta.url), "utf8");

function loadBridge() {
  class FakeStorage {
    constructor() { this.values = new Map(); }
    get length() { return this.values.size; }
    key(index) { return [...this.values.keys()][index] ?? null; }
    getItem(key) { return this.values.has(String(key)) ? this.values.get(String(key)) : null; }
    setItem(key, value) { this.values.set(String(key), String(value)); }
    removeItem(key) { this.values.delete(String(key)); }
    clear() { this.values.clear(); }
  }
  const posts = [];
  const localStorage = new FakeStorage();
  const window = {
    location: { origin: "http://127.0.0.1:8766" },
    localStorage,
  };
  window.top = window;

  class FakeXHR {
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader() {}
    send() {
      this.status = 200;
      this.responseText = this.url.endsWith("/api/library")
        ? JSON.stringify({ actionToken: "token" })
        : JSON.stringify({ values: { "cs-library:progress": '{"page":7}', ignored: "x" } });
    }
  }

  vm.runInNewContext(SOURCE, {
    window,
    document: {},
    Storage: FakeStorage,
    XMLHttpRequest: FakeXHR,
    fetch: async (url, options) => { posts.push({ url, options }); return { ok: true }; },
    URL,
    Headers,
    JSON,
    String,
    Object,
  });

  return { window, localStorage, posts };
}

test("desktop bridge hydrates only CS Library keys", () => {
  const bridge = loadBridge();
  assert.equal(bridge.localStorage.getItem("cs-library:progress"), '{"page":7}');
  assert.equal(bridge.localStorage.getItem("ignored"), null);
});

test("desktop bridge mirrors state writes and deletes", async () => {
  const bridge = loadBridge();
  bridge.localStorage.setItem("cs-library:theme", '"dark"');
  bridge.localStorage.removeItem("cs-library:theme");
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(bridge.posts.length, 2);
  assert.match(bridge.posts[0].url, /api\/state\/set$/);
  assert.match(bridge.posts[1].url, /api\/state\/delete$/);
});

test("native bridge mirrors clear only for CS Library keys", async () => {
  const bridge = loadBridge();
  bridge.localStorage.setItem("unrelated", "keep local");
  bridge.posts.length = 0;
  bridge.localStorage.clear();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(bridge.posts.length, 1);
  assert.match(bridge.posts[0].url, /api\/state\/delete$/);
  assert.deepEqual(JSON.parse(bridge.posts[0].options.body), {
    namespace: "localStorage",
    key: "cs-library:progress",
  });
});
