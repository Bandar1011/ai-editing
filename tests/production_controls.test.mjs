import assert from "node:assert/strict";
import test from "node:test";
import { createProduction } from "../web/production.js";

// Exercise the real control handler with a delayed API response, without media or a browser.
function controls(t, role = "graphic") {
  const names = ["document", "Audio", "setInterval"];
  const previous = names.map((name) => [name, Object.hasOwn(globalThis, name), globalThis[name]]);
  t.after(() => {
    for (const [name, existed, value] of previous)
      if (existed) globalThis[name] = value;
      else delete globalThis[name];
  });
  const elements = new Map();
  const element = () => ({
    value: "", checked: false, dataset: {}, style: {}, hidden: false,
    innerHTML: "", textContent: "", paused: true, duration: 1, currentTime: 0,
    pause() {}, play() { return Promise.resolve(); }, load() {},
    addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    classList: { add() {}, remove() {}, toggle() {} }, scrollIntoView() {},
  });
  globalThis.document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
    querySelector: element, querySelectorAll: () => [],
  };
  globalThis.Audio = function () { return element(); };
  globalThis.setInterval = () => 0;
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const project = {
    id: "test", media: { duration: 5 }, cuts: [],
    overlays: [{ id: "ref", asset_id: "visual", role, entrance_sound: null,
      start: 1, end: 4, enabled: true }],
    punches: [], retakes: [], music: null, subtitles: [], subtitle_style: {},
  };
  const visual = { id: "visual", kind: "image", tags: [], name: "visual", description: "", has_audio: false };
  const pop = { id: "pop", kind: "audio", tags: [], name: "pop", description: "", has_audio: true, duration: 1 };
  createProduction({
    getProject: () => project, applyProject() {},
    api: async (path) => path === "/api/assets/reference-sound" ? pending : path === "/api/assets" ? [visual, pop] : {},
    changed() {}, pushUndo() {}, saveNow() {}, toast() {}, time: String, parseTime: Number,
    video: { currentTime: 0, paused: true, muted: false, volume: 1, style: {}, addEventListener() {} },
    outputTime: (t) => t, isEdited: () => true, showOriginal() {}, refreshTimeline() {},
    task() {}, selectLayer() {}, onPreviewUpdate() {},
  });
  const change = (field, value, pop = false) => elements.get("overlay-list").onchange({
    target: {
      dataset: pop ? { popField: field } : { overlayField: field },
      type: pop ? "checkbox" : "select-one", value, checked: value,
      closest: () => ({ dataset: { overlay: "ref" } }),
    },
  });
  return {
    project, change,
    release: () => release({ asset_id: "pop", asset_in: .1, volume: .35, enabled: true }),
  };
}

test("a delayed default cannot overwrite a newer Title choice", async (t) => {
  const c = controls(t);
  const pending = c.change("role", "reference");
  await c.change("role", "title");
  c.release(); await pending;
  assert.equal(c.project.overlays[0].role, "title");
  assert.equal(c.project.overlays[0].entrance_sound, null);
});

test("a delayed pop enable cannot attach sound to a newer Graphic choice", async (t) => {
  const c = controls(t, "reference");
  const pending = c.change("enabled", true, true);
  await c.change("role", "graphic");
  c.release(); await pending;
  assert.equal(c.project.overlays[0].role, "graphic");
  assert.equal(c.project.overlays[0].entrance_sound, null);
});

test("turning pop off while its default loads cancels the earlier enable", async (t) => {
  const c = controls(t, "reference");
  const pending = c.change("enabled", true, true);
  await c.change("enabled", false, true);
  c.release(); await pending;
  assert.equal(c.project.overlays[0].entrance_sound, null);
});
