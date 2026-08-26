import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const SCRIPT = fs.readFileSync(new URL("../ui/audio-player.js", import.meta.url), "utf8");
const CSS = fs.readFileSync(new URL("../ui/audio-player.css", import.meta.url), "utf8");
const APP = fs.readFileSync(new URL("../ui/app.js", import.meta.url), "utf8");
const HTML = fs.readFileSync(new URL("../ui/index.html", import.meta.url), "utf8");
const STYLES = fs.readFileSync(new URL("../ui/styles.css", import.meta.url), "utf8");
const MAC_BUILD = fs.readFileSync(new URL("../scripts/build-macos-app.sh", import.meta.url), "utf8");
const MAC_UPDATER = fs.readFileSync(new URL("../native/MacUpdateInstaller.swift", import.meta.url), "utf8");
const WINDOWS_BUILD = fs.readFileSync(new URL("../windows/build-windows.ps1", import.meta.url), "utf8");
const WINDOWS_INSTALLER = fs.readFileSync(new URL("../windows/install.ps1", import.meta.url), "utf8");

test("audio player supports the declared local formats through secure content routes", () => {
  for (const format of ["MP3", "M4A", "WAV", "FLAC"]) assert.match(SCRIPT, new RegExp(`\\b${format}\\b`));
  assert.match(SCRIPT, /\/content\//);
  assert.match(SCRIPT, /split\("\/"\)\.map\(encodeURIComponent\)/);
  assert.doesNotMatch(SCRIPT, /URL\.createObjectURL|FileReader/);
});

test("audio player restores position without autoplay and exposes media controls", () => {
  assert.match(SCRIPT, /cs-library:audio-player-v1/);
  assert.match(SCRIPT, /pendingRestoreTime/);
  assert.match(SCRIPT, /audio\.currentTime/);
  assert.doesNotMatch(SCRIPT, /autoplay/);
  assert.match(SCRIPT, /navigator\.mediaSession/);
  assert.match(SCRIPT, /setActionHandler/);
  assert.match(SCRIPT, /beforeunload/);
});

test("audio dock remains available in the reader and collapses on small screens", () => {
  assert.match(CSS, /body\.reader-open \.lattice-audio/);
  assert.match(CSS, /@media \(max-width: 760px\)/);
  assert.match(CSS, /position:\s*fixed/);
  assert.match(CSS, /\.lattice-audio-shelf/);
});

test("the Add modal stays above and isolates the audio and Tutor surfaces", () => {
  assert.match(STYLES, /\.import-shell\s*\{[\s\S]*?z-index:\s*190/);
  assert.match(APP, /function setImportBackgroundInert\(inert\)[\s\S]*?#latticeAudioPlayer[\s\S]*?#tutorScrim[\s\S]*?#tutorPanel/);
  assert.match(APP, /function openImportDialog[\s\S]*?setImportBackgroundInert\(true\)/);
  assert.match(APP, /function closeImportDialog[\s\S]*?setImportBackgroundInert\(false\)/);
});

test("the shelf, reader, and import workflow expose local audio as a first-class action", () => {
  assert.match(HTML, /value="audio"/);
  assert.match(HTML, /id="readerAudioButton"/);
  assert.match(HTML, /audio-player\.css/);
  assert.match(HTML, /audio-player\.js/);
  for (const suffix of ["mp3", "m4a", "wav", "flac"]) assert.match(HTML, new RegExp(`\\.${suffix}`));
  assert.match(APP, /AUDIO_FORMATS/);
  assert.match(APP, /playMaterial\(file\)/);
  assert.match(APP, /state\.audioPlayer\?\.setLibrary\(payload\.materials\)/);
  assert.match(APP, /openAudioImportDialog/);
});

test("desktop builders and update verifiers retain the audio player assets", () => {
  for (const source of [MAC_BUILD, MAC_UPDATER, WINDOWS_BUILD, WINDOWS_INSTALLER]) {
    assert.match(source, /audio-player\.js/);
    assert.match(source, /audio-player\.css/);
  }
});
