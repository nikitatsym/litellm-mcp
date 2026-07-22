"""Platform op round-trips over respx + the two mandatory adversarials (Step 8).

create_policy -> create_policy_attachment flow, the create_eval_run override,
append_workflow_event, and cloudzero_dry_run wire construction; the scope-drop
verify raise; and the version_status Literal rejected by Pydantic before any HTTP
call.
"""

from __future__ import annotations

import json

import pytest

from litellm_mcp import server
from litellm_mcp.tools._generated_platform import (
    append_workflow_event,
    cloudzero_dry_run,
    create_policy,
    create_policy_attachment,
)
from litellm_mcp.tools.overrides import create_eval_run


# --- create_policy -> create_policy_attachment flow -------------------------

def test_create_policy_then_attachment_flow(client_env, respx_mock):
    respx_mock.post("/policies").respond(200, json={"policy_id": "pol-1", "policy_name": "p1"})
    att = respx_mock.post("/policies/attachments").respond(
        200,
        json={"attachment_id": "att-1", "policy_name": "p1", "scope": "*", "teams": ["t1"]},
    )
    create_policy(policy_name="p1")
    create_policy_attachment(policy_name="p1", scope="*", teams=["t1"])
    req = att.calls.last.request
    assert req.url.path == "/policies/attachments"
    assert json.loads(req.content) == {"policy_name": "p1", "scope": "*", "teams": ["t1"]}


# --- create_eval_run override: nested eval path + body ----------------------

def test_create_eval_run_wire(client_env, respx_mock):
    route = respx_mock.post("/v1/evals/ev-1/runs").respond(
        200,
        json={"id": "run-1", "name": "r1", "status": "queued", "eval_id": "ev-1",
              "data_source": {}, "created_at": 1},
    )
    create_eval_run(eval_id="ev-1", data_source={"type": "responses"}, name="r1")
    req = route.calls.last.request
    assert req.url.path == "/v1/evals/ev-1/runs"
    body = json.loads(req.content)
    assert body["data_source"] == {"type": "responses"}
    assert body["name"] == "r1"


# --- append_workflow_event: nested run_id path + body -----------------------

def test_append_workflow_event_wire(client_env, respx_mock):
    # live: the event row echoes the sent fields; append_workflow_event now verifies a subset.
    echo = {"event_type": "step", "step_name": "s1", "data": {"k": "v"}}
    route = respx_mock.post("/v1/workflows/runs/wf-1/events").respond(200, json=echo)
    append_workflow_event(run_id="wf-1", event_type="step", step_name="s1", data={"k": "v"})
    req = route.calls.last.request
    assert req.url.path == "/v1/workflows/runs/wf-1/events"
    assert json.loads(req.content) == {"event_type": "step", "step_name": "s1", "data": {"k": "v"}}


# --- cloudzero_dry_run: POST-but-read body ----------------------------------

def test_cloudzero_dry_run_wire(client_env, respx_mock):
    route = respx_mock.post("/cloudzero/dry-run").respond(200, json={"message": "ok", "status": "ok"})
    cloudzero_dry_run(limit=10, operation="sum")
    req = route.calls.last.request
    assert req.url.path == "/cloudzero/dry-run"
    assert json.loads(req.content) == {"limit": 10, "operation": "sum"}


# --- adversarial (a): attachment echo drops the sent scope -> verify raises --

def test_attachment_scope_drop_raises(client_env, respx_mock):
    # Echo omits `scope` although it was sent -> _verify_response must name it.
    respx_mock.post("/policies/attachments").respond(
        200, json={"attachment_id": "att-1", "policy_name": "p1"}
    )
    with pytest.raises(ValueError) as ei:
        create_policy_attachment(policy_name="p1", scope="*")
    assert "scope" in str(ei.value)


# --- adversarial (b): unknown version_status rejected before any HTTP call ---

async def test_version_status_unknown_enum_rejected_pre_http(client_env, respx_mock):
    route = respx_mock.put("/policies/pol-1/status").respond(200, json={})
    with pytest.raises(ValueError) as ei:
        await server._dispatch(
            "UpdatePolicyVersionStatus", "litellm_write",
            {"policy_id": "pol-1", "version_status": "active"},
        )
    assert "version_status" in str(ei.value)
    assert route.call_count == 0            # Pydantic rejected the Literal
    assert len(respx_mock.calls) == 0       # nothing reached the wire


async def test_version_status_valid_enum_reaches_wire(client_env, respx_mock):
    route = respx_mock.put("/policies/pol-1/status").respond(
        200,
        json={"policy_id": "pol-1", "policy_name": "p1", "version_status": "production"},
    )
    await server._dispatch(
        "UpdatePolicyVersionStatus", "litellm_write",
        {"policy_id": "pol-1", "version_status": "production"},
    )
    assert route.call_count == 1
    assert json.loads(route.calls.last.request.content)["version_status"] == "production"
