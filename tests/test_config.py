"""Config contract: empty-string defaults so nothing crashes at import;
the client crashes on first use when env is missing; `_reset_settings`
isolates the cache between tests.
"""

from __future__ import annotations

import pytest

import litellm_mcp.client as client_mod
import litellm_mcp.config as config_mod
from litellm_mcp.client import LiteLLMClient
from litellm_mcp.config import get_settings


def test_import_does_not_require_env():
    # Importing config and client with no env set must not raise.
    assert config_mod.get_settings is not None
    assert client_mod.LiteLLMClient is not None


def test_missing_env_crashes_on_client_use_not_import(monkeypatch):
    monkeypatch.delenv("LITELLM_URL", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    config_mod._reset_settings()
    # Empty defaults load fine; the crash is on first client construction.
    assert get_settings().litellm_url == ""
    with pytest.raises(ValueError):
        LiteLLMClient()


def test_reset_settings_isolates(monkeypatch):
    monkeypatch.delenv("LITELLM_URL", raising=False)
    config_mod._reset_settings()
    assert get_settings().litellm_url == ""
    # A new env value is invisible until the cache is dropped.
    monkeypatch.setenv("LITELLM_URL", "https://a.test")
    assert get_settings().litellm_url == ""
    config_mod._reset_settings()
    assert get_settings().litellm_url == "https://a.test"
