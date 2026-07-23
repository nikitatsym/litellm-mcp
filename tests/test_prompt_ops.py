"""Prompt op round-trips over respx + the mandated adversarials (Step 2).

create_prompt body (omitted-vs-null), the Decision 11 update_prompt wire shape
(path id duplicated into the body), list slimming with the secret-drop
guarantee, get/delete environment passthrough, agent_daily_activity query
construction; plus the three adversarials: limit truncation is loud, an api_key
in a prompt row never survives slimming, and an unknown create_prompt param is
rejected before any HTTP call.
"""

from __future__ import annotations

import json

import pytest

from litellm_mcp import server
from litellm_mcp.tools._generated_platform import agent_daily_activity
from litellm_mcp.tools._generated_prompts import (
    create_prompt,
    delete_prompt,
    get_prompt,
    list_prompt_versions,
    list_prompts,
)
from litellm_mcp.tools.overrides import update_prompt

_PARAMS = {"prompt_integration": "dotprompt", "dotprompt_content": "---\nmodel: gpt-4o\n---\nHi"}


def _prompt_row(i: int) -> dict[str, object]:
    """A full PromptSpec row as upstream returns it, secrets included."""
    return {
        "prompt_id": f"p{i}",
        "version": 1,
        "environment": "development",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "created_by": "admin",
        "litellm_params": {"prompt_integration": "dotprompt", "api_key": "sk-secret-xxx"},
        "prompt_info": {"prompt_type": "db"},
    }


# --- create_prompt: Prompt body, omitted-vs-null ----------------------------

def test_create_prompt_body_omits_unset(client_env, respx_mock):
    # echo carries prompt_id: the promoted subset verify (Step 4) checks its presence.
    route = respx_mock.post("/prompts").respond(200, json={"prompt_id": "p1"})
    create_prompt(prompt_id="p1", litellm_params=_PARAMS)
    body = json.loads(route.calls.last.request.content)
    assert body == {"prompt_id": "p1", "litellm_params": _PARAMS}
    assert "prompt_info" not in body  # _UNSET omitted


def test_create_prompt_explicit_null_survives(client_env, respx_mock):
    route = respx_mock.post("/prompts").respond(200, json={"prompt_id": "p1"})
    create_prompt(prompt_id="p1", litellm_params=_PARAMS, prompt_info=None)
    body = json.loads(route.calls.last.request.content)
    assert "prompt_info" in body and body["prompt_info"] is None  # explicit null survives


# --- create_prompt: the promoted subset verify catches a dropped id (Step 4) ---

def test_create_prompt_verify_catches_dropped_id(client_env, respx_mock):
    respx_mock.post("/prompts").respond(200, json={"unrelated": 1})  # echo drops prompt_id
    with pytest.raises(ValueError) as ei:
        create_prompt(prompt_id="p1", litellm_params=_PARAMS)
    assert "prompt_id" in str(ei.value)


# --- update_prompt: Decision 11 wire shape (path id duplicated into the body) -

def test_update_prompt_duplicates_id_into_body(client_env, respx_mock):
    # echo carries prompt_id: the override's subset verify (Step 4) checks its presence.
    route = respx_mock.put("/prompts/p1").respond(200, json={"prompt_id": "p1.v2"})
    update_prompt(prompt_id="p1", litellm_params=_PARAMS)
    req = route.calls.last.request
    assert req.url.path == "/prompts/p1"  # path id
    body = json.loads(req.content)
    assert body["prompt_id"] == "p1"  # AND duplicated in the body
    assert body["litellm_params"] == _PARAMS


# --- list_prompts: slim + secret drop ---------------------------------------

def test_list_prompts_slims_and_drops_litellm_params(client_env, respx_mock):
    respx_mock.get("/prompts/list").respond(200, json={"prompts": [_prompt_row(0)]})
    out = list_prompts()
    row = out["data"][0]
    assert set(row) == {
        "prompt_id", "version", "environment", "created_at", "updated_at", "created_by"
    }
    assert "litellm_params" not in row  # secret-bearing field dropped from list output


def test_list_prompt_versions_uses_container(client_env, respx_mock):
    route = respx_mock.get("/prompts/p1/versions").respond(
        200, json={"prompts": [_prompt_row(0), _prompt_row(1)]}
    )
    out = list_prompt_versions(prompt_id="p1", environment="production")
    assert route.calls.last.request.url.params.get("environment") == "production"
    assert out["total"] == 2
    assert "litellm_params" not in out["data"][0]


# --- get / delete: environment passthrough ----------------------------------

def test_get_prompt_query(client_env, respx_mock):
    route = respx_mock.get("/prompts/p1").respond(200, json={"prompt_spec": {}})
    get_prompt(prompt_id="p1", environment="production")
    req = route.calls.last.request
    assert req.url.path == "/prompts/p1"
    assert req.url.params.get("environment") == "production"


def test_delete_prompt_query(client_env, respx_mock):
    route = respx_mock.delete("/prompts/p1").respond(200, json={})
    delete_prompt(prompt_id="p1", environment="staging")
    req = route.calls.last.request
    assert req.method == "DELETE"
    assert req.url.path == "/prompts/p1"
    assert req.url.params.get("environment") == "staging"


# --- agent_daily_activity: query construction -------------------------------

def test_agent_daily_activity_query(client_env, respx_mock):
    route = respx_mock.get("/agent/daily/activity").respond(
        200, json={"results": [], "metadata": {}}
    )
    agent_daily_activity(agent_ids="a1,a2", exclude_agent_ids="a3")
    params = route.calls.last.request.url.params
    assert params.get("agent_ids") == "a1,a2"
    assert params.get("exclude_agent_ids") == "a3"
    assert "model" not in params  # _UNSET omitted


# --- adversarial (1): truncation the caller cannot miss ---------------------

async def test_list_prompts_truncation_is_loud(client_env, respx_mock):
    rows = [_prompt_row(i) for i in range(3)]
    respx_mock.get("/prompts/list").respond(200, json={"prompts": rows})
    out = await server._dispatch("ListPrompts", "litellm_read", {"limit": 2})
    assert out["truncated"] is True
    assert out["total"] == 3
    assert out["returned"] == 2


# --- adversarial (2): an api_key in a prompt row never survives slimming -----

def test_list_prompts_never_leaks_api_key(client_env, respx_mock):
    respx_mock.get("/prompts/list").respond(200, json={"prompts": [_prompt_row(0)]})
    out = list_prompts()
    assert "sk-secret-xxx" not in json.dumps(out)  # secret cannot reach the caller
    assert "api_key" not in json.dumps(out)


# --- adversarial (3): unknown create_prompt param rejected before any HTTP ---

async def test_create_prompt_unknown_param_rejected(client_env, respx_mock):
    route = respx_mock.post("/prompts").respond(200, json={})
    with pytest.raises(ValueError) as ei:
        await server._dispatch(
            "CreatePrompt", "litellm_write",
            {"prompt_id": "p1", "litellm_params": _PARAMS, "bogus_field": 1},
        )
    assert "bogus_field" in str(ei.value)
    assert route.call_count == 0  # nothing reached the wire
