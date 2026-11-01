import { overlayBox } from "./canvas.mjs?v=factory-4";
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
  refreshTimeline,
  task,
  selectLayer,
  onPreviewUpdate,
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
      if (getProject()) render(getProject());
      refreshTimeline();
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
        .map((a) => {
          const media = `/api/assets/${a.id}/media`;
          const thumb =
            a.kind === "image"
              ? `<img src="${media}" loading="lazy" alt="">`
              : a.kind === "video"
                ? `<video src="${media}" muted preload="metadata"></video>`
                : '<span class="audio-icon" aria-hidden="true">♪</span>';
          return `<article class="asset-card"><div class="asset-thumbnail">${thumb}</div><div class="asset-info"><strong title="${esc(a.name)}">${esc(a.name)}</strong><small>${a.kind === "image" ? "Image" : a.kind === "audio" ? "Audio" : "Video"}${a.kind !== "image" ? " · " + time(a.duration, false) : ""}</small><div class="asset-actions"><button class="text-button" data-use-asset="${a.id}">${a.kind === "audio" ? "Add audio" : "Add overlay"}</button>${a.has_audio ? `<button class="text-button" data-use-music="${a.id}">Use as music</button>` : ""}<button class="text-button" data-edit-asset="${a.id}">Details</button></div></div></article>`;
        })
        .join("") || '<p class="empty-list">No media</p>';
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
    $("music-asset").value = p.music?.asset_id || "";
    $("music-volume").value = p.music?.volume ?? 0.12;
    $("music-duck").checked = p.music?.duck ?? true;
    $("music-offset").value = p.music?.offset ?? 0;
    document.querySelector(".retakes").hidden = !p.retakes.length;
    $("retake-list").innerHTML =
      p.retakes
        .map(
          (r) =>
            `<article class="retake-card"><small>${r.automatic ? "Selected automatically" : r.status === "selected" ? "Your selection" : "Compare takes"}</small>${r.takes.map((t, i) => `<div><button class="text-button" data-preview-take="${t.start}" data-preview-end="${t.end}">▷ ${time(t.start)}–${time(t.end)}</button><p>${esc(t.text)}</p><button class="button subtle ${r.selected === i && r.status === "selected" ? "chosen" : ""}" data-take="${r.id}" data-index="${i}">Keep take ${i + 1}</button></div>`).join("")}<p class="panel-hint">${esc(r.reason)}</p><button class="text-button" data-keep-both="${r.id}">Keep both</button></article>`,
        )
        .join("") ||
      '<p class="panel-hint">Make a first cut to check for repeated takes. Decisions remain reversible.</p>';
    $("overlay-list").innerHTML = p.overlays
      .map((o) => {
        const a = library.find((a) => a.id === o.asset_id),
          audioOnly = a?.kind === "audio";
        return `<article class="overlay-card" data-overlay="${o.id}"><div class="row-heading"><strong>${esc(a?.name || "Overlay")}</strong><button class="text-button" data-remove-overlay="${o.id}">Remove</button></div><div class="two-settings"><label>Source start<input data-overlay-field="start" value="${time(o.start)}" aria-label="Overlay start"></label><label>Source end<input data-overlay-field="end" value="${time(o.end)}" aria-label="Overlay end"></label></div>${a?.kind !== "image" ? `<label>Clip offset (seconds)<input type="number" min="0" step="0.1" data-overlay-field="asset_in" value="${o.asset_in}"></label>` : ""}${!audioOnly && (o.x != null || o.y != null) ? `<button class="text-button" data-reset-overlay="${o.id}">Reset position</button>` : ""}${!audioOnly ? `<label>Placement<select data-overlay-field="layout"><option value="top" ${o.layout === "top" ? "selected" : ""}>Top</option><option value="bottom" ${o.layout === "bottom" ? "selected" : ""}>Bottom</option><option value="full" ${o.layout === "full" ? "selected" : ""}>Full frame</option></select></label>` : ""}${a?.has_audio && !audioOnly ? `<label class="inline-label">Play clip audio<input type="checkbox" data-overlay-field="audio" ${o.audio ? "checked" : ""}></label>` : ""}${a?.has_audio && (o.audio || audioOnly) ? `<label>Audio volume<input type="range" min="0" max="1" step="0.01" data-overlay-field="volume" value="${o.volume ?? 0.4}"></label>` : ""}<label class="inline-label">${audioOnly ? "Enable audio" : "Show overlay"}<input type="checkbox" data-overlay-field="enabled" ${o.enabled ? "checked" : ""}></label></article>`;
      })
      .join("");
    $("punch-list").innerHTML = p.punches
      .map(
        (z) =>
          `<article class="punch-card" data-punch="${z.id}"><div class="row-heading"><strong>Zoom ${z.scale}×</strong><button class="text-button" data-remove-punch="${z.id}">Remove</button></div><div class="two-settings"><label>Source start<input data-punch-field="start" value="${time(z.start)}"></label><label>Source end<input data-punch-field="end" value="${time(z.end)}"></label></div><label>Zoom<input type="range" min="1" max="1.3" step="0.01" value="${z.scale}" data-punch-field="scale"></label></article>`,
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
  $("close-asset-details").onclick = () => {
    $("asset-metadata").hidden = true;
  };
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
  function addAsset(a, asMusic = false) {
    const p = getProject();
    pushUndo();
    if (asMusic) {
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
          a.kind === "video" || a.kind === "audio" ? a.duration : 4,
          p.media.duration - start,
        );
      p.overlays.push({
        id: uid(),
        asset_id: a.id,
        start,
        end: start + length,
        asset_in: 0,
        audio: a.kind === "audio",
        volume: 0.4,
        layout: "top",
        enabled: true,
        purpose: "",
      });
    }
    change();
    render(p);
    if (!asMusic) selectLayer({ kind: "overlay", id: p.overlays.at(-1).id });
    if (asMusic) {
      const controls = document.querySelector(".music-tools");
      controls.open = true;
      controls.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } else
      document
        .querySelector(`[data-overlay="${p.overlays.at(-1).id}"]`)
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  $("asset-list").onclick = (e) => {
    const use = e.target.closest("[data-use-asset]"),
      edit = e.target.closest("[data-edit-asset]"),
      music = e.target.closest("[data-use-music]");
    if (use) addAsset(library.find((a) => a.id === use.dataset.useAsset));
    if (music)
      addAsset(
        library.find((a) => a.id === music.dataset.useMusic),
        true,
      );
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
            : field === "asset_in" || field === "volume"
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
    const next = { ...o, [field]: value },
      asset = library.find((a) => a.id === o.asset_id);
    if (
      (field === "asset_in" || field === "start" || field === "end") &&
      asset &&
      asset.kind !== "image" &&
      (next.asset_in < 0 ||
        next.asset_in + next.end - next.start > asset.duration + 0.05)
    ) {
      toast("The selected range exceeds the clip length.", true);
      render(p);
      return;
    }
    if (o[field] === value) return;
    pushUndo();
    o[field] = value;
    if (field === "layout") {
      delete o.x;
      delete o.y;
    }
    change();
    if (field === "audio" || field === "layout") render(p);
  };
  $("overlay-list").onclick = (e) => {
    const reset = e.target.closest("[data-reset-overlay]");
    if (reset) {
      const o = getProject().overlays.find(
        (o) => o.id === reset.dataset.resetOverlay,
      );
      pushUndo();
      delete o.x;
      delete o.y;
      change();
      render(getProject());
      return;
    }
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

  $("punch-list").onchange = (e) => {
    const row = e.target.closest("[data-punch]"),
      field = e.target.dataset.punchField;
    if (!row || !field) return;
    const p = getProject(),
      z = p.punches.find((z) => z.id === row.dataset.punch);
    const value =
      field === "scale" ? Number(e.target.value) : parseTime(e.target.value);
    if (
      !Number.isFinite(value) ||
      (field !== "scale" &&
        (value < 0 ||
          value > p.media.duration ||
          (field === "start" ? z.end - value : value - z.start) < 0.02))
    ) {
      toast("Use a range inside the video.", true);
      render(p);
      return;
    }
    if (z[field] === value) return;
    pushUndo();
    z[field] = value;
    change();
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
  const overlayAudio = new Map(),
    overlayNodes = new Map();
  function updatePreview() {
    const p = getProject();
    if (!p) return;
    const t = video.currentTime || 0,
      edited = isEdited(),
      stage = $("video-stage"),
      holder = $("reference-overlay");
    const z = edited
      ? p.punches.filter((z) => z.enabled && z.start <= t && t < z.end).at(-1)
      : null;
    video.style.transform = z ? `scale(${z.scale})` : "";
    if (edited) takePreviewEnd = null;
    if (takePreviewEnd !== null && t >= takePreviewEnd) {
      takePreviewEnd = null;
      video.pause();
    }
    const visible = new Set();
    for (const [order, o] of p.overlays.entries()) {
      const a = library.find((a) => a.id === o.asset_id);
      if (
        !edited ||
        !o.enabled ||
        o.start > t ||
        t >= o.end ||
        !a ||
        a.kind === "audio"
      )
        continue;
      visible.add(o.id);
      let node = overlayNodes.get(o.id);
      if (node && node.dataset.asset !== o.asset_id) {
        node.querySelector("video")?.pause();
        node.remove();
        overlayNodes.delete(o.id);
        node = null;
      }
      if (!node) {
        node = document.createElement("div");
        node.className = "canvas-overlay";
        node.dataset.canvasOverlay = o.id;
        node.dataset.asset = o.asset_id;
        node.dataset.kind = a.kind;
        node.setAttribute("role", "button");
        node.tabIndex = 0;
        const content = document.createElement(
          a.kind === "video" ? "video" : "img",
        );
        content.src = `/api/assets/${o.asset_id}/media`;
        content.draggable = false;
        if (a.kind === "video") {
          content.muted = true;
          content.playsInline = true;
          content.preload = "metadata";
          content.addEventListener("loadedmetadata", updatePreview);
        } else content.alt = a.name;
        node.append(content);
        holder.append(node);
        overlayNodes.set(o.id, node);
      }
      const b = overlayBox(o);
      node.setAttribute("aria-label", `Overlay: ${a.name}`);
      Object.assign(node.style, {
        width: `${b.width * 100}%`,
        height: `${b.height * 100}%`,
        left: `${(b.x - b.width / 2) * 100}%`,
        top: `${(b.y - b.height / 2) * 100}%`,
        zIndex: order,
      });
      const clip = node.querySelector("video");
      if (clip) {
        const expected = o.asset_in + t - o.start;
        if (
          Number.isFinite(clip.duration) &&
          Math.abs(clip.currentTime - expected) > 0.15
        )
          clip.currentTime = Math.min(expected, clip.duration);
        if (video.paused) clip.pause();
        else clip.play().catch(() => {});
      }
    }
    holder.hidden = !visible.size;
    for (const [id, node] of overlayNodes)
      if (!visible.has(id)) {
        node.querySelector("video")?.pause();
        node.remove();
        overlayNodes.delete(id);
      }
    onPreviewUpdate();
    const sounding = new Set();
    if (edited && !video.paused && !video.muted)
      for (const o of p.overlays) {
        const a = library.find((a) => a.id === o.asset_id);
        if (
          !o.enabled ||
          !o.audio ||
          !a?.has_audio ||
          t < o.start ||
          t >= o.end
        )
          continue;
        const key = `${p.id}/${o.id}/${o.asset_id}`;
        sounding.add(key);
        if (!overlayAudio.has(key))
          overlayAudio.set(key, new Audio(`/api/assets/${o.asset_id}/media`));
        const player = overlayAudio.get(key),
          expected = o.asset_in + t - o.start;
        if (
          Number.isFinite(player.duration) &&
          Math.abs(player.currentTime - expected) > 0.15
        )
          player.currentTime = Math.min(expected, player.duration);
        player.volume = o.volume ?? 0.4;
        player.play().catch(() => {});
      }
    for (const [key, player] of overlayAudio)
      if (!sounding.has(key)) {
        player.pause();
        overlayAudio.delete(key);
      }
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
  for (const event of ["play", "pause", "seeked", "timeupdate", "volumechange"])
    video.addEventListener(event, updatePreview);
  return { render, updatePreview, loadLibrary, getAssets: () => library };
}
