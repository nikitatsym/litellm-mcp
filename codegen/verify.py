"""Per-write-op verify data (write module authored in Step 6).

`ROOT_SKIP` is the global root-level skip set (request-only / transformed
transport fields). Each `VERIFY` entry is keyed by op name; an unknown key is a
generation-time error. Exactly one form per entry:

    VERIFY[op] = {"skip": [...]}      # full verify; drop these extra root keys
    VERIFY[op] = {"subset": [...]}    # verify only this subset of sent body keys
    VERIFY[op] = {"no_verify": "..."} # body is not echoed as a row; reason string

`subset` is the tool for LiteLLM's partial row echoes: the response is the
stored DB row, which omits most request-only knobs, so a full presence check
would false-positive on every un-echoed field. `subset` whitelists the scalar
identity/limit fields the typed response schema proves are echoed - a real drop
of any of them still raises. `skip`-form (full verify) is reserved for the few
ops whose typed response echoes the entire sent body cleanly.

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
    "200 response is untyped {} in the snapshot; the echoed row shape is not "
    "provable pre-live (Decision 10). Revisit in Step 9 and promote to subset."
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
    # --- no_verify: untyped {} response, unprovable pre-live -------------------
    "update_key": {"no_verify": _UNTYPED},
    "update_team": {"no_verify": _UNTYPED},
    "team_model_add": {"no_verify": _UNTYPED},
    "update_user": {"no_verify": _UNTYPED},
    "new_budget": {"no_verify": _UNTYPED},
    "update_budget": {"no_verify": _UNTYPED},
    "add_model": {"no_verify": _UNTYPED},
    "update_model": {"no_verify": _UNTYPED},
    "patch_model": {"no_verify": _UNTYPED},
    "create_access_group": {"no_verify": _UNTYPED},
    "create_mcp_server": {"no_verify": _UNTYPED},
    "update_mcp_server": {"no_verify": _UNTYPED},
    "create_toolset": {"no_verify": _UNTYPED},
    "update_toolset": {"no_verify": _UNTYPED},
    "create_credential": {"no_verify": _UNTYPED},
    "update_credential": {"no_verify": _UNTYPED},
    "new_tag": {"no_verify": _UNTYPED},
    "update_tag": {"no_verify": _UNTYPED},
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
}
