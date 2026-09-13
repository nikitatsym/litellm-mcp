"""Config contract: empty-string defaults so nothing crashes at import;
the client crashes on first use when env is missing; `_reset_settings`
isolates the cache between tests; a host-bound client beats the singleton.
"""

from __future__ import annotations

import pytest

import litellm_mcp.client as client_mod
import litellm_mcp.config as config_mod
from litellm_mcp.client import LiteLLMClient
from litellm_mcp.config import get_settings
from litellm_mcp.tools import helpers


def test_import_does_not_require_env():
    # Importing config and client with no env set must not raise.
    assert config_mod.get_settings is not None
    assert client_mod.LiteLLMClient is not None


def test_missing_env_crashes_on_client_use_not_import(monkeypatch):
    monkeypatch.delenv("LITELLM_URL", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    config_mod._reset_settings()
    # Empty defaults load fine; the crash is on first client construction, and
    # names the setting - a startup traceback has to say what is unset.
    assert get_settings().litellm_url == ""
    with pytest.raises(ValueError, match="LITELLM_URL"):
        LiteLLMClient()


def test_bound_client_wins_over_singleton(client_env):
    # A host serving several instances binds one client per request; reading the
    # module singleton instead would answer with another instance's credentials.
    bound = LiteLLMClient(base_url="https://bound.test", api_key="sk-bound")
    token = helpers.client_var.set(bound)
    try:
        assert helpers._get_client() is bound
    finally:
        helpers.client_var.reset(token)
    assert helpers._get_client() is not bound


def test_reset_settings_isolates(monkeypatch):
    monkeypatch.delenv("LITELLM_URL", raising=False)
    config_mod._reset_settings()
    assert get_settings().litellm_url == ""
    # A new env value is invisible until the cache is dropped.
    monkeypatch.setenv("LITELLM_URL", "https://a.test")
    assert get_settings().litellm_url == ""
    config_mod._reset_settings()
    assert get_settings().litellm_url == "https://a.test"
