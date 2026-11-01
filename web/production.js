export function createProduction({
  getProject,
  applyProject,
  api,
  changed,
  pushUndo,
  saveNow,
  toast,
  time,
  parseTime,
  video,
  outputTime,
  isEdited,
  showOriginal,
  task,
}) {
  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  api("/api/capture/config")
    .then((config) => {
      $("capture-target").textContent = config.configured
        ? config.name + " · this Mac"
        : "Configure a local app capture target";
    })
    .catch(() => {});
  const uid = () => crypto.randomUUID().replaceAll("-", "").slice(0, 10);
  let library = [],
    loading = false,
    libraryReady = false,
    downloadJob = null,
    takePreviewEnd = null;
  const act =
    (fn) =>
    async (...args) => {
      try {
        await fn(...args);
      } catch (e) {
        toast(e.message, true);
      }
    };
  async function loadLibrary() {
    if (loading) return;
    loading = true;
    try {
      library = await api("/api/assets");
      libraryReady = true;
      renderLibrary();
    } finally {
      loading = false;
    }
  }
  function renderLibrary() {
    const q = $("asset-search").value.toLowerCase();
    const filtered = library.filter((a) =>
      [a.name, a.description, ...a.tags].join(" ").toLowerCase().includes(q),
    );
    $("asset-list").innerHTML =
      filtered
        .map(
          (a) =>
            `<article class="asset-card"><strong>${esc(a.name)}</strong><small>${a.kind} · ${esc(a.tags.join(", "))}</small><p>${esc(a.description.slice(0, 140))}</p><button class="text-button" data-use-asset="${a.id}">${a.kind === "audio" ? "Use music" : "Add overlay"}</button><button class="text-button" data-edit-asset="${a.id}">Details</button></article>`,
        )
        .join("") ||
      '<p class="panel-hint">Import a screenshot, recording, B-roll clip, or music track.</p>';
    const options =
      '<option value="">No music</option>' +
      library
        .filter((a) => a.has_audio)
        .map((a) => `<option value="${a.id}">${esc(a.name)}</option>`)
        .join("");
    $("music-asset").innerHTML = options;
    const p = getProject();
    if (p) $("music-asset").value = p.music?.asset_id || "";
  }
  function render(p) {
    if (
      !libraryReady ||
      p.overlays.some((o) => !library.some((a) => a.id === o.asset_id)) ||
      (p.music && !library.some((a) => a.id === p.music.asset_id))
    )
      loadLibrary().catch((e) => toast(e.message, true));
    $("caption-case").checked = p.subtitle_style.uppercase;
    $("caption-margin").value = p.subtitle_style.margin_percent;
    $("caption-outline").value = p.subtitle_style.outline;
    $("caption-max-words").value = p.subtitle_style.max_words;
    for (const key of ["topic", "hook", "hook_reason", "cta", "app_bundle_id"])
      $(`story-${key}`).value = p.story[key] || "";
    $("music-asset").value = p.music?.asset_id || "";
    $("music-volume").value = p.music?.volume ?? 0.12;
    $("music-duck").checked = p.music?.duck ?? true;
    $("music-offset").value = p.music?.offset ?? 0;
    $("retake-list").innerHTML =
      p.retakes
        .map(
          (r) =>
            `<article class="retake-card"><small>${r.automatic ? "Selected automatically" : r.status === "selected" ? "Your selection" : "Compare takes"}</small>${r.takes.map((t, i) => `<div><button class="text-button" data-preview-take="${t.start}" data-preview-end="${t.end}">▷ ${time(t.start)}–${time(t.end)}</button><p>${esc(t.text)}</p><button class="button subtle ${r.selected === i && r.status === "selected" ? "chosen" : ""}" data-take="${r.id}" data-index="${i}">Keep take ${i + 1}</button></div>`).join("")}<p class="panel-hint">${esc(r.reason)}</p><button class="text-button" data-keep-both="${r.id}">Keep both</button></article>`,
        )
        .join("") ||
      '<p class="panel-hint">Make a first cut to check for repeated takes. Decisions remain reversible.</p>';
    $("overlay-list").innerHTML =
      p.overlays
        .map((o) => {
          const a = library.find((a) => a.id === o.asset_id);
          return `<article class="overlay-card" data-overlay="${o.id}"><div class="row-heading"><strong>${esc(a?.name || "Reference overlay")}</strong><button class="text-button" data-remove-overlay="${o.id}">Remove</button></div><div class="two-settings"><label>Source in<input data-overlay-field="start" value="${time(o.start)}" aria-label="Overlay start"></label><label>Source out<input data-overlay-field="end" value="${time(o.end)}" aria-label="Overlay end"></label></div><label>Placement<select data-overlay-field="layout"><option value="top" ${o.layout === "top" ? "selected" : ""}>Top card</option><option value="bottom" ${o.layout === "bottom" ? "selected" : ""}>Lower card</option><option value="full" ${o.layout === "full" ? "selected" : ""}>Full screen</option></select></label>${a?.kind === "video" ? `<label>Recording offset (seconds)<input data-overlay-field="asset_in" type="number" min="0" step="0.1" value="${o.asset_in}"></label>` : ""}<label>What does it explain?<input data-overlay-field="purpose" value="${esc(o.purpose)}" maxlength="2000"></label><label class="inline-label">Show overlay<input type="checkbox" data-overlay-field="enabled" ${o.enabled ? "checked" : ""}></label></article>`;
        })
        .join("") ||
      '<p class="panel-hint">Add a library asset at the playhead. Keep references relevant to what you say.</p>';
    $("punch-list").innerHTML = p.punches
      .map(
        (z) =>
          `<div class="punch-row"><span>${time(z.start)}–${time(z.end)} · ${z.scale}×</span><button class="text-button" data-remove-punch="${z.id}">Remove</button></div>`,
      )
      .join("");
    updatePreview();
  }
  function change() {
    changed();
    updatePreview();
  }
  $("prepare-button").onclick = act(() => task("prepare"));
  for (const [id, key] of [
    ["caption-case", "uppercase"],
    ["caption-margin", "margin_percent"],
    ["caption-outline", "outline"],
    ["caption-max-words", "max_words"],
  ]) {
    $(id).onchange = (e) => {
      const p = getProject();
      if (!p) return;
      pushUndo();
      p.subtitle_style[key] =
        e.target.type === "checkbox"
          ? e.target.checked
          : Number(e.target.value);
      change();
    };
  }
  for (const key of ["topic", "hook", "hook_reason", "cta", "app_bundle_id"]) {
    $(`story-${key}`).onfocus = pushUndo;
    $(`story-${key}`).oninput = (e) => {
      getProject().story[key] = e.target.value;
      change();
    };
  }
  $("suggest-hooks").onclick = act(async () => {
    const p = getProject(),
      result = await api(
        "/api/hooks?" +
          new URLSearchParams({ topic: p.story.topic || p.brief.goal }),
      );
    $("hook-suggestions").innerHTML = result.patterns
      .map(
        (h) =>
          `<button class="hook-choice" data-hook="${esc(h.text)}">${esc(h.text)}<small>${esc(h.purpose)}</small></button>`,
      )
      .join("");
    $("hook-history").innerHTML =
      result.related_performance
        .map(
          (h) =>
            `<p class="panel-hint">${esc(h.text)} · ${h.views ?? "—"} views · ${h.retention === null ? "—" : Math.round(h.retention * 100) + "%"} retention</p>`,
        )
        .join("") ||
      '<p class="panel-hint">No measured performance for this topic yet.</p>';
  });
  $("hook-suggestions").onclick = (e) => {
    const b = e.target.closest("[data-hook]");
    if (!b) return;
    pushUndo();
    getProject().story.hook = b.dataset.hook;
    $("story-hook").value = b.dataset.hook;
    change();
  };
  $("save-hook-performance").onclick = act(async () => {
    const p = getProject(),
      views = $("hook-views").value,
      retention = $("hook-retention").value;
    await api("/api/hooks", {
      method: "POST",
      body: {
        text: p.story.hook,
        topic: p.story.topic,
        source_url: $("hook-source").value,
        views: views === "" ? null : Number(views),
        retention: retention === "" ? null : Number(retention) / 100,
        notes: p.story.hook_reason,
      },
    });
    toast("Hook saved with the supplied performance evidence.");
  });
  $("retake-list").onclick = act(async (e) => {
    const preview = e.target.closest("[data-preview-take]");
    if (preview) {
      showOriginal();
      takePreviewEnd = Number(preview.dataset.previewEnd);
      video.currentTime = Number(preview.dataset.previewTake);
      video.play();
      return;
    }
    const b = e.target.closest("[data-take],[data-keep-both]");
    if (!b) return;
    await saveNow();
    const p = getProject(),
      selected = b.dataset.take ? Number(b.dataset.index) : null;
    const next = await api(
      `/api/projects/${p.id}/retakes/${b.dataset.take || b.dataset.keepBoth}`,
      {
        method: "POST",
        body: {
          selected,
          reason:
            selected === null
              ? "Keep both after reviewing the delivery."
              : "Selected this take after reviewing its delivery.",
        },
      },
    );
    applyProject(next);
    toast("Take decision saved.");
  });
  $("asset-search").oninput = renderLibrary;
  $("add-asset").onclick = () => $("asset-file").click();
  $("asset-file").onchange = act(async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const data = new FormData();
    data.append("file", file);
    const a = await api("/api/assets/upload", { method: "POST", body: data });
    await loadLibrary();
    openMetadata(a);
    e.target.value = "";
    toast("Asset copied into your local library.");
  });
  function openMetadata(a) {
    $("asset-metadata").hidden = false;
    $("asset-metadata").dataset.id = a.id;
    for (const key of ["name", "description", "rights"])
      $(`asset-${key}`).value = a[key];
    $("asset-tags").value = a.tags.join(", ");
    $("asset-provenance").textContent = a.source_url || a.source_kind;
  }
  $("asset-metadata").onsubmit = act(async (e) => {
    e.preventDefault();
    const id = $("asset-metadata").dataset.id;
    await api(`/api/assets/${id}`, {
      method: "PUT",
      body: {
        name: $("asset-name").value,
        description: $("asset-description").value,
        rights: $("asset-rights").value,
        tags: $("asset-tags")
          .value.split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      },
    });
    $("asset-metadata").hidden = true;
    await loadLibrary();
    toast("Asset details saved.");
  });
  function addAsset(a) {
    const p = getProject();
    pushUndo();
    if (a.kind === "audio") {
      p.music = {
        asset_id: a.id,
        volume: 0.12,
        offset: 0,
        duck: true,
        enabled: true,
      };
      $("music-asset").value = a.id;
    } else {
      const start = Math.min(video.currentTime || 0, p.media.duration - 0.02),
        length = Math.min(
          a.kind === "video" ? a.duration : 4,
          p.media.duration - start,
        );
      p.overlays.push({
        id: uid(),
        asset_id: a.id,
        start,
        end: start + length,
        asset_in: 0,
        layout: "top",
        enabled: true,
        purpose: "",
      });
    }
    change();
    render(p);
  }
  $("asset-list").onclick = (e) => {
    const use = e.target.closest("[data-use-asset]"),
      edit = e.target.closest("[data-edit-asset]");
    if (use) addAsset(library.find((a) => a.id === use.dataset.useAsset));
    if (edit)
      openMetadata(library.find((a) => a.id === edit.dataset.editAsset));
  };
  $("fetch-asset").onclick = act(async () => {
    const result = await api("/api/assets/fetch", {
      method: "POST",
      body: { url: $("asset-url").value, kind: $("download-kind").value },
    });
    downloadJob = result.id;
    $("download-status").textContent = "Downloading to your local library…";
  });
  $("refresh-assets").onclick = act(loadLibrary);
  $("capture-app").onclick = act(async () => {
    const result = await api("/api/assets/capture-app", {
      method: "POST",
      body: {
        mode: $("app-capture-mode").value,
        seconds: Number($("app-capture-seconds").value),
        description: "App reference captured on this Mac",
      },
    });
    downloadJob = result.id;
    $("download-status").textContent = "Capturing the app on this Mac…";
  });
  async function pollDownload() {
    if (!downloadJob) return;
    try {
      const j = await api("/api/assets/jobs/" + downloadJob);
      if (j.status === "running") return;
      downloadJob = null;
      $("download-status").textContent =
        j.status === "done" ? "Download ready." : j.message;
      if (j.status === "done") {
        await loadLibrary();
        openMetadata(j.asset);
      }
    } catch (e) {
      downloadJob = null;
      $("download-status").textContent = e.message;
    }
  }
  setInterval(pollDownload, 1800);
  for (const id of [
    "music-asset",
    "music-volume",
    "music-offset",
    "music-duck",
  ])
    $(id).onchange = () => {
      const p = getProject();
      pushUndo();
      p.music = $("music-asset").value
        ? {
            asset_id: $("music-asset").value,
            volume: Number($("music-volume").value),
            offset: Number($("music-offset").value),
            duck: $("music-duck").checked,
            enabled: true,
          }
        : null;
      change();
    };
  $("overlay-list").onfocusin = (e) => {
    if (e.target.matches("input,select")) pushUndo();
  };
  $("overlay-list").onchange = (e) => {
    const row = e.target.closest("[data-overlay]"),
      field = e.target.dataset.overlayField;
    if (!row || !field) return;
    const p = getProject(),
      o = p.overlays.find((o) => o.id === row.dataset.overlay),
      value =
        e.target.type === "checkbox"
          ? e.target.checked
          : field === "start" || field === "end"
            ? parseTime(e.target.value)
            : field === "asset_in"
              ? Number(e.target.value)
              : e.target.value;
    if (
      (field === "start" || field === "end") &&
      (!Number.isFinite(value) ||
        value < 0 ||
        value > p.media.duration ||
        (field === "start" ? o.end - value : value - o.start) < 0.02)
    ) {
      toast("Use valid source times inside the recording.", true);
      render(p);
      return;
    }
    o[field] = value;
    change();
  };
  $("overlay-list").onclick = (e) => {
    const b = e.target.closest("[data-remove-overlay]");
    if (!b) return;
    const p = getProject();
    pushUndo();
    p.overlays = p.overlays.filter((o) => o.id !== b.dataset.removeOverlay);
    change();
    render(p);
  };
  $("add-punch").onclick = () => {
    const p = getProject();
    pushUndo();
    const start = Math.min(video.currentTime || 0, p.media.duration - 0.02);
    p.punches.push({
      id: uid(),
      start,
      end: Math.min(p.media.duration, start + 2),
      scale: 1.1,
      enabled: true,
    });
    change();
    render(p);
  };
  $("punch-list").onclick = (e) => {
    const b = e.target.closest("[data-remove-punch]");
    if (!b) return;
    const p = getProject();
    pushUndo();
    p.punches = p.punches.filter((z) => z.id !== b.dataset.removePunch);
    change();
    render(p);
  };
  function updatePreview() {
    const p = getProject();
    if (!p) return;
    const t = video.currentTime || 0,
      edited = isEdited(),
      stage = $("video-stage"),
      holder = $("reference-overlay"),
      image = $("reference-image"),
      clip = $("reference-video");
    const z = edited
      ? p.punches.filter((z) => z.enabled && z.start <= t && t < z.end).at(-1)
      : null;
    video.style.transform = z ? `scale(${z.scale})` : "";
    if (edited) takePreviewEnd = null;
    if (takePreviewEnd !== null && t >= takePreviewEnd) {
      takePreviewEnd = null;
      video.pause();
    }
    const o = edited
      ? p.overlays.filter((o) => o.enabled && o.start <= t && t < o.end).at(-1)
      : null;
    holder.hidden = !o;
    if (o) {
      const a = library.find((a) => a.id === o.asset_id),
        ratio = p.media.width / p.media.height,
        h = Math.min(stage.clientHeight, stage.clientWidth / ratio),
        w = Math.min(stage.clientWidth, stage.clientHeight * ratio),
        full = o.layout === "full";
      holder.style.width = `${w * (full ? 1 : 0.88)}px`;
      holder.style.height = `${h * (full ? 1 : 0.38)}px`;
      holder.style.left = `${(stage.clientWidth - w * (full ? 1 : 0.88)) / 2}px`;
      holder.style.top = `${(stage.clientHeight - h) / 2 + h * (full ? 0 : o.layout === "top" ? 0.05 : 0.48)}px`;
      const src = `/api/assets/${o.asset_id}/media`;
      image.hidden = a?.kind === "video";
      clip.hidden = a?.kind !== "video";
      if (a?.kind === "video") {
        if (clip.dataset.asset !== a.id) {
          clip.src = src;
          clip.dataset.asset = a.id;
          clip.load();
        }
        const expected = o.asset_in + t - o.start;
        if (
          Number.isFinite(clip.duration) &&
          Math.abs(clip.currentTime - expected) > 0.15
        )
          clip.currentTime = Math.min(expected, clip.duration);
        if (!video.paused) clip.play().catch(() => {});
        else clip.pause();
      } else if (image.dataset.asset !== o.asset_id) {
        image.src = src;
        image.dataset.asset = o.asset_id;
      }
    } else clip.pause();
    const audio = $("music-preview"),
      music = edited && p.music?.enabled ? p.music : null;
    if (!music || video.paused || video.muted) {
      audio.pause();
      return;
    }
    const a = library.find((a) => a.id === music.asset_id);
    if (!a) return;
    if (audio.dataset.asset !== a.id) {
      audio.src = `/api/assets/${a.id}/media`;
      audio.dataset.asset = a.id;
      audio.load();
    }
    const expected = (music.offset + outputTime(t)) % a.duration;
    if (
      Number.isFinite(audio.duration) &&
      Math.abs(audio.currentTime - expected) > 0.2
    )
      audio.currentTime = expected;
    audio.volume =
      music.volume *
      (music.duck && p.subtitles.some((c) => c.start <= t && t < c.end)
        ? 0.25
        : 1);
    audio.play().catch(() => {});
  }
  for (const event of ["play", "pause", "seeked", "timeupdate"])
    video.addEventListener(event, updatePreview);
  return { render, updatePreview, loadLibrary };
}
