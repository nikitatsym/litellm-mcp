"""Unit-test scaffolding for litellm-mcp.

No docker-compose. Non-integration tests run against fake HTTP via respx;
no real LiteLLM instance and no real credentials.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location

import pytest
import respx

from litellm_mcp import config
from litellm_mcp.tools import helpers

TEST_BASE_URL = "https://litellm.test"


@pytest.fixture
def regenerated_op(tmp_path):
    """Load an emitted module with its actual package-relative dependencies."""
    def load_op(module_source, name):
        path = tmp_path / "regenerated.py"
        path.write_text(module_source, encoding="utf-8")
        spec = spec_from_file_location("litellm_mcp.tools.regenerated", path)
        assert spec is not None and spec.loader is not None
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, name)

    return load_op


@pytest.fixture(autouse=True)
def _reset_state():
    """Drop the cached settings + client singletons before and after every
    test so env changes / a mocked client in one case never leak into the
    next."""
    config._settings = None
    helpers._client = None
    yield
    config._settings = None
    helpers._client = None


@pytest.fixture
def client_env(monkeypatch):
    """Set LITELLM_URL / LITELLM_API_KEY to test values.

    Use in tests that walk the settings/config path directly.
    """
    monkeypatch.setenv("LITELLM_URL", TEST_BASE_URL)
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test")
    return TEST_BASE_URL


@pytest.fixture
def respx_mock():
    """respx router scoped to the fake LiteLLM base URL.

    `assert_all_called=False`: tests may register routes they do not hit.
    """
    with respx.mock(base_url=TEST_BASE_URL, assert_all_called=False) as mock:
        yield mock
