import threading
import time

import pytest
from fastapi.testclient import TestClient

from aiedit import media
from aiedit.server import create_app
from test_media_and_api import recording, wait_for  # noqa: F401
from test_production import words
from test_review_workflow import edit_body


@pytest.fixture
def prepared_client(recording, tmp_path, monkeypatch):
    """Real PCM/silence processing; replace only the optional recognizer boundary."""
    calls = []
    original_binary = media.binary
    executable = tmp_path / "recognizer"
    executable.write_bytes(b"test recognizer v1")
    monkeypatch.setattr(
        media,
        "binary",
        lambda name: (
            str(executable) if name == "whisper-cli" else original_binary(name)
        ),
    )
    from aiedit import analysis

    original_identity = analysis.tool_identity
    monkeypatch.setattr(
        analysis,
        "tool_identity",
        lambda name: (
            analysis.file_identity(executable)
            if name == "whisper-cli"
            else original_identity(name)
        ),
    )

    def recognize(wav, directory, model, language, duration):
        media.validate_speech_audio(wav)
        calls.append(language)
        source_words = words("Here is the app.", 0, 0.98) + words(
            "Here is the app.", 3, 0.7
        )
        return {
            "language": language,
            "words": source_words,
            "cues": [
                {
                    "id": "source",
                    "start": 0,
                    "end": 4.2,
                    "text": "Here is the app. Here is the app.",
                }
            ],
        }

    monkeypatch.setattr(media, "transcribe_audio", recognize)
    with TestClient(
        create_app(tmp_path / "data", assistant_session=False), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        editor.model.parent.mkdir(exist_ok=True)
        editor.model.write_bytes(b"test model v1")
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        yield client, editor, p, calls


def prepare_video(client, editor, p, **options):
    response = client.post(f"/api/projects/{p['id']}/prepare", json=options)
    assert response.status_code == 200, response.text
    return wait_for(editor, p["id"])


def test_repeated_preparation_and_grouping_reuse_raw_analysis(
    prepared_client, monkeypatch
):
    client, editor, p, calls = prepared_client
    p = prepare_video(client, editor, p, language="en")
    original_edit = edit_body(p)
    assert calls == ["en"]
    assert p["retakes"][0]["selected"] == 0

    def unexpected(*args, **kwargs):
        pytest.fail("A warm preparation must not start another decoder or recognizer")

    monkeypatch.setattr(media, "run", unexpected)
    original_run = media.subprocess.run

    def guarded(command, *args, **kwargs):
        from pathlib import Path

        if Path(command[0]).name in {
            "ffmpeg",
            "whisper-cli",
            "whisper-vad-speech-segments",
        }:
            unexpected()
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(media.subprocess, "run", guarded)
    p = prepare_video(client, editor, p, language="en")
    assert {k: v for k, v in edit_body(p).items() if k != "base_revision"} == {
        k: v for k, v in original_edit.items() if k != "base_revision"
    }
    p = prepare_video(client, editor, p, language="en", max_words=1)
    assert all(len(c["text"].split()) == 1 for c in p["subtitles"])
    assert calls == ["en"]
    assert all(stage["reused"] for stage in p["jobs"]["prepare"]["stages"])


def test_authored_caption_and_restored_range_survive_identical_prepare(prepared_client):
    client, editor, p, calls = prepared_client
    p = prepare_video(client, editor, p, language="en")
    body = edit_body(p)
    body["subtitles"][0]["text"] = "Human correction"
    body["cuts"].append(
        {"id": "restore", "start": 3, "end": 4.2, "enabled": False, "kind": "manual"}
    )
    saved = client.put(f"/api/projects/{p['id']}", json=body)
    assert saved.status_code == 200, saved.text
    p = prepare_video(client, editor, saved.json(), language="en")
    assert p["subtitles"] == body["subtitles"]
    assert body["cuts"][-1] in p["cuts"]
    assert calls == ["en"]
    response = client.post(
        f"/api/projects/{p['id']}/prepare", json={"language": "en", "max_words": 1}
    )
    assert response.status_code == 200
    deadline = time.monotonic() + 10
    while p["id"] in editor.active and time.monotonic() < deadline:
        time.sleep(0.01)
    p = editor.repo.load(p["id"])
    assert p["jobs"]["prepare"]["status"] == "error"
    assert p["subtitles"] == body["subtitles"]
    assert body["cuts"][-1] in p["cuts"]


def test_language_model_and_corrupt_transcript_invalidate_recognition(prepared_client):
    client, editor, p, calls = prepared_client
    p = prepare_video(client, editor, p, language="en")
    prepare_video(client, editor, p, language="ar")
    assert calls == ["en", "ar"]
    editor.model.write_bytes(b"test model v2")
    p = prepare_video(client, editor, p, language="ar")
    assert calls == ["en", "ar", "ar"]
    folder = editor.repo.directory(p["id"]) / "working/analysis"
    for artifact in folder.glob("transcription-*.json"):
        artifact.write_text("{incomplete")
    prepare_video(client, editor, p, language="ar")
    assert calls == ["en", "ar", "ar", "ar"]


def test_interrupted_analysis_reuses_completed_transcription_without_partial_edits(
    prepared_client, monkeypatch
):
    client, editor, p, calls = prepared_client
    original = media.detect_silence
    monkeypatch.setattr(
        media,
        "detect_silence",
        lambda *args: (_ for _ in ()).throw(RuntimeError("detector failed")),
    )
    response = client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    assert response.status_code == 200
    deadline = time.monotonic() + 10
    while p["id"] in editor.active and time.monotonic() < deadline:
        time.sleep(0.01)
    failed = editor.repo.load(p["id"])
    assert failed["jobs"]["prepare"]["status"] == "error"
    assert failed["subtitles"] == p["subtitles"] == []
    assert failed["cuts"] == p["cuts"] == []
    assert calls == ["en"]
    monkeypatch.setattr(media, "detect_silence", original)
    result = prepare_video(client, editor, p, language="en")
    assert calls == ["en"]
    assert result["subtitles"]


def test_concurrent_correction_is_not_overwritten_by_preparation(
    prepared_client, monkeypatch
):
    client, editor, p, _ = prepared_client
    recognize = media.transcribe_audio
    manual = [{"id": "human", "start": 0.2, "end": 1, "text": "Keep this"}]

    def concurrent(*args):
        result = recognize(*args)
        editor.repo.change(
            p["id"],
            lambda current: current.update(subtitles=manual, captions_authored=True),
        )
        return result

    monkeypatch.setattr(media, "transcribe_audio", concurrent)
    assert (
        client.post(
            f"/api/projects/{p['id']}/prepare", json={"language": "en"}
        ).status_code
        == 200
    )
    deadline = time.monotonic() + 10
    while p["id"] in editor.active and time.monotonic() < deadline:
        time.sleep(0.01)
    result = editor.repo.load(p["id"])
    assert result["jobs"]["prepare"]["status"] == "error"
    assert result["subtitles"] == manual
    assert result["cuts"] == []


def test_prepare_queues_once_behind_preview_and_records_actual_start(
    prepared_client, monkeypatch, recording
):
    client, editor, _, calls = prepared_client
    entered, release = threading.Event(), threading.Event()
    original = editor.preview

    def preview(identifier):
        entered.set()
        assert release.wait(10)
        original(identifier)

    monkeypatch.setattr(editor, "preview", preview)
    created = editor.create(recording, recording.name)
    try:
        assert entered.wait(5)
        route = f"/api/projects/{created['id']}/prepare"
        first = client.post(route, json={"language": "en"})
        assert first.status_code == 200, first.text
        job = first.json()["jobs"]["prepare"]
        assert job["status"] == "queued" and job["started_at"] is None
        duplicate = client.post(route, json={"language": "en"})
        assert duplicate.json()["jobs"]["prepare"]["id"] == job["id"]
        assert client.post(route, json={"language": "ar"}).status_code == 409
        assert (
            client.post(f"/api/projects/{created['id']}/export", json={}).status_code
            == 409
        )
    finally:
        release.set()
    result = wait_for(editor, created["id"])
    job = result["jobs"]["prepare"]
    assert job["started_at"] >= result["jobs"]["preview"]["finished_at"]
    assert job["queue_seconds"] > 0
    assert job["seconds"] > 0
    assert calls == ["en"]


def test_pcm_quality_matches_known_clipped_samples(tmp_path):
    import array
    import sys
    import wave

    values = array.array("h", [0] * 16000 + [32767] * 8000 + [0] * 8000)
    if sys.byteorder != "little":
        values.byteswap()
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(values.tobytes())
    assert media.pcm_audio_quality(path, 0, 1)["clipped_fraction"] == 0
    assert media.pcm_audio_quality(path, 1, 2)["clipped_fraction"] == 0.5


def test_context_is_bounded_and_status_omits_export_snapshots(prepared_client):
    client, editor, p, _ = prepared_client
    p = prepare_video(client, editor, p, language="en")
    editor.repo.change(
        p["id"],
        lambda p: p["exports"].append(
            {"file": "candidate.mp4", "edit_state": {"large": "x" * 10000}}
        ),
    )
    route = f"/api/projects/{p['id']}"
    status = client.get(route + "/status")
    full = client.get(route)
    context = client.get(route + "/context", params={"start": 0.5, "end": 2}).json()
    assert len(status.content) < len(full.content) / 2
    assert "exports" not in status.json()
    assert context["window"] == {"start": 0.5, "end": 2, "next_start": 2}
    assert context["source_words"] and context["captions"]
    assert all(w["start"] < 2 and w["end"] > 0.5 for w in context["source_words"])
    assert "source_file" not in context and "exports" not in context
    assert context["base_revision"] == editor.repo.load(p["id"])["revision"]
    for params in [
        {"start": -1},
        {"start": 4, "end": 2},
        {"end": "nan"},
        {"end": "inf"},
    ]:
        assert client.get(route + "/context", params=params).status_code == 400


def test_take_decision_rejects_stale_context(prepared_client):
    client, editor, p, _ = prepared_client
    p = prepare_video(client, editor, p, language="en")
    candidate = p["retakes"][0]
    editor.repo.change(
        p["id"], lambda current: current.update(name="Changed elsewhere")
    )
    response = client.post(
        f"/api/projects/{p['id']}/retakes/{candidate['id']}",
        json={
            "base_revision": p["revision"],
            "selected": 1,
            "reason": "Prefer delivery",
        },
    )
    assert response.status_code == 409
    assert editor.repo.load(p["id"])["retakes"][0] == candidate


def test_generate_invalidates_preparation_completion_but_keeps_raw_cache(
    prepared_client,
):
    client, editor, p, calls = prepared_client
    p = prepare_video(client, editor, p, language="en")
    route = f"/api/projects/{p['id']}"
    response = client.post(route + "/transcribe", json={"language": "ar"})
    assert response.status_code == 200
    generated = wait_for(editor, p["id"])
    assert generated["transcript"]["language"] == "ar"
    assert generated["preparation_key"] is None
    prepared = prepare_video(client, editor, generated, language="en")
    assert prepared["transcript"]["language"] == "en"
    assert calls == ["en", "ar"]


def test_pcm_corruption_rebuilds_audio_without_rerunning_recognition(
    prepared_client, monkeypatch
):
    client, editor, p, calls = prepared_client
    p = prepare_video(client, editor, p, language="en")
    wav = editor.repo.directory(p["id"]) / "working/speech.wav"
    wav.write_bytes(b"broken PCM")
    extracts = []
    original = media.extract_speech_audio

    def extract(*args):
        extracts.append(1)
        return original(*args)

    monkeypatch.setattr(media, "extract_speech_audio", extract)
    prepare_video(client, editor, p, language="en")
    media.validate_speech_audio(wav)
    assert extracts == [1] and calls == ["en"]


def test_scoring_contract_change_reuses_recognition(prepared_client, monkeypatch):
    from aiedit.analysis import CONTRACTS

    client, editor, p, calls = prepared_client
    p = prepare_video(client, editor, p, language="en")
    monkeypatch.setitem(CONTRACTS, "retakes", CONTRACTS["retakes"] + 1)
    p = prepare_video(client, editor, p, language="en")
    assert calls == ["en"]
    stages = {entry["stage"]: entry for entry in p["jobs"]["prepare"]["stages"]}
    assert stages["transcription"]["reused"] and not stages["retakes"]["reused"]


def test_vad_model_and_padding_change_reuse_recognition(prepared_client, monkeypatch):
    from aiedit import analysis

    client, editor, p, calls = prepared_client
    editor.vad_model.write_bytes(b"vad-model1")
    identity = analysis.tool_identity
    monkeypatch.setattr(
        analysis,
        "tool_identity",
        lambda name: (
            "test-vad-tool" if name == "whisper-vad-speech-segments" else identity(name)
        ),
    )
    vad_calls = []

    def regions(wav, model, padding):
        vad_calls.append(padding)
        return [{"start": 0, "end": 1.2}, {"start": 3, "end": 4.2}]

    monkeypatch.setattr(media, "speech_regions", regions)
    p = prepare_video(client, editor, p, language="en")
    prepare_video(client, editor, p, language="en")
    assert len(vad_calls) == 1
    p = prepare_video(client, editor, p, language="en", padding=0.05)
    editor.vad_model.write_bytes(b"vad-model2")
    prepare_video(client, editor, p, language="en", padding=0.05)
    assert len(vad_calls) == 3 and calls == ["en"]


def test_editorial_decisions_apply_only_targeted_fields_and_are_atomic(prepared_client):
    client, editor, p, _ = prepared_client
    p = prepare_video(client, editor, p, language="en")
    route = f"/api/projects/{p['id']}/editorial"
    original_style = p["subtitle_style"].copy()
    original_cuts = p["cuts"]
    cue = p["subtitles"][0]
    changed = client.patch(
        route,
        json={
            "base_revision": p["revision"],
            "caption_fixes": [{"id": cue["id"], "text": "Faithful correction"}],
            "story": {"topic": "Clarity"},
        },
    )
    assert changed.status_code == 200, changed.text
    after = changed.json()
    assert after["subtitles"][0]["text"] == "Faithful correction"
    assert after["subtitles"][1:] == p["subtitles"][1:]
    assert after["subtitle_style"] == original_style and after["cuts"] == original_cuts
    assert after["story"]["topic"] == "Clarity"
    assert (
        client.patch(
            route, json={"base_revision": p["revision"], "story": {"topic": "Stale"}}
        ).status_code
        == 409
    )
    invalid = client.patch(
        route,
        json={
            "base_revision": after["revision"],
            "caption_fixes": [
                {"id": cue["id"], "text": "Must roll back"},
                {"id": "unknown", "text": "No caption"},
            ],
        },
    )
    assert invalid.status_code == 400
    current = editor.repo.load(p["id"])
    assert current["revision"] == after["revision"]
    assert current["subtitles"] == after["subtitles"]


def test_editorial_long_caption_rejected_without_partial_changes(prepared_client):
    client, editor, p, _ = prepared_client
    p = prepare_video(client, editor, p, language="en")
    response = client.patch(
        f"/api/projects/{p['id']}/editorial",
        json={
            "base_revision": p["revision"],
            "caption_fixes": [
                {"id": p["subtitles"][0]["id"], "text": "These are four spoken words"}
            ],
            "story": {"topic": "Must roll back"},
        },
    )
    assert response.status_code == 400, response.text
    current = editor.repo.load(p["id"])
    assert current["revision"] == p["revision"]
    assert current["subtitles"] == p["subtitles"]
    assert current["story"] == p["story"]


def test_editorial_take_choices_precede_caption_corrections(prepared_client):
    client, editor, p, _ = prepared_client
    p = prepare_video(client, editor, p, language="en")
    route = f"/api/projects/{p['id']}/editorial"
    choice = {
        "id": p["retakes"][0]["id"],
        "selected": 1,
        "reason": "Prefer the delivery",
    }
    mixed = client.patch(
        route,
        json={
            "base_revision": p["revision"],
            "take_choices": [choice],
            "caption_fixes": [{"id": p["subtitles"][0]["id"], "text": "Correction"}],
        },
    )
    assert mixed.status_code == 400
    assert editor.repo.load(p["id"])["revision"] == p["revision"]
    selected = client.patch(
        route, json={"base_revision": p["revision"], "take_choices": [choice]}
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["retakes"][0]["selected"] == 1
    assert any(c["start"] >= 3 for c in selected.json()["subtitles"])


def test_take_change_fills_newly_visible_captions_without_replacing_corrections(
    prepared_client,
):
    client, editor, p, _ = prepared_client
    p = prepare_video(client, editor, p, language="en")
    route = f"/api/projects/{p['id']}/editorial"
    cue = p["subtitles"][0]
    corrected = client.patch(
        route,
        json={
            "base_revision": p["revision"],
            "caption_fixes": [{"id": cue["id"], "text": "Keep my correction"}],
        },
    ).json()
    selected = client.patch(
        route,
        json={
            "base_revision": corrected["revision"],
            "take_choices": [
                {
                    "id": p["retakes"][0]["id"],
                    "selected": 1,
                    "reason": "Better delivery",
                }
            ],
        },
    )
    assert selected.status_code == 200, selected.text
    current = selected.json()
    assert any(
        c["id"] == cue["id"] and c["text"] == "Keep my correction"
        for c in current["subtitles"]
    )
    assert any(c["start"] >= 3 for c in current["subtitles"])


@pytest.mark.parametrize("has_audio", [False, True])
def test_silent_recording_keeps_interactions_without_asr(
    recording, tmp_path, monkeypatch, has_audio
):
    source = tmp_path / "silent.mp4"
    command = [
        media.binary("ffmpeg"),
        "-v",
        "error",
        "-n",
        "-i",
        str(recording),
        "-c:v",
        "copy",
    ]
    command += ["-af", "volume=0", "-c:a", "aac"] if has_audio else ["-an"]
    media.run(command + [str(source)])

    def unexpected(*args, **kwargs):
        pytest.fail("A silent recording must not invoke recognition")

    monkeypatch.setattr(media, "transcribe_audio", unexpected)
    with TestClient(
        create_app(tmp_path / "data", assistant_session=False), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(source, source.name)["id"])
        result = prepare_video(client, editor, p)
        assert result["cuts"] == [] and result["subtitles"] == []
        assert result["preparation_kind"] == "visual"
        assert result["media"]["duration"] == p["media"]["duration"]


def test_approved_caption_edit_is_not_retuned_after_contract_upgrade(
    prepared_client, monkeypatch
):
    from aiedit.analysis import CONTRACTS

    client, editor, p, calls = prepared_client
    p = prepare_video(client, editor, p, language="en")
    body = edit_body(p)
    body["subtitles"][0]["text"] = "Approved wording"
    assert client.put(f"/api/projects/{p['id']}", json=body).status_code == 200
    monkeypatch.setitem(CONTRACTS, "prepare", CONTRACTS["prepare"] + 1)
    result = prepare_video(client, editor, p, language="en")
    assert result["subtitles"] == body["subtitles"] and calls == ["en"]


def test_editorial_overlay_update_preserves_positions_and_unrelated_layers(prepared_client, tmp_path):
    client, editor, p, _ = prepared_client
    image = tmp_path / "reference.png"
    media.run([media.binary("ffmpeg"), "-v", "error", "-n", "-f", "lavfi", "-i", "color=red:s=64x64",
               "-frames:v", "1", "-threads", "1", str(image)])
    asset = editor.library.import_file(image)
    route = f"/api/projects/{p['id']}/editorial"
    first = client.patch(route, json={"base_revision": p["revision"], "overlays": [
        {"id": "first", "asset_id": asset["id"], "start": 0, "end": 4, "role": "graphic", "x": .2, "y": .3},
        {"id": "second", "asset_id": asset["id"], "start": 1, "end": 3, "role": "graphic"}]}).json()
    second = client.patch(route, json={"base_revision": first["revision"], "overlays": [
        {"id": "first", "asset_id": asset["id"], "start": 0, "end": 4, "width": .6}]})
    assert second.status_code == 200, second.text
    overlays = second.json()["overlays"]
    assert [o["id"] for o in overlays] == ["first", "second"]
    assert (overlays[0]["x"], overlays[0]["y"], overlays[0]["role"], overlays[0]["width"]) == (.2, .3, "graphic", .6)
    assert overlays[1] == first["overlays"][1]
