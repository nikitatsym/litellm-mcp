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
from .groups import litellm_read, litellm_write
from .helpers import _get_client, _qp, _verify_response


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


@_op(litellm_write)
def update_organization(
    organization_id: Annotated[
        str, Field(description="ID of the organization to update (addressing field).")
    ],
    organization_alias: Annotated[
        str | None, Field(description="Human-readable organization name.")
    ] = cast(str | None, _UNSET),
    budget_id: Annotated[
        str | None, Field(description="ID of the budget object governing this org.")
    ] = cast(str | None, _UNSET),
    metadata: dict[str, Any] | None = cast(dict[str, Any] | None, _UNSET),
    models: Annotated[
        list[str] | None, Field(description="Model names this org may access.")
    ] = cast(list[str] | None, _UNSET),
    max_budget: Annotated[
        float | None, Field(description="Hard USD budget cap for the org.")
    ] = cast(float | None, _UNSET),
    soft_budget: Annotated[
        float | None, Field(description="USD spend that triggers an alert (no block).")
    ] = cast(float | None, _UNSET),
    tpm_limit: Annotated[
        int | None, Field(description="Org-wide tokens-per-minute cap.")
    ] = cast(int | None, _UNSET),
    rpm_limit: Annotated[
        int | None, Field(description="Org-wide requests-per-minute cap.")
    ] = cast(int | None, _UNSET),
    max_parallel_requests: int | None = cast(int | None, _UNSET),
    budget_duration: Annotated[
        str | None, Field(description="Budget reset window, e.g. '30d', '1mo'.")
    ] = cast(str | None, _UNSET),
    model_max_budget: dict[str, Any] | None = cast(dict[str, Any] | None, _UNSET),
    updated_by: str | None = cast(str | None, _UNSET),
) -> Any:
    """Update an existing organization's settings.

    Spec-gap override: PATCH /organization/update carries no requestBody in the
    snapshot, so the fields here follow the LiteLLM organization-update model.
    Only the fields you pass are changed; `organization_id` addresses the org
    and is required. Field names verified live in Step 9.
    """
    body: dict[str, Any] = {}
    if organization_id is not _UNSET:
        body["organization_id"] = organization_id
    if organization_alias is not _UNSET:
        body["organization_alias"] = organization_alias
    if budget_id is not _UNSET:
        body["budget_id"] = budget_id
    if metadata is not _UNSET:
        body["metadata"] = metadata
    if models is not _UNSET:
        body["models"] = models
    if max_budget is not _UNSET:
        body["max_budget"] = max_budget
    if soft_budget is not _UNSET:
        body["soft_budget"] = soft_budget
    if tpm_limit is not _UNSET:
        body["tpm_limit"] = tpm_limit
    if rpm_limit is not _UNSET:
        body["rpm_limit"] = rpm_limit
    if max_parallel_requests is not _UNSET:
        body["max_parallel_requests"] = max_parallel_requests
    if budget_duration is not _UNSET:
        body["budget_duration"] = budget_duration
    if model_max_budget is not _UNSET:
        body["model_max_budget"] = model_max_budget
    if updated_by is not _UNSET:
        body["updated_by"] = updated_by
    result = _get_client().patch("/organization/update", json=body)
    # LiteLLM_OrganizationTableWithMembers echoes these row fields; budget/limit
    # knobs land in the budget table, so verify only the org-row scalars/list.
    _verify_response(
        {k: body[k] for k in ("organization_id", "organization_alias", "models") if k in body},
        result,
    )
    return result
