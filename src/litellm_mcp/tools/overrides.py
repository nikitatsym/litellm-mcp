"""Hand-written ops, outside the generated inventory.

ROOT `litellm_version` plus the ops listed in `codegen/overrides.py` that need
bespoke logic the emitter cannot express. Every non-ROOT op here MUST be listed
in `codegen/overrides.py` (else the generator would also emit it - the reverse
dedupe gate catches that). Overrides follow the same rules generated ops get:
`_UNSET` semantics, `Annotated[..., Field(description=...)]`, slims where they
apply. The write/execute/eval overrides land in Steps 6-8.
"""

from __future__ import annotations

import importlib.metadata
from typing import Annotated, Any, cast

from pydantic import Field

from ..registry import ROOT, _UNSET, _op
from .groups import litellm_read
from .helpers import _get_client, _qp


@_op(ROOT)
def litellm_version() -> dict[str, Any]:
    """Get the MCP server version and the LiteLLM service readiness.

    `mcp` is this package's version. `service` is GET /health/readiness,
    which carries the running LiteLLM version and database status.
    """
    return {
        "mcp": importlib.metadata.version("litellm-mcp"),
        "service": _get_client().get("/health/readiness"),
    }


@_op(litellm_read)
def key_health(
    key: Annotated[
        str, Field(description="Virtual key to probe; sent as the bearer for this one call.")
    ],
) -> Any:
    """Check a virtual key's health by using it as the bearer for this call.

    Upstream POST /key/health probes the CALLING key and takes no body, so the
    given key is sent as the Authorization bearer for this one call only; every
    other call still uses the server-configured admin key.
    """
    return _get_client().post("/key/health", auth=key)


@_op(litellm_read)
def health(
    model: Annotated[
        str | None, Field(description="Probe only this public model name; omit to probe all.")
    ] = cast(str | None, _UNSET),
    model_id: Annotated[
        str | None, Field(description="Probe only this deployment ID.")
    ] = cast(str | None, _UNSET),
    timeout: Annotated[
        float,
        Field(description="Per-call HTTP timeout in seconds; the probe reaches every deployment and can be slow."),
    ] = 120.0,
) -> Any:
    """Probe configured model deployments and report each healthy or unhealthy.

    This is the one slow management call (it reaches out to every deployment),
    so `timeout` defaults to 120s and is routed to httpx for this call only.
    """
    return _get_client().get(
        "/health", params=_qp(model=model, model_id=model_id), timeout=timeout
    )


@_op(litellm_read)
def model_cost_map(
    filter: Annotated[
        str | None,
        Field(description="Case-insensitive substring; keep only model names containing it."),
    ] = cast(str | None, _UNSET),
    limit: Annotated[
        int, Field(description="Max models returned after filtering.")
    ] = 20,
) -> Any:
    """Look up per-model pricing and context limits from the LiteLLM cost map.

    The upstream map covers thousands of models; this returns a filtered,
    truncated slice keyed by model name, with counts so the caller cannot miss
    that data was cut. Pass `filter` to narrow by model-name substring.
    """
    cost_map = _get_client().get("/public/litellm_model_cost_map")
    if filter:
        needle = filter.lower()
        cost_map = {k: v for k, v in cost_map.items() if needle in k.lower()}
    total = len(cost_map)
    kept = dict(list(cost_map.items())[:limit]) if limit > 0 else cost_map
    return {
        "data": kept,
        "total": total,
        "returned": len(kept),
        "truncated": total > len(kept),
    }
