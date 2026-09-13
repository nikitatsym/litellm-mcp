"""Shared helpers for the LiteLLM tool modules.

Client accessor (request-scoped `client_var` first, module singleton
fallback), query-param builder, the slim/truncation wrappers for list
results, and `_verify_response` (the write-echo drop check).
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from ..client import LiteLLMClient
from ..registry import _UNSET

# Public: a host serving several LiteLLM instances in one process binds the
# per-request client here, so tools never read credentials from module state.
client_var: ContextVar[LiteLLMClient | None] = ContextVar("litellm_client", default=None)
_client: LiteLLMClient | None = None


def _verify_response(
    sent: dict[str, Any],
    received: Any,
    skip_root: frozenset[str] = frozenset(),
    _path: str = "",
) -> None:
    """Raise if the write echo silently dropped a key we sent (recursive).

    Presence check only: every key in `sent` must appear in `received`,
    recursing into non-empty nested dicts so a dropped nested leaf
    (`metadata.budget_note`) is named with its full path. `skip_root` lists
    request-only or transformed transport fields and is consulted at the ROOT
    level ONLY - a nested drop always raises. Values are never compared
    (LiteLLM normalizes them on the wire); presence is the whole contract. A
    non-dict `received` (no row to check against) is a no-op.
    """
    if not isinstance(received, dict):
        return
    for key, value in sent.items():
        if _path == "" and key in skip_root:
            continue
        full = f"{_path}.{key}" if _path else key
        if key not in received:
            raise ValueError(
                f"LiteLLM silently dropped {full!r} from the write echo; the "
                "field may have been ignored (check the value or field name)."
            )
        if isinstance(value, dict) and value:
            _verify_response(value, received[key], skip_root, full)


def _get_client() -> LiteLLMClient:
    """Return the client bound to this request, else the module singleton."""
    global _client
    if (bound := client_var.get()) is not None:
        return bound
    if _client is None:
        _client = LiteLLMClient()
    return _client


def _qp(**params: Any) -> dict[str, Any]:
    """Build a query-param dict, dropping `_UNSET` and `None` values.

    Explicit values (including `False`, `0`, `""`) are kept; httpx coerces
    them on the wire. Omitted (`_UNSET`) and null (`None`) params never reach
    the query string.
    """
    return {k: v for k, v in params.items() if v is not _UNSET and v is not None}


def _truncate(items: list[Any], limit: int) -> dict[str, Any]:
    """Cap a client-side list and report what was cut.

    For endpoints that don't paginate upstream: return the first `limit`
    items plus metadata so the caller cannot miss that data was truncated.
    `limit <= 0` returns everything. Shape per mcp-framework `truncate`.
    """
    total = len(items)
    returned = items[:limit] if limit > 0 else items
    return {
        "data": returned,
        "total": total,
        "returned": len(returned),
        "truncated": total > len(returned),
    }


def _slim(row: Any, fields: set[str]) -> Any:
    """Project one row down to `fields`, preserving upstream key order.

    A non-dict row (e.g. a bare key-hash string when `return_full_object` is
    false) passes through untouched.
    """
    if not isinstance(row, dict):
        return row
    return {k: v for k, v in row.items() if k in fields}


def _slim_list(
    result: Any,
    fields: set[str],
    limit: int,
    container: str | None = None,
) -> dict[str, Any]:
    """Slim each row to `fields`, cap the page at `limit`, report what was cut.

    `container` names the envelope key holding the rows (`keys`, `data`, ...);
    when None, `result` is the row list itself. A wrong container key raises
    (fail loud) rather than silently returning an empty page. Any other
    envelope fields (server-side pagination counts) survive under `page_info`,
    so the caller still sees that more rows exist upstream.
    """
    if container is not None:
        rows = result[container]
        page_info = {k: v for k, v in result.items() if k != container}
    else:
        rows, page_info = result, {}
    out = _truncate([_slim(row, fields) for row in rows], limit)
    if page_info:
        out["page_info"] = page_info
    return out
