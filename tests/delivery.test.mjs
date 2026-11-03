import assert from "node:assert/strict";
import test from "node:test";
import { createAirDrop, currentExport, exportMatches } from "../web/delivery.mjs";

function fixture() {
  const project = { id: "video", revision: 8, source_sha256: "original",
    cuts: [], split_points: [], subtitles: [], subtitle_style: { enabled: true },
    overlays: [], punches: [], music: null, story: {}, brief: {}, references: [], jobs: {}, exports: [] };
  const exported = { file: "0000000001.mp4", source_sha256: "original", brief: {}, references: {},
    render_settings: { format: "vertical", plain: false, burn_subtitles: false }, edit_state: {} };
  for (const k of ["cuts", "split_points", "subtitles", "subtitle_style", "overlays", "punches", "music", "story"])
    exported.edit_state[k] = structuredClone(project[k]);
  exported.references = [];
  project.exports.push(exported);
  const context = { project, dirty: false, conflicted: false, editSequence: 0, busy: false };
  return { project, exported, context };
}

test("delivery finds the newest matching vertical export and rejects stale or plain versions", () => {
  const { project, exported } = fixture();
  project.exports.push({ ...exported, file: "old.mp4", render_settings: { ...exported.render_settings, plain: true } });
  assert.equal(currentExport(project).file, exported.file);
  project.cuts.push({ start: 1, end: 2 });
  assert.equal(currentExport(project), undefined);
  assert.equal(exportMatches(project, exported), false);
});

test("existing current video goes to AirDrop without another render", async () => {
  const { context, project, exported } = fixture(), calls = [], messages = [];
  const native = { id: "request", file: exported.file, project_id: project.id };
  const controller = createAirDrop({ read: () => context, save: async () => {}, apply: (p) => { context.project = p; },
    notify: (...v) => messages.push(v), wait: async () => {},
    api: async (path, options) => {
      calls.push([path, options]);
      if (path.endsWith("/airdrop")) return { ...native, status: "choosing", message: "Choose your iPhone" };
      if (path.includes("/airdrop/")) return { ...native, status: "cancelled", message: "AirDrop cancelled" };
      return structuredClone(project);
    } });
  const result = await controller.send();
  assert.equal(result.status, "cancelled");
  assert.equal(calls.some(([path]) => path.endsWith("/export")), false);
  assert.equal(calls.find(([path]) => path.endsWith("/airdrop"))[1].body.file, exported.file);
  assert.equal(messages.some(([phase]) => phase === "shared"), false);
  assert.equal(controller.pending, false);
});

test("a project switch during saving never sends the previous video", async () => {
  const { context } = fixture();
  let release, calls = 0;
  const saving = new Promise((r) => { release = r; });
  const controller = createAirDrop({ read: () => context, save: () => saving, apply() {}, notify() {},
    api: async () => { calls++; } });
  const pending = controller.send();
  context.project = { ...context.project, id: "another-video" };
  release();
  await assert.rejects(pending, /edit changed/);
  assert.equal(calls, 0);
});

test("an external edit while exporting stops sharing and cannot overwrite browser work", async () => {
  const { project, context } = fixture();
  project.exports = [];
  let posts = 0, applied = 0;
  const controller = createAirDrop({ read: () => context, save: async () => {}, apply() { applied++; }, notify() {},
    api: async (path) => {
      if (path.endsWith("/export")) {
        posts++;
        const changed = structuredClone(project);
        changed.cuts = [{ start: 1, end: 2 }];
        changed.jobs.export = { id: "job", status: "running" };
        return changed;
      }
      throw new Error("Must not share a changed edit");
    } });
  await assert.rejects(controller.send(), /edit changed/);
  assert.equal(posts, 1);
  assert.equal(applied, 0);
});

test("a double click starts one native sharing request", async () => {
  const { project, context, exported } = fixture();
  let release, posts = 0;
  const saving = new Promise((r) => { release = r; });
  const controller = createAirDrop({ read: () => context, save: () => saving, apply() {}, notify() {},
    api: async (path) => {
      if (path.endsWith("/airdrop")) { posts++; return { id: "job", project_id: project.id, file: exported.file,
        status: "closed", message: "AirDrop window closed" }; }
      return project;
    } });
  const first = controller.send();
  await controller.send();
  release();
  await first;
  assert.equal(posts, 1);
});

test("missing export is rendered once and the resulting immutable file is shared", async () => {
  const { project, context, exported } = fixture();
  project.exports = [];
  const server = structuredClone(project), calls = [];
  const controller = createAirDrop({ read: () => context, save: async () => {},
    apply: (p) => { context.project = p; }, notify() {}, wait: async () => {},
    api: async (path, options) => {
      calls.push([path, options]);
      if (path.endsWith("/export")) {
        assert.equal(options.body.base_revision, 8);
        server.jobs.export = { id: "export-job", status: "queued" };
        server.revision++;
      } else if (path.endsWith("/status")) {
        server.jobs.export.status = "done";
        server.exports.push(exported);
        server.revision++;
      } else if (path.endsWith("/airdrop")) {
        assert.equal(options.body.file, exported.file);
        assert.equal(options.body.base_revision, server.revision);
        return { id: "native", project_id: project.id, file: exported.file, status: "closed", message: "AirDrop window closed" };
      }
      return structuredClone(server);
    } });
  assert.equal((await controller.send()).status, "closed");
  assert.equal(calls.filter(([p]) => p.endsWith("/export")).length, 1);
  assert.equal(calls.filter(([p]) => p.endsWith("/airdrop")).length, 1);
});
