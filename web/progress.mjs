const STEPS = [
  ["import", "Add video", []],
  ["preview", "Prepare preview", ["preview", "waveform"]],
  ["audio", "Prepare audio", ["audio", "signal"]],
  ["transcript", "Transcribe", ["transcription"]],
  ["pauses", "Remove pauses", ["silence", "speech"]],
  ["takes", "Compare takes", ["retakes"]],
  ["captions", "Create captions", ["apply"]],
  ["assistant", "AI edit", []],
  ["export", "Export", []],
];
const active = (job) => job && ["queued", "running"].includes(job.status);

function stageState(job, stages) {
  if (!job) return { state: "pending" };
  const records = new Map((job.stages || []).map((s) => [s.stage, s]));
  if (job.status === "error" && stages.includes(job.stage))
    return { state: "error", detail: job.message };
  if (job.status === "running" && stages.includes(job.stage) &&
      (job.stage_status === "running" || !records.has(job.stage)))
    return { state: "active" };
  const found = stages.map((s) => records.get(s));
  if (found.every(Boolean)) {
    const skipped = found.every((s) => s.status === "skipped");
    return {
      state: skipped ? "skipped" : "done",
      detail: found.map((s) => s.reason).filter(Boolean).join("; "),
    };
  }
  return { state: job.status === "queued" ? "queued" : "pending" };
}

/** Describe recorded work; never infer completion just from pipeline order. */
export function describeProgress(project, { upload = null, exportReady = false } = {}) {
  const rows = STEPS.map(([key, label]) => ({ key, label, state: "pending", detail: "" }));
  const row = (key) => rows.find((r) => r.key === key);
  if (upload) {
    row("import").state = "active";
    const message = upload.phase === "copying"
      ? `Copying video${upload.percent == null ? "" : ` · ${upload.percent}%`}`
      : upload.phase === "opening" ? "Opening video" : "Importing video";
    return { rows, message, loading: message, error: false, visible: true };
  }
  if (!project) return { rows, message: "", loading: "", error: false, visible: false };
  row("import").state = "done";
  const jobs = project.jobs || {}, prepare = jobs.prepare;
  const assistant = project.preparation_key &&
    jobs.assistant?.preparation_key === project.preparation_key ? jobs.assistant : null;
  const preparing = active(prepare);
  const preview = jobs.preview;
  if (preview) Object.assign(row("preview"), {
    state: preview.status === "done" ? "done" : preview.status === "error" ? "error" :
      preview.status === "queued" ? "queued" : "active",
    detail: preview.status === "error" ? preview.message : "",
  });
  else if (project.media_ready) row("preview").state = "done";
  if ((prepare?.stages || []).some((s) => ["preview", "waveform"].includes(s.stage)) ||
      ["preview", "waveform"].includes(prepare?.stage))
    Object.assign(row("preview"), stageState(prepare, ["preview", "waveform"]));

  for (const [key, , stages] of STEPS.slice(2, 7))
    Object.assign(row(key), stageState(prepare, stages));
  // Old records did not log successful 'apply' or optional skipped work.
  if (prepare?.status === "done" && project.preparation_key)
    row("captions").state = project.preparation_kind === "visual" ? "skipped" : "done";
  if (project.preparation_kind === "visual" && prepare?.status === "done")
    for (const key of ["transcript", "pauses", "takes", "captions"])
      row(key).state = "skipped";
  const laterThanPrepare = (job) => job && (!prepare || (job.queued_at || 0) > (prepare.queued_at || 0));
  if (laterThanPrepare(jobs.transcribe)) {
    const job = jobs.transcribe;
    Object.assign(row("transcript"), stageState(job, ["transcription"]));
    Object.assign(row("audio"), stageState(job, ["audio"]));
    if (job.status === "done") {
      row("transcript").state = "done";
      row("captions").state = "done";
    }
  }
  if (laterThanPrepare(jobs.silence)) {
    const job = jobs.silence;
    row("pauses").state = job.status === "done" ? "done" : job.status === "error" ? "error" :
      job.status === "queued" ? "queued" : "active";
  }

  if (assistant && !preparing) Object.assign(row("assistant"), {
    state: assistant.stage === "preserved" ? "skipped" :
      assistant.status === "done" ? "done" : assistant.status === "error" ? "error" :
        assistant.status === "queued" ? "queued" : "active",
    detail: assistant.message,
  });
  if (prepare?.next_job_pending && !active(assistant)) row("assistant").state = "queued";
  const exported = jobs.export;
  if (active(exported)) row("export").state = exported.status === "queued" ? "queued" : "active";
  else if (exportReady) row("export").state = "done";

  const running = Object.entries(jobs).find(([, j]) => j.status === "running") ||
    Object.entries(jobs).find(([, j]) => active(j));
  const names = Object.fromEntries(STEPS.flatMap(([, label, stages]) => stages.map((s) => [s, label])));
  let message = "", error = false;
  if (running) {
    const [kind, job] = running;
    message = job.status === "queued" ? "Queued" : kind === "assistant"
      ? job.message : names[job.stage] || ({ prepare: "Preparing video", export: "Exporting video",
        transcribe: "Transcribing", silence: "Removing pauses" })[kind] || "Preparing preview";
    if (kind === "preview" && job.stage === "waveform") message = "Preparing audio waveform";
    // Standalone actions report only their own real work.
    if (kind === "transcribe") Object.assign(row("transcript"), stageState(job, ["transcription"]));
    if (kind === "silence") row("pauses").state = job.status === "running" ? "active" : "queued";
  } else if (prepare?.next_job_pending) message = "Waiting for AI editor";
  else {
    const relevant = [preview, prepare, assistant, exported, jobs.transcribe, jobs.silence].filter(Boolean)
      .sort((a, b) => (b.queued_at || 0) - (a.queued_at || 0))[0];
    if (relevant?.status === "error") {
      error = true;
      message = relevant.message || "Processing stopped";
    } else if (assistant?.status === "done")
      message = assistant.outcome === "needs_review" ? "Review needed" :
        assistant.stage === "preserved" ? "Saved edit preserved" : "Ready for review";
    else if (prepare?.status === "done") message = "Ready for review";
  }
  return { rows, message, error, visible: !!running || !!prepare?.next_job_pending,
    loading: project.media_ready ? "" : error ? message :
      preview?.stage === "waveform" ? "Preparing audio waveform" : "Preparing video preview" };
}

/** Mount once. Updating text/classes must not replace an animating indicator. */
export function mountProgress(root, message) {
  const nodes = new Map();
  for (const [key, label] of STEPS) {
    const item = document.createElement("li"), icon = document.createElement("span"),
      text = document.createElement("span");
    item.className = "processing-step";
    icon.className = "step-icon";
    icon.setAttribute("aria-hidden", "true");
    text.textContent = label;
    item.append(icon, text);
    root.append(item);
    nodes.set(key, { item, icon });
  }
  return {
    update(view) {
      root.hidden = !view.visible;
      for (const r of view.rows) {
        const { item, icon } = nodes.get(r.key);
        if (item.dataset.state !== r.state) item.dataset.state = r.state;
        const symbol = r.state === "done" ? "✓" : r.state === "skipped" ? "–" : r.state === "error" ? "!" : "";
        if (icon.textContent !== symbol) icon.textContent = symbol;
        item.title = r.detail || "";
        item.setAttribute("aria-label", `${r.label}: ${r.state}${r.detail ? `. ${r.detail}` : ""}`);
        if (r.state === "active") item.setAttribute("aria-current", "step");
        else item.removeAttribute("aria-current");
      }
      if (message.textContent !== view.message) message.textContent = view.message;
      message.classList.toggle("error", view.error);
      message.hidden = !view.message || (!view.visible && !view.error) ||
        view.rows.some((r) => r.state === "active" && r.label === view.message);
    },
  };
}
