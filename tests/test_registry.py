"""Registry sentinel identity and operation decoration contracts."""

from __future__ import annotations

import pytest

from litellm_mcp.registry import UNSET, Group, Unset, op


def test_unset_singleton():
    assert Unset() is UNSET
    assert Unset() is Unset()


def test_unset_falsy_for_optional_filter():
    assert not UNSET


def test_op_without_docstring_raises_and_names_function():
    """Adversarial: a docstring-less op must be rejected loudly at import (the
    decorator runs when the module defining the op is imported)."""
    g = Group("g", "doc")
    with pytest.raises(RuntimeError) as ei:
        @op(g)
        def missing_docstring(x: int):
            pass

    assert "missing_docstring" in str(ei.value)


def test_op_with_docstring_tags_group():
    g = Group("g", "doc")

    @op(g)
    def has_docstring(x: int):
        """Present."""
        return x

    assert has_docstring._mcp_group is g
