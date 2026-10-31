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
  tab = "cuts",
  mode = "edited";
let selectedCut = null,
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
const ownJobs = new Set();

function time(value, precise = true) {
  const n = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(n / 60),
    seconds = Math.floor(n % 60),
    centiseconds = Math.floor((n % 1) * 100 + 0.001);
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
    cuts: clone(p.cuts),
    subtitles: clone(p.subtitles),
    subtitle_style: clone(p.subtitle_style),
    brief: clone(p.brief),
    references: clone(p.references),
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
}
function setSaveStatus(text) {
  $("save-status").innerHTML = '<span class="status-dot"></span>' + esc(text);
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
  $("project-count").textContent = projects.length;
  $("project-list").innerHTML = projects
    .map(
      (p) =>
        `<button class="project-item ${project?.id === p.id ? "active" : ""}" data-project="${p.id}" title="${esc(p.name)}"><span class="project-item-icon">▻</span><div><strong>${esc(p.name)}</strong><small>${time(p.media.duration, false)} · ${p.media.height}p</small></div></button>`,
    )
    .join("");
}
async function openProject(id, discard = false) {
  if (project && !discard) await saveNow();
  video.pause();
  const p = await api(`/api/projects/${id}`);
  project = p;
  reviewFile = p.exports.at(-1)?.file || null;
  $("history-results").innerHTML = "";
  dirty = false;
  conflicted = false;
  editSequence = 0;
  undo = [];
  redo = [];
  selectedCut = selectedSubtitle = null;
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
  $("project-name").value = project.name;
  $("project-details").innerHTML =
    `${project.media.width} × ${project.media.height} <span class="muted">/</span> ${Math.round(project.media.fps * 100) / 100} fps<br>${esc(project.filename)}`;
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
  $("waveform").hidden = !project.waveform_ready;
  if (project.waveform_ready)
    $("waveform").src = `/api/projects/${project.id}/waveform`;
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
  for (const key of ["goal", "target", "rights"])
    $(`brief-${key}`).value = project.brief[key];
  renderReferences();
  $("timeline-ruler").innerHTML = Array.from(
    { length: 7 },
    (_, i) =>
      `<span style="left:${(i / 6) * 100}%">${time((duration() * i) / 6, false)}</span>`,
  ).join("");
  renderLists();
  renderTimeline();
  renderJobs();
  updateSummary();
  updateUndo();
  updateCaption();
  updateTime();
  renderExport();
  renderReview();
}
function renderExport() {
  const exported = project.exports.at(-1);
  $("export-result").hidden = !exported;
  if (!exported) return;
  const current = {
    cuts: project.cuts,
    subtitles: project.subtitles,
    subtitle_style: project.subtitle_style,
  };
  const matches =
    exported.edit_state &&
    JSON.stringify(exported.edit_state) === JSON.stringify(current) &&
    JSON.stringify(exported.brief) === JSON.stringify(project.brief) &&
    JSON.stringify(exported.references) === JSON.stringify(project.references);
  $("export-result").innerHTML =
    `<span>${matches ? "✓ Export ready" : "Previous export"} <span class="muted">· ${time(exported.duration, false)}</span></span><a download href="/api/projects/${project.id}/exports/${exported.file}">Download video ↗</a>`;
}
function renderLists() {
  $("cut-count").textContent = project.cuts.filter((c) => c.enabled).length;
  $("subtitle-count").textContent = project.subtitles.length;
  $("cuts-list").innerHTML =
    [...project.cuts]
      .sort((a, b) => a.start - b.start)
      .map(
        (c, i) =>
          `<div class="cut-row ${c.enabled ? "" : "disabled"} ${selectedCut === c.id ? "selected" : ""}" data-cut="${c.id}"><div class="cut-row-top"><input type="checkbox" aria-label="Enable cut ${i + 1}" data-cut-toggle="${c.id}" ${c.enabled ? "checked" : ""}><strong>${c.kind === "silence" ? "Quiet section" : "Manual cut"} ${i + 1}</strong><small>${(c.end - c.start).toFixed(2)}s</small><button class="remove-item" data-remove-cut="${c.id}" aria-label="Remove cut ${i + 1}">×</button></div><div class="times"><label>IN</label><input class="time-input" aria-label="Cut ${i + 1} start" value="${time(c.start)}" data-cut-field="start" data-id="${c.id}"><label>OUT</label><input class="time-input" aria-label="Cut ${i + 1} end" value="${time(c.end)}" data-cut-field="end" data-id="${c.id}"><button class="seek-item" data-seek="${c.start}" aria-label="Preview cut ${i + 1}">▷</button></div></div>`,
      )
      .join("") ||
    '<div class="empty-list"><span>◌</span>A little space is good.<br>Find pauses, then decide what stays.</div>';
  $("subtitles-list").innerHTML =
    [...project.subtitles]
      .sort((a, b) => a.start - b.start)
      .map(
        (c, i) =>
          `<div class="subtitle-row" data-subtitle="${c.id}"><div class="times"><button class="seek-item" data-seek="${c.start}" aria-label="Preview subtitle ${i + 1}">▷</button><input class="time-input" aria-label="Subtitle ${i + 1} start" data-subtitle-field="start" data-id="${c.id}" value="${time(c.start)}"><span class="muted">→</span><input class="time-input" aria-label="Subtitle ${i + 1} end" data-subtitle-field="end" data-id="${c.id}" value="${time(c.end)}"><button class="remove-item" data-remove-subtitle="${c.id}" aria-label="Remove subtitle ${i + 1}">×</button></div><textarea dir="auto" aria-label="Subtitle ${i + 1} text" placeholder="Type a subtitle…" maxlength="5000" data-caption-text="${c.id}">${esc(c.text)}</textarea><button class="text-button cut-speech" data-cut-speech="${c.id}" aria-label="Cut speech ${i + 1}">✂ Cut speech</button></div>`,
      )
      .join("") ||
    '<div class="empty-list"><span>▤</span>No subtitles yet.<br>Generate them, import an SRT, or add your own.</div>';
}
function renderTimeline() {
  const d = duration();
  $("cut-regions").innerHTML = project.cuts
    .map(
      (c) =>
        `<div class="cut-region ${c.enabled ? "" : "disabled"} ${c.id === selectedCut ? "selected" : ""}" data-region="${c.id}" style="left:${(c.start / d) * 100}%;width:${((c.end - c.start) / d) * 100}%" title="${time(c.start)} – ${time(c.end)}"><div class="edge start" data-edge="start" data-id="${c.id}"></div><div class="edge end" data-edge="end" data-id="${c.id}"></div></div>`,
    )
    .join("");
  $("subtitle-track").innerHTML = project.subtitles
    .map(
      (c) =>
        `<div class="subtitle-segment" data-cue="${c.id}" style="left:${(c.start / d) * 100}%;width:${((c.end - c.start) / d) * 100}%" title="${esc(c.text)}">${esc(c.text)}</div>`,
    )
    .join("");
}
function renderJobs() {
  const running = Object.entries(project.jobs).find(
    ([, j]) => j.status === "running",
  );
  const error = Object.entries(project.jobs)
    .reverse()
    .find(([, j]) => j.status === "error");
  const names = {
    preview: "Preparing video & waveform…",
    silence: "Finding the quiet sections…",
    transcribe: "Transcribing on your Mac…",
    export: "Rendering your video…",
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
}
function updateSummary() {
  if (!project) return;
  const saved = mergedCuts().reduce((sum, c) => sum + c.end - c.start, 0);
  const count = project.cuts.filter((c) => c.enabled).length;
  $("removed-duration").textContent = `${saved.toFixed(1)}s`;
  $("cut-summary").textContent = count
    ? `${count} section${count === 1 ? "" : "s"} cut · ${saved.toFixed(1)}s removed`
    : "Your full recording, untouched";
  $("edited-summary").textContent =
    `${time(duration() - saved, false)} edited · ${time(duration(), false)} original`;
  $("total-time").textContent = time(
    mode === "edited" ? duration() - saved : duration(),
  );
  $("export-button").disabled = busy() || conflicted || dirty;
  $("plain-export-button").disabled = busy() || conflicted || dirty;
  const libraryItem = document.querySelector(`[data-project="${project.id}"]`);
  if (libraryItem) {
    libraryItem.title = project.name;
    libraryItem.querySelector("strong").textContent = project.name;
  }
  renderExport();
}
function updateCaption() {
  if (!project) return;
  const t = video.currentTime || 0;
  const cues = project.subtitles.filter(
    (c) => c.start <= t && t < c.end && c.text.trim(),
  );
  $("caption-overlay").textContent = project.subtitle_style.enabled
    ? cues.map((c) => c.text).join("\n")
    : "";
  const stage = $("video-stage");
  const ratio = project.media.width / project.media.height;
  const actualHeight = Math.min(stage.clientHeight, stage.clientWidth / ratio);
  const actualWidth = Math.min(stage.clientWidth, stage.clientHeight * ratio);
  const inset = (stage.clientHeight - actualHeight) / 2 + actualHeight * 0.065;
  $("caption-overlay").style.fontSize =
    `${(project.subtitle_style.font_size * actualHeight) / 1080}px`;
  $("caption-overlay").style.maxWidth = `${actualWidth * 0.88}px`;
  $("caption-overlay").style.top =
    project.subtitle_style.position === "top" ? `${inset}px` : "auto";
  $("caption-overlay").style.bottom =
    project.subtitle_style.position === "bottom" ? `${inset}px` : "auto";
  document.querySelectorAll(".subtitle-row").forEach((row) =>
    row.classList.toggle(
      "active",
      cues.some((c) => c.id === row.dataset.subtitle),
    ),
  );
}
function updateTime() {
  if (!project) return;
  const t = video.currentTime || 0;
  $("current-time").textContent = time(mode === "edited" ? outputTime(t) : t);
  $("playhead").style.left = `${Math.min(100, (t / duration()) * 100)}%`;
  $("cut-badge").hidden = !project.cuts.some(
    (c) => c.enabled && t >= c.start && t < c.end,
  );
  updateCaption();
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
  if (!project?.media_ready) return;
  if (video.paused) video.play().catch((e) => toast(e.message, true));
  else video.pause();
}
function setTab(value) {
  tab = value;
  document
    .querySelector(".preview-column")
    .classList.toggle("reviewing", value === "review");
  for (const name of ["cuts", "subtitles", "review"]) {
    $(`${name}-tab`).classList.toggle("active", value === name);
    $(`${name}-tab`).setAttribute("aria-selected", value === name);
    $(`${name}-panel`).hidden = value !== name;
  }
  $("review-stage").hidden = value !== "review" || !project?.exports.length;
  if (value === "review") {
    video.pause();
    renderReview();
  } else $("review-video").pause();
}
function setMode(value) {
  mode = value;
  $("edited-mode").classList.toggle("active", value === "edited");
  $("original-mode").classList.toggle("active", value === "original");
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
  if (kind === "export")
    body = {
      burn_subtitles: !plain && project.subtitle_style.enabled,
      label: $("export-label").value,
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

$("project-list").addEventListener(
  "click",
  act(async (e) => {
    const button = e.target.closest("[data-project]");
    if (button) await openProject(button.dataset.project);
  }),
);
for (const id of ["import-button", "sidebar-import"])
  $(id).onclick = () => $("video-input").click();
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
$("cuts-tab").onclick = () => setTab("cuts");
$("subtitles-tab").onclick = () => setTab("subtitles");
$("review-tab").onclick = () => setTab("review");
$("edited-mode").onclick = () => setMode("edited");
$("original-mode").onclick = () => setMode("original");
$("play-button").onclick = togglePlay;
$("video-stage").onclick = togglePlay;
$("back-button").onclick = () => seek(video.currentTime - 2);
$("forward-button").onclick = () => seek(video.currentTime + 2);
$("mute-button").onclick = () => {
  video.muted = !video.muted;
  $("mute-button").textContent = video.muted ? "Sound off" : "Sound on";
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
video.addEventListener("loadedmetadata", updateTime);
new ResizeObserver(updateCaption).observe($("video-stage"));
$("threshold").oninput = () =>
  ($("threshold-value").textContent = `${$("threshold").value} dB`);
$("analyze-button").onclick = act(() => task("silence"));
$("transcribe-button").onclick = act(() => task("transcribe"));
$("export-button").onclick = act(() => task("export"));
$("plain-export-button").onclick = act(() => task("export", true));
$("project-name").onfocus = () => {
  if (project) pushUndo();
};
$("project-name").oninput = (e) => {
  if (project && e.target.value.trim()) {
    project.name = e.target.value;
    changed();
  }
};
$("add-cut-button").onclick = () => {
  if (!project || duration() < 0.04) return;
  pushUndo();
  const start = Math.min(video.currentTime || 0, duration() - 0.04),
    end = Math.min(duration(), start + 1);
  const cut = { id: uid(), start, end, enabled: true, kind: "manual" };
  project.cuts.push(cut);
  selectedCut = cut.id;
  setTab("cuts");
  changed();
  renderLists();
  renderTimeline();
};
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
  changed();
};
$("captions-enabled").onchange = () => {
  pushUndo();
  project.subtitle_style.enabled = $("captions-enabled").checked;
  changed();
};
for (const name of ["cuts-list", "subtitles-list"]) {
  $(name).addEventListener("focusin", (e) => {
    if (e.target.matches("input.time-input,textarea")) pushUndo();
  });
  $(name).addEventListener("input", (e) => {
    const id = e.target.dataset.captionText;
    if (id) {
      const cue = project.subtitles.find((c) => c.id === id);
      if (cue) {
        cue.text = e.target.value;
        changed();
        renderTimeline();
      }
    }
    const cutField = e.target.dataset.cutField,
      subtitleField = e.target.dataset.subtitleField;
    if (cutField || subtitleField) {
      const field = cutField || subtitleField,
        items = cutField ? project.cuts : project.subtitles;
      const item = items.find((c) => c.id === e.target.dataset.id),
        value = parseTime(e.target.value);
      if (
        item &&
        Number.isFinite(value) &&
        value >= 0 &&
        value <= duration() &&
        (field === "start" ? item.end - value : value - item.start) >= 0.02 &&
        value !== item[field]
      ) {
        item[field] = value;
        if (cutField) item.kind = "manual";
        changed();
        renderTimeline();
        const row = e.target.closest(".cut-row,.subtitle-row");
        const seekButton = row?.querySelector("[data-seek]");
        if (seekButton) seekButton.dataset.seek = item.start;
        if (cutField) {
          row.querySelector("strong").textContent = "Manual cut";
          row.querySelector("small").textContent =
            `${(item.end - item.start).toFixed(2)}s`;
        }
      }
    }
  });
  $(name).addEventListener("change", (e) => {
    if (e.target.dataset.cutToggle) {
      pushUndo();
      const c = project.cuts.find((c) => c.id === e.target.dataset.cutToggle);
      c.enabled = e.target.checked;
      c.kind = "manual";
      changed();
      renderLists();
      renderTimeline();
      return;
    }
    const cutField = e.target.dataset.cutField,
      subtitleField = e.target.dataset.subtitleField;
    if (!cutField && !subtitleField) return;
    const field = cutField || subtitleField,
      items = cutField ? project.cuts : project.subtitles,
      item = items.find((c) => c.id === e.target.dataset.id);
    const value = parseTime(e.target.value);
    if (
      !Number.isFinite(value) ||
      value < 0 ||
      value > duration() ||
      (field === "start" ? item.end - value : value - item.start) < 0.02
    ) {
      toast(
        "Use a time inside the video, with the out point after the in point.",
        true,
      );
      e.target.value = time(item[field]);
      return;
    }
    item[field] = value;
    if (cutField) item.kind = "manual";
    changed();
    renderLists();
    renderTimeline();
  });
  $(name).addEventListener("click", (e) => {
    const target = e.target.closest("button");
    if (!target) return;
    if (target.dataset.seek) {
      seek(Number(target.dataset.seek));
      return;
    }
    if (target.dataset.removeCut) {
      pushUndo();
      project.cuts = project.cuts.filter(
        (c) => c.id !== target.dataset.removeCut,
      );
      changed();
      renderLists();
      renderTimeline();
    }
    if (target.dataset.removeSubtitle) {
      pushUndo();
      project.subtitles = project.subtitles.filter(
        (c) => c.id !== target.dataset.removeSubtitle,
      );
      changed();
      renderLists();
      renderTimeline();
    }
    if (target.dataset.cutSpeech) {
      const cue = project.subtitles.find(
        (c) => c.id === target.dataset.cutSpeech,
      );
      if (!cue) return;
      pushUndo();
      project.cuts.push({
        id: uid(),
        start: cue.start,
        end: cue.end,
        enabled: true,
        kind: "manual",
      });
      changed();
      renderLists();
      renderTimeline();
      toast("Speech range cut. Review both joins in the preview.");
    }
  });
}
$("timeline").addEventListener("pointerdown", (e) => {
  if (!project) return;
  const edge = e.target.closest("[data-edge]");
  if (edge) {
    e.preventDefault();
    pushUndo();
    selectedCut = edge.dataset.id;
    dragging = { id: edge.dataset.id, edge: edge.dataset.edge };
    $("timeline").setPointerCapture(e.pointerId);
    document.body.classList.add("dragging");
    return;
  }
  const region = e.target.closest("[data-region]");
  if (region) {
    selectedCut = region.dataset.region;
    setTab("cuts");
    renderLists();
    renderTimeline();
  }
  const rect = $("timeline").getBoundingClientRect();
  seek(((e.clientX - rect.left) / rect.width) * duration());
});
$("timeline").addEventListener("pointermove", (e) => {
  if (!dragging) return;
  const c = project.cuts.find((c) => c.id === dragging.id),
    rect = $("timeline").getBoundingClientRect();
  c.kind = "manual";
  let t =
    Math.round(
      Math.max(
        0,
        Math.min(
          duration(),
          ((e.clientX - rect.left) / rect.width) * duration(),
        ),
      ) * 1000,
    ) / 1000;
  if (dragging.edge === "start")
    c.start = Math.max(0, Math.min(c.end - 0.03, t));
  else c.end = Math.min(duration(), Math.max(c.start + 0.03, t));
  const region = document.querySelector(`[data-region="${c.id}"]`);
  region.style.left = `${(c.start / duration()) * 100}%`;
  region.style.width = `${((c.end - c.start) / duration()) * 100}%`;
  updateSummary();
});
$("timeline").addEventListener("pointerup", () => {
  if (dragging) {
    dragging = null;
    document.body.classList.remove("dragging");
    changed();
    renderLists();
    renderTimeline();
  }
});
$("timeline").addEventListener("pointercancel", () => {
  if (dragging) {
    dragging = null;
    document.body.classList.remove("dragging");
    changed();
    renderLists();
    renderTimeline();
  }
});
$("subtitle-track").onclick = (e) => {
  if (!project) return;
  const cue = e.target.closest("[data-cue]");
  if (cue) {
    const c = project.subtitles.find((c) => c.id === cue.dataset.cue);
    seek(c.start);
    setTab("subtitles");
    document
      .querySelector(`[data-subtitle="${c.id}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
};
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
  if (e.target.matches("input,textarea,select") || $("help-dialog").open)
    return;
  if (e.code === "Space") {
    e.preventDefault();
    togglePlay();
  }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
    e.preventDefault();
    e.shiftKey ? redoEdit() : undoEdit();
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
  if (dirty || savePromise) {
    e.preventDefault();
    e.returnValue = "";
  }
});

function renderReferences() {
  $("reference-list").innerHTML = project.references
    .map(
      (r, i) =>
        `<div class="reference-row" data-reference="${i}"><input data-reference-field="title" value="${esc(r.title)}" maxlength="200" aria-label="Source ${i + 1} title" placeholder="Source title"><input data-reference-field="url" value="${esc(r.url)}" maxlength="2000" aria-label="Source ${i + 1} URL" placeholder="https://…"><textarea data-reference-field="purpose" maxlength="2000" aria-label="Source ${i + 1} purpose" placeholder="What this source contributes">${esc(r.purpose)}</textarea><button data-remove-reference="${i}" class="text-button">Remove source</button></div>`,
    )
    .join("");
}
for (const key of ["goal", "target", "rights"]) {
  $(`brief-${key}`).onfocus = pushUndo;
  $(`brief-${key}`).oninput = (e) => {
    project.brief[key] = e.target.value;
    changed();
  };
}
$("add-reference").onclick = () => {
  if (!project) return;
  pushUndo();
  project.references.push({ title: "Untitled source", url: "", purpose: "" });
  changed();
  renderReferences();
};
$("reference-list").onfocusin = (e) => {
  if (e.target.matches("input,textarea")) pushUndo();
};
$("reference-list").oninput = (e) => {
  const row = e.target.closest("[data-reference]"),
    field = e.target.dataset.referenceField;
  if (row && field) {
    project.references[Number(row.dataset.reference)][field] = e.target.value;
    changed();
  }
};
$("reference-list").onclick = (e) => {
  const button = e.target.closest("[data-remove-reference]");
  if (!button) return;
  pushUndo();
  project.references.splice(Number(button.dataset.removeReference), 1);
  changed();
  renderReferences();
};
function renderReview() {
  document
    .querySelector(".preview-column")
    .classList.toggle("reviewing", tab === "review");
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
  $("review-stage").hidden = tab !== "review" || !exported;
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
    `<a download href="${route + exported.file}">MP4 ↗</a><a download href="${route + exported.captions_file}">Version captions ↗</a><a download href="${route + exported.manifest_file}">Edit manifest ↗</a>`;
  const notes = project.reviews.filter((n) => n.export_file === reviewFile);
  $("review-notes").innerHTML =
    notes
      .map((n) => {
        const fixed = versions.find((e) => e.file === n.resolved_in);
        const later = versions.filter((e) => e.version > exported.version);
        return `<article class="review-note"><div class="note-meta"><button class="text-button" data-note-seek="${n.time}">${time(n.time)}</button><span>${n.scope === "reusable" ? "Reusable preference" : "This edit"}</span></div><p>${esc(n.change)}</p><small>${esc(n.reason)}</small>${fixed ? `<div class="note-resolution">Correction linked to v${String(fixed.version).padStart(3, "0")} <button class="text-button" data-reopen="${n.id}">Reopen</button></div>` : later.length ? `<label class="resolution-label">Link a corrected version<select data-resolution="${n.id}" aria-label="Corrected version for note"><option value="">Choose a later export…</option>${later.map((e) => `<option value="${e.file}">v${String(e.version).padStart(3, "0")} · ${esc(e.label)}</option>`).join("")}</select></label>` : '<div class="note-resolution">Open · render a later version to link the correction</div>'}</article>`;
      })
      .join("") || '<p class="panel-hint">No notes for this version yet.</p>';
}
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
      .join("") || '<p class="panel-hint">No matching feedback yet.</p>';
});

async function poll() {
  if (pollRunning || !project || dirty || savePromise || dragging || conflicted)
    return;
  pollRunning = true;
  try {
    const id = project.id,
      p = await api(`/api/projects/${project.id}`);
    if (
      project?.id !== id ||
      dirty ||
      savePromise ||
      p.revision <= project.revision
    )
      return;
    const was = project.jobs;
    const changedEdit =
      JSON.stringify(editable(p)) !== JSON.stringify(savedEditable);
    if (changedEdit && !ownJobs.size) {
      undo = [];
      redo = [];
      toast("Updated from chat.");
    }
    if (
      ownJobs.has("export") &&
      was.export?.status === "running" &&
      p.jobs.export?.status === "done"
    )
      reviewFile = p.exports.at(-1)?.file;
    project = p;
    savedEditable = editable(p);
    renderProject();
    for (const [kind, job] of Object.entries(p.jobs)) {
      if (was[kind]?.status === "running" && job.status === "done") {
        ownJobs.delete(kind);
        if (kind === "silence")
          toast(
            `Found ${p.cuts.filter((c) => c.kind === "silence").length} quiet sections. Review or adjust each cut.`,
          );
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
  else if (projects.length) await openProject(projects[0].id);
})();
setInterval(poll, 1300);
