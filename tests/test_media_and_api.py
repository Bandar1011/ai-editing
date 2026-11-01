import hashlib
import json
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


@pytest.mark.parametrize("transfer", ["arib-std-b67", "smpte2084"])
def test_hdr_preview_and_export_use_sdr_color_without_changing_original(tmp_path, transfer):
    source = tmp_path / "hdr.mkv"
    media.run([
        media.binary("ffmpeg"), "-v", "error", "-n", "-f", "lavfi", "-i",
        "testsrc2=size=180x320:rate=30:duration=1",
        "-vf", f"setparams=color_primaries=bt2020:color_trc={transfer}:colorspace=bt2020nc",
        "-c:v", "libx264",
        "-preset", "ultrafast", "-threads", "2",
        "-pix_fmt", "yuv420p10le", "-color_primaries", "bt2020",
        "-color_trc", transfer, "-colorspace", "bt2020nc", str(source),
    ])
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1") as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(source, source.name)["id"])
        route = f"/api/projects/{p['id']}"
        assert client.post(route + "/export", json={"format": "vertical"}).status_code == 200
        p = wait_for(editor, p["id"])
        folder = editor.repo.directory(p["id"])
        for output in (folder / "working/preview.mp4", folder / "exports" / p["exports"][-1]["file"]):
            stream = json.loads(media.run([
                media.binary("ffprobe"), "-v", "error", "-select_streams", "v:0",
                "-show_streams", "-of", "json", str(output),
            ]))["streams"][0]
            assert stream["color_transfer"] == "bt709"
            assert stream["color_primaries"] == "bt709"
            assert stream["color_space"] == "bt709"
            assert stream["pix_fmt"] == "yuv420p"
            media.run([media.binary("ffmpeg"), "-v", "error", "-i", str(output), "-f", "null", "-"])
        assert hashlib.sha256((folder / p["source_file"]).read_bytes()).hexdigest() == original_hash
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


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


def test_vertical_export_and_persistent_nondestructive_splits(recording, tmp_path):
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        route = f"/api/projects/{p['id']}"
        body = {
            k: p[k]
            for k in (
                "name",
                "cuts",
                "subtitles",
                "subtitle_style",
                "brief",
                "references",
            )
        }
        body.update(base_revision=p["revision"], split_points=[3, 1, 3])
        saved = client.put(route, json=body)
        assert saved.status_code == 200, saved.text
        p = saved.json()
        assert p["split_points"] == [1, 3]
        assert p["cuts"] == []
        assert client.get(route).json()["split_points"] == [1, 3]
        body.update(base_revision=p["revision"], split_points=None)
        p = client.put(route, json=body).json()
        assert p["split_points"] == [1, 3]
        del body["split_points"]
        body.update(base_revision=p["revision"])
        p = client.put(route, json=body).json()
        assert p["split_points"] == [1, 3]
        body.update(base_revision=p["revision"], split_points=[6])
        assert client.put(route, json=body).status_code == 400
        assert (
            client.post(route + "/export", json={"format": "vertical"}).status_code
            == 200
        )
        p = wait_for(editor, p["id"])
        result = p["exports"][-1]
        actual = media.probe(
            editor.repo.directory(p["id"]) / "exports" / result["file"]
        )
        assert actual["width"] * 16 == actual["height"] * 9
        assert actual["fps"] == 24 and actual["has_audio"]
        assert abs(actual["duration"] - 5) < 0.09
        assert result["edit_state"]["split_points"] == [1, 3]
        assert result["render_settings"]["format"] == "vertical"
