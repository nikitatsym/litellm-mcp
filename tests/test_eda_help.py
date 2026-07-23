"""Help rendering for the execute / delete / admin groups (Step 7).

Signatures, Field-description bullets, and the destructive docstring bodies the
plan mandates (delete_keys, cache_flushall, global_spend_reset irreversibility;
regenerate_key secret-once + body-variant).
"""

from __future__ import annotations

from litellm_mcp import server


def _help(group: str, search: str | None = None) -> str:
    return server._build_help(group, search=search)


# --- execute ----------------------------------------------------------------

def test_execute_signatures_and_bullets():
    h = _help("litellm_execute")
    assert "BlockKey(key: str) - Block a virtual key (reversible via unblock_key)." in h
    assert "key: Virtual key to block; hashed token from list_keys accepted." in h
    assert "BlockCustomer(user_ids: list[str])" in h
    assert "user_ids: Customer IDs to block; every listed ID in one call." in h


def test_regenerate_key_secret_once_and_body_variant():
    h = _help("litellm_execute")
    assert "RegenerateKey(" in h
    assert "returned ONCE" in h
    assert "never lands in proxy access logs" in h  # Decision 9 body-variant note


def test_cache_delete_override_present_in_execute_help():
    """The hand-written override renders like any generated execute op."""
    h = _help("litellm_execute")
    assert "CacheDelete(keys: list[str])" in h
    assert "keys: Cache keys to delete; must be non-empty." in h


def test_apply_guardrail_help_cost_note():
    """The guardrail-loop override renders with the loud cost note (Decision 2)."""
    h = _help("litellm_execute")
    assert "ApplyGuardrail(guardrail_name: str, text: str, input_type: str = 'request'" in h
    assert "MAY SPEND MONEY" in h  # provider-backed types call an external service
    assert "resolved BY NAME" in h  # 404-on-unknown-name resolution documented
    assert "guardrail_name: NAME of an initialized guardrail" in h


def test_invoke_agent_guardrails_bullet_in_help():
    """invoke_agent's new guardrails param surfaces the silent-unknown-name warning."""
    h = _help("litellm_execute")
    assert "InvokeAgent(" in h
    assert "SILENTLY SKIPPED on this path" in h  # unlike apply_guardrail's 404
    assert "check a name with list_guardrails or apply_guardrail first." in h


# --- delete -----------------------------------------------------------------

def test_delete_signatures_and_irreversible_bodies():
    h = _help("litellm_delete")
    assert "DeleteKeys(" in h
    assert "keys: Key tokens to delete; every listed key is removed in one call." in h
    assert "Irreversible" in h  # delete bodies say what cannot be undone
    assert "CacheFlushall() - Flush the ENTIRE proxy cache." in h
    assert "wipes every cached entry" in h


# --- admin ------------------------------------------------------------------

def test_admin_signatures_and_global_reset_body():
    h = _help("litellm_admin")
    assert "GlobalSpendReset() - Reset ALL global spend counters to zero." in h
    assert "the running totals cannot be restored" in h
    assert "AddAllowedIp(ip: str)" in h
    assert "ip: IPv4/IPv6 address or CIDR to allow." in h
    assert "BulkUpdateUsers(" in h


# --- search + sentinel hygiene ----------------------------------------------

def test_search_matches_within_execute():
    h = _help("litellm_execute", search="regenerate")
    assert "RegenerateKey(" in h
    assert "BlockKey(" not in h


def test_unset_never_leaks_into_help():
    for group in ("litellm_execute", "litellm_delete", "litellm_admin"):
        h = _help(group)
        assert "_Unset" not in h
        assert "_UNSET" not in h
