import copy
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from aiedit import media, story
from aiedit.production import PrepareOptions, prepare, preserve_manual, merge_automatic
from aiedit.render import mapped_spans
from aiedit.server import create_app
from test_media_and_api import recording, wait_for
from test_review_workflow import edit_body


def words(text, start=0, confidence=0.9):
    return [
        {
            "id": str(i) + str(start),
            "start": start + i * 0.3,
            "end": start + (i + 1) * 0.3,
            "text": t,
            "confidence": confidence,
        }
        for i, t in enumerate(text.split())
    ]


def test_captions_keep_language_and_strict_word_limit_without_crossing_cuts():
    source = words("Hello there. مرحبا بكم في التطبيق الجديد.", 0)
    result = story.short_captions(source, [{"start": 0.6, "end": 0.9}], 2.1)
    assert all(1 <= len(c["text"].split()) <= 3 for c in result)
    assert any("بكم" in c["text"] for c in result)
    assert all(c["end"] <= 0.6 or c["start"] >= 0.9 for c in result)
    assert not any("مرحبا" in c["text"] for c in result)


def test_dtw_boundaries_join_subword_tokens_and_fail_without_alignment():
    raw = {
        "transcription": [
            {
                "offsets": {"from": 0, "to": 1000},
                "tokens": [
                    {"text": " Hello", "t_dtw": 20, "p": 0.9},
                    {"text": " world", "t_dtw": 65, "p": 0.95},
                    {"text": "s", "t_dtw": 75, "p": 0.9},
                    {"text": ".", "t_dtw": 110, "p": 0.9},
                ],
            }
        ]
    }
    result = story.aligned_words(raw)
    assert [w["text"] for w in result] == ["Hello", "worlds."]
    assert result[0]["end"] == result[1]["start"] == 0.45
    assert result[-1]["end"] == 1
    raw["transcription"][0]["tokens"][0]["t_dtw"] = -1
    with pytest.raises(ValueError, match="alignment is unavailable"):
        story.aligned_words(raw)


def test_retake_quality_can_keep_the_first_take_and_preserves_changed_meaning():
    first = words("This is my new app.", 0, 0.98)
    second = words("This is my new app.", 3, 0.7)
    result = story.retake_candidates(first + second)
    assert len(result) == 1 and result[0]["selected"] == 0 and result[0]["automatic"]
    cut = story.retake_cuts(result)[0]
    assert cut["start"] == 3
    assert not story.retake_candidates(words("very very good", 0))
    changed = story.retake_candidates(
        words("I do not recommend this app.", 0) + words("I do recommend this app.", 4)
    )
    assert changed and not changed[0]["automatic"]
    assert not story.retake_candidates(
        words("We should stop.", 0) + words("We should stop wasting time.", 4)
    )


def test_prepare_preserves_manual_restore_and_saves_decision_evidence(
    recording, tmp_path, monkeypatch
):
    editor = create_app(tmp_path / "data").state.editor
    try:
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        source = words("Here is the app.", 0, 0.98) + words("Here is the app.", 3, 0.65)

        def transcribe(identifier, language):
            editor.repo.change(
                identifier,
                lambda p: p.update(
                    transcript={"words": source}, subtitles=[], captions_authored=False
                ),
            )

        monkeypatch.setattr(editor, "transcribe", transcribe)
        monkeypatch.setattr(
            media, "audio_quality", lambda *args: {"clipped_fraction": 0}
        )
        restore = {
            "id": "restore",
            "start": 1.4,
            "end": 1.8,
            "enabled": False,
            "kind": "manual",
        }
        editor.repo.change(p["id"], lambda p: p.update(cuts=[restore]))
        prepare(editor, p["id"], PrepareOptions())
        p = editor.repo.load(p["id"])
        assert restore in p["cuts"]
        assert p["retakes"][0]["selected"] == 0
        assert all(len(c["text"].split()) <= 3 for c in p["subtitles"])
        assert all(
            c["end"] <= 1.4 or c["start"] >= 1.8 for c in p["cuts"] if c["enabled"]
        )
    finally:
        editor.pool.shutdown(wait=True)


def test_asset_overlay_music_and_punch_in_are_encoded_and_manifested(
    recording, tmp_path
):
    image = tmp_path / "reference.png"
    music = tmp_path / "music.wav"
    media.run(
        [
            media.binary("ffmpeg"),
            "-v",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=320x180",
            "-frames:v",
            "1",
            str(image),
        ]
    )
    media.run(
        [
            media.binary("ffmpeg"),
            "-v",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=800:duration=2",
            str(music),
        ]
    )
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        a = client.post(
            "/api/assets/import",
            json={
                "path": str(image),
                "source_kind": "web",
                "source_url": "https://ffmpeg.org",
                "description": "Reference evidence",
            },
        ).json()
        m = client.post(
            "/api/assets/import",
            json={"path": str(music), "tags": ["calm", "tutorial"]},
        ).json()
        assert (
            client.get("/api/assets", params={"q": "tutorial"}).json()[0]["id"]
            == m["id"]
        )
        assert client.get(f"/api/assets/{a['id']}/media").status_code == 200
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        route = f"/api/projects/{p['id']}"
        body = edit_body(p)
        body.update(
            cuts=[
                {"id": "gap", "start": 2, "end": 3, "kind": "manual", "enabled": True}
            ],
            overlays=[
                {
                    "id": "overlay",
                    "asset_id": a["id"],
                    "start": 1,
                    "end": 4,
                    "layout": "top",
                    "enabled": True,
                    "asset_in": 0,
                    "purpose": "Show the reference",
                }
            ],
            punches=[
                {"id": "zoom", "start": 0.2, "end": 0.8, "scale": 1.1, "enabled": True}
            ],
            music={
                "asset_id": m["id"],
                "volume": 0.1,
                "offset": 0,
                "duck": True,
                "enabled": True,
            },
        )
        saved = client.put(route, json=body)
        assert saved.status_code == 200, saved.text
        client.post(route + "/export", json={"label": "Composed"})
        p = wait_for(editor, p["id"])
        rendered = p["exports"][-1]
        assert rendered["edit_state"]["overlays"] == saved.json()["overlays"]
        assert len(rendered["assets"]) == 2
        assert (
            next(x for x in rendered["assets"] if x["id"] == a["id"])["source_url"]
            == "https://ffmpeg.org"
        )
        output = editor.repo.directory(p["id"]) / "exports" / rendered["file"]

        def pixel(at):
            return subprocess.run(
                [
                    media.binary("ffmpeg"),
                    "-v",
                    "error",
                    "-ss",
                    str(at),
                    "-i",
                    str(output),
                    "-vf",
                    "crop=2:2:160:30,format=rgb24",
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-",
                ],
                capture_output=True,
                check=True,
            ).stdout[:3]

        for t in (1.5, 2.5):
            rgb = pixel(t)
            assert rgb[0] > 200 and rgb[1] < 60 and rgb[2] < 60, rgb
        media.run(
            [
                media.binary("ffmpeg"),
                "-v",
                "error",
                "-i",
                str(output),
                "-f",
                "null",
                "-",
            ]
        )
        assert media.probe(output)["has_audio"]
        client.post(route + "/export", json={"plain": True, "burn_subtitles": False})
        p = wait_for(editor, p["id"])
        assert p["exports"][-1]["render_settings"]["plain"]
        assert p["exports"][-1]["assets"] == []
        body = edit_body(p)
        body["subtitles"] = [
            {"id": "too-long", "start": 0, "end": 1, "text": "four words are forbidden"}
        ]
        assert client.put(route, json=body).status_code == 400
        assert client.get("/api/assets/../../etc/passwd/media").status_code == 404


def test_mapped_overlay_skips_deleted_source_time():
    assert mapped_spans(1, 4, [(0, 2), (3, 5)]) == [
        {"start": 1, "end": 2, "source_start": 1},
        {"start": 2, "end": 3, "source_start": 3},
    ]


def test_hook_performance_is_only_user_supplied(tmp_path):
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        assert (
            client.get("/api/hooks", params={"topic": "screen time"}).json()[
                "related_performance"
            ]
            == []
        )
        entry = {
            "text": "My screen time experiment",
            "topic": "screen time",
            "views": 120,
            "retention": 0.45,
            "source_url": "https://example.com/reel",
        }
        assert client.post("/api/hooks", json=entry).status_code == 200
        result = client.get("/api/hooks", params={"topic": "screen time"}).json()
        assert result["related_performance"][0]["views"] == 120
        assert (
            client.post("/api/hooks", json=dict(entry, retention=2)).status_code == 422
        )


def test_transcript_gaps_and_isolated_hesitations_do_not_remove_meaningful_words():
    cues = [
        {"start": 0.5, "end": 1.5, "text": "One thought."},
        {"start": 3, "end": 4, "text": "Next thought."},
    ]
    gaps = story.speech_gap_cuts(cues, 5, 0.35, 0.1)
    assert [(c["start"], c["end"]) for c in gaps] == [(0, 0.4), (1.6, 2.9), (4.1, 5)]
    hesitant = words("Um.", 0) + words("I like this app.", 2)
    removed = story.filler_cuts(hesitant)
    assert len(removed) == 1 and removed[0]["start"] == 0
    assert not story.filler_cuts(words("I like this app.", 0))


def test_overlapping_automatic_decisions_have_one_restorable_cut():
    automatic = [
        {"id": "quiet", "start": 1, "end": 2.5, "enabled": True, "kind": "silence"},
        {"id": "gap", "start": 1.2, "end": 2.3, "enabled": True, "kind": "speech"},
    ]
    merged = merge_automatic(automatic)
    assert len(merged) == 1 and merged[0]["start"] == 1 and merged[0]["end"] == 2.5
    manual = {
        "id": "restore",
        "start": 1.5,
        "end": 1.8,
        "enabled": False,
        "kind": "manual",
    }
    result = preserve_manual(automatic, [manual])
    assert len(result) == 3 and manual in result
    assert all(c["end"] <= 1.5 or c["start"] >= 1.8 for c in result if c["enabled"])


def test_take_reselection_restores_the_baseline_and_preserves_manual_ranges(
    recording, tmp_path
):
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        candidate = {
            "id": "retry",
            "takes": [
                {"start": 0.1, "end": 1, "text": "first"},
                {"start": 3, "end": 4, "text": "second"},
            ],
            "selected": 0,
            "status": "selected",
            "automatic": True,
            "reason": "quality evidence",
        }
        quiet = {
            "id": "quiet",
            "start": 1.3,
            "end": 2.1,
            "enabled": True,
            "kind": "silence",
        }
        manual = {
            "id": "restore",
            "start": 3.2,
            "end": 3.4,
            "enabled": False,
            "kind": "manual",
        }
        editor.repo.change(
            p["id"],
            lambda p: p.update(
                retakes=[candidate],
                transcript={
                    "words": [
                        {"id": "first", "start": 0.1, "end": 1, "text": "first"},
                        {"id": "second", "start": 3, "end": 4, "text": "second"},
                    ]
                },
                captions_authored=False,
                analysis_cuts=[quiet],
                cuts=preserve_manual(
                    [quiet] + story.retake_cuts([candidate]), [manual]
                ),
            ),
        )
        route = f"/api/projects/{p['id']}/retakes/retry"
        response = client.post(
            route,
            json={"selected": 1, "reason": "Reviewed clearer delivery in take two."},
        )
        assert response.status_code == 200, response.text
        p = response.json()
        assert any(c["start"] == 0.1 and c["end"] == 1 for c in p["cuts"])
        assert not any(c["enabled"] and c["start"] <= 3.2 < c["end"] for c in p["cuts"])
        assert any(c["text"] == "second" for c in p["subtitles"])
        assert not any(c["text"] == "first" for c in p["subtitles"])
        both = client.post(
            route, json={"selected": None, "reason": "The repetition is intentional."}
        ).json()
        assert all(c["kind"] != "retake" for c in both["cuts"])
        assert manual in both["cuts"]
        assert any(c["text"] == "first" for c in both["subtitles"])


def test_video_reference_keeps_its_timing_across_a_source_cut(recording, tmp_path):
    clip = tmp_path / "app-recording.mp4"
    media.run(
        [
            media.binary("ffmpeg"),
            "-v",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x96:rate=12:duration=4",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(clip),
        ]
    )
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        asset = editor.library.import_file(
            clip, source_kind="simulator", description="Synthetic app-recording test"
        )
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        body = edit_body(p)
        body.update(
            cuts=[
                {"id": "gap", "start": 2, "end": 3, "enabled": True, "kind": "manual"}
            ],
            overlays=[
                {
                    "id": "recording",
                    "asset_id": asset["id"],
                    "start": 1,
                    "end": 4,
                    "asset_in": 0.5,
                    "layout": "full",
                    "enabled": True,
                    "purpose": "Demonstrate an interaction",
                }
            ],
        )
        route = f"/api/projects/{p['id']}"
        assert client.put(route, json=body).status_code == 200
        client.post(route + "/export", json={})
        p = wait_for(editor, p["id"])
        output = editor.repo.directory(p["id"]) / "exports" / p["exports"][-1]["file"]
        info = media.probe(output)
        assert info["fps"] == 24 and abs(info["duration"] - 4) < 0.09
        media.run(
            [
                media.binary("ffmpeg"),
                "-v",
                "error",
                "-i",
                str(output),
                "-f",
                "null",
                "-",
            ]
        )
        body = edit_body(p)
        body["overlays"] = [
            {
                "id": "too-long",
                "asset_id": asset["id"],
                "start": 0,
                "end": 5,
                "asset_in": 0,
            }
        ]
        assert client.put(route, json=body).status_code == 400


def test_non_frame_aligned_cuts_preserve_native_frame_rate(recording, tmp_path):
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        editor = client.app.state.editor
        p = wait_for(editor, editor.create(recording, recording.name)["id"])
        body = edit_body(p)
        body["cuts"] = [
            {"id": "lead", "start": 0, "end": 0.078, "enabled": True, "kind": "manual"},
            {
                "id": "gap",
                "start": 1.959,
                "end": 3.413,
                "enabled": True,
                "kind": "manual",
            },
        ]
        route = f"/api/projects/{p['id']}"
        assert client.put(route, json=body).status_code == 200
        assert client.post(route + "/export", json={"plain": True}).status_code == 200
        p = wait_for(editor, p["id"])
        output = editor.repo.directory(p["id"]) / "exports" / p["exports"][-1]["file"]
        info = media.probe(output)
        assert info["fps"] == p["media"]["fps"] == 24
        assert abs(info["duration"] - (p["media"]["duration"] - 1.532)) < 0.09


def test_capture_requires_configuration_and_an_owned_lease(tmp_path):
    import os, sys
    from pathlib import Path

    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1"
    ) as client:
        assert not client.get("/api/capture/config").json()["configured"]
        assert client.post("/api/assets/capture-app", json={}).status_code == 400
    repo = tmp_path / "source"
    repo.mkdir()
    script = Path(__file__).resolve().parents[1] / "scripts/capture_app.py"
    environment = {k: v for k, v in os.environ.items() if not k.startswith("SANDY_")}
    response = subprocess.run(
        [
            sys.executable,
            str(script),
            "--settings",
            str(tmp_path / "no-settings.json"),
            "--repo",
            str(repo),
            "--scheme",
            "Example",
            "--bundle",
            "com.example.app",
            "--output",
            str(tmp_path / "capture.png"),
            "--leased",
        ],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert response.returncode != 0 and "valid owned Simulator lease" in response.stderr
    assert not (tmp_path / "capture.png").exists()


def test_word_alignment_is_bounded_by_the_recording_without_dropping_spoken_text():
    bounded = story.bound_words([{"start": 0.8, "end": 2, "text": "ending."}], 1)
    assert bounded == [{"start": 0.8, "end": 1, "text": "ending."}]
    with pytest.raises(ValueError, match="beyond the recording"):
        story.bound_words([{"start": 1.2, "end": 2, "text": "uncertain"}], 1)


def test_manual_retake_choice_survives_reanalysis():
    original = story.retake_candidates(
        words("This is a complete take.", 0, 0.98)
        + words("This is a complete take.", 3, 0.7)
    )
    original[0].update(
        automatic=False,
        selected=1,
        status="selected",
        reason="Second take has better eye contact.",
    )
    rerun = story.retake_candidates(
        words("This is a complete take.", 0, 0.98)
        + words("This is a complete take.", 3, 0.7)
    )
    decisions = story.preserve_take_decisions(rerun, original)
    assert decisions[0]["selected"] == 1 and decisions[0]["id"] == original[0]["id"]
    assert "eye contact" in decisions[0]["reason"]


def test_download_validates_actual_duration_when_source_metadata_is_missing(
    recording, tmp_path, monkeypatch
):
    import shutil
    from aiedit import assets

    monkeypatch.setattr(
        assets.socket,
        "getaddrinfo",
        lambda *a: [(None, None, None, None, ("1.1.1.1", 443))],
    )
    original_binary = media.binary
    monkeypatch.setattr(
        media,
        "binary",
        lambda name: "yt-dlp" if name == "yt-dlp" else original_binary(name),
    )

    def fetched(command, folder):
        shutil.copyfile(recording, folder / "source.mp4")
        (folder / "source.info.json").write_text(
            json.dumps({"title": "Reference", "duration": None})
        )

    monkeypatch.setattr(assets, "download", fetched)
    library = assets.AssetLibrary(tmp_path / "library" / "assets")
    saved = library.fetch("https://example.com/media", "video")
    assert saved["duration"] == 5 and saved["source_url"] == "https://example.com/media"
    monkeypatch.setattr(
        media, "run", lambda *a, **k: json.dumps({"format": {"duration": 601}})
    )
    with pytest.raises(ValueError, match="at most ten minutes"):
        library.fetch("https://example.com/too-long", "video")
    assert len(library.list()) == 1


def test_unknown_size_download_stops_its_owned_process_at_the_disk_budget(tmp_path):
    import sys
    import time
    from aiedit.assets import download

    with (tmp_path / "source.part").open("wb") as output:
        output.truncate(101 * 1024**2)
    started = time.monotonic()
    with pytest.raises(ValueError, match="100 MB"):
        download([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path)
    assert time.monotonic() - started < 3
