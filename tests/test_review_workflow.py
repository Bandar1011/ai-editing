import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from aiedit import media
from aiedit.server import create_app
from test_media_and_api import recording, wait_for


def edit_body(p, **updates):
    body = {
        key: copy.deepcopy(p[key])
        for key in (
            "name",
            "cuts",
            "subtitles",
            "subtitle_style",
            "brief",
            "references",
        )
    }
    return dict(body, base_revision=p["revision"], **updates)


def test_versions_preserve_captions_ranges_provenance_and_feedback(recording, tmp_path):
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(
            editor,
            client.post("/api/projects/import", json={"path": str(recording)}).json()[
                "id"
            ],
        )
        route = f"/api/projects/{p['id']}"
        body = edit_body(p)
        body.update(
            cuts=[
                {"id": "cut", "start": 1, "end": 2, "enabled": True, "kind": "manual"}
            ],
            subtitles=[
                {"id": "cue", "start": 2.5, "end": 4, "text": "Original wording"}
            ],
            brief={
                "goal": "Explain one clear idea",
                "target": "Keep native format",
                "rights": "Generated test media",
            },
            references=[
                {
                    "title": "FFmpeg",
                    "url": "https://ffmpeg.org",
                    "purpose": "Generated test footage",
                }
            ],
        )
        assert client.put(route, json=body).status_code == 200
        assert (
            client.post(
                route + "/export",
                json={"burn_subtitles": False, "label": "Story review"},
            ).status_code
            == 200
        )
        p = wait_for(editor, p["id"])
        first = p["exports"][0]
        encoded = editor.repo.directory(p["id"]) / "exports" / first["file"]
        assert first["duration"] == media.probe(encoded)["duration"]
        first_srt = client.get(route + "/exports/" + first["captions_file"]).text
        manifest_bytes = client.get(
            route + "/exports/" + first["manifest_file"]
        ).content
        manifest = json.loads(manifest_bytes)
        assert manifest["label"] == "Story review" and not manifest["captioned"]
        assert manifest["source_ranges"] == [
            {"start": 0, "end": 1},
            {"start": 2, "end": 5},
        ]
        assert "00:00:01,500 --> 00:00:03,000" in first_srt
        assert manifest["references"] == body["references"]
        assert manifest["brief"] == body["brief"]
        assert (
            manifest["source_sha256"]
            == hashlib.sha256(recording.read_bytes()).hexdigest()
        )
        video = client.get(route + "/exports/" + first["file"]).content
        assert hashlib.sha256(video).hexdigest() == manifest["sha256"]
        note = {
            "export_file": first["file"],
            "time": 1.5,
            "change": "Increase caption size",
            "reason": "Readability on phones",
            "scope": "reusable",
        }
        response = client.post(route + "/reviews", json=note)
        assert response.status_code == 200
        p = response.json()
        note_id = p["reviews"][0]["id"]
        assert (
            client.post(route + "/reviews", json=dict(note, time=100)).status_code
            == 400
        )
        assert (
            client.post(
                route + "/reviews", json=dict(note, export_file="missing.mp4")
            ).status_code
            == 404
        )
        body = edit_body(p)
        body["subtitles"][0]["text"] = "Corrected wording"
        body["subtitle_style"]["font_size"] = 64
        assert client.put(route, json=body).status_code == 200
        client.post(route + "/export", json={"label": "Caption review"})
        p = wait_for(editor, p["id"])
        second = p["exports"][1]
        assert second["version"] == 2 and second["captioned"]
        assert (
            client.get(route + "/exports/" + first["manifest_file"]).content
            == manifest_bytes
        )
        assert (
            client.get(route + "/exports/" + first["captions_file"]).text == first_srt
        )
        assert (
            "Corrected wording"
            in client.get(route + "/exports/" + second["captions_file"]).text
        )
        assert (
            client.patch(
                route + "/reviews/" + note_id, json={"resolved_in": first["file"]}
            ).status_code
            == 400
        )
        resolved = client.patch(
            route + "/reviews/" + note_id, json={"resolved_in": second["file"]}
        )
        assert resolved.json()["reviews"][0]["resolved_in"] == second["file"]
        matches = client.get(
            "/api/history", params={"q": "caption phones", "reusable": "true"}
        ).json()
        assert len(matches) == 1 and matches[0]["project_id"] == p["id"]
        client.post(
            route + "/reviews",
            json=dict(note, change="One-off crop", scope="this_edit"),
        )
        assert len(client.get("/api/history", params={"reusable": "true"}).json()) == 1
        assert len(client.get("/api/history").json()) == 2
        assert client.get(route + "/exports/project.json").status_code == 404
        assert (
            editor.repo.directory(p["id"]) / p["source_file"]
        ).parent.name == "source"


def test_source_transcript_survives_caption_edits(recording, tmp_path, monkeypatch):
    cues = [{"id": "original", "start": 0.5, "end": 2, "text": "Words actually spoken"}]
    monkeypatch.setattr(media, "transcribe", lambda *args: copy.deepcopy(cues))
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        editor.transcribe(p["id"], "en")
        p = editor.repo.load(p["id"])
        body = edit_body(p)
        body["subtitles"][0]["text"] = "Human caption correction"
        route = f"/api/projects/{p['id']}"
        assert client.put(route, json=body).status_code == 200
        assert client.get(route + "/transcript.json").json()["cues"] == cues
        assert "Words actually spoken" in client.get(route + "/transcript.srt").text
        assert "Human caption correction" in client.get(route + "/subtitles.srt").text


def test_transcription_cannot_replace_concurrent_human_correction(
    recording, tmp_path, monkeypatch
):
    editor = create_app(tmp_path / "data").state.editor
    try:
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        manual = [{"id": "human", "start": 0.2, "end": 1, "text": "Keep my correction"}]

        def transcribe(*args):
            editor.repo.change(
                p["id"], lambda project: project.update(subtitles=manual)
            )
            return [
                {"id": "generated", "start": 0.2, "end": 1, "text": "Generated text"}
            ]

        monkeypatch.setattr(media, "transcribe", transcribe)
        with pytest.raises(ValueError, match="preserved"):
            editor.transcribe(p["id"], "en")
        assert editor.repo.load(p["id"])["subtitles"] == manual
    finally:
        editor.pool.shutdown(wait=True)


def test_scriptable_ids_and_reference_urls_are_rejected(recording, tmp_path):
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        body = edit_body(p)
        body["subtitles"] = [
            {"id": '"><img onerror=alert(1)>', "start": 0, "end": 1, "text": "caption"}
        ]
        route = f"/api/projects/{p['id']}"
        assert client.put(route, json=body).status_code == 422
        body["subtitles"] = []
        body["references"] = [
            {"title": "Unsafe", "url": "javascript:alert(1)", "purpose": ""}
        ]
        assert client.put(route, json=body).status_code == 400


def test_portrait_clip_without_audio_preserves_native_format(tmp_path):
    source = tmp_path / "portrait.mp4"
    media.run(
        [
            media.binary("ffmpeg"),
            "-v",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=180x320:rate=25:duration=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(source),
        ]
    )
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(source, source.name)["id"])
        route = f"/api/projects/{p['id']}"
        assert p["media_ready"] and not p["waveform_ready"]
        assert client.post(route + "/transcribe", json={}).status_code == 400
        assert client.post(route + "/silence", json={}).status_code == 400
        client.post(route + "/export", json={})
        p = wait_for(editor, p["id"])
        output = editor.repo.directory(p["id"]) / "exports" / p["exports"][0]["file"]
        info = media.probe(output)
        assert (info["width"], info["height"], info["fps"], info["has_audio"]) == (
            180,
            320,
            25,
            False,
        )
