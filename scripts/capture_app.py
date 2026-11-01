"""Capture an app on this Mac through an owned, resource-bounded Simulator lease."""

import argparse
import hashlib
import json
import os
import plistlib
import select
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(args, **kwargs):
    return subprocess.run(
        args, check=True, text=True, capture_output=True, **kwargs
    ).stdout.strip()


def fingerprint(repo):
    digest = hashlib.sha256()
    files = run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repo,
    ).split("\0")
    for relative in sorted(set(files)):
        path = repo / relative
        if not relative or relative.split("/")[0].startswith(".") or not path.is_file():
            continue
        digest.update(relative.encode())
        digest.update(path.read_bytes())
    # XcodeGen output can be ignored in Git and remains a real build input.
    for path in sorted(repo.glob("*.xcodeproj/project.pbxproj")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def product_hash(app):
    digest = hashlib.sha256()
    for path in sorted(app.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(app)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def capture(
    mode, output, seconds, udid, receipt, reusable, launch_arguments, status_path=None
):
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ValueError("Choose a new capture filename.")
    if mode not in {"screenshot", "video"} or not 1 <= seconds <= 30:
        raise ValueError(
            "Choose screenshot/video and a recording duration of 1–30 seconds."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    if mode == "screenshot":
        run(["xcrun", "simctl", "io", udid, "screenshot", str(output)])
    else:
        command = [
            "xcrun",
            "simctl",
            "io",
            udid,
            "recordVideo",
            "--codec=h264",
            str(output),
        ]
        recording = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
        )
        try:
            deadline, started = time.monotonic() + 20, False
            while time.monotonic() < deadline and recording.poll() is None:
                if select.select([recording.stderr], [], [], 1)[0]:
                    if "Recording started" in recording.stderr.readline():
                        started = True
                        break
            if not started:
                raise RuntimeError("The Simulator did not begin recording.")
            if status_path:
                status_path.write_text(
                    json.dumps({"status": "recording", "file": str(output)}) + "\n"
                )
            time.sleep(seconds)
        finally:
            if recording.poll() is None:
                recording.send_signal(signal.SIGINT)
            try:
                recording.wait(timeout=30)
            except subprocess.TimeoutExpired:
                recording.terminate()
                try:
                    recording.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    recording.kill()
                    recording.wait(timeout=10)
                raise RuntimeError(
                    "The owned recording process did not finalize after SIGINT; capture was stopped for cleanup."
                )
        if recording.returncode:
            raise RuntimeError("Simulator recording did not finalize successfully.")
    if not output.is_file() or output.stat().st_size < 100:
        raise RuntimeError("No usable capture was produced.")
    provenance = dict(
        receipt,
        file=str(output),
        device=udid,
        mode=mode,
        reused_build=reusable,
        captured_at=time.time(),
        launch_arguments=launch_arguments,
    )
    output.with_suffix(output.suffix + ".json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "file": str(output),
                "bundle": receipt["bundle"],
                "source_head": receipt["source_head"],
                "reused_build": reusable,
            }
        ),
        flush=True,
    )


def configuration(path):
    return json.loads(path.read_text()) if path.exists() else {}


def main():
    initial = argparse.ArgumentParser(add_help=False)
    initial.add_argument(
        "--settings", type=Path, default=ROOT / ".aiedit/capture-settings.json"
    )
    initial_args, _ = initial.parse_known_args()
    settings = configuration(initial_args.settings)
    parser = argparse.ArgumentParser(description=__doc__, parents=[initial])
    parser.add_argument("--repo", type=Path, default=settings.get("repo"))
    parser.add_argument("--scheme", default=settings.get("scheme"))
    parser.add_argument("--bundle", default=settings.get("bundle"))
    parser.add_argument("--configuration", default="Debug")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="PNG screenshot or MP4 recording path outside the app repository",
    )
    parser.add_argument("--mode", choices=["screenshot", "video"], default="screenshot")
    parser.add_argument("--seconds", type=float, default=4)
    parser.add_argument("--launch-arg", action="append", default=[])
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Hold one owned Simulator lease for navigation and multiple requested captures",
    )
    parser.add_argument("--cache-root", type=Path, default=settings.get("cache_root"))
    parser.add_argument("--leased", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.repo or not args.scheme or not args.bundle:
        parser.error(
            "Configure .aiedit/capture-settings.json or supply --repo, --scheme, and --bundle."
        )
    args.repo = args.repo.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if not 1 <= args.seconds <= 30:
        parser.error("Record between 1 and 30 seconds.")
    if args.output.exists():
        parser.error("Choose a new output filename; captures are never overwritten.")
    if args.repo == args.output or args.repo in args.output.parents:
        parser.error("Keep captured media outside the app's source repository.")
    cache = (
        (
            args.cache_root
            or Path.home() / "Library/Developer/AgentBuilds/AIEditing" / args.repo.name
        )
        .expanduser()
        .resolve()
    )
    if not args.leased:
        wrapper = Path(
            os.environ.get(
                "AIEDIT_BUILD_WRAPPER", Path.home() / ".local/bin/sandy-local-build"
            )
        )
        if not wrapper.is_file():
            parser.error(
                "Install/configure the approved local build/Simulator wrapper first. No unmanaged Simulator will be booted."
            )
        environment = dict(
            os.environ,
            SANDY_BUILD_TASK_ID="ai-editing-capture",
            SANDY_BUILD_OUTPUT_ROOT=str(cache),
            SANDY_BUILD_DERIVED_DATA=str(cache / "DerivedData"),
            SANDY_SIMSLIM="1",
            SANDY_LOCAL_BUILD_JOBS="2",
        )
        command = [
            str(wrapper),
            "--simulator",
            "exec",
            sys.executable,
            str(Path(__file__).resolve()),
            *sys.argv[1:],
            "--leased",
        ]
        return subprocess.run(command, cwd=args.repo, env=environment).returncode
    if os.environ.get("SANDY_LOCAL_BUILD_ACTIVE") != "1" or not os.environ.get(
        "SANDY_SIMULATOR_UDID"
    ):
        parser.error("A valid owned Simulator lease is required.")
    udid = os.environ["SANDY_SIMULATOR_UDID"]
    cache.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    source_hash = fingerprint(args.repo)
    head = run(["git", "rev-parse", "HEAD"], cwd=args.repo)
    toolchain = run(["xcodebuild", "-version"])
    sdk_version = run(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"])
    derived = Path(os.environ["SANDY_BUILD_DERIVED_DATA"])
    receipt_path = cache / "capture-build.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    app = Path(receipt.get("app", "/nonexistent"))
    expected = {
        "source_sha256": source_hash,
        "scheme": args.scheme,
        "configuration": args.configuration,
        "toolchain": toolchain,
        "bundle": args.bundle,
        "sdk": "iphonesimulator",
        "architecture": "arm64",
        "sdk_version": sdk_version,
    }
    reusable = (
        all(receipt.get(k) == v for k, v in expected.items())
        and app.is_dir()
        and receipt.get("product_sha256") == product_hash(app)
    )
    if not reusable:
        if shutil.disk_usage(cache).free < 2 * 1024**3:
            raise RuntimeError(
                "Less than 2 GiB remains for a bounded native build. Free space before capturing this app."
            )
        projects = list(args.repo.glob("*.xcodeproj"))
        if len(projects) != 1:
            raise RuntimeError(
                "Expected one generated Xcode project in the configured app repository."
            )
        command = [
            "xcodebuild",
            "-project",
            str(projects[0]),
            "-scheme",
            args.scheme,
            "-configuration",
            args.configuration,
            "-sdk",
            "iphonesimulator",
            "-destination",
            "platform=iOS Simulator,id=" + udid,
            "-derivedDataPath",
            str(derived),
            "-jobs",
            "2",
            "CODE_SIGNING_ALLOWED=NO",
            "COMPILER_INDEX_STORE_ENABLE=NO",
            "build",
        ]
        build_log = cache / "capture-build.log"
        print(
            "Building the configured app once; subsequent captures reuse matching products.",
            flush=True,
        )
        with build_log.open("w") as handle:
            result = subprocess.run(
                command,
                cwd=args.repo,
                text=True,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        if result.returncode:
            raise RuntimeError("Native build failed. See " + str(build_log))
        if fingerprint(args.repo) != source_hash:
            raise RuntimeError(
                "App sources changed during the build. Retry against a stable candidate."
            )
        candidates = []
        for path in (
            derived / "Build/Products" / (args.configuration + "-iphonesimulator")
        ).glob("*.app"):
            with (path / "Info.plist").open("rb") as handle:
                if plistlib.load(handle).get("CFBundleIdentifier") == args.bundle:
                    candidates.append(path)
        if len(candidates) != 1:
            raise RuntimeError(
                "The compiled app does not match the requested bundle identity."
            )
        app = candidates[0]
        with (app / "Info.plist").open("rb") as handle:
            executable = plistlib.load(handle)["CFBundleExecutable"]
        architectures = run(["xcrun", "lipo", "-archs", str(app / executable)]).split()
        if "arm64" not in architectures:
            raise RuntimeError(
                "The compiled app does not contain an arm64 Simulator binary."
            )
        receipt = dict(
            expected,
            app=str(app),
            source_head=head,
            product_sha256=product_hash(app),
            build_log=str(build_log),
            build_command=command,
            source_branch=run(["git", "branch", "--show-current"], cwd=args.repo),
        )
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    run(["xcrun", "simctl", "install", udid, str(app)])
    run(["xcrun", "simctl", "launch", udid, args.bundle, *args.launch_arg])
    time.sleep(2)
    if args.interactive:
        control = args.output.parent / (args.output.stem + ".session")
        control.mkdir(parents=True, exist_ok=False)
        (control / "requests").mkdir()
        (control / "results").mkdir()
        (control / "ready.json").write_text(
            json.dumps(
                {
                    "udid": udid,
                    "bundle": args.bundle,
                    "source_head": head,
                    "source_sha256": source_hash,
                    "expires_seconds": 900,
                }
            )
            + "\n"
        )
        print("Interactive capture ready: " + str(control), flush=True)
        deadline = time.monotonic() + 900
        completed = set()
        while time.monotonic() < deadline:
            if (control / "DONE").exists():
                break
            for request in sorted((control / "requests").glob("*.json")):
                if request.name in completed:
                    continue
                result_path = control / "results" / request.name
                try:
                    command = json.loads(request.read_text())
                    output = Path(command["output"]).expanduser().resolve()
                    if args.repo == output or args.repo in output.parents:
                        raise ValueError(
                            "Keep captures outside the app source repository."
                        )
                    result_path.write_text(json.dumps({"status": "capturing"}) + "\n")
                    capture(
                        command.get("mode", "screenshot"),
                        output,
                        float(command.get("seconds", 4)),
                        udid,
                        receipt,
                        reusable,
                        args.launch_arg,
                        result_path,
                    )
                    result_path.write_text(
                        json.dumps({"status": "done", "file": str(output)}) + "\n"
                    )
                except Exception as exc:
                    result_path.write_text(
                        json.dumps({"status": "error", "message": str(exc)}) + "\n"
                    )
                completed.add(request.name)
            time.sleep(0.25)
        else:
            raise RuntimeError(
                "The 15-minute interactive capture lease expired; native cleanup will release it."
            )
    else:
        capture(
            args.mode,
            args.output,
            args.seconds,
            udid,
            receipt,
            reusable,
            args.launch_arg,
        )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
