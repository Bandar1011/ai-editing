import os
import subprocess
from pathlib import Path

import pytest

from aiedit import toolchain
from aiedit.analysis import Analysis, file_identity, key_for
from aiedit.render import font_environment


def test_linked_library_upgrade_and_symlink_change_invalidate_tool(
    tmp_path, monkeypatch
):
    root = tmp_path / "bin/tool"
    root.parent.mkdir()
    root.write_bytes(b"executable stays unchanged")
    lib = tmp_path / "lib/library.dylib"
    lib.parent.mkdir()
    lib.write_bytes(b"version1")
    runtime = tmp_path / "os-version"
    runtime.write_bytes(b"build1")
    monkeypatch.setattr(toolchain.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(toolchain, "runtime_files", lambda: [runtime])
    calls = []

    def inspect(command):
        calls.append(command)
        path = Path(command[-1])
        if command[1] == "-L":
            links = (
                "\t@rpath/library.dylib (compatibility version 1.0.0, current version 1.0.0)\n"
                if path == root
                else "\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\n"
            )
            return 0, str(path) + ":\n" + links, ""
        return (
            0,
            "cmd LC_RPATH\n cmdsize 32\n path @loader_path/../lib (offset 12)\n",
            "",
        )

    monkeypatch.setattr(toolchain, "inspect", inspect)
    toolchain.macho_links.cache_clear()
    first = toolchain.identity(root, file_identity, key_for)
    assert first
    count = len(calls)
    assert toolchain.identity(root, file_identity, key_for) == first
    assert len(calls) == count
    before = root.read_bytes()
    modified = lib.stat().st_mtime_ns
    lib.write_bytes(b"version2")
    os.utime(lib, ns=(modified, modified))
    second = toolchain.identity(root, file_identity, key_for)
    assert second != first and root.read_bytes() == before
    assert len(calls) > count
    alternate = lib.with_name("another.dylib")
    alternate.write_bytes(b"version3")
    lib.unlink()
    lib.symlink_to(alternate.name)
    assert toolchain.identity(root, file_identity, key_for) != second
    runtime.write_bytes(b"build2")
    assert toolchain.identity(root, file_identity, key_for) != second


def test_unknown_loader_configuration_does_not_publish_reusable_facts(
    tmp_path, monkeypatch
):
    root = tmp_path / "source"
    root.write_bytes(b"source")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", str(tmp_path))
    assert toolchain.identity(root, file_identity, key_for) is None
    analysis = Analysis(root, tmp_path / "working")
    calls = []

    def calculate():
        calls.append(1)
        return {"real_result": True}

    assert analysis.fact("silence", {"decoder": None}, calculate)["real_result"]
    assert analysis.fact("silence", {"decoder": None}, calculate)["real_result"]
    assert calls == [1, 1]
    assert list(analysis.directory.iterdir()) == []


def test_active_user_font_alias_and_font_replacement_invalidate_environment(
    tmp_path, monkeypatch
):
    from aiedit import media, render

    font = tmp_path / "face.ttf"
    font.write_bytes(b"font-v1")
    config = tmp_path / "user-fonts.conf"
    config.write_text("<fontconfig><alias>First</alias></fontconfig>")
    monkeypatch.setattr(render.shutil, "which", lambda name: name)
    monkeypatch.setattr(
        media,
        "run",
        lambda command, **options: (
            str(font) + "\n"
            if command[0] == "fc-list"
            else "+ " + str(config) + ": User aliases\n"
        ),
    )
    first = key_for(font_environment())
    config.write_text("<fontconfig><alias>Other</alias></fontconfig>")
    second = key_for(font_environment())
    assert second != first
    modified = font.stat().st_mtime_ns
    font.write_bytes(b"font-v2")
    os.utime(font, ns=(modified, modified))
    assert key_for(font_environment()) != second
    monkeypatch.setenv("FONTCONFIG_FILE", str(config))
    assert font_environment() is None


@pytest.mark.parametrize("helper", ["fc-list", "fc-conflist"])
@pytest.mark.parametrize(
    "failure",
    [RuntimeError("Unavailable"), OSError("Missing"), subprocess.TimeoutExpired("font-discovery", 5)],
)
def test_font_discovery_errors_disable_reuse(helper, failure, tmp_path, monkeypatch):
    from aiedit import media, render

    font = tmp_path / "face.ttf"
    font.write_bytes(b"font")
    monkeypatch.setattr(render.shutil, "which", lambda name: name)

    def discover(command, **options):
        assert 0 < options["timeout"] <= 10
        if command[0] == helper:
            raise failure
        return str(font) + "\n"

    monkeypatch.setattr(media, "run", discover)
    assert font_environment() is None
