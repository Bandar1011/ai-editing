import { createCanvas } from "./canvas.mjs?v=factory-3";
import {
  keptRanges,
  clipsFor,
  sourceAt,
  cutsForClips,
  trimClip,
  mappedSpans,
  lanesFor,
} from "./timeline.mjs?v=factory-3";
import { createProduction } from "./production.js?v=factory-3";
const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const clone = (value) => structuredClone(value);
const uid = () => crypto.randomUUID().replaceAll("-", "").slice(0, 10);
const video = $("video");
let project = null,
  projects = [],
  health = {},
  tab = "auto",
  mode = "edited";
let selectedClip = null,
  selectedSubtitle = null,
  undo = [],
  redo = [];
let dirty = false,
  savePromise = null,
  saveTimer = null,
  editSequence = 0,
  savedEditable = null;
let conflicted = false,
  pollRunning = false,
  dragging = null,
  toastTimer;
let reviewFile = null;
let timelineFrame = null;
let activeCaptionIds = new Set();
let lastTrimTarget = null;
let lastTab = "auto",
  selectedLayer = null,
  canvas;
const ownJobs = new Set();
const production = createProduction({
  getProject: () => project,
  applyProject: (p) => {
    project = p;
    savedEditable = editable(p);
    renderProject();
  },
  api,
  changed,
  pushUndo,
  saveNow: async () => {
    await saveNow();
    if (conflicted)
      throw new Error("Load the latest project before continuing.");
  },
  toast,
  time,
  parseTime,
  video,
  outputTime,
  isEdited: () => mode === "edited" && clips().length > 0,
  showOriginal: () => setMode("original"),
  refreshTimeline: () => {
    if (project) renderTimeline();
  },
  task,
  selectLayer,
  onPreviewUpdate: () => canvas?.refresh(),
});
canvas = createCanvas({
  stage: $("video-stage"),
  getSelection: () => selectedLayer,
  getItem: layerItem,
  select: selectLayer,
  pushUndo,
  changed: () => {
    changed();
    renderLists();
    updateCaption();
    production.render(project);
  },
  refreshPreview: () => {
    updateCaption();
    production.updatePreview();
  },
  blocked: () => busy() || conflicted,
});

function time(value, precise = true) {
  const n = Math.max(0, Number(value) || 0);
  const ticks = Math.floor(n * 100 + 0.000001),
    minutes = Math.floor(ticks / 6000),
    seconds = Math.floor(ticks / 100) % 60,
    centiseconds = ticks % 100;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}${precise ? "." + String(centiseconds).padStart(2, "0") : ""}`;
}
function parseTime(value) {
  const parts = String(value).trim().split(":");
  if (!parts.every((p) => /^\d+(\.\d+)?$/.test(p)) || parts.length > 3)
    return NaN;
  return parts.reduce((total, part) => total * 60 + Number(part), 0);
}
function toast(message, error = false) {
  $("toast").textContent = message;
  $("toast").classList.toggle("error", error);
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(
    () => ($("toast").hidden = true),
    error ? 8000 : 4200,
  );
}
async function api(path, options = {}) {
  const opts = { ...options };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = { "Content-Type": "application/json", ...opts.headers };
    opts.body = JSON.stringify(opts.body);
  }
  const result = await fetch(path, opts);
  if (!result.ok) {
    const payload = await result.json().catch(() => ({}));
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((e) => e.msg).join("; ")
      : payload.detail;
    const error = new Error(detail || `Request failed (${result.status})`);
    error.status = result.status;
    throw error;
  }
  return result.json();
}
function editable(p = project) {
  return {
    name: p.name,
    split_points: clone(p.split_points || []),
    cuts: clone(p.cuts),
    subtitles: clone(p.subtitles),
    subtitle_style: clone(p.subtitle_style),
    brief: clone(p.brief),
    references: clone(p.references),
    overlays: clone(p.overlays),
    punches: clone(p.punches),
    music: clone(p.music),
    story: clone(p.story),
  };
}
function busy() {
  return (
    project && Object.values(project.jobs).some((j) => j.status === "running")
  );
}
function duration() {
  return project?.media.duration || 0;
}
function mergedCuts() {
  const result = [];
  for (const cut of [...project.cuts]
    .filter((c) => c.enabled)
    .sort((a, b) => a.start - b.start)) {
    const last = result.at(-1);
    if (last && cut.start <= last.end + 0.001)
      last.end = Math.max(last.end, cut.end);
    else result.push({ start: cut.start, end: cut.end });
  }
  return result;
}
function outputTime(sourceTime) {
  return (
    sourceTime -
    mergedCuts().reduce(
      (sum, c) => sum + Math.max(0, Math.min(sourceTime, c.end) - c.start),
      0,
    )
  );
}
function pushUndo() {
  if (!project) return;
  undo.push(editable());
  if (undo.length > 60) undo.shift();
  redo = [];
  updateUndo();
}
function updateUndo() {
  $("undo-button").disabled = !undo.length;
  $("redo-button").disabled = !redo.length;
}
function changed() {
  if (!project) return;
  dirty = true;
  editSequence++;
  localStorage.setItem(
    `aiedit-draft-${project.id}`,
    JSON.stringify(editable()),
  );
  setSaveStatus("Saving…");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(
    () => saveNow().catch((e) => toast(e.message, true)),
    450,
  );
  updateSummary();
  updateCaption();
  scheduleTimeline();
}
function setSaveStatus(text) {
  $("save-status").textContent = text === "All changes saved" ? "Saved" : text;
}
async function saveNow() {
  clearTimeout(saveTimer);
  if (savePromise) {
    await savePromise;
    if (dirty && !conflicted) return saveNow();
    return;
  }
  if (!project || !dirty || conflicted) return;
  const id = project.id,
    snapshot = editable(),
    sequence = editSequence;
  const base = clone(savedEditable);
  savePromise = (async () => {
    let response;
    try {
      response = await api(`/api/projects/${id}`, {
        method: "PUT",
        body: { base_revision: project.revision, ...snapshot },
      });
    } catch (error) {
      if (error.status !== 409) throw error;
      const remote = await api(`/api/projects/${id}`);
      if (JSON.stringify(editable(remote)) !== JSON.stringify(base)) {
        conflicted = true;
        $("conflict-banner").hidden = false;
        setSaveStatus("Draft kept locally");
        throw new Error(
          "This project changed in chat. Load the latest project to continue; your browser draft is retained.",
        );
      }
      response = await api(`/api/projects/${id}`, {
        method: "PUT",
        body: { base_revision: remote.revision, ...snapshot },
      });
    }
    if (project?.id !== id) return;
    project.revision = response.revision;
    project.jobs = response.jobs;
    project.exports = response.exports;
    project.reviews = response.reviews;
    savedEditable = editable(response);
    if (sequence === editSequence) {
      dirty = false;
      localStorage.removeItem(`aiedit-draft-${id}`);
      setSaveStatus("All changes saved");
      renderJobs();
      updateSummary();
    }
  })();
  try {
    await savePromise;
  } finally {
    savePromise = null;
  }
  if (dirty && !conflicted) return saveNow();
}

async function loadProjects() {
  projects = await api("/api/projects");
}
async function openProject(id, discard = false) {
  if (project && !discard) await saveNow();
  video.pause();
  const p = await api(`/api/projects/${id}`);
  project = p;
  localStorage.setItem("aiedit-active-project", p.id);
  $("import-button").textContent = "Replace video";
  reviewFile = p.exports.at(-1)?.file || null;
  $("history-results").innerHTML = "";
  dirty = false;
  conflicted = false;
  editSequence = 0;
  undo = [];
  redo = [];
  selectedClip = selectedSubtitle = null;
  selectedLayer = null;
  setTab("auto");
  savedEditable = editable(p);
  $("conflict-banner").hidden = true;
  history.replaceState(null, "", `?project=${p.id}`);
  renderProject();
  await loadProjects();
  const draft = localStorage.getItem(`aiedit-draft-${id}`);
  if (draft && !discard)
    toast(
      "An unsaved browser draft is available. It is retained locally; the latest saved project is shown.",
      true,
    );
}
function renderProject() {
  if (!project) return;
  $("empty-state").hidden = true;
  $("editor").hidden = false;
  $("editor").style.setProperty("--preview-ratio", 9 / 16);
  const address = `/api/projects/${project.id}/media`;
  if (project.media_ready && video.dataset.project !== project.id) {
    video.src = address;
    video.dataset.project = project.id;
    video.load();
  } else if (!project.media_ready && video.dataset.project !== project.id) {
    video.removeAttribute("src");
    video.load();
  }
  $("video-placeholder").hidden = project.media_ready;
  $("video-placeholder").innerHTML =
    project.jobs.preview?.status === "error"
      ? "Preview could not be prepared. Check the operation message."
      : '<span class="spinner"></span>Preparing your preview…';
  $("threshold").value = project.silence_options.threshold_db;
  $("threshold-value").textContent =
    `${project.silence_options.threshold_db} dB`;
  $("minimum").value = project.silence_options.minimum;
  $("padding").value = project.silence_options.padding;
  $("font-size").value = project.subtitle_style.font_size;
  $("font-size-value").textContent = project.subtitle_style.font_size;
  $("caption-position").value = project.subtitle_style.position;
  $("captions-enabled").checked = project.subtitle_style.enabled;
  $("download-srt").href = `/api/projects/${project.id}/subtitles.srt`;
  $("source-transcript").href = `/api/projects/${project.id}/transcript.srt`;
  $("source-json").href = `/api/projects/${project.id}/transcript.json`;
  $("transcript-downloads").hidden = !project.transcript;
  const available = clips();
  if (
    mode === "edited" &&
    Number.isFinite(video.duration) &&
    available.length &&
    !available.some(
      (c) => video.currentTime >= c.start && video.currentTime < c.end,
    )
  ) {
    const next =
      available.find((c) => c.start > video.currentTime) || available.at(-1);
    video.currentTime =
      next.start > video.currentTime
        ? next.start
        : Math.max(next.start, next.end - 1 / project.media.fps);
  }
  renderLists();
  renderTimeline();
  renderJobs();
  updateSummary();
  updateUndo();
  updateCaption();
  updateTime();
  renderExport();
  renderReview();
  production.render(project);
}
function renderExport() {
  const exported = project.exports.at(-1);
  $("export-result").hidden = !exported;
  if (!exported) return;
  const current = {
    cuts: project.cuts,
    split_points: project.split_points,
    subtitles: project.subtitles,
    subtitle_style: project.subtitle_style,
    overlays: project.overlays,
    punches: project.punches,
    music: project.music,
    story: project.story,
  };
  const matches =
    exported.edit_state &&
    Object.entries(current).every(
      ([key, value]) =>
        JSON.stringify(
          exported.edit_state[key] ?? (key === "split_points" ? [] : null),
        ) === JSON.stringify(value),
    ) &&
    JSON.stringify(exported.brief) === JSON.stringify(project.brief) &&
    JSON.stringify(exported.references) === JSON.stringify(project.references);
  $("export-result").innerHTML =
    `<span>${matches ? "✓ Export ready" : "Previous export"} <span class="muted">· ${time(exported.duration, false)}</span></span><a download href="/api/projects/${project.id}/exports/${exported.file}">Download video ↗</a>`;
}
function renderLists() {
  $("subtitles-list").innerHTML =
    [...project.subtitles]
      .sort((a, b) => a.start - b.start)
      .map(
        (c, i) =>
          `<div class="subtitle-row" data-subtitle="${c.id}"><div class="times"><button class="seek-item" data-seek="${c.start}" aria-label="Preview subtitle ${i + 1}">▷</button><input class="time-input" aria-label="Subtitle ${i + 1} start" data-subtitle-field="start" data-id="${c.id}" value="${time(c.start)}"><span class="muted">→</span><input class="time-input" aria-label="Subtitle ${i + 1} end" data-subtitle-field="end" data-id="${c.id}" value="${time(c.end)}"><button class="remove-item" data-remove-subtitle="${c.id}" aria-label="Remove subtitle ${i + 1}">×</button></div><textarea dir="auto" aria-label="Subtitle ${i + 1} text" placeholder="Type a subtitle…" maxlength="5000" data-caption-text="${c.id}">${esc(c.text)}</textarea>${c.x != null && c.y != null ? `<button class="text-button" data-reset-caption="${c.id}">Reset position</button>` : ""}</div>`,
      )
      .join("") || '<div class="empty-list">No captions</div>';
}
function scheduleTimeline() {
  if (timelineFrame !== null) return;
  timelineFrame = requestAnimationFrame(() => {
    timelineFrame = null;
    renderTimeline();
  });
}
function sourceRanges() {
  return keptRanges(duration(), project?.cuts || []);
}
function clips() {
  return project
    ? clipsFor(duration(), project.cuts, project.split_points)
    : [];
}
function editDuration() {
  return clips().reduce((sum, c) => sum + c.length, 0);
}
function updateClipActions() {
  const all = clips(),
    t = video.currentTime;
  $("split-button").disabled =
    busy() ||
    conflicted ||
    !all.some((c) => t > c.start + 0.04 && t < c.end - 0.04);
  $("delete-clip-button").disabled =
    ((selectedClip === null || !all[selectedClip]) && !layerItem()) ||
    busy() ||
    conflicted;
  $("restore-video").disabled = busy() || conflicted;
  $("restore-video").hidden =
    !project?.cuts.some((c) => c.enabled) && !project?.split_points?.length;
  $("range-label").textContent =
    selectedClip !== null && all[selectedClip]
      ? `Clip ${selectedClip + 1} · ${time(all[selectedClip].length)}`
      : "";
}
function renderTimeline() {
  if (timelineFrame !== null) {
    cancelAnimationFrame(timelineFrame);
    timelineFrame = null;
  }
  if (!project) return;
  const all = clips(),
    d = duration(),
    assets = production.getAssets();
  if (!all[selectedClip]) selectedClip = null;
  const style = (a, b) =>
    `left:${(a / d) * 100}%;width:${((b - a) / d) * 100}%`;
  const target = (d / Math.max(1, $("timeline").clientWidth)) * 110;
  const step =
    [
      0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800,
      3600, 7200, 14400,
    ].find((n) => n >= target) || 14400;
  $("timeline-ruler").innerHTML = Array.from(
    { length: Math.floor(d / step) + 1 },
    (_, i) =>
      `<span style="left:${((i * step) / d) * 100}%">${time(i * step, step < 1)}</span>`,
  ).join("");
  $("video-clips").innerHTML = all
    .map(
      (c, i) =>
        `<div class="track-clip video-segment ${i === selectedClip ? "selected" : ""}" data-clip="${i}" style="${style(c.output, c.output + c.length)}" title="${esc(project.filename)} · ${time(c.start)}–${time(c.end)}"><button class="clip-select" data-select-clip="${i}" aria-label="Select video clip ${i + 1}">${esc(project.filename)}</button><span class="trim-handle start" data-trim="start" title="Drag to trim. Double-click to restore." role="slider" tabindex="0" aria-label="Clip ${i + 1} start" aria-valuemin="${i ? all[i - 1].end : 0}" aria-valuemax="${c.end - 0.04}" aria-valuenow="${c.start}" aria-valuetext="${time(c.start)}"></span><span class="trim-handle end" data-trim="end" title="Drag to trim. Double-click to restore." role="slider" tabindex="0" aria-label="Clip ${i + 1} end" aria-valuemin="${c.start + 0.04}" aria-valuemax="${i < all.length - 1 ? all[i + 1].start : duration()}" aria-valuenow="${c.end}" aria-valuetext="${time(c.end)}"></span></div>`,
    )
    .join("");
  const px = $("timeline").clientWidth / d;
  $("voice-clips").innerHTML = all
    .map(
      (c, i) =>
        `<button class="track-clip voice-segment ${i === selectedClip ? "selected" : ""}" data-select-clip="${i}" style="${style(c.output, c.output + c.length)}" aria-label="Select original audio clip ${i + 1}">${project.waveform_ready ? `<i class="audio-wave" style="background-image:url('/api/projects/${project.id}/waveform');background-size:${duration() * px}px 100%;background-position:${-c.start * px}px 0"></i>` : ""}</button>`,
    )
    .join("");
  $("voice-row").hidden = !project.media.has_audio;
  const spans = (item, join = true) => {
    const mapped = mappedSpans(item.start, item.end, all);
    if (!join) return mapped;
    return mapped.reduce((result, span) => {
      const last = result.at(-1);
      if (last && Math.abs(last.end - span.start) < 0.001) last.end = span.end;
      else result.push({ ...span });
      return result;
    }, []);
  };
  $("subtitle-track").innerHTML = project.subtitle_style.enabled
    ? project.subtitles
        .flatMap((c) =>
          spans(c).map(
            (s) =>
              `<button class="subtitle-segment ${c.id === selectedSubtitle ? "selected" : ""}" data-cue="${c.id}" style="${style(s.start, s.end)}" title="${esc(c.text)}" aria-label="Caption: ${esc(c.text || "Empty caption")}">${esc(c.text || "Caption")}</button>`,
          ),
        )
        .join("")
    : "";
  $("overlay-track").innerHTML = project.overlays
    .filter(
      (o) =>
        o.enabled && assets.find((a) => a.id === o.asset_id)?.kind !== "audio",
    )
    .flatMap((o) =>
      spans(o).map(
        (s) =>
          `<button class="track-clip" data-track-overlay="${o.id}" style="${style(s.start, s.end)}">${esc(assets.find((a) => a.id === o.asset_id)?.name || "Overlay")}</button>`,
      ),
    )
    .join("");
  $("effect-track").innerHTML = project.punches
    .filter((p) => p.enabled && p.scale > 1)
    .flatMap((p) =>
      spans(p).map(
        (s) =>
          `<button class="track-clip effect-clip" data-track-effect="${p.id}" style="${style(s.start, s.end)}">Zoom ${p.scale}×</button>`,
      ),
    )
    .join("");
  function audioClip(asset, start, end, offset, attrs, name) {
    const wave =
      asset?.has_audio && asset.duration > 0
        ? `background-image:url('/api/assets/${asset.id}/waveform');background-repeat:repeat-x;background-size:${asset.duration * px}px 100%;background-position:${-(offset % asset.duration) * px}px 0`
        : "";
    return `<button class="track-clip audio-clip" ${attrs} style="${style(start, end)}" title="${esc(name)}"><i class="audio-wave" style="${wave}"></i><span>${esc(name)}</span></button>`;
  }
  const m = project.music,
    ma = assets.find((a) => a.id === m?.asset_id);
  $("music-track").innerHTML =
    m?.enabled && ma && all.length
      ? audioClip(
          ma,
          0,
          editDuration(),
          m.offset,
          'data-track-music="true"',
          ma.name,
        )
      : "";
  $("addon-audio-track").innerHTML = project.overlays
    .filter(
      (o) =>
        o.enabled &&
        o.audio &&
        assets.some((a) => a.id === o.asset_id && a.has_audio),
    )
    .flatMap((o) =>
      spans(o, false).map((s) => {
        const a = assets.find((a) => a.id === o.asset_id);
        return audioClip(
          a,
          s.start,
          s.end,
          o.asset_in + s.source - o.start,
          `data-track-overlay="${o.id}"`,
          a.name,
        );
      }),
    )
    .join("");
  for (const [row, track] of [
    ["caption", "subtitle"],
    ["overlay", "overlay"],
    ["effect", "effect"],
    ["music", "music"],
    ["addon-audio", "addon-audio"],
  ])
    $(row + "-row").hidden = !$(track + "-track").childElementCount;
  for (const [row, track] of [
    ["caption", "subtitle"],
    ["overlay", "overlay"],
    ["effect", "effect"],
    ["addon-audio", "addon-audio"],
  ]) {
    const lane = $(track + "-track"),
      nodes = [...lane.children];
    const lanes = lanesFor(
      nodes.map((el) => ({
        start: parseFloat(el.style.left),
        end: parseFloat(el.style.left) + parseFloat(el.style.width),
      })),
    );
    nodes.forEach((el, i) => (el.style.top = `${lanes[i] * 26 + 2}px`));
    const height = Math.max(26, (Math.max(-1, ...lanes) + 1) * 26);
    lane.style.height = height + "px";
    $(row + "-row").style.height = height + 2 + "px";
  }
  updateClipActions();
}

function renderJobs() {
  const running = Object.entries(project.jobs).find(
    ([, j]) => j.status === "running",
  );
  const latest = Object.entries(project.jobs).sort(
    (a, b) => (b[1].started_at || 0) - (a[1].started_at || 0),
  )[0];
  const error = latest?.[1].status === "error" ? latest : null;
  const names = {
    preview: "Preparing video & waveform…",
    silence: "Finding the quiet sections…",
    transcribe: "Transcribing on your Mac…",
    export: "Rendering your video…",
    prepare: "Preparing captions, speech cuts, and retake decisions…",
  };
  $("job-status").hidden = !running && !error;
  $("job-status").classList.toggle("error", !running && !!error);
  $("job-status").innerHTML = running
    ? `<span class="spinner"></span>${names[running[0]]}`
    : error
      ? esc(error[1].message)
      : "";
  $("export-button").disabled = !!running || conflicted || dirty;
  $("plain-export-button").disabled = !!running || conflicted || dirty;
  $("analyze-button").disabled =
    !!running || !project.media.has_audio || conflicted;
  $("transcribe-button").disabled =
    !!running ||
    !project.media.has_audio ||
    !health.transcription_ready ||
    !health.whisper_ready ||
    conflicted;
  $("transcribe-button").title = !health.transcription_ready
    ? "The local speech model is not installed yet."
    : "";
  $("silence-settings").disabled = !!running;
  $("prepare-button").disabled =
    !!running ||
    !project.media.has_audio ||
    conflicted ||
    !health.transcription_ready;
}
function updateSummary() {
  if (!project) return;
  const saved = mergedCuts().reduce((sum, c) => sum + c.end - c.start, 0);

  $("total-time").textContent = time(
    mode === "edited" ? duration() - saved : duration(),
  );
  $("export-button").disabled = busy() || conflicted || dirty;
  $("plain-export-button").disabled = busy() || conflicted || dirty;
  const empty = !clips().length;
  video.style.visibility = empty ? "hidden" : "";
  $("video-placeholder").hidden = project.media_ready && !empty;
  if (empty) $("video-placeholder").textContent = "No clips";
  $("export-button").disabled = busy() || conflicted || dirty || empty;
  updateClipActions();
  renderExport();
}
function updateCaption() {
  if (!project) return;
  const t = video.currentTime || 0,
    style = project.subtitle_style;
  const cues =
    style.enabled && mode === "edited" && clips().length
      ? project.subtitles.filter(
          (c) => c.start <= t && t < c.end && c.text.trim(),
        )
      : [];
  const holder = $("caption-overlay"),
    stage = $("video-stage"),
    active = new Set(cues.map((c) => c.id));
  for (const node of [...holder.children])
    if (!active.has(node.dataset.canvasCaption)) node.remove();
  for (const cue of cues) {
    let node = holder.querySelector(`[data-canvas-caption="${cue.id}"]`);
    if (!node) {
      node = document.createElement("div");
      node.className = "canvas-caption";
      node.dataset.canvasCaption = cue.id;
      node.setAttribute("role", "button");
      node.tabIndex = 0;
      holder.append(node);
    }
    const text = style.uppercase ? cue.text.toUpperCase() : cue.text;
    if (node.textContent !== text) node.textContent = text;
    node.setAttribute("aria-label", `Caption: ${cue.text}`);
    node.style.webkitTextStroke = `${(style.outline * stage.clientHeight) / 1080}px #101010`;
    node.style.fontSize = `${(style.font_size * stage.clientHeight) / 1080}px`;
    if (cue.x != null && cue.y != null) {
      node.style.left = `${cue.x * 100}%`;
      node.style.top = `${cue.y * 100}%`;
      node.style.bottom = "auto";
      node.style.transform = "translate(-50%,-50%)";
    } else {
      node.style.left = "50%";
      node.style.transform = "translateX(-50%)";
      node.style.top =
        style.position === "top" ? `${style.margin_percent}%` : "auto";
      node.style.bottom =
        style.position === "bottom" ? `${style.margin_percent}%` : "auto";
    }
  }
  for (const id of new Set([...activeCaptionIds, ...active]))
    document
      .querySelector(`[data-subtitle="${id}"]`)
      ?.classList.toggle("active", active.has(id));
  activeCaptionIds = active;
  canvas?.refresh();
}
function layerItem(selection = selectedLayer) {
  if (!project || !selection) return null;
  return (
    selection.kind === "caption"
      ? project.subtitles
      : selection.kind === "overlay"
        ? project.overlays
        : selection.kind === "effect"
          ? project.punches
          : []
  ).find((item) => item.id === selection.id);
}
function selectLayer(selection, { seekTo = false } = {}) {
  selectedLayer = selection;
  selectedSubtitle = selection?.kind === "caption" ? selection.id : null;
  if (!selection || selection.kind !== "video") selectedClip = null;
  const item = layerItem(selection);
  if (seekTo && item) {
    if (mode !== "edited") setMode("edited");
    video.pause();
    const span = mappedSpans(item.start, item.end, clips())[0];
    if (span) seek(span.source + Math.min(0.002, (span.end - span.start) / 2));
  }
  if (selection && selection.kind !== "video") {
    lastTab = selection.kind === "caption" ? "subtitles" : "visuals";
    if (tab) setTab(lastTab);
  }
  renderTimeline();
  document
    .querySelectorAll("[data-overlay],[data-punch],[data-subtitle]")
    .forEach((el) =>
      el.classList.toggle(
        "selected",
        !!selection &&
          [el.dataset.overlay, el.dataset.punch, el.dataset.subtitle].includes(
            selection.id,
          ),
      ),
    );
  canvas?.refresh();
}
function deleteSelection() {
  const item = layerItem();
  if (!item || selectedLayer?.kind === "video") {
    deleteClip();
    return;
  }
  if (busy() || conflicted) return;
  pushUndo();
  const key =
    selectedLayer.kind === "caption"
      ? "subtitles"
      : selectedLayer.kind === "overlay"
        ? "overlays"
        : "punches";
  project[key] = project[key].filter((o) => o.id !== item.id);
  selectedLayer = null;
  selectedSubtitle = null;
  changed();
  renderLists();
  production.render(project);
  renderTimeline();
  canvas?.refresh();
}

function updateTime() {
  if (!project) return;
  let t = video.currentTime || 0;
  if ($("export-dialog").open) {
    const version = project.exports.find((e) => e.file === reviewFile);
    let remaining = $("review-video").currentTime || 0;
    for (const range of version?.source_ranges || []) {
      t = Math.min(range.end, range.start + remaining);
      if (remaining <= range.end - range.start) break;
      remaining -= range.end - range.start;
    }
  }
  $("current-time").textContent = time(mode === "edited" ? outputTime(t) : t);
  $("playhead").style.left =
    `${Math.min(100, (outputTime(t) / (duration() || 1)) * 100)}%`;
  updateClipActions();
  updateCaption();
  production.updatePreview();
}
function skipCut() {
  if (!project || mode !== "edited" || video.paused) return;
  const c = mergedCuts().find(
    (c) =>
      video.currentTime >= c.start - 0.006 && video.currentTime < c.end - 0.006,
  );
  if (c) {
    if (c.end >= duration() - 0.03) {
      video.pause();
      video.currentTime = Math.min(duration(), c.end);
    } else video.currentTime = c.end + 0.002;
  }
}
function seek(t) {
  if (project?.media_ready) {
    video.currentTime = Math.max(0, Math.min(duration(), t));
    updateTime();
  }
}
function togglePlay() {
  if (!project?.media_ready || !clips().length) return;
  if (mode !== "edited") setMode("edited");
  const player = $("export-dialog").open ? $("review-video") : video;
  if (!player.currentSrc) return;
  if (player.paused) player.play().catch((e) => toast(e.message, true));
  else player.pause();
}
function setTab(value) {
  if (value) lastTab = value;
  tab = value;
  $("inspector").hidden = !value;
  $("editor").classList.toggle("panel-open", !!value);
  $("open-inspector").hidden = !!value;
  $("open-inspector").setAttribute("aria-expanded", String(!!value));
  for (const name of ["auto", "visuals", "subtitles"]) {
    $(`${name}-tab`).classList.toggle("active", value === name);
    $(`${name}-tab`).setAttribute("aria-selected", String(value === name));
    $(`${name}-panel`).hidden = value !== name;
  }
  canvas?.refresh();
}
function openExport() {
  if (!project?.exports.length) return;
  video.pause();
  renderReview();
  if (!$("export-dialog").open) $("export-dialog").showModal();
}
$("close-export").onclick = () => $("export-dialog").close();
$("export-dialog").addEventListener("close", () => {
  $("review-video").pause();
  updateTime();
});

function setMode(value) {
  mode = value;
  updateSummary();
  updateTime();
  skipCut();
}
async function task(kind, plain = false) {
  if (!project || busy()) return;
  await saveNow();
  if (conflicted) return;
  let body = {};
  if (kind === "silence")
    body = {
      threshold_db: Number($("threshold").value),
      minimum: Number($("minimum").value),
      padding: Number($("padding").value),
    };
  if (kind === "transcribe") body = { language: $("language").value };
  if (kind === "prepare")
    body = {
      language: $("language").value,
      max_words: project.subtitle_style.max_words,
    };
  if (kind === "export")
    body = {
      burn_subtitles: !plain && project.subtitle_style.enabled,
      label: $("export-label").value,
      plain,
      format: "vertical",
    };
  if (kind !== "export") pushUndo();
  ownJobs.add(kind);
  try {
    project = await api(`/api/projects/${project.id}/${kind}`, {
      method: "POST",
      body,
    });
    savedEditable = editable();
    renderProject();
  } catch (error) {
    ownJobs.delete(kind);
    throw error;
  }
}
async function upload(file) {
  if (!file) return;
  await saveNow();
  $("upload-overlay").hidden = false;
  $("upload-progress").textContent = "Copying to your local workspace…";
  try {
    const form = new FormData();
    form.append("file", file);
    const result = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/projects/upload");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable)
          $("upload-progress").textContent =
            `${Math.round((e.loaded / e.total) * 100)}% copied`;
      };
      xhr.onerror = () =>
        reject(new Error("The upload could not reach the local editor."));
      xhr.onload = () => {
        let data;
        try {
          data = JSON.parse(xhr.responseText);
        } catch {
          reject(new Error("The video could not be imported."));
          return;
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(data.detail || "Unable to import video."));
      };
      xhr.send(form);
    });
    await openProject(result.id);
  } finally {
    $("upload-overlay").hidden = true;
    $("video-input").value = "";
  }
}
function act(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (e) {
      toast(e.message, true);
    }
  };
}

$("import-button").onclick = () => $("video-input").click();
$("dropzone").onclick = () => $("video-input").click();
$("dropzone").onkeydown = (e) => {
  if (e.key === "Enter" || e.key === " ") $("video-input").click();
};
$("video-input").onchange = act((e) => upload(e.target.files[0]));
document.addEventListener("dragover", (e) => {
  if (e.dataTransfer.types.includes("Files")) {
    e.preventDefault();
    $("dropzone").classList.add("dragover");
  }
});
document.addEventListener("dragleave", (e) => {
  if (!e.relatedTarget) $("dropzone").classList.remove("dragover");
});
document.addEventListener(
  "drop",
  act((e) => {
    if (e.dataTransfer.files.length) {
      e.preventDefault();
      $("dropzone").classList.remove("dragover");
      return upload(e.dataTransfer.files[0]);
    }
  }),
);

$("visuals-tab").onclick = () => setTab("visuals");
$("subtitles-tab").onclick = () => setTab("subtitles");
$("auto-tab").onclick = () => setTab("auto");
$("open-inspector").onclick = () => setTab(lastTab);
$("close-inspector").onclick = () => setTab(null);
$("play-button").onclick = togglePlay;

$("back-button").onclick = () => seek(video.currentTime - 2);
$("forward-button").onclick = () => seek(video.currentTime + 2);
$("mute-button").onclick = () => {
  video.muted = !video.muted;
  $("mute-button").textContent = video.muted ? "Unmute" : "Mute";
  $("mute-button").setAttribute(
    "aria-label",
    video.muted ? "Unmute video" : "Mute video",
  );
};
$("fullscreen-button").onclick = act(() =>
  $("video-stage").requestFullscreen(),
);
video.addEventListener("timeupdate", () => {
  skipCut();
  updateTime();
});
let frameLoopActive = false;
function previewFrame() {
  if (video.paused) {
    frameLoopActive = false;
    return;
  }
  skipCut();
  $("playhead").style.left =
    `${Math.min(100, (outputTime(video.currentTime) / (duration() || 1)) * 100)}%`;
  if (video.requestVideoFrameCallback)
    video.requestVideoFrameCallback(previewFrame);
  else requestAnimationFrame(previewFrame);
}
video.addEventListener("play", () => {
  $("play-button").textContent = "Ⅱ";
  $("play-button").setAttribute("aria-label", "Pause video");
  skipCut();
  if (!frameLoopActive) {
    frameLoopActive = true;
    previewFrame();
  }
});
video.addEventListener("pause", () => {
  $("play-button").textContent = "▶";
  $("play-button").setAttribute("aria-label", "Play video");
});
video.addEventListener("seeked", updateTime);
video.addEventListener("loadedmetadata", () => {
  const first = sourceRanges()[0];
  if (mode === "edited" && first && video.currentTime < first[0])
    video.currentTime = Math.min(first[1], first[0] + 0.002);
  updateTime();
});
new ResizeObserver(() => {
  updateCaption();
  production.updatePreview();
}).observe($("video-stage"));
$("threshold").oninput = () =>
  ($("threshold-value").textContent = `${$("threshold").value} dB`);
$("analyze-button").onclick = act(() => task("silence"));
$("transcribe-button").onclick = act(() => task("transcribe"));
$("export-button").onclick = act(() => task("export"));
$("plain-export-button").onclick = act(() => task("export", true));
$("add-caption-button").onclick = () => {
  if (!project || duration() < 0.04) return;
  pushUndo();
  const start = Math.min(video.currentTime || 0, duration() - 0.04);
  const cue = {
    id: uid(),
    start,
    end: Math.min(duration(), start + 2),
    text: "",
  };
  project.subtitles.push(cue);
  changed();
  renderLists();
  renderTimeline();
  document.querySelector(`[data-caption-text="${cue.id}"]`)?.focus();
};
$("font-size").onpointerdown = pushUndo;
$("font-size").oninput = () => {
  project.subtitle_style.font_size = Number($("font-size").value);
  $("font-size-value").textContent = $("font-size").value;
  changed();
};
$("caption-position").onchange = () => {
  pushUndo();
  project.subtitle_style.position = $("caption-position").value;
  for (const cue of project.subtitles) {
    delete cue.x;
    delete cue.y;
  }
  changed();
  renderLists();
};
$("captions-enabled").onchange = () => {
  pushUndo();
  project.subtitle_style.enabled = $("captions-enabled").checked;
  changed();
};
const captionEdits = new WeakSet();
$("subtitles-list").addEventListener("focusin", (e) =>
  captionEdits.delete(e.target),
);
$("subtitles-list").addEventListener("input", (e) => {
  const textId = e.target.dataset.captionText,
    field = e.target.dataset.subtitleField;
  if (!textId && !field) return;
  const item = project.subtitles.find(
    (c) => c.id === (textId || e.target.dataset.id),
  );
  const value = textId ? e.target.value : parseTime(e.target.value);
  if (
    !item ||
    (!textId &&
      (!Number.isFinite(value) ||
        value < 0 ||
        value > duration() ||
        (field === "start" ? item.end - value : value - item.start) < 0.02))
  )
    return;
  const key = textId ? "text" : field;
  if (item[key] === value) return;
  if (!captionEdits.has(e.target)) {
    pushUndo();
    captionEdits.add(e.target);
  }
  item[key] = value;
  changed();
  renderTimeline();
  const seekButton = e.target
    .closest(".subtitle-row")
    ?.querySelector("[data-seek]");
  if (seekButton) seekButton.dataset.seek = item.start;
});
$("subtitles-list").addEventListener("change", (e) => {
  const field = e.target.dataset.subtitleField;
  if (!field) return;
  const item = project.subtitles.find((c) => c.id === e.target.dataset.id),
    value = parseTime(e.target.value);
  if (
    !Number.isFinite(value) ||
    value < 0 ||
    value > duration() ||
    (field === "start" ? item.end - value : value - item.start) < 0.02
  ) {
    toast("Use a time inside the video, with the end after the start.", true);
    e.target.value = time(item[field]);
  }
});
$("subtitles-list").addEventListener("click", (e) => {
  const button = e.target.closest("button");
  if (!button) return;
  if (button.dataset.seek) {
    seek(Number(button.dataset.seek));
    return;
  }
  if (button.dataset.removeSubtitle) {
    pushUndo();
    project.subtitles = project.subtitles.filter(
      (c) => c.id !== button.dataset.removeSubtitle,
    );
    changed();
    renderLists();
    renderTimeline();
  }
});

function applyClips(next) {
  project.cuts = cutsForClips(duration(), next, project.cuts, uid);
  project.split_points = next.slice(0, -1).map((c) => c.end);
}
function splitClip() {
  if (!project || busy() || conflicted) return;
  const all = clips(),
    t = Math.round(video.currentTime * project.media.fps) / project.media.fps;
  const index = all.findIndex((c) => t > c.start + 0.04 && t < c.end - 0.04);
  if (index < 0) return;
  pushUndo();
  project.split_points = [...new Set([...project.split_points, t])].sort(
    (a, b) => a - b,
  );
  selectedClip = index + 1;
  changed();
  renderTimeline();
}
function deleteClip() {
  const all = clips();
  if (selectedClip === null || !all[selectedClip] || busy() || conflicted)
    return;
  pushUndo();
  video.pause();
  const at = all[selectedClip].output;
  applyClips(all.filter((_, i) => i !== selectedClip));
  selectedClip = null;
  changed();
  renderTimeline();
  seek(sourceAt(clips(), Math.min(at, editDuration())));
}
$("split-button").onclick = splitClip;
$("delete-clip-button").onclick = deleteSelection;
$("restore-video").onclick = () => {
  if (busy() || conflicted) return;
  pushUndo();
  project.cuts = [];
  project.split_points = [];
  selectedClip = null;
  changed();
  renderTimeline();
  seek(0);
};
function timelineTime(e) {
  const rect = $("timeline").getBoundingClientRect();
  return Math.max(
    0,
    Math.min(
      editDuration(),
      ((e.clientX - rect.left) / rect.width) * duration(),
    ),
  );
}
$("timeline-grid").addEventListener("pointerdown", (e) => {
  if (!project || !e.target.closest(".timeline-lane")) return;
  if (
    e.target.closest(
      "[data-track-overlay],[data-track-effect],[data-track-music],[data-cue]",
    )
  )
    return;
  if ($("export-dialog").open) $("export-dialog").close();
  const handle = e.target.closest("[data-trim]"),
    item = e.target.closest("[data-clip],[data-select-clip]");
  if (handle && !busy() && !conflicted) {
    e.preventDefault();
    video.pause();
    selectedClip = Number(handle.closest("[data-clip]").dataset.clip);
    lastTrimTarget = {
      index: selectedClip,
      edge: handle.dataset.trim,
      at: performance.now(),
    };
    dragging = {
      type: "trim",
      edge: handle.dataset.trim,
      index: selectedClip,
      initial: clips(),
      x: e.clientX,
      scale: duration() / $("timeline").getBoundingClientRect().width,
      changed: false,
    };
    document.body.classList.add("dragging");
    $("timeline-grid").setPointerCapture(e.pointerId);
  } else {
    lastTrimTarget = null;
    selectedLayer = { kind: "video" };
    selectedSubtitle = null;
    selectedClip = item
      ? Number(item.dataset.selectClip ?? item.dataset.clip)
      : null;
    seek(sourceAt(clips(), timelineTime(e)));
    renderTimeline();
    canvas?.refresh();
  }
});
$("timeline-grid").addEventListener("pointermove", (e) => {
  if (dragging?.type !== "trim") return;
  const delta =
    Math.round((e.clientX - dragging.x) * dragging.scale * project.media.fps) /
    project.media.fps;
  const next = trimClip(
    dragging.initial,
    dragging.index,
    dragging.edge,
    delta,
    duration(),
  );
  const a = next[dragging.index],
    b = dragging.initial[dragging.index];
  if (
    !dragging.changed &&
    Math.abs(a[dragging.edge] - b[dragging.edge]) < 0.001
  )
    return;
  if (!dragging.changed) {
    pushUndo();
    dragging.changed = true;
  }
  applyClips(next);
  renderTimeline();
  updateSummary();
  seek(dragging.edge === "start" ? a.start : Math.max(a.start, a.end - 0.04));
});
function finishTrim() {
  if (!dragging) return;
  const edited = dragging.changed;
  dragging = null;
  document.body.classList.remove("dragging");
  if (edited) {
    changed();
    renderTimeline();
  }
}
for (const event of ["pointerup", "pointercancel", "lostpointercapture"])
  $("timeline-grid").addEventListener(event, finishTrim);
$("timeline-grid").addEventListener("dblclick", (e) => {
  const handle = e.target.closest("[data-trim]");
  if (!handle && e.target !== $("timeline-grid")) return;
  const target = handle
    ? {
        index: Number(handle.closest("[data-clip]").dataset.clip),
        edge: handle.dataset.trim,
        at: performance.now(),
      }
    : lastTrimTarget;
  if (!target || performance.now() - target.at > 500 || busy() || conflicted)
    return;
  e.preventDefault();
  pushUndo();
  applyClips(
    trimClip(
      clips(),
      target.index,
      target.edge,
      target.edge === "start" ? -duration() : duration(),
      duration(),
    ),
  );
  selectedClip = target.index;
  lastTrimTarget = null;
  changed();
  renderTimeline();
});
$("timeline-grid").addEventListener("keydown", (e) => {
  const handle = e.target.closest("[data-trim]");
  if (
    handle &&
    ["ArrowLeft", "ArrowRight"].includes(e.key) &&
    !busy() &&
    !conflicted
  ) {
    e.preventDefault();
    pushUndo();
    const index = Number(handle.closest("[data-clip]").dataset.clip),
      edge = handle.dataset.trim;
    applyClips(
      trimClip(
        clips(),
        index,
        edge,
        (e.key === "ArrowLeft" ? -1 : 1) *
          (e.shiftKey ? 1 : 1 / project.media.fps),
        duration(),
      ),
    );
    selectedClip = index;
    changed();
    renderTimeline();
    document
      .querySelector(`[data-clip="${index}"] [data-trim="${edge}"]`)
      ?.focus();
  }
  const item = e.target.closest("[data-select-clip]");
  if (item && (e.key === "Enter" || e.key === " ")) {
    e.preventDefault();
    selectedClip = Number(item.dataset.selectClip);
    selectedLayer = { kind: "video" };
    selectedSubtitle = null;
    seek(clips()[selectedClip].start);
    renderTimeline();
    canvas?.refresh();
  }
});
$("subtitle-track").onclick = (e) => {
  const cue = e.target.closest("[data-cue]");
  if (!cue) return;
  selectLayer({ kind: "caption", id: cue.dataset.cue }, { seekTo: true });
  document
    .querySelector(`[data-subtitle="${cue.dataset.cue}"]`)
    ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
};
$("timeline-grid").addEventListener("click", (e) => {
  const item = e.target.closest(
    "[data-track-overlay],[data-track-effect],[data-track-music]",
  );
  if (!item) return;
  if (tab) setTab("visuals");
  if (item.dataset.trackMusic) {
    document.querySelector(".music-tools").open = true;
    $("music-asset").focus();
    return;
  }
  const key = item.dataset.trackOverlay ? "overlays" : "punches",
    id = item.dataset.trackOverlay || item.dataset.trackEffect;
  const part = project[key].find((o) => o.id === id);
  selectLayer(
    { kind: key === "overlays" ? "overlay" : "effect", id },
    { seekTo: true },
  );
  const selector =
    key === "overlays" ? `[data-overlay="${id}"]` : `[data-punch="${id}"]`;
  document
    .querySelector(selector)
    ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  document
    .querySelectorAll(".overlay-card.selected,.punch-card.selected")
    .forEach((e) => e.classList.remove("selected"));
  document.querySelector(selector)?.classList.add("selected");
});
$("timeline-zoom").oninput = (e) => {
  $("timeline-grid").style.width = `${Number(e.target.value) * 100}%`;
  renderTimeline();
  const scroll = $("timeline-scroll");
  scroll.scrollLeft = Math.max(
    0,
    96 +
      (outputTime(video.currentTime) / (duration() || 1)) *
        $("timeline").clientWidth -
      scroll.clientWidth / 2,
  );
};
new ResizeObserver(() => {
  if (project) renderTimeline();
}).observe($("timeline-scroll"));

function undoEdit() {
  if (!undo.length || !project) return;
  redo.push(editable());
  Object.assign(project, undo.pop());
  changed();
  renderProject();
}
function redoEdit() {
  if (!redo.length || !project) return;
  undo.push(editable());
  Object.assign(project, redo.pop());
  changed();
  renderProject();
}
$("undo-button").onclick = undoEdit;
$("redo-button").onclick = redoEdit;
document.addEventListener("keydown", (e) => {
  if (
    e.target.closest("input,textarea,select,[contenteditable=true]") ||
    $("help-dialog").open ||
    $("export-dialog").open
  )
    return;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
    e.preventDefault();
    e.shiftKey ? redoEdit() : undoEdit();
    return;
  }
  if (e.key === "Escape") {
    selectedClip = null;
    selectLayer(null);
    renderTimeline();
  }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
    e.preventDefault();
    splitClip();
    return;
  }
  if (e.key === "Backspace" || e.key === "Delete") {
    e.preventDefault();
    deleteSelection();
    return;
  }
  if (
    selectedLayer &&
    ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)
  ) {
    const step = e.shiftKey ? 10 : 1;
    if (
      canvas.moveBy(
        e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0,
        e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0,
      )
    ) {
      e.preventDefault();
      return;
    }
  }
  if (
    e.code === "Space" &&
    !e.target.closest("button,a,summary,video[controls]")
  ) {
    e.preventDefault();
    togglePlay();
  }
});
$("import-srt-button").onclick = () => $("srt-input").click();
$("srt-input").onchange = act(async (e) => {
  const file = e.target.files[0];
  if (!file || !project) return;
  await saveNow();
  pushUndo();
  const data = new FormData();
  data.append("file", file);
  project = await api(`/api/projects/${project.id}/subtitles/import`, {
    method: "POST",
    body: data,
  });
  savedEditable = editable();
  renderProject();
  e.target.value = "";
  toast("Subtitles imported.");
});
$("download-srt").onclick = act(async (e) => {
  if (dirty || savePromise) {
    e.preventDefault();
    await saveNow();
    if (!conflicted) window.location.assign(e.target.href);
  }
});
$("reload-button").onclick = act(() => openProject(project.id, true));
$("help-button").onclick = () => $("help-dialog").showModal();
$("close-help").onclick = () => $("help-dialog").close();
window.addEventListener("beforeunload", (e) => {
  if (dirty || savePromise || canvas?.dragging) {
    e.preventDefault();
    e.returnValue = "";
  }
});

function renderReview() {
  const versions = project.exports;
  if (!versions.some((e) => e.file === reviewFile))
    reviewFile = versions.at(-1)?.file || null;
  const exported = versions.find((e) => e.file === reviewFile);
  const options = versions
    .slice()
    .reverse()
    .map(
      (e) =>
        `<option value="${e.file}">v${String(e.version).padStart(3, "0")} · ${esc(e.label)}</option>`,
    )
    .join("");
  if ($("review-version").innerHTML !== options)
    $("review-version").innerHTML = options;
  $("review-version").value = reviewFile || "";
  $("review-version").hidden = !exported;
  $("no-exports").hidden = !!exported;
  $("review-form").hidden = !exported;
  $("review-stage").hidden = !exported;
  if (!exported) {
    $("review-notes").innerHTML = "";
    return;
  }
  const route = `/api/projects/${project.id}/exports/`;
  const player = $("review-video"),
    key = `${project.id}/${reviewFile}`;
  if (player.dataset.version !== key) {
    player.pause();
    player.src = route + reviewFile;
    player.dataset.version = key;
    player.load();
    $("review-time").value = "00:00.00";
  }
  $("review-version-label").textContent =
    `v${String(exported.version).padStart(3, "0")} · ${exported.label}`;
  $("review-downloads").innerHTML =
    `<a download href="${route + exported.file}">MP4 ↗</a><a download href="${route + exported.captions_file}">Captions ↗</a><a download href="${route + exported.manifest_file}">Edit details ↗</a>`;
  const notes = project.reviews.filter((n) => n.export_file === reviewFile);
  $("review-notes").hidden = !notes.length;
  $("review-notes").innerHTML =
    notes
      .map((n) => {
        const fixed = versions.find((e) => e.file === n.resolved_in);
        const later = versions.filter((e) => e.version > exported.version);
        return `<article class="review-note"><div class="note-meta"><button class="text-button" data-note-seek="${n.time}">${time(n.time)}</button><span>${n.scope === "reusable" ? "Reusable preference" : "This edit"}</span></div><p>${esc(n.change)}</p><small>${esc(n.reason)}</small>${fixed ? `<div class="note-resolution">Correction linked to v${String(fixed.version).padStart(3, "0")} <button class="text-button" data-reopen="${n.id}">Reopen</button></div>` : later.length ? `<label class="resolution-label">Link a corrected version<select data-resolution="${n.id}" aria-label="Corrected version for note"><option value="">Choose a later export…</option>${later.map((e) => `<option value="${e.file}">v${String(e.version).padStart(3, "0")} · ${esc(e.label)}</option>`).join("")}</select></label>` : '<div class="note-resolution">Open · render a later version to link the correction</div>'}</article>`;
      })
      .join("") || '<p class="panel-hint">No feedback yet.</p>';
}
for (const event of ["timeupdate", "seeked", "loadedmetadata"])
  $("review-video").addEventListener(event, updateTime);
$("review-version").onchange = (e) => {
  reviewFile = e.target.value;
  renderReview();
};
$("capture-review-time").onclick = () => {
  $("review-time").value = time($("review-video").currentTime);
};
$("review-form").onsubmit = act(async (e) => {
  e.preventDefault();
  await saveNow();
  if (conflicted) return;
  const at = parseTime($("review-time").value),
    candidate = project.exports.find((e) => e.file === reviewFile);
  if (!candidate || !Number.isFinite(at) || at > candidate.duration)
    throw new Error("Use a time inside the selected export.");
  project = await api(`/api/projects/${project.id}/reviews`, {
    method: "POST",
    body: {
      export_file: reviewFile,
      time: at,
      change: $("review-change").value,
      reason: $("review-reason").value,
      scope: $("review-scope").value,
    },
  });
  savedEditable = editable();
  $("review-change").value = "";
  $("review-reason").value = "";
  renderReview();
  toast("Note saved with this exact version.");
});
$("review-notes").onclick = act(async (e) => {
  const seekButton = e.target.closest("[data-note-seek]");
  if (seekButton) {
    $("review-video").currentTime = Number(seekButton.dataset.noteSeek);
    return;
  }
  const reopen = e.target.closest("[data-reopen]");
  if (reopen) {
    await saveNow();
    if (conflicted) return;
    project = await api(
      `/api/projects/${project.id}/reviews/${reopen.dataset.reopen}`,
      { method: "PATCH", body: { resolved_in: null } },
    );
    savedEditable = editable();
    renderReview();
  }
});
$("review-notes").onchange = act(async (e) => {
  if (!e.target.dataset.resolution || !e.target.value) return;
  await saveNow();
  if (conflicted) return;
  project = await api(
    `/api/projects/${project.id}/reviews/${e.target.dataset.resolution}`,
    { method: "PATCH", body: { resolved_in: e.target.value } },
  );
  savedEditable = editable();
  renderReview();
  toast("Correction linked to the selected export.");
});
$("history-form").onsubmit = act(async (e) => {
  e.preventDefault();
  const params = new URLSearchParams({
    q: $("history-query").value,
    reusable: $("history-reusable").checked,
  });
  const notes = await api(`/api/history?${params}`);
  $("history-results").innerHTML =
    notes
      .map(
        (n) =>
          `<article class="review-note"><a href="/?project=${n.project_id}">${esc(n.project_name)} ↗</a><div class="note-meta">${time(n.time)} · ${n.scope === "reusable" ? "Reusable preference" : "This edit"}</div><p>${esc(n.change)}</p><small>${esc(n.reason)}</small></article>`,
      )
      .join("") || '<p class="panel-hint">No matching feedback.</p>';
});

async function poll() {
  if (
    pollRunning ||
    !project ||
    dirty ||
    savePromise ||
    dragging ||
    canvas?.dragging ||
    conflicted
  )
    return;
  pollRunning = true;
  try {
    const id = project.id,
      p = await api(`/api/projects/${project.id}`);
    if (project?.id !== id || dirty || savePromise) return;
    if (p.revision <= project.revision) {
      setSaveStatus("All changes saved");
      return;
    }
    const was = project.jobs;
    const changedEdit =
      JSON.stringify(editable(p)) !== JSON.stringify(savedEditable);
    if (changedEdit && !ownJobs.size) {
      undo = [];
      redo = [];
      toast("Updated from chat.");
    }
    const finishedExport =
      ownJobs.has("export") &&
      was.export?.status === "running" &&
      p.jobs.export?.status === "done";
    if (finishedExport) reviewFile = p.exports.at(-1)?.file;
    project = p;
    savedEditable = editable(p);
    renderProject();
    if (finishedExport) openExport();
    for (const [kind, job] of Object.entries(p.jobs)) {
      if (was[kind]?.status === "running" && job.status === "done") {
        ownJobs.delete(kind);
        if (kind === "silence")
          toast("Pauses removed. Drag clip edges to adjust.");
        if (kind === "transcribe")
          toast(`${p.subtitles.length} subtitles ready to review.`);
        if (kind === "export") toast("Your export is ready to download.");
      }
      if (job.status === "error") ownJobs.delete(kind);
    }
    setSaveStatus("All changes saved");
  } catch (e) {
    setSaveStatus("Reconnecting…");
  } finally {
    pollRunning = false;
  }
}

await act(async () => {
  health = await api("/api/health");
  await loadProjects();
  const id = new URLSearchParams(location.search).get("project");
  if (id) await openProject(id);
  else {
    const active = localStorage.getItem("aiedit-active-project");
    const current =
      projects.find((p) => p.id === active) ||
      projects.find((p) => p.media.height >= p.media.width) ||
      projects[0];
    if (current) await openProject(current.id);
    else $("import-button").textContent = "Import video";
  }
})();
setInterval(poll, 1300);
