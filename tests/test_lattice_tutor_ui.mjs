import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";


const HTML = fs.readFileSync(new URL("../ui/index.html", import.meta.url), "utf8");
const TUTOR = fs.readFileSync(new URL("../ui/tutor.js", import.meta.url), "utf8");
const TUTOR_STYLES = fs.readFileSync(new URL("../ui/tutor-styles.css", import.meta.url), "utf8");
const APP = fs.readFileSync(new URL("../ui/app.js", import.meta.url), "utf8");
const VIDEOS = fs.readFileSync(new URL("../ui/videos.js", import.meta.url), "utf8");
const MAC_BUILD = fs.readFileSync(new URL("../scripts/build-macos-app.sh", import.meta.url), "utf8");
const WINDOWS_BUILD = fs.readFileSync(new URL("../windows/build-windows.ps1", import.meta.url), "utf8");
const WINDOWS_UPDATE_HARNESS = fs.readFileSync(new URL("../windows/UpdateSecurityHarness/Program.cs", import.meta.url), "utf8");


test("Tutor stays an optional closed drawer with an explicit local-source disclosure", () => {
  assert.match(HTML, /id="tutorOpenButton"/);
  assert.match(HTML, /id="tutorPanel"[^>]*aria-hidden="true"/);
  assert.match(HTML, /Optional study companion/);
  assert.match(HTML, /relevant excerpts from the chosen sources are processed through your signed-in Codex account/);
  assert.match(HTML, /Video sources provide catalog metadata, not transcripts/);
  assert.match(TUTOR_STYLES, /\.tutor-panel\s*\{[\s\S]*position:\s*fixed/);
  assert.match(TUTOR_STYLES, /body\.tutor-open \.tutor-panel/);
});

test("Tutor offers the supported models, Light through Max thinking, and source scoping", () => {
  for (const model of ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]) {
    assert.match(HTML, new RegExp(`value="${model}"`));
    assert.match(TUTOR, new RegExp(model.replaceAll(".", "\\.")));
  }
  for (const effort of ["low", "medium", "high", "xhigh", "max"]) {
    assert.match(HTML, new RegExp(`value="${effort}"`));
  }
  assert.match(HTML, /value="all" checked/);
  assert.match(HTML, /value="selected"/);
  assert.match(TUTOR, /workIds:\s*\[\.\.\.state\.workIds\]/);
  assert.match(TUTOR, /courseIds:\s*\[\.\.\.state\.courseIds\]/);
});

test("Tutor uses authenticated local endpoints and renders model output without HTML injection", () => {
  assert.match(TUTOR, /fetch\("\/api\/tutor\/status"/);
  assert.match(TUTOR, /post\("\/api\/tutor\/chat"/);
  assert.match(TUTOR, /"X-Library-Token": state\.token/);
  assert.match(TUTOR, /document\.createTextNode/);
  assert.doesNotMatch(TUTOR, /innerHTML\s*=/);
  assert.match(TUTOR, /state\.messages\s*=\s*\[\]/);
  assert.doesNotMatch(TUTOR, /localStorage\.setItem\([^\n]*messages/i);
});

test("Shelf, reader, citations, and video courses all bridge into Tutor", () => {
  assert.match(APP, /openForWork\(work\.id\)/);
  assert.match(APP, /readerTutorButton/);
  assert.match(APP, /readerTutorPeekButton/);
  assert.match(APP, /peekForWork\(state\.readerWorkId\)/);
  assert.match(APP, /peekForCourse\(course\.id\)/);
  assert.match(APP, /closeContext\("video"\)/);
  assert.match(TUTOR, /presentation:\s*"peek"/);
  assert.match(TUTOR, /tutor-reader-session/);
  assert.match(TUTOR, /tutor-video-session/);
  assert.match(TUTOR, /Make Tutor compact/);
  assert.match(TUTOR, /Ask about this course/);
  assert.match(TUTOR, /Your lecture stays visible while you talk\./);
  assert.match(TUTOR_STYLES, /body\.tutor-peek \.tutor-panel/);
  assert.match(TUTOR_STYLES, /\.reader-tutor-peek-button\s*\{[\s\S]*bottom:\s*43px/);
  assert.match(HTML, /id="tutorExpandButton"/);
  assert.match(HTML, /id="readerTutorPeekButton"/);
  assert.doesNotMatch(HTML, /id="readerTutorPeekButton"[^>]*>[\s\S]*?<em>/);
  assert.doesNotMatch(TUTOR_STYLES, /\.reader-tutor-peek-button:hover[\s\S]*?width:\s*72px/);
  assert.match(APP, /openTutorCitation/);
  assert.match(APP, /openCourseById/);
  assert.match(VIDEOS, /onAskTutor/);
  assert.match(VIDEOS, /onCloseTutor/);
  assert.match(VIDEOS, /openCourseById\(courseId/);
});

test("desktop packages carry the Tutor UI, broker, and PDF parser", () => {
  for (const required of ["tutor.js", "tutor-styles.css", "lattice_tutor.py", "vendor/pypdf"]) {
    assert.match(MAC_BUILD, new RegExp(required.replaceAll("/", "\\/")));
  }
  for (const required of ["tutor.js", "tutor-styles.css", "lattice_tutor.py", "scripts\\vendor"]) {
    assert.ok(WINDOWS_BUILD.includes(required), `Windows build should include ${required}`);
  }
  for (const required of ["ui/tutor.js", "ui/tutor-styles.css"]) {
    assert.ok(WINDOWS_UPDATE_HARNESS.includes(`"${required}"`), `Windows updater fixtures should include ${required}`);
  }
});
