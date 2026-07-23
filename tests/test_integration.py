"""Integration smokes against a live LiteLLM proxy (tests/docker-compose.yml).

Every scenario drives the REGISTERED ops through the dispatch layer, so the
slims / _verify_response / override behavior is exactly what is under test - not
raw httpx. The one exception is scenario 8, which posts an unknown field through
the client on purpose (the tool signature would reject it before the wire).

Run:  npm run litellm:up && uv run python dev.py e2e   (then npm run litellm:down)

Decision 13: a platform area that turns out enterprise-gated or module-absent on
the OSS image raises an APIError with the documented shape (premium body OR
404/501). Those areas are asserted with `pytest.raises(APIError)` once observed
live; the checked-in lifecycles below assume the feature is present and are
narrowed to the observed reality during the live run.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Callable
from typing import Any

import pytest

import litellm_mcp.tools.helpers as helpers
from litellm_mcp.client import APIError
from litellm_mcp.config import _reset_settings
from litellm_mcp.server import _all_grouped, _dispatch, _to_pascal
from litellm_mcp.tools.helpers import _get_client, _verify_response
from litellm_mcp.tools.overrides import litellm_version

pytestmark = pytest.mark.integration

BASE_URL = os.environ.get("LITELLM_URL", "http://localhost:4010")
MASTER_KEY = os.environ.get("LITELLM_API_KEY", "sk-test-master")


@pytest.fixture(autouse=True)
def _live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the client at the compose instance for each integration test."""
    monkeypatch.setenv("LITELLM_URL", BASE_URL)
    monkeypatch.setenv("LITELLM_API_KEY", MASTER_KEY)
    _reset_settings()
    helpers._client = None


def call(op: str, **params: Any) -> Any:
    """Dispatch a registered op by snake_case name, mirroring an MCP client."""
    if op == "litellm_version":
        return litellm_version()
    pascal = _to_pascal(op)
    return asyncio.run(_dispatch(pascal, _all_grouped[pascal], params))


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _extract_id(obj: Any, *keys: str) -> Any:
    """First non-null value among `keys`, whether at the root or one dict deep."""
    for container in (obj, obj.get("data") if isinstance(obj, dict) else None):
        if not isinstance(container, dict):
            continue
        for k in keys:
            if container.get(k) is not None:
                return container[k]
    raise AssertionError(f"none of {keys} present in {obj!r}")


def _uniq(prefix: str) -> str:
    return f"itest-{prefix}-{uuid.uuid4().hex[:8]}"


def _name(prefix: str) -> str:
    # MCP server names reject '-' upstream, so this variant is hyphen-free.
    return f"itest{prefix}{uuid.uuid4().hex[:8]}"


def _assert_unknown_field_caught(send: Callable[[], Any], field: str = "itest_unknown_field") -> None:
    """The silent-drop guarantee (incus-11b disjunction): an unknown body field is
    either rejected fail-fast (APIError 400/422) or dropped from a 2xx echo, which
    _verify_response turns into a ValueError. An echo that carried the field back
    would raise neither and fail pytest.raises - exactly the drop we want to catch.
    `send` posts the bogus body and returns the echo."""
    with pytest.raises((APIError, ValueError)) as exc:
        echo = send()
        _verify_response({field: "sentinel"}, echo)
    if isinstance(exc.value, APIError):
        assert exc.value.status in (400, 422), f"expected fail-fast, got {exc.value.status}"


# --- 1. version -----------------------------------------------------------------

def test_1_version() -> None:
    result = call("litellm_version")
    assert result["mcp"]
    service = result["service"]
    # /health/readiness on v1.93.0 returns {status, db}; no version field on this image.
    assert isinstance(service, dict) and service.get("status")


# --- 2. key / team lifecycle ----------------------------------------------------

def test_2_key_team_lifecycle() -> None:
    team = call("new_team", team_alias=_uniq("team"))
    team_id = team["team_id"]
    try:
        gen = call("generate_key", team_id=team_id, key_alias=_uniq("key"))
        secret, token = gen["key"], gen["token"]
        assert secret.startswith("sk-")

        listed = call("list_keys", team_id=team_id, return_full_object=True)
        assert {"data", "total", "returned", "truncated"} <= set(listed)
        assert secret not in _dumps(listed)
        assert any(isinstance(r, dict) and r.get("token") == token for r in listed["data"])

        assert secret not in _dumps(call("key_info", key=token))

        updated = call("update_team", team_id=team_id, tpm_limit=4242)
        assert "4242" in _dumps(updated), "update_team echo should reflect the new tpm_limit"

        call("block_key", key=token)
        call("unblock_key", key=token)

        # regenerate_key is enterprise-gated on OSS v1.93.0 (Decision 13); assert
        # the documented error rather than skipping, then delete the original key.
        with pytest.raises(APIError) as exc:
            call("regenerate_key", key=token)
        assert exc.value.status in (403, 500)
        assert "enterprise" in _dumps(exc.value.body).lower()
        call("delete_keys", keys=[token])
    finally:
        call("delete_teams", team_ids=[team_id])

    assert team_id not in _dumps(call("list_teams"))


# --- 3. users / budgets ---------------------------------------------------------

def test_3_users_budgets() -> None:
    user_id = _uniq("user")
    budget_id = _uniq("budget")
    call("new_user", user_id=user_id, max_budget=10.0)
    try:
        call("new_budget", budget_id=budget_id, max_budget=5.0)
        info = call("budget_info", budgets=[budget_id])
        assert budget_id in _dumps(info)
        call("delete_budget", id=budget_id)
    finally:
        call("delete_users", user_ids=[user_id])


# --- 4. models ------------------------------------------------------------------

def test_4_models() -> None:
    name = _uniq("model")
    added = call(
        "add_model",
        model_name=name,
        litellm_params={"model": "gpt-3.5-turbo", "mock_response": "ok", "api_key": "sk-unused"},
        model_info={},
    )
    model_id = _extract_id(added, "id", "model_id")
    try:
        assert name in _dumps(call("model_info"))
        # get_model keys by public model NAME via /v1/models/{name}; the just-added
        # DB deployment is not in the router's /v1/models yet (polling lag), so
        # exercise it on the always-present config model.
        assert call("get_model", model_id="mock-gpt")["id"] == "mock-gpt"
    finally:
        call("delete_model", id=model_id)


# --- 5. spend surface -----------------------------------------------------------

def test_5_spend_surface() -> None:
    window = {"start_date": "2020-01-01", "end_date": "2030-01-01"}
    logs = call("spend_logs", **window)
    assert isinstance(logs, dict) and "data" in logs  # empty on a fresh instance, no 500
    # global_spend_report is enterprise-gated on OSS v1.93.0 (Decision 13).
    with pytest.raises(APIError) as exc:
        call("global_spend_report", **window)
    assert exc.value.status in (400, 402, 403)
    assert "enterprise" in _dumps(exc.value.body).lower()


# --- 6. MCP gateway + access groups ---------------------------------------------

def test_6_mcp_gateway() -> None:
    cred = "creds-must-not-leak-in-list"
    server = call("create_mcp_server", server_name=_name("mcp"), transport="http",
                  url="http://unreachable.invalid:9/mcp", auth_type="api_key",
                  credentials={"api_key": cred})
    server_id = _extract_id(server, "server_id", "id")
    try:
        servers = call("list_mcp_servers")
        assert cred not in _dumps(servers), "slim MCP list must never carry credentials"
        assert server_id in _dumps(servers)

        health = call("mcp_server_health", server_ids=[server_id])
        rows = health if isinstance(health, list) else health.get("data", [])
        statuses = {r.get("status") for r in rows if isinstance(r, dict)}
        assert server_id in _dumps(health)
        assert "healthy" not in statuses and "connected" not in statuses  # url is unreachable

        grp = call("create_access_group", access_group_name=_uniq("grp"),
                   access_mcp_server_ids=[server_id])
        grp_id = _extract_id(grp, "access_group_id", "id", "access_group_name")
        assert grp_id in _dumps(call("list_access_groups"))
        call("delete_access_group", access_group_id=grp_id)
    finally:
        call("delete_mcp_server", server_id=server_id)


# --- 7. platform lifecycles (narrowed to observed gates during the live run) ----

def test_7_platform_lifecycles() -> None:
    tag = uuid.uuid4().hex[:8]

    pol_name = f"itest-pol-{tag}"
    pol = call("create_policy", policy_name=pol_name, description="itest")
    try:
        att = call("create_policy_attachment", policy_name=pol_name, scope="*")
        call("resolve_policies", force_sync=True)
        call("delete_policy_attachment", attachment_id=_extract_id(att, "attachment_id", "id"))
    finally:
        call("delete_policy", policy_id=_extract_id(pol, "policy_id", "id"))

    # evals: create needs a real OpenAI backend key on this image (Decision 13);
    # we configure no provider keys, so the write is accepted then fails at the
    # OpenAI connection - assert that documented error rather than skipping.
    with pytest.raises(APIError) as exc:
        call("create_eval", name=f"itest-eval-{tag}",
             data_source_config={"type": "custom", "item_schema": {"type": "object"}},
             testing_criteria=[{"type": "label_model", "name": "grade",
                                "labels": ["good", "bad"], "passing_labels": ["good"],
                                "model": "mock-gpt",
                                "input": [{"role": "user", "content": "{{item.q}}"}]}])
    assert "openai" in _dumps(exc.value.body).lower() or exc.value.status in (404, 501)

    ag = call("create_agent", agent_name=f"itest-agent-{tag}",
              agent_card_params={"name": f"itest-agent-{tag}", "description": "itest",
                                 "url": "http://unreachable.invalid:9/a2a"})
    call("list_agents")
    call("get_agent", agent_id=_extract_id(ag, "agent_id", "id"))

    run = call("create_workflow_run", workflow_type="itest", input={"seed": 1})
    run_id = _extract_id(run, "run_id", "id")
    call("append_workflow_event", run_id=run_id, event_type="started", step_name="s1",
         data={"k": "v"})
    call("list_workflow_events", run_id=run_id)
    call("update_workflow_run", run_id=run_id, status="completed")

    call("cloudzero_settings")


# --- 8. adversarial silent-drop (incus-11b disjunction) -------------------------

def test_8_update_team_silent_drop() -> None:
    team = call("new_team", team_alias=_uniq("drop"))
    team_id = team["team_id"]
    bogus = {"team_id": team_id, "itest_unknown_field": "sentinel"}
    try:
        _assert_unknown_field_caught(lambda: _get_client().post("/team/update", json=bogus))
    finally:
        call("delete_teams", team_ids=[team_id])


# --- 9. adversarial contract: secrets appear once, credentials never in lists ---

def test_9_secret_contract() -> None:
    team = call("new_team", team_alias=_uniq("secret"))
    team_id = team["team_id"]
    try:
        gen = call("generate_key", team_id=team_id, key_alias=_uniq("sec"))
        secret, token = gen["key"], gen["token"]
        assert secret.startswith("sk-") and secret != token

        assert secret not in _dumps(call("list_keys", team_id=team_id, return_full_object=True))
        assert secret not in _dumps(call("key_info", key=token))

        # regenerate_key is enterprise-gated (Decision 13); the original key's
        # secret contract still holds - assert the gate, then delete the key.
        with pytest.raises(APIError) as exc:
            call("regenerate_key", key=token)
        assert "enterprise" in _dumps(exc.value.body).lower()
        call("delete_keys", keys=[token])

        cred = "sekret-cred-should-not-surface"
        srv = call("create_mcp_server", server_name=_name("secmcp"), transport="http",
                   url="http://unreachable.invalid:9/mcp", auth_type="api_key",
                   credentials={"api_key": cred})
        try:
            assert cred not in _dumps(call("list_mcp_servers"))
        finally:
            call("delete_mcp_server", server_id=_extract_id(srv, "server_id", "id"))
    finally:
        call("delete_teams", team_ids=[team_id])


# --- 10. prompt lifecycle -------------------------------------------------------

# The config model's fixed mock reply (mirrors tests/litellm-config.yaml).
_MOCK_RESPONSE = "Mock response from the litellm-mcp integration harness."


def _dotprompt(body: str) -> str:
    return f"---\nmodel: mock-gpt\n---\n{body}"


def test_10_prompt_lifecycle() -> None:
    pid = _uniq("prompt")
    params = {"prompt_integration": "dotprompt", "dotprompt_content": _dotprompt("Hello {{name}}")}
    call("create_prompt", prompt_id=pid, litellm_params=params)
    try:
        # list_prompts shows it, slimmed - secret-bearing litellm_params dropped.
        listed = call("list_prompts", limit=0)  # limit=0: no client-side truncation
        assert pid in _dumps(listed)
        assert "litellm_params" not in _dumps(listed)
        assert "dotprompt_content" not in _dumps(listed)

        assert pid in _dumps(call("get_prompt", prompt_id=pid))

        # PUT creates a NEW version (Decision 11 wire shape, live) and verifies its echo.
        params2 = {"prompt_integration": "dotprompt", "dotprompt_content": _dotprompt("Updated {{name}}")}
        call("update_prompt", prompt_id=pid, litellm_params=params2)

        versions = call("list_prompt_versions", prompt_id=pid)
        assert versions["total"] >= 2  # v1 + v2 both stored

        # patch_prompt echo is subset-verified (promoted from no_verify this step).
        params3 = {"prompt_integration": "dotprompt", "dotprompt_content": _dotprompt("Patched {{name}}")}
        call("patch_prompt", prompt_id=pid, litellm_params=params3)
    finally:
        call("delete_prompt", prompt_id=pid)
    assert pid not in _dumps(call("list_prompts", limit=0))


# --- 11. prompt attach to a key (enterprise-gated on OSS v1.93.0, Decision 13) --

def test_11_prompt_attach_gated() -> None:
    pid = _uniq("attach")
    params = {"prompt_integration": "dotprompt", "dotprompt_content": _dotprompt("Hi")}
    call("create_prompt", prompt_id=pid, litellm_params=params)
    try:
        # Attaching prompts to a key is an Enterprise feature on this image; the
        # key is never minted. Assert the documented gate rather than skipping.
        with pytest.raises(APIError) as exc:
            call("generate_key", key_alias=_uniq("pkey"), prompts=[pid])
        assert exc.value.status in (403, 500)
        assert "enterprise" in _dumps(exc.value.body).lower()
    finally:
        call("delete_prompt", prompt_id=pid)


# --- 12. test_prompt live: deterministic mock stream collected client-side ------

def test_12_test_prompt_live() -> None:
    out = call("test_prompt", dotprompt_content=_dotprompt("Say hi to {{name}}"),
               prompt_variables={"name": "Ada"})
    assert out["truncated"] is False
    assert out["model"] == "mock-gpt"
    assert out["text"] == _MOCK_RESPONSE  # the whole SSE stream collected into text


# --- 13. agent loop: create -> card -> invoke -> activity -> delete -------------

def test_13_agent_loop() -> None:
    tag = uuid.uuid4().hex[:8]
    ag = call("create_agent", agent_name=f"itestagent{tag}",
              agent_card_params={"name": f"itestagent{tag}", "description": "itest",
                                 "url": "http://a2a-fixture:8080"})
    agent_id = _extract_id(ag, "agent_id", "id")
    try:
        card = call("get_agent_card", agent_id=agent_id)
        assert isinstance(card, dict) and card.get("name")

        # convenience text form: the fixture mirrors the request text back.
        ping = f"ping-{tag}"
        out = call("invoke_agent", agent_id=agent_id, text=ping)
        assert out["truncated"] is False
        assert ping in _dumps(out["result"])

        # full message form with an explicit contextId - passthrough proven live.
        ctx_ping = f"ctxping-{tag}"
        msg = {"role": "user", "parts": [{"kind": "text", "text": ctx_ping}],
               "messageId": uuid.uuid4().hex, "contextId": "ctx-itest"}
        out2 = call("invoke_agent", agent_id=agent_id, message=msg)
        assert ctx_ping in _dumps(out2["result"])
        assert "ctx-itest" in _dumps(out2["result"])

        # user_daily_activity-shaped envelope; a $0 mock invoke may leave results empty.
        activity = call("agent_daily_activity", start_date="2020-01-01",
                        end_date="2030-01-01", agent_ids=agent_id)
        assert {"results", "metadata"} <= set(activity)
    finally:
        call("delete_agent", agent_id=agent_id)

    # Adversarial: invoking the deleted agent surfaces an agent-not-found error
    # (HTTP 404 carrying a JSON-RPC error body, or a JSON-RPC error at HTTP 200).
    with pytest.raises((APIError, ValueError)) as exc:
        call("invoke_agent", agent_id=agent_id, text="after-delete")
    detail = exc.value.body if isinstance(exc.value, APIError) else str(exc.value)
    assert "not found" in _dumps(detail).lower()


# --- 14. adversarial silent-drop on patch_prompt (once promoted to subset) ------

def test_14_patch_prompt_silent_drop() -> None:
    pid = _uniq("drop")
    params = {"prompt_integration": "dotprompt", "dotprompt_content": _dotprompt("Hi")}
    call("create_prompt", prompt_id=pid, litellm_params=params)
    bogus = {"litellm_params": params, "itest_unknown_field": "sentinel"}
    try:
        _assert_unknown_field_caught(lambda: _get_client().patch(f"/prompts/{pid}", json=bogus))
    finally:
        call("delete_prompt", prompt_id=pid)
