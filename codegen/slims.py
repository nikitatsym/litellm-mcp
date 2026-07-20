"""Per-list-op slim data (authored in Step 5; EMPTY in Step 4).

Each entry is keyed by op name; an unknown key is a generation-time error.

    SLIMS[op_name] = {"fields": ["id", "name", ...], "limit": 20}
    SLIMS[op_name] = {"no_slim": "reason the full payload is returned"}

With no entry the op returns the upstream payload verbatim (Step 4 baseline).
"""

from __future__ import annotations

from typing import Any

SLIMS: dict[str, dict[str, Any]] = {}
