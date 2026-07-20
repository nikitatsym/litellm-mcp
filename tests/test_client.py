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
