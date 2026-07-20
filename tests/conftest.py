"""Unit-test scaffolding for litellm-mcp.

No docker-compose. Non-integration tests run against fake HTTP via respx;
no real LiteLLM instance and no real credentials.
"""

from __future__ import annotations

import pytest
import respx

import litellm_mcp.tools.helpers as helpers
from litellm_mcp.config import _reset_settings

TEST_BASE_URL = "https://litellm.test"


@pytest.fixture(autouse=True)
def _reset_state():
    """Drop the cached settings + client singletons before and after every
    test so env changes / a mocked client in one case never leak into the
    next."""
    _reset_settings()
    helpers._client = None
    yield
    _reset_settings()
    helpers._client = None


@pytest.fixture
def client_env(monkeypatch):
    """Set LITELLM_URL / LITELLM_API_KEY to test values and reset the cache.

    Use in tests that walk the settings/config path directly.
    """
    monkeypatch.setenv("LITELLM_URL", TEST_BASE_URL)
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test")
    _reset_settings()
    return TEST_BASE_URL


@pytest.fixture
def respx_mock():
    """respx router scoped to the fake LiteLLM base URL.

    `assert_all_called=False`: tests may register routes they do not hit.
    """
    with respx.mock(base_url=TEST_BASE_URL, assert_all_called=False) as mock:
        yield mock
