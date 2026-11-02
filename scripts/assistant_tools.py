"""Project-scoped MCP stdio adapter for the local editorial assistant."""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MAX_LINE = 2 * 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024
TOOL_PATH = re.compile(r"/api/projects/[a-f0-9]{12}/assistant/tools\Z")


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def endpoint():
    raw = os.environ.get("REELS_FACTORY_TOOL_URL", "")
    parsed = urlsplit(raw)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid assistant tool endpoint.") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not TOOL_PATH.fullmatch(parsed.path)
        or parsed.netloc != f"{parsed.hostname}:{port}"
    ):
        raise ValueError("Invalid assistant tool endpoint.")
    return raw


def definitions():
    from aiedit.assistant import tool_definitions

    return tool_definitions()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def tool_call(name, arguments):
    if not isinstance(name, str) or not isinstance(arguments, dict):
        raise RpcError(-32602, "Invalid tool call parameters.")
    if name not in {item["name"] for item in definitions()}:
        raise RpcError(-32602, "Unknown assistant tool.")
    url = endpoint()
    token = os.environ.get("REELS_FACTORY_TOOL_TOKEN", "")
    if not token or "\n" in token or "\r" in token:
        raise ValueError("Assistant tool credential is unavailable.")
    payload = json.dumps({"name": name, "arguments": arguments}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with OPENER.open(request, timeout=180) as response:
            data = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        # The backend may return useful validation detail; never echo headers or tokens.
        detail = exc.read(min(MAX_RESPONSE, 8192)).decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except (ValueError, AttributeError):
            pass
        return {
            "content": [{"type": "text", "text": str(detail)[:1800]}],
            "isError": True,
        }
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Local assistant tool unavailable: {type(exc).__name__}.",
                }
            ],
            "isError": True,
        }
    if len(data) > MAX_RESPONSE:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Assistant tool response exceeded the size limit.",
                }
            ],
            "isError": True,
        }
    try:
        result = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return {
            "content": [{"type": "text", "text": "Invalid assistant tool response."}],
            "isError": True,
        }
    if not isinstance(result, dict) or not isinstance(result.get("content"), list):
        return {
            "content": [{"type": "text", "text": "Invalid assistant tool response."}],
            "isError": True,
        }
    return result


def response(message):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise RpcError(-32600, "Invalid JSON-RPC request.")
    if "id" not in message:
        return None
    request_id = message["id"]
    if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
        raise RpcError(-32600, "Invalid JSON-RPC request ID.")
    method = message.get("method")
    params = message.get("params", {})
    if not isinstance(method, str) or not isinstance(params, dict):
        raise RpcError(-32600, "Invalid JSON-RPC request.")
    if method == "initialize":
        version = params.get("protocolVersion", "2024-11-05")
        if not isinstance(version, str):
            raise RpcError(-32602, "Invalid protocol version.")
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "reels-factory-editor", "version": "1"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": definitions()}
    elif method == "tools/call":
        result = tool_call(params.get("name"), params.get("arguments", {}))
    else:
        raise RpcError(-32601, "Method not found.")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def emit(message):
    sys.stdout.write(
        json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    sys.stdout.flush()


def main():
    while True:
        raw = sys.stdin.buffer.readline(MAX_LINE + 2)
        if not raw:
            return
        if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
            if not raw.endswith(b"\n"):
                while True:
                    tail = sys.stdin.buffer.readline(MAX_LINE + 2)
                    if not tail or tail.endswith(b"\n"):
                        break
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Request too large or incomplete.",
                    },
                }
            )
            continue
        try:
            message = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error."},
                }
            )
            continue
        try:
            reply = response(message)
        except RpcError as exc:
            request_id = message.get("id") if isinstance(message, dict) else None
            if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
                request_id = None
            reply = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": exc.code, "message": str(exc)},
            }
        except (ValueError, KeyError, TypeError) as exc:
            reply = {
                "jsonrpc": "2.0",
                "id": message.get("id") if isinstance(message, dict) else None,
                "error": {"code": -32603, "message": str(exc)[:1800]},
            }
        if reply is not None:
            emit(reply)


if __name__ == "__main__":
    main()
