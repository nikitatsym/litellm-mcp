"""Per-list-op slim data (read modules authored in Step 5).

Each entry is keyed by op name; an unknown key is a generation-time error.

    SLIMS[op_name] = {"fields": [...], "limit": 20}                # bare list
    SLIMS[op_name] = {"fields": [...], "limit": 20, "container": "keys"}
    SLIMS[op_name] = {"no_slim": "reason the full payload is returned"}

`container` names the envelope key holding the rows (`keys`, `teams`, `data`,
...) for endpoints that wrap their page; without it the response is the row
list itself. The emitter turns an entry into `_slim_list(result, {fields},
limit, container?)` - each row projected to `fields` (upstream key order kept),
the page capped at `limit`, cut counts reported, and any other envelope fields
(server pagination counts) carried through under `page_info`.

Baseline field sets are fixed by the v2.5-build plan (Decision 11). Adding a
field is allowed; a removal or rename is a gap-decision. A list op with no
entry fails the completeness gate once its module is gated.
"""

from __future__ import annotations

from typing import Any

# Baseline slim field sets (plan Step 5). Field names verified against the
# snapshot response schemas where the endpoint is typed; the untyped ones
# (models/spend rows) follow the plan and are confirmed live in Step 9.
_SLIM_KEY = [
    "token", "key_name", "key_alias", "user_id", "team_id", "spend",
    "max_budget", "models", "blocked", "expires", "created_at",
]
_SLIM_TEAM = [
    "team_id", "team_alias", "spend", "max_budget", "models",
    "tpm_limit", "rpm_limit", "blocked", "organization_id",
]
_SLIM_USER = [
    "user_id", "user_email", "user_role", "teams", "spend",
    "max_budget", "created_at",
]
_SLIM_MODEL = [
    "model_name", "litellm_model", "model_id", "provider",
    "input_cost", "output_cost", "db_model",
]
_SLIM_SPEND_LOG = [
    "request_id", "api_key_alias", "model", "spend", "total_tokens",
    "startTime", "user", "team_id", "status",
]
_SLIM_ORG = [
    "organization_id", "organization_alias", "spend", "models", "created_at",
]
_SLIM_MCP_SERVER = [
    # Never credentials / static_headers / env_vars: secret-bearing fields
    # stay out of list output (plan Decision 11).
    "server_id", "server_name", "alias", "url", "transport",
    "auth_type", "mcp_access_groups", "status",
]
# Platform (Step 8). Policy rows carry condition/pipeline dicts; the list view
# keeps only identity + version status (full row via policy_info).
_SLIM_POLICY = [
    "policy_id", "policy_name", "version_number", "version_status",
    "is_latest", "description", "updated_at",
]
# Never litellm_params / static_headers / extra_headers / agent_card_params:
# credential-bearing or heavy fields stay out of list output (get_agent returns
# the full row).
_SLIM_AGENT = [
    "agent_id", "agent_name", "spend", "tpm_limit", "rpm_limit",
    "session_tpm_limit", "session_rpm_limit", "created_at",
]
# Not a plan baseline set: list_customers is marked slim with no set given, so
# this projection is authored here (gap-decision) from CustomerResponse.
_SLIM_CUSTOMER = [
    "user_id", "alias", "spend", "blocked", "default_model", "budget_id",
]

SLIMS: dict[str, dict[str, Any]] = {
    # --- read_core ---------------------------------------------------------
    "list_keys": {"fields": _SLIM_KEY, "limit": 20, "container": "keys"},
    "list_teams": {"fields": _SLIM_TEAM, "limit": 20, "container": "teams"},
    "list_users": {"fields": _SLIM_USER, "limit": 20, "container": "users"},
    "list_organizations": {"fields": _SLIM_ORG, "limit": 20},
    "list_customers": {"fields": _SLIM_CUSTOMER, "limit": 20},
    "list_budgets": {"no_slim": "bounded config list; budget rows are few and small"},
    # --- read_infra --------------------------------------------------------
    "model_info": {"fields": _SLIM_MODEL, "limit": 20, "container": "data"},
    "spend_logs": {"fields": _SLIM_SPEND_LOG, "limit": 20, "container": "data"},
    "list_mcp_servers": {"fields": _SLIM_MCP_SERVER, "limit": 20},
    "list_models": {
        "no_slim": "OpenAI-shape id list; rows are already minimal id records "
        "and reshaping would break OpenAI compatibility"
    },
    "list_access_groups": {"no_slim": "bounded config list; access groups are few"},
    "list_credentials": {"no_slim": "bounded config list; secret values masked upstream"},
    "list_tags": {"no_slim": "returns a bounded tag->info map, not a row list"},
    "list_guardrails": {"no_slim": "bounded config list; guardrail configs are few"},
    "list_audit_logs": {"no_slim": "paginated upstream (page/page_size); per-page bounded"},
    "spend_tags": {"no_slim": "date-range-scoped per-tag aggregate; bounded by tag count"},
    "global_spend_report": {"no_slim": "aggregated report; bounded by group_by cardinality"},
    "list_mcp_tools": {"no_slim": "tool descriptors are the payload; bounded by registered tools"},
    "list_toolsets": {"no_slim": "bounded config list; toolsets are few"},
    "list_providers": {"no_slim": "bare list of provider-name strings; already minimal"},
    # --- delete (Step 7) ---------------------------------------------------
    # Not a browse list: the 200 is an array of the org rows just deleted, so
    # the completeness gate flags it as a list op. A delete confirmation is
    # returned whole - slimming it would hide what was removed.
    "delete_organizations": {"no_slim": "delete confirmation returning the deleted "
                             "org rows; not a browse list, returned whole"},
    # --- platform (Step 8) -------------------------------------------------
    # Slimmed: heavy per-row payloads worth projecting for the list view.
    "list_policies": {"fields": _SLIM_POLICY, "limit": 20, "container": "policies"},
    "list_policy_versions": {"fields": _SLIM_POLICY, "limit": 20, "container": "versions"},
    "list_agents": {"fields": _SLIM_AGENT, "limit": 20},  # bare array; secrets dropped
    # no_slim: cursor/limit-paginated upstream (the emitter forbids a client
    # `limit` alongside a spec `limit`), or lightweight rows.
    "list_policy_attachments": {"no_slim": "bounded list; attachment rows are the "
                                "scope definition (id + selector lists), returned whole"},
    "list_evals": {"no_slim": "OpenAI-Evals cursor pagination via the spec limit/after/"
                   "before params; a client slim would collide with the spec `limit`"},
    "list_eval_runs": {"no_slim": "OpenAI-Evals cursor pagination via the spec limit/"
                       "after/before params; a client slim would collide with `limit`"},
    "list_workflow_runs": {"no_slim": "upstream-limited via the spec `limit` param; the "
                           "200 shape is untyped {} in the snapshot, so no client slim "
                           "is authored (returned whole)"},
    "list_workflow_events": {"no_slim": "upstream-limited via the spec `limit` param; "
                             "untyped {} response in the snapshot, returned whole"},
    "list_workflow_messages": {"no_slim": "upstream-limited via the spec `limit` param; "
                               "untyped {} response in the snapshot, returned whole"},
}
