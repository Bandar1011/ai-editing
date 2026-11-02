import hashlib

from fastapi.testclient import TestClient

from aiedit import media
from aiedit.server import create_app
from test_media_and_api import recording, wait_for  # noqa: F401
from test_review_workflow import edit_body


def export(client, editor, identifier, **options):
    response = client.post(f"/api/projects/{identifier}/export", json=options)
    assert response.status_code == 200, response.text
    return wait_for(editor, identifier)["exports"][-1]


def test_identical_export_reuses_bytes_with_independent_snapshot_and_captions(
    recording, tmp_path, monkeypatch
):
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        first = export(client, editor, p["id"], burn_subtitles=False, label="First")
        assert not first["render_cache"]["hit"]
        original = media.export_video

        def unexpected(*args, **kwargs):
            raise AssertionError("The identical edit must not encode again")

        monkeypatch.setattr(media, "export_video", unexpected)
        # Change only editable caption text that is not burned, plus review metadata.
        p = editor.repo.load(p["id"])
        body = edit_body(p)
        body["subtitles"] = [
            {"id": "caption", "start": 0.2, "end": 1, "text": "New sidecar text"}
        ]
        assert client.put(f"/api/projects/{p['id']}", json=body).status_code == 200
        second = export(client, editor, p["id"], burn_subtitles=False, label="Second")
        assert second["render_cache"]["hit"]
        assert second["render_cache"]["reused_from"] == first["file"]
        assert second["file"] != first["file"]
        assert second["sha256"] == first["sha256"]
        folder = editor.repo.directory(p["id"]) / "exports"
        assert (folder / first["file"]).stat().st_ino != (
            folder / second["file"]
        ).stat().st_ino
        assert (folder / first["captions_file"]).read_text() == "\n"
        assert "New sidecar text" in (folder / second["captions_file"]).read_text()
        assert first["edit_state"]["subtitles"] == []
        assert second["edit_state"]["subtitles"][0]["text"] == "New sidecar text"
        assert (
            client.get(
                f"/api/projects/{p['id']}/exports/{first['manifest_file']}"
            ).json()["label"]
            == "First"
        )
        monkeypatch.setattr(media, "export_video", original)


def test_burned_caption_and_corrupt_candidate_require_new_encode(
    recording, tmp_path, monkeypatch
):
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        body = edit_body(p)
        body["subtitles"] = [
            {"id": "caption", "start": 0.2, "end": 1, "text": "First text"}
        ]
        assert client.put(f"/api/projects/{p['id']}", json=body).status_code == 200
        calls = []
        original = media.export_video

        def render(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(media, "export_video", render)
        first = export(client, editor, p["id"])
        p = editor.repo.load(p["id"])
        body = edit_body(p)
        body["subtitles"][0]["text"] = "Changed text"
        assert client.put(f"/api/projects/{p['id']}", json=body).status_code == 200
        second = export(client, editor, p["id"])
        assert len(calls) == 2 and not second["render_cache"]["hit"]
        assert first["sha256"] != second["sha256"]
        folder = editor.repo.directory(p["id"]) / "exports"
        (folder / second["file"]).write_bytes(b"corrupted candidate")
        third = export(client, editor, p["id"])
        assert len(calls) == 3 and not third["render_cache"]["hit"]
        assert (
            hashlib.sha256((folder / third["file"]).read_bytes()).hexdigest()
            == third["sha256"]
        )
