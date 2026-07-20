"""Step 3 fixtures: v2.5 dispatch core (_build_params_model, _dispatch,
_build_help, _build_schema, _make_tool) against a tiny synthetic group.

The synthetic group keeps these tests independent of the (still empty at
Step 3) generated tool inventory.
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Annotated, cast

import pytest
from pydantic import Field

import litellm_mcp.server as server
from litellm_mcp.registry import _UNSET, Group

GROUP = "test_group"

_received: list[dict] = []


def first_op(name: str) -> dict:
    """Create a thing."""
    return {"name": name}


def second_op(
    tag: Annotated[str | None, Field(description="Tag to attach.")] = cast(
        "str | None", _UNSET
    ),
) -> dict:
    """List things.

    Extra context line that should render indented under the signature.
    """
    kwargs = {} if tag is _UNSET else {"tag": tag}
    _received.append(kwargs)
    return kwargs


def shapes_op(
    req: str,
    nul: str | None,
    opt: str = cast("str", _UNSET),
    opt_nul: str | None = cast("str | None", _UNSET),
) -> dict:
    """Render shapes across required, optional, and nullable params."""
    return {"req": req}


@pytest.fixture
def tiny_group(monkeypatch):
    _received.clear()
    group = Group(GROUP, "Synthetic group for dispatch tests.")
    ops = {}
    for fn in (first_op, second_op, shapes_op):
        fn._mcp_group = group
        server._prepare_op(fn)
        ops[server._to_pascal(fn.__name__)] = fn
    monkeypatch.setitem(server._group_ops, GROUP, ops)
    for pascal in ops:
        monkeypatch.setitem(server._all_grouped, pascal, GROUP)
    return ops


async def test_help_shows_ops_marker_and_bullet(tiny_group):
    out = await server._dispatch("help", GROUP, {})
    assert "FirstOp(name: str)" in out
    assert "SecondOp(tag?: str | None)" in out
    assert "Create a thing." in out
    assert "    tag: Tag to attach." in out
    assert "    Extra context line" in out


async def test_help_renders_all_four_param_shapes(tiny_group):
    out = await server._dispatch("help", GROUP, {})
    # required, nullable-required, optional, optional+nullable
    assert (
        "ShapesOp(req: str, nul: str | None, opt?: str, opt_nul?: str | None)"
        in out
    )


async def test_unset_never_in_help_output(tiny_group):
    out = await server._dispatch("help", GROUP, {})
    assert "_Unset" not in out
    assert "_UNSET" not in out


async def test_schema_via_dispatch(tiny_group):
    first = await server._dispatch("schema", GROUP, {"op": "FirstOp"})
    assert first["additionalProperties"] is False
    assert first["required"] == ["name"]
    second = await server._dispatch("schema", GROUP, {"op": "SecondOp"})
    assert second["properties"]["tag"]["description"] == "Tag to attach."


async def test_unset_never_in_schema_output(tiny_group):
    for op in ("FirstOp", "SecondOp", "ShapesOp"):
        dumped = json.dumps(await server._dispatch("schema", GROUP, {"op": op}))
        assert "_Unset" not in dumped
        assert "_UNSET" not in dumped


def test_build_schema_direct(tiny_group):
    via_helper = server._build_schema(GROUP, "FirstOp")
    assert via_helper["additionalProperties"] is False
    assert via_helper["required"] == ["name"]


async def test_schema_without_op_lists_names(tiny_group):
    out = await server._dispatch("schema", GROUP, {})
    assert out == ["FirstOp", "SecondOp", "ShapesOp"]


async def test_unknown_op_names_known_ops(tiny_group):
    with pytest.raises(ValueError) as exc:
        await server._dispatch("NoSuchOp", GROUP, {})
    msg = str(exc.value)
    assert "FirstOp" in msg
    assert "SecondOp" in msg


async def test_unknown_param_names_field_and_points_at_schema(tiny_group):
    with pytest.raises(ValueError, match="foo") as exc:
        await server._dispatch("FirstOp", GROUP, {"name": "x", "foo": "bar"})
    assert "operation='schema'" in str(exc.value)


async def test_missing_required_param(tiny_group):
    with pytest.raises(ValueError, match="name"):
        await server._dispatch("FirstOp", GROUP, {})


async def test_meta_tool_no_mutable_default_leak(tiny_group):
    """Two dispatches through the meta-tool share no state: the second call's
    params must not leak into a later default-args call."""
    tool_fn = server._make_tool(GROUP, "doc")
    assert await tool_fn("SecondOp") == {}
    assert await tool_fn("SecondOp", {"tag": "x"}) == {"tag": "x"}
    assert await tool_fn("SecondOp") == {}
    assert _received == [{}, {"tag": "x"}, {}]


async def test_wrong_group_hint(tiny_group, monkeypatch):
    """An op that lives in another group is redirected there, not reported as
    unknown."""
    other = Group("other_group", "Other synthetic group.")

    def other_op(x: int) -> dict:
        """An op in another group."""
        return {"x": x}

    other_op._mcp_group = other
    server._prepare_op(other_op)
    monkeypatch.setitem(server._group_ops, "other_group", {"OtherOp": other_op})
    monkeypatch.setitem(server._all_grouped, "OtherOp", "other_group")

    with pytest.raises(ValueError, match="other_group"):
        await server._dispatch("OtherOp", GROUP, {})


def test_reject_var_keyword_at_registration():
    """A tool declaring **kwargs is rejected when its params model is built."""

    def bad_op(**kwargs) -> dict:
        """Has a var-keyword param."""
        return kwargs

    with pytest.raises(RuntimeError, match="bad_op"):
        server._build_params_model(bad_op)


def test_docstringless_op_in_throwaway_module_crashes_registration(
    tmp_path, monkeypatch
):
    """Adversarial: a tools module with a docstring-less @_op crashes the
    import the registration walk performs, and the message names the
    function."""
    mod = tmp_path / "throwaway_bad_ops.py"
    mod.write_text(
        "from litellm_mcp.registry import _op\n"
        "from litellm_mcp.tools.groups import litellm_read\n"
        "\n"
        "@_op(litellm_read)\n"
        "def broken_op(x: int):\n"
        "    return x\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        with pytest.raises(RuntimeError, match="broken_op"):
            importlib.import_module("throwaway_bad_ops")
    finally:
        sys.modules.pop("throwaway_bad_ops", None)
