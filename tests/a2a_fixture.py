"""Deterministic A2A agent backend for the integration smokes.

One file, stdlib only (http.server), mounted into a python image by
tests/docker-compose.yml. The proxy forwards invoke_agent's JSON-RPC
message/send to this service's URL (agent_card_params.url). Behavior:

- any GET  -> the agent-card JSON (agents advertise a well-known card).
- any POST -> a JSON-RPC 2.0 result Message whose text mirrors the request
  text (the parts' text joined), echoing back contextId when present.

Deterministic and side-effect free: no inference, no persistence.
"""

from __future__ import annotations

import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_PORT = 8080

_CARD: dict[str, Any] = {
    "name": "itest-echo-agent",
    "description": "Deterministic echo agent for litellm-mcp integration smokes",
    "url": f"http://a2a-fixture:{_PORT}",
    "version": "1.0.0",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": False},
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "skills": [],
}


def _collect_text(message: Any) -> str:
    """Join the text of every text part, tolerating flat and root-wrapped parts."""
    if not isinstance(message, dict):
        return ""
    texts: list[str] = []
    for part in message.get("parts", []):
        if not isinstance(part, dict):
            continue
        node = part.get("root") if isinstance(part.get("root"), dict) else part
        text = node.get("text")
        if isinstance(text, str):
            texts.append(text)
    return " ".join(texts)


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        self._send(200, _CARD)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("content-length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        req = json.loads(raw)
        message = (req.get("params") or {}).get("message") or {}
        result: dict[str, Any] = {
            "kind": "message",
            "role": "agent",
            "parts": [{"kind": "text", "text": _collect_text(message)}],
            "messageId": str(uuid.uuid4()),
        }
        context_id = message.get("contextId")
        if context_id is not None:
            result["contextId"] = context_id
        self._send(200, {"jsonrpc": "2.0", "id": req.get("id"), "result": result})

    def log_message(self, *args: Any) -> None:  # silence per-request stderr noise
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", _PORT), _Handler).serve_forever()
