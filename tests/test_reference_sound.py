import array
import copy
import json
import math
import subprocess
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aiedit import media
from aiedit.server import create_app
from aiedit.timeline import entrance_event
from test_media_and_api import recording, wait_for
from test_review_workflow import edit_body


def test_reference_sound_timing_scenarios():
    fixture = json.loads((Path(__file__).parent / "fixtures/reference_sound_cases.json").read_text())
    for case in fixture["cases"]:
        overlay = copy.deepcopy(fixture["overlay"])
        overlay.update(case.get("overlay", {}))
        overlay["entrance_sound"].update(case.get("sound", {}))
        event = entrance_event(overlay, case["kept"], case["sound_duration"])
        if case["expected"] is None:
            assert event is None, case["name"]
        else:
            assert {k: event[k] for k in ("start", "end", "source")} == pytest.approx(case["expected"]), case["name"]


@pytest.fixture
def reference_assets(tmp_path):
    image = tmp_path / "screenshot.png"
    Image.new("RGB", (40, 60), "white").save(image)
    pop = tmp_path / "generated-pop.wav"
    with wave.open(str(pop), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        samples = array.array("h", (
            round(16000 * math.sin(2 * math.pi * 1200 * i / 48000))
            if 4800 <= i < 28800 else 0
            for i in range(33600)
        ))
        output.writeframes(samples.tobytes())
    return image, pop


def import_reference_assets(client, paths):
    image, pop = paths
    visual = client.post("/api/assets/import", json={"path": str(image)}).json()
    sound = client.post("/api/assets/import", json={
        "path": str(pop), "tags": ["sound-effect", "default-reference-pop"],
    }).json()
    return visual, sound


def test_reference_creation_defaults_are_frozen_and_existing_edits_survive(
    recording, reference_assets, tmp_path,
):
    with TestClient(create_app(tmp_path / "data", assistant_session=False), base_url="http://127.0.0.1") as client:
        editor = client.app.state.editor
        visual, sound = import_reference_assets(client, reference_assets)
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        route = f"/api/projects/{p['id']}"
        # A legacy overlay remains silent even after the default is available.
        legacy = {"id": "legacy", "asset_id": visual["id"], "start": 0, "end": 1}
        response = client.put(route, json=edit_body(p, overlays=[legacy]))
        assert response.status_code == 200, response.text
        p = response.json()
        saved_legacy = copy.deepcopy(p["overlays"][0])
        overlays = p["overlays"] + [
            {"id": "ref", "asset_id": visual["id"], "start": 1, "end": 4,
             "role": "reference"},
            {"id": "title", "asset_id": visual["id"], "start": 0, "end": 2.5,
             "role": "title"},
            {"id": "graphic", "asset_id": visual["id"], "start": 1, "end": 3,
             "role": "graphic"},
            {"id": "no-pop", "asset_id": visual["id"], "start": 1, "end": 3,
             "role": "reference", "entrance_sound": None},
            {"id": "audio", "asset_id": sound["id"], "start": 0, "end": .7,
             "audio": True},
        ]
        response = client.put(route, json=edit_body(p, overlays=overlays))
        assert response.status_code == 200, response.text
        p = response.json()
        assert p["overlays"][0] == saved_legacy
        reference = p["overlays"][1]
        assert reference["entrance_sound"] == {
            "asset_id": sound["id"], "asset_in": .1, "volume": .35, "enabled": True,
        }
        assert all(not o.get("entrance_sound") for o in p["overlays"][2:])
        # An older client omitting the new fields preserves the chosen recipe.
        submitted = copy.deepcopy(p["overlays"])
        submitted[1].pop("entrance_sound")
        submitted[1].pop("role")
        response = client.put(route, json=edit_body(p, overlays=submitted))
        assert response.status_code == 200, response.text
        p = response.json()
        assert p["overlays"][1] == reference
        assert len(p["overlays"]) == 6
        # Explicit gain/off and null stay authored; repeated saves never reattach.
        p["overlays"][1]["entrance_sound"].update(volume=.2, enabled=False)
        response = client.put(route, json=edit_body(p, overlays=p["overlays"]))
        p = response.json()
        assert p["overlays"][1]["entrance_sound"]["volume"] == .2
        assert not p["overlays"][1]["entrance_sound"]["enabled"]
        p["overlays"][1]["entrance_sound"] = None
        p = client.put(route, json=edit_body(p, overlays=p["overlays"])).json()
        assert p["overlays"][1]["entrance_sound"] is None


def test_reference_sound_validation_and_default_failures_are_atomic(
    recording, reference_assets, tmp_path,
):
    with TestClient(create_app(tmp_path / "data", assistant_session=False), base_url="http://127.0.0.1") as client:
        editor = client.app.state.editor
        image, pop = reference_assets
        visual = editor.library.import_file(image)
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        route = f"/api/projects/{p['id']}"
        reference = {"id": "ref", "asset_id": visual["id"], "start": 1, "end": 4,
                     "role": "reference"}
        assert client.get("/api/assets/reference-sound").json() is None
        missing = client.put(route, json=edit_body(p, overlays=[reference]))
        assert missing.status_code == 400 and "pop" in missing.text.lower()
        assert editor.repo.load(p["id"])["revision"] == p["revision"]
        sound = editor.library.import_file(pop, tags=["default-reference-pop"])
        configured = client.get("/api/assets/reference-sound").json()
        assert configured["asset_id"] == sound["id"]
        invalid = dict(reference, entrance_sound=dict(configured, asset_id=visual["id"]))
        assert client.put(route, json=edit_body(p, overlays=[invalid])).status_code == 400
        invalid = dict(reference, entrance_sound=dict(configured, asset_in=100))
        assert client.put(route, json=edit_body(p, overlays=[invalid])).status_code == 400
        invalid = dict(reference, role="title", entrance_sound=configured)
        assert client.put(route, json=edit_body(p, overlays=[invalid])).status_code == 400
        invalid = dict(reference, asset_id=sound["id"])
        assert client.put(route, json=edit_body(p, overlays=[invalid])).status_code == 400
        assert client.put(route, json=edit_body(p, overlays=[reference, reference])).status_code == 400
        stale = edit_body(p, overlays=[reference]); stale["base_revision"] -= 1
        assert client.put(route, json=stale).status_code == 409
        editor.library.import_file(pop, tags=["default-reference-pop"])
        duplicate = client.put(route, json=edit_body(p, overlays=[reference]))
        assert duplicate.status_code == 400 and "one" in duplicate.text.lower()
        assert editor.repo.load(p["id"])["revision"] == p["revision"]


def test_pop_is_encoded_once_continuously_across_a_speech_cut(reference_assets, tmp_path):
    source = tmp_path / "silent.mp4"
    media.run([
        media.binary("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
        "color=black:size=180x320:rate=24:duration=4", "-f", "lavfi", "-i",
        "anullsrc=r=48000:cl=mono", "-t", "4", "-c:v", "libx264",
        "-preset", "ultrafast", "-threads", "2", "-c:a", "aac", str(source),
    ])
    with TestClient(create_app(tmp_path / "data", assistant_session=False), base_url="http://127.0.0.1") as client:
        editor = client.app.state.editor
        visual, sound = import_reference_assets(client, reference_assets)
        p = wait_for(editor, editor.create(source, source.name)["id"])
        route = f"/api/projects/{p['id']}"
        response = client.put(route, json=edit_body(p,
            cuts=[{"id": "gap", "start": 1.4, "end": 2.2, "enabled": True, "kind": "manual"}],
            overlays=[{"id": "ref", "asset_id": visual["id"], "start": 1.2,
                       "end": 3.4, "role": "reference"}],
        ))
        assert response.status_code == 200, response.text
        assert client.post(route + "/export", json={}).status_code == 200
        p = wait_for(editor, p["id"])
        exported = p["exports"][-1]
        assert exported["edit_state"]["overlays"][0]["entrance_sound"]["asset_id"] == sound["id"]
        assert {a["id"] for a in exported["assets"]} == {sound["id"], visual["id"]}
        path = editor.repo.directory(p["id"]) / "exports" / exported["file"]
        raw = subprocess.run([
            media.binary("ffmpeg"), "-v", "error", "-i", str(path), "-vn",
            "-ar", "16000", "-ac", "1", "-f", "f32le", "-",
        ], capture_output=True, check=True).stdout
        samples = array.array("f"); samples.frombytes(raw)
        def rms(start, end):
            values = samples[round(start * 16000):round(end * 16000)]
            return math.sqrt(sum(v * v for v in values) / len(values))
        assert rms(1.05, 1.15) < .001
        assert rms(1.25, 1.35) > .04
        assert rms(1.5, 1.6) > .04  # Tail survives the source-time jump.
        assert rms(1.85, 2.1) < .001  # No restart at the intervening cut.
