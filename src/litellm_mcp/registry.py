"""Tool registration primitives."""

from __future__ import annotations

from typing import Any, Callable, TypeVar


class Group:
    """A named group of MCP tool operations exposed as a single meta-tool."""

    __slots__ = ("name", "doc")

    def __init__(self, name: str, doc: str) -> None:
        self.name = name
        self.doc = doc


ROOT = Group("root", "")


class _Unset:
    """Sentinel singleton: caller did not pass this field.

    Distinct from None. None means "caller explicitly passed null" - the
    LiteLLM API treats null as a clearing operation on some nullable body
    fields. Optional body params declared with default _UNSET carry the
    omitted-vs-cleared distinction through Pydantic validation
    (exclude_unset=True) and on to the wire: body construction drops _UNSET
    but keeps an explicit None.
    """

    _instance: "_Unset | None" = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "_UNSET"

    def __bool__(self) -> bool:
        return False


# `Any` by design: tool signatures declare their public type (e.g. `str |
# None`) and use `_UNSET` as the default. If `_UNSET` were typed as
# `_Unset`, every `x is _UNSET` gate would trip `comparison-overlap`.
_UNSET: Any = _Unset()


F = TypeVar("F", bound=Callable[..., Any])


def _op(group: Group) -> Callable[[F], F]:
    """Mark a function as an MCP tool in the given group.

    A Pydantic params model is built from the signature at server registration
    time; descriptions/constraints in `Annotated[T, Field(...)]` flow into the
    JSON Schema returned by `operation='schema'`.
    """
    def decorator(fn: F) -> F:
        if not fn.__doc__:
            raise RuntimeError(f"Tool function {fn.__name__!r} has no docstring")
        setattr(fn, "_mcp_group", group)
        return fn
    return decorator
