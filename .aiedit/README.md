# Local media storage

Reels Factory saves uploads and edited versions here on your laptop. GitHub contains only this README and the empty `projects/.gitkeep` placeholder. All generated data and project contents are ignored by Git.

Each upload creates a project folder:

```text
projects/<project-id>/
  source/original.<extension>  Uploaded original, preserved unchanged
  exports/                    Edited videos and their captions and edit snapshots
  working/                    Preview video, waveform, and transcript
  references/                 Supporting assets
  history/                    Earlier project revisions
  project.json                Current editing decisions
```

Exports are versioned: making another edit or export keeps earlier versions. Shared library assets and speech models also stay local under `library/` and `models/`.

Back up this folder separately to preserve your media and editing history. The top-level `footage/` and `exports/` folders are optional staging areas; browser uploads and automatic exports use the project folders above.
