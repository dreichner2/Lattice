import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const workspace = require("../native/LibraryWorkspace.js");

test("normalizes only local readable library paths", () => {
  assert.deepEqual(workspace.normalizeDocument({
    path: "books/example.epub", workId: "example", title: "Example", format: "EPUB", sha256: "abc",
  }), {
    path: "books/example.epub", workId: "example", title: "Example", format: "epub", sha256: "abc",
  });
  assert.equal(workspace.normalizeDocument({ path: "../outside.pdf" }), null);
  assert.equal(workspace.normalizeDocument({ path: "books/../outside.pdf" }), null);
  assert.equal(workspace.normalizeDocument({ path: "metadata/example.json" }), null);
});

test("normalizes and clamps durable locations", () => {
  const position = workspace.normalizePosition({ locator: { entry: "chapter.xhtml" }, page: 4, progress: 1.7 });
  assert.deepEqual(position.locator, { entry: "chapter.xhtml" });
  assert.equal(position.page, 4);
  assert.equal(position.progress, 1);
  assert.equal(typeof position.updatedAt, "number");
  assert.equal(workspace.clamp(-2), 0);
  assert.equal(workspace.clamp(0.4), 0.4);
  assert.equal(workspace.canonicalJSON({ z: 1, a: { y: 2, x: 3 } }), '{"a":{"x":3,"y":2},"z":1}');
});
