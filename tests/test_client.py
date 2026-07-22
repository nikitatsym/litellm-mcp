"""Client contract tests: auth, error surfacing, response mapping, and the
two additions this surface requires (delete-with-body, per-call auth override).
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

from litellm_mcp.client import APIError, LiteLLMClient

BASE = "https://litellm.test"


def _client() -> LiteLLMClient:
    # Constructed inside the active respx context so httpx traffic is mocked.
    return LiteLLMClient(base_url=BASE, api_key="sk-test")


def test_auth_header_sent(respx_mock):
    route = respx_mock.get("/key/list").respond(200, json={"keys": []})
    _client().get("/key/list")
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-test"


def test_204_returns_none(respx_mock):
    respx_mock.delete("/key/1").respond(204)
    assert _client().delete("/key/1") is None


def test_empty_body_returns_none(respx_mock):
    respx_mock.get("/anything").respond(200)
    assert _client().get("/anything") is None


def test_apierror_carries_status_method_path_body(respx_mock):
    respx_mock.get("/boom").respond(500, json={"error": "kaboom"})
    with pytest.raises(APIError) as ei:
        _client().get("/boom")
    err = ei.value
    assert err.status == 500
    assert err.method == "GET"
    assert err.path == "/boom"
    assert err.body == {"error": "kaboom"}


def test_apierror_body_fidelity(respx_mock):
    """Adversarial: a 400 with a structured JSON error body must surface that
    body verbatim, not a generic message."""
    body = {
        "error": {
            "message": "budget_id 'team-x' already exists",
            "type": "bad_request",
            "code": "400",
        }
    }
    respx_mock.post("/budget/new").respond(400, json=body)
    with pytest.raises(APIError) as ei:
        _client().post("/budget/new", json={"budget_id": "team-x"})
    assert ei.value.body == body
    # The verbatim upstream message reaches the exception string, not a stub.
    assert "budget_id 'team-x' already exists" in str(ei.value)


def test_delete_sends_json_body(respx_mock):
    route = respx_mock.delete("/organization/delete").respond(200, json={"deleted": True})
    _client().delete("/organization/delete", json={"organization_ids": ["org-1"]})
    sent = _json.loads(route.calls.last.request.content)
    assert sent == {"organization_ids": ["org-1"]}


def test_per_call_timeout_reaches_httpx(respx_mock):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout"))
        return httpx.Response(200, json={})

    respx_mock.get("/health").mock(side_effect=handler)
    c = _client()
    c.get("/health", timeout=120.0)
    c.get("/health")
    assert seen[0]["read"] == 120.0  # per-call override reaches httpx
    assert seen[1]["read"] == 30.0   # omitted -> client default, not "no timeout"


def test_per_call_auth_override_scoped_to_one_call(respx_mock):
    """key_health-style: the probed key becomes the bearer for one call only,
    then the default key is used again."""
    probe = respx_mock.post("/key/health").respond(200, json={"healthy": True})
    listing = respx_mock.get("/key/list").respond(200, json=[])
    c = _client()
    c.post("/key/health", auth="sk-probed")
    assert probe.calls.last.request.headers["Authorization"] == "Bearer sk-probed"
    c.get("/key/list")
    assert listing.calls.last.request.headers["Authorization"] == "Bearer sk-test"


# --- post_sse: the Decision 12 streaming contract ---------------------------

_SSE_CT = {"content-type": "text/event-stream"}


def _sse_body(*events: str) -> str:
    """Render SSE `data:` blocks (each event is the raw payload after 'data: ')."""
    return "".join(f"data: {e}\n\n" for e in events)


class _RecordingStream(httpx.SyncByteStream):
    """A byte stream that records how many chunks were pulled and whether it
    was closed - so a test can prove the client released it early."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.pulled = 0
        self.closed = False

    def __iter__(self):
        for chunk in self._chunks:
            self.pulled += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


def test_post_sse_clean_done_yields_each_data_dict(respx_mock):
    body = _sse_body('{"i": 0}', '{"i": 1}', "[DONE]")
    respx_mock.post("/prompts/test").respond(200, headers=_SSE_CT, content=body)
    with _client().post_sse("/prompts/test", json={}) as events:
        got = list(events)
    assert got == [{"i": 0}, {"i": 1}]


def test_post_sse_non_2xx_raises_apierror_with_body(respx_mock):
    respx_mock.post("/prompts/test").respond(400, json={"error": "no model in frontmatter"})
    with pytest.raises(APIError) as ei:
        with _client().post_sse("/prompts/test", json={}):
            pass
    assert ei.value.status == 400
    assert ei.value.body == {"error": "no model in frontmatter"}


def test_post_sse_2xx_non_stream_raises_with_payload_preview(respx_mock):
    """Upstream documents 'always streamed'; a plain-JSON 200 is a contract
    change to surface, carrying the payload preview (Decision 2)."""
    respx_mock.post("/prompts/test").respond(
        200, headers={"content-type": "application/json"}, content='{"unexpected": "json"}'
    )
    with pytest.raises(APIError) as ei:
        with _client().post_sse("/prompts/test", json={}):
            pass
    assert ei.value.status == 200
    assert "unexpected" in ei.value.body


def test_post_sse_bad_json_chunk_raises(respx_mock):
    body = _sse_body('{"ok": 1}', "not-json-at-all", "[DONE]")
    respx_mock.post("/prompts/test").respond(200, headers=_SSE_CT, content=body)
    with pytest.raises(APIError):
        with _client().post_sse("/prompts/test", json={}) as events:
            list(events)


def test_post_sse_premature_eof_raises(respx_mock):
    """No [DONE] terminus: an incomplete stream is a failed call, not a short
    answer."""
    body = _sse_body('{"i": 0}', '{"i": 1}')  # no [DONE]
    respx_mock.post("/prompts/test").respond(200, headers=_SSE_CT, content=body)
    with pytest.raises(APIError) as ei:
        with _client().post_sse("/prompts/test", json={}) as events:
            list(events)
    assert "[DONE]" in str(ei.value)


def test_post_sse_cap_break_releases_stream_without_reading_to_done():
    """Adversarial: a consumer that breaks mid-stream (test_prompt's cap-stop)
    must release the HTTP response WITHOUT reading through to [DONE]."""
    chunks = [f"data: {{\"i\": {i}}}\n\n".encode() for i in range(4)] + [b"data: [DONE]\n\n"]
    stream = _RecordingStream(chunks)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=_SSE_CT, stream=stream)

    c = LiteLLMClient(base_url=BASE, api_key="sk-test", transport=httpx.MockTransport(handler))
    seen: list[dict] = []
    with c.post_sse("/prompts/test", json={}) as events:
        for event in events:
            seen.append(event)
            break  # cap-stop after the first event

    assert seen == [{"i": 0}]
    assert stream.closed is True  # the with-block closed the response
    assert stream.pulled < len(chunks)  # we never read through to [DONE]
