import hashlib
import json
import time
import threading
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from aiedit import delivery
from aiedit.assistant import Assistant
from aiedit.server import ExportOptions, create_app
from test_media_and_api import recording, wait_for  # noqa: F401


@pytest.fixture
def exported_client(tmp_path, recording, monkeypatch):
    with TestClient(
        create_app(tmp_path / "data", assistant_session=False),
        base_url="http://127.0.0.1",
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        client.post(f"/api/projects/{p['id']}/export", json={"format": "vertical"})
        p = wait_for(editor, p["id"])
        opened = []
        monkeypatch.setattr(delivery.platform, "system", lambda: "Darwin")

        def native_boundary(self, identifier, options):
            self.validate(identifier, options.file, checksum=True)
            opened.append((identifier, options.file))
            self.requests[(identifier, options.request_id)].update(
                status="choosing", message="Choose your iPhone"
            )

        monkeypatch.setattr(delivery.AirDrop, "open", native_boundary)
        yield client, editor, p, opened


def body(p, **changes):
    return dict(
        base_revision=p["revision"],
        file=p["exports"][-1]["file"],
        request_id="a" * 32,
        **changes,
    )


def test_airdrop_pins_current_export_and_duplicate_requests_do_not_open_twice(
    exported_client,
):
    client, editor, p, opened = exported_client
    route = f"/api/projects/{p['id']}/airdrop"
    payload = body(p)
    response = client.post(route, json=payload)
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 5
    while not opened and time.monotonic() < deadline:
        time.sleep(0.01)
    assert opened == [(p["id"], payload["file"])]
    assert client.post(route, json=payload).status_code == 200
    assert len(opened) == 1
    status = client.get(route + "/" + payload["request_id"]).json()
    assert status["file"] == payload["file"] and status["status"] == "choosing"
    assert (
        client.get(
            "/api/projects/000000000000/airdrop/" + payload["request_id"]
        ).status_code
        == 404
    )
    assert (
        client.post(route, json=dict(payload, file="0000000000.mp4")).status_code == 409
    )
    assert (
        client.post(route, json=dict(payload, request_id="b" * 32)).status_code == 409
    )
    assert (
        client.post(
            route, json=payload, headers={"Origin": "https://other.example"}
        ).status_code
        == 403
    )


def test_stale_or_changed_edit_cannot_be_shared(exported_client):
    client, editor, p, opened = exported_client
    route = f"/api/projects/{p['id']}/airdrop"
    changed = editor.repo.change(
        p["id"],
        lambda current: current["cuts"].append(
            {"id": "manual", "start": 1, "end": 2, "kind": "manual", "enabled": True}
        ),
    )
    assert client.post(route, json=body(p)).status_code == 409
    result = client.post(route, json=body(changed))
    assert result.status_code == 409 and "current edit" in result.text
    assert opened == []


def test_modified_export_file_is_rejected_by_checksum(exported_client):
    client, editor, p, _ = exported_client
    export = p["exports"][-1]
    path = editor.repo.directory(p["id"]) / "exports" / export["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == export["sha256"]
    path.write_bytes(b"changed generated export")
    with pytest.raises(ValueError, match="export file changed"):
        client.app.state.airdrop.validate(p["id"], export["file"], checksum=True)


def test_export_revision_guard_rejects_stale_request_before_starting(exported_client):
    client, editor, p, _ = exported_client
    route = f"/api/projects/{p['id']}/export"
    changed = editor.repo.change(
        p["id"], lambda current: current["brief"].update(goal="New edit")
    )
    response = client.post(
        route, json={"format": "vertical", "base_revision": p["revision"]}
    )
    assert response.status_code == 409
    assert editor.repo.load(p["id"])["jobs"] == changed["jobs"]
    assert len(editor.repo.load(p["id"])["exports"]) == 1


def test_native_result_is_reported_without_claiming_phone_receipt(exported_client):
    client, _, p, opened = exported_client
    route = f"/api/projects/{p['id']}/airdrop"
    client.post(route, json=body(p))
    deadline = time.monotonic() + 5
    while not opened and time.monotonic() < deadline:
        time.sleep(0.01)
    entry = client.app.state.airdrop.requests[(p["id"], "a" * 32)]
    entry["state_file"].write_text(
        json.dumps({"status": "cancelled", "message": "AirDrop cancelled"})
    )
    status = client.get(route + "/" + "a" * 32).json()
    assert status["status"] == "cancelled"
    assert status["message"] == "AirDrop cancelled"


def test_recorded_preview_has_real_stage_completions(exported_client):
    _, _, p, _ = exported_client
    preview = p["jobs"]["preview"]
    assert preview["stage_status"] == "done"
    assert {s["stage"] for s in preview["stages"] if s["status"] == "done"} == {
        "preview",
        "waveform",
    }


def test_export_does_not_deadlock_against_ai_start(exported_client, monkeypatch):
    client, editor, p, _ = exported_client
    editor.assistant = Assistant(editor, session=lambda run: {"summary": "Unused", "review_notes": []})
    original_lock = editor.repo.lock
    original_running = editor.assistant.is_running
    ai_has_lock, export_check = threading.Event(), threading.Event()
    errors = []

    @contextmanager
    def controlled_lock(identifier):
        lock = original_lock(identifier)
        if threading.current_thread().name == "ai-start":
            ai_has_lock.set()
            assert export_check.wait(3)
            if not lock.acquire(timeout=1):
                raise TimeoutError("AI start could not acquire the project lock during export")
        else:
            lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def checking(identifier):
        export_check.set()
        assert ai_has_lock.wait(3)
        return original_running(identifier)

    monkeypatch.setattr(editor.repo, "lock", controlled_lock)
    monkeypatch.setattr(editor.assistant, "is_running", checking)
    endpoint = next(r.endpoint for r in client.app.routes if getattr(r, "path", "") == "/api/projects/{identifier}/export")

    def invoke(function):
        try:
            function()
        except Exception as error:
            errors.append(error)

    ai = threading.Thread(name="ai-start", target=lambda: invoke(lambda: editor.assistant.start(p["id"], "http://127.0.0.1/tools")), daemon=True)
    export = threading.Thread(name="export-request", target=lambda: invoke(lambda: endpoint(p["id"], ExportOptions(base_revision=p["revision"], format="vertical"))), daemon=True)
    ai.start()
    assert ai_has_lock.wait(3)
    export.start()
    ai.join(4)
    export.join(4)
    assert not ai.is_alive() and not export.is_alive()
    assert not errors, [str(error) for error in errors]
    wait_for(editor, p["id"])
