"""Execute / delete / admin op round-trips over respx (Step 7).

Wire assertions (body-variant URLs, list payloads, bodyless posts), the
block/unblock verify decisions, the cache_delete override, and the two mandatory
adversarials: block_key echo without `blocked` raises; cache_delete with empty
`keys` is rejected before any HTTP call.
"""

from __future__ import annotations

import json

import pytest

from litellm_mcp.tools._generated_admin import global_spend_reset
from litellm_mcp.tools._generated_delete import delete_keys
from litellm_mcp.tools._generated_execute import (
    block_customer,
    block_key,
    block_model,
    regenerate_key,
)
from litellm_mcp.tools.overrides import cache_delete

# --- regenerate_key: key in the BODY, never the URL path (Decision 9) --------

def test_regenerate_key_uses_body_variant(client_env, respx_mock):
    route = respx_mock.post("/key/regenerate").respond(200, json={"key": "sk-new"})
    out = regenerate_key(key="sk-old")
    req = route.calls.last.request
    assert req.url.path == "/key/regenerate"      # key NOT in the path
    assert "sk-old" not in str(req.url)
    payload = json.loads(req.content)
    assert payload["key"] == "sk-old"             # key rides the body
    assert out["key"] == "sk-new"


# --- delete_keys: list payload, omitted params off the wire ------------------

def test_delete_keys_sends_list_payload(client_env, respx_mock):
    # live: /key/delete returns {deleted_keys: [...]}; delete_keys now asserts its presence.
    route = respx_mock.post("/key/delete").respond(200, json={"deleted_keys": ["sk-1", "sk-2"]})
    delete_keys(keys=["sk-1", "sk-2"])
    payload = json.loads(route.calls.last.request.content)
    assert payload["keys"] == ["sk-1", "sk-2"]
    assert "key_aliases" not in payload           # omitted (_UNSET) never sent


# --- global_spend_reset: bodyless admin POST, no verify ----------------------

def test_global_spend_reset_posts_bodyless(client_env, respx_mock):
    route = respx_mock.post("/global/spend/reset").respond(200, json={})
    global_spend_reset()
    req = route.calls.last.request
    assert req.url.path == "/global/spend/reset"
    assert req.read() == b""                       # no request body


# --- block_model: subset verify on the addressing key (typed row) ------------

def test_block_model_verifies_model_id(client_env, respx_mock):
    respx_mock.post("/model/block").respond(
        200, json={"model_id": "m-1", "model_name": "x", "litellm_params": {}, "blocked": True}
    )
    assert block_model(model_id="m-1")["model_id"] == "m-1"


def test_block_model_missing_model_id_raises(client_env, respx_mock):
    respx_mock.post("/model/block").respond(200, json={"model_name": "x"})
    with pytest.raises(ValueError) as ei:
        block_model(model_id="m-1")
    assert "model_id" in str(ei.value)


# --- block_customer: present verify on the result field (typed envelope) -----

def test_block_customer_missing_blocked_users_raises(client_env, respx_mock):
    respx_mock.post("/customer/block").respond(200, json={"other": 1})
    with pytest.raises(ValueError) as ei:
        block_customer(user_ids=["u1"])
    assert "blocked_users" in str(ei.value)


# --- MANDATORY adversarial (a): block_key echo without `blocked` raises -------

def test_block_key_passes_when_blocked_present(client_env, respx_mock):
    respx_mock.post("/key/block").respond(200, json={"token": "hash", "blocked": True})
    assert block_key(key="sk-1")["blocked"] is True


def test_block_key_missing_blocked_raises(client_env, respx_mock):
    """The block echo omits the `blocked` state -> verify raises naming it. A
    green run that skips this assertion is a step failure."""
    respx_mock.post("/key/block").respond(200, json={"token": "hash", "key_alias": "k"})
    with pytest.raises(ValueError) as ei:
        block_key(key="sk-1")
    assert "blocked" in str(ei.value)


# --- cache_delete override: happy path + MANDATORY adversarial (b) -----------

def test_cache_delete_sends_only_named_keys(client_env, respx_mock):
    route = respx_mock.post("/cache/delete").respond(200, json={"status": "ok"})
    cache_delete(keys=["a", "b"])
    assert json.loads(route.calls.last.request.content) == {"keys": ["a", "b"]}


def test_cache_delete_empty_keys_rejected_before_http(client_env, respx_mock):
    """Empty `keys` is rejected by the override's own validation BEFORE any HTTP
    call; respx must see zero requests."""
    route = respx_mock.post("/cache/delete").respond(200, json={})
    with pytest.raises(ValueError) as ei:
        cache_delete(keys=[])
    assert "keys" in str(ei.value)
    assert route.call_count == 0                   # no request ever left
