"""Help rendering for the write group (Step 6).

Signatures and Field-description bullets for the representative write ops plus
the docstring warnings the plan mandates (secret-once, credentials write-only,
litellm_params stays a dict).
"""

from __future__ import annotations

from litellm_mcp import server


def _help(search: str | None = None) -> str:
    return server._build_help("litellm_write", search=search)


def test_generate_key_signature_and_bullets():
    h = _help()
    assert "GenerateKey(" in h
    assert "key_alias?: str | None" in h
    # mandated docstring: the secret is returned exactly once.
    assert "returned ONCE" in h
    assert "max_budget: Hard USD budget cap" in h
    assert "tpm_limit: Tokens-per-minute cap." in h


def test_add_model_litellm_params_is_documented_dict():
    h = _help()
    assert "AddModel(model_name: str, litellm_params: dict, model_info: dict)" in h
    assert "litellm_params: Provider call config as a dict" in h
    assert "genuinely dynamic" in h  # documented as a per-provider opaque dict


def test_create_guardrail_signature_and_bullet():
    h = _help()
    assert "CreateGuardrail(guardrail: dict)" in h
    assert "guardrail: Guardrail spec as a dict" in h


def test_create_mcp_server_warns_credentials_write_only():
    h = _help()
    assert "CreateMcpServer(" in h
    assert "write-only" in h


def test_update_organization_override_present_with_bullets():
    """The hand-written override renders like any generated op."""
    h = _help()
    assert "UpdateOrganization(organization_id: str" in h
    assert "organization_alias: Human-readable organization name." in h


def test_unset_never_leaks_into_help():
    h = _help()
    assert "_Unset" not in h
    assert "_UNSET" not in h
