"""Shared helpers for the LiteLLM tool modules.

Client singleton, query-param builder, and the slim/truncation wrappers for
list results. `_verify_response` lands in Step 6.
"""

from __future__ import annotations

from typing import Any

from ..client import LiteLLMClient
from ..registry import _UNSET

_client: LiteLLMClient | None = None


def _get_client() -> LiteLLMClient:
    global _client
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
