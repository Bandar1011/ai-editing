"""Identify trusted local media tools and their loaded runtime dependencies."""

import os
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


def stamp(path):
    path = Path(path).resolve()
    stat = path.stat()
    return (
        str(path),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def inspect(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout, result.stderr


@lru_cache(maxsize=2048)
def macho_links(image_stamp):
    path = image_stamp[0]
    code, linked, _ = inspect(["/usr/bin/otool", "-L", path])
    load_code, commands, _ = inspect(["/usr/bin/otool", "-l", path])
    if code or load_code:
        return None
    links = tuple(
        line.strip().split(" (compatibility", 1)[0]
        for line in linked.splitlines()[1:]
        if line.strip()
    )
    rpaths = tuple(
        re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset", commands)
    )
    return links, rpaths


def macho_graph(executable):
    graph, visited = {}, set()

    def expand(value, image):
        return value.replace("@loader_path", str(image.parent)).replace(
            "@executable_path", str(executable.parent)
        )

    def visit(image, inherited):
        image = image.resolve()
        state = (str(image), inherited)
        if state in visited:
            return True
        visited.add(state)
        record = macho_links(stamp(image))
        if record is None:
            return False
        links, raw_paths = record
        paths = tuple(
            dict.fromkeys(tuple(expand(p, image) for p in raw_paths) + inherited)
        )
        if any("@" in p for p in paths):
            return False
        graph[str(image)] = image
        for link in links:
            if link.startswith(("/System/Library/", "/usr/lib/")):
                # These images can live only in dyld's shared cache. The OS build
                # below identifies that runtime; do not invent a missing dylib hash.
                continue
            if link.startswith("@rpath/"):
                targets = [Path(p) / link[len("@rpath/") :] for p in paths]
                targets = [p for p in targets if p.is_file()]
            else:
                target = Path(expand(link, image))
                targets = [target] if target.is_absolute() and target.is_file() else []
            if not targets or not all(visit(target, paths) for target in targets):
                return False
        return True

    if not visit(executable, ()):
        return None
    inspected = set()
    while set(graph) - inspected:
        name = next(iter(set(graph) - inspected))
        inspected.add(name)
        image = graph[name]
        if "ggml" in image.name or "whisper" in image.name:
            for plugin in image.parent.glob("libggml*.dylib"):
                if not visit(plugin, ()):
                    return None
            for pattern in ("*.metal", "*.metallib"):
                for resource in image.parent.glob(pattern):
                    graph[str(resource)] = resource
                    inspected.add(str(resource))
    return graph


def linux_graph(executable):
    with executable.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            return None
    loader = shutil.which("ldd")
    if not loader:
        return None
    code, output, error = inspect([loader, str(executable)])
    if "statically linked" in output + error:
        return {str(executable): executable}
    if code:
        return None
    graph = {str(executable): executable}
    for line in output.splitlines():
        if "not found" in line:
            return None
        value = line.split("=>", 1)[-1].rsplit(" (", 1)[0].strip()
        if value.startswith(("linux-vdso", "linux-gate")):
            continue
        path = Path(value)
        if not path.is_absolute() or not path.is_file():
            return None
        graph[value] = path
    return graph


def runtime_files():
    return (
        [Path("/System/Library/CoreServices/SystemVersion.plist")]
        if platform.system() == "Darwin"
        else []
    )


def identity(executable, digest, key_for):
    if any(
        name.startswith(("DYLD_", "LD_", "GGML_", "WHISPER_")) for name in os.environ
    ):
        return None
    executable = Path(executable).resolve()
    try:
        if platform.system() == "Darwin":
            graph = macho_graph(executable)
            if graph is None:
                return None
        elif platform.system() == "Linux":
            graph = linux_graph(executable)
            if graph is None:
                return None
            inspected = set()
            while set(graph) - inspected:
                name = next(iter(set(graph) - inspected))
                inspected.add(name)
                image = graph[name]
                if "ggml" in image.name or "whisper" in image.name:
                    resolved = {path.resolve() for path in graph.values()}
                    for plugin in image.parent.glob("libggml*.so*"):
                        if plugin.resolve() not in resolved:
                            extra = linux_graph(plugin.resolve())
                            if extra is None:
                                return None
                            graph.update(extra)
                    for pattern in ("*.metal", "*.metallib"):
                        for resource in image.parent.glob(pattern):
                            graph[str(resource)] = resource
                            inspected.add(str(resource))
        else:
            return None
        for runtime in runtime_files():
            if not runtime.is_file():
                return None
            graph[str(runtime)] = runtime
        return key_for(
            {
                "platform": (platform.system(), platform.release(), platform.machine()),
                "images": {
                    name: {"resolved": str(path.resolve()), "sha256": digest(path)}
                    for name, path in graph.items()
                },
            }
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
