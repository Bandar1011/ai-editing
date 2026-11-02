import base64
import json
import threading
import time

import pytest
from fastapi import HTTPException

from aiedit.assistant import Assistant
from test_media_and_api import recording  # noqa: F401
from test_preparation import prepared_client, prepare_video  # noqa: F401


def wait_ai(editor, identifier):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        p = editor.repo.load(identifier)
        if (
            not any(
                j["status"] in {"queued", "running"} or j.get("next_job_pending")
                for j in p["jobs"].values()
            )
            and identifier not in editor.active
            and not editor.assistant.is_running(identifier)
        ):
            return p
        time.sleep(0.01)
    pytest.fail("AI session did not finish")


def call(editor, run, name, **arguments):
    result = editor.assistant.tool(run.project_id, run.token, name, arguments)
    return json.loads(result["content"][0]["text"])


def test_prepare_automatically_runs_editorial_tools_and_fixed_title(prepared_client):
    client, editor, p, _ = prepared_client
    invocations = []

    def session(run):
        invocations.append(run.id)
        assert run.project_id not in editor.active
        ctx = call(editor, run, "context")
        assert ctx["window"]["next_start"] is None
        image = editor.assistant.tool(
            run.project_id, run.token, "inspect", {"time": 0.2}
        )
        assert base64.b64decode(image["content"][1]["data"]).startswith(b"\xff\xd8")
        call(
            editor,
            run,
            "apply",
            base_revision=ctx["base_revision"],
            caption_fixes=[
                {"id": ctx["captions"][0]["id"], "text": "Faithful correction"}
            ],
        )
        call(
            editor,
            run,
            "title",
            lines=["Focus better"],
            reason="The clip demonstrates focusing.",
        )
        return {
            "summary": "Corrected captions and added the opening title.",
            "review_notes": [],
        }

    editor.assistant = Assistant(editor, session=session)
    assert (
        client.post(
            f"/api/projects/{p['id']}/prepare", json={"language": "en"}
        ).status_code
        == 200
    )
    after = wait_ai(editor, p["id"])
    assert after["jobs"]["prepare"]["status"] == "done"
    assert after["jobs"]["assistant"]["status"] == "done"
    assert after["subtitles"][0]["text"] == "Faithful correction"
    title = next(o for o in after["overlays"] if o["role"] == "title")
    assert title["id"] == "assistant-title" and title["white_nits"] == 1000
    assert title.get("entrance_sound") is None
    assert len(after["jobs"]["assistant"]["receipts"]) == 2
    prepare_video(client, editor, after, language="en")
    assert wait_ai(editor, p["id"])["overlays"] == after["overlays"]
    assert invocations == [after["jobs"]["assistant"]["id"]]


def test_duplicate_prepare_and_wrong_tool_token_do_not_start_another_ai(
    prepared_client,
):
    client, editor, p, _ = prepared_client
    entered, release = threading.Event(), threading.Event()
    invocations = []

    def session(run):
        invocations.append(run)
        call(editor, run, "context")
        entered.set()
        assert release.wait(10)
        return {"summary": "Read the clip.", "review_notes": ["Title requires review."]}

    editor.assistant = Assistant(editor, session=session)
    try:
        client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
        assert entered.wait(10)
        before = editor.repo.load(p["id"])
        response = client.post(
            f"/api/projects/{p['id']}/prepare", json={"language": "en"}
        )
        assert response.status_code == 200
        assert (
            response.json()["jobs"]["prepare"]["id"] == before["jobs"]["prepare"]["id"]
        )
        conflict = client.post(
            f"/api/projects/{p['id']}/prepare", json={"language": "ar"}
        )
        assert conflict.status_code == 409, conflict.text
        route = f"/api/projects/{p['id']}/assistant/tools"
        assert (
            client.post(
                route,
                json={"name": "context", "arguments": {}},
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                route,
                json={"name": "context", "arguments": {}},
                headers={"Authorization": "Bearer " + invocations[0].token},
            ).status_code
            == 200
        )
    finally:
        release.set()
    after = wait_ai(editor, p["id"])
    assert (
        len(invocations) == 1
        and after["jobs"]["assistant"]["outcome"] == "needs_review"
    )
    assert (
        client.post(
            route,
            json={"name": "context", "arguments": {}},
            headers={"Authorization": "Bearer " + invocations[0].token},
        ).status_code
        == 403
    )


def test_manual_change_stops_ai_without_overwriting_caption(prepared_client):
    client, editor, p, _ = prepared_client
    entered, release = threading.Event(), threading.Event()

    def session(run):
        ctx = call(editor, run, "context")
        entered.set()
        assert release.wait(10)
        call(
            editor,
            run,
            "apply",
            base_revision=ctx["base_revision"],
            caption_fixes=[{"id": ctx["captions"][0]["id"], "text": "AI correction"}],
        )
        return {"summary": "Must not complete.", "review_notes": []}

    editor.assistant = Assistant(editor, session=session)
    try:
        client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
        assert entered.wait(10)
        latest = editor.repo.load(p["id"])
        changed = client.patch(
            f"/api/projects/{p['id']}/editorial",
            json={
                "base_revision": latest["revision"],
                "caption_fixes": [
                    {"id": latest["subtitles"][0]["id"], "text": "My correction"}
                ],
            },
        )
        assert changed.status_code == 200
    finally:
        release.set()
    after = wait_ai(editor, p["id"])
    assert after["subtitles"][0]["text"] == "My correction"
    assert after["jobs"]["assistant"]["status"] == "error"
    assert "preserved" in after["jobs"]["assistant"]["message"]


def test_retry_preserves_partial_decisions_and_authored_captions(prepared_client):
    client, editor, p, _ = prepared_client
    attempts = []

    def session(run):
        attempts.append(run.id)
        ctx = call(editor, run, "context")
        if len(attempts) == 1:
            call(
                editor,
                run,
                "apply",
                base_revision=ctx["base_revision"],
                caption_fixes=[
                    {"id": ctx["captions"][0]["id"], "text": "Saved correction"}
                ],
            )
            editor.assistant.tool(run.project_id, run.token, "inspect", {"time": 0.2})
            call(
                editor,
                run,
                "title",
                lines=["Focus"],
                reason="The source discusses focus.",
            )
            raise RuntimeError("Connection interrupted after saving")
        assert ctx["captions"][0]["text"] == "Saved correction"
        with pytest.raises(ValueError, match="protected"):
            call(
                editor,
                run,
                "apply",
                base_revision=ctx["base_revision"],
                caption_fixes=[
                    {"id": ctx["captions"][0]["id"], "text": "Must not overwrite"}
                ],
            )
        call(
            editor,
            run,
            "apply",
            base_revision=ctx["base_revision"],
            caption_fixes=[{"id": ctx["captions"][1]["id"], "text": "App."}],
        )
        assert call(editor, run, "title", lines=["Focus"], reason="Preserve it")[
            "preserved"
        ]
        return {
            "summary": "Preserved the saved correction.",
            "review_notes": ["Title needs review."],
        }

    editor.assistant = Assistant(editor, session=session)
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    failed = wait_ai(editor, p["id"])
    assert failed["jobs"]["prepare"]["status"] == "done"
    assert failed["jobs"]["assistant"]["status"] == "error"
    assert failed["jobs"]["assistant"]["receipts"]
    response = client.post(f"/api/projects/{p['id']}/assistant/retry")
    assert response.status_code == 200
    done = wait_ai(editor, p["id"])
    assert len(attempts) == 2 and done["subtitles"][0]["text"] == "Saved correction"
    assert done["jobs"]["assistant"]["status"] == "done"
    assert done["subtitles"][1]["text"] == "App."
    assert len([o for o in done["overlays"] if o["role"] == "title"]) == 1


def test_ai_without_source_context_is_not_reported_complete(prepared_client):
    client, editor, p, _ = prepared_client
    editor.assistant = Assistant(
        editor,
        session=lambda run: {
            "summary": "Nothing was saved.",
            "review_notes": ["Tool access failed."],
        },
    )
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    after = wait_ai(editor, p["id"])
    assert after["jobs"]["prepare"]["status"] == "done"
    assert after["jobs"]["assistant"]["status"] == "error"
    assert "retry AI" in after["jobs"]["assistant"]["message"]


def test_take_revision_survives_this_sessions_progress_updates(prepared_client):
    client, editor, p, _ = prepared_client

    def session(run):
        ctx = call(editor, run, "context")
        call(
            editor,
            run,
            "apply",
            base_revision=ctx["base_revision"],
            take_choices=[
                {
                    "id": ctx["retakes"][0]["id"],
                    "base_revision": ctx["base_revision"],
                    "selected": None,
                    "reason": "Preserve both takes for review",
                }
            ],
        )
        return {"summary": "Kept both takes.", "review_notes": ["Title needs review."]}

    editor.assistant = Assistant(editor, session=session)
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    after = wait_ai(editor, p["id"])
    assert after["jobs"]["assistant"]["status"] == "done", after["jobs"]["assistant"][
        "message"
    ]
    assert after["retakes"][0]["selected"] is None


def test_manual_caption_between_attempts_is_protected(prepared_client):
    client, editor, p, _ = prepared_client
    attempts = []

    def session(run):
        attempts.append(run.id)
        ctx = call(editor, run, "context")
        if len(attempts) == 1:
            call(
                editor,
                run,
                "apply",
                base_revision=ctx["base_revision"],
                caption_fixes=[
                    {"id": ctx["captions"][0]["id"], "text": "Saved correction"}
                ],
            )
            raise RuntimeError("Connection interrupted")
        assert {c["id"] for c in ctx["captions"]} <= set(ctx["protected_caption_ids"])
        return {
            "summary": "Preserved all authored text.",
            "review_notes": ["Title needs review."],
        }

    editor.assistant = Assistant(editor, session=session)
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    first = wait_ai(editor, p["id"])
    response = client.patch(
        f"/api/projects/{p['id']}/editorial",
        json={
            "base_revision": first["revision"],
            "caption_fixes": [
                {"id": first["subtitles"][1]["id"], "text": "Human wording"}
            ],
        },
    )
    assert response.status_code == 200
    client.post(f"/api/projects/{p['id']}/assistant/retry")
    after = wait_ai(editor, p["id"])
    assert after["jobs"]["assistant"]["status"] == "done"
    assert after["subtitles"][1]["text"] == "Human wording"


def test_retry_can_correct_newly_revealed_captions_without_changing_human_text(
    prepared_client,
):
    client, editor, p, _ = prepared_client
    p = prepare_video(client, editor, p, language="en")
    cue = p["subtitles"][0]
    changed = client.patch(
        f"/api/projects/{p['id']}/editorial",
        json={
            "base_revision": p["revision"],
            "caption_fixes": [{"id": cue["id"], "text": "Human correction"}],
        },
    )
    assert changed.status_code == 200
    attempts = []

    def session(run):
        attempts.append(run.id)
        ctx = call(editor, run, "context")
        if len(attempts) == 1:
            call(
                editor,
                run,
                "apply",
                base_revision=ctx["base_revision"],
                take_choices=[
                    {
                        "id": ctx["retakes"][0]["id"],
                        "selected": None,
                        "reason": "Restore both takes for review",
                    }
                ],
            )
            raise RuntimeError("Interrupted after restoring footage")
        fresh = next(
            c for c in ctx["captions"] if c["id"] not in ctx["protected_caption_ids"]
        )
        call(
            editor,
            run,
            "apply",
            base_revision=ctx["base_revision"],
            caption_fixes=[{"id": fresh["id"], "text": "New correction"}],
        )
        return {
            "summary": "Corrected newly revealed words.",
            "review_notes": ["Title needs review."],
        }

    editor.assistant = Assistant(editor, session=session)
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    failed = wait_ai(editor, p["id"])
    assert failed["jobs"]["assistant"]["status"] == "error"
    client.post(f"/api/projects/{p['id']}/assistant/retry")
    after = wait_ai(editor, p["id"])
    assert after["jobs"]["assistant"]["status"] == "done", after["jobs"]["assistant"]
    assert (
        next(c for c in after["subtitles"] if c["id"] == cue["id"])["text"]
        == "Human correction"
    )
    assert any(c["text"] == "New correction" for c in after["subtitles"])


@pytest.mark.parametrize("selected", [0, None])
def test_prior_human_take_choice_is_preserved(prepared_client, selected):
    client, editor, p, _ = prepared_client
    p = prepare_video(client, editor, p, language="en")
    take = p["retakes"][0]
    response = client.post(
        f"/api/projects/{p['id']}/retakes/{take['id']}",
        json={"selected": selected, "reason": "Human reviewed this delivery"},
    )
    assert response.status_code == 200

    def session(run):
        ctx = call(editor, run, "context")
        try:
            call(
                editor,
                run,
                "apply",
                base_revision=ctx["base_revision"],
                take_choices=[
                    {
                        "id": take["id"],
                        "selected": 1,
                        "reason": "Must preserve human choice",
                    }
                ],
            )
        except ValueError:
            pass
        return {
            "summary": "Preserved the selected take.",
            "review_notes": ["Title needs review."],
        }

    editor.assistant = Assistant(editor, session=session)
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    after = wait_ai(editor, p["id"])
    assert after["retakes"][0]["selected"] == selected
    assert after["retakes"][0]["reason"] == "Human reviewed this delivery"


@pytest.mark.parametrize("operation", ["export", "silence", "transcribe"])
def test_native_operations_are_blocked_during_ai_handoff(prepared_client, operation):
    client, editor, p, _ = prepared_client
    entered, release = threading.Event(), threading.Event()

    def session(run):
        call(editor, run, "context")
        return {
            "summary": "Read the prepared clip.",
            "review_notes": ["Title needs review."],
        }

    editor.assistant = Assistant(editor, session=session)
    original_start = editor.assistant.start

    def delayed_start(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original_start(*args, **kwargs)

    editor.assistant.start = delayed_start
    try:
        client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
        assert entered.wait(10)
        assert p["id"] not in editor.active
        assert (
            client.post(
                f"/api/projects/{p['id']}/prepare", json={"language": "en"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/projects/{p['id']}/prepare", json={"language": "ar"}
            ).status_code
            == 409
        )
        result = client.post(f"/api/projects/{p['id']}/{operation}", json={})
        assert result.status_code == 409, result.text
    finally:
        release.set()
        wait_ai(editor, p["id"])


def test_exported_edit_is_preserved_without_calling_model(prepared_client):
    client, editor, p, _ = prepared_client
    p = prepare_video(client, editor, p, language="en")
    editor.repo.change(
        p["id"], lambda current: current["exports"].append({"file": "approved.mp4"})
    )

    def unexpected(run):
        pytest.fail("Do not retrofit AI effects onto an exported edit")

    editor.assistant = Assistant(editor, session=unexpected)
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    after = wait_ai(editor, p["id"])
    assert after["jobs"]["assistant"]["stage"] == "preserved"
    assert after["subtitles"] == p["subtitles"]


def test_absent_codex_is_an_honest_retryable_error(prepared_client, monkeypatch):
    client, editor, p, _ = prepared_client
    from aiedit import assistant

    original = assistant.shutil.which
    monkeypatch.setattr(
        assistant.shutil,
        "which",
        lambda name: None if name == "codex" else original(name),
    )
    editor.assistant = Assistant(editor)
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    after = wait_ai(editor, p["id"])
    assert after["jobs"]["prepare"]["status"] == "done"
    assert after["jobs"]["assistant"]["status"] == "error"
    assert "not installed" in after["jobs"]["assistant"]["message"]


def test_session_tool_scope_and_visual_evidence_are_enforced(prepared_client):
    client, editor, p, _ = prepared_client

    def session(run):
        ctx = call(editor, run, "context")
        with pytest.raises(HTTPException):
            editor.assistant.tool("000000000000", run.token, "context", {})
        with pytest.raises(ValueError, match="Inspect"):
            call(editor, run, "title", lines=["A title"], reason="Context")
        with pytest.raises(ValueError, match="Unknown"):
            editor.assistant.tool(run.project_id, run.token, "shell", {})
        with pytest.raises(Exception):
            call(
                editor,
                run,
                "import_reference",
                filename="../../other.png",
                source_url="https://example.com",
                description="Not a capture",
            )
        return {
            "summary": "Read the clip safely.",
            "review_notes": ["Title needs review."],
        }

    editor.assistant = Assistant(editor, session=session)
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    after = wait_ai(editor, p["id"])
    assert after["jobs"]["assistant"]["status"] == "done"


def test_shutdown_interrupts_the_owned_session(prepared_client):
    client, editor, p, _ = prepared_client
    entered = threading.Event()

    def session(run):
        call(editor, run, "context")
        entered.set()
        assert run.stopped.wait(10)
        return {"summary": "Must not become ready.", "review_notes": []}

    editor.assistant = Assistant(editor, session=session)
    client.post(f"/api/projects/{p['id']}/prepare", json={"language": "en"})
    assert entered.wait(10)
    editor.assistant.close()
    after = wait_ai(editor, p["id"])
    assert after["jobs"]["assistant"]["status"] == "error"
    assert after["jobs"]["prepare"]["status"] == "done"
