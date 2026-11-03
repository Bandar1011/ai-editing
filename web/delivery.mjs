const FIELDS = ["cuts", "split_points", "subtitles", "subtitle_style", "overlays", "punches", "music", "story"];
const editKey = (p) => JSON.stringify([
  ...FIELDS.map((k) => p[k] ?? (k === "split_points" ? [] : null)),
  p.brief, p.references, p.source_sha256,
]);

export function exportMatches(project, exported) {
  const settings = exported.render_settings || {};
  return settings.format === "vertical" && settings.plain === false &&
    settings.burn_subtitles === !!(project.subtitle_style.enabled && project.subtitles.length) &&
    exported.source_sha256 === project.source_sha256 &&
    FIELDS.every((key) => JSON.stringify(exported.edit_state?.[key] ?? (key === "split_points" ? [] : null)) ===
      JSON.stringify(project[key] ?? (key === "split_points" ? [] : null))) &&
    JSON.stringify(exported.brief) === JSON.stringify(project.brief) &&
    JSON.stringify(exported.references) === JSON.stringify(project.references);
}

export function currentExport(project) {
  return project && [...project.exports].reverse().find((e) => exportMatches(project, e));
}

/** Own one delivery attempt and its frozen edit, through export and native sharing. */
export function createAirDrop({ read, save, api, apply, notify, wait = (ms) => new Promise((r) => setTimeout(r, ms)) }) {
  let pending = false;
  return {
    get pending() { return pending; },
    async send() {
      if (pending) return;
      const initial = read(), id = initial.project?.id;
      if (!id || initial.busy || initial.conflicted || initial.uploading)
        throw new Error("Finish processing and save this edit before sharing.");
      pending = true;
      try {
        notify("preparing", "Preparing video for AirDrop");
        await save();
        let context = read();
        if (context.project?.id !== id || context.editSequence !== initial.editSequence || context.dirty || context.conflicted)
          throw new Error("The edit changed. Try sharing the saved edit again.");
        const binding = editKey(context.project);
        const check = (server = null) => {
          const current = read();
          if (current.project?.id !== id || current.dirty || current.conflicted ||
              editKey(current.project) !== binding || (server && editKey(server) !== binding))
            throw new Error("The edit changed while preparing AirDrop. Your changes were preserved.");
        };
        let exported = currentExport(context.project);
        if (!exported) {
          notify("exporting", "Exporting video for AirDrop");
          let response = await api(`/api/projects/${id}/export`, { method: "POST", body: {
            base_revision: context.project.revision, format: "vertical", plain: false,
            burn_subtitles: context.project.subtitle_style.enabled,
          } });
          check(response);
          const jobId = response.jobs.export.id;
          apply(response);
          while (["queued", "running"].includes(response.jobs.export.status)) {
            await wait(500);
            check();
            response = await api(`/api/projects/${id}/status`);
            if (response.jobs.export?.id !== jobId) throw new Error("Another export replaced this request. Try sharing again.");
          }
          if (response.jobs.export.status !== "done") throw new Error(response.jobs.export.message || "Export failed.");
        }
        // Read the current revision immediately before the guarded delivery request.
        const latest = await api(`/api/projects/${id}`);
        check(latest);
        apply(latest);
        exported = currentExport(latest);
        if (!exported) throw new Error("A current export is not available. Export the video and try again.");
        const filename = exported.file;
        notify("preparing", "Opening AirDrop");
        let result = await api(`/api/projects/${id}/airdrop`, { method: "POST", body: {
          base_revision: latest.revision, file: filename,
          request_id: crypto.randomUUID().replaceAll("-", ""),
        } });
        const checkResult = () => {
          if (result.file !== filename || result.project_id !== id) throw new Error("The AirDrop request changed.");
        };
        checkResult();
        while (["preparing", "choosing"].includes(result.status)) {
          notify(result.status, result.message);
          await wait(700);
          result = await api(`/api/projects/${id}/airdrop/${result.id}`);
          checkResult();
        }
        if (result.status === "error") throw new Error(result.message);
        if (!["closed", "cancelled"].includes(result.status)) throw new Error("AirDrop did not confirm completion.");
        notify(result.status, result.message);
        return result;
      } catch (error) {
        notify("error", error.message);
        throw error;
      } finally { pending = false; }
    },
  };
}
