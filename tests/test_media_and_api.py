import hashlib
import time

import pytest
from fastapi.testclient import TestClient

from aiedit import media
from aiedit.server import create_app
from aiedit.timeline import kept_ranges


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "a video with spaces.mp4"
    media.run(
        [
            media.binary("ffmpeg"),
            "-v",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=5",
            "-af",
            "volume=0:enable='between(t,1,2.2)'",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(path),
        ]
    )
    return path


def wait_for(editor, identifier):
    deadline = time.monotonic() + 30
    while identifier in editor.active and time.monotonic() < deadline:
        time.sleep(0.05)
    assert identifier not in editor.active
    p = editor.repo.load(identifier)
    assert all(j["status"] == "done" for j in p["jobs"].values()), p["jobs"]
    return p


def test_real_silence_detection_and_captioned_export(recording, tmp_path):
    info = media.probe(recording)
    cuts = media.detect_silence(recording, info["duration"], -35, 0.5, 0.12)
    assert len(cuts) == 1
    assert 1.08 < cuts[0]["start"] < 1.18
    assert 2.03 < cuts[0]["end"] < 2.13
    p = {
        "media": info,
        "cuts": cuts,
        "subtitles": [{"start": 2.3, "end": 4, "text": "Export verification"}],
        "subtitle_style": {"font_size": 48, "position": "bottom"},
    }
    output = media.export_video(p, recording, tmp_path / "export folder", True)
    actual = media.probe(output)
    expected = sum(b - a for a, b in kept_ranges(info["duration"], cuts))
    assert abs(actual["duration"] - expected) < 0.09
    assert (actual["width"], actual["height"]) == (320, 180)
    assert actual["has_audio"]
    assert actual["fps"] == 24
    assert "Export verification" in output.with_suffix(".ass").read_text()
    media.run(
        [media.binary("ffmpeg"), "-v", "error", "-i", str(output), "-f", "null", "-"]
    )


def test_upload_preview_ranges_and_conflict_protection(recording, tmp_path):
    app = create_app(tmp_path / "data")
    original_hash = hashlib.sha256(recording.read_bytes()).hexdigest()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        with recording.open("rb") as handle:
            response = client.post(
                "/api/projects/upload",
                files={"file": (recording.name, handle, "video/mp4")},
            )
        assert response.status_code == 200, response.text
        p = wait_for(app.state.editor, response.json()["id"])
        assert p["media_ready"] and p["waveform_ready"]
        route = f"/api/projects/{p['id']}"
        playback = client.get(route + "/media", headers={"Range": "bytes=0-99"})
        assert playback.status_code == 206
        assert len(playback.content) == 100
        edit = {
            key: p[key]
            for key in (
                "name",
                "cuts",
                "subtitles",
                "subtitle_style",
                "brief",
                "references",
            )
        }
        edit.update(
            base_revision=p["revision"],
            cuts=[
                {"id": "cut1", "start": 1, "end": 2, "kind": "manual", "enabled": True}
            ],
        )
        saved = client.put(route, json=edit)
        assert saved.status_code == 200
        assert client.put(route, json=edit).status_code == 409
        edit["base_revision"] = saved.json()["revision"]
        edit["cuts"][0]["start"] = -1
        assert client.put(route, json=edit).status_code == 400
        assert (
            client.post(
                "/api/projects/import",
                json={"path": str(recording)},
                headers={"Origin": "https://unrelated.example"},
            ).status_code
            == 403
        )
        assert client.get("/api/projects/invalid").status_code == 404
        exported = client.post(route + "/export", json={"burn_subtitles": False})
        assert exported.status_code == 200
        final = wait_for(app.state.editor, p["id"])
        result = final["exports"][-1]
        assert result["edit_state"]["cuts"] == saved.json()["cuts"]
        download = client.get(route + "/exports/" + result["file"])
        assert (
            download.status_code == 200
            and download.headers["content-type"] == "video/mp4"
        )
    assert hashlib.sha256(recording.read_bytes()).hexdigest() == original_hash


def test_rerunning_detection_preserves_manually_restored_audio(recording, tmp_path):
    app = create_app(tmp_path / "data")
    editor = app.state.editor
    try:
        p = editor.create(recording, recording.name)
        p = wait_for(editor, p["id"])
        manual = {
            "id": "restore",
            "start": 1.4,
            "end": 1.8,
            "kind": "manual",
            "enabled": False,
        }
        editor.repo.change(p["id"], lambda p: p.update(cuts=[manual]))
        from aiedit.server import SilenceOptions

        editor.silence(p["id"], SilenceOptions())
        result = editor.repo.load(p["id"])
        assert manual in result["cuts"]
        assert all(
            c["end"] <= 1.4 or c["start"] >= 1.8 for c in result["cuts"] if c["enabled"]
        )
        assert list(
            (editor.repo.directory(p["id"]) / "history").glob("revision-*.json")
        )
    finally:
        editor.pool.shutdown(wait=True)
