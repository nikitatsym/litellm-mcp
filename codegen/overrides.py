"""Operations implemented by hand and excluded from generated output.

Overrides cover snapshot endpoints without request bodies and operations
whose client-side behavior the emitter cannot express. Unknown operation
names are generation errors. The sync gate requires implementations for
overrides in gated modules and an inventory entry for every non-ROOT
operation in tools/overrides.py.
"""

from __future__ import annotations

from typing import Any

OVERRIDES: dict[str, dict[str, Any]] = {
    "key_health": {
        "reason": "endpoint has no requestBody in the snapshot (upstream spec gap); "
        "upstream probes the caller's key, so the op sends the given key as bearer "
        "for this one call",
        "step": 5,
    },
    "health": {
        "reason": "documented per-call timeout (default 120) routed to httpx; the "
        "generator does not express per-call timeouts",
        "step": 5,
    },
    "model_cost_map": {
        "reason": "client-side substring filter + limit + truncation metadata over "
        "the huge upstream cost map (thousands of models)",
        "step": 5,
    },
    "update_organization": {
        "reason": "endpoint has no requestBody in the snapshot (upstream spec gap); "
        "fields per LiteLLM docs",
        "step": 6,
    },
    "cache_delete": {
        "reason": "endpoint has no requestBody in the snapshot (upstream spec gap); "
        "keys list required and non-empty",
        "step": 7,
    },
    "create_eval": {
        "reason": "endpoint has no requestBody in the snapshot (upstream spec gap); "
        "body per LiteLLM/OpenAI Evals docs",
        "step": 8,
    },
    "update_eval": {
        "reason": "endpoint has no requestBody in the snapshot (upstream spec gap); "
        "body per LiteLLM/OpenAI Evals docs",
        "step": 8,
    },
    "create_eval_run": {
        "reason": "endpoint has no requestBody in the snapshot (upstream spec gap); "
        "runs consume model inference - docstring notes cost",
        "step": 8,
    },
    "update_prompt": {
        "reason": "body prompt_id collides with the path param (the generator drops "
        "the colliding body field, so the emitted op would 422) and upstream ignores "
        "the body id anyway; the op exposes one prompt_id and duplicates it into the "
        "body wire-side (Decision 11)",
        "step": 2,
    },
    "test_prompt": {
        "reason": "upstream forces stream=True and always answers an OpenAI-style SSE "
        "stream; the op collects it client-side into a bounded fixed-shape result "
        "(Decision 2), which the plain r.json() emitter cannot express",
        "step": 3,
    },
    "invoke_agent": {
        "reason": "JSON-RPC body read via request.json(), so the snapshot shows no "
        "requestBody; the op owns the message/send envelope and bounds the A2A result "
        "(Decision 4)",
        "step": 3,
    },
    "apply_guardrail": {
        "reason": "snapshot's ApplyGuardrailRequest carries language/entities but the "
        "handler never forwards them (dead params in v1.93.0); the generator has no "
        "field-exclusion knob, so the override exposes only the applied fields "
        "(guardrail-loop Decision 3)",
        "step": 2,
    },
}
