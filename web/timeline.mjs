// Source media stays intact. Clips are views of kept ranges, separated by edit points.
export function keptRanges(duration, cuts) {
  const removed = [...cuts]
    .filter((c) => c.enabled)
    .sort((a, b) => a.start - b.start);
  const kept = [];
  let cursor = 0;
  for (const c of removed) {
    if (c.start > cursor) kept.push([cursor, c.start]);
    cursor = Math.max(cursor, c.end);
  }
  if (cursor < duration) kept.push([cursor, duration]);
  return kept;
}
export function clipsFor(duration, cuts, splits = []) {
  const clips = [];
  let output = 0;
  for (const [start, end] of keptRanges(duration, cuts)) {
    const points = [
      start,
      ...[...new Set(splits)]
        .filter((t) => t > start + 0.001 && t < end - 0.001)
        .sort((a, b) => a - b),
      end,
    ];
    for (let i = 0; i < points.length - 1; i++) {
      const length = points[i + 1] - points[i];
      clips.push({ start: points[i], end: points[i + 1], output, length });
      output += length;
    }
  }
  return clips;
}
export function sourceAt(clips, time) {
  if (!clips.length) return 0;
  const clip =
    clips.find((c) => time < c.output + c.length - 0.000001) || clips.at(-1);
  return Math.min(
    clip.end - 0.000001,
    clip.start + Math.max(0, time - clip.output),
  );
}
export function cutsForClips(duration, clips, previous, makeId) {
  const ranges = [...clips].sort((a, b) => a.start - b.start);
  const removed = [];
  let cursor = 0;
  for (const c of ranges) {
    if (c.start - cursor >= 0.02) removed.push([cursor, c.start]);
    cursor = Math.max(cursor, c.end);
  }
  if (duration - cursor >= 0.02) removed.push([cursor, duration]);
  return [
    ...previous.filter((c) => !c.enabled),
    ...removed.map(([start, end]) => {
      const existing = previous.find(
        (c) =>
          c.enabled &&
          Math.abs(c.start - start) < 0.000001 &&
          Math.abs(c.end - end) < 0.000001,
      );
      return (
        existing || { id: makeId(), start, end, enabled: true, kind: "manual" }
      );
    }),
  ];
}
export function trimClip(clips, index, edge, delta, duration) {
  const next = clips.map((c) => ({ ...c }));
  const clip = next[index];
  if (edge === "start")
    clip.start = Math.max(
      index ? next[index - 1].end : 0,
      Math.min(clip.end - 0.04, clip.start + delta),
    );
  else
    clip.end = Math.min(
      index < next.length - 1 ? next[index + 1].start : duration,
      Math.max(clip.start + 0.04, clip.end + delta),
    );
  // Avoid unrepresentable, sub-frame gaps: a tiny gap snaps closed.
  const left = index ? next[index - 1].end : 0;
  const right = index < next.length - 1 ? next[index + 1].start : duration;
  if (clip.start - left < 0.02) clip.start = left;
  if (right - clip.end < 0.02) clip.end = right;
  return next;
}
export function mappedSpans(start, end, clips) {
  return clips.flatMap((c) => {
    const a = Math.max(start, c.start),
      b = Math.min(end, c.end);
    return b - a >= 0.001
      ? [
          {
            start: c.output + a - c.start,
            end: c.output + b - c.start,
            source: a,
          },
        ]
      : [];
  });
}

export function lanesFor(items) {
  const ends = [],
    lanes = [];
  for (const { item, index } of items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => a.item.start - b.item.start)) {
    let lane = ends.findIndex((end) => end <= item.start + 0.000001);
    if (lane < 0) lane = ends.length;
    ends[lane] = item.end;
    lanes[index] = lane;
  }
  return lanes;
}
