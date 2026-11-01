import test from "node:test";
import assert from "node:assert/strict";
import {
  clipsFor,
  cutsForClips,
  keptRanges,
  mappedSpans,
  sourceAt,
  trimClip,
} from "../web/timeline.mjs";
const makeId = () => "manual";

test("splits survive saving without removing frames or changing annotation anchors", () => {
  const edit = JSON.parse(JSON.stringify({ cuts: [], split_points: [3, 7] }));
  const clips = clipsFor(10, edit.cuts, edit.split_points);
  assert.deepEqual(
    clips.map((c) => [c.start, c.end, c.output]),
    [
      [0, 3, 0],
      [3, 7, 3],
      [7, 10, 7],
    ],
  );
  assert.deepEqual(mappedSpans(2, 8, clips), [
    { start: 2, end: 3, source: 2 },
    { start: 3, end: 7, source: 3 },
    { start: 7, end: 8, source: 7 },
  ]);
  assert.deepEqual(cutsForClips(10, clips, [], makeId), []);
});
test("deleting a middle clip closes the gap and maps surviving captions and audio to the same frames", () => {
  const clips = clipsFor(10, [], [3, 7]).filter((_, i) => i !== 1);
  const cuts = cutsForClips(10, clips, [], makeId),
    next = clipsFor(10, cuts, [3]);
  assert.deepEqual(keptRanges(10, cuts), [
    [0, 3],
    [7, 10],
  ]);
  assert.equal(sourceAt(next, 3), 7);
  assert.deepEqual(mappedSpans(6, 9, next), [{ start: 3, end: 5, source: 7 }]);
});
test("either clip edge can restore deleted source footage without overlapping its neighbour", () => {
  const clips = clipsFor(10, [{ start: 3, end: 7, enabled: true }]);
  const restored = trimClip(clips, 0, "end", 4, 10);
  assert.deepEqual(cutsForClips(10, restored, [], makeId), []);
  assert.equal(restored[0].end, 7);
  assert.equal(trimClip(clips, 1, "start", -4, 10)[1].start, 3);
  assert.equal(trimClip(clips, 0, "end", 100, 10)[0].end, 7);
  assert.equal(trimClip(clips, 1, "start", -100, 10)[1].start, 3);
});
test("trimming a source remains reversible and bounded, including removing the last clip", () => {
  const one = clipsFor(10, []);
  const trimmed = trimClip(one, 0, "start", 2, 10);
  assert.deepEqual(keptRanges(10, cutsForClips(10, trimmed, [], makeId)), [
    [2, 10],
  ]);
  assert.equal(trimClip(trimmed, 0, "start", -2, 10)[0].start, 0);
  assert.equal(trimClip(one, 0, "start", 100, 10)[0].start, 9.96);
  assert.equal(trimClip(one, 0, "end", 100, 10)[0].end, 10);
  assert.deepEqual(clipsFor(10, cutsForClips(10, [], [], makeId)), []);
  assert.equal(sourceAt([], 0), 0);
});

test("overlapping additions stay individually selectable in lanes of one track", async () => {
  const { lanesFor } = await import("../web/timeline.mjs");
  assert.deepEqual(
    lanesFor([
      { start: 0, end: 10 },
      { start: 0, end: 5 },
      { start: 5, end: 8 },
    ]),
    [0, 1, 1],
  );
  assert.deepEqual(
    lanesFor([
      { start: 4, end: 6 },
      { start: 0, end: 4 },
    ]),
    [0, 0],
  );
});
