"""Private, dependency-keyed source facts. Editable project state is never cached."""

import copy
import hashlib
import json
import time
import uuid
import wave
from functools import lru_cache
from pathlib import Path

from . import media, story
from .presets import SPEECH

# Bump only the affected contract when a parser or scoring algorithm changes.
CONTRACTS = {
    "signal": 1,
    "transcription": 1,
    "silence": 1,
    "speech": 1,
    "retakes": 1,
    "prepare": 1,
}


def key_for(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@lru_cache(maxsize=4096)
def _file_digest(path, device, inode, size, modified, changed):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_identity(path):
    path = Path(path).resolve()
    stat = path.stat()
    return _file_digest(
        str(path),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def tool_identity(name):
    from .toolchain import identity

    return identity(media.binary(name), file_identity, key_for)


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Analysis:
    def __init__(self, source, working, report=None):
        self.source = Path(source)
        self.working = Path(working)
        self.directory = self.working / "analysis"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.source_key = file_identity(source)
        self.report = report or (lambda **event: None)
        self.keys = {}
        self._audio = None

    def _event(self, stage, status, started, reused=False):
        self.report(
            stage=stage,
            status=status,
            reused=reused,
            seconds=round(time.monotonic() - started, 4),
        )

    def fact(self, stage, dependencies, compute, validate=None):
        if any(value is None for value in dependencies.values()):
            started = time.monotonic()
            self.keys[stage] = None
            self._event(stage, "running", started)
            value = compute()
            if validate:
                validate(value)
            self._event(stage, "done", started)
            return copy.deepcopy(value)
        key = key_for(
            {"stage": stage, "schema": CONTRACTS[stage], "dependencies": dependencies}
        )
        self.keys[stage] = key
        path = self.directory / f"{stage}-{key}.json"
        started = time.monotonic()
        try:
            record = json.loads(path.read_text())
            if not isinstance(record, dict):
                raise ValueError("Invalid analysis manifest")
            value = record["value"]
            if record["key"] != key or record["sha256"] != key_for(value):
                raise ValueError("Incomplete analysis artifact")
            if validate:
                validate(value)
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            pass
        else:
            self._event(stage, "done", started, reused=True)
            return copy.deepcopy(value)
        self._event(stage, "running", started)
        value = compute()
        if validate:
            validate(value)
        atomic_json(path, {"key": key, "sha256": key_for(value), "value": value})
        self._event(stage, "done", started)
        return copy.deepcopy(value)

    def audio(self):
        if self._audio is not None:
            return self._audio
        decoder = tool_identity("ffmpeg")
        key = key_for(
            {
                "source": self.source_key,
                "decoder": decoder,
                "format": "default-audio/mono/16000/s16le/v1",
            }
        )
        self.keys["audio"] = key if decoder is not None else None
        wav, manifest = self.working / "speech.wav", self.directory / "audio.json"
        started = time.monotonic()
        try:
            record = json.loads(manifest.read_text())
            if not isinstance(record, dict):
                raise ValueError("Invalid audio manifest")
            valid = (
                decoder is not None
                and record["key"] == key
                and record["sha256"] == file_identity(wav)
            )
            if valid:
                media.validate_speech_audio(wav)
        except (
            FileNotFoundError,
            ValueError,
            KeyError,
            TypeError,
            wave.Error,
            EOFError,
        ):
            valid = False
        if valid:
            self._event("audio", "done", started, reused=True)
            self._audio = wav
            return wav
        self._event("audio", "running", started)
        temporary = self.working / f"speech-{uuid.uuid4().hex}.wav"
        try:
            media.extract_speech_audio(self.source, temporary)
            media.validate_speech_audio(temporary)
            temporary.replace(wav)
            if decoder is not None:
                atomic_json(manifest, {"key": key, "sha256": file_identity(wav)})
        finally:
            temporary.unlink(missing_ok=True)
        self._event("audio", "done", started)
        self._audio = wav
        return wav

    def transcript(self, model, language, duration):
        if not model.is_file():
            raise ValueError(
                "The local speech model is missing. Run: uv run python scripts/setup_model.py"
            )
        wav = self.audio()
        dependencies = {
            "audio": self.keys["audio"],
            "model": file_identity(model),
            "recognizer": tool_identity("whisper-cli"),
            "language": language,
            "dtw": media.alignment_preset(model),
            "flash_attention": False,
            "suppress_non_speech": True,
            "threads": 2,
            "parser": 1,
            "duration": duration,
        }
        if any(model.parent.glob("*.mlmodelc")):
            dependencies["coreml"] = None

        def validate(value):
            if (
                not isinstance(value, dict)
                or not value.get("words")
                or not value.get("cues")
            ):
                raise ValueError("No usable source transcript")
            for word in value["words"]:
                if not (
                    0 <= word["start"] < word["end"] <= duration
                    and word["text"].strip()
                ):
                    raise ValueError("Invalid source word timing")

        return self.fact(
            "transcription",
            dependencies,
            lambda: media.transcribe_audio(
                wav, self.working, model, language, duration
            ),
            validate,
        )

    def silent(self):
        wav = self.audio()
        return self.fact(
            "signal",
            {"audio": self.keys["audio"], "maximum_pcm_sample": 2},
            lambda: media.digital_silence(wav),
        )

    def quiet(self, duration, threshold, minimum, padding):
        def compute():
            try:
                return {
                    "cuts": media.detect_silence(
                        self.source, duration, threshold, minimum, padding
                    ),
                    "whole_recording_quiet": False,
                }
            except ValueError as exc:
                if "whole recording" not in str(exc):
                    raise
                return {"cuts": [], "whole_recording_quiet": True}

        return self.fact(
            "silence",
            {
                "source": self.source_key,
                "decoder": tool_identity("ffmpeg"),
                "duration": duration,
                "threshold": threshold,
                "minimum": minimum,
                "padding": padding,
            },
            compute,
        )

    def regions(self, model, padding):
        wav = self.audio()
        return self.fact(
            "speech",
            {
                "audio": self.keys["audio"],
                "model": file_identity(model),
                "detector": tool_identity("whisper-vad-speech-segments"),
                "settings": dict(SPEECH),
                "padding": padding,
            },
            lambda: media.speech_regions(wav, model, padding),
        )

    def retakes(self, words):
        wav = self.audio()
        return self.fact(
            "retakes",
            {
                "words": words,
                "audio": self.keys["audio"],
                "scoring": "mono16000-pcm-clipping-v1",
            },
            lambda: story.retake_candidates(
                words, lambda a, b: media.pcm_audio_quality(wav, a, b)
            ),
        )
