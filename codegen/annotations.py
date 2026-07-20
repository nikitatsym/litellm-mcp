"""Per-op annotation data (read modules authored in Step 5).

Each entry is keyed by op name; an unknown op key, or an unknown inner key, is
a generation-time error. Supported inner fields (all optional):

    ANNOTATIONS[op_name] = {
        "doc":    "docstring head override (else the spec summary)",
        "body":   "extra docstring body lines (rendered under the signature)",
        "params": {param_name: "Field(description=...) text"},
        "types":  {param_name: "type expression that NARROWS the generated type"},
        "bare":   "reason this op genuinely needs no annotation (marker only)",
    }

`bare` records an explicit "nothing to add" decision so the completeness gate
can tell a decided op from a forgotten one; the generator ignores its value.
The type mapping is total with empty data, so `types` only ever narrows.
"""

from __future__ import annotations

from typing import Any

# Reused description fragments (kept short; ASCII only).
_START = "Start of the window, YYYY-MM-DD."
_END = "End of the window, YYYY-MM-DD."
_PAGE = "1-based page number."
_PAGE_SIZE = "Rows per page."
_SORT_ORDER = "Sort direction: 'asc' or 'desc'."
_BARE = "self-explanatory summary; no non-obvious params"

ANNOTATIONS: dict[str, dict[str, Any]] = {
    # ===================== read_core =====================================
    "list_keys": {
        "doc": "List virtual keys (rows slimmed to essentials).",
        "body": "By default only key-hash strings are returned; pass "
        "return_full_object=true to get full objects, which are then slimmed "
        "to essential fields.",
        "params": {
            "page": _PAGE,
            "size": _PAGE_SIZE,
            "key_hash": "Hashed key token (from a prior list; safe to log).",
            "return_full_object": "true returns full key objects (slimmed); "
            "false (default) returns key-hash strings only.",
            "status": "Filter by key status, e.g. 'active' or 'blocked'.",
            "sort_order": _SORT_ORDER,
            "substring_matching": "Match key_alias as a substring instead of exact.",
        },
    },
    "key_info": {
        "doc": "Get one virtual key's full details.",
        "body": "The key rides in the query string (upstream offers no body "
        "variant), so prefer passing the hashed token from list_keys rather "
        "than a raw secret key.",
        "params": {
            "key": "Key token to look up; prefer the hashed token from list_keys.",
        },
    },
    "list_teams": {
        "doc": "List teams (paginated; rows slimmed to essentials).",
        "params": {
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
            "search": "Free-text match on team alias.",
            "sort_order": _SORT_ORDER,
            "status": "Filter by team status.",
        },
    },
    "team_info": {
        "doc": "Get one team's details.",
        "params": {
            "team_id": "Team ID to look up.",
            "key_limit": "Cap on the number of team keys included in the response.",
        },
    },
    "team_daily_activity": {
        "doc": "Per-day team usage and spend.",
        "params": {
            "team_ids": "Comma-separated team IDs.",
            "exclude_team_ids": "Comma-separated team IDs to exclude.",
            "start_date": _START,
            "end_date": _END,
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
        },
    },
    "team_permissions": {
        "doc": "List a team's configured member permissions.",
        "params": {"team_id": "Team ID to inspect."},
    },
    "team_callbacks": {
        "doc": "Get a team's logging/alerting callbacks.",
        "params": {"team_id": "Team ID to inspect."},
    },
    "list_users": {
        "doc": "List users (paginated; rows slimmed to essentials).",
        "params": {
            "role": "Filter by user role.",
            "user_ids": "Comma-separated user IDs.",
            "sso_user_ids": "Comma-separated SSO user IDs.",
            "organization_ids": "Comma-separated organization IDs.",
            "user_email": "Filter by exact email.",
            "team": "Filter by team ID.",
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
            "sort_order": _SORT_ORDER,
        },
    },
    "user_info": {
        "doc": "Get one user's details; omit user_id for the calling key's user.",
        "params": {"user_id": "User ID to look up; omit for the caller."},
    },
    "user_daily_activity": {
        "doc": "Per-day user usage and spend.",
        "params": {
            "start_date": _START,
            "end_date": _END,
            "user_id": "User ID to scope to; omit for the caller.",
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
            "timezone": "UTC offset in hours for day bucketing.",
        },
    },
    "list_organizations": {
        "doc": "List organizations (rows slimmed to essentials).",
        "params": {
            "org_id": "Filter by organization ID.",
            "org_alias": "Filter by organization alias.",
        },
    },
    "organization_info": {
        "doc": "Get one organization's details, members, and teams.",
        "params": {"organization_id": "Organization ID to look up."},
    },
    "organization_daily_activity": {
        "doc": "Per-day organization usage and spend.",
        "params": {
            "organization_ids": "Comma-separated organization IDs.",
            "exclude_organization_ids": "Comma-separated organization IDs to exclude.",
            "start_date": _START,
            "end_date": _END,
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
        },
    },
    "list_customers": {
        "doc": "List customers (end users; rows slimmed to essentials).",
        "bare": "list op; slim set in slims.py",
    },
    "customer_info": {
        "doc": "Get one customer's (end user's) details.",
        "params": {"end_user_id": "Customer / end-user ID to look up."},
    },
    "customer_daily_activity": {
        "doc": "Per-day customer (end-user) usage and spend.",
        "params": {
            "end_user_ids": "Comma-separated customer IDs.",
            "exclude_end_user_ids": "Comma-separated customer IDs to exclude.",
            "start_date": _START,
            "end_date": _END,
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
        },
    },
    "list_budgets": {"doc": "List configured budgets.", "bare": "no params"},
    "budget_info": {
        "doc": "Get details for one or more budgets.",
        "params": {"budgets": "Budget IDs to look up."},
    },
    "budget_settings": {
        "doc": "Get the settable fields and defaults for a budget.",
        "params": {"budget_id": "Budget ID whose settings to return."},
    },
    # ===================== read_infra ====================================
    "list_models": {
        "doc": "List model IDs available to the caller (OpenAI /v1/models shape).",
        "params": {
            "team_id": "Scope the listing to a team's models.",
            "return_wildcard_routes": "Include wildcard (provider/*) routes.",
            "healthy_only": "Only models that passed their last health check.",
        },
    },
    "model_info": {
        "doc": "List configured model deployments with pricing and provider (v2).",
        "body": "Rows are slimmed to essential fields; provider credentials are "
        "masked upstream.",
        "params": {
            "model": "Filter by public model name.",
            "search": "Free-text match across deployments.",
            "page": _PAGE,
            "size": _PAGE_SIZE,
            "modelId": "Filter by deployment ID (upstream camelCase).",
            "teamId": "Filter by team ID (upstream camelCase).",
            "sortBy": "Field to sort by (upstream camelCase).",
            "sortOrder": "Sort direction, 'asc' or 'desc' (upstream camelCase).",
        },
    },
    "get_model": {
        "doc": "Get one model deployment's details by deployment ID.",
        "params": {
            "model_id": "Deployment ID to look up.",
            "healthy_only": "Only return it if its last health check passed.",
        },
    },
    "model_group_info": {
        "doc": "Aggregate info for a model group (all deployments of a public name).",
        "params": {"model_group": "Public model name; omit for all groups."},
    },
    "list_access_groups": {
        "doc": "List unified access groups (gate both models and MCP servers).",
        "bare": "no params",
    },
    "access_group_info": {
        "doc": "Get one access group's members and gated resources.",
        "params": {"access_group_id": "Access group ID to look up."},
    },
    "list_credentials": {
        "doc": "List stored provider credentials (secret values masked upstream).",
        "bare": "no params",
    },
    "get_credential": {
        "doc": "Get one credential by name (secret values masked upstream).",
        "params": {"credential_name": "Credential name to look up."},
    },
    "credential_by_model": {
        "doc": "Get the credential bound to a model deployment.",
        "params": {"model_id": "Deployment ID whose credential to return."},
    },
    "list_tags": {
        "doc": "List tags with usage.",
        "params": {"start_date": _START, "end_date": _END},
    },
    "tag_info": {
        "doc": "Get details for one or more tags.",
        "params": {"names": "Tag names to look up."},
    },
    "tag_daily_activity": {
        "doc": "Per-day usage and spend grouped by tag.",
        "params": {
            "tags": "Comma-separated tag names.",
            "start_date": _START,
            "end_date": _END,
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
        },
    },
    "list_guardrails": {
        "doc": "List configured guardrails (v2).",
        "bare": "no params",
    },
    "guardrail_info": {
        "doc": "Get one guardrail's configuration.",
        "params": {"guardrail_id": "Guardrail ID to look up."},
    },
    "spend_logs": {
        "doc": "Query per-request spend logs with rich filters (paginated).",
        "body": "Rows are slimmed to essential fields.",
        "params": {
            "start_date": _START,
            "end_date": _END,
            "min_spend": "Only rows with spend >= this (USD).",
            "max_spend": "Only rows with spend <= this (USD).",
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
            "status_filter": "Filter by request status, e.g. 'success' or 'failure'.",
            "sort_order": _SORT_ORDER,
        },
    },
    "spend_tags": {
        "doc": "Spend totals grouped by tag.",
        "params": {"start_date": _START, "end_date": _END},
    },
    "global_spend_report": {
        "doc": "Global spend report grouped by team, customer, or api_key.",
        "params": {
            "start_date": _START,
            "end_date": _END,
            "group_by": "Dimension to group spend by.",
        },
    },
    "calculate_spend": {
        "doc": "Compute the cost of a completion (POST-but-read; nothing stored).",
        "params": {
            "model": "Model name used for pricing.",
            "messages": "Chat messages to price a request from.",
            "completion_response": "A completion response object to price instead.",
        },
    },
    "cost_estimate": {
        "doc": "Estimate cost for a model at a given token volume.",
        "params": {
            "model": "Model name to price.",
            "input_tokens": "Prompt tokens per request.",
            "output_tokens": "Completion tokens per request.",
            "num_requests_per_day": "Requests per day for a daily estimate.",
            "num_requests_per_month": "Requests per month for a monthly estimate.",
        },
    },
    "list_audit_logs": {
        "doc": "List audit-log entries (paginated).",
        "params": {
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
            "start_date": _START,
            "end_date": _END,
            "action": "Filter by action, e.g. 'created', 'updated', 'deleted'.",
            "table_name": "Filter by the changed table.",
            "object_id": "Filter by the changed object's ID.",
            "sort_order": _SORT_ORDER,
        },
    },
    "audit_log_info": {
        "doc": "Get one audit-log entry by ID.",
        "params": {"id": "Audit-log entry ID."},
    },
    "health_readiness": {"bare": _BARE},
    "health_services": {
        "doc": "Probe connectivity of a configured logging/alerting service.",
        "params": {"service": "The integration to probe (known values listed) or any custom name."},
    },
    "active_callbacks": {"bare": _BARE},
    "router_settings": {"bare": _BARE},
    "get_fallback": {
        "doc": "Get the configured fallback models for a model.",
        "params": {
            "model": "Model name whose fallbacks to return.",
            "fallback_type": "Which fallback list to return.",
        },
    },
    "cache_ping": {"bare": _BARE},
    "cache_redis_info": {"bare": _BARE},
    "cache_settings": {"bare": _BARE},
    "sso_settings": {"bare": _BARE},
    "default_team_settings": {"bare": _BARE},
    "internal_user_settings": {"bare": _BARE},
    "email_event_settings": {"bare": _BARE},
    "cost_margin_config": {"bare": _BARE},
    "cost_discount_config": {"bare": _BARE},
    "list_mcp_servers": {
        "doc": "List registered MCP gateway servers (secret fields omitted from rows).",
        "body": "Rows never carry credentials, static_headers, or env_vars.",
        "params": {"team_id": "Scope the listing to a team's servers."},
    },
    "get_mcp_server": {
        "doc": "Get one registered MCP server's full configuration.",
        "body": "Unlike the list op this returns whatever upstream stores; "
        "credentials, static_headers, and env_vars are secret-bearing.",
        "params": {"server_id": "MCP server ID to look up."},
    },
    "mcp_server_health": {
        "doc": "Probe health of registered MCP servers.",
        "params": {"server_ids": "MCP server IDs to probe; omit for all."},
    },
    "list_mcp_tools": {"doc": "List tools exposed through the MCP gateway.", "bare": "no params"},
    "mcp_access_groups": {
        "doc": "List access-group names known to the MCP surface.",
        "bare": "no params",
    },
    "list_toolsets": {"doc": "List registered MCP toolsets.", "bare": "no params"},
    "get_toolset": {
        "doc": "Get one MCP toolset's configuration.",
        "params": {"toolset_id": "Toolset ID to look up."},
    },
    "token_counter": {
        "doc": "Count tokens for a model (POST-but-read).",
        "params": {
            "model": "Model whose tokenizer to use.",
            "prompt": "Raw prompt string to tokenize.",
            "messages": "Chat messages to tokenize instead of a prompt.",
            "call_endpoint": "Ask the provider endpoint for the count instead of local counting.",
        },
    },
    "supported_openai_params": {
        "doc": "List the OpenAI request params supported for a model.",
        "params": {"model": "Model name to inspect."},
    },
    "list_providers": {"doc": "List supported LLM providers.", "bare": "no params"},
}
