"""Execute overrides test_prompt + invoke_agent over respx (Step 3).

test_prompt: an OpenAI-style SSE stream collected into the Decision 2 fixed
shape; the cap-stop, the 2xx non-SSE raise, and the mid-stream error event.
invoke_agent: the pinned JSON-RPC message/send envelope asserted exactly,
verbatim forwarding of message/configuration/metadata, the op-side rejections
(text+message, neither, blocking=false), a JSON-RPC error on HTTP 200, and the
whole-result bounding rules (bytes_omitted, string cap, history_omitted, the
generic DataPart/metadata walk, and the many-parts backstop stub).
"""

from __future__ import annotations

import json
import uuid

import pytest

from litellm_mcp import server
from litellm_mcp.client import APIError
# Alias: the override is named test_prompt, which pytest would else collect as a test.
from litellm_mcp.tools.overrides import invoke_agent
from litellm_mcp.tools.overrides import test_prompt as run_test_prompt

_SSE_CT = {"content-type": "text/event-stream"}
_DOTPROMPT = "---\nmodel: gpt-4o\n---\nHi {{name}}"


def _sse(*events: str) -> str:
    return "".join(f"data: {e}\n\n" for e in events)


def _chunk(
    content: str | None = None,
    model: str = "gpt-4o",
    finish: str | None = None,
    usage: dict | None = None,
) -> str:
    choice: dict = {"index": 0, "delta": {}, "finish_reason": finish}
    if content is not None:
        choice["delta"]["content"] = content
    payload: dict = {"model": model, "choices": [choice]}
    if usage is not None:
        payload["usage"] = usage
    return json.dumps(payload)


# --- test_prompt: mocked SSE -> the Decision 2 fixed shape -------------------

def test_test_prompt_collects_fixed_shape(client_env, respx_mock):
    body = _sse(
        _chunk(content="Hello "),
        _chunk(content="world"),
        _chunk(finish="stop", usage={"total_tokens": 5}),
        "[DONE]",
    )
    respx_mock.post("/prompts/test").respond(200, headers=_SSE_CT, content=body)
    out = run_test_prompt(dotprompt_content=_DOTPROMPT, prompt_variables={"name": "Ada"})
    assert out == {
        "model": "gpt-4o",
        "text": "Hello world",
        "finish_reason": "stop",
        "usage": {"total_tokens": 5},
        "truncated": False,
    }


def test_test_prompt_body_omits_unset(client_env, respx_mock):
    route = respx_mock.post("/prompts/test").respond(200, headers=_SSE_CT, content=_sse("[DONE]"))
    run_test_prompt(dotprompt_content=_DOTPROMPT)
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"dotprompt_content": _DOTPROMPT}  # prompt_variables/history omitted


# --- test_prompt adversarial (1): long stream stops at the cap --------------

def test_test_prompt_stops_at_cap_truncated(client_env, respx_mock):
    big = "x" * 5000
    chunks = [_chunk(content=big) for _ in range(5)] + ["[DONE]"]
    respx_mock.post("/prompts/test").respond(200, headers=_SSE_CT, content=_sse(*chunks))
    out = run_test_prompt(dotprompt_content=_DOTPROMPT)
    assert out["truncated"] is True
    assert len(out["text"]) == 20_000  # capped, not 25000


# --- test_prompt adversarial (2): a 2xx plain-JSON response raises -----------

def test_test_prompt_2xx_non_sse_raises(client_env, respx_mock):
    respx_mock.post("/prompts/test").respond(
        200, headers={"content-type": "application/json"}, json={"not": "streamed"}
    )
    with pytest.raises(APIError) as ei:
        run_test_prompt(dotprompt_content=_DOTPROMPT)
    assert ei.value.status == 200


# --- test_prompt adversarial (3): a mid-stream error event raises loudly -----

def test_test_prompt_streamed_error_event_raises(client_env, respx_mock):
    body = _sse(
        _chunk(content="partial"),
        json.dumps({"error": {"message": "provider exploded", "type": "server_error"}}),
        "[DONE]",
    )
    respx_mock.post("/prompts/test").respond(200, headers=_SSE_CT, content=body)
    with pytest.raises(ValueError) as ei:
        run_test_prompt(dotprompt_content=_DOTPROMPT)
    assert "provider exploded" in str(ei.value)  # upstream payload preserved


# --- invoke_agent: the pinned envelope asserted exactly ---------------------

def test_invoke_agent_pinned_text_envelope(client_env, respx_mock):
    route = respx_mock.post("/v1/a2a/a1/message/send").respond(200, json={"result": {}})
    invoke_agent(agent_id="a1", text="hello")
    env = json.loads(route.calls.last.request.content)
    assert env["jsonrpc"] == "2.0"
    assert env["method"] == "message/send"
    uuid.UUID(env["id"])  # fresh uuid4 id (raises if malformed)
    params = env["params"]
    assert set(params) == {"message", "configuration"}  # no metadata forwarded
    assert params["configuration"] == {"blocking": True}  # blocking injected
    msg = dict(params["message"])
    autofilled = msg.pop("messageId")
    uuid.UUID(autofilled)  # messageId autofilled with a uuid4
    assert msg == {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}


def test_invoke_agent_uses_supplied_message_id(client_env, respx_mock):
    route = respx_mock.post("/v1/a2a/a1/message/send").respond(200, json={"result": {}})
    invoke_agent(agent_id="a1", text="hi", message_id="fixed-id")
    env = json.loads(route.calls.last.request.content)
    assert env["params"]["message"]["messageId"] == "fixed-id"


def test_invoke_agent_forwards_message_and_config_verbatim(client_env, respx_mock):
    route = respx_mock.post("/v1/a2a/a2/message/send").respond(200, json={"result": {}})
    full_msg = {
        "role": "user",
        "parts": [{"kind": "text", "text": "x"}, {"kind": "file", "file": {"uri": "http://f"}}],
        "messageId": "caller-mid",
        "contextId": "ctx-1",
    }
    invoke_agent(
        agent_id="a2",
        message=full_msg,
        configuration={"acceptedOutputModes": ["text"]},
        metadata={"trace": "t1"},
    )
    params = json.loads(route.calls.last.request.content)["params"]
    assert params["message"] == full_msg  # forwarded verbatim
    assert params["configuration"] == {"acceptedOutputModes": ["text"], "blocking": True}
    assert params["metadata"] == {"trace": "t1"}  # forwarded verbatim


# --- invoke_agent adversarials: op-side rejections BEFORE any HTTP ----------

def test_invoke_agent_text_and_message_rejected(client_env, respx_mock):
    route = respx_mock.post("/v1/a2a/a1/message/send").respond(200, json={"result": {}})
    with pytest.raises(ValueError):
        invoke_agent(agent_id="a1", text="hi", message={"role": "user"})
    assert route.call_count == 0


def test_invoke_agent_neither_text_nor_message_rejected(client_env, respx_mock):
    route = respx_mock.post("/v1/a2a/a1/message/send").respond(200, json={"result": {}})
    with pytest.raises(ValueError):
        invoke_agent(agent_id="a1")
    assert route.call_count == 0


def test_invoke_agent_blocking_false_rejected(client_env, respx_mock):
    route = respx_mock.post("/v1/a2a/a1/message/send").respond(200, json={"result": {}})
    with pytest.raises(ValueError):
        invoke_agent(agent_id="a1", text="hi", configuration={"blocking": False})
    assert route.call_count == 0


# --- invoke_agent: a JSON-RPC error object raises even on HTTP 200 -----------

def test_invoke_agent_jsonrpc_error_raises_with_code_and_message(client_env, respx_mock):
    respx_mock.post("/v1/a2a/a1/message/send").respond(
        200, json={"jsonrpc": "2.0", "id": "x", "error": {"code": -32001, "message": "agent not found"}}
    )
    with pytest.raises(ValueError) as ei:
        invoke_agent(agent_id="a1", text="hi")
    assert "-32001" in str(ei.value)
    assert "agent not found" in str(ei.value)


# --- invoke_agent: the whole-result bounding rules --------------------------

def test_invoke_agent_bounds_fat_task(client_env, respx_mock):
    huge = "y" * 25_000
    task = {
        "kind": "task",
        "id": "t1",
        "status": {"state": "completed"},
        "artifacts": [
            {
                "artifactId": "art1",
                "parts": [
                    {"kind": "text", "text": huge},
                    {
                        "kind": "file",
                        "file": {
                            "name": "big.bin",
                            "mimeType": "application/octet-stream",
                            "uri": "http://x",
                            "bytes": "A" * 4000,
                        },
                    },
                    {"kind": "data", "data": {"blob": huge}, "metadata": {"note": huge}},
                ],
            }
        ],
        "history": [
            {"kind": "message", "role": "user", "parts": [{"kind": "text", "text": f"turn {i}"}],
             "messageId": f"m{i}"}
            for i in range(8)
        ],
    }
    respx_mock.post("/v1/a2a/a1/message/send").respond(
        200, json={"jsonrpc": "2.0", "id": "x", "result": task}
    )
    out = invoke_agent(agent_id="a1", text="hi")
    assert out["truncated"] is True
    res = out["result"]
    # history capped to the last 5 with the drop count
    assert len(res["history"]) == 5
    assert res["history_omitted"] == 3
    parts = res["artifacts"][0]["parts"]
    # ANY string over the cap truncated (text part + fat DataPart + nested metadata)
    assert len(parts[0]["text"]) == 20_000
    assert len(parts[2]["data"]["blob"]) == 20_000
    assert len(parts[2]["metadata"]["note"]) == 20_000
    # file bytes dropped, other file fields kept
    fp = parts[1]["file"]
    assert "bytes" not in fp
    assert fp["bytes_omitted"] == 4000
    assert fp["name"] == "big.bin" and fp["uri"] == "http://x"


def test_invoke_agent_backstop_stub_on_many_parts(client_env, respx_mock):
    parts = [{"kind": "text", "text": "abcdefghij" * 5} for _ in range(3000)]
    task = {"kind": "task", "id": "t1", "artifacts": [{"artifactId": "a", "parts": parts}], "history": []}
    respx_mock.post("/v1/a2a/a1/message/send").respond(200, json={"result": task})
    out = invoke_agent(agent_id="a1", text="hi")
    assert out["truncated"] is True
    res = out["result"]
    assert set(res) == {"kinds", "parts_total", "artifacts_total", "history_len", "serialized_chars"}
    assert res["parts_total"] == 3000
    assert res["artifacts_total"] == 1
    assert res["history_len"] == 0
    assert res["kinds"] == ["task", "text"]
    assert res["serialized_chars"] > 100_000


def test_invoke_agent_small_result_untouched(client_env, respx_mock):
    result = {"kind": "message", "role": "agent", "parts": [{"kind": "text", "text": "ok"}], "messageId": "m1"}
    respx_mock.post("/v1/a2a/a1/message/send").respond(200, json={"result": result})
    out = invoke_agent(agent_id="a1", text="hi")
    assert out == {"result": result, "truncated": False}


# --- invoke_agent: unknown-param dispatch rejection -------------------------

async def test_invoke_agent_unknown_param_rejected(client_env, respx_mock):
    route = respx_mock.post("/v1/a2a/a1/message/send").respond(200, json={"result": {}})
    with pytest.raises(ValueError) as ei:
        await server._dispatch(
            "InvokeAgent", "litellm_execute", {"agent_id": "a1", "text": "hi", "bogus_field": 1}
        )
    assert "bogus_field" in str(ei.value)
    assert route.call_count == 0
