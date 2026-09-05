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

# Write-path reused fragments.
_TPM = "Tokens-per-minute cap."
_RPM = "Requests-per-minute cap."
_MAX_BUDGET = "Hard USD budget cap; use blocks once exceeded."
_SOFT_BUDGET = "USD spend that raises an alert; does not block."
_BUDGET_DURATION = "Budget reset window, e.g. '30d', '1mo'."
_MODELS = "Model names this resource may access; empty means all."
_METADATA = "Free-form JSON metadata stored on the row."
_BLOCKED = "true blocks all use immediately."
_DURATION = "Key lifetime, e.g. '30d', '24h'; stored as an expiry timestamp."
_LITELLM_PARAMS = (
    "Provider call config as a dict, e.g. {'model': 'openai/gpt-4o', "
    "'api_key': 'os.environ/OPENAI_API_KEY'}. Keys are provider-specific "
    "(genuinely dynamic), so this stays an opaque dict - see LiteLLM docs."
)

# --- platform (Step 8) reused fragments -----------------------------------
_POLICY_ID = "Policy ID (one specific version row of a policy)."
_POLICY_NAME_ADDR = "Policy name (addresses the policy across all its versions)."
_ATTACHMENT_ID = "Policy attachment ID."
_CUSTOM_LLM_PROVIDER = "Provider override for the eval backend; omit to use the configured default."
# create/update policy share these body fields.
_POLICY_INHERIT = "Name of a parent policy to inherit guardrails from."
_POLICY_DESCRIPTION = "Human-readable description of the policy."
_POLICY_GADD = "Guardrail names to add."
_POLICY_GREMOVE = "Guardrail names to remove (from the inherited set)."
_POLICY_CONDITION = "Condition object controlling when this policy applies."
_POLICY_PIPELINE = "Guardrail pipeline for ordered execution; contains 'mode' and 'steps'."
# create_policy_attachment / estimate_attachment_impact share the scope selectors.
_ATTACH_SCOPE = "Attachment scope; use '*' for global (applies to all requests)."
_ATTACH_TEAMS = "Team aliases or patterns this attachment applies to."
_ATTACH_KEYS = "Key aliases or patterns this attachment applies to."
_ATTACH_MODELS = "Model names or patterns this attachment applies to."
_ATTACH_TAGS = "Tag patterns this attachment applies to; supports wildcards (e.g. 'health-*')."
_ATTACH_PARAMS = {
    "policy_name": "Name of the policy to attach.",
    "scope": _ATTACH_SCOPE,
    "teams": _ATTACH_TEAMS,
    "keys": _ATTACH_KEYS,
    "models": _ATTACH_MODELS,
    "tags": _ATTACH_TAGS,
}
# a2a agents share the same write body across create/update/patch.
_AGENT_PARAMS = {
    "agent_name": "Human-readable agent name.",
    "agent_card_params": "A2A agent-card fields (name, description, skills, ...) as a dict.",
    "litellm_params": "Provider call config for the agent's backend model, as a dict.",
    "object_permission": "Object-level permission config (models/routes this agent may use).",
    "tpm_limit": _TPM,
    "rpm_limit": _RPM,
    "session_tpm_limit": "Per-session tokens-per-minute cap.",
    "session_rpm_limit": "Per-session requests-per-minute cap.",
    "static_headers": "Fixed headers sent to the agent backend; may carry secrets (write-only).",
    "extra_headers": "Additional header names to forward to the agent backend.",
}
# cloudzero export/dry-run share the window selectors.
_CZ_PARAMS = {
    "limit": "Max spend records to export; omit for no cap.",
    "operation": "CloudZero write mode: 'replace_hourly' overwrites the hour, 'sum' adds.",
    "start_time_utc": "Window start (UTC ISO-8601); omit for the default range.",
    "end_time_utc": "Window end (UTC ISO-8601); omit for the default range.",
}
_CZ_OPERATION = "Literal['replace_hourly', 'sum']"

# --- prompts (prompts-and-agent-activity plan, Step 2) reused fragments -----
_PROMPT_LITELLM_PARAMS = (
    "Prompt provider config (PromptLiteLLMParams) as a dict: prompt_integration "
    "(the registry kind, required, e.g. 'dotprompt'); dotprompt_content (inline "
    "template text with frontmatter for the 'dotprompt' integration); "
    "api_base/api_key to point at an EXTERNAL prompt registry; prompt_id inside "
    "params overrides the registry lookup key. Secret-bearing (api_key) - never "
    "surfaced in list output."
)
_PROMPT_INFO = (
    "Prompt metadata (PromptInfo) as a dict; its 'environment' selects the "
    "version's environment (default 'development')."
)
_PROMPT_ENV = (
    "Environment to scope to, e.g. 'development' or 'production'; omit for the default."
)

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
            "return_wildcard_routes": "Append wildcard (provider/*) routes "
            "(upstream is additive: they appear even when false).",
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
    # ===================== write =========================================
    "generate_key": {
        "doc": "Mint a new virtual API key.",
        "body": "The generated secret is returned ONCE, in this response's `key` "
        "field - it is never retrievable again (list_keys/key_info show only the "
        "hashed token). Store it now.",
        "params": {
            "key_alias": "Human-readable label for the key.",
            "duration": _DURATION,
            "models": _MODELS,
            "max_budget": _MAX_BUDGET,
            "soft_budget": _SOFT_BUDGET,
            "tpm_limit": _TPM,
            "rpm_limit": _RPM,
            "budget_duration": _BUDGET_DURATION,
            "user_id": "Owning user; omit to leave unassigned.",
            "team_id": "Owning team; scopes the key's model access and budget.",
            "key": "Provide a custom key string instead of a generated one.",
            "metadata": _METADATA,
            "blocked": _BLOCKED,
        },
    },
    "update_key": {
        "doc": "Update an existing virtual key's settings.",
        "body": "Addresses the key by its `key` token; only the fields you pass "
        "are changed.",
        "params": {
            "key": "Token of the key to update (hashed token accepted).",
            "models": _MODELS,
            "max_budget": _MAX_BUDGET,
            "tpm_limit": _TPM,
            "rpm_limit": _RPM,
            "budget_duration": _BUDGET_DURATION,
            "blocked": _BLOCKED,
            "metadata": _METADATA,
        },
    },
    "new_team": {
        "doc": "Create a team.",
        "params": {
            "team_alias": "Human-readable team name.",
            "team_id": "Provide a custom ID; omit to auto-generate.",
            "organization_id": "Parent organization, if any.",
            "models": _MODELS,
            "max_budget": _MAX_BUDGET,
            "tpm_limit": _TPM,
            "rpm_limit": _RPM,
            "budget_duration": _BUDGET_DURATION,
            "members_with_roles": "Initial members as {'user_id'|'user_email', 'role'} dicts.",
            "blocked": _BLOCKED,
        },
    },
    "update_team": {
        "doc": "Update a team's settings.",
        "params": {
            "team_id": "ID of the team to update.",
            "models": _MODELS,
            "max_budget": _MAX_BUDGET,
            "tpm_limit": _TPM,
            "rpm_limit": _RPM,
            "budget_duration": _BUDGET_DURATION,
            "blocked": _BLOCKED,
        },
    },
    "team_member_add": {
        "doc": "Add one or more members to a team.",
        "params": {
            "team_id": "Team to add members to.",
            "member": "A member or list of members: {'user_id'|'user_email', 'role'}.",
            "max_budget_in_team": "Per-member USD budget scoped to this team.",
        },
    },
    "team_member_update": {
        "doc": "Update a team member's role or limits.",
        "params": {
            "team_id": "Team the member belongs to.",
            "role": "Member role within the team.",
            "max_budget_in_team": "Per-member USD budget scoped to this team.",
            "tpm_limit": _TPM,
            "rpm_limit": _RPM,
        },
    },
    "team_model_add": {
        "doc": "Grant a team access to additional models.",
        "params": {
            "team_id": "Team to grant access to.",
            "models": "Model names to add to the team's allow-list.",
        },
    },
    "team_permissions_update": {
        "doc": "Replace a team's member-permission list.",
        "params": {
            "team_id": "Team whose permissions to set.",
            "team_member_permissions": "Full permission list (replaces, not merges).",
        },
    },
    "add_team_callback": {
        "doc": "Register a logging/alerting callback on a team.",
        "params": {
            "team_id": "Team to attach the callback to.",
            "callback_name": "Callback integration name, e.g. 'langfuse', 'slack'.",
            "callback_type": "When the callback fires.",
            "callback_vars": "Callback config as a dict (endpoints, keys, ...).",
        },
    },
    "new_user": {
        "doc": "Create an internal user.",
        "body": "If auto_create_key is left on, a default key is minted and its "
        "secret is returned ONCE in this response.",
        "params": {
            "user_email": "User email (login identity).",
            "user_role": "Proxy-level role.",
            "user_id": "Provide a custom ID; omit to auto-generate.",
            "teams": "Team IDs to add the user to.",
            "models": _MODELS,
            "max_budget": _MAX_BUDGET,
            "tpm_limit": _TPM,
            "rpm_limit": _RPM,
            "duration": _DURATION,
        },
    },
    "update_user": {
        "doc": "Update an internal user's settings.",
        "params": {
            "user_id": "ID of the user to update.",
            "user_role": "Proxy-level role.",
            "models": _MODELS,
            "max_budget": _MAX_BUDGET,
            "tpm_limit": _TPM,
            "rpm_limit": _RPM,
            "password": "New UI login password.",
        },
    },
    "new_organization": {
        "doc": "Create an organization.",
        "params": {
            "organization_alias": "Human-readable organization name.",
            "organization_id": "Provide a custom ID; omit to auto-generate.",
            "models": _MODELS,
            "max_budget": _MAX_BUDGET,
            "tpm_limit": _TPM,
            "rpm_limit": _RPM,
            "budget_duration": _BUDGET_DURATION,
        },
    },
    "organization_member_add": {
        "doc": "Add one or more members to an organization.",
        "params": {
            "organization_id": "Organization to add members to.",
            "member": "A member or list of members: {'user_id'|'user_email', 'role'}.",
            "max_budget_in_organization": "Per-member USD budget scoped to this org.",
        },
    },
    "organization_member_update": {
        "doc": "Update an organization member's role or budget.",
        "params": {
            "organization_id": "Organization the member belongs to.",
            "role": "Member role within the organization.",
            "max_budget_in_organization": "Per-member USD budget scoped to this org.",
        },
    },
    "new_customer": {
        "doc": "Create an end-customer (end user) budget profile.",
        "body": "Customers are end users tracked for spend/budget, distinct from "
        "internal users; user_id is the customer identifier you report spend for.",
        "params": {
            "user_id": "Customer identifier (your end-user ID).",
            "alias": "Human-readable customer name.",
            "max_budget": _MAX_BUDGET,
            "budget_id": "Attach an existing budget object instead of inline limits.",
            "allowed_model_region": "Restrict routing to a data region.",
            "default_model": "Fallback model when the request names none.",
            "blocked": _BLOCKED,
        },
    },
    "update_customer": {
        "doc": "Update an end-customer's budget profile.",
        "params": {
            "user_id": "Customer identifier to update.",
            "alias": "Human-readable customer name.",
            "max_budget": _MAX_BUDGET,
            "allowed_model_region": "Restrict routing to a data region.",
            "default_model": "Fallback model when the request names none.",
            "blocked": _BLOCKED,
        },
    },
    "new_budget": {
        "doc": "Create a reusable budget object.",
        "params": {
            "budget_id": "Provide a custom ID; omit to auto-generate.",
            "max_budget": _MAX_BUDGET,
            "soft_budget": _SOFT_BUDGET,
            "tpm_limit": _TPM,
            "rpm_limit": _RPM,
            "budget_duration": _BUDGET_DURATION,
        },
    },
    "update_budget": {
        "doc": "Update a budget object.",
        "params": {
            "budget_id": "ID of the budget to update.",
            "max_budget": _MAX_BUDGET,
            "soft_budget": _SOFT_BUDGET,
            "budget_duration": _BUDGET_DURATION,
        },
    },
    "add_model": {
        "doc": "Register a new model deployment on the proxy.",
        "params": {
            "model_name": "Public model name callers request (e.g. 'gpt-4o').",
            "litellm_params": _LITELLM_PARAMS,
            "model_info": "Optional metadata dict (id, mode, base_model, ...).",
        },
    },
    "update_model": {
        "doc": "Replace a model deployment's config (full update).",
        "params": {
            "model_name": "Public model name for the deployment.",
            "litellm_params": _LITELLM_PARAMS,
            "model_info": "Metadata dict; must carry the target model_info.id.",
            "blocked": _BLOCKED,
        },
    },
    "patch_model": {
        "doc": "Partially update a model deployment.",
        "params": {
            "model_id": "Deployment ID to patch (in the path).",
            "litellm_params": _LITELLM_PARAMS,
            "blocked": _BLOCKED,
        },
    },
    "create_access_group": {
        "doc": "Create a unified access group (gates models and MCP servers).",
        "params": {
            "access_group_name": "Unique name for the access group.",
            "access_model_names": "Model names the group grants.",
            "access_mcp_server_ids": "MCP server IDs the group grants.",
            "assigned_team_ids": "Teams the group is assigned to.",
        },
    },
    "update_access_group": {
        "doc": "Update a unified access group.",
        "params": {
            "access_group_id": "ID of the access group to update (in the path).",
            "access_group_name": "New name for the access group.",
            "access_model_names": "Model names the group grants (replaces).",
        },
    },
    "create_mcp_server": {
        "doc": "Register a backend MCP server in the gateway.",
        "body": "Credential fields (credentials, static_headers, env_vars) are "
        "write-only: they are stored but never returned by the read ops. Supply "
        "them here; they cannot be read back afterwards.",
        "params": {
            "url": "Server URL (for http/sse transports).",
            "transport": "Transport protocol the server speaks.",
            "auth_type": "Authentication scheme for reaching the server.",
            "credentials": "Write-only auth material as a dict.",
            "mcp_access_groups": "Access-group names that may reach this server.",
            "command": "Executable to launch (stdio transport).",
        },
    },
    "update_mcp_server": {
        "doc": "Update a registered MCP server (id in the body).",
        "body": "Credential fields are write-only, as for create_mcp_server.",
        "params": {
            "server_id": "ID of the MCP server to update.",
            "url": "Server URL (for http/sse transports).",
            "transport": "Transport protocol the server speaks.",
            "credentials": "Write-only auth material as a dict.",
        },
    },
    "create_toolset": {
        "doc": "Create an MCP toolset (a named bundle of tools).",
        "params": {
            "toolset_name": "Unique name for the toolset.",
            "tools": "Tool descriptors as a list of dicts.",
        },
    },
    "update_toolset": {
        "doc": "Update an MCP toolset (id in the body).",
        "params": {
            "toolset_id": "ID of the toolset to update.",
            "tools": "Tool descriptors as a list of dicts (replaces).",
        },
    },
    "create_credential": {
        "doc": "Store a named provider credential.",
        "params": {
            "credential_name": "Unique name to reference the credential by.",
            "credential_values": "Secret key/value pairs (write-only) as a dict.",
            "credential_info": "Non-secret descriptive metadata as a dict.",
            "model_id": "Bind the credential to a specific model deployment.",
        },
    },
    "update_credential": {
        "doc": "Update a stored credential.",
        "params": {
            "credential_name": "Name of the credential to update (in the path).",
            "credential_values": "Secret key/value pairs (write-only) as a dict.",
            "credential_info": "Non-secret descriptive metadata as a dict.",
        },
    },
    "new_tag": {
        "doc": "Create a spend-tracking tag.",
        "params": {
            "name": "Unique tag name.",
            "models": "Model names the tag scopes spend to.",
            "max_budget": _MAX_BUDGET,
            "budget_duration": _BUDGET_DURATION,
        },
    },
    "update_tag": {
        "doc": "Update a spend-tracking tag.",
        "params": {
            "name": "Name of the tag to update.",
            "models": "Model names the tag scopes spend to (replaces).",
            "max_budget": _MAX_BUDGET,
        },
    },
    "create_guardrail": {
        "doc": "Create a guardrail.",
        "params": {
            "guardrail": "Guardrail spec as a dict: {'guardrail_name', "
            "'litellm_params': {'guardrail': <provider>, 'mode': <when>, ...}}. "
            "Shape is provider-specific - see LiteLLM guardrail docs.",
        },
    },
    "update_guardrail": {
        "doc": "Update a guardrail.",
        "params": {
            "guardrail_id": "ID of the guardrail to update (in the path).",
            "guardrail": "Full guardrail spec as a dict (replaces).",
        },
    },
    "create_fallback": {
        "doc": "Define a fallback chain for a model.",
        "params": {
            "model": "Primary model the fallback applies to.",
            "fallback_models": "Ordered models tried when the primary fails.",
            "fallback_type": "Which failure class triggers this chain.",
        },
    },
    # ===================== execute ========================================
    "block_key": {
        "doc": "Block a virtual key (reversible via unblock_key).",
        "params": {"key": "Virtual key to block; hashed token from list_keys accepted."},
    },
    "unblock_key": {
        "doc": "Unblock a previously blocked virtual key.",
        "params": {"key": "Virtual key to unblock; hashed token from list_keys accepted."},
    },
    "regenerate_key": {
        "doc": "Rotate a virtual key: invalidate the old secret and mint a new one.",
        "body": "The key is addressed in the request BODY, never the URL path, so "
        "the secret never lands in proxy access logs (Decision 9). The NEW secret "
        "is returned ONCE in this response's `key` field - store it now; the old "
        "secret stops working immediately.",
        "params": {
            "key": "Existing key to rotate; addressed in the body (never the URL).",
            "duration": _DURATION,
            "new_master_key": "New master-key value (master-key rotation only).",
        },
    },
    "reset_key_spend": {
        "doc": "Reset a virtual key's accumulated spend counter.",
        "body": "Upstream offers only the path variant here, so the key rides in "
        "the URL path (Decision 9 exception); prefer the hashed token. `reset_to` "
        "sets the new spend value.",
        "params": {
            "key": "Key whose spend to reset (in the URL path).",
            "reset_to": "New spend value in USD (e.g. 0 to zero it).",
        },
    },
    "block_team": {
        "doc": "Block a team (reversible via unblock_team).",
        "params": {"team_id": "Team ID to block."},
    },
    "unblock_team": {
        "doc": "Unblock a previously blocked team.",
        "params": {"team_id": "Team ID to unblock."},
    },
    "disable_team_logging": {
        "doc": "Turn off a team's configured logging callbacks.",
        "params": {"team_id": "Team whose logging to disable."},
    },
    "block_model": {
        "doc": "Block a model deployment (reversible via unblock_model).",
        "params": {"model_id": "Model deployment ID to block."},
    },
    "unblock_model": {
        "doc": "Unblock a previously blocked model deployment.",
        "params": {"model_id": "Model deployment ID to unblock."},
    },
    "block_customer": {
        "doc": "Block one or more customers (end users).",
        "params": {"user_ids": "Customer IDs to block; every listed ID in one call."},
    },
    "unblock_customer": {
        "doc": "Unblock one or more customers (end users).",
        "params": {"user_ids": "Customer IDs to unblock; every listed ID in one call."},
    },
    "test_model_connection": {
        "doc": "Probe a model deployment config before adding it (mutates nothing).",
        "params": {
            "mode": "Operation to test the model for, e.g. 'chat' or 'embedding'.",
            "litellm_params": _LITELLM_PARAMS,
            "model_info": "Optional metadata dict for the candidate deployment.",
        },
    },
    "test_cache_connection": {
        "doc": "Probe the given cache settings for connectivity (mutates nothing).",
        "params": {"cache_settings": "Cache config to test as a dict (host, port, type, ...)."},
    },
    "test_mcp_connection": {
        "doc": "Probe an MCP server config before registering it (mutates nothing).",
        "params": {
            "url": "Server URL to probe (http/sse transports).",
            "transport": "Transport protocol the server speaks.",
            "command": "Executable to launch (stdio transport).",
        },
    },
    "test_mcp_tools_list": {
        "doc": "List the tools an unregistered MCP server config exposes (mutates nothing).",
        "params": {
            "url": "Server URL to probe (http/sse transports).",
            "transport": "Transport protocol the server speaks.",
        },
    },
    # ===================== delete =========================================
    "delete_keys": {
        "doc": "Delete virtual keys.",
        "body": "Irreversible: the keys stop working immediately and cannot be "
        "recovered. Pass either `keys` (tokens) or `key_aliases`.",
        "params": {
            "keys": "Key tokens to delete; every listed key is removed in one call.",
            "key_aliases": "Key aliases to delete instead of tokens; batch semantics.",
        },
    },
    "delete_teams": {
        "doc": "Delete teams.",
        "body": "Irreversible. Every listed team is deleted in one call.",
        "params": {"team_ids": "Team IDs to delete; every listed ID in one call."},
    },
    "team_member_delete": {
        "doc": "Remove a member from a team.",
        "params": {
            "team_id": "Team to remove the member from.",
            "user_id": "Member user ID to remove (or use user_email).",
            "user_email": "Member email to remove (or use user_id).",
        },
    },
    "team_model_delete": {
        "doc": "Revoke a team's access to models.",
        "params": {
            "team_id": "Team whose model access to revoke.",
            "models": "Model names to remove from the team; every listed name in one call.",
        },
    },
    "delete_users": {
        "doc": "Delete internal users.",
        "body": "Irreversible. Every listed user is deleted in one call.",
        "params": {"user_ids": "User IDs to delete; every listed ID in one call."},
    },
    "delete_organizations": {
        "doc": "Delete organizations.",
        "body": "Irreversible; returns the deleted org rows. Every listed org is "
        "removed in one call.",
        "params": {"organization_ids": "Organization IDs to delete; every listed ID in one call."},
    },
    "organization_member_delete": {
        "doc": "Remove a member from an organization.",
        "params": {
            "organization_id": "Organization to remove the member from.",
            "user_id": "Member user ID to remove (or use user_email).",
            "user_email": "Member email to remove (or use user_id).",
        },
    },
    "delete_customers": {
        "doc": "Delete customers (end users).",
        "body": "Irreversible. Every listed customer is deleted in one call.",
        "params": {"user_ids": "Customer IDs to delete; every listed ID in one call."},
    },
    "delete_budget": {
        "doc": "Delete a budget object.",
        "params": {"id": "Budget ID to delete."},
    },
    "delete_model": {
        "doc": "Delete a model deployment.",
        "params": {"id": "Model deployment ID to delete."},
    },
    "delete_access_group": {
        "doc": "Delete a unified access group.",
        "params": {"access_group_id": "Access group ID to delete."},
    },
    "delete_mcp_server": {
        "doc": "Remove a registered MCP server from the gateway.",
        "params": {"server_id": "MCP server ID to delete."},
    },
    "delete_toolset": {
        "doc": "Delete an MCP toolset.",
        "params": {"toolset_id": "Toolset ID to delete."},
    },
    "delete_credential": {
        "doc": "Delete a stored provider credential.",
        "params": {"credential_name": "Credential name to delete."},
    },
    "delete_tag": {
        "doc": "Delete a spend-tracking tag.",
        "params": {"name": "Tag name to delete."},
    },
    "delete_guardrail": {
        "doc": "Delete a guardrail.",
        "params": {"guardrail_id": "Guardrail ID to delete."},
    },
    "delete_fallback": {
        "doc": "Remove a model's fallback chain.",
        "params": {
            "model": "Model whose fallback chain to remove.",
            "fallback_type": "Which fallback list to remove.",
        },
    },
    "cache_flushall": {
        "doc": "Flush the ENTIRE proxy cache.",
        "body": "Irreversible and unscoped: wipes every cached entry for all keys, "
        "teams, and models at once. Use cache_delete to remove specific keys instead.",
    },
    # ===================== admin ==========================================
    "update_sso_settings": {
        "doc": "Update proxy-wide SSO configuration.",
        "params": {
            "ui_access_mode": "Who may reach the admin UI (mode name or a rule dict).",
            "role_mappings": "Map IdP groups/roles to proxy roles as a dict.",
        },
    },
    "update_default_team_settings": {
        "doc": "Update the defaults applied to newly SSO-provisioned teams.",
        "params": {
            "models": "Default models new teams may access.",
            "max_budget": _MAX_BUDGET,
            "budget_duration": _BUDGET_DURATION,
        },
    },
    "update_internal_user_settings": {
        "doc": "Update the defaults applied to newly provisioned internal users.",
        "params": {
            "user_role": "Default proxy role for new users.",
            "max_budget": _MAX_BUDGET,
            "models": "Default models new users may access.",
        },
    },
    "update_email_event_settings": {
        "doc": "Configure which events trigger notification emails.",
        "params": {"settings": "Per-event on/off settings as a list of dicts."},
    },
    "reset_email_event_settings": {"doc": "Reset email-event settings to defaults."},
    "update_cost_margin_config": {
        "doc": "Set the global cost-margin config (markup applied to model costs).",
        "params": {"body": "Cost-margin config as a dict; shape per LiteLLM docs."},
    },
    "update_cost_discount_config": {
        "doc": "Set the global cost-discount config (discount applied to model costs).",
        "params": {"body": "Cost-discount config as a dict; shape per LiteLLM docs."},
    },
    "update_cache_settings": {
        "doc": "Update the proxy cache configuration.",
        "params": {"cache_settings": "Cache config as a dict (type, host, ttl, ...)."},
    },
    "add_allowed_ip": {
        "doc": "Add an IP to the proxy allow-list.",
        "params": {"ip": "IPv4/IPv6 address or CIDR to allow."},
    },
    "delete_allowed_ip": {
        "doc": "Remove an IP from the proxy allow-list.",
        "params": {"ip": "IPv4/IPv6 address or CIDR to remove."},
    },
    "global_spend_reset": {
        "doc": "Reset ALL global spend counters to zero.",
        "body": "Irreversible and proxy-wide: zeroes the aggregated spend for every "
        "key, team, user, and model at once. Historical spend logs are not deleted, "
        "but the running totals cannot be restored.",
    },
    "bulk_update_users": {
        "doc": "Update many users in one sanctioned bulk call.",
        "body": "Either target specific `users` or set all_users=true with a shared "
        "`user_updates` patch. Applies to every matched user at once.",
        "params": {
            "users": "Per-user update dicts to apply.",
            "all_users": "true applies user_updates to every user (mass edit).",
            "user_updates": "Shared field patch applied when all_users is true.",
        },
    },
    # ===================== platform: policies ============================
    "list_policies": {
        "doc": "List policies (rows slimmed to identity and version status).",
        "params": {
            "version_status": "Filter by version status: draft, published, or production.",
        },
    },
    "policy_info": {
        "doc": "Get one policy version's full definition.",
        "params": {"policy_id": _POLICY_ID},
    },
    "list_policy_versions": {
        "doc": "List every version of one policy (slimmed).",
        "params": {"policy_name": _POLICY_NAME_ADDR},
    },
    "compare_policy_versions": {
        "doc": "Diff two policy versions field by field.",
        "params": {
            "version_a": "Policy version ID on the left of the diff.",
            "version_b": "Policy version ID on the right of the diff.",
        },
    },
    "policy_resolved_guardrails": {
        "doc": "Show the guardrails a policy resolves to after inheritance.",
        "params": {"policy_id": _POLICY_ID},
    },
    "list_policy_attachments": {
        "doc": "List policy attachments (which policies bind to which key/team/model/tag).",
    },
    "policy_attachment_info": {
        "doc": "Get one policy attachment's scope.",
        "params": {"attachment_id": _ATTACHMENT_ID},
    },
    "policies_usage_overview": {
        "doc": "Aggregate policy pass/block counts over a date window.",
        "params": {"start_date": _START, "end_date": _END},
    },
    "resolve_policies": {
        "doc": "Resolve which policies and guardrails apply to a given context.",
        "body": "Read-only: returns the effective guardrails for the described "
        "request context (key/model/team/tags); it changes nothing.",
        "params": {
            "key_alias": "Key alias to resolve for.",
            "model": "Model name to resolve for.",
            "tags": "Tags to resolve for.",
            "team_alias": "Team alias to resolve for.",
            "force_sync": "Force a DB sync before resolving; default uses the in-memory cache.",
        },
    },
    "estimate_attachment_impact": {
        "doc": "Preview how many keys/teams a would-be attachment would affect.",
        "body": "Read-only: estimates the blast radius of the described attachment "
        "without creating it.",
        "params": _ATTACH_PARAMS,
    },
    "create_policy": {
        "doc": "Create a policy (DB-backed policy engine).",
        "params": {
            "policy_name": "Unique name for the policy.",
            "inherit": _POLICY_INHERIT,
            "description": _POLICY_DESCRIPTION,
            "guardrails_add": _POLICY_GADD,
            "guardrails_remove": _POLICY_GREMOVE,
            "condition": _POLICY_CONDITION,
            "pipeline": _POLICY_PIPELINE,
        },
    },
    "update_policy": {
        "doc": "Update a policy version's fields.",
        "params": {
            "policy_id": _POLICY_ID,
            "policy_name": "New name for the policy.",
            "inherit": _POLICY_INHERIT,
            "description": _POLICY_DESCRIPTION,
            "guardrails_add": _POLICY_GADD,
            "guardrails_remove": _POLICY_GREMOVE,
            "condition": _POLICY_CONDITION,
            "pipeline": _POLICY_PIPELINE,
        },
    },
    "create_policy_version": {
        "doc": "Create a new draft version of a policy by cloning an existing one.",
        "params": {
            "policy_name": _POLICY_NAME_ADDR,
            "source_policy_id": "Policy version ID to clone from; omit to clone the "
            "current production version.",
        },
    },
    "update_policy_version_status": {
        "doc": "Activate a policy version (publish or promote to production).",
        "body": "Moves the addressed version to the given status. 'published' stages "
        "it; 'production' makes it the live version. A version starts as a draft and "
        "is promoted through this endpoint.",
        "params": {
            "policy_id": _POLICY_ID,
            "version_status": "Target status: 'published' (staged) or 'production' (live).",
        },
        # Snapshot types this as a bare string; narrow to the documented settable
        # values so a bad status is rejected by Pydantic before any HTTP call.
        "types": {"version_status": "Literal['published', 'production']"},
    },
    "create_policy_attachment": {
        "doc": "Attach a policy to keys, teams, models, or tags.",
        "body": "Binds the named policy to the given scope so its guardrails apply "
        "to matching requests. Use estimate_attachment_impact first to preview reach.",
        "params": _ATTACH_PARAMS,
    },
    "test_policy_pipeline": {
        "doc": "Run test messages through a guardrail pipeline and report the outcome.",
        "body": "Evaluation only: nothing is stored; the response is the pipeline's "
        "pass/block result for the given messages.",
        "params": {
            "pipeline": "Pipeline definition with 'mode' and 'steps'.",
            "test_messages": "Messages to run through the pipeline, e.g. "
            "[{'role': 'user', 'content': '...'}].",
        },
    },
    "delete_policy": {
        "doc": "Delete one policy version (irreversible).",
        "params": {"policy_id": _POLICY_ID},
    },
    "delete_policy_all_versions": {
        "doc": "Delete a policy and every one of its versions (irreversible).",
        "params": {"policy_name": _POLICY_NAME_ADDR},
    },
    "delete_policy_attachment": {
        "doc": "Remove a policy attachment (irreversible).",
        "params": {"attachment_id": _ATTACHMENT_ID},
    },
    # ===================== platform: evals ==============================
    "list_evals": {
        "doc": "List evals (OpenAI-Evals-compatible; cursor-paginated).",
        "params": {
            "limit": "Page size (cursor pagination).",
            "after": "Return items after this eval ID (forward paging).",
            "before": "Return items before this eval ID (backward paging).",
            "order": "Sort direction by created_at: 'asc' or 'desc'.",
            "order_by": "Field to sort by, e.g. 'created_at'.",
            "custom_llm_provider": _CUSTOM_LLM_PROVIDER,
        },
    },
    "get_eval": {
        "doc": "Get one eval's definition.",
        "params": {"eval_id": "Eval ID.", "custom_llm_provider": _CUSTOM_LLM_PROVIDER},
    },
    "list_eval_runs": {
        "doc": "List an eval's runs (cursor-paginated).",
        "params": {
            "eval_id": "Eval ID.",
            "limit": "Page size (cursor pagination).",
            "after": "Return runs after this run ID.",
            "before": "Return runs before this run ID.",
            "order": "Sort direction by created_at: 'asc' or 'desc'.",
            "custom_llm_provider": _CUSTOM_LLM_PROVIDER,
        },
    },
    "get_eval_run": {
        "doc": "Get one eval run's status and results.",
        "params": {
            "eval_id": "Eval ID.",
            "run_id": "Eval run ID.",
            "custom_llm_provider": _CUSTOM_LLM_PROVIDER,
        },
    },
    "cancel_eval": {
        "doc": "Cancel an eval and stop its in-flight runs.",
        "params": {"eval_id": "Eval ID.", "custom_llm_provider": _CUSTOM_LLM_PROVIDER},
    },
    "cancel_eval_run": {
        "doc": "Cancel a single eval run.",
        "params": {
            "eval_id": "Eval ID.",
            "run_id": "Eval run ID.",
            "custom_llm_provider": _CUSTOM_LLM_PROVIDER,
        },
    },
    "delete_eval": {
        "doc": "Delete an eval and all its runs (irreversible).",
        "params": {"eval_id": "Eval ID.", "custom_llm_provider": _CUSTOM_LLM_PROVIDER},
    },
    "delete_eval_run": {
        "doc": "Delete a single eval run (irreversible).",
        "params": {
            "eval_id": "Eval ID.",
            "run_id": "Eval run ID.",
            "custom_llm_provider": _CUSTOM_LLM_PROVIDER,
        },
    },
    # ===================== platform: a2a agents =========================
    "list_agents": {
        "doc": "List registered A2A agents (rows slimmed; secrets omitted).",
        "params": {
            "health_check": "true probes each agent's URL and drops unreachable ones "
            "(HTTP >= 500); agents without a URL are kept.",
        },
    },
    "get_agent": {
        "doc": "Get one registered A2A agent's full config.",
        "params": {"agent_id": "Agent ID."},
    },
    "get_agent_card": {
        "doc": "Get an agent's public A2A card, as A2A clients discover it.",
        "params": {"agent_id": "Agent ID."},
    },
    "create_agent": {
        "doc": "Register an A2A agent.",
        "body": "static_headers may carry backend credentials; they are write-only "
        "and never returned in list output.",
        "params": _AGENT_PARAMS,
    },
    "update_agent": {
        "doc": "Replace an A2A agent's config (full update).",
        "params": {"agent_id": "Agent ID.", **_AGENT_PARAMS},
    },
    "patch_agent": {
        "doc": "Update some of an A2A agent's fields (partial update).",
        "params": {"agent_id": "Agent ID.", **_AGENT_PARAMS},
    },
    "delete_agent": {
        "doc": "Remove a registered A2A agent.",
        "params": {"agent_id": "Agent ID."},
    },
    "agent_daily_activity": {
        "doc": "Per-day A2A agent usage and spend.",
        "params": {
            "agent_ids": "Comma-separated agent IDs to include.",
            "exclude_agent_ids": "Comma-separated agent IDs to exclude.",
            "start_date": _START,
            "end_date": _END,
            "model": "Filter to a single model name.",
            "api_key": "Filter to a single hashed key token.",
            "page": _PAGE,
            "page_size": _PAGE_SIZE,
        },
    },
    # ===================== platform: workflow runs ======================
    "list_workflow_runs": {
        "doc": "List workflow runs (filter by type/status).",
        "params": {
            "workflow_type": "Filter by workflow type.",
            "status": "Filter by run status.",
            "limit": "Max runs to return.",
        },
    },
    "get_workflow_run": {
        "doc": "Get one workflow run's details.",
        "params": {"run_id": "Workflow run ID."},
    },
    "list_workflow_events": {
        "doc": "List a workflow run's events.",
        "params": {"run_id": "Workflow run ID.", "limit": "Max events to return."},
    },
    "list_workflow_messages": {
        "doc": "List a workflow run's messages.",
        "params": {"run_id": "Workflow run ID.", "limit": "Max messages to return."},
    },
    "create_workflow_run": {
        "doc": "Start a new workflow run.",
        "params": {
            "workflow_type": "Type of workflow to run.",
            "input": "Initial input payload for the run.",
            "metadata": _METADATA,
        },
    },
    "update_workflow_run": {
        "doc": "Update a workflow run's status or output.",
        "params": {
            "run_id": "Workflow run ID.",
            "status": "New run status.",
            "output": "Run output payload.",
            "metadata": _METADATA,
        },
    },
    "append_workflow_event": {
        "doc": "Append an event to a workflow run.",
        "params": {
            "run_id": "Workflow run ID.",
            "event_type": "Event type label.",
            "step_name": "Name of the workflow step the event belongs to.",
            "data": "Event payload.",
        },
    },
    "append_workflow_message": {
        "doc": "Append a message to a workflow run.",
        "params": {
            "run_id": "Workflow run ID.",
            "role": "Message role, e.g. 'user' or 'assistant'.",
            "content": "Message content.",
            "session_id": "Session this message belongs to.",
        },
    },
    # ===================== platform: cloudzero ==========================
    "cloudzero_settings": {
        "doc": "Get the CloudZero export settings (API key masked).",
    },
    "cloudzero_dry_run": {
        "doc": "Preview a CloudZero spend export without sending anything.",
        "body": "Read-only: returns exactly what a real export would push, so you can "
        "review the payload before running cloudzero_export.",
        "params": _CZ_PARAMS,
        "types": {"operation": _CZ_OPERATION},
    },
    "init_cloudzero": {
        "doc": "Configure CloudZero export credentials.",
        "params": {
            "api_key": "CloudZero API key (write-only; stored, never returned).",
            "connection_id": "CloudZero connection ID for data submission.",
            "timezone": "Timezone for date handling (default: UTC).",
        },
    },
    "update_cloudzero_settings": {
        "doc": "Update the CloudZero export credentials.",
        "params": {
            "api_key": "New CloudZero API key (write-only).",
            "connection_id": "New CloudZero connection ID.",
            "timezone": "New timezone for date handling.",
        },
    },
    "cloudzero_export": {
        "doc": "Export spend data to CloudZero.",
        "body": "This PUSHES aggregated spend data to CloudZero, an external SaaS "
        "billing platform - the data leaves your infrastructure. Run cloudzero_dry_run "
        "first to review exactly what would be sent.",
        "params": _CZ_PARAMS,
        "types": {"operation": _CZ_OPERATION},
    },
    "delete_cloudzero_settings": {
        "doc": "Delete the CloudZero export settings (irreversible).",
    },
    # ===================== prompts =======================================
    "list_prompts": {
        "doc": "List prompts (rows slimmed; secret-bearing litellm_params dropped).",
        "params": {"environment": _PROMPT_ENV},
    },
    "get_prompt": {
        "doc": "Get one prompt's full spec, template, and environments.",
        "body": "Returns the full PromptInfoResponse (not slimmed). Its "
        "prompt_spec.litellm_params is secret-bearing (api_key, dotprompt_content), "
        "so treat this response as sensitive.",
        "params": {
            "prompt_id": "Prompt ID to look up.",
            "environment": _PROMPT_ENV,
        },
    },
    "list_prompt_versions": {
        "doc": "List every stored version of one prompt (rows slimmed).",
        "params": {
            "prompt_id": "Prompt ID whose versions to list.",
            "environment": _PROMPT_ENV,
        },
    },
    "create_prompt": {
        "doc": "Register a prompt in the Prompt Management registry.",
        "body": "Two shapes via litellm_params: an INLINE dotprompt "
        "(prompt_integration='dotprompt' with dotprompt_content carrying the "
        "template and its frontmatter), or an EXTERNAL registry reference "
        "(prompt_integration naming the provider, api_base/api_key/prompt_id "
        "pointing at it). prompt_id here is the registry key you assign.",
        "params": {
            "prompt_id": "Unique prompt identifier you assign (the registry key).",
            "litellm_params": _PROMPT_LITELLM_PARAMS,
            "prompt_info": _PROMPT_INFO,
        },
    },
    "patch_prompt": {
        "doc": "Partially update a prompt (only the fields you pass).",
        "params": {
            "prompt_id": "Prompt ID to patch.",
            "litellm_params": _PROMPT_LITELLM_PARAMS,
            "prompt_info": _PROMPT_INFO,
            "environment": _PROMPT_ENV,
        },
    },
    "delete_prompt": {
        "doc": "Delete a prompt (irreversible).",
        "params": {
            "prompt_id": "Prompt ID to delete.",
            "environment": _PROMPT_ENV,
        },
    },
}
