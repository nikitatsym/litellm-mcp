"""Shared helpers for the LiteLLM tool modules.

Client singleton, query-param builder, and the truncation wrapper for
non-paginated lists. Slims and `_verify_response` land in later steps.
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
