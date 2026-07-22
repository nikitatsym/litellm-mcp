"""Per-write-op verify data (write module authored in Step 6).

`ROOT_SKIP` is the global root-level skip set (request-only / transformed
transport fields). Each `VERIFY` entry is keyed by op name; an unknown key is a
generation-time error. Exactly one form per entry:

    VERIFY[op] = {"skip": [...]}      # full verify; drop these extra root keys
    VERIFY[op] = {"subset": [...]}    # verify only this subset of sent body keys
    VERIFY[op] = {"present": [...]}   # assert these response keys exist (not sent)
    VERIFY[op] = {"no_verify": "..."} # body is not echoed as a row; reason string

`subset` is the tool for LiteLLM's partial row echoes: the response is the
stored DB row, which omits most request-only knobs, so a full presence check
would false-positive on every un-echoed field. `subset` whitelists the scalar
identity/limit fields the typed response schema proves are echoed - a real drop
of any of them still raises. `skip`-form (full verify) is reserved for the few
ops whose typed response echoes the entire sent body cleanly.

`present` (added Step 7) checks RESPONSE keys the typed schema proves, regardless
of what was sent: block/unblock ops echo the updated row's `blocked` state (or a
`blocked_users` result field), not the addressing key posted, so subset (which
filters SENT keys) cannot express it. A real drop of the named response key still
raises - this is the mechanism behind the mandatory block_key adversarial.

`no_verify` covers two families: (1) ops whose 200 response is untyped `{}` in
the snapshot - the echoed shape cannot be proven pre-live, so verifying would
risk false positives; Step 9 confirms these live and promotes them to `subset`;
(2) ops that genuinely do not echo the body as a row (member-add expands the
member into user/membership objects; callback registration returns a status
envelope).

Every entry after this step needs explicit sign-off: a stray `skip` on a field
that DOES echo silently weakens a real check.
"""

from __future__ import annotations

from typing import Any

# Request-only or transformed transport fields, never echoed as-is on the row.
# `duration` -> `expires`; `key` is the addressing/secret field (echoed as the
# `token` hash on updates); `auto_create_key` / `send_invite_email` are consumed
# side-effect flags; `budget_duration` -> a budget-table reset schedule.
ROOT_SKIP: frozenset[str] = frozenset(
    {"duration", "key", "auto_create_key", "send_invite_email", "budget_duration"}
)

_UNTYPED = (
    "200 response is untyped {} in the snapshot and the Step-9 lifecycle does not "
    "exercise this op, so the live echo was not observed; kept no_verify (residue) "
    "rather than guessing a subset (Decision 10)."
)

# --- Step 9 live-observation reasons (promotion sweep, cited from the pinned image) --
_DEL_ROW_ID = (
    "live: returns the deleted budget row keyed by budget_id, not the sent `id` "
    "param; no sent key is echoed under its own name to presence-check."
)
_DEL_MSG = (
    "live: returns a {message} confirmation string, not a row echoing the sent id."
)
_DEL_COUNT = (
    "live: returns a bare integer count of deleted rows; _verify_response no-ops "
    "on a non-dict response."
)

# Step-7 NO_VERIFY reasons that are NOT untyped-promotable (the Step 9 sweep
# greps for _UNTYPED and skips these): genuine non-echo responses.
_BODYLESS = (
    "bodyless op (no request body); nothing is sent that could be echoed. "
    "Not promotable to a body check."
)
_PROBE = (
    "connection probe; the response is a pass/fail result envelope, not an "
    "echoed write row."
)
_OPAQUE_BODY = (
    "opaque free-form config-map body (no named fields) and an untyped {} "
    "response; nothing named to echo-check."
)
_LIST_RESP = (
    "returns a list of deleted rows; _verify_response no-ops on a non-dict "
    "(list) response, so there is nothing to check."
)
_SECRET_ONLY = (
    "200 response is untyped {} and the only sent field is the secret key "
    "(root transport); there is no echoable field. Not promotable."
)
_RESET_SPEND = (
    "response is an opaque status object (additionalProperties, no typed "
    "fields); the sent reset_to becomes the row's spend (transformed), not echoed."
)

# Platform (Step 8) non-promotable reasons.
_COPY_FROM = (
    "the sole sent field (source_policy_id) is a copy-from pointer consumed "
    "server-side (the row uses parent_version_id); nothing sent is echoed."
)
_TEST_RESULT = (
    "pipeline test: nothing is stored; the response is a pass/block result "
    "envelope, not an echoed write row."
)
_CZ_ENVELOPE = (
    "CloudZeroInitResponse is a {message, status} envelope; the sent settings "
    "are not echoed (api_key is a write-only secret)."
)
_CZ_EXPORT = (
    "CloudZeroExportResponse is an export-result summary (records_exported, "
    "summary); the sent window params are not echoed as a row."
)

VERIFY: dict[str, dict[str, Any]] = {
    # --- subset: partial row echo, verify the scalar fields the schema proves --
    "generate_key": {
        # GenerateKeyResponse echoes these; the secret rides `key`/`token`
        # (root-skipped) and `duration` becomes `expires`.
        "subset": ["key_alias", "user_id", "team_id", "max_budget", "tpm_limit", "rpm_limit"],
    },
    "new_team": {
        "subset": [
            "team_alias", "team_id", "organization_id", "max_budget",
            "tpm_limit", "rpm_limit", "blocked",
        ],
    },
    "new_user": {
        "subset": ["user_id", "user_email", "user_role", "max_budget", "tpm_limit", "rpm_limit"],
    },
    "new_customer": {
        "subset": ["user_id", "alias", "blocked", "allowed_model_region", "default_model", "budget_id"],
    },
    "update_customer": {
        "subset": ["user_id", "alias", "blocked", "allowed_model_region", "default_model", "budget_id"],
    },
    "new_organization": {
        # tpm/rpm/max_budget land in litellm_budget_table, not on the org row.
        "subset": ["organization_alias", "organization_id", "budget_id", "models"],
    },
    "organization_member_update": {
        # max_budget_in_organization -> budget table; role -> user_role.
        "subset": ["organization_id", "user_id"],
    },
    "team_member_update": {
        # TeamMemberUpdateResponse echoes the membership; `role` is transformed.
        "subset": ["team_id", "user_id", "max_budget_in_team", "tpm_limit", "rpm_limit"],
    },
    "team_permissions_update": {
        "subset": ["team_id", "team_member_permissions"],
    },
    # --- skip-form full verify: typed response echoes the whole sent body ------
    "update_access_group": {"skip": []},  # AccessGroupResponse echoes every body field
    "create_fallback": {"skip": []},      # FallbackResponse echoes model/fallback_models/fallback_type
    # --- Step 9 promotions: live echo observed, promoted from _UNTYPED ---------
    # update_key echoes the full key row at root; verify the mutable scalar knobs.
    "update_key": {"subset": ["tpm_limit", "rpm_limit", "max_budget", "metadata", "models"]},
    # update_team/update_user wrap the row under a nested `data` key; only the
    # addressing id is at root, so that is the one presence-checkable sent field.
    "update_team": {"subset": ["team_id"]},
    "update_user": {"subset": ["user_id"]},
    # new_budget/update_budget echo the full budget row at root.
    "new_budget": {"subset": ["budget_id", "max_budget", "soft_budget", "tpm_limit", "rpm_limit"]},
    "update_budget": {"subset": ["budget_id", "max_budget", "soft_budget", "tpm_limit", "rpm_limit"]},
    # add_model echoes the deployment row; model_name is the sent identity at root
    # (litellm_params values are encrypted on the echo, model_id is server-assigned).
    "add_model": {"subset": ["model_name"]},
    # create_access_group echoes the full group row (name + grant lists) at root.
    "create_access_group": {"subset": ["access_group_name", "access_mcp_server_ids", "access_model_names"]},
    # create/update_mcp_server echo the server row; credentials come back null
    # (write-only) so they are excluded - verify the plain scalar config fields.
    "create_mcp_server": {"subset": ["server_name", "url", "transport", "auth_type"]},
    "update_mcp_server": {"subset": ["server_id", "url", "transport", "description"]},
    # new_tag/update_tag return {message, tag}; the row is under `tag`, so a subset
    # on the flat sent keys cannot reach it - assert the tag object is present.
    "new_tag": {"present": ["tag"]},
    "update_tag": {"present": ["tag"]},
    # --- residue: untyped {} response, NOT exercised by the Step-9 lifecycle ----
    "team_model_add": {"no_verify": _UNTYPED},
    "update_model": {"no_verify": _UNTYPED},
    "patch_model": {"no_verify": _UNTYPED},
    "create_toolset": {"no_verify": _UNTYPED},
    "update_toolset": {"no_verify": _UNTYPED},
    "create_credential": {"no_verify": _UNTYPED},
    "update_credential": {"no_verify": _UNTYPED},
    "create_guardrail": {"no_verify": _UNTYPED},
    "update_guardrail": {"no_verify": _UNTYPED},
    # --- no_verify: body genuinely not echoed as a row ------------------------
    "team_member_add": {
        "no_verify": "TeamAddMemberResponse expands the member into "
        "updated_users / updated_team_memberships; the sent member is not a row field.",
    },
    "organization_member_add": {
        "no_verify": "OrganizationAddMemberResponse returns updated_users / "
        "updated_organization_memberships; the sent member is not a row field.",
    },
    "add_team_callback": {
        "no_verify": "returns a status envelope, not the callback config as a row.",
    },
    # ===================== execute (Step 7) ==============================
    # block/unblock echo the updated row; verify the state/result field the
    # typed response schema proves (present), or the addressing key when the
    # response requires it (subset). cache_delete is a hand-written override.
    "block_key": {"present": ["blocked"]},  # LiteLLM_VerificationToken carries blocked
    "unblock_key": {"no_verify": _SECRET_ONLY},
    "regenerate_key": {
        # GenerateKeyResponse echoes the new key's settings (same schema/subset
        # as generate_key); the new secret rides key/token (root transport).
        "subset": ["key_alias", "user_id", "team_id", "max_budget", "tpm_limit", "rpm_limit"],
    },
    "reset_key_spend": {"no_verify": _RESET_SPEND},
    # live: block/unblock_team echo the full team row with `blocked` at root
    # (same mechanism as block_key).
    "block_team": {"present": ["blocked"]},
    "unblock_team": {"present": ["blocked"]},
    "disable_team_logging": {"no_verify": _BODYLESS},
    "block_model": {"subset": ["model_id"]},  # LiteLLM_ProxyModelTable requires model_id
    "unblock_model": {"subset": ["model_id"]},
    "block_customer": {"present": ["blocked_users"]},  # BlockUsersResponse requires it
    "unblock_customer": {"present": ["blocked_users"]},  # UnblockUsersResponse requires it
    "test_model_connection": {"no_verify": _PROBE},
    "test_cache_connection": {"no_verify": _PROBE},
    "test_mcp_connection": {"no_verify": _PROBE},
    "test_mcp_tools_list": {"no_verify": _PROBE},
    # ===================== delete (Step 7) ===============================
    # Deletes rarely echo a row; body-carrying deletes with untyped {} responses
    # are _UNTYPED (Step 9 may promote), bodyless/path-addressed ones and the few
    # typed summary/list responses get non-promotable reasons.
    # live: delete_keys/delete_teams return {deleted_keys|deleted_teams: [...]} -
    # a result list the request did not send, so assert its presence.
    "delete_keys": {"present": ["deleted_keys"]},
    "delete_teams": {"present": ["deleted_teams"]},
    "team_member_delete": {"no_verify": _UNTYPED},
    "team_model_delete": {"no_verify": _UNTYPED},
    "delete_users": {"no_verify": _DEL_COUNT},
    "delete_organizations": {"no_verify": _LIST_RESP},
    "organization_member_delete": {"no_verify": _UNTYPED},
    "delete_customers": {
        "no_verify": "DeleteCustomersResponse is a {deleted_customers, message} "
        "summary; the sent user_ids are not echoed as a row.",
    },
    "delete_budget": {"no_verify": _DEL_ROW_ID},
    "delete_model": {"no_verify": _DEL_MSG},
    "delete_access_group": {"no_verify": _BODYLESS},
    "delete_mcp_server": {"no_verify": _BODYLESS},
    "delete_toolset": {"no_verify": _BODYLESS},
    "delete_credential": {"no_verify": _BODYLESS},
    "delete_tag": {"no_verify": _UNTYPED},
    "delete_guardrail": {"no_verify": _BODYLESS},
    "delete_fallback": {"no_verify": _BODYLESS},
    "cache_flushall": {"no_verify": _BODYLESS},
    # ===================== admin (Step 7) ================================
    "update_sso_settings": {"no_verify": _UNTYPED},
    "update_default_team_settings": {"no_verify": _UNTYPED},
    "update_internal_user_settings": {"no_verify": _UNTYPED},
    "update_email_event_settings": {"no_verify": _UNTYPED},
    "reset_email_event_settings": {"no_verify": _BODYLESS},
    "update_cost_margin_config": {"no_verify": _OPAQUE_BODY},
    "update_cost_discount_config": {"no_verify": _OPAQUE_BODY},
    "update_cache_settings": {"no_verify": _UNTYPED},
    "add_allowed_ip": {"no_verify": _UNTYPED},
    "delete_allowed_ip": {"no_verify": _UNTYPED},
    "global_spend_reset": {"no_verify": _BODYLESS},
    "bulk_update_users": {
        "no_verify": "BulkUpdateUserResponse is a {results, total_requested, ...} "
        "run summary; the sent users are not echoed as a row.",
    },
    # ===================== platform: policies ============================
    # PolicyDBResponse echoes the scalar policy fields; verify the ones sent.
    "create_policy": {"subset": ["policy_name", "inherit", "description"]},
    "update_policy": {"subset": ["policy_name", "inherit", "description"]},
    # PolicyDBResponse.version_status reflects the status we set (echoed).
    "update_policy_version_status": {"subset": ["version_status"]},
    # PolicyAttachmentDBResponse echoes the scope; `scope` presence is the
    # mandatory adversarial (a) - a dropped scope must raise.
    "create_policy_attachment": {"subset": ["policy_name", "scope"]},
    "create_policy_version": {"no_verify": _COPY_FROM},
    "test_policy_pipeline": {"no_verify": _TEST_RESULT},
    "delete_policy": {"no_verify": _BODYLESS},
    "delete_policy_all_versions": {"no_verify": _BODYLESS},
    "delete_policy_attachment": {"no_verify": _BODYLESS},
    # ===================== platform: evals ==============================
    # cancel/delete are bodyless (only a query param); nothing sent to echo.
    "cancel_eval": {"no_verify": _BODYLESS},
    "cancel_eval_run": {"no_verify": _BODYLESS},
    "delete_eval": {"no_verify": _BODYLESS},
    "delete_eval_run": {"no_verify": _BODYLESS},
    # ===================== platform: a2a agents =========================
    # AgentResponse echoes the scalar knobs; verify the ones sent (name is
    # required in the response, the limits are optional so a drop is catchable).
    "create_agent": {
        "subset": ["agent_name", "tpm_limit", "rpm_limit", "session_tpm_limit", "session_rpm_limit"],
    },
    "update_agent": {
        "subset": ["agent_name", "tpm_limit", "rpm_limit", "session_tpm_limit", "session_rpm_limit"],
    },
    "patch_agent": {
        "subset": ["agent_name", "tpm_limit", "rpm_limit", "session_tpm_limit", "session_rpm_limit"],
    },
    "delete_agent": {"no_verify": _BODYLESS},
    # ===================== platform: workflow runs ======================
    # 200 is untyped {} in the snapshot but these are real create/update writes
    # that should echo the run row live - _UNTYPED so Step 9 promotes them.
    # live: workflow writes echo the run/event row at root; verify the sent fields.
    "create_workflow_run": {"subset": ["workflow_type", "input"]},
    "update_workflow_run": {"subset": ["status"]},
    "append_workflow_event": {"subset": ["event_type", "step_name", "data"]},
    # append_workflow_message is not exercised by the lifecycle - residue.
    "append_workflow_message": {"no_verify": _UNTYPED},
    # ===================== platform: cloudzero ==========================
    "init_cloudzero": {"no_verify": _CZ_ENVELOPE},
    "update_cloudzero_settings": {"no_verify": _CZ_ENVELOPE},
    "cloudzero_export": {"no_verify": _CZ_EXPORT},
    "delete_cloudzero_settings": {"no_verify": _BODYLESS},
    # ===================== prompts =======================================
    # create/patch return untyped {} in the snapshot; Step 4 promotes them to
    # `subset` from the live echo (Decision 6). delete_prompt is bodyless (path
    # id + query only) and stays no_verify - no row to check.
    "create_prompt": {"no_verify": _UNTYPED},
    "patch_prompt": {"no_verify": _UNTYPED},
    "delete_prompt": {"no_verify": _BODYLESS},
}
