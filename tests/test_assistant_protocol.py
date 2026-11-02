"""MCP wire and loopback boundary tests for the editorial adapter."""

import importlib.util
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "assistant_tools.py"
SPEC = importlib.util.spec_from_file_location("assistant_tools", SCRIPT)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(
        adapter,
        "definitions",
        lambda: [
            {
                "name": "context",
                "description": "Read context",
                "inputSchema": {"type": "object"},
            }
        ],
    )


def request(method, params=None, request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def test_initialize_list_ping_and_notification(tools):
    initialized = adapter.response(
        request("initialize", {"protocolVersion": "2025-03-26"})
    )
    assert initialized["result"]["protocolVersion"] == "2025-03-26"
    assert initialized["result"]["capabilities"] == {"tools": {}}
    assert (
        adapter.response(request("initialize"))["result"]["protocolVersion"]
        == "2024-11-05"
    )
    assert (
        adapter.response(request("tools/list"))["result"]["tools"][0]["name"]
        == "context"
    )
    assert adapter.response(request("ping"))["result"] == {}
    assert (
        adapter.response({"jsonrpc": "2.0", "method": "notifications/initialized"})
        is None
    )


def test_stdio_rejects_bad_json_and_unknown_method_without_reply_to_notification(
    monkeypatch, tools
):
    input_data = (
        b"{broken\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
        + b"\n"
        + json.dumps(request("unknown", request_id="x")).encode()
        + b"\n"
    )
    monkeypatch.setattr(adapter.sys, "stdin", io.TextIOWrapper(io.BytesIO(input_data)))
    output = io.StringIO()
    monkeypatch.setattr(adapter.sys, "stdout", output)
    adapter.main()
    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(replies) == 2
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["id"] == "x" and replies[1]["error"]["code"] == -32601


def test_endpoint_rejects_non_project_urls(monkeypatch):
    valid = "http://127.0.0.1:8775/api/projects/abcdef012345/assistant/tools"
    monkeypatch.setenv("REELS_FACTORY_TOOL_URL", valid)
    assert adapter.endpoint() == valid
    for url in (
        "https://127.0.0.1:8775/api/projects/abcdef012345/assistant/tools",
        "http://example.com:8775/api/projects/abcdef012345/assistant/tools",
        "http://user:pass@127.0.0.1:8775/api/projects/abcdef012345/assistant/tools",
        valid + "?next=/elsewhere",
        valid + "#fragment",
        valid + "/extra",
        "http://127.0.0.1:8775/api/projects/ABCDEF012345/assistant/tools",
    ):
        monkeypatch.setenv("REELS_FACTORY_TOOL_URL", url)
        with pytest.raises(ValueError, match="Invalid assistant tool endpoint"):
            adapter.endpoint()


def test_tool_call_posts_only_whitelisted_name_with_bearer_token(monkeypatch, tools):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            seen.append(
                (
                    self.path,
                    self.headers.get("Authorization"),
                    json.loads(self.rfile.read(length)),
                )
            )
            body = json.dumps(
                {"content": [{"type": "text", "text": "revision 3"}], "isError": False}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv(
            "REELS_FACTORY_TOOL_URL",
            f"http://127.0.0.1:{server.server_port}/api/projects/abcdef012345/assistant/tools",
        )
        monkeypatch.setenv("REELS_FACTORY_TOOL_TOKEN", "secret-token")
        assert (
            adapter.response(
                request("tools/call", {"name": "context", "arguments": {"start": 0}})
            )["result"]["content"][0]["text"]
            == "revision 3"
        )
        assert seen == [
            (
                "/api/projects/abcdef012345/assistant/tools",
                "Bearer secret-token",
                {"name": "context", "arguments": {"start": 0}},
            )
        ]
        with pytest.raises(adapter.RpcError) as exc:
            adapter.response(request("tools/call", {"name": "shell", "arguments": {}}))
        assert exc.value.code == -32602
        assert len(seen) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_failure_is_tool_error_not_success(monkeypatch, tools):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = b'{"detail":"Revision conflict"}'
            self.send_response(409)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv(
            "REELS_FACTORY_TOOL_URL",
            f"http://127.0.0.1:{server.server_port}/api/projects/abcdef012345/assistant/tools",
        )
        monkeypatch.setenv("REELS_FACTORY_TOOL_TOKEN", "secret-token")
        result = adapter.tool_call("context", {})
        assert result == {
            "content": [{"type": "text", "text": "Revision conflict"}],
            "isError": True,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
