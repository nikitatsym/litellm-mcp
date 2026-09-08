from __future__ import annotations

import json

import httpx
import pytest
from mcp.types import TextContent

from litellm_mcp import server
from litellm_mcp.client import APIError
from litellm_mcp.tools import overrides


def _registered(name: str):
    return server.mcp._tool_manager._tools[name].fn


def _data(result: object) -> dict:
    """Registered tools hand the SDK a one-line JSON text block, not a dict."""
    assert isinstance(result, TextContent)
    assert "\n" not in result.text
    return json.loads(result.text)


async def _raise(exc: Exception):
    raise exc


def test_registration_preserves_sync_async_flavor():
    """MCP classifies tools with `iscoroutinefunction`; the ROOT op is sync so
    the SDK keeps its blocking HTTP call in a worker thread."""
    tools = server.mcp._tool_manager._tools

    assert tools["litellm_version"].is_async is False
    assert tools["litellm_read"].is_async is True


def test_registered_root_returns_contextual_api_error(monkeypatch):
    class BrokenClient:
        def get(self, _path: str):
            raise APIError(503, "GET", "/health/readiness?token=secret", {"detail": "unavailable"})

    monkeypatch.setattr(overrides, "_get_client", lambda: BrokenClient())

    result = _data(_registered("litellm_version")())

    assert result["error"].startswith("GET /health/readiness -> 503")
    assert "secret" not in result["error"]


def test_registered_root_preserves_success_shape(monkeypatch):
    class OkClient:
        def get(self, _path: str):
            return {"status": "healthy"}

    monkeypatch.setattr(overrides, "_get_client", lambda: OkClient())

    result = _data(_registered("litellm_version")())

    assert result["service"] == {"status": "healthy"}
    assert "mcp" in result


async def test_registered_tool_redacts_transport_query_values(monkeypatch):
    request = httpx.Request("GET", "https://litellm.example/key/info?token=secret")
    monkeypatch.setattr(
        server,
        "_dispatch",
        lambda *_args: _raise(httpx.ConnectError("connection refused", request=request)),
    )

    result = _data(await _registered("litellm_read")("KeyHealth", {}))

    assert "LiteLLM transport failure: GET /key/info: ConnectError" in result["error"]
    assert "secret" not in result["error"]
    assert "token=" not in result["error"]


async def test_registered_tool_returns_missing_parameter_error():
    result = _data(await _registered("litellm_read")("KeyHealth", {}))

    assert "Invalid params for KeyHealth" in result["error"]
    assert "key" in result["error"]


async def test_registered_tool_propagates_programming_error(monkeypatch):
    def broken(*_args: object) -> None:
        raise AttributeError("programming error")

    monkeypatch.setattr(server, "_dispatch", broken)

    with pytest.raises(AttributeError):
        await _registered("litellm_read")("KeyHealth", {})


def test_every_registered_tool_is_unstructured():
    """A tool registered without `_compact` would pretty-print and, with a typed
    return, duplicate the payload as structured content."""
    for tool in server.mcp._tool_manager.list_tools():
        assert tool.fn_metadata.output_schema is None, tool.name


async def test_call_tool_returns_single_compact_text_block():
    result = await server.mcp.call_tool("litellm_read", {"operation": "schema", "params": {}})

    assert result.structured_content is None
    (block,) = result.content
    assert isinstance(block, TextContent)
    assert "\n" not in block.text
    assert "KeyHealth" in json.loads(block.text)


def test_error_text_redacts_secret_fields():
    """Container values are redacted whole: a partial match would leave the
    tail of a list or nested dict in the reported error."""
    text = server._redact_error_text(
        {"password": ["too short", "p@ssw0rd"], "api_secret": "zzz", "detail": "keep me"}
    )

    assert "p@ssw0rd" not in text
    assert "zzz" not in text
    assert "keep me" in text
