"""Registry primitives: the `@_op` docstring guard fires at decoration time,
and the `_UNSET` sentinel is a falsy singleton with a stable repr.
"""

from __future__ import annotations

import pytest

from litellm_mcp.registry import _UNSET, Group, _Unset, _op


def test_unset_singleton():
    assert _Unset() is _UNSET
    assert _Unset() is _Unset()


def test_unset_falsy():
    assert not _UNSET
    assert bool(_UNSET) is False


def test_unset_repr():
    assert repr(_UNSET) == "_UNSET"


def test_op_without_docstring_raises_and_names_function():
    """Adversarial: a docstring-less op must be rejected loudly at import (the
    decorator runs when the module defining the op is imported)."""
    g = Group("g", "doc")
    with pytest.raises(RuntimeError) as ei:
        @_op(g)
        def missing_docstring(x: int):
            pass

    assert "missing_docstring" in str(ei.value)


def test_op_with_docstring_tags_group():
    g = Group("g", "doc")

    @_op(g)
    def has_docstring(x: int):
        """Present."""
        return x

    assert has_docstring._mcp_group is g
