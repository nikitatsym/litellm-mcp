"""Ops implemented by hand in `tools/overrides.py`, skipped by the emitter.

Seeded in Step 4 with EXACTLY the six spec-gap ops whose snapshot endpoint has
no requestBody (upstream spec gap) - the generator cannot emit a body it does
not know, so these are hand-written. Each entry names the reason and the step
that lands the implementation. The entries stay PENDING until their module's
completeness gate turns on (Steps 5-8): the sync gate requires an override to
be implemented in `tools/overrides.py` only once its module is gated, and
conversely requires every non-ROOT `@_op` in `tools/overrides.py` to be listed
here (no silent runtime duplicate). An unknown key is a generation-time error.
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
}
