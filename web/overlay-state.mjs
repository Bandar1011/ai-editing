// Merge only server-owned enrichment; later local edits and deletions win.
export function mergeOverlayNormalization(live, sent, canonical) {
  let changed = false;
  const result = live.map((overlay) => {
    const before = sent.find((o) => o.id === overlay.id);
    const saved = canonical.find((o) => o.id === overlay.id);
    if (
      !before || !saved || overlay.asset_id !== before.asset_id ||
      saved.asset_id !== before.asset_id
    )
      return overlay;
    let next = overlay;
    for (const field of ["role", "entrance_sound"]) {
      if (field === "entrance_sound" && overlay.role !== saved.role) continue;
      if (
        Object.hasOwn(saved, field) &&
        JSON.stringify(overlay[field]) === JSON.stringify(before[field]) &&
        JSON.stringify(overlay[field]) !== JSON.stringify(saved[field])
      ) {
        next = { ...next, [field]: structuredClone(saved[field]) };
        changed = true;
      }
    }
    return next;
  });
  return changed ? result : live;
}
