"""Write-response verification tests for helpers and generated operations.

Cover recursive key presence, root-only exclusions, value normalization,
request-body omission and null handling, and dropped-field diagnostics.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from codegen import generate
from litellm_mcp.tools._generated_write import create_fallback, new_team
from litellm_mcp.tools.helpers import verify_response
from litellm_mcp.tools.overrides import update_organization

# --- verify_response semantics --------------------------------------------

def test_pass_when_all_sent_keys_present():
    verify_response({"a": 1, "b": 2}, {"a": 1, "b": 2, "c": 3})


def test_flat_drop_names_the_key():
    with pytest.raises(ValueError) as ei:
        verify_response({"a": 1, "tpm_limit": 2}, {"a": 1})
    assert "tpm_limit" in str(ei.value)


def test_nested_drop_names_full_path():
    """The mandated nested case: metadata.budget_note dropped -> full path named."""
    with pytest.raises(ValueError) as ei:
        verify_response({"metadata": {"budget_note": "x"}}, {"metadata": {}})
    assert "metadata.budget_note" in str(ei.value)


def test_non_dict_received_is_noop():
    verify_response({"a": 1}, ["not", "a", "dict"])
    verify_response({"a": 1}, None)


def test_value_equality_is_not_checked():
    # int 2 vs str "2": presence only, no false positive on normalization.
    verify_response({"tpm_limit": "2"}, {"tpm_limit": 2})


def test_root_skip_applies_at_root():
    verify_response({"key": "secret", "a": 1}, {"a": 1}, frozenset({"key"}))


def test_root_skip_does_not_apply_nested():
    """The whole point of root-only skip: a nested key by the same name still raises."""
    with pytest.raises(ValueError) as ei:
        verify_response({"config": {"key": "x"}}, {"config": {}}, frozenset({"key"}))
    assert "config.key" in str(ei.value)


# --- op-level: new_team subset verify over respx ---------------------------

def _team_row(**extra: Any) -> dict[str, Any]:
    row = {"team_alias": "t", "team_id": "team-1", "organization_id": None, "blocked": False}
    row.update(extra)
    return row


def test_new_team_verify_passes_when_row_echoes_subset(client_env, respx_mock):
    respx_mock.post("/team/new").respond(200, json=_team_row(tpm_limit=5, rpm_limit=9))
    out = new_team(team_alias="t", tpm_limit=5)
    assert out["team_id"] == "team-1"


def test_new_team_silent_drop_raises_tpm_limit(client_env, respx_mock):
    """MANDATORY adversarial 1: /team/new echoes everything except tpm_limit ->
    ValueError names tpm_limit. A green run that skips this assertion is a step
    failure."""
    # The row carries every field EXCEPT the tpm_limit we sent.
    respx_mock.post("/team/new").respond(200, json=_team_row(rpm_limit=9, max_budget=100))
    with pytest.raises(ValueError) as ei:
        new_team(team_alias="t", tpm_limit=5)
    assert "tpm_limit" in str(ei.value)


# --- body-builder gates asserted against the actual request payload --------

def test_body_builder_omitted_absent_explicit_none_null(client_env, respx_mock):
    route = respx_mock.post("/team/new").respond(200, json=_team_row(tpm_limit=5))
    # tpm_limit=5 (explicit value), metadata=None (explicit null), rpm_limit omitted.
    new_team(team_alias="t", tpm_limit=5, metadata=None)
    payload = json.loads(route.calls.last.request.content)
    assert payload["tpm_limit"] == 5           # explicit value present
    assert "metadata" in payload and payload["metadata"] is None  # explicit None -> null
    assert "rpm_limit" not in payload
    assert "team_id" not in payload            # never passed, stays off the wire


# --- override: update_organization verifies its own echo -------------------

def test_update_organization_override_verifies(client_env, respx_mock):
    respx_mock.patch("/organization/update").respond(
        200, json={"organization_id": "org-1", "organization_alias": "Acme"}
    )
    out = update_organization(organization_id="org-1", organization_alias="Acme")
    assert out["organization_id"] == "org-1"


def test_update_organization_override_raises_on_drop(client_env, respx_mock):
    # Echo omits organization_alias that we sent.
    respx_mock.patch("/organization/update").respond(200, json={"organization_id": "org-1"})
    with pytest.raises(ValueError) as ei:
        update_organization(organization_id="org-1", organization_alias="Acme")
    assert "organization_alias" in str(ei.value)


# --- MANDATORY adversarial 2: a bogus skip entry weakens a real check -------

def test_bogus_skip_entry_weakens_real_check(monkeypatch, client_env, respx_mock, regenerated_op):
    """create_fallback full-verifies the echoed row. Adding a bogus per-op skip
    for fallback_type (a field it DOES echo) and regenerating makes the drop of
    fallback_type go silent - proving skip entries weaken real checks and thus
    need the sign-off rule."""
    # /fallback echoes model + fallback_models but DROPS the fallback_type we sent.
    respx_mock.post("/fallback").respond(200, json={"model": "m", "fallback_models": ["f"]})

    # Committed verify.py: the drop is caught loudly.
    with pytest.raises(ValueError) as ei:
        create_fallback(model="m", fallback_models=["f"], fallback_type="general")
    assert "fallback_type" in str(ei.value)

    # Inject a bogus skip entry naming fallback_type and regenerate (temp context).
    monkeypatch.setattr(generate, "VERIFY", {"create_fallback": {"skip": ["fallback_type"]}})
    src = generate.emit_tree(generate.load_spec())["_generated_write.py"]

    weakened = regenerated_op(src, "create_fallback")
    # Same drop, but now it passes silently - the check was weakened.
    weakened(model="m", fallback_models=["f"], fallback_type="general")  # no raise
