export function movedPosition(start, dx, dy, width, height) {
  const clamp = (n) => Math.round(Math.max(0, Math.min(1, n)) * 1e6) / 1e6;
  return { x: clamp(start.x + dx / width), y: clamp(start.y + dy / height) };
}
export function overlayBox(item) {
  const full = item.layout === "full";
  return {
    width: item.width ?? (full ? 1 : 0.88),
    height: item.height ?? (full ? 1 : 0.38),
    x: item.x ?? 0.5,
    y: item.y ?? (full ? 0.5 : item.layout === "bottom" ? 0.67 : 0.24),
  };
}
export function createCanvas({
  stage,
  getSelection,
  getItem,
  select,
  pushUndo,
  changed,
  refreshPreview,
  blocked,
}) {
  const box = document.getElementById("canvas-selection");
  let drag = null;
  function element() {
    const selected = getSelection();
    return (
      selected &&
      stage.querySelector(
        selected.kind === "caption"
          ? `[data-canvas-caption="${selected.id}"]`
          : `[data-canvas-overlay="${selected.id}"]`,
      )
    );
  }
  function refresh() {
    const selected = getSelection(),
      target = element();
    stage.classList.toggle(
      "base-selected",
      selected?.kind === "video" || selected?.kind === "effect",
    );
    box.hidden = !target;
    stage
      .querySelectorAll("[data-canvas-caption],[data-canvas-overlay]")
      .forEach((el) => el.setAttribute("aria-pressed", String(el === target)));
    if (!target) return;
    const r = target.getBoundingClientRect(),
      s = stage.getBoundingClientRect();
    box.style.left = `${((r.left - s.left) / s.width) * 100}%`;
    box.style.top = `${((r.top - s.top) / s.height) * 100}%`;
    box.style.width = `${(r.width / s.width) * 100}%`;
    box.style.height = `${(r.height / s.height) * 100}%`;
    box.dataset.kind = selected.kind;
    box.dataset.id = selected.id;
  }
  function position() {
    const target = element();
    if (!target) return null;
    const r = target.getBoundingClientRect(),
      s = stage.getBoundingClientRect();
    return {
      x: (r.left + r.width / 2 - s.left) / s.width,
      y: (r.top + r.height / 2 - s.top) / s.height,
    };
  }
  stage.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const caption = e.target.closest("[data-canvas-caption]"),
      overlay = e.target.closest("[data-canvas-overlay]");
    let selection = caption
      ? { kind: "caption", id: caption.dataset.canvasCaption }
      : overlay
        ? { kind: "overlay", id: overlay.dataset.canvasOverlay }
        : e.target.closest("#canvas-selection")
          ? getSelection()
          : null;
    if (!selection) {
      select(null);
      stage.focus({ preventScroll: true });
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    select(selection);
    element()?.focus({ preventScroll: true });
    if (blocked()) return;
    const item = getItem(selection),
      start = position();
    if (!item || !start) return;
    stage.querySelector("#video").pause();
    drag = {
      pointer: e.pointerId,
      item,
      start,
      x: e.clientX,
      y: e.clientY,
      rect: stage.getBoundingClientRect(),
      changed: false,
    };
    stage.setPointerCapture(e.pointerId);
  });
  stage.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.pointer) return;
    const dx = e.clientX - drag.x,
      dy = e.clientY - drag.y;
    if (!drag.changed && Math.hypot(dx, dy) < 2) return;
    if (!drag.changed) {
      pushUndo();
      drag.changed = true;
      stage.classList.add("moving-layer");
    }
    Object.assign(
      drag.item,
      movedPosition(drag.start, dx, dy, drag.rect.width, drag.rect.height),
    );
    refreshPreview();
  });
  function finish(e) {
    if (!drag || e.pointerId !== drag.pointer) return;
    const edited = drag.changed;
    drag = null;
    stage.classList.remove("moving-layer");
    if (edited) changed();
    refresh();
  }
  for (const event of ["pointerup", "pointercancel", "lostpointercapture"])
    stage.addEventListener(event, finish);
  function moveBy(dx, dy) {
    const item = getItem(getSelection()),
      start = position();
    if (!item || !start || blocked()) return false;
    pushUndo();
    Object.assign(
      item,
      movedPosition(start, dx, dy, stage.clientWidth, stage.clientHeight),
    );
    changed();
    refreshPreview();
    return true;
  }
  stage.addEventListener("keydown", (e) => {
    const caption = e.target.closest("[data-canvas-caption]"),
      overlay = e.target.closest("[data-canvas-overlay]");
    if ((caption || overlay) && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      e.stopPropagation();
      select(
        caption
          ? { kind: "caption", id: caption.dataset.canvasCaption }
          : { kind: "overlay", id: overlay.dataset.canvasOverlay },
      );
    }
  });
  return {
    refresh,
    moveBy,
    get dragging() {
      return !!drag;
    },
  };
}
