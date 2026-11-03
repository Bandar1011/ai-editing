import assert from "node:assert/strict";
import test from "node:test";
import { describeProgress, mountProgress } from "../web/progress.mjs";

const project = (jobs = {}) => ({ id: "clip", media_ready: true, jobs });
const state = (view, key) => view.rows.find((r) => r.key === key).state;

test("AirDrop progress excludes completed editing and only offers export when needed", () => {
  const p = project({ prepare: { status: "done" }, assistant: { status: "done" },
    export: { status: "running" } });
  const exporting = describeProgress(p, { delivery: { phase: "exporting", needsExport: true } });
  assert.deepEqual(exporting.rows.map((r) => r.label), ["Exporting video", "Choose your iPhone"]);
  assert.equal(state(exporting, "export"), "active");
  assert.equal(state(exporting, "phone"), "pending");
  const ready = describeProgress(p, { delivery: { phase: "choosing", needsExport: false } });
  assert.deepEqual(ready.rows.map((r) => r.label), ["Choose your iPhone"]);
  assert.equal(state(ready, "phone"), "active");
  assert.equal(ready.message, "");
  const opening = describeProgress(p, { delivery: { phase: "preparing", needsExport: true, exportReady: true } });
  assert.equal(state(opening, "export"), "done");
  assert.equal(state(opening, "phone"), "active");
  assert.equal(opening.rows[1].label, "Opening AirDrop");
});

test("a normal export never replays the preparation checklist", () => {
  const v = describeProgress(project({ export: { status: "running" } }));
  assert.deepEqual(v.rows.map((r) => r.label), ["Exporting video"]);
});

test("preparation groups technical stages into four useful milestones", () => {
  const v = describeProgress(project({ prepare: { status: "running", stage: "audio", stages: [] } }));
  assert.deepEqual(v.rows.filter((r) => !r.hidden).map((r) => r.label),
    ["Preparing video", "Transcribing speech", "Removing pauses", "Editing video"]);
  assert.equal(state(v, "preview"), "active");
  assert.equal(v.message, "Preparing video");
});

test("standalone transcription always shows its current operation during audio prep and setup", () => {
  for (const stage of ["audio", "transcribe", "transcription"]) {
    const v = describeProgress(project({ transcribe: { status: "running", stage, stages: [] } }));
    const shown = v.rows.filter((r) => !r.hidden);
    assert.equal(shown.length, 1);
    assert.equal(shown[0].key, "transcript");
    assert.equal(shown[0].state, "active");
    assert.equal(v.message, shown[0].label);
  }
});

test("cached audio revisits do not erase completed transcription or fake the next active step", () => {
  const p = project({ prepare: { status: "running", stage: "audio", stage_status: "done",
    stages: [{ stage: "audio" }, { stage: "signal" }, { stage: "transcription" }] } });
  const v = describeProgress(p);
  assert.equal(state(v, "audio"), "done");
  assert.equal(state(v, "transcript"), "done");
  assert.equal(state(v, "pauses"), "pending");
});

test("an actual running stage remains bold even when a prior completion was recorded", () => {
  const v = describeProgress(project({ prepare: { status: "running", stage: "transcription",
    stage_status: "running", stages: [{ stage: "transcription" }] } }));
  assert.equal(state(v, "transcript"), "active");
});

test("skipped work has its own state and no completed marker", () => {
  const v = describeProgress(project({ prepare: { status: "done", stages: [
    { stage: "retakes", status: "skipped", reason: "Disabled" },
  ] } }));
  assert.equal(state(v, "takes"), "skipped");
  assert.equal(state(v, "transcript"), "pending");
});

test("a failed speech stage preserves completed transcription and future work", () => {
  const v = describeProgress(project({ prepare: { status: "error", stage: "speech",
    message: "Speech detection failed", stages: [{ stage: "transcription" }] } }));
  assert.equal(state(v, "transcript"), "done");
  assert.equal(state(v, "pauses"), "error");
  assert.equal(state(v, "takes"), "pending");
  assert.equal(v.message, "Speech detection failed");
});

test("a new queued attempt does not borrow completed steps from an older AI pass", () => {
  const p = { ...project({ prepare: { status: "queued" },
    assistant: { status: "done", preparation_key: "old" } }), preparation_key: "old" };
  assert.equal(state(describeProgress(p), "assistant"), "pending");
  p.jobs.prepare = { status: "done", next_job_pending: true };
  p.preparation_key = "new";
  const v = describeProgress(p);
  assert.equal(state(v, "assistant"), "queued");
  assert.equal(v.message, "Waiting for AI editor");
});

test("silent recordings explicitly skip speech editing without showing fake successful transcription", () => {
  const p = { ...project({ prepare: { status: "done" } }), preparation_key: "visual", preparation_kind: "visual" };
  const v = describeProgress(p);
  assert.equal(state(v, "transcript"), "skipped");
  assert.equal(state(v, "pauses"), "skipped");
});

test("an old export only completes the export step when the current edit matches", () => {
  const p = project({ export: { status: "done" } });
  assert.equal(state(describeProgress(p), "export"), "pending");
  assert.equal(state(describeProgress(p, { exportReady: true }), "export"), "done");
});

test("the checklist is visible only during work and the prepare-to-AI handoff", () => {
  assert.equal(describeProgress(project({ prepare: { status: "running", stages: [] } })).visible, true);
  assert.equal(describeProgress(project({ prepare: { status: "done", next_job_pending: true } })).visible, true);
  assert.equal(describeProgress(project({ prepare: { status: "done" } })).visible, false);
  assert.equal(describeProgress(project({ prepare: { status: "error", message: "Stopped" } })).visible, false);
});

test("upload byte completion still reports importing until the server responds", () => {
  const v = describeProgress(null, { upload: { phase: "importing" } });
  assert.equal(v.loading, "Importing video");
  assert.equal(state(v, "import"), "active");
  assert.deepEqual(v.rows.map((r) => r.key), ["import"]);
});

test("standalone transcription and pause removal show their own completed work", () => {
  const v = describeProgress(project({ transcribe: { status: "done", queued_at: 10, stages: [{ stage: "audio" }, { stage: "transcription" }] },
    silence: { status: "done", queued_at: 11 } }));
  for (const key of ["audio", "transcript", "captions", "pauses"]) assert.equal(state(v, key), "done");
  assert.equal(state(v, "assistant"), "pending");
});

test("a preview recovered within preparation replaces the old preview failure", () => {
  const v = describeProgress(project({ preview: { status: "error", message: "Old failure" },
    prepare: { status: "running", stage: "transcription", stages: [{ stage: "preview" }, { stage: "waveform" }] } }));
  assert.equal(state(v, "preview"), "done");
});

test("polling preserves the spinner element and updates its state in place", (t) => {
  const previous = globalThis.document;
  const element = () => ({ children: [], dataset: {}, textContent: "", attrs: {},
    append(...children) { this.children.push(...children); },
    setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; },
    classList: { toggle() {} } });
  globalThis.document = { createElement: element };
  t.after(() => { if (previous) globalThis.document = previous; else delete globalThis.document; });
  const root = element(), message = element(), presenter = mountProgress(root, message);
  const v = describeProgress(project({ prepare: { status: "running", stage: "transcription", stages: [] } }));
  presenter.update(v);
  const item = root.children[3], indicator = item.children[0];
  for (let i = 0; i < 20; i++) presenter.update(structuredClone(v));
  assert.equal(root.children.length, 9);
  assert.strictEqual(root.children[3], item);
  assert.strictEqual(item.children[0], indicator);
  assert.equal(item.dataset.state, "active");
  presenter.update(describeProgress(project({ prepare: { status: "done", stages: [{ stage: "transcription" }] } })));
  assert.strictEqual(item.children[0], indicator);
  assert.equal(indicator.textContent, "✓");
});
