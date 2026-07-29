"""Read-op round-trips over respx: URL/query construction, slim + truncation,
and the three hand-written overrides.

Ops are called directly for wire assertions and through `_dispatch` for
validation (unknown params, caller-visible truncation).
"""

from __future__ import annotations

import httpx
import pytest

from litellm_mcp import server
from litellm_mcp.tools._generated_read_core import (
    list_keys,
    list_organizations,
)
from litellm_mcp.tools._generated_read_infra import list_guardrails, model_info
from litellm_mcp.tools.overrides import health, key_health, model_cost_map

# --- query construction: _UNSET omitted, explicit values present -----------

def test_query_construction_drops_unset(client_env, respx_mock):
    route = respx_mock.get("/organization/list").respond(200, json=[])
    list_organizations(org_id="org-1")
    params = route.calls.last.request.url.params
    assert params.get("org_id") == "org-1"
    assert "org_alias" not in params  # omitted (_UNSET) never hits the wire


# --- bare-array slim: projects rows, truncates, reports counts -------------

def test_bare_list_slims_and_truncates(client_env, respx_mock):
    rows = [
        {
            "organization_id": f"o{i}",
            "organization_alias": "acme",
            "spend": 1.0,
            "models": [],
            "created_at": "2026-01-01",
            "metadata": {"secret": "x"},  # not in the slim set
        }
        for i in range(25)
    ]
    respx_mock.get("/organization/list").respond(200, json=rows)
    out = list_organizations()
    assert out["total"] == 25
    assert out["returned"] == 20
    assert out["truncated"] is True
    assert set(out["data"][0]) == {
        "organization_id", "organization_alias", "spend", "models", "created_at"
    }
    assert "metadata" not in out["data"][0]  # secret-ish field stripped


# --- envelope slim: container extracted, server counts kept as page_info ----

def test_envelope_container_and_page_info(client_env, respx_mock):
    keys = [{"token": f"h{i}", "spend": i, "key_name": "k"} for i in range(3)]
    respx_mock.get("/key/list").respond(
        200, json={"keys": keys, "total_count": 42, "current_page": 1, "total_pages": 21}
    )
    out = list_keys()
    assert out["total"] == 3
    assert out["truncated"] is False
    assert out["page_info"]["total_count"] == 42  # server-side count survives
    assert set(out["data"][0]) <= {"token", "spend", "key_name"}


# --- adversarial: a truncation the caller cannot miss ----------------------

async def test_list_keys_truncation_is_loud(client_env, respx_mock):
    keys = [{"token": f"h{i}"} for i in range(3)]
    respx_mock.get("/key/list").respond(200, json={"keys": keys})
    out = await server._dispatch("ListKeys", "litellm_read", {"limit": 2})
    assert out["truncated"] is True
    assert out["total"] == 3
    assert out["returned"] == 2


# --- adversarial: unknown param rejected, pointed at schema -----------------

async def test_unknown_param_rejected(client_env, respx_mock):
    respx_mock.get("/key/list").respond(200, json={"keys": []})
    with pytest.raises(ValueError) as ei:
        await server._dispatch("ListKeys", "litellm_read", {"bogus_filter": 1})
    msg = str(ei.value)
    assert "bogus_filter" in msg
    assert "schema" in msg  # steers the caller to operation='schema'


# --- no_slim op returns the upstream payload verbatim ----------------------

def test_no_slim_returns_raw(client_env, respx_mock):
    payload = {"guardrails": [{"guardrail_id": "g1", "config": {"big": "blob"}}]}
    respx_mock.get("/v2/guardrails/list").respond(200, json=payload)
    assert list_guardrails() == payload  # no truncation wrapper


# --- model_info: untyped {"data": [...]} envelope + camelCase params --------

def test_model_info_container_and_camelcase(client_env, respx_mock):
    rows = [{"model_name": f"m{i}", "litellm_model": "x", "extra": 1} for i in range(25)]
    route = respx_mock.get("/v2/model/info").respond(200, json={"data": rows})
    out = model_info(modelId="dep-1")
    assert route.calls.last.request.url.params.get("modelId") == "dep-1"
    assert out["total"] == 25
    assert out["returned"] == 20
    assert "extra" not in out["data"][0]  # slimmed to _SLIM_MODEL


# --- override: model_cost_map filters by substring and truncates ------------

def test_model_cost_map_filters_and_truncates(client_env, respx_mock):
    cost = {
        "gpt-4o": {"input_cost_per_token": 1},
        "gpt-4o-mini": {"input_cost_per_token": 2},
        "claude-opus": {"input_cost_per_token": 3},
    }
    respx_mock.get("/public/litellm_model_cost_map").respond(200, json=cost)
    out = model_cost_map(filter="gpt", limit=1)
    assert out["total"] == 2  # only the two gpt models matched
    assert out["returned"] == 1
    assert out["truncated"] is True
    assert all("gpt" in name for name in out["data"])


# --- override: health routes the per-call timeout to httpx ------------------

def _capture_read_timeouts(respx_mock) -> list[float]:
    """Mock GET /health and record the httpx read timeout of each call."""
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json={})

    respx_mock.get("/health").mock(side_effect=handler)
    return seen


def test_health_routes_timeout(client_env, respx_mock):
    seen = _capture_read_timeouts(respx_mock)
    health(timeout=5.0)
    assert seen[0] == 5.0


def test_health_default_timeout_is_120(client_env, respx_mock):
    seen = _capture_read_timeouts(respx_mock)
    health()
    assert seen[0] == 120.0


# --- override: key_health probes the given key as the bearer ----------------

def test_key_health_sends_probed_key_as_bearer(client_env, respx_mock):
    route = respx_mock.post("/key/health").respond(200, json={"key": "healthy"})
    key_health("sk-probed-123")
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer sk-probed-123"
    assert req.read() == b""  # bodyless probe
