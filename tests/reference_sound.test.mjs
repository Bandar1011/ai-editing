import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { entranceEvent } from "../web/timeline.mjs";
import { mergeOverlayNormalization } from "../web/overlay-state.mjs";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/reference_sound_cases.json", import.meta.url)));
test("reference pop timing matches the export scenarios", () => {
  for (const scenario of fixture.cases) {
    const overlay = { ...structuredClone(fixture.overlay), ...scenario.overlay };
    Object.assign(overlay.entrance_sound, scenario.sound);
    const event = entranceEvent(overlay, scenario.kept, scenario.sound_duration);
    if (scenario.expected === null) assert.equal(event, null, scenario.name);
    else for (const key of ["start", "end", "source"])
      assert.ok(Math.abs(event[key] - scenario.expected[key]) < 1e-9, `${scenario.name}: ${key}`);
  }
});

test("server enrichment preserves edits and never resurrects deleted references", () => {
  const sent = [{ id: "ref", asset_id: "visual", start: 1, end: 4, role: "reference" }];
  const sound = { asset_id: "pop", asset_in: .1, volume: .35, enabled: true };
  const canonical = [{ ...sent[0], entrance_sound: sound }];
  const live = [{ ...sent[0], start: 2 }];
  const merged = mergeOverlayNormalization(live, sent, canonical);
  assert.equal(merged[0].start, 2);
  assert.deepEqual(merged[0].entrance_sound, sound);
  assert.deepEqual(mergeOverlayNormalization([], sent, canonical), []);
  const optedOut = [{ ...live[0], entrance_sound: null }];
  assert.equal(mergeOverlayNormalization(optedOut, sent, canonical)[0].entrance_sound, null);
  const adjusted = [{ ...live[0], entrance_sound: { ...sound, volume: .2, enabled: false } }];
  assert.deepEqual(mergeOverlayNormalization(adjusted, sent, canonical), adjusted);
  const roleChanged = [{ ...live[0], role: "title", entrance_sound: null }];
  assert.deepEqual(mergeOverlayNormalization(roleChanged, sent, canonical), roleChanged);
  const reclassified = [{ ...live[0], role: "graphic" }];
  assert.deepEqual(mergeOverlayNormalization(reclassified, sent, canonical), reclassified);
  assert.equal(sent[0].entrance_sound, undefined);
  // The same reconciliation freezes a redo snapshot created while save was pending.
  const redo = mergeOverlayNormalization(structuredClone(sent), sent, canonical);
  assert.deepEqual(redo[0].entrance_sound, sound);
  assert.equal(mergeOverlayNormalization(merged, canonical, canonical), merged);
});
