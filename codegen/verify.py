"""Per-write-op verify data (authored in Step 6; EMPTY in Step 4).

`ROOT_SKIP` is the global root-level skip set (request-only/transformed
transport fields). Each `VERIFY` entry is keyed by op name; an unknown key is
a generation-time error.

    VERIFY[op_name] = {"skip": [...]}       # extra root-level skips for this op
    VERIFY[op_name] = {"subset": [...]}     # only verify this subset of sent keys
    VERIFY[op_name] = {"no_verify": "reason the body is not echoed as a row"}

With no entry the op emits no `_verify_response` call (Step 4 baseline).
"""

from __future__ import annotations

from typing import Any

ROOT_SKIP: frozenset[str] = frozenset()

VERIFY: dict[str, dict[str, Any]] = {}
