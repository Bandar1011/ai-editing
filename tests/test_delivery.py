import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from aiedit import delivery
from aiedit.server import create_app
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
